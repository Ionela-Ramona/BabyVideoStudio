"""Where characters may stand in a decor: a safe zone on the ground, perspective, and the objects to keep clear of.

A zone is set once per decor (in the library, by the user) in fractions of the decor's picture. Here it becomes
fractions of the frame, for 16:9 or 9:16, which show different crops of the same picture. A decor without a zone keeps
the old fixed ground line (the director then passes no `Ground`).

The rule for objects: a character may never cover one, unless it stands in front of it (its feet lower than the
object's bottom). So nobody stands on the ball or in the flower bed, but someone may stand before a tree.
When the decor's depth is known (`depth.py`), what is nearer than a character is drawn again over it (`cover`), so it
may also stand behind an object, as long as only its legs are hidden.
"""
from dataclasses import dataclass, field, replace

import numpy as np
from PIL import Image

Box = tuple[float, float, float, float]  # left, top, right, bottom
CENTERING = (0.5, 0.6)  # how a decor is cropped to fill the frame: a little more of the ground than of the sky
HIDDEN = 0.4  # with a known depth, an object in front may hide this much of a character, from its feet up
NEARER = 0.05  # of the depth's 0..1: a pixel this much nearer than the ground under the feet is in front
SOFT = 0.03  # the edge of what is in front, for smooth outlines


def crop(picture: tuple[int, int], frame: tuple[int, int]) -> Box:
    """The part of the picture that fills the frame, in the picture's pixels (as `ImageOps.fit` cuts it)."""
    (pw, ph), (fw, fh) = picture, frame
    w, h = (ph * fw / fh, ph) if pw / ph >= fw / fh else (pw, pw * fh / fw)
    left, top = (pw - w) * CENTERING[0], (ph - h) * CENTERING[1]
    return left, top, left + w, top + h


def overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@dataclass(frozen=True)
class Ground:
    """All in fractions of the frame. `far`/`near`: the highest and lowest place where feet may stand."""
    left: float
    far: float
    right: float
    near: float
    far_size: float = 1.0  # a character at the far edge, of its size at the near edge
    obstacles: tuple[Box, ...] = ()
    nearness: np.ndarray | None = field(default=None, compare=False, repr=False)  # the decor's depth, frame size
    profile: np.ndarray | None = field(default=None, compare=False, repr=False)  # the ground's nearness, per frame row

    @classmethod
    def from_picture(cls, zone: Box, far_size: float, obstacles: list[Box], picture: tuple[int, int],
                     frame: tuple[int, int], depth: Image.Image | None = None, profile: list[float] | None = None) -> "Ground":
        """`depth`: the decor's nearness map (any size, the picture's proportions; 16-bit); `profile`: its ground."""
        box = crop(picture, frame)
        x0, y0, x1, y1 = box
        fx = lambda v: (v * picture[0] - x0) / (x1 - x0)  # noqa: E731
        fy = lambda v: (v * picture[1] - y0) / (y1 - y0)  # noqa: E731
        moved = lambda b: (fx(b[0]), fy(b[1]), fx(b[2]), fy(b[3]))  # noqa: E731
        left, far, right, near = moved(zone)
        nearness = rows = None
        if depth is not None and profile:
            kx, ky = depth.width / picture[0], depth.height / picture[1]
            shown = depth.resize(frame, Image.BILINEAR, box=(x0 * kx, y0 * ky, x1 * kx, y1 * ky))
            nearness = (np.asarray(shown, np.float32) / 65535).astype(np.float16)  # 4 MB at 1080p
            at = (y0 + (np.arange(frame[1]) + 0.5) / frame[1] * (y1 - y0)) / picture[1]  # each frame row, in the picture
            rows = np.interp(at, np.linspace(0, 1, len(profile)), profile).astype(np.float32)
        return cls(max(left, 0.0), far, min(right, 1.0), min(near, 1.0), far_size, tuple(moved(o) for o in obstacles),
                   nearness, rows)

    def at(self, frame: tuple[int, int]) -> "Ground":
        """The same ground for a drawing of another size (a preview, a thumbnail): its depth resized to that frame,
        so that what is in front of a character is looked up where the character really is."""
        if self.nearness is None or self.nearness.shape == (frame[1], frame[0]):
            return self
        near = Image.fromarray(self.nearness.astype(np.float32), "F").resize(frame, Image.BILINEAR)
        rows = np.interp(np.linspace(0, len(self.profile) - 1, frame[1]), np.arange(len(self.profile)), self.profile)
        return replace(self, nearness=np.asarray(near, np.float16), profile=rows.astype(np.float32))

    def scale_at(self, y: float) -> float:
        if self.near - self.far < 1e-6:
            return 1.0
        u = min(1.0, max(0.0, (y - self.far) / (self.near - self.far)))
        return self.far_size + (1 - self.far_size) * u

    def inside(self, x: float, y: float) -> bool:
        e = 1e-6
        return self.left - e <= x <= self.right + e and self.far - e <= y <= self.near + e

    def hidden(self, box: Box, feet: float | None = None) -> float:
        """How much of the character's height (0..1, from its feet up to the highest part hidden) the decor hides.
        With a known depth, from the depth itself; without, any object it would cover from behind hides it all:
        that place is not allowed."""
        feet = box[3] if feet is None else feet
        if self.nearness is None:
            return 1.0 if any(overlap(box, o) and feet < o[3] for o in self.obstacles) else 0.0
        h, w = self.nearness.shape
        step = 4  # a coarse look is enough to decide where to stand
        x0, x1 = max(0, int(box[0] * w)), min(w, int(box[2] * w) + 1)
        y0, y1 = max(0, int(box[1] * h)), min(h, int(box[3] * h) + 1)
        if x1 - x0 < step or y1 - y0 < step:
            return 0.0
        ground = self.profile[min(h - 1, max(0, int(feet * h)))]
        rows = (self.nearness[y0:y1:step, x0:x1:step] > ground + NEARER).mean(1) >= 0.25
        if not rows.any():
            return 0.0
        return 1 - np.argmax(rows) / len(rows)  # from the highest hidden row down to the feet

    def hits(self, box: Box, feet: float | None = None) -> bool:
        """It stands behind something that would hide more than its legs (or, without depth, behind any object)."""
        return self.hidden(box, feet) > HIDDEN

    def cover(self, frame: Image.Image, backdrop: Image.Image, box: tuple[int, int, int, int], feet: float) -> None:
        """Draw again, over a character just drawn in `box` (pixels), what in the decor is nearer than its feet."""
        if self.nearness is None or self.profile is None:
            return
        w, h = frame.size
        left, top, right, bottom = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
        if right <= left or bottom <= top:
            return
        ground = self.profile[min(h - 1, max(0, round(feet)))]
        alpha = np.clip((self.nearness[top:bottom, left:right] - ground - NEARER) / SOFT, 0, 1)
        if alpha.max() <= 0:
            return
        patch = backdrop.crop((left, top, right, bottom))
        patch.putalpha(Image.fromarray((alpha * 255).astype(np.uint8)))
        frame.alpha_composite(patch, (left, top))

    def free(self, box: Box) -> bool:
        """Feet in the zone, the whole character in the frame, no object covered from behind."""
        return (self.inside((box[0] + box[2]) / 2, box[3]) and box[0] >= 0 and box[2] <= 1 and box[1] >= 0
                and not self.hits(box))

    def box(self, x: float, y: float, size: tuple[float, float]) -> Box:
        """A character standing at (x, y): `size` is its width and height at the near edge."""
        s = self.scale_at(y)
        w, h = size[0] * s, size[1] * s
        return x - w / 2, y - h, x + w / 2, y

    def clear(self, x0: float, x1: float, y: float, size: tuple[float, float], y1: float | None = None) -> bool:
        """It can walk from (x0, y) to (x1, y1) (the same depth if no y1) without stepping on or hiding behind
        anything (in perspective: smaller farther back)."""
        y1 = y if y1 is None else y1
        steps = max(1, round(max(abs(x1 - x0), abs(y1 - y)) / 0.01))
        return all(not self.hits(self.box(x0 + (x1 - x0) * k / steps, y + (y1 - y) * k / steps, size))
                   for k in range(steps + 1))

    def spot(self, prefer: float, size: tuple[float, float], taken: list[Box], gap: float = 0.03) -> tuple[float, float]:
        """The free place nearest to `prefer` (x), rather in front, not touching those already placed. If the zone
        has no room at all, the front edge at `prefer`: the overlap check will then show it."""
        best, fallback = None, None
        for j in range(9):
            y = self.near - (self.near - self.far) * j / 8
            for i in range(61):
                x = self.left + (self.right - self.left) * i / 60
                box = self.box(x, y, size)
                if not self.free(box):
                    continue
                cost = abs(x - prefer) + 0.15 * j / 8 + 0.5 * self.hidden(box)  # rather fully seen
                if fallback is None or cost < fallback[0]:
                    fallback = (cost, x, y)
                wide = (box[0] - gap, box[1], box[2] + gap, box[3])
                if any(overlap(wide, t) for t in taken):
                    continue
                if best is None or cost < best[0]:
                    best = (cost, x, y)
        chosen = best or fallback
        return (chosen[1], chosen[2]) if chosen else (min(max(prefer, self.left), self.right), self.near)

    def reach(self, x: float, y: float, size: tuple[float, float], distance: float) -> float:
        """Where a walk of `distance` (signed) from x ends: as far as the way is free, or the other way if that is
        longer. Returns x itself when there is nowhere to go."""
        n = max(1, round(abs(distance) / 0.01))
        best = x
        for d in (distance, -distance):
            end = x
            for k in range(1, n + 1):
                if not self.free(self.box(x + d * k / n, y, size)):
                    break
                end = x + d * k / n
            if abs(end - x) > abs(best - x) + 0.02:
                best = end
            if abs(best - x) >= abs(distance) * 0.6:
                break
        return best
