# -*- coding: utf-8 -*-
"""What changed between a saved version of the screenplay and the screenplay as it is now, episode by episode.

No model reads anything: both texts are split at their ``第N集`` lines and each episode's lines are
compared. The answer says which episodes changed, were added or were removed, and for a changed
episode lists the lines that went and the lines that came, so a writer can decide whether to roll back
before doing it. Limits and labels are in ``app/data/prompt/script_compare.json``.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from app.core import prompt_data

_DATA = "script_compare"


def _limit(key: str) -> int:
    return int(prompt_data.value(_DATA, "limits")[key])


def label(status: str) -> str:
    return str(prompt_data.value(_DATA, "labels")[status])


def no_version_text() -> str:
    return str(prompt_data.value(_DATA, "errors")["no_version"])


def by_episode(text: str) -> dict[int, list[str]]:
    """The screenplay's non-empty lines per episode; what comes before the first episode line is episode 0."""
    heading = re.compile(str(prompt_data.value(_DATA, "heading")))
    episodes: dict[int, list[str]] = {}
    current = 0
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        found = heading.match(line)
        if found:
            current = int(found.group(1))
        episodes.setdefault(current, []).append(line)
    return episodes


def _shown(lines: list[str]) -> list[str]:
    width, count = _limit("line_chars"), _limit("lines_per_change")
    cut = [line if len(line) <= width else line[:width] + "…" for line in lines[:count]]
    return cut + (["…"] if len(lines) > count else [])


def _title(lines: list[str]) -> str:
    return lines[0][: _limit("line_chars")] if lines else ""


def compare(old: str, new: str) -> dict[str, Any]:
    """``old`` is the saved version, ``new`` the current screenplay: per-episode status and the changed lines."""
    before, after = by_episode(old), by_episode(new)
    rows: list[dict[str, Any]] = []
    totals = {"same": 0, "changed": 0, "added": 0, "removed": 0, "lines_added": 0, "lines_removed": 0}
    for episode in sorted({*before, *after}):
        was, now = before.get(episode), after.get(episode)
        if was is None:
            status = "added"
        elif now is None:
            status = "removed"
        else:
            status = "same" if was == now else "changed"
        totals[status] += 1
        row: dict[str, Any] = {
            "episode": episode, "status": status, "label": label(status),
            "title": str(prompt_data.value(_DATA, "preface")) if episode == 0 else _title(now or was or []),
            "lines_added": 0, "lines_removed": 0, "changes": [], "more_changes": 0,
        }
        if status == "added":
            row["lines_added"] = len(now or [])
        elif status == "removed":
            row["lines_removed"] = len(was or [])
        elif status == "changed":
            blocks = [code for code in difflib.SequenceMatcher(None, was, now, autojunk=False).get_opcodes() if code[0] != "equal"]
            for _tag, i1, i2, j1, j2 in blocks:
                row["lines_removed"] += i2 - i1
                row["lines_added"] += j2 - j1
            keep = _limit("changes_per_episode")
            row["changes"] = [{"old": _shown(was[i1:i2]), "new": _shown(now[j1:j2])} for _tag, i1, i2, j1, j2 in blocks[:keep]]
            row["more_changes"] = max(0, len(blocks) - keep)
        totals["lines_added"] += row["lines_added"]
        totals["lines_removed"] += row["lines_removed"]
        rows.append(row)
    return {"identical": not (totals["changed"] or totals["added"] or totals["removed"]), "summary": totals,
            "episodes": [row for row in rows if row["status"] != "same"]}


__all__ = ["by_episode", "compare", "label", "no_version_text"]
