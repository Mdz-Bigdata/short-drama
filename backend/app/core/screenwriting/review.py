# -*- coding: utf-8 -*-
"""Review of written episodes: who confirmed what, and which episodes are still violating drafts.

An episode the engine wrote is "pending" until a person confirms it. Confirmation
binds to the plan's fingerprint, so an edit after it puts the episode back to
"changed" without anyone having to remember. An episode whose plan still breaks a
content rule is a quarantined draft: it is kept and shown, but cannot be confirmed
until it is repaired — by the model, with the reasons fed back, or by hand.

The gate on the stages after the script is soft: production may start, but the
pending and draft episodes are named in the stage record so nobody is surprised.
Nothing here calls a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

REVIEWS_KEY = "reviews"
DRAFT_KEY = "draft"
GATE_KEY = "2_review_gate"

STATUS_MISSING = "missing"
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_CHANGED = "changed"
STATUS_CONFIRMED = "confirmed"

STATUS_LABEL = {
    STATUS_MISSING: "未写出",
    STATUS_DRAFT: "违约草稿",
    STATUS_PENDING: "待审核",
    STATUS_CHANGED: "改动后待复审",
    STATUS_CONFIRMED: "已确认",
}


class ReviewError(ValueError):
    """The review action makes no sense for this episode right now."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry(state: Mapping[str, Any], episode: int) -> Mapping[str, Any] | None:
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    entry = episodes.get(str(int(episode)))
    return entry if isinstance(entry, Mapping) else None


def _record(state: Mapping[str, Any], episode: int) -> Mapping[str, Any] | None:
    reviews = state.get(REVIEWS_KEY) if isinstance(state.get(REVIEWS_KEY), Mapping) else {}
    record = reviews.get(str(int(episode)))
    return record if isinstance(record, Mapping) else None


def draft_of(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The quarantine note on a written episode: why it is still a draft, and how many tries it took."""
    draft = entry.get(DRAFT_KEY) if isinstance(entry, Mapping) else None
    return dict(draft) if isinstance(draft, Mapping) and draft.get("reasons") else None


def quarantine(reasons: list[str], *, origin: str, attempts: int = 0) -> dict[str, Any]:
    return {"reasons": [str(r) for r in reasons if str(r).strip()], "origin": origin, "attempts": int(attempts), "quarantined_at": _now()}


def status_of(state: Mapping[str, Any], episode: int) -> dict[str, Any]:
    """Where one episode stands: missing / draft / pending / changed / confirmed, with the confirmation it has."""
    entry = _entry(state, episode)
    record = _record(state, episode)
    base = {
        "episode": int(episode),
        "confirmed_revision": str(record.get("revision") or "") if record else None,
        "confirmed_at": record.get("confirmed_at") if record else None,
        "confirmed_by": record.get("by") if record else None,
        "draft": None,
    }
    if entry is None:
        return {**base, "status": STATUS_MISSING}
    draft = draft_of(entry)
    if draft:
        return {**base, "status": STATUS_DRAFT, "draft": draft}
    if record is None:
        return {**base, "status": STATUS_PENDING}
    current = str(entry.get("plan_revision") or "")
    return {**base, "status": STATUS_CONFIRMED if current and current == base["confirmed_revision"] else STATUS_CHANGED}


def confirm(state: Mapping[str, Any], episode: int, *, by: str | None = None) -> dict[str, Any]:
    """Accept the episode as it is now; a draft with open violations must be repaired first."""
    new = deepcopy(dict(state))
    entry = _entry(new, episode)
    if entry is None:
        raise ReviewError(f"第 {episode} 集尚未写出，无法确认")
    draft = draft_of(entry)
    if draft:
        raise ReviewError(f"第 {episode} 集仍是带违约的草稿（{'；'.join(draft['reasons'][:3])}），先修复再确认")
    new.setdefault(REVIEWS_KEY, {})[str(int(episode))] = {
        "revision": str(entry.get("plan_revision") or ""),
        "confirmed_at": _now(),
        "by": by or None,
    }
    return new


def reopen(state: Mapping[str, Any], episode: int) -> dict[str, Any]:
    new = deepcopy(dict(state))
    reviews = new.get(REVIEWS_KEY) if isinstance(new.get(REVIEWS_KEY), dict) else {}
    if str(int(episode)) not in reviews:
        raise ReviewError(f"第 {episode} 集没有确认记录")
    reviews.pop(str(int(episode)), None)
    return new


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    """Episode numbers by status, in ledger order, plus the one-line gate message (empty when all confirmed)."""
    numbers = sorted(
        int(entry.get("episode") or 0) for entry in (state.get("ledger") or []) if isinstance(entry, Mapping) and int(entry.get("episode") or 0) > 0
    )
    if not numbers:
        episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
        numbers = sorted(int(key) for key in episodes if str(key).isdigit())
    buckets: dict[str, list[int]] = {STATUS_CONFIRMED: [], STATUS_PENDING: [], STATUS_CHANGED: [], STATUS_DRAFT: [], STATUS_MISSING: []}
    for number in numbers:
        buckets[status_of(state, number)["status"]].append(number)
    return {
        "total": len(numbers),
        "confirmed": buckets[STATUS_CONFIRMED],
        "pending": buckets[STATUS_PENDING],
        "changed": buckets[STATUS_CHANGED],
        "drafts": buckets[STATUS_DRAFT],
        "missing": buckets[STATUS_MISSING],
        "all_confirmed": bool(numbers) and len(buckets[STATUS_CONFIRMED]) == len(numbers),
        "message": gate_message(buckets),
    }


def _join(numbers: list[int]) -> str:
    return "、".join(str(n) for n in numbers)


def gate_message(buckets: Mapping[str, list[int]]) -> str:
    parts = []
    if buckets.get(STATUS_DRAFT):
        parts.append(f"第 {_join(buckets[STATUS_DRAFT])} 集仍是带违约的草稿")
    if buckets.get(STATUS_CHANGED):
        parts.append(f"第 {_join(buckets[STATUS_CHANGED])} 集在确认后改过，待复审")
    if buckets.get(STATUS_PENDING):
        parts.append(f"第 {_join(buckets[STATUS_PENDING])} 集尚未审核确认")
    return "；".join(parts)


def gate_record(state: Mapping[str, Any], *, stage: int) -> dict[str, Any]:
    """What the soft gate saw when a later stage started: kept on the task so the warning has a home."""
    view = summary(state)
    return {
        "stage": int(stage),
        "checked_at": _now(),
        "soft": True,
        "passed": view["all_confirmed"],
        "message": view["message"],
        "pending": view["pending"],
        "changed": view["changed"],
        "drafts": view["drafts"],
    }


def renumber(state: dict[str, Any], mapping: Mapping[int, int]) -> None:
    """Carry confirmation records across a ledger renumbering; records of dropped episodes go."""
    reviews = state.get(REVIEWS_KEY) if isinstance(state.get(REVIEWS_KEY), Mapping) else {}
    state[REVIEWS_KEY] = {
        str(mapping[int(key)]): dict(record)
        for key, record in reviews.items()
        if str(key).isdigit() and int(key) in mapping and isinstance(record, Mapping)
    }


__all__ = [
    "DRAFT_KEY", "GATE_KEY", "REVIEWS_KEY", "STATUS_CHANGED", "STATUS_CONFIRMED", "STATUS_DRAFT", "STATUS_LABEL",
    "STATUS_MISSING", "STATUS_PENDING", "ReviewError",
    "confirm", "draft_of", "gate_message", "gate_record", "quarantine", "renumber", "reopen", "status_of", "summary",
]
