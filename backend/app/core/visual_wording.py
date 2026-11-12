# -*- coding: utf-8 -*-
"""What the camera sees is written as visible things, and ordinary motion is written slow and steady.

Two writing rules for visual text (a shot's description, its image and video prompt, a storyboard
row): no subjective adjectives (a model cannot draw "beautiful"; it can draw a raised mouth corner),
and no fast or violent speed words for movement that is not a fight (fast motion is what breaks
first). Fight shots follow their own rules, so the fast-motion check never fires on them.

The word lists, the longer words a listed word may sit inside without counting, the replacement
hints and the sentences live in ``app/data/prompt/visual_wording.json``. These are hints: callers
report them as warnings, never as errors and never as a reason to send a draft back to the model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core import prompt_data

_DATA = "visual_wording"

SUBJECTIVE_CODE = "subjective_wording"
FAST_MOTION_CODE = "fast_motion_wording"


@dataclass(frozen=True)
class VisualWordingFinding:
    code: str
    rule: str
    words: tuple[str, ...]
    message: str


def _entries(key: str) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in prompt_data.value(_DATA, key) if isinstance(item, Mapping))


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _covered(text: str, at: int, word: str, longer: Sequence[str]) -> bool:
    """Whether the ``word`` found at ``at`` is part of one of the ``longer`` words around it."""
    for whole in longer:
        offset = whole.find(word)
        while offset >= 0:
            start = at - offset
            if start >= 0 and text.startswith(whole, start):
                return True
            offset = whole.find(word, offset + 1)
    return False


def _occurs(text: str, word: str, longer: Sequence[str]) -> bool:
    """``word`` appears in ``text`` at least once outside the ``longer`` words that contain it."""
    at = text.find(word)
    while at >= 0:
        if not _covered(text, at, word, longer):
            return True
        at = text.find(word, at + 1)
    return False


def _hits(key: str, texts: Sequence[Any]) -> list[str]:
    cleaned = "\n".join(_clean(text) for text in texts)
    return [
        str(entry["word"]) for entry in _entries(key)
        if _occurs(cleaned, str(entry["word"]), [str(item) for item in entry.get("not_in") or []])
    ]


def subjective_hits(*texts: Any) -> list[str]:
    """The subjective adjectives (漂亮 / 震撼 / 高级感 …) written in ``texts``, in the table's order."""
    return _hits("subjective_words", texts)


def fast_motion_hits(*texts: Any, fight: bool) -> list[str]:
    """The fast or violent speed words in ``texts``, in the table's order; none at all for a fight shot."""
    if fight:
        return []
    return _hits("fast_motion_words", texts)


def _hints(key: str, words: Sequence[str]) -> str:
    by_word = {str(entry["word"]): str(entry.get("hint") or "") for entry in _entries(key)}
    item = prompt_data.text(_DATA, "hint_item")
    return prompt_data.text(_DATA, "hint_separator").join(item.format(word=word, hint=by_word[word]) for word in words)


def _finding(code: str, prefix: str, words: Sequence[str]) -> VisualWordingFinding:
    marks = "".join(prompt_data.text(_DATA, "word_mark").format(word=word) for word in words)
    message = prompt_data.text(_DATA, f"{prefix}_message").format(words=marks, hints=_hints(f"{prefix}_words", words))
    return VisualWordingFinding(code, prompt_data.text(_DATA, f"{prefix}_rule"), tuple(words), message)


def findings(*texts: Any, fight: bool) -> list[VisualWordingFinding]:
    """At most one subjective-word finding and one fast-motion finding (none for a fight) for one shot's visual text."""
    found: list[VisualWordingFinding] = []
    subjective = subjective_hits(*texts)
    if subjective:
        found.append(_finding(SUBJECTIVE_CODE, "subjective", subjective))
    fast = fast_motion_hits(*texts, fight=fight)
    if fast:
        found.append(_finding(FAST_MOTION_CODE, "fast_motion", fast))
    return found


def subjective_examples() -> str:
    """The subjective words, joined for a writing rule."""
    return prompt_data.text(_DATA, "separator").join(str(entry["word"]) for entry in _entries("subjective_words"))


def fast_motion_examples() -> str:
    """The fast-motion words, joined for a writing rule."""
    return prompt_data.text(_DATA, "separator").join(str(entry["word"]) for entry in _entries("fast_motion_words"))


def codes() -> frozenset[str]:
    return frozenset({SUBJECTIVE_CODE, FAST_MOTION_CODE})


__all__ = [
    "FAST_MOTION_CODE", "SUBJECTIVE_CODE", "VisualWordingFinding", "codes", "fast_motion_examples", "fast_motion_hits",
    "findings", "subjective_examples", "subjective_hits",
]
