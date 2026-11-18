"""Test for „Are mama o fetiță": the intro and the start of the first verse (0–20 s of the real song), as the
storyboard asks, in the style without deformation, 1920×1080 with the project's logo. Nothing of the project changes.

    .venv\\Scripts\\python.exe tools\\test_are_mama.py

Scene 1 (0–9.1 s, "Are mama o fetiță"): the bright room; mother and daughter come in softly, together, smiling; the
camera comes slowly closer; they sway a little; a few hearts. Scene 2 (9.1–20.1 s, "Are ochii ca două stele"): the
meadow with the rainbow; the girl in front, her mother beside her; a slow close-up on the girl; butterflies.
The times are where the singing really is in the MP3 (heard by the local voice model).

Writes the video, a contact sheet, close-ups and a report to output/teste animatie/Are mama - test/.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.media import verify_output  # noqa: E402
from baby_video_studio.models import AnimScene, Role  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402

PROJECT = "Are mama o fetita"
GIRL, MOTHER = "Fetița cu fundiță", "Mama"
VERSE = 9.12  # "Are ochii ca două stele" begins
END = 20.14  # "Când zâmbește mititica" begins
OUT = projects.ROOT / "output" / "teste animatie" / "Are mama - test"


def scenes() -> list[AnimScene]:
    intro = AnimScene(start=0.0, end=VERSE, section="Intro", lines=["Are mama o fetiță"],
                      decor="Cozy Pastel Family Living Room", effects=["Hearts"], camera="apropiere", roles=[
                          Role(character=GIRL, acts=[(0.0, 4.6, "leagana"), (4.6, VERSE, "inclina")], enters=0.3,
                               place=(0.41, 0.0)),
                          Role(character=MOTHER, acts=[(0.0, 4.6, "inclina"), (4.6, VERSE, "leagana")], enters=0.3,
                               place=(0.59, 0.06))])
    verse = AnimScene(start=VERSE, end=END, section="Strofa 1", lines=["Are ochii ca două stele"],
                      decor="Whimsical Rainbow Meadow Symphony", effects=[], camera="prim-plan", focus=GIRL, roles=[
                          Role(character=GIRL, acts=[(VERSE, 14.6, "leagana"), (14.6, END, "inclina")], place=(0.38, 0.0), size=1.1),
                          Role(character=MOTHER, acts=[(VERSE, END, "inclina")], place=(0.7, 0.25)),
                          Role(character="Fluturaș galben", acts=[(VERSE, END, "pluteste")], size=0.5),
                          Role(character="Fluturaș roz", acts=[(VERSE, END, "pluteste")], size=0.5)])
    return [intro, verse]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library._look.cache_clear()
    p = projects.load(PROJECT)
    settings = p.anim.model_copy(update={"characters": [GIRL, MOTHER, "Fluturaș galben", "Fluturaș roz"]})
    audio = projects.media_dir(p) / p.audio
    out = stage.FULL_16_9
    logo, logo_key = director._logo(p.logo, projects.media_dir(p) / p.logo.file, out.size) if p.logo.enabled else (None, "")
    plan = scenes()
    built = [director.build(s, settings, p.logo, plan[n - 1] if n else None) for n, s in enumerate(plan)]
    video = OUT / "Are mama - test 0-20 s.mp4"
    began = time.perf_counter()
    stage.render(built, audio, video, 0.0, END, out, logo, fade=(0.0, 0.8),
                 on_progress=lambda f, m: print(f"\r  {m}   ", end="", flush=True))
    print()
    seconds = time.perf_counter() - began
    info = verify_output(video, *out.size, END, tolerance=0.3)
    contact_sheet(video, video.with_suffix(".jpg"), END, tiles=12)
    report = {"video": video.name, "secunde_randare": round(seconds, 1), "durata": round(info["duration"], 2),
              "format": f'{info["width"]}x{info["height"]} {info["codec_video"]} {info["fps"]} + {info["codec_audio"]}'}
    for n, s in enumerate(plan):
        found = director.problems(s, settings, out.size, 1 / 30, plan[n - 1] if n else None)
        report[f"scena {n + 1}"] = {k: v for k, v in found.items() if v} or "fără probleme"
    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
