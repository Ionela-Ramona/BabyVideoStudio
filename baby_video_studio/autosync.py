"""Automatic lyrics sync: a local speech model (faster-whisper, CPU, int8) hears the sung words,
then the user's own lyrics are aligned to them, in order.

The model only says *when* words were sung; the text always comes from the user's lyrics.
Lines the model did not hear clearly are flagged for checking, never given made-up precision.
"""
import hashlib
import importlib.util
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .audio import decode
from .media import RenderError
from .models import Segment
from .planner import _plain
from .render import CACHE_DIR
from .timeline import EXTRA, INSTRUMENTAL, INTRO

MODEL, SMALL_MODEL = "large-v3-turbo", "small"  # the small one is the fallback when memory is short
RATE = 16000  # what the speech model expects
CACHE = CACHE_DIR / "voce"
SURE = 0.6  # rows below this confidence are flagged for checking
SAME_WORD = 0.6  # how alike a heard word and a lyric word must be to count as the same
GAP_SECONDS = 4.0  # a pause this long between sung lines gets its own row
SPOKEN_WORD = 0.25  # seconds; the model's invented phrases in silence come out much faster than real singing

Word = list  # [start, end, text, probability]
Progress = Callable[[float, str], None]


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def vocals_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def _cache_file(audio: Path, vocals: bool) -> Path:
    key = hashlib.sha1(audio.read_bytes()).hexdigest()[:16]
    return CACHE / f"{key}-{'voce' if vocals else 'mix'}.json"


def is_cached(audio: Path, vocals: bool) -> bool:
    return _cache_file(audio, vocals).exists()


def forget(audio: Path, vocals: bool) -> None:
    """Drop the kept analysis, so the next hear() listens to the song again."""
    _cache_file(audio, vocals).unlink(missing_ok=True)


def hear(audio: Path, vocals: bool, progress: Progress) -> list[Word]:
    """The sung words with their times; the result is kept, so the same song is never analysed twice."""
    cached = _cache_file(audio, vocals)
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))["words"]
    progress(0.0, "Citesc melodia…")
    samples = decode(audio, RATE)
    if vocals:
        from .vocals import separate
        samples = separate(samples, RATE, lambda f, m: progress(0.4 * f, m))
    start = 0.4 if vocals else 0.0
    words, model = _transcribe(samples, lambda f, m: progress(start + (1 - start) * f, m))
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"model": model, "words": words}, ensure_ascii=False), encoding="utf-8")
    return words


def _out_of_memory(error: BaseException) -> bool:
    return isinstance(error, MemoryError) or any(w in str(error).lower() for w in ("memory", "alloc"))


def _load(name: str):
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(name, device="cpu", compute_type="int8")
    except Exception as error:
        if _out_of_memory(error):
            raise
        raise RenderError("Nu am putut pregăti modelul de recunoaștere a vocii. Prima dată ai nevoie de internet, ca să se "
                          f"descarce (o singură dată). Detalii: {error}") from None


def _transcribe(samples, progress: Progress) -> tuple[list[Word], str]:
    seconds = len(samples) / RATE
    for name in (MODEL, SMALL_MODEL):
        try:
            progress(0.01, f"Pregătesc modelul de recunoaștere a vocii ({name}). Prima dată se descarcă "
                           f"(~{'1,6 GB' if name == MODEL else '500 MB'}), apoi rămâne pe calculator.")
            segments, _ = _load(name).transcribe(samples, language="ro", word_timestamps=True, beam_size=5,
                                                 condition_on_previous_text=False)
            words = []
            for segment in segments:
                progress(min(segment.end / seconds, 1), f"Ascult vocea: {segment.end:.0f} din {seconds:.0f} secunde…")
                words += [[round(w.start, 2), round(w.end, 2), w.word, round(w.probability, 3)] for w in segment.words]
            return words, name
        except (MemoryError, RuntimeError) as error:
            if not _out_of_memory(error):
                raise RenderError(f"Recunoașterea vocii a eșuat: {error}") from None
        progress(0.0, "Memoria nu ajunge pentru modelul mare. Încerc modelul mic (mai puțin precis)…")
    raise RenderError("Memoria calculatorului nu ajunge pentru recunoașterea vocii. Închide alte programe "
                      "(mai ales browserele cu multe file) și încearcă din nou.")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _plain(text))


def _match(lyric: list[str], heard: list[str]) -> list[tuple[int, int]]:
    """Global alignment of the two word sequences, in order; returns the pairs that are the same word."""
    similar: dict[tuple[str, str], float] = {}

    def sim(a: str, b: str) -> float:
        if (a, b) not in similar:
            similar[a, b] = SequenceMatcher(None, a, b).ratio()
        return similar[a, b]

    gap = -1.0
    n, m = len(lyric), len(heard)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * gap
    for j in range(1, m + 1):
        score[0][j] = j * gap
    for i in range(1, n + 1):
        row, above, a = score[i], score[i - 1], lyric[i - 1]
        for j in range(1, m + 1):
            row[j] = max(above[j - 1] + 4 * (sim(a, heard[j - 1]) - 0.5), above[j] + gap, row[j - 1] + gap)
    pairs, i, j = [], n, m
    while i and j:
        s = 4 * (sim(lyric[i - 1], heard[j - 1]) - 0.5)
        if score[i][j] == score[i - 1][j - 1] + s:
            if sim(lyric[i - 1], heard[j - 1]) >= SAME_WORD:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif score[i][j] == score[i - 1][j] + gap:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _sung(words: list[Word]) -> bool:
    """Real singing, not a phrase the model invented in a quiet part ("Mulțumim pentru vizionare")."""
    return len(words) >= 4 and sum(w[1] - w[0] for w in words) / len(words) >= SPOKEN_WORD


def align(rows: list[Segment], words: list[Word], total_seconds: float) -> list[Segment]:
    """Start time and confidence for every lyric row, plus rows for the pauses between them.

    `rows` come from timeline.rows_from_lyrics(); its instrumental placeholders are replaced by the pauses
    actually found in the song. A row the model did not hear gets a time between its neighbours,
    confidence 0, and is flagged. Times written in the lyrics ([1:15.5]) are kept as they are.
    """
    lines = [r for r in rows[1:] if r.text != INSTRUMENTAL]
    lyric, owner = [], []
    for n, row in enumerate(lines):
        tokens = _tokens(row.text)
        lyric += tokens
        owner += [n] * len(tokens)
    heard, source = [], []
    for k, word in enumerate(words):
        tokens = _tokens(word[2])
        heard += tokens
        source += [k] * len(tokens)

    found: list[list[int]] = [[] for _ in lines]  # heard word indices matched to each line
    for i, j in _match(lyric, heard):
        if source[j] not in found[owner[i]]:
            found[owner[i]].append(source[j])
    used = {k for ks in found for k in ks}

    starts: list[float | None] = []
    ends: list[float | None] = []
    confidence: list[float] = []
    for row, ks in zip(lines, found):
        size = max(1, len(_tokens(row.text)))
        if len(ks) < max(1, size / 3):
            starts.append(None), ends.append(None), confidence.append(0.0)
            continue
        first_heard = _tokens(words[ks[0]][2])[0] == _tokens(row.text)[0] if _tokens(row.text) else False
        probability = sum(words[k][3] for k in ks[1:] or ks) / len(ks[1:] or ks)  # a line's first word is often scored low
        starts.append(words[ks[0]][0])
        ends.append(words[ks[-1]][1])
        confidence.append(round(min(1.0, len(ks) / size) * (0.5 + 0.5 * probability) * (1 if first_heard else 0.75), 2))

    # Rows the model did not hear: share the time between the neighbours it did hear, by length, and flag them.
    n = 0
    while n < len(lines):
        if starts[n] is not None:
            n += 1
            continue
        last = n
        while last < len(lines) and starts[last] is None:
            last += 1
        a = ends[n - 1] if n else 0.0
        b = starts[last] if last < len(lines) else total_seconds
        sizes = [max(1, len(_tokens(lines[k].text))) for k in range(n, last)]
        position = a
        for k, size in zip(range(n, last), sizes):
            starts[k] = round(position, 2)
            position += (b - a) * size / sum(sizes)
            ends[k] = round(position, 2)
        n = last

    for n in range(1, len(lines)):  # never two rows at the same moment
        if starts[n] <= starts[n - 1] + 0.2:
            starts[n] = round(starts[n - 1] + 0.2, 2)
            confidence[n] = min(confidence[n], 0.3)

    def pause(start: float, until: float, section: str) -> Segment:
        """It continues the section before it, so a short sung line never gets a picture of its own just before a pause."""
        between = [w for k, w in enumerate(words) if k not in used and start <= w[0] < until]
        if _sung(between):
            return Segment(text=EXTRA + "".join(w[2] for w in between).strip(), section=section, start=round(start, 2),
                           confidence=0.3)
        return Segment(text=INSTRUMENTAL, section=section, start=round(start, 2), confidence=1.0)

    result = []
    if lines and starts[0] >= GAP_SECONDS:
        result.append(Segment(text=INSTRUMENTAL, section=INTRO, start=0, confidence=1.0))
    for n, row in enumerate(lines):
        if row.start is not None:  # written by the user in the lyrics
            result.append(row.model_copy(update={"confidence": None}))
            continue
        if n and starts[n] - ends[n - 1] >= GAP_SECONDS and confidence[n] and confidence[n - 1]:
            result.append(pause(ends[n - 1], starts[n], lines[n - 1].section))
        result.append(row.model_copy(update={"start": starts[n], "confidence": confidence[n]}))
    if lines and confidence[-1] and total_seconds - ends[-1] >= GAP_SECONDS:
        result.append(pause(ends[-1], total_seconds, lines[-1].section))
    if result:
        result[0] = result[0].model_copy(update={"start": 0.0})  # the first row always starts with the song
    return result
