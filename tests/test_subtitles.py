from baby_video_studio import timeline
from baby_video_studio.models import Segment, Subtitle

ROWS = [Segment(text=timeline.INSTRUMENTAL, section=timeline.INTRO, start=0, confidence=1.0),
        Segment(text="În grădină, printre flori,", section="Strofa 1", start=8.4, confidence=0.99),
        Segment(text="Iepurașul sare-n zori.", section="Strofa 1", start=11.1, confidence=0.4),
        Segment(text="Țup, țup, iepuraș,", section="Refren", start=28.32, confidence=0.9),
        Segment(text=timeline.INSTRUMENTAL, section="Refren", start=36.9, confidence=1.0),
        Segment(text=timeline.EXTRA + "Țup, țup", section="Refren", start=40, confidence=0.3),
        Segment(text="Țup, țup, iepuraș,", section="Refren final", start=82.06, confidence=1.0)]


def test_every_sung_line_becomes_a_subtitle_with_its_own_text():
    subs = timeline.subtitles(ROWS, 180, 0.6)
    assert [s.text for s in subs] == ["În grădină, printre flori,", "Iepurașul sare-n zori.", "Țup, țup, iepuraș,",
                                      "Țup, țup, iepuraș,"], "no instrumental or 🎤 rows; the repeated chorus stays"
    assert [(s.start, s.end) for s in subs] == [(8.4, 11.1), (11.1, 28.32), (28.32, 36.9), (82.06, 180)]
    assert [s.unsure for s in subs] == [False, True, False, False]
    assert not timeline.subtitle_problems(subs, 180)


def test_srt_is_valid_for_youtube():
    text = timeline.to_srt(timeline.subtitles(ROWS, 180, 0.6))
    assert text.startswith("1\n00:00:08,400 --> 00:00:11,100\nÎn grădină, printre flori,\n\n2\n00:00:11,100 --> 00:00:28,320\n")
    assert "4\n00:01:22,060 --> 00:03:00,000\nȚup, țup, iepuraș,\n\n" in text and text.endswith("\n\n")
    assert timeline.srt_time(3725.0004) == "01:02:05,000"


def test_invalid_times_are_reported_and_not_exported():
    bad = [Subtitle(text="a", start=1, end=3), Subtitle(text="b", start=2.5, end=4), Subtitle(text="c", start=5, end=5),
           Subtitle(text="d", start=None, end=None), Subtitle(text="e", start=8, end=200), Subtitle(text=" ", start=9, end=10)]
    errors = " ".join(timeline.subtitle_problems(bad, 180))
    for expected in ("Subtitrarea 2 („b”) începe înainte", "Subtitrarea 3 („c”) se termină înainte", "Subtitrarea 4 („d”) nu are timp",
                     "Subtitrarea 5 („e”) se termină după finalul", "Subtitrarea 6 nu are text"):
        assert expected in errors
    unmarked = [Segment(text=timeline.INSTRUMENTAL, start=0), Segment(text="Nani", start=None), Segment(text="Puișor", start=5)]
    assert "nu are timp" in timeline.subtitle_problems(timeline.subtitles(unmarked, 10, 0.6), 10)[0]


def test_file_name_has_no_diacritics_or_spaces():
    assert timeline.srt_name("Țup, țup, iepuraș!") == "Tup_Tup_Iepuras_RO.srt"
    assert timeline.srt_name("Somn ușor, puișor") == "Somn_Usor_Puisor_RO.srt"
    assert timeline.srt_name("!!!") == "Subtitrare_RO.srt"
