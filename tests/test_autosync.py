import numpy as np
import pytest

from baby_video_studio import autosync, timeline
from baby_video_studio.media import RenderError

LYRICS = """[Strofa 1]
Luna strălucește lin
Cerul nopții e senin

[Refren]
Nani nani puișor
Somn ușor somn ușor

[Strofa 2]
Un iepuraș cu blana moale
[1:05.5] Doarme liniștit pe-o floare

[Refren]
"""


def sung(text: str, start: float, seconds_per_word: float = 0.6, probability: float = 0.95) -> list:
    words = []
    for word in text.split():
        words.append([start, start + seconds_per_word - 0.1, " " + word, probability])
        start += seconds_per_word
    return words


def heard() -> list:
    return (sung("Muzica", 3, 1.2, 0.7)  # the model's invention during the instrumental intro: a single word
            + sung("Luna strălucește lin", 10) + sung("Cerul nopții e senin", 13)
            + sung("Nani nani puișor", 17) + sung("Somn usor somn usor", 20)
            + sung("Un iepuras cu blana moale", 40)  # sung after a long instrumental break
            + sung("Doarme liniștit pe-o floare", 65.5)
            + sung("Nani nani puișor", 70) + sung("Somn ușor somn ușor", 73)
            + sung("Nani nani puișor", 76) + sung("Somn ușor somn ușor", 79)  # a chorus sung once more than written
            + sung("Să vă mulțumim pentru vizionare", 110, 0.1))  # invented in the silence at the end


def test_lines_get_the_time_they_are_sung_and_pauses_get_their_own_rows():
    rows = autosync.align(timeline.rows_from_lyrics(LYRICS), heard(), 120)
    by_text = {}
    for row in rows:
        by_text.setdefault(row.text, []).append(row)
    assert rows[0].section == timeline.INTRO and rows[0].start == 0 and rows[0].text == timeline.INSTRUMENTAL
    assert by_text["Luna strălucește lin"][0].start == 10, "the intro lasts until the first sung word, not the invented 'Muzica'"
    assert by_text["Cerul nopții e senin"][0].start == 13
    assert by_text["Un iepuraș cu blana moale"][0].start == 40
    assert by_text["Doarme liniștit pe-o floare"][0].start == 65.5, "a time written in the lyrics is kept"
    assert by_text["Doarme liniștit pe-o floare"][0].confidence is None
    starts = [r.start for r in rows]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)

    pauses = [r for r in rows[1:] if r.text == timeline.INSTRUMENTAL]
    assert [round(p.start) for p in pauses] == [22, 81], "the break before Strofa 2 and the silent ending"
    assert [p.section for p in pauses] == ["Refren", "Refren"], "a pause continues the section (and picture) before it"
    extra = [r for r in rows if r.text.startswith(timeline.EXTRA)]
    assert len(extra) == 1 and "Nani" in extra[0].text and extra[0].confidence < autosync.SURE, \
        "singing that is not in the lyrics is shown and flagged, not hidden inside another line"
    assert timeline.lyric_lines(rows) == timeline.lyric_lines(timeline.rows_from_lyrics(LYRICS)), \
        "every written line is kept once, repeated choruses included"


def test_a_line_that_was_not_heard_is_placed_between_its_neighbours_and_flagged():
    words = [w for w in heard() if not 13 <= w[0] < 17]  # the model missed "Cerul nopții e senin"
    rows = autosync.align(timeline.rows_from_lyrics(LYRICS), words, 120)
    missed = next(r for r in rows if r.text == "Cerul nopții e senin")
    assert missed.confidence == 0 and missed.confidence < autosync.SURE
    assert 11 < missed.start < 17
    assert all(r.confidence >= autosync.SURE for r in rows if r.text in ("Luna strălucește lin", "Un iepuraș cu blana moale"))


def test_a_song_that_starts_singing_at_once_has_no_intro_row():
    rows = autosync.align(timeline.rows_from_lyrics("Luna strălucește lin\nCerul nopții e senin"),
                          sung("Luna strălucește lin", 0.8) + sung("Cerul nopții e senin", 3), 10)
    assert [r.text for r in rows] == ["Luna strălucește lin", "Cerul nopții e senin", timeline.INSTRUMENTAL]
    assert rows[0].start == 0


def test_nothing_heard_flags_every_line():
    rows = autosync.align(timeline.rows_from_lyrics(LYRICS), [], 120)
    assert all(r.confidence == 0 for r in rows if r.start != 65.5 and r.text != timeline.INSTRUMENTAL)


def test_a_song_is_analysed_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(autosync, "CACHE", tmp_path / "voce")
    monkeypatch.setattr(autosync, "decode", lambda path, rate: np.zeros(rate))
    monkeypatch.setattr(autosync, "_transcribe", lambda samples, progress: (calls.append(1) or heard(), "test"))
    song = tmp_path / "melodie.mp3"
    song.write_bytes(b"cantec")
    assert not autosync.is_cached(song, False)
    first = autosync.hear(song, False, lambda f, m: None)
    assert autosync.is_cached(song, False) and not autosync.is_cached(song, True)
    assert autosync.hear(song, False, lambda f, m: None) == first and len(calls) == 1
    song.write_bytes(b"alt cantec")
    autosync.hear(song, False, lambda f, m: None)
    assert len(calls) == 2, "a different file is analysed again"


class FakeModel:
    def transcribe(self, samples, **options):
        class Word:
            start, end, word, probability = 1.0, 1.5, " Nani", 0.9

        class Piece:
            end, words = 1.5, [Word()]

        return iter([Piece()]), None


def test_short_on_memory_falls_back_to_the_small_model(monkeypatch):
    def load(name):
        if name == autosync.MODEL:
            raise RuntimeError("std::bad_alloc")
        return FakeModel()

    monkeypatch.setattr(autosync, "_load", load)
    messages = []
    words, model = autosync._transcribe(np.zeros(autosync.RATE * 2, np.float32), lambda f, m: messages.append(m))
    assert model == autosync.SMALL_MODEL and words == [[1.0, 1.5, " Nani", 0.9]]
    assert any("Memoria nu ajunge" in m for m in messages)

    monkeypatch.setattr(autosync, "_load", lambda name: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(RenderError, match="Închide alte programe"):
        autosync._transcribe(np.zeros(autosync.RATE, np.float32), lambda f, m: None)
