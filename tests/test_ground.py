import numpy as np
from PIL import Image, ImageOps

from baby_video_studio.ground import CENTERING, Ground, crop

PICTURE = (410, 227)
ZONE = (0.05, 0.6, 0.95, 0.97)
BALL = (0.15, 0.7, 0.3, 0.95)  # an object on the grass, left of the middle


def test_the_zone_lands_where_the_picture_shows_it_in_both_formats():
    picture = Image.new("RGB", PICTURE, (40, 160, 60))
    picture.putpixel((round(0.3 * PICTURE[0]), round(0.8 * PICTURE[1])), (255, 0, 0))
    for frame in ((1920, 1080), (1080, 1920)):
        drawn = picture.resize(frame, Image.NEAREST, box=crop(PICTURE, frame))
        same = ImageOps.fit(picture, frame, Image.NEAREST, centering=CENTERING)
        assert np.abs(np.asarray(drawn, int) - np.asarray(same, int)).mean() < 1, "cropped as the decor always was"
        g = Ground.from_picture((0.3, 0.8, 0.3, 0.8), 1.0, [], PICTURE, frame)
        red = np.argwhere(np.asarray(drawn)[..., 0] > 200)
        if len(red):  # in 9:16 the dot may fall outside the narrow crop
            y, x = red.mean(0)
            assert abs(x - g.left * frame[0]) < frame[0] * 0.01 + 3 and abs(y - g.far * frame[1]) < frame[1] * 0.01 + 3


def test_farther_back_is_smaller():
    g = Ground(*ZONE, far_size=0.6)
    assert g.scale_at(0.6) == 0.6 and g.scale_at(0.97) == 1.0 and 0.6 < g.scale_at(0.8) < 1.0


def test_nobody_stands_on_an_object_but_one_may_stand_in_front_of_it():
    g = Ground(*ZONE, obstacles=(BALL,))
    size = (0.1, 0.3)
    assert g.hits(g.box(0.22, 0.85, size)), "on the ball"
    assert not g.hits(g.box(0.22, 0.97, size)), "in front of it"
    assert not g.free(g.box(0.5, 0.4, size)), "feet in the sky"


def test_places_are_free_apart_and_near_the_wished_ones():
    g = Ground(*ZONE, far_size=0.7, obstacles=(BALL,))
    size, taken = (0.12, 0.35), []
    for prefer in (0.2, 0.5, 0.8):
        x, y = g.spot(prefer, size, taken)
        box = g.box(x, y, size)
        assert g.free(box)
        assert not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken)
        assert abs(x - prefer) < 0.2
        taken.append(box)


def test_a_walk_stops_before_an_object():
    g = Ground(*ZONE, obstacles=(BALL,))
    size = (0.1, 0.3)
    end = g.reach(0.6, 0.85, size, -0.4)
    assert g.clear(0.6, end, 0.85, size) and end > BALL[2]


def meadow(size=(320, 180), bush=(0.1, 0.55, 0.3, 1.0)):
    """A nearness map: sky far away, ground getting nearer towards the bottom, a bush standing in front on the left."""
    w, h = size
    rows = np.arange(h)[:, None] / h
    near = np.clip((rows - 0.5) / 0.5, 0, 1) * np.ones((1, w))
    x0, y0, x1, y1 = (round(v * s) for v, s in zip(bush, (w, h, w, h)))
    near[y0:y1, x0:x1] = np.maximum(near[y0:y1, x0:x1], 0.95)
    return near.astype(np.float32)


def test_the_depth_shows_the_ground_the_zone_and_the_objects():
    from baby_video_studio import depth
    found = depth.analyse(meadow())
    assert 0.45 <= found.horizon <= 0.56
    left, far, right, near = found.zone
    assert far > found.horizon and near > 0.9 and right - left > 0.5
    assert 0.4 <= found.far_size <= 0.6, "at the far edge, about half as big"
    assert any(o[0] <= 0.12 and o[2] >= 0.28 and o[3] >= 0.95 for o in found.obstacles), found.obstacles


def depth_ground(size=(320, 180)):
    from baby_video_studio import depth
    near = meadow(size)
    found = depth.analyse(near)
    picture = Image.fromarray((near * 65535).astype(np.uint16))
    return Ground.from_picture(found.zone, found.far_size, found.obstacles, size, size, picture, found.profile)


def test_with_depth_one_may_stand_behind_a_bush_if_only_the_legs_are_hidden():
    g = depth_ground()
    assert g.hidden((0.15, 0.5, 0.25, 0.75), 0.75) > 0.6, "right behind the bush, most of it hidden"
    assert g.hidden((0.15, 0.4, 0.25, 0.65), 0.65) <= 0.45, "farther back, only the legs"
    assert g.hidden((0.5, 0.5, 0.6, 0.9), 0.9) == 0.0, "on open ground, nothing"


def test_what_is_in_front_is_drawn_over_the_character():
    size = (320, 180)
    g = depth_ground(size)
    backdrop = Image.new("RGBA", size, (0, 200, 0, 255))
    frame = backdrop.copy()
    frame.paste((255, 0, 0, 255), (40, 70, 90, 120))  # a character standing at row 120, partly behind the bush
    g.cover(frame, backdrop, (40, 70, 90, 120), 120)
    pixels = np.asarray(frame)
    assert pixels[110, 45, 1] == 200, "its legs behind the bush are hidden"
    assert pixels[75, 85, 0] == 255, "the rest of it is seen"


def test_a_close_up_has_no_ground_and_a_strip_at_the_bottom_is_not_ground():
    from baby_video_studio import depth
    close_up = np.full((180, 320), 0.9, np.float32)
    close_up[:60] = 0.0  # a big flower, sky behind it: nowhere to stand
    assert depth.analyse(close_up).zone is None
    cut = meadow()
    cut[-12:] = 1.0  # a white strip left over from a collage
    found = depth.analyse(cut)
    assert found.zone and found.zone[3] < 0.95 and found.horizon < 0.6


def test_a_smaller_drawing_looks_up_what_is_in_front_at_the_right_place():
    big = depth_ground((640, 360))
    backdrop = Image.new("RGBA", (320, 180), (0, 200, 0, 255))
    box, feet = (150, 110, 190, 170), 170  # a character on open ground, low in a small drawing

    def drawn(ground):
        frame = backdrop.copy()
        frame.paste((255, 0, 0, 255), box)
        ground.cover(frame, backdrop, box, feet)
        return np.asarray(frame)[140, 170, 0]
    assert drawn(big.at((320, 180))) == 255, "with its depth at this size, nothing of the decor is drawn over it"
