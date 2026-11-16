# -*- coding: utf-8 -*-
"""Named lighting setups: when each fits, how to write it, what it cannot share a shot with, how it fails.

The shot-design reference has a lighting chapter, but it sits past the part of that file a storyboard
prompt has room for, so the model that writes each shot's lighting never saw a named setup. This table
is the short form: for the shots in hand it picks the setups their content calls for (a candle, a
window, an interrogation, dusk) and tells the model how to write each, what not to stack on it and the
failure to guard against, under one rule: one key light per shot. A lighting line that names two
setups which cancel each other gets a hint for the editor; nothing is sent back to the model.

The table and every sentence are ``app/data/prompt/light_setups.json``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.core import prompt_data

_DATA = "light_setups"
CLASH = "light_clash"


def _setups() -> list[Mapping[str, Any]]:
    return [item for item in prompt_data.value(_DATA, "setups") if isinstance(item, Mapping) and item.get("name")]


def names() -> list[str]:
    return [str(item["name"]) for item in _setups()]


def for_content(text: str, limit: int | None = None) -> list[Mapping[str, Any]]:
    """The setups ``text`` (the content of the shots in hand) calls for, in the order it first mentions them."""
    cap = prompt_data.number(_DATA, "guide_limit") if limit is None else limit
    found: list[tuple[int, int, Mapping[str, Any]]] = []
    for order, item in enumerate(_setups()):
        places = [text.find(str(cue)) for cue in item.get("cues") or [] if str(cue) and str(cue) in text]
        if places:
            found.append((min(places), order, item))
    return [item for _place, _order, item in sorted(found, key=lambda entry: entry[:2])[: max(0, cap)]]


def guide(text: str) -> str:
    """What the model writing lighting is told for these shots; ``""`` when their content calls for no named setup."""
    chosen = for_content(text)
    if not chosen:
        return ""
    separator = prompt_data.text(_DATA, "name_separator")
    lines = [prompt_data.text(_DATA, "head")]
    for item in chosen:
        avoid = separator.join(str(name) for name in item.get("not_with") or [])
        template = prompt_data.text(_DATA, "item" if avoid else "item_alone")
        lines.append(template.format(name=item["name"], write=item.get("write") or "", not_with=avoid, guard=item.get("guard") or ""))
    return "".join(lines)


def scene_brief(text: str) -> str:
    """What the storyboard writer is told for one scene; ``""`` when its content calls for no named setup.

    A scene has one key light, copied shot by shot, so the brief asks for one choice among the few that fit.
    """
    chosen = for_content(text, prompt_data.number(_DATA, "scene_limit"))
    if not chosen:
        return ""
    separator = prompt_data.text(_DATA, "name_separator")
    lines = [prompt_data.text(_DATA, "scene_head")]
    for item in chosen:
        avoid = separator.join(str(name) for name in item.get("not_with") or [])
        template = prompt_data.text(_DATA, "scene_item" if avoid else "scene_item_alone")
        lines.append(template.format(name=item["name"], write=item.get("write") or "", not_with=avoid, guard=item.get("guard") or ""))
    return "\n".join(lines)


def written(lighting: str) -> list[str]:
    """The setups a written lighting line uses, by the words that mark each."""
    return [str(item["name"]) for item in _setups() if any(str(mark) and str(mark) in lighting for mark in item.get("marks") or [])]


def clashes(lighting: str) -> list[str]:
    """One hint per pair of setups in a lighting line that cannot share a shot."""
    used = written(lighting)
    avoid = {str(item["name"]): {str(name) for name in item.get("not_with") or []} for item in _setups()}
    hints: list[str] = []
    for index, first in enumerate(used):
        for second in used[index + 1:]:
            if second in avoid.get(first, ()) or first in avoid.get(second, ()):
                hints.append(prompt_data.text(_DATA, "clash").format(first=first, second=second))
    return hints


def content_of(scenes: Iterable[Mapping[str, Any]]) -> str:
    """The text of a batch of shots that says where and when they play: setting and description."""
    return "\n".join(f"{scene.get('setting') or ''} {scene.get('scene_description') or ''}" for scene in scenes if isinstance(scene, Mapping))


__all__ = ["CLASH", "clashes", "content_of", "for_content", "guide", "names", "scene_brief", "written"]
