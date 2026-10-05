"""Photoreal version of "Proyecto Lázaro" rendered with Blender Cycles (path tracing).

usage: python scene.py <shot> [first_frame last_frame] [--preview]
Shots: establish, frozen, needle, blood, dna, mutation
Frames are written to photoreal/frames/<shot>/####.jpg
"""
import bpy, bmesh, json, math, os, sys, random
from mathutils import Vector, Matrix, Euler, Quaternion

ROOT = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(ROOT, 'export')
ASSETS = os.path.join(ROOT, '..', 'assets')
FPS = 24
SHOTS = {  # name: (seconds, lab export state)
    'establish': (4.5, '10'),
    'frozen': (4.0, '10'),
    'needle': (3.5, '25.5'),
    'blood': (4.5, None),
    'dna': (4.5, None),
    'mutation': (6.0, '60'),
}
ORIG = {'establish': 6.0, 'frozen': 5.0, 'needle': 4.5, 'mutation': 7.0}  # keyframes below are authored in these timings
SERUM = (0.1, 1.0, 0.72)


def conv(v):
    return Vector((v[0], -v[2], v[1]))


# ------------------------------------------------------------------ helpers
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def settings(w, h, samples, frames):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.04
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.max_bounces = 6
    cy.diffuse_bounces = 2
    cy.glossy_bounces = 2
    cy.transmission_bounces = 4
    cy.volume_bounces = 1
    cy.transparent_max_bounces = 16
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.sample_clamp_indirect = 4.0
    cy.volume_step_rate = 4.0
    cy.volume_max_steps = 128
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.frame_start = 1
    sc.frame_end = frames
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.35
    sc.render.use_persistent_data = True
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    sc.render.image_settings.file_format = 'JPEG'
    sc.render.image_settings.quality = 95


def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
    return n


def link(nt, a, b):
    nt.links.new(a, b)


def principled(name, base=(0.8, 0.8, 0.8), rough=0.5, metal=0.0, **kw):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*base, 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    for k, v in kw.items():
        key = {'sss': 'Subsurface Weight', 'sss_radius': 'Subsurface Radius', 'sss_scale': 'Subsurface Scale', 'trans': 'Transmission Weight', 'ior': 'IOR',
               'coat': 'Coat Weight', 'sheen': 'Sheen Weight', 'emit': 'Emission Color', 'emit_s': 'Emission Strength', 'alpha': 'Alpha', 'spec': 'Specular IOR Level'}[k]
        val = v if not isinstance(v, tuple) or len(v) != 3 or key in ('Subsurface Radius',) else (*v, 1)
        p.inputs[key].default_value = val
    return m


def emission(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    e = node(nt, 'ShaderNodeEmission', Color=(*color, 1), Strength=strength)
    link(nt, e.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    return m


def add_noise_roughness(m, lo, hi, scale=40.0):
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    nz = node(nt, 'ShaderNodeTexNoise', (-700, 0), Scale=scale, Detail=6.0)
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    mr = node(nt, 'ShaderNodeMapRange', (-450, 0))
    mr.inputs['To Min'].default_value = lo
    mr.inputs['To Max'].default_value = hi
    link(nt, nz.outputs['Fac'], mr.inputs['Value'])
    link(nt, mr.outputs['Result'], p.inputs['Roughness'])
    bump = node(nt, 'ShaderNodeBump', (-300, -250), Strength=0.08, Distance=0.002)
    link(nt, nz.outputs['Fac'], bump.inputs['Height'])
    link(nt, bump.outputs['Normal'], p.inputs['Normal'])
    return m


def world(color=(0.004, 0.006, 0.01), strength=1.0, haze=0.0, haze_color=(0.6, 0.75, 0.9), aniso=0.35):
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


def camera(lens=35, fstop=2.8, sensor=36):
    cd = bpy.data.cameras.new('Cam')
    cd.lens = lens
    cd.sensor_width = sensor
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    cd.clip_start = 0.005
    cd.clip_end = 300
    cam = bpy.data.objects.new('Cam', cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    tgt = bpy.data.objects.new('CamTarget', None)
    bpy.context.scene.collection.objects.link(tgt)
    c = cam.constraints.new('TRACK_TO')
    c.target = tgt
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    cd.dof.focus_object = tgt
    return cam, tgt


def keys(obj, path, frames_vals, interp='BEZIER'):
    for f, v in frames_vals:
        setattr_path(obj, path, v)
        obj.keyframe_insert(data_path=path, frame=f)
    ad = obj.animation_data
    if ad and ad.action:
        set_interp(ad.action, interp)


def setattr_path(obj, path, v):
    if path == 'location':
        obj.location = v
    elif path == 'lens':
        obj.lens = v
    else:
        exec(f'obj.{path} = v')


def set_interp(action, interp):
    try:
        curves = action.fcurves
    except AttributeError:
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    curves.extend(cb.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = interp


def value_node(nt, name, loc=(0, 0)):
    v = nt.nodes.new('ShaderNodeValue')
    v.name = name
    v.label = name
    v.location = loc
    return v


def key_value(mat_or_world, name, frames_vals):
    nt = mat_or_world.node_tree
    v = nt.nodes[name]
    for f, val in frames_vals:
        v.outputs[0].default_value = val
        v.outputs[0].keyframe_insert('default_value', frame=f)


def area(name, loc, size, power, color, rot=(0, 0, 0), shape='RECTANGLE', size_y=None):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = power
    ld.color = color
    ld.shape = shape
    ld.size = size
    if size_y:
        ld.size_y = size_y
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    o.rotation_euler = rot
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
    o.location = loc
    bpy.context.scene.collection.objects.link(o)
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return o


def point(name, loc, power, color, radius=0.02):
    ld = bpy.data.lights.new(name, 'POINT')
    ld.energy = power
    ld.color = color
    ld.shadow_soft_size = radius
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    bpy.context.scene.collection.objects.link(o)
    return o


# ================================================================== LAB
def lab_materials(info):
    M = {}
    M['Gunmetal'] = add_noise_roughness(principled('Gunmetal', (0.11, 0.13, 0.15), 0.32, 0.85), 0.22, 0.45, 60)
    M['GunmetalLight'] = add_noise_roughness(principled('GunmetalLight', (0.35, 0.38, 0.41), 0.25, 0.95), 0.15, 0.35, 80)
    M['LED'] = emission('LED', (0.25, 0.85, 1.0), 14)
    M['CeilingPanel'] = emission('CeilingPanel', (0.85, 0.93, 1.0), 9)
    M['StripLight'] = emission('StripLight', (0.2, 0.75, 1.0), 10)
    M['Pipe'] = add_noise_roughness(principled('Pipe', (0.3, 0.33, 0.36), 0.35, 0.9), 0.25, 0.6, 30)
    M['Beam'] = principled('Beam', (0.04, 0.045, 0.05), 0.5, 0.7)
    M['RobotWhite'] = add_noise_roughness(principled('RobotWhite', (0.72, 0.74, 0.76), 0.28, 0.0, coat=0.6), 0.22, 0.35, 120)
    M['RobotDark'] = principled('RobotDark', (0.02, 0.022, 0.025), 0.35, 0.6)
    M['Serum'] = principled('Serum', (0.02, 0.2, 0.15), 0.1, 0.0, emit=SERUM, emit_s=18.0)
    M['Suit'] = principled('Suit', (0.78, 0.8, 0.82), 0.78, 0.0, sheen=0.6)
    M['SuitJoints'] = principled('SuitJoints', (0.55, 0.58, 0.6), 0.6, 0.0, sheen=0.4)
    M['Gown'] = principled('Gown', (0.72, 0.76, 0.8), 0.82, 0.0, sheen=0.7)
    M['Visor'] = principled('Visor', (0.005, 0.006, 0.008), 0.05, 0.0, coat=1.0)
    M['TankFigure'] = principled('TankFigure', (0.12, 0.16, 0.18), 0.55, 0.0, sss=0.3, sss_radius=(0.2, 0.3, 0.4))
    M['Electrode'] = principled('Electrode', (0.75, 0.78, 0.8), 0.18, 1.0)
    M['Cable'] = principled('Cable', (0.015, 0.016, 0.018), 0.45, 0.0)
    M['Mattress'] = principled('Mattress', (0.45, 0.55, 0.62), 0.45, 0.0, sss=0.2, sss_radius=(0.3, 0.4, 0.5), coat=0.3)
    # glowing data cables: emissive pulses travelling along the tube u coordinate
    for nm, col in (('CableGlow', SERUM), ('CableGlowBlue', (0.2, 0.55, 1.0))):
        m = principled(nm, (0.02, 0.022, 0.025), 0.4, 0.0)
        nt = m.node_tree
        p = nt.nodes['Principled BSDF']
        tc = node(nt, 'ShaderNodeTexCoord', (-1100, 0))
        sep = node(nt, 'ShaderNodeSeparateXYZ', (-900, 0))
        link(nt, tc.outputs['UV'], sep.inputs[0])
        tv = value_node(nt, 'Time', (-900, -200))
        mul = node(nt, 'ShaderNodeMath', (-700, 0)); mul.operation = 'MULTIPLY'; mul.inputs[1].default_value = 6.0
        link(nt, sep.outputs['X'], mul.inputs[0])
        mt = node(nt, 'ShaderNodeMath', (-700, -200)); mt.operation = 'MULTIPLY'; mt.inputs[1].default_value = 0.35
        link(nt, tv.outputs[0], mt.inputs[0])
        sub = node(nt, 'ShaderNodeMath', (-500, 0)); sub.operation = 'SUBTRACT'
        link(nt, mul.outputs[0], sub.inputs[0]); link(nt, mt.outputs[0], sub.inputs[1])
        fr = node(nt, 'ShaderNodeMath', (-350, 0)); fr.operation = 'FRACT'
        link(nt, sub.outputs[0], fr.inputs[0])
        mr = node(nt, 'ShaderNodeMapRange', (-200, 0))
        mr.inputs['From Min'].default_value = 0.42; mr.inputs['From Max'].default_value = 0.5
        mr.inputs['To Min'].default_value = 0.0; mr.inputs['To Max'].default_value = 1.0
        link(nt, fr.outputs[0], mr.inputs['Value'])
        p.inputs['Emission Color'].default_value = (*col, 1)
        link(nt, mr.outputs['Result'], p.inputs['Emission Strength'])
        M[nm] = m
    # pod lid: thin glass (transparent + fresnel reflection) with frost growing from the rim
    g = bpy.data.materials.new('GlassLid')
    g.use_nodes = True
    nt = g.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    tc = node(nt, 'ShaderNodeTexCoord', (-1200, 0))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1000, 200))
    link(nt, tc.outputs['Object'], sep.inputs[0])
    nz = node(nt, 'ShaderNodeTexNoise', (-1000, -100), Scale=9.0, Detail=12.0, Roughness=0.65)
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    h = node(nt, 'ShaderNodeMapRange', (-800, 200))
    h.inputs['From Min'].default_value = 0.0; h.inputs['From Max'].default_value = 0.42
    h.inputs['To Min'].default_value = 1.0; h.inputs['To Max'].default_value = 0.0
    link(nt, sep.outputs['Z'], h.inputs['Value'])
    add_ = node(nt, 'ShaderNodeMath', (-600, 100)); add_.operation = 'ADD'
    link(nt, h.outputs['Result'], add_.inputs[0])
    nzs = node(nt, 'ShaderNodeMath', (-800, -100)); nzs.operation = 'MULTIPLY'; nzs.inputs[1].default_value = 0.9
    link(nt, nz.outputs['Fac'], nzs.inputs[0]); link(nt, nzs.outputs[0], add_.inputs[1])
    ramp = node(nt, 'ShaderNodeValToRGB', (-450, 100))
    ramp.color_ramp.elements[0].position = 0.68; ramp.color_ramp.elements[1].position = 0.98
    link(nt, add_.outputs[0], ramp.inputs['Fac'])
    fv = value_node(nt, 'Frost', (-450, -150))
    fm = node(nt, 'ShaderNodeMath', (-250, 0)); fm.operation = 'MULTIPLY'
    link(nt, ramp.outputs['Color'], fm.inputs[0]); link(nt, fv.outputs[0], fm.inputs[1])
    tr = node(nt, 'ShaderNodeBsdfTransparent', (0, 200))
    gl = node(nt, 'ShaderNodeBsdfGlossy', (0, 50), Roughness=0.04)
    fr = node(nt, 'ShaderNodeFresnel', (-200, 300), IOR=1.5)
    m1 = node(nt, 'ShaderNodeMixShader', (200, 150))
    link(nt, fr.outputs[0], m1.inputs['Fac']); link(nt, tr.outputs[0], m1.inputs[1]); link(nt, gl.outputs[0], m1.inputs[2])
    frost = node(nt, 'ShaderNodeBsdfPrincipled', (0, -300))
    frost.inputs['Base Color'].default_value = (0.8, 0.86, 0.92, 1)
    frost.inputs['Roughness'].default_value = 0.6
    mix = node(nt, 'ShaderNodeMixShader', (400, 0))
    mm = node(nt, 'ShaderNodeMath', (100, -150)); mm.operation = 'MULTIPLY'; mm.inputs[1].default_value = 0.85
    link(nt, fm.outputs[0], mm.inputs[0]); link(nt, mm.outputs[0], mix.inputs['Fac'])
    link(nt, m1.outputs[0], mix.inputs[1]); link(nt, frost.outputs[0], mix.inputs[2])
    link(nt, mix.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    fv.outputs[0].default_value = 1.0
    M['GlassLid'] = g
    tg = principled('TankGlass', (0.05, 0.3, 0.4), 0.1, 0.0, alpha=0.35, emit=(0.1, 0.65, 0.9), emit_s=0.8)
    M['TankGlass'] = tg
    return M


def skin_material(info, front_keys, frost_keys, vein_keys, scale_keys, eye_keys):
    """Physically based skin (SSS) + frost + glowing veins + scales + eye glow, all driven by keyed values."""
    m = bpy.data.materials.new('SkinPR')
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    out = nt.nodes['Material Output']
    col = bpy.data.images.load(os.path.join(ASSETS, 'Map-COL.jpg'))
    nrm = bpy.data.images.load(os.path.join(ASSETS, 'Infinite-Level_02_Tangent_SmoothUV.jpg'))
    nrm.colorspace_settings.name = 'Non-Color'
    tex = node(nt, 'ShaderNodeTexImage', (-1600, 400)); tex.image = col
    ntex = node(nt, 'ShaderNodeTexImage', (-1600, -600)); ntex.image = nrm
    nmap = node(nt, 'ShaderNodeNormalMap', (-1300, -600), Strength=0.9)
    link(nt, ntex.outputs['Color'], nmap.inputs['Color'])
    geo = node(nt, 'ShaderNodeNewGeometry', (-2200, 0))
    # ---- distance to the injection point (world) with an organic front
    inj = conv(info['inj'])
    dist = node(nt, 'ShaderNodeVectorMath', (-1900, 100)); dist.operation = 'DISTANCE'
    link(nt, geo.outputs['Position'], dist.inputs[0]); dist.inputs[1].default_value = inj
    fnz = node(nt, 'ShaderNodeTexNoise', (-1900, -100), Scale=18.0, Detail=3.0)
    link(nt, geo.outputs['Position'], fnz.inputs['Vector'])
    fnzs = node(nt, 'ShaderNodeMath', (-1700, -100)); fnzs.operation = 'MULTIPLY_ADD'; fnzs.inputs[1].default_value = 0.05; fnzs.inputs[2].default_value = -0.025
    link(nt, fnz.outputs['Fac'], fnzs.inputs[0])
    d = node(nt, 'ShaderNodeMath', (-1500, 50)); d.operation = 'ADD'
    link(nt, dist.outputs['Value'], d.inputs[0]); link(nt, fnzs.outputs[0], d.inputs[1])
    front = value_node(nt, 'Front', (-1500, -150))
    # inside = 1 when d < front
    ins = node(nt, 'ShaderNodeMapRange', (-1300, 100))
    link(nt, d.outputs[0], ins.inputs['Value'])
    fm = node(nt, 'ShaderNodeMath', (-1450, 250)); fm.operation = 'SUBTRACT'; fm.inputs[1].default_value = 0.03
    link(nt, front.outputs[0], fm.inputs[0])
    link(nt, fm.outputs[0], ins.inputs['From Min']); link(nt, front.outputs[0], ins.inputs['From Max'])
    ins.inputs['To Min'].default_value = 1.0; ins.inputs['To Max'].default_value = 0.0
    # rim (bright leading edge)
    rim_d = node(nt, 'ShaderNodeMath', (-1300, -100)); rim_d.operation = 'SUBTRACT'
    link(nt, d.outputs[0], rim_d.inputs[0]); link(nt, front.outputs[0], rim_d.inputs[1])
    rim_a = node(nt, 'ShaderNodeMath', (-1150, -100)); rim_a.operation = 'ABSOLUTE'
    link(nt, rim_d.outputs[0], rim_a.inputs[0])
    rim = node(nt, 'ShaderNodeMapRange', (-1000, -100))
    rim.inputs['From Min'].default_value = 0.0; rim.inputs['From Max'].default_value = 0.012
    rim.inputs['To Min'].default_value = 1.0; rim.inputs['To Max'].default_value = 0.0
    link(nt, rim_a.outputs[0], rim.inputs['Value'])
    # ---- veins: ridged noise lines
    vnz = node(nt, 'ShaderNodeTexNoise', (-1500, -350), Scale=85.0, Detail=2.0, Roughness=0.5, Distortion=0.5)
    link(nt, geo.outputs['Position'], vnz.inputs['Vector'])
    vs = node(nt, 'ShaderNodeMath', (-1300, -350)); vs.operation = 'SUBTRACT'; vs.inputs[1].default_value = 0.5
    link(nt, vnz.outputs['Fac'], vs.inputs[0])
    va = node(nt, 'ShaderNodeMath', (-1150, -350)); va.operation = 'ABSOLUTE'
    link(nt, vs.outputs[0], va.inputs[0])
    vl = node(nt, 'ShaderNodeMapRange', (-1000, -350))
    vl.inputs['From Min'].default_value = 0.0; vl.inputs['From Max'].default_value = 0.012
    vl.inputs['To Min'].default_value = 1.0; vl.inputs['To Max'].default_value = 0.0
    link(nt, va.outputs[0], vl.inputs['Value'])
    vin = node(nt, 'ShaderNodeMath', (-850, -250)); vin.operation = 'MULTIPLY_ADD'
    link(nt, rim.outputs['Result'], vin.inputs[0]); vin.inputs[1].default_value = 2.5
    link(nt, ins.outputs['Result'], vin.inputs[2])
    vein = node(nt, 'ShaderNodeMath', (-700, -300)); vein.operation = 'MULTIPLY'
    link(nt, vl.outputs['Result'], vein.inputs[0]); link(nt, vin.outputs[0], vein.inputs[1])
    vstr = value_node(nt, 'Vein', (-700, -450))
    emv = node(nt, 'ShaderNodeMath', (-550, -350)); emv.operation = 'MULTIPLY'
    link(nt, vein.outputs[0], emv.inputs[0]); link(nt, vstr.outputs[0], emv.inputs[1])
    # ---- eyes glow
    ems = [emv]
    for k in ('eyeL', 'eyeR'):
        e = node(nt, 'ShaderNodeVectorMath', (-1900, -800)); e.operation = 'DISTANCE'
        link(nt, geo.outputs['Position'], e.inputs[0]); e.inputs[1].default_value = conv(info[k])
        e2 = node(nt, 'ShaderNodeMapRange', (-1700, -800))
        e2.inputs['From Min'].default_value = 0.0; e2.inputs['From Max'].default_value = 0.022
        e2.inputs['To Min'].default_value = 1.0; e2.inputs['To Max'].default_value = 0.0
        e2.interpolation_type = 'SMOOTHSTEP'
        link(nt, e.outputs['Value'], e2.inputs['Value'])
        ems.append(e2)
    eyev = value_node(nt, 'Eye', (-1500, -950))
    esum = node(nt, 'ShaderNodeMath', (-1300, -850)); esum.operation = 'ADD'
    link(nt, ems[1].outputs['Result'], esum.inputs[0]); link(nt, ems[2].outputs['Result'], esum.inputs[1])
    emE = node(nt, 'ShaderNodeMath', (-1100, -850)); emE.operation = 'MULTIPLY'
    link(nt, esum.outputs[0], emE.inputs[0]); link(nt, eyev.outputs[0], emE.inputs[1])
    emT = node(nt, 'ShaderNodeMath', (-400, -500)); emT.operation = 'ADD'
    link(nt, emv.outputs[0], emT.inputs[0]); link(nt, emE.outputs[0], emT.inputs[1])
    p.inputs['Emission Color'].default_value = (*SERUM, 1)
    link(nt, emT.outputs[0], p.inputs['Emission Strength'])
    # ---- frost & frozen tint (only outside the front)
    frz = value_node(nt, 'Frost', (-1300, 600))
    out_front = node(nt, 'ShaderNodeMath', (-1100, 500)); out_front.operation = 'SUBTRACT'; out_front.inputs[0].default_value = 1.0
    link(nt, ins.outputs['Result'], out_front.inputs[1])
    frozen = node(nt, 'ShaderNodeMath', (-950, 550)); frozen.operation = 'MULTIPLY'
    link(nt, frz.outputs[0], frozen.inputs[0]); link(nt, out_front.outputs[0], frozen.inputs[1])
    hsv = node(nt, 'ShaderNodeHueSaturation', (-1300, 350), Saturation=0.25, Value=0.85)
    link(nt, tex.outputs['Color'], hsv.inputs['Color'])
    tint = node(nt, 'ShaderNodeMix', (-1100, 350)); tint.data_type = 'RGBA'; tint.blend_type = 'MULTIPLY'
    tint.inputs['Factor'].default_value = 1.0
    link(nt, hsv.outputs['Color'], tint.inputs['A']); tint.inputs['B'].default_value = (0.75, 0.88, 1.05, 1)
    rnz = node(nt, 'ShaderNodeTexNoise', (-1300, 800), Scale=260.0, Detail=4.0)
    link(nt, geo.outputs['Position'], rnz.inputs['Vector'])
    rr = node(nt, 'ShaderNodeMapRange', (-1100, 800))
    rr.inputs['From Min'].default_value = 0.52; rr.inputs['From Max'].default_value = 0.7
    link(nt, rnz.outputs['Fac'], rr.inputs['Value'])
    rime = node(nt, 'ShaderNodeMath', (-850, 750)); rime.operation = 'MULTIPLY'
    link(nt, rr.outputs['Result'], rime.inputs[0]); link(nt, frozen.outputs[0], rime.inputs[1])
    c1 = node(nt, 'ShaderNodeMix', (-800, 400)); c1.data_type = 'RGBA'
    link(nt, frozen.outputs[0], c1.inputs['Factor']); link(nt, tex.outputs['Color'], c1.inputs['A']); link(nt, tint.outputs['Result'], c1.inputs['B'])
    c2 = node(nt, 'ShaderNodeMix', (-600, 400)); c2.data_type = 'RGBA'
    rime_f = node(nt, 'ShaderNodeMath', (-700, 600)); rime_f.operation = 'MULTIPLY'; rime_f.inputs[1].default_value = 0.5
    link(nt, rime.outputs[0], rime_f.inputs[0]); link(nt, rime_f.outputs[0], c2.inputs['Factor'])
    link(nt, c1.outputs['Result'], c2.inputs['A']); c2.inputs['B'].default_value = (0.8, 0.86, 0.92, 1)
    # ---- scales behind the front
    vor = node(nt, 'ShaderNodeTexVoronoi', (-1300, 1100), Scale=140.0); vor.feature = 'DISTANCE_TO_EDGE'
    link(nt, geo.outputs['Position'], vor.inputs['Vector'])
    border = node(nt, 'ShaderNodeMapRange', (-1100, 1100))
    border.inputs['From Min'].default_value = 0.0; border.inputs['From Max'].default_value = 0.08
    border.inputs['To Min'].default_value = 1.0; border.inputs['To Max'].default_value = 0.0
    link(nt, vor.outputs['Distance'], border.inputs['Value'])
    sv = value_node(nt, 'Scale', (-1300, 1300))
    behind = node(nt, 'ShaderNodeMapRange', (-1100, 1300))
    fm2 = node(nt, 'ShaderNodeMath', (-1300, 1450)); fm2.operation = 'SUBTRACT'; fm2.inputs[1].default_value = 0.035
    link(nt, front.outputs[0], fm2.inputs[0])
    fm3 = node(nt, 'ShaderNodeMath', (-1300, 1550)); fm3.operation = 'SUBTRACT'; fm3.inputs[1].default_value = 0.075
    link(nt, front.outputs[0], fm3.inputs[0])
    link(nt, d.outputs[0], behind.inputs['Value']); link(nt, fm3.outputs[0], behind.inputs['From Min']); link(nt, fm2.outputs[0], behind.inputs['From Max'])
    behind.inputs['To Min'].default_value = 1.0; behind.inputs['To Max'].default_value = 0.0
    pnz = node(nt, 'ShaderNodeTexNoise', (-1300, 1700), Scale=12.0, Detail=2.0)
    link(nt, geo.outputs['Position'], pnz.inputs['Vector'])
    pr = node(nt, 'ShaderNodeMapRange', (-1100, 1700)); pr.inputs['From Min'].default_value = 0.45; pr.inputs['From Max'].default_value = 0.6
    link(nt, pnz.outputs['Fac'], pr.inputs['Value'])
    sm1 = node(nt, 'ShaderNodeMath', (-900, 1300)); sm1.operation = 'MULTIPLY'
    link(nt, behind.outputs['Result'], sm1.inputs[0]); link(nt, sv.outputs[0], sm1.inputs[1])
    smask = node(nt, 'ShaderNodeMath', (-750, 1300)); smask.operation = 'MULTIPLY'
    link(nt, sm1.outputs[0], smask.inputs[0]); link(nt, pr.outputs['Result'], smask.inputs[1])
    scol = node(nt, 'ShaderNodeMix', (-600, 1100)); scol.data_type = 'RGBA'
    link(nt, border.outputs['Result'], scol.inputs['Factor']); scol.inputs['A'].default_value = (0.06, 0.085, 0.09, 1); scol.inputs['B'].default_value = (0.005, 0.01, 0.012, 1)
    c3 = node(nt, 'ShaderNodeMix', (-400, 400)); c3.data_type = 'RGBA'
    link(nt, smask.outputs[0], c3.inputs['Factor']); link(nt, c2.outputs['Result'], c3.inputs['A']); link(nt, scol.outputs['Result'], c3.inputs['B'])
    link(nt, c3.outputs['Result'], p.inputs['Base Color'])
    # roughness: frost rough, scales glossy
    rgh = node(nt, 'ShaderNodeMapRange', (-400, 200)); rgh.inputs['To Min'].default_value = 0.42; rgh.inputs['To Max'].default_value = 0.7
    link(nt, rime.outputs[0], rgh.inputs['Value'])
    rgh2 = node(nt, 'ShaderNodeMix', (-250, 200)); rgh2.data_type = 'FLOAT'
    link(nt, smask.outputs[0], rgh2.inputs['Factor']); link(nt, rgh.outputs['Result'], rgh2.inputs['A']); rgh2.inputs['B'].default_value = 0.18
    link(nt, rgh2.outputs['Result'], p.inputs['Roughness'])
    p.inputs['Coat Weight'].default_value = 0.0
    link(nt, smask.outputs[0], p.inputs['Coat Weight'])
    # subsurface (less when frozen)
    ssw = node(nt, 'ShaderNodeMapRange', (-400, 0)); ssw.inputs['To Min'].default_value = 0.35; ssw.inputs['To Max'].default_value = 0.08
    link(nt, frozen.outputs[0], ssw.inputs['Value'])
    link(nt, ssw.outputs['Result'], p.inputs['Subsurface Weight'])
    p.inputs['Subsurface Radius'].default_value = (1.0, 0.35, 0.2)
    p.inputs['Subsurface Scale'].default_value = 0.006
    p.subsurface_method = 'BURLEY'
    # bump: veins raised + scale borders
    bh = node(nt, 'ShaderNodeMath', (-500, -700)); bh.operation = 'MULTIPLY_ADD'
    link(nt, vein.outputs[0], bh.inputs[0]); bh.inputs[1].default_value = 0.5
    bh2 = node(nt, 'ShaderNodeMath', (-650, -800)); bh2.operation = 'MULTIPLY'
    link(nt, border.outputs['Result'], bh2.inputs[0]); link(nt, smask.outputs[0], bh2.inputs[1])
    link(nt, bh2.outputs[0], bh.inputs[2])
    bump = node(nt, 'ShaderNodeBump', (-300, -700), Strength=0.35, Distance=0.0015)
    link(nt, bh.outputs[0], bump.inputs['Height']); link(nt, nmap.outputs['Normal'], bump.inputs['Normal'])
    link(nt, bump.outputs['Normal'], p.inputs['Normal'])
    for nm, ks in (('Front', front_keys), ('Frost', frost_keys), ('Vein', vein_keys), ('Scale', scale_keys), ('Eye', eye_keys)):
        key_value(m, nm, ks)
    return m


def ice_crystals(bust, info, count=700, seed=3):
    """Scatter tiny ice shards over the upward-facing skin."""
    rnd = random.Random(seed)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = bust.evaluated_get(dg)
    me = ev.to_mesh()
    mw = bust.matrix_world
    tris = []
    me.calc_loop_triangles()
    for t in me.loop_triangles:
        n = (mw.to_3x3() @ t.normal).normalized()
        if n.z > 0.15:
            c = mw @ t.center
            tris.append((c, n, t.area))
    bm = bmesh.new()
    proto = bmesh.new()
    bmesh.ops.create_cone(proto, cap_ends=True, segments=6, radius1=1.0, radius2=0.0, depth=1.0)
    proto_v = [v.co.copy() for v in proto.verts]
    proto_f = [[v.index for v in f.verts] for f in proto.faces]
    for k in range(count):
        c, n, a = tris[rnd.randrange(len(tris))]
        s = 0.0005 + rnd.random() ** 3 * 0.0016
        q = n.to_track_quat('Z', 'Y') @ Euler((rnd.uniform(-0.9, 0.9), rnd.uniform(-0.9, 0.9), rnd.uniform(0, 6.28))).to_quaternion()
        off = len(bm.verts)
        for v in proto_v:
            vv = Vector((v.x * s * 0.45, v.y * s * 0.45, (v.z + 0.5) * s * 2.2))
            bm.verts.new(c + q @ vv)
        bm.verts.ensure_lookup_table()
        for f in proto_f:
            try:
                bm.faces.new([bm.verts[off + i] for i in f])
            except ValueError:
                pass
    mesh = bpy.data.meshes.new('Ice')
    bm.to_mesh(mesh)
    ob = bpy.data.objects.new('Ice', mesh)
    bpy.context.scene.collection.objects.link(ob)
    ev.to_mesh_clear()
    return ob


def ice_material(info, front_keys):
    m = bpy.data.materials.new('Ice')
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (0.85, 0.92, 1.0, 1)
    p.inputs['Roughness'].default_value = 0.15
    p.inputs['Coat Weight'].default_value = 1.0
    geo = node(nt, 'ShaderNodeNewGeometry', (-900, 0))
    dist = node(nt, 'ShaderNodeVectorMath', (-700, 0)); dist.operation = 'DISTANCE'
    link(nt, geo.outputs['Position'], dist.inputs[0]); dist.inputs[1].default_value = conv(info['inj'])
    front = value_node(nt, 'Front', (-700, -200))
    cmp = node(nt, 'ShaderNodeMath', (-500, 0)); cmp.operation = 'GREATER_THAN'
    link(nt, dist.outputs['Value'], cmp.inputs[0]); link(nt, front.outputs[0], cmp.inputs[1])
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-200, -200))
    mix = node(nt, 'ShaderNodeMixShader', (100, 0))
    link(nt, cmp.outputs[0], mix.inputs['Fac']); link(nt, tr.outputs[0], mix.inputs[1]); link(nt, p.outputs[0], mix.inputs[2])
    link(nt, mix.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    key_value(m, 'Front', front_keys)
    return m


def build_lab(state, mut):
    bpy.ops.import_scene.gltf(filepath=os.path.join(EXP, f'lab_{state}.glb'))
    info = json.load(open(os.path.join(EXP, f'lab_{state}.json')))
    for o in list(bpy.data.objects):
        if o.type in ('LIGHT', 'CAMERA'):
            bpy.data.objects.remove(o)
    # remove the scientist standing at the foot end (too close to camera for a mannequin)
    dg = bpy.context.evaluated_depsgraph_get()
    kill = set()
    for o in list(bpy.data.objects):
        if o.type == 'MESH' and o.name.startswith('Beta_Surface') and o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name.startswith('Suit'):
            ev = o.evaluated_get(dg); me = ev.to_mesh()
            idx = range(0, len(me.vertices), 50); cx = sum((o.matrix_world @ me.vertices[i].co).x for i in idx) / len(idx)
            ev.to_mesh_clear()
            if cx < -1.5 and o.parent:
                kill.add(o.parent.name)
    for an in kill:
        arm = bpy.data.objects[an]
        for c in list(arm.children_recursive) + [arm]:
            bpy.data.objects.remove(c, do_unlink=True)
    M = lab_materials(info)
    skin = skin_material(info, *mut)
    bust = None
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        base = o.name.split('.')[0]
        if base == 'Bust':
            bust = o
            o.data.materials.clear(); o.data.materials.append(skin)
            for poly in o.data.polygons:
                poly.use_smooth = True
            continue
        if base in ('GlassLid', 'TankGlass'):
            o.data.materials.clear(); o.data.materials.append(M[base])
            o.visible_shadow = False
            continue
        for slot in o.material_slots:
            if slot.material:
                mn = slot.material.name.split('.')[0]
                if mn in M:
                    slot.material = M[mn]
                elif mn == 'SheetMat':
                    sm = slot.material
                    pb = sm.node_tree.nodes.get('Principled BSDF')
                    if pb:
                        pb.inputs['Roughness'].default_value = 0.9
                        pb.inputs['Sheen Weight'].default_value = 0.8
                        pb.inputs['Base Color'].default_value = (0.5, 0.56, 0.6, 1)
                elif mn == 'FloorMat':
                    pb = slot.material.node_tree.nodes.get('Principled BSDF')
                    if pb:
                        pb.inputs['Metallic'].default_value = 0.4
    return info, bust, M


def lab_lights(info, alarm=False, haze=0.018):
    world(color=(0.002, 0.003, 0.006), strength=1.0, haze=haze, haze_color=(0.65, 0.8, 0.95), aniso=0.45)
    spot('Key', (0.25, -0.2, 3.9), (0.25, 0, 1.0), 900, (0.82, 0.92, 1.0), angle=44, blend=0.7, radius=0.15)
    spot('RimA', (-2.6, 3.6, 2.6), (0.4, 0, 1.0), 700, (0.3, 0.8, 1.0), angle=40, blend=0.8, radius=0.3)
    spot('RimB', (3.2, 3.2, 2.4), (0.6, 0, 1.1), 500, (0.35, 0.85, 1.0), angle=36, blend=0.8, radius=0.3)
    area('Fill', (0.5, -2.5, 3.0), 2.0, 120, (0.7, 0.85, 1.0), rot=(math.radians(50), 0, 0))
    area('PodGlow', (0.1, 0.0, 1.55), 1.6, 18, (0.6, 0.85, 1.0), size_y=0.5)
    point('Warm', (1.45, -0.5, 1.0), 25, (1.0, 0.55, 0.25), radius=0.05)
    point('TankL', (-3, 4.4, 1.6), 300, (0.2, 0.85, 1.0), radius=0.4)
    point('TankR', (3, 4.4, 1.6), 300, (0.2, 0.85, 1.0), radius=0.4)
    if alarm:
        point('Alarm', (-3.0, 3.0, 3.2), 800, (1.0, 0.1, 0.05), radius=0.2)


def ground_fog(density=1.2):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.45))
    c = bpy.context.active_object
    c.name = 'GroundFog'
    c.scale = (13.6, 11.6, 0.9)
    m = bpy.data.materials.new('GroundFog')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    v = node(nt, 'ShaderNodeVolumePrincipled', (200, 0), Anisotropy=0.3)
    v.inputs['Color'].default_value = (0.75, 0.85, 0.95, 1)
    tc = node(nt, 'ShaderNodeTexCoord', (-800, 0))
    nz = node(nt, 'ShaderNodeTexNoise', (-600, 0), Scale=2.2, Detail=4.0, Roughness=0.6)
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-600, -250))
    link(nt, tc.outputs['Object'], sep.inputs[0])
    hz = node(nt, 'ShaderNodeMapRange', (-400, -250)); hz.inputs['From Min'].default_value = -0.5; hz.inputs['From Max'].default_value = 0.5
    hz.inputs['To Min'].default_value = 1.0; hz.inputs['To Max'].default_value = 0.0
    link(nt, sep.outputs['Z'], hz.inputs['Value'])
    nr = node(nt, 'ShaderNodeMapRange', (-400, 0)); nr.inputs['From Min'].default_value = 0.42; nr.inputs['From Max'].default_value = 0.75
    link(nt, nz.outputs['Fac'], nr.inputs['Value'])
    mul = node(nt, 'ShaderNodeMath', (-200, 0)); mul.operation = 'MULTIPLY'
    link(nt, nr.outputs['Result'], mul.inputs[0]); link(nt, hz.outputs['Result'], mul.inputs[1])
    mul2 = node(nt, 'ShaderNodeMath', (0, 0)); mul2.operation = 'MULTIPLY'; mul2.inputs[1].default_value = density
    link(nt, mul.outputs[0], mul2.inputs[0]); link(nt, mul2.outputs[0], v.inputs['Density'])
    link(nt, v.outputs[0], nt.nodes['Material Output'].inputs['Volume'])
    c.data.materials.append(m)
    return c


def find(name):
    for o in bpy.data.objects:
        if o.name.split('.')[0] == name:
            return o
    return None


def cam_path(cam, tgt, keyset, lens=None, fstop=None, interp='BEZIER'):
    for f, pos, look in keyset:
        cam.location = pos
        cam.keyframe_insert('location', frame=f)
        tgt.location = look
        tgt.keyframe_insert('location', frame=f)
    for o in (cam, tgt):
        set_interp(o.animation_data.action, interp)
    if lens:
        for f, v in lens:
            cam.data.lens = v
            cam.data.keyframe_insert('lens', frame=f)
    if fstop:
        cam.data.dof.aperture_fstop = fstop


def handheld(cam, frames, amp=0.004, seed=1):
    rnd = random.Random(seed)
    for axis in range(3):
        fc_mod = None
    # add a subtle noise modifier to each location curve
    ad = cam.animation_data
    if not ad or not ad.action:
        return
    try:
        curves = list(ad.action.fcurves)
    except AttributeError:
        curves = []
        for layer in ad.action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    curves.extend(cb.fcurves)
    for fc in curves:
        if fc.data_path == 'location':
            m = fc.modifiers.new('NOISE')
            m.scale = 40
            m.strength = amp
            m.phase = rnd.random() * 100
            m.depth = 1


# ================================================================== shots
def frames_of(shot):
    return int(round(SHOTS[shot][0] * FPS))


def shot_lab(shot):
    n = frames_of(shot)
    kt = SHOTS[shot][0] / ORIG[shot]
    F = lambda s: 1 + s * FPS * kt
    state = SHOTS[shot][1]
    if shot in ('establish', 'frozen'):
        mut = ([(1, -0.05)], [(1, 1.0)], [(1, 0.0)], [(1, 0.0)], [(1, 0.0)])
    elif shot == 'needle':
        mut = ([(1, -0.02), (F(1.6), -0.01), (F(4.5), 0.018)], [(1, 1.0)], [(1, 0.0), (F(1.6), 0.0), (F(3.0), 2.5), (F(4.5), 3.5)], [(1, 0.0)], [(1, 0.0)])
    else:  # mutation
        mut = ([(1, 0.03), (F(5.2), 0.2), (F(7), 0.26)], [(1, 1.0), (F(4), 0.6)], [(1, 2.5), (F(3), 3.5), (F(7), 4.0)], [(1, 0.0), (F(2.0), 0.0), (F(5.0), 1.0)], [(1, 0.0), (F(4.6), 0.0), (F(6.4), 12.0), (F(7), 30.0)])
    info, bust, M = build_lab(state, mut)
    lab_lights(info, alarm=(shot == 'mutation'), haze=0.018 if shot == 'establish' else 0.0)
    if shot == 'establish':
        ground_fog(1.0)
    bpy.context.scene.view_settings.exposure = {'establish': 0.6, 'frozen': -1.1, 'needle': -0.8, 'mutation': -1.0}[shot]
    face = conv(info['face'])
    inj = conv(info['inj'])
    injN = conv(info['injN']).normalized()
    if shot in ('frozen', 'needle', 'mutation'):
        ice = ice_crystals(bust, info)
        ice.data.materials.append(ice_material(info, mut[0]))
        ice.visible_shadow = False
    lid = find('GlassLid')
    if shot == 'establish':
        cam, tgt = camera(lens=32, fstop=2.0)
        cam_path(cam, tgt, [(1, (-4.4, -4.5, 0.55), (0.35, 0.0, 0.85)), (n, (-2.55, -2.85, 0.95), (0.45, 0.0, 1.0))])
        handheld(cam, n, 0.006, 1)
    elif shot == 'frozen':
        cam, tgt = camera(lens=85, fstop=2.2)
        p0 = face + Vector((-0.42, -0.62, 0.42)); p1 = face + Vector((-0.3, -0.5, 0.33))
        cam_path(cam, tgt, [(1, p0, face + Vector((0.0, -0.05, 0.0))), (n, p1, face)])
        # rack focus: glass first, then the face
        cam.data.dof.focus_object = None
        dg = (p0 - face).length
        for f, dd in ((1, dg * 0.47), (F(0.6), dg * 0.47), (F(1.9), (p1 - face).length), (n, (p1 - face).length)):
            cam.data.dof.focus_distance = dd
            cam.data.dof.keyframe_insert('focus_distance', frame=f)
        handheld(cam, n, 0.0015, 2)
    elif shot == 'needle':
        cam, tgt = camera(lens=85, fstop=3.5)
        up = Vector((0, 0, 1)); ax = Vector((1, 0, 0))
        cam_path(cam, tgt, [(1, inj + up * 0.24 + injN * 0.16 - ax * 0.12, inj + injN * 0.09), (n, inj + up * 0.19 + injN * 0.12 - ax * 0.07, inj + injN * 0.04)])
        handheld(cam, n, 0.0012, 3)
        # injector approaches (rigid move of the arm), serum drains
        rob = find('Robot')
        if rob:
            base = rob.location.copy()
            for f, k in ((1, 0.12), (F(1.5), 0.0), (n, 0.0)):
                rob.location = base + injN * k
                rob.keyframe_insert('location', frame=f)
        fl = find('SerumFluid')
        if fl:
            s0 = fl.scale.copy()
            for f, k in ((1, 1.0), (F(1.8), 1.0), (n, 0.2)):
                fl.scale = (s0.x, s0.y * k, s0.z)
                fl.keyframe_insert('scale', frame=f)
        point('InjGlow', inj + injN * 0.03, 0.0, SERUM)
    else:
        cam, tgt = camera(lens=65, fstop=2.5)
        eyes = (conv(info['eyeL']) + conv(info['eyeR'])) * 0.5
        cam_path(cam, tgt, [(1, face + Vector((-0.24, -0.26, 0.36)), face), (F(4.5), face + Vector((-0.12, -0.16, 0.3)), face.lerp(eyes, 0.6)), (n, face + Vector((-0.06, -0.08, 0.24)), eyes)])
        handheld(cam, n, 0.002, 4)
        point('EyeGlow', eyes + Vector((0, 0, 0.06)), 0.0, SERUM)
        e = find('EyeGlow')
        for f, v in ((1, 0.0), (F(4.6), 0.0), (F(7), 3.0)):
            e.data.energy = v
            e.data.keyframe_insert('energy', frame=f)
    # glowing cable pulses
    for mn in ('CableGlow', 'CableGlowBlue'):
        if mn in M:
            key_value(M[mn], 'Time', [(1, 0.0), (n, SHOTS[shot][0])])
            for fc in M[mn].node_tree.animation_data.action.fcurves if hasattr(M[mn].node_tree.animation_data.action, 'fcurves') else []:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
    return n


# ------------------------------------------------------------------ bloodstream
def biconcave_mesh():
    R = 0.004
    prof = []
    for k in range(25):
        x = k / 24
        h = R * math.sqrt(max(0.0, 1 - x * x)) * (0.0518 + 2.0026 * x * x - 1.122 * x ** 4) * 1.15
        prof.append((x * R, h))
    bm = bmesh.new()
    seg = 40
    rings = []
    pts = prof + [(r, -h) for r, h in reversed(prof[:-1])]
    for i, (r, h) in enumerate(pts):
        ring = []
        for s in range(seg):
            a = 2 * math.pi * s / seg
            ring.append(bm.verts.new((math.cos(a) * max(r, 1e-6), math.sin(a) * max(r, 1e-6), h)))
        rings.append(ring)
    for i in range(len(rings) - 1):
        for s in range(seg):
            a, b = rings[i][s], rings[i][(s + 1) % seg]
            c, d = rings[i + 1][(s + 1) % seg], rings[i + 1][s]
            try:
                bm.faces.new((a, b, c, d))
            except ValueError:
                pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    me = bpy.data.meshes.new('RBC')
    bm.to_mesh(me)
    for p in me.polygons:
        p.use_smooth = True
    return me


def shot_blood():
    n = frames_of('blood')
    world(color=(0.01, 0.0005, 0.0005), strength=1.0, haze=1.2, haze_color=(0.9, 0.2, 0.15), aniso=0.2)
    rnd = random.Random(11)
    # vessel: a long curved tube (units: metres at micro scale, radius 3 cm here, treated as 30 µm)
    pts = [Vector((math.sin(k * 0.55) * 0.05 + math.sin(k * 1.3) * 0.012, k * 0.09, math.cos(k * 0.41) * 0.035)) for k in range(12)]
    cu = bpy.data.curves.new('Vessel', 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('NURBS')
    sp.points.add(len(pts) - 1)
    for p, v in zip(sp.points, pts):
        p.co = (*v, 1)
    sp.use_endpoint_u = True
    sp.order_u = 4
    cu.bevel_depth = 0.032
    cu.bevel_resolution = 16
    cu.resolution_u = 48
    vo = bpy.data.objects.new('Vessel', cu)
    bpy.context.scene.collection.objects.link(vo)
    wall = bpy.data.materials.new('Wall')
    wall.use_nodes = True
    nt = wall.node_tree
    p = nt.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (0.42, 0.05, 0.05, 1)
    p.inputs['Subsurface Weight'].default_value = 1.0
    p.inputs['Subsurface Radius'].default_value = (1.0, 0.25, 0.15)
    p.inputs['Subsurface Scale'].default_value = 0.01
    p.inputs['Roughness'].default_value = 0.35
    p.inputs['Coat Weight'].default_value = 0.5
    geo = node(nt, 'ShaderNodeNewGeometry', (-900, 0))
    vor = node(nt, 'ShaderNodeTexVoronoi', (-700, 0), Scale=320.0); vor.feature = 'DISTANCE_TO_EDGE'
    link(nt, geo.outputs['Position'], vor.inputs['Vector'])
    nz = node(nt, 'ShaderNodeTexNoise', (-700, -250), Scale=90.0, Detail=6.0)
    link(nt, geo.outputs['Position'], nz.inputs['Vector'])
    h = node(nt, 'ShaderNodeMath', (-500, 0)); h.operation = 'MULTIPLY_ADD'; h.inputs[1].default_value = 0.6
    link(nt, vor.outputs['Distance'], h.inputs[0]); link(nt, nz.outputs['Fac'], h.inputs[2])
    bump = node(nt, 'ShaderNodeBump', (-300, -100), Strength=0.6, Distance=0.0008)
    link(nt, h.outputs[0], bump.inputs['Height']); link(nt, bump.outputs['Normal'], p.inputs['Normal'])
    ramp = node(nt, 'ShaderNodeValToRGB', (-400, 250))
    ramp.color_ramp.elements[0].color = (0.18, 0.01, 0.015, 1); ramp.color_ramp.elements[1].color = (0.55, 0.09, 0.07, 1)
    link(nt, nz.outputs['Fac'], ramp.inputs['Fac']); link(nt, ramp.outputs['Color'], p.inputs['Base Color'])
    cu.materials.append(wall)
    # sample the vessel centreline
    dg = bpy.context.evaluated_depsgraph_get()
    path = [vo.evaluated_get(dg).to_mesh()]
    samples = []
    me = path[0]
    # centreline from the NURBS evaluation: use the spline evaluated points via a temporary curve copy without bevel
    cu2 = cu.copy(); cu2.bevel_depth = 0
    tmp = bpy.data.objects.new('tmp', cu2); bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    m2 = tmp.evaluated_get(dg).to_mesh()
    samples = [v.co.copy() for v in m2.vertices]
    tmp.evaluated_get(dg).to_mesh_clear(); bpy.data.objects.remove(tmp)
    vo.evaluated_get(dg).to_mesh_clear()
    # cumulative length param
    L = [0.0]
    for i in range(1, len(samples)):
        L.append(L[-1] + (samples[i] - samples[i - 1]).length)
    total = L[-1]

    def at(s):
        s = max(0.0, min(total - 1e-6, s))
        lo, hi = 0, len(L) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if L[mid] <= s: lo = mid
            else: hi = mid
        u = (s - L[lo]) / max(1e-9, L[hi] - L[lo])
        pnt = samples[lo].lerp(samples[hi], u)
        tan = (samples[hi] - samples[lo]).normalized()
        return pnt, tan

    def frame(tan):
        up = Vector((0, 0, 1)) if abs(tan.z) < 0.9 else Vector((1, 0, 0))
        nrm = tan.cross(up).normalized()
        bi = tan.cross(nrm).normalized()
        return nrm, bi

    rbc_me = biconcave_mesh()
    rbc_mat = principled('RBC', (0.5, 0.02, 0.03), 0.32, 0.0, sss=1.0, sss_radius=(1.0, 0.2, 0.1), sss_scale=0.002, coat=0.4)
    rbc_me.materials.append(rbc_mat)
    cam_speed = 0.022  # m per second along the path
    s_cam0 = 0.12
    secs = SHOTS['blood'][0]
    R = 0.032
    objs = []
    for i in range(170):
        rr = math.sqrt(rnd.random()) * (R - 0.006)
        th = rnd.random() * 6.283
        v = 0.03 * (1 - (rr / R) ** 2) + 0.008
        s0 = s_cam0 - 0.02 + rnd.random() * (cam_speed * secs + 0.14)
        o = bpy.data.objects.new('RBC', rbc_me)
        bpy.context.scene.collection.objects.link(o)
        ax = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))).normalized()
        w = rnd.uniform(-1.5, 1.5)
        sc = rnd.uniform(0.85, 1.15)
        o.scale = (sc, sc, sc)
        for f in range(1, n + 1, 4):
            tsec = (f - 1) / FPS
            pnt, tan = at(s0 + v * tsec)
            nrm, bi = frame(tan)
            o.location = pnt + nrm * math.cos(th) * rr + bi * math.sin(th) * rr
            o.rotation_mode = 'QUATERNION'
            o.rotation_quaternion = Quaternion(ax, w * tsec + i)
            o.keyframe_insert('location', frame=f)
            o.keyframe_insert('rotation_quaternion', frame=f)
        objs.append(o)
    # nanocarriers: emissive cores with a glassy lipid shell
    core = principled('NanoCore', (0.02, 0.3, 0.2), 0.2, 0.0, emit=SERUM, emit_s=6.0)
    shell = principled('NanoShell', (0.7, 1.0, 0.95), 0.05, 0.0, trans=1.0, ior=1.33)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.00045)
    cme = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    cme.materials.append(core)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.0008)
    sme = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    sme.materials.append(shell)
    for p_ in cme.polygons: p_.use_smooth = True
    for p_ in sme.polygons: p_.use_smooth = True
    for i in range(70):
        off = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)))
        ds = rnd.uniform(0.02, 0.09)
        rr = rnd.uniform(0.0, 0.016)
        th = rnd.random() * 6.283
        swirl = rnd.uniform(0.4, 1.4)
        sc = rnd.uniform(0.6, 1.4)
        c = bpy.data.objects.new('Nano', cme); bpy.context.scene.collection.objects.link(c)
        s = bpy.data.objects.new('NanoShell', sme); bpy.context.scene.collection.objects.link(s)
        s.parent = c
        c.scale = (sc, sc, sc)
        for f in range(1, n + 1, 3):
            tsec = (f - 1) / FPS
            pnt, tan = at(s_cam0 + ds + cam_speed * 1.15 * tsec)
            nrm, bi = frame(tan)
            a = th + swirl * tsec
            c.location = pnt + nrm * math.cos(a) * rr + bi * math.sin(a) * rr + tan * math.sin(tsec * 2 + i) * 0.002
            c.keyframe_insert('location', frame=f)
    swarm_light = point('Swarm', (0, 0, 0), 0.05, SERUM, radius=0.01)
    cam, tgt = camera(lens=24, fstop=11)
    cam.data.clip_start = 0.0005
    cam.data.dof.focus_object = None
    cam.data.dof.focus_distance = 0.03
    lamp = point('CamLamp', (0, 0, 0), 0.06, (1.0, 0.85, 0.8), radius=0.003)
    lamp.parent = cam
    for f in range(1, n + 1, 2):
        tsec = (f - 1) / FPS
        pnt, tan = at(s_cam0 + cam_speed * tsec)
        nrm, bi = frame(tan)
        cam.location = pnt + nrm * 0.008 + bi * 0.005
        cam.keyframe_insert('location', frame=f)
        lk, _ = at(s_cam0 + cam_speed * tsec + 0.05)
        tgt.location = lk + nrm * 0.003
        tgt.keyframe_insert('location', frame=f)
        sw, _ = at(s_cam0 + cam_speed * 1.15 * tsec + 0.05)
        swarm_light.location = sw
        swarm_light.keyframe_insert('location', frame=f)
    return n


# ------------------------------------------------------------------ DNA
def shot_dna():
    n = frames_of('dna')
    world(color=(0.002, 0.002, 0.01), strength=1.0, haze=0.02, haze_color=(0.5, 0.55, 1.0), aniso=0.5)
    rnd = random.Random(5)
    NBP, RISE, RAD, TW, OFF = 110, 0.34, 1.0, math.pi / 5, math.pi * 0.78
    X0 = -NBP * RISE / 2
    F = lambda s: 1 + s * FPS
    secs = SHOTS['dna'][0]
    front0, front1 = -12.0, 6.0

    def strand(x, s, f):
        a = (x - X0) / RISE * TW + (OFF if s else 0)
        r = RAD + math.exp(-((x - f) / 2.0) ** 2) * 1.0
        return Vector((x, math.cos(a) * r, math.sin(a) * r))

    back = principled('Backbone', (0.08, 0.16, 0.6), 0.22, 0.0, sss=0.6, sss_radius=(0.3, 0.5, 1.0), sss_scale=0.3, coat=0.8)
    gold = principled('Edited', (0.55, 0.3, 0.04), 0.25, 0.3, emit=(1.0, 0.5, 0.08), emit_s=0.8, coat=0.6)
    basem = {b: principled('Base' + b, c, 0.3, 0.0, sss=0.5, sss_radius=(0.5, 0.5, 0.5), sss_scale=0.2, coat=0.5) for b, c in
             (('A', (0.05, 0.25, 0.9)), ('T', (0.9, 0.62, 0.05)), ('G', (0.1, 0.75, 0.2)), ('C', (0.75, 0.08, 0.45)))}
    glow = principled('EditGlow', (0.02, 0.3, 0.2), 0.2, 0.0, emit=SERUM, emit_s=2.0)
    # the editing front position is animated by moving an empty; geometry built per strand with hooks is complex,
    # so bases/phosphates are separate objects keyed per frame (only those near the camera matter).
    def front_at(tsec):
        u = max(0.0, min(1.0, (tsec - 0.4) / (secs - 0.8)))
        u = u * u * (3 - 2 * u)
        return front0 + (front1 - front0) * u
    # backbone tubes (static), regions behind the front get the edited material via a second copy revealed by a boolean-free trick:
    for s in (0, 1):
        pts = [strand(X0 + i * RISE / 6, s, -99) for i in range(NBP * 6 + 1)]
        cu = bpy.data.curves.new(f'BB{s}', 'CURVE'); cu.dimensions = '3D'
        sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1)
        for p, v in zip(sp.points, pts): p.co = (*v, 1)
        cu.bevel_depth = 0.12; cu.bevel_resolution = 6
        cu.materials.append(back)
        o = bpy.data.objects.new(f'BB{s}', cu); bpy.context.scene.collection.objects.link(o)
    seq = ['ATGC'[rnd.randrange(4)] for _ in range(NBP)]
    PAIR = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=0.085, depth=1.0)
    cyl = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=0.19)
    sph = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    for p_ in sph.polygons: p_.use_smooth = True
    sph.materials.append(back)
    step = 2
    for i in range(NBP):
        x = X0 + i * RISE
        if x < -15 or x > 12:
            continue
        objs = []
        for k in (0, 1):
            me = cyl.copy()
            b = seq[i] if k == 0 else PAIR[seq[i]]
            me.materials.append(basem[b])
            me.materials.append(gold if rnd.random() < 0.5 else glow)
            o = bpy.data.objects.new('Base', me); bpy.context.scene.collection.objects.link(o)
            ph = bpy.data.objects.new('Phos', sph); bpy.context.scene.collection.objects.link(ph)
            objs.append((o, ph, k))
        edited_frame = None
        for f in range(1, n + 1, step):
            tsec = (f - 1) / FPS
            fr = front_at(tsec)
            pA, pB = strand(x, 0, fr), strand(x, 1, fr)
            mid = (pA + pB) * 0.5
            gap = 0.04 + math.exp(-((x - fr) / 2.0) ** 2) * 0.9
            for o, ph, k in objs:
                P = pA if k == 0 else pB
                d = (mid - P)
                ln = d.length - gap / 2
                d.normalize()
                o.location = P + d * (ln / 2 + 0.1)
                o.rotation_mode = 'QUATERNION'
                o.rotation_quaternion = d.to_track_quat('Z', 'Y')
                o.scale = (1, 1, max(0.05, ln - 0.12))
                ph.location = P
                o.keyframe_insert('location', frame=f); o.keyframe_insert('rotation_quaternion', frame=f); o.keyframe_insert('scale', frame=f)
                ph.keyframe_insert('location', frame=f)
            if edited_frame is None and fr > x:
                edited_frame = f
        # swap material slot at the moment the front passes (polygon material index keyed via object pass: use two meshes)
        if edited_frame:
            for o, ph, k in objs:
                for p_ in o.data.polygons:
                    p_.material_index = 0
                o2 = bpy.data.objects.new('BaseEd', o.data.copy()); bpy.context.scene.collection.objects.link(o2)
                for p_ in o2.data.polygons:
                    p_.material_index = 1
                o2.parent = o; o2.matrix_parent_inverse = o.matrix_world.inverted() @ o.matrix_world
                o2.scale = (1.02, 1.02, 1.0)
                for f, hide in ((1, True), (edited_frame, False)):
                    o2.hide_render = hide; o2.keyframe_insert('hide_render', frame=f)
                    o.hide_render = not hide; o.keyframe_insert('hide_render', frame=f)
    # editing complex: ring of glowing particles + clamp
    bpy.ops.mesh.primitive_torus_add(major_radius=2.2, minor_radius=0.1, major_segments=64, minor_segments=12)
    ring = bpy.context.active_object; ring.rotation_euler = (0, math.radians(90), 0)
    ring.data.materials.append(principled('Clamp', (0.05, 0.5, 0.4), 0.15, 0.2, emit=SERUM, emit_s=5.0, coat=1.0))
    bpy.ops.mesh.primitive_torus_add(major_radius=2.0, minor_radius=0.45, major_segments=64, minor_segments=24)
    shell = bpy.context.active_object; shell.rotation_euler = (0, math.radians(90), 0)
    shell.data.materials.append(principled('ClampShell', (0.6, 1.0, 0.95), 0.08, 0.0, trans=1.0, ior=1.2))
    fl = point('FrontLight', (0, 0, 0), 80, SERUM, radius=0.3)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.05)
    pme = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    pme.materials.append(principled('Part', (0.05, 0.5, 0.4), 0.2, 0.0, emit=SERUM, emit_s=25.0))
    parts = []
    for i in range(70):
        o = bpy.data.objects.new('Part', pme); bpy.context.scene.collection.objects.link(o)
        parts.append((o, rnd.random() * 6.28, rnd.uniform(1.4, 2.9), rnd.uniform(-0.8, 0.8), rnd.uniform(0.8, 2.5)))
    for f in range(1, n + 1, 2):
        tsec = (f - 1) / FPS
        fr = front_at(tsec)
        for o in (ring, shell):
            o.location = (fr + 0.2, 0, 0); o.keyframe_insert('location', frame=f)
        fl.location = (fr, 0.8, 1.8); fl.keyframe_insert('location', frame=f)
        for o, a0, r, dx, w in parts:
            a = a0 + w * tsec
            o.location = (fr + dx, math.cos(a) * r, math.sin(a) * r)
            o.keyframe_insert('location', frame=f)
    # background chromatin + floating bokeh
    bg = principled('Chromatin', (0.15, 0.1, 0.5), 0.4, 0.0, emit=(0.25, 0.15, 0.9), emit_s=0.6)
    for k in range(5):
        pts = []
        yy, zz = (k - 2) * 6.5, -12 - (k % 3) * 7
        for i in range(160):
            x = -30 + i * 0.4
            a = x * 1.4
            pts.append(Vector((x, zz + math.sin(a) * 1.0, yy + math.cos(a) * 1.0 + x * 0.1 * (1 if k % 2 else -1))))
        cu = bpy.data.curves.new('Chrom', 'CURVE'); cu.dimensions = '3D'
        sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1)
        for p, v in zip(sp.points, pts): p.co = (*v, 1)
        cu.bevel_depth = 0.14; cu.materials.append(bg)
        o = bpy.data.objects.new('Chrom', cu); bpy.context.scene.collection.objects.link(o)
    dmat = principled('Dust', (0.3, 0.3, 0.8), 0.5, 0.0, emit=(0.5, 0.6, 1.0), emit_s=4.0)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.04)
    dme = bpy.context.active_object.data; bpy.data.objects.remove(bpy.context.active_object)
    dme.materials.append(dmat)
    for i in range(160):
        o = bpy.data.objects.new('Dust', dme); bpy.context.scene.collection.objects.link(o)
        o.location = (rnd.uniform(-25, 20), rnd.uniform(-15, 25), rnd.uniform(-12, 12))
    area('KeyD', (2, -6, 8), 6, 900, (0.75, 0.85, 1.0), rot=(math.radians(40), 0, 0))
    area('RimD', (-4, 8, -3), 6, 1400, (0.6, 0.35, 1.0), rot=(math.radians(-120), 0, 0))
    cam, tgt = camera(lens=40, fstop=2.0)
    for f in range(1, n + 1, 2):
        tsec = (f - 1) / FPS
        fr = front_at(tsec)
        u = tsec / secs
        a = 0.9 - 1.1 * u
        dist = 7.0 - 1.0 * u + 9 * max(0.0, (u - 0.7) / 0.3) ** 2
        cam.location = (fr - 2.0 - 2 * max(0.0, u - 0.7), -math.cos(a) * dist, math.sin(a) * dist * 0.55 + 0.8)
        tgt.location = (fr + 0.6, 0, 0)
        cam.keyframe_insert('location', frame=f); tgt.keyframe_insert('location', frame=f)
    return n


# ================================================================== main
def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    shot = argv[0]
    preview = '--preview' in argv
    nums = [a for a in argv[1:] if not a.startswith('--')]
    reset()
    if shot in ('establish', 'frozen', 'needle', 'mutation'):
        n = shot_lab(shot)
    elif shot == 'blood':
        n = shot_blood()
    else:
        n = shot_dna()
    w, h, samples = (960, 402, 14)
    if preview:
        w, h, samples = (480, 201, 8)
    settings(w, h, samples, n)
    if shot == 'blood':
        bpy.context.scene.view_settings.exposure = -0.7
    out = os.path.join(ROOT, 'frames' if not preview else 'preview', shot)
    os.makedirs(out, exist_ok=True)
    first = int(nums[0]) if nums else 1
    last = int(nums[1]) if len(nums) > 1 else n
    step = int(nums[2]) if len(nums) > 2 else 1
    sc = bpy.context.scene
    import time
    for f in range(first, min(last, n) + 1, step):
        path = os.path.join(out, f'{f:04d}.jpg')
        if os.path.exists(path) and not preview:
            continue
        t0 = time.time()
        sc.frame_set(f)
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print(f'[{shot}] frame {f}/{n} {time.time() - t0:.1f}s', flush=True)


if __name__ == '__main__':
    main()
