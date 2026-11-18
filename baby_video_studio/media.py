import json
import os
import shutil
import subprocess
from pathlib import Path

from .models import FPS

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RenderError(Exception):
    pass


class MissingToolError(RenderError):
    pass


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # winget updates PATH only for newly started programs
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for candidate in winget.glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"):
        return str(candidate)
    raise MissingToolError(
        f"Nu găsesc programul {name}. Instalează FFmpeg cu comanda: "
        "winget install Gyan.FFmpeg.Essentials, apoi repornește aplicația."
    )


def _probe(path: Path, entries: str) -> dict:
    result = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RenderError(f"Nu pot citi fișierul {Path(path).name}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def probe_duration(path: Path) -> float:
    try:
        duration = float(_probe(path, "format=duration")["format"]["duration"])
    except (KeyError, ValueError):
        raise RenderError(f"Nu pot afla durata fișierului {Path(path).name}.") from None
    if duration <= 0:
        raise RenderError(f"Fișierul {Path(path).name} nu conține sunet.")
    return duration


def probe_video(path: Path) -> dict:
    data = _probe(path, "format=duration:stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate")
    streams = {s["codec_type"]: s for s in data.get("streams", [])}
    video, audio = streams.get("video"), streams.get("audio")
    if not video or not audio:
        raise RenderError("Videoclipul final nu are atât imagine, cât și sunet.")
    return {
        "codec_video": video["codec_name"], "codec_audio": audio["codec_name"],
        "width": video["width"], "height": video["height"],
        "pix_fmt": video["pix_fmt"], "fps": video["r_frame_rate"], "duration": float(data["format"]["duration"]),
    }


def verify_output(path: Path, width: int, height: int, expected_seconds: float, tolerance: float = 0.25) -> dict:
    """Check the finished file against the export spec; raise on the first mismatch."""
    info = probe_video(path)
    duration = info["duration"]
    expected = {
        "codec_video": "h264", "codec_audio": "aac", "width": width, "height": height,
        "pix_fmt": "yuv420p", "fps": f"{FPS}/1",
    }
    for key, value in expected.items():
        if info[key] != value:
            raise RenderError(f"Verificare eșuată: {key} este {info[key]}, trebuia {value}.")
    if abs(duration - expected_seconds) > tolerance:
        raise RenderError(f"Verificare eșuată: durata este {duration:.2f} s, trebuia {expected_seconds:.2f} s.")
    return info
