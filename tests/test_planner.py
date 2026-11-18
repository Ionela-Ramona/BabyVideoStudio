import pytest

from baby_video_studio import planner
from baby_video_studio.models import FPS

IMAGES = ["Dreamy Lamb Under the Stars.png", "Dreamy Moonlit Bunny Bedtime.png", "Dreamy Moonlit Teddy Bear Cuddle.png"]
STORY = ("At the beginning, a little girl sleeps peacefully while hugging her teddy bear. Then a blond boy appears "
         "sleeping on a fluffy cloud. Later, a cute sheep sleeps among the stars. The moon glows softly. "
         "Repeat the scenes naturally until the song ends.")


def assert_contiguous(scenes, xf):
    for current, following in zip(scenes, scenes[1:]):
        assert following.start_frame == current.end_frame - xf
        assert current.frames > xf


@pytest.mark.parametrize("seconds", [20, 61.37, 162.4, 305.01])
def test_timeline_fills_song_exactly(seconds):
    scenes, _ = planner.plan(STORY, IMAGES, seconds)
    assert scenes[0].start_frame == 0
    assert scenes[-1].end_frame == round(seconds * FPS)
    assert_contiguous(scenes, 60)


def test_crossfade_is_even_frames_and_centered_on_cuts():
    assert planner.even_crossfade_frames(2.5) == 76
    scenes, _ = planner.plan(STORY, IMAGES, 90, crossfade_seconds=3)
    assert_contiguous(scenes, 90)


def test_parse_drops_repeat_sentence_and_connectors():
    beats = planner.parse_storyboard(STORY)
    assert len(beats) == 4
    assert beats[1].text.startswith("a blond boy")


def test_scene_order_follows_storyboard_and_matches_filenames():
    scenes, _ = planner.plan(STORY, IMAGES, 162.4)
    assert scenes[0].image == IMAGES[2]
    assert scenes[1].image == IMAGES[1] and scenes[1].auto_matched and scenes[1].clouds
    assert scenes[2].image == IMAGES[0] and not scenes[2].auto_matched


def test_romanian_storyboard_with_diacritics():
    text = "O fetiță doarme cu ursulețul. Apoi o oiță doarme printre stele."
    scenes, _ = planner.plan(text, IMAGES, 40)
    assert scenes[0].image == IMAGES[2]
    assert scenes[1].image == IMAGES[0]


def test_no_image_twice_in_a_row_when_avoidable():
    scenes, _ = planner.plan(STORY, IMAGES, 300)
    assert all(a.image != b.image for a, b in zip(scenes, scenes[1:]))


def test_images_are_repeated_and_all_used_without_storyboard():
    scenes, _ = planner.plan("", IMAGES, 200)
    assert {s.image for s in scenes} == set(IMAGES)
    assert len(scenes) > len(IMAGES)


def test_scene_length_respected():
    scenes, _ = planner.plan(STORY, IMAGES, 150, scene_seconds=20)
    assert all(12 * FPS <= s.frames <= 28 * FPS for s in scenes)


def test_short_song_gets_one_scene():
    scenes, _ = planner.plan(STORY, IMAGES, 4)
    assert len(scenes) == 1 and scenes[0].frames == 120


def test_timestamps_place_scenes_precisely():
    text = "0:00 fetița cu ursulețul\n1:00 oița printre stele"
    scenes, _ = planner.plan(text, IMAGES, 120)
    anchored = next(s for s in scenes if s.description.startswith("oița"))
    assert anchored.start_frame == 60 * FPS - 30


def test_timestamp_past_end_warns():
    _, warnings = planner.plan("5:00 oița printre stele", IMAGES, 60)
    assert warnings


def test_trim_for_preview():
    scenes, _ = planner.plan(STORY, IMAGES, 162.4)
    trimmed = planner.trim_scenes(scenes, 900, 60)
    assert trimmed[-1].end_frame == 900
    assert_contiguous(trimmed, 60)


def test_no_images_is_a_clear_error():
    with pytest.raises(ValueError):
        planner.plan(STORY, [], 60)
