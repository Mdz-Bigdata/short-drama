"""Transition vocabulary: classic cut types plus media-driven categories.

Editing-book types (cut, fade, dissolve, flash, wipe, push/pull, match cut,
montage) carry the pacing; media categories (occlusion, camera move, action,
light, time-lapse, emotion, space jump) carry the *how* for AI clips, where a
transition is generated inside the shot rather than in an NLE. Every transition
can be written with one formula: outgoing action + medium + camera move +
incoming scene + light mood.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core import prompt_data

# The editing types, the media categories, their aliases, the hard-cut rewrites, the prompt guide
# and the sentence templates: app/data/prompt/transition_catalog.json.
_WORDING = "transition_catalog"
_TYPE_COLUMNS = ("value", "label", "en", "usage", "emotions", "pacing")
_CATEGORY_COLUMNS = ("value", "label", "purpose", "media")
# The formula's slots in the order they are written; each is a ``says`` template filled with ``{text}``.
_FORMULA_SLOTS = ("outgoing_action", "medium", "camera_move", "incoming_scene", "light")


def _says(key: str, /, **values: object) -> str:
    """A sentence of the catalog's wording, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _rows(table: str, columns: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """A table of the catalog's data as tuples of its columns, in file order."""
    return tuple(tuple(str(row[column]) for column in columns) for row in prompt_data.value(_WORDING, table))


def _aliases(table: str) -> dict[str, tuple[str, ...]]:
    return {str(name): tuple(str(alias) for alias in aliases) for name, aliases in prompt_data.value(_WORDING, table).items()}


# value, zh label, en, usage, emotions, pacing
TRANSITION_TYPES: tuple[tuple[str, str, str, str, str, str], ...] = _rows("types", _TYPE_COLUMNS)  # type: ignore[assignment]
# value, zh label, purpose, media examples
TRANSITION_CATEGORIES: tuple[tuple[str, str, str, str], ...] = _rows("categories", _CATEGORY_COLUMNS)  # type: ignore[assignment]
_TYPE_BY_KEY = {value: value for value, *_ in TRANSITION_TYPES}
_TYPE_SYNONYMS = _aliases("type_synonyms")
_CATEGORY_LABELS = {value: label for value, label, _, _ in TRANSITION_CATEGORIES}
_CATEGORY_SYNONYMS = _aliases("category_synonyms")
# 认不出类型时的标签：不用硬切，一律按匹配剪辑处理。
_FALLBACK_LABEL = prompt_data.text(_WORDING, "fallback_label")


def _key(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).casefold()


def normalize_transition_type(value: Any) -> tuple[str, bool]:
    """Canonical editing type for free text such as '声音先行硬切' (sound bridge wins over plain cut)."""
    key = _key(value)
    if not key:
        return "cut", False
    if key in _TYPE_BY_KEY:
        return key, True
    best: tuple[int, str] | None = None
    for canonical, aliases in _TYPE_SYNONYMS.items():
        for alias in aliases:
            alias_key = _key(alias)
            if alias_key and alias_key in key:
                score = (len(alias_key), canonical)
                if best is None or score > best:
                    best = score
    if best:
        return best[1], True
    return "cut", False


def classify_transition_category(value: Any) -> str:
    """Media category suggested by the transition prose, or '' when it names none."""
    key = _key(value)
    best: tuple[int, str] | None = None
    for category, aliases in _CATEGORY_SYNONYMS.items():
        for alias in aliases:
            alias_key = _key(alias)
            if alias_key and alias_key in key and (best is None or len(alias_key) > best[0]):
                best = (len(alias_key), category)
    return best[1] if best else ""


class TransitionSpec(BaseModel):
    """One transition written with the universal formula."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    kind_label: str
    category: str = ""
    category_label: str = ""
    usage: str = ""
    emotions: str = ""
    prompt: str = Field("", max_length=1000)


def transition_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "types": [
            {"value": value, "label": label, "en": en, "usage": usage, "emotions": emotions, "pacing": pacing}
            for value, label, en, usage, emotions, pacing in TRANSITION_TYPES
        ],
        "categories": [
            {"value": value, "label": label, "purpose": purpose, "media": media}
            for value, label, purpose, media in TRANSITION_CATEGORIES
        ],
    }


def compose_transition(
    kind: str,
    *,
    outgoing_action: str = "",
    medium: str = "",
    camera_move: str = "",
    incoming_scene: str = "",
    light: str = "",
    category: str = "",
) -> TransitionSpec:
    """Universal formula: outgoing action + medium + camera move + incoming scene + light mood."""
    canonical = smooth_kind(normalize_transition_type(kind)[0])
    _, label, _en, usage, emotions, _pacing = next(row for row in TRANSITION_TYPES if row[0] == canonical)
    category = category if category in _CATEGORY_LABELS else classify_transition_category(medium or outgoing_action)
    separator = _says("separator")
    parts = [
        _says(slot, text=text.strip()) if text.strip() else ""
        for slot, text in zip(_FORMULA_SLOTS, (outgoing_action, medium, camera_move, incoming_scene, light))
    ]
    prompt = _says("prompt_head", label=label, usage=usage) + separator.join(part for part in parts if part)
    return TransitionSpec(
        kind=canonical,
        kind_label=label,
        category=category,
        category_label=_CATEGORY_LABELS.get(category, ""),
        usage=usage,
        emotions=emotions,
        prompt=prompt.rstrip(separator),
    )


def transition_label(kind: str) -> str:
    return next((label for value, label, *_ in TRANSITION_TYPES if value == smooth_kind(kind)), _FALLBACK_LABEL)


def smooth_kind(kind: str) -> str:
    """不用硬切：读到的硬切一律按匹配剪辑(动作 / 视线 / 姿态延续)处理。"""
    return "match_cut" if kind == "cut" else kind


_HARD_CUT_WORDS = prompt_data.pattern(_WORDING, "hard_cut_words")
_SOUND_FIRST = prompt_data.text(_WORDING, "sound_first")
_SOUND_FIRST_JOIN = prompt_data.text(_WORDING, "sound_first_join")
_SMOOTH_JOIN = prompt_data.text(_WORDING, "smooth_join")
# 交接说明里的剪切动词换成连贯的说法(只用于转场交接文字，那里它们都指切镜)，按顺序替换。
_CUT_VERBS = prompt_data.pairs(_WORDING, "cut_verbs")


def smooth_text(text: Any) -> str:
    """转场说明里出现的「硬切 / 直切 / 跳切 / 切入切出」改写成连贯衔接的说法，旧数据进视频提示词前也不带硬切。"""
    out = _HARD_CUT_WORDS.sub(lambda m: _SOUND_FIRST_JOIN if m.group(0).startswith(_SOUND_FIRST) else _SMOOTH_JOIN, str(text or ""))
    for old, new in _CUT_VERBS:
        out = out.replace(old, new)
    return out


def describe_transition(value: Any) -> str:
    """Short catalog note for free-text transition types, used in prompts and checks."""
    canonical, matched = normalize_transition_type(value)
    canonical = smooth_kind(canonical)
    _, label, _en, usage, emotions, _pacing = next(row for row in TRANSITION_TYPES if row[0] == canonical)
    category = classify_transition_category(value)
    note = _says("note", label=label, usage=usage, emotions=emotions)
    if category:
        note += _says("note_category", category=_CATEGORY_LABELS[category])
    if not matched:
        note += _says("note_unmatched")
    return note


TRANSITION_PROMPT_GUIDE = "".join(prompt_data.words(_WORDING, "prompt_guide"))
_FORMULA_PATTERN = prompt_data.pattern(_WORDING, "formula_pattern")


def uses_transition_grammar(text: Any) -> bool:
    return bool(_FORMULA_PATTERN.search(str(text or "")))
