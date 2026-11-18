"""P2 check: 10 seconds of Fetița with her skeleton (arms and legs that bend), on the decor analysed in P1.

    .venv\\Scripts\\python.exe tools\\test_p2.py

She walks in (one knee up, then the other), claps, hops, dances and waves; a butterfly follows her. Writes 16:9 and
9:16 videos, contact sheets, a sheet of her poses and a report to output/teste animatie/P2/.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.models import AnimationSettings, AnimScene, Role  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402
from test_p0 import DECOR, SECONDS, SONG, START  # noqa: E402

OUT = projects.ROOT / "output" / "teste animatie" / "P2"
ACTS = [(0.0, 4.6, "merge"), (4.6, 6.2, "palme"), (6.2, 7.6, "sare"), (7.6, 8.9, "danseaza"), (8.9, SECONDS, "salut")]


def scene() -> AnimScene:
    t = START
    return AnimScene(start=t, end=t + SECONDS, decor=DECOR, effects=[], camera="fix", roles=[
        Role(character="Fetita", acts=[(t + a, t + b, act) for a, b, act in ACTS], enters=t),
        Role(character="Fluturaș roz", acts=[(t, t + SECONDS, "zboara")], interaction="urmareste", partner="Fetita",
             at=t + 1.0),
    ])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library._look.cache_clear()
    if library.look("Fetita").rig is None:
        sys.exit("Fetița nu are încă schelet: „🦴 Scheletul” din aplicație, „✨ Propune scheletul automat”.")
    director.pose_sheet("Fetita", 500).save(OUT / "poze.jpg")
    report = {}
    for aspect, out in (("16:9", stage.FULL_16_9), ("9:16", stage.FULL_9_16)):
        settings = AnimationSettings(characters=["Fetita", "Fluturaș roz"], decors=[DECOR], aspect=aspect)
        built = director.build(scene(), settings)
        video = OUT / f"Fetita P2 {aspect.replace(':', 'x')}.mp4"
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
