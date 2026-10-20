"""Every provider call, as a record the project can be billed and audited by.

A provider call is the unit of usage: one text completion, one image, one video
job, one speech synthesis. The gateway records each one here — success or
failure, with the units it consumed and the reference cost those units come to
under the declared prices. Records are attributed to the project whose stage was
running (bound with ``bind_task``), so the project can show what it has spent and
what a batch is about to cost.

Cost here is a reference figure, never a bill: unpriced models are recorded
without a cost and counted as such, and currencies are never added together.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping

from app.core.providers.pricing import pricing_table

logger = logging.getLogger("app.core.usage_ledger")

MEDIA_TYPES = ("text", "image", "video", "audio")
STATUSES = ("success", "failed")
# A project keeps this many records; older ones fall off the end.
MAX_RECORDS_PER_TASK = 5000

_current_task: ContextVar[str | None] = ContextVar("usage_task", default=None)
_current_purpose: ContextVar[str | None] = ContextVar("usage_purpose", default=None)

Sink = Callable[[str, dict[str, Any]], None]
_sink: Sink | None = None
_sink_lock = threading.Lock()
# Calls made outside any project (model discovery, standalone endpoints) are kept in memory.
unattributed: deque[dict[str, Any]] = deque(maxlen=500)


def configure_sink(sink: Sink | None) -> None:
    """Install the function that persists a record onto its project."""
    global _sink
    with _sink_lock:
        _sink = sink


@contextmanager
def bind_task(task_id: str | None, purpose: str | None = None) -> Iterator[None]:
    """Attribute every provider call made inside the block to ``task_id``."""
    task_token = _current_task.set(task_id)
    purpose_token = _current_purpose.set(purpose)
    try:
        yield
    finally:
        _current_purpose.reset(purpose_token)
        _current_task.reset(task_token)


@contextmanager
def purpose(name: str) -> Iterator[None]:
    """Name what the calls inside the block are for (``stage_5_video``, ``script_plan`` …)."""
    token = _current_purpose.set(name)
    try:
        yield
    finally:
        _current_purpose.reset(token)


def current_task_id() -> str | None:
    return _current_task.get()


def record(
    media_type: str,
    *,
    provider: str,
    model: str,
    status: str,
    units: Mapping[str, Any] | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    """Write one provider-call record and return it."""
    if media_type not in MEDIA_TYPES:
        raise ValueError(f"unknown media type: {media_type!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown call status: {status!r}")
    clean_units = {str(key): value for key, value in (units or {}).items() if value is not None}
    priced = pricing_table().cost(model, units=clean_units) if status == "success" else (0.0, "")
    entry = {
        "id": uuid.uuid4().hex,
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "media_type": media_type,
        "provider": str(provider or "unknown"),
        "model": str(model or ""),
        "purpose": purpose or _current_purpose.get() or "unspecified",
        "status": status,
        "units": clean_units,
        "cost": round(priced[0], 6) if priced else None,
        "currency": priced[1] if priced and priced[1] else None,
        "priced": bool(priced and priced[1]),
        "error": (error or "")[:300] or None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
    }
    task_id = _current_task.get()
    with _sink_lock:
        sink = _sink
    if task_id and sink is not None:
        try:
            sink(task_id, entry)
        except Exception as exc:  # noqa: BLE001 - a bookkeeping failure never fails the call it describes
            logger.warning("[Usage] 记录调用失败 task=%s: %s", task_id, type(exc).__name__)
            unattributed.append({**entry, "task_id": task_id})
    else:
        unattributed.append({**entry, "task_id": task_id})
    return entry


@contextmanager
def timed_call(
    media_type: str, *, provider: str, model: str, units: Mapping[str, Any] | None = None, purpose: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Record a call around a block: success unless the block raises or sets ``outcome["failed"]``.

    The block may add to ``outcome["units"]`` (tokens read from the response) and set
    ``outcome["error"]``.
    """
    started = time.monotonic()
    outcome: dict[str, Any] = {"units": dict(units or {}), "failed": False, "error": None}
    try:
        yield outcome
    except Exception as exc:
        outcome["failed"] = True
        outcome["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        record(
            media_type, provider=provider, model=model,
            status="failed" if outcome["failed"] else "success",
            units=outcome["units"], error=outcome.get("error"),
            duration_ms=int((time.monotonic() - started) * 1000), purpose=purpose,
        )


def append_to_task(task: dict[str, Any], entry: Mapping[str, Any]) -> None:
    """The default sink's mutation: keep the project's newest records, bounded."""
    records = task.get("usage_records")
    if not isinstance(records, list):
        records = []
    records.append(dict(entry))
    if len(records) > MAX_RECORDS_PER_TASK:
        del records[: len(records) - MAX_RECORDS_PER_TASK]
    task["usage_records"] = records


def summarize(records: list[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Totals a project page can show: calls, failures, cost per currency, and what could not be priced."""
    items = [item for item in (records or []) if isinstance(item, Mapping)]
    cost_by_currency: dict[str, float] = {}
    by_media: dict[str, dict[str, Any]] = {}
    by_purpose: dict[str, dict[str, Any]] = {}
    unpriced_calls = 0
    unpriced_models: set[str] = set()
    failed = 0
    for item in items:
        media = str(item.get("media_type") or "unknown")
        purpose_name = str(item.get("purpose") or "unspecified")
        media_bucket = by_media.setdefault(media, {"calls": 0, "failed": 0, "cost": {}})
        purpose_bucket = by_purpose.setdefault(purpose_name, {"calls": 0, "failed": 0, "cost": {}})
        media_bucket["calls"] += 1
        purpose_bucket["calls"] += 1
        if item.get("status") == "failed":
            failed += 1
            media_bucket["failed"] += 1
            purpose_bucket["failed"] += 1
            continue
        if item.get("priced") and item.get("currency"):
            currency = str(item["currency"])
            amount = float(item.get("cost") or 0.0)
            cost_by_currency[currency] = round(cost_by_currency.get(currency, 0.0) + amount, 6)
            media_bucket["cost"][currency] = round(media_bucket["cost"].get(currency, 0.0) + amount, 6)
            purpose_bucket["cost"][currency] = round(purpose_bucket["cost"].get(currency, 0.0) + amount, 6)
        else:
            unpriced_calls += 1
            if item.get("model"):
                unpriced_models.add(str(item["model"]))
    primary = max(cost_by_currency, key=lambda currency: cost_by_currency[currency]) if cost_by_currency else None
    return {
        "calls": len(items),
        "succeeded": len(items) - failed,
        "failed": failed,
        "cost_by_currency": cost_by_currency,
        "primary_currency": primary,
        "by_media_type": by_media,
        "by_purpose": by_purpose,
        "unpriced_calls": unpriced_calls,
        "unpriced_models": sorted(unpriced_models),
    }


def estimate(model: str, media_type: str, units: Mapping[str, Any]) -> dict[str, Any]:
    """What one call would cost under the declared prices; ``priced`` is false when unknown."""
    priced = pricing_table().cost(model, units=units)
    if not priced or not priced[1]:
        return {"priced": False, "cost": None, "currency": None}
    return {"priced": True, "cost": round(priced[0], 6), "currency": priced[1]}
