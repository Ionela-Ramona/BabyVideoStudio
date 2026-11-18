"""Etapa 1 check: the same 12 seconds as test_p3, in the style without deformation: every picture stays exactly as it
is, on the floor; it only sways a little and steps a little aside; gestures come from frames when there are any.

    .venv\\Scripts\\python.exe tools\\test_fara_deformare.py

Writes a 16:9 video, its contact sheet and a report to output/teste animatie/Fara deformare/.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.models import AnimationSettings  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402
from test_p0 import DECOR, SONG, START  # noqa: E402
from test_p3 import CAST, SECONDS, scene  # noqa: E402

OUT = projects.ROOT / "output" / "teste animatie" / "Fara deformare"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library._look.cache_clear()
    frames = {name: sorted(library.look(name).looks) for name in CAST}
    settings = AnimationSettings(characters=list(CAST), decors=[DECOR], aspect="16:9", style="fara_deformare")
    built = director.build(scene(), settings)
    video = OUT / "Fara deformare 16x9.mp4"
    began = time.perf_counter()
    stage.render([built], SONG, video, START, SECONDS, stage.FULL_16_9, None, fade=(0.6, 1.0),
                 on_progress=lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
    print()
    contact_sheet(video, video.with_suffix(".jpg"), SECONDS, tiles=12)
    found = director.problems(scene(), settings, stage.FULL_16_9.size, step=1 / 30)
    report = {"cadre": frames, "secunde_randare": round(time.perf_counter() - began, 1),
              **{k: v for k, v in found.items() if v}}
    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
