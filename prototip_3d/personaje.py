"""Personaje 3D stilizate (Mama, Fetita) construite doar din bpy.

API (vezi CONTRACT.md):
    build_mama(name="Mama") -> dict
    build_fetita(name="Fetita") -> dict
    dict = {"rig": armature, "mouth": obiect (shape key "zambet"),
            "eyelids": [pleoapa.L, pleoapa.R] (shape key "clipire"), "height": float}

Piese rigide parentate pe oase (parent_type BONE), fara skinning.
Controalele (root, hand_ik, foot_ik, privire, *_pole) au axele aliniate cu lumea,
deci pose_bone.location = deplasare in metri in coordonate lume (X, Y, Z) la rest.
"""
import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

# ---------------------------------------------------------------- utilitare


def _lin(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def _grid(rings, cap0=None, cap1=None, closed=True):
    """Inele de puncte (aceeasi lungime) -> (verts, faces); cap0/cap1 = poli la capete."""
    n = len(rings[0])
    V = [tuple(v) for r in rings for v in r]
    F = []
    m = n if closed else n - 1
    for i in range(len(rings) - 1):
        for j in range(m):
            a, b = i * n + j, i * n + (j + 1) % n
            F.append((a, b, b + n, a + n))
    if cap0 is not None:
        V.append(tuple(cap0))
        c = len(V) - 1
        F += [(c, (j + 1) % n, j) for j in range(m)]
    if cap1 is not None:
        V.append(tuple(cap1))
        c, o = len(V) - 1, (len(rings) - 1) * n
        F += [(o + j, o + (j + 1) % n, c) for j in range(m)]
    return V, F


def _merge(parts):
    V, F = [], []
    for v, f in parts:
        o = len(V)
        V += v
        F += [tuple(i + o for i in p) for p in f]
    return V, F


def _frame(d, ref=Vector((0, -1, 0))):
    d = d.normalized()
    if abs(d.dot(ref)) > 0.95:
        ref = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
    u = d.cross(ref).normalized()
    return d, u, d.cross(u).normalized()


def _ell(c, r, rot=None, nu=16, nv=10):
    c, R = Vector(c), (rot or Matrix.Identity(3))
    rings = []
    for i in range(1, nv):
        th = math.pi * i / nv
        z, s = -math.cos(th), math.sin(th)
        rings.append([c + R @ Vector((r[0] * s * math.cos(2 * math.pi * j / nu),
                                      r[1] * s * math.sin(2 * math.pi * j / nu), r[2] * z))
                      for j in range(nu)])
    return _grid(rings, c + R @ Vector((0, 0, -r[2])), c + R @ Vector((0, 0, r[2])))


def _curl(c, r, ph, rot, nu=12, nv=14):
    """Bucla: elipsoid alungit cu un sant elicoidal (tirbuson)."""
    c = Vector(c)
    rings = []
    for i in range(1, nv):
        th = math.pi * i / nv
        z, s = -math.cos(th), math.sin(th)
        ring = []
        for j in range(nu):
            a = 2 * math.pi * j / nu
            k = 1 + 0.16 * math.sin(a + z * 9 + ph)
            ring.append(c + rot @ Vector((r * k * s * math.cos(a), r * k * s * math.sin(a), 1.35 * r * z)))
        rings.append(ring)
    return _grid(rings, c + rot @ Vector((0, 0, -1.35 * r)), c + rot @ Vector((0, 0, 1.35 * r)))


def _rot_axes(x, y, z):
    """Matrice 3x3 cu coloanele = axele date (local X,Y,Z ale elipsoidului)."""
    return Matrix((x, y, z)).transposed()


def _tube(pts, radii, nu=10, ref=Vector((0, -1, 0)), caps=True):
    """Tub de-a lungul unei curbe; radii[i] = r sau (ru, rv)."""
    pts = [Vector(p) for p in pts]
    rings = []
    for i, p in enumerate(pts):
        t = pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]
        _, u, v = _frame(t, ref)
        ra = radii[i] if isinstance(radii[i], (tuple, list)) else (radii[i], radii[i])
        rings.append([p + ra[0] * math.cos(a) * u + ra[1] * math.sin(a) * v
                      for a in (2 * math.pi * j / nu for j in range(nu))])
    if not caps:
        return _grid(rings)
    d0 = (pts[0] - pts[1]).normalized()
    d1 = (pts[-1] - pts[-2]).normalized()
    r0 = radii[0] if not isinstance(radii[0], (tuple, list)) else min(radii[0])
    r1 = radii[-1] if not isinstance(radii[-1], (tuple, list)) else min(radii[-1])
    return _grid(rings, pts[0] + d0 * r0 * 0.6, pts[-1] + d1 * r1 * 0.6)


def _caps(p0, p1, r0, r1, nu=12, nh=3):
    p0, p1 = Vector(p0), Vector(p1)
    d, u, v = _frame(p1 - p0)

    def ring(c, r):
        return [c + r * (math.cos(a) * u + math.sin(a) * v) for a in (2 * math.pi * j / nu for j in range(nu))]
    rings = [ring(p0 - d * r0 * math.cos(t), r0 * math.sin(t))
             for t in (math.pi / 2 * k / nh for k in range(1, nh + 1))]
    rings += [ring(p1 + d * r1 * math.cos(t), r1 * math.sin(t))
              for t in (math.pi / 2 * k / nh for k in range(nh, 0, -1))]
    return _grid(rings, p0 - d * r0, p1 + d * r1)


def _mesh(name, VF, coll, mats, origin=None, sub=2, solid=0.0, smooth=True):
    V, F = VF
    o = Vector(origin) if origin is not None else Vector()
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(Vector(v) - o) for v in V], [], F)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    ob.location = o
    coll.objects.link(ob)
    if solid:
        md = ob.modifiers.new("Solidify", 'SOLIDIFY')
        md.thickness = solid
        md.offset = -1
    if sub:
        md = ob.modifiers.new("Subsurf", 'SUBSURF')
        md.levels = 1
        md.render_levels = sub
    return ob


def _attach(ob, rig, bone):
    b = rig.data.bones[bone]
    ob.parent = rig
    ob.parent_type = 'BONE'
    ob.parent_bone = bone
    ob.matrix_parent_inverse = (rig.matrix_world @ b.matrix_local @
                                Matrix.Translation((0, b.length, 0))).inverted()


# ---------------------------------------------------------------- materiale


def _pb(name, color, rough=0.5, sheen=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    if color:
        b.inputs["Base Color"].default_value = _lin(color)
        m.diffuse_color = _lin(color)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Coat Weight"].default_value = coat
    return m


class _G:
    """Mic ajutor pentru noduri de shader."""

    def __init__(s, m):
        s.t = m.node_tree
        s.bsdf = s.t.nodes["Principled BSDF"]

    def n(s, typ, **kw):
        nd = s.t.nodes.new(typ)
        for k, v in kw.items():
            setattr(nd, k, v)
        return nd

    def set(s, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            s.t.links.new(v, sock)
        else:
            sock.default_value = v

    def math(s, op, a, b=0.0, clamp=False):
        nd = s.n('ShaderNodeMath', operation=op, use_clamp=clamp)
        s.set(nd.inputs[0], a)
        s.set(nd.inputs[1], b)
        return nd.outputs[0]

    def vmath(s, op, a, b=(0, 0, 0)):
        nd = s.n('ShaderNodeVectorMath', operation=op)
        s.set(nd.inputs[0], a)
        s.set(nd.inputs[1], b)
        return nd.outputs[1] if op in ('DOT_PRODUCT', 'DISTANCE', 'LENGTH') else nd.outputs[0]

    def mix(s, fac, a, b):
        nd = s.n('ShaderNodeMix', data_type='RGBA')
        s.set(nd.inputs[0], fac)
        s.set(nd.inputs[6], a)
        s.set(nd.inputs[7], b)
        return nd.outputs[2]

    def obj(s):
        return s.n('ShaderNodeTexCoord').outputs['Object']

    def xyz(s, v):
        nd = s.n('ShaderNodeSeparateXYZ')
        s.set(nd.inputs[0], v)
        return nd.outputs

    def ramp(s, fac, stops, constant=False):
        nd = s.n('ShaderNodeValToRGB')
        if constant:
            nd.color_ramp.interpolation = 'CONSTANT'
        els = nd.color_ramp.elements
        els[0].position, els[0].color = stops[0][0], _lin(stops[0][1])
        els[1].position, els[1].color = stops[-1][0], _lin(stops[-1][1])
        for p, c in stops[1:-1]:
            els.new(p).color = _lin(c)
        s.set(nd.inputs[0], fac)
        return nd.outputs[0]


def _skin_mat(name, cheeks, rad):
    m = _pb(name, '#F6C3A0', 0.55)
    g = _G(m)
    o = g.obj()
    d = g.math('MINIMUM', g.vmath('DISTANCE', o, cheeks[0]), g.vmath('DISTANCE', o, cheeks[1]))
    f = g.math('SUBTRACT', 1.0, g.math('DIVIDE', d, rad), clamp=True)
    f = g.math('MULTIPLY', g.math('MULTIPLY', f, f), 0.55)
    g.set(g.bsdf.inputs["Base Color"], g.mix(f, _lin('#F6C3A0'), _lin('#F28B8B')))
    return m


def _eye_mat(name, iris_deg):
    m = _pb(name, None, 0.08, coat=0.6)
    g = _G(m)
    nrm = g.vmath('NORMALIZE', g.obj())
    front = g.vmath('DOT_PRODUCT', nrm, (0, -1, 0))
    ci = math.cos(math.radians(iris_deg))
    cp = math.cos(math.radians(iris_deg * 0.45))
    col = g.ramp(front, [(ci - 0.004, '#F8F8F6'), (ci, '#16306E'), (ci + 0.03, '#2559B8'),
                         (cp - 0.03, '#4FA0EE'), (cp - 0.002, '#3A86DA'), (cp, '#0B0B14'), (1.0, '#0B0B14')])
    h1 = g.vmath('DOT_PRODUCT', nrm, Vector((0.32, -0.85, 0.42)).normalized())
    h2 = g.vmath('DOT_PRODUCT', nrm, Vector((-0.2, -0.93, -0.3)).normalized())
    hl = g.math('MAXIMUM', g.math('GREATER_THAN', h1, 0.988), g.math('GREATER_THAN', h2, 0.997))
    g.set(g.bsdf.inputs["Base Color"], g.mix(hl, col, (1, 1, 1, 1)))
    g.set(g.bsdf.inputs["Emission Color"], (1, 1, 1, 1))
    g.set(g.bsdf.inputs["Emission Strength"], g.math('MULTIPLY', hl, 1.5))
    return m


def _mouth_mat(name):
    m = _pb(name, None, 0.35)
    g = _G(m)
    uv = g.n('ShaderNodeUVMap').outputs[0]
    v = g.xyz(uv)[1]
    col = g.ramp(v, [(0.0, '#D45A6E'), (0.3, '#B23A4C'), (0.55, '#5E1A24'),
                     (0.79, '#4A121B'), (0.8, '#FBF8F2'), (1.0, '#FBF8F2')])
    g.set(g.bsdf.inputs["Base Color"], col)
    return m


def _hair_mat(name, color):
    m = _pb(name, color, 0.42, sheen=0.3)
    g = _G(m)
    mp = g.n('ShaderNodeMapping')
    g.set(mp.inputs['Vector'], g.obj())
    g.set(mp.inputs['Scale'], (160, 160, 5))
    nz = g.n('ShaderNodeTexNoise')
    g.set(nz.inputs['Vector'], mp.outputs[0])
    g.set(nz.inputs['Detail'], 3.0)
    base = Vector(_lin(color)[:3])
    dark, light = tuple(base * 0.85) + (1,), tuple(base * 1.15) + (1,)
    g.set(g.bsdf.inputs["Base Color"], g.mix(nz.outputs['Fac'], dark, light))
    return m


def _dots_mat(name, base, dot, scale, thr):
    m = _pb(name, base, 0.7, sheen=0.4)
    g = _G(m)
    vo = g.n('ShaderNodeTexVoronoi')
    g.set(vo.inputs['Vector'], g.obj())
    g.set(vo.inputs['Scale'], scale)
    g.set(vo.inputs['Randomness'], 0.0)
    mask = g.math('LESS_THAN', vo.outputs['Distance'], thr)
    g.set(g.bsdf.inputs["Base Color"], g.mix(mask, _lin(base), _lin(dot)))
    return m


def _flower_skirt_mat(name, base, zrow, rrow, n):
    """Rand de floricele albe cu centru galben langa tiv (coordonate cilindrice)."""
    m = _pb(name, base, 0.75, sheen=0.4)
    g = _G(m)
    x, y, z = g.xyz(g.obj())[:3]
    u = g.math('ADD', g.math('MULTIPLY', g.math('ARCTAN2', x, y), n / (2 * math.pi)), 0.5)
    fu = g.math('SUBTRACT', g.math('FRACT', u), 0.5)
    v = g.math('DIVIDE', g.math('SUBTRACT', z, zrow), 2 * math.pi * rrow / n)
    d = g.math('SQRT', g.math('ADD', g.math('MULTIPLY', fu, fu), g.math('MULTIPLY', v, v)))
    th = g.math('ARCTAN2', v, fu)
    lim = g.math('MULTIPLY', g.math('ADD', 0.5, g.math('MULTIPLY', 0.5, g.math(
        'ABSOLUTE', g.math('COSINE', g.math('MULTIPLY', th, 2.5))))), 0.34)
    white = g.math('LESS_THAN', d, lim)
    yel = g.math('LESS_THAN', d, 0.09)
    col = g.mix(white, _lin(base), _lin('#FFFFFF'))
    g.set(g.bsdf.inputs["Base Color"], g.mix(yel, col, _lin('#F7C928')))
    return m


def _mask_mat(name, a, b, maskfn, rough=0.7, sheen=0.4):
    """Culoare a, sau b unde maskfn(g, x, y, z) -> 1."""
    m = _pb(name, a, rough, sheen=sheen)
    g = _G(m)
    x, y, z = g.xyz(g.obj())[:3]
    g.set(g.bsdf.inputs["Base Color"], g.mix(maskfn(g, x, y, z), _lin(a), _lin(b)))
    return m


# ---------------------------------------------------------------- cap


class _Head:
    def __init__(s, c, r, taper):
        s.c, s.r, s.taper = Vector(c), r, taper

    def pt(s, th, ph, k=1.0, dy=0.0, dz=0.0):
        X, Y, Z = math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)
        t = max(0.0, -Z)
        w = 1 - s.taper * t * t
        return Vector((s.c.x + s.r[0] * k * w * X, s.c.y + dy + s.r[1] * k * w * Y, s.c.z + dz + s.r[2] * k * Z))

    def mesh(s, k=1.0, dy=0.0, dz=0.0, nu=48, nv=32):
        rings = [[s.pt(math.pi * i / nv, 2 * math.pi * j / nu, k, dy, dz) for j in range(nu)] for i in range(1, nv)]
        return _grid(rings, s.pt(0, 0, k, dy, dz), s.pt(math.pi, 0, k, dy, dz))

    def norm(s, p):
        """(X,Y,Z) normalizat si factorul de ingustare."""
        u = (p.z - s.c.z) / s.r[2]
        t = max(0.0, -u)
        w = 1 - s.taper * t * t
        return (p.x - s.c.x) / (s.r[0] * w), (p.y - s.c.y) / (s.r[1] * w), u, w

    def inside(s, p):
        X, Y, Z, _ = s.norm(p)
        return X * X + Y * Y + Z * Z < 1.0

    def front(s, x, z, off=0.0):
        """Punct pe fata capului (spre -Y) la (x, z) + normala * off."""
        u = (z - s.c.z) / s.r[2]
        t = max(0.0, -u)
        w = 1 - s.taper * t * t
        q = max(0.0, 1 - (x / (s.r[0] * w)) ** 2 - u * u)
        p = Vector((x, s.c.y - s.r[1] * w * math.sqrt(q), z))
        n = Vector(((p.x - s.c.x) / (s.r[0] * w) ** 2, (p.y - s.c.y) / (s.r[1] * w) ** 2,
                    (p.z - s.c.z) / s.r[2] ** 2)).normalized()
        return p + n * off, n


def _hair_cap(head, k, cut, dy=0.006, dz=0.006):
    """Calota de par = coaja capului scalata k, fara fetele unde cut(p); marginea netezita."""
    V, F = head.mesh(k, dy, dz, nu=48, nv=30)
    F = [f for f in F if not cut(sum((Vector(V[i]) for i in f), Vector()) / len(f))]
    cnt = {}
    for f in F:
        for i in range(len(f)):
            e = tuple(sorted((f[i], f[(i + 1) % len(f)])))
            cnt[e] = cnt.get(e, 0) + 1
    nb = {}
    for (a, b), n in cnt.items():
        if n == 1:
            nb.setdefault(a, []).append(b)
            nb.setdefault(b, []).append(a)
    V = [Vector(v) for v in V]
    off = Vector((0, dy, dz))
    for _ in range(10):
        new = {i: (V[i] * 2 + sum((V[j] for j in ns), Vector())) / (2 + len(ns)) for i, ns in nb.items()}
        for i, p in new.items():
            X, Y, Z, _ = head.norm(p - off)
            L = math.sqrt(X * X + Y * Y + Z * Z)
            V[i] = head.c + off + (p - off - head.c) * (k / L)
    return V, F


def _edir(e, a):
    e, a = math.radians(e), math.radians(a)
    return Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))


def _boundary(head, c, R, a, up=True):
    """Elevatia (grade) la care sfera ochiului (raza R) intra in cap, pe azimutul a."""
    step = 2 if up else -2
    for e in range(0, step * 61, step):
        if head.inside(c + R * _edir(e, a)):
            return e
    return 120 * (1 if up else -1)


# ---------------------------------------------------------------- rig


def _make_rig(name, coll, P):
    H = P
    bones = {}  # nume: (head, tail, parent, connect, deform)
    W = lambda p: Vector(p)  # noqa: E731
    Y = Vector((0, 0.1 * P['scale'], 0))
    bones['root'] = (W((0, 0, 0)), W((0, 0.3 * P['scale'], 0)), None, False, False)
    bones['hips'] = (W((0, 0, H['hips'])), W((0, 0, H['spine'])), 'root', False, True)
    bones['spine'] = (W((0, 0, H['spine'])), W((0, 0, H['chest'])), 'hips', True, True)
    bones['chest'] = (W((0, 0, H['chest'])), W((0, 0, H['neck'])), 'spine', True, True)
    bones['neck'] = (W((0, 0, H['neck'])), W((0, 0, H['headb'])), 'chest', True, True)
    bones['head'] = (W((0, 0, H['headb'])), W((0, 0, H['top'])), 'neck', True, True)
    ex, ez, er = P['eye']
    bones['privire'] = (W((0, -1.0, ez)), W((0, -1.0, ez)) + Y, 'root', False, False)
    for s, sx in (('L', 1), ('R', -1)):
        m = lambda v: Vector((v[0] * sx, v[1], v[2]))  # noqa: E731
        sh, el, wr, ht = m(P['sh']), m(P['el']), m(P['wr']), m(P['ht'])
        hp, kn, an, toe = m(P['hip']), m(P['kn']), m(P['an']), m(P['toe'])
        bones['upper_arm.' + s] = (sh, el, 'chest', False, True)
        bones['forearm.' + s] = (el, wr, 'upper_arm.' + s, True, True)
        bones['hand.' + s] = (wr, ht, 'forearm.' + s, True, True)
        bones['thigh.' + s] = (hp, kn, 'hips', False, True)
        bones['shin.' + s] = (kn, an, 'thigh.' + s, True, True)
        bones['foot.' + s] = (an, toe, 'shin.' + s, True, True)
        bones['hand_ik.' + s] = (wr, wr + Y, 'root', False, False)
        bones['foot_ik.' + s] = (an, an + Y, 'root', False, False)
        bones['mch_foot.' + s] = (an, toe, 'foot_ik.' + s, False, False)
        bones['arm_pole.' + s] = (el + Vector((0, 0.45 * P['scale'], 0)),
                                  el + Vector((0, 0.45 * P['scale'], 0)) + Y, 'chest', False, False)
        bones['knee_pole.' + s] = (kn + Vector((0, -0.5 * P['scale'], 0)),
                                   kn + Vector((0, -0.5 * P['scale'], 0)) + Y, 'root', False, False)
        ec = P['eye_c'][s]
        bones['eye.' + s] = (ec, ec + Vector((0, -er * 1.5, 0)), 'head', False, True)

    arm = bpy.data.armatures.new(name + "_Armature")
    arm.display_type = 'STICK'
    rig = bpy.data.objects.new(name + "_Rig", arm)
    coll.objects.link(rig)
    rig.show_in_front = True
    vl = bpy.context.view_layer
    vl.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.edit_bones
    for bn, (h, t, _, _, d) in bones.items():
        b = eb.new(bn)
        b.head, b.tail, b.roll, b.use_deform = h, t, 0.0, d
    for bn, (_, _, par, conn, _) in bones.items():
        if par:
            eb[bn].parent = eb[par]
            eb[bn].use_connect = conn
    bpy.ops.object.mode_set(mode='OBJECT')

    pb, db = rig.pose.bones, rig.data.bones

    def pole_angle(base, tip, pole):
        # unghiul de pol care pastreaza poza de repaus (formula standard)
        b, t, p = db[base], db[tip], db[pole].head_local
        axis = b.tail_local - b.head_local
        proj = (t.tail_local - b.head_local).cross(p - b.head_local).cross(axis)
        x = b.matrix_local.col[0].xyz
        a = x.angle(proj)
        return a if x.cross(proj).dot(axis) < 0 else -a

    for s in ('L', 'R'):
        for owner, base, tgt, pole, infl in (('shin.', 'thigh.', 'foot_ik.', 'knee_pole.', 1.0),
                                              ('forearm.', 'upper_arm.', 'hand_ik.', 'arm_pole.', 0.0)):
            c = pb[owner + s].constraints.new('IK')
            c.target, c.subtarget = rig, tgt + s
            c.pole_target, c.pole_subtarget = rig, pole + s
            c.pole_angle = pole_angle(base + s, owner + s, pole + s)
            c.chain_count, c.use_stretch, c.influence = 2, False, infl
        c = pb['foot.' + s].constraints.new('COPY_ROTATION')
        c.target, c.subtarget = rig, 'mch_foot.' + s
        c = pb['eye.' + s].constraints.new('DAMPED_TRACK')
        c.target, c.subtarget, c.track_axis = rig, 'privire', 'TRACK_Y'
        # ochii nu se rotesc peste ~30 grade (altfel irisul intra in cap); pentru mai mult, rotiti head/neck
        c = pb['eye.' + s].constraints.new('LIMIT_ROTATION')
        c.owner_space = 'LOCAL'
        c.use_limit_x = c.use_limit_z = True
        c.min_x, c.max_x = math.radians(-22), math.radians(22)
        c.min_z, c.max_z = math.radians(-30), math.radians(30)
    return rig


# ---------------------------------------------------------------- constructie comuna


def _build(name, P):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    head = _Head(P['head_c'], P['head_r'], P['taper'])
    ex, ez, er = P['eye']

    # ochi: centrul sub suprafata, iese ~55% din sfera
    P['eye_c'] = {}
    for s, sx in (('L', 1), ('R', -1)):
        sp, n = head.front(ex * sx, ez)
        P['eye_c'][s] = sp - n * er * 0.45
    rig = _make_rig(name, coll, P)

    cheeks = []
    for sx in (1, -1):
        p, _ = head.front(sx * (ex + er * 0.35), ez - er * 1.45)
        cheeks.append(p)
    skin = _skin_mat(f"{name}_piele", cheeks, er * 1.15)
    eye_m = _eye_mat(f"{name}_ochi", P['iris'])
    hair_m = _hair_mat(f"{name}_par", P['hair'])
    dark_m = _pb(f"{name}_gene", '#2A1714', 0.5)
    brow_m = _pb(f"{name}_sprancene", P['brow'], 0.6)

    def add(part, VF, mats, bone, **kw):
        ob = _mesh(f"{name}_{part}", VF, coll, mats if isinstance(mats, list) else [mats], **kw)
        _attach(ob, rig, bone)
        return ob

    # cap, nas, ochi, pleoape, gene, sprancene
    add("cap", head.mesh(), skin, 'head', sub=0)
    npnt, nn = head.front(0, P['nose'][0], 0.0)
    nr = P['nose'][1]
    add("nas", _ell(npnt + nn * nr[1] * 0.2, nr, nu=12, nv=8), skin, 'head', sub=2)

    lids = []
    for s, sx in (('L', 1), ('R', -1)):
        c = P['eye_c'][s]
        add(f"ochi.{s}", _ell(c, (er, er, er), nu=32, nv=20), eye_m, f"eye.{s}", origin=c, sub=0)
        RL = er * 1.09
        A = [sx * a for a in range(-84, 85, 12)]
        m = 8
        up = [_boundary(head, c, RL, a, True) + 9 for a in A]
        lo = [_boundary(head, c, RL, a, False) - 7 for a in A]

        def lid_rings(edges):
            return [[c + RL * _edir(118 + (e - 118) * i / m, a) for a, e in zip(A, edges)] for i in range(m + 1)]
        V0, F = _grid(lid_rings(up), closed=False)
        V1, _ = _grid(lid_rings(lo), closed=False)
        lid = add(f"pleoapa.{s}", (V0, F), skin, 'head', sub=0)
        lid.shape_key_add(name="Basis", from_mix=False)
        k = lid.shape_key_add(name="clipire", from_mix=False)
        for i, v in enumerate(V1):
            k.data[i].co = v
        lids.append(lid)

        # contur gene pe marginea de sus a ochiului, cu "codita" spre exterior
        La = list(range(-60, 76, 9))
        pts = [c + er * 1.04 * _edir(_boundary(head, c, er, sx * a, True) - 2, sx * a) for a in La]
        pts.append(pts[-1] + Vector((sx * er * 0.25, 0.0, er * 0.18)))
        rad = [er * (0.035 + 0.075 * (i / (len(pts) - 1)) ** 1.5) for i in range(len(pts))]
        add(f"gene.{s}", _tube(pts, rad, nu=8), dark_m, 'head', sub=1)

        bp = []
        for t in [i / 6 * 2 - 1 for i in range(7)]:
            x = sx * (ex + t * er * 0.95 + er * 0.1)
            z = ez + er * P['brow_h'] + er * 0.28 * (1 - t * t) + t * er * 0.06 * -1
            bp.append(head.front(x, z, P['brow_w'] * 0.6)[0])
        add(f"spranceana.{s}", _tube(bp, [P['brow_w'] * (0.55 + 0.45 * (1 - t * t)) for t in
                                         [i / 6 * 2 - 1 for i in range(7)]], nu=8), brow_m, 'head', sub=1)

    # gura: benzi (sus, dinti, mijloc, jos) proiectate pe fata, shape key "zambet"
    mz, mw, md = P['mouth']
    cols = 17
    rowsv = [0.0, 0.3, 0.6, 0.8, 1.0]

    def mouth_pts(big):
        out = []
        for v in rowsv:
            for j in range(cols):
                t = j / (cols - 1) * 2 - 1
                if not big:
                    w = mw
                    zc = mz + 0.35 * mw * t * t
                    th = mw * 0.09 * (1 - 0.75 * t * t)
                    z = zc + th * (min(v, 0.8) / 0.8 - 0.5)
                else:
                    w = mw * 1.12
                    top = mz + md * 0.25 + 0.2 * w * t * t
                    bot = top - md * (1 - t * t) ** 0.8
                    tb = top - (top - bot) * 0.28
                    z = top if v >= 1.0 else (tb if v >= 0.8 else bot + (tb - bot) * v / 0.8)
                out.append(head.front(t * w, z, 0.0018)[0])
        return out
    M0, M1 = mouth_pts(False), mouth_pts(True)
    F = [(i * cols + j, i * cols + j + 1, (i + 1) * cols + j + 1, (i + 1) * cols + j)
         for i in range(len(rowsv) - 1) for j in range(cols - 1)]
    mouth = add("gura", (M0, F), _mouth_mat(f"{name}_gura"), 'head', sub=0)
    me = mouth.data
    uvl = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        uvl.data[lp.index].uv = ((lp.vertex_index % cols) / (cols - 1), rowsv[lp.vertex_index // cols])
    mouth.shape_key_add(name="Basis", from_mix=False)
    k = mouth.shape_key_add(name="zambet", from_mix=False)
    for i, v in enumerate(M1):
        k.data[i].co = v

    # gat
    hb = P['neck']
    add("gat", _caps((0, 0, hb - 0.03 * P['scale']), (0, 0, P['head_c'][2] - P['head_r'][2] * 0.6),
                     P['neck_r'], P['neck_r']), skin, 'neck')

    # brate si picioare
    for s, sx in (('L', 1), ('R', -1)):
        m = lambda v: Vector((v[0] * sx, v[1], v[2]))  # noqa: E731
        sh, el, wr, ht = m(P['sh']), m(P['el']), m(P['wr']), m(P['ht'])
        hp, kn, an = m(P['hip']), m(P['kn']), m(P['an'])
        ra, rf, rh = P['arm_r'], P['fore_r'], P['hand_r']
        add(f"brat.{s}", _caps(sh, el, ra[0], ra[1]), skin, f"upper_arm.{s}")
        add(f"antebrat.{s}", _caps(el, wr, rf[0], rf[1]), skin, f"forearm.{s}")
        add(f"cot.{s}", _ell(el, (ra[1] * 1.02,) * 3, nu=12, nv=8), skin, f"forearm.{s}")
        d = (ht - wr).normalized()
        side = Vector((sx, 0, 0))
        fwd = d.cross(side).normalized()
        if fwd.y > 0:
            fwd = -fwd
        R = _rot_axes(fwd.cross(d).normalized(), fwd, d)
        palm = wr + d * rh[2] * 0.85
        th0 = wr + d * rh[2] * 0.35 + fwd * rh[1] * 0.7
        add(f"mana.{s}", _merge([_ell(palm, rh, R, nu=12, nv=8),
                                 _caps(th0, th0 + d * rh[2] * 0.75 + fwd * rh[1] * 0.25, rh[0] * 0.55, rh[0] * 0.45,
                                       nu=8, nh=2)]),
            skin, f"hand.{s}")
        rt, rs = P['thigh_r'], P['shin_r']
        add(f"coapsa.{s}", _caps(hp, kn, rt[0], rt[1]), skin, f"thigh.{s}")
        add(f"gamba.{s}", _caps(kn, an, rs[0], rs[1]), skin, f"shin.{s}")
        add(f"genunchi.{s}", _ell(kn, (rs[0] * 1.03,) * 3, nu=12, nv=8), skin, f"shin.{s}")
    return coll, rig, head, add, skin, hair_m, mouth, lids


# ---------------------------------------------------------------- Mama


MAMA = dict(
    scale=1.0, H=1.65,
    head_c=(0, 0.0, 1.505), head_r=(0.102, 0.108, 0.128), taper=0.34,
    hips=0.90, spine=1.0, chest=1.12, neck=1.34, headb=1.40, top=1.66,
    sh=(0.15, 0, 1.30), el=(0.21, 0.025, 1.05), wr=(0.27, 0.0, 0.82), ht=(0.285, -0.015, 0.72),
    hip=(0.075, 0, 0.86), kn=(0.08, -0.012, 0.47), an=(0.085, 0, 0.075), toe=(0.085, -0.15, 0.02),
    eye=(0.043, 1.49, 0.0285), iris=46, nose=(1.452, (0.009, 0.009, 0.012)),
    mouth=(1.413, 0.032, 0.024), brow_h=1.55, brow_w=0.0032,
    neck_r=0.032, arm_r=(0.036, 0.029), fore_r=(0.029, 0.022), hand_r=(0.016, 0.034, 0.05),
    thigh_r=(0.066, 0.05), shin_r=(0.046, 0.03),
    hair='#55301B', brow='#4A2A18', dress='#DB6F93',
)


def build_mama(name="Mama"):
    P = dict(MAMA)
    dress = _mask_mat(f"{name}_rochie", P['dress'], '#F6C3A0',
                      lambda g, x, y, z: g.math('MULTIPLY', g.math('MULTIPLY',
                                                g.math('GREATER_THAN', z, 1.272),
                                                g.math('LESS_THAN', g.math('ABSOLUTE', x), 0.072)),
                                                g.math('LESS_THAN', y, 0.0)))
    coll, rig, head, add, skin, hair_m, mouth, lids = _build(name, P)
    plain = _pb(f"{name}_rochie_simpla", P['dress'], 0.75, sheen=0.4)
    shoes = _pb(f"{name}_pantofi", '#EFA3B9', 0.35)

    # trunchi (bust) pe chest: inele (z, rx, ry, cy)
    T = [(1.065, 0.098, 0.078, 0.0), (1.12, 0.104, 0.08, 0.0), (1.19, 0.128, 0.098, -0.006),
         (1.245, 0.138, 0.104, -0.012), (1.29, 0.142, 0.088, -0.004), (1.325, 0.12, 0.072, 0.0),
         (1.352, 0.07, 0.052, 0.0)]
    ring = lambda z, rx, ry, cy, n=24: [Vector((rx * math.cos(a), cy + ry * math.sin(a), z))  # noqa: E731
                                        for a in (2 * math.pi * j / n for j in range(n))]
    add("bust", _grid([ring(*t) for t in T], (0, 0, 1.045), (0, 0, 1.362)), dress, 'chest')
    add("talie", _ell((0, 0, 1.03), (0.102, 0.08, 0.075)), plain, 'spine')
    belt = _pb(f"{name}_cordon", '#D96A8C', 0.7, sheen=0.4)
    add("cordon", _grid([ring(z, 0.108 * k, 0.085 * k, 0.0) for z, k in
                         ((0.995, 0.96), (1.005, 1.0), (1.055, 1.0), (1.065, 0.96))], closed=True), belt, 'spine')
    bc = Vector((-0.07, -0.075, 1.03))
    fw = Vector((-0.6, -0.8, 0))
    sd = Vector((0.8, -0.6, 0))
    Rb = lambda ang: _rot_axes(sd, fw, Vector((0, 0, 1))) @ Matrix.Rotation(ang, 3, 'Y')  # noqa: E731
    add("fundita_talie", _merge([
        _ell(bc + sd * 0.032 + Vector((0, 0, 0.008)), (0.032, 0.012, 0.02), Rb(-0.35), nu=12, nv=8),
        _ell(bc - sd * 0.032 + Vector((0, 0, 0.008)), (0.032, 0.012, 0.02), Rb(0.35), nu=12, nv=8),
        _ell(bc, (0.013, 0.012, 0.015), nu=10, nv=6),
        _tube([bc, bc + sd * 0.012 + Vector((0, 0, -0.05)), bc + sd * 0.02 + Vector((0, 0, -0.085))],
              [(0.011, 0.004)] * 3, ref=fw),
        _tube([bc, bc - sd * 0.014 + Vector((0, 0, -0.045)), bc - sd * 0.026 + Vector((0, 0, -0.075))],
              [(0.011, 0.004)] * 3, ref=fw)]), belt, 'spine')

    # fusta clopot cu pliuri, pe hips
    S = [(1.02, 0.10, 0.078), (0.97, 0.13, 0.105), (0.89, 0.172, 0.145), (0.76, 0.225, 0.195),
         (0.62, 0.275, 0.24), (0.49, 0.325, 0.285), (0.455, 0.33, 0.29)]
    rings = []
    for z, rx, ry in S:
        f = (1.02 - z) / 0.57
        rings.append([Vector((rx * (1 + 0.045 * f * math.cos(14 * a)) * math.cos(a),
                              ry * (1 + 0.045 * f * math.cos(14 * a)) * math.sin(a), z))
                      for a in (2 * math.pi * j / 56 for j in range(56))])
    add("fusta", _grid(rings), plain, 'hips', solid=0.006)
    add("bazin", _ell((0, 0, 0.88), (0.13, 0.1, 0.09)), plain, 'hips')

    for s, sx in (('L', 1), ('R', -1)):
        sh = Vector((P['sh'][0] * sx, 0, P['sh'][2]))
        add(f"maneca.{s}", _ell(sh + Vector((0.012 * sx, 0, -0.035)), (0.062, 0.062, 0.068)), plain, f"upper_arm.{s}")
        add(f"pantof.{s}", _ell((0.085 * sx, -0.045, 0.032), (0.043, 0.108, 0.034)), shoes, f"foot.{s}")

    # par: calota + masa lunga la spate + suvite laterale
    def cut(p):
        X, Y, Z, _ = head.norm(p)
        return (Y < -0.12 and Z < 0.6 - 1.15 * X * X) or (Z < -0.2 and Y < 0.5)
    V, F = _hair_cap(head, 1.1, cut)
    add("par_calota", (V, F), hair_m, 'head', solid=0.014)

    B = [(1.62, 0.02, 0.10, 0.09), (1.55, 0.035, 0.122, 0.092), (1.47, 0.055, 0.138, 0.08),
         (1.39, 0.105, 0.155, 0.055), (1.31, 0.145, 0.172, 0.045), (1.21, 0.17, 0.168, 0.044),
         (1.11, 0.168, 0.15, 0.04), (1.03, 0.16, 0.12, 0.03), (0.99, 0.155, 0.08, 0.02)]
    rings = []
    for z, cy, rx, ry in B:
        rings.append([Vector((rx * (1 + 0.07 * math.sin(6 * a + 30 * z)) * math.cos(a),
                              cy + ry * (1 + 0.07 * math.sin(6 * a + 30 * z)) * math.sin(a), z))
                      for a in (2 * math.pi * j / 28 for j in range(28))])
    add("par_spate", _grid(rings, (0, 0.02, 1.645), (0, 0.155, 0.975)), hair_m, 'head')
    for s, sx in (('L', 1), ('R', -1)):
        # suvite plate, ondulate, care incadreaza fata (u = adancime, v = grosime laterala)
        pts = [(0.092 * sx, -0.03, 1.545), (0.106 * sx, -0.042, 1.505), (0.114 * sx, -0.045, 1.46),
               (0.124 * sx, -0.035, 1.41), (0.128 * sx, -0.025, 1.37), (0.137 * sx, -0.02, 1.345)]
        rad = [(0.03, 0.014), (0.036, 0.017), (0.036, 0.018), (0.032, 0.017), (0.026, 0.014), (0.012, 0.008)]
        add(f"par_suvita.{s}", _tube(pts, rad, nu=10, ref=Vector((sx, 0, 0))), hair_m, 'head')

    return {"rig": rig, "mouth": mouth, "eyelids": lids, "height": P['H']}


# ---------------------------------------------------------------- Fetita


FETITA = dict(
    scale=0.6, H=0.95,
    head_c=(0, 0.0, 0.775), head_r=(0.135, 0.126, 0.14), taper=0.22,
    hips=0.36, spine=0.42, chest=0.47, neck=0.60, headb=0.645, top=0.93,
    sh=(0.105, 0, 0.585), el=(0.152, 0.015, 0.455), wr=(0.19, -0.005, 0.345), ht=(0.198, -0.015, 0.295),
    hip=(0.055, 0, 0.355), kn=(0.058, -0.01, 0.205), an=(0.06, 0, 0.06), toe=(0.06, -0.11, 0.02),
    eye=(0.054, 0.757, 0.034), iris=47, nose=(0.722, (0.013, 0.011, 0.01)),
    mouth=(0.69, 0.034, 0.03), brow_h=1.7, brow_w=0.0042,
    neck_r=0.034, arm_r=(0.031, 0.027), fore_r=(0.027, 0.023), hand_r=(0.014, 0.027, 0.036),
    thigh_r=(0.05, 0.041), shin_r=(0.039, 0.03),
    hair='#8A4C24', brow='#7A4522', dress='#E0247E',
)


def build_fetita(name="Fetita"):
    P = dict(FETITA)
    pink = P['dress']
    coll, rig, head, add, skin, hair_m, mouth, lids = _build(name, P)
    white = _pb(f"{name}_alb", '#FAF8F4', 0.75, sheen=0.4)
    yellow = _pb(f"{name}_galben", '#F7C928', 0.4)
    top = _mask_mat(f"{name}_bluza", pink, '#FAF8F4', lambda g, x, y, z: g.math(
        'MULTIPLY', g.math('GREATER_THAN', z, 0.522),
        g.math('GREATER_THAN', g.math('ABSOLUTE', g.math('SUBTRACT', g.math('ABSOLUTE', x), 0.056)), 0.015)))
    skirt = _flower_skirt_mat(f"{name}_fusta", pink, 0.262, 0.215, 18)
    dots = _dots_mat(f"{name}_fundita", '#E3287F', '#FFFFFF', 42.0, 0.22)
    shoe = _pb(f"{name}_pantofi", '#E0247E', 0.45)

    ring = lambda z, rx, ry, cy, n=24: [Vector((rx * math.cos(a), cy + ry * math.sin(a), z))  # noqa: E731
                                        for a in (2 * math.pi * j / n for j in range(n))]
    T = [(0.43, 0.10, 0.085, 0.0), (0.47, 0.108, 0.094, -0.008), (0.51, 0.108, 0.09, -0.006),
         (0.55, 0.108, 0.078, 0.0), (0.585, 0.098, 0.068, 0.0), (0.612, 0.055, 0.042, 0.0)]
    torso = add("bust", _grid([ring(*t) for t in T], (0, 0, 0.41), (0, 0, 0.622)), top, 'chest')
    add("burta", _ell((0, -0.004, 0.43), (0.102, 0.088, 0.06)), top, 'spine')

    # floare mare + nasturi pe pieptar (lipite de suprafata reala)
    bvh = BVHTree.FromObject(torso, bpy.context.evaluated_depsgraph_get())

    def on_torso(x, z, off):
        loc, n, _, _ = bvh.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)))
        return loc + n * off, n
    fc, fn = on_torso(0, 0.488, 0.002)
    _, fu, fv = _frame(fn, Vector((0, 0, 1)))
    petals = [_ell(fc + 0.012 * (math.cos(a) * fu + math.sin(a) * fv), (0.0105, 0.0075, 0.003),
                   _rot_axes(math.cos(a) * fu + math.sin(a) * fv, -math.sin(a) * fu + math.cos(a) * fv, -fn),
                   nu=10, nv=6) for a in (2 * math.pi * k / 5 + math.pi / 2 for k in range(5))]
    add("floare", _merge(petals), white, 'chest')
    add("floare_centru", _ell(fc - fn * 0.002, (0.0055, 0.0055, 0.004), nu=10, nv=6), yellow, 'chest')
    add("nasturi", _merge([_ell(on_torso(sx * 0.056, 0.53, 0.001)[0], (0.0055,) * 3, nu=10, nv=6)
                           for sx in (1, -1)]), yellow, 'chest')

    # fusta cu volane, pe hips
    S = [(0.478, 0.114, 0.1), (0.45, 0.13, 0.115), (0.39, 0.165, 0.148), (0.32, 0.198, 0.178),
         (0.262, 0.218, 0.198), (0.232, 0.224, 0.205)]
    rings = []
    for z, rx, ry in S:
        f = (0.478 - z) / 0.246
        rings.append([Vector((rx * (1 + 0.06 * f * math.cos(16 * a)) * math.cos(a),
                              ry * (1 + 0.06 * f * math.cos(16 * a)) * math.sin(a), z))
                      for a in (2 * math.pi * j / 64 for j in range(64))])
    add("fusta", _grid(rings), skirt, 'hips', solid=0.005)
    add("bazin", _ell((0, 0, 0.36), (0.1, 0.082, 0.06)), white, 'hips')

    for s, sx in (('L', 1), ('R', -1)):
        sh = Vector((P['sh'][0] * sx, 0, P['sh'][2]))
        add(f"maneca.{s}", _ell(sh + Vector((0.01 * sx, 0, -0.025)), (0.048, 0.047, 0.05)), white, f"upper_arm.{s}")
        an = Vector((0.06 * sx, 0, 0.06))
        add(f"soseta.{s}", _caps(an + Vector((0, 0, -0.01)), an + Vector((0, 0, 0.075)), 0.036, 0.035),
            white, f"shin.{s}")
        add(f"pantof.{s}", _ell((0.06 * sx, -0.033, 0.036), (0.043, 0.078, 0.034)), shoe, f"foot.{s}")
        add(f"talpa.{s}", _ell((0.06 * sx, -0.033, 0.013), (0.046, 0.082, 0.015)), white, f"foot.{s}")

    # par: calota cu breton lateral + bucle
    def cut(p):
        X, Y, Z, _ = head.norm(p)
        return (Y < -0.12 and Z < 0.5 - 1.25 * X * X - 0.15 * X) or (Z < -0.28 and Y < 0.55)
    V, F = _hair_cap(head, 1.07, cut)
    add("par_calota", (V, F), hair_m, 'head', solid=0.014)
    c = Vector(P['head_c'])
    rx, ry = P['head_r'][:2]
    curls = []
    rnd = random.Random(7)
    for dz, k, r, span, n in ((0.1, 0.92, 0.036, 80, 9), (0.05, 1.02, 0.04, 98, 11), (-0.0, 1.08, 0.042, 106, 12),
                              (-0.05, 1.12, 0.042, 110, 12), (-0.1, 1.1, 0.04, 112, 12), (-0.15, 1.02, 0.036, 108, 11)):
        for i in range(n):
            a = math.radians(-span + 2 * span * (i + rnd.uniform(-0.3, 0.3)) / (n - 1))
            rr = r * rnd.uniform(0.85, 1.15)
            p = c + Vector((math.sin(a) * rx * k, math.cos(a) * ry * k, dz + rnd.uniform(-0.012, 0.012)))
            curls.append(_curl(p, rr, rnd.uniform(0, 6.3), Matrix.Rotation(rnd.uniform(-0.4, 0.4), 3, 'Y')))
    add("par_bucle", _merge(curls), hair_m, 'head')
    # breton lateral: suvite peste frunte, de la carare (stanga) spre tampla dreapta
    locks = []
    for (t0, p0), (t1, p1), w in (((20, -45), (62, -128), 0.03), ((30, -60), (70, -140), 0.026),
                                  ((24, -30), (50, -105), 0.026)):
        path = [head.pt(math.radians(t0 + (t1 - t0) * q), math.radians(p0 + (p1 - p0) * q), 1.1, 0.006, 0.006)
                for q in (i / 6 for i in range(7))]
        locks.append(_tube(path, [(w * (0.5 + 0.5 * math.sin(math.pi * (0.15 + 0.85 * i / 6))), 0.013)
                                  for i in range(7)], nu=10))
    add("par_breton", _merge(locks), hair_m, 'head')

    # bentita + fundita cu buline
    R = 1.115
    band = [c + Vector((math.sin(t) * rx * R, 0.012, math.cos(t) * P['head_r'][2] * R))
            for t in (math.radians(a) for a in range(-80, 81, 10))]
    add("bentita", _tube(band, [(0.006, 0.011)] * len(band), nu=8, ref=Vector((0, 1, 0))), dots, 'head')
    t = math.radians(38)
    nrm = Vector((math.sin(t), 0, math.cos(t)))
    tg = Vector((math.cos(t), 0, -math.sin(t)))
    bc = c + Vector((math.sin(t) * rx * 1.17, 0.0, math.cos(t) * P['head_r'][2] * 1.17))
    lobes = []
    for sgn in (1, -1):
        d = (tg * sgn).normalized()
        ax = (Matrix.Rotation(sgn * math.radians(-18), 3, 'Y') @ d).normalized()
        nn = ax.cross(Vector((0, -1, 0))).normalized()
        lobes.append(_ell(bc + ax * 0.058, (0.062, 0.03, 0.045), _rot_axes(ax, Vector((0, -1, 0)), nn),
                          nu=16, nv=10))
    lobes.append(_ell(bc + Vector((0, -0.006, 0)), (0.024, 0.026, 0.024), nu=12, nv=8))
    add("fundita", _merge(lobes), dots, 'head')

    return {"rig": rig, "mouth": mouth, "eyelids": lids, "height": P['H']}
