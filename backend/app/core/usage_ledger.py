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
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
from functools import partial, wraps
from typing import Any, Callable, Iterator, Mapping

from app.core.providers.pricing import pricing_table

logger = logging.getLogger("app.core.usage_ledger")

MEDIA_TYPES = ("text", "image", "video", "audio")
STATUSES = ("success", "failed")
# A project keeps this many records; older ones fall off the end.
MAX_RECORDS_PER_TASK = 5000

_current_task: ContextVar[str | None] = ContextVar("usage_task", default=None)
_current_purpose: ContextVar[str | None] = ContextVar("usage_purpose", default=None)
_current_user: ContextVar[str | None] = ContextVar("usage_user", default=None)

Sink = Callable[[str, dict[str, Any]], None]
_sink: Sink | None = None
_sink_lock = threading.Lock()
# Calls made outside any project (model discovery, standalone endpoints) are kept in memory.
unattributed: deque[dict[str, Any]] = deque(maxlen=500)


BillingSink = Callable[[dict[str, Any]], None]
_billing_sink: BillingSink | None = None
# Something with ``reserve`` and ``settle``, while charging is on: see app.platform.billing_book.
_billing_guard: Any = None


def configure_billing_guard(guard: Any) -> None:
    global _billing_guard
    _billing_guard = guard


def current_user_id() -> str | None:
    return _current_user.get()


def configure_billing_sink(sink: BillingSink | None) -> None:
    """Install the function that keeps every record for billing, whichever project it belongs to, or none."""
    global _billing_sink
    with _sink_lock:
        _billing_sink = sink


def bind_user(user_id: str | None) -> None:
    """Who is asking, for the rest of this request and anything it starts with its context."""
    _current_user.set(user_id)


def carrying_context(work: Callable[..., Any]) -> Callable[..., Any]:
    """``work`` with the caller's project and user: a new thread starts with neither, so its calls would belong to nobody."""
    return partial(copy_context().run, work)


def metered(media_type: str, *, provider: str, describe: Callable[..., tuple[str, Mapping[str, Any]]]):
    """Record a provider client's paid method; ``describe`` turns its arguments into (model, units)."""

    def decorate(method):
        @wraps(method)
        def call(*args, **kwargs):
            model, units = describe(*args, **kwargs)
            with timed_call(media_type, provider=provider, model=model, units=units):
                return method(*args, **kwargs)

        return call

    return decorate


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
    billing_mode: str | None = None,
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
    with _sink_lock:
        billing_sink = _billing_sink
    if billing_sink is not None:
        try:
            billing_sink({**entry, "task_id": task_id, "user_id": _current_user.get(), "billing_mode": billing_mode})
        except Exception as exc:  # noqa: BLE001 - same: the call already happened
            logger.error("[Usage] 计费记录写入失败 usage=%s: %s", entry["id"], type(exc).__name__)
    return entry


@contextmanager
def timed_call(
    media_type: str, *, provider: str, model: str, units: Mapping[str, Any] | None = None, purpose: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Record a call around a block: success unless the block raises or sets ``outcome["failed"]``.

    The block may add to ``outcome["units"]`` (tokens read from the response) and set
    ``outcome["error"]``.
    """
    guard = _billing_guard
    # With charging on, this is where a call that cannot be paid for stops: it raises and the provider is never reached.
    handle = guard.reserve(
        media_type=media_type, provider=provider, model=model, units=dict(units or {}),
        task_id=_current_task.get(), user_id=_current_user.get(),
    ) if guard is not None else None
    started = time.monotonic()
    outcome: dict[str, Any] = {"units": dict(units or {}), "failed": False, "error": None}
    try:
        yield outcome
    except BaseException as exc:  # a cancelled call holds nothing either
        outcome["failed"] = True
        outcome["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        entry = record(
            media_type, provider=provider, model=model,
            status="failed" if outcome["failed"] else "success",
            units=outcome["units"], error=outcome.get("error"),
            duration_ms=int((time.monotonic() - started) * 1000), purpose=purpose,
            billing_mode=handle.mode if handle is not None else None,
        )
        if handle is not None:
            try:
                guard.settle(handle, entry)
            except Exception as exc:  # noqa: BLE001 - the call happened; the reconciliation will show this
                logger.error("[Usage] 结算失败 usage=%s: %s", entry["id"], type(exc).__name__)


def append_to_task(task: dict[str, Any], entry: Mapping[str, Any]) -> None:
    """The default sink's mutation: keep the project's newest records, bounded."""
    records = task.get("usage_records")
    if not isinstance(records, list):
        records = []
    records.append(dict(entry))
    if len(records) > MAX_RECORDS_PER_TASK:
        del records[: len(records) - MAX_RECORDS_PER_TASK]
    task["usage_records"] = records


def _count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def summarize(records: list[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Totals a project page can show: calls, failures, cost per currency, and what could not be priced."""
    items = [item for item in (records or []) if isinstance(item, Mapping)]
    cost_by_currency: dict[str, float] = {}
    by_media: dict[str, dict[str, Any]] = {}
    by_purpose: dict[str, dict[str, Any]] = {}
    unpriced_calls = 0
    unpriced_models: set[str] = set()
    failed = 0
    tokens = {
        "input": 0, "output": 0, "reasoning": 0, "cached_input": 0,
        "reused_calls": 0, "reused_saved": 0, "system_chars_saved": 0,
    }
    for item in items:
        units = item.get("units") if isinstance(item.get("units"), Mapping) else {}
        tokens["input"] += _count(units.get("input_tokens"))
        tokens["output"] += _count(units.get("output_tokens"))
        tokens["reasoning"] += _count(units.get("reasoning_tokens"))
        tokens["cached_input"] += _count(units.get("cached_tokens"))
        tokens["system_chars_saved"] += _count(units.get("system_chars_saved"))
        if units.get("reused"):
            # A question not asked: nothing was spent, so it is neither a provider call nor an unpriced one.
            tokens["reused_calls"] += 1
            tokens["reused_saved"] += _count(units.get("saved_tokens"))
            continue
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
    calls = len(items) - tokens["reused_calls"]
    return {
        "calls": calls,
        "succeeded": calls - failed,
        "tokens": tokens,
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
