import pytest

from baby_video_studio import actions, director, library, stage, talking
from baby_video_studio.models import AnimationSettings, Segment
from baby_video_studio.timeline import INSTRUMENTAL
from test_render import have_ffmpeg
from test_talking import star

LINES = [("🎵", "Introducere", 0.0), ("În grădină, printre flori,", "Strofa 1", 8.0), ("Iepurașul sare-n zori.", "Strofa 1", 11.0),
         ("Fluturașii iar apar.", "Strofa 1", 14.0), ("Unul vine lângă el,", "Strofa 1", 17.0),
         ("Țup, țup, iepuraș,", "Refren", 22.0), ("Sărim toți la fel ca el!", "Refren", 26.0),
         ("Noapte bună, drăgălaș!", "Outro", 31.0), ("🎵", "Outro", 36.0)]
TOTAL = 42.0


@pytest.fixture
def characters(tmp_path, monkeypatch):
    """A rabbit and a star on the ground in a library of their own, with the drawn butterflies."""
    monkeypatch.setattr(talking, "PROFILES", tmp_path / "personaje")
    monkeypatch.setattr(library, "DECORS", tmp_path / "decoruri")
    monkeypatch.setattr(library, "TEMPLATES", tmp_path / "sabloane")
    monkeypatch.setattr(stage, "CLIPS", tmp_path / "clipuri")
    picture, _ = star()
    for name, kind in (("Iepurașul", "animal"), ("Steluța", "personaj")):
        profile = talking.Profile(name=name, kind=kind, names=actions.names_for(name))
        profile.image = "poza.png"
        talking.profile_dir(name).mkdir(parents=True)
        picture.save(talking.profile_dir(name) / profile.image)
        face = talking.detect_face(picture)
        profile.mouth, profile.eyes = list(face.mouth), [list(e) for e in face.eyes]
        talking.save_profile(profile)
    library._look.cache_clear()
    return AnimationSettings(characters=["Iepurașul", "Steluța", "Fluturaș galben", "Fluturaș roz"],
                             decors=["🎨 Grădină însorită", "🎨 Grădină noaptea"], singer="Steluța")


def rows():
    return [Segment(text=INSTRUMENTAL if t == "🎵" else t, section=s, start=a, confidence=0.9) for t, s, a in LINES]


def test_the_song_becomes_scenes_that_cover_it_in_order(characters):
    scenes = director.plan(rows(), TOTAL, characters)
    assert scenes[0].start == 0 and scenes[-1].end == TOTAL
    assert all(a.end == b.start for a, b in zip(scenes, scenes[1:]))
    assert all(4 <= s.end - s.start <= 16 for s in scenes)
    assert scenes[-1].decor == "🎨 Grădină noaptea", "„Noapte bună” picks the night"
    assert scenes[1].decor == "🎨 Grădină însorită"


def test_the_lyrics_choose_who_is_there_and_what_they_do(characters):
    scenes = director.plan(rows(), TOTAL, characters)
    verse = next(s for s in scenes if "Iepurașul sare-n zori." in s.lines)
    rabbit = next(r for r in verse.roles if r.character == "Iepurașul")
    assert any(a <= 11.0 < b and action == "sare" for a, b, action in rabbit.acts), "„Iepurașul sare” makes it hop"
    butterflies = [r for r in verse.roles if r.character.startswith("Fluturaș")]
    assert butterflies and all(r.enters == 14.0 for r in butterflies), "„Fluturașii iar apar” brings them in"
    near = next(s for s in scenes if any("lângă" in line for line in s.lines))
    assert any(r.interaction in ("urmareste", "apropie") for r in near.roles), "„Unul vine lângă el”"
    chorus = next(s for s in scenes if any("toți" in line for line in s.lines))
    assert any(r.interaction == "imita" for r in chorus.roles), "„Sărim toți la fel ca el”"
    assert all(len(s.roles) <= director.MAX_CAST for s in scenes)
    assert all(any(r.character == "Steluța" for r in s.roles) for s in scenes), "the singer is always there"


def test_nobody_touches_or_leaves_the_frame(characters):
    for aspect, size in (("16:9", (480, 270)), ("9:16", (270, 480))):
        characters.aspect = aspect
        scenes = director.plan(rows(), TOTAL, characters)
        for n, scene in enumerate(scenes):
            found = director.problems(scene, characters, size, 0.25, scenes[n - 1] if n else None)
            grounded = {k: v for k, v in found["atingeri"].items()
                        if not any(f.startswith("Fluturaș") for f in k.split(" + "))}
            assert not grounded and not found["iesiri"], (aspect, n, found)
            assert sum(found["atingeri"].values()) <= 2, (aspect, n, found)


def test_changing_one_scene_changes_only_that_scene(characters):
    characters.scenes = director.plan(rows(), TOTAL, characters)
    before = director.keys(characters.scenes, characters)
    times = [(s.start, s.end) for s in characters.scenes]
    characters.scenes[1] = director.regenerate(rows(), TOTAL, characters, 1)
    characters.scenes[2].look += 1
    director.swap_character(characters.scenes[0], "Iepurașul", "Fluturaș roz")
    assert [(s.start, s.end) for s in characters.scenes] == times, "the timing never changes"
    after = director.keys(characters.scenes, characters)
    assert [a != b for a, b in zip(before, after)][4:] == [False] * (len(after) - 4), "later scenes keep their clips"
    swapped = characters.scenes[0]
    assert all(r.character != "Iepurașul" for r in swapped.roles) and swapped.edited
    again = director.plan(rows(), TOTAL, characters, characters.scenes)
    assert again[0] == swapped, "regenerating the whole video keeps the scenes I changed"


def test_one_action_for_the_whole_scene_and_back(characters):
    scene = director.plan(rows(), TOTAL, characters)[1]
    director.set_action(scene, "Iepurașul", "danseaza")
    built = director.build(scene, characters)
    rabbit = next(a for a in built.actors if a.name == "Iepurașul")
    assert {a.action for a in rabbit.acts} == {"danseaza"}
    director.set_action(scene, "Fluturaș galben", "merge")
    assert next(r for r in scene.roles if r.character == "Fluturaș galben").action == "zboara", "flyers fly, not walk"


def test_a_scene_saved_as_template_is_reused(characters):
    scenes = director.plan(rows(), TOTAL, characters)
    library.save_template("Grădina", scenes[1])
    director.apply_template(scenes[3], library.load_template("Grădina"))
    assert scenes[3].decor == scenes[1].decor and {r.character for r in scenes[3].roles} == {r.character for r in scenes[1].roles}
    assert scenes[3].start != scenes[1].start and scenes[3].edited


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_export_draws_each_scene_once_and_redraws_only_what_changed(characters, tmp_path):
    import wave

    import numpy as np
    from baby_video_studio import media
    song = tmp_path / "song.wav"
    t = np.arange(int(TOTAL * 16000)) / 16000
    with wave.open(str(song), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
        out.writeframes((0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes())
    characters.singer = ""
    scenes = director.plan(rows(), TOTAL, characters)
    small = stage.Output((192, 108), 30, "ultrafast")
    output = tmp_path / "anim.mp4"
    tiny = lambda settings, preview: small  # noqa: E731
    director.output_for, real = tiny, director.output_for
    try:
        first = director.export(scenes, characters, song, output, True)
        again = director.export(scenes, characters, song, output, True)
        scenes[-1].look += 1
        changed = director.export(scenes, characters, song, output, True)
    finally:
        director.output_for = real
    assert first["drawn"] == len(scenes) and again["drawn"] == 0 and changed["drawn"] == 2
    probe = media.probe_video(output)
    assert (probe["width"], probe["codec_audio"]) == (192, "aac") and probe["duration"] == pytest.approx(TOTAL, abs=0.2)


def test_in_a_decor_with_a_safe_zone_everyone_stands_in_it_and_off_the_objects(characters, monkeypatch):
    from io import BytesIO

    from PIL import Image

    from baby_video_studio import pictures
    from baby_video_studio import depth
    monkeypatch.setattr(pictures, "available", lambda: False)
    monkeypatch.setattr(depth, "available", lambda: False)
    buffer = BytesIO()
    Image.new("RGB", (800, 450), (90, 170, 80)).save(buffer, "PNG")
    item = library.add_decor("Pajiste.png", buffer.getvalue())
    library.save_zone(item.name, (0.05, 0.62, 0.95, 0.96), 0.7, [(0.38, 0.7, 0.62, 0.95)])  # a bush in the middle
    characters.decors = [item.name]
    for aspect, size in (("16:9", (480, 270)), ("9:16", (270, 480))):
        characters.aspect = aspect
        scenes = director.plan(rows(), TOTAL, characters)
        for n, scene in enumerate(scenes):
            built = director.build(scene, characters, before=scenes[n - 1] if n else None)
            assert built.ground, "the zone is used"
            for actor in built.actors:
                if not actor.flying and not any(m.edge for m in actor.moves):
                    assert built.ground.inside(actor.x, actor.y) or n, (aspect, n, actor.name)
            found = director.problems(scene, characters, size, 0.25, scenes[n - 1] if n else None)
            assert not found["obstacole"] and not found["iesiri"], (aspect, n, found)


def test_without_deformation_nobody_walks_and_who_comes_in_fades_in(characters):
    characters.style = "fara_deformare"
    scenes = director.plan(rows(), TOTAL, characters)
    for n, scene in enumerate(scenes):
        built = director.build(scene, characters, before=scenes[n - 1] if n else None)
        assert built.rigid
        for actor in built.actors:
            if not actor.flying:
                assert not actor.moves, (n, actor.name, actor.moves)
    scene = scenes[1].model_copy(deep=True)
    scene.roles[0].enters = scene.start + 1.0
    actor = director.build(scene, characters).actors[0]
    assert actor.appears == scene.start + 1.0 and not actor.moves


def test_a_character_placed_by_hand_stays_there_at_its_size(characters):
    scenes = director.plan(rows(), TOTAL, characters)
    scene = scenes[1].model_copy(deep=True)
    grounded = [r for r in scene.roles if not library.character(r.character).flying]
    grounded[0].place, grounded[0].size = (0.2, 0.0), 1.3
    built = director.build(scene, characters)
    actor = next(a for a in built.actors if a.name == grounded[0].character)
    assert actor.fixed and abs(actor.x - 0.2) < 1e-6 and abs(actor.height - director.BASE_HEIGHT * library.character(actor.name).size * 1.3) < 1e-6


def test_post_chorus_and_pre_chorus_are_not_the_chorus():
    assert director._key("Chorus – catchy") == director._key("Final Chorus") == director._key("Refren 2") == "refren"
    assert director._key("Post-refren") != "refren" and director._key("Pre-Chorus") != "refren"
