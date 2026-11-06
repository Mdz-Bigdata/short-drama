# -*- coding: utf-8 -*-
"""Prompt wording and word tables, kept as data in ``app/data/prompt/*.json``.

The modules that write prompts (the clip prompt engine, the style packs' named rules, the
sound planner, the storyboard reviewer, the stage-4 writing rules) read their sentences,
word lists, patterns and limits from here instead of carrying them in code: a wording change
is a data change. Each file is read once per process.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "data" / "prompt"


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    """The whole ``<name>.json`` as a dict."""
    return json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))


def value(name: str, key: str) -> Any:
    return load(name)[key]


def text(name: str, key: str) -> str:
    return str(load(name)[key])


def number(name: str, key: str) -> int:
    return int(load(name)[key])


def words(name: str, key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in load(name)[key])


def pairs(name: str, key: str) -> tuple[tuple[str, str], ...]:
    return tuple((str(first), str(second)) for first, second in load(name)[key])


def pattern(name: str, key: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(text(name, key), flags)


__all__ = ["ROOT", "load", "number", "pairs", "pattern", "text", "value", "words"]
