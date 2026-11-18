"""The library every animated video reuses: characters, decors and scene templates, saved next to the app.

Characters are the profiles of the "Personaj vorbitor" mode (personaje/<name>/profil.json: picture, mouth and eyes,
mouth variants) plus what the animation needs (kind, flying, names in lyrics, size, a waving picture), and a few
characters drawn by the program. Decors live in decoruri/, templates in sabloane/.
"""
import io
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import actions, depth, effects, pictures, stage, talking
from .ground import Ground, crop
from .models import AnimScene
from .projects import ROOT, safe_name

DECORS = ROOT / "decoruri"
TEMPLATES = ROOT / "sabloane"
KINDS = {"personaj": "Personaj (stea, jucărie…)", "animal": "Animal", "om": "Copil sau om", "obiect": "Obiect animat"}
# frames: the same character in the same picture, in another pose; shown on the beat, softly, instead of bending it
FRAMES = {"palme_deschise": "✋ Mâini depărtate (gata de palme)", "palme": "👏 Palmele lipite",
          "sare": "🦘 Sare (în aer)", "salut": "👋 Salută (mâna sus)", "ochi_inchisi": "😌 Cu ochii închiși (clipit)"}


@dataclass(frozen=True)
class Character:
    name: str
    kind: str = "personaj"
    flying: bool = False
    names: tuple[str, ...] = ()
    size: float = 1.0
    built_in: bool = False


BUILT_IN = {  # drawn by the program, ready before any picture is made
    "Fluturaș galben": (Character("Fluturaș galben", "animal", True, ("flutur",), 0.45, True),
                        lambda: effects.butterfly((255, 200, 90))),
    "Fluturaș roz": (Character("Fluturaș roz", "animal", True, ("flutur",), 0.42, True),
                     lambda: effects.butterfly((255, 150, 200))),
    "Fluturaș albastru": (Character("Fluturaș albastru", "animal", True, ("flutur",), 0.42, True),
                          lambda: effects.butterfly((140, 190, 255))),
    "Norișor": (Character("Norișor", "obiect", True, ("noris", "nor "), 0.4, True), effects.cloud_buddy),
}


# --- characters ----------------------------------------------------------------------------------------------------

def characters() -> list[str]:
    """Everything that can be cast: the saved characters with a picture, then the drawn ones."""
    saved = [n for n in talking.list_profiles() if talking.load_profile(n).image]
    return saved + list(BUILT_IN)


def character(name: str) -> Character:
    if name in BUILT_IN:
        return BUILT_IN[name][0]
    profile = talking.load_profile(name)
    return Character(name, profile.kind, profile.flying, tuple(profile.names or actions.names_for(name)), profile.size)


def _changed(name: str) -> float:
    folder = talking.profile_dir(name)
    return max((f.stat().st_mtime for f in folder.iterdir()), default=0.0) if folder.exists() else 0.0


@lru_cache(maxsize=12)
def _look(name: str, changed: float) -> stage.Look:
    if name in BUILT_IN:
        return BUILT_IN[name][1]()
    profile = talking.load_profile(name)
    folder = talking.profile_dir(name)
    looks = {}
    with Image.open(folder / profile.image) as source:
        main = ImageOps.exif_transpose(source).convert("RGBA")
    for pose, file in profile.looks.items():
        if (folder / file).exists():
            with Image.open(folder / file) as source:
                looks[pose] = align(main, ImageOps.exif_transpose(source).convert("RGBA"))
    return stage.Look.from_profile(name, looks)


def align(main: Image.Image, frame: Image.Image) -> Image.Image:
    """A frame moved so that the character stands exactly where it stands in the main picture: frames made one by
    one are often a few pixels off, and it would twitch at every change. The head and the shoulders are matched
    (they do not change between poses); a frame too different is left as it is."""
    frame = frame.resize(main.size, Image.LANCZOS) if frame.size != main.size else frame
    w, h = main.size
    k = max(1, max(w, h) // 512)
    box = main.getbbox() or (0, 0, w, h)
    rows = slice(box[1] // k, (box[1] + int(0.45 * (box[3] - box[1]))) // k)  # the head and the shoulders

    def prepared(image: Image.Image) -> np.ndarray:
        rgba = np.asarray(image.resize((w // k, h // k), Image.BILINEAR), np.float32)
        grey = np.zeros(rgba.shape[:2], np.float32)
        grey[rows] = rgba[rows, :, :3].mean(-1) * rgba[rows, :, 3] / 255
        return grey - grey[rows].mean()

    a, b = np.fft.fft2(prepared(main)), np.fft.fft2(prepared(frame))
    cross = a * np.conj(b)
    peak = np.fft.ifft2(cross / (np.abs(cross) + 1e-6)).real
    dy, dx = np.unravel_index(int(np.argmax(peak)), peak.shape)
    dy = dy - peak.shape[0] if dy > peak.shape[0] // 2 else dy
    dx = dx - peak.shape[1] if dx > peak.shape[1] // 2 else dx
    if (dx, dy) == (0, 0) or abs(dx) > 0.1 * peak.shape[1] or abs(dy) > 0.1 * peak.shape[0]:
        return frame
    moved = Image.new("RGBA", main.size)
    moved.paste(frame, (int(dx * k), int(dy * k)))
    return moved


def look(name: str) -> stage.Look:
    """Kept ready between scenes and runs: a character's drawn pictures are reused, not redrawn."""
    return _look(name, 0.0 if name in BUILT_IN else _changed(name))


def picture_for_library(data: bytes) -> tuple[Image.Image, bool]:
    """Every imported picture comes through here. Returns it and whether it has a transparent background.
    ponytail: no automatic cut-out yet; a local background-removal model would plug in here, with the user's consent."""
    with Image.open(io.BytesIO(data)) as source:
        picture = ImageOps.exif_transpose(source).convert("RGBA")
    return picture, picture.getchannel("A").getextrema()[0] < 250


def create_character(name: str, filename: str, data: bytes) -> talking.Profile:
    picture, _ = picture_for_library(data)
    profile = talking.Profile(name=safe_name(name.strip()), names=actions.names_for(name))
    profile.image = talking.store(profile, filename, data)
    if face := talking.detect_face(picture):
        profile.mouth, profile.eyes = list(face.mouth), [list(e) for e in face.eyes]
    talking.save_profile(profile)
    return profile


# --- decors --------------------------------------------------------------------------------------------------------

class Decor(BaseModel):
    name: str
    file: str = ""
    night: bool = False
    description: str = ""  # what is in it, found by the vision model and from its name: chooses it for the lyrics
    # where characters may stand, set once by the user; fractions of the picture. No zone: the old fixed ground line
    zone: tuple[float, float, float, float] | None = None  # left, far (top), right, near (bottom), for the feet
    far_size: float = 1.0  # a character at the far edge of the zone, of its size at the near edge
    obstacles: list[tuple[float, float, float, float]] = []  # objects not to stand on or behind: left, top, right, bottom
    depth: str = ""  # its nearness map (16-bit PNG next to it), found by the depth model: what is in front of whom
    ground_depth: list[float] = []  # how near the ground is, from the top of the picture to its bottom
    no_ground: bool = False  # a close-up with nowhere to stand (found by the depth model): chosen only if nothing else


BUILT_IN_DECORS = {"🎨 Grădină însorită": Decor(name="🎨 Grădină însorită", description="grădină flori iarbă soare cer zi"),
                   "🎨 Grădină noaptea": Decor(name="🎨 Grădină noaptea", night=True,
                                               description="noapte lună stele cer grădină somn vis")}


def _index() -> dict[str, Decor]:
    path = DECORS / "decoruri.json"
    if not path.exists():
        return {}
    return {k: Decor.model_validate(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def decors() -> list[str]:
    return [*(k for k, d in _index().items() if (DECORS / d.file).exists()), *BUILT_IN_DECORS]


def decor(name: str) -> Decor:
    return BUILT_IN_DECORS.get(name) or _index().get(name) or BUILT_IN_DECORS["🎨 Grădină însorită"]


def add_decor(filename: str, data: bytes) -> Decor:
    DECORS.mkdir(exist_ok=True)
    file = safe_name(Path(filename).name)
    (DECORS / file).write_bytes(data)
    picture, _ = picture_for_library(data)
    grey = np.asarray(picture.convert("L").resize((64, 36)), np.float32)
    found = {}
    if pictures.available():
        seen, _ = pictures.evidence({file: DECORS / file}, {}, lambda f, m: None)
        found = seen.get(file, {})
    item = Decor(name=Path(file).stem, file=file, night=bool(grey.mean() < 95),
                 description=" ".join(filter(None, [pictures.describe(found, 10), Path(file).stem])))
    index = _index()
    index[item.name] = item
    _save_index(index)
    if depth.available():
        analyse_decor(item.name)
    return decor(item.name)


def analyse_decor(name: str) -> depth.Analysis:
    """Look at the decor with the depth model: keep its depth map and propose where characters may stand (the user's
    own zone is replaced by the proposal; it can be corrected and saved again)."""
    item = decor(name)
    picture = _decor_picture(item.file, (DECORS / item.file).stat().st_mtime)
    nearness = depth.nearness(picture)
    found = depth.analyse(nearness)
    file = f"{Path(item.file).stem}.adancime.png"
    Image.fromarray((nearness * 65535).astype(np.uint16)).save(DECORS / file)
    index = _index()
    index[name] = item.model_copy(update={"zone": found.zone, "far_size": found.far_size, "obstacles": found.obstacles,
                                          "depth": file, "ground_depth": found.profile,
                                          "no_ground": found.zone is None})
    _save_index(index)
    return found


def _save_index(index: dict[str, Decor]) -> None:
    (DECORS / "decoruri.json").write_text(json.dumps({k: v.model_dump() for k, v in index.items()}, ensure_ascii=False,
                                                     indent=2), encoding="utf-8")


def remove_decor(name: str) -> None:
    index = _index()
    if item := index.pop(name, None):
        (DECORS / item.file).unlink(missing_ok=True)
        if item.depth:
            (DECORS / item.depth).unlink(missing_ok=True)
        _save_index(index)


def save_zone(name: str, zone: tuple[float, float, float, float] | None, far_size: float = 1.0,
              obstacles: list[tuple[float, float, float, float]] | None = None) -> None:
    """Where characters may stand in this decor, kept for every project that uses it. None: back to the fixed line."""
    index = _index()
    item = index[name]
    index[name] = item.model_copy(update={"zone": zone, "far_size": far_size, "obstacles": obstacles or []})
    _save_index(index)


def picture_size(name: str) -> tuple[int, int]:
    item = decor(name)
    return _decor_picture(item.file, (DECORS / item.file).stat().st_mtime).size


@lru_cache(maxsize=4)
def _depth_picture(file: str, changed: float) -> Image.Image:
    with Image.open(DECORS / file) as source:
        return source.convert("I;16")


def depth_of(name: str) -> tuple[Image.Image | None, list[float]]:
    """The decor's nearness map and ground profile, if it was analysed."""
    item = decor(name)
    if item.depth and (DECORS / item.depth).exists() and item.ground_depth:
        return _depth_picture(item.depth, (DECORS / item.depth).stat().st_mtime), item.ground_depth
    return None, []


@lru_cache(maxsize=6)  # each holds the depth at frame size: a few MB
def _ground(name: str, size: tuple[int, int], stamp: str) -> Ground | None:
    item = decor(name)
    return Ground.from_picture(item.zone, item.far_size, item.obstacles, picture_size(name), size, *depth_of(name))


def ground(name: str, size: tuple[int, int]) -> Ground | None:
    """The decor's zone in this frame (16:9 and 9:16 show different parts of the picture), with its depth when
    known, or None if it has no zone."""
    item = decor(name)
    if not (item.zone and item.file and (DECORS / item.file).exists()):
        return None
    return _ground(name, size, item.model_dump_json(include={"zone", "far_size", "obstacles", "depth", "ground_depth"}))


@lru_cache(maxsize=8)
def _decor_picture(file: str, changed: float) -> Image.Image:
    with Image.open(DECORS / file) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def backdrop(name: str) -> Callable[[tuple[int, int], int], Image.Image]:
    """The decor as a picture of any frame size: cropped to fill it, never stretched."""
    item = decor(name)
    if not item.file:
        return lambda size, seed: effects.garden(size, seed, night=item.night)
    picture = _decor_picture(item.file, (DECORS / item.file).stat().st_mtime)
    return lambda size, seed: picture.resize(size, Image.LANCZOS, box=crop(picture.size, size))


# --- templates -----------------------------------------------------------------------------------------------------

def templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATES.glob("*.json")) if TEMPLATES.exists() else []


def save_template(name: str, scene: AnimScene) -> None:
    """A scene that worked, kept without its times: decor, effects, camera, characters and what each one does."""
    TEMPLATES.mkdir(exist_ok=True)
    roles = []
    for role in scene.roles:
        main = role.action or (max(set(a for _, _, a in role.acts), key=[a for _, _, a in role.acts].count)
                               if role.acts else "")
        roles.append({"character": role.character, "action": main, "interaction": role.interaction, "partner": role.partner})
    data = {"decor": scene.decor, "effects": scene.effects, "camera": scene.camera, "roles": roles}
    (TEMPLATES / f"{safe_name(name)}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_template(name: str) -> dict:
    return json.loads((TEMPLATES / f"{safe_name(name)}.json").read_text(encoding="utf-8"))
