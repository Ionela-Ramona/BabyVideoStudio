"""P3 check: 12 seconds of Fetița with the bunny, the fox and the chick, each with its own skeleton, on the decor
analysed in P1: ears that swing, a tail that wags, little wings that flap, heads that tilt, feet that step.

    .venv\\Scripts\\python.exe tools\\test_p3.py

Writes 16:9 and 9:16 videos, contact sheets, a sheet of each animal's poses and a report to output/teste animatie/P3/.
"""
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.models import AnimationSettings, AnimScene, Role  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402
from test_p0 import DECOR, SONG, START  # noqa: E402

SECONDS = 12.0
OUT = projects.ROOT / "output" / "teste animatie" / "P3"
CAST = {  # who does what, in seconds from the start
    "Iepuraș": [(0, 3, "leagana"), (3, 6, "sare"), (6, 9, "danseaza"), (9, 12, "palme")],
    "Fetita": [(0, 3, "inclina"), (3, 6, "palme"), (6, 9, "danseaza"), (9, 12, "salut")],
    "Vulpiță": [(0, 3, "danseaza"), (3, 6, "leagana"), (6, 9, "sare"), (9, 12, "salut")],
    "Puișor": [(0, 3, "danseaza"), (3, 6, "palme"), (6, 9, "leagana"), (9, 12, "sare")],
}


def scene() -> AnimScene:
    t = START
    return AnimScene(start=t, end=t + SECONDS, decor=DECOR, effects=[], camera="fix", roles=[
        Role(character=name, acts=[(t + a, t + b, act) for a, b, act in acts]) for name, acts in CAST.items()])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library._look.cache_clear()
    missing = [name for name in CAST if library.look(name).rig is None]
    if missing:
        sys.exit(f"Fără schelet: {', '.join(missing)}. „🦴 Scheletul personajelor”, „✨ Propune scheletul automat”.")
    sheets = [director.pose_sheet(name, 300) for name in CAST]
    sheet = Image.new("RGB", (max(s.width for s in sheets), sum(s.height for s in sheets)), (235, 240, 245))
    y = 0
    for s in sheets:
        sheet.paste(s, (0, y))
        y += s.height
    sheet.save(OUT / "poze.jpg")
    report = {}
    for aspect, out in (("16:9", stage.FULL_16_9), ("9:16", stage.FULL_9_16)):
        settings = AnimationSettings(characters=list(CAST), decors=[DECOR], aspect=aspect)
        built = director.build(scene(), settings)
        video = OUT / f"Animale P3 {aspect.replace(':', 'x')}.mp4"
        began = time.perf_counter()
        stage.render([built], SONG, video, START, SECONDS, out, None, fade=(0.6, 1.0),
                     on_progress=lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
        print()
        seconds = time.perf_counter() - began
        contact_sheet(video, video.with_suffix(".jpg"), SECONDS, tiles=12)
        found = director.problems(scene(), settings, out.size, step=1 / 30)
        report[aspect] = {"secunde_randare": round(seconds, 1), "ms_pe_cadru": round(1000 * seconds / (SECONDS * 30)),
                          **{k: v for k, v in found.items() if v}}
    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
