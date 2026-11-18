"""Lyrics-synchronized timeline: one row per sung line, timed by the user while listening.

Nothing here guesses when a line is sung. Times come from the user's marks (or from times
written in the lyrics); rows without a time are reported, never estimated.
"""
import math
import re
import unicodedata
from collections import Counter
from itertools import pairwise

import numpy as np

from .audio import LYRIC_LINE
from .models import FPS, Scene, Segment, Subtitle
from .pictures import CONCEPTS, LABELS, concepts_in
from .planner import (CHORUS, PANS, ROTATION, SCENERY, SECTION_HEADER, Section, Slot, _assign, _attach_story, _chunks,
                      _close, _groups, _image_words, _plain, _tokens, even_crossfade_frames, stamp)

INTRO = "Introducere"
INSTRUMENTAL = "🎵 (instrumental)"
EXTRA = "🎤 "  # automatic sync: singing heard in the song but not written in the lyrics
LINES_PER_IMAGE = 4  # before the rows are timed, a long section changes image every few lines


def rows_from_lyrics(lyrics: str) -> list[Segment]:
    """Every sung line becomes a row, repeated choruses included; an instrumental intro row comes first.

    A chorus header with no lines under it repeats the first chorus. A line written as
    [1:15.5] Nani keeps that start time.
    """
    sections: list[tuple[str, list[tuple[str, float | None]]]] = []
    for line in lyrics.splitlines():
        if header := SECTION_HEADER.match(line):
            sections.append((header[1], []))
        elif line.strip():
            if not sections:
                sections.append(("", []))
            timed = LYRIC_LINE.match(line)
            start = int(timed[1]) * 60 + float(timed[2].replace(",", ".")) if timed else None
            sections[-1][1].append((LYRIC_LINE.sub("", line).strip(), start))
    if not sections:
        return []
    first_chorus = next((lines for label, lines in sections if CHORUS.search(label) and lines), [])
    rows = [Segment(text=INSTRUMENTAL, section=INTRO, start=0)]
    for label, lines in sections:
        if not lines and CHORUS.search(label):
            lines = [(text, None) for text, _ in first_chorus]
        rows += [Segment(text=text, section=label, start=start) for text, start in lines or [(INSTRUMENTAL, None)]]
    return rows


def lyric_lines(segments: list[Segment]) -> list[str]:
    """The rows that come from the written lyrics, without instrumental or extra rows."""
    return [s.text for s in segments if s.text != INSTRUMENTAL and not s.text.startswith(EXTRA)]


def starts(segments: list[Segment]) -> list[float | None]:
    """The first row always starts with the song."""
    return [0.0, *(s.start for s in segments[1:])] if segments else []


def in_order(segments: list[Segment], total_seconds: float) -> bool:
    """Every row has a start, each starts after the one before, and all start before the song ends."""
    times = starts(segments)
    return bool(times) and None not in times and all(a < b for a, b in zip(times, times[1:])) and times[-1] < total_seconds


def _image_runs(segments: list[Segment]) -> list[list[int]]:
    """Row indices grouped where the image stays the same: no transition between them."""
    runs: list[list[int]] = []
    for i, row in enumerate(segments):
        if runs and segments[runs[-1][0]].image == row.image:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _split(rows: list[int], times: list[float | None], end: float | None, scene_seconds: float) -> list[list[int]]:
    """Rows of one section in groups that each get an image: by sung time when known, else by line count."""
    known = end is not None and all(times[i] is not None for i in rows)
    if known:
        count = max(1, min(len(rows), round((end - times[rows[0]]) / scene_seconds)))
        span = (end - times[rows[0]]) / count
        firsts = [0]
        for k in range(1, count):
            target = times[rows[0]] + k * span
            best = min(range(firsts[-1] + 1, len(rows)), key=lambda j: abs(times[rows[j]] - target), default=None)
            if best is not None and best not in firsts:
                firsts.append(best)
    else:
        count = math.ceil(len(rows) / LINES_PER_IMAGE)
        firsts = sorted({j * len(rows) // count for j in range(count)})
    return [rows[a:b] for a, b in zip(firsts, [*firsts[1:], len(rows)])]


def suggest_images(segments: list[Segment], images: list[str], storyboard: str, tags: dict[str, str],
                   total_seconds: float, scene_seconds: float) -> tuple[list[Segment], list[str]]:
    """Pick an image (and camera motion) for every row, using filenames, the user's descriptions and the story.

    Rows of one section share an image; a long section is split at line boundaries. Later choruses reuse
    the first chorus's images; the last image always ends the video. The rows' times are left exactly as they are.
    """
    if not images:
        raise ValueError("Adaugă cel puțin o imagine.")
    warnings: list[str] = []
    runs: list[tuple[Section, list[int]]] = []
    for i, row in enumerate(segments):
        if not runs or runs[-1][0].label != row.section:
            runs.append((Section(row.section), []))
        runs[-1][1].append(i)
        runs[-1][0].text += row.text + "\n"
    _attach_story(storyboard, [section for section, _ in runs], warnings)

    times = starts(segments)
    slots, groups = [], []
    for n, (section, rows) in enumerate(runs):
        end = times[runs[n + 1][1][0]] if n + 1 < len(runs) else total_seconds
        parts = _split(rows, times, end, scene_seconds)
        for position, (part, story) in enumerate(zip(parts, _chunks(section.story, len(parts)))):
            slots.append(Slot(section, position, " ".join(story)))
            groups.append(part)

    words = {i: _image_words(i, tags) for i in images}
    # The last picture is kept for the end of the video, so it closes the outro and never repeats just before it.
    picks = _assign(slots[:-1], images[:-1] or images, words) + [(images[-1], 0)] if slots else []
    if missing := set(images) - {image for image, _ in picks}:
        warnings.append(f"Sunt mai puține grupuri de versuri decât imagini. Nu au fost folosite: {', '.join(sorted(missing))}.")

    result = list(segments)
    used = Counter()
    for slot, part, (image, _) in zip(slots, groups, picks):
        choices = PANS if "cloud" in _groups(_tokens(slot.story) | words[image], SCENERY) else ROTATION
        motion = choices[(used[image] + images.index(image)) % len(choices)]
        used[image] += 1
        for i in part:
            result[i] = segments[i].model_copy(update={"image": image, "motion": motion})
    return result, warnings


SHORT, LONG = 5.0, 12.0  # seconds: the scene length a baby can follow comfortably; outside it costs, it is not forbidden
SCENE_COST = 0.5  # a new picture must explain the lines this much better than the current one
LINE = 2.5  # seconds of a typical sung line: the unit in which a picture's fit is counted
NEW_SECTION = 0.4  # a scene that runs on into the next stanza costs this much
CONTEXT = 0.35  # weight of what the rest of the stanza mentions, next to 1 for what the line itself sings
REUSE = 0.15  # relevance a picture loses each time it was already used (repeated chorus lines are exempt)
NEUTRAL = 0.5  # fit of a line that names nothing a picture could show
SIGNALS = (0.5, 0.35, 0.15)  # weights of: what the picture shows, the lyrics' own words in its description, the stanza named there
GOOD_MATCH = 0.45  # below this a scene is flagged for checking
STOP = {"care", "este", "sunt", "pentru", "printre", "langa", "peste", "toti", "foarte", "cand", "unde", "doar", "inca",
        "acum", "dupa", "spre"}
SECTION_NAME = re.compile(r"\b(strofa|refren|refrenul|intro|introducere|outro|final|bridge)\b\s*(\d*)")


def _section_runs(segments: list[Segment]) -> list[list[int]]:
    runs: list[list[int]] = []
    for i, row in enumerate(segments):
        if runs and segments[runs[-1][0]].section == row.section:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def wants(segments: list[Segment]) -> np.ndarray:
    """rows x concepts: 1 for what a row sings about, CONTEXT for what the rest of its stanza mentions."""
    result = np.zeros((len(segments), len(CONCEPTS)))
    for run in _section_runs(segments):
        context = sorted(concepts_in(" ".join(segments[i].text for i in run if not segments[i].text.startswith(EXTRA))))
        for i in run:
            if not segments[i].text.startswith(EXTRA):  # singing that is not in the lyrics belongs to no stanza
                result[i, context] = CONTEXT
            result[i, sorted(concepts_in(segments[i].text))] = 1.0
    return result


def _words(text: str) -> set[str]:
    return {t for t in _tokens(text) if len(t) >= 4 and t not in STOP}


def _fits(segments: list[Segment], images: list[str], seen: dict[str, dict[str, float]], tags: dict[str, str]) -> np.ndarray:
    """rows x images, 0..1: how well each picture fits each row.

    What the picture shows (seen) against what the row and its stanza sing about, together with the lyrics' own
    words and the stanza name found in the picture's file name or the user's description.
    """
    want = wants(segments)
    shows = np.array([[seen.get(image, {}).get(label, 0.0) for label in LABELS] for image in images]).reshape(len(images), len(LABELS))
    size = want.sum(1, keepdims=True)
    concept = np.where(size > 0, want @ shows.T / np.maximum(size, 1e-9), NEUTRAL)

    described = [_image_words(image, tags) for image in images]
    common = Counter(w for words in described for w in words)
    rare = [{w for w in words if common[w] <= max(1, len(images) // 2)} for words in described]  # "iepuraș" is in all of them
    named = [{" ".join(m).strip() for m in SECTION_NAME.findall(_plain(tags.get(image, "")))} for image in images]
    words, label = np.zeros_like(concept), np.zeros_like(concept)
    for r, row in enumerate(segments):
        sung = _words(row.text)
        heading = _plain(row.section)
        for m in range(len(images)):
            if sung:
                words[r, m] = sum(any(_close(t, w) for w in rare[m]) for t in sung) / len(sung)
            label[r, m] = not row.text.startswith(EXTRA) and any(heading.startswith(n) for n in named[m])
    # A signal no picture has for a row (no descriptions, say) is left out of that row's average, so it cannot lower it.
    parts = [concept, words, label]
    weights = [np.where(part.max(1, keepdims=True) > 0, w, 0.0) for part, w in zip(parts, SIGNALS)]
    weights[0] = np.full_like(concept, SIGNALS[0])
    return sum(w * part for w, part in zip(weights, parts)) / sum(weights)


def storyboard(segments: list[Segment], images: list[str], seen: dict[str, dict[str, float]], tags: dict[str, str],
               total_seconds: float, crossfade_seconds: float, keep_mine: bool = True) -> tuple[list[Segment], list[str]]:
    """Group the timed rows into scenes and give each scene the picture that best fits what is sung in it.

    The rows' times are never changed. A scene changes picture where the lyrics move on to something another
    picture shows better, preferably at a new stanza, and lasts about SHORT–LONG seconds. Pictures the user chose
    (locked) are kept when `keep_mine`. Repeated chorus lines may show their earlier picture again; other pictures
    are not repeated without need. Call only when in_order() holds.
    """
    if not images:
        raise ValueError("Adaugă cel puțin o imagine.")
    count, times, size = len(segments), [*starts(segments), total_seconds], len(images)
    seconds = np.diff(times)
    fit = _fits(segments, images, seen, tags)
    # A wrong picture costs by the time it is on screen; a typical line lasts about LINE seconds.
    total = np.vstack([np.zeros(size), np.cumsum(fit * seconds[:, None] / LINE, 0)])
    # Long music without singing may stay on one picture longer: it counts half towards LONG.
    felt = np.concatenate([[0], np.cumsum([t * (0.5 if s.text == INSTRUMENTAL else 1) for t, s in zip(seconds, segments)])])
    fixed = [s.image if keep_mine and s.locked and s.image in images else None for s in segments]
    shortest = even_crossfade_frames(crossfade_seconds) / FPS + 1  # what the renderer needs for one picture
    crossings = np.cumsum([0] + [int(segments[r].section != segments[r - 1].section) for r in range(1, count)])

    def chosen(i: int, j: int) -> set[str]:
        return {fixed[r] for r in range(i, j)} - {None}

    # best[j, m]: the best storyboard of rows before j whose last scene shows picture m. Two scenes in a row
    # never show the same picture (they would be one scene), so a new scene must be worth its own picture.
    best = np.full((count + 1, size), -math.inf)
    best[0] = 0.0
    back = np.zeros((count + 1, size, 2), int)
    for j in range(1, count + 1):
        for i in range(j - 1, -1, -1):
            length = times[j] - times[i]
            if length > 3 * LONG and i < j - 1:
                break
            mine = chosen(i, j)
            if (length < shortest and (i, j) != (0, count)) or len(mine) > 1:
                continue
            value = total[j] - total[i] - SCENE_COST - NEW_SECTION * (crossings[j - 1] - crossings[i])
            value -= 0.4 * max(0.0, SHORT - length) + 0.1 * max(0.0, felt[j] - felt[i] - LONG)
            if mine:
                value[[m for m in range(size) if images[m] not in mine]] = -math.inf
            if i == 0:
                before, origin = np.zeros(size), np.zeros(size, int)
            else:  # the best earlier storyboard whose last picture is a different one
                order = np.argsort(-best[i])
                origin = np.where(np.arange(size) == order[0], order[min(1, size - 1)], order[0])
                before = best[i][origin]
                if size == 1:
                    before = np.full(size, -math.inf)
            better = before + value > best[j]
            best[j][better] = (before + value)[better]
            back[j][better] = np.stack([np.full(size, i), origin], 1)[better]
    if not np.isfinite(best[count].max()):
        raise ValueError("Imaginile alese de tine nu se pot păstra așa: două imagini diferite ar sta mai puțin de "
                         f"{shortest:.0f} secunde fiecare. Bifează „Înlocuiește și imaginile alese de mine”.")
    scenes, j, m = [], count, int(best[count].argmax())
    while j:
        i, previous = back[j][m]
        scenes.append((int(i), j))
        j, m = int(i), int(previous)
    scenes.reverse()

    def average(i: int, j: int) -> np.ndarray:
        return (total[j] - total[i]) / (times[j] - times[i]) * LINE

    uses, by_text = Counter(), {}
    result, previous, warnings = list(segments), None, []
    for i, j in scenes:
        if mine := chosen(i, j):
            pick = next(iter(mine))
        else:
            score = average(i, j) - REUSE * np.array([uses[m] for m in images])
            for earlier in {by_text[segments[r].text] for r in range(i, j)
                            if segments[r].text in by_text and segments[r].text != INSTRUMENTAL}:
                score[images.index(earlier)] += REUSE * uses[earlier]  # a repeated chorus may show its picture again
            if previous in images:
                score[images.index(previous)] = -math.inf
            pick = images[int(score.argmax())] if np.isfinite(score.max()) else (previous or images[0])
        motion = _gentle_motion(pick, uses[pick], images, seen)
        uses[pick] += 1
        previous = pick
        for r in range(i, j):
            by_text.setdefault(segments[r].text, pick)
            if not (keep_mine and segments[r].locked):
                result[r] = segments[r].model_copy(update={"image": pick, "motion": motion, "locked": False})
    if missing := [i for i in images if i not in uses]:
        warnings.append(f"Nu au fost folosite {len(missing)} imagini, pentru că altele se potrivesc mai bine cu versurile: "
                        f"{', '.join(missing[:6])}{' …' if len(missing) > 6 else ''}.")
    return result, warnings


def _gentle_motion(image: str, used: int, images: list[str], seen: dict[str, dict[str, float]]) -> str:
    """Slow zooms and pans in turn; sideways only over clouds, so they drift with the camera."""
    choices = PANS if seen.get(image, {}).get("nori", 0) >= 0.5 else ROTATION
    return choices[(used + images.index(image)) % len(choices)]


def scene_list(segments: list[Segment], images: list[str], seen: dict[str, dict[str, float]], tags: dict[str, str],
               total_seconds: float) -> list[dict]:
    """One entry per scene (rows that share a picture), with how well the picture fits what is sung in it."""
    fit = _fits(segments, images, seen, tags) if images else np.zeros((len(segments), 0))
    want = wants(segments)
    times = [*starts(segments), total_seconds]
    result = []
    for run in _image_runs(segments):
        image = segments[run[0]].image
        known = image in images
        match = float(fit[run, images.index(image)].mean()) if known else 0.0
        has = seen.get(image, {})
        asked = want[run].max(0)
        sung = [LABELS[k] for k in np.argsort(-asked) if asked[k] >= 1]  # named by the lines themselves
        nowhere = [c for c in sung if not any(seen.get(i, {}).get(c, 0) >= 0.5 for i in images)]
        lacking = [c for c in sung if has.get(c, 0) < 0.5]
        hint = ("Adaugă o imagine cu: " + ", ".join(nowhere[:3]) if nowhere
                else "Nu se vede: " + ", ".join(lacking[:3]) if lacking and match < GOOD_MATCH else "")
        result.append({"rows": run, "start": times[run[0]], "end": times[run[-1] + 1], "image": image, "match": match,
                       "check": not known or match < GOOD_MATCH, "hint": hint,
                       "text": " / ".join(segments[r].text for r in run), "mine": any(segments[r].locked for r in run)})
    return result


def _rows(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:8])
    return shown + (" …" if len(numbers) > 8 else "")


def problems(segments: list[Segment], images: list[str], total_seconds: float, crossfade_seconds: float) -> list[str]:
    """What stops the timeline from being rendered, in words for the user; empty when it is ready."""
    if not segments:
        return ["Creează mai întâi rândurile din versuri."]
    errors = []
    if unmarked := [i + 1 for i, s in enumerate(segments) if i and s.start is None]:
        errors.append(f"Rândurile {_rows(unmarked)} nu au încă timp de început. Marchează-le ascultând melodia sau scrie timpul în tabel.")
    if no_image := [i + 1 for i, s in enumerate(segments) if s.image not in images]:
        errors.append(f"Alege imaginea pentru rândurile {_rows(no_image)}.")
    if errors:
        return errors

    total = round(total_seconds * FPS)
    frames = [round(t * FPS) for t in starts(segments)]
    for i in range(1, len(frames)):
        if frames[i] <= frames[i - 1]:
            errors.append(f"Rândul {i + 1} începe la {stamp(frames[i])}, dar rândul {i} începe la {stamp(frames[i - 1])}. "
                          "Rândurile trebuie să fie în ordinea din melodie și să nu se suprapună.")
    if frames[-1] >= total:
        errors.append(f"Rândul {len(frames)} începe la {stamp(frames[-1])}, după finalul melodiei ({stamp(total)}).")
    if errors:
        return errors

    xf = even_crossfade_frames(crossfade_seconds)
    runs = _image_runs(segments)
    if len(runs) > 1:
        edges = [frames[run[0]] for run in runs] + [total]
        for run, a, b in zip(runs, edges, edges[1:]):
            if b - a < xf + FPS:
                errors.append(f"Imaginea de la rândul {run[0] + 1} ({stamp(a)} – {stamp(b)}) ar sta pe ecran doar {(b - a) / FPS:.1f} s. "
                              f"Cu tranziția aleasă are nevoie de cel puțin {(xf + FPS) / FPS:.0f} s: alege aceeași imagine "
                              "ca la rândul vecin, ca să se lipească, sau micșorează tranziția.")
    return errors


def to_scenes(segments: list[Segment], total_frames: int, xf: int, tags: dict[str, str], particles: bool = True) -> list[Scene]:
    """Scenes for the renderer, cut exactly at the marked times.

    Each transition starts at the moment its line starts, so a picture never shows before its lyric.
    Rows with the same image in a row are one scene. Call only when problems() is empty.
    """
    runs = _image_runs(segments)
    cuts = [0, *(round(segments[run[0]].start * FPS) for run in runs[1:]), total_frames]
    scenes = []
    for i, run in enumerate(runs):
        first = segments[run[0]]
        end = cuts[i + 1] + (xf if i < len(runs) - 1 else 0)
        scenes.append(Scene(description=" / ".join(segments[j].text for j in run), image=first.image, motion=first.motion,
                            particles=particles,
                            clouds="cloud" in _groups(_image_words(first.image, tags), SCENERY),
                            start_frame=cuts[i], frames=end - cuts[i], lyric_section=first.section, time_source="manual"))
    return scenes


def subtitles(segments: list[Segment], total_seconds: float, sure: float) -> list[Subtitle]:
    """One subtitle per sung line of the lyrics, repeated choruses included, with the line's own text.

    A line is on screen from its start until the next row starts (an instrumental pause ends it where the singing
    stops). Instrumental rows and 🎤 rows (heard but not in the lyrics) get no subtitle.
    """
    times = [*starts(segments), total_seconds]
    return [Subtitle(text=row.text, start=times[i], end=times[i + 1] if times[i] is not None else None,
                     unsure=row.confidence is not None and row.confidence < sure)
            for i, row in enumerate(segments) if row.text != INSTRUMENTAL and not row.text.startswith(EXTRA)]


def subtitle_problems(items: list[Subtitle], total_seconds: float) -> list[str]:
    """What stops the subtitles from being exported, in words for the user; empty when they are valid."""
    if not items:
        return ["Nu există subtitrări. Apasă „Generează subtitrarea”."]
    errors = []
    for n, item in enumerate(items, 1):
        if not item.text.strip():
            errors.append(f"Subtitrarea {n} nu are text.")
        if item.start is None or item.end is None:
            errors.append(f"Subtitrarea {n} („{item.text}”) nu are timp. Sincronizează versurile sau scrie timpul în tabel.")
        elif item.start >= item.end:
            errors.append(f"Subtitrarea {n} („{item.text}”) se termină înainte să înceapă.")
        elif item.end > total_seconds + 0.01:
            errors.append(f"Subtitrarea {n} („{item.text}”) se termină după finalul melodiei ({total_seconds:.1f} s).")
        elif n > 1 and items[n - 2].end is not None and item.start < items[n - 2].end - 0.001:
            errors.append(f"Subtitrarea {n} („{item.text}”) începe înainte să se termine subtitrarea {n - 1}.")
    return errors


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d},{rest % 1000:03d}"


def to_srt(items: list[Subtitle]) -> str:
    """SubRip text as YouTube Studio reads it. Call only when subtitle_problems() is empty."""
    return "".join(f"{n}\n{srt_time(item.start)} --> {srt_time(item.end)}\n{item.text.strip()}\n\n"
                   for n, item in enumerate(items, 1))


def srt_name(title: str) -> str:
    """Tup_Tup_Iepuras_RO.srt from "Țup, țup, iepuraș!": no diacritics or spaces, which some uploaders mangle."""
    words = re.findall(r"[A-Za-z0-9]+", "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c)))
    return "_".join(w[:1].upper() + w[1:] for w in words or ["subtitrare"]) + "_RO.srt"
