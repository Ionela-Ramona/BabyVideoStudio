"""Layered 2D animation: a backdrop, gentle effects and several characters moving at once, independently, on the
same timeline; a slow camera; the channel logo on top. Frames are drawn with Pillow and piped into FFmpeg.

A character is a `Look` (its picture, and optionally a face that talks and blinks, other pictures such as a waving
arm or closed eyes, and separate parts that move by themselves, like a butterfly's wings) plus what it does in a
scene: motions from `motions.ACTIONS` over time, a path (walk somewhere, go next to another character), and
interactions (follow another character). Sizes and places are fractions of the frame, so one scene fits 16:9 and 9:16;
`fit` shrinks the characters on the ground until none of them can touch another or leave the frame.
"""
import hashlib
import math
import os
import subprocess
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import rig as rigging
from . import talking
from .audio import decode
from .media import NO_WINDOW, RenderError, find_tool
from .models import LogoSettings
from .ground import Ground
from .motions import ACTIONS, RAMP, Beat, Pose, beat_of, combine, ease, glide, weight
from .projects import ROOT

FPS = 30
SPREAD = 0.12  # room kept around a ground character, of its height, for its sway, tilt and dance
CACHE = 120  # drawn pictures kept per character

Progress = Callable[[float, str], None]


# --- how a character looks -----------------------------------------------------------------------------------------

@dataclass
class Part:
    """A separate piece of a character that moves by itself (a wing, an arm), drawn over or under the picture."""
    image: Image.Image
    at: tuple[float, float]  # where its pivot sits on the character's picture
    pivot: tuple[float, float]  # the point it turns or folds around, in its own pixels
    motion: Callable[[float], tuple[float, float, float]]  # time -> (angle, sx, sy)
    front: bool = True


def transformed(image: Image.Image, pivot: tuple[float, float], angle: float = 0.0, sx: float = 1.0,
                sy: float = 1.0) -> tuple[Image.Image, tuple[float, float]]:
    """The image squashed and turned around `pivot`, and where that pivot ended up in the new image."""
    if abs(sx - 1) > 1e-3 or abs(sy - 1) > 1e-3:
        size = (max(1, round(image.width * sx)), max(1, round(image.height * sy)))
        pivot = (pivot[0] * size[0] / image.width, pivot[1] * size[1] / image.height)
        image = image.resize(size, Image.BILINEAR)
    if abs(angle) > 0.05:
        vx, vy = pivot[0] - image.width / 2, pivot[1] - image.height / 2
        a = math.radians(angle)
        image = image.rotate(angle, Image.BICUBIC, expand=True)
        pivot = (image.width / 2 + vx * math.cos(a) + vy * math.sin(a), image.height / 2 - vx * math.sin(a) + vy * math.cos(a))
    return image, pivot


class Look:
    """A character's pictures, ready to be drawn at any size with its mouth, eyes, other pictures and parts."""

    def __init__(self, picture: Image.Image, face: talking.Face | None = None, looks: dict[str, Image.Image] | None = None,
                 parts: list[Part] | None = None, mouths: dict[str, Image.Image] | None = None,
                 rig: "rigging.Rig | None" = None):
        self.picture = picture.convert("RGBA")
        self.face, self.mouths = face, mouths or {}
        self.looks = {k: v.convert("RGBA").resize(self.picture.size, Image.LANCZOS) for k, v in (looks or {}).items()}
        self.parts = parts or []
        self.rig = rig  # arms and legs that bend: its pictures are wider and taller, feet on the bottom edge
        self._puppets: dict[str | None, talking.Puppet] = {}
        self._drawn: OrderedDict = OrderedDict()

    @classmethod
    def from_profile(cls, name: str, looks: dict[str, Image.Image] | None = None) -> "Look":
        """A character saved in the "Personaj vorbitor" mode: its picture, its face and its mouth variants."""
        profile = talking.load_profile(name)
        folder = talking.profile_dir(name)
        with Image.open(folder / profile.image) as source:
            picture = ImageOps.exif_transpose(source).convert("RGBA")
        mouths = {}
        for shape, path in talking.variant_files(profile).items():
            with Image.open(path) as source:
                mouths[shape] = ImageOps.exif_transpose(source).convert("RGBA")
        picture = solid(picture)
        box = picture.getbbox() or (0, 0, *picture.size)  # no empty margins: its feet are its lowest pixels
        face = profile.face
        if face:
            shift = lambda b: (b[0] - box[0], b[1] - box[1], b[2] - box[0], b[3] - box[1])  # noqa: E731
            face = talking.Face(shift(face.mouth), [shift(e) for e in face.eyes])
        crop = lambda image: solid(image.resize(picture.size, Image.LANCZOS)).crop(box)  # noqa: E731
        body = picture.crop(box)
        skeleton = None
        if rigging.usable(profile.rig) and rigging.available():
            w, h = picture.size
            points = {k: ((x * w - box[0]) / body.width, (y * h - box[1]) / body.height) for k, (x, y) in profile.rig.items()}
            skeleton = rigging.Rig(body, points)
        return cls(body, face, {k: crop(v) for k, v in (looks or {}).items()}, None,
                   {k: crop(v) for k, v in mouths.items()}, skeleton)

    @property
    def aspect(self) -> float:
        return self.picture.width / self.picture.height

    @property
    def visible(self) -> tuple[float, float, float, float]:
        """Where the picture really has something, as fractions of its width and height (for keeping apart)."""
        if not hasattr(self, "_visible"):
            drawn = self.picture.resize((max(1, round(200 * self.aspect)), 200)) if self.rig else self.image(200)
            box = drawn.getchannel("A").point(lambda v: 255 if v > 96 else 0).getbbox() or (0, 0, *drawn.size)
            self._visible = (box[0] / drawn.width, box[1] / drawn.height, box[2] / drawn.width, box[3] / drawn.height)
        return self._visible

    def _puppet(self, look: str | None) -> talking.Puppet:
        if look not in self._puppets:  # a waving picture keeps its face where it was: same boxes, same mouth
            self._puppets[look] = talking.Puppet(self.looks.get(look, self.picture), self.face, self.mouths)
        return self._puppets[look]

    def image(self, height: int, opening: float = 0.0, roundness: float = 0.0, lids: float = 0.0,
              look: str | None = None, t: float = 0.0, joints: dict[str, float] | None = None, blend: float = 1.0,
              rigid: bool = False, under: str | None = None, under_blend: float = 1.0) -> Image.Image:
        """The character `height` pixels tall. With a skeleton (unless `rigid`), posed by `joints` (see
        motions.JOINTS) on a wider and taller picture, feet on its bottom edge, centred; without one, the plain
        picture. `look` is another picture of it (a frame), shown `blend` over the plain one."""
        if look not in self.looks:
            closed = lids > 0.5 and "ochi_inchisi" in self.looks and (rigid or not self.face)
            look, blend = ("ochi_inchisi" if closed else None), 1.0
        if rigid:
            lids = 0.0  # without deformation the eyes close only in a frame, never with drawn eyelids
        shown = round(min(1.0, max(0.0, blend)) * 5) / 5 if look else 1.0  # a few steps: the pictures are kept
        if look and shown == 0:
            look, shown = None, 1.0
        skeleton = self.rig if not rigid else None
        moves = tuple((round(a), round(sx, 2), round(sy, 2)) for a, sx, sy in (p.motion(t) for p in self.parts))
        bends = tuple(sorted((k, round(v, 1)) for k, v in (joints or {}).items() if abs(v) > 0.05)) if skeleton else ()
        below = round(min(1.0, max(0.0, under_blend)) * 5) / 5 if under in self.looks else 0.0
        key = (height, round(opening * 20), round(roundness * 4), round(lids * 10) if self.face else 0, look, moves, bends,
               shown, rigid, under if below else None, below)
        if key in self._drawn:
            self._drawn.move_to_end(key)
            return self._drawn[key]
        if self.face and (opening > 0 or lids > 0):
            picture = self._puppet(look).frame(key[1] / 20, key[2] / 4, key[3] / 10)
            if look and shown < 1:
                picture = Image.blend(self._puppet(None).frame(key[1] / 20, key[2] / 4, key[3] / 10), picture, shown)
        else:
            base = Image.blend(self.picture, self.looks[under], below) if below else self.picture  # e.g. hands apart
            picture = self.looks.get(look, base)
            if look and shown < 1:
                picture = Image.blend(base, picture, shown)
        if self.parts:
            canvas = Image.new("RGBA", picture.size)
            for front in (False, True):
                if front:
                    canvas.alpha_composite(picture)
                for part, (angle, sx, sy) in zip(self.parts, moves):
                    if part.front == front:
                        image, pivot = transformed(part.image, part.pivot, angle, sx, sy)
                        canvas.alpha_composite(image, (round(part.at[0] - pivot[0]), round(part.at[1] - pivot[1])))
            picture = canvas
        if skeleton:
            drawn = skeleton.draw(picture, height, dict(bends))
        else:
            drawn = picture.resize((max(1, round(height * self.aspect)), height), Image.LANCZOS)
        self._drawn[key] = drawn
        if len(self._drawn) > (8 if skeleton else CACHE):  # a posed character is rarely the same twice, and big
            self._drawn.popitem(last=False)
        return drawn


# --- what happens in a scene ---------------------------------------------------------------------------------------

@dataclass
class Act:
    action: str  # a key of motions.ACTIONS
    start: float
    end: float
    params: dict = field(default_factory=dict)


@dataclass
class Move:
    """Go somewhere between `start` and `end`: to `x` (of the frame's width), or next to another character."""
    start: float
    end: float
    x: float | None = None
    y: float | None = None
    near: str | None = None
    side: int = -1  # -1: stop on the other's left, 1: on its right
    gap: float = 0.02  # of the frame's width, between the two
    edge: bool = False  # coming in or going out of the frame: it may be partly outside meanwhile
    walk: bool = False  # at an even pace, as one walks (otherwise speeding up and slowing down all the way)


@dataclass
class Follow:
    """Stay near another character, a little later than it moves: above its shoulder, on `side`."""
    leader: str
    start: float
    end: float
    side: int = -1
    lag: float = 0.5


@dataclass
class Actor:
    name: str
    look: Look
    height: float  # of the frame's shorter side
    x: float  # of the frame's width, where it stands (its middle)
    y: float  # of the frame's height: its feet, or its middle for those who fly
    flying: bool = False
    acts: list[Act] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    follow: Follow | None = None
    sings: bool = False
    blink_every: float | None = 4.5
    appears: float | None = None  # comes into the scene here by fading in where it stands (instead of walking in)
    fixed: bool = False  # placed by hand: never shrunk to make room


class Effect:
    """Something in the decor that moves by itself; drawn behind the characters, or in front when `front`."""
    front = False

    def draw(self, frame: Image.Image, t: float) -> None:
        raise NotImplementedError


def solid(image: Image.Image) -> Image.Image:
    """The picture without the faint haze and the stray specks a background remover leaves behind. They cannot be
    seen, but they count as the picture: its feet would float above the floor and it would seem wider than it is."""
    alpha = image.getchannel("A").point(lambda v: 0 if v <= 12 else v)
    core = alpha.point(lambda v: 255 if v > 64 else 0).filter(ImageFilter.MinFilter(5))  # specks under 5 px go
    near = core.reduce(4).point(lambda v: 255 if v else 0).filter(ImageFilter.MaxFilter(5)).resize(alpha.size, Image.NEAREST)
    out = image.copy()
    out.putalpha(ImageChops.multiply(alpha, near))  # soft edges within ~8 px of the body stay as they are
    return out


@dataclass
class Scene:
    start: float
    end: float
    backdrop: Callable[[tuple[int, int], int], Image.Image]  # (size, seed) -> picture
    actors: list[Actor]
    effects: list[Callable[[tuple[int, int], int], Effect]] = field(default_factory=list)  # (size, seed) -> effect
    zoom: tuple[float, float] = (1.0, 1.05)  # the camera comes slowly closer
    seed: int = 0  # another seed: another look for the same scene, same timing ("🎲 Surprinde-mă")
    energy: float = 1.0  # how big the motions are: 0.5 calmer, 1.5 livelier
    ground: Ground | None = None  # the decor's safe zone, perspective and objects; None: everyone on one fixed line
    rigid: bool = False  # without deformation: pictures only turn a little and move a little; gestures from frames
    focus: tuple[float, float] | None = None  # where the camera comes close (frame fractions); None: the middle
    title: str = ""  # words at the top of the screen, coming softly after the scene's first second
    pan: float = 0.0  # how far the camera glides from left to right during the scene, of the frame's width


TITLE_FONT = Path(r"C:\Windows\Fonts\seguibl.ttf")  # Segoe UI Black: round, bold, with ă â î ș ț


def title_card(text: str, size: tuple[int, int]) -> Image.Image:
    """The words in pink with a white rim and a soft shadow, as wide as fits in 80% of the frame."""
    px = round(min(size) * 0.085)
    while True:
        font = ImageFont.truetype(str(TITLE_FONT), px) if TITLE_FONT.exists() else ImageFont.load_default(px)
        left, top, right, bottom = font.getbbox(text, stroke_width=px // 9)
        if right - left <= size[0] * 0.8 or px < 20:
            break
        px = round(px * 0.9)
    pad = px // 3
    card = Image.new("RGBA", (right - left + 2 * pad, bottom - top + 2 * pad))
    shadow = Image.new("RGBA", card.size)
    ImageDraw.Draw(shadow).text((pad - left, pad - top + px // 14), text, font=font, fill=(120, 40, 90, 110),
                                stroke_width=px // 9, stroke_fill=(120, 40, 90, 110))
    card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(px / 16)))
    ImageDraw.Draw(card).text((pad - left, pad - top), text, font=font, fill=(232, 72, 140, 255), stroke_width=px // 9,
                              stroke_fill=(255, 255, 255, 255))
    return card


@dataclass
class Placed:
    """One character on one frame: where it was drawn, for checking overlaps."""
    name: str
    box: tuple[int, int, int, int]
    edge: bool
    feet: float = 0.0  # where it stands (pixels from the top), even while in the air


class Staged:
    """A scene ready to draw at one frame size: sizes fitted, decor and effects made."""

    def __init__(self, scene: Scene, size: tuple[int, int]):
        self.scene, self.size = scene, size
        self.backdrop = scene.backdrop(size, scene.seed).convert("RGBA")
        self.effects = [make(size, scene.seed) for make in scene.effects]
        self.by_name = {a.name: a for a in scene.actors}
        self.scale = fit(scene, size)
        self.ground = scene.ground.at(size) if scene.ground else None  # its depth at this drawing's size
        self._shadows: dict[int, Image.Image] = {}
        self._nudges: dict[int, dict[str, tuple[float, float]]] = {}

    def height(self, actor: Actor, y: float | None = None) -> int:
        """In pixels; a character on the ground standing at `y` (pixels) is smaller the farther back it stands."""
        if actor.flying:
            return round(actor.height * min(self.size))
        far = self.scene.ground.scale_at(y / self.size[1]) if self.scene.ground and y is not None else 1.0
        return round(actor.height * min(self.size) * self.scale * far)

    def width(self, actor: Actor, y: float | None = None) -> float:
        return self.height(actor, y) * actor.look.aspect

    def _beside(self, actor: Actor, x: float, other_x: float, y: float, side: int, gap: float, other: Actor) -> float:
        """Where to stop next to another character: on `side`, or on the other side if an object is in the way there,
        or nowhere (stays at x) if both are taken."""
        width, height = self.size
        room = (self.width(actor, y) + self.width(other, y)) / 2 + SPREAD * (self.height(actor, y) + self.height(other, y))
        ground = self.scene.ground
        for s in (side, -side):
            tx = other_x + s * (room + gap * width)
            if ground is None:
                return tx
            v = actor.look.visible
            w, h = self.width(actor, y), self.height(actor, y)
            box = ((tx - w / 2 + v[0] * w) / width, (y - h + v[1] * h) / height, (tx - w / 2 + v[2] * w) / width, y / height)
            if ground.free(box):
                return tx
        return x

    def path(self, actor: Actor, t: float, depth: int = 0) -> tuple[float, float, bool]:
        """Where the character stands at `t` (pixels), before its motions; and whether it is coming in or out."""
        width, height = self.size
        x, y = actor.x * width, actor.y * height
        edge = any(m.edge and t < m.end for m in actor.moves)  # waiting outside, or coming in
        for move in actor.moves:
            if t <= move.start:
                break
            tx, ty = x if move.x is None else move.x * width, y if move.y is None else move.y * height
            if move.near and depth < 3:
                other = self.by_name[move.near]
                ox, oy, _ = self.path(other, move.end, depth + 1)
                if self.scene.ground and not actor.flying:
                    ty = oy  # side by side, at the same depth
                tx = self._beside(actor, x, ox, ty, move.side, move.gap, other)
            share = (t - move.start) / max(move.end - move.start, 1e-6)
            u = glide(share, RAMP / max(move.end - move.start, 1e-6)) if move.walk else ease(share)
            x, y = x + (tx - x) * u, y + (ty - y) * u
        follow = actor.follow
        if follow and depth < 3 and (w := weight(t, follow.start, follow.end + 1.5)) > 0:
            leader = self.by_name[follow.leader]
            lx, ly, _ = self.path(leader, max(follow.start, t - follow.lag), depth + 1)
            lw, lh = self.width(leader, ly), self.height(leader, ly)
            above = lh + 0.3 * lh + self.height(actor) / 2
            fx, fy = lx + follow.side * 0.45 * lw, ly - above
            w = ease(min(1.0, (t - follow.start) / 1.5)) if t < follow.end else w  # flies in slowly, stays until the end
            x, y = x + (fx - x) * w, y + (fy - y) * w
        return x, y, edge

    def shadow(self, width: int) -> Image.Image:
        if width not in self._shadows:
            sheet = Image.new("L", (width, max(4, width // 6)), 0)
            ImageDraw.Draw(sheet).ellipse((width * 0.12, sheet.height * 0.2, width * 0.88, sheet.height * 0.8), fill=80)
            self._shadows[width] = sheet.filter(ImageFilter.GaussianBlur(width / 30))
        return self._shadows[width]

    def pose(self, actor: Actor, t: float, beat: Beat) -> Pose:
        rigid = self.scene.rigid
        skeleton = {"skeleton": bool(actor.look.rig) and not rigid, "rigid": rigid,  # what the motions may use
                    "frames": tuple(actor.look.looks)}
        poses = [(weight(t, a.start, a.end), ACTIONS[a.action](t, beat, {**a.params, **skeleton})) for a in actor.acts]
        if not actor.flying:
            # going somewhere on foot is walking: no hopping or dancing on the way, and the steps begin just before
            # it sets off and end just after it stops
            going = max((weight(t, m.start - RAMP, m.end + RAMP) for m in actor.moves), default=0.0)
            if going > 0:
                walking = max([going, *(w for (w, _), a in zip(poses, actor.acts) if a.action == "merge")])
                poses = [(w * (1 - going), p) for (w, p), a in zip(poses, actor.acts) if a.action != "merge"]
                poses.append((walking, ACTIONS["merge"](t, beat, skeleton)))
        pose = combine([(1.0, ACTIONS["respira"](t, beat, {"phase": len(actor.name) / 7})), *poses])
        if actor.appears is not None:
            pose.alpha *= ease((t - actor.appears) / 0.8)
        if rigid:  # the picture as it is: no squash, no hop off the floor, a small sway and a small step at most
            pose.sx = pose.sy = 1.0
            pose.joints = {}
            if not actor.flying:
                pose.dy = 0.0
                pose.dx = max(-0.02, min(0.02, pose.dx))
                pose.angle = max(-3.0, min(3.0, pose.angle))
        if self.scene.energy != 1:
            e = self.scene.energy
            pose.dx, pose.dy, pose.angle = pose.dx * e, pose.dy * e, pose.angle * e
            pose.sx, pose.sy = 1 + (pose.sx - 1) * e, 1 + (pose.sy - 1) * e
            pose.joints = {k: v * e for k, v in pose.joints.items()}
        return pose

    def spot(self, actor: Actor, t: float, pose: Pose) -> tuple[float, float, bool]:
        """Where the character's anchor (feet, or middle for flyers) is drawn, motions included."""
        x, y, edge = self.path(actor, t)
        height = self.height(actor, y)
        return x + pose.dx * height, y + pose.dy * height, edge

    def box(self, actor: Actor, x: float, y: float, pose: Pose, feet: float | None = None) -> tuple[float, float, float, float]:
        h = self.height(actor, feet) * pose.sy
        w = self.height(actor, feet) * actor.look.aspect * pose.sx
        left, top = x - w / 2, y - (h / 2 if actor.flying else h)
        v = actor.look.visible
        return left + v[0] * w, top + v[1] * h, left + v[2] * w, top + v[3] * h

    def nudges(self, t: float, beat: Beat) -> dict[str, tuple[float, float]]:
        """How far each flyer is gently moved aside so it never sits on another character. Worked out frame by frame
        from just before the scene, the same way every time, so a scene looks the same alone or in the whole video."""
        flyers = sorted((a for a in self.scene.actors if a.flying), key=lambda a: a.name)
        if not flyers:
            return {}
        first = round((self.scene.start - CROSSFADE) * FPS)
        n = max(first, round(t * FPS))
        if n in self._nudges:
            return self._nudges[n]
        k = max([f for f in self._nudges if f < n], default=first - 1)
        state = dict(self._nudges.get(k, {a.name: (0.0, 0.0) for a in flyers}))
        gap = 0.02 * self.size[0]
        for frame in range(k + 1, n + 1):
            moment = frame / FPS
            boxes = {}
            for actor in self.scene.actors:
                pose = self.pose(actor, moment, beat)
                x, y, _ = self.spot(actor, moment, pose)
                ox, oy = state.get(actor.name, (0.0, 0.0))
                boxes[actor.name] = self.box(actor, x + ox, y + oy, pose, self.path(actor, moment)[1])
            for actor in flyers:
                ox, oy = state[actor.name]
                ox, oy = ox * 0.985, oy * 0.985  # drifts back home when there is room again
                a = boxes[actor.name]
                for other, b in boxes.items():
                    if other == actor.name:
                        continue
                    wide = min(a[2], b[2]) - max(a[0], b[0]) + gap
                    tall = min(a[3], b[3]) - max(a[1], b[1]) + gap
                    if wide > 0 and tall > 0:
                        grounded = not self.by_name[other].flying
                        if tall < wide or grounded:  # over a character on the ground: always upwards
                            above = grounded or (a[1] + a[3], actor.name) < (b[1] + b[3], other)
                            oy -= 0.4 * tall * (1 if above else -1)
                        else:
                            right = (a[0] + a[2], actor.name) > (b[0] + b[2], other)  # a tie: by name, never both
                            ox += 0.4 * wide * (1 if right else -1)
                state[actor.name] = (ox, oy)
            self._nudges[frame] = dict(state)
        for old in [f for f in self._nudges if f < n - 2]:
            del self._nudges[old]
        return self._nudges[n]

    def draw(self, t: float, beat: Beat, voice: tuple[float, float], lids: dict[str, float],
             placed: list[Placed] | None = None) -> Image.Image:
        frame = self.backdrop.copy()
        for effect in self.effects:
            if not effect.front:
                effect.draw(frame, t)
        feet = {a.name: self.path(a, t)[1] for a in self.scene.actors}
        order = sorted(self.scene.actors, key=lambda a: (a.flying, feet[a.name]))  # the nearer, the later
        nudges = self.nudges(t, beat)
        for actor in order:
            pose = self.pose(actor, t, beat)
            height = self.height(actor, feet[actor.name])
            opening, roundness = voice if actor.sings else (0.0, 0.0)
            image = actor.look.image(height, opening, roundness, lids.get(actor.name, 0.0), pose.look, t, pose.joints,
                                     pose.blend, self.scene.rigid, pose.under, pose.under_blend)
            pivot = (image.width / 2, image.height / 2 if actor.flying else image.height)
            image, pivot = transformed(image, pivot, pose.angle, pose.sx, pose.sy)
            x, y, edge = self.spot(actor, t, pose)
            ox, oy = nudges.get(actor.name, (0.0, 0.0))
            x, y = x + ox, y + oy
            left, top = x - pivot[0], y - pivot[1]
            seen = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)  # a posed picture has room around
            if not edge:  # never outside the frame, unless walking in or out
                left = min(max(left, -seen[0]), self.size[0] - seen[2])
                top = min(max(top, -seen[1]), self.size[1] - seen[3])
            if not actor.flying:
                lift = max(0.0, -pose.dy) / 0.16  # the shadow stays on the ground, lighter as it hops
                shadow = self.shadow(round(height * actor.look.aspect * 0.9 * pose.sx))
                strength = shadow.point(lambda v, k=1 - 0.6 * min(lift, 1): round(v * k))
                ground = feet[actor.name]
                frame.paste((40, 60, 30), (round(x - shadow.width / 2), round(ground - shadow.height / 2)), strength)
            if pose.alpha < 1:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda v: round(v * pose.alpha)))
            frame.alpha_composite(image, (round(left), round(top)))
            if self.ground and not actor.flying:  # flowers, stones… nearer than it are drawn again over it
                self.ground.cover(frame, self.backdrop, (round(left), round(top), round(left) + image.width,
                                                               round(top) + image.height), feet[actor.name])
            if placed is not None and (box := image.getchannel("A").point(lambda v: 255 if v > 96 else 0).getbbox()):
                placed.append(Placed(actor.name, (round(left) + box[0], round(top) + box[1], round(left) + box[2],
                                                  round(top) + box[3]), edge, feet[actor.name]))
        for effect in self.effects:
            if effect.front:
                effect.draw(frame, t)
        progress = ease((t - self.scene.start) / max(self.scene.end - self.scene.start, 1e-6))
        zoom = self.scene.zoom[0] + (self.scene.zoom[1] - self.scene.zoom[0]) * progress
        if zoom > 1.0005:
            width, height = self.size
            w, h = width / zoom, height / zoom
            left, top = (width - w) / 2, (height - h) * 0.6  # a little lower than the middle: the characters
            if self.scene.focus:  # on one character, as far as the decor allows
                left = min(max(self.scene.focus[0] * width - w / 2, 0), width - w)
                top = min(max(self.scene.focus[1] * height - h / 2, 0), height - h)
            if self.scene.pan:  # a slow glide from left to right, as far as the decor allows
                left = min(max(left + self.scene.pan * width * (progress - 0.5), 0), width - w)
            frame = frame.resize(self.size, Image.BILINEAR, box=(left, top, left + w, top + h))
        if self.scene.title:  # on the screen, not in the decor: the camera does not move it
            if not hasattr(self, "_title"):
                self._title = title_card(self.scene.title, self.size)
            shown = ease((t - self.scene.start - 1.0) / 1.5)
            if shown > 0:
                card = self._title if shown >= 1 else self._title.copy()
                if shown < 1:
                    card.putalpha(card.getchannel("A").point(lambda v: round(v * shown)))
                top = 0.06 if self.size[0] >= self.size[1] else 0.13  # 9:16: under the logo and the Shorts' top bar
                frame.alpha_composite(card, ((self.size[0] - card.width) // 2, round(self.size[1] * top)))
        return frame


def where(scene: Scene, size: tuple[int, int], t: float) -> dict[str, tuple[float, float]]:
    """Where everyone stands at `t`, as fractions of the frame (feet, or middle for flyers), without drawing anything."""
    probe = Staged.__new__(Staged)
    probe.scene, probe.size, probe.scale = scene, size, fit(scene, size)
    probe.by_name = {a.name: a for a in scene.actors}
    out = {}
    for actor in scene.actors:
        x, y, _ = probe.path(actor, t)
        out[actor.name] = (x / size[0], y / size[1])
    return out


def fit(scene: Scene, size: tuple[int, int]) -> float:
    """How much to shrink the ground characters so that, along all their paths, none can touch another or leave the
    frame (each one with room around it for its motions)."""
    width, height = size
    grounded = [a for a in scene.actors if not a.flying]
    times = np.arange(scene.start, scene.end + 0.25, 0.25)
    scale = 1.0
    for _ in range(30):
        probe = Staged.__new__(Staged)
        probe.scene, probe.size, probe.scale = scene, size, scale
        probe.by_name = {a.name: a for a in scene.actors}
        ok = True
        for t in times:
            boxes = []
            for actor in grounded:
                x, y, edge = probe.path(actor, t)
                h = probe.height(actor, y)
                # room for its sway and its hops; without deformation it only sways a little, never hops
                spread, hop = (0.03, 1.0) if scene.rigid else (SPREAD, 1.2)
                half = probe.width(actor, y) / 2 + spread * h
                box = (x - half, y - hop * h, x + half, y)
                if not edge and (box[0] < 0 or box[2] > width or box[1] < 0):
                    ok = False
                boxes.append(box)
            for i, a in enumerate(boxes):  # on one line this is "side by side"; in depth, one may stand behind another
                for j, b in enumerate(boxes[i + 1:], i + 1):
                    if grounded[i].fixed and grounded[j].fixed:
                        continue  # both put there by hand: their size is the user's choice (the check still warns)
                    if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                        ok = False
            if not ok:
                break
        if ok:
            return scale
        scale *= 0.94
    return scale


# --- the video -----------------------------------------------------------------------------------------------------

@dataclass
class Output:
    size: tuple[int, int] = (1920, 1080)
    crf: int = 18
    preset: str = "medium"


PREVIEW_16_9, FULL_16_9 = Output((960, 540), 26, "veryfast"), Output((1920, 1080))
PREVIEW_9_16, FULL_9_16 = Output((540, 960), 26, "veryfast"), Output((1080, 1920))
CLIPS = ROOT / "cache" / "animatie"
CLIP_VERSION = 7
CROSSFADE = 1.0


class Track:
    """The song heard once: its pulse, the singer's mouth and everyone's blinks, for every frame from `start`."""

    def __init__(self, audio: Path, scenes: list[Scene], start: float = 0.0, seconds: float | None = None,
                 words: list[tuple[float, float, str]] | None = None):
        song = decode(audio, talking.RATE)
        self.beat = beat_of(song, talking.RATE)
        self.total = len(song) / talking.RATE
        self.start = start
        self.seconds = min(seconds or self.total - start, self.total - start)
        self.frames = round(self.seconds * FPS)
        samples = song[round(start * talking.RATE): round((start + self.seconds) * talking.RATE)]
        if any(a.sings for s in scenes for a in s.actors):
            words = talking.spoken_words(audio) if words is None else words
            near = [(a - start, b - start, w) for a, b, w in words if b > start and a < start + self.seconds]
            self.opening, self.roundness = talking.mouth_track(samples, near, self.frames)
        else:
            self.opening, self.roundness = np.zeros(self.frames), np.zeros(self.frames)
        every = {a.name: a.blink_every for s in scenes for a in s.actors if a.blink_every}
        self.lids = {name: talking.blinks(self.frames, e, seed=sum(map(ord, name))) for name, e in every.items()}

    def at(self, n: int) -> tuple[tuple[float, float], dict[str, float]]:
        n = min(n, self.frames - 1)
        return (float(self.opening[n]), float(self.roundness[n])), {k: float(v[n]) for k, v in self.lids.items()}


def logo_strength(t: float, settings: LogoSettings | None) -> float:
    """How visible the logo is at `t`: a watermark stays to the end; "only at the start" fades out after its seconds."""
    if settings is None:
        return 1.0
    k = min(1.0, t / settings.fade_in) if settings.fade_in > 0 else 1.0
    if settings.mode == "start":
        if t >= settings.seconds:
            return 0.0
        if settings.fade_out > 0:
            k = min(k, (settings.seconds - t) / settings.fade_out)
    return max(0.0, k)


class Logo:
    def __init__(self, image: Image.Image, at: tuple[int, int], settings: LogoSettings | None = None):
        self.image, self.at, self.settings = image, at, settings
        self._faded: dict[int, Image.Image] = {}

    def put(self, frame: Image.Image, t: float) -> None:
        level = round(20 * logo_strength(t, self.settings))
        if level <= 0:
            return
        if level not in self._faded:
            image = self.image.copy()
            image.putalpha(image.getchannel("A").point(lambda v: round(v * level / 20)))
            self._faded[level] = image
        frame.alpha_composite(self._faded[level], self.at)


def _encoder(output: Path, out: Output, audio: list[str] | None = None) -> subprocess.Popen:
    width, height = out.size
    command = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-", *(audio or []), "-c:v", "libx264",
               "-preset", out.preset, "-crf", str(out.crf), "-pix_fmt", "yuv420p", "-threads", "4", "-r", str(FPS),
               "-movflags", "+faststart", str(output)]
    output.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)


def _finish(process: subprocess.Popen, partial: Path, output: Path) -> None:
    process.stdin.close()
    error = process.stderr.read().decode("utf-8", "replace")
    if process.wait():
        raise RenderError("FFmpeg a raportat o eroare:\n" + error[-800:])
    partial.replace(output)


def render(scenes: list[Scene], audio: Path, output: Path, start: float, seconds: float, out: Output = FULL_16_9,
           logo: Logo | None = None, crossfade: float = CROSSFADE, fade: tuple[float, float] = (0.0, 0.0),
           words: list[tuple[float, float, str]] | None = None, on_progress: Progress = lambda f, m: None,
           placed: list[list[Placed]] | None = None) -> dict:
    """Draw `seconds` of the scenes from the song's time `start` and encode them with the song into an MP4."""
    on_progress(0.0, "Ascult melodia…")
    track = Track(audio, scenes, start, seconds, words)
    on_progress(0.02, "Pregătesc scenele…")
    staged = [Staged(s, out.size) for s in scenes]
    fades = [*([f"fade=t=in:d={fade[0]}"] if fade[0] else []),
             *([f"fade=t=out:st={track.seconds - fade[1]:.3f}:d={fade[1]}"] if fade[1] else [])]
    sound = ["-ss", f"{start:.3f}", "-t", f"{track.seconds:.3f}", "-i", str(audio), "-map", "0:v", "-map", "1:a:0",
             *(["-vf", ",".join(fades), "-af", ",".join(f.replace("fade=", "afade=") for f in fades)] if fades else []),
             "-c:a", "aac", "-b:a", "192k", "-shortest"]
    partial = output.with_name(output.stem + ".part.mp4")
    process = _encoder(partial, out, sound)
    try:
        for n in range(track.frames):
            t = start + n / FPS
            voice, lids = track.at(n)
            here = [] if placed is not None else None
            frame = _frame(staged, t, track.beat, voice, lids, crossfade, here)
            if placed is not None:
                placed.append(here)
            if logo is not None:
                logo.put(frame, t)
            process.stdin.write(frame.convert("RGB").tobytes())
            if n % 15 == 0:
                on_progress(0.03 + 0.97 * n / track.frames, f"Animez: {n * 100 // track.frames}%")
        _finish(process, partial, output)
    finally:
        if process.poll() is None:
            process.kill()
        partial.unlink(missing_ok=True)
    on_progress(1.0, "Gata!")
    return {"frames": track.frames, "beat": track.beat, "opening": track.opening, "scales": [s.scale for s in staged],
            "ffmpeg": process}


def render_video(scenes: list[Scene], keys: list[str], audio: Path, output: Path, out: Output = FULL_16_9,
                 logo: Logo | None = None, logo_key: str = "", fade_out: bool = False,
                 on_progress: Progress = lambda f, m: None) -> dict:
    """The whole song, one cached clip per scene (a scene changed by the user is the only one drawn again), then the
    clips joined without re-encoding and the song added. `keys[i]` must change whenever scene i or its neighbours do."""
    on_progress(0.0, "Ascult melodia…")
    track = Track(audio, scenes)
    edges = [round(s.start * FPS) for s in scenes[1:]]
    spans = list(zip([0, *edges], [*edges, track.frames]))
    CLIPS.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, key in enumerate(keys):
        last = i == len(scenes) - 1
        name = hashlib.sha1(repr((CLIP_VERSION, key, out, logo_key, fade_out and last, track.frames if last else 0))
                            .encode()).hexdigest()[:24]
        clips.append(CLIPS / f"{name}_{out.size[0]}x{out.size[1]}.mp4")
    todo = [i for i, clip in enumerate(clips) if not clip.exists()]
    work = sum(spans[i][1] - spans[i][0] for i in todo) or 1
    done = 0
    for i in todo:
        near = {k: Staged(scenes[k], out.size) for k in (i - 1, i, i + 1) if 0 <= k < len(scenes)}
        order = [near[k] for k in sorted(near)]
        partial = clips[i].with_name(clips[i].stem + ".part.mp4")
        process = _encoder(partial, out)
        try:
            for n in range(*spans[i]):
                t = n / FPS
                voice, lids = track.at(n)
                frame = _frame(order, t, track.beat, voice, lids, CROSSFADE, None)
                if fade_out and t > track.total - 2.5:
                    black = Image.new("RGBA", frame.size, (0, 0, 0, 255))
                    frame = Image.blend(frame, black, min(1.0, (t - track.total + 2.5) / 2.5))
                if logo is not None:
                    logo.put(frame, t)
                process.stdin.write(frame.convert("RGB").tobytes())
                done += 1
                if done % 15 == 0:
                    on_progress(0.02 + 0.93 * done / work, f"Animez scena {i + 1} din {len(scenes)}: {done * 100 // work}%")
            _finish(process, partial, clips[i])
        finally:
            if process.poll() is None:
                process.kill()
            partial.unlink(missing_ok=True)
    on_progress(0.96, "Pun scenele cap la cap și adaug melodia…")
    listing = CLIPS / f"lista_{os.getpid()}.txt"
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    partial = output.with_name(output.stem + ".part.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    fade = ["-af", f"afade=t=out:st={track.total - 2.5:.3f}:d=2.5"] if fade_out else []
    command = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(listing), "-i", str(audio), "-map", "0:v", "-map", "1:a:0", "-c:v", "copy", *fade,
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(partial)]
    try:
        result = subprocess.run(command, capture_output=True, creationflags=NO_WINDOW)
        if result.returncode:
            raise RenderError("FFmpeg a raportat o eroare:\n" + result.stderr.decode("utf-8", "replace")[-800:])
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
    on_progress(1.0, "Gata!")
    return {"drawn": len(todo), "scenes": len(scenes), "frames": track.frames}


def _frame(staged: list[Staged], t: float, beat: Beat, voice, lids, crossfade: float, placed) -> Image.Image:
    """The scene at `t`; around a change of scene, the two are blended softly."""
    index = max(0, sum(1 for s in staged if s.scene.start <= t) - 1)
    half = crossfade / 2
    for a, b in ((index - 1, index), (index, index + 1)):
        if 0 <= a and b < len(staged) and crossfade and abs(t - staged[b].scene.start) < half:
            u = ease((t - staged[b].scene.start + half) / crossfade)
            return Image.blend(staged[a].draw(t, beat, voice, lids), staged[b].draw(t, beat, voice, lids, placed), u)
    return staged[index].draw(t, beat, voice, lids, placed)

