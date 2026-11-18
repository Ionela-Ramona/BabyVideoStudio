"""„Pisicuța jucăușă": the music-mode project built from the MP3, the final lyrics and the 6 pictures, then a 1080p
preview (stanza 1 + first chorus) or, with --full, the whole video. Only the camera moves (the pictures are complete,
decor included); no sparkles; 1 s dissolves. Times come from the automatic sync; the project can then be opened in
the app to move any line's start by hand and export again.

    .venv\\Scripts\\python.exe tools\\pisicuta.py           (project + preview)
    .venv\\Scripts\\python.exe tools\\pisicuta.py --full    (project + whole video + .srt)
    .venv\\Scripts\\python.exe tools\\pisicuta.py --short   (9:16 Short: stanza 1 + first chorus)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import autosync, planner, projects, render, timeline  # noqa: E402
from baby_video_studio.media import probe_duration  # noqa: E402
from baby_video_studio.models import FPS, Project  # noqa: E402

ROOT = projects.ROOT
NAME = "Pisicuta jucausa"
AUDIO = ROOT / "input" / "audio" / "Pisicuța Jucăușă.mp3"
PICS = ROOT / "input" / "images" / "Piscuta jucausa"
HIDE, RUG, PAW, YARN, BOX, NAP = (
    "Kitten’s Peekaboo Hide-and-Seek.png", "Happy Kitten on the Lavender Rug.png", "Cheerful Kitten Greeting.png",
    "Playful Kitten and Pink Yarn Ball.png", "Peekaboo Kitten in Polka-Dot Box.png",
    "Peaceful Kitten Nap in a Cozy Playroom.png")
# (picture, camera) per section; stanza 1 changes picture at its third line („Eu o strig…").
SECTIONS = {"Strofa 2": (YARN, "pan_left"), "Strofa 3": (BOX, "zoom_in"), "Strofa 4": (NAP, "zoom_in")}
CHORUS = (PAW, "zoom_in")      # every ordinary chorus: the same scene
LAST_CHORUS = (NAP, "zoom_in")  # the gentle last chorus stays on the sleeping kitten
LYRICS = """[Strofa 1]
Pisicuța jucăușă
Se ascunde după ușă.
Eu o strig: „Unde-i pisica?”
Hop! Și-apare mititica!

[Refren]
Miau, miau, pisicuță,
Dă-mi și mie o lăbuță!
Țup, țup, pe covor,
După ghem, ușor, ușor!

[Strofa 2]
Ghemul sare, se-nvârtește,
Pisicuța îl pândește.
Dă cu laba: hop, hop, hop!
Și îl prinde dintr-un hop!

[Refren]
Miau, miau, pisicuță,
Dă-mi și mie o lăbuță!
Țup, țup, pe covor,
După ghem, ușor, ușor!

[Strofa 3]
În cutia colorată,
Pisicuța-i cocoțată.
Scoate-o labă, scoate două,
Miau! Începe-o joacă nouă!

[Refren]
Miau, miau, pisicuță,
Dă-mi și mie o lăbuță!
Țup, țup, pe covor,
După ghem, ușor, ușor!

[Strofa 4]
După-atâta alergat,
Pisicuța s-a culcat.
Toarce-ncet pe-o pernuță,
Noapte bună, pisicuță!

[Refren final – cântat mai blând]
Miau, miau, pisicuță,
Dă-mi și mie o lăbuță!
Țup, țup, pe covor,
După ghem, ușor, ușor!
"""


def pictures(rows) -> None:
    """Picture and camera for every row; instrumental rows keep the scene before them (the intro opens on HIDE)."""
    previous, line_in_stanza1, chorus_seen = (HIDE, "zoom_in"), 0, 0
    last_chorus = max(i for i, r in enumerate(rows) if planner.CHORUS.search(r.section))
    for i, row in enumerate(rows):
        if row.text == timeline.INSTRUMENTAL or row.text.startswith(timeline.EXTRA):
            pick = previous
        elif row.section == "Strofa 1":
            pick = (HIDE, "zoom_in") if line_in_stanza1 < 2 else (RUG, "pan_right")
            line_in_stanza1 += 1
        elif planner.CHORUS.search(row.section):
            pick = LAST_CHORUS if "final" in row.section.lower() else CHORUS
        else:
            pick = SECTIONS[row.section]
        row.image, row.motion = pick
        row.locked = True
        previous = pick


def build() -> tuple[Project, list, float]:
    try:
        p = projects.load(NAME)
    except FileNotFoundError:
        p = Project(name=NAME)
    p.kind, p.lyrics, p.sparkles, p.crossfade_seconds, p.fade_out = "music", LYRICS, False, 1.0, False
    p.audio = projects.store_file(p, AUDIO.name, AUDIO.read_bytes())
    p.images = [projects.store_file(p, f, (PICS / f).read_bytes()) for f in (HIDE, RUG, PAW, YARN, BOX, NAP)]
    projects.apply_logo_defaults(p)  # the channel logo the user saved in the app
    audio = projects.media_dir(p) / p.audio
    total_seconds = probe_duration(audio)
    words = autosync.hear(audio, False, lambda f, m: None)
    rows = autosync.align(timeline.rows_from_lyrics(p.lyrics), words, total_seconds)
    assert timeline.in_order(rows, total_seconds), "sync gave times out of order"
    pictures(rows)
    p.timeline, p.timing = rows, "synced"
    if errors := timeline.problems(rows, p.images, total_seconds, p.crossfade_seconds):
        sys.exit("\n".join(errors))
    p.subtitles = timeline.subtitles(rows, total_seconds, autosync.SURE)
    projects.save(p)
    total = round(total_seconds * FPS)
    scenes = timeline.to_scenes(rows, total, planner.even_crossfade_frames(p.crossfade_seconds), p.image_tags, p.sparkles)
    return p, scenes, total_seconds


def report(p: Project, scenes) -> None:
    for r in p.timeline:
        flag = " ⚠" if r.confidence is not None and r.confidence < autosync.SURE else ""
        print(f"{r.start:7.2f}  {r.section[:12]:12} {r.text[:42]:42} {r.image[:22]}{flag}")
    print("\nScenes:")
    for s in scenes:
        print(f"  {planner.stamp(s.start_frame)} – {planner.stamp(s.end_frame)}  {s.motion:9} {s.image}")


# Kitten centre (fraction of the picture width) for the vertical Short, read off the pictures.
KITTEN_X = {HIDE: 0.31, RUG: 0.42, PAW: 0.47}
SHORT_WIDE = 1.25  # the 9:16 crop would touch ears/tail, so take a wider strip and fill above/below with its blur


def vertical(src: Path, dst: Path, centre: float) -> None:
    """1080×1920 picture: a strip around the kitten across the full width, on a blurred copy (never an empty band)."""
    from PIL import Image, ImageFilter
    im = Image.open(src).convert("RGB")
    W, H = im.size
    w = round(H * 9 / 16 * SHORT_WIDE)
    x = round(min(max(centre * W - w / 2, 0), W - w))
    strip = im.crop((x, 0, x + w, H))
    back = strip.resize((1080, 1920), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    front = strip.resize((1080, round(1080 * H / w)), Image.LANCZOS)
    back.paste(front, (0, (1920 - front.height) // 2))
    back.save(dst)


def short() -> None:
    """9:16 Short: stanza 1 + the first chorus, without the instrumental intro; camera only zooms in gently."""
    import tempfile
    p, _, _ = build()
    rows = p.timeline
    begin = next(r.start for r in rows if r.section == "Strofa 1") - 0.5
    end = next(r.start for r in rows if r.section == "Strofa 2")
    rows = [r.model_copy(update={"start": max(0.0, r.start - begin), "motion": "zoom_in"})
            for r in rows if begin <= r.start < end]
    total = round((end - begin) * FPS)
    xf = planner.even_crossfade_frames(p.crossfade_seconds)
    scenes = timeline.to_scenes(rows, total, xf, p.image_tags, False)
    media = projects.media_dir(p)
    out = projects.unique_output("Pisicuța jucăușă - Short 9x16")
    (out.with_suffix(".srt")).write_text(timeline.to_srt(timeline.subtitles(rows, end - begin, autosync.SURE)),
                                         encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for s in scenes:
            vertical(media / s.image, folder / s.image, KITTEN_X[s.image])
        audio = folder / "clip.wav"  # the song's own piece, same speed/pitch; short fades so it doesn't click
        render.run_ffmpeg(["-ss", f"{begin:.3f}", "-t", f"{end - begin:.3f}", "-i", str(media / p.audio),
                           "-af", f"afade=t=in:d=0.3,afade=t=out:st={end - begin - 1:.3f}:d=1", str(audio)])
        logo = media / p.logo.file if p.logo.enabled and p.logo.file else None
        info = render.render_video(scenes, folder, audio, out, render.Format(1080, 1920, 18, "medium"), xf, False,
                                   None, lambda f, m: print(f"\r{m:50}", end="", flush=True),
                                   logo_file=logo, logo=p.logo)
    print("\n", out, info)


def main() -> None:
    if "--short" in sys.argv:
        return short()
    full = "--full" in sys.argv
    p, scenes, total_seconds = build()
    report(p, scenes)
    media = projects.media_dir(p)
    logo = media / p.logo.file if p.logo.enabled and p.logo.file else None
    if full:
        out = projects.unique_output("Pisicuța jucăușă - videoclip 16x9")
        (out.with_suffix(".srt")).write_text(timeline.to_srt(p.subtitles), encoding="utf-8")
        limit = None
    else:  # stanza 1 + the first chorus, up to the next row after it
        first = next(i for i, r in enumerate(p.timeline) if planner.CHORUS.search(r.section))
        after = next(i for i in range(first, len(p.timeline)) if not planner.CHORUS.search(p.timeline[i].section))
        limit = round(p.timeline[after].start * FPS) + FPS
        out = ROOT / "output" / "Pisicuța jucăușă - previzualizare.mp4"
    info = render.render_video(scenes, media, media / p.audio, out, render.FULL,
                               planner.even_crossfade_frames(p.crossfade_seconds), p.fade_out, limit,
                               lambda f, m: print(f"\r{m:50}", end="", flush=True), logo_file=logo, logo=p.logo)
    print("\n", out, info)


if __name__ == "__main__":
    main()
