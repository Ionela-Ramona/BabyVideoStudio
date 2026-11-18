"""The storyboard for „Are mama o fetiță", put into the project's scenes (all marked as changed by hand, so "generate
again" keeps them), then the whole video exported at 1920×1080.

    .venv\\Scripts\\python.exe tools\\storyboard_are_mama.py [--no-export]
    .venv\\Scripts\\python.exe tools\\storyboard_are_mama.py --vertical   (9:16 Shorts; the project stays as it is)

A story of a mother and her daughter, told with the composite pictures (both in one picture, never turned or bent):
every stanza is cut into shots on its lines, wide and close in turn, joined by soft dissolves; only the camera moves.
Clapping (the two standing pictures with their clapping frames) only on the rhythmic lines of the choruses and on
"Batem palma". Decors: the three rooms and the picnic, as the user chose. Times come from the project's timeline (the
lyrics synced to the MP3), found by each line's first words; the lyrics are never changed.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects  # noqa: E402
from baby_video_studio.media import probe_duration, verify_output  # noqa: E402
from baby_video_studio.models import AnimScene, Role  # noqa: E402
from baby_video_studio.planner import _plain  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402

PROJECT = "Are mama o fetita"
GIRL, MOTHER = "Fetița cu fundiță", "Mama"
FACE, PLAY, CUDDLE = "Mama și fetița - față în față", "Mama și fetița - joacă pe covor", "Mama și fetița - alint"
HUG = "Mama cu fetița în brațe"
ROOM, PARTY, NIGHT = "Cozy Pastel Family Living Room", "Colorful Music Party Playroom", "Dreamy Moonlit Nursery Retreat"
PICNIC = "Whimsical Rainbow Garden Picnic"
DECORS = [ROOM, PARTY, NIGHT, PICNIC]


VERTICAL = 1.5  # 9:16 shows the middle of a decor about 1.8× bigger: the characters grow too, to keep their proportions


def storyboard(lines: list, total: float, vertical: bool = False) -> list[AnimScene]:
    grow = VERTICAL if vertical else 1.0
    size = (1080, 1920) if vertical else (1920, 1080)

    def at(words: str, n: int = 0) -> float:
        return [l.start for l in lines if _plain(l.text).startswith(_plain(words))][n]

    def shot(section, start, end, decor, camera, effects, roles, **extra) -> AnimScene:
        return AnimScene(start=start, end=end, section=section, decor=decor, camera=camera, effects=effects,
                         roles=roles, edited=True, lines=[l.text for l in lines if start <= l.start < end and l.text],
                         **extra)

    def still(name, start, end, action="respira"):
        """A composite picture in the middle of the floor, as it was drawn; the mother holding her girl, standing, as
        tall as the standing mother next to the kneeling pictures (1.3×)."""
        return [Role(character=name, acts=[(start, end, action)], place=(0.5, 0.0), size=(1.3 if name == HUG else 1.0) * grow)]

    def pair(decor, start, end, action="palme", enters=None):
        """Mother and daughter standing side by side, close (1.3×: as tall as next to the kneeling pictures)."""
        floor = library.ground(decor, size)
        across = lambda x: (x - floor.left) / (floor.right - floor.left)  # noqa: E731
        girl, mother = (0.36, 0.64) if vertical else (0.46, 0.565)  # in the narrow frame, a little apart
        return [Role(character=GIRL, acts=[(start, end, action)], place=(across(girl), 0.0), size=1.3 * grow, enters=enters),
                Role(character=MOTHER, acts=[(start, end, action)], place=(across(mother), 0.06), size=1.3 * grow,
                     enters=enters)]

    def butterflies(a, b):
        return [Role(character=f"Fluturaș {c}", acts=[(a, b, "pluteste")], size=0.5) for c in ("galben", "roz")]

    def chorus(section, k, end, faces_camera, extra):
        """"Are mama o fetiță, dulce…": face to face; "…veselă și mititică, Hop, hop, hop, casa-i plină": clapping on
        the beat; "Pup pe frunte, pup pe nas": the caress, close. The same in every chorus, but for camera and effects."""
        a, again, pup = at("Are mama", 2 * k + 2), at("Are mama", 2 * k + 3), at("Pup pe frunte", k)
        return [shot(section, a, again, PARTY, faces_camera, ["Balloons", *extra], still(FACE, a, again), focus=FACE),
                shot(section, again, pup, PARTY, "departare", ["Balloons", *extra], pair(PARTY, again, pup)),
                shot(section, pup, end, PARTY, "aproape", ["Hearts", *extra], still(CUDDLE, pup, end), focus=CUDDLE)]

    verse1, cheeks, smile, babble = at("Are ochii"), at("Obrăjori"), at("Când zâmbește"), at("Când începe")
    verse2, hands, laugh, clap = at("Fetița mamei"), at("Dă din mâini"), at("Râde mama"), at("Batem palma")
    bridge, outro, little = at("Când ți-e somn"), at("Are mama", 8), at("Puiul mamei")
    return [
        # intro: in the bright room, they come in softly, side by side; then face to face, the camera coming closer
        shot("Intro", 0.0, at("Are mama", 1), ROOM, "apropiere", ["Hearts"], pair(ROOM, 0.0, at("Are mama", 1), "leagana", 0.3)),
        shot("Intro", at("Are mama", 1), verse1, ROOM, "prim-plan", [], still(FACE, at("Are mama", 1), verse1), focus=FACE),
        # "Are ochii ca două stele… Obrăjori ca doi bujori": the caress at the picnic, wide, then close on their faces
        shot("Strofa 1", verse1, cheeks, PICNIC, "apropiere", [], still(CUDDLE, verse1, cheeks) + butterflies(verse1, cheeks)),
        shot("Strofa 1", cheeks, smile, PICNIC, "aproape", ["Hearts"], still(CUDDLE, cheeks, smile), focus=CUDDLE),
        # "Când zâmbește mititica, râde vesel și mămica": face to face, smiling; wide, then close
        shot("Strofa 1", smile, babble, PICNIC, "panoramare", [], still(FACE, smile, babble), focus=FACE),
        shot("Strofa 1", babble, at("Are mama", 2), PICNIC, "aproape", ["Hearts"], still(FACE, babble, at("Are mama", 2)), focus=FACE),
        *chorus("Refren", 0, verse2, "apropiere", []),
        # verse 2 in the playroom: smiling face to face, then playing on the mat (the camera gliding, then close),
        # then "Batem palma, unu, doi": clapping together on the beat
        shot("Strofa 2", verse2, hands, ROOM, "apropiere", ["Twinkles"], still(FACE, verse2, hands)),
        shot("Strofa 2", hands, laugh, ROOM, "panoramare", [], still(PLAY, hands, laugh), focus=PLAY),
        shot("Strofa 2", laugh, clap, ROOM, "aproape", ["Hearts"], still(PLAY, laugh, clap), focus=PLAY),
        shot("Strofa 2", clap, at("Are mama", 4), ROOM, "fix", [], pair(ROOM, clap, at("Are mama", 4))),
        *chorus("Refren", 1, bridge, "panoramare", ["Lights"]),
        # the bridge: the night room, the mother rocking her girl slowly (at most 2°), soft lights and stars
        shot("Bridge", bridge, at("Are mama", 6), NIGHT, "prim-plan", ["Twinkles", "Lights"],
             still(HUG, bridge, at("Are mama", 6), "legana_lin"), focus=HUG),
        *chorus("Refren final", 2, outro, "apropiere", ["Confetti"]),
        # the end: face to face, close; then in her arms in the bright room, and the song's name on the screen
        shot("Final", outro, little, ROOM, "aproape", ["Hearts"], still(FACE, outro, little), focus=FACE),
        shot("Final", little, total, ROOM, "apropiere", ["Hearts"], still(HUG, little, total), title="Are mama o fetiță"),
    ]


def main() -> None:
    library._look.cache_clear()
    p = projects.load(PROJECT)
    audio = projects.media_dir(p) / p.audio
    total = probe_duration(audio)
    lines = director.lines_of(p.timeline, total)
    vertical = "--vertical" in sys.argv
    if vertical:  # the Shorts: the same story in 9:16, exported without touching the project
        settings = p.anim.model_copy(update={"aspect": "9:16", "scenes": storyboard(lines, total, vertical=True)})
        name = "animatie 9x16 (Shorts)"
    else:
        p.anim.decors = DECORS  # the gardens do not fit the song: only the rooms and the picnic
        p.anim.scenes = storyboard(lines, total)
        projects.save(p)
        settings, name = p.anim, "animatie 16x9"
    size = (1080, 1920) if vertical else (1920, 1080)
    for n, s in enumerate(settings.scenes, 1):
        print(f"{n:2}. {s.start:6.2f}–{s.end:6.2f}  {s.section:12} {s.decor[:28]:28} {s.camera:10} "
              f"{[r.character for r in s.roles][:2]}  {s.effects}")
    if "--no-export" in sys.argv:
        return
    out = projects.ROOT / "output" / f"{PROJECT} - {name}.mp4"
    began = time.perf_counter()
    director.export(settings.scenes, settings, audio, out, False, p.logo, projects.media_dir(p) / p.logo.file, p.fade_out,
                    on_progress=lambda f, m: print(f"\r  {m}   ", end="", flush=True))
    print()
    info = verify_output(out, *size, total, tolerance=0.3)
    contact_sheet(out, out.with_suffix(".jpg"), total, tiles=24)
    report = {"video": out.name, "minute_randare": round((time.perf_counter() - began) / 60, 1),
              "durata": round(info["duration"], 2), "format": f'{info["width"]}x{info["height"]} {info["codec_video"]}'}
    for n, s in enumerate(settings.scenes):
        found = director.problems(s, settings, size, 0.25, settings.scenes[n - 1] if n else None)
        report[f"cadrul {n + 1}"] = {k: v for k, v in found.items() if v} or "fără probleme"
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
