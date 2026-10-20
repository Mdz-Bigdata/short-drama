# -*- coding: utf-8 -*-
"""Operations on the episode ledger: the person's hand on how the source is cut.

The ledger is the one record of what an episode is. These operations change it
directly — splitting an episode at a point, moving the boundary between two,
merging neighbours, cutting a piece of unsplit source, creating or moving or
deleting an episode — and renumber everything that follows. A candidate replan
is the exception: it is written beside the ledger, compared, and only replaces
the cut episodes once adopted.

Every operation says which written episodes it would throw away, so the caller
can ask before anything expensive is lost. Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.screenwriting import review
from app.core.screenwriting.text_metrics import count_reading_units

CANDIDATE_KEY = "replan_candidate"
_SCENE_PREFIX = re.compile(r"^E(\d+)(S\d+.*)$")


class LedgerOperationError(ValueError):
    """The operation names an episode or a position that makes no sense for this ledger."""


@dataclass
class LedgerChange:
    """What an operation did: the new state, the episodes whose written work it discarded, notes for the person."""

    state: dict[str, Any]
    discarded: list[int] = field(default_factory=list)
    created: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    renumbered: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------- reading


def _entries(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in (state.get("ledger") or []) if isinstance(entry, Mapping)]


def _origin(entry: Mapping[str, Any]) -> str:
    origin = str(entry.get("source_origin") or "")
    if origin in ("cut", "own", "none"):
        return origin
    return "cut" if isinstance(entry.get("source_range"), Mapping) else "none"


def _range(entry: Mapping[str, Any]) -> tuple[int, int] | None:
    span = entry.get("source_range")
    if not isinstance(span, Mapping):
        return None
    return int(span.get("start") or 0), int(span.get("end") or 0)


def _find(state: Mapping[str, Any], episode: int) -> dict[str, Any]:
    for entry in state.get("ledger") or []:
        if isinstance(entry, dict) and int(entry.get("episode") or 0) == int(episode):
            return entry
    raise LedgerOperationError(f"分集账本中没有第 {episode} 集")


def cut_entries_in_source_order(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = [entry for entry in (state.get("ledger") or []) if isinstance(entry, dict) and _origin(entry) == "cut" and _range(entry)]
    return sorted(entries, key=lambda entry: _range(entry)[0])


def unsplit_spans(state: Mapping[str, Any]) -> list[dict[str, int]]:
    """Stretches of the whole source no cut episode covers, in source order."""
    text = str(state.get("source_text") or "")
    if not text:
        return []
    spans: list[dict[str, int]] = []
    cursor = 0
    for entry in cut_entries_in_source_order(state):
        start, end = _range(entry)
        if start > cursor and text[cursor:start].strip():
            spans.append({"start": cursor, "end": start})
        cursor = max(cursor, end)
    if cursor < len(text) and text[cursor:].strip():
        spans.append({"start": cursor, "end": len(text)})
    return spans


def is_written(state: Mapping[str, Any], episode: int) -> bool:
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    entry = episodes.get(str(int(episode)))
    return isinstance(entry, Mapping) and bool((entry.get("script") or {}).get("scenes") or entry.get("prose"))


def impact(state: Mapping[str, Any], episodes: Sequence[int]) -> list[dict[str, Any]]:
    """What each episode would lose: whether it was written, how many shots, whether it has prose."""
    written = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    result = []
    for number in episodes:
        entry = written.get(str(int(number))) if isinstance(written, Mapping) else None
        script = entry.get("script") if isinstance(entry, Mapping) and isinstance(entry.get("script"), Mapping) else {}
        ledger = next((item for item in state.get("ledger") or [] if isinstance(item, Mapping) and int(item.get("episode") or 0) == int(number)), {})
        result.append({
            "episode": int(number),
            "title": str(ledger.get("title") or ""),
            "origin": _origin(ledger) if ledger else "none",
            "written": is_written(state, number),
            "scenes": len(script.get("scenes") or []),
            "has_prose": bool(entry.get("prose")) if isinstance(entry, Mapping) else False,
        })
    return result


def layout_revision(state: Mapping[str, Any]) -> str:
    """A fingerprint of the ledger's layout: numbers, origins and source spans."""
    rows = [(int(e.get("episode") or 0), _origin(e), _range(e)) for e in _entries(state)]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def source_fingerprint(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(str(state.get("source_text") or "").encode("utf-8")).hexdigest()[:16]


def describe(state: Mapping[str, Any], language: str | None = None) -> dict[str, Any]:
    """The ledger as the Episodes view shows it: each entry with its length and status, the unsplit gaps, the candidate."""
    text = str(state.get("source_text") or "")
    units_noun = "字" if (language or state.get("language") or "zh") == "zh" else "词"
    entries = []
    for entry in _entries(state):
        span = _range(entry)
        excerpt = text[span[0]:span[1]] if span and _origin(entry) == "cut" else str(entry.get("source_text") or "")
        entries.append({
            "episode": int(entry.get("episode") or 0),
            "title": str(entry.get("title") or ""),
            "hook": str(entry.get("hook") or ""),
            "origin": _origin(entry),
            "source_kind": entry.get("source_kind"),
            "source_name": entry.get("source_name"),
            "source_range": dict(span and {"start": span[0], "end": span[1]} or {}) or None,
            "units": count_reading_units(excerpt, language or state.get("language")) if excerpt else 0,
            "units_noun": units_noun,
            "opening": excerpt[:40].strip(),
            "closing": excerpt[-40:].strip(),
            "written": is_written(state, int(entry.get("episode") or 0)),
            "ledger_status": str(entry.get("ledger_status") or "planned"),
        })
    candidate = state.get(CANDIDATE_KEY) if isinstance(state.get(CANDIDATE_KEY), Mapping) else None
    return {
        "entries": entries,
        "unsplit": unsplit_spans(state),
        "source_length": len(text),
        "layout_revision": layout_revision(state),
        "candidate": compare_candidate(state) if candidate else None,
    }


# ---------------------------------------------------------------------------- renumbering


def _renumber(state: dict[str, Any], order: Sequence[int]) -> dict[int, int]:
    """Give the ledger the play order ``order`` (old numbers); every number everywhere follows."""
    mapping = {int(old): position for position, old in enumerate(order, start=1)}
    by_old = {int(entry.get("episode") or 0): entry for entry in state.get("ledger") or [] if isinstance(entry, dict)}
    state["ledger"] = []
    for old in order:
        entry = by_old[int(old)]
        entry["episode"] = mapping[int(old)]
        state["ledger"].append(entry)
    episodes = state.get("episodes") if isinstance(state.get("episodes"), dict) else {}
    renumbered: dict[str, Any] = {}
    for key, entry in episodes.items():
        old = int(key) if str(key).isdigit() else None
        if old is None or old not in mapping:
            continue
        new = mapping[old]
        if isinstance(entry, dict):
            entry["episode"] = new
            for layer in ("plan", "script"):
                block = entry.get(layer)
                if isinstance(block, dict):
                    if layer == "script":
                        block["episode"] = new
                    for scene in block.get("scenes") or []:
                        if isinstance(scene, dict):
                            scene["scene_id"] = _rewrite_scene_id(str(scene.get("scene_id") or ""), new)
            entry["needs_replan"] = [_rewrite_scene_id(str(item), new) for item in (entry.get("needs_replan") or [])]
            for violation in entry.get("violations") or []:
                if isinstance(violation, dict) and violation.get("scene_id"):
                    violation["scene_id"] = _rewrite_scene_id(str(violation["scene_id"]), new)
        renumbered[str(new)] = entry
    state["episodes"] = renumbered
    review.renumber(state, mapping)
    state["episode_count"] = len(state["ledger"])
    return mapping


def _rewrite_scene_id(scene_id: str, episode: int) -> str:
    match = _SCENE_PREFIX.match(scene_id)
    return f"E{episode}{match.group(2)}" if match else scene_id


def _drop_written(state: dict[str, Any], numbers: Sequence[int]) -> list[int]:
    dropped = []
    episodes = state.get("episodes") if isinstance(state.get("episodes"), dict) else {}
    for number in numbers:
        if is_written(state, number):
            dropped.append(int(number))
        episodes.pop(str(int(number)), None)
        try:
            _find(state, number)["ledger_status"] = "planned"
        except LedgerOperationError:
            pass
    return dropped


def _touch(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state.pop(CANDIDATE_KEY, None) if state.get(CANDIDATE_KEY) and state[CANDIDATE_KEY].get("layout_revision") != layout_revision(state) else None


def _order(state: Mapping[str, Any]) -> list[int]:
    return [int(entry.get("episode") or 0) for entry in state.get("ledger") or [] if isinstance(entry, Mapping)]


def _new_number(state: Mapping[str, Any]) -> int:
    return max(_order(state), default=0) + 1


def _entry(number: int, *, title: str, origin: str, span: tuple[int, int] | None = None, text: str | None = None, kind: str | None = None, name: str | None = None) -> dict[str, Any]:
    return {
        "episode": number, "title": title, "hook": "", "story_beats": [], "next_episode_teaser": None,
        "source_range": {"start": span[0], "end": span[1]} if span else None,
        "source_origin": origin, "source_text": text, "source_kind": kind, "source_name": name,
        "ledger_status": "planned",
    }


# ---------------------------------------------------------------------------- manual split


def split_episode(state: Mapping[str, Any], episode: int, offset: int, title: str = "") -> LedgerChange:
    """Cut one episode in two at ``offset`` (absolute in the source); the second half follows it."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    span = _range(entry) if _origin(entry) == "cut" else None
    if span is None:
        raise LedgerOperationError(f"第 {episode} 集不是从整本源文切出的，不能按位置拆分")
    text = str(new.get("source_text") or "")
    if not span[0] < offset < span[1] or not text[span[0]:offset].strip() or not text[offset:span[1]].strip():
        raise LedgerOperationError("拆分位置必须在本集原文之内，且两边都要有正文")
    discarded = _drop_written(new, [episode])
    entry["source_range"] = {"start": span[0], "end": offset}
    second = _entry(_new_number(new), title=title.strip() or f"{entry.get('title') or f'第{episode}集'}（续）", origin="cut", span=(offset, span[1]))
    new["ledger"].append(second)
    order = _order(new)
    order.remove(second["episode"])
    order.insert(order.index(int(episode)) + 1, second["episode"])
    fresh = int(second["episode"])
    mapping = _renumber(new, order)
    _touch(new)
    return LedgerChange(new, discarded=discarded, created=[mapping[fresh]], renumbered=mapping)


def move_boundary(state: Mapping[str, Any], episode: int, new_end: int) -> LedgerChange:
    """Move the boundary between ``episode`` and the next cut episode to ``new_end``."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    following = _next_cut(new, entry)
    if following is None:
        raise LedgerOperationError(f"第 {episode} 集后面没有相邻的切出集，没有可移动的边界")
    first, second = _range(entry), _range(following)
    text = str(new.get("source_text") or "")
    if not first[0] < new_end < second[1] or not text[first[0]:new_end].strip() or not text[new_end:second[1]].strip():
        raise LedgerOperationError("边界必须落在两集原文之间，且两边都要有正文")
    discarded = _drop_written(new, [episode, int(following["episode"])])
    entry["source_range"] = {"start": first[0], "end": new_end}
    following["source_range"] = {"start": new_end, "end": second[1]}
    _touch(new)
    return LedgerChange(new, discarded=discarded)


def merge_with_next(state: Mapping[str, Any], episode: int, *, include_unsplit: bool = False) -> LedgerChange:
    """Fold the next cut episode into ``episode``; unsplit text between them is pulled in only when asked."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    following = _next_cut(new, entry)
    if following is None:
        raise LedgerOperationError(f"第 {episode} 集后面没有可合并的切出集")
    first, second = _range(entry), _range(following)
    if first[1] < second[0] and not include_unsplit:
        raise LedgerOperationError("两集之间还有未切分的原文，确认一并并入后再合并")
    discarded = _drop_written(new, [episode, int(following["episode"])])
    entry["source_range"] = {"start": first[0], "end": second[1]}
    removed = int(following["episode"])
    order = [number for number in _order(new) if number != removed]
    new["ledger"] = [item for item in new["ledger"] if int(item.get("episode") or 0) != removed]
    mapping = _renumber(new, order)
    _touch(new)
    return LedgerChange(new, discarded=discarded, renumbered=mapping)


def cut_unsplit(state: Mapping[str, Any], start: int, end: int, title: str = "") -> LedgerChange:
    """Make a cut episode out of part of an unsplit stretch of the source."""
    new = deepcopy(dict(state))
    text = str(new.get("source_text") or "")
    span = next((item for item in unsplit_spans(new) if item["start"] <= start < end <= item["end"]), None)
    if span is None or not text[start:end].strip():
        raise LedgerOperationError("只能从尚未切分的原文里切出新集")
    created = _entry(_new_number(new), title=title.strip() or f"第{len(_order(new)) + 1}集", origin="cut", span=(start, end))
    new["ledger"].append(created)
    # It takes its place among the cut episodes by source order.
    preceding = [e for e in cut_entries_in_source_order(new) if _range(e)[1] <= start]
    order = [number for number in _order(new) if number != created["episode"]]
    position = order.index(int(preceding[-1]["episode"])) + 1 if preceding else 0
    order.insert(position, created["episode"])
    fresh = int(created["episode"])
    mapping = _renumber(new, order)
    _touch(new)
    return LedgerChange(new, created=[mapping[fresh]], renumbered=mapping)


def clear_after(state: Mapping[str, Any], episode: int) -> LedgerChange:
    """Return every cut episode after ``episode`` (in source order) to unsplit source; other episodes stay."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    if _origin(entry) != "cut":
        raise LedgerOperationError(f"第 {episode} 集不是切出集")
    end = _range(entry)[1]
    removed = [int(e["episode"]) for e in cut_entries_in_source_order(new) if _range(e)[0] >= end]
    discarded = _drop_written(new, removed)
    new["ledger"] = [item for item in new["ledger"] if int(item.get("episode") or 0) not in removed]
    mapping = _renumber(new, _order(new))
    _touch(new)
    return LedgerChange(new, discarded=discarded, renumbered=mapping, notes=[f"已清除第 {episode} 集之后的 {len(removed)} 个切出集"] if removed else [])


# ---------------------------------------------------------------------------- episodes of their own


def create_episode(state: Mapping[str, Any], *, title: str, text: str = "", source_kind: str | None = None, after: int | None = None) -> LedgerChange:
    """A new episode with its own text (``own``) or none; placed after ``after`` (0 first, None last)."""
    new = deepcopy(dict(state))
    clean = str(text or "").strip()
    if clean and source_kind not in ("novel", "screenplay", None):
        raise LedgerOperationError("逐集原文的体裁只能是 novel 或 screenplay")
    created = _entry(
        _new_number(new), title=title.strip() or f"第{len(_order(new)) + 1}集",
        origin="own" if clean else "none", text=clean or None, kind=(source_kind or "novel") if clean else None,
    )
    new["ledger"].append(created)
    order = [number for number in _order(new) if number != created["episode"]]
    if after is None:
        order.append(created["episode"])
    elif int(after) == 0:
        order.insert(0, created["episode"])
    else:
        if int(after) not in order:
            raise LedgerOperationError(f"分集账本中没有第 {after} 集")
        order.insert(order.index(int(after)) + 1, created["episode"])
    fresh = int(created["episode"])
    mapping = _renumber(new, order)
    _touch(new)
    return LedgerChange(new, created=[mapping[fresh]], renumbered=mapping)


def move_episode(state: Mapping[str, Any], episode: int, *, after: int | None) -> LedgerChange:
    """Put ``episode`` after ``after`` (0 first, None last); a cut episode must keep its place in source order."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    order = [number for number in _order(new) if number != int(episode)]
    if after is None:
        order.append(int(episode))
    elif int(after) == 0:
        order.insert(0, int(episode))
    else:
        if int(after) not in order:
            raise LedgerOperationError(f"分集账本中没有第 {after} 集")
        order.insert(order.index(int(after)) + 1, int(episode))
    if _origin(entry) == "cut":
        by_number = {int(e["episode"]): e for e in new["ledger"]}
        cuts_in_play = [n for n in order if _origin(by_number[n]) == "cut"]
        cuts_in_source = [int(e["episode"]) for e in cut_entries_in_source_order(new)]
        if cuts_in_play != cuts_in_source:
            raise LedgerOperationError("切出的集必须保持原文顺序；要改顺序请移动边界或重新规划")
    mapping = _renumber(new, order)
    _touch(new)
    return LedgerChange(new, renumbered=mapping)


def delete_episode(state: Mapping[str, Any], episode: int) -> LedgerChange:
    """Remove an episode and everything written for it; the ones after it move up."""
    new = deepcopy(dict(state))
    _find(new, episode)
    discarded = _drop_written(new, [episode])
    new["ledger"] = [item for item in new["ledger"] if int(item.get("episode") or 0) != int(episode)]
    mapping = _renumber(new, _order(new))
    _touch(new)
    return LedgerChange(new, discarded=discarded, renumbered=mapping)


def update_own_source(state: Mapping[str, Any], episode: int, *, text: str, source_kind: str | None = None) -> LedgerChange:
    """Edit the text of an episode that brought its own; its written work is discarded."""
    new = deepcopy(dict(state))
    entry = _find(new, episode)
    if _origin(entry) != "own":
        raise LedgerOperationError(f"第 {episode} 集不是自带原文的集")
    clean = str(text or "").strip()
    if not clean:
        raise LedgerOperationError("逐集原文不能为空")
    discarded = _drop_written(new, [episode])
    entry["source_text"] = clean
    if source_kind in ("novel", "screenplay"):
        entry["source_kind"] = source_kind
    _touch(new)
    return LedgerChange(new, discarded=discarded)


def _next_cut(state: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any] | None:
    if _origin(entry) != "cut":
        return None
    cuts = cut_entries_in_source_order(state)
    for position, item in enumerate(cuts):
        if int(item.get("episode") or 0) == int(entry.get("episode") or 0):
            return cuts[position + 1] if position + 1 < len(cuts) else None
    return None


# ---------------------------------------------------------------------------- replan candidate


def replan_start(state: Mapping[str, Any], from_episode: int) -> int:
    """The source offset a replan from ``from_episode`` starts at."""
    entry = _find(state, from_episode)
    span = _range(entry) if _origin(entry) == "cut" else None
    if span is None:
        raise LedgerOperationError(f"第 {from_episode} 集不是切出集，重新规划只针对整本源文切出的集")
    return span[0]


def store_candidate(state: Mapping[str, Any], from_episode: int, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep a candidate plan beside the ledger; it binds to the layout and the source it was planned against."""
    new = deepcopy(dict(state))
    _find(new, from_episode)
    new[CANDIDATE_KEY] = {
        "from_episode": int(from_episode),
        "entries": [deepcopy(dict(entry)) for entry in entries],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "layout_revision": layout_revision(new),
        "source_fingerprint": source_fingerprint(new),
    }
    return new


def compare_candidate(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Old cut episodes from the replan point against the candidate's: boundaries, counts, what each new one covers."""
    candidate = state.get(CANDIDATE_KEY)
    if not isinstance(candidate, Mapping):
        return None
    start = replan_start(state, int(candidate["from_episode"]))
    text = str(state.get("source_text") or "")
    old = [e for e in cut_entries_in_source_order(state) if _range(e)[0] >= start]
    new_entries = [dict(e) for e in candidate.get("entries") or []]
    old_spans = [(int(e["episode"]), _range(e)) for e in old]
    rows = []
    for position, entry in enumerate(new_entries, start=1):
        span = _range(entry)
        same = next((number for number, old_span in old_spans if old_span == span), None)
        overlapping = [number for number, old_span in old_spans if old_span and span and old_span[0] < span[1] and span[0] < old_span[1]]
        rows.append({
            "position": position, "title": str(entry.get("title") or ""), "hook": str(entry.get("hook") or ""),
            "source_range": {"start": span[0], "end": span[1]} if span else None,
            "units": count_reading_units(text[span[0]:span[1]], state.get("language")) if span else 0,
            "relation": "same" if same else ("overlaps" if overlapping else "new"),
            "overlaps": overlapping,
        })
    old_units = [count_reading_units(text[s[0]:s[1]], state.get("language")) for _, s in old_spans if s]
    new_units = [row["units"] for row in rows]
    return {
        "from_episode": int(candidate["from_episode"]),
        "created_at": candidate.get("created_at"),
        "adoptable": candidate.get("layout_revision") == layout_revision(state) and candidate.get("source_fingerprint") == source_fingerprint(state),
        "old_count": len(old_spans),
        "new_count": len(rows),
        "old_average_units": round(sum(old_units) / len(old_units)) if old_units else 0,
        "new_average_units": round(sum(new_units) / len(new_units)) if new_units else 0,
        "replaced_written": [number for number, _ in old_spans if is_written(state, number)],
        "entries": rows,
    }


def adopt_candidate(state: Mapping[str, Any], *, delete_replaced: bool = False) -> LedgerChange:
    """Replace the cut episodes from the replan point with the candidate's.

    Replaced episodes that were written are kept at the end without a source (their
    work stays until they are deleted) unless ``delete_replaced``; unwritten ones go.
    Episodes with their own text or none that sat after the replan point follow the
    new cut episodes in their old order.
    """
    candidate = state.get(CANDIDATE_KEY)
    if not isinstance(candidate, Mapping):
        raise LedgerOperationError("没有待采纳的重新规划")
    comparison = compare_candidate(state)
    if not comparison or not comparison["adoptable"]:
        raise LedgerOperationError("源文或分集账本在规划之后变过，这份候选已不能采纳，请重新规划")
    new = deepcopy(dict(state))
    start = replan_start(new, int(candidate["from_episode"]))
    replaced = [int(e["episode"]) for e in cut_entries_in_source_order(new) if _range(e)[0] >= start]
    order = _order(new)
    insert_at = order.index(replaced[0]) if replaced else len(order)
    kept_written: list[int] = []
    for number in replaced:
        entry = _find(new, number)
        if is_written(new, number) and not delete_replaced:
            entry["source_origin"] = "none"
            entry["source_range"] = None
            entry["ledger_status"] = "stale"
            kept_written.append(number)
        else:
            _drop_written(new, [number])
    discarded = [n for n in replaced if n not in kept_written and is_written(state, n)]
    new["ledger"] = [item for item in new["ledger"] if int(item.get("episode") or 0) not in replaced or int(item.get("episode") or 0) in kept_written]
    created: list[int] = []
    for entry in candidate.get("entries") or []:
        fresh = _entry(_new_number(new), title=str(entry.get("title") or ""), origin="cut", span=_range(entry))
        fresh["hook"] = str(entry.get("hook") or "")
        fresh["story_beats"] = list(entry.get("story_beats") or [])
        fresh["next_episode_teaser"] = entry.get("next_episode_teaser")
        new["ledger"].append(fresh)
        created.append(fresh["episode"])
    remaining = [n for n in order if n not in replaced]
    trailing = [n for n in remaining[insert_at:]]
    play_order = remaining[:insert_at] + created + trailing + kept_written
    mapping = _renumber(new, play_order)
    new.pop(CANDIDATE_KEY, None)
    _touch(new)
    notes = []
    if kept_written:
        notes.append(f"{len(kept_written)} 个已写出的旧集保留在末尾（无原文、已过期），可随时删除")
    return LedgerChange(new, discarded=discarded, created=[mapping[n] for n in created], renumbered=mapping, notes=notes)


def discard_candidate(state: Mapping[str, Any]) -> dict[str, Any]:
    new = deepcopy(dict(state))
    new.pop(CANDIDATE_KEY, None)
    return new


__all__ = [
    "CANDIDATE_KEY", "LedgerChange", "LedgerOperationError",
    "adopt_candidate", "clear_after", "compare_candidate", "create_episode", "cut_entries_in_source_order", "cut_unsplit",
    "delete_episode", "describe", "discard_candidate", "impact", "is_written", "layout_revision", "merge_with_next",
    "move_boundary", "move_episode", "replan_start", "source_fingerprint", "split_episode", "store_candidate",
    "unsplit_spans", "update_own_source",
]
