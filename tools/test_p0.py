"""P0 check: 10 seconds of Fetița in a decor with a safe zone, through the same path as the app (director.build).

    .venv\\Scripts\\python.exe tools\\test_p0.py

She walks (even pace, no bounce), stops, hops, dances and waves; a butterfly follows her and Norișor floats above.
Writes 16:9 and 9:16 videos, a contact sheet of each and a report to output/teste animatie/P0/. If the decor has no
zone yet, the one below is saved for it (it can be changed later in the app, "📐 Unde stau personajele în decor").
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.models import AnimationSettings, AnimScene, Role  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402

SONG = projects.ROOT / "projects" / "Top, top" / "media" / "Țup.mp3"
START, SECONDS = 28.0, 10.0  # "Țup, țup, iepuraș, hai să facem câte-un pas…"
DECOR = "Festive Forest Glade with Flowers"
ZONE = (0.05, 0.62, 0.95, 0.96)
FAR_SIZE = 0.65
OBJECTS = [(0.0, 0.52, 0.22, 1.0), (0.1, 0.63, 0.2, 0.73), (0.8, 0.68, 1.0, 1.0), (0.78, 0.48, 1.0, 0.68)]
OUT = projects.ROOT / "output" / "teste animatie" / "P0"


def scene() -> AnimScene:
    t = START
    return AnimScene(start=t, end=t + SECONDS, decor=DECOR, effects=[], camera="fix", roles=[
        Role(character="Fetita", acts=[(t, t + 3.5, "merge"), (t + 3.5, t + 5.5, "sare"), (t + 5.5, t + 8.0, "danseaza"),
                                       (t + 8.0, t + SECONDS, "salut")]),
        Role(character="Fluturaș roz", acts=[(t, t + SECONDS, "zboara")], interaction="urmareste", partner="Fetita",
             at=t + 1.0),
        Role(character="Norișor", acts=[(t, t + SECONDS, "pluteste")]),
    ])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if library.decor(DECOR).zone is None:
        library.save_zone(DECOR, ZONE, FAR_SIZE, OBJECTS)
    report = {"zona": library.decor(DECOR).model_dump(include={"zone", "far_size", "obstacles"})}
    for aspect, out in (("16:9", stage.FULL_16_9), ("9:16", stage.FULL_9_16)):
        settings = AnimationSettings(characters=["Fetita", "Fluturaș roz", "Norișor"], decors=[DECOR], aspect=aspect)
        built = director.build(scene(), settings)
        video = OUT / f"Fetita P0 {aspect.replace(':', 'x')}.mp4"
        began = time.perf_counter()
        stage.render([built], SONG, video, START, SECONDS, out, None, fade=(0.6, 1.0),
                     on_progress=lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
        print()
        contact_sheet(video, video.with_suffix(".jpg"), SECONDS, tiles=12)
        found = director.problems(scene(), settings, out.size, step=1 / 30)
        girl = next(a for a in built.actors if a.name == "Fetita")
        report[aspect] = {"secunde_randare": round(time.perf_counter() - began, 1),
                          "fetita_sta_la": [round(girl.x, 3), round(girl.y, 3)],
                          "marime_fata_de_fata_zonei": round(built.ground.scale_at(girl.y), 2) if built.ground else None,
                          **{k: v for k, v in found.items() if v}}
    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
