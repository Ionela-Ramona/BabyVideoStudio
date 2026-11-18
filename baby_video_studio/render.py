"""FFmpeg rendering: one cached clip per scene, then a single crossfade + encode pass."""
import hashlib
import os
import random
import re
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fractions import Fraction
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .media import NO_WINDOW, RenderError, find_tool, probe_duration, probe_video, verify_output
from .models import FPS, LogoSettings, Scene
from .planner import trim_scenes
from .projects import ROOT

CACHE_DIR = ROOT / "cache"
CACHE_VERSION = 2
ZOOM_PER_SECOND = 0.006
MAX_ZOOM = 0.15
LOOP_SECONDS = 12
NIGHT_BLUE = "0x0b1030"
LOGO_MARGIN = 0.03  # of the video width
LOGO_MAX_HEIGHT = 0.8  # of the video height, so a tall logo always fits
PROGRESS_LINE = re.compile(r"\w+=\S*")
# pattern_type none: a "%" in a file name must not be read as a frame pattern.
IMAGE_INPUT = ["-f", "image2", "-pattern_type", "none"]


@dataclass(frozen=True)
class Format:
    width: int
    height: int
    crf: int
    preset: str
    upscale: int = 3  # zoompan rounds to whole pixels; supersampling hides the stair-stepping


FULL = Format(1920, 1080, 18, "medium")
PREVIEW = Format(640, 360, 26, "veryfast")
PREVIEW_SECONDS = 30


def run_ffmpeg(args: list[str], on_frame: Callable[[int], None] | None = None) -> None:
    command = [find_tool("ffmpeg"), "-hide_banner", "-y", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", *args]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    errors = deque(maxlen=15)
    try:
        for line in process.stdout:
            line = line.strip()
            if line.startswith("frame=") and on_frame:
                on_frame(int(line[6:]))
            elif line and not PROGRESS_LINE.fullmatch(line):
                errors.append(line)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
    if process.returncode:
        raise RenderError("FFmpeg a raportat o eroare:\n" + "\n".join(errors))


def _sprite(radius: int, rays: bool) -> Image.Image:
    size = radius * 10 + 1
    center = size // 2
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([center - radius, center - radius, center + radius, center + radius], fill=120)
    mask = mask.filter(ImageFilter.GaussianBlur(radius * 1.4))
    draw = ImageDraw.Draw(mask)
    core = max(1, radius // 2)
    draw.ellipse([center - core, center - core, center + core, center + core], fill=255)
    if rays:
        reach = radius * 4
        draw.line([center - reach, center, center + reach, center], fill=170)
        draw.line([center, center - reach, center, center + reach], fill=170)
    mask = mask.filter(ImageFilter.GaussianBlur(max(0.6, radius / 4)))
    sprite = Image.new("RGBA", (size, size), (255, 240, 190, 0))
    sprite.putalpha(mask)
    return sprite


def _scatter(sheet: Image.Image, count: int, rng: random.Random, scale: float, spare_center: bool) -> None:
    sprites = [_sprite(max(1, round(r * scale)), spare_center and r >= 3) for r in (2, 3, 4)]
    margin = sprites[-1].width
    width, height = sheet.size
    placed = 0
    while placed < count:
        x, y = rng.randrange(width - margin), rng.randrange(height - margin)
        # Characters usually sit in the lower middle of the picture; keep sparkles off faces.
        if spare_center and ((x / width - 0.5) / 0.32) ** 2 + ((y / height - 0.62) / 0.42) ** 2 < 1:
            continue
        sheet.alpha_composite(rng.choice(sprites), (x, y))
        placed += 1


def _glow(width: int, height: int, strength: float) -> Image.Image:
    radial = Image.radial_gradient("L").point(lambda v: round((255 - v) * strength)).resize((width, height), Image.BICUBIC)
    sheet = Image.new("RGBA", (width, height), (255, 225, 170, 0))
    sheet.putalpha(radial)
    return sheet


def _cloud_tile(width: int, height: int, rng: random.Random) -> Image.Image:
    """A horizontally seamless band of soft clouds, doubled so it can scroll."""
    mask = Image.new("L", (width * 3, height), 0)
    draw = ImageDraw.Draw(mask)
    for _ in range(26):
        x, y = rng.randrange(width), rng.randrange(height // 2, height)
        rx, ry = rng.randrange(width // 16, width // 7), rng.randrange(height // 6, height // 3)
        for shift in (0, width, width * 2):
            draw.ellipse([x + shift - rx, y - ry, x + shift + rx, y + ry], fill=105)
    mask = mask.filter(ImageFilter.GaussianBlur(height / 9)).crop((width, 0, width * 2, height))
    tile = Image.new("RGBA", (width * 2, height), (236, 234, 255, 0))
    alpha = Image.new("L", (width * 2, height))
    alpha.paste(mask, (0, 0))
    alpha.paste(mask, (width, 0))
    tile.putalpha(alpha)
    return tile


def ensure_assets(fmt: Format) -> dict[str, Path]:
    """Build the overlay sheets and the seamless twinkle loop once per resolution."""
    folder = CACHE_DIR / f"assets_v{CACHE_VERSION}_{fmt.width}x{fmt.height}"
    assets = {"sparkle": folder / "sparkle.mkv", "dust": folder / "dust.png", "clouds": folder / "clouds.png"}
    if all(p.exists() for p in assets.values()):
        return assets
    folder.mkdir(parents=True, exist_ok=True)
    width, height, scale = fmt.width, fmt.height, fmt.height / 1080
    rng = random.Random(1234)

    sheets = []
    for name, strength in (("a", 0.17), ("b", 0.12), ("c", 0.145)):
        sheet = _glow(width, height, strength)
        _scatter(sheet, 45, rng, scale, spare_center=True)
        sheet.save(folder / f"twinkle_{name}.png")
        sheets.append(folder / f"twinkle_{name}.png")

    dust = Image.new("RGBA", (width, height), (255, 240, 190, 0))
    _scatter(dust, 30, rng, scale, spare_center=False)
    doubled = Image.new("RGBA", (width, height * 2), (255, 240, 190, 0))
    doubled.paste(dust, (0, 0))
    doubled.paste(dust, (0, height))
    doubled.putalpha(doubled.getchannel("A").point(lambda v: round(v * 0.55)))
    doubled.save(assets["dust"])
    _cloud_tile(width, height * 2 // 5, rng).save(assets["clouds"])

    # A -> B -> C -> A: every frame is a blend of two sheets and the loop closes on itself.
    fade = LOOP_SECONDS // 3
    inputs, parts = [], []
    for i, path in enumerate([*sheets, sheets[0]]):
        inputs += [*IMAGE_INPUT, "-loop", "1", "-framerate", str(FPS), "-t", str(LOOP_SECONDS), "-i", str(path)]
        parts.append(f"[{i}:v]format=yuva420p,settb=1/{FPS}[s{i}]")
    parts.append(f"[s0][s1]xfade=transition=fade:duration={fade}:offset=0[x1]")
    parts.append(f"[x1][s2]xfade=transition=fade:duration={fade}:offset={fade}[x2]")
    parts.append(f"[x2][s3]xfade=transition=fade:duration={fade}:offset={fade * 2}[out]")
    partial = folder / "sparkle.part.mkv"
    run_ffmpeg([*inputs, "-filter_complex", ";".join(parts), "-map", "[out]", "-frames:v", str(LOOP_SECONDS * FPS),
                "-c:v", "ffv1", "-level", "3", "-slices", "4", str(partial)])
    os.replace(partial, assets["sparkle"])
    return assets


def motion_exprs(motion: str, frames: int) -> tuple[str, str, str]:
    """zoompan z/x/y expressions; a constant camera speed regardless of scene length."""
    delta = min(MAX_ZOOM, ZOOM_PER_SECOND * frames / FPS)
    progress = f"on/{max(frames - 1, 1)}"
    x_center, y_center = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if motion == "zoom_in":
        return f"1+{delta:.5f}*{progress}", x_center, y_center
    if motion == "zoom_out":
        return f"{1 + delta:.5f}-{delta:.5f}*{progress}", x_center, y_center
    if motion == "pan_right":
        return f"{1 + delta:.5f}", f"(iw-iw/zoom)*{progress}", y_center
    if motion == "pan_left":
        return f"{1 + delta:.5f}", f"(iw-iw/zoom)*(1-{progress})", y_center
    raise ValueError(motion)


def clip_command(image: Path, scene: Scene, fmt: Format, assets: dict[str, Path], output: Path) -> list[str]:
    width, height = fmt.width, fmt.height
    big_w, big_h = width * fmt.upscale, height * fmt.upscale
    seconds = f"{scene.frames / FPS:.4f}"
    zoom, x, y = motion_exprs(scene.motion, scene.frames)
    scale = height / 1080
    loop_input = [*IMAGE_INPUT, "-loop", "1", "-framerate", str(FPS), "-t", seconds, "-i"]

    inputs = [*IMAGE_INPUT, "-i", str(image)]
    graph = [f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos"
             f":out_color_matrix=bt709:out_range=tv,crop={big_w}:{big_h},format=yuv444p,"
             f"zoompan=z='{zoom}':x='{x}':y='{y}':d={scene.frames}:s={width}x{height}:fps={FPS},"
             f"format=yuv420p,setsar=1[v0]"]
    last, index = "v0", 1
    if scene.clouds:
        inputs += [*loop_input, str(assets["clouds"])]
        cloud_y = height - height * 2 // 5
        graph.append(f"[{last}][{index}:v]overlay=x='-mod(t*{7 * scale:.2f},{width})':y={cloud_y}[v{index}]")
        last, index = f"v{index}", index + 1
    if scene.particles:
        inputs += ["-stream_loop", "-1", "-t", seconds, "-i", str(assets["sparkle"])]
        graph.append(f"[{last}][{index}:v]overlay[v{index}]")
        last, index = f"v{index}", index + 1
        inputs += [*loop_input, str(assets["dust"])]
        graph.append(f"[{last}][{index}:v]overlay=x=0:y='-mod(t*{11 * scale:.2f},{height})'[v{index}]")
        last, index = f"v{index}", index + 1
    return [*inputs, "-filter_complex", ";".join(graph), "-map", f"[{last}]", "-frames:v", str(scene.frames), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", "-threads", "3",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            str(output)]


class PreparedLogo(NamedTuple):
    path: Path
    x: int
    y: int
    settings: LogoSettings


def logo_position(position: str, frame_w: int, frame_h: int, width: int, height: int) -> tuple[int, int]:
    margin = round(frame_w * LOGO_MARGIN)
    if position == "center":
        return (frame_w - width) // 2, (frame_h - height) // 2
    x = margin if position.endswith("left") else frame_w - width - margin
    y = margin if position.startswith("top") else frame_h - height - margin
    return x, y


def has_transparency(path: Path) -> bool:
    with Image.open(path) as image:
        return image.convert("RGBA").getchannel("A").getextrema()[0] < 255


def prepare_logo(path: Path, logo: LogoSettings, frame_w: int, frame_h: int) -> PreparedLogo:
    """Size the logo and apply its opacity once, with Pillow: its RGBA resize keeps transparent edges clean."""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except OSError:
        raise RenderError(f"Nu pot citi logo-ul {Path(path).name}. Încarcă altă imagine PNG sau JPG.") from None
    width = frame_w * logo.size_percent / 100
    height = width * image.height / image.width
    shrink = min(1.0, frame_h * LOGO_MAX_HEIGHT / height)
    width, height = max(2, round(width * shrink / 2) * 2), max(2, round(height * shrink / 2) * 2)
    resized = image.resize((width, height), Image.LANCZOS)
    resized.putalpha(resized.getchannel("A").point(lambda v: round(v * logo.opacity / 100)))
    key = hashlib.sha1(f"{width}x{height}|{logo.opacity}|{Path(path).read_bytes()!r}".encode()).hexdigest()
    prepared = CACHE_DIR / "logos" / f"{key}.png"
    prepared.parent.mkdir(parents=True, exist_ok=True)
    resized.save(prepared)
    return PreparedLogo(prepared, *logo_position(logo.position, frame_w, frame_h, width, height), logo)


def _logo_overlay(index: int, logo: PreparedLogo, video_seconds: float, base: str, out: str) -> tuple[list[str], str]:
    """Input args and filter that lay the logo over `base`, after scenes and transitions are joined, so the camera
    never moves it. A watermark stays to the last frame; otherwise every frame after the logo passes through untouched."""
    always = logo.settings.mode == "always"
    seconds = video_seconds if always else min(logo.settings.seconds, video_seconds)
    fade_out_wanted = 0.0 if always else logo.settings.fade_out
    fades = logo.settings.fade_in + fade_out_wanted
    squeeze = min(1.0, seconds / fades) if fades else 1.0
    fade_in, fade_out = logo.settings.fade_in * squeeze, fade_out_wanted * squeeze
    chain = f"[{index}:v]scale=iw:ih:out_color_matrix=bt709:out_range=tv,format=yuva420p"
    if fade_in:
        chain += f",fade=t=in:st=0:d={fade_in:.3f}:alpha=1"
    if fade_out:
        chain += f",fade=t=out:st={seconds - fade_out:.3f}:d={fade_out:.3f}:alpha=1"
    inputs = [*IMAGE_INPUT, "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}", "-i", str(logo.path)]
    return inputs, f"{chain}[logo];[{base}][logo]overlay=x={logo.x}:y={logo.y}:eof_action=pass[{out}]"


def logo_command(video: Path, logo: PreparedLogo, video_seconds: float, output: Path) -> list[str]:
    inputs, graph = _logo_overlay(1, logo, video_seconds, "0:v:0", "out")
    return ["-i", str(video), *inputs, "-filter_complex", graph, "-map", "[out]", "-map", "0:a:0", "-fps_mode", "passthrough",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", str(FPS * 2), "-bf", "2",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-c:a", "copy", "-movflags", "+faststart", str(output)]


def add_logo_to_video(video: Path, logo_file: Path, logo: LogoSettings, output: Path,
                      on_progress: Callable[[float, str], None] = lambda fraction, message: None) -> dict:
    """Overlay the logo on a finished MP4 without redoing the animation; the audio stream is copied as is."""
    source = probe_video(video)
    prepared = prepare_logo(logo_file, logo, source["width"], source["height"])
    total = round(source["duration"] * Fraction(source["fps"]))
    partial = output.with_name(output.stem + ".part.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(logo_command(video, prepared, source["duration"], partial),
                   lambda frame: on_progress(min(frame, total) / total, f"Adaug logo-ul: {frame * 100 // total}%"))
        info = probe_video(partial)
        same = all(info[key] == source[key] for key in ("width", "height", "fps", "codec_audio"))
        if not same or abs(info["duration"] - source["duration"]) > 0.25:
            raise RenderError("Verificare eșuată: videoclipul cu logo diferă de cel original.")
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)
    on_progress(1.0, "Gata!")
    return info


def final_command(clips: list[Path], scenes: list[Scene], audio: Path, fmt: Format, output: Path,
                  crossfade_frames: int, fade_out: bool, logo: PreparedLogo | None = None) -> list[str]:
    total = scenes[-1].end_frame
    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    audio_index = len(clips)
    graph = [f"[{i}:v]fps={FPS},format=yuv420p,setsar=1,settb=1/{FPS},setpts=PTS-STARTPTS[v{i}]" for i in range(len(clips))]
    last = "v0"
    for i in range(1, len(clips)):
        graph.append(f"[{last}][v{i}]xfade=transition=fade:duration={crossfade_frames / FPS:.6f}"
                     f":offset={scenes[i].start_frame / FPS:.6f}[x{i}]")
        last = f"x{i}"
    # Visuals only, and to night blue rather than black; the song is never touched.
    if fade_out:
        graph.append(f"[{last}]fade=t=out:st={max(0, total / FPS - 3):.3f}:d=3:color={NIGHT_BLUE}[faded]")
        last = "faded"
    logo_input = []
    if logo:  # after the fade, so a watermark stays clear to the last frame
        logo_input, overlay = _logo_overlay(audio_index + 1, logo, total / FPS, last, "with_logo")
        graph.append(overlay)
        last = "with_logo"
    graph.append(f"[{last}]format=yuv420p[out]")
    return [*inputs, "-i", str(audio), *logo_input, "-filter_complex", ";".join(graph),
            "-map", "[out]", "-map", f"{audio_index}:a:0",
            "-frames:v", str(total), "-t", f"{total / FPS:.6f}",
            "-c:v", "libx264", "-preset", fmt.preset, "-crf", str(fmt.crf), "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-g", str(FPS * 2), "-bf", "2", "-r", str(FPS),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]


def _clip_path(image: Path, scene: Scene, fmt: Format) -> Path:
    key = f"{CACHE_VERSION}|{hashlib.sha1(image.read_bytes()).hexdigest()}|{scene.motion}|{scene.frames}|{scene.particles}|{scene.clouds}|{fmt.width}x{fmt.height}"
    return CACHE_DIR / "clips" / f"{hashlib.sha1(key.encode()).hexdigest()}.mp4"


def _render_clip(image: Path, scene: Scene, fmt: Format, assets: dict[str, Path], clip: Path) -> None:
    partial = clip.with_suffix(".part.mp4")
    try:
        run_ffmpeg(clip_command(image, scene, fmt, assets, partial))
        os.replace(partial, clip)
    finally:
        partial.unlink(missing_ok=True)


def render_video(scenes: list[Scene], image_dir: Path, audio: Path, output: Path, fmt: Format = FULL,
                 crossfade_frames: int = 60, fade_out: bool = False, limit_frames: int | None = None,
                 on_progress: Callable[[float, str], None] = lambda fraction, message: None,
                 logo_file: Path | None = None, logo: LogoSettings | None = None) -> dict:
    prepared_logo = prepare_logo(logo_file, logo, fmt.width, fmt.height) if logo_file and logo else None
    audio_seconds = probe_duration(audio)
    if limit_frames is None:
        if scenes[-1].end_frame != round(audio_seconds * FPS):
            raise RenderError("Planul scenelor nu mai corespunde melodiei. Refă planul și încearcă din nou.")
    elif limit_frames < scenes[-1].end_frame:
        scenes = trim_scenes(scenes, limit_frames, crossfade_frames)
    for scene in scenes:
        if not (image_dir / scene.image).exists():
            raise RenderError(f"Lipsește imaginea {scene.image}. Adaug-o din nou sau alege alta în plan.")

    on_progress(0.0, "Pregătesc efectele…")
    assets = ensure_assets(fmt)
    (CACHE_DIR / "clips").mkdir(parents=True, exist_ok=True)
    clips = [_clip_path(image_dir / s.image, s, fmt) for s in scenes]
    todo = {clip: scene for clip, scene in zip(clips, scenes) if not clip.exists()}
    workers = max(1, min((os.cpu_count() or 2) // 4, 4))
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(_render_clip, image_dir / s.image, s, fmt, assets, c) for c, s in todo.items()]
        try:
            for done, future in enumerate(as_completed(futures), 1):
                future.result()
                on_progress(0.7 * done / len(futures), f"Animez scenele: {done} din {len(futures)}")
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    total = scenes[-1].end_frame
    partial = output.with_name(output.stem + ".part.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(final_command(clips, scenes, audio, fmt, partial, crossfade_frames, fade_out, prepared_logo),
                   lambda frame: on_progress(0.7 + 0.3 * min(frame, total) / total, f"Asamblez videoclipul: {frame * 100 // total}%"))
        info = verify_output(partial, fmt.width, fmt.height, total / FPS)
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)
    on_progress(1.0, "Gata!")
    return info
