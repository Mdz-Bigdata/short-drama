"""Declared reference prices for provider models.

A price is a fact about a provider, not about this program, so none is written
into the code. Prices live in a JSON file the deployment maintains
(``MODEL_PRICING_PATH``, default ``backend/runtime/model_pricing.json``; see
``backend/app/data/model_pricing.example.json`` for the shape). A model without
an entry is "unpriced": its calls are still recorded, and estimates say so
instead of showing a low figure.

Every entry names one way of charging:

* ``per_million_tokens`` — text: ``input`` and ``output`` prices per million tokens
* ``per_image`` — one price per generated image, optionally by resolution
* ``per_second`` — video: one price per second of clip, optionally by resolution
* ``per_thousand_characters`` — speech: one price per thousand characters of text
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

from app import settings

logger = logging.getLogger("app.core.providers.pricing")

PriceKind = Literal["per_million_tokens", "per_image", "per_second", "per_thousand_characters"]
PRICE_KINDS: tuple[str, ...] = ("per_million_tokens", "per_image", "per_second", "per_thousand_characters")
DEFAULT_PRICING_FILE = settings.RUNTIME_DIR / "model_pricing.json"


@dataclass(frozen=True)
class PriceEntry:
    model: str
    kind: str
    currency: str = "CNY"
    # per_million_tokens
    input: float = 0.0
    output: float = 0.0
    # per_image / per_second / per_thousand_characters: a flat price, or one per resolution label
    price: float = 0.0
    by_resolution: Mapping[str, float] = field(default_factory=dict)

    def unit_price(self, resolution: str | None = None) -> float:
        if resolution and resolution in self.by_resolution:
            return float(self.by_resolution[resolution])
        return float(self.price)


class PricingTable:
    """Reference prices keyed by model id; lookups match the longest id that the model name contains."""

    def __init__(self, entries: Mapping[str, PriceEntry] | None = None) -> None:
        self._entries: dict[str, PriceEntry] = {key.lower(): value for key, value in (entries or {}).items()}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PricingTable":
        entries: dict[str, PriceEntry] = {}
        for model, spec in (raw or {}).items():
            if not isinstance(spec, Mapping) or spec.get("kind") not in PRICE_KINDS:
                logger.warning("[Pricing] 忽略无效定价条目: %s", model)
                continue
            try:
                entries[str(model)] = PriceEntry(
                    model=str(model),
                    kind=str(spec["kind"]),
                    currency=str(spec.get("currency") or "CNY").upper(),
                    input=float(spec.get("input") or 0.0),
                    output=float(spec.get("output") or 0.0),
                    price=float(spec.get("price") or 0.0),
                    by_resolution={str(k): float(v) for k, v in (spec.get("by_resolution") or {}).items()},
                )
            except (TypeError, ValueError):
                logger.warning("[Pricing] 定价条目数值无效: %s", model)
        return cls(entries)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "PricingTable":
        """The deployment's price file; an absent or unreadable file means every model is unpriced."""
        chosen = Path(path or os.getenv("MODEL_PRICING_PATH") or DEFAULT_PRICING_FILE)
        try:
            raw = json.loads(chosen.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as error:
            logger.warning("[Pricing] 无法读取定价文件 %s: %s", chosen, type(error).__name__)
            return cls()
        return cls.from_mapping(raw.get("models") if isinstance(raw, Mapping) and "models" in raw else raw)

    def lookup(self, model: str | None) -> PriceEntry | None:
        key = str(model or "").strip().lower()
        if not key:
            return None
        if key in self._entries:
            return self._entries[key]
        # "doubao-seedance-2-5-pro-250428" is priced by its "seedance-2-5" entry.
        matches = [entry for name, entry in self._entries.items() if name in key]
        return max(matches, key=lambda entry: len(entry.model)) if matches else None

    def cost(self, model: str | None, *, units: Mapping[str, Any]) -> tuple[float, str] | None:
        """Cost of one call in (amount, currency), or ``None`` when the model is unpriced."""
        entry = self.lookup(model)
        if entry is None:
            return None
        resolution = str(units.get("resolution") or "") or None
        if entry.kind == "per_million_tokens":
            tokens_in = float(units.get("input_tokens") or 0)
            tokens_out = float(units.get("output_tokens") or 0)
            return (tokens_in * entry.input + tokens_out * entry.output) / 1_000_000, entry.currency
        if entry.kind == "per_image":
            return float(units.get("images") or 1) * entry.unit_price(resolution), entry.currency
        if entry.kind == "per_second":
            return float(units.get("seconds") or 0) * entry.unit_price(resolution), entry.currency
        if entry.kind == "per_thousand_characters":
            return float(units.get("characters") or 0) / 1000 * entry.unit_price(resolution), entry.currency
        return None

    def __len__(self) -> int:
        return len(self._entries)


_table: PricingTable | None = None


def pricing_table() -> PricingTable:
    global _table
    if _table is None:
        _table = PricingTable.load()
    return _table


def set_pricing_table(table: PricingTable | None) -> None:
    """Tests install their own table; ``None`` goes back to the deployment's file."""
    global _table
    _table = table
