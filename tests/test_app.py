import shutil
import subprocess
from pathlib import Path

import pytest
import streamlit
from PIL import Image
from streamlit.testing.v1 import AppTest

from baby_video_studio import media, pictures, planner, projects
from baby_video_studio.models import LogoSettings
from test_render import have_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
LYRICS = "[Strofa 1]\nLuna strălucește lin\n\n[Refren]\nNani, nani, puișor\n\n[Outro]\nSomn ușor"
GENERATE = "Generează planul scenelor"


def click(app, label):
    return next(b for b in app.button if label in b.label).click().run()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """The test never reads or writes the user's own folders."""
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(projects, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(projects, "DEFAULTS_DIR", tmp_path / "defaults")
    monkeypatch.setattr(projects, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(pictures, "available", lambda: False)  # the vision model has its own tests
    (tmp_path / "defaults").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "input/audio").mkdir(parents=True)
    (tmp_path / "input/images").mkdir()
    Image.new("RGBA", (200, 200), (250, 200, 60, 255)).save(tmp_path / "defaults" / "logo - test.png")
    (tmp_path / "defaults" / "logo.json").write_text(LogoSettings(file="logo - test.png", enabled=True).model_dump_json(), encoding="utf-8")
    for name, color in (("Dreamy Lamb Under the Stars.png", "#6688dd"), ("Dreamy Moonlit Bunny Bedtime.png", "#ddcc66"),
                        ("Dreamy Moonlit Teddy Bear Cuddle.png", "#dd88aa"), ("poza.png", "#88cc88")):
        Image.new("RGB", (800, 450), color).save(tmp_path / "input/images" / name)
    subprocess.run([media.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=60",
                    str(tmp_path / "input/audio/melodie.mp3")], check=True)
    return tmp_path


def start(name, timing="estimated"):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not app.exception
    app.sidebar.text_input[0].set_value(name)
    next(b for b in app.sidebar.button if b.label == "Creează proiectul").click().run()
    assert not app.exception
    click(app, "input/")
    assert not app.exception
    next(r for r in app.radio if "momentele" in r.label).set_value(timing).run()
    assert not app.exception
    return app


def editor_returning(monkeypatch, change):
    """data_editor that hands back the rows with `change` applied, as if typed in the browser."""
    real_editor = streamlit.data_editor

    def editor(rows, **kwargs):
        shown = real_editor(rows, **kwargs)
        if not kwargs.get("key", "").startswith(("timeline_", "plan_")):  # the change is meant for the rows table
            return shown
        return [{**row, **change.get(i, {})} for i, row in enumerate(rows)]

    monkeypatch.setattr(streamlit, "data_editor", editor)


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_ui_plan_is_reviewed_then_rendered_and_restored(isolated):
    app = start("Cântec de probă")
    project = app.session_state.project
    assert not project.scenes, "the plan waits for the button"
    assert not any("Previzualizare" in b.label for b in app.button)

    click(app, GENERATE)
    assert not app.exception
    assert app.session_state.project.scenes

    story = next(t for t in app.text_area if "Descrie" in t.label)
    story.set_value("O fetiță cu ursulețul. Apoi o oiță printre stele.").run()
    assert not app.exception
    assert any("Ai schimbat" in w.value for w in app.warning), "stale plans are flagged, not silently replaced"
    click(app, GENERATE)
    assert app.session_state.project.scenes[0].image.endswith("Teddy Bear Cuddle.png")
    assert not any("Ai schimbat" in w.value for w in app.warning)

    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    next(t for t in app.text_input if t.key.endswith("poza.png")).set_value("oiță").run()
    click(app, GENERATE)
    assert not app.exception
    scenes = app.session_state.project.scenes
    assert {s.lyric_section for s in scenes} == {"Strofa 1", "Refren", "Outro"}
    assert len({s.image for s in scenes}) == 4

    next(c for c in app.checkbox if "Sincronizează" in c.label).uncheck().run()
    click(app, GENERATE)
    assert not any(s.music_cut for s in app.session_state.project.scenes)

    click(app, "Previzualizare")
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    assert (isolated / "projects" / "Cântec de probă" / "previzualizare.mp4").exists()
    assert app.success

    project = app.session_state.project
    assert project.logo.file and project.logo.enabled, "new projects start from the saved logo defaults"
    next(c for c in app.checkbox if c.label == "Afișează logo-ul").uncheck().run()
    assert not app.exception and not app.session_state.project.logo.enabled
    assert any("Logo-ul canalului este oprit" in i.value for i in app.info), "the render step says the logo is off"

    reopened = projects.load("Cântec de probă")
    assert reopened.storyboard.startswith("O fetiță") and reopened.lyrics == LYRICS
    assert reopened.image_tags == {"poza.png": "oiță"}
    assert [(s.lyric_section, s.image, s.start_frame, s.frames) for s in reopened.scenes] == [
        (s.lyric_section, s.image, s.start_frame, s.frames) for s in app.session_state.project.scenes]
    shutil.rmtree(isolated / "projects")


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_table_edits_reach_the_saved_plan(isolated, monkeypatch):
    change = {}
    editor_returning(monkeypatch, change)
    app = start("Tabel")
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    click(app, GENERATE)
    original = app.session_state.project.scenes
    assert len(original) >= 3

    wanted = planner.parse_stamp(planner.stamp(planner.scene_cuts(original)[0] + 60))
    change[1] = {"Început": planner.stamp(wanted), "Secțiune": "Refrenul meu", "Imagine": "poza.png", "Efect animație": "Depărtare lentă"}
    app.run()
    assert not app.exception
    scenes = projects.load("Tabel").scenes
    assert planner.scene_cuts(scenes)[0] == wanted
    assert scenes[1].time_source == "manual" and scenes[1].lyric_section == "Refrenul meu"
    assert scenes[1].image == "poza.png" and scenes[1].motion == "zoom_out"

    button = next(b for b in app.button if GENERATE in b.label)
    assert button.disabled, "regenerating must not silently discard corrected times"
    next(c for c in app.checkbox if "Înlocuiește" in c.label).check().run()
    assert not next(b for b in app.button if GENERATE in b.label).disabled

    change[1] = {"Început": "nu e timp"}
    app.run()
    assert any("Nu înțeleg" in e.value for e in app.error)
    assert not any("Previzualizare" in b.label for b in app.button), "no render while the table holds an unusable time"


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_synced_timeline_is_built_timed_checked_and_rendered(isolated, monkeypatch):
    change = {}
    editor_returning(monkeypatch, change)
    app = start("Sincron", "synced")
    assert not any("Previzualizare" in b.label for b in app.button)
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    click(app, "Creează rândurile din versuri")
    assert not app.exception
    rows = app.session_state.project.timeline
    assert [r.section for r in rows] == ["Introducere", "Strofa 1", "Refren", "Outro"]
    assert all(r.image for r in rows) and all(r.start is None for r in rows[1:]), "images suggested, times left to the user"
    assert any("nu au încă timp" in e.value for e in app.error)
    assert not any("Previzualizare" in b.label for b in app.button), "no render before every row is timed"

    change.update({2: {"Început": "0:20.0"}, 1: {"Început": "0:40.0"}, 3: {"Început": "0:50.0"}})
    app.run()
    assert any("ordinea" in e.value for e in app.error), "a mistyped time is reported, not silently reordered"

    change.update({1: {"Început": "0:05.0"}, 3: {"Început": "0:40.0", "Imagine": "poza.png"}})
    app.run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    saved = projects.load("Sincron").timeline
    assert [r.start for r in saved] == [0, 5, 20, 40] and saved[3].image == "poza.png"
    assert any("Cronologia este completă" in s.value for s in app.success)

    click(app, "Previzualizare")
    assert not app.exception and not app.error, [e.value for e in app.error]
    assert (isolated / "projects" / "Sincron" / "previzualizare.mp4").exists()


@pytest.mark.skipif(not have_ffmpeg(), reason="FFmpeg lipsește")
def test_automatic_sync_builds_a_timeline_that_renders(isolated, monkeypatch):
    from baby_video_studio import autosync
    from test_autosync import sung

    calls = []
    words = sung("Luna strălucește lin", 8) + sung("Nani nani puișor", 20) + sung("Somn ușor", 40)
    monkeypatch.setattr(autosync, "hear", lambda path, vocals, progress: calls.append(vocals) or words)
    app = start("Automat", "auto")
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    click(app, "Sincronizează automat")
    assert not app.exception and calls == [False]
    rows = projects.load("Automat").timeline
    assert [r.text for r in rows] == ["🎵 (instrumental)", "Luna strălucește lin", "🎵 (instrumental)", "Nani, nani, puișor",
                                      "🎵 (instrumental)", "Somn ușor", "🎵 (instrumental)"]
    assert [r.start for r in rows[1:]] == [8, 9.7, 20, 21.7, 40, 41.1], "lines start when sung; pauses after each"
    assert all(r.image for r in rows), "the automatic storyboard gives every row a picture"
    assert not app.error, [e.value for e in app.error]
    assert any("Niciun rând nesigur" in s.value for s in app.success)
    assert any("Cronologia este completă" in s.value for s in app.success)

    button = next(b for b in app.button if "Sincronizează automat" in b.label)
    assert not button.disabled, "automatic times can be redone without a confirmation"
    click(app, "Previzualizare")
    assert not app.exception and not app.error, [e.value for e in app.error]
    assert (isolated / "projects" / "Automat" / "previzualizare.mp4").exists()


def test_an_old_broken_timeline_does_not_block_automatic_sync_and_can_be_analysed_again(isolated, monkeypatch):
    from baby_video_studio import autosync
    from baby_video_studio.models import Segment
    from test_autosync import sung

    heard, forgotten = [], []
    words = sung("Luna strălucește lin", 8) + sung("Nani nani puișor", 20) + sung("Somn ușor", 40)
    monkeypatch.setattr(autosync, "hear", lambda path, vocals, progress: heard.append(1) or words)
    monkeypatch.setattr(autosync, "is_cached", lambda path, vocals: True)
    monkeypatch.setattr(autosync, "forget", lambda path, vocals: forgotten.append(path.name))
    app = start("Vechi", "auto")
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    p = app.session_state.project  # the open project, as the app holds it
    p.timeline = [Segment(text="🎵 (instrumental)", start=0), Segment(text="🎵 (instrumental)", start=17),  # like "Top, top"
                  Segment(text="Luna strălucește lin", start=9.7), Segment(text="Nani, nani, puișor"), Segment(text="Somn ușor")]
    projects.save(p)
    app.run()
    assert any("nu sunt sincronizate cu vocea" in w.value for w in app.warning)
    assert not any("Niciun rând nesigur" in s.value or "Cronologia este completă" in s.value for s in app.success)
    assert not any("Înlocuiește" in c.label for c in app.checkbox), "old times out of order are not worth a confirmation"

    click(app, "Reanalizează melodia")
    assert not app.exception and forgotten == ["melodie.mp3"] and heard == [1]
    rows = projects.load("Vechi").timeline
    starts = [r.start for r in rows]
    assert starts == sorted(starts) and len(set(starts)) == len(starts) and None not in starts
    assert any("Cronologia este completă" in s.value for s in app.success)


def test_in_order():
    from baby_video_studio.models import Segment
    from baby_video_studio.timeline import in_order
    rows = lambda *t: [Segment(start=s) for s in t]
    assert in_order(rows(0, 5, 9), 10)
    assert not in_order(rows(0, 17, 9.7), 10) and not in_order(rows(0, 5, None), 10) and not in_order(rows(0, 5, 10), 10)


def test_storyboard_scenes_can_be_changed_and_keep_the_users_choice(isolated, monkeypatch):
    from baby_video_studio import autosync
    from test_autosync import sung

    words = sung("Luna strălucește lin", 8) + sung("Nani nani puișor", 20) + sung("Somn ușor", 40)
    monkeypatch.setattr(autosync, "hear", lambda path, vocals, progress: words)
    app = start("Storyboard", "auto")
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    click(app, "Sincronizează automat")
    assert not app.exception and app.session_state.project.image_seen, "the sync builds the storyboard"
    assert next(c for c in app.checkbox if "doar scenele" in c.label)

    real_editor = streamlit.data_editor

    def choose_teddy(rows, **kwargs):
        shown = real_editor(rows, **kwargs)
        if kwargs.get("key", "").startswith("scenes_") and rows:
            return [{**rows[0], "Imagine": "Dreamy Moonlit Teddy Bear Cuddle.png"}, *rows[1:]]
        return shown

    monkeypatch.setattr(streamlit, "data_editor", choose_teddy)
    app.run()
    first = projects.load("Storyboard").timeline[0]
    assert first.image == "Dreamy Moonlit Teddy Bear Cuddle.png" and first.locked, "a picture changed in the scene list is kept"
    monkeypatch.setattr(streamlit, "data_editor", real_editor)

    click(app, "Creează storyboard automat")
    assert not app.exception
    rows = projects.load("Storyboard").timeline
    assert rows[0].image == "Dreamy Moonlit Teddy Bear Cuddle.png", "regenerating keeps the user's choice"
    next(c for c in app.checkbox if "imaginile alese de mine" in c.label).check().run()
    click(app, "Creează storyboard automat")
    assert not projects.load("Storyboard").timeline[0].locked, "unless they ask to replace it"


def test_subtitles_are_made_from_the_synced_lyrics_corrected_and_downloaded(isolated, monkeypatch):
    from baby_video_studio import autosync
    from test_autosync import sung

    words = sung("Luna strălucește lin", 8) + sung("Nani nani puișor", 20) + sung("Somn ușor", 40)
    monkeypatch.setattr(autosync, "hear", lambda path, vocals, progress: words)
    app = start("Subtitrări", "auto")
    next(t for t in app.text_area if t.label == "Versurile melodiei").set_value(LYRICS).run()
    click(app, "Sincronizează automat")
    click(app, "Generează subtitrarea")
    assert not app.exception and not app.error, [e.value for e in app.error]
    subs = projects.load("Subtitrări").subtitles
    assert [(s.text, s.start, s.end) for s in subs] == [("Luna strălucește lin", 8, 9.7), ("Nani, nani, puișor", 20, 21.7),
                                                        ("Somn ușor", 40, 41.1)], "lyrics text with diacritics, sung times"
    download = app.get("download_button")[0]
    assert "Descarcă subtitrarea" in download.proto.label and not download.proto.disabled

    real_editor = streamlit.data_editor

    def overlap(rows, **kwargs):  # the user types a start inside the previous subtitle
        shown = real_editor(rows, **kwargs)
        if kwargs.get("key", "").startswith("subtitles_"):
            return [rows[0], {**rows[1], "Început": "0:09.00", "Text": "Nani, nani, puișor drag"}, rows[2]]
        return shown

    monkeypatch.setattr(streamlit, "data_editor", overlap)
    app.run()
    monkeypatch.setattr(streamlit, "data_editor", real_editor)
    app.run()
    second = projects.load("Subtitrări").subtitles[1]
    assert (second.text, second.start) == ("Nani, nani, puișor drag", 9.0), "text and times can be corrected"
    assert any("începe înainte să se termine" in e.value for e in app.error)
    assert app.get("download_button")[0].proto.disabled, "invalid times are not exported"


def test_talking_character_mode_uses_a_saved_profile_and_makes_a_preview(isolated, monkeypatch):
    import wave

    import numpy as np

    from baby_video_studio import talking
    from test_talking import star

    monkeypatch.setattr(talking, "PROFILES", isolated / "personaje")
    picture, face = star()
    profile = talking.Profile(name="Steluța Muzicală")
    profile.image = "steluta.png"
    (talking.profile_dir(profile.name)).mkdir(parents=True)
    picture.save(talking.profile_dir(profile.name) / profile.image)
    found = talking.detect_face(picture)
    profile.mouth, profile.eyes = list(found.mouth), [list(e) for e in found.eyes]
    talking.save_profile(profile)
    monkeypatch.setattr(talking, "spoken_words", lambda audio: [(0.3, 1.5, "bună"), (2.0, 4.0, "prieteni")])

    app = start("Prezentare")
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("talking").run()
    assert not app.exception
    assert next(s for s in app.selectbox if s.label == "Personajul folosit").value == "Steluța Muzicală"
    assert not any("Previzualizare 5" in b.label and not b.disabled for b in app.button), "needs a voice first"

    p = app.session_state.project
    t = np.arange(6 * 16000) / 16000
    sound = 0.3 * np.sin(2 * np.pi * 600 * t) * ((t > 0.3) & (t < 1.5) | (t > 2.0) & (t < 4.0))
    projects.media_dir(p).mkdir(parents=True, exist_ok=True)
    with wave.open(str(projects.media_dir(p) / "voce.wav"), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
        out.writeframes((sound * 32767).astype("<i2").tobytes())
    p.talk.voice = "voce.wav"
    app.run()
    click(app, "Previzualizare 5 secunde")
    assert not app.exception and not app.error, [e.value for e in app.error]
    preview = isolated / "projects" / "Prezentare" / "previzualizare-personaj.mp4"
    assert media.probe_video(preview)["height"] == 1920
    assert projects.load("Prezentare").kind == "talking"
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("music").run()
    assert not app.exception and any("Melodia și imaginile" in h.value for h in app.subheader), "the music video is still there"


def test_automatic_animation_mode_plans_previews_and_changes_one_scene(isolated, monkeypatch):
    from baby_video_studio import director, library, stage, talking, timeline
    from baby_video_studio.models import Segment
    from test_talking import star

    monkeypatch.setattr(talking, "PROFILES", isolated / "personaje")
    monkeypatch.setattr(library, "DECORS", isolated / "decoruri")
    monkeypatch.setattr(library, "TEMPLATES", isolated / "sabloane")
    monkeypatch.setattr(stage, "CLIPS", isolated / "clipuri")
    monkeypatch.setattr(director, "output_for", lambda settings, preview: stage.Output((192, 108), 30, "ultrafast"))
    monkeypatch.setattr(talking, "spoken_words", lambda audio: [(9.0, 10.0, "steluța"), (20.0, 21.0, "sare")])
    picture, _ = star()
    profile = talking.Profile(name="Steluța", image="steluta.png")
    talking.profile_dir("Steluța").mkdir(parents=True)
    picture.save(talking.profile_dir("Steluța") / profile.image)
    face = talking.detect_face(picture)
    profile.mouth, profile.eyes = list(face.mouth), [list(e) for e in face.eyes]
    talking.save_profile(profile)

    app = start("Animație")
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("animation").run()
    assert not app.exception, app.exception
    assert any("Sincronizarea cu vocea" in h.value for h in app.subheader)
    p = app.session_state.project
    p.lyrics = "[Strofa 1]\nSteluța cântă lin\nFluturașii iar apar\n\n[Refren]\nSărim toți la fel ca ea"
    p.timeline = [Segment(text=timeline.INSTRUMENTAL, section="Introducere", start=0, confidence=1.0),
                  *(Segment(text=t, section=s, start=a, confidence=0.9) for t, s, a in
                    (("Steluța cântă lin", "Strofa 1", 8.0), ("Fluturașii iar apar", "Strofa 1", 16.0),
                     ("Sărim toți la fel ca ea", "Refren", 30.0)))]
    app.run()
    assert not app.exception, app.exception
    cast = next(m for m in app.multiselect if "Personajele din videoclip" in m.label)
    assert cast.value == ["Steluța", "Fluturaș galben"], "my character first, then a drawn friend"
    assert next(s for s in app.selectbox if "Cine cântă" in s.label).value == "Steluța"
    click(app, "Generează animația automat")
    assert not app.exception and not app.error, [e.value for e in app.error]
    p = app.session_state.project
    assert p.kind == "animation" and len(p.anim.scenes) >= 3 and p.anim.scenes[-1].end == pytest.approx(60, abs=0.1)
    preview = isolated / "projects" / "Animație" / "previzualizare-animatie.mp4"
    assert media.probe_video(preview)["width"] == 192
    before = [s.model_copy(deep=True) for s in p.anim.scenes]
    click(app, "Surprinde-mă")
    assert not app.exception and not app.error, [e.value for e in app.error]
    p = app.session_state.project
    assert p.anim.scenes[0].look == 1 and p.anim.scenes[1:] == before[1:], "only the chosen scene changed"
    assert (isolated / "projects" / "Animație" / "previzualizare-scena.mp4").exists()
    assert projects.load("Animație").anim.scenes[0].edited
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("music").run()
    assert not app.exception and any("Melodia și imaginile" in h.value for h in app.subheader), "the music video is still there"


def test_the_safe_zone_of_a_decor_is_set_seen_and_saved(isolated, monkeypatch):
    from io import BytesIO

    from baby_video_studio import depth, library, pictures, talking
    monkeypatch.setattr(depth, "available", lambda: False)
    monkeypatch.setattr(talking, "PROFILES", isolated / "personaje")
    monkeypatch.setattr(library, "DECORS", isolated / "decoruri")
    monkeypatch.setattr(pictures, "available", lambda: False)
    buffer = BytesIO()
    Image.new("RGB", (800, 450), (90, 170, 80)).save(buffer, "PNG")
    library.add_decor("Pajiste.png", buffer.getvalue())
    app = start("Zona")
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("animation").run()
    assert not app.exception, app.exception
    assert any("Zona: de la stânga la dreapta" in s.label for s in app.slider), "the zone editor is there"
    click(app, "Salvează zona decorului")
    assert not app.exception, app.exception
    assert library.decor("Pajiste").zone == pytest.approx((0.05, 0.62, 0.95, 0.97))


def test_a_skeleton_is_proposed_seen_and_kept(isolated, monkeypatch):
    from baby_video_studio import library, rig, talking
    from test_rig import figure
    if not rig.available():
        pytest.skip("no OpenGL 3.3 here")
    monkeypatch.setattr(talking, "PROFILES", isolated / "personaje")
    monkeypatch.setattr(library, "DECORS", isolated / "decoruri")
    profile = talking.Profile(name="Copila", image="copila.png", kind="om")
    talking.profile_dir("Copila").mkdir(parents=True)
    figure().save(talking.profile_dir("Copila") / profile.image)
    talking.save_profile(profile)
    library._look.cache_clear()
    app = start("Schelet")
    next(r for r in app.radio if "Ce fel de videoclip" in r.label).set_value("animation").run()
    assert not app.exception, app.exception
    click(app, "Propune scheletul automat")
    assert not app.exception, app.exception
    assert len(talking.load_profile("Copila").rig) == len(rig.POINTS)
    assert not app.error, [e.value for e in app.error]
