import subprocess

import pytest
from PIL import Image

from baby_video_studio import media, planner, projects, render
from baby_video_studio.models import FPS, Scene


def have_ffmpeg() -> bool:
    try:
        media.find_tool("ffmpeg"), media.find_tool("ffprobe")
        return True
    except media.MissingToolError:
        return False


needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
ASSETS = {"sparkle": "s.mkv", "dust": "d.png", "clouds": "c.png"}
TINY = render.Format(320, 180, 30, "ultrafast", 2)


@pytest.fixture
def synthetic(tmp_path):
    """Unicode, spaces and % in every path: the names most likely to break FFmpeg."""
    folder = tmp_path / "Cântec ușor 100%"
    folder.mkdir()
    for name, color in (("fetiță cu ursuleț 100%.png", "#dd88aa"), ("oiță.jpg", "#6688dd"), ("lună.png", "#ddcc66")):
        Image.new("RGB", (800, 450), color).save(folder / name)
    audio = folder / "Somn ușor, puișor.mp3"
    subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=14.2",
                    "-ar", "44100", str(audio)], check=True)
    return folder, audio


def probe_lines(path, args):
    result = subprocess.run([media.find_tool("ffprobe"), "-v", "error", *args, str(path)], capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip()


def test_motion_expressions_are_slow_and_bounded():
    z, _, _ = render.motion_exprs("zoom_in", 3000)
    assert z.startswith(f"1+{render.MAX_ZOOM:.5f}")
    with pytest.raises(ValueError):
        render.motion_exprs("spin", 100)


def test_clip_command_has_no_paths_in_filtergraph():
    scene = Scene(image="x.png", start_frame=0, frames=300, clouds=True)
    command = render.clip_command("C:/Ș ț/100%.png", scene, render.FULL, ASSETS, "out.mp4")
    graph = command[command.index("-filter_complex") + 1]
    assert "100%" not in graph and "d=300" in graph
    assert command[command.index("-frames:v") + 1] == "300"
    assert command[:4] == ["-f", "image2", "-pattern_type", "none"]


def test_final_command_crossfade_offsets_and_audio_mapping():
    scenes = [Scene(image="a", start_frame=0, frames=330), Scene(image="b", start_frame=270, frames=360), Scene(image="c", start_frame=570, frames=330)]
    command = render.final_command(["0.mp4", "1.mp4", "2.mp4"], scenes, "song.mp3", render.FULL, "out.mp4", 60, False)
    graph = command[command.index("-filter_complex") + 1]
    assert "duration=2.000000:offset=9.000000" in graph
    assert "duration=2.000000:offset=19.000000" in graph
    assert graph.count("xfade") == 2
    assert graph.count("settb=1/30") == 3 and graph.count("setpts=PTS-STARTPTS") == 3
    assert "3:a:0" in command, "only the audio stream: Suno MP3s carry cover art as a video stream"
    assert command[command.index("-frames:v") + 1] == "900"
    assert "afade" not in graph


def test_fade_out_touches_only_video():
    scenes = [Scene(image="a", start_frame=0, frames=300)]
    command = render.final_command(["0.mp4"], scenes, "s.mp3", render.FULL, "o.mp4", 60, True)
    graph = command[command.index("-filter_complex") + 1]
    assert "fade=t=out:st=7.000:d=3" in graph
    assert "-af" not in command


def test_missing_tool_message(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", "Z:/nu-exista")
    with pytest.raises(media.MissingToolError, match="ffmpeg"):
        media.find_tool("ffmpeg")


@pytest.mark.parametrize("raw, expected", [("Somn ușor", "Somn ușor"), ("a/b\\c:d", "a_b_c_d"), ("..", "proiect"), ("CON", "_CON")])
def test_safe_name(raw, expected):
    assert projects.safe_name(raw) == expected


def test_project_round_trip_and_unique_output(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "p")
    monkeypatch.setattr(projects, "OUTPUT_DIR", tmp_path / "o")
    project = projects.Project(name="Cântec ușor", storyboard="Luna strălucește")
    projects.save(project)
    assert projects.load("Cântec ușor") == project
    first = projects.unique_output("Cântec ușor")
    first.write_bytes(b"x")
    assert projects.unique_output("Cântec ușor").name == "Cântec ușor (2).mp4"


@needs_ffmpeg
def test_audio_duration_with_unicode_path(synthetic):
    _, audio = synthetic
    assert media.probe_duration(audio) == pytest.approx(14.2, abs=0.1)


@needs_ffmpeg
def test_duration_check_rejects_wrong_length(synthetic, tmp_path):
    folder, audio = synthetic
    images = ["lună.png", "oiță.jpg"]
    scenes, _ = planner.plan("", images, media.probe_duration(audio))
    out = tmp_path / "o.mp4"
    render.render_video(scenes, folder, audio, out, TINY)
    with pytest.raises(media.RenderError, match="durata"):
        media.verify_output(out, TINY.width, TINY.height, 30)


@needs_ffmpeg
def test_real_render_end_to_end(synthetic, tmp_path):
    folder, audio = synthetic
    images = ["fetiță cu ursuleț 100%.png", "oiță.jpg", "lună.png"]
    seconds = media.probe_duration(audio)
    scenes, _ = planner.plan("O fetiță cu ursulețul. Apoi o oiță pe un nor pufos.", images, seconds, scene_seconds=8)
    assert len(scenes) == 2 and scenes[1].clouds
    output = tmp_path / "Videoclip final ă.mp4"
    steps = []
    info = render.render_video(scenes, folder, audio, output, TINY, on_progress=lambda f, m: steps.append(f))
    assert info["codec_video"] == "h264" and info["codec_audio"] == "aac" and info["fps"] == "30/1"
    assert info["duration"] == pytest.approx(seconds, abs=0.25)
    frames = probe_lines(output, ["-count_frames", "-select_streams", "v", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0"])
    assert int(frames) == round(seconds * FPS)
    assert steps == sorted(steps) and steps[-1] == 1.0
    assert not list(tmp_path.glob("*.part.mp4"))

    black = subprocess.run([media.find_tool("ffmpeg"), "-hide_banner", "-i", str(output), "-vf", "blackdetect=d=0.03:pix_th=0.08", "-an", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "black_start" not in black.stderr


@needs_ffmpeg
def test_stale_plan_is_rejected(synthetic, tmp_path):
    folder, audio = synthetic
    scenes = [Scene(image="lună.png", start_frame=0, frames=999)]
    with pytest.raises(media.RenderError, match="Refă planul"):
        render.render_video(scenes, folder, audio, tmp_path / "x.mp4", TINY)


@needs_ffmpeg
def test_broken_image_reports_error_and_leaves_no_partial(synthetic, tmp_path):
    folder, audio = synthetic
    (folder / "stricat.png").write_bytes(b"not an image")
    frames = round(media.probe_duration(audio) * FPS)
    scenes = [Scene(image="stricat.png", start_frame=0, frames=frames)]
    with pytest.raises(media.RenderError):
        render.render_video(scenes, folder, audio, tmp_path / "x.mp4", TINY)
    assert not list(tmp_path.glob("*.mp4"))
