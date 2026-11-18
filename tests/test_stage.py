import numpy as np
import pytest
from PIL import Image, ImageDraw

from baby_video_studio import effects, media, motions, stage
from baby_video_studio.stage import Act, Actor, Follow, Move, Scene
from test_render import have_ffmpeg
from test_talking import star

BEAT = motions.Beat(0.5, 0.0)
SIZE = (640, 360)


def plain(size, seed):
    return Image.new("RGB", size, (90 + 40 * (seed % 2), 150, 220))


def puppet_look():
    picture, face = star()
    return stage.Look(picture, face)


def boxes(scene, t, lids=None, voice=(0.0, 0.0)):
    placed = []
    staged = stage.Staged(scene, SIZE)
    frame = staged.draw(t, BEAT, voice, lids or {}, placed)
    return {p.name: p.box for p in placed}, frame


def test_walking_keeps_the_feet_down_and_blinks_then_hops_once_there():
    """Hopping is asked for the whole time, but on the way it walks: no bounce, no hop. It hops once it stands."""
    walker = Actor("a", puppet_look(), 0.4, 0.3, 0.9, acts=[Act("merge", 0, 3), Act("sare", 0, 6)],
                   moves=[Move(0, 3, x=0.6, walk=True)])
    scene = Scene(0, 6, plain, [walker], zoom=(1, 1))
    start, _ = boxes(scene, 0.0)
    middle, open_eyes = boxes(scene, 2.25)
    _, shut = boxes(scene, 2.25, {"a": 1.0})
    assert middle["a"][0] > start["a"][0] + 40, "it walked"
    feet = [boxes(scene, t)[0]["a"][3] for t in np.arange(0.2, 3.0, 0.1)]
    assert max(feet) - min(feet) <= 4, "with its feet on the ground all the way"
    assert np.abs(np.asarray(open_eyes, int) - np.asarray(shut, int)).sum() > 0, "and blinks while doing it"
    later = [boxes(scene, t)[0]["a"][3] for t in np.arange(4.2, 5.4, 0.05)]
    assert min(later) < start["a"][3] - 5, "then, standing, it hops"


def test_a_walk_goes_at_an_even_pace():
    walker = Actor("a", puppet_look(), 0.4, 0.2, 0.9, moves=[Move(0, 4, x=0.8, walk=True)])
    staged = stage.Staged(Scene(0, 4, plain, [walker], zoom=(1, 1)), SIZE)
    xs = [staged.path(walker, t)[0] for t in np.arange(1.0, 3.01, 0.25)]
    steps = np.diff(xs)
    assert steps.min() > 0.95 * steps.max(), "the same speed in the middle of the way"


def test_singing_and_dancing_at_once():
    singer = Actor("s", puppet_look(), 0.5, 0.5, 0.95, acts=[Act("danseaza", 0, 4)], sings=True)
    scene = Scene(0, 4, plain, [singer], zoom=(1, 1))
    tilted, closed = boxes(scene, 1.25)  # mid-sway
    _, sung = boxes(scene, 1.25, voice=(0.9, 0.0))
    still, _ = boxes(Scene(0, 4, plain, [Actor("s", puppet_look(), 0.5, 0.5, 0.95)], zoom=(1, 1)), 1.5)
    assert tilted["s"] != still["s"], "it dances"
    assert np.abs(np.asarray(closed, int) - np.asarray(sung, int)).sum() > 0, "and its mouth moves meanwhile"


def test_one_goes_next_to_the_other_and_a_butterfly_follows():
    a = Actor("a", puppet_look(), 0.4, 0.2, 0.95, moves=[Move(0, 2, near="b", side=-1)])
    b = Actor("b", puppet_look(), 0.4, 0.75, 0.95)
    fly = Actor("f", effects.butterfly(), 0.15, 0.9, 0.2, flying=True, follow=Follow("a", 0, 6, side=-1, lag=0.5))
    scene = Scene(0, 6, plain, [a, b, fly], zoom=(1, 1))
    early, _ = boxes(scene, 0.0)
    late, _ = boxes(scene, 5.0)
    assert late["a"][2] < late["b"][0] and late["b"][0] - late["a"][2] < 0.15 * SIZE[0], "close, not touching"
    assert early["a"][2] < late["a"][2]
    middle = lambda box: (box[0] + box[2]) / 2  # noqa: E731
    assert abs(middle(late["f"]) - middle(late["a"])) < 0.8 * (late["a"][2] - late["a"][0]), "the butterfly came along, above her shoulder"
    assert late["f"][3] <= late["a"][1], "above, not over the star"


def test_characters_shrink_to_fit_a_narrow_frame():
    cast = [Actor(n, puppet_look(), 0.6, x, 0.9, acts=[Act("danseaza", 0, 2)]) for n, x in (("a", 0.25), ("b", 0.75))]
    scene = Scene(0, 2, plain, cast, zoom=(1, 1))
    assert stage.fit(scene, (1920, 1080)) == 1.0
    tall = stage.fit(scene, (540, 960))
    assert tall < 1.0
    placed = []
    staged = stage.Staged(scene, (540, 960))
    for t in np.arange(0, 2, 0.1):
        placed = []
        staged.draw(t, BEAT, (0, 0), {}, placed)
        a, b = (p.box for p in placed)
        assert a[2] <= b[0] and a[0] >= 0 and b[2] <= 540


def test_another_seed_is_another_look_with_the_same_timing():
    def scene(seed):
        return Scene(0, 4, effects.garden, [Actor("a", puppet_look(), 0.4, 0.5, 0.9, acts=[Act("sare", 0, 4)])],
                     [effects.Clouds, effects.Flowers], seed=seed)
    one, frame_one = boxes(scene(1), 1.0)
    again, frame_again = boxes(scene(1), 1.0)
    two, frame_two = boxes(scene(2), 1.0)
    assert np.array_equal(np.asarray(frame_one), np.asarray(frame_again))
    assert not np.array_equal(np.asarray(frame_one), np.asarray(frame_two))
    assert one == two, "the characters do the same thing at the same time"


def test_the_tempo_is_found():
    rate = 16000
    song = np.zeros(rate * 12, np.float32)
    for k in np.arange(0.2, 12, 0.5):  # 120 bpm clicks
        song[int(k * rate): int(k * rate) + 400] = 0.8 * np.sin(np.arange(400) / 3)
    beat = motions.beat_of(song, rate)
    assert beat.period == pytest.approx(0.5, abs=0.02) and beat.phase % 0.5 == pytest.approx(0.2, abs=0.03)


def test_motions_start_and_stop_softly():
    assert motions.weight(0, 0, 4) == 0 and motions.weight(0.05, 0, 4) < 0.05 and motions.weight(2, 0, 4) == 1
    hop = [motions.hop(t, BEAT, {}).dy for t in np.arange(0, 2, 1 / 30)]
    assert max(np.abs(np.diff(hop))) < 0.04, "no jumps from one frame to the next"


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_render_makes_a_video_with_the_song(tmp_path):
    import wave
    voice = tmp_path / "song.wav"
    t = np.arange(3 * 16000) / 16000
    with wave.open(str(voice), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
        out.writeframes((0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes())
    cast = [Actor("a", puppet_look(), 0.4, 0.3, 0.9, acts=[Act("sare", 0, 3)]),
            Actor("f", effects.butterfly(), 0.2, 0.7, 0.3, flying=True, acts=[Act("zboara", 0, 3)], blink_every=None)]
    output = tmp_path / "anim.mp4"
    stage.render([Scene(0, 3, effects.garden, cast, [effects.Twinkles])], voice, output, 0, 2,
                 stage.Output((320, 180), 28, "veryfast"))
    probe = media.probe_video(output)
    assert (probe["width"], probe["height"], probe["codec_audio"]) == (320, 180, "aac")
    assert probe["duration"] == pytest.approx(2, abs=0.1)


def test_without_deformation_a_hop_stays_on_the_floor_and_shows_the_jumping_frame():
    picture, face = star()
    jumping = picture.copy()
    ImageDraw.Draw(jumping).ellipse((10, 10, 60, 60), (0, 0, 255, 255))  # the same character, another pose
    hopper = Actor("a", stage.Look(picture, face, {"sare": jumping}), 0.5, 0.5, 0.9, acts=[Act("sare", 0, 4)])
    plain_hopper = Actor("b", stage.Look(picture, face), 0.5, 0.5, 0.9, acts=[Act("sare", 0, 4)])
    for actor in (hopper, plain_hopper):
        scene = Scene(0, 4, plain, [actor], zoom=(1, 1), rigid=True)
        feet = {boxes(scene, t)[0][actor.name][3] for t in np.arange(0.6, 3.4, 0.1)}
        tall = {boxes(scene, t)[0][actor.name][3] - boxes(scene, t)[0][actor.name][1] for t in np.arange(0.6, 3.4, 0.1)}
        assert max(feet) - min(feet) <= 3, "never off the floor"
        if actor is plain_hopper:  # (the other one's frame is a little larger: it shows when the frame does)
            assert max(tall) - min(tall) <= 3, "never squashed"
    staged = stage.Staged(Scene(0, 4, plain, [hopper], zoom=(1, 1), rigid=True), SIZE)
    shown = lambda t: (np.abs(np.asarray(staged.draw(t, BEAT, (0, 0), {}), int)[..., :3] - (0, 0, 255)).sum(-1) < 60).sum()  # noqa: E731
    blue = [shown(t) for t in np.arange(0.6, 3.4, 0.05)]
    assert max(blue) > 50 and min(blue) == 0, "the jumping frame comes and goes on the beat"


def test_a_clapping_frame_comes_on_the_beat_and_goes_between():
    on = motions.clap(0.0, BEAT, {"rigid": True, "frames": ("palme",)})
    off = motions.clap(BEAT.period / 2, BEAT, {"rigid": True, "frames": ("palme",)})
    assert on.look == "palme" and on.blend > 0.95 and off.blend < 0.05
    assert motions.clap(0.0, BEAT, {"rigid": True}).look is None, "no frame: a nod, nothing made up"


def test_a_frame_a_little_off_is_put_back_in_place():
    from baby_video_studio import library
    picture, _ = star()
    frame = Image.new("RGBA", picture.size)
    frame.paste(picture, (9, -6))
    back = library.align(picture, frame)
    assert np.abs(np.asarray(back, int) - np.asarray(picture, int)).mean() < \
        0.2 * np.abs(np.asarray(frame, int) - np.asarray(picture, int)).mean()


def test_without_deformation_eyes_close_only_in_a_frame():
    picture, face = star()
    look = stage.Look(picture, face)
    assert np.array_equal(np.asarray(look.image(200, lids=1.0, rigid=True)), np.asarray(look.image(200, rigid=True))), \
        "no drawn eyelids"
    shut = picture.copy()
    ImageDraw.Draw(shut).rectangle((0, 0, 30, 30), (0, 0, 0, 255))
    framed = stage.Look(picture, face, {"ochi_inchisi": shut})
    assert not np.array_equal(np.asarray(framed.image(200, lids=1.0, rigid=True)), np.asarray(framed.image(200, rigid=True)))


def test_balloons_and_hearts_keep_coming_late_in_the_song():
    for effect in (effects.Balloons(SIZE), effects.Hearts(SIZE)):
        drawn = []
        for t in np.arange(100.0, 125.0, 0.5):  # long after the song began
            frame = plain(SIZE, 0).convert("RGBA")
            effect.draw(frame, t)
            drawn.append(np.abs(np.asarray(frame, int) - np.asarray(plain(SIZE, 0).convert("RGBA"), int)).sum() > 0)
        assert any(drawn), type(effect).__name__


def test_a_close_up_looks_at_the_chosen_place():
    actor = Actor("a", puppet_look(), 0.4, 0.8, 0.9)
    middle = stage.Staged(Scene(0, 4, plain, [actor], zoom=(1.3, 1.3)), SIZE).draw(2.0, BEAT, (0, 0), {})
    closer = stage.Staged(Scene(0, 4, plain, [actor], zoom=(1.3, 1.3), focus=(0.8, 0.7)), SIZE).draw(2.0, BEAT, (0, 0), {})
    shift = lambda frame: np.argwhere(np.abs(np.asarray(frame.convert("RGB"), int) - np.asarray(plain(SIZE, 0), int)).sum(-1) > 30)[:, 1].mean()  # noqa: E731
    assert shift(closer) < shift(middle) - 20, "the character on the right comes towards the middle of the picture"


def test_a_clap_goes_from_hands_apart_to_hands_together():
    pose = motions.clap(0.0, BEAT, {"rigid": True, "frames": ("palme", "palme_deschise")})
    assert pose.look == "palme" and pose.under == "palme_deschise"


def test_clapping_frames_are_used_in_any_style_and_in_a_dance_without_deformation():
    frames = {"frames": ("palme", "palme_deschise")}
    assert motions.clap(0.0, BEAT, {**frames, "skeleton": False}).look == "palme", "natural style, no skeleton"
    assert motions.clap(0.0, BEAT, {**frames, "rigid": True}).look == "palme"
    dancing = motions.dance(0.0, BEAT, {**frames, "rigid": True})
    assert dancing.look == "palme" and dancing.under == "palme_deschise"


def test_confetti_falls_slowly_and_a_title_comes_softly_on_top():
    frame = Image.new("RGBA", SIZE, (0, 0, 0, 255))
    rain = effects.Confetti(SIZE, seed=1)
    rain.draw(frame, 3.0)
    assert np.asarray(frame)[..., :3].any()  # some pieces are on the screen
    late = stage.Scene(0.0, 10.0, lambda s, seed: Image.new("RGB", s, (30, 30, 30)), [], title="Are mama o fetiță")
    staged = stage.Staged(late, SIZE)
    before, after = (np.asarray(staged.draw(t, BEAT, (0, 0), {})).astype(int) for t in (0.5, 4.0))
    assert (before[..., 0] == 30).all()  # nothing yet in the first second
    assert (after[..., 0] > 200).sum() > 500  # then the pink and white words, at the top
    assert (after[: SIZE[1] // 3, :, 0] > 200).sum() == (after[..., 0] > 200).sum()


def test_rocking_to_sleep_stays_within_two_degrees():
    angles = [motions.ACTIONS["legana_lin"](t / 10, BEAT, {"phase": 0.3}).angle for t in range(200)]
    assert 1.9 < max(abs(a) for a in angles) <= 2.0


def test_the_haze_a_background_remover_leaves_does_not_count_as_the_picture():
    picture = Image.new("RGBA", (200, 300), (255, 255, 255, 6))  # almost invisible haze everywhere
    ImageDraw.Draw(picture).rectangle((60, 40, 140, 250), fill=(200, 80, 120, 255))  # the character
    picture.putpixel((5, 295), (0, 0, 0, 120))  # a stray speck in the corner
    assert stage.solid(picture).getbbox() == (60, 40, 141, 251)  # its feet are its lowest visible pixels
    assert stage.solid(picture).getpixel((100, 100)) == (200, 80, 120, 255)  # the character itself is untouched
