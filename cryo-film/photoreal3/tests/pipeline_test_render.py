import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import *
reset()
import_lab('60')
info = lab_info('60')
b = bust()
m, nt, p, out = new_material('SkinTest')
col, nrm = skin_textures()
tex = node(nt, 'ShaderNodeTexImage', (-600, 200)); tex.image = col
link(nt, tex.outputs['Color'], p.inputs['Base Color'])
p.inputs['Subsurface Weight'].default_value = 0.3
geo = node(nt, 'ShaderNodeNewGeometry', (-800, -400))
dist = node(nt, 'ShaderNodeVectorMath', (-600, -400)); dist.operation = 'DISTANCE'
link(nt, geo.outputs['Position'], dist.inputs[0]); dist.inputs[1].default_value = conv(info['inj'])
aov_out(nt, 'injdist', dist.outputs['Value'])
b.data.materials.clear(); b.data.materials.append(m)
settings(samples=64)
enable_passes([('injdist', 'VALUE')])
world((0.01, 0.012, 0.015))
face = conv(info['face'])
camera(face + Vector((-0.24, -0.26, 0.36)), face, lens=65, fstop=2.8)
area('Key', face + Vector((0.3, -0.4, 0.8)), face, 60, (0.8, 0.9, 1.0), size=0.6)
render_exr('pipeline_test')
