"""What every payment channel provides, in this system's own terms: money in fen, states in our own words."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Protocol


class ChannelError(RuntimeError):
    """The channel could not be reached or said no. The message is safe to log; it never holds a key."""


class NotificationRejected(ValueError):
    """Failed verification. Not from the channel, as far as anyone can tell: nothing may be done with it."""


# A trade's state.
PAID = "paid"
UNPAID = "unpaid"
CLOSED = "closed"
REFUNDED = "refunded"

# A refund's state. "pending" means the channel has no record of it: send it again, same number, same amount.
REFUND_NOT_RECEIVED = "pending"
REFUND_PROCESSING = "processing"
REFUND_SUCCEEDED = "succeeded"
REFUND_FAILED = "failed"


@dataclass(frozen=True)
class ChannelTrade:
    state: str
    out_trade_no: str
    channel_trade_no: str | None = None
    amount_minor: int | None = None
    currency: str = "CNY"
    merchant_id: str = ""
    paid_at: datetime | None = None


@dataclass(frozen=True)
class ChannelEvent:
    """A verified notification. ``trade`` is None for a kind of event this system has no use for."""

    event_id: str
    trade: ChannelTrade | None


@dataclass(frozen=True)
class BillRow:
    kind: str  # "payment" or "refund"
    out_trade_no: str
    amount_minor: int
    channel_trade_no: str = ""
    out_refund_no: str = ""


@dataclass(frozen=True)
class DayBill:
    """What a channel says happened on one day. ``raw`` is kept only long enough to be fingerprinted."""

    raw: bytes
    rows: tuple[BillRow, ...]


class BillNotReady(ChannelError):
    """Nothing to read yet. Channels publish yesterday's bill the next morning."""


class BillUnreadable(ChannelError):
    """A bill arrived and cannot be trusted. Treating it as empty would hide every payment on it."""


@dataclass(frozen=True)
class ChannelRefund:
    state: str
    channel_refund_no: str | None = None
    detail: str = ""


class PaymentChannel(Protocol):
    name: str
    merchant_id: str
    #: Whether a code can still be paid after being closed, and so has to keep being asked about.
    code_survives_close: bool

    def create_qr(self, *, out_trade_no: str, amount_minor: int, description: str, expires_at: datetime) -> str: ...

    def query(self, out_trade_no: str) -> ChannelTrade: ...

    def close(self, out_trade_no: str) -> None: ...

    def parse_notification(self, headers: Mapping[str, str], body: bytes) -> ChannelEvent: ...

    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_minor: int, total_minor: int, reason: str,
    ) -> ChannelRefund: ...

    def query_refund(self, *, out_trade_no: str, out_refund_no: str) -> ChannelRefund: ...

    def download_bill(self, day: date) -> DayBill: ...


def new_merchant_no(prefix: str) -> str:
    """Up to 31 characters and only letters and digits: WeChat allows 32 at most, and a UUID is 36."""
    return f"{prefix}{datetime.now(timezone.utc):%Y%m%d%H%M%S}{secrets.token_hex(8)}"
