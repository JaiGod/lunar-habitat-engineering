"""Build the three Lunar Habitat Engineering Portal modules in Blender and export each as a GLB.

Run headless:  blender -b --factory-startup --python build_modules.py -- <output_folder>

Everything is in metres. Objects are named for what they are, and carry custom properties
(exported as glTF "extras") that the website reads:
    role      what the object is used for in the viewer (layer, crew, monitor, pipe, tank, ...)
    layer     shielding layer id (radiation module)
    areal     areal density of a shielding layer in g/cm2
    path      JSON list of points a pipe follows (fluid/food modules), for flow particles
Sizes follow lunar-habitat practice: a 4.5 m diameter rigid module (close to ISS-class modules),
a 20 cm water jacket (20 g/cm2, NASA's recommended minimum surround), 10 cm of polyethylene,
and a 1 m regolith berm (about 150 g/cm2 at 1.5 g/cm3).
"""
import bpy, bmesh, math, json, sys, os
from mathutils import Vector, Matrix

OUT = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else os.path.join(os.path.expanduser('~'), 'lunar_glb')
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------ helpers
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def mat(name, color, metal=0.0, rough=0.6, alpha=1.0, emit=None, emit_strength=0.0, transmission=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    b.inputs['Alpha'].default_value = alpha
    if 'Transmission Weight' in b.inputs: b.inputs['Transmission Weight'].default_value = transmission
    if emit:
        b.inputs['Emission Color'].default_value = (*emit, 1)
        b.inputs['Emission Strength'].default_value = emit_strength
    if alpha < 1:
        try: m.surface_render_method = 'BLENDED'
        except Exception: m.blend_method = 'BLEND'
    return m

def finish(o, name, material=None, **props):
    o.name = name; o.data.name = name
    if material:
        o.data.materials.clear(); o.data.materials.append(material)
    for k, v in props.items(): o[k] = v
    return o

def mesh_from_bm(name, bm):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o

def tube_x(name, r_in, r_out, length, z0, seg=96, cut_below=None, material=None, **props):
    """Hollow cylinder along X (a habitat shell or shielding layer), with end rings closed."""
    bm = bmesh.new()
    rings = []
    for r in (r_out, r_in):
        ring = []
        for xs in (-length/2, length/2):
            ring.append([bm.verts.new((xs, r*math.cos(a), z0 + r*math.sin(a))) for a in [2*math.pi*i/seg for i in range(seg)]])
        rings.append(ring)
    (oL, oR), (iL, iR) = rings
    for i in range(seg):
        j = (i+1) % seg
        bm.faces.new((oL[i], oL[j], oR[j], oR[i]))          # outer wall
        bm.faces.new((iL[j], iL[i], iR[i], iR[j]))          # inner wall
        bm.faces.new((oL[j], oL[i], iL[i], iL[j]))          # left end ring
        bm.faces.new((oR[i], oR[j], iR[j], iR[i]))          # right end ring
    if cut_below is not None:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, cut_below), plane_no=(0, 0, 1), clear_inner=True)
    bm.normal_update()
    o = mesh_from_bm(name, bm)
    return finish(o, name, material, **props)

def end_caps(name, r, length, z0, thick, material=None, **props):
    """Domed end bulkheads as two flat discs (simple, but correct thickness)."""
    bm = bmesh.new()
    for xs in (-length/2 - thick/2, length/2 + thick/2):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=r, radius2=r, depth=thick,
                              matrix=Matrix.Translation((xs, 0, z0)) @ Matrix.Rotation(math.pi/2, 4, 'Y'))
    o = mesh_from_bm(name, bm); return finish(o, name, material, **props)

def box(name, size, loc, material=None, **props):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts); bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    o = mesh_from_bm(name, bm); return finish(o, name, material, **props)

def cyl(name, r, h, loc, axis='Z', seg=48, material=None, **props):
    bm = bmesh.new()
    rot = {'Z': Matrix.Identity(4), 'X': Matrix.Rotation(math.pi/2, 4, 'Y'), 'Y': Matrix.Rotation(math.pi/2, 4, 'X')}[axis]
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=h, matrix=Matrix.Translation(loc) @ rot)
    o = mesh_from_bm(name, bm); return finish(o, name, material, **props)

def sphere(name, r, loc, material=None, **props):
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=r, matrix=Matrix.Translation(loc))
    o = mesh_from_bm(name, bm); return finish(o, name, material, **props)

def pipe(name, pts, r=0.04, material=None, **props):
    """Pipe as a beveled curve converted to mesh; the point list is stored for flow particles."""
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 4
    sp = cu.splines.new('POLY'); sp.points.add(len(pts)-1)
    for p, c in zip(sp.points, pts): p.co = (*c, 1)
    o = bpy.data.objects.new(name, cu); bpy.context.scene.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    me = bpy.data.meshes.new_from_object(o.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(o); bpy.data.curves.remove(cu)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    props['path'] = json.dumps([[round(v, 3) for v in c] for c in pts])
    return finish(o, name, material, **props)

def crew(name, loc, material, **props):
    """1.75 m crew member as capsule body + head (dose sampling point in the viewer)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.2, radius2=0.18, depth=1.45, matrix=Matrix.Translation((loc[0], loc[1], loc[2]+0.725)))
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.13, matrix=Matrix.Translation((loc[0], loc[1], loc[2]+1.62)))
    o = mesh_from_bm(name, bm); return finish(o, name, material, role='crew', **props)

def ground(size=60, material=None):
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=60, y_segments=60, size=size/2)
    import random; random.seed(7)
    for v in bm.verts:   # gentle regolith undulation, kept flat near the habitat
        d = (v.co.x**2 + v.co.y**2) ** 0.5
        v.co.z = -0.02 + (0 if d < 9 else (random.random()-0.5)*0.25*min(1,(d-9)/10))
    o = mesh_from_bm('Lunar_Ground', bm); return finish(o, 'Lunar_Ground', material, role='ground')

def export(fname):
    path = os.path.join(OUT, fname)
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_extras=True, export_apply=True, export_yup=True)
    print('EXPORTED', path, os.path.getsize(path))

# ------------------------------------------------------------------ materials
def materials():
    return dict(
        al=mat('Aluminium_2219', (0.78, 0.80, 0.83), metal=0.9, rough=0.35),
        hdpe=mat('Polyethylene_HDPE', (0.92, 0.92, 0.88), rough=0.55),
        water=mat('Water_Jacket', (0.12, 0.45, 0.75), rough=0.08, alpha=0.45, transmission=0.6),
        regolith=mat('Regolith_Berm', (0.32, 0.31, 0.30), rough=0.95),
        ground=mat('Lunar_Regolith', (0.36, 0.35, 0.34), rough=0.97),
        shelter=mat('Shelter_Water_Walls', (0.15, 0.50, 0.80), rough=0.2, alpha=0.6),
        floor=mat('Floor_Panel', (0.30, 0.33, 0.37), metal=0.3, rough=0.6),
        crew=mat('Crew_Suit', (0.90, 0.90, 0.92), rough=0.7),
        monitor=mat('Rad_Monitor', (0.12, 0.13, 0.15), metal=0.4, rough=0.5, emit=(0.2, 0.9, 1.0), emit_strength=2.0),
        steel=mat('Stainless_Pipe', (0.70, 0.72, 0.75), metal=0.85, rough=0.3),
        pipe=mat('Pipe_Transparent', (0.75, 0.88, 0.95), rough=0.05, alpha=0.25, transmission=0.8),
        pump=mat('Pump_Housing', (0.20, 0.36, 0.55), metal=0.6, rough=0.4),
        tank=mat('Tank_Composite', (0.85, 0.86, 0.88), metal=0.2, rough=0.45, alpha=0.35),
        valve=mat('Valve_Red', (0.80, 0.18, 0.15), metal=0.5, rough=0.4),
        plant=mat('Leaf_Green', (0.18, 0.55, 0.18), rough=0.7),
        raft=mat('Raft_Foam', (0.95, 0.95, 0.93), rough=0.8),
        led=mat('Grow_LED', (0.9, 0.3, 0.8), emit=(1.0, 0.35, 0.85), emit_strength=3.0),
        fish=mat('Tilapia', (0.55, 0.58, 0.60), metal=0.3, rough=0.4),
        frame=mat('Rack_Frame', (0.55, 0.57, 0.60), metal=0.8, rough=0.35),
        filt=mat('Biofilter_Media', (0.45, 0.32, 0.20), rough=0.8))

# ------------------------------------------------------------------ 1. radiation cross-section module
def build_radiation():
    reset(); M = materials()
    L, z0 = 10.0, 2.65                       # module length; axis height (sits on the berm footing)
    ground(material=M['ground'])
    tube_x('Hab_Pressure_Shell', 2.20, 2.25, L, z0, material=M['al'], role='layer', layer='shell', areal=1.35,
           note='Aluminium 2219 pressure shell, 5 mm structural (modelled 5 cm for visibility)')
    end_caps('Hab_End_Bulkheads', 2.25, L, z0, 0.05, material=M['al'], role='layer', layer='shell', areal=1.35)
    tube_x('Shield_Polyethylene', 2.25, 2.35, L, z0, material=M['hdpe'], role='layer', layer='poly', areal=9.5,
           note='10 cm high-density polyethylene liner (0.95 g/cm3)')
    tube_x('Shield_Water_Jacket', 2.35, 2.55, L, z0, material=M['water'], role='layer', layer='water', areal=20.0,
           note='20 cm water jacket = 20 g/cm2, the NASA-recommended minimum surround')
    tube_x('Shield_Regolith_Berm', 2.60, 3.60, L + 0.6, z0, cut_below=0.0, material=M['regolith'], role='layer', layer='regolith', areal=150.0,
           note='1 m bagged regolith berm at ~1.5 g/cm3 (~150 g/cm2), built by robots from local soil')
    box('Hab_Floor', (L - 0.4, 3.6, 0.08), (0, 0, z0 - 1.25), material=M['floor'], role='structure')
    # storm shelter: crew-quarters-sized core walled with water bags (NASA RadWorks concept)
    sx, sy, sh = 2.4, 2.2, 2.1; cx = -2.6; fz = z0 - 1.21
    bm = bmesh.new()
    for (sz, off) in (((sx, 0.15, sh), (0, sy/2, sh/2)), ((sx, 0.15, sh), (0, -sy/2, sh/2)),
                      ((0.15, sy, sh), (sx/2, 0, sh/2)), ((0.15, sy, sh), (-sx/2, 0, sh/2)), ((sx, sy, 0.15), (0, 0, sh))):
        g = bmesh.ops.create_cube(bm, size=1.0)['verts']
        bmesh.ops.scale(bm, vec=sz, verts=g); bmesh.ops.translate(bm, vec=(cx+off[0], off[1], fz+off[2]), verts=g)
    o = mesh_from_bm('Storm_Shelter_Water_Walls', bm)
    finish(o, 'Storm_Shelter_Water_Walls', M['shelter'], role='layer', layer='shelter', areal=15.0,
           note='15 cm water bags lining the shelter: extra 15 g/cm2 during a solar storm')
    crew('Crew_1_Shelter', (cx - 0.5, 0.4, fz), M['crew'], zone='shelter')
    crew('Crew_2_Shelter', (cx + 0.5, -0.4, fz), M['crew'], zone='shelter')
    crew('Crew_3_Work', (1.5, 0.6, fz), M['crew'], zone='work')
    crew('Crew_4_Work', (3.4, -0.5, fz), M['crew'], zone='work')
    for i, (x, y) in enumerate(((-2.6, 0.95), (1.8, 1.5), (3.8, -1.5)), 1):
        box(f'Rad_Monitor_{i}', (0.25, 0.08, 0.18), (x, y, z0 + 0.2), material=M['monitor'], role='monitor',
            note='Active dosimeter (like the ISS Radiation Assessment Detector), reads dose rate every minute')
    cyl('Comms_Mast', 0.06, 3.0, (4.2, 2.4, z0 + 3.5), material=M['al'], role='structure')
    export('radiation_module.glb')

# ------------------------------------------------------------------ 2. fluid dynamics module
def build_fluids():
    reset(); M = materials()
    ground(size=40, material=M['ground'])
    box('Utility_Floor', (12.0, 7.0, 0.1), (0, 0, 0.05), material=M['floor'], role='structure')
    # two 2 m3 storage tanks (r 0.6 m, h 1.8 m) - also used as radiation shielding in the habitat
    for i, x in enumerate((-4.8, -3.4), 1):
        cyl(f'Tank_Storage_{"AB"[i-1]}', 0.6, 1.8, (x, 2.2, 1.0), material=M['tank'], role='tank', volume_m3=2.0)
        cyl(f'Tank_Storage_{"AB"[i-1]}_Water', 0.57, 1.6, (x, 2.2, 0.92), material=M['water'], role='tank_level', tank=f'Tank_Storage_{"AB"[i-1]}')
    # pump stations: duty + standby (N+1), each motor + volute
    for i, x in enumerate((-2.2, -2.2), 1):
        y = 0.6 if i == 1 else -0.6
        cyl(f'Pump_{i}_Motor', 0.16, 0.45, (x, y, 0.45), axis='X', material=M['pump'], role='pump', duty='duty' if i == 1 else 'standby')
        cyl(f'Pump_{i}_Volute', 0.2, 0.18, (x + 0.33, y, 0.45), axis='X', material=M['steel'], role='pump')
    # hydroponic grow chamber (3 x 1.2 x 2 m) and aquaponic fish tank (1.5 m3)
    box('Grow_Chamber_Hydroponic', (3.0, 1.2, 2.0), (2.8, 2.2, 1.1), material=M['tank'], role='load', demand='hydroponics')
    for k in range(3):
        box(f'Grow_Chamber_Shelf_{k+1}', (2.9, 1.1, 0.04), (2.8, 2.2, 0.45 + k*0.6), material=M['frame'], role='structure')
        box(f'Grow_Chamber_LED_{k+1}', (2.6, 0.9, 0.03), (2.8, 2.2, 0.95 + k*0.6), material=M['led'], role='structure')
    cyl('Fish_Tank', 0.75, 0.9, (2.8, -2.2, 0.55), material=M['tank'], role='load', demand='aquaponics', volume_m3=1.5)
    cyl('Fish_Tank_Water', 0.72, 0.8, (2.8, -2.2, 0.5), material=M['water'], role='tank_level', tank='Fish_Tank')
    box('Crew_Galley_Tap', (0.6, 0.5, 0.9), (5.3, 0.0, 0.55), material=M['frame'], role='load', demand='crew')
    # pipe network (DN80, r 4 cm): supply header, branches, return
    P = M['pipe']
    pipe('Pipe_Tank_Header', [(-4.8, 2.2, 0.2), (-4.8, 1.2, 0.2), (-3.4, 1.2, 0.2), (-2.6, 0.6, 0.45)], material=P, role='pipe', segment='suction')
    pipe('Pipe_Supply_Main', [(-1.85, 0.6, 0.45), (-1.0, 0.6, 0.45), (-1.0, 0.0, 0.9), (1.0, 0.0, 0.9)], material=P, role='pipe', segment='supply')
    pipe('Pipe_Branch_Hydro', [(1.0, 0.0, 0.9), (1.0, 1.4, 0.9), (1.3, 2.2, 0.9)], material=P, role='pipe', segment='hydro')
    pipe('Pipe_Branch_Fish', [(1.0, 0.0, 0.9), (1.0, -1.4, 0.9), (2.05, -2.2, 0.9)], material=P, role='pipe', segment='fish')
    pipe('Pipe_Branch_Crew', [(1.0, 0.0, 0.9), (4.9, 0.0, 0.9)], material=P, role='pipe', segment='crew')
    pipe('Pipe_Return', [(4.3, 2.2, 0.15), (5.8, 2.2, 0.15), (5.8, -3.2, 0.15), (-5.6, -3.2, 0.15), (-5.6, 2.2, 0.15), (-5.4, 2.2, 0.6)], material=P, role='pipe', segment='return')
    for i, (x, y, z) in enumerate(((-1.0, 0.6, 0.45), (1.0, 1.0, 0.9), (1.0, -1.0, 0.9), (3.0, 0.0, 0.9)), 1):
        sphere(f'Valve_Isolation_{i}', 0.09, (x, y, z), material=M['valve'], role='valve')
    sphere('Leak_Point', 0.06, (2.0, 0.0, 0.9), material=M['valve'], role='leak', note='Where the leak button opens a crack in the supply main')
    for i, (x, y) in enumerate(((-1.4, 0.6), (1.0, 0.5), (1.0, -0.5)), 1):
        cyl(f'Flow_Meter_{i}', 0.07, 0.16, (x, y, 0.9 if i > 1 else 0.45), axis='X' if i == 1 else 'Y', material=M['monitor'], role='sensor')
    export('fluids_module.glb')

# ------------------------------------------------------------------ 3. food production module
def fish_mesh(name, M):
    bm = bmesh.new()   # 30 cm tilapia: stretched sphere body + tail fin
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.5, matrix=Matrix.Diagonal((0.15, 0.045, 0.07, 1)))
    t = [bm.verts.new(c) for c in ((-0.07, 0, 0), (-0.13, 0, 0.05), (-0.13, 0, -0.05))]; bm.faces.new(t)
    o = mesh_from_bm(name, bm); return finish(o, name, M['fish'], role='fish_template')

def build_food():
    reset(); M = materials()
    ground(size=40, material=M['ground'])
    box('Greenhouse_Floor', (14.0, 8.0, 0.1), (0, 0, 0.05), material=M['floor'], role='structure')
    # --- aquaponics side (y > 0): 2 fish tanks -> biofilter -> 3 raft beds -> sump -> back
    for i, x in enumerate((-5.5, -3.8), 1):
        cyl(f'Aqua_Fish_Tank_{i}', 0.75, 1.0, (x, 2.5, 0.6), material=M['tank'], role='fish_tank', volume_m3=1.7)
        cyl(f'Aqua_Fish_Tank_{i}_Water', 0.72, 0.9, (x, 2.5, 0.55), material=M['water'], role='water')
    cyl('Aqua_Biofilter', 0.45, 1.2, (-2.0, 2.5, 0.7), material=M['filt'], role='filter', note='Bacteria turn fish ammonia into nitrate')
    for k in range(3):
        x = -0.4 + k*2.1
        box(f'Aqua_Raft_Bed_{k+1}', (1.9, 1.2, 0.3), (x, 2.5, 0.35), material=M['water'], role='grow_bed', system='aquaponics')
        box(f'Aqua_Raft_{k+1}', (1.85, 1.15, 0.05), (x, 2.5, 0.52), material=M['raft'], role='structure')
        for a in range(4):
            for b in range(3):
                sphere(f'Aqua_Lettuce_{k+1}_{a}{b}', 0.13, (x - 0.7 + a*0.47, 2.1 + b*0.4, 0.62), material=M['plant'], role='plant', system='aquaponics')
    cyl('Aqua_Sump', 0.4, 0.6, (6.0, 2.5, 0.35), material=M['tank'], role='tank')
    P = M['pipe']
    pipe('Aqua_Pipe_Tank_to_Filter', [(-4.8, 2.5, 1.0), (-2.45, 2.5, 1.0)], material=P, role='pipe', loop='aquaponics')
    pipe('Aqua_Pipe_Filter_to_Beds', [(-1.55, 2.5, 0.9), (-1.4, 2.5, 0.45), (5.6, 2.5, 0.45)], material=P, role='pipe', loop='aquaponics')
    pipe('Aqua_Pipe_Return', [(6.0, 2.9, 0.3), (6.0, 3.6, 0.3), (-5.5, 3.6, 0.3), (-5.5, 3.25, 1.0)], material=P, role='pipe', loop='aquaponics')
    fish_mesh('Fish_Template', M)
    # --- hydroponics side (y < 0): nutrient tank -> 3-tier NFT racks -> back
    cyl('Hydro_Nutrient_Tank', 0.5, 1.0, (-5.0, -2.5, 0.55), material=M['tank'], role='tank', note='Nutrient salts dissolved in water, shipped from Earth')
    for k in range(3):
        x = -2.4 + k*2.6
        box(f'Hydro_NFT_Rack_{k+1}', (2.2, 0.9, 0.04), (x, -2.5, 0.1), material=M['frame'], role='structure')
        for t in range(3):
            zt = 0.5 + t*0.6
            box(f'Hydro_NFT_Channel_{k+1}_{t+1}', (2.2, 0.12, 0.06), (x, -2.5, zt), material=M['raft'], role='grow_bed', system='hydroponics')
            box(f'Hydro_LED_{k+1}_{t+1}', (2.1, 0.5, 0.02), (x, -2.5, zt + 0.42), material=M['led'], role='structure')
            for a in range(6):
                sphere(f'Hydro_Plant_{k+1}_{t+1}_{a}', 0.1, (x - 0.9 + a*0.36, -2.5, zt + 0.1), material=M['plant'], role='plant', system='hydroponics')
    pipe('Hydro_Pipe_Supply', [(-4.5, -2.5, 0.9), (-3.7, -2.5, 0.9), (-3.7, -2.5, 1.7), (3.3, -2.5, 1.7)], material=P, role='pipe', loop='hydroponics')
    pipe('Hydro_Pipe_Return', [(3.3, -2.9, 0.3), (-5.0, -3.4, 0.3), (-5.0, -3.0, 0.9)], material=P, role='pipe', loop='hydroponics')
    export('food_module.glb')

if __name__ == '__main__':
    which = os.environ.get('LHE_BUILD', 'radiation,fluids,food').split(',')
    if 'radiation' in which: build_radiation()
    if 'fluids' in which: build_fluids()
    if 'food' in which: build_food()
    print('DONE')
