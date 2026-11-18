"""Prototype: one garden scene, 20 s of "Țup, țup, iepuraș", five characters moving at once.

    .venv\\Scripts\\python.exe tools\\prototip_animatie.py [--preview] [--only 16x9|9x16]

Writes to output/teste animatie/ and reports render time, memory, overlaps and characters leaving the frame.
The scene is written by hand here; choosing it automatically from the lyrics is the next stage.
"""
import ctypes
import ctypes.wintypes
import json
import sys
import time
from itertools import combinations
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import effects, render, stage  # noqa: E402
from baby_video_studio.models import LogoSettings  # noqa: E402
from baby_video_studio.projects import ROOT  # noqa: E402
from baby_video_studio.stage import Act, Actor, Follow, Move, Scene  # noqa: E402

SONG = ROOT / "projects" / "Top, top" / "media" / "Țup.mp3"
START, SECONDS = 18.0, 20.0
OUT = ROOT / "output" / "teste animatie"


def scene(vertical: bool, seed: int = 0) -> Scene:
    """Lyrics (song time): 19.72 Fluturașii iar apar · 21.70 Unul vine lângă el · 24.02 Îl salută frumușel ·
    28.32 Țup, țup, iepuraș · 30.68 Hai să facem câte-un pas · 32.62 Hop, hop, hop, ușurel · 35.04 Sărim toți la fel ca el"""
    ground, tall = (0.74, 0.44) if vertical else (0.88, 0.43)
    walk_to = 0.3 if vertical else 0.34
    end = START + SECONDS
    star = Actor("Steluța", stage.Look.from_profile("Steluța Muzicală"), tall, 0.24, ground, acts=[
        Act("inclina", START, 21.7),
        Act("salut", 24.0, 26.4),  # no waving picture yet: the friendly wiggle stands in
        Act("merge", 26.2, 28.3), Act("sare", 26.2, 28.3),  # walking + hopping + blinking at once
        Act("sare", 28.3, 30.7),
        Act("merge", 30.7, 32.6), Act("sare", 30.7, 32.6),  # and again, up to the other star
        Act("danseaza", 32.6, 35.0, {"mirror": 1}),  # dancing together, facing each other
        Act("sare", 35.0, end),
    ], moves=[Move(26.2, 28.3, x=walk_to), Move(30.7, 32.6, near="Steluța 2", side=-1)], blink_every=4.0)
    singer = Actor("Steluța 2", stage.Look.from_profile("Steluta Muizicala 2"), tall, 0.75, ground, sings=True, acts=[
        Act("danseaza", START, 35.0, {"mirror": -1}),  # singing + dancing at once
        Act("sare", 35.0, end, {"lag": 0.5}),  # "Sărim toți la fel ca el": hops after her, half a beat later
    ], blink_every=5.0)
    yellow = Actor("Fluturaș galben", effects.butterfly((255, 200, 90)), 0.2, -0.08, 0.34, flying=True, acts=[
        Act("zboara", 19.7, 22.5), Act("pluteste", 22.0, end),
    ], moves=[Move(19.7, 21.6, x=0.14, y=0.42 if vertical else 0.3, edge=True)], follow=Follow("Steluța", 21.7, end, side=-1, lag=0.6),
        blink_every=None)
    pink = Actor("Fluturaș roz", effects.butterfly((255, 150, 200)), 0.18, 1.08, 0.24 if not vertical else 0.4,
                 flying=True, acts=[Act("zboara", 20.2, end, {"phase": 0.5})],
                 moves=[Move(20.2, 22.4, x=0.8, edge=True)], blink_every=None)
    cloud = Actor("Norișor", effects.cloud_buddy(), 0.17, 0.5, 0.15 if not vertical else 0.24, flying=True, acts=[
        Act("pluteste", START, 35.0, {"phase": 0.3}), Act("sare", 35.0, end, {"lag": 1}),
    ], blink_every=5.5)
    return Scene(START, end, effects.garden, [star, singer, yellow, pink, cloud],
                 [effects.Clouds, effects.Twinkles, effects.Balloons, effects.Flowers, effects.Lights],
                 zoom=(1.0, 1.06), seed=seed)


class Memory(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("faults", ctypes.wintypes.DWORD), ("peak", ctypes.c_size_t),
                ("now", ctypes.c_size_t), *[(f"x{k}", ctypes.c_size_t) for k in range(6)]]


def peak_mb(handle) -> float:
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD]
    counters = Memory()
    counters.cb = ctypes.sizeof(Memory)
    ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    return counters.peak / 2 ** 20


def check(placed: list[list[stage.Placed]], size: tuple[int, int]) -> dict:
    """Frames where two characters' visible boxes meet, or a character is outside the frame (not while coming in)."""
    touching, outside = {}, {}
    for n, frame in enumerate(placed):
        for a, b in combinations(frame, 2):
            if a.box[0] < b.box[2] and b.box[0] < a.box[2] and a.box[1] < b.box[3] and b.box[1] < a.box[3]:
                touching.setdefault(f"{a.name} + {b.name}", []).append(n)
        for p in frame:
            if not p.edge and (p.box[0] < 0 or p.box[1] < 0 or p.box[2] > size[0] or p.box[3] > size[1]):
                outside.setdefault(p.name, []).append(n)
    return {"atingeri": {k: len(v) for k, v in touching.items()}, "iesiri": {k: len(v) for k, v in outside.items()}}


def make(name: str, out: stage.Output, vertical: bool) -> dict:
    settings = LogoSettings.model_validate_json((ROOT / "defaults" / "logo.json").read_text(encoding="utf-8"))
    prepared = render.prepare_logo(ROOT / "defaults" / settings.file, settings, *out.size)
    with Image.open(prepared.path) as source:
        logo = source.convert("RGBA")
    placed: list = []
    began = time.perf_counter()
    info = stage.render([scene(vertical)], SONG, OUT / name, START, SECONDS, out, stage.Logo(logo, (prepared.x, prepared.y)),
                        fade=(0.6, 1.0), placed=placed,
                        on_progress=lambda f, m: print(f"\r  {m}   ", end="", flush=True))
    seconds = time.perf_counter() - began
    print()
    return {"fisier": name, "marime": out.size, "secunde_randare": round(seconds, 1),
            "ms_pe_cadru": round(1000 * seconds / info["frames"], 1),
            "estimare_3_minute_min": round(seconds / SECONDS * 180 / 60, 1),
            "ffmpeg_varf_mb": round(peak_mb(int(info["ffmpeg"]._handle))), "tempo_bpm": round(60 / info["beat"].period),
            "micsorare_personaje": round(info["scales"][0], 2), **check(placed, out.size)}


def main() -> None:
    preview = "--preview" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    jobs = [("16x9", stage.PREVIEW_16_9 if preview else stage.FULL_16_9, False),
            ("9x16", stage.PREVIEW_9_16 if preview else stage.FULL_9_16, True)]
    report = []
    for tag, out, vertical in jobs:
        if only and tag != only:
            continue
        name = f"Prototip personaje multiple {tag}{' previzualizare' if preview else ''}.mp4"
        print(name)
        report.append(make(name, out, vertical))
    report.append({"python_varf_mb": round(peak_mb(ctypes.c_void_p(-1)))})
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
