from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import settings
from app.api.auth_api import get_current_user
from app.platform import payment_flow
from app.platform.dependencies import get_platform_store
from app.platform.payments import get_payment_channels
from app.platform.payments.base import PAID, ChannelError, NotificationRejected
from app.platform.store import PaymentInFlight, PlatformStore
from app.schema.platform import OrderCreateRequest, OrderPayRequest
from app.core import prompt_data, quote


_WORDING_FILE = "api_billing_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_billing_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


router = APIRouter(prefix="/api/billing", tags=list(_words_of("module.tags")))
logger = logging.getLogger("app.api.billing")

#: A notification is a few KB. This route is public, so nothing larger gets read.
_MAX_NOTIFICATION_BYTES = 64 * 1024


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


@router.get("/price-list")
async def price_list(_: dict = Depends(get_current_user)):
    """What each model is quoted at, for anyone signed in. The official prices behind it stay inside."""
    return {"items": quote.price_list(with_official=False)}


@router.get("/plans")
async def plans(store: PlatformStore = Depends(get_platform_store)):
    return {"sandbox_enabled": settings.payment_sandbox_enabled(), "channels": sorted(get_payment_channels()), "items": [{
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
    available, held = await store.point_balance(user["user_id"])
    return {
        "points": snapshot.points,
        "available": available,
        "held": held,
        "frozen": await store.frozen_points(user["user_id"]),
        "charging": settings.billing_enforced(),
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


@router.get("/entitlements")
async def entitlements(
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """For showing what the plan includes. The limits themselves are enforced on the server."""
    return {"items": await store.effective_entitlements(user["user_id"]), "enforced": settings.billing_enforced()}


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
    if request.provider not in (None, "sandbox") and request.provider not in get_payment_channels():
        raise HTTPException(status_code=422, detail=_text_of("create_order.detail"))
    try:
        item = await store.create_order(
            user_id=user["user_id"], plan_id=request.plan_id,
            provider=request.provider, idempotency_key=request.idempotency_key,
        )
        return _order(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _own_order(order_id: str, user: dict, store: PlatformStore):
    order = await store.get_order(order_id)
    if not order or order.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail=_text_of("_own_order.detail"))
    return order


def _order_with_attempt(order, attempt) -> dict:
    return {**_order(order), "attempt": attempt and {
        "provider": attempt.provider, "qr_code": attempt.qr_code, "expires_at": attempt.expires_at,
    }}


@router.post("/orders/{order_id}/pay")
async def pay_order(
    order_id: str,
    request: OrderPayRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """A QR code for this order at this channel. Any other open one is closed at its channel first."""
    await _own_order(order_id, user, store)
    channel = get_payment_channels().get(request.provider)
    if channel is None:
        raise HTTPException(status_code=422, detail=_text_of("pay_order.detail"))
    try:
        attempt = await payment_flow.pay(store, get_payment_channels(), channel, order_id=order_id, user_id=user["user_id"])
    except PaymentInFlight as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChannelError as exc:
        logger.warning("出码失败: %s", exc)
        raise HTTPException(status_code=502, detail=_text_of("pay_order.detail.2")) from exc
    return _order_with_attempt(await store.get_order(order_id), attempt)


@router.get("/orders/{order_id}")
async def order_status(
    order_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """What the payment dialog polls. It also asks the channel, because a notification may never come."""
    await _own_order(order_id, user, store)
    attempt = await payment_flow.refresh(store, get_payment_channels(), order_id)
    return _order_with_attempt(await store.get_order(order_id), attempt)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    await _own_order(order_id, user, store)
    try:
        await payment_flow.cancel(store, get_payment_channels(), order_id)
    except ChannelError as exc:
        logger.warning("关单失败: %s", exc)
        raise HTTPException(status_code=502, detail=_text_of("cancel_order.detail")) from exc
    return _order(await store.get_order(order_id))


@router.post("/orders/{order_id}/sandbox-confirm")
async def sandbox_confirm(
    order_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    if not settings.payment_sandbox_enabled():
        raise HTTPException(status_code=404, detail=_text_of("sandbox_confirm.detail"))
    order = await store.get_order(order_id)
    if not order or order.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail=_text_of("sandbox_confirm.detail.2"))
    if order.provider != "sandbox":
        raise HTTPException(status_code=422, detail=_text_of("sandbox_confirm.detail.3"))
    try:
        return _order(await store.confirm_paid_order(order.id, f"sandbox:{order.id}"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _notification_reply(provider: str, ok: bool, status: int = 500) -> Response:
    """Each channel has its own idea of an acknowledgement, and retries until it hears exactly that."""
    if provider == "alipay":
        return PlainTextResponse("success" if ok else "fail")
    return Response(status_code=204) if ok else JSONResponse({"code": "FAIL", "message": _text_of("_notification_reply.message")}, status_code=status)


@router.post("/webhooks/{provider}")
async def payment_webhook(
    provider: str,
    request: Request,
    store: PlatformStore = Depends(get_platform_store),
):
    channel = get_payment_channels().get(provider)
    if channel is None:
        raise HTTPException(status_code=404, detail=_text_of("payment_webhook.detail"))
    body = await request.body()
    if len(body) > _MAX_NOTIFICATION_BYTES:
        return _notification_reply(provider, False, 413)
    try:
        event = channel.parse_notification(request.headers, body)
    except NotificationRejected as exc:
        logger.warning("支付通知被拒绝 %s: %s", provider, exc)
        return _notification_reply(provider, False, 401)
    if event.trade is not None and event.trade.state == PAID:
        try:
            await store.apply_channel_payment(
                provider=provider, trade=event.trade, source="notification",
                event_id=event.event_id, payload_sha256=hashlib.sha256(body).hexdigest(),
            )
        except Exception:  # noqa: BLE001 - the channel retries; a query will find it too
            logger.exception("支付通知入账失败 %s", provider)
            return _notification_reply(provider, False)
    return _notification_reply(provider, True)
