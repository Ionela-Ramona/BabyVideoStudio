"""Talking character: a still picture whose mouth moves with a voice, with blinks and a gentle sway.

No AI model draws anything. The mouth follows what is said: every recognized word (faster-whisper, local) is split
into syllables and its vowels give the mouth's shape (a open, e/i wide, o/u round, m/b/p closed); the voice's
loudness sets how wide it opens. Background music never moves the mouth.

Two ways to show the shapes:
A. From the picture itself: its mouth squeezed, kept, widened or narrowed; for a closed mouth it is covered with the
   skin around it and its upper outline drawn as a smile. Eyelids are painted from the skin around the eyes.
B. From variants of the same picture made by the user (mouth closed, open, round…, eyes closed): only the mouth or
   eye area is taken from them, aligned and blended in. Everything else always stays pixel for pixel the original.

A character is saved once as a reusable profile (picture, where its mouth and eyes are, variants); a video then
only needs a voice and some backdrops.
"""
import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from pydantic import BaseModel

from .audio import decode
from .media import NO_WINDOW, RenderError, find_tool
from .projects import ROOT, safe_name

FPS = 30
WIDTH, HEIGHT = 1080, 1920
RATE = 16000
PROFILES = ROOT / "personaje"
Box = tuple[int, int, int, int]  # left, top, right, bottom, in the picture's pixels
Progress = Callable[[float, str], None]

SHAPES = {"inchisa": "Gura închisă", "putin": "Gura puțin deschisă", "deschisa": "Gura deschisă",
          "larga": "Gura larg deschisă", "rotunda": "Gura rotunjită (o, u)", "ochi_inchisi": "Ochii închiși"}
# How open and how round (negative = stretched wide) the mouth is on each vowel.
VOWELS = {"a": (1.0, 0.0), "ă": (0.65, 0.0), "e": (0.6, -0.5), "i": (0.35, -0.6), "y": (0.35, -0.6),
          "o": (0.75, 0.75), "u": (0.45, 1.0), "â": (0.45, 0.0), "î": (0.45, 0.0)}
LIPS = set("mbp")  # the lips meet on these
BLINK_FRAMES = {"rapid": 4, "normal": 6, "lent": 9}


@dataclass
class Face:
    mouth: Box
    eyes: list[Box]


@dataclass
class Style:
    mouth: float = 1.0  # how wide the mouth opens, 0.5–1.5
    blink: bool = True
    blink_every: float = 4.5  # seconds between blinks, on average
    blink_speed: str = "normal"  # rapid, normal or lent
    sway: float = 1.0  # 0 = still, 1 = gentle, 2 = livelier
    scene_seconds: float = 8.0  # shortest time on one backdrop
    crossfade: float = 0.6


class Profile(BaseModel):
    """A character saved for reuse: its picture, where its mouth and eyes are, and its optional variants."""
    name: str
    image: str = ""
    mouth: list[int] = []
    eyes: list[list[int]] = []
    variants: dict[str, str] = {}  # SHAPES key -> file in the profile's folder
    # Used only by the automatic animation with several characters:
    kind: str = "personaj"  # personaj, animal, om, obiect
    flying: bool = False
    names: list[str] = []  # how the lyrics call it: "iepuraș", "iepurașul", "iepurașii"
    size: float = 1.0  # height next to the others
    looks: dict[str, str] = {}  # other pictures in the same pose: "salut" (an arm raised)
    rig: dict[str, list[float]] = {}  # the skeleton's points (rig.POINTS), fractions of the picture: arms and legs bend

    @property
    def face(self) -> Face | None:
        return Face(tuple(self.mouth), [tuple(e) for e in self.eyes]) if len(self.mouth) == 4 else None


# --- profiles ----------------------------------------------------------------------------------------------------

def profile_dir(name: str) -> Path:
    return PROFILES / safe_name(name)


def list_profiles() -> list[str]:
    return sorted(p.parent.name for p in PROFILES.glob("*/profil.json")) if PROFILES.exists() else []


def load_profile(name: str) -> Profile:
    return Profile.model_validate_json((profile_dir(name) / "profil.json").read_text(encoding="utf-8"))


def save_profile(profile: Profile) -> None:
    folder = profile_dir(profile.name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profil.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def store(profile: Profile, filename: str, data: bytes) -> str:
    folder = profile_dir(profile.name)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_name(Path(filename).name)
    (folder / name).write_bytes(data)
    return name


def variant_files(profile: Profile) -> dict[str, Path]:
    folder = profile_dir(profile.name)
    return {shape: folder / name for shape, name in profile.variants.items() if (folder / name).exists()}


# --- the voice ---------------------------------------------------------------------------------------------------

def spoken_words(audio: Path) -> list[tuple[float, float, str]]:
    """Every word with its start and end, from the local speech recognition (kept in the cache)."""
    from . import autosync
    return [(w[0], w[1], w[2].strip()) for w in autosync.hear(audio, False, lambda f, m: None)]


def _keys(text: str, start: float, end: float) -> list[tuple[float, float, float]]:
    """(time, opening, roundness) along one word: a key on each vowel group and on each consonant group."""
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return []
    step, keys, i = (end - start) / len(letters), [], 0
    while i < len(letters):
        vowel = letters[i] in VOWELS
        j = i
        while j < len(letters) and (letters[j] in VOWELS) == vowel:
            j += 1
        at = start + (i + j) / 2 * step
        if vowel:  # ea, oa, ia…: the most open vowel of the group shapes the mouth, held while it lasts
            opening, roundness = max((VOWELS[v] for v in letters[i:j]), key=lambda v: v[0])
            keys += [(start + (i + 0.5) * step, opening, roundness), (start + (j - 0.5) * step, opening, roundness)]
        elif LIPS & set(letters[i:j]):  # the lips meet, long enough to be seen
            keys += [(start + (i + 0.1) * step, 0.0, 0.0), (start + (j - 0.1) * step, 0.0, 0.0)]
        else:
            keys.append((at, 0.2, 0.0))
        i = j
    return keys


def mouth_track(samples: np.ndarray, words: list[tuple[float, float, str]], frames: int) -> tuple[np.ndarray, np.ndarray]:
    """Per video frame: how open the mouth is (0..1) and how round (-0.6 wide .. 1 round).

    The syllables of each word give the shapes; the voice's loudness (300–3400 Hz, above the music heard between
    the words) says how wide, and also trims a word to the part where the voice is really heard.
    """
    window = 1024
    hertz = np.fft.rfftfreq(window, 1 / RATE)
    band = (hertz > 300) & (hertz < 3400)
    level = np.zeros(frames)
    padded = np.pad(samples, window)
    for n in range(frames):
        middle = window + round(n * RATE / FPS)
        power = np.abs(np.fft.rfft(padded[middle - window // 2: middle + window // 2] * np.hanning(window))) ** 2
        level[n] = 10 * np.log10(power[band].sum() + 1e-9)
    times = np.arange(frames) / FPS
    talking = np.zeros(frames, bool)
    for a, b, _ in words:
        talking |= (times >= a) & (times < b)
    floor = np.median(level[~talking]) if (~talking).sum() > FPS // 2 else np.percentile(level, 10)
    peak = np.percentile(level[talking], 95) if talking.any() else floor + 20
    loud = np.clip((level - floor - 2) / max(peak - floor - 2, 3), 0, 1)

    shape, roundness = np.zeros(frames), np.zeros(frames)
    for a, b, text in words:
        inside = np.where((times >= a) & (times < b))[0]
        heard = inside[loud[inside] > 0.12]
        if len(heard):  # recognition times can be generous: keep to where the voice is heard
            a, b = max(a, times[heard[0]] - 1 / FPS), min(b, times[heard[-1]] + 2 / FPS)
        inner = _keys(text, a, b)
        rounds = [k[2] for k in inner if k[1] > 0.2] or [0.0]  # the lips already take the shape of the next vowel
        keys = [(a, 0.05, rounds[0]), *inner, (b, 0.05, rounds[-1])]
        span = (times >= a) & (times < b)
        at, opens, rounds = (np.array(k) for k in zip(*keys))
        shape[span] = np.interp(times[span], at, opens)
        roundness[span] = np.interp(times[span], at, rounds)
    raw = shape * np.clip(0.55 + 0.7 * loud, 0, 1.15) * (loud > 0.04)

    def smooth(values: np.ndarray, rise: float, fall: float) -> np.ndarray:
        out, last = np.zeros_like(values), 0.0
        for n, v in enumerate(values):
            last += (v - last) * (rise if v > last else fall)
            out[n] = last
        return out

    opening = smooth(raw, 0.75, 0.7)
    opening = np.concatenate([opening[1:], [0.0]])  # one frame early: a mouth slightly ahead of the sound looks in sync
    opening = np.where(opening < 0.06, 0.0, opening)
    return opening, np.where(opening > 0, smooth(roundness, 0.6, 0.6), 0.0)


def blinks(frames: int, every: float = 4.5, speed: str = "normal", seed: int = 7) -> np.ndarray:
    """Eyelids per frame (0 open .. 1 closed): a soft blink every `every` seconds, give or take a third."""
    length = BLINK_FRAMES.get(speed, 6)
    shape = np.sin(np.linspace(0, np.pi, length + 2)[1:-1]) ** 0.6
    out, rng, n = np.zeros(frames), random.Random(seed), int(FPS * min(1.5, every / 2))
    while n < frames - length:
        out[n:n + length] = np.maximum(out[n:n + length], shape)
        n += max(length + 1, int(FPS * every * rng.uniform(0.65, 1.35)))
    return out


# --- the face ----------------------------------------------------------------------------------------------------

def _not_skin(rgb: np.ndarray) -> np.ndarray:
    """Everything that is not the character's warm skin (yellow, also in its highlights and shadows)."""
    r, g, b = (rgb[..., k].astype(int) for k in range(3))
    return ~((r > 150) & (g > 110) & (r - b > 70) & (g - b > 50))


def _blush(rgb: np.ndarray) -> np.ndarray:
    r, g, b = (rgb[..., k].astype(int) for k in range(3))
    return (r > 190) & (r - g > 45) & (b > 90)


def _grow(mask: np.ndarray, pixels: int) -> np.ndarray:
    """The mask made `pixels` larger all around, with round corners."""
    if pixels <= 2:
        image = Image.fromarray(mask.astype(np.uint8) * 255)
        for _ in range(pixels):
            image = image.filter(ImageFilter.MaxFilter(3))
        return np.asarray(image) > 127
    blurred = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(pixels / 2)))
    return (blurred > 6) | mask


def _specks_removed(mask: np.ndarray, pixels: int = 2) -> np.ndarray:
    """Without the skin's glitter dots, which are not part of an eye or a mouth."""
    image = Image.fromarray(mask.astype(np.uint8) * 255)
    for _ in range(pixels):
        image = image.filter(ImageFilter.MinFilter(3))
    for _ in range(pixels):
        image = image.filter(ImageFilter.MaxFilter(3))
    return (np.asarray(image) > 127) & mask


def _component(mask: np.ndarray, point: tuple[int, int]) -> np.ndarray:
    """The connected part of `mask` that holds `point` (or the mask pixel nearest to it): one eye with its lashes."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return mask
    nearest = int(np.argmin((xs - point[0]) ** 2 + (ys - point[1]) ** 2))
    region = np.zeros_like(mask)
    region[ys[nearest], xs[nearest]] = True
    for _ in range(1000):
        grown = _grow(region, 2) & mask
        if grown.sum() == region.sum():
            break
        region = grown
    return region


def _fill(rgb: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """The hole painted with the skin around it, with the skin's own fine grain, so it does not look flat."""
    out = rgb.astype(np.float32).copy()
    skin = ~hole & ~_not_skin(rgb)  # not brows, cheeks or headphones
    guess, have = np.zeros_like(out), np.zeros(hole.shape, bool)
    for radius in (6, 15, 40, 100):  # nearest skin weighs most
        weight = np.asarray(Image.fromarray(skin.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(radius)), np.float32)
        kept = np.asarray(Image.fromarray((rgb * skin[..., None]).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius)),
                          np.float32)
        ready = (weight > 25) & ~have
        guess[ready] = (kept * 255 / np.maximum(weight, 1)[..., None])[ready]
        have |= ready
    guess[~have] = rgb[skin].mean(0) if skin.any() else out[~hole].mean(0)
    out[hole] = guess[hole]
    for _ in range(150):
        p = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        out[hole] = ((p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4)[hole]
    smooth = np.asarray(Image.fromarray(rgb).filter(ImageFilter.GaussianBlur(2)), np.float32)
    detail = (rgb.astype(np.float32) - smooth)[~hole]
    grain = 1.4826 * np.median(np.abs(detail - np.median(detail, 0)), 0)  # robust: the glitter dots do not count
    out[hole] += np.random.default_rng(1).normal(0, 1, (int(hole.sum()), 1)) * grain * 0.5
    return out.clip(0, 255).astype(np.uint8)


def _parts(mask: np.ndarray, smallest: int) -> list[np.ndarray]:
    """The separate pieces of a mask, largest first."""
    pieces, left = [], mask.copy()
    while left.sum() >= smallest:
        ys, xs = np.nonzero(left)
        piece = _component(left, (int(xs[0]), int(ys[0])))
        left &= ~piece
        if piece.sum() >= smallest:
            pieces.append(piece)
    return sorted(pieces, key=lambda p: -p.sum())


def _box(mask: np.ndarray, scale: float, margin: int = 0) -> Box:
    ys, xs = np.nonzero(mask)
    return (int(xs.min() / scale) - margin, int(ys.min() / scale) - margin, int((xs.max() + 1) / scale) + margin,
            int((ys.max() + 1) / scale) + margin)


def detect_face(picture: Image.Image) -> Face | None:
    """Where the eyes (a pair of blue irises side by side) and the mouth (dark red below them) are; None when not found."""
    scale = min(1.0, 420 / max(picture.size))
    small = picture.convert("RGBA").resize((round(picture.width * scale), round(picture.height * scale)), Image.BILINEAR)
    rgba = np.asarray(small)
    rgb, body = rgba[..., :3], rgba[..., 3] > 128
    r, g, b = (rgb[..., k].astype(int) for k in range(3))
    rows, columns = np.indices(r.shape)
    skin = ~_not_skin(rgb)
    # Blue, not purple (headphones): an iris has more green than red. It sits in the face, not in the sky.
    blue = _parts(body & (b > r + 60) & (g > r + 15) & (b > 110), max(6, body.sum() // 3000))[:8]
    blue = [m for m in blue if skin[_grow(m, 12) & ~m].mean() > 0.15]
    centre = lambda m: (np.nonzero(m)[1].mean(), np.nonzero(m)[0].mean())  # noqa: E731
    pairs = [(m, n) for i, m in enumerate(blue) for n in blue[i + 1:]
             if min(m.sum(), n.sum()) > 0.35 * max(m.sum(), n.sum())  # two eyes of about the same size
             and abs(centre(m)[1] - centre(n)[1]) < 0.12 * r.shape[0]]  # side by side
    if not pairs:
        return None
    irises = sorted(max(pairs, key=lambda p: p[0].sum() + p[1].sum()), key=lambda m: centre(m)[0])
    eyes, around = [], _specks_removed(_not_skin(rgb) & ~_blush(rgb) & body, 1)
    for iris in irises:
        x, y = centre(iris)
        ys, xs = np.nonzero(iris)
        reach = 1.6 * max(np.ptp(xs), np.ptp(ys)) + 4  # the eye with its lashes, never the headphones next to it
        window = (abs(columns - x) < reach) & (abs(rows - y) < reach)
        eyes.append(_box(_component(around & window, (int(x), int(y))), scale, 4))
    level = (centre(irises[0])[1] + centre(irises[1])[1]) / 2  # below the eyes' middle: the head may be tilted
    lefts, rights = min(e[0] for e in eyes) * scale, max(e[2] for e in eyes) * scale
    apart = centre(irises[1])[0] - centre(irises[0])[0]
    window = (rows > level) & (rows < level + 1.5 * apart) & (columns > lefts) & (columns < rights)
    pieces = _parts(body & window & (r > 90) & (g < 110) & (b < 130) & ~_blush(rgb), 4)
    if not pieces:
        return None
    x, y = centre(pieces[0])
    mouth = _component(_not_skin(rgb) & body & window, (int(x), int(y)))  # with the pink tongue
    return Face(_box(mouth, scale, 3), eyes)


def _aligned(base: np.ndarray, variant: np.ndarray, area: Box, reach: int = 24) -> np.ndarray:
    """The variant's pixels for `area`, shifted so its surroundings line up with the base picture."""
    left, top, right, bottom = area
    gray = lambda a: a[..., :3].astype(np.float32).mean(-1)  # noqa: E731
    target = gray(base[top:bottom, left:right])
    ring = np.ones(target.shape, bool)
    ring[target.shape[0] // 4: -target.shape[0] // 4, target.shape[1] // 4: -target.shape[1] // 4] = False  # the feature moves
    padded = np.pad(variant, ((reach, reach), (reach, reach), (0, 0)), mode="edge")
    source = gray(padded)

    def cost(dx: int, dy: int) -> float:
        window = source[top + reach + dy: bottom + reach + dy, left + reach + dx: right + reach + dx]
        return float(np.abs(window - target)[ring].mean())

    best = min(((dx, dy) for dx in range(-reach, reach + 1, 3) for dy in range(-reach, reach + 1, 3)), key=lambda d: cost(*d))
    best = min(((best[0] + dx, best[1] + dy) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)
                if abs(best[0] + dx) <= reach and abs(best[1] + dy) <= reach), key=lambda d: cost(*d))
    dx, dy = best
    return padded[top + reach + dy: bottom + reach + dy, left + reach + dx: right + reach + dx]


class Puppet:
    """The character picture with its mouth and eyes ready to move."""

    def __init__(self, picture: Image.Image, face: Face, variants: dict[str, Image.Image] | None = None):
        self.picture = picture.convert("RGBA")
        rgba = np.asarray(self.picture)
        rgb = rgba[..., :3]
        left, top, right, bottom = face.mouth
        pad, below = 10, 10 + round(0.3 * (bottom - top))  # room under the mouth for its widest opening
        height, width = rgb.shape[:2]
        self.area = (max(0, left - pad), max(0, top - pad), min(width, right + pad), min(height, bottom + below))
        crop = rgb[self.area[1]:self.area[3], self.area[0]:self.area[2]]
        inside = np.zeros(crop.shape[:2], bool)
        inside[top - self.area[1]:bottom - self.area[1], left - self.area[0]:right - self.area[0]] = True
        mouth = _specks_removed(_not_skin(crop) & inside, 1)  # pink counts here: the tongue is pink too
        self.clean = _fill(crop, _grow(mouth, 3) & _grow(inside, 2))
        alpha = Image.fromarray(_grow(mouth, 1).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.2))
        self.mouth = Image.fromarray(crop).convert("RGBA")
        self.mouth.putalpha(alpha)
        rows, columns = np.where(mouth.any(1))[0], np.where(mouth.any(0))[0]
        self.mouth_box = (columns[0], rows[0], columns[-1] + 1, rows[-1] + 1)  # inside self.area
        # The upper outline of the mouth, which becomes the closed mouth's smile.
        self.smile = [(x, int(np.argmax(mouth[:, x]))) for x in range(columns[0], columns[-1] + 1) if mouth[:, x].any()]
        self.ink = tuple(int(v) for v in np.percentile(crop[mouth].reshape(-1, 3), 8, axis=0)) + (255,)
        self.eyes = [self._eye(box, rgb) for box in face.eyes]

        # Variants (B): only the mouth or eye area, lined up with this picture and blended in softly.
        self.shapes: dict[str, tuple[Image.Image, Image.Image]] = {}
        around = Image.fromarray((_grow(_grow(mouth, 2) | inside, 8)).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(4))
        for shape, image in (variants or {}).items():
            pixels = np.asarray(image.convert("RGBA").resize(self.picture.size, Image.LANCZOS))
            if shape == "ochi_inchisi":
                patches = []
                for eye in self.eyes:
                    soft = Image.fromarray(eye["mask"].astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(4))
                    patches.append((Image.fromarray(_aligned(rgba, pixels, eye["box"])[..., :3]), soft))
                self.closed_eyes = patches
            else:
                self.shapes[shape] = (Image.fromarray(_aligned(rgba, pixels, self.area)[..., :3]), around)

    def _eye(self, box: Box, rgb: np.ndarray) -> dict:
        pad = 50  # room around the eye: its lashes may reach past the box, and the painted lid must end on plain skin
        height, width = rgb.shape[:2]
        left, top, right, bottom = max(0, box[0] - pad), max(0, box[1] - pad), min(width, box[2] + pad), min(height, box[3] + pad)
        centre = ((box[0] + box[2]) // 2 - left, (box[1] + box[3]) // 2 - top)
        crop = rgb[top:bottom, left:right]
        eye = _component(_specks_removed(_not_skin(crop) & ~_blush(crop)), centre)
        rows, columns = np.where(eye.any(1))[0], np.where(eye.any(0))[0]
        # The lid also covers the light rim around the eye, so it ends on plain skin.
        return {"box": (left, top, right, bottom), "mask": _grow(eye, 13), "clean": _fill(crop, _grow(eye, 14)),
                "top": rows[0], "bottom": rows[-1], "left": columns[0], "right": columns[-1],
                "ink": tuple(int(v) for v in np.percentile(crop[eye].reshape(-1, 3), 3, axis=0)) + (255,)}

    @staticmethod
    def shape_for(opening: float, roundness: float) -> str:
        if opening <= 0:
            return "inchisa"
        if roundness > 0.5 and opening > 0.2:
            return "rotunda"
        return "putin" if opening < 0.35 else "deschisa" if opening < 0.8 else "larga"

    def frame(self, opening: float, roundness: float, blink: float) -> Image.Image:
        """The picture with the mouth this open and round, and the eyelids this closed (0..1)."""
        picture = self.picture.copy()
        shape = self.shape_for(opening, roundness)
        if shape in self.shapes:
            patch, soft = self.shapes[shape]
            picture.paste(patch, self.area[:2], soft)
        else:
            picture.paste(self._drawn_mouth(opening, roundness), self.area[:2])
        if blink > 0:
            if hasattr(self, "closed_eyes"):
                for eye, (patch, soft) in zip(self.eyes, self.closed_eyes):
                    picture.paste(patch, eye["box"][:2], soft.point(lambda v, k=min(1.0, blink * 1.4): round(v * k)))
            else:
                for eye in self.eyes:
                    self._close(picture, eye, blink)
        return picture

    def _drawn_mouth(self, opening: float, roundness: float) -> Image.Image:
        area = Image.fromarray(self.clean).convert("RGBA")
        left, top, right, bottom = self.mouth_box
        width, height = right - left, bottom - top
        if opening <= 0:
            ImageDraw.Draw(area).line(self.smile, fill=self.ink, width=max(2, round(width / 28)), joint="curve")
        else:
            wide = 1 + 0.08 * opening - 0.32 * roundness * opening
            tall = 0.2 + 0.95 * opening
            size = (max(2, round(width * wide)), max(2, round(height * tall)))
            mouth = self.mouth.crop((left, top, right, bottom)).resize(size, Image.LANCZOS)
            area.alpha_composite(mouth, (round(left + (width - size[0]) / 2), top))
        return area.convert("RGB")

    @staticmethod
    def _close(picture: Image.Image, eye: dict, amount: float) -> None:
        left, top, right, bottom = eye["box"]
        crop = np.asarray(picture.crop(eye["box"]).convert("RGB")).copy()
        height = eye["bottom"] - eye["top"]
        middle, half = (eye["left"] + eye["right"]) / 2, max(1.0, (eye["right"] - eye["left"]) / 2)
        xs = np.arange(crop.shape[1])
        # The lid comes down to the lower lash line, lowest in the middle: a closed eye smiles (‿).
        edge = eye["top"] + amount * height * (0.88 + 0.14 * np.clip(1 - ((xs - middle) / half) ** 2, 0, 1))
        covered = (np.arange(crop.shape[0])[:, None] < edge[None, :]) & eye["mask"]
        alpha = np.asarray(Image.fromarray(covered.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(2.5)), np.float32)
        alpha = np.maximum(alpha, covered * 255.0)[..., None] / 255  # feathered, so the lid melts into the skin
        crop = (crop * (1 - alpha) + eye["clean"] * alpha).astype(np.uint8)
        lid = Image.fromarray(crop)
        line = [(int(x), float(edge[x])) for x in range(eye["left"], eye["right"] + 1) if eye["mask"][:, x].any()]
        if len(line) > 1:
            ImageDraw.Draw(lid).line(line, fill=eye["ink"][:3], width=max(2, round(height / (12 if amount >= 1 else 16))),
                                     joint="curve")
        picture.paste(lid, (left, top))


# --- the video ---------------------------------------------------------------------------------------------------

def cover(path: Path) -> Image.Image:
    """A backdrop filling 9:16 (its sides may be cut; the character never is)."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return ImageOps.fit(image, (WIDTH, HEIGHT), Image.LANCZOS)


def night_sky() -> Image.Image:
    """The backdrop when none is chosen: a soft evening gradient."""
    top, bottom = np.array([28, 30, 92]), np.array([150, 110, 200])
    rows = np.linspace(0, 1, HEIGHT)[:, None, None]
    return Image.fromarray(np.broadcast_to(top + (bottom - top) * rows, (HEIGHT, WIDTH, 3)).astype(np.uint8))


def backdrop_starts(words: list[tuple[float, float, str]], seconds: float, count: int, shortest: float) -> list[float]:
    """When each backdrop begins: at the pause between words nearest to an even share of the video."""
    pauses = [(a_end + b_start) / 2 for (_, a_end, _), (b_start, _, _) in zip(words, words[1:]) if b_start - a_end >= 0.25]
    starts = [0.0]
    for k in range(1, count):
        fits = [p for p in pauses if p - starts[-1] >= shortest and seconds - p >= shortest]
        if not fits:
            break
        starts.append(min(fits, key=lambda p: abs(p - seconds * k / count)))
    return starts


def render(character: Path, face: Face, audio: Path, output: Path, decors: list[Path] | None = None,
           variants: dict[str, Path] | None = None, start: float = 0.0, seconds: float | None = None,
           style: Style = Style(), on_progress: Progress = lambda f, m: None) -> dict:
    """A vertical 1080×1920, 30 FPS MP4 of the talking character over its backdrops, with the voice as recorded."""
    on_progress(0.0, "Ascult vocea…")
    samples = decode(audio, RATE)
    total = len(samples) / RATE
    seconds = min(seconds or total, total - start)
    frames = round(seconds * FPS)
    words = [(a - start, b - start, text) for a, b, text in spoken_words(audio) if b > start and a < start + seconds]
    opening, roundness = mouth_track(samples[round(start * RATE): round((start + seconds) * RATE)], words, frames)
    opening = np.clip(opening * style.mouth, 0, 1.2)
    lids = blinks(frames, style.blink_every, style.blink_speed) if style.blink else np.zeros(frames)

    on_progress(0.02, "Pregătesc personajul…")
    with Image.open(character) as source:
        picture = ImageOps.exif_transpose(source).convert("RGBA")
    # Sized once for the video: the whole character, with a margin so the sway never cuts it.
    scale = min(WIDTH * 0.88 / picture.width, HEIGHT * 0.6 / picture.height)
    size = (round(picture.width * scale), round(picture.height * scale))
    margin = round(0.04 * max(size))
    canvas = Image.new("RGBA", (size[0] + 2 * margin, size[1] + 2 * margin), (0, 0, 0, 0))
    canvas.paste(picture.resize(size, Image.LANCZOS), (margin, margin))

    def moved(box: Box) -> Box:
        return tuple(round(v * scale) + margin for v in box)  # type: ignore[return-value]

    shapes = {}
    for shape, path in (variants or {}).items():
        with Image.open(path) as source:
            variant = ImageOps.exif_transpose(source).convert("RGBA").resize(picture.size, Image.LANCZOS)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(variant.resize(size, Image.LANCZOS), (margin, margin))
        shapes[shape] = layer
    puppet = Puppet(canvas, Face(moved(face.mouth), [moved(e) for e in face.eyes]), shapes)

    backs = [cover(path) for path in decors or []] or [night_sky()]
    starts = backdrop_starts(words, seconds, len(backs), style.scene_seconds)
    backs = backs[:len(starts)]
    place = ((WIDTH - canvas.width) // 2, round(HEIGHT * 0.82) - canvas.height)  # standing in the lower part
    lift = np.convolve(opening, np.ones(9) / 9, "same")  # a little livelier while speaking

    command = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}",
               "-i", str(audio), "-map", "0:v", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest",
               "-movflags", "+faststart", str(output)]
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".part.mp4")
    command[-1] = str(partial)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        for n in range(frames):
            t = n / FPS
            scene = sum(1 for s in starts if s <= t) - 1
            back = backs[scene]
            if scene + 1 < len(starts) and starts[scene + 1] - t < style.crossfade:  # a soft change of backdrop
                back = Image.blend(back, backs[scene + 1], 1 - (starts[scene + 1] - t) / style.crossfade)
            angle = style.sway * (0.9 * math.sin(2 * math.pi * t / 4.7) + 0.5 * lift[n] * math.sin(2 * math.pi * t / 1.3))
            rise = style.sway * (5 * math.sin(2 * math.pi * t / 3.1) + 12 * lift[n])
            body = puppet.frame(float(opening[n]), float(roundness[n]), float(lids[n])).rotate(
                angle, Image.BICUBIC, center=(canvas.width / 2, canvas.height * 0.92))
            frame = back.copy()
            frame.paste(body, (place[0], round(place[1] - rise)), body)
            process.stdin.write(frame.tobytes())
            if n % 15 == 0:
                on_progress(0.05 + 0.95 * n / frames, f"Animez personajul: {n * 100 // frames}%")
        process.stdin.close()
        error = process.stderr.read().decode("utf-8", "replace")
        if process.wait():
            raise RenderError("FFmpeg a raportat o eroare:\n" + error[-800:])
        partial.replace(output)
    finally:
        if process.poll() is None:
            process.kill()
        partial.unlink(missing_ok=True)
    on_progress(1.0, "Gata!")
    return {"frames": frames, "opening": opening, "roundness": roundness, "blinks": lids, "words": words,
            "backdrops": starts}
