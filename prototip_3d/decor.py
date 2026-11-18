"""Decor (Agent 4): pastel playroom, lights, cameras, render settings. Pure bpy, nothing runs on import."""
import math

import bmesh
import bpy
from mathutils import Vector

ENGINE = 'BLENDER_EEVEE_NEXT' if bpy.app.version < (5, 0, 0) else 'BLENDER_EEVEE'

_COLL = None  # collection being filled by build_room()

# Room layout (metres). Back wall front face at y=BACK_Y, left wall front face at x=LEFT_X.
BACK_Y = 2.2
LEFT_X = -3.9


def _lin(hexstr):
    """sRGB hex -> linear RGBA."""
    c = [int(hexstr[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def _mat(name, hexcol, rough=0.7, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = _lin(hexcol)
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = _lin(hexcol)
        b.inputs["Emission Strength"].default_value = emit
    return m


def _wood_mat():
    """Light wood planks: brick texture in object space + faint grain noise."""
    m = _mat("Decor_Podea_Lemn", "E6C9A0", 0.55)
    nt = m.node_tree
    n = nt.nodes
    tc = n.new("ShaderNodeTexCoord")
    brick = n.new("ShaderNodeTexBrick")
    brick.offset, brick.offset_frequency = 0.5, 1
    brick.inputs["Color1"].default_value = _lin("E9CDA4")
    brick.inputs["Color2"].default_value = _lin("DDBC90")
    brick.inputs["Mortar"].default_value = _lin("C4A177")
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.006
    brick.inputs["Brick Width"].default_value = 1.4
    brick.inputs["Row Height"].default_value = 0.18
    mp = n.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0, 14.0, 1.0)  # grain stretched along planks (x)
    noise = n.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    mix = n.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = 'RGBA', 'MULTIPLY'
    mix.inputs["Factor"].default_value = 0.12
    nt.links.new(tc.outputs["Object"], brick.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], noise.inputs["Vector"])
    nt.links.new(brick.outputs["Color"], mix.inputs[6])
    nt.links.new(noise.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], n["Principled BSDF"].inputs["Base Color"])
    return m


def _mesh(kind, dims, seg=32):
    bm = bmesh.new()
    if kind == 'cube':
        bmesh.ops.create_cube(bm, size=1.0)
    elif kind == 'sphere':
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.5)
    else:  # 'cyl', axis Z
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=0.5, radius2=0.5, depth=1.0)
    bmesh.ops.scale(bm, vec=dims, verts=bm.verts)
    me = bpy.data.meshes.new(kind)
    bm.to_mesh(me)
    bm.free()
    return me


def _link(ob):
    _COLL.objects.link(ob)
    return ob


def _part(name, kind, dims, mat, loc, rot=(0, 0, 0), bevel=0.0, seg=32):
    """Mesh primitive sized by `dims` (full extents), smooth shaded, optional rounded bevel."""
    me = _mesh(kind, dims, seg)
    me.shade_smooth()
    me.materials.append(mat)
    ob = _link(bpy.data.objects.new(name, me))
    ob.location = loc
    ob.rotation_euler = rot
    if bevel:
        b = ob.modifiers.new("Bevel", 'BEVEL')
        b.width, b.segments, b.limit_method, b.harden_normals = bevel, 3, 'ANGLE', True
    return ob


def _aim(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat('-Z', 'Y').to_euler()


def _light(name, loc, target, energy, hexcol, size, spread=180):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy, ld.color = energy, _lin(hexcol)[:3]
    ld.shape, ld.size = 'DISK', size
    ld.spread = math.radians(spread)
    ob = _link(bpy.data.objects.new(name, ld))
    ob.location = loc
    _aim(ob, target)
    return ob


def _camera(name, loc, target, lens):
    old = bpy.data.objects.get(name)  # factory startup already has a "Camera"
    if old:
        bpy.data.objects.remove(old)
    cd = bpy.data.cameras.new(name)
    cd.lens, cd.sensor_width, cd.clip_end = lens, 36.0, 50.0
    ob = _link(bpy.data.objects.new(name, cd))
    ob.location = loc
    _aim(ob, target)
    return ob


def _star(name, mat, loc, r_out=0.22, r_in=0.1):
    pts = [((r_out if i % 2 == 0 else r_in) * math.sin(i * math.pi / 5), 0.0,
            (r_out if i % 2 == 0 else r_in) * math.cos(i * math.pi / 5)) for i in range(10)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [], [list(range(10))[::-1]])
    me.materials.append(mat)
    ob = _link(bpy.data.objects.new(name, me))
    ob.location = loc
    s = ob.modifiers.new("Grosime", 'SOLIDIFY')
    s.thickness, s.offset = 0.05, 1.0
    b = ob.modifiers.new("Bevel", 'BEVEL')
    b.width, b.segments, b.harden_normals = 0.015, 3, True
    me.shade_smooth()
    return ob


def _bunting(M, x0, x1, z, sag, y):
    cols = [M["roz"], M["menta"], M["galben"], M["bleu"], M["lila"]]
    cu = bpy.data.curves.new("Ghirlanda_Sfoara", 'CURVE')
    cu.dimensions, cu.bevel_depth = '3D', 0.006
    sp = cu.splines.new('POLY')
    n = 13
    sp.points.add(n - 1)
    for i in range(n):
        t = i / (n - 1)
        sp.points[i].co = (x0 + (x1 - x0) * t, y, z - sag * 4 * t * (1 - t), 1.0)
    ob = _link(bpy.data.objects.new("Ghirlanda_Sfoara", cu))
    cu.materials.append(M["alb"])
    for i in range(1, n - 1):
        x, _, zz, _ = sp.points[i].co
        f = _link(bpy.data.objects.new(f"Ghirlanda_Steag_{i:02d}", _flag_mesh()))
        f.data.materials.append(cols[i % len(cols)])
        f.location = (x, y - 0.005, zz)
        f.rotation_euler = (0, 0, 0)
    return ob


def _flag_mesh():
    me = bpy.data.meshes.new("steag")
    me.from_pydata([(-0.13, 0, 0), (0.13, 0, 0), (0, 0, -0.26)], [], [(0, 2, 1)])
    return me


def build_room():
    """Builds the playroom in collection "Decor". Returns {"camera", "camera_aproape", "lights", "root"}."""
    global _COLL
    scene = bpy.context.scene
    _COLL = bpy.data.collections.new("Decor")
    scene.collection.children.link(_COLL)

    M = {k: _mat(f"Decor_{k}", h, r) for k, (h, r) in {
        "perete": ("BDEBD6", 0.9),     # mint wall
        "lambriu": ("FBEFE4", 0.85),   # cream wainscot
        "perete2": ("F9D9DA", 0.9),    # soft pink side wall
        "alb": ("FFFBF5", 0.5),
        "roz": ("F7B5C6", 0.6),
        "menta": ("A8E3C8", 0.6),
        "galben": ("FCE5A0", 0.6),
        "bleu": ("AFD5F2", 0.6),
        "lila": ("D8C4F0", 0.6),
        "covor": ("FFF4EA", 1.0),
        "covor_margine": ("F6BFCB", 1.0),
        "ursulet": ("E2B486", 0.85),
        "ursulet2": ("F6E2C8", 0.85),
        "negru": ("3A2E2E", 0.3),
        "coral": ("F9A99B", 0.45),
    }.items()}
    M["cer"] = _mat("Decor_Fereastra_Cer", "D6ECFF", 1.0, emit=2.5)

    # --- shell: floor, walls, wainscot, skirting
    _part("Podea", 'cube', (11.0, 8.0, 0.1), _wood_mat(), (-0.5, -1.0, -0.05))
    _part("Perete_Spate", 'cube', (11.0, 0.2, 3.4), M["perete"], (-0.5, BACK_Y + 0.1, 1.7))
    _part("Perete_Stanga", 'cube', (0.2, 6.0, 3.4), M["perete2"], (LEFT_X - 0.1, -0.8, 1.7))
    _part("Lambriu_Spate", 'cube', (11.0, 0.03, 0.85), M["lambriu"], (-0.5, BACK_Y - 0.015, 0.425))
    _part("Brau_Spate", 'cube', (11.0, 0.05, 0.05), M["alb"], (-0.5, BACK_Y - 0.03, 0.86), bevel=0.012)
    _part("Plinta_Spate", 'cube', (11.0, 0.05, 0.1), M["alb"], (-0.5, BACK_Y - 0.04, 0.05), bevel=0.01)
    _part("Plinta_Stanga", 'cube', (0.05, 6.0, 0.1), M["alb"], (LEFT_X + 0.025, -0.8, 0.05), bevel=0.01)

    # --- window (back wall, right of the action) with curtains
    wx, wz, ww, wh, fy = 2.25, 1.6, 1.1, 1.15, BACK_Y - 0.02
    _part("Fereastra_Cer", 'cube', (ww, 0.01, wh), M["cer"], (wx, BACK_Y - 0.005, wz))
    for nm, d, l in [("Sus", (ww + 0.1, 0.06, 0.07), (wx, fy, wz + wh / 2)),
                     ("Jos", (ww + 0.1, 0.06, 0.07), (wx, fy, wz - wh / 2)),
                     ("St", (0.07, 0.06, wh), (wx - ww / 2, fy, wz)),
                     ("Dr", (0.07, 0.06, wh), (wx + ww / 2, fy, wz)),
                     ("MijV", (0.04, 0.05, wh), (wx, fy, wz)),
                     ("MijO", (ww, 0.05, 0.04), (wx, fy, wz))]:
        _part(f"Fereastra_Rama_{nm}", 'cube', d, M["alb"], l, bevel=0.012)
    _part("Fereastra_Pervaz", 'cube', (ww + 0.3, 0.16, 0.05), M["alb"], (wx, BACK_Y - 0.08, wz - wh / 2 - 0.05), bevel=0.015)
    for s in (-1, 1):
        _part(f"Perdea_{'St' if s < 0 else 'Dr'}", 'cube', (0.26, 0.06, 1.55), M["roz"],
              (wx + s * (ww / 2 + 0.17), BACK_Y - 0.06, wz + 0.05), bevel=0.025)

    # --- rug in the centre of the action (thin so feet at z=0 don't sink visibly)
    _part("Covor_Margine", 'cyl', (5.0, 2.5, 0.004), M["covor_margine"], (-0.6, 0.3, 0.002), seg=64)
    _part("Covor", 'cyl', (4.6, 2.15, 0.006), M["covor"], (-0.6, 0.3, 0.003), seg=64)

    # --- wall decor: bunting, star, cloud
    _bunting(M, LEFT_X + 0.15, 1.45, 2.55, 0.28, BACK_Y - 0.02)
    _star("Stea_Perete", M["galben"], (-1.35, BACK_Y - 0.06, 1.85))
    _star("Stea_Mica", M["galben"], (-0.85, BACK_Y - 0.06, 2.1), 0.12, 0.055)
    for i, (dx, dz, r) in enumerate([(-0.2, 0, 0.17), (0.0, 0.07, 0.22), (0.22, 0.0, 0.16), (0.05, -0.06, 0.15)]):
        _part(f"Nor_{i}", 'sphere', (2 * r * 1.15, 0.06, 2 * r), M["alb"], (-2.7 + dx, BACK_Y - 0.04, 1.7 + dz))

    # --- shelf with toys (back-left corner)
    sx, sy, sw, sd, sh = -3.2, BACK_Y - 0.2, 0.95, 0.36, 0.95
    _part("Raft_Spate", 'cube', (sw, 0.03, sh), M["lambriu"], (sx, sy + sd / 2 - 0.015, sh / 2))
    for s in (-1, 1):
        _part(f"Raft_Lateral_{s:+d}", 'cube', (0.05, sd, sh), M["alb"], (sx + s * sw / 2, sy, sh / 2), bevel=0.015)
    for i, z in enumerate((0.04, 0.48, sh)):
        _part(f"Raft_Polita_{i}", 'cube', (sw + 0.05, sd, 0.05), M["alb"], (sx, sy, z), bevel=0.015)
    _part("Raft_Cub_A", 'cube', (0.2, 0.2, 0.2), M["bleu"], (sx - 0.22, sy, 0.165), (0, 0, 0.2), bevel=0.035)
    _part("Raft_Cub_B", 'cube', (0.2, 0.2, 0.2), M["galben"], (sx + 0.05, sy, 0.165), (0, 0, -0.15), bevel=0.035)
    _part("Raft_Minge", 'sphere', (0.16, 0.16, 0.16), M["roz"], (sx + 0.3, sy, 0.145))
    for i, (r, col) in enumerate([(0.2, "lila"), (0.16, "bleu"), (0.12, "menta"), (0.08, "galben")]):
        _part(f"Raft_Piramida_{i}", 'cyl', (r, r, 0.05), M[col], (sx - 0.2, sy, 0.535 + i * 0.05), bevel=0.02)
    _part("Raft_Piramida_Varf", 'sphere', (0.06, 0.06, 0.06), M["roz"], (sx - 0.2, sy, 0.75))
    _part("Raft_Iepuras_Corp", 'sphere', (0.16, 0.13, 0.18), M["alb"], (sx + 0.2, sy, 0.59))
    _part("Raft_Iepuras_Cap", 'sphere', (0.12, 0.11, 0.11), M["alb"], (sx + 0.2, sy, 0.72))
    for s in (-1, 1):
        _part(f"Raft_Iepuras_Ureche_{s:+d}", 'sphere', (0.035, 0.025, 0.12), M["roz"],
              (sx + 0.2 + s * 0.03, sy, 0.81), (0, s * 0.2, 0))
    _part("Raft_Lampa", 'sphere', (0.22, 0.18, 0.18), M["menta"], (sx, sy, 1.06))

    # --- floor toys (out of the walking path)
    _part("Minge", 'sphere', (0.34, 0.34, 0.34), M["coral"], (-3.1, 0.55, 0.17))
    _part("Minge_Dunga", 'cyl', (0.345, 0.345, 0.06), M["alb"], (-3.1, 0.55, 0.17), (0.4, 0.3, 0), seg=24)
    bx, by = 1.55, 1.25
    for i, (dx, dy, z, rz, col) in enumerate([(0, 0, 0.12, 0.1, "roz"), (0.25, 0.05, 0.12, -0.25, "bleu"),
                                               (0.12, 0.02, 0.36, 0.3, "menta"), (0.4, -0.25, 0.12, 0.6, "galben")]):
        _part(f"Cub_Jucarie_{i}", 'cube', (0.24, 0.24, 0.24), M[col], (bx + dx, by + dy, z), (0, 0, rz), bevel=0.045)

    # --- teddy bear sitting under the window, facing camera
    tx, ty = 2.45, 1.55
    br, cr = M["ursulet"], M["ursulet2"]
    _part("Ursulet_Corp", 'sphere', (0.36, 0.3, 0.4), br, (tx, ty, 0.22))
    _part("Ursulet_Burta", 'sphere', (0.22, 0.1, 0.25), cr, (tx, ty - 0.12, 0.2))
    _part("Ursulet_Cap", 'sphere', (0.3, 0.27, 0.27), br, (tx, ty - 0.02, 0.53))
    _part("Ursulet_Bot", 'sphere', (0.12, 0.08, 0.09), cr, (tx, ty - 0.15, 0.5))
    _part("Ursulet_Nas", 'sphere', (0.045, 0.03, 0.035), M["negru"], (tx, ty - 0.19, 0.52))
    for s in (-1, 1):
        _part(f"Ursulet_Ureche_{s:+d}", 'sphere', (0.1, 0.06, 0.1), br, (tx + s * 0.12, ty, 0.66))
        _part(f"Ursulet_Ochi_{s:+d}", 'sphere', (0.035, 0.02, 0.035), M["negru"], (tx + s * 0.06, ty - 0.14, 0.57))
        _part(f"Ursulet_Brat_{s:+d}", 'sphere', (0.11, 0.11, 0.24), br, (tx + s * 0.19, ty - 0.04, 0.27), (0.3, s * 0.5, 0))
        _part(f"Ursulet_Picior_{s:+d}", 'sphere', (0.13, 0.24, 0.12), br, (tx + s * 0.1, ty - 0.17, 0.06))
        _part(f"Ursulet_Talpa_{s:+d}", 'sphere', (0.09, 0.02, 0.09), cr, (tx + s * 0.1, ty - 0.29, 0.07))

    # --- lighting: big soft warm key from front-left (sunny side), cool fill front-right,
    # warm rim from behind/above to separate characters from the wall, window glow.
    lights = [
        _light("Lumina_Cheie", (-3.0, -3.6, 3.1), (-0.6, 0.3, 0.7), 900, "FFE6C8", 2.5),
        _light("Lumina_Umplere", (3.2, -4.2, 2.0), (-0.4, 0.0, 0.9), 350, "E6ECFF", 4.0),
        _light("Lumina_Contur", (-0.6, 0.9, 3.0), (-0.6, -0.3, 1.0), 300, "FFF0DC", 2.0, 90),
        _light("Lumina_Fereastra", (wx, BACK_Y - 0.25, wz), (wx - 0.6, 0.0, 0.3), 120, "DDEEFF", 1.2, 60),
    ]

    # --- world: soft pastel ambient
    w = scene.world or bpy.data.worlds.new("World")
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = _lin("FFF1E8")
    bg.inputs["Strength"].default_value = 0.6

    # --- cameras (look from -Y to +Y)
    cam = _camera("Camera", (-0.6, -5.3, 1.2), (-0.6, 0.0, 0.83), 35.0)
    cam2 = _camera("Camera_aproape", (0.2, -3.7, 1.05), (0.2, 0.0, 0.88), 40.0)
    scene.camera = cam
    return {"camera": cam, "camera_aproape": cam2, "lights": lights, "root": _COLL}


def setup_render(width=960, height=540, fps=30, samples=16):
    sc = bpy.context.scene
    r = sc.render
    r.engine = ENGINE
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.fps, r.fps_base = fps, 1.0
    r.film_transparent = False
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    sc.eevee.taa_render_samples = samples
    # AgX keeps soft highlight rolloff on cream/white surfaces; Punchy look restores pastel saturation AgX mutes.
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'AgX - Punchy'
    sc.view_settings.exposure = 0.25
    sc.view_settings.gamma = 1.0
