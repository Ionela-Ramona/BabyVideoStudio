"""Arms and legs that bend: a character's picture on a 2D skeleton (stage P2).

The picture is covered by a fine mesh of triangles; every point of the mesh follows one or two bones (shoulder to
elbow, elbow to hand, hip to knee, knee to ankle, and the body), so elbows and knees bend smoothly. How much a point
follows a bone is measured *inside* the character's shape, so a hand beside the skirt does not drag the skirt along.
The mesh is drawn by the graphics card (OpenGL, through moderngl), with the legs behind the body and the arms in
front of it.

The characters are seen from the front, so a motion is turned into what the camera sees:
- a limb raised sideways (`*_lat`) turns in the picture;
- a limb swung forward (`umar_*`, `sold_*`) or a bent elbow or knee gets shorter, as seen from the front;
- `palme` (0..1) brings both hands together in front of the chest.
The lower foot always stays on the ground, so bending both knees lowers the body and lifting one knee lifts its foot.

Points are kept with the character (`talking.Profile.rig`), in fractions of its picture. `guess` proposes them from
the shape alone; the user corrects them once.
"""
import heapq
import math
import threading

import numpy as np
from PIL import Image

# the skeleton's points; "drept"/"stâng" are the character's own sides (its right is on the left of the picture)
POINTS = {
    "crestet": "creștetul capului", "gat": "gâtul", "bazin": "mijlocul, unde încep picioarele",
    "umar_drept": "umărul drept", "cot_drept": "cotul drept", "mana_dreapta": "încheietura mâinii drepte",
    "umar_stang": "umărul stâng", "cot_stang": "cotul stâng", "mana_stanga": "încheietura mâinii stângi",
    "sold_drept": "șoldul drept", "genunchi_drept": "genunchiul drept", "glezna_dreapta": "glezna dreaptă",
    "sold_stang": "șoldul stâng", "genunchi_stang": "genunchiul stâng", "glezna_stanga": "glezna stângă",
}
# layers, drawn in this order: behind everything an animal's tummy completed under its paws (they are drawn on it, so
# when they move there would be a hole), legs, upper arms (their tops hide under the sleeves and the curls), the body,
# forearms and paws (in front, so the hands can meet before the tummy)
LEGS, UPPER, BODY, FORE, BACK = 0, 1, 2, 3, 4
ORDER = (BACK, LEGS, UPPER, BODY, FORE)
STRETCH = 2.5  # a triangle pulled longer than this (between a still shoulder and a raised arm) is not drawn
BONES = [  # a child's skeleton: name, from, to, layer
    ("corp", "bazin", "gat", BODY), ("cap", "gat", "crestet", BODY),
    ("brat_drept", "umar_drept", "cot_drept", UPPER), ("antebrat_drept", "cot_drept", "mana_dreapta", FORE),
    ("brat_stang", "umar_stang", "cot_stang", UPPER), ("antebrat_stang", "cot_stang", "mana_stanga", FORE),
    ("coapsa_dreapta", "sold_drept", "genunchi_drept", LEGS), ("gamba_dreapta", "genunchi_drept", "glezna_dreapta", LEGS),
    ("coapsa_stanga", "sold_stang", "genunchi_stang", LEGS), ("gamba_stanga", "genunchi_stang", "glezna_stanga", LEGS),
]
INDEX = {name: n for n, (name, *_) in enumerate(BONES)}
# an animal standing like a toy (stage P3): a big head on a round body, and only the parts it has: ears, a tail, paws
# or little wings, feet. Each part is one bone; the head turns on the body, the ears and the tail on the head and body.
ANIMAL_POINTS = {
    "crestet": "creștetul capului", "gat": "unde se unește capul cu corpul", "bazin": "jos, la mijlocul corpului",
    "ureche_dreapta": "baza urechii drepte", "ureche_dreapta_varf": "vârful urechii drepte",
    "ureche_stanga": "baza urechii stângi", "ureche_stanga_varf": "vârful urechii stângi",
    "coada": "baza cozii", "coada_varf": "vârful cozii",
    "umar_drept": "unde se prinde lăbuța (aripioara) dreaptă", "mana_dreapta": "vârful lăbuței (aripioarei) drepte",
    "umar_stang": "unde se prinde lăbuța (aripioara) stângă", "mana_stanga": "vârful lăbuței (aripioarei) stângi",
    "sold_drept": "sus, pe talpa dreaptă", "glezna_dreapta": "jos, sub talpa dreaptă",
    "sold_stang": "sus, pe talpa stângă", "glezna_stanga": "jos, sub talpa stângă",
}
ANIMAL_BONES = [
    ("corp", "bazin", "gat", BODY), ("cap", "gat", "crestet", BODY),
    ("ureche_dreapta", "ureche_dreapta", "ureche_dreapta_varf", BODY),
    ("ureche_stanga", "ureche_stanga", "ureche_stanga_varf", BODY),
    ("coada", "coada", "coada_varf", LEGS),
    ("laba_dreapta", "umar_drept", "mana_dreapta", FORE), ("laba_stanga", "umar_stang", "mana_stanga", FORE),
    ("talpa_dreapta", "sold_drept", "glezna_dreapta", LEGS), ("talpa_stanga", "sold_stang", "glezna_stanga", LEGS),
]
MAX_BONES = 16
HEAD = 4.0  # degrees the head may tilt on the body: more tears long curls and fur that have no neck between


def is_human(points: dict) -> bool:
    return set(POINTS) <= set(points)


def skeleton(points: dict) -> list[tuple[str, str, str, int]]:
    """The bones these points make: a child's whole skeleton, or an animal's body, head and the parts it has."""
    if is_human(points):
        return BONES
    return [b for b in ANIMAL_BONES if b[1] in points and b[2] in points]


def usable(points: dict) -> bool:
    return is_human(points) or {"crestet", "gat", "bazin"} <= set(points)


def labels(points: dict) -> dict[str, str]:
    return POINTS if is_human(points) else {k: v for k, v in ANIMAL_POINTS.items() if k in points}
PAD = (0.35, 0.25)  # room around the picture for raised arms: of its width on each side, of its height on top

VERTEX = """
#version 330
uniform mat3 bones[16];
uniform vec2 canvas;
uniform vec2 offset;
in vec2 pos;
in vec2 uv;
in vec2 ids;
in vec2 wts;
in float only;
out vec2 g_uv;
out vec2 g_rest;
out vec2 g_posed;
out float g_only;
void main() {
    vec3 p = vec3(pos, 1.0);
    vec2 q = wts.x * (bones[int(ids.x)] * p).xy + wts.y * (bones[int(ids.y)] * p).xy;
    vec2 c = (q + offset) / canvas;
    gl_Position = vec4(c.x * 2.0 - 1.0, c.y * 2.0 - 1.0, 0.0, 1.0);
    g_uv = uv;
    g_rest = pos;
    g_posed = q;
    g_only = only;
}
"""
GEOMETRY = """
#version 330
layout(triangles) in;
layout(triangle_strip, max_vertices = 3) out;
uniform float stretch;
in vec2 g_uv[];
in vec2 g_rest[];
in vec2 g_posed[];
in float g_only[];
out vec2 v_uv;
flat out float v_only;
void main() {
    for (int i = 0; i < 3; i++) {
        int j = (i + 1) % 3;
        if (length(g_posed[i] - g_posed[j]) > stretch * max(length(g_rest[i] - g_rest[j]), 1.0)) return;
    }
    for (int i = 0; i < 3; i++) {
        gl_Position = gl_in[i].gl_Position;
        v_uv = g_uv[i];
        v_only = g_only[i];
        EmitVertex();
    }
    EndPrimitive();
}
"""
FRAGMENT = """
#version 330
uniform sampler2D tex;
uniform sampler2D owner;
in vec2 v_uv;
flat in float v_only;
out vec4 color;
void main() {
    // a cell where an arm touches the skirt is drawn twice, once with each: each copy keeps its own pixels
    if (v_only >= 0.0 && abs(texture(owner, v_uv).r * 255.0 - v_only) > 0.5) discard;
    color = texture(tex, v_uv);
}
"""
_local = threading.local()  # an OpenGL context belongs to the thread that made it


def available() -> bool:
    try:
        _gl()
        return True
    except Exception:  # no moderngl, or no OpenGL 3.3 on this computer: characters move as whole pictures
        return False


def _gl():
    if not hasattr(_local, "ctx"):
        import moderngl
        ctx = moderngl.create_standalone_context(require=330)
        _local.ctx = ctx
        _local.program = ctx.program(vertex_shader=VERTEX, geometry_shader=GEOMETRY, fragment_shader=FRAGMENT)
    return _local.ctx, _local.program


# --- proposing the points from the shape ---------------------------------------------------------------------------

def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate([[0], row.astype(np.int8), [0]])))
    return list(zip(edges[::2], edges[1::2]))


def _arm(alpha: np.ndarray, top: float, bottom: int, side: int) -> list[tuple[float, float]]:
    """Wrist, elbow and shoulder of the arm on one side (-1: left of the picture), for an arm hanging a little away
    from the body: row by row from the fingertips upwards, the middle of the outermost run of the shape, until that
    run gets as wide as a body."""
    h, w = alpha.shape
    rows = range(int(top), int(bottom))
    ends = [(_runs(alpha[y])[0 if side < 0 else -1], y) for y in rows if alpha[y].any()]
    tip_run, tip_y = min(ends, key=lambda e: e[0][0]) if side < 0 else max(ends, key=lambda e: e[0][1])
    tip = (tip_run[0] if side < 0 else tip_run[1], tip_y)
    line = []
    for y in range(tip_y, int(top), -1):
        run = _runs(alpha[y])[0 if side < 0 else -1]
        if run[1] - run[0] > 0.18 * w:  # the sleeve or the body: the arm ends here
            break
        line.append(((run[0] + run[1]) / 2, y))
    if len(line) < 4:  # no arm apart from the body: proportions of a standing child
        x0 = w / 2 + side * 0.17 * w
        return [(w / 2 + side * 0.4 * w, top + 0.35 * (bottom - top)), (w / 2 + side * 0.3 * w, top + 0.25 * (bottom - top)),
                (x0, top + 0.15 * (bottom - top))]
    points = np.array([tip, *line], float)
    steps = np.hypot(*np.diff(points, axis=0).T)
    along = np.concatenate([[0], np.cumsum(steps)])
    at = lambda share: tuple(points[np.searchsorted(along, share * along[-1]).clip(0, len(points) - 1)])  # noqa: E731
    wrist, elbow, top_end = at(0.3), at(0.68), points[-1]
    reach = np.array(top_end) - np.array(elbow)
    shoulder = tuple(np.array(top_end) + 0.45 * reach)  # under the sleeve, beyond where the bare arm starts
    return [wrist, elbow, shoulder]


def guess(picture: Image.Image) -> dict[str, tuple[float, float]]:
    """Where the joints probably are, from the outline of a character standing seen from the front, arms a little
    away from the body: feet at the bottom, legs parting under the clothes, hands at the outer ends of the arms."""
    alpha = np.asarray(picture.getchannel("A")) > 128
    h, w = alpha.shape
    ys, xs = np.nonzero(alpha)
    top, bottom = ys.min(), ys.max()
    tall = bottom - top
    cx = (xs.min() + xs.max()) / 2
    # the legs: two runs of pixels near the bottom, followed upwards until they join
    legs_row = bottom - round(0.06 * tall)
    runs = sorted(_runs(alpha[legs_row]), key=lambda r: r[1] - r[0], reverse=True)[:2]
    runs = sorted(runs) if len(runs) == 2 else [(cx - 0.12 * w, cx - 0.02 * w), (cx + 0.02 * w, cx + 0.12 * w)]
    split = legs_row
    for y in range(legs_row, top, -1):
        middle = alpha[y, int(runs[0][1]):int(runs[1][0])]
        if middle.size == 0 or middle.all():
            break
        split = y
    ankle_y = bottom - 0.07 * tall
    feet = [((a + b) / 2, ankle_y) for a, b in runs]
    hips = [((a + b) / 2 + (cx - (a + b) / 2) * 0.25, split) for a, b in runs]
    knees = [((hx + fx) / 2, (split + ankle_y) / 2) for (hx, _), (fx, _) in zip(hips, feet)]
    # the arms: followed on the drawing itself, from the fingertips up the middle of the arm to where it meets the
    # sleeve or the body; the wrist, the elbow and the shoulder are then placed along that line
    neck = (cx, top + 0.42 * tall)
    arms = [_arm(alpha, top + 0.3 * tall, split, side) for side in (-1, 1)]
    hands, elbows, shoulders = [a[0] for a in arms], [a[1] for a in arms], [a[2] for a in arms]
    found = {"crestet": (cx, top + 0.02 * tall), "gat": neck, "bazin": (cx, split),
             "umar_drept": shoulders[0], "cot_drept": elbows[0], "mana_dreapta": hands[0],
             "umar_stang": shoulders[1], "cot_stang": elbows[1], "mana_stanga": hands[1],
             "sold_drept": hips[0], "genunchi_drept": knees[0], "glezna_dreapta": feet[0],
             "sold_stang": hips[1], "genunchi_stang": knees[1], "glezna_stanga": feet[1]}
    return {k: (round(float(x) / w, 4), round(float(y) / h, 4)) for k, (x, y) in found.items()}


def guess_animal(picture: Image.Image) -> dict[str, tuple[float, float]]:
    """The parts of an animal standing like a toy, from its outline: the head on top, feet as two shapes at the
    bottom, ears as two shapes on top of the head, a tail sticking out on one side only, little wings sticking out on
    both sides."""
    alpha = np.asarray(picture.getchannel("A")) > 128
    h, w = alpha.shape
    ys, xs = np.nonzero(alpha)
    top, bottom = ys.min(), ys.max()
    tall = bottom - top
    cx = (xs.min() + xs.max()) / 2
    row = lambda share: int(top + share * tall)  # noqa: E731
    found = {"crestet": (cx, top + 0.03 * tall), "gat": (cx, row(0.55)), "bazin": (cx, row(0.82))}
    # feet: the two widest shapes just above the bottom
    feet = sorted(sorted(_runs(alpha[bottom - max(2, int(0.03 * tall))]), key=lambda r: r[0] - r[1])[:2])
    if len(feet) == 2:
        for (hip, ankle), (a, b) in zip((("sold_drept", "glezna_dreapta"), ("sold_stang", "glezna_stanga")), feet):
            found[hip] = ((a + b) / 2, row(0.9))
            found[ankle] = ((a + b) / 2, bottom)
        cx = (feet[0][0] + feet[1][1]) / 2  # the body's middle: a tail makes the whole picture lopsided
        for k in ("crestet", "gat", "bazin"):
            found[k] = (cx, found[k][1])
    # ears: two shapes on top, followed down until they join the head
    tips = sorted(sorted(_runs(alpha[row(0.07)]), key=lambda r: r[0] - r[1])[:2])
    if len(tips) == 2 and min(b - a for a, b in tips) > 0.04 * w:
        y = row(0.07)
        while y < row(0.5) and len(_runs(alpha[y][int(tips[0][0]):int(tips[1][1]) + 1])) >= 2:
            y += 1
        if y - row(0.07) > 0.06 * tall:
            for side, (a, b) in zip(("dreapta", "stanga"), tips):
                found[f"ureche_{side}_varf"] = ((a + b) / 2, row(0.07))
                found[f"ureche_{side}"] = ((a + b) / 2 + (cx - (a + b) / 2) * 0.3, y + 0.04 * tall)
    # sides of the body, row by row, from the middle
    band = range(row(0.58), row(0.95))  # below the head: its cheeks are not wings
    left = np.array([cx - np.flatnonzero(alpha[y]).min() if alpha[y].any() else 0 for y in band])
    right = np.array([np.flatnonzero(alpha[y]).max() - cx if alpha[y].any() else 0 for y in band])
    lower = max(left[-len(band) // 5:].max(), right[-len(band) // 5:].max())  # the round bottom of the body
    # a tail: far out on one side only
    for side, reach, other in ((-1, left, right), (1, right, left)):
        if reach.max() > other.max() + 0.12 * w:
            k = int(np.argmax(reach))
            found["coada_varf"] = (cx + side * reach[k], band[k])
            found["coada"] = (cx + side * 0.8 * other.max(), row(0.8))
    # little wings: out on both sides at the middle, beyond the round bottom. Paws held on the tummy are painted on
    # it: moving them would tear it, so they get no bones (the head and the ears say hello and clap instead)
    middle = slice(0, len(band) // 2)
    gap = len(band) // 3

    def widest(reach):  # the middle of the widest stretch (a wing cut by the picture's edge is widest for a while)
        rows = np.flatnonzero(reach[middle] >= reach[middle].max() - 1)
        return int(rows[len(rows) // 2])

    def sticks_out(reach):  # out further than both what is a little above it and a little below it: a wing, not a ball
        k = widest(reach)
        above = cx - np.flatnonzero(alpha[band[k] - gap]).min() if reach is left else np.flatnonzero(alpha[band[k] - gap]).max() - cx
        return reach[k] > max(above, reach[min(len(reach) - 1, k + gap)]) + 0.06 * w
    if sticks_out(left) and sticks_out(right) and "coada" not in found:
        for side, name, reach in ((-1, "drept", left), (1, "stang", right)):
            k = widest(reach)
            found[f"umar_{name}"] = (cx + side * 0.75 * lower, band[k])
            found[f"mana_{'dreapta' if name == 'drept' else 'stanga'}"] = (cx + side * reach[k], band[k])
    return {k: (round(float(x) / w, 4), round(float(y) / h, 4)) for k, (x, y) in found.items()}


# --- the mesh and how its points follow the bones ------------------------------------------------------------------

STEPS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
EDGE = 40  # crossing from one colour to a very different one (skin to pink) costs about this many cells


def _crossings(colours: np.ndarray) -> list[list[list[float]]]:
    """For each of the 8 steps, what it costs to go from each cell to that neighbour: the way, plus the change of
    colour (the edge of a sleeve, of a skirt, of a curl)."""
    out = []
    for dy, dx in STEPS:
        there = np.roll(colours, (-dy, -dx), (0, 1))
        out.append((math.hypot(dy, dx) + EDGE * np.abs(there - colours).mean(-1)).tolist())
    return out


def _geodesic(inside: np.ndarray, sources: list[tuple[int, int]], crossings: list[list[list[float]]]) -> np.ndarray:
    """Distance from the sources to every cell, walking only inside the shape (8 neighbours), a change of colour
    counting as a long way: a hand drawn against the skirt is far from it."""
    h, w = inside.shape
    dist = np.full((h, w), np.inf)
    inside_ = inside.tolist()
    best = dist.tolist()
    queue = []
    for y, x in sources:
        if 0 <= y < h and 0 <= x < w and inside_[y][x] and best[y][x] > 0:
            best[y][x] = 0.0
            queue.append((0.0, y, x))
    heapq.heapify(queue)
    while queue:
        d, y, x = heapq.heappop(queue)
        if d > best[y][x]:
            continue
        for k, (dy, dx) in enumerate(STEPS):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and inside_[ny][nx]:
                nd = d + crossings[k][y][x]
                if nd < best[ny][nx]:
                    best[ny][nx] = nd
                    heapq.heappush(queue, (nd, ny, nx))
    return np.array(best)


def _turn(centre: np.ndarray, degrees: float) -> np.ndarray:
    """A turn about a point of the picture (+ is clockwise on screen, as y goes down)."""
    a = math.radians(degrees)
    m = np.eye(3)
    m[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    m[:2, 2] = centre - m[:2, :2] @ centre
    return m


def _shift(dx: float, dy: float) -> np.ndarray:
    m = np.eye(3)
    m[:2, 2] = dx, dy
    return m


class Rig:
    def __init__(self, picture: Image.Image, points: dict[str, tuple[float, float]]):
        self.size = picture.size
        w, h = self.size
        self.points = {k: np.array([v[0] * w, v[1] * h]) for k, v in points.items()}
        self.human = is_human(points)
        self.bones = skeleton(points)
        self.index = {name: n for n, (name, *_) in enumerate(self.bones)}
        bones_ = self.bones
        alpha = np.asarray(picture.getchannel("A"), np.float32)
        self.cell = cell = max(4, round(h / 160))
        gh, gw = -(-h // cell), -(-w // cell)
        padded = np.zeros((gh * cell, gw * cell), np.float32)
        padded[:h, :w] = alpha
        blocks = padded.reshape(gh, cell, gw, cell)
        cover = blocks.mean((1, 3)) / 255  # how much of each cell is drawn
        solid = cover > 160 / 255  # the shape, for distances: a thin gap between hand and skirt stays a gap
        drawn = blocks.max((1, 3)) > 0  # every cell with anything in it gets triangles
        grown = drawn.copy()
        grown[1:] |= drawn[:-1]
        grown[:-1] |= drawn[1:]
        grown[:, 1:] |= grown[:, :-1].copy()
        grown[:, :-1] |= grown[:, 1:].copy()

        # distances inside the shape from every bone, then weights: the two nearest bones, mostly the nearest
        rgb = np.zeros((gh * cell, gw * cell, 3), np.float32)
        rgb[:h, :w] = np.asarray(picture.convert("RGB"), np.float32) / 255
        weight = padded.reshape(gh, cell, gw, cell)[..., None] + 1e-3
        colours = (rgb.reshape(gh, cell, gw, cell, 3) * weight).sum((1, 3)) / weight.sum((1, 3))
        crossings = _crossings(colours)
        dists = []
        for name, a, b, _ in bones_:
            p, q = self.points[a] / cell, self.points[b] / cell
            n = max(2, int(np.hypot(*(q - p)) * 2))
            line = {(int(round(p[1] + (q[1] - p[1]) * k / n)), int(round(p[0] + (q[0] - p[0]) * k / n))) for k in range(n + 1)}
            dists.append(_geodesic(solid, list(line), crossings))
        dists = np.stack(dists)  # bones × cells
        # a limb moves only what lies beyond its first joint and close to its bone: the skirt, the sleeves' tops and
        # the curls hanging by the shoulders stay with the body
        cy, cx = np.mgrid[0:gh, 0:gw]
        centres = np.stack([(cx + 0.5) * cell, (cy + 0.5) * cell], -1)
        for n, (name, a, b, group) in enumerate(bones_):
            if name in ("corp", "cap"):
                continue
            root, axis = self.points[a], self.points[b] - self.points[a]
            length = max(float(np.hypot(*axis)), 1e-6)
            along = ((centres - root) @ axis) / length ** 2
            nearest = root + np.clip(along, 0, 1)[..., None] * axis
            away = np.hypot(*(centres - nearest).transpose(2, 0, 1))
            lower = name.startswith(("antebrat", "gamba", "talpa", "coada", "ureche"))  # reach past the tip
            start = 0.1 if name.startswith("brat") else 0.0 if name.startswith("laba") else -0.15  # hair over shoulders
            radius = 0.6 if name.startswith("laba") else 1.0 if lower else 0.5  # a paw does not take the tummy round it
            dists[n][(along < start) | (away > radius * length)] = np.inf
        # inside the trunk (between the shoulders and the hips) everything stays with the body, also where an arm
        # touches its side
        if self.human:
            corners = [self.points[k] / cell for k in ("umar_drept", "umar_stang", "sold_stang", "sold_drept")]
            gx, gy = cx + 0.5, cy + 0.5
            sides = [(b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])
                     for a, b in zip(corners, corners[1:] + corners[:1])]
            trunk = np.all([v >= 0 for v in sides], 0) | np.all([v <= 0 for v in sides], 0)
            for n, (_, _, _, group) in enumerate(bones_):
                if group != BODY:
                    dists[n][trunk] = np.inf
        reach = np.isfinite(dists).any(0)
        if (~reach & grown).any():  # cells outside the solid shape (edges, gaps): take the nearest solid cell's values
            dists = self._spread(dists, reach)

        # the mesh: corners of the cells that have something
        corner_ids = -np.ones((gh + 1, gw + 1), np.int64)
        cells = np.argwhere(grown)
        for y, x in cells:
            corner_ids[y:y + 2, x:x + 2] = 0
        corners = np.argwhere(corner_ids == 0)
        corner_ids[corners[:, 0], corners[:, 1]] = np.arange(len(corners))
        pos = corners[:, ::-1].astype(np.float32) * cell
        cy_, cx_ = np.clip(corners[:, 0], 0, gh - 1), np.clip(corners[:, 1], 0, gw - 1)
        # a corner follows the fullest of its cells: the edge of the skirt goes with the skirt, not with the hand
        # that happens to be drawn next to it
        around = [(np.clip(cy_ - dy, 0, gh - 1), np.clip(cx_ - dx, 0, gw - 1)) for dy in (0, 1) for dx in (0, 1)]
        fullest = np.argmax(np.stack([cover[y, x] for y, x in around]), 0)
        d = np.stack([dists[:, y, x] for y, x in around])[fullest, :, np.arange(len(corners))]  # corners × bones
        strength = 1 / (d + 0.5) ** 6  # mostly the nearest bone: short bends, few stretched triangles
        best = np.argsort(-strength, 1)[:, :2]
        wts = np.take_along_axis(strength, best, 1)
        wts = wts / np.maximum(wts.sum(1, keepdims=True), 1e-12)
        # a bone that would carry a point only a little (the hand, for the edge of the skirt next to it, reached
        # round by the shoulder) does not carry it at all: the true bends (shoulder, hip) share far more evenly
        wts[:, 1] = np.where(wts[:, 1] < 0.25, 0.0, wts[:, 1])
        wts = wts / wts.sum(1, keepdims=True)
        # elbows and knees bend like skin: across the joint the two bones share the points over a third of the upper
        # bone's length, so a strong bend makes a round elbow instead of a fold
        for upper, lower in (("brat_drept", "antebrat_drept"), ("brat_stang", "antebrat_stang"),
                             ("coapsa_dreapta", "gamba_dreapta"), ("coapsa_stanga", "gamba_stanga")):
            if upper not in self.index:
                continue
            u, l = self.index[upper], self.index[lower]
            pair = ((best[:, 0] == u) & (best[:, 1] == l)) | ((best[:, 0] == l) & (best[:, 1] == u))
            if not pair.any():
                continue
            _, a, b, _ = bones_[u]
            root, axis = self.points[a], self.points[b] - self.points[a]
            t = ((pos[pair] - root) @ axis) / max(float(axis @ axis), 1e-6)
            k = np.clip((t - 0.82) / 0.36, 0, 1)
            share = k * k * (3 - 2 * k)  # the lower bone's part: 0 before the joint, 1 past it
            best[pair] = [u, l]
            wts[pair] = np.stack([1 - share, share], 1)
        self.vertices = np.concatenate([pos, pos / np.array([w, h], np.float32), best.astype(np.float32),
                                        wts.astype(np.float32)], 1).astype(np.float32)
        quads = np.stack([corner_ids[cells[:, 0], cells[:, 1]], corner_ids[cells[:, 0], cells[:, 1] + 1],
                          corner_ids[cells[:, 0] + 1, cells[:, 1] + 1], corner_ids[cells[:, 0] + 1, cells[:, 1]]], 1)
        triangles = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
        main = np.zeros((len(pos), len(bones_)))
        np.put_along_axis(main, best, wts, 1)
        groups = np.array([g for *_, g in bones_])
        share = np.stack([main[:, groups == g].sum(1) for g in (LEGS, UPPER, BODY, FORE)], 1)  # corners × layers
        tri_group = share[triangles].sum(1).argmax(1)
        # two parts meet for real only at the shoulders and the hips; anywhere else (a hand by the skirt, an elbow by
        # the waist) the touch is only in the drawing. Such a cell is drawn once with each part, and each copy keeps
        # only its own pixels, told apart by colour (skin by the arm's skin, pink by the skirt's pink)
        self.vertices = np.concatenate([self.vertices, np.full((len(self.vertices), 1), -1.0, np.float32)], 1)
        both = np.concatenate([cells, cells])
        centre = (both[:, ::-1] + 0.5) * cell
        limbs = [b for b in bones_ if b[0] not in ("corp", "cap")]
        firsts = [b for b in limbs if not b[0].startswith(("antebrat", "gamba"))]  # where a limb joins the body
        roots = np.array([self.points[a] for _, a, _, _ in firsts]) if firsts else np.zeros((1, 2)) - 1e6
        reach = 0.5 * np.mean([np.hypot(*(self.points[b] - self.points[a])) for _, a, b, _ in firsts]) if firsts else 0
        at_joint = np.min(np.hypot(*(centre[:, None, :] - roots[None]).transpose(2, 0, 1)), 1) < reach
        # the parts that move apart: the body (with the head), each arm, each leg, each ear, the tail
        limb = [name.replace("antebrat", "brat").replace("gamba", "coapsa") for name, *_ in bones_]
        part = np.array([0 if name in ("corp", "cap") else 1 + sorted(set(limb)).index(limb[n])
                         for n, (name, *_) in enumerate(bones_)])
        # a cell touches two parts when the solid cells around it (and itself) belong to more than one
        owner = np.argmin(np.where(np.isfinite(dists), dists, 1e9), 0)  # reliable on the solid cells
        cell_part = np.where(solid, part[owner], -1)
        low = np.where(cell_part >= 0, cell_part, 99)
        high = cell_part.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            low = np.minimum(low, np.roll(np.where(cell_part >= 0, cell_part, 99), (dy, dx), (0, 1)))
            high = np.maximum(high, np.roll(cell_part, (dy, dx), (0, 1)))
        touching = (high >= 0) & (low != high)
        touch = np.flatnonzero(touching[both[:, 0], both[:, 1]] & ~at_joint)
        self.owner = np.full((h, w), 255, np.uint8)  # 255: any bone may draw this pixel
        if len(touch):
            rgb = np.asarray(picture.convert("RGB"), np.float32)
            keep = np.ones(len(triangles), bool)
            extra, extra_tris, extra_groups = [], [], []
            for y, x in {tuple(c) for c in both[touch]}:
                # the bones of the solid cells around, and the colour of each one's pixels there
                around = {}
                for ny in range(max(0, y - 2), min(gh, y + 3)):
                    for nx in range(max(0, x - 2), min(gw, x + 3)):
                        if solid[ny, nx] and (ny, nx) != (y, x):
                            around.setdefault(int(owner[ny, nx]), []).append((ny, nx))
                keep[(both[:, 0] == y) & (both[:, 1] == x)] = False
                if not around:
                    continue
                colours = {b: np.mean([rgb[cy * cell:(cy + 1) * cell, cx * cell:(cx + 1) * cell].reshape(-1, 3).mean(0)
                                       for cy, cx in where], 0) for b, where in around.items()}
                bones = list(colours)
                block = rgb[y * cell:(y + 1) * cell, x * cell:(x + 1) * cell]
                seen = alpha[y * cell:(y + 1) * cell, x * cell:(x + 1) * cell][:block.shape[0], :block.shape[1]] / 255
                py, px = np.mgrid[y * cell:y * cell + block.shape[0], x * cell:x * cell + block.shape[1]] + 0.5
                cost = []
                for b in bones:  # how far (in cells) from that part's own cells, and how unlike its colour
                    centres = np.array(around[b]) * cell + cell / 2
                    far = np.min(np.hypot(py[..., None] - centres[:, 0], px[..., None] - centres[:, 1]), -1) / cell
                    unlike = np.abs(block - colours[b]).sum(-1) / 40
                    # a drawn pixel goes by its colour (skin with the arm, pink with the skirt); a faint edge pixel's
                    # colour says little, so it goes by where it is
                    cost.append(unlike * seen + far * (1.2 - seen))
                nearest = np.argmin(np.stack(cost), 0)
                self.owner[y * cell:(y + 1) * cell, x * cell:(x + 1) * cell] = np.array(bones, np.uint8)[nearest]
                for b in bones:  # one copy of the cell for each bone, keeping only its pixels
                    first = len(self.vertices) + len(extra)
                    for cy, cx in ((y, x), (y, x + 1), (y + 1, x + 1), (y + 1, x)):
                        extra.append([cx * cell, cy * cell, cx * cell / w, cy * cell / h, b, b, 1.0, 0.0, b])
                    extra_tris += [[first, first + 1, first + 2], [first, first + 2, first + 3]]
                    extra_groups += [bones_[b][3]] * 2
            triangles, tri_group = triangles[keep], tri_group[keep]
            if extra:
                self.vertices = np.concatenate([self.vertices, np.array(extra, np.float32)])
                triangles = np.concatenate([triangles, np.array(extra_tris)])
                tri_group = np.concatenate([tri_group, np.array(extra_groups)])
        self.triangles = {g: triangles[tri_group == g].astype(np.int32) for g in ORDER}
        self.backing = None
        if not self.human:
            self._backing(picture, owner, solid, grown, cover, cell)
        self._gpu = None
        self._texture_of = None

    def _backing(self, picture: Image.Image, owner: np.ndarray, solid: np.ndarray, grown: np.ndarray,
                 cover: np.ndarray, cell: int) -> None:
        """An animal's paws (and the roots of its little wings) are drawn over its tummy: there is no tummy under them
        in the picture. It is completed there once, from the colours around, and drawn first, behind everything: it
        only shows where a paw is no longer."""
        w, h = self.size
        layers = np.array([g for *_, g in self.bones])[owner]
        body = solid & (layers == BODY)
        closed = body.copy()
        for grow in (True, False):  # the body's outline as if the paws were not there
            for _ in range(4):
                shifted = [np.roll(closed, (dy, dx), (0, 1)) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                closed = np.logical_or.reduce([closed, *shifted]) if grow else np.logical_and.reduce([closed, *shifted])
        moving = np.isin(owner, [n for n, (name, *_) in enumerate(self.bones) if name.startswith(("laba", "coada"))])
        near = moving & grown
        for _ in range(2):  # and the tummy right round them, which a moving paw pulls a little
            near |= np.logical_or.reduce([np.roll(near, (dy, dx), (0, 1)) for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
        behind = closed & grown & near & (cover > 0)
        if not behind.any():
            return
        big = lambda m: np.repeat(np.repeat(m, cell, 0), cell, 1)[:h, :w]  # noqa: E731
        rgba = np.asarray(picture.convert("RGBA"), np.float32)
        have = big(body & ~near) & (rgba[..., 3] > 128)
        todo = big(behind)
        colour = rgba[..., :3] * have[..., None]
        for _ in range(8 * cell):  # each round fills one ring with the mean of the filled pixels next to it
            open_ = todo & ~have
            if not open_.any():
                break
            total, count = np.zeros_like(colour), np.zeros((h, w), np.float32)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                total += np.roll(colour * have[..., None], (dy, dx), (0, 1))
                count += np.roll(have, (dy, dx), (0, 1))
            new = open_ & (count > 0)
            colour[new] = total[new] / count[new][:, None]
            have |= new
        filled = todo & have
        backing = np.zeros((h, w, 4), np.uint8)
        backing[filled, :3] = colour[filled]
        backing[filled, 3] = 255
        self.backing = Image.fromarray(backing, "RGBA")
        cells = np.argwhere(behind)
        corp = self.index["corp"]
        extra = [[x * cell, y * cell, x * cell / w, y * cell / h, corp, corp, 1.0, 0.0, -1.0]
                 for cy, cx in cells for y, x in ((cy, cx), (cy, cx + 1), (cy + 1, cx + 1), (cy + 1, cx))]
        quads = len(self.vertices) + np.arange(4 * len(cells)).reshape(-1, 4)
        self.vertices = np.concatenate([self.vertices, np.array(extra, np.float32)])
        self.triangles[BACK] = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]]).astype(np.int32)

    @staticmethod
    def _spread(dists: np.ndarray, reach: np.ndarray) -> np.ndarray:
        """Give unreached cells the distances of the nearest reached cell (plus the way there)."""
        out = dists.copy()
        known = reach.copy()
        extra = 0.0
        while not known.all() and extra < 200:
            extra += 1
            grow = known.copy()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                shifted = np.roll(known, (dy, dx), (0, 1))
                values = np.roll(out, (dy, dx), (1, 2))
                take = shifted & ~grow
                out[:, take] = values[:, take] + 1
                grow |= take
            known = grow
        return out

    # --- posing ----------------------------------------------------------------------------------------------------

    def _side(self, point: str) -> int:
        """+1 for a limb on the left of the picture (the character's right): turning it outwards is +angle there."""
        return 1 if self.points[point][0] < self.points["gat"][0] else -1

    def solve(self, joints: dict[str, float]) -> list[np.ndarray]:
        """One 3×3 matrix per bone, from the picture's pixels to where they go."""
        P = self.points
        rad = math.radians
        if not self.human:
            return self._solve_animal(joints)
        mats = [np.eye(3) for _ in self.bones]

        def matrix(p0, v, q0, angle, length):
            rest = math.atan2(v[1], v[0])
            s = length / max(np.hypot(*v), 1e-6)
            r1 = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
            r0 = np.array([[math.cos(rest), math.sin(rest)], [-math.sin(rest), math.cos(rest)]])
            m = r1 @ np.diag([s, 1.0]) @ r0
            out = np.eye(3)
            out[:2, :2] = m
            out[:2, 2] = q0 - m @ p0
            return out

        def direction(angle):
            return np.array([math.cos(angle), math.sin(angle)])

        clap = min(1.0, max(0.0, joints.get("palme", 0.0)))
        chest = (P["umar_drept"] + P["umar_stang"]) / 2
        for side, hand in (("drept", "mana_dreapta"), ("stang", "mana_stanga")):
            s0, e0, w0 = P[f"umar_{side}"], P[f"cot_{side}"], P[hand]
            v1, v2 = e0 - s0, w0 - e0
            sign = self._side(f"umar_{side}")
            flex, bend = joints.get(f"umar_{side}", 0.0), joints.get(f"cot_{side}", 0.0)
            a1 = math.atan2(v1[1], v1[0]) + sign * rad(joints.get(f"umar_{side}_lat", 0.0))
            l1 = np.hypot(*v1) * math.cos(rad(min(89.0, abs(flex))))
            up = math.acos(max(-1.0, min(1.0, direction(a1) @ np.array([0.0, 1.0]))))  # 0: hanging, π/2: sideways
            a2 = a1 + (math.atan2(v2[1], v2[0]) - math.atan2(v1[1], v1[0])) + sign * rad(bend) * math.sin(up)
            l2 = np.hypot(*v2) * math.cos(rad(min(89.0, abs(flex + bend * math.cos(up)))))
            if clap > 0:
                # as a toddler claps: the upper arms stay down, a little in and forward; the forearms come forward
                # and the hands meet in front of the chest
                mix = lambda a, b: a + (math.remainder(b - a, 2 * math.pi)) * clap  # noqa: E731
                down = math.atan2(1.0, 0.0) + sign * rad(5)
                a1 = mix(a1, down)
                l1 += (np.hypot(*v1) * math.cos(rad(30)) - l1) * clap
                elbow = s0 + l1 * direction(a1)
                target = chest + np.array([-sign * 0.1 * np.hypot(*v2), 1.25 * np.hypot(*v1)])  # by the tummy
                way = target - elbow
                a2 = mix(a2, math.atan2(way[1], way[0]))
                l2 += (min(np.hypot(*way), np.hypot(*v2)) - l2) * clap
            elbow = s0 + l1 * direction(a1)
            mats[self.index[f"brat_{side}"]] = matrix(s0, v1, s0, a1, l1)
            mats[self.index[f"antebrat_{side}"]] = matrix(e0, v2, elbow, a2, l2)
        lows = []
        for side, knee_name, ankle in (("drept", "genunchi_drept", "glezna_dreapta"), ("stang", "genunchi_stang", "glezna_stanga")):
            h0, k0, f0 = P[f"sold_{side}"], P[knee_name], P[ankle]
            v1, v2 = k0 - h0, f0 - k0
            sign = self._side(f"sold_{side}")
            flex, bend = joints.get(f"sold_{side}", 0.0), joints.get(f"genunchi_{side}", 0.0)
            a1 = math.atan2(v1[1], v1[0]) + sign * rad(joints.get(f"sold_{side}_lat", 0.0))
            l1 = np.hypot(*v1) * math.cos(rad(min(89.0, abs(flex))))
            a2 = a1 + math.atan2(v2[1], v2[0]) - math.atan2(v1[1], v1[0])
            l2 = np.hypot(*v2) * math.cos(rad(min(89.0, abs(flex - bend))))
            knee = h0 + l1 * direction(a1)
            thigh = self.index[f"coapsa_{'dreapta' if side == 'drept' else 'stanga'}"]
            shin = self.index[f"gamba_{'dreapta' if side == 'drept' else 'stanga'}"]
            mats[thigh] = matrix(h0, v1, h0, a1, l1)
            mats[shin] = matrix(k0, v2, knee, a2, l2)
            lows.append((mats[shin] @ np.array([f0[0], self.size[1], 1.0]))[1])
        drop = self.size[1] - max(lows)  # the lower foot stays on the ground
        mats[self.index["cap"]] = _turn(P["gat"], max(-HEAD, min(HEAD, joints.get("cap", 0.0))))  # head on the neck
        for m in mats:
            m[1, 2] += drop
        return mats

    def _solve_animal(self, joints: dict[str, float]) -> list[np.ndarray]:
        """An animal like a toy: its head tilts on the body and takes the ears with it, the ears swing on the head,
        the tail wags, paws and little wings turn where they are fixed (out and up when raised, in for a clap), a
        foot lifts for a step and both bend a little for a landing. The lower foot stays on the ground."""
        P, i = self.points, self.index
        mats = [np.eye(3) for _ in self.bones]
        head = _turn(P["gat"], max(-HEAD, min(HEAD, joints.get("cap", 0.0))))
        mats[i["cap"]] = head
        for side in ("dreapta", "stanga"):
            if f"ureche_{side}" in i:
                out = -1 if P[f"ureche_{side}"][0] < P["gat"][0] else 1  # outwards: anticlockwise on the left
                mats[i[f"ureche_{side}"]] = head @ _turn(P[f"ureche_{side}"], out * joints.get("urechi", 0.0))
        if "coada" in i:
            mats[i["coada"]] = _turn(P["coada"], joints.get("coada", 0.0))
        clap = min(1.0, max(0.0, joints.get("palme", 0.0)))
        for side, tip, name in (("drept", "mana_dreapta", "laba_dreapta"), ("stang", "mana_stanga", "laba_stanga")):
            if name in i:
                out = self._side(f"umar_{side}")
                wing = abs(P[tip][0] - P["gat"][0]) > abs(P[f"umar_{side}"][0] - P["gat"][0])  # sticks out: a wing
                most, inwards = (70.0, 20.0) if wing else (25.0, 12.0)  # paws on the tummy only a little
                raise_ = min(most, joints.get(f"umar_{side}_lat", 0.0) * (1 if wing else 0.5)) - inwards * clap
                mats[i[name]] = _turn(P[f"umar_{side}"], out * raise_)
        lows = []
        for side, hip, ankle, name in (("drept", "sold_drept", "glezna_dreapta", "talpa_dreapta"),
                                       ("stang", "sold_stang", "glezna_stanga", "talpa_stanga")):
            if name in i:
                tall = np.hypot(*(P[ankle] - P[hip]))
                lift = tall * 0.9 * math.sin(math.radians(min(90.0, joints.get(f"genunchi_{side}", 0.0))))
                mats[i[name]] = _shift(0.0, -lift)
                lows.append(P[ankle][1] - lift)
        if lows:  # both feet bent (a landing): the body comes down onto them; one lifted foot just lifts
            rest = max(P[f"glezna_{s}"][1] for s in ("dreapta", "stanga") if f"talpa_{s}" in i)
            for m in mats:
                m[1, 2] += rest - max(lows)
        return mats

    # --- drawing ---------------------------------------------------------------------------------------------------

    def canvas(self, height: int) -> tuple[int, int, float]:
        """The drawing's size for a character `height` pixels tall (room for raised arms), and the scale."""
        w, h = self.size
        k = height / h
        return round(w * (1 + 2 * PAD[0]) * k), round(h * (1 + PAD[1]) * k), k

    def draw(self, picture: Image.Image, height: int, joints: dict[str, float]) -> Image.Image:
        """The character posed, `height` pixels tall, its feet on the bottom edge, centred: a wider and taller picture
        than the plain one, with room around it."""
        import moderngl
        ctx, program = _gl()
        if self._gpu is None or self._gpu[0] is not ctx:
            vbo = ctx.buffer(self.vertices.tobytes())
            vaos = {g: ctx.vertex_array(program, [(vbo, "2f 2f 2f 2f 1f", "pos", "uv", "ids", "wts", "only")],
                                        ctx.buffer(t.tobytes())) for g, t in self.triangles.items() if len(t)}
            self._gpu = (ctx, vaos)
        if self._texture_of is not picture:
            def upload(image):
                rgba = np.asarray(image.convert("RGBA"), np.float32)
                rgba[..., :3] *= rgba[..., 3:] / 255  # premultiplied: soft edges blend right
                texture = ctx.texture(image.size, 4, rgba.astype(np.uint8).tobytes())
                texture.build_mipmaps()
                texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                texture.anisotropy = 4.0
                return texture
            for old in getattr(self, "_textures", {}).values():
                old.release()
            self._textures = {"picture": upload(picture)}
            if self.backing is not None:
                self._textures["backing"] = upload(self.backing)
            self._texture_of = picture
            if getattr(self, "_owner", None) is None or self._owner_ctx is not ctx:
                self._owner = ctx.texture(self.size, 1, np.ascontiguousarray(self.owner).tobytes())
                self._owner.filter = (moderngl.NEAREST, moderngl.NEAREST)
                self._owner_ctx = ctx
        w, h = self.size
        width, tall, k = self.canvas(height)
        fbo = ctx.simple_framebuffer((width, tall), components=4)
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        program["tex"] = 0
        program["owner"] = 1
        self._owner.use(1)
        mats = self.solve(joints)
        mats = mats + [np.eye(3)] * (MAX_BONES - len(mats))
        program["bones"].write(np.stack([m.T for m in mats]).astype(np.float32).tobytes())
        program["canvas"] = (w * (1 + 2 * PAD[0]), h * (1 + PAD[1]))
        program["offset"] = (w * PAD[0], h * PAD[1])
        program["stretch"] = STRETCH
        for group in ORDER:
            if group in self._gpu[1]:
                self._textures["backing" if group == BACK else "picture"].use(0)
                self._gpu[1][group].render(moderngl.TRIANGLES)
        pixels = np.frombuffer(fbo.read(components=4), np.uint8).reshape(tall, width, 4).astype(np.float32)
        fbo.release()
        a = pixels[..., 3:]
        pixels[..., :3] = np.where(a > 0, pixels[..., :3] * 255 / np.maximum(a, 1), 0)
        return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGBA")
