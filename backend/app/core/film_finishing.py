# -*- coding: utf-8 -*-
"""Film finishing (成片精修): how the finished film looks, kept beside the four basic switches.

Four things a person can set for the whole film, all saved under ``timeline["settings"]["finishing"]`` and
changed through the same ``settings`` edit as the switches:

- ``title``    — the title card's animation and, optionally, a frame of one of the film's shots behind the title;
- ``subtitle`` — size, colour, position and outline of every burned subtitle;
- ``color``    — a film-wide grade: brightness, contrast, saturation and warmth, with a few presets;
- ``ending``   — an optional card after the last shot with one line of the user's own text.

Every default is "exactly as before": a timeline that never touched these renders with no finishing
arguments at all (:func:`render_spec` returns ``None``), so its filter graph is the one it always had.

Nothing here draws or runs ffmpeg — :mod:`app.core.film_finishing_render` does that. Option tables, numbers
and the wording of errors live in ``app/data/prompt/film_finishing.json``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from app.core import prompt_data

_DATA = "film_finishing"
#: Where the finishing settings sit inside ``timeline["settings"]``.
KEY = "finishing"
SECTIONS = ("title", "subtitle", "color", "ending")
#: The grade's preset name once a slider was moved off every preset.
CUSTOM_PRESET = "custom"
_SUBTITLE_TABLES = {"size": "sizes", "color": "colors", "position": "positions", "outline": "outlines"}


class FinishingError(ValueError):
    """A finishing setting names an option or a value that does not exist."""


def _table(key: str) -> Any:
    return prompt_data.value(_DATA, key)


def _error(key: str, *values: Any) -> FinishingError:
    return FinishingError(str(_table("errors")[key]).format(*values))


def sliders() -> tuple[str, ...]:
    return tuple(str(name) for name in _table("color")["sliders"])


def _presets() -> dict[str, dict[str, int]]:
    return {str(row["id"]): {name: int(row.get(name) or 0) for name in sliders()} for row in _table("color")["presets"]}


def _preset_of(values: Mapping[str, Any]) -> str:
    """The preset these slider values are, or ``custom`` when they match none."""
    current = {name: int(values.get(name) or 0) for name in sliders()}
    return next((name for name, preset in _presets().items() if preset == current), CUSTOM_PRESET)


def defaults() -> dict[str, Any]:
    """The settings of a film nobody finished: today's title card, today's subtitles, no grade, no ending card."""
    return {
        "title": {"animation": str(_table("title")["default_animation"]), "background": None},
        "subtitle": {key: str(value) for key, value in _table("subtitle")["defaults"].items()},
        "color": {"preset": str(_table("color")["neutral_preset"]), **dict.fromkeys(sliders(), 0)},
        "ending": {"enabled": False, "text": ""},
    }


# ---------------------------------------------------------------------------- reading and changing

Refuse = Callable[..., None]


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def _clip_named(clips: Sequence[Any], shot_uid: Any, shot_id: Any) -> Mapping[str, Any] | None:
    """The clip a background names: by ``shot_uid`` when it has one (``shot_id`` repeats in every scene)."""
    rows = [clip for clip in clips if isinstance(clip, Mapping)]
    if shot_uid is not None:
        found = next((clip for clip in rows if str(clip.get("shot_uid")) == str(shot_uid)), None)
        if found is not None:
            return found
        rows = [clip for clip in rows if not clip.get("shot_uid")]
    return next((clip for clip in rows if shot_id is not None and str(clip.get("shot_id")) == str(shot_id)), None)


def _background(picked: Any, clips: Sequence[Any] | None, refuse: Refuse) -> dict[str, Any] | None | bool:
    """The saved form of a title background, ``None`` for the plain card, ``False`` when it cannot be read."""
    if picked is None or picked == "":
        return None
    if not isinstance(picked, Mapping) or (picked.get("shot_uid") is None and picked.get("shot_id") is None):
        refuse("title_background")
        return False
    at = _number(picked.get("at", 0.0))
    if at is None:
        refuse("title_background")
        return False
    saved = {"shot_uid": picked.get("shot_uid"), "shot_id": picked.get("shot_id"), "at": round(max(0.0, at), 2)}
    if clips is None:
        return saved
    clip = _clip_named(clips, saved["shot_uid"], saved["shot_id"])
    if clip is None or not clip.get("video_url"):
        refuse("title_shot")
        return False
    duration = _number(clip.get("duration")) or 0.0
    if duration > 0:
        saved["at"] = round(min(saved["at"], max(0.0, duration - float(_table("title")["background"]["end_margin_seconds"]))), 2)
    return {**saved, "shot_uid": clip.get("shot_uid"), "shot_id": clip.get("shot_id")}


def _known_keys(section: str, change: Mapping[str, Any], allowed: Sequence[str], refuse: Refuse) -> None:
    for key in change:
        if key not in allowed:
            refuse("unknown_key", section, key, ", ".join(allowed))


def _title(current: Mapping[str, Any], change: Mapping[str, Any], clips: Sequence[Any] | None, refuse: Refuse) -> dict[str, Any]:
    new = dict(current)
    _known_keys("title", change, ("animation", "background"), refuse)
    animations = [str(name) for name in _table("title")["animations"]]
    if "animation" in change:
        if change["animation"] in animations:
            new["animation"] = str(change["animation"])
        else:
            refuse("title_animation", change["animation"], ", ".join(animations))
    if "background" in change:
        background = _background(change["background"], clips, refuse)
        if background is not False:
            new["background"] = background
    return new


def _subtitle(current: Mapping[str, Any], change: Mapping[str, Any], refuse: Refuse) -> dict[str, Any]:
    new = dict(current)
    _known_keys("subtitle", change, tuple(_SUBTITLE_TABLES), refuse)
    for key, table in _SUBTITLE_TABLES.items():
        if key not in change:
            continue
        options = [str(name) for name in _table("subtitle")[table]]
        if change[key] in options:
            new[key] = str(change[key])
        else:
            refuse("subtitle_option", _table("subtitle_option_names")[key], change[key], ", ".join(options))
    return new


def _color(current: Mapping[str, Any], change: Mapping[str, Any], refuse: Refuse) -> dict[str, Any]:
    new = dict(current)
    limit = int(_table("color")["limit"])
    presets = _presets()
    _known_keys("color", change, ("preset", *sliders()), refuse)
    if "preset" in change and change["preset"] != CUSTOM_PRESET:
        if change["preset"] in presets:
            new.update(presets[str(change["preset"])])
        else:
            refuse("color_preset", change["preset"], ", ".join(presets))
    for name in sliders():
        if name not in change:
            continue
        amount = _number(change[name])
        if amount is None:
            refuse("color_value", name, limit)
        else:
            new[name] = int(max(-limit, min(limit, round(amount))))
    new["preset"] = _preset_of(new)
    return new


def clean_ending_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[: int(_table("ending")["max_chars"])]


def _ending(current: Mapping[str, Any], change: Mapping[str, Any], refuse: Refuse) -> dict[str, Any]:
    new = dict(current)
    _known_keys("ending", change, ("enabled", "text"), refuse)
    if "enabled" in change:
        if isinstance(change["enabled"], bool):
            new["enabled"] = change["enabled"]
        else:
            refuse("ending_enabled")
    if "text" in change:
        if change["text"] is None or isinstance(change["text"], str):
            new["text"] = clean_ending_text(change["text"])
        else:
            refuse("ending_text")
    return new


def _applied(base: Mapping[str, Any], changes: Any, *, strict: bool, clips: Sequence[Any] | None = None) -> dict[str, Any]:
    """``base`` with ``changes`` laid over it, section by section. Strict refuses what it cannot read; lenient skips it."""

    def refuse(key: str, *values: Any) -> None:
        if strict:
            raise _error(key, *values)

    new = deepcopy(dict(base))
    if not isinstance(changes, Mapping):
        refuse("not_an_object")
        return new
    for section, change in changes.items():
        if section not in SECTIONS:
            refuse("unknown_section", section, ", ".join(SECTIONS))
            continue
        if not isinstance(change, Mapping):
            refuse("not_an_object")
            continue
        if section == "title":
            new["title"] = _title(new["title"], change, clips, refuse)
        elif section == "subtitle":
            new["subtitle"] = _subtitle(new["subtitle"], change, refuse)
        elif section == "color":
            new["color"] = _color(new["color"], change, refuse)
        else:
            new["ending"] = _ending(new["ending"], change, refuse)
    return new


def _saved(timeline: Mapping[str, Any]) -> Any:
    settings = timeline.get("settings") if isinstance(timeline.get("settings"), Mapping) else {}
    return settings.get(KEY)


def of(timeline: Mapping[str, Any]) -> dict[str, Any]:
    """The film's finishing settings in full. A timeline saved before they existed reads as the defaults."""
    saved = _saved(timeline)
    return _applied(defaults(), saved, strict=False) if isinstance(saved, Mapping) else defaults()


def changed(timeline: Mapping[str, Any], changes: Any) -> dict[str, Any]:
    """The settings after an edit, ready to save. ``changes`` names only what moves: ``{"color": {"contrast": 12}}``.

    Raises :class:`FinishingError` for an unknown option, a shot the timeline does not hold, or a value that is not one.
    """
    clips = [clip for clip in timeline.get("clips") or [] if isinstance(clip, Mapping)]
    return _applied(of(timeline), changes, strict=True, clips=clips)


def is_default(value: Mapping[str, Any]) -> bool:
    return dict(value) == defaults()


# ---------------------------------------------------------------------------- what the compositor is told


def render_spec(timeline: Mapping[str, Any], *, title_card: bool = True, subtitles: bool = True) -> dict[str, Any] | None:
    """What the compositor needs beyond today's arguments, or ``None`` when nothing was finished.

    Only the parts that differ from the defaults are named, so an untouched part is rendered by the code it always was:
    ``title`` (animation + the background clip and moment), ``subtitle`` (the four style choices), ``grade`` (the four
    slider values) and ``ending`` (text + seconds).
    """
    value = of(timeline)
    base = defaults()
    spec: dict[str, Any] = {}
    if title_card:
        picked = value["title"]["background"]
        clip = _clip_named(timeline.get("clips") or [], picked.get("shot_uid"), picked.get("shot_id")) if picked else None
        background = {"video_url": str(clip["video_url"]), "at": float(picked.get("at") or 0.0)} if clip and clip.get("video_url") else None
        if background or value["title"]["animation"] != base["title"]["animation"]:
            spec["title"] = {"animation": value["title"]["animation"], "background": background}
    if subtitles and value["subtitle"] != base["subtitle"]:
        spec["subtitle"] = dict(value["subtitle"])
    if any(value["color"][name] for name in sliders()):
        spec["grade"] = {name: int(value["color"][name]) for name in sliders()}
    if value["ending"]["enabled"] and value["ending"]["text"]:
        spec["ending"] = {"text": value["ending"]["text"], "seconds": float(_table("ending")["seconds"])}
    return spec or None


def fingerprint(spec: Mapping[str, Any] | None) -> str:
    """A stable text of a render spec, for the film's file name."""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True) if spec else ""


def ending_seconds(timeline: Mapping[str, Any]) -> float:
    """How long the ending card adds to the film: nothing unless it is on and has a line."""
    ending = of(timeline)["ending"] if isinstance(_saved(timeline), Mapping) else None
    return float(_table("ending")["seconds"]) if ending and ending["enabled"] and ending["text"] else 0.0


def ending_transition() -> dict[str, Any]:
    return dict(_table("ending")["transition"])


def grade_filters(grade: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """The ffmpeg filters of a grade as (filter name, filter text); none at all for neutral values."""
    if not grade:
        return []
    table = _table("color")
    limit = float(table["limit"])
    amount = {name: max(-limit, min(limit, float(grade.get(name) or 0))) for name in sliders()}
    filters: list[tuple[str, str]] = []
    if any(amount[name] for name in table["eq"]):
        parts = [f"{name}={rule['base'] + amount[name] / limit * rule['span']:.3f}" for name, rule in table["eq"].items()]
        filters.append(("eq", "eq=" + ":".join(parts)))
    if amount.get("warmth"):
        rule = table["temperature"]
        kelvin = rule["neutral"] + amount["warmth"] * rule["kelvin_per_step"]
        filters.append(("colortemperature", f"colortemperature=temperature={int(max(rule['min'], min(rule['max'], kelvin)))}"))
    return filters


def subtitle_metrics(style: Mapping[str, Any] | None, *, height: int) -> dict[str, Any]:
    """The numbers a subtitle is drawn with for a style, at a frame ``height`` pixels tall.

    The medium size at the reference height is the layout subtitles always had; other sizes scale it.
    """
    table = _table("subtitle")
    chosen = {**table["defaults"], **{key: value for key, value in (style or {}).items() if key in _SUBTITLE_TABLES}}
    for key, name in _SUBTITLE_TABLES.items():
        if chosen[key] not in table[name]:
            chosen[key] = table["defaults"][key]
    base = table["metrics"]
    scale = table["sizes"][chosen["size"]] / base["font_px"]
    position = table["positions"][chosen["position"]]
    return {
        "font_px": int(table["sizes"][chosen["size"]]),
        **{key: int(round(base[key] * scale)) for key in ("line_height", "box_pad_x", "box_top", "box_bottom", "text_mid")},
        "box_alpha": int(base["box_alpha"]), "max_chars": int(base["max_chars"]), "side_margin": int(base["side_margin"]),
        "color": tuple(int(part) for part in table["colors"][chosen["color"]]),
        "outline_px": int(table["outlines"][chosen["outline"]]),
        "bottom_safe": max(int(position["min_px"]), int(height * position["fraction"])),
    }


# ---------------------------------------------------------------------------- what the page is told


def options() -> dict[str, Any]:
    """The choices the page offers, by id; what each is called is the page's wording."""
    subtitle, color = _table("subtitle"), _table("color")
    return {
        "title_animations": list(_table("title")["animations"]),
        "subtitle": {
            "sizes": list(subtitle["sizes"]), "positions": list(subtitle["positions"]), "outlines": list(subtitle["outlines"]),
            "colors": [{"id": name, "rgb": list(rgb)} for name, rgb in subtitle["colors"].items()],
        },
        "color": {"limit": int(color["limit"]), "sliders": list(sliders()),
                  "presets": [{"id": name, **values} for name, values in _presets().items()]},
        "ending": {"max_chars": int(_table("ending")["max_chars"]), "seconds": float(_table("ending")["seconds"])},
    }


def teaser_of(task: Mapping[str, Any], episode: Any = None) -> str:
    """The episode ledger's 下集预告 for the episode on the timeline, to offer as the ending card's line.

    Without an episode (a film made in one run) it is the last episode's; empty when the ledger has none.
    """
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get("2_screenwriting") if isinstance(assets.get("2_screenwriting"), Mapping) else {}
    rows = sorted((row for row in state.get("ledger") or [] if isinstance(row, Mapping)), key=lambda row: int(row.get("episode") or 0))
    if episode is not None:
        rows = [row for row in rows if str(row.get("episode")) == str(episode)]
    return clean_ending_text(rows[-1].get("next_episode_teaser")) if rows else ""


def view(timeline: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    return {"value": of(timeline), "options": options(), "ending_teaser": teaser_of(task, timeline.get("episode"))}


__all__ = [
    "CUSTOM_PRESET", "FinishingError", "KEY", "SECTIONS", "changed", "clean_ending_text", "defaults", "ending_seconds",
    "ending_transition", "fingerprint", "grade_filters", "is_default", "of", "options", "render_spec", "sliders",
    "subtitle_metrics", "teaser_of", "view",
]
