# -*- coding: utf-8 -*-
"""Where several people stand in one frame, so a group shot is not a row of tourists.

Asked for "two people talking" or "three people meeting", image and video models line everyone up across the middle.
Blocking does the storytelling instead: depth (who is near the lens), height (who sits, who stands), grouping by
distance and facing (two together, one apart), a triangle of heads for three, a frame within the frame or one odd out
for four, and a character who is in the scene but out of this shot written as fully out of frame.

:func:`brief` goes to the stage-4 shot-table writer with the formulas up to the scene's head count; :func:`table_issues`
checks the drafted table and sends a lined-up shot back. Positions are the frame coordinates of
:mod:`app.core.frame_position`; wording and word lists live in ``app/data/prompt/group_blocking.json``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.core import prompt_data
from app.core.frame_position import parse_frame_positions


_WORDING_FILE = "group_blocking"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/group_blocking.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

_DATA = "group_blocking"
_CLAUSE = re.compile(r"[^；;。\n]+")


def brief(people: int) -> str:
    """The blocking formulas a scene with ``people`` named characters can use (one to four, and five or more)."""
    if people < 1:
        return ""
    formulas = prompt_data.value(_DATA, "formulas")
    lines = [prompt_data.text(_DATA, "heading")]
    lines += [formulas[str(count)] for count in range(1, min(people, len(formulas)) + 1)]
    if people >= 2:
        lines.append(prompt_data.text(_DATA, "offscreen"))
    return "\n".join(lines)


def _posture(desc: str, name: str) -> str:
    """How high this person is in the frame, from the clauses that mention them: low / high / bent / '' (standing or unsaid)."""
    words = prompt_data.value(_DATA, "posture_words")
    clauses = " ".join(clause for clause in _CLAUSE.findall(desc) if name in clause)
    for level in ("high", "low", "bent"):
        if any(word in clauses for word in words[level]):
            return level
    return ""


def _cast(shot: Mapping[str, object]) -> list[str]:
    raw = shot.get("characters")
    names = raw if isinstance(raw, list) else re.split(r"[、，,/\s]+", str(raw or ""))
    return [str(name).strip() for name in names if str(name).strip() and str(name).strip() not in {_text_of("_cast.text"), _text_of("_cast.text.2")}]


def shot_issue(desc: str, cast: Sequence[str]) -> tuple[str, str] | None:
    """(rule, detail) when a shot lines its people up, else None."""
    if len(cast) < 2:
        return None
    positions = [p for p in parse_frame_positions(desc, list(cast)) if p.depth]
    if len(positions) < len(cast):
        return None  # 没全写深度层：交给「构图未用镜头坐标」那条
    depths = {p.depth for p in positions}
    heights = {_posture(desc, p.subject) for p in positions}
    if len(depths) > 1 or len(heights) > 1:
        return None
    if any(term in desc for term in prompt_data.words(_DATA, "together_terms")):
        return None
    issues = prompt_data.value(_DATA, "issues")
    names = "、".join(p.subject for p in positions)
    if len(cast) >= 3:
        spec = issues["line_up"]
        return spec["rule"], spec["detail"].replace("{names}", names).replace("{depth}", positions[0].depth)
    facing_camera = prompt_data.words(_DATA, "camera_facing")
    clauses = {p.subject: " ".join(c for c in _CLAUSE.findall(desc) if p.subject in c) for p in positions}
    if all(any(word in clauses[name] or word in p.facing for word in facing_camera) for name, p in zip(clauses, positions)):
        spec = issues["tourist"]
        return spec["rule"], spec["detail"].replace("{names}", names)
    return None


def table_issues(shots: Sequence[Mapping[str, object]]) -> list[str]:
    """A drafted shot table, one line per lined-up shot, for the revision round."""
    template = prompt_data.text(_DATA, "table_issue")
    lines = []
    for index, shot in enumerate(shots, start=1):
        found = shot_issue(str(shot.get("desc") or ""), _cast(shot))
        if found:
            lines.append(template.format(shot=shot.get("shot_id", index), rule=found[0], detail=found[1]))
    return lines


__all__ = ["brief", "shot_issue", "table_issues"]
