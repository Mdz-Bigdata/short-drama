# -*- coding: utf-8 -*-
"""How long a video prompt may be for the model it goes to, and what to cut when it is too long.

Every video model has a length past which it starts dropping information rather than
using it. A prompt is built from named sections; the sections that carry the shot
(locks, subject, action, camera) are never cut, and the rest come off in a fixed order —
sound, environment detail, lighting numbers, colour, effects, dialogue delivery notes —
until the prompt fits. A prompt still over budget after that stays over: the picture the table
wrote is what the clip is for, and cutting it silently films a different shot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.video_references import _normalize_model_token

# (alias, low, high) — matched longest-alias-first on the normalised model id.
MODEL_PROMPT_BUDGETS: tuple[tuple[str, int, int], ...] = (
    ("seedance2.5", 400, 900), ("seedance-2.5", 400, 900),
    ("seedance2.0", 200, 600), ("seedance-2.0", 200, 600), ("seedance", 200, 600), ("jimeng", 200, 400), ("即梦", 200, 400),
    ("kling", 300, 500), ("可灵", 300, 500),
    ("runway", 500, 800), ("veo", 400, 700), ("luma", 300, 500), ("pika", 200, 400), ("vidu", 200, 350),
    ("hailuo", 250, 400), ("minimax-h3", 400, 900), ("minimax h3", 400, 900), ("h3", 400, 900),
    ("libtv", 500, 1000), ("star video", 500, 1000),
)
DEFAULT_BUDGET = (200, 600)
# Sora takes prose of any length.
UNLIMITED_MODELS = ("sora",)

# Optional sections, first to go → last to go.
CUT_ORDER: tuple[str, ...] = ("sound", "environment", "light_numbers", "colour", "effects", "contact", "handoff", "dialogue_notes")
NEVER_CUT: frozenset[str] = frozenset({"style_lock", "locks", "anchors", "subject", "action", "camera", "dialogue", "rules"})
# Layers restated verbatim on every prompt: they do not count toward the body budget, the
# way lock tags do not count toward a picture description's length limit.
# 外貌简述一人至多 80 字、每镜重写，算作锁定层：预算再紧也不拿它顶数。
FIXED_SECTIONS: frozenset[str] = frozenset({
    "style_lock", "stage", "appearance", "quality", "anchor_cast", "anchor_costumes", "anchor_scene", "anchor_props", "anchors",
    "closing", "rules", "negatives",
})
_NUMBER_NOTE = re.compile(r"[（(][^（）()]*?(?:\d+K|\d+:\d+|\d+\s*mm|ISO\s*\d+|\d+\s*stop)[^（）()]*?[）)]")


def prompt_budget(model: str) -> int | None:
    """The upper character budget for ``model``; ``None`` when the model has no limit."""
    normalized = _normalize_model_token(model)
    if any(name in normalized for name in UNLIMITED_MODELS):
        return None
    ranked = sorted(MODEL_PROMPT_BUDGETS, key=lambda item: len(_normalize_model_token(item[0])), reverse=True)
    for alias, _low, high in ranked:
        if _normalize_model_token(alias) in normalized:
            return high
    return DEFAULT_BUDGET[1]


def prompt_length(text: str) -> int:
    """Characters that cost the model something: whitespace and layout do not count."""
    return len(re.sub(r"\s+", "", str(text or "")))


@dataclass
class PressureReport:
    """``length`` is the body (what the budget applies to); ``total_length`` includes the fixed layers."""

    model: str
    budget: int | None
    length: int
    tier: str                                # green | yellow | red | unlimited
    total_length: int = 0
    dropped: list[str] = field(default_factory=list)
    trimmed: list[str] = field(default_factory=list)
    # 正文经去重 / 精炼压短而不是逐段裁掉：内容都在，可能仍略超预算。
    distilled: bool = False

    @property
    def ratio(self) -> float | None:
        return None if not self.budget else round(self.length / self.budget, 2)

    def as_dict(self) -> dict:
        return {
            "model": self.model, "budget": self.budget, "length": self.length, "total_length": self.total_length,
            "ratio": self.ratio, "tier": self.tier, "dropped": list(self.dropped), "trimmed": list(self.trimmed),
            "distilled": self.distilled,
        }


def tier_for(length: int, budget: int | None) -> str:
    if budget is None:
        return "unlimited"
    if length <= budget * 0.8:
        return "green"
    if length <= budget:
        return "yellow"
    return "red"


def pressure(text: str, model: str) -> PressureReport:
    """Where ``text`` stands against the model's budget, without changing it."""
    budget = prompt_budget(model)
    length = prompt_length(text)
    return PressureReport(model=model, budget=budget, length=length, tier=tier_for(length, budget), total_length=length)


def compress(
    sections: Mapping[str, str], model: str, *, fixed: frozenset[str] = FIXED_SECTIONS,
    distill: Callable[[Mapping[str, str], int], Mapping[str, str] | None] | None = None,
) -> tuple[dict[str, str], PressureReport]:
    """Cut optional sections in ``CUT_ORDER`` until the body fits the model's budget.

    With ``distill(sections, budget)`` (see :mod:`app.core.prompt_distiller`) an over-budget body is
    condensed instead: the returned sections are used as they are and nothing is cut afterwards, even
    if they are still somewhat over budget — content comes first. ``None`` falls back to cutting.

    ``fixed`` sections are restated on every prompt and are not measured. Sections not in
    ``CUT_ORDER`` are never removed, the main picture description included. Lighting numbers are
    trimmed out of the light section before the section itself goes.
    """
    kept = {key: str(value or "") for key, value in sections.items()}
    budget = prompt_budget(model)
    report = PressureReport(model=model, budget=budget, length=0, tier="unlimited")

    def total() -> int:
        return sum(prompt_length(value) for key, value in kept.items() if key not in fixed)

    def everything() -> int:
        return sum(prompt_length(value) for value in kept.values())

    if budget is None:
        report.length, report.total_length = total(), everything()
        return kept, report
    if total() > budget and distill is not None:
        condensed = distill(dict(kept), budget)
        if condensed:
            kept = {key: str(value or "") for key, value in condensed.items()}
            report.distilled = True
            report.length, report.total_length = total(), everything()
            report.tier = tier_for(report.length, budget)
            return {key: value for key, value in kept.items() if value}, report
    for key in CUT_ORDER:
        if total() <= budget:
            break
        if key == "light_numbers":
            light = kept.get("light", "")
            trimmed = _NUMBER_NOTE.sub("", light)
            if trimmed != light:
                kept["light"] = trimmed
                report.trimmed.append("light")
            continue
        if kept.get(key):
            kept[key] = ""
            report.dropped.append(key)
    report.length, report.total_length = total(), everything()
    report.tier = tier_for(report.length, budget)
    return {key: value for key, value in kept.items() if value}, report


__all__ = [
    "CUT_ORDER", "DEFAULT_BUDGET", "FIXED_SECTIONS", "MODEL_PROMPT_BUDGETS", "NEVER_CUT",
    "PressureReport", "compress", "pressure", "prompt_budget", "prompt_length", "tier_for",
]
