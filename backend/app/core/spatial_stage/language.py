# -*- coding: utf-8 -*-
"""The words a storyboard uses for blocking changes, read the same way by the planner and the checks.

A verb only counts inside the clause that names the character ("沈砚后退，黄琰上前"
moves each of them once, never both twice), and a posture is what someone *holds*
("跪倒" → kneeling), not a movement they pass through.
"""

from __future__ import annotations

import re

from app.core import prompt_data

# The verbs, posture words and clause-ending marks: app/data/prompt/stage_vocabulary.json.
_VERBS = prompt_data.value("stage_vocabulary", "blocking_verbs")
ENTRANCE_WORDS = re.compile("|".join(_VERBS["entrance"]))
_APPROACH = "|".join(_VERBS["approach"])
_RETREAT = "|".join(_VERBS["retreat"])
TRAVEL_WORDS = re.compile(f"{_APPROACH}|{_RETREAT}")
RETREAT_WORDS = frozenset(_RETREAT.split("|"))
# First match wins, in the order the table lists them.
POSTURE_RULES: tuple[tuple[str, str], ...] = tuple(("|".join(words), str(posture)) for words, posture in _VERBS["postures"])
_CLAUSE_GAP = "[^" + _VERBS["clause_stops"] + "]{0,%d}?"


def _after_name(name: str, pattern: str, text: str, gap: int) -> re.Match[str] | None:
    if not name:
        return None
    return re.search(re.escape(name) + (_CLAUSE_GAP % gap) + "(" + pattern + ")", str(text or ""))


def posture_in(name: str, text: str, default: str | None = "stand") -> str | None:
    for pattern, posture in POSTURE_RULES:
        if _after_name(name, pattern, text, 8):
            return posture
    return default


def travel_in(name: str, text: str) -> str:
    """``"approach"`` / ``"retreat"`` when the clause naming ``name`` moves them toward or away from someone."""
    found = _after_name(name, TRAVEL_WORDS.pattern, text, 10)
    if found is None:
        return ""
    return "retreat" if found.group(1) in RETREAT_WORDS else "approach"


def enters_in(name: str, text: str) -> bool:
    return _after_name(name, ENTRANCE_WORDS.pattern, text, 12) is not None


__all__ = ["ENTRANCE_WORDS", "POSTURE_RULES", "RETREAT_WORDS", "TRAVEL_WORDS", "enters_in", "posture_in", "travel_in"]
