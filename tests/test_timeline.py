import subprocess

from PIL import Image

from baby_video_studio import media, render, timeline
from baby_video_studio.models import FPS, Segment
from test_render import TINY, needs_ffmpeg

IMAGES = ["Dreamy Lamb Under the Stars.png", "Dreamy Moonlit Bunny Bedtime.png", "Dreamy Moonlit Teddy Bear Cuddle.png",
          "Mother Goodnight Kiss.png"]
LYRICS = """[Strofa 1]
Luna strălucește lin,
Fetița doarme cu ursulețul.

[Refren]
Nani, nani, puișor,
Somn ușor, somn ușor.

[Strofa 2]
Un iepuraș cu blana moale
[1:05.5] Doarme liniștit pe-o floare.

[Refren]

[Outro]
"""


def marked(times, images):
    return [Segment(text=f"rând {i}", start=t, image=image) for i, (t, image) in enumerate(zip(times, images))]


def test_every_sung_line_is_a_row_and_repeated_choruses_are_separate():
    rows = timeline.rows_from_lyrics(LYRICS)
    assert rows[0].section == timeline.INTRO and rows[0].start == 0
    assert [r.section for r in rows[1:]] == ["Strofa 1"] * 2 + ["Refren"] * 2 + ["Strofa 2"] * 2 + ["Refren"] * 2 + ["Outro"]
    assert rows[7].text == rows[3].text == "Nani, nani, puișor,", "an empty chorus header repeats the first chorus"
    assert rows[-1].text == timeline.INSTRUMENTAL


def test_only_times_written_in_the_lyrics_are_filled_in():
    rows = timeline.rows_from_lyrics(LYRICS)
    assert rows[6].start == 65.5 and rows[6].text == "Doarme liniștit pe-o floare."
    assert all(r.start is None for i, r in enumerate(rows) if i not in (0, 6)), "nothing is guessed"


def test_no_lyrics_no_rows():
    assert timeline.rows_from_lyrics("") == []


def test_suggestions_use_lyrics_story_and_reuse_chorus_images():
    rows = timeline.rows_from_lyrics(LYRICS)
    rows, _ = timeline.suggest_images(rows, IMAGES, "Introducere: o oiță printre stele.", {}, 120, 15)
    by_section = {}
    for row in rows:
        by_section.setdefault(row.section, set()).add(row.image)
    assert by_section[timeline.INTRO] == {"Dreamy Lamb Under the Stars.png"}
    assert by_section["Strofa 2"] == {"Dreamy Moonlit Bunny Bedtime.png"}
    assert {r.image for r in rows[3:5]} & {r.image for r in rows[7:9]}, "the repeated chorus reuses the first chorus"
    assert rows[6].start == 65.5, "suggesting images leaves the times alone"


def test_a_long_timed_section_is_split_at_line_boundaries():
    rows = [Segment(text="intro", section=timeline.INTRO, start=0)]
    rows += [Segment(text=f"vers {i}", section="Strofa 1", start=10 + 5 * i) for i in range(8)]
    rows, _ = timeline.suggest_images(rows, IMAGES, "", {}, 50, 15)
    assert len({r.image for r in rows[1:]}) == 3, "40 s of verse with 15 s scenes gives 3 pictures"


def test_ready_timeline_has_no_problems():
    rows = marked([0, 5, 9.5, 20], ["a.png", "b.png", "b.png", "a.png"])
    assert timeline.problems(rows, ["a.png", "b.png"], 30, 2) == []


def test_unmarked_rows_and_missing_images_are_reported():
    rows = marked([0, 5, None, 20], ["a.png", "b.png", "", "a.png"])
    errors = timeline.problems(rows, ["a.png", "b.png"], 30, 2)
    assert any("Rândurile 3 nu au" in e for e in errors) and any("Alege imaginea" in e for e in errors)


def test_rows_out_of_order_or_past_the_end_are_refused():
    assert any("ordinea" in e for e in timeline.problems(marked([0, 9, 7], ["a.png", "b.png", "a.png"]), ["a.png", "b.png"], 30, 2))
    assert any("după finalul" in e for e in timeline.problems(marked([0, 31], ["a.png", "b.png"]), ["a.png", "b.png"], 30, 2))


def test_a_picture_too_short_for_its_transition_is_refused_unless_it_continues():
    short = marked([0, 5, 6.5, 20], ["a.png", "b.png", "a.png", "b.png"])
    assert any("1.5 s" in e for e in timeline.problems(short, ["a.png", "b.png"], 30, 2))
    same = marked([0, 5, 6.5, 20], ["a.png", "b.png", "b.png", "a.png"])
    assert timeline.problems(same, ["a.png", "b.png"], 30, 2) == []


def test_scenes_start_exactly_at_the_marks_and_cover_the_song():
    rows = marked([0, 5, 9.5, 20.2], ["a.png", "b.png", "b.png", "a.png"])
    scenes = timeline.to_scenes(rows, 30 * FPS, 60, {})
    assert [s.image for s in scenes] == ["a.png", "b.png", "a.png"]
    assert [s.start_frame for s in scenes] == [0, 5 * FPS, 606], "the transition begins at the mark, never before it"
    assert scenes[0].end_frame == 5 * FPS + 60 and scenes[-1].end_frame == 30 * FPS


@needs_ffmpeg
def test_render_does_not_show_the_next_picture_before_its_mark(tmp_path):
    colors = {"rosu.png": (220, 30, 30), "albastru.png": (30, 30, 220)}
    for name, color in colors.items():
        Image.new("RGB", (800, 450), color).save(tmp_path / name)
    audio = tmp_path / "melodie.mp3"
    ffmpeg = media.find_tool("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=20", str(audio)], check=True)
    total = round(media.probe_duration(audio) * FPS)
    rows = marked([0, 12.0], list(colors))
    assert timeline.problems(rows, list(colors), total / FPS, 2) == []
    scenes = [s.model_copy(update={"particles": False}) for s in timeline.to_scenes(rows, total, 60, {})]

    output = tmp_path / "video.mp4"
    render.render_video(scenes, tmp_path, audio, output, TINY, 60)
    assert abs(media.probe_duration(output) - media.probe_duration(audio)) < 0.1

    def blue_share(second: float) -> float:
        frame = tmp_path / f"{second}.png"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", str(second), "-i", str(output), "-frames:v", "1", str(frame)], check=True)
        r, _, b = Image.open(frame).convert("RGB").getpixel((160, 90))
        return (b - 30) / 190 if r < b else 1 - (r - 30) / 190

    assert blue_share(11.8) < 0.05, "nothing of the next picture before its line starts"
    assert 0.1 < blue_share(13.0) < 0.9, "the transition runs after the mark"
    assert blue_share(14.3) > 0.95


def test_the_last_image_closes_the_video_and_is_not_used_just_before():
    rows = timeline.rows_from_lyrics(LYRICS)
    rows, _ = timeline.suggest_images(rows, IMAGES, "", {}, 120, 15)
    assert rows[-1].image == IMAGES[-1]
    assert IMAGES[-1] not in {r.image for r in rows[:-1]}
