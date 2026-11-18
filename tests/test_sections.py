import subprocess

import pytest
from PIL import Image

from baby_video_studio import media, planner, render
from baby_video_studio.models import FPS
from test_render import TINY, needs_ffmpeg

IMAGES = ["Dreamy Lamb Under the Stars.png", "Dreamy Moonlit Bunny Bedtime.png", "Dreamy Moonlit Teddy Bear Cuddle.png",
          "Mother Goodnight Kiss.png", "Whimsical Garden.png"]
LYRICS = """[Strofa 1]
Luna strălucește lin, fetița doarme cu ursulețul.
Cerul nopții e senin, somnul vine lin, ușor.

[Refren]
Nani, nani, stea de vis, ochii mici deja s-au închis.

[Strofa 2]
Un iepuraș cu blana moale doarme liniștit pe-o floare.
Fluturașii s-au culcat, toate florile-au visat.

[Refren final – soft]
Nani, nani, stea de vis, ochii mici deja s-au închis.

[Outro]
"""


def test_sections_are_read_in_order_with_their_text():
    sections = planner.parse_sections(LYRICS)
    assert [s.label for s in sections] == ["Strofa 1", "Refren", "Strofa 2", "Refren final – soft", "Outro"]
    assert "iepuraș" in sections[2].text and sections[4].text == ""
    assert sections[1].chorus and sections[3].chorus and not sections[0].chorus


def test_no_headers_means_no_sections():
    assert planner.parse_sections("Luna strălucește\n[1:15.5] Somn ușor") == []


def test_plan_covers_song_exactly_and_uses_every_image():
    scenes, _ = planner.plan("", IMAGES, 150, lyrics=LYRICS)
    assert scenes[0].start_frame == 0 and scenes[-1].end_frame == 150 * FPS
    assert {s.image for s in scenes} == set(IMAGES)
    assert all(a.image != b.image for a, b in zip(scenes, scenes[1:]))
    assert all(a.lyric_section for a in scenes) and all(s.time_source == "auto" for s in scenes)


def test_more_images_than_scenes_shortens_scenes_so_all_fit():
    images = [f"imagine {i}.png" for i in range(12)]
    scenes, warnings = planner.plan("", images, 150, scene_seconds=30, lyrics=LYRICS)
    assert {s.image for s in scenes} == set(images) and not warnings


def test_too_short_song_says_which_images_were_left_out():
    images = [f"imagine {i}.png" for i in range(12)]
    _, warnings = planner.plan("", images, 45, lyrics=LYRICS)
    assert any("Nu au intrat" in w for w in warnings)


def test_lyrics_pick_the_matching_image():
    scenes, _ = planner.plan("", IMAGES, 150, lyrics=LYRICS)
    by_section = {s.lyric_section: s.image for s in scenes}
    assert by_section["Strofa 2"] == "Dreamy Moonlit Bunny Bedtime.png"


def test_story_outweighs_lyrics_and_follows_labels():
    scenes, _ = planner.plan("Strofa 2: o oiță printre stele.", IMAGES, 150, lyrics=LYRICS)
    assert next(s for s in scenes if s.lyric_section == "Strofa 2").image == "Dreamy Lamb Under the Stars.png"


def test_unlabelled_story_runs_in_order_across_sections():
    story = "O oiță doarme. Mama îi dă un sărut. Un iepuraș doarme. Grădina visează."
    scenes, _ = planner.plan(story, IMAGES, 150, lyrics=LYRICS)
    first = {}
    for scene in scenes:
        first.setdefault(scene.lyric_section, scene.image)
    assert first["Strofa 1"] == "Dreamy Lamb Under the Stars.png"
    assert first["Refren"] == "Mother Goodnight Kiss.png"
    assert first["Strofa 2"] == "Dreamy Moonlit Bunny Bedtime.png"


def test_later_chorus_reuses_first_chorus_images():
    scenes, _ = planner.plan("", IMAGES, 300, lyrics=LYRICS)
    first = {s.image for s in scenes if s.lyric_section == "Refren"}
    final = {s.image for s in scenes if s.lyric_section == "Refren final – soft"}
    assert first & final


def test_tags_decide_when_the_filename_says_nothing():
    images = ["a.png", "b.png"]
    scenes, _ = planner.plan("O oiță doarme.", images, 20, tags={"b.png": "oiță albă, nor"})
    assert scenes[0].image == "b.png" and not scenes[0].auto_matched


def test_image_without_any_clue_is_flagged():
    scenes, _ = planner.plan("", ["a.png"], 60, lyrics="[Strofa 1]\nLuna strălucește\n[Outro]\n")
    assert all(s.auto_matched for s in scenes)


def test_times_written_in_lyrics_are_kept_exactly():
    text = "[Strofa 1]\nLuna\n[Refren]\n[1:10.5] Nani, nani\n[Outro]\nSomn"
    scenes, _ = planner.plan("", IMAGES, 150, lyrics=text)
    chorus = next(s for s in scenes if s.lyric_section == "Refren")
    assert planner.scene_cuts(scenes)[scenes.index(chorus) - 1] == round(70.5 * FPS)
    assert chorus.time_source == "lyrics"


def test_unusable_written_time_is_reported():
    _, warnings = planner.plan("", IMAGES, 100, lyrics="[Strofa 1]\nLuna\n[Refren]\n[0:01] Nani\n[Outro]\nSomn")
    assert any("Refren" in w for w in warnings)


def test_estimates_prefer_a_musical_change_near_the_expected_place():
    text = "[Strofa 1]\nLuna strălucește\n[Refren]\nLuna strălucește"
    salience = [0.0] * 1201
    salience[550] = 1.0  # 55 s, inside the window around the 60 s estimate
    scenes, _ = planner.plan("", IMAGES, 120, scene_seconds=30, salience=salience, lyrics=text)
    chorus = next(s for s in scenes if s.lyric_section == "Refren")
    assert planner.scene_cuts(scenes)[scenes.index(chorus) - 1] == 55 * FPS


@pytest.mark.parametrize("seconds", [45, 61.37, 305.01])
def test_section_timeline_has_centered_crossfades(seconds):
    scenes, _ = planner.plan("", IMAGES, seconds, crossfade_seconds=3, lyrics=LYRICS)
    assert scenes[-1].end_frame == round(seconds * FPS)
    assert all(b.start_frame == a.end_frame - 90 for a, b in zip(scenes, scenes[1:]))


@pytest.mark.parametrize("text,frames", [("1:15", 2250), ("1:15.5", 2265), ("75,5", 2265), (" 0:05 ", 150)])
def test_parse_stamp(text, frames):
    assert planner.parse_stamp(text) == frames


@pytest.mark.parametrize("text", ["", None, "abc", "1:75", "1:2:3"])
def test_parse_stamp_rejects_nonsense(text):
    assert planner.parse_stamp(text) is None


def _table(scenes, total):
    starts = [planner.stamp(c) for c in [0, *planner.scene_cuts(scenes)]]
    ends = [planner.stamp(c) for c in [*planner.scene_cuts(scenes), total]]
    return starts, ends


@pytest.fixture
def planned():
    scenes, _ = planner.plan("", IMAGES, 150, lyrics=LYRICS)
    return scenes, *_table(scenes, 150 * FPS)


def test_untouched_table_changes_nothing(planned):
    scenes, starts, ends = planned
    assert planner.apply_time_edits(scenes, starts, ends, 60, 150 * FPS) is None


def test_editing_a_start_moves_the_cut_for_both_neighbours(planned):
    scenes, starts, ends = planned
    wanted = planner.parse_stamp(starts[2]) + 45
    starts[2] = planner.stamp(wanted)
    updated = planner.apply_time_edits(scenes, starts, ends, 60, 150 * FPS)
    assert planner.scene_cuts(updated)[1] == wanted
    assert updated[2].time_source == "manual" and updated[1].time_source == "auto"
    assert updated[1].end_frame == wanted + 30 and updated[2].start_frame == wanted - 30
    assert updated[-1].end_frame == 150 * FPS


def test_editing_an_end_moves_the_same_cut(planned):
    scenes, starts, ends = planned
    wanted = planner.parse_stamp(ends[0]) - 30
    ends[0] = planner.stamp(wanted)
    assert planner.scene_cuts(planner.apply_time_edits(scenes, starts, ends, 60, 150 * FPS))[0] == wanted


def test_first_and_last_times_are_fixed(planned):
    scenes, starts, ends = planned
    with pytest.raises(ValueError):
        planner.apply_time_edits(scenes, ["0:01.0", *starts[1:]], ends, 60, 150 * FPS)
    with pytest.raises(ValueError):
        planner.apply_time_edits(scenes, starts, [*ends[:-1], "9:00.0"], 60, 150 * FPS)


@pytest.mark.parametrize("bad", ["abc", "0:00.5", "9:00.0"])
def test_bad_times_are_refused_with_a_message(planned, bad):
    scenes, starts, ends = planned
    starts[1] = bad
    with pytest.raises(ValueError):
        planner.apply_time_edits(scenes, starts, ends, 60, 150 * FPS)


def test_retime_follows_a_new_crossfade():
    scenes, _ = planner.plan("", IMAGES, 150, lyrics=LYRICS)
    cuts = planner.scene_cuts(scenes)
    updated = planner.retime(scenes, cuts, 120, 150 * FPS)
    assert planner.scene_cuts(updated) == cuts and planner.crossfade_of(updated) == 120


@needs_ffmpeg
def test_render_shows_each_image_at_the_edited_times(tmp_path):
    """The plan drives the real FFmpeg render: a moved cut moves the picture."""
    colors = {"rosu.png": (220, 30, 30), "albastru.png": (30, 30, 220)}
    for name, color in colors.items():
        Image.new("RGB", (800, 450), color).save(tmp_path / name)
    audio = tmp_path / "melodie.mp3"
    ffmpeg = media.find_tool("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=20", str(audio)], check=True)
    total = round(media.probe_duration(audio) * FPS)
    scenes, _ = planner.plan("", list(colors), media.probe_duration(audio), scene_seconds=10, crossfade_seconds=1,
                             lyrics="[Strofa 1]\nLuna\n[Refren]\nNani")
    assert len(scenes) == 2
    scenes = [s.model_copy(update={"particles": False, "clouds": False}) for s in scenes]
    moved = planner.apply_time_edits(scenes, [planner.stamp(0), "0:16.0"], ["0:16.0", planner.stamp(total)], 30, total)

    output = tmp_path / "video.mp4"
    render.render_video(moved, tmp_path, audio, output, TINY, 30)
    assert abs(media.probe_duration(output) - media.probe_duration(audio)) < 0.1

    def red_is_stronger(second: float) -> bool:
        frame = tmp_path / f"{second}.png"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", str(second), "-i", str(output), "-frames:v", "1", str(frame)], check=True)
        r, _, b = Image.open(frame).convert("RGB").getpixel((160, 90))
        return r > b

    expected_first = red_is_stronger(0.5)
    assert red_is_stronger(14) == expected_first, "the cut moved to 16 s, so the first picture must still show at 14 s"
    assert red_is_stronger(18) != expected_first
