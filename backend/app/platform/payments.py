from __future__ import annotations

import hashlib
import hmac
import os


class PaymentSignatureError(ValueError):
    pass


def verify_webhook_signature(body: bytes, signature: str) -> None:
    secret = (os.getenv("PAYMENT_WEBHOOK_SECRET") or "").strip()
    if len(secret) < 32 or secret.upper().startswith("YOUR_"):
        raise PaymentSignatureError("支付回调密钥未配置")
    supplied = (signature or "").strip().lower()
    if len(supplied) != 64:
        raise PaymentSignatureError("支付回调签名无效")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise PaymentSignatureError("支付回调签名无效")
