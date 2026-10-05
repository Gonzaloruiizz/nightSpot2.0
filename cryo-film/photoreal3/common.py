"""Shared Blender (bpy) helpers for the photoreal v3 pipeline.

Approach: render a few very high quality stills per shot (Cycles, many samples, physically based
materials, low-key cinematic lighting) as multilayer EXR with extra passes (depth, emission and
custom AOV masks). All motion is then created in compositing (comp.py): 2.5D camera moves with
parallax, depth-of-field, mask-driven mutation growth, particles, film grade.

Run shot render scripts with the bpy python:
    $BPY photoreal3/shots/<shot>_render.py [--preview]
"""
import bpy, os, sys, math, json, random
from mathutils import Vector, Matrix, Euler, Quaternion

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(ROOT, '..'))
ASSETS = os.path.join(REPO, 'assets')
EXPORT = os.path.join(REPO, 'photoreal', 'export')      # glTF exports of the lab (see export_lab.mjs)
RENDERS = os.path.join(ROOT, 'renders')                  # EXR output
PREVIEW = '--preview' in sys.argv
os.makedirs(RENDERS, exist_ok=True)

# final still resolution (2.39:1). Previews are rendered at 1/3.
W, H = 1920, 804


def conv(v):
    """three.js (y-up) coordinates -> Blender (z-up)."""
    return Vector((v[0], -v[2], v[1]))


def lab_info(state='60'):
    return json.load(open(os.path.join(EXPORT, f'lab_{state}.json')))


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def settings(samples=256, w=W, h=H, threads=0, transparent=False, exposure=0.0, look='AgX - Base Contrast'):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    if PREVIEW:
        w, h, samples = w // 3, h // 3, max(16, samples // 8)
        if not threads:
            threads = 2          # several agents preview in parallel on a 4-core box
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.01
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.max_bounces = 12
    cy.diffuse_bounces = 4
    cy.glossy_bounces = 4
    cy.transmission_bounces = 12
    cy.volume_bounces = 2
    cy.transparent_max_bounces = 32
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.sample_clamp_indirect = 10.0
    cy.volume_step_rate = 1.0
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = transparent
    if threads:
        sc.render.threads_mode = 'FIXED'
        sc.render.threads = threads
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = look
    except Exception:
        pass
    sc.view_settings.exposure = exposure
    return sc


def enable_passes(aovs=()):
    """Depth + emission + diffuse color + custom AOVs (name, 'VALUE'|'COLOR')."""
    vl = bpy.context.view_layer
    vl.use_pass_z = True
    vl.use_pass_emit = True
    vl.use_pass_diffuse_color = True
    vl.use_pass_normal = True
    for name, kind in aovs:
        a = vl.aovs.add()
        a.name = name
        a.type = kind


def render_exr(name):
    """Render the current scene to renders/<name>.exr (multilayer, float, all passes)."""
    sc = bpy.context.scene
    st = sc.render.image_settings
    try:
        st.media_type = 'MULTI_LAYER_IMAGE'
    except Exception:
        pass
    st.file_format = 'OPEN_EXR_MULTILAYER'
    st.color_depth = '32'
    st.exr_codec = 'ZIP'
    suffix = '_preview' if PREVIEW else ''
    path = os.path.join(RENDERS, f'{name}{suffix}.exr')
    sc.render.filepath = path
    import time
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f'[render] {name}{suffix}: {time.time() - t0:.1f}s -> {path}', flush=True)
    # also save camera intrinsics/extrinsics for 2.5D compositing
    cam = sc.camera
    meta = {
        'lens': cam.data.lens, 'sensor': cam.data.sensor_width, 'w': sc.render.resolution_x, 'h': sc.render.resolution_y,
        'matrix_world': [list(r) for r in cam.matrix_world], 'clip': [cam.data.clip_start, cam.data.clip_end],
        'focus': cam.data.dof.focus_distance if not cam.data.dof.focus_object else (cam.data.dof.focus_object.matrix_world.translation - cam.matrix_world.translation).length,
        'fstop': cam.data.dof.aperture_fstop,
    }
    json.dump(meta, open(path.replace('.exr', '.json'), 'w'), indent=1)
    return path


# ------------------------------------------------------------------ node helpers
def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
    return n


def link(nt, a, b):
    nt.links.new(a, b)


def new_material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree, m.node_tree.nodes['Principled BSDF'], m.node_tree.nodes['Material Output']


def aov_out(nt, name, socket_or_value, loc=(600, -400)):
    """Write a float into a shader AOV (enable_passes must declare it)."""
    o = nt.nodes.new('ShaderNodeOutputAOV')
    o.aov_name = name
    o.location = loc
    if isinstance(socket_or_value, (int, float)):
        o.inputs['Value'].default_value = socket_or_value
    else:
        nt.links.new(socket_or_value, o.inputs['Value'])
    return o


def grunge(nt, scale=30.0, detail=8.0, loc=(-900, 0)):
    tc = node(nt, 'ShaderNodeTexCoord', (loc[0] - 200, loc[1]))
    nz = node(nt, 'ShaderNodeTexNoise', loc, Scale=scale, Detail=detail, Roughness=0.6)
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    return nz


def bevel_normal(nt, radius=0.004, loc=(-300, -300)):
    b = node(nt, 'ShaderNodeBevel', loc)
    b.inputs['Radius'].default_value = radius
    b.samples = 6
    return b


def metal(name, base, rough=0.3, rough_var=0.15, bevel=0.004, scratch=True):
    """Worn metal with bevelled edges (hides low-poly box edges) and roughness breakup."""
    m, nt, p, out = new_material(name)
    p.inputs['Base Color'].default_value = (*base, 1)
    p.inputs['Metallic'].default_value = 1.0
    g = grunge(nt, 22.0)
    mr = node(nt, 'ShaderNodeMapRange', (-650, 0))
    mr.inputs['To Min'].default_value = rough - rough_var
    mr.inputs['To Max'].default_value = rough + rough_var
    link(nt, g.outputs['Fac'], mr.inputs['Value'])
    if scratch:
        tc = node(nt, 'ShaderNodeTexCoord', (-1300, -300))
        sc = node(nt, 'ShaderNodeTexNoise', (-1100, -300), Scale=900.0, Detail=1.0)
        sc.inputs['Distortion'].default_value = 0.0
        mp = node(nt, 'ShaderNodeMapping', (-1200, -300))
        mp.inputs['Scale'].default_value = (1.0, 40.0, 1.0)
        link(nt, tc.outputs['Object'], mp.inputs['Vector']); link(nt, mp.outputs['Vector'], sc.inputs['Vector'])
        sr = node(nt, 'ShaderNodeMapRange', (-900, -300))
        sr.inputs['From Min'].default_value = 0.62; sr.inputs['From Max'].default_value = 0.7
        sr.inputs['To Min'].default_value = 0.0; sr.inputs['To Max'].default_value = -0.12
        link(nt, sc.outputs['Fac'], sr.inputs['Value'])
        ad = node(nt, 'ShaderNodeMath', (-450, 0)); ad.operation = 'ADD'
        link(nt, mr.outputs['Result'], ad.inputs[0]); link(nt, sr.outputs['Result'], ad.inputs[1])
        link(nt, ad.outputs[0], p.inputs['Roughness'])
    else:
        link(nt, mr.outputs['Result'], p.inputs['Roughness'])
    if bevel:
        b = bevel_normal(nt, bevel)
        link(nt, b.outputs['Normal'], p.inputs['Normal'])
    return m


def painted(name, base, rough=0.45, bevel=0.003, coat=0.0):
    m, nt, p, out = new_material(name)
    p.inputs['Base Color'].default_value = (*base, 1)
    p.inputs['Coat Weight'].default_value = coat
    g = grunge(nt, 35.0)
    mr = node(nt, 'ShaderNodeMapRange', (-650, 0))
    mr.inputs['To Min'].default_value = rough * 0.75
    mr.inputs['To Max'].default_value = min(1.0, rough * 1.3)
    link(nt, g.outputs['Fac'], mr.inputs['Value'])
    link(nt, mr.outputs['Result'], p.inputs['Roughness'])
    if bevel:
        b = bevel_normal(nt, bevel)
        link(nt, b.outputs['Normal'], p.inputs['Normal'])
    return m


def emission(name, color, strength):
    m, nt, p, out = new_material(name)
    nt.nodes.remove(p)
    e = node(nt, 'ShaderNodeEmission', Color=(*color, 1), Strength=strength)
    link(nt, e.outputs[0], out.inputs['Surface'])
    return m


def world(color=(0.0, 0.0, 0.0), strength=1.0, haze=0.0, haze_color=(0.7, 0.8, 0.9), aniso=0.5):
    w = bpy.data.worlds.new('World')
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes['Background']
    bg.inputs['Color'].default_value = (*color, 1)
    bg.inputs['Strength'].default_value = strength
    if haze > 0:
        v = node(nt, 'ShaderNodeVolumePrincipled', (0, -200), Density=haze, Anisotropy=aniso)
        v.inputs['Color'].default_value = (*haze_color, 1)
        link(nt, v.outputs[0], nt.nodes['World Output'].inputs['Volume'])
    return w


def camera(pos, target, lens=50.0, fstop=2.8, focus=None, sensor=36.0, clip=(0.005, 200.0)):
    cd = bpy.data.cameras.new('Cam')
    cd.lens = lens
    cd.sensor_width = sensor
    cd.sensor_fit = 'HORIZONTAL'
    cd.clip_start, cd.clip_end = clip
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    cd.dof.aperture_blades = 7
    cam = bpy.data.objects.new('Cam', cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.location = Vector(pos)
    d = Vector(target) - Vector(pos)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    cd.dof.focus_distance = focus if focus else d.length
    return cam


def no_dof():
    bpy.context.scene.camera.data.dof.use_dof = False


def area(name, loc, target, power, color, size=1.0, size_y=None, shape='RECTANGLE', spread=180):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = power
    ld.color = color
    ld.shape = shape
    ld.size = size
    if size_y:
        ld.size_y = size_y
    ld.spread = math.radians(spread)
    o = bpy.data.objects.new(name, ld)
    o.location = Vector(loc)
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.collection.objects.link(o)
    return o


def spot(name, loc, target, power, color, angle=40, blend=0.5, radius=0.05):
    ld = bpy.data.lights.new(name, 'SPOT')
    ld.energy = power
    ld.color = color
    ld.spot_size = math.radians(angle)
    ld.spot_blend = blend
    ld.shadow_soft_size = radius
    o = bpy.data.objects.new(name, ld)
    o.location = Vector(loc)
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.collection.objects.link(o)
    return o


def point(name, loc, power, color, radius=0.02):
    ld = bpy.data.lights.new(name, 'POINT')
    ld.energy = power
    ld.color = color
    ld.shadow_soft_size = radius
    o = bpy.data.objects.new(name, ld)
    o.location = Vector(loc)
    bpy.context.scene.collection.objects.link(o)
    return o


def import_lab(state='60', keep_people=False):
    """Import the lab exported from the three.js film (pod, sheet, bust, cables, robot, tanks...)."""
    bpy.ops.import_scene.gltf(filepath=os.path.join(EXPORT, f'lab_{state}.glb'))
    for o in list(bpy.data.objects):
        if o.type in ('LIGHT', 'CAMERA'):
            bpy.data.objects.remove(o)
    if not keep_people:
        arms = set()
        for o in bpy.data.objects:
            if o.type == 'MESH' and o.name.startswith(('Beta_Surface', 'Beta_Joints')) and o.material_slots and o.material_slots[0].material \
                    and o.material_slots[0].material.name.startswith('Suit') and o.parent:
                arms.add(o.parent.name)
        for an in arms:
            arm = bpy.data.objects[an]
            for c in list(arm.children_recursive) + [arm]:
                bpy.data.objects.remove(c, do_unlink=True)
    return {o.name: o for o in bpy.data.objects}


def find(prefix):
    return [o for o in bpy.data.objects if o.name.split('.')[0] == prefix]


def bust():
    b = find('Bust')
    return b[0] if b else None


def skin_textures():
    col = bpy.data.images.load(os.path.join(ASSETS, 'Map-COL.jpg'), check_existing=True)
    nrm = bpy.data.images.load(os.path.join(ASSETS, 'Infinite-Level_02_Tangent_SmoothUV.jpg'), check_existing=True)
    nrm.colorspace_settings.name = 'Non-Color'
    return col, nrm
