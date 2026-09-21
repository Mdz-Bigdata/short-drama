# -*- coding: utf-8 -*-
"""Single source of truth for "how long does this spoken line take".

Used by the script-plan stage (duration lower bound: a shot may not be shorter
than its dialogue) and by the admission check that flags shots whose speech
cannot fit into the longest clip the video model can render.

Rates are reading units per second (see :mod:`text_metrics`), so a Chinese
rate of 5 字/秒 and an English rate of 2.5 词/秒 are both expressed in the
unit the planner already counts.
"""

from __future__ import annotations

from app.core.screenwriting.text_metrics import count_reading_units

DEFAULT_SPEECH_RATE_UPS: float = 5.0
SPEECH_RATE_UPS_BY_LANGUAGE: dict[str, float] = {"zh": 5.0, "en": 2.5, "vi": 2.5}

# Loose bounds that only reject obvious mistakes (a TTS multiplier, a millisecond
# value). 0.001 keeps every downstream micro-second conversion far from overflow.
MIN_SPEECH_RATE_UPS: float = 0.001
MAX_SPEECH_RATE_UPS: float = 20.0


def is_valid_speech_rate(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        rate = float(value)
    except (OverflowError, ValueError):
        return False
    return MIN_SPEECH_RATE_UPS <= rate <= MAX_SPEECH_RATE_UPS


def speech_rate_units_per_second(language: str | None = None, override: float | None = None) -> float:
    """Effective rate: a valid project override wins, otherwise the language default."""
    if override is not None and is_valid_speech_rate(override):
        return float(override)
    if not language:
        return DEFAULT_SPEECH_RATE_UPS
    return SPEECH_RATE_UPS_BY_LANGUAGE.get(language.strip().lower(), DEFAULT_SPEECH_RATE_UPS)


def estimate_spoken_seconds(text: str | None, language: str | None = None, override: float | None = None) -> float:
    """Seconds needed to read ``text`` aloud; blank or punctuation-only text is 0."""
    if not text:
        return 0.0
    units = count_reading_units(text, language)
    if units <= 0:
        return 0.0
    return units / speech_rate_units_per_second(language, override)


__all__ = [
    "DEFAULT_SPEECH_RATE_UPS",
    "SPEECH_RATE_UPS_BY_LANGUAGE",
    "MIN_SPEECH_RATE_UPS",
    "MAX_SPEECH_RATE_UPS",
    "is_valid_speech_rate",
    "speech_rate_units_per_second",
    "estimate_spoken_seconds",
]
