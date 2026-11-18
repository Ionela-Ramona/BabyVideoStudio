import numpy as np
import pytest
from PIL import Image, ImageDraw

from baby_video_studio import motions, rig

pytestmark = pytest.mark.skipif(not rig.available(), reason="no OpenGL 3.3 here")
RED, GREEN, BLUE, SKIN = (230, 30, 30, 255), (30, 160, 30, 255), (40, 60, 230, 255), (240, 190, 150, 255)


def figure() -> Image.Image:
    """A child standing seen from the front: round head with a blue curl by the left shoulder, a body, red arms a
    little away from it, green legs."""
    picture = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
    pen = ImageDraw.Draw(picture)
    pen.ellipse((130, 10, 270, 160), SKIN)
    pen.ellipse((95, 135, 135, 180), BLUE)  # a curl hanging by the shoulder on the left of the picture
    pen.rectangle((140, 160, 260, 380), (240, 60, 160, 255))
    pen.line((140, 190, 60, 330), RED, 26)
    pen.line((260, 190, 340, 330), RED, 26)
    pen.line((175, 380, 170, 570), GREEN, 34)
    pen.line((225, 380, 230, 570), GREEN, 34)
    pen.rectangle((150, 565, 195, 599), GREEN)
    pen.rectangle((205, 565, 250, 599), GREEN)
    return picture


def where(image: Image.Image, colour) -> np.ndarray:
    px = np.asarray(image).astype(int)
    return np.argwhere((np.abs(px[..., :3] - colour[:3]).sum(-1) < 60) & (px[..., 3] > 200))


def test_the_joints_are_proposed_from_the_shape():
    points = rig.guess(figure())
    assert points["mana_dreapta"][0] < 0.25 and points["mana_stanga"][0] > 0.75, "hands at the outer ends"
    assert points["glezna_dreapta"][1] > 0.85 and points["glezna_dreapta"][0] < 0.5 < points["glezna_stanga"][0]
    assert 0.55 < points["bazin"][1] < 0.75, "the legs part under the body"


def test_standing_it_looks_like_the_picture_with_its_feet_on_the_bottom_edge():
    picture = figure()
    r = rig.Rig(picture, rig.guess(picture))
    drawn = r.draw(picture, 300, {})
    assert drawn.size == r.canvas(300)[:2]
    box = drawn.getbbox()
    assert box[3] == drawn.height, "feet on the ground"
    assert abs((box[0] + box[2]) / 2 - drawn.width / 2) < 4, "centred"


def test_a_step_lifts_one_foot_and_the_other_carries_her():
    picture = figure()
    r = rig.Rig(picture, rig.guess(picture))
    still = where(r.draw(picture, 300, {}), GREEN)
    step = where(r.draw(picture, 300, motions.walk(0.25, motions.Beat(), {"skeleton": True}).joints), GREEN)
    middle = r.canvas(300)[0] / 2
    low = lambda pts, right: pts[(pts[:, 1] > middle) == right][:, 0].max()  # noqa: E731
    assert low(step, True) < low(still, True) - 8, "her left foot (right of the picture) is up"
    assert abs(low(step, False) - low(still, False)) <= 2, "the other one stays on the ground"


def test_clapping_brings_the_hands_together_and_the_curl_stays():
    picture = figure()
    points = rig.guess(picture)  # its head is small: the arms are where the user would drag them
    points.update({"umar_drept": (0.35, 0.32), "cot_drept": (0.25, 0.43), "mana_dreapta": (0.15, 0.55),
                   "umar_stang": (0.65, 0.32), "cot_stang": (0.75, 0.43), "mana_stanga": (0.85, 0.55)})
    r = rig.Rig(picture, points)
    still, clap = r.draw(picture, 300, {}), r.draw(picture, 300, {"palme": 1.0})
    middle = still.width / 2

    def hands(image):  # the lowest red: the hands, how far from the middle
        red = where(image, RED)
        low = red[red[:, 0] >= red[:, 0].max() - 12]
        return np.abs(low[:, 1] - middle).mean()
    assert hands(clap) < hands(still) * 0.4, "hands in front of the tummy"
    raised = r.draw(picture, 300, {"umar_drept_lat": 90})
    curl = lambda image: where(image, BLUE).mean(0)  # noqa: E731
    assert np.abs(curl(raised) - curl(still)).max() < 3, "the arm went up, the curl did not come with it"
    pink = lambda image: {tuple(v) for v in where(image, (240, 60, 160))}  # noqa: E731
    moved = pink(raised) - pink(still)
    assert len(moved) < 0.015 * len(pink(still)), "and the body did not tear where the arm touched it"  # 2.4% without the trunk rule


ORANGE, PINK, BROWN = (240, 130, 40, 255), (250, 170, 190, 255), (120, 70, 40, 255)


def animal() -> Image.Image:
    """A little fox standing like a toy: two pink ears on a round head, a round body, two brown feet, a brown tail
    out on the right."""
    picture = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
    pen = ImageDraw.Draw(picture)
    pen.polygon([(120, 40), (150, 130), (95, 130)], PINK)
    pen.polygon([(280, 40), (305, 130), (250, 130)], PINK)
    pen.ellipse((90, 100, 310, 320), ORANGE)
    pen.ellipse((110, 300, 290, 540), ORANGE)
    pen.polygon([(270, 470), (390, 330), (395, 360), (290, 500)], BROWN)  # the tail, out on one side
    pen.ellipse((125, 525, 190, 599), BROWN)
    pen.ellipse((210, 525, 275, 599), BROWN)
    return picture


def test_an_animal_gets_ears_a_tail_and_feet_from_its_shape():
    points = rig.guess_animal(animal())
    names = [b[0] for b in rig.skeleton(points)]
    assert {"ureche_dreapta", "ureche_stanga", "coada", "talpa_dreapta", "talpa_stanga"} <= set(names), names
    assert not any(n.startswith("laba") for n in names), "no wings on a fox"
    assert points["coada_varf"][0] > 0.8, "the tail is on the right"


def test_an_animal_wags_its_tail_flaps_its_ears_and_steps():
    picture = animal()
    r = rig.Rig(picture, rig.guess_animal(picture))
    still = r.draw(picture, 300, {})
    happy = r.draw(picture, 300, {"urechi": 12, "coada": 15})
    ears = lambda image: where(image, PINK)[:, 1].std()  # noqa: E731
    assert ears(happy) > ears(still) + 1, "the ears swing out"
    tail = lambda image: where(image, BROWN)[where(image, BROWN)[:, 0] < image.height * 0.85].mean(0)  # noqa: E731
    assert np.abs(tail(happy) - tail(still)).max() > 3, "the tail wags"
    step = r.draw(picture, 300, {"genunchi_stang": 70})
    feet = lambda image, right: where(image, BROWN)[(where(image, BROWN)[:, 1] > image.width / 2) == right][:, 0].max()  # noqa: E731
    assert feet(step, True) < feet(still, True) - 4, "one foot up"
    assert abs(feet(step, False) - feet(still, False)) <= 2, "the other on the ground"
