"""Approximate musical structure: how much the music changes at each moment."""
import re
import subprocess
from pathlib import Path

import numpy as np

from .media import NO_WINDOW, RenderError, find_tool

SAMPLE_RATE = 11025
WINDOW = 2048
HOP = 512
GRID_HZ = 10
CONTEXT_SECONDS = 4
BANDS = 24
LYRIC_BONUS = 0.5
LYRIC_LINE = re.compile(r"^\s*\[?(\d{1,2}):(\d{2}(?:[.,]\d+)?)\]?")


def lyric_times(lyrics: str) -> list[float]:
    """Start times of lyric lines written as [1:15.5] or 1:15; plain lines carry no timing."""
    times = []
    for line in lyrics.splitlines():
        if match := LYRIC_LINE.match(line):
            times.append(int(match[1]) * 60 + float(match[2].replace(",", ".")))
    return times


def decode(path: Path, rate: int = SAMPLE_RATE) -> np.ndarray:
    # Only the audio stream: Suno MP3s also carry cover art.
    result = subprocess.run(
        [find_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0",
         "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
        capture_output=True, creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RenderError(f"Nu pot analiza melodia {Path(path).name}.")
    return np.frombuffer(result.stdout, np.float32)


def salience_curve(samples: np.ndarray) -> np.ndarray:
    """0..1 per grid step: high where the sound changes (sections) or a note starts."""
    length = int(len(samples) / SAMPLE_RATE * GRID_HZ) + 1
    if len(samples) < WINDOW * 4:
        return np.zeros(length)
    windows = np.lib.stride_tricks.sliding_window_view(samples, WINDOW)[::HOP] * np.hanning(WINDOW)
    power = np.cumsum(np.abs(np.fft.rfft(windows, axis=1)) ** 2, axis=1)
    edges = np.unique(np.geomspace(3, power.shape[1] - 1, BANDS + 1).astype(int))
    features = np.log1p(np.diff(power[:, edges], axis=1))

    span = int(CONTEXT_SECONDS * SAMPLE_RATE / HOP)
    totals = np.vstack([np.zeros(features.shape[1]), np.cumsum(features, axis=0)])
    novelty = np.zeros(len(features))
    if len(features) > 2 * span:
        centers = np.arange(span, len(features) - span)
        before = totals[centers] - totals[centers - span]
        after = totals[centers + span] - totals[centers]
        novelty[centers] = np.linalg.norm(after - before, axis=1) / span

    onsets = np.concatenate([[0], np.clip(np.diff(features, axis=0), 0, None).sum(axis=1)])
    grid = np.minimum((np.arange(len(features)) * HOP / SAMPLE_RATE * GRID_HZ).astype(int), length - 1)
    curve = 0.75 * _to_grid(novelty, grid, length) + 0.25 * _to_grid(onsets, grid, length)
    # Only moments that stand out from the song's usual level should attract a cut.
    baseline = np.median(curve)
    return np.clip((curve - baseline) / max(np.percentile(curve, 99) - baseline, 1e-3), 0, 1)


def _to_grid(values: np.ndarray, grid: np.ndarray, length: int) -> np.ndarray:
    pooled = np.zeros(length)
    np.maximum.at(pooled, grid, values)
    scale = np.percentile(pooled, 98)
    return np.clip(pooled / scale, 0, 1) if scale > 1e-3 else pooled


def analyze(path: Path, lyrics: str = "") -> list[float]:
    curve = salience_curve(decode(path))
    for seconds in lyric_times(lyrics):
        index = round(seconds * GRID_HZ)
        if 0 <= index < len(curve):
            curve[index] = min(1.0, curve[index] + LYRIC_BONUS)
    return curve.tolist()
