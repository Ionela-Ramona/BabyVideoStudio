"""Optional: separate the singing from the music with Demucs before listening, for songs where the music is loud.

Needs `pip install demucs` (about 1 GB with PyTorch for CPU). Runs on the CPU in short pieces, to show
progress and keep memory use low.
"""
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from .media import NO_WINDOW, RenderError, find_tool

PIECE_SECONDS = 30


def separate(audio: Path, rate: int, progress: Callable[[float, str], None]) -> np.ndarray:
    """The vocals alone, mono, at `rate`."""
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    progress(0.0, "Pregătesc separarea vocii (Demucs). Prima dată se descarcă modelul (~80 MB)…")
    model = get_model("htdemucs")
    model.eval()
    result = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(audio), "-map", "0:a:0", "-ac", "2",
                             "-ar", str(model.samplerate), "-f", "f32le", "-"], capture_output=True, creationflags=NO_WINDOW)
    if result.returncode:
        raise RenderError(f"Nu pot citi melodia {audio.name}.")
    wav = torch.from_numpy(np.frombuffer(result.stdout, np.float32).reshape(-1, 2).T.copy())
    mean, std = wav.mean(), wav.std() + 1e-8
    piece = PIECE_SECONDS * model.samplerate
    vocals = []
    torch.set_num_threads(max(1, torch.get_num_threads()))
    with torch.no_grad():
        for start in range(0, wav.shape[1], piece):
            chunk = (wav[:, start:start + piece] - mean) / std
            sources = apply_model(model, chunk[None], split=True, overlap=0.1, progress=False, device="cpu")[0]
            vocals.append((sources[model.sources.index("vocals")].mean(0) * std + mean).numpy())
            done = min(start + piece, wav.shape[1]) / wav.shape[1]
            progress(done, f"Separ vocea de muzică: {done:.0%}")
    mono = np.concatenate(vocals).astype(np.float32)
    resampled = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-f", "f32le", "-ar", str(model.samplerate), "-ac", "1",
                                "-i", "-", "-ar", str(rate), "-f", "f32le", "-"], input=mono.tobytes(), capture_output=True,
                               creationflags=NO_WINDOW)
    return np.frombuffer(resampled.stdout, np.float32)
