"""Gentle, combinable motions for animated characters (made for babies 0–2: soft starts, small amplitudes).

A motion is a function of time that says how a character is moved away from where it stands: a shift, a tilt, a
squash or stretch, a fade, and optionally which picture of the character to show ("salut" for a waving arm, …).
Several motions run at once and simply add up: a character can walk, hop and blink at the same time.

Shifts are in the character's own heights, so the same motion fits a big or a small character, 16:9 or 9:16.
Moving from place to place (walking, approaching another character, following one) is not a motion here: it is the
character's path, kept by the stage, so a shift never piles up over time.
"""
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

RAMP = 0.5  # seconds for every motion to fade in and out: nothing starts or stops abruptly
# How the limbs of a character with a skeleton (rig.py) bend, in degrees from the picture's pose; a plain picture
# ignores them. umar_*/sold_*: swung forward; *_lat: raised sideways; cot_*/genunchi_*: bent; palme: hands together
# (0..1); cap: the head tilted on the body; urechi: ears swung out (-: flopped in); coada: the tail wagged. Sides are
# the character's own (its right arm is on the left of the picture). An animal uses what it has: its paws or wings
# take the arms' values, its feet lift with the knees.
JOINTS = ("umar_drept", "umar_stang", "umar_drept_lat", "umar_stang_lat", "cot_drept", "cot_stang",
          "sold_drept", "sold_stang", "sold_drept_lat", "sold_stang_lat", "genunchi_drept", "genunchi_stang", "palme",
          "cap", "urechi", "coada")


@dataclass
class Pose:
    dx: float = 0.0  # in the character's heights, + right
    dy: float = 0.0  # in the character's heights, + down
    angle: float = 0.0  # degrees, + counter-clockwise
    sx: float = 1.0
    sy: float = 1.0
    alpha: float = 1.0
    look: str | None = None  # another picture of the character, if it has one (a frame: "palme", "sare", "salut")
    blend: float = 1.0  # how much of that picture shows over the plain one: frames change softly, never at once
    under: str | None = None  # a frame shown instead of the plain picture, under `look` (hands apart, under together)
    under_blend: float = 1.0
    joints: dict[str, float] = field(default_factory=dict)  # bends of the limbs (see JOINTS), for a skeleton


@dataclass(frozen=True)
class Beat:
    """The song's pulse: a beat every `period` seconds, the first one at `phase`."""
    period: float = 0.5
    phase: float = 0.0

    def count(self, t: float) -> float:
        return (t - self.phase) / self.period


def ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def glide(x: float, ramp: float) -> float:
    """0 → 1 at an even pace (walking), speeding up and slowing down softly over `ramp` of the way at each end."""
    x, r = min(1.0, max(0.0, x)), min(max(ramp, 1e-6), 0.5)
    v = 1 / (1 - r)
    if x < r:
        return v * x * x / (2 * r)
    if x < 1 - r:
        return v * (x - r / 2)
    return 1 - v * (1 - x) ** 2 / (2 * r)


def weight(t: float, start: float, end: float) -> float:
    """0 → 1 → 0 across a motion's time, with soft edges."""
    if t <= start or t >= end:
        return 0.0
    ramp = min(RAMP, (end - start) / 2)
    return ease((t - start) / ramp) * ease((end - t) / ramp)


# --- the catalogue -------------------------------------------------------------------------------------------------
# Each motion: (t, beat, params) -> Pose, t being the song's time. Params: "lag" (in beats, to follow another
# character's rhythm a little later), "phase" (0..1, so two characters don't move like clones), "mirror" (-1/1).

def breathe(t: float, beat: Beat, p: dict) -> Pose:
    s = math.sin(2 * math.pi * (t / 3.4 + p.get("phase", 0)))
    return Pose(sy=1 + 0.012 * s, sx=1 - 0.006 * s)


def float_(t: float, beat: Beat, p: dict) -> Pose:
    k = 2 * math.pi * (t / 3.2 + p.get("phase", 0))
    return Pose(dy=0.05 * math.sin(k), dx=0.02 * math.sin(k / 2), angle=2 * math.sin(k / 2 + 1))


def _rigid_hop(t: float, beat: Beat, p: dict) -> Pose:
    """Without deformation: the picture stays on the floor. With a jumping frame, it shows on the beat; without one,
    a happy sway on the beat."""
    cycle = (beat.count(t) - p.get("lag", 0)) / 2 % 1
    if "sare" in p.get("frames", ()):
        return Pose(look="sare", blend=_frame(math.sin(math.pi * min(1.0, cycle / 0.55))))
    return Pose(angle=3 * math.sin(math.pi * (beat.count(t) - p.get("lag", 0))))


def hop(t: float, beat: Beat, p: dict) -> Pose:
    """A hop every two beats: up, down, a soft squash on landing. With a skeleton: arms up in the air, knees bent on
    landing (the body goes down with them)."""
    if p.get("rigid"):
        return _rigid_hop(t, beat, p)
    cycle = (beat.count(t) - p.get("lag", 0)) / 2 % 1
    air, land = 0.55, 0.2
    if cycle < air:
        u = math.sin(math.pi * cycle / air)
        return Pose(dy=-0.16 * u, sy=1 + 0.04 * u, sx=1 - 0.02 * u,
                    joints={"umar_drept_lat": 45 * u, "umar_stang_lat": 45 * u, "cot_drept": 20 * u, "cot_stang": 20 * u,
                            "sold_drept": 15 * u, "sold_stang": 15 * u, "genunchi_drept": 25 * u, "genunchi_stang": 25 * u,
                            "urechi": -6 * u})  # the ears stand up in the air
    if cycle < air + land:
        u = math.sin(math.pi * (cycle - air) / land)
        squash = 0.03 if p.get("skeleton") else 0.06  # the knees take the landing
        return Pose(sy=1 - squash * u, sx=1 + squash * 0.7 * u,
                    joints={"sold_drept": 20 * u, "sold_stang": 20 * u, "genunchi_drept": 40 * u, "genunchi_stang": 40 * u,
                            "urechi": 14 * u})  # and flop out as it lands
    return Pose()


def dance(t: float, beat: Beat, p: dict) -> Pose:
    """Sway from side to side over two beats, a small bounce on every beat."""
    b = beat.count(t) - p.get("lag", 0)
    side = math.sin(math.pi * b) * p.get("mirror", 1)
    bounce = abs(math.sin(math.pi * b * 2)) ** 1.5
    if p.get("rigid"):  # a sway from side to side on the beat, a little step aside, the feet on the floor
        sway = Pose(angle=-3 * side, dx=0.015 * side)
        if frames := _clapping(t, beat, p):  # and, with clapping frames, clapping on the beat while swaying
            sway.look, sway.blend, sway.under = frames.look, frames.blend, frames.under
        return sway
    if p.get("skeleton"):  # the arms dance and the knees give the bounce, the feet stay on the ground
        return Pose(angle=-4 * side, dx=0.02 * side,
                    joints={"umar_drept_lat": 32 + 18 * side, "umar_stang_lat": 32 - 18 * side, "cot_drept": 45,
                            "cot_stang": 45, "sold_drept": 12 * bounce, "sold_stang": 12 * bounce,
                            "cap": 5 * side, "urechi": 8 * side, "coada": 18 * side,
                            "genunchi_drept": 25 * bounce, "genunchi_stang": 25 * bounce})
    return Pose(angle=-6 * side, dx=0.03 * side, dy=-0.035 * bounce)


def sway(t: float, beat: Beat, p: dict) -> Pose:
    k = math.sin(2 * math.pi * (t / 4.2 + p.get("phase", 0)))
    if p.get("skeleton"):  # the head leans a little more than the body, the tail follows slowly
        return Pose(angle=2 * k, joints={"cap": 4 * k, "coada": 10 * k, "urechi": 3 * k})
    return Pose(angle=3 * k)


def lull(t: float, beat: Beat, p: dict) -> Pose:
    """Rocking a little one to sleep: very slow, at most 2°, around the feet; nothing bends, nothing else moves."""
    return Pose(angle=2 * math.sin(2 * math.pi * (t / 5.0 + p.get("phase", 0))))


def walk(t: float, beat: Beat, p: dict) -> Pose:
    """A calm step on every beat: the weight goes from one foot to the other (a slight rock), with no bounce, which
    on a picture without legs would look like hopping. With a skeleton one knee comes up while the other leg carries
    the body, and the arms swing the other way. Where to goes in the path, at an even pace."""
    s = math.sin(math.pi * beat.count(t))
    if p.get("rigid"):  # no walking without legs that move: a light rock on the spot
        return Pose(angle=1.5 * s)
    left, right = max(0.0, s), max(0.0, -s)
    return Pose(angle=1.5 * s, joints={"sold_stang": 35 * left, "genunchi_stang": 70 * left, "sold_drept": 35 * right,
                                       "genunchi_drept": 70 * right, "umar_stang": -20 * s, "umar_drept": 20 * s,
                                       "umar_drept_lat": 6, "umar_stang_lat": 6, "cot_drept": 15, "cot_stang": 15,
                                       "coada": 10 * s, "cap": 1.5 * s})


def nod(t: float, beat: Beat, p: dict) -> Pose:
    """A slow tilt of the head, to one side and back, every four beats."""
    u = (beat.count(t) - p.get("lag", 0)) / 4 % 1
    tilt = p.get("mirror", 1) * math.sin(math.pi * u) ** 2
    if p.get("skeleton"):
        return Pose(angle=1.5 * tilt, joints={"cap": 9 * tilt, "urechi": 6 * tilt})
    return Pose(angle=5 * tilt)


def wave(t: float, beat: Beat, p: dict) -> Pose:
    """With a skeleton the right arm goes up and the hand waves; with a "salut" picture the arm is up; without
    either, a friendly little wiggle says hello instead."""
    k = math.sin(2 * math.pi * t * 1.1)
    if p.get("rigid"):  # the waving frame if there is one, a small friendly tilt either way
        return Pose(angle=1.5 * k, look="salut" if "salut" in p.get("frames", ()) else None)
    if p.get("skeleton"):
        # the elbow stays out under the curls and the forearm stands up by the cheek: the whole arm is seen
        return Pose(angle=1.5 * k, joints={"umar_drept_lat": 55 + 4 * k, "cot_drept": 105 + 18 * k,
                                           "cap": 6 + 3 * k, "urechi": 6 * k})  # an animal tilts its head, ears waving
    return Pose(angle=4 * k, dy=-0.015 * abs(k), look="salut")


def _clapping(t: float, beat: Beat, p: dict) -> Pose | None:
    """The clapping frames on every beat (hands apart, then together), when the character has them."""
    if "palme" not in p.get("frames", ()):
        return None
    together = math.cos(math.pi * (beat.count(t) - p.get("lag", 0))) ** 2
    apart = "palme_deschise" if "palme_deschise" in p.get("frames", ()) else None
    return Pose(look="palme", blend=_frame(together), under=apart)


def clap(t: float, beat: Beat, p: dict) -> Pose:
    """Hands together in front of the tummy on every beat: from frames when the character has them (and no skeleton
    to bend its arms), in any style; with a skeleton, its arms; otherwise a happy little nod."""
    together = math.cos(math.pi * (beat.count(t) - p.get("lag", 0))) ** 2
    if not p.get("skeleton") and (frames := _clapping(t, beat, p)):
        return frames
    if p.get("rigid"):  # no frame: a happy nod, nothing made up
        return Pose(angle=2 * math.sin(2 * math.pi * beat.count(t) / 2))
    if p.get("skeleton"):  # an animal without hands bobs its head and its ears jump on the beat
        return Pose(dy=-0.006 * together, joints={"palme": 0.6 + 0.4 * together, "urechi": 8 * together,
                                                   "cap": 3 * math.sin(math.pi * beat.count(t))})
    return Pose(angle=2 * math.sin(2 * math.pi * beat.count(t) / 2), dy=-0.012 * together)


def fly(t: float, beat: Beat, p: dict) -> Pose:
    """A butterfly's flight: a lazy figure eight and a little bank into the turns."""
    k = 2 * math.pi * (t / 4.0 + p.get("phase", 0))
    return Pose(dx=0.35 * math.sin(k), dy=0.18 * math.sin(2 * k), angle=-8 * math.cos(k))


ACTIONS: dict[str, Callable[[float, Beat, dict], Pose]] = {
    "respira": breathe, "pluteste": float_, "sare": hop, "danseaza": dance, "leagana": sway, "merge": walk,
    "inclina": nod, "salut": wave, "zboara": fly, "palme": clap, "legana_lin": lull,
}


def combine(poses: list[tuple[float, Pose]]) -> Pose:
    """Motions running together, each with its weight: shifts and tilts add up, squashes multiply."""
    out = Pose()
    best = 0.05
    for w, pose in poses:
        out.dx += w * pose.dx
        out.dy += w * pose.dy
        out.angle += w * pose.angle
        out.sx *= 1 + w * (pose.sx - 1)
        out.sy *= 1 + w * (pose.sy - 1)
        out.alpha *= 1 - w * (1 - pose.alpha)
        for joint, bend in pose.joints.items():
            out.joints[joint] = out.joints.get(joint, 0.0) + w * bend
        if pose.look and w * pose.blend > best:  # the frame most asked for, fading in and out with its motion
            out.look, best = pose.look, w * pose.blend
            out.blend = best
        if pose.under and w > out.under_blend * (out.under is not None):
            out.under, out.under_blend = pose.under, w
    return out


def _frame(share: float) -> float:
    """0..1 into how much a frame shows: none below a third, all above two thirds, softly between."""
    return ease((share - 1 / 3) * 3)


# --- the song's pulse ----------------------------------------------------------------------------------------------

def beat_of(samples: np.ndarray, rate: int) -> Beat:
    """Tempo and the time of the first beat, from how the sound's energy rises (enough for nursery songs)."""
    hop_ = rate // 100  # 10 ms
    frames = len(samples) // hop_
    if frames < 400:
        return Beat()
    energy = np.log1p(1000 * np.square(samples[:frames * hop_].reshape(frames, hop_)).mean(1))
    onset = np.maximum(np.diff(energy, prepend=energy[0]), 0)
    onset -= onset.mean()
    lags = np.arange(30, 100)  # 0.3–1.0 s: 60–200 beats a minute
    score = np.array([np.dot(onset[:-lag], onset[lag:]) for lag in lags])
    score *= 1 + 0.15 * np.exp(-((lags - 55) / 25) ** 2)  # nursery songs sit around 100–120 bpm
    period = lags[int(np.argmax(score))]
    phase = int(np.argmax([onset[k::period].sum() for k in range(period)]))
    return Beat(period / 100, phase / 100)
