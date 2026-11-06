"""What a customer's membership lets them use. Staff are not limited by this; what they may do is in permissions.py.

A purchase keeps a copy of its plan's entitlements, so changing a plan here never changes what someone already bought.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

UNLIMITED = -1

PLAN_ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "free": {"project.max": 2, "video.max_resolution": "768p", "mcp.access": False, "export.jianying": False},
    "starter": {"project.max": 10, "video.max_resolution": "768p", "mcp.access": False, "export.jianying": True},
    "studio": {"project.max": 50, "video.max_resolution": "2k", "mcp.access": True, "export.jianying": True},
    "pro": {"project.max": UNLIMITED, "video.max_resolution": "2k", "mcp.access": True, "export.jianying": True},
}
_RESOLUTION_ORDER = {"768p": 0, "2k": 1}


def plan_entitlements(plan_id: str) -> dict[str, Any]:
    return dict(PLAN_ENTITLEMENTS.get(plan_id, PLAN_ENTITLEMENTS["free"]))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def current_term(terms: Iterable[Any], now: datetime) -> Any | None:
    """The term in force: the one that started most recently among those running now."""
    running = [
        term for term in terms
        if term.status == "active" and _aware(term.starts_at) <= now < _aware(term.expires_at)
    ]
    return max(running, key=lambda term: _aware(term.starts_at), default=None)


def entitlements_from(terms: Iterable[Any], now: datetime) -> dict[str, Any]:
    term = current_term(terms, now)
    return dict(term.entitlements) if term is not None and term.entitlements else plan_entitlements("free")


def resolution_allowed(entitlements: dict[str, Any], resolution: str) -> bool:
    highest = str(entitlements.get("video.max_resolution") or "768p")
    return _RESOLUTION_ORDER.get(resolution, 99) <= _RESOLUTION_ORDER.get(highest, 0)
