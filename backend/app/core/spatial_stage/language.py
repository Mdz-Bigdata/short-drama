# -*- coding: utf-8 -*-
"""The words a storyboard uses for blocking changes, read the same way by the planner and the checks.

A verb only counts inside the clause that names the character ("沈砚后退，黄琰上前"
moves each of them once, never both twice), and a posture is what someone *holds*
("跪倒" → kneeling), not a movement they pass through.
"""

from __future__ import annotations

import re

ENTRANCE_WORDS = re.compile(r"走进|进门|冲进|推门|闯入|闯进|赶到|赶来|入场|进入|踏入|迈入|跨进")
_APPROACH = "走向|走到|走近|冲向|扑向|逼近|上前|跑向|奔向|迎上|凑近"
_RETREAT = "后退|退后|倒退|退开"
TRAVEL_WORDS = re.compile(f"{_APPROACH}|{_RETREAT}")
RETREAT_WORDS = frozenset(_RETREAT.split("|"))
POSTURE_RULES: tuple[tuple[str, str], ...] = (
    (r"起身|站起|站直|爬起", "stand"), (r"跪", "kneel"), (r"倒地|倒在|躺|昏倒|瘫", "lie"),
    (r"蹲|伏低", "crouch"), (r"坐|落座|伏案", "sit"),
)
_CLAUSE_GAP = r"[^，,。；！？\n]{0,%d}?"


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
