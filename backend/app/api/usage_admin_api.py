"""Point rates and what usage comes to: the view for deciding prices before any balance is charged."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.api.auth_api import require_permission
from app.platform.dependencies import get_platform_store
from app.platform.permissions import PRICING_MANAGE, RECON_READ
from app.platform.store import PlatformStore
from app.platform.usage_billing import RATE_KINDS, UsageSpool, usage_differences
from app.platform.usage_stats import usage_stats
from app.repository.task_repo import TaskRepository
from app.schema.platform import PointRateCreateRequest
from app.core import prompt_data, quote


_WORDING_FILE = "api_usage_admin_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_usage_admin_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

router = APIRouter(prefix="/api/admin", tags=list(_words_of("module.tags")))
_tasks = TaskRepository()
#: Records this recent may still be on their way from the spool.
_SETTLING = timedelta(minutes=5)


def read_usage_records(task_ids: set[str]) -> dict[str, list]:
    """What each project keeps of its own calls. Blocking: it reads the projects."""
    found: dict[str, list] = {}
    for task_id in task_ids:
        task = _tasks.get_task(task_id)
        if isinstance(task, dict):
            found[task_id] = list(task.get("usage_records") or [])
    return found


def _task_titles(task_ids: set[str]) -> dict[str, str]:
    """The name each project goes by. Blocking: it reads the projects."""
    found: dict[str, str] = {}
    for task_id in task_ids:
        task = _tasks.get_task(task_id)
        if isinstance(task, dict):
            config = task.get("config") if isinstance(task.get("config"), dict) else {}
            found[task_id] = str(config.get("title_suggestion") or config.get("titleSuggestion") or "")
    return found


def _rate(item) -> dict[str, Any]:
    return {
        "id": item.id, "model": item.model, "resolution": item.resolution, "kind": item.kind,
        "input": item.input, "cached_input": item.cached_input, "output": item.output, "price": item.price,
        "effective_from": item.effective_from, "created_by": item.created_by,
    }


@router.get("/pricing/rates")
async def list_rates(
    _: dict = Depends(require_permission(PRICING_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    return {"kinds": list(RATE_KINDS), "items": [_rate(item) for item in await store.list_point_rates()]}


@router.post("/pricing/rates", status_code=201)
async def add_rate(
    request: PointRateCreateRequest,
    user: dict = Depends(require_permission(PRICING_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    now = datetime.now(timezone.utc)
    effective = request.effective_from or now
    if effective.tzinfo is None:
        raise HTTPException(status_code=422, detail=_text_of("add_rate.detail"))
    if effective < now - timedelta(minutes=1):
        raise HTTPException(status_code=422, detail=_text_of("add_rate.detail.2"))
    fields = request.model_dump(exclude={"effective_from"})
    fields["model"] = fields["model"].strip().lower()
    fields["resolution"] = fields["resolution"].strip().lower()
    return _rate(await store.add_point_rate(actor_id=user["user_id"], effective_from=effective, **fields))


@router.get("/finance/usage")
async def usage_summary(
    days: int = Query(30, ge=1, le=365),
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    """By model: what calls came to in points and in reference cost, which is how a rate is judged."""
    charges = await store.list_usage_charges(since=datetime.now(timezone.utc) - timedelta(days=days))
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {
        "calls": 0, "failed": 0, "points": Decimal(0), "without_rate": 0, "reference_cost": Decimal(0),
        "unpriced_calls": 0, "units": defaultdict(float),
    })
    for charge in charges:
        group = groups[(charge.media_type, charge.provider, charge.model)]
        group["calls"] += 1
        group["failed"] += charge.status != "success"
        group["points"] += Decimal(str(charge.points))
        group["without_rate"] += bool(charge.rate_missing)
        if charge.status == "success":
            if charge.reference_cost is None or not charge.reference_currency:
                group["unpriced_calls"] += 1
            else:
                group["reference_cost"] += Decimal(str(charge.reference_cost))
                group["currency"] = charge.reference_currency
            for key, value in (charge.units or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    group["units"][key] += value
    return {
        "days": days,
        "calls": len(charges),
        "by_mode": {
            mode: sum(1 for charge in charges if charge.billing_mode == mode)
            for mode in sorted({charge.billing_mode for charge in charges})
        },
        "items": [
            {"media_type": key[0], "provider": key[1], "model": key[2], **group, "units": dict(group["units"])}
            for key, group in sorted(groups.items())
        ],
    }


@router.get("/finance/usage/live")
async def usage_live(
    minutes: int = Query(60, ge=5, le=60 * 24 * 31),
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    """The last ``minutes``: calls, tokens, official cost and the quote, in total, by model, by user, by project and over time.

    Calls reach the table a few seconds after they finish (the usage spool drains every five seconds),
    so a page that asks again every few seconds shows them as they happen.
    """
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=minutes)
    stats = usage_stats(await store.list_usage_charges(since=now - window), now=now, window=window)
    # Who a row is: the account's own name where it still resolves.
    names: dict[str, str] = {}
    for row in stats["by_user"]:
        user = await store.get_user(row["user_id"]) if row["user_id"] else None
        names[row["user_id"]] = (user.display_name or user.username or user.email or "") if user else ""
        row["user_name"] = names[row["user_id"]]
    for row in stats["recent"]:
        row["user_name"] = names.get(row["user_id"], "")
    titles = await run_in_threadpool(_task_titles, {row["task_id"] for row in stats["by_task"]})
    for row in stats["by_task"]:
        row["title"] = titles.get(row["task_id"], "")
        row["user_name"] = names.get(row["user_id"], "")
    return stats


@router.get("/pricing/quote")
async def quote_list(_: dict = Depends(require_permission(RECON_READ))):
    """The price list as it is quoted outward, beside the official prices it is worked out from."""
    return {"markup": float(quote.markup()), "usd_cny": float(quote.usd_cny()), "items": quote.price_list(with_official=True)}


@router.get("/recon/usage")
async def usage_reconciliation(
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    """R6 and R7. Worked out when asked for; scheduled runs and a history of them come with the reconciliation stage."""
    charges = await store.list_usage_charges()
    rates = await store.list_point_rates()

    records = await run_in_threadpool(read_usage_records, {charge.task_id for charge in charges if charge.task_id})
    result = usage_differences(charges, rates, records, settled_before=datetime.now(timezone.utc) - _SETTLING)
    result["spool_files_waiting"] = UsageSpool().backlog()
    return result


@router.get("/recon/billing")
async def billing_reconciliation(
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    """R3, R5, and that what calls came to is what was taken from balances."""
    return await store.billing_differences(settled_before=datetime.now(timezone.utc) - _SETTLING)
