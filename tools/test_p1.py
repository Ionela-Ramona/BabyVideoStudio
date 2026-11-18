"""P1 check: the same 10 seconds as test_p0, on the decor analysed by the depth model: the zone, the perspective and
the objects found by themselves, and Fetița walking in from the side, behind what is in front of her.

    .venv\\Scripts\\python.exe tools\\test_p1.py

Writes 16:9 and 9:16 videos, contact sheets, a picture of the analysis and a report to output/teste animatie/P1/.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import depth, director, library, projects, stage  # noqa: E402
from baby_video_studio.models import AnimationSettings  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402
from test_p0 import DECOR, SECONDS, SONG, START, scene  # noqa: E402

OUT = projects.ROOT / "output" / "teste animatie" / "P1"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    found = library.analyse_decor(DECOR)
    report = {"analiza_secunde": round(time.perf_counter() - began, 1), "zona": found.zone, "perspectiva": found.far_size,
              "orizont": found.horizon, "obiecte": found.obstacles}
    item = library.decor(DECOR)
    director.zone_preview(DECOR, (1280, 720), ["Fetita"], item.zone, item.far_size, item.obstacles).save(OUT / "analiza.jpg")
    nearness = library.depth_of(DECOR)[0]
    nearness.point(lambda v: v / 256).convert("L").save(OUT / "adancime.png")
    plan = scene()
    plan.roles[0].enters = START  # she walks in
    for aspect, out in (("16:9", stage.FULL_16_9), ("9:16", stage.FULL_9_16)):
        settings = AnimationSettings(characters=["Fetita", "Fluturaș roz", "Norișor"], decors=[DECOR], aspect=aspect)
        built = director.build(plan, settings)
        video = OUT / f"Fetita P1 {aspect.replace(':', 'x')}.mp4"
        began = time.perf_counter()
        stage.render([built], SONG, video, START, SECONDS, out, None, fade=(0.6, 1.0),
                     on_progress=lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
        print()
        contact_sheet(video, video.with_suffix(".jpg"), SECONDS, tiles=12)
        found_problems = director.problems(plan, settings, out.size, step=1 / 30)
        girl = next(a for a in built.actors if a.name == "Fetita")
        report[aspect] = {"secunde_randare": round(time.perf_counter() - began, 1),
                          "intra_din": "stânga" if girl.x < 0 else "dreapta" if girl.x > 1 else "nu intră (e deja acolo)",
                          "sta_la": [round(m.x, 3) for m in girl.moves if m.x is not None][:1] or [round(girl.x, 3)],
                          "adancime": round(girl.y, 3), **{k: v for k, v in found_problems.items() if v}}
    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if not depth.available():
        sys.exit("Modelul de adâncime nu e descărcat: apasă o dată „🔍 Analizează decorul automat” în aplicație.")
    main()
