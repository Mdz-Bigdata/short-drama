# -*- coding: utf-8 -*-
"""Reading-unit metrics for screenplay planning.

The Writer Agent reasons about "how much source text fits in one episode" and
"how many seconds does this line take to speak" in *reading units*: Chinese
characters for CJK text, words for Latin-script languages. Both the episode
planner and the speech-rate estimator share this single definition so the
volume a planner promises and the seconds a duration check enforces never drift
apart.

Behavioral reference: ArcReel's ``lib/text_metrics.py`` (reimplemented
clean-room, see THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import re

# CJK Unified Ideographs (basic + ext A), compatibility ideographs, CJK
# punctuation, full-width forms and the SIP plane extensions.
_CJK_UNIT = re.compile("[㐀-鿿豈-﫿　-〿＀-￯𠀀-𲎯]")
_LATIN_WORD = re.compile(r"\b\w+\b", re.UNICODE)

_WORD_LANGUAGES = frozenset({"en", "vi"})


def _pattern_for(language: str | None) -> re.Pattern[str]:
    code = (language or "").strip().lower()
    return _LATIN_WORD if code in _WORD_LANGUAGES else _CJK_UNIT


def count_reading_units(text: str, language: str | None = None) -> int:
    """Count reading units of ``text`` for ``language`` (unknown languages count as zh)."""
    if not text:
        return 0
    return len(_pattern_for(language).findall(text))


def reading_unit_noun(language: str | None = None) -> str:
    """The Chinese measure word for one reading unit: 词 for word languages, 字 otherwise."""
    return "词" if _pattern_for(language) is _LATIN_WORD else "字"


def find_reading_unit_offset(text: str, target_units: int, language: str | None = None) -> int:
    """Character offset just after the ``target_units``-th reading unit.

    Scans in order so mixed ASCII/CJK text maps to the right position instead of a
    proportional guess. ``target_units <= 0`` gives 0, more units than the text has
    gives ``len(text)``.
    """
    if target_units <= 0 or not text:
        return 0
    for count, match in enumerate(_pattern_for(language).finditer(text), start=1):
        if count >= target_units:
            return match.end()
    return len(text)


__all__ = ["count_reading_units", "reading_unit_noun", "find_reading_unit_offset"]
