"""Live usage figures: what was called, how many tokens it took, what it cost and what it is quoted at.

Built from the ``usage_charges`` rows of a time window. A row carries the reference (official) cost of
one call; the quote is that cost plus the markup (``app.core.quote``). Everything is shown in yuan: a cost
recorded in dollars is converted at the project's one rate (``quote.in_cny``). A currency with no rate
keeps its own name and is never added to another. Pure: the caller fetches the rows and names the clock.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from app.core import quote

TOKEN_UNITS = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")
OTHER_UNITS = ("images", "seconds", "characters")
#: Windows up to these lengths are drawn by the minute, by the hour, and past that by the day.
MINUTE_BUCKETS_UP_TO = timedelta(hours=3)
HOUR_BUCKETS_UP_TO = timedelta(days=4)
RECENT = 30
_STEP = Decimal("0.000001")
TOP_USERS = 20
TOP_TASKS = 20


def _units(charge: Any) -> dict[str, float]:
    units = charge.units if isinstance(charge.units, dict) else {}
    return {key: float(value) for key, value in units.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}


def _blank() -> dict[str, Any]:
    return {
        "calls": 0, "failed": 0, "unpriced_calls": 0,
        **{key: 0.0 for key in (*TOKEN_UNITS, *OTHER_UNITS)},
        "cost": defaultdict(Decimal), "quote": defaultdict(Decimal),
    }


def _add(group: dict[str, Any], charge: Any) -> None:
    group["calls"] += 1
    ok = charge.status == "success"
    group["failed"] += not ok
    if not ok:
        # A call that failed is counted as a call and nothing more: what it asked for was never delivered or billed.
        return
    units = _units(charge)
    for key in (*TOKEN_UNITS, *OTHER_UNITS):
        group[key] += units.get(key, 0.0)
    if charge.reference_cost is None or not charge.reference_currency:
        group["unpriced_calls"] += 1
        return
    cost, currency = quote.in_cny(charge.reference_cost, charge.reference_currency)
    group["cost"][currency] += cost
    group["quote"][currency] += quote.quoted(cost)


def _out(group: dict[str, Any]) -> dict[str, Any]:
    money = lambda amounts: {currency: float(amount.quantize(_STEP)) for currency, amount in sorted(amounts.items())}  # noqa: E731
    return {
        **{key: group[key] for key in ("calls", "failed", "unpriced_calls")},
        **{key: int(group[key]) for key in TOKEN_UNITS},
        "tokens": int(group["input_tokens"] + group["output_tokens"]),
        **{key: round(group[key], 3) for key in OTHER_UNITS},
        "cost": money(group["cost"]), "quote": money(group["quote"]),
    }


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def bucket_size(window: timedelta) -> timedelta:
    if window <= MINUTE_BUCKETS_UP_TO:
        return timedelta(minutes=1) if window <= timedelta(hours=1) else timedelta(minutes=5)
    return timedelta(hours=1) if window <= HOUR_BUCKETS_UP_TO else timedelta(days=1)


def usage_stats(charges: Iterable[Any], *, now: datetime, window: timedelta) -> dict[str, Any]:
    """Totals, the same by model, by user and by project, a series over the window, and the newest calls."""
    now = _aware(now)
    since = now - window
    rows = sorted((charge for charge in charges if _aware(charge.occurred_at) >= since), key=lambda charge: _aware(charge.occurred_at))
    total = _blank()
    by_model: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(_blank)
    by_user: dict[str, dict[str, Any]] = defaultdict(_blank)
    by_task: dict[tuple[str, str], dict[str, Any]] = defaultdict(_blank)
    size = bucket_size(window)
    count = max(1, int(window / size))
    start = now - size * count
    buckets = [_blank() for _ in range(count)]
    unpriced: dict[str, int] = defaultdict(int)
    for charge in rows:
        _add(total, charge)
        _add(by_model[(charge.media_type, charge.provider, charge.model)], charge)
        _add(by_user[charge.user_id or ""], charge)
        if charge.task_id:
            _add(by_task[(charge.task_id, charge.user_id or "")], charge)
        index = min(count - 1, max(0, int((_aware(charge.occurred_at) - start) / size)))
        _add(buckets[index], charge)
        if charge.status == "success" and (charge.reference_cost is None or not charge.reference_currency):
            unpriced[charge.model] += 1

    def weight(group: dict[str, Any]) -> tuple:
        return (-sum(group["cost"].values()), -group["input_tokens"] - group["output_tokens"], -group["calls"])

    recent = []
    for charge in reversed(rows[-RECENT:]):
        units = _units(charge)
        priced = charge.status == "success" and charge.reference_cost is not None and bool(charge.reference_currency)
        cost, currency = quote.in_cny(charge.reference_cost, charge.reference_currency) if priced else (Decimal(0), "")
        recent.append({
            "at": _aware(charge.occurred_at).isoformat(), "media_type": charge.media_type, "provider": charge.provider, "model": charge.model,
            "purpose": charge.purpose or "", "status": charge.status, "user_id": charge.user_id or "", "task_id": charge.task_id or "",
            "input_tokens": int(units.get("input_tokens", 0)), "output_tokens": int(units.get("output_tokens", 0)),
            "cost": float(cost.quantize(_STEP)) if priced else None,
            "quote": float(quote.quoted(cost)) if priced else None,
            "currency": currency,
        })
    return {
        "generated_at": now.isoformat(), "since": since.isoformat(), "window_minutes": int(window.total_seconds() // 60),
        "bucket_seconds": int(size.total_seconds()), "markup": float(quote.markup()),
        # The rate dollar costs were converted at, and whether this window had any: the page says so when it did.
        "usd_cny": float(quote.usd_cny()),
        "converted_from_usd": any(str(charge.reference_currency or "").upper() == "USD" and charge.status == "success" for charge in rows) and quote.usd_cny() > 0,
        "total": _out(total),
        "by_model": [
            {"media_type": key[0], "provider": key[1], "model": key[2], **_out(group)}
            for key, group in sorted(by_model.items(), key=lambda item: weight(item[1]))
        ],
        "by_user": [
            {"user_id": user_id, **_out(group)} for user_id, group in sorted(by_user.items(), key=lambda item: weight(item[1]))[:TOP_USERS]
        ],
        # One project is one job to quote: what it took so far and what that comes to.
        "by_task": [
            {"task_id": key[0], "user_id": key[1], **_out(group)} for key, group in sorted(by_task.items(), key=lambda item: weight(item[1]))[:TOP_TASKS]
        ],
        "series": [{"at": (start + size * index).isoformat(), **_out(bucket)} for index, bucket in enumerate(buckets)],
        "recent": recent,
        "unpriced_models": [{"model": model, "calls": calls} for model, calls in sorted(unpriced.items(), key=lambda item: -item[1])],
    }


__all__ = ["bucket_size", "usage_stats"]
