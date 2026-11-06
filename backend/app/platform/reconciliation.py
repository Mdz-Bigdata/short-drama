"""R1 to R10 of docs/access-and-billing/DESIGN.md: whether money, orders, points, usage and audit records still agree.

The checks only read. What they find becomes a ``ReconItem`` that stays open until it stops being true or a person
explains it. The one thing done automatically is posting a payment a channel's bill shows and a query confirms.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.platform.entitlements import entitlements_from, resolution_allowed
from app.platform.models import (
    AuditEvent,
    ChannelBill,
    ChannelBillRow,
    LedgerEntry,
    MembershipTerm,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    PointBalance,
    PointHold,
    PointLot,
    ReconItem,
    ReconRun,
    UsageCharge,
    UserRole,
    WalletAdjustment,
)
from app.platform.payments import get_payment_channels
from app.platform.payments.base import BillNotReady, ChannelError, PaymentChannel
from app.platform.permissions import REFUND_APPROVE, REFUND_REQUEST, WALLET_ADJUST_APPROVE, WALLET_ADJUST_REQUEST, permissions_for
from app.platform.store import PAID_ORDER_STATES, REFUND_ON_REQUEST, REFUND_OPEN, PlatformStore, money_audit
from app.platform.usage_billing import usage_differences

logger = logging.getLogger("app.platform.reconciliation")

CHINA = timezone(timedelta(hours=8))
HOURLY_RULES = ("R2", "R3", "R5", "R6")
DAILY_RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")
CRITICAL, WARNING, INFO = "critical", "warning", "info"
#: Records this recent may still be on their way from the spool.
_SETTLING = timedelta(minutes=5)
_BILL_DAYS_TO_TRY = 3
#: A bill this many days late is worth telling someone about: channels publish the next morning, sometimes later.
_BILL_LATE_AFTER_DAYS = 2
_NEAR_MIDNIGHT = timedelta(minutes=10)
_STUCK_AFTER = timedelta(days=3)
_DAILY_RUN_AFTER = (10, 30)  # China time, once both channels have published
_LOOP_EVERY_SECONDS = 300
_NO_LIMIT = 10**9

RecordsReader = Callable[[set[str]], dict[str, list]]


@dataclass(frozen=True)
class Finding:
    rule: str
    kind: str
    severity: str
    reference: str
    expected: str = ""
    actual: str = ""
    order_id: str | None = None

    @property
    def fingerprint(self) -> str:
        return f"{self.rule}:{self.kind}:{self.reference}"[:200]


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _china_day(moment: datetime) -> date:
    return _aware(moment).astimezone(CHINA).date()


@dataclass
class Books:
    orders: Sequence[PaymentOrder]
    attempts: Sequence[PaymentAttempt]
    refunds: Sequence[PaymentRefund]
    lots: Sequence[PointLot]
    balances: Sequence[PointBalance]
    holds: Sequence[PointHold]
    terms: Sequence[MembershipTerm]
    ledger: Sequence[LedgerEntry]
    bills: Sequence[ChannelBill]
    rows: Sequence[ChannelBillRow]
    adjustments: Sequence[WalletAdjustment]
    audits: Sequence[AuditEvent]
    charges: Sequence[UsageCharge]
    grants: Sequence[UserRole]


async def load_books(store: PlatformStore) -> Books:
    async with store.sessions() as session:
        async def everything(model, *conditions):
            return (await session.scalars(select(model).where(*conditions))).all()

        audited = ("refund.request", "refund.approve", "wallet.adjust_request", "wallet.adjust_approve", "user.roles_change")
        return Books(
            orders=await everything(PaymentOrder), attempts=await everything(PaymentAttempt), refunds=await everything(PaymentRefund),
            lots=await everything(PointLot), balances=await everything(PointBalance),
            holds=await everything(PointHold, PointHold.status == "active"), terms=await everything(MembershipTerm),
            ledger=await everything(LedgerEntry, LedgerEntry.asset == "points"), bills=await everything(ChannelBill),
            rows=await everything(ChannelBillRow), adjustments=await everything(WalletAdjustment),
            audits=await everything(AuditEvent, AuditEvent.action.in_(audited)), charges=await everything(UsageCharge),
            grants=await everything(UserRole),
        )


def _is_paid(order: PaymentOrder) -> bool:
    return order.status in PAID_ORDER_STATES


def _duplicate_attempts(books: Books) -> set[str]:
    return {refund.attempt_id for refund in books.refunds if refund.reason == "duplicate_payment"}


def check_r1(books: Books, today: date) -> list[Finding]:
    """Every line of a channel's bill has a payment here at the same amount, and the other way round."""
    found: list[Finding] = []
    attempts = {(item.provider, item.out_trade_no): item for item in books.attempts}
    days = {(bill.provider, bill.bill_date) for bill in books.bills}
    on_bill = set()
    for row in books.rows:
        if row.kind != "payment":
            continue
        on_bill.add((row.provider, row.out_trade_no))
        attempt = attempts.get((row.provider, row.out_trade_no))
        reference = f"{row.provider}:{row.out_trade_no}"
        if attempt is None:
            found.append(Finding("R1", "on_bill_not_here", CRITICAL, reference, "这里有支付单", f"账单 {row.amount_minor} 分"))
        elif attempt.status != "paid":
            found.append(Finding("R1", "on_bill_not_paid_here", CRITICAL, reference, "已入账", attempt.status, attempt.order_id))
        elif attempt.amount_minor != row.amount_minor:
            found.append(Finding("R1", "amount_differs", CRITICAL, reference, str(attempt.amount_minor), str(row.amount_minor), attempt.order_id))
        elif attempt.channel_trade_no != row.channel_trade_no:
            found.append(Finding("R1", "trade_number_differs", CRITICAL, reference, attempt.channel_trade_no or "", row.channel_trade_no, attempt.order_id))
    late_days: set[tuple[str, date]] = set()
    for attempt in books.attempts:
        if attempt.status != "paid" or (attempt.provider, attempt.out_trade_no) in on_bill or not attempt.paid_at:
            continue
        day = _china_day(attempt.paid_at)
        reference = f"{attempt.provider}:{attempt.out_trade_no}"
        if (attempt.provider, day) not in days:
            if (today - day).days > _BILL_LATE_AFTER_DAYS:
                late_days.add((attempt.provider, day))
            continue
        end_of_day = datetime.combine(day + timedelta(days=1), datetime.min.time(), CHINA)
        next_bill_here = (attempt.provider, day + timedelta(days=1)) in days
        if end_of_day - _aware(attempt.paid_at) <= _NEAR_MIDNIGHT and not next_bill_here:
            # May well be on tomorrow's bill. This closes itself once that arrives.
            found.append(Finding("R1", "crosses_midnight", INFO, reference, "在账单上", "等下一天账单", attempt.order_id))
        else:
            found.append(Finding("R1", "paid_here_not_on_bill", CRITICAL, reference, "在账单上", "账单没有", attempt.order_id))
    found.extend(Finding("R1", "bill_missing", WARNING, f"{provider}:{day}", "已下载", "缺失") for provider, day in sorted(late_days))
    return found


def check_r2(books: Books) -> list[Finding]:
    """A paid order has exactly one payment behind it, and any more have a refund."""
    found: list[Finding] = []
    orders = {order.id: order for order in books.orders}
    paid_by_order: dict[str, list[PaymentAttempt]] = defaultdict(list)
    duplicates = _duplicate_attempts(books)
    for attempt in books.attempts:
        if attempt.status == "mismatch":
            found.append(Finding("R2", "attempt_mismatch", CRITICAL, attempt.out_trade_no, str(attempt.amount_minor), "通知的金额或商户不符", attempt.order_id))
        if attempt.status != "paid":
            continue
        paid_by_order[attempt.order_id].append(attempt)
        order = orders.get(attempt.order_id)
        if order is None or not _is_paid(order):
            found.append(Finding("R2", "payment_but_order_not_paid", CRITICAL, attempt.out_trade_no, "已付", order.status if order else "无订单", attempt.order_id))
    for order in books.orders:
        if not _is_paid(order) or order.provider == "sandbox":
            continue
        paid = paid_by_order.get(order.id, [])
        first = [item for item in paid if f"{item.provider}:{item.channel_trade_no}" == order.provider_event_id]
        if not first:
            found.append(Finding("R2", "order_paid_without_payment", CRITICAL, order.id, "一笔已付支付单", str(len(paid)), order.id))
        for extra in paid:
            if extra not in first and extra.id not in duplicates:
                found.append(Finding("R2", "second_payment_without_refund", CRITICAL, extra.out_trade_no, "有退款单", "没有", order.id))
    return found


def check_r3_r5(differences: Mapping[str, Any]) -> list[Finding]:
    found = [
        Finding("R3", problem, CRITICAL, item["order_id"], "", "", item["order_id"])
        for item in differences["r3"]["samples"] for problem in item["problems"]
    ]
    found.extend(
        Finding("R5", "balance_differs", CRITICAL, item["user_id"], f"账本 {item['ledger']}", f"批次 {item['lots']} / 余额 {item['balance']}")
        for item in differences["r5"]["samples"]
    )
    return found


def _lot_draws(books: Books) -> dict[str, dict[str, Decimal]]:
    """What the ledger says left each lot, by category."""
    drawn: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for entry in books.ledger:
        if entry.direction != "debit":
            continue
        metadata = entry.metadata_json or {}
        for lot_id, amount in (metadata.get("lots") or {}).items():
            drawn[lot_id][entry.category] += Decimal(str(amount))
        if metadata.get("lot_id"):
            drawn[metadata["lot_id"]][entry.category] += entry.amount
    return drawn


def check_r5_lots(books: Books) -> list[Finding]:
    """Each lot accounted for line by line, and what is set aside or held adds up on every side."""
    found: list[Finding] = []
    drawn = _lot_draws(books)
    sandbox = {order.id for order in books.orders if order.provider == "sandbox"}
    frozen_by_lot: dict[str, Decimal] = defaultdict(Decimal)
    for refund in books.refunds:
        if refund.status in REFUND_OPEN and refund.lot_id:
            frozen_by_lot[refund.lot_id] += refund.points_clawback
    frozen_by_user: dict[str, Decimal] = defaultdict(Decimal)
    for lot in books.lots:
        frozen_by_user[lot.user_id] += lot.frozen
        if lot.remaining < lot.frozen or lot.frozen < 0:
            found.append(Finding("R5", "lot_negative", CRITICAL, lot.id, f"剩余 ≥ 冻结 {lot.frozen}", str(lot.remaining), lot.order_id))
        if lot.frozen != frozen_by_lot.get(lot.id, Decimal(0)):
            found.append(Finding("R5", "frozen_differs", CRITICAL, lot.id, str(frozen_by_lot.get(lot.id, Decimal(0))), str(lot.frozen), lot.order_id))
        if lot.order_id in sandbox:
            continue
        left = lot.granted - sum(drawn.get(lot.id, {}).values(), Decimal(0))
        if left != lot.remaining:
            found.append(Finding("R5", "lot_differs", CRITICAL, lot.id, str(left), str(lot.remaining), lot.order_id))
    held_by_user: dict[str, Decimal] = defaultdict(Decimal)
    for hold in books.holds:
        held_by_user[hold.user_id] += hold.amount
    for balance in books.balances:
        if balance.frozen != frozen_by_user.get(balance.user_id, Decimal(0)):
            found.append(Finding("R5", "balance_frozen_differs", CRITICAL, balance.user_id, str(frozen_by_user.get(balance.user_id, Decimal(0))), str(balance.frozen)))
        if balance.held != held_by_user.get(balance.user_id, Decimal(0)):
            found.append(Finding("R5", "balance_held_differs", WARNING, balance.user_id, str(held_by_user.get(balance.user_id, Decimal(0))), str(balance.held)))
    return found


def check_r6_r7(books: Books, differences: Mapping[str, Any], usage: Mapping[str, Any], rules: Sequence[str]) -> list[Finding]:
    found: list[Finding] = []
    if "R6" in rules:
        found.extend(Finding("R6", item["problem"], WARNING, item["usage_id"], item["expected"], item["actual"]) for item in usage["r6"]["samples"])
        found.extend(Finding("R6", "charge_not_taken", WARNING, item["usage_id"], item["expected"], str(item["taken"])) for item in differences["usage_vs_ledger"]["samples"])
    if "R7" in rules:
        found.extend(Finding("R7", "record_without_charge", WARNING, item["usage_id"], "有计费记录", item["task_id"]) for item in usage["r7"]["records_without_charge"])
        found.extend(Finding("R7", "charge_not_on_project", WARNING, item["usage_id"], "项目有记录", item["task_id"]) for item in usage["r7"]["charges_not_on_project"])
    return found


def check_r4(books: Books, now: datetime) -> list[Finding]:
    """A refund that succeeded took back its points, stays within what was paid, and appears on the channel's bill."""
    found: list[Finding] = []
    orders = {order.id: order for order in books.orders}
    attempts = {item.id: item for item in books.attempts}
    clawbacks = {entry.idempotency_key: entry for entry in books.ledger if entry.category == "refund_clawback"}
    by_id = {refund.id: refund for refund in books.refunds}
    for key, entry in clawbacks.items():
        refund = by_id.get(key.split(":")[1]) if key.count(":") == 2 else None
        if refund is None or refund.status != "succeeded":
            found.append(Finding("R4", "points_taken_without_refund", CRITICAL, key, "退款成功", refund.status if refund else "无退款单", entry.order_id))
    refunded_on_attempt: dict[str, int] = defaultdict(int)
    refunded_on_order: dict[str, int] = defaultdict(int)
    for refund in books.refunds:
        age = now - _aware(refund.created_at)
        if refund.status == "succeeded":
            refunded_on_attempt[refund.attempt_id] += refund.refund_minor
            if refund.reason == REFUND_ON_REQUEST:
                refunded_on_order[refund.order_id] += refund.refund_minor
            if refund.points_clawback > 0:
                entry = clawbacks.get(f"refund:{refund.id}:clawback")
                if entry is None or entry.amount != refund.points_clawback:
                    found.append(Finding("R4", "points_not_taken", CRITICAL, refund.id, str(refund.points_clawback), str(entry.amount) if entry else "0", refund.order_id))
        elif refund.status == "failed":
            found.append(Finding("R4", "refund_failed", CRITICAL, refund.id, "退款成功", refund.detail or "失败", refund.order_id))
        elif refund.status in ("pending", "processing") and age > _STUCK_AFTER:
            found.append(Finding("R4", "refund_stuck", WARNING, refund.id, "3 天内完成", refund.status, refund.order_id))
        elif refund.status == "requested" and age > _STUCK_AFTER:
            found.append(Finding("R4", "refund_waiting_for_decision", INFO, refund.id, "3 天内处理", "待审批", refund.order_id))
    for attempt_id, total in refunded_on_attempt.items():
        attempt = attempts.get(attempt_id)
        if attempt and total > attempt.amount_minor:
            found.append(Finding("R4", "refunded_more_than_paid", CRITICAL, attempt.out_trade_no, f"≤ {attempt.amount_minor}", str(total), attempt.order_id))
    for order in books.orders:
        total = refunded_on_order.get(order.id, 0)
        if order.status in ("partially_refunded", "refunded") or total:
            paid = next((a.amount_minor for a in books.attempts if f"{a.provider}:{a.channel_trade_no}" == order.provider_event_id), 0)
            expected = "refunded" if total >= paid and paid else "partially_refunded" if total else "paid"
            if order.status != expected:
                found.append(Finding("R4", "order_status_differs", CRITICAL, order.id, expected, order.status, order.id))
    by_number = {refund.out_refund_no: refund for refund in books.refunds}
    latest_bill: dict[str, date] = {}
    for bill in books.bills:
        latest_bill[bill.provider] = max(latest_bill.get(bill.provider, bill.bill_date), bill.bill_date)
    on_bill = set()
    for row in books.rows:
        if row.kind != "refund":
            continue
        on_bill.add(row.out_refund_no)
        refund = by_number.get(row.out_refund_no)
        if refund is None:
            found.append(Finding("R4", "refund_on_bill_not_here", CRITICAL, f"{row.provider}:{row.out_refund_no}", "有退款单", f"账单 {row.amount_minor} 分"))
        elif refund.refund_minor != row.amount_minor:
            found.append(Finding("R4", "refund_amount_differs", CRITICAL, refund.id, str(refund.refund_minor), str(row.amount_minor), refund.order_id))
        elif refund.status in ("requested", "rejected"):
            found.append(Finding("R4", "refund_on_bill_not_approved", CRITICAL, refund.id, "已批准", refund.status, refund.order_id))
    for refund in books.refunds:
        if refund.status == "succeeded" and refund.finished_at and refund.out_refund_no not in on_bill:
            latest = latest_bill.get(refund.provider)
            # Billed by the day it was asked for, so a day's margin before calling it missing.
            if latest and _china_day(refund.finished_at) < latest:
                found.append(Finding("R4", "refund_not_on_bill", CRITICAL, refund.id, "在账单上", "账单没有", refund.order_id))
    return found


def check_r8(books: Books, now: datetime) -> list[Finding]:
    """A term in force rests on an order not fully refunded, and charged use of a paid tier falls within a term allowing it."""
    found: list[Finding] = []
    orders = {order.id: order for order in books.orders}
    for term in books.terms:
        order = orders.get(term.order_id)
        running = term.status == "active" and _aware(term.expires_at) > now
        if running and (order is None or order.status not in ("paid", "partially_refunded")):
            found.append(Finding("R8", "term_without_paid_order", CRITICAL, term.id, "有已付订单", order.status if order else "无订单", term.order_id))
        if term.status != "active" and order is not None and order.status != "refunded":
            found.append(Finding("R8", "term_ended_order_not_refunded", WARNING, term.id, order.status, term.status, term.order_id))
    terms_by_user: dict[str, list[Any]] = defaultdict(list)
    for term in books.terms:
        # As they stood then: a term refunded since was still in force at the time.
        terms_by_user[term.user_id].append(SimpleNamespace(
            status="active", starts_at=term.starts_at, expires_at=term.expires_at, entitlements=term.entitlements,
        ))
    for charge in books.charges:
        resolution = str((charge.units or {}).get("resolution") or "").strip().lower()
        if charge.billing_mode != "charged" or charge.media_type != "video" or not resolution or not charge.user_id:
            continue
        allowed = entitlements_from(terms_by_user.get(charge.user_id, []), _aware(charge.occurred_at))
        if not resolution_allowed(allowed, resolution):
            found.append(Finding("R8", "paid_tier_used_outside_term", WARNING, charge.usage_id, f"≤ {allowed.get('video.max_resolution')}", resolution))
    return found


def money_position(books: Books) -> dict[str, Any]:
    """R9: money in less money back equals what has been earned plus what is still owed in points. In fen."""
    sandbox = {order.id for order in books.orders if order.provider == "sandbox"}
    lots = [lot for lot in books.lots if lot.order_id not in sandbox and lot.order_id]
    lot_by_id = {lot.id: lot for lot in lots}
    duplicates = _duplicate_attempts(books)
    received = sum(a.amount_minor for a in books.attempts if a.status == "paid")
    second_payments = sum(a.amount_minor for a in books.attempts if a.status == "paid" and a.id in duplicates)
    refunded = sum(r.refund_minor for r in books.refunds if r.status == "succeeded")
    refunded_on_request = sum(r.refund_minor for r in books.refunds if r.status == "succeeded" and r.reason == REFUND_ON_REQUEST)
    earned_usage = earned_expired = earned_adjusted = clawed = Decimal(0)
    for lot_id, categories in _lot_draws(books).items():
        lot = lot_by_id.get(lot_id)
        if lot is None:
            continue
        earned_usage += categories.get("usage_charge", Decimal(0)) * lot.unit_value_minor
        earned_expired += categories.get("points_expired", Decimal(0)) * lot.unit_value_minor
        earned_adjusted += categories.get("manual_adjust", Decimal(0)) * lot.unit_value_minor
        clawed += categories.get("refund_clawback", Decimal(0)) * lot.unit_value_minor
    deferred = sum((lot.remaining * lot.unit_value_minor for lot in lots), Decimal(0))
    # What a refund gave back differs from what its points were worth by rounding, or by someone changing the amount.
    kept_on_refunds = clawed - refunded_on_request
    earned = earned_usage + earned_expired + earned_adjusted
    net = Decimal(received - second_payments - refunded_on_request)
    return {
        "received_minor": received, "refunded_minor": refunded, "second_payments_minor": second_payments,
        "second_payments_to_return_minor": second_payments - (refunded - refunded_on_request),
        "net_minor": net, "earned_minor": earned, "earned_usage_minor": earned_usage, "earned_expired_minor": earned_expired,
        "earned_adjusted_minor": earned_adjusted, "deferred_minor": deferred, "kept_on_refunds_minor": kept_on_refunds,
        "difference_minor": net - (earned + deferred + kept_on_refunds),
        # Points are worth a fraction of a fen, so each lot may round by up to a fen.
        "tolerance_minor": Decimal(len(lots)),
    }


def check_r9(books: Books) -> list[Finding]:
    position = money_position(books)
    if abs(position["difference_minor"]) <= position["tolerance_minor"]:
        return []
    return [Finding(
        "R9", "money_and_points_differ", CRITICAL, "all",
        f"净收 {position['net_minor']}", f"已确认+递延 {position['earned_minor'] + position['deferred_minor'] + position['kept_on_refunds_minor']}",
    )]


def check_r10(books: Books) -> list[Finding]:
    """Each manual money decision has its audit record, by someone allowed to, and asker and decider were two people."""
    found: list[Finding] = []
    audits = {(event.action, event.resource_id): event for event in books.audits}

    def check(reference: str, action: str, actor: str | None, permission: str, order_id: str | None = None) -> None:
        event = audits.get((action, reference))
        if event is None or event.actor_id != actor:
            found.append(Finding("R10", "no_audit_record", CRITICAL, f"{action}:{reference}", str(actor), str(event.actor_id) if event else "没有", order_id))
        elif permission not in permissions_for((event.details or {}).get("actor_roles") or ()):
            found.append(Finding("R10", "not_allowed_at_the_time", CRITICAL, f"{action}:{reference}", permission, ",".join((event.details or {}).get("actor_roles") or ()) or "无角色", order_id))

    for refund in books.refunds:
        if refund.reason != REFUND_ON_REQUEST:
            continue
        check(refund.id, "refund.request", refund.requested_by, REFUND_REQUEST, refund.order_id)
        if refund.approved_by:
            check(refund.id, "refund.approve", refund.approved_by, REFUND_APPROVE, refund.order_id)
            if refund.approved_by == refund.requested_by:
                found.append(Finding("R10", "same_person", CRITICAL, refund.id, "两个人", refund.approved_by, refund.order_id))
    for adjustment in books.adjustments:
        check(adjustment.id, "wallet.adjust_request", adjustment.requested_by, WALLET_ADJUST_REQUEST)
        if adjustment.approved_by:
            check(adjustment.id, "wallet.adjust_approve", adjustment.approved_by, WALLET_ADJUST_APPROVE)
            if adjustment.approved_by == adjustment.requested_by:
                found.append(Finding("R10", "same_person", CRITICAL, adjustment.id, "两个人", adjustment.approved_by))
    role_changes = {(event.resource_id, event.actor_id) for event in books.audits if event.action == "user.roles_change"}
    for grant in books.grants:
        # Grants with no one named came from the migration that created the table, not from a person.
        if grant.granted_by and (grant.user_id, grant.granted_by) not in role_changes:
            found.append(Finding("R10", "role_grant_not_audited", CRITICAL, f"{grant.user_id}:{grant.role}", grant.granted_by, "没有"))
    return found


async def _post_what_the_bill_shows(store: PlatformStore, channels: Mapping[str, PaymentChannel], books: Books) -> int:
    """A payment on the bill and not here is confirmed with the channel, then posted through the usual path."""
    attempts = {(item.provider, item.out_trade_no): item for item in books.attempts}
    posted = 0
    for row in books.rows:
        attempt = attempts.get((row.provider, row.out_trade_no))
        channel = channels.get(row.provider)
        if row.kind != "payment" or attempt is None or attempt.status == "paid" or channel is None:
            continue
        try:
            trade = await asyncio.to_thread(channel.query, attempt.out_trade_no)
            if trade.state == "paid":
                await store.apply_channel_payment(provider=row.provider, trade=trade, source="reconciliation")
                posted += 1
        except ChannelError as exc:
            logger.warning("对账补单查询失败 %s: %s", attempt.id, exc)
    return posted


async def fetch_bills(store: PlatformStore, channels: Mapping[str, PaymentChannel], now: datetime) -> list[Finding]:
    """The last few days' bills that are not here yet. A bill that arrives and cannot be read is a finding, not a gap."""
    found: list[Finding] = []
    today = _china_day(now)
    async with store.sessions() as session:
        have = {(row[0], row[1]) for row in (await session.execute(select(ChannelBill.provider, ChannelBill.bill_date))).all()}
    for name, channel in channels.items():
        for back in range(1, _BILL_DAYS_TO_TRY + 1):
            day = today - timedelta(days=back)
            if (name, day) in have:
                continue
            try:
                bill = await asyncio.to_thread(channel.download_bill, day)
            except BillNotReady as exc:
                logger.info("账单未就绪 %s %s: %s", name, day, exc)
                continue
            except ChannelError as exc:
                logger.warning("账单下载失败 %s %s: %s", name, day, exc)
                found.append(Finding("R1", "bill_unusable", WARNING, f"{name}:{day}", "可读的账单", str(exc)[:200]))
                continue
            await _save_bill(store, name, day, bill)
    return found


async def _save_bill(store: PlatformStore, provider: str, day: date, bill: Any) -> None:
    payments = [row for row in bill.rows if row.kind == "payment"]
    refunds = [row for row in bill.rows if row.kind == "refund"]
    record = ChannelBill(
        id=str(uuid4()), provider=provider, bill_date=day, sha256=hashlib.sha256(bill.raw).hexdigest(), row_count=len(bill.rows),
        paid_minor=sum(row.amount_minor for row in payments), refunded_minor=sum(row.amount_minor for row in refunds),
    )
    try:
        async with store.sessions() as session:
            async with session.begin():
                session.add(record)
                await session.flush()
                session.add_all(ChannelBillRow(
                    bill_id=record.id, provider=provider, kind=row.kind, out_trade_no=row.out_trade_no,
                    channel_trade_no=row.channel_trade_no, out_refund_no=row.out_refund_no, amount_minor=row.amount_minor,
                ) for row in bill.rows)
    except IntegrityError:
        pass  # another worker got there first


async def _record_findings(store: PlatformStore, run: ReconRun, rules: Sequence[str], findings: Sequence[Finding]) -> dict[str, Any]:
    """Open what is new, leave alone what someone already explained, and close what is no longer true."""
    now = datetime.now(timezone.utc)
    wanted = {finding.fingerprint: finding for finding in findings}
    new_critical = 0
    async with store.sessions() as session:
        async with session.begin():
            existing = (await session.scalars(select(ReconItem).where(ReconItem.rule.in_(rules)).order_by(ReconItem.created_at))).all()
            latest = {item.fingerprint: item for item in existing}
            for fingerprint, finding in wanted.items():
                item = latest.get(fingerprint)
                if item and item.status == "open":
                    item.last_run_id, item.severity, item.expected, item.actual = run.id, finding.severity, finding.expected[:200], finding.actual[:200]
                    continue
                unchanged = item and item.expected == finding.expected[:200] and item.actual == finding.actual[:200]
                if item and item.status in ("resolved", "ignored") and unchanged:
                    continue
                session.add(ReconItem(
                    fingerprint=fingerprint, rule=finding.rule, kind=finding.kind, severity=finding.severity, order_id=finding.order_id,
                    reference=finding.reference[:160], expected=finding.expected[:200], actual=finding.actual[:200],
                    first_run_id=run.id, last_run_id=run.id,
                ))
                if finding.severity == CRITICAL:
                    new_critical += 1
                    logger.error("对账严重差异 %s: %s %s", finding.rule, finding.kind, finding.reference)
            for item in existing:
                if item.status == "open" and item.fingerprint not in wanted:
                    item.status, item.resolved_at, item.resolution = "auto_resolved", now, "复核时已对上"
            if new_critical:
                session.add(AuditEvent(
                    actor_id=None, action="recon.critical", resource_type="recon_run", resource_id=run.id, details={"new": new_critical},
                ))
    return {"found": dict(Counter(finding.rule for finding in findings)), "new_critical": new_critical}


async def run_checks(
    store: PlatformStore, *, period: str, rules: Sequence[str], read_records: RecordsReader | None = None,
    channels: Mapping[str, PaymentChannel] | None = None, now: datetime | None = None,
) -> ReconRun | None:
    """One pass. None when this period has already been claimed, so several workers run it once between them."""
    moment = now or datetime.now(timezone.utc)
    active = get_payment_channels() if channels is None else channels
    run = ReconRun(id=str(uuid4()), period=period, rules=list(rules), started_at=moment)
    try:
        async with store.sessions() as session:
            session.add(run)
            await session.commit()
    except IntegrityError:
        return None
    try:
        findings: list[Finding] = []
        posted = 0
        if "R1" in rules:
            findings.extend(await fetch_bills(store, active, moment))
            posted = await _post_what_the_bill_shows(store, active, await load_books(store))
        books = await load_books(store)
        differences = await store.billing_differences(settled_before=moment - _SETTLING, sample=_NO_LIMIT)
        usage = None
        if "R6" in rules or "R7" in rules:
            task_ids = {charge.task_id for charge in books.charges if charge.task_id}
            records = await asyncio.to_thread(read_records, task_ids) if read_records and "R7" in rules else {}
            rates = await store.list_point_rates()
            usage = usage_differences(books.charges, rates, records, settled_before=moment - _SETTLING, sample=_NO_LIMIT)
        checks = {
            "R1": lambda: check_r1(books, _china_day(moment)), "R2": lambda: check_r2(books),
            "R4": lambda: check_r4(books, moment), "R8": lambda: check_r8(books, moment),
            "R9": lambda: check_r9(books), "R10": lambda: check_r10(books),
        }
        for rule in rules:
            if rule in checks:
                findings.extend(checks[rule]())
        wanted = check_r3_r5(differences)
        findings.extend(item for item in wanted if item.rule in rules)
        if "R5" in rules:
            findings.extend(check_r5_lots(books))
        if usage is not None:
            findings.extend(check_r6_r7(books, differences, usage, rules))
        summary = await _record_findings(store, run, rules, findings)
        summary["posted_from_bill"] = posted
        summary["sandbox_points_not_voided"] = differences["sandbox_points_not_voided"]
        status = "done"
    except Exception as exc:  # noqa: BLE001 - recorded on the run, and the next one tries again
        logger.exception("对账运行失败")
        summary, status = {"error": type(exc).__name__}, "failed"
    async with store.sessions() as session:
        await session.execute(
            update(ReconRun).where(ReconRun.id == run.id)
            .values(status=status, summary=summary, finished_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return await session.get(ReconRun, run.id)


async def resolve_item(store: PlatformStore, *, item_id: str, actor: Mapping, status: str, resolution: str) -> ReconItem:
    """A person's explanation. It changes nothing in the books: a correction is a separate adjustment, with two people."""
    if status not in ("resolved", "ignored"):
        raise ValueError("处理结果只能是已解决或忽略")
    if not resolution.strip():
        raise ValueError("必须填写处理原因")
    async with store.sessions() as session:
        item = await session.get(ReconItem, item_id)
        if not item:
            raise LookupError("差异单不存在")
        moved = await session.execute(
            update(ReconItem).where(ReconItem.id == item_id, ReconItem.status == "open").values(
                status=status, resolved_by=actor["user_id"], resolution=resolution[:500], resolved_at=datetime.now(timezone.utc),
            )
        )
        if moved.rowcount != 1:
            raise ValueError("差异单已处理")
        money_audit(session, actor, "recon.resolve", "recon_item", item_id, status=status, rule=item.rule, kind=item.kind, resolution=resolution[:200])
        await session.commit()
        await session.refresh(item)
        return item


async def run_loop(store: PlatformStore, read_records: RecordsReader | None = None) -> None:
    """Hourly for what can drift by itself; daily, once the channels have published, for everything."""
    while True:
        await asyncio.sleep(_LOOP_EVERY_SECONDS)
        try:
            moment = datetime.now(timezone.utc)
            local = moment.astimezone(CHINA)
            if (local.hour, local.minute) >= _DAILY_RUN_AFTER:
                await run_checks(store, period=f"daily:{local.date()}", rules=DAILY_RULES, read_records=read_records)
            await run_checks(store, period=f"hourly:{local:%Y-%m-%dT%H}", rules=HOURLY_RULES)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logger.warning("对账循环失败: %s", type(exc).__name__)


async def finance_summary(store: PlatformStore) -> dict[str, Any]:
    """Money in and out, what is earned and what is still owed in points, what the calls cost, and what is unexplained. In fen."""
    books = await load_books(store)
    position = money_position(books)
    lot_values = {lot.id: lot.unit_value_minor for lot in books.lots if lot.order_id}
    sandbox_orders = {order.id for order in books.orders if order.provider == "sandbox"}
    sandbox_lots = {lot.id for lot in books.lots if lot.order_id in sandbox_orders}

    def month(moment: datetime) -> str:
        return f"{_aware(moment).astimezone(CHINA):%Y-%m}"

    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for attempt in books.attempts:
        if attempt.status == "paid" and attempt.paid_at:
            months[month(attempt.paid_at)]["received_minor"] += attempt.amount_minor
    for refund in books.refunds:
        if refund.status == "succeeded" and refund.finished_at:
            months[month(refund.finished_at)]["refunded_minor"] += refund.refund_minor
    for entry in books.ledger:
        metadata = entry.metadata_json or {}
        if entry.direction != "debit" or entry.category == "refund_clawback":
            continue
        drawn = dict(metadata.get("lots") or {})
        if metadata.get("lot_id"):
            drawn[metadata["lot_id"]] = entry.amount
        for lot_id, amount in drawn.items():
            if lot_id in lot_values and lot_id not in sandbox_lots:
                months[month(entry.created_at)]["earned_minor"] += Decimal(str(amount)) * lot_values[lot_id]
    costs: dict[str, Decimal] = defaultdict(Decimal)
    for charge in books.charges:
        if charge.billing_mode == "charged" and charge.status == "success" and charge.reference_cost is not None:
            currency = charge.reference_currency or "CNY"
            costs[currency] += charge.reference_cost
            if currency == "CNY":
                months[month(charge.occurred_at)]["cost_cny_minor"] += charge.reference_cost * 100
    # Only comparable when every call's cost is known in the same currency as the income.
    margin = position["earned_usage_minor"] - costs.get("CNY", Decimal(0)) * 100 if set(costs) <= {"CNY"} else None
    async with store.sessions() as session:
        open_items = (await session.scalars(select(ReconItem).where(ReconItem.status == "open"))).all()
    return {
        **position,
        "reference_cost": dict(costs), "gross_margin_minor": margin,
        "by_month": [{"month": key, **{name: value for name, value in months[key].items()}} for key in sorted(months, reverse=True)],
        "open_items": dict(Counter(item.severity for item in open_items)),
        "bills": len(books.bills),
    }
