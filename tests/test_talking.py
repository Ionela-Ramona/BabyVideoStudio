import numpy as np
import pytest
from PIL import Image, ImageDraw

from baby_video_studio import media, talking
from test_render import have_ffmpeg

SKIN, MOUTH, EYE, VARIANT = (250, 205, 40), (120, 20, 20), (40, 90, 220), (20, 160, 60)


def star(mouth=MOUTH) -> tuple[Image.Image, talking.Face]:
    """A yellow face with an open dark-red mouth and two blue eyes with dark lashes, on a transparent backdrop."""
    picture = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.ellipse((40, 40, 360, 380), fill=SKIN)
    draw.ellipse((170, 250, 230, 290), fill=mouth)
    for left in (120, 240):
        draw.ellipse((left, 140, left + 40, 190), fill=EYE, outline=(25, 20, 20), width=3)
    return picture, talking.Face(mouth=(160, 240, 240, 300), eyes=[(110, 130, 170, 200), (230, 130, 290, 200)])


def count(picture: Image.Image, colour: tuple, box: tuple) -> int:
    pixels = np.asarray(picture.convert("RGB").crop(box)).astype(int)
    return int((np.abs(pixels - colour).sum(-1) < 60).sum())


def test_the_mouth_closes_opens_and_nothing_else_moves():
    picture, face = star()
    puppet = talking.Puppet(picture, face)
    closed, half, open_ = (puppet.frame(o, 0, 0) for o in (0, 0.4, 1))
    assert count(closed, MOUTH, face.mouth) < 0.15 * count(picture, MOUTH, face.mouth), "a closed mouth is a smile line"
    assert count(closed, MOUTH, face.mouth) < count(half, MOUTH, face.mouth) < count(open_, MOUTH, face.mouth)
    outside = np.ones((400, 400), bool)
    outside[230:330, 150:250] = False
    for frame in (closed, half, open_):
        assert (np.asarray(frame)[outside] == np.asarray(picture)[outside]).all(), "eyes and body untouched"


def test_a_blink_hides_the_eyes():
    picture, face = star()
    shut = talking.Puppet(picture, face).frame(0.5, 0, 1)
    for box in face.eyes:
        assert count(shut, EYE, box) < 0.05 * count(picture, EYE, box)


def test_mouth_and_eyes_are_found_by_themselves():
    picture, face = star()
    found = talking.detect_face(picture)
    assert found is not None
    centre = lambda b: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)  # noqa: E731
    assert np.allclose(centre(found.mouth), (200, 270), atol=6)
    assert [np.allclose(centre(e), c, atol=6) for e, c in zip(found.eyes, [(140, 165), (260, 165)])] == [True, True]
    assert talking.detect_face(Image.new("RGBA", (300, 300), SKIN + (255,))) is None, "no face, no guess"


def test_a_variant_gives_its_mouth_and_only_its_mouth():
    picture, face = star()
    variant, _ = star(mouth=VARIANT)
    variant = Image.new("RGBA", variant.size)
    shifted, _ = star(mouth=VARIANT)
    variant.paste(shifted, (6, -4))  # made by an image generator: a few pixels off
    puppet = talking.Puppet(picture, face, {"deschisa": variant})
    opened = puppet.frame(0.6, 0, 0)
    assert count(opened, VARIANT, face.mouth) > 0.7 * count(picture, MOUTH, face.mouth), "the variant's mouth is used"
    assert count(opened, MOUTH, face.mouth) == 0
    assert count(puppet.frame(0.2, 0, 0), MOUTH, face.mouth) > 0, "shapes without a variant come from the picture"
    outside = np.ones((400, 400), bool)
    outside[200:360, 120:280] = False
    assert (np.asarray(opened)[outside] == np.asarray(picture)[outside]).all()


def test_the_mouth_follows_the_syllables_only_while_someone_speaks():
    rate, frames = talking.RATE, 90
    t = np.arange(3 * rate) / rate
    sound = 0.05 * np.sin(2 * np.pi * 110 * t)  # music all along
    voice = slice(rate // 2, 2 * rate)
    sound[voice] += 0.3 * np.sin(2 * np.pi * 800 * t[voice])
    opening, roundness = talking.mouth_track(sound.astype(np.float32), [(0.5, 1.2, "mama"), (1.2, 2.0, "uuuu")], frames)
    assert (opening[:14] == 0).all() and (opening[62:] == 0).all(), "closed before and after the words, music or not"
    mama = opening[15:36]
    assert mama.max() > 0.7 and (mama[2:-2] < 0.15).any(), "open on 'a', the lips meet on 'm'"
    assert roundness[42:52].min() > 0.5 and roundness[17:34].max() < 0.3, "round on 'u', not on 'a'"


def test_blinks_follow_the_settings():
    every4 = talking.blinks(30 * 40, every=4)
    every8 = talking.blinks(30 * 40, every=8)
    starts = lambda lids: [n for n in range(1, len(lids)) if lids[n] > 0 and lids[n - 1] == 0]  # noqa: E731
    assert len(starts(every4)) > 1.5 * len(starts(every8))
    lengths = {speed: int((talking.blinks(30 * 10, speed=speed) > 0).sum() / len(starts(talking.blinks(30 * 10, speed=speed))))
               for speed in ("rapid", "normal", "lent")}
    assert lengths["rapid"] < lengths["normal"] < lengths["lent"]


def test_backdrops_change_in_pauses():
    words = [(0, 1.8, "a"), (2.2, 5.0, "b"), (5.6, 9.0, "c"), (9.4, 14.0, "d"), (14.5, 20, "e")]
    assert talking.backdrop_starts(words, 20, 2, 5) == [0.0, 9.2], "the pause nearest to the middle"
    assert talking.backdrop_starts(words, 20, 3, 5) == [0.0, 5.3, 14.25]
    assert talking.backdrop_starts(words, 20, 5, 8) == [0.0, 9.2], "never shorter than the shortest scene; the rest wait"


def test_a_profile_is_saved_and_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(talking, "PROFILES", tmp_path)
    profile = talking.Profile(name="Steluța Muzicală", mouth=[1, 2, 3, 4], eyes=[[5, 6, 7, 8]])
    profile.image = talking.store(profile, "steluta.png", b"png")
    profile.variants["inchisa"] = talking.store(profile, "inchisa.png", b"png")
    talking.save_profile(profile)
    assert talking.list_profiles() == ["Steluța Muzicală"]
    again = talking.load_profile("Steluța Muzicală")
    assert again == profile and again.face.mouth == (1, 2, 3, 4)
    assert talking.variant_files(again) == {"inchisa": tmp_path / "Steluța Muzicală" / "inchisa.png"}


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_render_makes_a_vertical_video_with_the_voice(tmp_path, monkeypatch):
    picture, face = star()
    character = tmp_path / "star.png"
    picture.save(character)
    voice = tmp_path / "voce.wav"
    import wave
    t = np.arange(3 * 16000) / 16000
    sound = 0.02 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 600 * t) * ((t > 0.2) & (t < 1.2) | (t > 1.6) & (t < 2.8))
    with wave.open(str(voice), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
        out.writeframes((sound * 32767).astype("<i2").tobytes())
    decors = []
    for n, colour in enumerate(((20, 40, 120), (120, 40, 20))):
        decors.append(tmp_path / f"decor{n}.png")
        Image.new("RGB", (800, 600), colour).save(decors[-1])
    monkeypatch.setattr(talking, "spoken_words", lambda audio: [(0.2, 1.2, "bună"), (1.6, 2.8, "prieteni")])
    output = tmp_path / "personaj.mp4"
    info = talking.render(character, face, voice, output, decors, style=talking.Style(scene_seconds=1))
    probe = media.probe_video(output)
    assert (probe["width"], probe["height"], probe["fps"], probe["codec_audio"]) == (1080, 1920, "30/1", "aac")
    assert probe["duration"] == pytest.approx(3, abs=0.1)
    assert info["backdrops"] == [0.0, 1.4] and info["opening"].max() > 0


def test_purple_headphones_are_not_taken_for_an_eye():
    picture, face = star()
    ImageDraw.Draw(picture).ellipse((20, 150, 90, 280), fill=(150, 60, 230))  # a headphone touching the face
    found = talking.detect_face(picture)
    centre = lambda b: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)  # noqa: E731
    assert [np.allclose(centre(e), c, atol=6) for e, c in zip(found.eyes, [(140, 165), (260, 165)])] == [True, True]
    assert np.allclose(centre(found.mouth), (200, 270), atol=6)
