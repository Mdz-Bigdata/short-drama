# -*- coding: utf-8 -*-
"""How long a video prompt may be for the model it goes to, and what to cut when it is too long.

Every video model has a length past which it starts dropping information rather than
using it. A prompt is built from named sections; the sections that carry the shot
(locks, subject, action, camera) are never cut, and the rest come off in a fixed order —
sound, environment detail, lighting numbers, colour, contact, handoff, dialogue delivery notes, effects —
until the prompt fits. A prompt still over budget after that stays over: the picture the table
wrote is what the clip is for, and cutting it silently films a different shot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core import clip_skeleton, prompt_data
from app.core.video_references import _normalize_model_token, video_native_audio

_DATA = "prompt_budget"
# (alias, low, high) — matched longest-alias-first on the normalised model id. The numbers live in
# app/data/prompt/prompt_budget.json (MiniMax H3 at its official 7000).
MODEL_PROMPT_BUDGETS: tuple[tuple[str, int, int], ...] = tuple(
    (str(alias), int(low), int(high)) for alias, low, high in prompt_data.value(_DATA, "budgets")
)
DEFAULT_BUDGET: tuple[int, int] = tuple(int(n) for n in prompt_data.value(_DATA, "default"))  # type: ignore[assignment]
# Sora takes prose of any length.
UNLIMITED_MODELS: tuple[str, ...] = prompt_data.words(_DATA, "unlimited")
# A model that makes its own sound reads the voices, lip sync and sound layers from these sections
# (prompt_distiller keeps them out of condensing and out of the measured body for such a model).
UNCUT_FOR_NATIVE_AUDIO: frozenset[str] = frozenset(prompt_data.words(_DATA, "uncut_for_native_audio"))

# Optional sections, first to go → last to go. 特效最后才裁：修仙、武侠镜头里特效就是这一镜要拍的东西，
# 裁掉它模型只拿到名字(或什么都没有)；没有特效的镜头这一节本来就是空的，不占预算。
CUT_ORDER: tuple[str, ...] = ("sound", "environment", "light_numbers", "colour", "contact", "handoff", "dialogue_notes", "motive", "effects")
NEVER_CUT: frozenset[str] = frozenset({"style_lock", "locks", "anchors", "subject", "action", "camera", "dialogue", "rules"})
# Layers restated verbatim on every prompt: they do not count toward the body budget, the
# way lock tags do not count toward a picture description's length limit.
# 外貌简述一人至多 80 字、每镜重写，算作锁定层：预算再紧也不拿它顶数。
FIXED_SECTIONS: frozenset[str] = frozenset({
    "style_lock", "stage", "appearance", "quality", "anchor_cast", "anchor_costumes", "anchor_scene", "anchor_props", "anchors",
    "closing", "rules", "negatives",
    # 骨架的固定句(段名、锚型定义、对白语言、表演锁、回合锁、禁令与结尾三段)同样每条重申。
    *clip_skeleton.SECTIONS,
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


def clip_budget(model: str, beats: int) -> int | None:
    """The budget of a clip made of ``beats`` moments: the per-shot budget times the moments, except for a model whose
    limit is its official limit on the whole prompt (MiniMax H3's 7000), which a longer clip does not raise."""
    budget = prompt_budget(model)
    if budget is None:
        return None
    normalized = _normalize_model_token(model)
    whole = any(_normalize_model_token(alias) in normalized for alias in prompt_data.words(_DATA, "whole_prompt_limits"))
    return budget if whole else budget * max(1, int(beats))


def hard_limit(model: str) -> int | None:
    """The most characters the provider takes for the whole prompt, negatives included (Seedance 2.0: 2000); None when unknown."""
    normalized = _normalize_model_token(model)
    ranked = sorted(prompt_data.value(_DATA, "hard_limits"), key=lambda item: len(_normalize_model_token(item[0])), reverse=True)
    for alias, limit in ranked:
        if _normalize_model_token(alias) in normalized:
            return int(limit)
    return None


_SENTENCE_END = re.compile(r"[。！？；.!?;\n]")


def sound_heads() -> tuple[str, ...]:
    """声音段的标题(【声音事件】【声音设计】…)：按前缀认，【声音设计·三层】也算。"""
    return prompt_data.words(_DATA, "hard_fit_keep_native_sound")


def fit_hard_limit(prompt: str, model: str, *, plain: str = "") -> tuple[str, list[str]]:
    """The prompt cut to the provider's hard limit, and what was taken out.

    ``plain`` is the same prompt without the gateway's enhancement words, the first thing to give up. Then the generic
    boilerplate goes in the order of ``hard_fit_drop`` (English negative lists, the English style lock, style and sheet
    rules, the picture-quality line …); the shot's own description stays. Still over: cut at a sentence end and put the
    lines that must close every prompt (portrait safety, 禁止出现, the global negatives) back at the end. A model that
    makes its own sound (Seedance 2.x) keeps its whole sound section too; only the picture text is cut.
    """
    limit = hard_limit(model)
    text = str(prompt or "")
    if limit is None or len(text) <= limit:
        return text, []
    removed: list[str] = []
    if plain and len(plain) < len(text):
        text, removed = plain, ["enhancement"]
    for index, pattern in enumerate(prompt_data.value(_DATA, "hard_fit_drop")):
        if len(text) <= limit:
            break
        shorter = re.sub(pattern, "", text)
        if shorter != text:
            # 删掉一段后留下的连接符、句读：行尾的「 + 」、「。，」。
            shorter = re.sub(r"(?m)[ \t]*\+[ \t]*$", "", shorter).replace("。，", "。")
            text = re.sub(r"\n{3,}", "\n\n", shorter)
            removed.append(f"drop{index + 1}")
    if len(text) > limit:
        keep_heads = prompt_data.words(_DATA, "hard_fit_keep_tail")
        # 出声的模型(Seedance 2.x)：声音段整段留着(标题行连同下面的行，到下一个【】标题为止)，只截画面正文。
        heads = sound_heads() if video_native_audio(model) else ()
        tail: list[str] = []
        sound: list[str] = []
        rest: list[str] = []
        in_sound = False
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith(keep_heads):
                tail.append(line)
                in_sound = False
            elif heads and stripped.startswith(heads):
                sound.append(line)
                in_sound = True
            elif in_sound and stripped and not stripped.startswith("【"):
                sound.append(line)
            else:
                in_sound = False
                rest.append(line)
        body = "\n".join(rest).rstrip()
        room = max(0, limit - sum(len(line) + 1 for line in [*sound, *tail]))
        head = body[:room]
        ends = [match.end() for match in _SENTENCE_END.finditer(head)]
        head = head[: ends[-1]] if ends and ends[-1] > room // 2 else head
        text = "\n".join([head.rstrip(), *sound, *tail])[:limit]
        removed.append("truncated")
    return text, removed


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


def fixed_for(model: str) -> frozenset[str]:
    """Sections not measured against ``model``'s budget: the restated lock layers, and for a model that makes its own
    sound (MiniMax H3, Seedance 2.x) the sound sections too — they are kept whole and do not compete with the picture."""
    return FIXED_SECTIONS | UNCUT_FOR_NATIVE_AUDIO if video_native_audio(model) else FIXED_SECTIONS


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
    if fixed is FIXED_SECTIONS:
        fixed = fixed_for(model)
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
        # 不计入预算的小节(出声模型的声音)裁了也不省字数，原样留着。
        if key in fixed:
            continue
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
    "CUT_ORDER", "DEFAULT_BUDGET", "clip_budget", "fit_hard_limit", "hard_limit", "FIXED_SECTIONS", "MODEL_PROMPT_BUDGETS", "NEVER_CUT", "UNCUT_FOR_NATIVE_AUDIO",
    "PressureReport", "compress", "pressure", "prompt_budget", "prompt_length", "tier_for",
]
