# -*- coding: utf-8 -*-
"""Story directions offered before a project is made, and the things the creator rules out.

From one idea the text model proposes a few directions that really differ (what the lead wants, who
stands in the way, where the story lands); the creator picks one, or none. With no idea at all it
recommends directions of different genres from the creation type and the audience, and the one
picked becomes the idea. The chosen direction goes
to the stage-1 director as the outline of the plan to write. A separate list, the creator's own
no-go lines, goes to the director and to every batch of the episode planner.

Neither applies to an advert or to a project whose script was uploaded. A direction is a brief for
the director, not a replacement for the plan; nothing here is checked afterwards or sent back.
Wording and limits are data (``app/data/prompt/story_direction.json``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core import prompt_data, script_structure, target_audience
from app.core.screenwriting.structured_llm import extract_json_object

_DATA = "story_direction"
DIRECTION_KEY = "story_direction"
NO_GO_KEY = "story_no_go"


class StoryDirectionError(ValueError):
    """A request that cannot be answered, or a model answer that cannot be used."""


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> int:
    return int(_data()["limits"][key])


def _error(key: str, **values: object) -> StoryDirectionError:
    return StoryDirectionError(str(_data()["errors"][key]).format(**values))


def fields() -> tuple[str, ...]:
    return tuple(str(name) for name in _data()["fields"])


def field_labels() -> dict[str, str]:
    return {str(key): str(value) for key, value in _data()["field_labels"].items()}


def max_tokens() -> int:
    return _limit("max_tokens")


def _clean(value: Any, limit: int) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    return re.sub(r"\s+", " ", text).strip()[:limit]


def normalize_direction(raw: Any) -> dict[str, str]:
    """A direction with every field a short line, or ``{}`` when it has no title or no story."""
    if not isinstance(raw, Mapping):
        return {}
    found = {name: _clean(raw.get(name), _limit("title_chars") if name == "title" else _limit("field_chars")) for name in fields()}
    return found if found.get("title") and found.get("logline") else {}


def normalize_no_go(raw: Any) -> list[str]:
    """The creator's no-go lines: trimmed, without list marks, no repeats, within the limits."""
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, (list, tuple)):
        return []
    lines = [_clean(re.sub(r"^\s*(?:[-*•·]|\d+[.、)）])\s*", "", str(item)), _limit("no_go_chars")) for item in raw]
    return list(dict.fromkeys(line for line in lines if line))[: _limit("no_go_items")]


def applies(config: Mapping[str, Any] | None) -> bool:
    """Serials and the short film, written by the pipeline; an advert and an uploaded script have their own brief."""
    return script_structure.applies(config)


def direction_of(config: Mapping[str, Any] | None) -> dict[str, str]:
    return normalize_direction((config or {}).get(DIRECTION_KEY)) if applies(config) else {}


def no_go_of(config: Mapping[str, Any] | None) -> list[str]:
    return normalize_no_go((config or {}).get(NO_GO_KEY)) if applies(config) else []


# --------------------------------------------------------------------------- proposing directions


def clean_trend(raw: Any) -> str:
    """The hot topic the creator wants to borrow from, as one short line; '' when none was written."""
    return _clean(raw, _limit("trend_chars"))


def prompts(*, idea: str, config: Mapping[str, Any], count: int | None = None, trend: str = "") -> tuple[str, str, int]:
    """``(system, user, count)`` for one text call; :class:`StoryDirectionError` when the request cannot be made.

    ``trend`` is a hot topic the creator typed in: its feeling and shape are borrowed, never the real people or event.
    """
    if not applies(config):
        raise _error("not_for_mode")
    clean = "".join(ch for ch in str(idea or "") if ch in "\n\t" or ch.isprintable()).strip()
    if len(clean) > _limit("idea_chars"):
        raise _error("idea_too_long", limit=_limit("idea_chars"), length=len(clean))
    # No idea yet: the directions are recommended from the creation type and the audience alone.
    open_start = not clean
    wanted = min(_limit("count_max"), max(_limit("count_min"), int(count or _limit("count_open" if open_start else "count_default"))))
    data = _data()
    mode = str(config.get("creation_mode") or "drama")
    who = target_audience.who(config)
    structure = script_structure.label(script_structure.of(config))
    no_go = normalize_no_go(config.get(NO_GO_KEY))
    user = str(data["user_open" if open_start else "user"]).format(
        mode=str(data["modes"].get(mode, data["modes"]["drama"])),
        episodes=max(1, int(config.get("episode_count") or 1)),
        audience=str(data["user_audience"]).format(who=who) if who else "",
        structure=str(data["user_structure"]).format(label=structure) if structure else "",
        no_go=str(data["user_no_go"]).format(items=str(data["no_go_joiner"]).join(no_go)) if no_go else "",
        idea=clean,
    )
    system = str(data["system_open" if open_start else "system"]).format(count=wanted)
    borrowed = clean_trend(trend)
    if borrowed:
        system += str(data["trend_rule"])
        user = str(data["user_trend"]).format(trend=borrowed) + user
    return system, user, wanted


def idea_from(direction: Mapping[str, Any]) -> str:
    """The idea a picked direction stands in for when the creator wrote none: what goes into the idea box."""
    chosen = normalize_direction(direction)
    return str(_data()["idea_from_direction"]).format(**chosen) if chosen else ""


def parse(answer: str, minimum: int = 2) -> list[dict[str, str]]:
    """The usable directions of an answer, titles distinct; :class:`StoryDirectionError` when too few can be used."""
    if not str(answer or "").strip():
        raise _error("no_answer")
    found = extract_json_object(answer)
    rows = found.get("directions") if isinstance(found, dict) else None
    if not isinstance(rows, list):
        raise _error("not_object")
    usable: list[dict[str, str]] = []
    for row in rows:
        direction = normalize_direction(row)
        if direction and direction["title"] not in {item["title"] for item in usable}:
            usable.append(direction)
    usable = usable[: _limit("count_max")]
    if len(usable) < minimum:
        raise _error("too_few", found=len(usable))
    return usable


# --------------------------------------------------------------------------- what the stages are told


def _no_go_items(lines: list[str]) -> str:
    return "\n".join(str(_data()["no_go_item"]).format(text=line) for line in lines)


def director_rule(config: Mapping[str, Any] | None) -> str:
    """The chosen direction and the no-go list for the stage-1 director; empty when neither was given."""
    parts: list[str] = []
    direction = direction_of(config)
    if direction:
        parts.append(str(_data()["director_direction"]).format(**{name: direction.get(name) or "—" for name in fields()}))
    lines = no_go_of(config)
    if lines:
        parts.append(str(_data()["director_no_go"]).format(items=_no_go_items(lines)))
    return "\n\n".join(parts)


def outline_rules(creation: Mapping[str, Any] | None) -> list[str]:
    """The no-go list for one batch of the episode planner; the direction itself reaches it through the director's plan."""
    lines = no_go_of(creation)
    return [str(_data()["outline_no_go"]).format(items=str(_data()["no_go_joiner"]).join(lines))] if lines else []


__all__ = [
    "DIRECTION_KEY", "NO_GO_KEY", "StoryDirectionError", "applies", "clean_trend", "direction_of", "director_rule", "field_labels", "fields",
    "idea_from", "max_tokens", "no_go_of", "normalize_direction", "normalize_no_go", "outline_rules", "parse", "prompts",
]
