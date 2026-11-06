"""Taking points for model calls: a hold before the call, the real amount after it, nothing for a call that failed.

Provider calls run on worker threads with no event loop, so this has its own synchronous connection. Every change to a
balance is one transaction with a conditional update, so two calls cannot spend the same points.

It only exists while ``BILLING_ENFORCE`` is on. Off, calls are recorded by ``usage_billing`` and nothing is charged.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.platform.entitlements import UNLIMITED, entitlements_from, resolution_allowed
from app.platform.models import LedgerEntry, MembershipTerm, PlatformUser, PointBalance, PointHold, PointLot, PointRate, UserRole
from app.platform.usage_billing import FREE_PROVIDERS, find_rate, points_for

logger = logging.getLogger("app.platform.billing_book")

HOLD_MINUTES = 120
_RATES_TTL_SECONDS = 30.0
_ROLES_TTL_SECONDS = 60.0
_ACCOUNT_TTL_SECONDS = 60.0
#: The tier a video rate with no resolution means. Anything above it needs a rate of its own, or it would be sold cheap.
_BASE_VIDEO_RESOLUTION = "768p"
#: Measured on a real project: 2.63M tokens for 4.83M characters of prompt, about 4,200 tokens answered per call.
_TOKENS_PER_CHAR = 0.6
_ESTIMATED_OUTPUT_TOKENS = 4000

CHARGED = "charged"
EXEMPT = "exempt"
ABSORBED = "operator_absorbed"


class BillingRefused(BaseException):
    """A paid call that must not happen.

    A BaseException, as ``asyncio.CancelledError`` is: this code is full of ``except Exception`` that turn a failed
    model call into a fallback or a retry, and a refusal must not be mistaken for either. It stops the work and reaches
    the top, where the stage or the request reports it.
    """

    def __init__(self, code: str, detail: str, *, required: int | None = None, available: int | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.required, self.available = code, detail, required, available


@dataclass
class Handle:
    mode: str
    hold_id: str | None = None
    user_id: str | None = None
    amount: Decimal = field(default_factory=lambda: Decimal(0))
    rate: Any = None


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1).replace("sqlite+aiosqlite://", "sqlite://", 1)


def _estimated_units(rate: Any, units: Mapping[str, Any]) -> dict[str, Any]:
    if rate.kind != "per_million_tokens":
        return dict(units)
    return {
        "input_tokens": math.ceil(float(units.get("input_chars") or 0) * _TOKENS_PER_CHAR),
        "output_tokens": _ESTIMATED_OUTPUT_TOKENS,
    }


class BillingBook:
    def __init__(self, database_url: str, owner_of: Callable[[str], str | None]) -> None:
        sync_url = _sync_url(database_url)
        options = {"connect_args": {"timeout": 30}} if sync_url.startswith("sqlite") else {"pool_pre_ping": True}
        self.engine = create_engine(sync_url, **options)
        if sync_url.startswith("sqlite"):
            event.listen(self.engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
        self._owner_of = owner_of
        self._owners: dict[str, str | None] = {}
        self._rates: tuple[float, list[PointRate]] = (0.0, [])
        self._staff: dict[str, tuple[float, bool]] = {}
        self._accounts: dict[str, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self.engine.dispose()

    def _current_rates(self) -> list[PointRate]:
        with self._lock:
            loaded_at, rates = self._rates
        if time.monotonic() - loaded_at < _RATES_TTL_SECONDS and rates:
            return rates
        with Session(self.engine, expire_on_commit=False) as session:
            rates = list(session.scalars(select(PointRate)).all())
        with self._lock:
            self._rates = (time.monotonic(), rates)
        return rates

    def _is_staff(self, user_id: str) -> bool:
        with self._lock:
            known = self._staff.get(user_id)
        if known and time.monotonic() - known[0] < _ROLES_TTL_SECONDS:
            return known[1]
        with Session(self.engine) as session:
            staff = session.scalar(select(UserRole.role).where(UserRole.user_id == user_id).limit(1)) is not None
        with self._lock:
            self._staff[user_id] = (time.monotonic(), staff)
        return staff

    def _account_open(self, user_id: str) -> bool:
        with self._lock:
            known = self._accounts.get(user_id)
        if known and time.monotonic() - known[0] < _ACCOUNT_TTL_SECONDS:
            return known[1]
        try:
            with Session(self.engine) as session:
                status = session.scalar(select(PlatformUser.status).where(PlatformUser.id == user_id))
        except SQLAlchemyError as exc:
            # A database hiccup should not stop every generation in the system. The account was checked at login.
            logger.warning("[Billing] 账号状态查询失败，本次放行: %s", type(exc).__name__)
            return True
        is_open = status in (None, "active")  # an owner with no account record is older than accounts
        with self._lock:
            self._accounts[user_id] = (time.monotonic(), is_open)
        return is_open

    def forget_account(self, user_id: str) -> None:
        with self._lock:
            self._accounts.pop(user_id, None)

    def require_open_account(self, user_id: str) -> None:
        if not self._account_open(user_id):
            raise BillingRefused("account_closed", "账号已停用，不能继续生成。")

    def _task_owner(self, task_id: str | None) -> str | None:
        if not task_id:
            return None
        with self._lock:
            if task_id in self._owners:
                return self._owners[task_id]
        owner = self._owner_of(task_id)
        if owner:
            with self._lock:
                self._owners[task_id] = owner
        return owner

    def _entitlements(self, user_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            terms = list(session.scalars(select(MembershipTerm).where(MembershipTerm.user_id == user_id)).all())
        return entitlements_from(terms, datetime.now(timezone.utc))

    def require_feature(self, user_id: str, feature: str, *, current: int | None = None) -> None:
        """Refuses what the plan does not include. ``current`` is how many are in use, for a limit."""
        if self._is_staff(user_id):
            return
        granted = self._entitlements(user_id).get(feature)
        if current is not None:
            if granted != UNLIMITED and current >= int(granted or 0):
                raise BillingRefused("feature_not_in_plan", f"当前套餐最多 {granted} 个，已用 {current} 个。请升级套餐。")
        elif not granted:
            raise BillingRefused("feature_not_in_plan", "当前套餐不包含这项功能。请升级套餐。")

    def _payer(self, task_id: str | None, user_id: str | None) -> tuple[str | None, str | None]:
        """(who pays, who is working on someone else's project)."""
        owner = self._task_owner(task_id)
        if owner:
            return owner, user_id if user_id and user_id != owner else None
        return user_id, None

    def _price(self, payer: str, media_type: str, model: str, units: Mapping[str, Any]) -> tuple[Any, Decimal]:
        resolution = str(units.get("resolution") or "").strip().lower()
        rate = find_rate(self._current_rates(), model, resolution or None, datetime.now(timezone.utc))
        needs_own_rate = media_type == "video" and resolution and resolution != _BASE_VIDEO_RESOLUTION
        if rate is None or (needs_own_rate and rate.resolution != resolution):
            raise BillingRefused("rate_missing", f"模型 {model or '（未指定）'} 暂未开放使用。")
        if media_type == "video" and resolution and not resolution_allowed(self._entitlements(payer), resolution):
            raise BillingRefused("feature_not_in_plan", f"当前套餐不支持 {resolution} 视频。请升级套餐。")
        amount = points_for(rate, _estimated_units(rate, units))
        if amount <= 0:  # nothing to measure it by: it would go out free
            raise BillingRefused("rate_missing", f"模型 {model or '（未指定）'} 暂未开放使用。")
        return rate, amount

    def preflight(self, *, task_id: str, user_id: str | None, media_type: str, model: str, units: Mapping[str, Any]) -> None:
        """Before a batch: can the whole of it be paid for? Then none of it starts and fails half way."""
        payer, operator = self._payer(task_id, user_id)
        if not payer:
            raise BillingRefused("unattributed", "这次调用无法确定付费账号，已拒绝。")
        self.require_open_account(payer)
        if operator or self._is_staff(payer):
            return
        _rate, required = self._price(payer, media_type, model, units)
        with Session(self.engine) as session:
            balance = session.get(PointBalance, payer)
            available = balance.available if balance else Decimal(0)
        if available < required:
            raise self._insufficient(required, available)

    @staticmethod
    def _insufficient(required: Decimal, available: Decimal) -> BillingRefused:
        need, have = math.ceil(required), math.floor(available)
        return BillingRefused(
            "insufficient_points", f"积分不足：这一步预计需要 {need} 积分，当前可用 {have}。请到会员与支付中心充值后继续。",
            required=need, available=have,
        )

    def reserve(
        self, *, media_type: str, provider: str, model: str, units: Mapping[str, Any], task_id: str | None, user_id: str | None,
    ) -> Handle | None:
        """Before a provider call. Returns what to settle afterwards, or raises and the call never goes out."""
        if provider in FREE_PROVIDERS:
            return None
        payer, operator = self._payer(task_id, user_id)
        if not payer:
            logger.error("[Billing] 无法确定付费账号，已拒绝调用: model=%s task=%s", model, task_id)
            raise BillingRefused("unattributed", "这次调用无法确定付费账号，已拒绝。")
        self.require_open_account(payer)
        if operator:
            return Handle(ABSORBED)
        if self._is_staff(payer):
            return Handle(EXEMPT)
        rate, amount = self._price(payer, media_type, model, units)
        hold_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            moved = session.execute(
                update(PointBalance)
                .where(PointBalance.user_id == payer, PointBalance.available >= amount)
                .values(available=PointBalance.available - amount, held=PointBalance.held + amount)
            )
            if moved.rowcount != 1:
                balance = session.get(PointBalance, payer)
                raise self._insufficient(amount, balance.available if balance else Decimal(0))
            session.add(PointHold(
                id=hold_id, user_id=payer, task_id=task_id, model=model[:160], amount=amount,
                status="active", expires_at=now + timedelta(minutes=HOLD_MINUTES),
            ))
        return Handle(CHARGED, hold_id=hold_id, user_id=payer, amount=amount, rate=rate)

    def settle(self, handle: Handle, entry: Mapping[str, Any]) -> None:
        """After the call: the real amount for a success, nothing for a failure, and the rest of the hold goes back."""
        if handle.mode != CHARGED:
            return
        succeeded = entry.get("status") == "success"
        units = dict(entry.get("units") or {})
        owed = points_for(handle.rate, units) if succeeded else Decimal(0)
        usage_id = str(entry.get("id"))
        with Session(self.engine) as session, session.begin():
            closed = session.execute(
                update(PointHold).where(PointHold.id == handle.hold_id, PointHold.status == "active")
                .values(status="settled", usage_id=usage_id, captured=owed)
            )
            if closed.rowcount != 1:
                # Released as stale while the call ran: the points went back, so this is a fresh debit.
                session.execute(update(PointHold).where(PointHold.id == handle.hold_id).values(usage_id=usage_id, captured=owed))
                held_back = Decimal(0)
            else:
                held_back = handle.amount
            balance = session.get(PointBalance, handle.user_id, with_for_update=True)
            taken = min(owed, balance.available + held_back)
            balance.held -= held_back
            balance.available += held_back - taken
            if taken <= 0 and owed <= 0:
                return
            lots = session.scalars(
                select(PointLot).where(PointLot.user_id == handle.user_id, PointLot.remaining > PointLot.frozen)
                .order_by(PointLot.expires_at, PointLot.created_at).with_for_update()
            ).all()
            left, drawn = taken, {}
            for lot in lots:
                if left <= 0:
                    break
                part = min(left, lot.remaining - lot.frozen)
                lot.remaining -= part
                left -= part
                drawn[lot.id] = str(part)
            session.add(LedgerEntry(
                user_id=handle.user_id, asset="points", direction="debit", amount=taken, currency="PTS",
                category="usage_charge", idempotency_key=f"usage:{usage_id}",
                metadata_json={
                    "usage_id": usage_id, "hold_id": handle.hold_id, "model": str(entry.get("model") or ""),
                    "owed": str(owed), "shortfall": str(owed - taken), "lots": drawn,
                },
            ))
        if owed > taken:
            logger.warning("[Billing] 实际用量超出余额: usage=%s user=%s shortfall=%s", usage_id, handle.user_id, owed - taken)

    def release_stale(self) -> int:
        """Holds left by a process that died. What they held goes back; whatever already settled is untouched."""
        now, released = datetime.now(timezone.utc), 0
        with Session(self.engine) as session:
            stale = list(session.scalars(select(PointHold).where(PointHold.status == "active", PointHold.expires_at < now)).all())
        for hold in stale:
            with Session(self.engine) as session, session.begin():
                closed = session.execute(
                    update(PointHold).where(PointHold.id == hold.id, PointHold.status == "active").values(status="released")
                )
                if closed.rowcount == 1:
                    session.execute(
                        update(PointBalance).where(PointBalance.user_id == hold.user_id)
                        .values(available=PointBalance.available + hold.amount, held=PointBalance.held - hold.amount)
                    )
                    released += 1
        return released


class AccountGuard:
    """With charging off nothing is taken, but a closed account must still not spend the operator's money."""

    def __init__(self, book: BillingBook) -> None:
        self._book = book

    def reserve(self, *, media_type: str, provider: str, model: str, units: Mapping[str, Any], task_id: str | None, user_id: str | None) -> None:
        if provider in FREE_PROVIDERS:
            return None
        payer, _operator = self._book._payer(task_id, user_id)
        if payer:
            self._book.require_open_account(payer)
        return None

    def settle(self, handle: Any, entry: Mapping[str, Any]) -> None:
        return None


_active: BillingBook | None = None
_watching: BillingBook | None = None


def set_account_watcher(book: BillingBook | None) -> None:
    global _watching
    _watching = book


def account_status_changed(user_id: str) -> None:
    """So this process acts on it now. Any other process catches up within a minute."""
    if _watching is not None:
        _watching.forget_account(user_id)




def set_active_book(book: BillingBook | None) -> None:
    global _active
    _active = book


def active_book() -> BillingBook | None:
    """The book while charging is on; otherwise None, and nothing is limited or taken."""
    return _active
