"""Things drawn by the program itself: a garden backdrop, drifting clouds, soft twinkles, floating lights, balloons,
swaying flowers, and two simple characters (a butterfly with wings that beat, a little cloud that blinks).

All slow and soft, for babies: twinkles take seconds to brighten and dim, nothing flashes. Every effect takes the
frame size and a seed, so the same scene fits 16:9 and 9:16, and another seed gives another arrangement.
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .render import _sprite
from .stage import Effect, Look, Part

LEVELS = 16  # transparency steps kept ready for every sprite that fades


def _faded(sprite: Image.Image) -> list[Image.Image]:
    alpha = sprite.getchannel("A")
    out = []
    for k in range(LEVELS + 1):
        image = sprite.copy()
        image.putalpha(alpha.point(lambda v, f=k / LEVELS: round(v * f)))
        out.append(image)
    return out


def _turned(cache: dict, sprite: Image.Image, angle: float) -> Image.Image:
    """The sprite turned around the bottom of its middle, a quarter of a degree at a time, each angle made once."""
    key = round(angle * 4)
    if key not in cache:
        cache[key] = sprite.rotate(key / 4, Image.BICUBIC, expand=True, center=(sprite.width / 2, sprite.height))
    return cache[key]


def _shaded(mask: Image.Image, colour: tuple[int, int, int], shade: tuple[int, int, int], light: float = 0.35) -> Image.Image:
    """A soft 3D-looking body: lit from the top left, darker towards its lower edge."""
    size = mask.size
    m = np.asarray(mask, np.float32) / 255
    blur = np.asarray(mask.filter(ImageFilter.GaussianBlur(max(size) / 10)), np.float32) / 255
    shifted = np.roll(np.roll(blur, -size[1] // 12, 0), -size[0] // 12, 1)
    ys = np.linspace(0, 1, size[1])[:, None]
    k = np.clip(0.55 * ys + 0.45 * (1 - blur), 0, 1)[..., None]
    rgb = np.array(colour, np.float32) * (1 - k) + np.array(shade, np.float32) * k
    rgb += light * 255 * np.clip(shifted - 0.6, 0, 1)[..., None] * 1.2
    out = np.dstack([np.clip(rgb, 0, 255), m * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


# --- the backdrop --------------------------------------------------------------------------------------------------

DAY = {"sky": ((128, 186, 246), (255, 228, 214)), "glow": ((255, 243, 196), 0.75), "disc": ((255, 250, 225), 0.055),
       "hills": [((176, 214, 196), (150, 200, 170)), ((150, 206, 120), (120, 186, 96)), ((124, 200, 84), (66, 146, 46))],
       "grass": (96, 172, 70), "bloom": 1.0}
NIGHT = {"sky": ((22, 30, 84), (104, 92, 168)), "glow": ((190, 190, 255), 0.45), "disc": ((255, 246, 205), 0.045),
         "hills": [((70, 86, 140), (60, 76, 128)), ((52, 92, 104), (40, 76, 92)), ((40, 96, 82), (22, 62, 54))],
         "grass": (34, 92, 70), "bloom": 0.55}


def garden(size: tuple[int, int], seed: int = 0, night: bool = False) -> Image.Image:
    """A meadow: sky with the sun (or the moon), far hills, a near meadow full of tiny flowers."""
    colours = NIGHT if night else DAY
    width, height = size
    rng = random.Random(seed)
    ys = np.arange(height, dtype=np.float32)[:, None] / height
    xs = np.arange(width, dtype=np.float32)[None, :] / width
    unit = min(width, height) / height  # distances measured on the shorter side
    top, low = (np.array(c, np.float32) for c in colours["sky"])
    k = np.clip(ys / 0.6, 0, 1)[..., None]
    sky = top * (1 - k) + low * k
    sun = (0.8 if seed % 2 == 0 else 0.2, 0.17)
    d = np.hypot((xs - sun[0]) * width / height, ys - sun[1]) / unit
    (glow_colour, glow_amount), (disc_colour, disc_size) = colours["glow"], colours["disc"]
    picture = sky + (np.array(glow_colour) - sky) * glow_amount * np.exp(-(d / 0.22) ** 2)[..., None]
    picture = picture + (np.array(disc_colour) - picture) * np.clip((disc_size - d) / 0.006, 0, 1)[..., None]
    picture = np.broadcast_to(picture, (height, width, 3)).copy()

    def hill(base: float, amp: float, waves: float, colour_top, colour_low, soft: float) -> None:
        phase = rng.uniform(0, 6.28)
        line = base + amp * (np.sin(xs * math.pi * waves + phase) + 0.4 * np.sin(xs * math.pi * waves * 2.7 + phase * 2))
        inside = np.clip((ys - line) * height / soft, 0, 1)[..., None]
        depth = np.clip((ys - line) / 0.35, 0, 1)[..., None]
        colour = np.array(colour_top, np.float32) * (1 - depth) + np.array(colour_low, np.float32) * depth
        picture[:] = picture * (1 - inside) + colour * inside

    for (base, amp, waves, soft), (top_colour, low_colour) in zip(((0.5, 0.035, 2, 3), (0.57, 0.03, 3, 2),
                                                                    (0.66, 0.02, 1.5, 1.5)), colours["hills"]):
        hill(base, amp, waves, top_colour, low_colour, soft)
    image = Image.fromarray(np.clip(picture, 0, 255).astype(np.uint8))

    # a meadow sprinkled with grass and flowers, bigger nearer to us; sizes from the shorter side, so 9:16 matches
    short, area = min(size), width * height / (1920 * 1080)
    near = Image.new("RGBA", size)
    draw = ImageDraw.Draw(near)
    grass = colours["grass"]
    for _ in range(int(2500 * area)):  # grass: blades of slightly different greens
        y = height * (0.64 + 0.36 * rng.random() ** 0.8)
        r = short * 0.006 * (1 + 3 * (y / height - 0.64) / 0.36)
        x = rng.uniform(0, width)
        g = rng.randint(-22, 22)
        draw.ellipse((x - r * 0.35, y - r * 1.6, x + r * 0.35, y), fill=(grass[0] + g, grass[1] + g, grass[2] + g // 2, 120))
    for _ in range(int(260 * area)):
        y = height * (0.68 + 0.32 * rng.random() ** 0.8)
        r = short * 0.003 * (1 + 3 * (y / height - 0.66) / 0.34)
        x = rng.uniform(0, width)
        colour = rng.choice([(255, 255, 255), (255, 190, 214), (255, 226, 120), (214, 186, 255)])
        colour = tuple(round(c * colours["bloom"]) for c in colour)
        draw.ellipse((x - r, y - r * 0.8, x + r, y + r * 0.8), fill=colour + (230,))
        draw.ellipse((x - r / 3, y - r / 3, x + r / 3, y + r / 3), fill=(255, 200, 60, round(255 * colours["bloom"])))
    near = near.filter(ImageFilter.GaussianBlur(short / 1400))
    image.paste(near, (0, 0), near)
    return image.filter(ImageFilter.GaussianBlur(short / 1600))


# --- effects -------------------------------------------------------------------------------------------------------

class Clouds(Effect):
    """A few soft clouds drifting slowly across the sky."""

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 3):
        rng = random.Random(seed + 11)
        self.size = size
        unit = min(size)
        self.clouds = []
        for k in range(count):
            w, h = round(unit * rng.uniform(0.28, 0.4)), round(unit * rng.uniform(0.14, 0.18))
            mask = Image.new("L", (w, h))
            draw = ImageDraw.Draw(mask)
            for _ in range(7):  # puffs fully inside the sprite, so no edge is cut straight
                r = rng.uniform(0.22, 0.34) * h
                cx, cy = rng.uniform(r + h * 0.1, w - r - h * 0.1), rng.uniform(r + h * 0.1, h * 0.88 - r)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
            draw.rounded_rectangle((h * 0.2, h * 0.55, w - h * 0.2, h * 0.85), radius=h * 0.15, fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(h / 14))
            sprite = _shaded(mask, (255, 255, 255), (222, 222, 246), 0.1)
            sprite.putalpha(sprite.getchannel("A").point(lambda v: round(v * 0.92)))
            self.clouds.append((sprite, rng.uniform(0, 1), size[1] * rng.uniform(0.05, 0.24), unit * rng.uniform(0.008, 0.014)))

    def draw(self, frame: Image.Image, t: float) -> None:
        width = self.size[0]
        for sprite, start, y, speed in self.clouds:
            span = width + sprite.width
            x = (start * span + t * speed) % span - sprite.width
            frame.alpha_composite(sprite, (round(x), round(y)))


class Twinkles(Effect):
    """Little stars in the sky that brighten and dim slowly (seconds, never a flash)."""

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 9):
        rng = random.Random(seed + 23)
        scale = min(size) / 1080
        self.stars = [(_faded(_sprite(max(2, round(rng.choice((3, 4, 5)) * scale)), True)),
                       rng.uniform(0.03, 0.97) * size[0], rng.uniform(0.03, 0.4) * size[1],
                       rng.uniform(3.0, 5.5), rng.uniform(0, 1)) for _ in range(count)]

    def draw(self, frame: Image.Image, t: float) -> None:
        for levels, x, y, period, phase in self.stars:
            k = 0.25 + 0.55 * (0.5 + 0.5 * math.sin(2 * math.pi * (t / period + phase)))
            sprite = levels[round(k * LEVELS)]
            frame.alpha_composite(sprite, (round(x - sprite.width / 2), round(y - sprite.height / 2)))


class Lights(Effect):
    """Tiny warm lights rising slowly in front of everything, appearing and fading softly."""
    front = True

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 12):
        rng = random.Random(seed + 37)
        scale = min(size) / 1080
        self.size = size
        self.motes = [(_faded(_sprite(max(1, round(rng.choice((2, 3)) * scale)), False)), rng.uniform(0, 1),
                       rng.uniform(0.35, 1.0), rng.uniform(9, 14), rng.uniform(0, 1)) for _ in range(count)]

    def draw(self, frame: Image.Image, t: float) -> None:
        width, height = self.size
        for levels, x, y, life, phase in self.motes:
            age = (t / life + phase) % 1
            k = math.sin(math.pi * age) ** 2 * 0.7
            sprite = levels[round(k * LEVELS)]
            px = x * width + 0.02 * width * math.sin(2 * math.pi * (t / 6 + phase))
            py = (y - 0.25 * age) * height
            frame.alpha_composite(sprite, (round(px - sprite.width / 2), round(py - sprite.height / 2)))


def balloon(width: int, colour: tuple[int, int, int]) -> Image.Image:
    height = round(width * 1.2)
    sprite = Image.new("RGBA", (width, height + width))
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).ellipse((1, 1, width - 2, height - 2), fill=255)
    body = _shaded(mask.filter(ImageFilter.GaussianBlur(1)), colour, tuple(round(c * 0.72) for c in colour), 0.55)
    sprite.alpha_composite(body)
    draw = ImageDraw.Draw(sprite)
    draw.polygon([(width / 2 - width / 14, height - 2), (width / 2 + width / 14, height - 2), (width / 2, height + width / 14)],
                 fill=tuple(round(c * 0.8) for c in colour) + (255,))
    string = [(width / 2 + width / 10 * math.sin(k / 6), height + k * width / 40) for k in range(40)]
    draw.line(string, fill=(250, 250, 250, 200), width=max(1, width // 50))
    return sprite


class Balloons(Effect):
    """Balloons rising slowly at the sides, swaying a little."""

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 3, every: float = 7.0):
        rng = random.Random(seed + 41)
        unit = min(size)
        colours = [(255, 140, 170), (130, 190, 255), (255, 214, 110), (180, 150, 255), (140, 220, 170)]
        rng.shuffle(colours)
        self.size, self.turned, self.every = size, {}, every
        self.balloons = [(balloon(round(unit * rng.uniform(0.06, 0.08)), colours[k % len(colours)]),
                          rng.choice((rng.uniform(0.04, 0.2), rng.uniform(0.8, 0.96))), k * every + rng.uniform(0, 2),
                          rng.uniform(0, 1)) for k in range(count)]

    def draw(self, frame: Image.Image, t: float) -> None:
        width, height = self.size
        for sprite, x, born, phase in self.balloons:
            age = (t - born) % (len(self.balloons) * self.every)  # they keep coming, in any scene of the song
            travel = height + sprite.height
            if age < 0 or age * height / 16 > travel * 1.0:  # 16 s from the bottom to the top of a 16:9 frame
                continue
            image = _turned(self.turned.setdefault(id(sprite), {}), sprite, 5 * math.sin(2 * math.pi * (age / 4 + phase)))
            px = x * width + 0.02 * width * math.sin(2 * math.pi * (age / 7 + phase)) - image.width / 2
            py = height - age * height / 16
            frame.alpha_composite(image, (round(px), round(py)))


def heart(width: int, colour: tuple[int, int, int]) -> Image.Image:
    """A small round heart, softly shaded like the balloons."""
    mask = Image.new("L", (width, width))
    pen = ImageDraw.Draw(mask)
    r = width * 0.27
    pen.ellipse((width * 0.04, width * 0.08, width * 0.04 + 2 * r, width * 0.08 + 2 * r), fill=255)
    pen.ellipse((width * 0.96 - 2 * r, width * 0.08, width * 0.96, width * 0.08 + 2 * r), fill=255)
    pen.polygon([(width * 0.06, width * 0.38), (width * 0.94, width * 0.38), (width * 0.5, width * 0.94)], fill=255)
    body = _shaded(mask.filter(ImageFilter.GaussianBlur(max(1, width / 40))), colour,
                   tuple(round(c * 0.75) for c in colour), 0.5)
    pad = max(2, width // 10)  # a soft light rim: a pink heart still shows on a pink wall
    out = Image.new("RGBA", (width + 2 * pad, width + 2 * pad))
    glow = Image.new("L", out.size)
    glow.paste(mask, (pad, pad))
    glow = glow.filter(ImageFilter.MaxFilter(2 * (pad // 2) + 1)).filter(ImageFilter.GaussianBlur(pad / 2))
    out.paste((255, 255, 255, 255), (0, 0), glow.point(lambda v: v * 0.8))
    out.alpha_composite(body, (pad, pad))
    return out


class Hearts(Effect):
    """A few small hearts here and there: each one comes softly, rises a little, sways, and fades. Never many at once,
    never fast, never flashing."""

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 6, every: float = 1.6, life: float = 4.5):
        rng = random.Random(seed + 77)
        unit = min(size)
        colours = [(255, 120, 160), (255, 160, 190), (240, 90, 130), (255, 185, 210)]
        self.size, self.every, self.life = size, every, life
        self.hearts = [(_faded(heart(round(unit * rng.uniform(0.05, 0.075)), colours[k % len(colours)])),
                        rng.uniform(0.12, 0.88), rng.uniform(0.14, 0.5),
                        k * every + rng.uniform(0, 0.8), rng.uniform(0, 1)) for k in range(count)]

    def draw(self, frame: Image.Image, t: float) -> None:
        width, height = self.size
        for levels, x, y, born, phase in self.hearts:
            age = (t - born) % (len(self.hearts) * self.every)
            if age > self.life:
                continue
            share = age / self.life
            image = levels[round(math.sin(math.pi * share) * 0.85 * LEVELS)]  # comes and goes softly
            px = x * width + 0.012 * width * math.sin(2 * math.pi * (age / 3 + phase)) - image.width / 2
            py = y * height - 0.08 * height * share - image.height / 2
            frame.alpha_composite(image, (round(px), round(py)))


class Confetti(Effect):
    """A few small pieces of confetti falling slowly, swaying and turning a little, behind the characters: a quiet
    celebration, never a shower."""

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 16, fall: float = 11.0):
        rng = random.Random(seed + 89)
        unit = min(size)
        colours = [(255, 120, 160), (110, 175, 255), (255, 200, 70), (170, 130, 255), (110, 210, 150), (255, 150, 90)]
        self.size, self.fall, self.turned = size, fall, {}
        self.pieces = []
        for k in range(count):
            w = round(unit * rng.uniform(0.024, 0.032))
            mask = Image.new("L", (w, max(3, round(w * 0.6))))
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=mask.height / 3, fill=255)
            colour = colours[k % len(colours)]
            sprite = _shaded(mask, colour, tuple(round(c * 0.75) for c in colour), 0.3)
            self.pieces.append((sprite, rng.uniform(0.04, 0.96), k * fall / count + rng.uniform(0, 0.5),
                                rng.uniform(0, 1), rng.choice((-1, 1))))

    def draw(self, frame: Image.Image, t: float) -> None:
        width, height = self.size
        for sprite, x, born, phase, spin in self.pieces:
            age = (t - born) % self.fall  # each falls from the top to the bottom in `fall` seconds, then again
            image = _turned(self.turned.setdefault(id(sprite), {}), sprite,
                            spin * 25 * math.sin(2 * math.pi * (age / 2.5 + phase)))
            px = x * width + 0.025 * width * math.sin(2 * math.pi * (age / 3.5 + phase)) - image.width / 2
            py = age * (height + 2 * image.height) / self.fall - image.height
            frame.alpha_composite(image, (round(px), round(py)))


def flower(height: int, colour: tuple[int, int, int], rng: random.Random) -> Image.Image:
    head = round(height * 0.42)
    sprite = Image.new("RGBA", (head, height))
    draw = ImageDraw.Draw(sprite)
    draw.line([(head / 2, head / 2), (head / 2 + head * 0.05, height)], fill=(70, 150, 60, 255), width=max(2, head // 14))
    leaf = Image.new("RGBA", (head // 2, head // 4))
    ImageDraw.Draw(leaf).ellipse((0, 0, leaf.width - 1, leaf.height - 1), fill=(90, 175, 70, 255))
    sprite.alpha_composite(leaf.rotate(25, expand=True), (round(head / 2), round(height * 0.62)))
    petals = Image.new("L", (head, head))
    pd = ImageDraw.Draw(petals)
    count = rng.choice((5, 6, 8))
    for k in range(count):
        a = 2 * math.pi * k / count
        cx, cy = head / 2 + head * 0.24 * math.cos(a), head / 2 + head * 0.24 * math.sin(a)
        r = head * 0.2
        pd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    sprite.alpha_composite(_shaded(petals.filter(ImageFilter.GaussianBlur(1)), colour, tuple(round(c * 0.8) for c in colour), 0.2))
    centre = Image.new("L", (head, head))
    ImageDraw.Draw(centre).ellipse((head * 0.36, head * 0.36, head * 0.64, head * 0.64), fill=255)
    sprite.alpha_composite(_shaded(centre.filter(ImageFilter.GaussianBlur(1)), (255, 214, 80), (230, 150, 40), 0.3))
    return sprite


class Flowers(Effect):
    """Flowers in the front corners, swaying around their stems, each in its own time."""
    front = True

    def __init__(self, size: tuple[int, int], seed: int = 0, count: int = 6):
        rng = random.Random(seed + 53)
        unit = min(size)
        colours = [(255, 170, 200), (255, 255, 255), (255, 214, 120), (210, 180, 255)]
        self.size, self.turned = size, {}
        self.flowers = []
        for k in range(count):
            x = rng.uniform(0.01, 0.13) if k % 2 == 0 else rng.uniform(0.87, 0.99)
            self.flowers.append((flower(round(unit * rng.uniform(0.15, 0.22)), rng.choice(colours), rng), x,
                                 rng.uniform(3.2, 4.4), rng.uniform(0, 1)))

    def draw(self, frame: Image.Image, t: float) -> None:
        width, height = self.size
        for sprite, x, period, phase in self.flowers:
            image = _turned(self.turned.setdefault(id(sprite), {}), sprite, 4 * math.sin(2 * math.pi * (t / period + phase)))
            frame.alpha_composite(image, (round(x * width - image.width / 2), round(height - image.height * 0.92)))


# --- characters made by the program (stand-ins until the real pictures are ready) ----------------------------------

def butterfly(colour: tuple[int, int, int] = (255, 196, 80), size: int = 360) -> Look:
    """A body with two separate wings that beat by folding around it: an example of a character made of parts."""
    body = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(body)
    c = size / 2
    draw.ellipse((c - size * 0.035, c - size * 0.16, c + size * 0.035, c + size * 0.2), fill=(90, 60, 50, 255))
    draw.ellipse((c - size * 0.05, c - size * 0.24, c + size * 0.05, c - size * 0.14), fill=(90, 60, 50, 255))
    for side in (-1, 1):
        tip = (c + side * size * 0.12, c - size * 0.38)
        draw.line([(c + side * size * 0.015, c - size * 0.22), (c + side * size * 0.06, c - size * 0.33), tip],
                  fill=(90, 60, 50, 255), width=max(2, size // 90), joint="curve")
        draw.ellipse((tip[0] - size * 0.02, tip[1] - size * 0.02, tip[0] + size * 0.02, tip[1] + size * 0.02), fill=(90, 60, 50, 255))
    for side in (-1, 1):
        draw.ellipse((c + side * size * 0.035 - size * 0.012, c - size * 0.2, c + side * size * 0.035 + size * 0.012,
                      c - size * 0.18), fill=(255, 255, 255, 255))
    wing = Image.new("L", (size // 2, size))
    wd = ImageDraw.Draw(wing)
    w = size / 2
    wd.ellipse((w * 0.08, size * 0.12, w * 1.02, size * 0.56), fill=255)
    wd.ellipse((w * 0.3, size * 0.46, w * 1.0, size * 0.8), fill=255)
    left = _shaded(wing.filter(ImageFilter.GaussianBlur(2)), colour, tuple(round(v * 0.75) for v in colour), 0.45)
    dots = ImageDraw.Draw(left)
    for x, y, r in ((0.38, 0.3, 0.07), (0.56, 0.62, 0.05), (0.62, 0.22, 0.045)):
        dots.ellipse((w * x - w * r, size * y - w * r, w * x + w * r, size * y + w * r), fill=(255, 250, 240, 230))
    right = left.transpose(Image.FLIP_LEFT_RIGHT)

    def beat(t: float, offset: float = 0.0) -> tuple[float, float, float]:
        return 0.0, 0.3 + 0.7 * abs(math.cos(math.pi * 1.6 * t + offset)), 1.0

    return Look(body, parts=[Part(left, (c - 1, c), (w, size / 2), beat, front=False),
                             Part(right, (c + 1, c), (0, size / 2), beat, front=False)])


def cloud_buddy(size: int = 420) -> Look:
    """A little smiling cloud with a second picture where its eyes are closed: an example of a character with poses."""
    height = round(size * 0.68)
    mask = Image.new("L", (size, height))
    draw = ImageDraw.Draw(mask)
    for cx, cy, r in ((0.3, 0.6, 0.22), (0.5, 0.45, 0.3), (0.72, 0.58, 0.22), (0.5, 0.68, 0.24), (0.18, 0.72, 0.14),
                      (0.84, 0.72, 0.13)):
        draw.ellipse((size * (cx - r), height * cy - size * r, size * (cx + r), min(height - 3, height * cy + size * r)), fill=255)
    body = _shaded(mask.filter(ImageFilter.GaussianBlur(3)), (255, 255, 255), (206, 210, 246), 0.12)

    def face(closed: bool) -> Image.Image:
        picture = body.copy()
        d = ImageDraw.Draw(picture)
        for x in (0.4, 0.6):
            ex, ey, r = size * x, height * 0.55, size * 0.035
            if closed:
                d.arc((ex - r * 1.3, ey - r * 1.4, ex + r * 1.3, ey + r * 0.8), 20, 160, fill=(70, 60, 90, 255), width=max(3, size // 80))
            else:
                d.ellipse((ex - r, ey - r * 1.3, ex + r, ey + r * 1.3), fill=(60, 50, 80, 255))
                d.ellipse((ex - r * 0.2, ey - r * 0.9, ex + r * 0.45, ey - r * 0.25), fill=(255, 255, 255, 255))
        for x in (0.32, 0.68):
            d.ellipse((size * x - size * 0.04, height * 0.66, size * x + size * 0.04, height * 0.72), fill=(255, 170, 190, 150))
        d.arc((size * 0.45, height * 0.6, size * 0.55, height * 0.72), 20, 160, fill=(120, 70, 90, 255), width=max(3, size // 90))
        return picture

    return Look(face(False), looks={"ochi_inchisi": face(True)})
