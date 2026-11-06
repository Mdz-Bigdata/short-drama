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
from app.repository.task_repo import TaskRepository
from app.schema.platform import PointRateCreateRequest

router = APIRouter(prefix="/api/admin", tags=["用量计费"])
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
        raise HTTPException(status_code=422, detail="生效时间必须带时区")
    if effective < now - timedelta(minutes=1):
        raise HTTPException(status_code=422, detail="费率不能追溯生效：历史调用按当时的费率记录")
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
