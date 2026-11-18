"""What the lyrics ask for: which characters are sung about, what they do, with whom, and what the decor shows.

Plain rules from an editable catalogue (defaults/actiuni.json): a line containing a word that starts like one of the
catalogue's entries picks that action, effect or interaction. No AI service, nothing paid; the user can add words.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from .planner import _plain


CATALOGUE = Path(__file__).resolve().parents[1] / "defaults" / "actiuni.json"  # comes with the app; editable


@lru_cache(maxsize=4)
def _load(path: Path, changed: float) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def catalogue() -> dict:
    return _load(CATALOGUE, CATALOGUE.stat().st_mtime)


def _text(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", _plain(text))) + " "


def _has(text: str, stem: str) -> bool:
    """`stem` starts a word of the line; with a space inside or at its end, it is a whole phrase or word."""
    stem = _plain(stem)
    return f" {stem}" in text


def _found(text: str, table: dict[str, list[str]]) -> list[str]:
    plain = _text(text)
    return [key for key, stems in table.items() if any(_has(plain, s) for s in stems)]


def actions_in(text: str) -> list[str]:
    return _found(text, catalogue()["actiuni"])


def effects_in(text: str) -> list[str]:
    return _found(text, catalogue()["efecte"])


def interactions_in(text: str) -> list[str]:
    return _found(text, catalogue()["interactiuni"])


def enters(text: str) -> bool:
    plain = _text(text)
    return any(_has(plain, s) for s in catalogue()["intrari"])


def mentioned(text: str, names: dict[str, list[str]]) -> list[str]:
    """The characters a line sings about, in the order they come in the line."""
    plain = _text(text)
    found = []
    for character, stems in names.items():
        places = [plain.find(f" {_plain(s)}") for s in stems if _has(plain, s)]
        if places:
            found.append((min(places), character))
    return [character for _, character in sorted(found)]


def defaults(kind: str, flying: bool) -> list[str]:
    table = catalogue()["implicit"]
    return table["zburator"] if flying else table.get(kind, table["personaj"])


def fits(action: str, flying: bool) -> bool:
    return action in catalogue()["zburator" if flying else "pe_sol"]


def names_for(name: str) -> list[str]:
    """How lyrics may call a character, guessed from the first word of its name ("Iepurașul Țup" -> "iepuras",
    which also finds "iepurași", "iepurașul"); the other words are often colours or titles."""
    words = re.findall(r"[a-z]+", _plain(name))
    return [words[0][:max(4, len(words[0]) - 2)]] if words else []
