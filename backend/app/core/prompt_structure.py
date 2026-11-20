# -*- coding: utf-8 -*-
"""Fixed layouts a canvas prompt can be rewritten into, and a rule check of the result.

Three of the canvas optimizer's modes ask the text model for a prompt in fixed sections:

* ``structure``: eight sections for any clip (task, subjects, place, emotional aim, photography, a
  timed shot script, sound, continuity);
* ``fight``: eight sections for a fight (spec, fighters and weapons, space, rules, a timed action
  line where every beat is attack, answer, contact, reaction, surroundings, next start; sound,
  continuity, the picture it ends on);
* ``performance``: five sections that turn named emotions into ordered, measured movements of the
  face and body (for a clip with a timeline, for a picture as one caught instant).

:func:`guide` is what the model is told; :func:`check` reads the answer and says, by rule, whether
the sections are all there in order and whether the timed segments start at zero, join end to end
and add up to the clip's length. A fight is also checked for segments too short to hold an exchange,
a performance for emotion names and unmeasured adverbs left in the text.

Inside a timed script every segment may carry one camera move; that is the project's one-move rule
applied per segment instead of per clip. Nothing here calls a model or edits a prompt. Wording,
patterns and limits are data (``app/data/prompt/prompt_structure.json``).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping

from app.core import prompt_data

_DATA = "prompt_structure"
DEFAULT_LAYOUT = "structure"
_QUOTED = re.compile(r"「[^」]*」|“[^”]*”|\"[^\"]*\"")


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def layouts() -> tuple[str, ...]:
    return tuple(str(key) for key in _data()["layouts"])


def _layout(layout: str) -> Mapping[str, Any]:
    table = _data()["layouts"]
    return table[layout if layout in table else DEFAULT_LAYOUT]


def label(layout: str = DEFAULT_LAYOUT) -> str:
    return str(_layout(layout)["label"])


def video_only(layout: str = DEFAULT_LAYOUT) -> bool:
    return bool(_layout(layout).get("video_only"))


def headings(layout: str = DEFAULT_LAYOUT) -> tuple[str, ...]:
    return tuple(str(item) for item in _layout(layout)["headings"])


@lru_cache(maxsize=1)
def _patterns() -> dict[str, re.Pattern[str]]:
    return {key: re.compile(str(value)) for key, value in _data()["patterns"].items()}


def reset() -> None:
    _patterns.cache_clear()


def clip_seconds(value: Any) -> float:
    """A usable clip length in seconds, or ``0`` when none was given or it is out of range."""
    try:
        seconds = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    limits = _data()["limits"]
    return seconds if float(limits["duration_min"]) <= seconds <= float(limits["duration_max"]) else 0.0


def _seconds_text(seconds: float) -> str:
    return f"{round(seconds, 2):g}"


def _duration_rule(duration: Any) -> str:
    data = _data()
    seconds = clip_seconds(duration)
    return (str(data["duration_known"]).format(seconds=_seconds_text(seconds)) if seconds
            else str(data["duration_unknown"]))


def guide(duration: Any = 0, layout: str = DEFAULT_LAYOUT, medium: str = "video") -> str:
    """What the text model is told: the sections, what goes in each, and the hard rules."""
    chosen = _layout(layout)
    values = {"headings": "\n".join(headings(layout)), "duration_rule": _duration_rule(duration)}
    if "script_rule_video" in chosen:
        key = "script_rule_image" if medium == "image" else "script_rule_video"
        values["script_rule"] = str(chosen[key]).format(duration_rule=values["duration_rule"])
    return str(chosen["guide"]).format(**values)


def _section(text: str, layout: str, index: int) -> tuple[int, int]:
    """Where section ``index`` starts and ends in ``text``; ``(-1, -1)`` when its heading is absent."""
    titles = headings(layout)
    start = text.find(titles[index])
    if start < 0:
        return -1, -1
    ends = [text.find(title, start + 1) for title in titles[index + 1:]]
    ends = [end for end in ends if end > start]
    return start, (min(ends) if ends else len(text))


def spans(text: str, layout: str = DEFAULT_LAYOUT) -> list[tuple[float, float]]:
    """The timed segments of the script section, in the order they are written."""
    start, end = _section(text, layout, int(_layout(layout)["script_heading_index"]))
    script = text if start < 0 else text[start:end]
    return [(float(a), float(b)) for a, b in _patterns()["span"].findall(script)]


def _leftover(text: str, layout: str) -> list[str]:
    """Emotion names and unmeasured adverbs a performance rewrite was told to replace and did not."""
    rules = _layout(layout).get("leftover")
    if not rules:
        return []
    says = _data()["checks"]
    body = text
    # The ground rules name what to avoid, and spoken lines are the script's own words: neither is acting text.
    for index in sorted((int(i) for i in rules.get("skip_headings", [])), reverse=True):
        start, end = _section(body, layout, index)
        if start >= 0:
            body = body[:start] + body[end:]
    body = _QUOTED.sub("", body)
    cap = int(_data()["limits"]["problems"])
    found: list[str] = []
    for key in ("emotion_words", "vague_words"):
        words = [str(word) for word in rules[key] if str(word) in body][:cap]
        if words:
            found.append(str(says[key]).format(words=str(says["joiner"]).join(words)))
    return found


def check(text: str, duration: Any = 0, note: str = "", layout: str = DEFAULT_LAYOUT, medium: str = "video") -> dict[str, Any]:
    """Whether the rewritten prompt keeps its layout: ``{ok, problems, summary, total_s, segments}``.

    A partial output the creator asked for (only the shot script, a short version) is not held to the
    headings; its timed segments are still checked. A picture has no timeline to check.
    """
    data = _data()
    says = data["checks"]
    chosen = _layout(layout)
    text = str(text or "")
    problems: list[str] = []
    titles = headings(layout)
    partial = bool(_patterns()["partial_note"].search(str(note or "")))
    if not partial:
        places = [text.find(title) for title in titles]
        missing = [title for title, place in zip(titles, places) if place < 0]
        if missing:
            problems.append(str(says["missing"]).format(names=str(says["joiner"]).join(missing)))
        found = [(place, title) for place, title in zip(places, titles) if place >= 0]
        for (place, title), (later, _next) in zip(found, found[1:]):
            if later < place:
                problems.append(str(says["order"]).format(name=title))
                break

    timed = medium != "image"
    tolerance = float(data["limits"]["tolerance_s"])
    segments = spans(text, layout) if timed else []
    total = 0.0
    if timed and not segments:
        problems.append(str(says["no_spans"]).format(heading=titles[int(chosen["script_heading_index"])]))
    elif timed:
        if segments[0][0] > tolerance:
            problems.append(str(says["start"]).format(start=_seconds_text(segments[0][0])))
        shortest = float(chosen.get("segment_min_s") or 0)
        previous = segments[0][0]
        for start, end in segments:
            if end <= start:
                problems.append(str(says["backwards"]).format(start=_seconds_text(start), end=_seconds_text(end)))
            elif start - previous > tolerance:
                problems.append(str(says["gap"]).format(previous=_seconds_text(previous), start=_seconds_text(start)))
            elif previous - start > tolerance:
                problems.append(str(says["overlap"]).format(previous=_seconds_text(previous), start=_seconds_text(start)))
            elif shortest and end - start < shortest - tolerance:
                problems.append(str(says["short_segment"]).format(
                    start=_seconds_text(start), end=_seconds_text(end), length=_seconds_text(end - start),
                ))
            previous = max(previous, end)
        total = previous
        seconds = clip_seconds(duration)
        if seconds and abs(total - seconds) > tolerance:
            problems.append(str(says["total"]).format(
                total=_seconds_text(total), seconds=_seconds_text(seconds), diff=_seconds_text(abs(total - seconds)),
            ))
    problems.extend(_leftover(text, layout))
    problems = problems[: int(data["limits"]["problems"])]
    summary = ""
    if not problems:
        count = str(says["numerals"][len(titles)]) if len(titles) < len(says["numerals"]) else str(len(titles))
        if not timed:
            summary = str(says["ok_untimed"]).format(count=count)
        elif partial:
            summary = str(says["ok_partial"]).format(total=_seconds_text(total))
        else:
            key = "ok_sections" if clip_seconds(duration) else "ok_sections_no_duration"
            summary = str(says[key]).format(count=count, total=_seconds_text(total))
    return {"ok": not problems, "problems": problems, "summary": summary, "total_s": round(total, 2), "segments": len(segments)}


def video_only_error(layout: str = DEFAULT_LAYOUT) -> str:
    return str(_data()["errors"]["video_only"]).format(label=label(layout))


__all__ = [
    "DEFAULT_LAYOUT", "check", "clip_seconds", "guide", "headings", "label", "layouts", "reset", "spans", "video_only",
    "video_only_error",
]
