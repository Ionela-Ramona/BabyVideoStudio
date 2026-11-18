"""Deterministic, rule-based storyboard planner (no language model involved)."""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np

from .audio import GRID_HZ, LYRIC_LINE
from .models import FPS, Scene

MIN_SCENE_SECONDS = 6
SHORTEST_SCENE, LONGEST_SCENE = 0.6, 1.5  # relative to the requested scene length
REGULARITY = 1.0  # higher = steadier scene lengths, lower = follows the music more
CLEAR_CHANGE = 0.5
WANDER = 0.35  # how far a section start may move from its estimate, relative to the section length
STORY_WEIGHT = 3  # the story decides; the lyrics only help
REUSE_PENALTY = 1.5  # relevance an image loses each time it is reused
MIN_SECTION_WEIGHT = 0.35  # of the median, so a short or instrumental outro still gets screen time
SUBJECTS = {
    "girl": ("girl", "fetit", "copila"),
    "boy": ("boy", "baiat", "baiet"),
    "sheep": ("sheep", "lamb", "miel", "oaie", "oita", "oite"),
    "bear": ("bear", "teddy", "urs", "ursul", "ursulet"),
    "bunny": ("bunny", "rabbit", "iepur"),
    "chick": ("chick", "pui", "puis", "puiu"),
    "mother": ("mother", "mom", "mama", "mamei", "mami"),
}
SCENERY = {
    "moon": ("moon", "luna", "lunii"),
    "star": ("star", "stea", "stele", "stelut"),
    "cloud": ("cloud", "nor", "nori", "norul", "norii", "norisor", "norulet"),
    "garden": ("garden", "gradin", "flori", "floare", "flower"),
    "kiss": ("kiss", "sarut", "pupic"),
    "nest": ("nest", "cuib"),
}
NOISE = {"start", "starts", "started", "the", "and", "with", "under", "dreamy", "cute", "little", "image", "img", "cu", "si", "un", "o"}
REPEAT = re.compile(r"repeat|repet[aă]|until the (?:song|end)|p[âa]n[ăa] la (?:final|sf[âa]r[șs]it)|p[âa]n[ăa] se termin", re.I)
SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|,\s*(?=(?:then|apoi)\b)", re.I)
TIMESTAMP = re.compile(r"^\W*(?:(?:de\s+)?la\s+|at\s+)?(\d{1,2}):([0-5]\d)\b\W*", re.I)
CONNECTOR = re.compile(r"^\W*(?:at the beginning|in the beginning|then|later|next|finally|la [iî]nceput|apoi|mai t[âa]rziu|dup[ăa] aceea|[iî]n final)\b\W*", re.I)
ROTATION = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
PANS = ["pan_right", "pan_left"]
SECTION_HEADER = re.compile(r"^\s*\[\s*([^\]\d][^\]]*?)\s*\]\s*$")
CHORUS = re.compile(r"refren|chorus", re.I)
STORY_LABEL = re.compile(r"^\W*([^:\]]{2,40}?)\s*[:\]]\s*(.*)$", re.S)
STAMP = re.compile(r"^\s*(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$")


@dataclass
class Beat:
    text: str
    start: float | None = None
    image: str = ""
    auto: bool = False


@dataclass
class Section:
    label: str
    text: str = ""
    start: float | None = None  # only when the lyrics state it; never guessed here
    story: list[str] = field(default_factory=list)

    @property
    def chorus(self) -> bool:
        return bool(CHORUS.search(self.label))


@dataclass
class Slot:
    section: Section
    position: int
    story: str


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _plain(text))) - NOISE


def _is(token: str, stem: str) -> bool:
    return token == stem or (len(stem) >= 4 and token.startswith(stem))


def _groups(tokens: set[str], table: dict) -> set[str]:
    return {g for g, stems in table.items() if any(_is(t, s) for t in tokens for s in stems)}


def _close(a: str, b: str) -> bool:
    """Same word or a Romanian inflection of it (ursulet / ursuletul)."""
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def _score(scene: set[str], image: set[str]) -> int:
    return (3 * len(_groups(scene, SUBJECTS) & _groups(image, SUBJECTS))
            + len(_groups(scene, SCENERY) & _groups(image, SCENERY))
            + sum(any(_close(s, i) for i in image) for s in scene))


def _image_words(image: str, tags: dict[str, str]) -> set[str]:
    return _tokens(f"{Path(image).stem} {tags.get(image, '')}")


def parse_storyboard(text: str) -> list[Beat]:
    beats = []
    for raw in SPLIT.split(text.strip()):
        sentence = raw.strip()
        if not sentence or REPEAT.search(sentence):
            continue
        start = None
        if stamp := TIMESTAMP.match(sentence):
            start = int(stamp[1]) * 60 + int(stamp[2])
            sentence = sentence[stamp.end():]
        sentence = CONNECTOR.sub("", sentence).strip(" .")
        if sentence:
            beats.append(Beat(sentence, start))
    return beats


def match_images(beats: list[Beat], images: list[str], tags: dict[str, str] | None = None) -> list[Beat]:
    """First pass: clear winners by filename and description. Second pass: everything else gets the least used image."""
    used = Counter()
    pending = []
    for beat in beats:
        words = _tokens(beat.text)
        scores = {i: _score(words, _image_words(i, tags or {})) for i in images}
        best = max(scores.values())
        top = [i for i in images if scores[i] == best]
        if best and len(top) == 1:
            beat.image = top[0]
            used[top[0]] += 1
        else:
            pending.append((beat, top))
    for beat, candidates in pending:
        beat.image = min(candidates, key=lambda i: (used[i], images.index(i)))
        beat.auto = True
        used[beat.image] += 1
    return beats


def even_crossfade_frames(seconds: float) -> int:
    return max(2, round(seconds * FPS / 2) * 2)


def _even_cuts(a: int, b: int, target: float, min_gap: int) -> list[int]:
    count = max(1, min(round((b - a) / target), (b - a) // min_gap))
    return [a + (b - a) * j // count for j in range(count)]


def _salience_at(salience: list[float], frame: int) -> float:
    return salience[min(frame // (FPS // GRID_HZ), len(salience) - 1)]


def _musical_cuts(a: int, b: int, target: float, min_gap: int, salience: list[float]) -> list[int] | None:
    """Same number of scenes as an even split, but with the cuts moved onto musical changes.

    Dynamic programming over a 0.1 s grid. None when the span cannot be split within the allowed scene lengths.
    """
    count = len(_even_cuts(a, b, target, min_gap))
    if count == 1:
        return None
    step = FPS // GRID_HZ
    points = np.arange(a, b, step)
    reward = np.array([_salience_at(salience, int(p)) for p in points])
    shortest, longest = max(min_gap, round(target * SHORTEST_SCENE)), round(target * LONGEST_SCENE)

    def cost(gaps: np.ndarray) -> np.ndarray:
        return REGULARITY * ((gaps - target) / target) ** 2

    offsets = np.arange(-(-shortest // step), longest // step + 1)
    penalties = cost(offsets * step)
    best = np.full(len(points), -np.inf)
    best[0] = 0.0
    origins = []
    for _ in range(count - 1):
        layer, origin = np.full(len(points), -np.inf), np.zeros(len(points), dtype=int)
        for i in range(offsets[0], len(points)):
            valid = offsets <= i
            scores = best[i - offsets[valid]] - penalties[valid]
            winner = int(scores.argmax())
            if np.isfinite(scores[winner]):
                layer[i] = scores[winner] + reward[i]
                origin[i] = i - offsets[valid][winner]
        best = layer
        origins.append(origin)

    final_gaps = b - points
    final = np.where((final_gaps >= shortest) & (final_gaps <= longest), best - cost(final_gaps), -np.inf)
    index = int(final.argmax())
    if not np.isfinite(final[index]):
        return None
    cuts = []
    for origin in reversed(origins):
        cuts.append(int(points[index]))
        index = int(origin[index])
    return [a, *reversed(cuts)]


def plan(storyboard: str, images: list[str], audio_seconds: float,
         scene_seconds: float = 15, crossfade_seconds: float = 2,
         salience: list[float] | None = None, lyrics: str = "",
         tags: dict[str, str] | None = None) -> tuple[list[Scene], list[str]]:
    if not images:
        raise ValueError("Adaugă cel puțin o imagine.")
    total = round(audio_seconds * FPS)
    xf = even_crossfade_frames(crossfade_seconds)
    min_gap = max(MIN_SCENE_SECONDS * FPS, 2 * xf)
    target = max(scene_seconds * FPS, min_gap)
    warnings = []

    if sections := parse_sections(lyrics):
        if len(sections) * min_gap <= total:
            return _plan_sections(sections, storyboard, images, tags or {}, total, target, min_gap, xf, salience, warnings)
        warnings.append("Melodia este prea scurtă pentru toate secțiunile din versuri, așa că planul folosește doar povestea.")

    beats = match_images(parse_storyboard(storyboard), images, tags)
    leftover = [Beat("", image=i, auto=True) for i in images if i not in {b.image for b in beats}]

    anchors: dict[int, Beat] = {}
    for beat in sorted((b for b in beats if b.start is not None), key=lambda b: b.start):
        frame = round(beat.start * FPS)
        if frame >= total - min_gap and frame > 0:
            warnings.append(f"Momentul {int(beat.start)} s este prea aproape de finalul melodiei și a fost ignorat.")
            continue
        if not anchors and frame < min_gap:
            frame = 0
        elif anchors and frame - max(anchors) < min_gap:
            warnings.append(f"Momentul {int(beat.start)} s este prea aproape de scena anterioară și a fost ignorat.")
            continue
        anchors[frame] = beat

    untimed = [b for b in beats if b.start is None]
    pool = (untimed or beats) + leftover
    cursor = 0

    def next_beat(previous: str | None) -> Beat:
        nonlocal cursor
        for _ in pool:
            candidate = pool[cursor % len(pool)]
            cursor += 1
            if candidate.image != previous:
                return candidate
        return pool[(cursor - 1) % len(pool)]

    cuts, slots = [], []
    for a, b in pairwise(sorted({0, *anchors, total})):
        # Every scene has its own timestamp: the user chose the timing, so hold until the next one.
        if a in anchors and not untimed:
            span = [a]
        else:
            span = (salience and _musical_cuts(a, b, target, min_gap, salience)) or _even_cuts(a, b, target, min_gap)
        for j, cut in enumerate(span):
            cuts.append(cut)
            anchored = anchors.get(a) if j == 0 else None
            slots.append(anchored or next_beat(slots[-1].image if slots else None))
    cuts.append(total)

    used = Counter()
    scenes = []
    for i, beat in enumerate(slots):
        scenery = _groups(_tokens(beat.text), SCENERY)
        choices = PANS if "cloud" in scenery else ROTATION
        motion = choices[(used[beat.image] + images.index(beat.image)) % len(choices)]
        used[beat.image] += 1
        start = cuts[i] - xf // 2 if i else 0
        end = cuts[i + 1] + xf // 2 if i < len(slots) - 1 else total
        scenes.append(Scene(description=beat.text, image=beat.image, motion=motion,
                            clouds="cloud" in scenery, start_frame=start, frames=end - start,
                            auto_matched=beat.auto,
                            music_cut=bool(salience and i and cuts[i] not in anchors
                                           and _salience_at(salience, cuts[i]) >= CLEAR_CHANGE)))
    return scenes, warnings


def parse_sections(lyrics: str) -> list[Section]:
    """Lyrics split by [Strofa 1], [Refren]... headers; empty when there are none."""
    sections: list[Section] = []
    for line in lyrics.splitlines():
        if header := SECTION_HEADER.match(line):
            sections.append(Section(header[1]))
        elif sections and line.strip():
            section = sections[-1]
            if (timed := LYRIC_LINE.match(line)) and section.start is None:
                section.start = int(timed[1]) * 60 + float(timed[2].replace(",", "."))
            section.text += LYRIC_LINE.sub("", line).strip() + "\n"
    return sections


def _chunks(items: list[str], count: int) -> list[list[str]]:
    """Split in order over `count` places, repeating items when there are too few."""
    size = len(items)
    if not size:
        return [[] for _ in range(count)]
    return [items[j * size // count: max((j + 1) * size // count, j * size // count + 1)] for j in range(count)]


def _section_label(text: str, sections: list[Section]) -> tuple[list[int], str] | None:
    """A story sentence written as "Refren: ..." belongs to that section."""
    if not (match := STORY_LABEL.match(text)):
        return None
    wanted = " ".join(re.findall(r"[a-z0-9]+", _plain(match[1])))
    labels = [" ".join(re.findall(r"[a-z0-9]+", _plain(s.label))) for s in sections]
    hits = ([i for i, label in enumerate(labels) if label == wanted]
            or [i for i, label in enumerate(labels) if label.startswith(wanted) or wanted.startswith(label)])
    return (hits, match[2].strip()) if hits else None


def _attach_story(story: str, sections: list[Section], warnings: list[str]) -> None:
    beats = parse_storyboard(story)
    if any(b.start is not None for b in beats):
        warnings.append("Timpii scriși în poveste nu se folosesc atunci când versurile au secțiuni. Corectează-i direct în tabel.")
    labels = [_section_label(b.text, sections) for b in beats]
    if any(labels):
        targets = [0]
        for beat, label in zip(beats, labels):
            targets, text = label or (targets, beat.text)
            for index in targets:
                if text:
                    sections[index].story.append(text)
    else:
        first_chorus = next((s for s in sections if s.chorus), None)
        unique = [s for s in sections if not s.chorus or s is first_chorus]
        for section, chunk in zip(unique, _chunks([b.text for b in beats], len(unique))):
            section.story = chunk
    choruses = [s for s in sections if s.chorus]
    for chorus in choruses[1:]:
        chorus.story = chorus.story or choruses[0].story


def _best_moment(center: float, radius: float, salience: list[float] | None) -> int:
    if not salience:
        return int(round(center))
    points = np.arange(int(round(center - radius)), int(round(center + radius)) + 1, FPS // GRID_HZ)
    scores = [_salience_at(salience, int(p)) - 0.5 * ((p - center) / radius) ** 2 for p in points]
    return int(points[int(np.argmax(scores))])


def _section_starts(sections: list[Section], total: int, min_gap: int, salience: list[float] | None, warnings: list[str]) -> list[int]:
    """Start frame of each section.

    Times written in the lyrics are kept. The rest are estimates: an even share by amount of text,
    nudged to the nearest musical change. There is no audio-text alignment here.
    """
    count = len(sections)
    known = {0: 0}
    for i, section in enumerate(sections[1:], 1):
        if section.start is None:
            continue
        frame, (last_index, last_frame) = round(section.start * FPS), list(known.items())[-1]
        if frame - last_frame < (i - last_index) * min_gap or total - frame < (count - i) * min_gap:
            warnings.append(f"Timpul scris la „{section.label}” nu lasă loc celorlalte secțiuni și a fost ignorat.")
            section.start = None
        else:
            known[i] = frame
    known[count] = total

    amounts = np.array([sum(c in "aeiou" for c in _plain(s.text)) for s in sections], float)
    weights = np.maximum(amounts, max(1.0, MIN_SECTION_WEIGHT * float(np.median(amounts))))
    starts = [0] * count
    for (i, a), (j, b) in pairwise(known.items()):
        starts[i] = a
        expected = a + (b - a) * np.cumsum(weights[i:j])[:-1] / weights[i:j].sum()
        edges = [a, *expected, b]
        found = [_best_moment(edges[k], WANDER * min(edges[k] - edges[k - 1], edges[k + 1] - edges[k]), salience)
                 for k in range(1, len(edges) - 1)]
        for k in range(len(found)):
            found[k] = max(found[k], (found[k - 1] if k else a) + min_gap)
        for k in reversed(range(len(found))):
            found[k] = min(found[k], (found[k + 1] if k + 1 < len(found) else b) - min_gap)
        starts[i + 1:j] = found
    return starts


def _relevance(slot: Slot, words: set[str]) -> int:
    return STORY_WEIGHT * _score(_tokens(slot.story), words) + _score(_tokens(slot.section.text), words)


def _assign(slots: list[Slot], images: list[str], words: dict[str, set[str]]) -> list[tuple[str, int]]:
    """(image, relevance) per slot: relevance first, then variety.

    Every image appears once when there are enough slots, and later choruses reuse the first chorus.
    """
    first_chorus = next((s.section for s in slots if s.section.chorus), None)
    chorus_images: list[str] = []
    uses = Counter()
    picks: list[str] = []
    result = []
    for index, slot in enumerate(slots):
        def relevance(image: str) -> int:
            return _relevance(slot, words[image])

        previous = picks[-1] if picks else None
        unused = [i for i in images if not uses[i]]
        must_fill = len(unused) >= len(slots) - index
        pick = None
        if slot.section.chorus and slot.section is not first_chorus and chorus_images and not must_fill:
            turns = (chorus_images[(slot.position + k) % len(chorus_images)] for k in range(len(chorus_images)))
            pick = next((i for i in turns if i != previous), None)
        if pick is None:
            pool = unused if must_fill else [i for i in images if i != previous] or images
            if index + 1 < len(slots):  # the next scene could not use this image right after us: leave it free for a scene that asks for it
                wanted = max(images, key=lambda i: _relevance(slots[index + 1], words[i]))
                pool = [i for i in pool if i != wanted or relevance(i)] or pool
            pick = max(pool, key=lambda i: (relevance(i) - REUSE_PENALTY * uses[i], -images.index(i)))
        if slot.section is first_chorus:
            chorus_images.append(pick)
        uses[pick] += 1
        picks.append(pick)
        result.append((pick, relevance(pick)))
    return result


def _plan_sections(sections: list[Section], story: str, images: list[str], tags: dict[str, str], total: int, target: float,
                   min_gap: int, xf: int, salience: list[float] | None, warnings: list[str]) -> tuple[list[Scene], list[str]]:
    _attach_story(story, sections, warnings)
    starts = _section_starts(sections, total, min_gap, salience, warnings)
    spans = list(pairwise([*starts, total]))
    while sum(len(_even_cuts(a, b, target, min_gap)) for a, b in spans) < len(images) and target > min_gap:
        target = max(min_gap, target * 0.9)

    slots, cuts = [], []
    for section, (a, b) in zip(sections, spans):
        parts = (salience and _musical_cuts(a, b, target, min_gap, salience)) or _even_cuts(a, b, target, min_gap)
        for position, sentences in enumerate(_chunks(section.story, len(parts))):
            slots.append(Slot(section, position, " ".join(sentences)))
            cuts.append(parts[position])

    words = {i: _image_words(i, tags) for i in images}
    assigned = _assign(slots, images, words)
    missing = set(images) - {image for image, _ in assigned}
    if missing:
        warnings.append(f"Melodia este prea scurtă ca să încapă toate imaginile. Nu au intrat: {', '.join(sorted(missing))}.")

    used = Counter()
    scenes = []
    for i, (slot, (image, relevance)) in enumerate(zip(slots, assigned)):
        clouds = "cloud" in _groups(_tokens(slot.story) | words[image], SCENERY)
        choices = PANS if clouds else ROTATION
        motion = choices[(used[image] + images.index(image)) % len(choices)]
        used[image] += 1
        written = bool(i and slot.position == 0 and slot.section.start is not None)
        scenes.append(Scene(description=slot.story or next(iter(slot.section.text.splitlines()), ""), image=image, motion=motion,
                            clouds=clouds, start_frame=0, frames=1, auto_matched=relevance == 0, lyric_section=slot.section.label,
                            time_source="lyrics" if written else "auto",
                            music_cut=bool(salience and i and not written and _salience_at(salience, cuts[i]) >= CLEAR_CHANGE)))
    return retime(scenes, cuts[1:], xf, total), warnings


def stamp(frames: int) -> str:
    """Time as shown in the plan table: m:ss.d"""
    minutes, tenths = divmod(round(frames * 10 / FPS), 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def parse_seconds(text: str) -> float:
    """Seconds from a time parse_stamp() accepts, without rounding to frames."""
    match = STAMP.match(text)
    return int(match[1] or 0) * 60 + float(match[2].replace(",", "."))


def parse_stamp(text: str | None) -> int | None:
    """Frames from 1:15, 1:15.5 or 75.5; None when the text is not a time."""
    if not (match := STAMP.match(text or "")):
        return None
    seconds = float(match[2].replace(",", "."))
    if match[1] is not None and seconds >= 60:
        return None
    return round((int(match[1] or 0) * 60 + seconds) * FPS)


def scene_cuts(scenes: list[Scene]) -> list[int]:
    return [(a.end_frame + b.start_frame) // 2 for a, b in pairwise(scenes)]


def crossfade_of(scenes: list[Scene]) -> int | None:
    return scenes[0].end_frame - scenes[1].start_frame if len(scenes) > 1 else None


def retime(scenes: list[Scene], cuts: list[int], xf: int, total: int) -> list[Scene]:
    """The same scenes with new cut points; each crossfade stays centered on its cut."""
    edges = [0, *cuts, total]
    if len(edges) > 2:
        for number, (a, b) in enumerate(pairwise(edges), 1):
            if b - a < xf + FPS:
                raise ValueError(f"Scena {number} ar dura {(b - a) / FPS:.1f} secunde. "
                                 f"Trebuie să dureze cel puțin {(xf + FPS) / FPS:.0f} secunde, cu tranziția aleasă.")
    result = []
    for i, (scene, (a, b)) in enumerate(zip(scenes, pairwise(edges))):
        start = a - xf // 2 if i else 0
        end = b + xf // 2 if i < len(scenes) - 1 else total
        result.append(scene.model_copy(update={"start_frame": start, "frames": end - start}))
    return result


def apply_time_edits(scenes: list[Scene], starts: list[str], ends: list[str], xf: int, total: int) -> list[Scene] | None:
    """Scenes after the user changed times in the table, or None when nothing changed.

    A cut is both the end of one scene and the start of the next, so editing either moves it.
    Raises ValueError with a message for the user when a time cannot be used.
    """
    if starts[0] != stamp(0) or ends[-1] != stamp(total):
        raise ValueError(f"Prima scenă începe la {stamp(0)}, iar ultima se termină odată cu melodia, la {stamp(total)}.")
    cuts = scene_cuts(scenes)
    updated = list(cuts)
    moved = set()
    for i, cut in enumerate(cuts):
        for text in (starts[i + 1], ends[i]):
            if text != stamp(cut):
                frames = parse_stamp(text)
                if frames is None:
                    raise ValueError(f"Nu înțeleg timpul „{text}” de la scena {i + 2}. Scrie-l așa: 1:15.5")
                updated[i] = frames
                moved.add(i + 1)
                break
    if not moved:
        return None
    marked = [s.model_copy(update={"time_source": "manual", "music_cut": False}) if i in moved else s for i, s in enumerate(scenes)]
    return retime(marked, updated, xf, total)


def trim_scenes(scenes: list[Scene], limit: int, xf: int) -> list[Scene]:
    """Cut a plan to its first `limit` frames, for previews."""
    kept = [s for s in scenes if s.start_frame + xf < limit]
    return kept[:-1] + [kept[-1].model_copy(update={"frames": limit - kept[-1].start_frame})]
