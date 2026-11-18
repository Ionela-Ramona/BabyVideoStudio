"""What is near and what is far in a decor, so characters stand on its ground and behind the things in front of them.

A small local depth model (Depth Anything V2 Small, Apache-2.0, ~95 MB, ONNX on the CPU, about a second per decor,
downloaded once) tells how near every pixel is. Its answer is turned here into what the animation needs:

- the ground: in a meadow, nearness grows smoothly from the horizon down to the bottom of the picture; that profile is
  found row by row, so it also gives the perspective (a character half as near looks half as big);
- the objects: everything nearer than the ground of its own row stands up from it (flowers, stones, a ball, a fence);
- a safe zone and the objects as rectangles, the same the user can set by hand, offered as a first proposal;
- the depth map itself, kept next to the decor: while drawing, whatever in the decor is nearer than a character's
  feet is drawn again over the character, so it can walk behind a flower bed.

No semantic model is used (the free ones for that are licensed for non-commercial use only); this is geometry.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image

REPO, FILE = "onnx-community/depth-anything-v2-small", "onnx/model.onnx"
SIZE = 518  # the model's working size, on the shorter side
NEAR = 0.05  # how much nearer than the ground (of 0..1) a pixel must be to count as an object standing on it
ROWS = 100  # samples of the ground profile kept with the decor


def available() -> bool:
    """The model is on this computer (no download, no network)."""
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO, FILE, local_files_only=True)
        return True
    except Exception:  # not downloaded yet, or no huggingface_hub
        return False


_session = None


def _model():
    global _session
    if _session is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 4
        _session = onnxruntime.InferenceSession(hf_hub_download(REPO, FILE), options, providers=["CPUExecutionProvider"])
    return _session


def nearness(picture: Image.Image) -> np.ndarray:
    """0 (farthest: the sky) … 1 (nearest), at the model's resolution, same proportions as the picture."""
    w, h = picture.size
    k = SIZE / min(w, h)
    size = (max(14, round(w * k / 14) * 14), max(14, round(h * k / 14) * 14))
    x = np.asarray(picture.convert("RGB").resize(size, Image.BICUBIC), np.float32) / 255
    x = (x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
    d = _model().run(None, {"pixel_values": x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
    low, high = np.percentile(d, 1), np.percentile(d, 99.5)
    return np.clip((d - low) / max(high - low, 1e-6), 0, 1).astype(np.float32)


@dataclass
class Analysis:
    profile: list[float]  # the ground's nearness, ROWS samples from the top of the picture to its bottom
    zone: tuple[float, float, float, float] | None  # left, far, right, near: fractions of the picture; None: no ground
    far_size: float
    obstacles: list[tuple[float, float, float, float]]
    horizon: float


def ground_profile(d: np.ndarray) -> tuple[np.ndarray, int]:
    """For every row, how near the ground is there: followed from the bottom of the picture upwards, always a little
    farther, through whatever stands on it (objects are nearer than the ground of their row, never farther). Where the
    ground cannot be followed any more is the horizon: above it, 0. If a strip at the bottom is not ground (a picture
    cut from a collage), it starts a little higher. Also returns the row where the ground starts."""
    h = d.shape[0]
    tries = [_follow(d, h - max(1, h // 40)), _follow(d, int(0.92 * h)), _follow(d, int(0.85 * h))]
    return max(tries, key=lambda t: t[1] - np.argmax(t[0] > 0.05) if (t[0] > 0.05).any() else -1)


def _follow(d: np.ndarray, bottom: int) -> tuple[np.ndarray, int]:
    h, w = d.shape
    g = np.zeros(h)
    g[bottom:] = np.percentile(d[bottom:bottom + max(1, h // 40)], 15)  # there the ground is the farthest thing
    for r in range(bottom - 1, -1, -1):
        row = d[r]
        follows = row[(row >= g[r + 1] - 0.03) & (row <= g[r + 1] + 0.01)]
        if len(follows) < 0.03 * w:
            break
        g[r] = min(g[r + 1], float(np.median(follows)))
    k = max(2, h // 60)
    smooth = np.convolve(np.pad(g, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), "valid")
    return np.maximum.accumulate(smooth), bottom


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Connected areas of a small mask: (left, top, right, bottom, cells), 4-neighbours."""
    seen = np.zeros_like(mask, bool)
    out = []
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, cells = [(y0, x0)], 0
        seen[y0, x0] = True
        box = [x0, y0, x0, y0]
        while stack:
            y, x = stack.pop()
            cells += 1
            box = [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((*box, cells))
    return out


def analyse(d: np.ndarray) -> Analysis:
    """From a nearness map: the ground, the safe zone (where a character is at least half its front size), the
    perspective, and the objects standing in or near the zone."""
    h, w = d.shape
    rows = np.arange(h) / h
    g, start = ground_profile(d)
    horizon = float(rows[np.argmax(g > 0.05)]) if (g > 0.05).any() else 1.0
    below = rows[:, None] > horizon
    ground = below & (np.abs(d - g[:, None]) < NEAR)
    objects = below & (d - g[:, None] > NEAR)
    share = ground.mean(1)
    near_row = int(min(start, round(0.97 * h)))
    front = max(g[near_row], 1e-3)
    usable = (share >= 0.25) & (g >= 0.5 * front) & below[:, 0]
    far_row = int(np.argmax(usable)) if usable.any() else int(0.7 * h)
    band = ground[far_row:near_row + 1]
    cols = band.mean(0) >= 0.3 if len(band) else np.zeros(w, bool)
    left, right = (np.argmax(cols) / w, (w - np.argmax(cols[::-1])) / w) if cols.any() else (0.05, 0.95)
    # objects as rectangles: on a coarse grid, the connected areas big enough to matter whose base is in the zone
    step = max(1, w // 96)
    small = objects[::step, ::step]
    obstacles = []
    for x0, y0, x1, y1, cells in _components(small):
        bottom = (y1 + 1) * step / h
        if cells * step * step >= 0.003 * h * w and bottom >= far_row / h - 0.02:
            obstacles.append(tuple(round(float(v), 3) for v in (x0 * step / w, y0 * step / h,
                                                                  min(1, (x1 + 1) * step / w), min(1, bottom))))
    profile = np.interp(np.linspace(0, 1, ROWS), rows, g)
    zone = tuple(round(float(v), 3) for v in (left, far_row / h, right, near_row / h))
    followed = g[g > 0.05]
    flat = (followed < 0.6 * front).mean() < 0.2 if len(followed) else True  # a wall, not a ground going away
    if flat or horizon > 0.85 or right - left < 0.2 or near_row - far_row < 0.05 * h or not usable.any():
        zone = None  # a close-up (a big flower, a face): no ground to stand on
    return Analysis([round(float(v), 4) for v in profile], zone,
                    round(float(np.clip(g[far_row] / front, 0.4, 1.0)), 2), obstacles, round(horizon, 3))
