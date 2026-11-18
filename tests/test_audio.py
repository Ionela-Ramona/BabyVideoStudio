import subprocess

import numpy as np
import pytest

from baby_video_studio import audio, media, planner
from baby_video_studio.models import FPS
from test_render import needs_ffmpeg

IMAGES = ["a.png", "b.png", "c.png"]
RATE = audio.SAMPLE_RATE


def spikes(seconds: float, at: list[float]) -> list[float]:
    curve = [0.0] * (int(seconds * audio.GRID_HZ) + 1)
    for moment in at:
        curve[round(moment * audio.GRID_HZ)] = 1.0
    return curve


def music_cuts(scenes, xf=60):
    return [s.start_frame + xf // 2 for s in scenes[1:]]


def test_lyric_times_only_reads_timed_lines():
    text = "[Verse]\n[0:12.5] Somn ușor\n1:15 puișor\nfără timp\n[Chorus]"
    assert audio.lyric_times(text) == [12.5, 75.0]


def test_salience_finds_section_changes():
    tone = lambda hz, level, seconds: level * np.sin(2 * np.pi * hz * np.arange(int(seconds * RATE)) / RATE)
    signal = np.concatenate([tone(220, 0.2, 20), tone(1200, 0.5, 20), tone(440, 0.1, 20)]).astype(np.float32)
    curve = audio.salience_curve(signal)
    assert abs(curve[:300].argmax() / audio.GRID_HZ - 20) < 1
    assert abs((curve[300:].argmax() + 300) / audio.GRID_HZ - 40) < 1


def test_cuts_land_on_musical_changes():
    moments = [13.0, 31.0, 44.0, 61.0]
    scenes, _ = planner.plan("", IMAGES, 75, salience=spikes(75, moments))
    assert music_cuts(scenes) == [round(m * FPS) for m in moments]
    assert all(s.music_cut for s in scenes[1:]) and not scenes[0].music_cut


def test_sync_keeps_the_requested_number_of_scenes():
    curve = list(np.random.default_rng(7).random(1625))
    synced, _ = planner.plan("", IMAGES, 162.4, salience=curve)
    even, _ = planner.plan("", IMAGES, 162.4)
    assert len(synced) == len(even)


@pytest.mark.parametrize("target", [8, 15, 30])
def test_synced_timeline_stays_valid(target):
    curve = list(np.random.default_rng(target).random(2401))
    scenes, _ = planner.plan("", IMAGES, 240, scene_seconds=target, salience=curve)
    assert scenes[0].start_frame == 0 and scenes[-1].end_frame == 7200
    for current, following in zip(scenes, scenes[1:]):
        assert following.start_frame == current.end_frame - 60
    edges = [0, *music_cuts(scenes), 7200]
    gaps = [b - a for a, b in zip(edges, edges[1:])]
    assert min(gaps) >= max(6 * FPS, round(target * FPS * 0.6))
    assert max(gaps) <= round(target * FPS * 1.5) or len(scenes) == round(240 / target)


def test_flat_music_stays_close_to_even():
    scenes, _ = planner.plan("", IMAGES, 150, salience=[0.0] * 1501)
    assert [abs(c - 15 * FPS * (i + 1)) < FPS for i, c in enumerate(music_cuts(scenes))] == [True] * (len(scenes) - 1)
    assert not any(s.music_cut for s in scenes)


def test_storyboard_timestamps_beat_the_music():
    text = "0:00 o fetiță\n1:00 o oiță\nun iepuraș doarme"
    scenes, _ = planner.plan(text, IMAGES, 120, salience=spikes(120, [52.0, 62.0]))
    assert 60 * FPS in music_cuts(scenes)
    assert not next(s for s in scenes if s.start_frame == 60 * FPS - 30).music_cut


def test_unsplittable_span_falls_back_to_even_cuts():
    scenes, _ = planner.plan("", IMAGES, 13, scene_seconds=8, crossfade_seconds=4, salience=[1.0] * 131)
    assert scenes[-1].end_frame == 390


@needs_ffmpeg
def test_analyze_unicode_file_and_timed_lyrics(tmp_path):
    path = tmp_path / "Somn ușor 100%.wav"
    subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=30", str(path)], check=True)
    plain = audio.analyze(path)
    timed = audio.analyze(path, "[0:12] Somn ușor")
    assert len(plain) == pytest.approx(301, abs=2)
    assert timed[120] > plain[120]


@needs_ffmpeg
def test_analyze_bad_file_is_a_clear_error(tmp_path):
    path = tmp_path / "stricat.mp3"
    path.write_bytes(b"not audio")
    with pytest.raises(media.RenderError):
        audio.analyze(path)
