"""Paying at a channel: showing a QR code, finding out what happened to it, and sending back what should not have come.

The channels are slow and blocking, so they run in threads, and never while a database transaction is open.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from app.platform.models import PaymentAttempt, PaymentOrder, PaymentRefund
from app.platform.payments import get_payment_channels
from app.platform.payments.base import CLOSED, PAID, REFUNDED, UNPAID, ChannelError, PaymentChannel
from app.platform.store import PlatformStore

logger = logging.getLogger("app.platform.payment_flow")

QR_LIFETIME = timedelta(minutes=15)
#: A code with less time left than this is replaced rather than shown again.
_KEEP_QR_IF_LEFT = timedelta(minutes=1)
_QR_IN_FLIGHT = timedelta(seconds=30)
_POLL_EVERY = timedelta(seconds=5)
_SWEEP_EVERY = timedelta(seconds=60)
_FIRST_SWEEP_AFTER = timedelta(seconds=30)
_ABANDONED_AFTER = timedelta(hours=24)
#: Alipay's two hours, and a margin for a payment that was already under way when they ran out.
_CLOSED_CODE_PAYABLE_FOR = timedelta(hours=2, minutes=15)
_CLOSED_CODE_ASK_EVERY = timedelta(minutes=5)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


async def _ask(store: PlatformStore, channel: PaymentChannel, attempt: PaymentAttempt) -> str:
    """The channel's word on one attempt, acted on. Returns the state it reported."""
    trade = await asyncio.to_thread(channel.query, attempt.out_trade_no)
    if trade.state == PAID:
        await store.apply_channel_payment(provider=attempt.provider, trade=trade, source="query")
    elif trade.state == CLOSED:
        await store.end_attempt(attempt.id, "closed")
    elif trade.state == REFUNDED:
        await store.note_refunded_elsewhere(attempt)
        await store.end_attempt(attempt.id, "closed")
    return trade.state


async def _close(store: PlatformStore, channel: PaymentChannel, attempt: PaymentAttempt) -> str:
    """Ask first: someone may have paid a moment ago, and closing would hide it. Returns the state it reported."""
    state = await _ask(store, channel, attempt)
    if state == UNPAID:
        await asyncio.to_thread(channel.close, attempt.out_trade_no)
        await store.end_attempt(attempt.id, "closed")
    return state


async def close_at_channel(store: PlatformStore, channel: PaymentChannel, attempt: PaymentAttempt) -> str:
    return await _close(store, channel, attempt)


async def pay(
    store: PlatformStore, channels: Mapping[str, PaymentChannel], channel: PaymentChannel, *, order_id: str, user_id: str,
) -> PaymentAttempt | None:
    """The attempt to show, or None when the order turned out to be paid already."""
    now = datetime.now(timezone.utc)
    attempt, is_new, others = await store.open_payment_attempt(
        order_id=order_id, user_id=user_id, provider=channel.name, merchant_id=channel.merchant_id, now=now,
        lifetime=QR_LIFETIME, keep_if_left=_KEEP_QR_IF_LEFT, in_flight_for=_QR_IN_FLIGHT,
    )
    for other in others:
        old_channel = channels.get(other.provider)
        if old_channel is None:
            continue
        try:
            if await _close(store, old_channel, other) == PAID:
                await store.end_attempt(attempt.id, "closed")
                return None
        except ChannelError as exc:
            # The sweep keeps trying. If the old code does get paid as well, that payment is refunded automatically.
            logger.warning("旧支付单关闭失败 %s: %s", other.id, exc)
    if not is_new:
        return attempt
    order = await store.get_order(order_id)
    plan = await store.get_plan(order.plan_id)
    try:
        qr_code = await asyncio.to_thread(
            channel.create_qr, out_trade_no=attempt.out_trade_no, amount_minor=attempt.amount_minor,
            description=f"{plan.name if plan else order.plan_id} 会员", expires_at=_aware(attempt.expires_at),
        )
    except ChannelError:
        await store.end_attempt(attempt.id, "failed")
        raise
    if not await store.set_attempt_qr(attempt.id, qr_code):
        raise ValueError("订单已变更，请刷新后重试")
    attempt.qr_code = qr_code
    return attempt


async def refresh(store: PlatformStore, channels: Mapping[str, PaymentChannel], order_id: str) -> PaymentAttempt | None:
    """The attempt still worth showing, after asking its channel if nobody has in the last few seconds."""
    now = datetime.now(timezone.utc)
    order: PaymentOrder | None = await store.get_order(order_id)
    if not order or order.status != "pending":
        return None
    attempts = await store.open_attempts(order_id)
    for attempt in attempts:
        channel = channels.get(attempt.provider)
        if channel is None or not await store.claim_attempt_query(attempt.id, now, _POLL_EVERY):
            continue
        try:
            await _ask(store, channel, attempt)
        except ChannelError as exc:
            logger.warning("查单失败 %s: %s", attempt.id, exc)
    current = await store.get_order(order_id)
    if current.status != "pending":
        return None
    return next((
        attempt for attempt in await store.open_attempts(order_id)
        if attempt.qr_code and _aware(attempt.expires_at) > now
    ), None)


async def cancel(store: PlatformStore, channels: Mapping[str, PaymentChannel], order_id: str) -> None:
    """Closes the order unless it turns out to be paid. Raises if a channel cannot confirm, so nothing is left half-done."""
    order = await store.get_order(order_id)
    if not order or order.status != "pending":
        return
    for attempt in await store.open_attempts(order_id):
        channel = channels.get(attempt.provider)
        if channel is None:
            continue
        if await _close(store, channel, attempt) == PAID:
            return
    await store.close_order(order_id)


async def _sweep_attempts(store: PlatformStore, channels: Mapping[str, PaymentChannel], now: datetime) -> None:
    due = await store.attempts_due(now=now, settled_after=_FIRST_SWEEP_AFTER, every=_SWEEP_EVERY, limit=200)
    for attempt in due:
        channel = channels.get(attempt.provider)
        if channel is None or not await store.claim_attempt_query(attempt.id, now, _SWEEP_EVERY):
            continue
        try:
            if _aware(attempt.expires_at) <= now:
                await _close(store, channel, attempt)
            else:
                await _ask(store, channel, attempt)
        except ChannelError as exc:
            logger.warning("补偿查单失败 %s: %s", attempt.id, exc)


async def _sweep_closed_codes(store: PlatformStore, channels: Mapping[str, PaymentChannel], now: datetime) -> None:
    """Without this, a payment on a closed code whose notification is also lost would be money received and nothing granted."""
    providers = [name for name, channel in channels.items() if channel.code_survives_close]
    if not providers:
        return
    due = await store.closed_attempts_still_payable(
        providers=providers, now=now, code_lifetime=_CLOSED_CODE_PAYABLE_FOR, every=_CLOSED_CODE_ASK_EVERY, limit=200,
    )
    for attempt in due:
        if not await store.claim_attempt_query(attempt.id, now, _CLOSED_CODE_ASK_EVERY):
            continue
        try:
            await _ask(store, channels[attempt.provider], attempt)
        except ChannelError as exc:
            logger.warning("已关闭付款码查单失败 %s: %s", attempt.id, exc)


async def _sweep_refunds(store: PlatformStore, channels: Mapping[str, PaymentChannel], now: datetime) -> None:
    for refund in await store.refunds_due(now=now, every=_SWEEP_EVERY, limit=100):
        channel = channels.get(refund.provider)
        if channel is None or not await store.claim_refund(refund.id, now, _SWEEP_EVERY):
            continue
        await _push_refund(store, channel, refund)


async def _push_refund(store: PlatformStore, channel: PaymentChannel, refund: PaymentRefund) -> None:
    try:
        if refund.status == "pending":
            result = await asyncio.to_thread(
                channel.refund, out_trade_no=refund.out_trade_no, out_refund_no=refund.out_refund_no,
                refund_minor=refund.refund_minor, total_minor=refund.total_minor,
                # The customer may see this, so it is not the note the operators wrote to each other.
                reason="重复支付退款" if refund.reason == "duplicate_payment" else "会员订单退款",
            )
        else:
            result = await asyncio.to_thread(
                channel.query_refund, out_trade_no=refund.out_trade_no, out_refund_no=refund.out_refund_no,
            )
    except ChannelError as exc:
        # Stays as it is and goes again with the same number, which the channel refunds only once.
        logger.warning("退款未完成 %s: %s", refund.id, exc)
        return
    await store.record_refund(refund.id, status=result.state, channel_refund_no=result.channel_refund_no, detail=result.detail)


async def send_refund_now(store: PlatformStore, channels: Mapping[str, PaymentChannel], refund: PaymentRefund) -> None:
    """Straight after approval, rather than at the next sweep. Whatever goes wrong here the sweep picks up."""
    channel = channels.get(refund.provider)
    if channel is not None and await store.claim_refund(refund.id, datetime.now(timezone.utc), _SWEEP_EVERY):
        await _push_refund(store, channel, refund)


async def sweep(store: PlatformStore, channels: Mapping[str, PaymentChannel], now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    await _sweep_attempts(store, channels, moment)
    await _sweep_closed_codes(store, channels, moment)
    await _sweep_refunds(store, channels, moment)
    await store.close_abandoned_orders(created_before=moment - _ABANDONED_AFTER)


async def run_upkeep_loop(store: PlatformStore) -> None:
    """Notifications can be lost and refunds take time, so nothing here relies on being told."""
    while True:
        await asyncio.sleep(_SWEEP_EVERY.total_seconds())
        try:
            channels = get_payment_channels()
            if channels:
                await sweep(store, channels)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logger.warning("支付补偿失败: %s", type(exc).__name__)
