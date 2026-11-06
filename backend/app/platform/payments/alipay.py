"""Alipay order-code payment: ``alipay.trade.precreate`` gives the QR code, a signed notification settles it.

https://opendocs.alipay.com/open/8ad49e4a_alipay.trade.precreate
https://opendocs.alipay.com/open/194/103296
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from app.platform.payments import keys
from app.platform.payments.base import (
    CLOSED,
    PAID,
    REFUND_NOT_RECEIVED,
    REFUND_PROCESSING,
    REFUND_SUCCEEDED,
    UNPAID,
    BillNotReady,
    ChannelError,
    ChannelEvent,
    ChannelRefund,
    ChannelTrade,
    DayBill,
    NotificationRejected,
)
from app.platform.payments.bills import parse_alipay_trade_bill

GATEWAY = "https://openapi.alipay.com/gateway.do"
_CHINA = timezone(timedelta(hours=8))
_TRADE_STATES = {"TRADE_SUCCESS": PAID, "TRADE_FINISHED": PAID, "WAIT_BUYER_PAY": UNPAID, "TRADE_CLOSED": CLOSED}
_NOT_YET_A_TRADE = "ACQ.TRADE_NOT_EXIST"  # a QR code nobody has scanned yet is not a trade
_NOT_ALLOWED_IN_SUBJECT = str.maketrans("", "", "/=&")


@dataclass(frozen=True)
class AlipayConfig:
    app_id: str
    seller_id: str
    private_key_path: str
    public_key_path: str
    notify_url: str
    gateway: str = GATEWAY

    @classmethod
    def from_environment(cls, notify_base: str) -> "AlipayConfig | None":
        names = {
            "app_id": "ALIPAY_APP_ID", "seller_id": "ALIPAY_SELLER_ID",
            "private_key_path": "ALIPAY_PRIVATE_KEY_PATH", "public_key_path": "ALIPAY_PUBLIC_KEY_PATH",
        }
        values = {field: (os.getenv(name) or "").strip() for field, name in names.items()}
        if not notify_base or not all(values.values()):
            return None
        return cls(
            notify_url=f"{notify_base}/api/billing/webhooks/alipay",
            gateway=(os.getenv("ALIPAY_GATEWAY") or GATEWAY).strip(), **values,
        )


def _to_minor(yuan: object) -> int | None:
    """None for anything that is not a whole number of fen: rounding would make a wrong amount look right."""
    try:
        fen = Decimal(str(yuan)) * 100
        return int(fen) if fen.is_finite() and fen == fen.to_integral_value() else None
    except (InvalidOperation, ValueError):
        return None


def _paid_at(text: object) -> datetime | None:
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_CHINA)
    except ValueError:
        return None


def signing_string(params: Mapping[str, str]) -> bytes:
    return "&".join(f"{key}={params[key]}" for key in sorted(params)).encode()


def signed_part_of_response(raw: str, response_key: str) -> str | None:
    """The bytes the signature covers: the object under ``xxx_response``, exactly as sent."""
    start = raw.find(f'"{response_key}"')
    end = raw.rfind('"sign"')
    if start < 0 or end < start:
        return None
    return raw[raw.index("{", start):raw.rindex("}", 0, end) + 1]


class Alipay:
    name = "alipay"
    # A code is good for two hours and takes no shorter limit. One nobody has scanned is not a trade yet, so closing it
    # does nothing and it can still be paid.
    code_survives_close = True

    def __init__(self, config: AlipayConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._private_key = keys.load_private_key(config.private_key_path)
        self._public_key = keys.load_public_key(config.public_key_path)
        self._client = httpx.Client(timeout=15, transport=transport, trust_env=False)
        self.merchant_id = f"{config.seller_id}/{config.app_id}"

    def _call(self, method: str, biz: dict, *, notify: bool = False) -> dict:
        params = {
            "app_id": self._config.app_id, "method": method, "format": "JSON", "charset": "utf-8", "sign_type": "RSA2",
            "timestamp": datetime.now(_CHINA).strftime("%Y-%m-%d %H:%M:%S"), "version": "1.0",
            **({"notify_url": self._config.notify_url} if notify else {}),
        }
        content = json.dumps(biz, ensure_ascii=False, separators=(",", ":"))
        signature = keys.sign(self._private_key, signing_string({**params, "biz_content": content}))
        try:
            response = self._client.post(
                f"{self._config.gateway}?{urlencode({**params, 'sign': signature})}",
                data={"biz_content": content},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            )
        except httpx.HTTPError as exc:
            raise ChannelError(f"支付宝请求失败: {type(exc).__name__}") from exc
        raw = response.text
        key = method.replace(".", "_") + "_response"
        try:
            envelope = json.loads(raw)
        except ValueError as exc:
            raise ChannelError(f"支付宝应答无法解析: HTTP {response.status_code}") from exc
        answer = envelope.get(key)
        if not isinstance(answer, dict):
            raise ChannelError(f"支付宝应答异常: {str((envelope.get('error_response') or {}).get('sub_code') or 'unknown')}")
        part = signed_part_of_response(raw, key)
        if not part or not keys.verify(self._public_key, part.encode(), str(envelope.get("sign") or "")):
            raise ChannelError("支付宝应答验签失败")
        return answer

    @staticmethod
    def _failed(answer: dict, what: str) -> ChannelError:
        return ChannelError(f"支付宝{what}失败: {answer.get('sub_code') or answer.get('code')}")

    def create_qr(self, *, out_trade_no: str, amount_minor: int, description: str, expires_at: datetime) -> str:
        answer = self._call("alipay.trade.precreate", {
            "out_trade_no": out_trade_no, "total_amount": f"{Decimal(amount_minor) / 100:.2f}",
            "subject": description.translate(_NOT_ALLOWED_IN_SUBJECT)[:256], "product_code": "QR_CODE_OFFLINE",
        }, notify=True)
        if answer.get("code") != "10000" or not answer.get("qr_code"):
            raise self._failed(answer, "下单")
        return str(answer["qr_code"])

    def query(self, out_trade_no: str) -> ChannelTrade:
        answer = self._call("alipay.trade.query", {"out_trade_no": out_trade_no})
        if answer.get("sub_code") == _NOT_YET_A_TRADE:
            return ChannelTrade(state=UNPAID, out_trade_no=out_trade_no)
        if answer.get("code") != "10000":
            raise self._failed(answer, "查单")
        return ChannelTrade(
            state=_TRADE_STATES.get(str(answer.get("trade_status")), UNPAID),
            out_trade_no=str(answer.get("out_trade_no") or out_trade_no),
            channel_trade_no=str(answer.get("trade_no") or "") or None,
            amount_minor=_to_minor(answer.get("total_amount")),
            # A query answer does not name the seller; this merchant's own credentials asked for it.
            merchant_id=self.merchant_id,
            paid_at=_paid_at(answer.get("send_pay_date")),
        )

    def close(self, out_trade_no: str) -> None:
        answer = self._call("alipay.trade.close", {"out_trade_no": out_trade_no})
        if answer.get("code") == "10000" or answer.get("sub_code") == _NOT_YET_A_TRADE:
            return
        raise self._failed(answer, "关单")

    def parse_notification(self, headers: Mapping[str, str], body: bytes) -> ChannelEvent:
        try:
            params = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True))
        except ValueError as exc:
            raise NotificationRejected("支付宝通知格式无效") from exc
        signature = params.pop("sign", "")
        params.pop("sign_type", None)
        if not signature or not keys.verify(self._public_key, signing_string(params), signature):
            raise NotificationRejected("支付宝通知验签失败")
        return ChannelEvent(
            event_id=params.get("notify_id") or "",
            trade=ChannelTrade(
                state=_TRADE_STATES.get(params.get("trade_status") or "", UNPAID),
                out_trade_no=params.get("out_trade_no") or "",
                channel_trade_no=params.get("trade_no") or None,
                amount_minor=_to_minor(params.get("total_amount")),
                # seller_id is optional in a notification. When it is there it has to match; app_id always does.
                merchant_id=f"{params.get('seller_id') or self._config.seller_id}/{params.get('app_id') or ''}",
                paid_at=_paid_at(params.get("gmt_payment")),
            ),
        )

    def download_bill(self, day: date) -> DayBill:
        """https://opendocs.alipay.com/open/028woc. The link is good for 30 seconds and the file is unsigned."""
        answer = self._call("alipay.data.dataservice.bill.downloadurl.query", {"bill_type": "trade", "bill_date": day.isoformat()})
        if answer.get("code") != "10000" or not answer.get("bill_download_url"):
            # The documentation names no code for "not generated yet", so any refusal is retried until it counts as missing.
            raise BillNotReady(f"支付宝账单暂不可用: {answer.get('sub_code') or answer.get('code')}")
        target = urlsplit(str(answer["bill_download_url"]))
        host = target.hostname or ""
        if target.scheme not in ("http", "https") or not (host == "alipay.com" or host.endswith(".alipay.com")):
            raise ChannelError("支付宝账单下载地址不可信")
        try:
            response = self._client.get(str(answer["bill_download_url"]))
        except httpx.HTTPError as exc:
            raise ChannelError(f"支付宝账单下载失败: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ChannelError(f"支付宝账单下载失败: HTTP {response.status_code}")
        return DayBill(response.content, parse_alipay_trade_bill(response.content))

    def refund(self, *, out_trade_no: str, out_refund_no: str, refund_minor: int, total_minor: int, reason: str) -> ChannelRefund:
        answer = self._call("alipay.trade.refund", {
            "out_trade_no": out_trade_no, "out_request_no": out_refund_no,
            "refund_amount": f"{Decimal(refund_minor) / 100:.2f}", "refund_reason": reason[:256],
        })
        if answer.get("code") != "10000":
            raise self._failed(answer, "退款")
        return ChannelRefund(REFUND_SUCCEEDED if answer.get("fund_change") == "Y" else REFUND_PROCESSING, str(answer.get("trade_no") or "") or None)

    def query_refund(self, *, out_trade_no: str, out_refund_no: str) -> ChannelRefund:
        answer = self._call("alipay.trade.fastpay.refund.query", {"out_trade_no": out_trade_no, "out_request_no": out_refund_no})
        if answer.get("code") != "10000":
            raise self._failed(answer, "退款查询")
        # 10000 only means the query worked. Without REFUND_SUCCESS the refund did not happen, and the docs say to resend it.
        return ChannelRefund(REFUND_SUCCEEDED if answer.get("refund_status") == "REFUND_SUCCESS" else REFUND_NOT_RECEIVED, str(answer.get("trade_no") or "") or None)
