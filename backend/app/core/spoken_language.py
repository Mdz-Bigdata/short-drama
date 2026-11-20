# -*- coding: utf-8 -*-
"""Which language or dialect the characters speak in clips whose sound the video model makes itself.

A project may pick one (四川话, 粤语, 英语 …); the 「对白语言」 line of each shot's video prompt then names
it, and for a dialect says the three things that keep it from coming out as Mandarin with a few local
words. With nothing picked the line is exactly what it was (Mandarin), except that a project whose
content language is English or Vietnamese follows that language instead of being told to speak Mandarin.

Dubbed lines (TTS) are not this module's business. Wording and the list are data
(``app/data/prompt/spoken_language.json``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "spoken_language"
CONFIG_KEY = "spoken_language"


def _options() -> list[Mapping[str, Any]]:
    return list(prompt_data.value(_DATA, "options"))


def options() -> list[dict[str, str]]:
    """What a project can pick, the default first: ``[{key, label}]``."""
    return [{"key": str(item["key"]), "label": str(item["label"])} for item in _options()]


def normalize(key: Any) -> str:
    """A known key, or '' (the default) for anything else."""
    wanted = str(key or "").strip().lower()
    return wanted if wanted and any(item["key"] == wanted for item in _options()) else ""


def checked(key: Any) -> str:
    """Validate a new choice; '' or None is the default. An unknown key is refused."""
    wanted = str(key or "").strip().lower()
    if wanted and not normalize(wanted):
        raise ValueError(str(prompt_data.value(_DATA, "errors")["unknown"]).format(key=key))
    return wanted


def of(config: Mapping[str, Any] | None) -> str:
    """The project's spoken language: what was picked, else what its content language implies, else '' (Mandarin)."""
    config = config or {}
    picked = normalize(config.get(CONFIG_KEY))
    if picked:
        return picked
    implied: Mapping[str, Any] = prompt_data.value(_DATA, "from_content_language")
    return normalize(implied.get(str(config.get("content_language") or "").strip().lower()))


def phrase(config: Mapping[str, Any] | None) -> str:
    """How the 「对白语言」 line names it; '' leaves the line's own default."""
    key = of(config)
    found = next((item for item in _options() if item["key"] == key), None) if key else None
    if not found or found.get("kind") not in {"dialect", "foreign"}:
        return ""
    return str(prompt_data.value(_DATA, str(found["kind"]))).format(label=found["label"])


__all__ = ["CONFIG_KEY", "checked", "normalize", "of", "options", "phrase"]
