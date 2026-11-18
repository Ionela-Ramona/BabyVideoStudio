import numpy as np

from baby_video_studio import pictures, timeline
from baby_video_studio.models import Segment

IMAGES = ["morcov.png", "fluturi.png", "salt.png", "apus.png"]
SEEN = {"morcov.png": {"iepuraș": 1, "morcov": 1, "mâncare": 0.9, "gard": 0.8},
        "fluturi.png": {"iepuraș": 1, "fluturi": 1, "flori": 0.9},
        "salt.png": {"iepuraș": 1, "sărituri": 1},
        "apus.png": {"iepuraș": 0.9, "apus": 1, "somn": 1, "soare": 0.7}}
SONG = [("Introducere", "🎵 (instrumental)", 0), ("Strofa 1", "Fluturașii zboară printre flori", 6),
        ("Strofa 1", "Un fluture vine lângă el", 9), ("Strofa 1", "Crește-un morcov roșu, mare", 13),
        ("Strofa 1", "Și cu poftă l-a mâncat", 16), ("Refren", "Țup, țup, iepuraș", 22), ("Refren", "Hop, hop, hop, sărim", 25),
        ("Strofa 2", "Soarele coboară lin", 31), ("Strofa 2", "Iepurașul obosit doarme", 35), ("Refren", "Țup, țup, iepuraș", 41),
        ("Refren", "Hop, hop, hop, sărim", 44), ("Refren", "🎵 (instrumental)", 50)]
TOTAL = 62


def rows(locked: dict[int, str] | None = None) -> list[Segment]:
    return [Segment(section=section, text=text, start=start, image=(locked or {}).get(i, ""), locked=i in (locked or {}))
            for i, (section, text, start) in enumerate(SONG)]


def board(segments, keep_mine=True, seen=SEEN, tags=None):
    return timeline.storyboard(segments, IMAGES, seen, tags or {}, TOTAL, 2, keep_mine)


def test_lines_about_the_same_thing_share_the_picture_that_shows_it():
    result, _ = board(rows())
    by_text = {r.text: r.image for r in result}
    assert by_text["Fluturașii zboară printre flori"] == by_text["Un fluture vine lângă el"] == "fluturi.png"
    assert by_text["Crește-un morcov roșu, mare"] == by_text["Și cu poftă l-a mâncat"] == "morcov.png"
    assert by_text["Hop, hop, hop, sărim"] == "salt.png"
    assert by_text["Soarele coboară lin"] == by_text["Iepurașul obosit doarme"] == "apus.png"
    assert [r.start for r in result] == [r.start for r in rows()], "the sung times never change"
    assert not timeline.problems(result, IMAGES, TOTAL, 2), "every scene is long enough to render"
    lengths = [s["end"] - s["start"] for s in timeline.scene_list(result, IMAGES, SEEN, {}, TOTAL)]
    assert all(timeline.SHORT <= x for x in lengths) and max(lengths[1:-1]) <= timeline.LONG, lengths
    assert result[-1].image == result[-2].image == "salt.png", "the music after the last chorus stays on its picture"


def test_a_picture_the_user_chose_is_kept_unless_they_ask_to_replace_it():
    mine = rows({3: "salt.png", 4: "salt.png"})
    kept, _ = board(mine)
    assert [kept[3].image, kept[4].image] == ["salt.png", "salt.png"] and kept[3].locked
    replaced, _ = board(mine, keep_mine=False)
    assert replaced[3].image == "morcov.png" and not replaced[3].locked


def test_the_words_of_the_lyrics_in_the_users_description_count():
    tags = {"salt.png": "iepurașul mănâncă morcovul, ronț ronț"}
    result, _ = board(rows(), seen={}, tags=tags)  # no vision: only names and descriptions
    assert next(r.image for r in result if r.text == "Și cu poftă l-a mâncat") == "salt.png"


def test_scenes_without_a_fitting_picture_are_flagged_with_a_suggestion():
    segments = [Segment(section="Strofa", text="Stă o buburuză mică", start=0, image="apus.png"),
                Segment(section="Strofa", text="Pe o frunză, liniștită", start=6, image="apus.png")]
    [scene] = timeline.scene_list(segments, IMAGES, SEEN, {}, 12)
    assert scene["check"] and scene["match"] < timeline.GOOD_MATCH and "buburuză" in scene["hint"]
    good = timeline.scene_list(board(rows())[0], IMAGES, SEEN, {}, TOTAL)
    assert not any(s["check"] for s in good) and len(good) < len(SONG), "lines are grouped into scenes"


def test_concepts_are_found_in_romanian_lyrics_and_english_file_names():
    assert {pictures.LABELS[k] for k in pictures.concepts_in("Iepurașul a mâncat morcovul")} >= {"iepuraș", "mâncare", "morcov"}
    assert {pictures.LABELS[k] for k in pictures.concepts_in("Cozy Bunny Sunset Meadow")} >= {"iepuraș", "apus", "pajiște"}
    assert "peștișor" not in {pictures.LABELS[k] for k in pictures.concepts_in("Soarele apune peste grădină")}, \
        "peste means over, not fish"


def test_what_the_model_sees_is_combined_with_the_words(monkeypatch, tmp_path):
    bank = np.load(pictures.BANK)
    assert bank["text"].shape[0] == len(pictures.CONCEPTS), "rebuild concepts.npz with tools/make_concepts.py"
    carrot = bank["text"][pictures.LABELS.index("morcov")]
    monkeypatch.setattr(pictures, "vectors", lambda paths, progress: {p: carrot for p in paths})
    seen, note = pictures.evidence({"Bunny.png": tmp_path / "a.png"}, {"Bunny.png": "doarme sub lună"}, lambda f, m: None)
    assert not note and seen["Bunny.png"]["morcov"] == 1.0, "the picture shows a carrot"
    assert seen["Bunny.png"]["iepuraș"] == seen["Bunny.png"]["somn"] == seen["Bunny.png"]["lună"] == 1.0, "name and description"

    monkeypatch.setattr(pictures, "vectors", lambda paths, progress: (_ for _ in ()).throw(OSError("fără internet")))
    seen, note = pictures.evidence({"Bunny.png": tmp_path / "a.png"}, {}, lambda f, m: None)
    assert "fără internet" in note and seen == {"Bunny.png": {"iepuraș": 1.0}}, "without the model, the words still work"
