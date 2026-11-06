"""The finance console: orders, refunds, point adjustments, reconciliation. Every route names the permission it needs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.api.auth_api import require_permission
from app.api.usage_admin_api import read_usage_records
from app.platform import payment_flow, reconciliation
from app.platform.dependencies import get_platform_store
from app.platform.models import ChannelBill, ReconItem, ReconRun
from app.platform.payments import get_payment_channels
from app.platform.permissions import (
    ORDER_READ_ANY,
    RECON_READ,
    RECON_RESOLVE,
    REFUND_APPROVE,
    REFUND_REQUEST,
    WALLET_ADJUST_APPROVE,
    WALLET_ADJUST_REQUEST,
)
from app.platform.store import PlatformStore
from app.schema.platform import (
    DecisionRequest,
    ReconResolveRequest,
    RefundApproveRequest,
    RefundCreateRequest,
    WalletAdjustmentRequest,
)

router = APIRouter(prefix="/api/admin", tags=["财务后台"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _order(item, email: str = "") -> dict[str, Any]:
    return {
        "id": item.id, "user_id": item.user_id, "email": email, "plan_id": item.plan_id, "provider": item.provider,
        "amount": item.amount, "currency": item.currency, "status": item.status, "created_at": item.created_at, "paid_at": item.paid_at,
    }


def _refund(item, email: str = "") -> dict[str, Any]:
    return {
        "id": item.id, "order_id": item.order_id, "user_id": item.user_id, "email": email, "provider": item.provider,
        "out_refund_no": item.out_refund_no, "amount_minor": item.refund_minor, "suggested_minor": item.suggested_minor,
        "total_minor": item.total_minor, "points": item.points_clawback, "reason": item.reason, "status": item.status,
        "note": item.note, "decision_note": item.decision_note, "detail": item.detail, "requested_by": item.requested_by,
        "approved_by": item.approved_by, "rejected_by": item.rejected_by, "created_at": item.created_at,
        "decided_at": item.decided_at, "finished_at": item.finished_at,
    }


def _adjustment(item, email: str = "") -> dict[str, Any]:
    return {
        "id": item.id, "user_id": item.user_id, "email": email, "points": item.points, "reason": item.reason, "status": item.status,
        "requested_by": item.requested_by, "approved_by": item.approved_by, "rejected_by": item.rejected_by,
        "decision_note": item.decision_note, "created_at": item.created_at, "decided_at": item.decided_at,
    }


def _item(item) -> dict[str, Any]:
    return {
        "id": item.id, "rule": item.rule, "kind": item.kind, "severity": item.severity, "order_id": item.order_id,
        "reference": item.reference, "expected": item.expected, "actual": item.actual, "status": item.status,
        "resolved_by": item.resolved_by, "resolution": item.resolution, "created_at": item.created_at, "resolved_at": item.resolved_at,
    }


def _run(item) -> dict[str, Any]:
    return {
        "id": item.id, "period": item.period, "rules": item.rules, "status": item.status, "summary": item.summary,
        "started_at": item.started_at, "finished_at": item.finished_at,
    }


@router.get("/orders")
async def list_orders(
    status: str | None = Query(None, max_length=24),
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_permission(ORDER_READ_ANY)),
    store: PlatformStore = Depends(get_platform_store),
):
    rows, total = await store.list_all_orders(status=status, query=q.strip(), page=page, page_size=page_size)
    return {"items": [_order(*row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/orders/{order_id}")
async def order_detail(
    order_id: str,
    _: dict = Depends(require_permission(ORDER_READ_ANY)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        details = await store.order_details(order_id)
        quote = await store.refund_quote(order_id)
    except LookupError as exc:
        raise _http_error(exc) from exc
    lot, term = details["lot"], details["term"]
    return {
        "order": _order(details["order"], details["user"].email if details["user"] else ""),
        "attempts": [{
            "id": item.id, "provider": item.provider, "out_trade_no": item.out_trade_no, "channel_trade_no": item.channel_trade_no,
            "amount_minor": item.amount_minor, "status": item.status, "settled_by": item.settled_by, "paid_at": item.paid_at,
        } for item in details["attempts"]],
        "refunds": [_refund(item) for item in details["refunds"]],
        "lot": lot and {"granted": lot.granted, "remaining": lot.remaining, "frozen": lot.frozen, "expires_at": lot.expires_at},
        "term": term and {"plan_id": term.plan_id, "status": term.status, "starts_at": term.starts_at, "expires_at": term.expires_at},
        "recon_items": [_item(item) for item in details["recon_items"]],
        "quote": quote,
    }


@router.post("/orders/{order_id}/refunds", status_code=201)
async def create_refund(
    order_id: str,
    request: RefundCreateRequest,
    user: dict = Depends(require_permission(REFUND_REQUEST)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _refund(await store.request_refund(
            order_id=order_id, actor=user, note=request.note, points=request.points, amount_minor=request.amount_minor,
        ))
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/refunds")
async def list_refunds(
    status: str | None = Query(None, max_length=24),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_permission(ORDER_READ_ANY)),
    store: PlatformStore = Depends(get_platform_store),
):
    rows, total = await store.list_refunds(status=status, page=page, page_size=page_size)
    return {"items": [_refund(*row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/refunds/{refund_id}/approve")
async def approve_refund(
    refund_id: str,
    request: RefundApproveRequest,
    user: dict = Depends(require_permission(REFUND_APPROVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    channels = get_payment_channels()
    existing = await store.get_refund(refund_id)
    if existing and existing.provider not in channels:
        # Approving would release nothing and go nowhere, with the customer's points still set aside.
        raise HTTPException(status_code=409, detail="该支付渠道当前未配置，暂时无法退款")
    try:
        refund = await store.approve_refund(refund_id=refund_id, actor=user, amount_minor=request.amount_minor, note=request.note)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_error(exc) from exc
    await payment_flow.send_refund_now(store, channels, refund)
    return _refund(await store.get_refund(refund_id))


@router.post("/refunds/{refund_id}/reject")
async def reject_refund(
    refund_id: str,
    request: DecisionRequest,
    user: dict = Depends(require_permission(REFUND_APPROVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _refund(await store.reject_refund(refund_id=refund_id, actor=user, note=request.note))
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/wallet-adjustments")
async def list_adjustments(
    status: str | None = Query(None, max_length=24),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_permission(WALLET_ADJUST_REQUEST)),
    store: PlatformStore = Depends(get_platform_store),
):
    rows, total = await store.list_wallet_adjustments(status=status, page=page, page_size=page_size)
    return {"items": [_adjustment(*row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/wallet-adjustments", status_code=201)
async def create_adjustment(
    request: WalletAdjustmentRequest,
    user: dict = Depends(require_permission(WALLET_ADJUST_REQUEST)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _adjustment(await store.request_wallet_adjustment(
            user_id=request.user_id, points=request.points, reason=request.reason, actor=user,
        ))
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/wallet-adjustments/{adjustment_id}/approve")
async def approve_adjustment(
    adjustment_id: str,
    request: DecisionRequest,
    user: dict = Depends(require_permission(WALLET_ADJUST_APPROVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _adjustment(await store.approve_wallet_adjustment(adjustment_id=adjustment_id, actor=user, note=request.note))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/wallet-adjustments/{adjustment_id}/reject")
async def reject_adjustment(
    adjustment_id: str,
    request: DecisionRequest,
    user: dict = Depends(require_permission(WALLET_ADJUST_APPROVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _adjustment(await store.reject_wallet_adjustment(adjustment_id=adjustment_id, actor=user, note=request.note))
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/recon/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    async with store.sessions() as session:
        runs = (await session.scalars(select(ReconRun).order_by(ReconRun.started_at.desc()).limit(limit))).all()
        bills = (await session.scalars(select(ChannelBill).order_by(ChannelBill.bill_date.desc()).limit(limit))).all()
    return {
        "items": [_run(item) for item in runs],
        "bills": [{
            "provider": bill.provider, "bill_date": bill.bill_date, "row_count": bill.row_count, "paid_minor": bill.paid_minor,
            "refunded_minor": bill.refunded_minor, "sha256": bill.sha256,
        } for bill in bills],
    }


@router.post("/recon/runs", status_code=201)
async def start_run(
    user: dict = Depends(require_permission(RECON_RESOLVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    """All the rules, now, rather than waiting for the schedule."""
    run = await reconciliation.run_checks(
        store, period=f"manual:{uuid4()}", rules=reconciliation.DAILY_RULES, read_records=read_usage_records,
    )
    await store.record_audit(actor_id=user["user_id"], action="recon.run", resource_type="recon_run", resource_id=run.id)
    return _run(run)


@router.get("/recon/items")
async def list_items(
    status: str | None = Query("open", max_length=16),
    severity: str | None = Query(None, max_length=12),
    rule: str | None = Query(None, max_length=8),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    conditions = [
        column == value for column, value in (
            (ReconItem.status, status), (ReconItem.severity, severity), (ReconItem.rule, rule),
        ) if value
    ]
    async with store.sessions() as session:
        total = int(await session.scalar(select(func.count()).select_from(ReconItem).where(*conditions)) or 0)
        items = (await session.scalars(
            select(ReconItem).where(*conditions).order_by(ReconItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).all()
    return {"items": [_item(item) for item in items], "page": page, "page_size": page_size, "total": total}


@router.post("/recon/items/{item_id}/resolve")
async def resolve_item(
    item_id: str,
    request: ReconResolveRequest,
    user: dict = Depends(require_permission(RECON_RESOLVE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _item(await reconciliation.resolve_item(store, item_id=item_id, actor=user, status=request.status, resolution=request.resolution))
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/finance/summary")
async def summary(
    _: dict = Depends(require_permission(RECON_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    return await reconciliation.finance_summary(store)
