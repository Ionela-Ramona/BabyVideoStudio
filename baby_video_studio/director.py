"""The director: from the synced lyrics to a full animated video, by itself.

1. `plan` groups the lyric lines into scenes of about 7–15 seconds (a new scene where a section begins), gives each
   section a decor (choruses keep theirs), casts the characters the lines sing about plus the singer and a friend,
   picks what each one does on every line (from the catalogue, or a gentle default that never repeats mechanically),
   adds interactions (comes close, follows, dances together, does the same thing a little later) and effects.
2. The user may change any scene; `regenerate` redoes one scene, `AnimScene.look` gives it another look.
3. `build` turns a scene into layers for `stage`: places, sizes, paths, so nobody touches anyone or leaves the frame.

The choices are saved in the project (`AnimScene`), so the same plan always draws the same video.
"""
import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import actions, effects, library, render, stage
from .ground import Ground, crop
from .motions import ACTIONS, Beat
from .models import AnimationSettings, AnimScene, LogoSettings, Role, Segment
from .planner import _plain
from .timeline import EXTRA, INSTRUMENTAL

SHORT, LONG = 7.0, 15.0  # seconds a scene lasts, about
MAX_CAST = 5
MAX_GROUND = {"16:9": 3, "9:16": 2}
MAX_EFFECTS = 3
BASE_HEIGHT = 0.42  # a character of size 1, of the frame's shorter side
WALK_SPEED = 0.45  # character heights a second: a calm walk
WALK_STRIDE = 0.12  # of the frame's width, how far "merge" goes from home and back
EFFECTS = {"Twinkles": effects.Twinkles, "Clouds": effects.Clouds, "Balloons": effects.Balloons,
           "Flowers": effects.Flowers, "Lights": effects.Lights, "Hearts": effects.Hearts, "Confetti": effects.Confetti}
EFFECT_NAMES = {"Twinkles": "Stele care sclipesc", "Clouds": "Nori", "Balloons": "Baloane", "Flowers": "Flori",
                "Lights": "Luminițe", "Hearts": "Inimioare", "Confetti": "Confetti"}
ACTION_NAMES = {"respira": "Stă liniștit", "leagana": "Se leagănă", "danseaza": "Dansează", "sare": "Sare",
                "merge": "Merge", "inclina": "Înclină capul", "salut": "Salută", "zboara": "Zboară", "pluteste": "Plutește",
                "palme": "Bate din palme", "legana_lin": "Leagănă lin (de culcare, max. 2°)"}
INTERACTION_NAMES = {"": "—", "apropie": "Se apropie de", "urmareste": "Urmărește", "danseaza_impreuna": "Dansează cu",
                     "imita": "Face la fel ca"}
CAMERAS = {"apropiere": (1.0, 1.05), "departare": (1.05, 1.0), "fix": (1.0, 1.0), "prim-plan": (1.0, 1.15),
           "aproape": (1.25, 1.3), "panoramare": (1.12, 1.12)}  # aproape: a close shot on the faces, from the start
PAN = 0.08  # "panoramare": of the frame's width, slowly, left to right
NIGHT_WORDS = ("noapt", "luna", "stele", "somn", "nani", "dorm", "vis", "culca", "pupic")
CHORUS = ("refren", "chorus")


@dataclass
class Line:
    start: float
    end: float
    text: str  # empty for music without singing
    section: str


def lines_of(rows: list[Segment], total: float) -> list[Line]:
    """The timeline's rows as lines with an end; long stretches of music are cut in pieces of about 10 seconds."""
    out = []
    for row, after in zip(rows, [*rows[1:], None]):
        end = after.start if after else total
        text = "" if row.text == INSTRUMENTAL else row.text.removeprefix(EXTRA)
        pieces = max(1, round((end - row.start) / 10)) if not text and end - row.start > LONG else 1
        for k in range(pieces):
            a = row.start + (end - row.start) * k / pieces
            out.append(Line(a, row.start + (end - row.start) * (k + 1) / pieces, text, row.section))
    return out


def _key(section: str) -> str:
    """Choruses share a decor; every other section has its own."""
    plain = _plain(section)
    chorus = any(c in plain for c in CHORUS) and not re.search(r"(pre|post)\W*(refren|chorus)", plain)
    return "refren" if chorus else plain


def group(lines: list[Line]) -> list[list[Line]]:
    groups: list[list[Line]] = []
    for line in lines:
        if groups:
            current = groups[-1]
            length = current[-1].end - current[0].start
            same = _key(line.section) == _key(current[-1].section)
            if length < SHORT * (0.6 if not same else 1) or (same and length + line.end - line.start <= LONG):
                current.append(line)
                continue
        groups.append([line])
    if len(groups) > 1 and groups[-1][-1].end - groups[-1][0].start < SHORT:
        groups[-2] += groups.pop()
    return groups


# --- choices -------------------------------------------------------------------------------------------------------

def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", _plain(text)) if len(w) >= 4}


def choose_decors(groups: list[list[Line]], pool: list[str]) -> dict[str, str]:
    """A decor for every section: the one whose description fits its lyrics best, night or day, then the least used."""
    pool = pool or ["🎨 Grădină însorită"]
    texts: dict[str, str] = {}
    for g in groups:
        for line in g:
            texts[_key(line.section)] = texts.get(_key(line.section), "") + " " + line.text
    used = {name: 0 for name in pool}
    chosen = {}
    for key, text in texts.items():
        words = _words(text)
        night = any(w.startswith(n) for w in words for n in NIGHT_WORDS)

        def score(name: str) -> tuple:
            item = library.decor(name)
            described = _words(item.description)
            overlap = sum(1 for w in words if any(d.startswith(w[:5]) for d in described))
            return overlap + 2 * (item.night == night), -used[name], -pool.index(name)
        best = max(pool, key=score)
        chosen[key] = best
        used[best] += 1
    return chosen


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha1(repr(parts).encode()).hexdigest()[:12], 16))


def _named(texts: list[str], characters: list[str]) -> list[str]:
    known = {c: list(library.character(c).names) for c in characters}
    named = []
    for text in texts:
        for c in actions.mentioned(text, known):
            if c not in named:
                named.append(c)
    return named


def _cast(lines: list[Line], before: AnimScene | None, settings: AnimationSettings, rng: random.Random) -> list[str]:
    """Those the lines sing about, the singer, the main character, then who was just sung about in the scene before
    (the story goes on), then one friend if the scene would otherwise be lonely."""
    named = _named([line.text for line in lines], settings.characters)
    main = settings.characters[0] if settings.characters else ""
    staying = []
    if before:
        cast_before = [r.character for r in before.roles]
        staying = [c for c in _named(before.lines, cast_before)] + [c for c in cast_before if c not in (main, settings.singer)]
        staying = list(dict.fromkeys(staying))[:2]
    wanted = list(dict.fromkeys(w for w in [*named, settings.singer, main, *staying] if w in settings.characters))
    others = [c for c in settings.characters if c not in wanted]
    rng.shuffle(others)
    wanted += others[:1] if len(wanted) < 2 else []
    cast, ground = [], 0
    for c in wanted:
        flying = library.character(c).flying
        if len(cast) < MAX_CAST and (flying or ground < MAX_GROUND[settings.aspect]):
            cast.append(c)
            ground += not flying
    return cast


def _fitting(action: str, flying: bool) -> str:
    if actions.fits(action, flying):
        return action
    return {"danseaza": "pluteste", "merge": "zboara", "leagana": "pluteste", "zboara": "pluteste",
            "pluteste": "leagana"}.get(action, "respira" if not flying else "pluteste")


def decide(lines: list[Line], before: AnimScene | None, settings: AnimationSettings, decor: str, seed: int,
           look: int = 0) -> AnimScene:
    """One scene: who is in it, what each one does on every line, with whom, which effects and which camera."""
    rng = _rng(seed, round(lines[0].start, 2))
    cast = _cast(lines, before, settings, rng)
    just_named = _named(before.lines, cast) if before else []
    main = next((c for c in settings.characters if c in cast), cast[0] if cast else "")
    roles = {c: Role(character=c) for c in cast}
    known = {c: list(library.character(c).names) for c in cast}
    last: dict[str, str] = {}
    for line in lines:
        found = actions.actions_in(line.text)
        together = actions.interactions_in(line.text)
        who = actions.mentioned(line.text, known)
        doers = cast if "imita" in together else (who or ([main] if found else []))
        for c in cast:
            info = library.character(c)
            if c in doers and found:
                action = _fitting(found[0], info.flying)
            else:
                choices = [a for a in actions.defaults(info.kind, info.flying) if a != last.get(c)] or ["respira"]
                action = rng.choice(choices)
            acts = roles[c].acts
            if acts and acts[-1][2] == action and abs(acts[-1][1] - line.start) < 0.05:
                acts[-1] = (acts[-1][0], line.end, action)
            else:
                acts.append((line.start, line.end, action))
            last[c] = action
        # who comes in, who goes to whom
        if actions.enters(line.text):
            for c in who:
                if not before or c not in [r.character for r in before.roles]:
                    roles[c].enters = line.start
        if "apropie" in together and len(cast) > 1:
            # "Unul vine lângă el": the one who just came in, or was just sung about, goes to the main character
            candidates = [*(c for c in who if c != main), *(c for c, r in roles.items() if r.enters is not None),
                          *reversed(just_named), *(c for c in cast if library.character(c).flying), *cast]
            mover = next(c for c in candidates if c != main and c in roles)
            partner = main if mover != main else next(c for c in cast if c != main)
            flying = library.character(mover).flying
            roles[mover].interaction, roles[mover].partner = ("urmareste" if flying else "apropie"), partner
            roles[mover].at = line.start
        if "imita" in together and main:
            for c in cast:
                if c != main and not roles[c].interaction:
                    roles[c].interaction, roles[c].partner, roles[c].at = "imita", main, line.start
        if "danseaza_impreuna" in together or ("danseaza" in found and len(who) >= 2):
            pair = [c for c in (who or cast) if not library.character(c).flying][:2]
            if len(pair) == 2:
                roles[pair[0]].interaction, roles[pair[0]].partner, roles[pair[0]].at = "danseaza_impreuna", pair[1], line.start
    # without words that ask for it, a friend still keeps someone company now and then
    flyers = [c for c in cast if library.character(c).flying and not roles[c].interaction]
    grounded = [c for c in cast if not library.character(c).flying]
    if flyers and grounded and rng.random() < 0.5:
        roles[flyers[0]].interaction = "urmareste"
        roles[flyers[0]].partner = main if main in grounded else grounded[0]
        roles[flyers[0]].at = lines[0].start + 1.0
    if len(grounded) >= 2 and _key(lines[0].section) == "refren" and not any(r.interaction for r in roles.values()) \
            and rng.random() < 0.5:
        roles[grounded[1]].interaction, roles[grounded[1]].partner = "danseaza_impreuna", grounded[0]
        roles[grounded[1]].at = lines[0].start + (lines[-1].end - lines[0].start) / 3

    item = library.decor(decor)
    lyric_effects = actions.effects_in(" ".join(line.text for line in lines))
    if item.file:  # a painted decor already has its clouds and flowers: drawn ones would sit on its trees
        base = ["Twinkles"] if item.night else []
    else:
        base = ["Twinkles", "Lights"] if item.night else ["Clouds", "Flowers"]
    chosen = list(dict.fromkeys([*lyric_effects, *base]))[:MAX_EFFECTS]
    camera = rng.choice(["apropiere", "apropiere", "departare", "fix"])
    if before and before.camera == camera != "fix":
        camera = "fix"
    return AnimScene(start=lines[0].start, end=lines[-1].end, section=lines[0].section,
                     lines=[line.text for line in lines if line.text], decor=decor, effects=chosen,
                     roles=list(roles.values()), camera=camera, seed=seed, look=look)


def plan(rows: list[Segment], total: float, settings: AnimationSettings, keep: list[AnimScene] | None = None) -> list[AnimScene]:
    """The whole video. Scenes the user changed (`edited`) are kept when they still cover the same time."""
    groups = group(lines_of(rows, total))
    standable = [d for d in settings.decors if not library.decor(d).no_ground]
    decors = choose_decors(groups, standable or settings.decors)
    kept = {(round(s.start, 2), round(s.end, 2)): s for s in keep or [] if s.edited}
    scenes: list[AnimScene] = []
    for n, lines in enumerate(groups):
        mine = kept.get((round(lines[0].start, 2), round(lines[-1].end, 2)))
        scenes.append(mine or decide(lines, scenes[-1] if scenes else None, settings, decors[_key(lines[0].section)], n))
    return scenes


def regenerate(rows: list[Segment], total: float, settings: AnimationSettings, index: int) -> AnimScene:
    """The same stretch of the song, chosen again: other friends, other moves, another camera. Same decor, same times."""
    old = settings.scenes[index]
    lines = [line for line in lines_of(rows, total) if old.start - 0.01 <= line.start < old.end - 0.01] or \
        [Line(old.start, old.end, " ".join(old.lines), old.section)]
    lines[-1].end = old.end
    before = settings.scenes[index - 1] if index else None
    fresh = decide(lines, before, settings, old.decor, old.seed + 1000, old.look)
    fresh.edited = True
    return fresh


# --- from choices to layers ----------------------------------------------------------------------------------------

SLOTS = {1: [0.5], 2: [0.42, 0.58], 3: [0.25, 0.5, 0.75]}  # close together, as people who sing together


def slots(count: int) -> list[float]:
    """Where `count` characters stand across the frame: the usual places, or evenly spread when there are more."""
    return SLOTS.get(count) or [(n + 0.5) / count for n in range(count)]


def footprint(name: str, character: library.Character, size: tuple[int, int]) -> tuple[float, float]:
    """How much of the frame a character on the ground takes (its visible part, at the near edge of the zone)."""
    look = library.look(name)
    tall = BASE_HEIGHT * character.size * min(size)
    v = look.visible
    return tall * look.aspect * (v[2] - v[0]) / size[0], tall * (v[3] - v[1]) / size[1]


def stand(floor: Ground, wished: dict[str, float], feet: dict[str, tuple[float, float]],
          taken: list | None = None) -> dict[str, tuple[float, float]]:
    """In the decor's safe zone: each one, in order, at the free place nearest to its slot (0..1 across the zone),
    off the objects, apart from the others (and from the places in `taken`), in perspective."""
    taken, out = list(taken or []), {}
    for name, slot in wished.items():
        out[name] = floor.spot(floor.left + (floor.right - floor.left) * slot, feet[name], taken)
        taken.append(floor.box(*out[name], feet[name]))
    return out


def walk_time(distance: float, height: float, size: tuple[int, int]) -> float:
    """Seconds to walk `distance` (of the frame's width) at a calm pace, soft start and stop included."""
    return abs(distance) * size[0] / (WALK_SPEED * height * min(size)) + stage.RAMP


def build(scene: AnimScene, settings: AnimationSettings, logo: LogoSettings | None = None,
          before: AnimScene | None = None) -> stage.Scene:
    """The scene as layers. With the scene `before` it, everyone who was already there starts where it was left and
    walks (or flies) gently to its new place, so a change of scene never shows two of the same character."""
    vertical = settings.aspect == "9:16"
    size = (1080, 1920) if vertical else (1920, 1080)
    rigid = settings.style == "fara_deformare"  # nobody walks: whole pictures gliding about would not look like it
    was = stage.where(build(before, settings, logo), size, before.end) if before and not rigid else {}
    rng = _rng("look", scene.look, round(scene.start, 2))
    ground_y = 0.74 if vertical else 0.88
    info = {r.character: library.character(r.character) for r in scene.roles}
    grounded = [r for r in scene.roles if not info[r.character].flying]
    flyers = [r for r in scene.roles if info[r.character].flying]
    if scene.look:
        rng.shuffle(grounded)
    if was:  # the same order as before: nobody walks through anybody
        grounded.sort(key=lambda r: was.get(r.character, (0.5, 0))[0])
    xs = {r.character: x + rng.uniform(-0.03, 0.03) for r, x in zip(grounded, slots(len(grounded)))}
    logo_right = bool(logo and logo.enabled and logo.position.endswith("right"))
    logo_left = bool(logo and logo.enabled and logo.position.endswith("left"))
    left, right = (0.2 if logo_left else 0.1), (0.75 if logo_right else 0.88)
    band = (0.32, 0.46) if vertical else (0.2, 0.36)
    for n, r in enumerate(flyers):
        xs[r.character] = left + (right - left) * (n + rng.uniform(0.2, 0.8)) / max(1, len(flyers))
    ys = {r.character: ground_y if not info[r.character].flying else rng.uniform(*band) for r in scene.roles}
    floor = library.ground(scene.decor, size)
    feet = {r.character: tuple(v * r.size for v in footprint(r.character, info[r.character], size)) for r in grounded}
    placed = {r.character: r.place for r in grounded if r.place}  # set by hand: kept as they are
    for c, (across, depth) in placed.items():
        xs[c] = floor.left + (floor.right - floor.left) * across if floor else across
        ys[c] = floor.near - (floor.near - floor.far) * depth if floor else ground_y
    if floor:
        free = {r.character: xs[r.character] for r in grounded if r.character not in placed}
        for c, (x, y) in stand(floor, free, feet, [floor.box(xs[c], ys[c], feet[c]) for c in placed]).items():
            xs[c], ys[c] = x, y

    actors = []
    for r in scene.roles:
        c = info[r.character]
        x = xs[r.character]
        acts = [(scene.start, scene.end, r.action)] if r.action else list(r.acts)
        partner_x = xs.get(r.partner, 0.5)
        # dancing together: from that moment both dance, leaning towards each other; imitating: the same, a bit later
        dance_from, dance_with = (r.at, r.partner) if r.interaction == "danseaza_impreuna" else (None, "")
        for other in scene.roles:
            if other.interaction == "danseaza_impreuna" and other.partner == r.character:
                dance_from, dance_with = other.at, other.character
        copy_from = r.at if r.interaction == "imita" else None
        mirror = 1 if x < xs.get(dance_with, partner_x) else -1
        made, moves, back = [], [], 1 if x < 0.5 else -1
        y, here = ys[r.character], x
        tall = BASE_HEIGHT * c.size * r.size * (floor.scale_at(y) if floor else 1.0)
        for a, b, action in acts:
            cuts = sorted({a, b, *(t for t in (dance_from, copy_from) if t is not None and a < t < b)})
            for a2, b2 in zip(cuts, cuts[1:]):
                params, doing = {"phase": rng.random()}, action
                if dance_from is not None and a2 >= dance_from - 1e-6:
                    doing = "danseaza"
                if copy_from is not None and a2 >= copy_from - 1e-6:
                    params["lag"] = 0.5
                if doing == "danseaza":
                    params["mirror"] = mirror
                made.append(stage.Act(doing, a2, b2, params))
                if rigid and not c.flying:
                    pass  # it stays where it stands; "merge" becomes a light rock on the spot
                elif doing == "merge" and r.interaction != "apropie" and not c.flying:
                    # a few calm steps away from home and, next time, back: at walking pace, then it stands
                    if floor:
                        to = floor.reach(here, y, feet[r.character], x + WALK_STRIDE * back - here)
                    else:
                        to = min(0.85, max(0.15, x + WALK_STRIDE * back))
                    room = (b2 - a2 - stage.RAMP) * WALK_SPEED * tall * min(size) / size[0]
                    to = here + max(-room, min(room, to - here))
                    if abs(to - here) > 0.01:
                        arrives = a2 + walk_time(to - here, tall, size)
                        moves.append(stage.Move(a2, arrives, x=to, walk=True))
                        made[-1] = stage.Act(doing, a2, min(b2, arrives + stage.RAMP), params)  # no steps on the spot
                        here = to
                    else:  # nowhere to go: a gentle sway instead of walking on the spot
                        made[-1] = stage.Act("leagana", a2, b2, params)
                    back = -back
                elif doing == "merge" and r.interaction != "apropie":
                    moves.append(stage.Move(a2, b2, x=min(0.85, max(0.15, x + 0.08 * back))))
                    back = -back
        follow = None
        if r.interaction in ("apropie", "danseaza_impreuna") and r.partner in xs and r.at is not None and \
                not (rigid and not c.flying):
            moves.append(stage.Move(r.at, min(scene.end, r.at + 1.8), near=r.partner, side=-1 if x < partner_x else 1,
                                    walk=not c.flying))
        if r.interaction == "urmareste" and r.partner in xs:
            outward = -1 if partner_x > 0.5 else 1  # on the side with more room; a second follower takes the other side
            others = [o for o in scene.roles if o.interaction == "urmareste" and o.partner == r.partner]
            side = outward if others.index(r) % 2 == 0 else -outward
            follow = stage.Follow(r.partner, r.at if r.at is not None else scene.start, scene.end + 2, side=side, lag=0.6)
        start_x, start_y = x, ys[r.character]
        if r.character in was and r.enters is None:
            start_x, start_y = was[r.character]
            moves.insert(0, stage.Move(scene.start, scene.start + 2.0, x=x, y=ys[r.character]))
        appears = r.enters if rigid and not c.flying else None  # it fades in where it stands
        if r.enters is not None and appears is None:  # from the nearer side; two coming in together: opposite sides
            entering = [o.character for o in scene.roles if o.enters is not None]
            side = (x >= 0.5) if entering.index(r.character) % 2 == 0 else (x < 0.5)
            sides = [1.12 if side else -0.12, -0.12 if side else 1.12]
            starts = [(s, start_y) for s in sides]
            if floor and not c.flying:
                # on a free way: at its own depth, or else from farther back, where the things in front hide only its
                # legs, coming forward on a slant; with no free way at all it is simply there
                depths = [y - (y - floor.far) * k / 6 for k in range(7)]
                starts = [(s, d) for d in depths for s in sides if floor.clear(s, x, d, feet[r.character], y)]
            if starts:
                start_x, start_y = starts[0]
                way = np.hypot((x - start_x) * size[0], (y - start_y) * size[1]) / size[0]
                seconds = 2.5 if c.flying else min(4.5, max(2.5, walk_time(way, tall, size)))
                moves.insert(0, stage.Move(r.enters, r.enters + seconds, x=x, y=y, edge=True, walk=not c.flying))
        moves.sort(key=lambda m: m.start)
        actors.append(stage.Actor(r.character, library.look(r.character), BASE_HEIGHT * c.size * r.size, start_x, start_y,
                                  c.flying, made, moves, follow, sings=r.character == settings.singer,
                                  blink_every=rng.uniform(3.8, 5.5), appears=appears, fixed=r.place is not None))
    return stage.Scene(scene.start, scene.end, library.backdrop(scene.decor), actors,
                       [EFFECTS[e] for e in scene.effects if e in EFFECTS], CAMERAS[scene.camera], seed=scene.look,
                       energy=settings.energy, ground=floor, rigid=rigid, focus=_focus(scene, xs, ys, info, floor, size),
                       title=scene.title, pan=PAN if scene.camera == "panoramare" else 0.0)


def _focus(scene: AnimScene, xs: dict, ys: dict, info: dict, floor, size: tuple[int, int]) -> tuple[float, float] | None:
    """Where a close-up looks: the chosen character's face and shoulders (for one on the ground), else the middle; a
    close shot ("aproape") a little higher, on the faces; a pan, on the whole character."""
    who = scene.focus if scene.focus in xs else next((r.character for r in scene.roles if r.character in xs), None)
    if scene.camera not in ("prim-plan", "aproape", "panoramare") or who is None:
        return None
    role = next(r for r in scene.roles if r.character == who)
    tall = BASE_HEIGHT * info[who].size * role.size * (floor.scale_at(ys[who]) if floor else 1.0) * min(size) / size[1]
    up = {"prim-plan": 0.6, "aproape": 0.7, "panoramare": 0.5}[scene.camera]
    return xs[who], ys[who] - (up * tall if not info[who].flying else 0.0)


def fingerprint(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:20]


def describe(scene: AnimScene) -> str:
    """One line for the scene list: who does what."""
    out = []
    for r in scene.roles:
        doing = ACTION_NAMES.get(r.action) if r.action else ", ".join(dict.fromkeys(ACTION_NAMES.get(a, a) for _, _, a in r.acts))
        extra = f" · {INTERACTION_NAMES[r.interaction].lower()} {r.partner}" if r.interaction else ""
        extra += " · intră în cadru" if r.enters is not None else ""
        out.append(f"{r.character}: {doing.lower()}{extra}")
    return "; ".join(out)


def changed_files(settings: AnimationSettings, scene: AnimScene) -> list:
    """What else a scene's picture depends on: its characters' files and its decor's file."""
    stamps = [library._changed(r.character) if r.character not in library.BUILT_IN else 0 for r in scene.roles]
    item = library.decor(scene.decor)
    if item.file and (library.DECORS / item.file).exists():
        stamps.append((library.DECORS / item.file).stat().st_mtime)
        stamps.append([item.zone, item.far_size, item.obstacles, item.depth, item.ground_depth])  # redrawn when they change
    return stamps



# --- drawing and exporting -----------------------------------------------------------------------------------------

def output_for(settings: AnimationSettings, preview: bool) -> stage.Output:
    if settings.aspect == "9:16":
        return stage.PREVIEW_9_16 if preview else stage.FULL_9_16
    return stage.PREVIEW_16_9 if preview else stage.FULL_16_9


def _logo(logo: LogoSettings | None, logo_file: Path | None, size: tuple[int, int]) -> tuple[stage.Logo | None, str]:
    if not (logo and logo.enabled and logo_file and logo_file.exists()):
        return None, ""
    prepared = render.prepare_logo(logo_file, logo, *size)
    with Image.open(prepared.path) as source:
        image = source.convert("RGBA")
    return stage.Logo(image, (prepared.x, prepared.y), logo), fingerprint(logo.model_dump(), prepared.path.name)


def keys(scenes: list[AnimScene], settings: AnimationSettings) -> list[str]:
    """What each scene's clip depends on: itself, its neighbours (they show during the crossfades), the settings and
    the files of its characters and decor."""
    dumps = [s.model_dump(exclude={"edited"}) for s in scenes]
    common = (settings.aspect, settings.singer, settings.energy, settings.style, len(scenes))
    return [fingerprint(common, dumps[i - 1] if i else None, dumps[i], dumps[i + 1] if i + 1 < len(dumps) else None,
                        changed_files(settings, scenes[i])) for i in range(len(scenes))]


def export(scenes: list[AnimScene], settings: AnimationSettings, audio: Path, output: Path, preview: bool,
           logo: LogoSettings | None = None, logo_file: Path | None = None, fade_out: bool = False,
           on_progress: stage.Progress = lambda f, m: None) -> dict:
    out = output_for(settings, preview)
    shown, logo_key = _logo(logo, logo_file, out.size)
    built = [build(s, settings, logo, scenes[i - 1] if i else None) for i, s in enumerate(scenes)]
    return stage.render_video(built, keys(scenes, settings), audio, output, out, shown, logo_key, fade_out, on_progress)


def preview_scene(scenes: list[AnimScene], index: int, settings: AnimationSettings, audio: Path, output: Path,
                  logo: LogoSettings | None = None, logo_file: Path | None = None,
                  on_progress: stage.Progress = lambda f, m: None) -> dict:
    """Only this scene, small and fast, with its song and the softened changes from and to its neighbours."""
    out = output_for(settings, True)
    shown, _ = _logo(logo, logo_file, out.size)
    near = [build(scenes[k], settings, logo, scenes[k - 1] if k else None)
            for k in (index - 1, index, index + 1) if 0 <= k < len(scenes)]
    scene = scenes[index]
    return stage.render(near, audio, output, scene.start, scene.end - scene.start, out, shown, on_progress=on_progress)


def zone_preview(decor: str, size: tuple[int, int], cast: list[str], zone: tuple[float, float, float, float],
                 far_size: float, obstacles: list[tuple[float, float, float, float]]) -> Image.Image:
    """The decor as the video shows it in this format, with the safe zone (blue), the objects (red, numbered), a
    grid every 10% of the picture, and the characters on the ground standing where a scene would put them (behind
    what is in front of them, when the decor's depth is known)."""
    picture_size = library.picture_size(decor)
    backdrop = library.backdrop(decor)(size, 0).convert("RGBA")
    frame = backdrop.copy()
    floor = Ground.from_picture(zone, far_size, obstacles, picture_size, size, *library.depth_of(decor))
    marks = Image.new("RGBA", size)
    pen = ImageDraw.Draw(marks)
    w, h = size
    shown = crop(picture_size, size)  # the grid counts in the picture's percents, as the sliders do
    for k in range(1, 10):
        x = (k / 10 * picture_size[0] - shown[0]) / (shown[2] - shown[0]) * w
        y = (k / 10 * picture_size[1] - shown[1]) / (shown[3] - shown[1]) * h
        pen.line([(x, 0), (x, h)], (255, 255, 255, 60))
        pen.line([(0, y), (w, y)], (255, 255, 255, 60))
        pen.text((x + 2, 2), f"{k * 10}", (255, 255, 255, 200))
        pen.text((2, y + 2), f"{k * 10}", (255, 255, 255, 200))
    pen.rectangle((floor.left * w, floor.far * h, floor.right * w, floor.near * h), (80, 170, 255, 70), (40, 140, 255, 255), 3)
    for n, o in enumerate(floor.obstacles, 1):
        pen.rectangle((o[0] * w, o[1] * h, o[2] * w, o[3] * h), (230, 60, 60, 80), (230, 40, 40, 255), 2)
        pen.text((o[0] * w + 4, o[1] * h + 2), str(n), (255, 255, 255, 255))
    grounded = [c for c in cast if not library.character(c).flying][:MAX_GROUND["16:9" if w > h else "9:16"]]
    feet = {c: footprint(c, library.character(c), size) for c in grounded}
    places = stand(floor, dict(zip(grounded, slots(len(grounded)))), feet)
    for c, (x, y) in sorted(places.items(), key=lambda item: item[1][1]):  # the nearer, the later
        tall = round(BASE_HEIGHT * library.character(c).size * min(size) * floor.scale_at(y))
        image = library.look(c).image(tall)
        at = (round(x * w - image.width / 2), round(y * h - image.height))
        frame.alpha_composite(image, at)
        floor.cover(frame, backdrop, (*at, at[0] + image.width, at[1] + image.height), y * h)
    frame.alpha_composite(marks)
    return frame.convert("RGB")


POSES = (("repaus", None, 0.0), ("pas", "merge", 0.25), ("palme", "palme", 0.0), ("în aer", "sare", 0.3),
         ("dans", "danseaza", 0.25), ("salut", "salut", 0.2))


def pose_sheet(name: str, height: int = 260) -> Image.Image:
    """The character in each of its motions at their fullest, side by side: to check its skeleton at a glance."""
    look = library.look(name)
    tiles = []
    for _, action, t in POSES:
        joints = ACTIONS[action](t, Beat(), {"skeleton": True}).joints if action else {}
        tiles.append(look.image(height, joints=joints))
    sheet = Image.new("RGBA", (sum(t.width for t in tiles), max(t.height for t in tiles)), (235, 240, 245, 255))
    x = 0
    for tile in tiles:
        sheet.alpha_composite(tile, (x, sheet.height - tile.height))
        x += tile.width
    return sheet.convert("RGB")


def thumbnail(scene: AnimScene, settings: AnimationSettings, width: int = 320, before: AnimScene | None = None) -> Image.Image:
    """The scene a third of the way in, small: for the list of scenes."""
    size = (width, round(width * 9 / 16)) if settings.aspect == "16:9" else (round(width * 9 / 16), width)
    staged = stage.Staged(build(scene, settings, before=before), size)
    t = scene.start + (scene.end - scene.start) / 3
    return staged.draw(t, stage.Beat(), (0.0, 0.0), {}).convert("RGB")


def problems(scene: AnimScene, settings: AnimationSettings, size: tuple[int, int], step: float = 0.2,
             before: AnimScene | None = None) -> dict:
    """Moments where two characters meet, one leaves the frame (coming in from the side does not count), or one stands
    on or behind an object of the decor (when the decor has a zone)."""
    staged = stage.Staged(build(scene, settings, before=before), size)
    floor = staged.scene.ground
    touching, outside, blocked = {}, {}, {}
    for t in np.arange(scene.start, scene.end, step):
        placed: list[stage.Placed] = []
        staged.draw(float(t), stage.Beat(), (0.0, 0.0), {}, placed)
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if a.box[0] < b.box[2] and b.box[0] < a.box[2] and a.box[1] < b.box[3] and b.box[1] < a.box[3]:
                    touching[f"{a.name} + {b.name}"] = touching.get(f"{a.name} + {b.name}", 0) + 1
            if not a.edge and (a.box[0] < 0 or a.box[1] < 0 or a.box[2] > size[0] or a.box[3] > size[1]):
                outside[a.name] = outside.get(a.name, 0) + 1
            box = (a.box[0] / size[0], a.box[1] / size[1], a.box[2] / size[0], a.box[3] / size[1])
            if floor and not staged.by_name[a.name].flying and floor.hits(box, a.feet / size[1]):
                blocked[a.name] = blocked.get(a.name, 0) + 1
    return {"atingeri": touching, "iesiri": outside, "obstacole": blocked}


# --- the user's changes to one scene -------------------------------------------------------------------------------

def swap_character(scene: AnimScene, old: str, new: str) -> None:
    """Another character takes this one's place and does the same things (flying ones fly instead of walking)."""
    flying = library.character(new).flying
    for role in scene.roles:
        if role.character == old:
            role.character = new
            role.acts = [(a, b, _fitting(action, flying)) for a, b, action in role.acts]
            role.action = _fitting(role.action, flying) if role.action else ""
            if flying and role.interaction in ("apropie", "danseaza_impreuna"):
                role.interaction = "urmareste"
        if role.partner == old:
            role.partner = new
    scene.edited = True


def set_action(scene: AnimScene, who: str, action: str) -> None:
    """One action for the whole scene, or "" to go back to what the lyrics ask, line by line."""
    for role in scene.roles:
        if role.character == who:
            role.action = _fitting(action, library.character(who).flying) if action else ""
    scene.edited = True


def add_character(scene: AnimScene, who: str) -> None:
    info = library.character(who)
    scene.roles.append(Role(character=who, action=actions.defaults(info.kind, info.flying)[0]))
    scene.edited = True


def remove_character(scene: AnimScene, who: str) -> None:
    scene.roles = [r for r in scene.roles if r.character != who]
    for role in scene.roles:
        if role.partner == who:
            role.interaction, role.partner, role.at = "", "", None
    scene.edited = True


def apply_template(scene: AnimScene, template: dict) -> None:
    """A saved scene's decor, effects, camera, characters and actions, on this scene's times."""
    scene.decor = template.get("decor") or scene.decor
    scene.effects = [e for e in template.get("effects", []) if e in EFFECTS]
    scene.camera = template.get("camera", scene.camera)
    known = set(library.characters())
    roles = []
    for item in template.get("roles", []):
        if item["character"] in known:
            info = library.character(item["character"])
            roles.append(Role(character=item["character"], action=item.get("action") or actions.defaults(info.kind, info.flying)[0],
                              interaction=item.get("interaction", ""), partner=item.get("partner", ""),
                              at=scene.start + 1.0 if item.get("interaction") else None))
    cast = {r.character for r in roles}
    for role in roles:
        if role.partner not in cast:
            role.interaction, role.partner, role.at = "", "", None
    scene.roles = roles or scene.roles
    scene.edited = True
