# -*- coding: utf-8 -*-
"""对外报价：每个模型按官方价加一个固定比例(默认 20%)。

官方价在 ``runtime/model_pricing.json``(``providers.pricing``)，这里不另存一份价目：报价永远是官方价乘出来的，
官方价一改报价跟着改。加价比例读环境变量 ``QUOTE_MARKUP``(小数，0.2 就是加 20%)。没有官方价的模型报不了价，
在报价单和用量统计里单独列出，不猜。

对外和财务后台看到的金额一律是人民币：官方价按美元计的模型(ElevenLabs 等)按 ``data/prompt/spend_limits.json`` 的
``usd_to_cny`` 折成人民币再报，全项目只有这一个汇率(预算上限也用它)。别的外币没有汇率，原样保留并标出币种。
"""
from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping

from app.core import prompt_data
from app.core.providers.pricing import PriceEntry, PricingTable, pricing_table

DEFAULT_MARKUP = Decimal("0.20")
_STEP = Decimal("0.000001")


def markup() -> Decimal:
    """加价比例。写错(不是数、负数、十倍以上)按默认的 20% 算，不让一个手误把报价变成零或天价。"""
    raw = os.getenv("QUOTE_MARKUP")
    if raw is None or not raw.strip():
        return DEFAULT_MARKUP
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return DEFAULT_MARKUP
    return value if Decimal(0) <= value <= Decimal(10) else DEFAULT_MARKUP


def quoted(amount: Any) -> Decimal:
    """一笔官方价对外报多少。"""
    return (Decimal(str(amount or 0)) * (Decimal(1) + markup())).quantize(_STEP, rounding=ROUND_HALF_UP)


def usd_cny() -> Decimal:
    """一美元折多少人民币。数据文件里写坏了(不是正数)就当没有汇率：美元价原样保留，不按一个瞎猜的数折。"""
    try:
        rate = Decimal(str(prompt_data.value("spend_limits", "usd_to_cny")))
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return Decimal(0)
    return rate if rate.is_finite() and rate > 0 else Decimal(0)


def in_cny(amount: Any, currency: str | None) -> tuple[Decimal, str]:
    """一笔钱折成人民币(金额, 币种)。人民币原样；美元按汇率折；别的币种没有汇率，原样带着自己的币种回去。"""
    value = Decimal(str(amount or 0))
    code = str(currency or "CNY").upper()
    rate = usd_cny() if code == "USD" else Decimal(0)
    return (value * rate, "CNY") if rate else (value, code)


def _number(value: Decimal) -> float:
    return float(value)


def _prices(entry: PriceEntry, scale) -> dict[str, Any]:
    if entry.kind == "per_million_tokens":
        return {"input": _number(scale(entry.input)), "output": _number(scale(entry.output))}
    prices: dict[str, Any] = {"price": _number(scale(entry.price))}
    if entry.by_resolution:
        prices["by_resolution"] = {label: _number(scale(price)) for label, price in entry.by_resolution.items()}
    return prices


def price_list(table: PricingTable | None = None, *, with_official: bool = True) -> list[dict[str, Any]]:
    """每个有官方价的模型一行：计价方式、币种、对外报价；``with_official`` 时带上官方价(只给内部看)。"""
    rows: list[dict[str, Any]] = []
    for entry in (pricing_table() if table is None else table).entries():
        currency = in_cny(0, entry.currency)[1]
        yuan = lambda value, source=entry.currency: in_cny(value, source)[0]  # noqa: E731
        row: dict[str, Any] = {"model": entry.model, "kind": entry.kind, "currency": currency, "quote": _prices(entry, lambda value: quoted(yuan(value)))}
        if with_official:
            row["official"] = _prices(entry, lambda value: yuan(value).quantize(_STEP, rounding=ROUND_HALF_UP))
            # 只给内部看：这一行的官方价原本按什么币种计。
            row["priced_in"] = entry.currency
        rows.append(row)
    return sorted(rows, key=lambda row: (row["kind"], row["model"]))


def quote_for(model: str | None, units: Mapping[str, Any], table: PricingTable | None = None) -> tuple[Decimal, str] | None:
    """一次调用对外报多少(金额, 币种)；模型没有官方价时是 ``None``。"""
    cost = (pricing_table() if table is None else table).cost(model, units=units)
    if cost is None:
        return None
    amount, currency = in_cny(cost[0], cost[1])
    return quoted(amount), currency


__all__ = ["DEFAULT_MARKUP", "in_cny", "markup", "price_list", "quote_for", "quoted", "usd_cny"]
