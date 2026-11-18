"""Previews for „Are mama o fetiță" with the composite pictures (mother and daughter in one picture): the cuddle
(verse 1), the play (verse 2) and the chorus. Each stanza is cut into shots on its lines, wide and close in turn,
joined by soft dissolves. The composites are never turned or bent: only the camera moves; clapping (from the
two-frame pictures) only where the lyrics are rhythmic. Nothing of the project changes.

    .venv\\Scripts\\python.exe tools\\test_compozite.py [alint] [joaca] [refren]

Writes the three videos and their contact sheets to output/teste animatie/Are mama - compozite/.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.media import probe_duration, verify_output  # noqa: E402
from baby_video_studio.models import AnimScene, Role  # noqa: E402
from baby_video_studio.planner import _plain  # noqa: E402
from etapa4_test import contact_sheet  # noqa: E402

PROJECT = "Are mama o fetita"
GIRL, MOTHER = "Fetița cu fundiță", "Mama"
FACE, PLAY, CUDDLE = "Mama și fetița - față în față", "Mama și fetița - joacă pe covor", "Mama și fetița - alint"
ROOM, MEADOW, CHORUS = "Cozy Pastel Family Living Room", "Whimsical Rainbow Meadow Symphony", "Whimsical Sunset Meadow Celebration"
OUT = projects.ROOT / "output" / "teste animatie" / "Are mama - compozite"


def previews(lines: list) -> dict[str, list[AnimScene]]:
    def at(words: str, n: int = 0) -> float:
        return [l.start for l in lines if _plain(l.text).startswith(_plain(words))][n]

    def shot(start, end, decor, camera, effects, roles, **extra) -> AnimScene:
        return AnimScene(start=start, end=end, decor=decor, camera=camera, effects=effects, roles=roles, edited=True,
                         lines=[l.text for l in lines if start <= l.start < end and l.text], **extra)

    def together(name, start, end, x=0.5):
        """A composite picture in the middle of the floor, still: mother and daughter as they were drawn."""
        return [Role(character=name, acts=[(start, end, "respira")], place=(x, 0.0))]

    def clapping(decor, start, end):
        """Side by side, close, clapping on the beat (hands apart, then together), only for rhythmic lines."""
        floor = library.ground(decor, (1920, 1080))
        across = lambda x: (x - floor.left) / (floor.right - floor.left)  # noqa: E731
        # 1.3× their usual size: standing, the mother is about 1.4× as tall as kneeling in the composite pictures
        return [Role(character=GIRL, acts=[(start, end, "palme")], place=(across(0.46), 0.0), size=1.3),
                Role(character=MOTHER, acts=[(start, end, "palme")], place=(across(0.565), 0.06), size=1.3)]

    butterflies = lambda a, b: [Role(character=f"Fluturaș {c}", acts=[(a, b, "pluteste")], size=0.5) for c in ("galben", "roz")]  # noqa: E731
    v1, cheeks, smile = at("Are ochii"), at("Obrăjori"), at("Când zâmbește")
    c1, again, pup, v2 = at("Are mama", 2), at("Are mama", 3), at("Pup pe frunte"), at("Fetița mamei")
    hands, laugh, clap, c2 = at("Dă din mâini"), at("Râde mama"), at("Batem palma"), at("Are mama", 4)
    return {
        # "Are ochii ca două stele… Obrăjori ca doi bujori, îi sărut de mii de ori": the mother caresses her cheek;
        # wide on the meadow with butterflies, then close on their faces with a few hearts
        "alint": [
            shot(v1, cheeks, MEADOW, "apropiere", [], together(CUDDLE, v1, cheeks) + butterflies(v1, cheeks)),
            shot(cheeks, smile, MEADOW, "aproape", ["Hearts"], together(CUDDLE, cheeks, smile), focus=CUDDLE)],
        # "Fetița mamei zâmbește…": face to face, smiling; "Dă din mâini…": playing on the mat, the camera gliding;
        # "Râde mama, râde fata…": close on their faces over the toys; "Batem palma, unu, doi": clapping together
        "joaca": [
            shot(v2, hands, ROOM, "apropiere", ["Twinkles"], together(FACE, v2, hands)),
            shot(hands, laugh, ROOM, "panoramare", [], together(PLAY, hands, laugh), focus=PLAY),
            shot(laugh, clap, ROOM, "aproape", ["Hearts"], together(PLAY, laugh, clap), focus=PLAY),
            shot(clap, c2, ROOM, "fix", [], clapping(ROOM, clap, c2))],
        # "Are mama o fetiță, dulce…": face to face, wide, balloons; "Are mama o fetiță… Hop, hop, hop": clapping
        # on the beat, the camera going back; "Pup pe frunte, pup pe nas": the caress, close, hearts
        "refren": [
            shot(c1, again, CHORUS, "apropiere", ["Balloons"], together(FACE, c1, again)),
            shot(again, pup, CHORUS, "departare", ["Balloons"], clapping(CHORUS, again, pup)),
            shot(pup, v2, CHORUS, "aproape", ["Balloons", "Hearts"], together(CUDDLE, pup, v2), focus=CUDDLE)],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library._look.cache_clear()
    p = projects.load(PROJECT)
    audio = projects.media_dir(p) / p.audio
    out = stage.FULL_16_9
    logo, _ = director._logo(p.logo, projects.media_dir(p) / p.logo.file, out.size) if p.logo.enabled else (None, "")
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    for name, plan in previews(director.lines_of(p.timeline, probe_duration(audio))).items():
        if wanted and name not in wanted:
            continue
        settings = p.anim.model_copy(update={"characters": sorted({r.character for s in plan for r in s.roles})})
        built = [director.build(s, settings, p.logo, plan[n - 1] if n else None) for n, s in enumerate(plan)]
        start, seconds = plan[0].start, plan[-1].end - plan[0].start
        video = OUT / f"Are mama - {name}.mp4"
        began = time.perf_counter()
        stage.render(built, audio, video, start, seconds, out, logo, fade=(0.5, 0.8),
                     on_progress=lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
        print()
        info = verify_output(video, *out.size, seconds, tolerance=0.3)
        contact_sheet(video, video.with_suffix(".jpg"), seconds, tiles=12)
        print(f"  {name}: {start:.2f}–{start + seconds:.2f} s, {info['width']}x{info['height']}, "
              f"{time.perf_counter() - began:.0f} s de randare")
        for n, s in enumerate(plan, 1):
            found = director.problems(s, settings, out.size, 0.25, plan[n - 2] if n > 1 else None)
            print(f"   cadrul {n} ({s.camera}): {[r.character for r in s.roles][:2]}",
                  {k: v for k, v in found.items() if v} or "fără probleme")


if __name__ == "__main__":
    main()
