import hashlib
import subprocess

import pytest
from PIL import Image, ImageStat

from baby_video_studio import media, planner, projects, render
from baby_video_studio.models import FPS, LogoSettings, Project, Scene
from test_render import TINY, needs_ffmpeg, synthetic  # noqa: F401 (fixture)

FULL_HD = (1920, 1080)
START = {"mode": "start", "size_percent": 15, "opacity": 85}  # the logo for the first seconds, as it was before the watermark
RED = (220, 30, 40, 255)


@pytest.fixture
def logo_png(tmp_path):
    """Opaque red centre on a fully transparent background."""
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    image.paste(RED, (100, 100, 300, 300))
    path = tmp_path / "logo ștea.png"
    image.save(path)
    return path


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "CACHE_DIR", tmp_path / "cache")


@pytest.mark.parametrize("position, expected", [
    ("top-right", (1920 - 288 - 58, 58)), ("top-left", (58, 58)), ("bottom-right", (1920 - 288 - 58, 1080 - 288 - 58)),
    ("bottom-left", (58, 1080 - 288 - 58)), ("center", (816, 396))])
def test_positions(position, expected):
    assert render.logo_position(position, *FULL_HD, 288, 288) == expected


def test_defaults_match_the_request():
    logo = LogoSettings()
    assert (logo.mode, logo.size_percent, logo.position, logo.opacity) == ("always", 8, "top-right", 65), "a small watermark"
    assert (logo.seconds, logo.fade_in, logo.fade_out) == (3, 0.7, 0.7)
    assert not logo.enabled


def test_logos_saved_before_the_watermark_take_its_defaults_unless_changed():
    old = LogoSettings.model_validate({"file": "l.png", "enabled": True, "seconds": 3.5, "size_percent": 15, "opacity": 85,
                                       "position": "top-right", "fade_in": 0.7, "fade_out": 0.7})
    assert (old.mode, old.size_percent, old.opacity, old.seconds, old.enabled) == ("always", 8, 65, 3.5, True)
    mine = LogoSettings.model_validate({"file": "l.png", "size_percent": 20, "opacity": 50})
    assert (mine.size_percent, mine.opacity) == (20, 50), "values the user chose are kept"
    saved = LogoSettings(mode="start", size_percent=15, opacity=85)
    assert LogoSettings.model_validate_json(saved.model_dump_json()) == saved, "new saves are read back as they are"


def test_watermark_lasts_the_whole_video_without_fading_out(logo_png):
    prepared = render.prepare_logo(logo_png, LogoSettings(mode="always"), *FULL_HD)
    inputs, graph = render._logo_overlay(1, prepared, 180, "v", "o")
    assert inputs[inputs.index("-t") + 1] == "180.000" and "fade=t=in" in graph and "fade=t=out" not in graph


def test_prepared_png_keeps_transparency_and_applies_opacity(logo_png):
    prepared = render.prepare_logo(logo_png, LogoSettings(**START), *FULL_HD)
    image = Image.open(prepared.path)
    assert image.size == (288, 288)
    assert image.getpixel((0, 0))[3] == 0
    center = image.getpixel((144, 144))
    assert center[:3] == RED[:3] and center[3] == round(255 * 0.85)


def test_jpg_keeps_its_background(tmp_path):
    path = tmp_path / "logo.jpg"
    Image.new("RGB", (300, 300), "white").save(path)
    prepared = render.prepare_logo(path, LogoSettings(opacity=100), *FULL_HD)
    assert Image.open(prepared.path).getpixel((1, 1))[3] == 255


def test_tall_logo_always_fits(tmp_path):
    path = tmp_path / "t.png"
    Image.new("RGB", (100, 1000)).save(path)
    prepared = render.prepare_logo(path, LogoSettings(size_percent=40), *FULL_HD)
    assert Image.open(prepared.path).height <= 864


def test_broken_logo_is_a_clear_error(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"nu e imagine")
    with pytest.raises(media.RenderError, match="logo"):
        render.prepare_logo(path, LogoSettings(), *FULL_HD)


def test_logo_changes_only_the_picture_filter(logo_png):
    scenes = [Scene(image="a", start_frame=0, frames=330), Scene(image="b", start_frame=270, frames=360)]
    prepared = render.prepare_logo(logo_png, LogoSettings(**START), *FULL_HD)
    plain = render.final_command(["0.mp4", "1.mp4"], scenes, "song.mp3", render.FULL, "o.mp4", 60, False)
    with_logo = render.final_command(["0.mp4", "1.mp4"], scenes, "song.mp3", render.FULL, "o.mp4", 60, False, prepared)
    graph = with_logo[with_logo.index("-filter_complex") + 1]
    assert plain[plain.index("-filter_complex") + 1].split(";[x1]")[0] in graph
    assert "fade=t=in:st=0:d=0.700:alpha=1" in graph and "fade=t=out:st=2.300:d=0.700:alpha=1" in graph
    assert "eof_action=pass" in graph
    assert "2:a:0" in with_logo and with_logo[with_logo.index("-frames:v") + 1] == "630"
    assert with_logo[with_logo.index("-c:a"):] == plain[plain.index("-c:a"):]


def test_fades_never_exceed_the_logo_duration(logo_png):
    prepared = render.prepare_logo(logo_png, LogoSettings(mode="start", seconds=1, fade_in=2, fade_out=2), *FULL_HD)
    _, graph = render._logo_overlay(1, prepared, 100, "v", "o")
    assert "d=0.500" in graph and "st=0.500" in graph


def test_zero_fades_are_skipped(logo_png):
    prepared = render.prepare_logo(logo_png, LogoSettings(fade_in=0, fade_out=0), *FULL_HD)
    assert "fade" not in render._logo_overlay(1, prepared, 100, "v", "o")[1]


def test_defaults_round_trip(tmp_path, monkeypatch, logo_png):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "p")
    monkeypatch.setattr(projects, "DEFAULTS_DIR", tmp_path / "d")
    first = Project(name="Primul")
    first.logo.file = projects.store_file(first, projects.LOGO_PREFIX + logo_png.name, logo_png.read_bytes())
    first.logo.enabled, first.logo.opacity, first.logo.position = True, 70, "center"
    projects.save_logo_defaults(first)
    second = Project(name="Al doilea ă")
    projects.apply_logo_defaults(second)
    assert second.logo == first.logo
    assert (projects.media_dir(second) / second.logo.file).read_bytes() == logo_png.read_bytes()


def test_no_defaults_leaves_logo_off(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "DEFAULTS_DIR", tmp_path / "nu-exista")
    project = Project(name="x")
    projects.apply_logo_defaults(project)
    assert project.logo == LogoSettings()


def frame_at(video, seconds, target):
    subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-y", "-ss", str(seconds), "-i", str(video), "-frames:v", "1", str(target)], check=True)
    return Image.open(target).convert("RGB")


def count_frames(video):
    result = subprocess.run([media.find_tool("ffprobe"), "-v", "error", "-count_frames", "-select_streams", "v",
                             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    return int(result.stdout.strip())


def audio_md5(video):
    result = subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-i", str(video), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True)
    return result.stdout.strip()


def mean_in_logo(frame, logo):
    size = Image.open(logo.path).width
    box = (logo.x + size // 3, logo.y + size // 3, logo.x + 2 * size // 3, logo.y + 2 * size // 3)
    return ImageStat.Stat(frame.crop(box)).mean


def render_pair(folder, audio, tmp_path, logo_png, settings):
    seconds = media.probe_duration(audio)
    scenes, _ = planner.plan("", ["lună.png", "oiță.jpg"], seconds, scene_seconds=8)
    plain = tmp_path / "plain.mp4"
    marked = tmp_path / "marked.mp4"
    render.render_video(scenes, folder, audio, plain, TINY)
    render.render_video(scenes, folder, audio, marked, TINY, logo_file=logo_png, logo=settings)
    return plain, marked, render.prepare_logo(logo_png, settings, TINY.width, TINY.height)


@needs_ffmpeg
def test_real_render_shows_logo_only_in_the_first_seconds(synthetic, tmp_path, logo_png):  # noqa: F811
    folder, audio = synthetic
    settings = LogoSettings(enabled=True, mode="start", opacity=100, size_percent=30)
    plain, marked, prepared = render_pair(folder, audio, tmp_path, logo_png, settings)
    assert count_frames(plain) == count_frames(marked) == round(media.probe_duration(audio) * FPS)

    hold = mean_in_logo(frame_at(marked, 1.5, tmp_path / "a.png"), prepared)
    assert hold[0] > 170 and hold[1] < 80 and hold[2] < 90, hold

    for seconds, name in ((0, "start"), (3.6, "after")):
        with_logo = mean_in_logo(frame_at(marked, seconds, tmp_path / f"{name}1.png"), prepared)
        without = mean_in_logo(frame_at(plain, seconds, tmp_path / f"{name}2.png"), prepared)
        assert all(abs(a - b) < 8 for a, b in zip(with_logo, without)), (seconds, with_logo, without)


@needs_ffmpeg
def test_logo_on_existing_mp4_copies_audio_and_keeps_length(synthetic, tmp_path, logo_png):  # noqa: F811
    folder, audio = synthetic
    seconds = media.probe_duration(audio)
    scenes, _ = planner.plan("", ["lună.png"], seconds, scene_seconds=8)
    source = tmp_path / "Videoclip ă.mp4"
    render.render_video(scenes, folder, audio, source, TINY)
    before = hashlib.sha1(source.read_bytes()).hexdigest()

    output = tmp_path / "Videoclip ă - cu logo.mp4"
    settings = LogoSettings(enabled=True, opacity=100, size_percent=30)
    info = render.add_logo_to_video(source, logo_png, settings, output)
    assert hashlib.sha1(source.read_bytes()).hexdigest() == before
    assert audio_md5(source) == audio_md5(output)
    assert count_frames(source) == count_frames(output)
    assert info["duration"] == pytest.approx(media.probe_video(source)["duration"], abs=0.05)
    prepared = render.prepare_logo(logo_png, settings, TINY.width, TINY.height)
    assert mean_in_logo(frame_at(output, 1.5, tmp_path / "f.png"), prepared)[0] > 170
    assert not list(tmp_path.glob("*.part.mp4"))


@needs_ffmpeg
def test_real_render_keeps_the_watermark_in_every_scene_and_transition(synthetic, tmp_path, logo_png):  # noqa: F811
    folder, audio = synthetic
    settings = LogoSettings(enabled=True, opacity=100, size_percent=30)  # always, the default
    plain, marked, prepared = render_pair(folder, audio, tmp_path, logo_png, settings)
    seconds = media.probe_duration(audio)
    assert count_frames(plain) == count_frames(marked) == round(seconds * FPS)
    for moment in (1.5, 7.0, 8.0, 9.0, seconds - 0.2):  # intro, before, during and after a transition, last frame
        red = mean_in_logo(frame_at(marked, moment, tmp_path / f"w{moment}.png"), prepared)
        assert red[0] > 170 and red[1] < 80 and red[2] < 90, (moment, red)
    assert audio_md5(plain) == audio_md5(marked), "the song is the same"


@needs_ffmpeg
def test_watermark_on_an_existing_vertical_video(tmp_path, logo_png):
    """9:16 (Reels): the size and the 3% margin follow the video's own width."""
    source = tmp_path / "reel.mp4"
    subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x6688dd:s=360x640:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(source)], check=True)
    settings = LogoSettings(enabled=True, opacity=100, size_percent=30)
    output = tmp_path / "reel - cu logo.mp4"
    info = render.add_logo_to_video(source, logo_png, settings, output)
    assert (info["width"], info["height"]) == (360, 640)
    prepared = render.prepare_logo(logo_png, settings, 360, 640)
    assert (prepared.x, prepared.y) == (360 - 108 - 11, 11), "top right, 3% of the width from the edges"
    assert mean_in_logo(frame_at(output, 1.9, tmp_path / "end.png"), prepared)[0] > 170, "still there at the end"
