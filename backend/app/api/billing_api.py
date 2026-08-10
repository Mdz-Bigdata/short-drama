from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.api.auth_api import get_current_user
from app.platform.dependencies import get_platform_store
from app.platform.payments import PaymentSignatureError, verify_webhook_signature
from app.platform.store import PlatformStore
from app.schema.platform import OrderCreateRequest, PaymentWebhookPayload


router = APIRouter(prefix="/api/billing", tags=["会员积分与支付"])


def _order(item) -> dict:
    return {
        "id": item.id,
        "plan_id": item.plan_id,
        "provider": item.provider,
        "amount": item.amount,
        "currency": item.currency,
        "status": item.status,
        "created_at": item.created_at,
        "paid_at": item.paid_at,
    }


@router.get("/plans")
async def plans(store: PlatformStore = Depends(get_platform_store)):
    return {"items": [{
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "price": item.price,
        "currency": item.currency,
        "points": item.points,
        "duration_days": item.duration_days,
    } for item in await store.list_plans()]}


@router.get("/wallet")
async def wallet(
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    snapshot = await store.wallet(user["user_id"])
    return {
        "points": snapshot.points,
        "money": snapshot.money,
        "entries": [{
            "id": item.id,
            "asset": item.asset,
            "direction": item.direction,
            "amount": item.amount,
            "currency": item.currency,
            "category": item.category,
            "created_at": item.created_at,
        } for item in snapshot.entries],
    }


@router.get("/orders")
async def orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items, total = await store.list_orders(user["user_id"], page, page_size)
    return {"items": [_order(item) for item in items], "page": page, "page_size": page_size, "total": total}


@router.post("/orders")
async def create_order(
    request: OrderCreateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.create_order(
            user_id=user["user_id"], plan_id=request.plan_id,
            provider=request.provider, idempotency_key=request.idempotency_key,
        )
        return _order(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/orders/{order_id}/sandbox-confirm")
async def sandbox_confirm(
    order_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    order = await store.get_order(order_id)
    if not order or order.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.provider != "sandbox":
        raise HTTPException(status_code=422, detail="仅沙箱订单支持本地确认")
    try:
        return _order(await store.confirm_paid_order(order.id, f"sandbox:{order.id}"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/webhooks/{provider}")
async def payment_webhook(
    provider: str,
    request: Request,
    x_payment_signature: str = Header(""),
    store: PlatformStore = Depends(get_platform_store),
):
    if provider not in {"wechat", "alipay"}:
        raise HTTPException(status_code=404, detail="支付渠道不存在")
    body = await request.body()
    try:
        verify_webhook_signature(body, x_payment_signature)
        payload = PaymentWebhookPayload.model_validate_json(body)
        order, applied = await store.process_webhook_payment(
            provider=provider,
            event_id=payload.event_id,
            order_id=payload.order_id,
            amount=payload.amount,
            currency=payload.currency,
            payload_sha256=hashlib.sha256(body).hexdigest(),
        )
        return {"status": "success", "applied": applied, "order": _order(order)}
    except PaymentSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
