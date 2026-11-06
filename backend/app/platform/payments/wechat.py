"""WeChat Pay Native over APIv3: a QR code link, settled by a signed and encrypted notification.

Only the WeChat Pay public key mode is supported; merchants still on platform certificates need to switch it on.
https://pay.weixin.qq.com/doc/v3/merchant/4012791877
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.platform.payments import keys
from app.platform.payments.base import (
    CLOSED,
    PAID,
    REFUND_FAILED,
    REFUND_NOT_RECEIVED,
    REFUND_PROCESSING,
    REFUND_SUCCEEDED,
    REFUNDED,
    UNPAID,
    ChannelError,
    BillNotReady,
    BillUnreadable,
    ChannelEvent,
    ChannelRefund,
    ChannelTrade,
    DayBill,
    NotificationRejected,
)
from app.platform.payments.bills import parse_wechat_trade_bill

API_ROOT = "https://api.mch.weixin.qq.com"
_BILL_HOSTS = {"api.mch.weixin.qq.com", "api2.mch.weixin.qq.com"}
#: How long a captured notification stays usable. A retry from WeChat is signed afresh.
_NOTIFICATION_WINDOW_SECONDS = 300
_TRADE_STATES = {"SUCCESS": PAID, "NOTPAY": UNPAID, "CLOSED": CLOSED, "REFUND": REFUNDED, "REVOKED": CLOSED, "PAYERROR": CLOSED}
_REFUND_STATES = {"SUCCESS": REFUND_SUCCEEDED, "PROCESSING": REFUND_PROCESSING, "CLOSED": REFUND_FAILED, "ABNORMAL": REFUND_FAILED}


@dataclass(frozen=True)
class WeChatPayConfig:
    mch_id: str
    app_id: str
    cert_serial: str
    private_key_path: str
    api_v3_key: str
    public_key_id: str
    public_key_path: str
    notify_url: str

    @classmethod
    def from_environment(cls, notify_base: str) -> "WeChatPayConfig | None":
        names = {
            "mch_id": "WECHATPAY_MCH_ID", "app_id": "WECHATPAY_APP_ID", "cert_serial": "WECHATPAY_CERT_SERIAL",
            "private_key_path": "WECHATPAY_PRIVATE_KEY_PATH", "api_v3_key": "WECHATPAY_API_V3_KEY",
            "public_key_id": "WECHATPAY_PUBLIC_KEY_ID", "public_key_path": "WECHATPAY_PUBLIC_KEY_PATH",
        }
        values = {field: (os.getenv(name) or "").strip() for field, name in names.items()}
        if not notify_base or not all(values.values()):
            return None
        return cls(notify_url=f"{notify_base}/api/billing/webhooks/wechat", **values)


def _trade(data: Mapping) -> ChannelTrade:
    amount = data.get("amount") or {}
    paid_at = data.get("success_time")
    return ChannelTrade(
        state=_TRADE_STATES.get(str(data.get("trade_state")), UNPAID),
        out_trade_no=str(data.get("out_trade_no") or ""),
        channel_trade_no=str(data.get("transaction_id") or "") or None,
        amount_minor=int(amount["total"]) if amount.get("total") is not None else None,
        currency=str(amount.get("currency") or "CNY"),
        merchant_id=f"{data.get('mchid') or ''}/{data.get('appid') or ''}",
        paid_at=datetime.fromisoformat(paid_at) if paid_at else None,
    )


class WeChatPay:
    name = "wechat"
    code_survives_close = False

    def __init__(self, config: WeChatPayConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        if len(config.api_v3_key.encode()) != 32:
            raise ChannelError("微信支付 APIv3 密钥必须是 32 字节")
        self._config = config
        self._private_key = keys.load_private_key(config.private_key_path)
        self._public_key = keys.load_public_key(config.public_key_path)
        self._client = httpx.Client(base_url=API_ROOT, timeout=15, transport=transport, trust_env=False)
        self.merchant_id = f"{config.mch_id}/{config.app_id}"

    def _authorization(self, method: str, path: str, body: str) -> str:
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode()
        signature = keys.sign(self._private_key, message)
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self._config.mch_id}",nonce_str="{nonce}",'
            f'signature="{signature}",timestamp="{timestamp}",serial_no="{self._config.cert_serial}"'
        )

    def _signed_by_wechat(self, headers: Mapping[str, str], body: bytes) -> bool:
        if headers.get("wechatpay-serial") != self._config.public_key_id:
            return False
        timestamp, nonce = headers.get("wechatpay-timestamp") or "", headers.get("wechatpay-nonce") or ""
        message = f"{timestamp}\n{nonce}\n".encode() + body + b"\n"
        return keys.verify(self._public_key, message, headers.get("wechatpay-signature") or "")

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
        try:
            response = self._client.request(
                method, path, content=body.encode() if body else None,
                headers={
                    "Authorization": self._authorization(method, path, body), "Accept": "application/json",
                    **({"Content-Type": "application/json"} if body else {}),
                },
            )
        except httpx.HTTPError as exc:
            raise ChannelError(f"微信支付请求失败: {type(exc).__name__}") from exc
        if response.status_code < 400 and not self._signed_by_wechat(response.headers, response.content):
            # An answer that cannot be shown to be from WeChat is discarded, as the docs require.
            raise ChannelError("微信支付应答验签失败")
        data = response.json() if response.content else {}
        return response.status_code, data if isinstance(data, dict) else {}

    def create_qr(self, *, out_trade_no: str, amount_minor: int, description: str, expires_at: datetime) -> str:
        status, data = self._request("POST", "/v3/pay/transactions/native", {
            "appid": self._config.app_id, "mchid": self._config.mch_id, "description": description[:127],
            "out_trade_no": out_trade_no, "notify_url": self._config.notify_url,
            "time_expire": expires_at.astimezone(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "amount": {"total": amount_minor, "currency": "CNY"},
        })
        if status >= 400 or not data.get("code_url"):
            raise ChannelError(f"微信支付下单失败: {data.get('code') or status}")
        return str(data["code_url"])

    def query(self, out_trade_no: str) -> ChannelTrade:
        status, data = self._request("GET", f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={self._config.mch_id}")
        if status == 404:
            return ChannelTrade(state=UNPAID, out_trade_no=out_trade_no)
        if status >= 400:
            raise ChannelError(f"微信支付查单失败: {data.get('code') or status}")
        return _trade(data)

    def close(self, out_trade_no: str) -> None:
        status, data = self._request("POST", f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close", {"mchid": self._config.mch_id})
        if status >= 400:
            raise ChannelError(f"微信支付关单失败: {data.get('code') or status}")

    def parse_notification(self, headers: Mapping[str, str], body: bytes) -> ChannelEvent:
        lowered = {key.lower(): value for key, value in headers.items()}
        # Probe signatures need no special case: they are verified like any other and fail like any other.
        if not self._signed_by_wechat(lowered, body):
            raise NotificationRejected("微信支付通知验签失败")
        try:
            sent_at = int(lowered.get("wechatpay-timestamp") or 0)
        except ValueError as exc:
            raise NotificationRejected("微信支付通知时间戳无效") from exc
        if abs(time.time() - sent_at) > _NOTIFICATION_WINDOW_SECONDS:
            raise NotificationRejected("微信支付通知已过期")
        try:
            envelope = json.loads(body)
            event_id = str(envelope.get("id") or "")
            if envelope.get("event_type") != "TRANSACTION.SUCCESS":
                return ChannelEvent(event_id=event_id, trade=None)
            resource = envelope["resource"]
            plain = AESGCM(self._config.api_v3_key.encode()).decrypt(
                resource["nonce"].encode(), base64.b64decode(resource["ciphertext"]),
                (resource.get("associated_data") or "").encode(),
            )
            return ChannelEvent(event_id=event_id, trade=_trade(json.loads(plain)))
        except (InvalidTag, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise NotificationRejected("微信支付通知无法解密") from exc

    def download_bill(self, day: date) -> DayBill:
        """https://pay.weixin.qq.com/doc/v3/merchant/4013071227 and /4013071238. The file itself comes unsigned; a hash covers it."""
        status, data = self._request("GET", f"/v3/bill/tradebill?bill_date={day.isoformat()}&bill_type=ALL")
        if status >= 400:
            if data.get("code") in ("NO_STATEMENT_EXIST", "STATEMENT_CREATING"):
                raise BillNotReady(f"微信账单尚未生成: {data['code']}")
            raise ChannelError(f"微信账单申请失败: {data.get('code') or status}")
        target = urlsplit(str(data.get("download_url") or ""))
        if target.scheme != "https" or target.hostname not in _BILL_HOSTS:
            # This request carries our signature, so it only ever goes to WeChat.
            raise ChannelError("微信账单下载地址不可信")
        path = f"{target.path}?{target.query}"
        try:
            response = self._client.get(path, headers={"Authorization": self._authorization("GET", path, ""), "Accept": "*/*"})
        except httpx.HTTPError as exc:
            raise ChannelError(f"微信账单下载失败: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ChannelError(f"微信账单下载失败: HTTP {response.status_code}")
        kind, expected = str(data.get("hash_type") or "").upper(), str(data.get("hash_value") or "").lower()
        if kind != "SHA1" or hashlib.sha1(response.content, usedforsecurity=False).hexdigest() != expected:
            raise BillUnreadable("微信账单哈希不一致，下载不完整")
        return DayBill(response.content, parse_wechat_trade_bill(response.content))

    def refund(self, *, out_trade_no: str, out_refund_no: str, refund_minor: int, total_minor: int, reason: str) -> ChannelRefund:
        status, data = self._request("POST", "/v3/refund/domestic/refunds", {
            "out_trade_no": out_trade_no, "out_refund_no": out_refund_no, "reason": reason[:80],
            "amount": {"refund": refund_minor, "total": total_minor, "currency": "CNY"},
        })
        if status >= 400:
            raise ChannelError(f"微信支付退款失败: {data.get('code') or status}")
        return ChannelRefund(_REFUND_STATES.get(str(data.get("status")), REFUND_PROCESSING), str(data.get("refund_id") or "") or None)

    def query_refund(self, *, out_trade_no: str, out_refund_no: str) -> ChannelRefund:
        status, data = self._request("GET", f"/v3/refund/domestic/refunds/{out_refund_no}")
        if status == 404:
            return ChannelRefund(REFUND_NOT_RECEIVED)
        if status >= 400:
            raise ChannelError(f"微信支付退款查询失败: {data.get('code') or status}")
        return ChannelRefund(_REFUND_STATES.get(str(data.get("status")), REFUND_PROCESSING), str(data.get("refund_id") or "") or None)
