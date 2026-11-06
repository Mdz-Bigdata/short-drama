"""The payment channels this deployment is configured for. A channel with missing settings is simply not offered."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.platform.payments.alipay import Alipay, AlipayConfig
from app.platform.payments.base import ChannelError, PaymentChannel
from app.platform.payments.wechat import WeChatPay, WeChatPayConfig

logger = logging.getLogger("app.platform.payments")


@lru_cache(maxsize=1)
def get_payment_channels() -> dict[str, PaymentChannel]:
    notify_base = (os.getenv("PAYMENT_NOTIFY_BASE_URL") or "").strip().rstrip("/")
    channels: dict[str, PaymentChannel] = {}
    if notify_base and not notify_base.startswith("https://"):
        logger.error("PAYMENT_NOTIFY_BASE_URL 必须是 https 地址，支付渠道未启用")
        return channels
    for name, config, build in (
        ("wechat", WeChatPayConfig.from_environment(notify_base), WeChatPay),
        ("alipay", AlipayConfig.from_environment(notify_base), Alipay),
    ):
        if config is None:
            continue
        try:
            channels[name] = build(config)
        except (ChannelError, OSError, ValueError, TypeError) as exc:
            # Named by kind only: the message from a key loader is not something to put in a log.
            logger.error("支付渠道 %s 配置无效，未启用: %s", name, type(exc).__name__)
    return channels
