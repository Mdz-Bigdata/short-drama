# -*- coding: utf-8 -*-
"""视频模型出得了哪几档分辨率，以及一个项目的「成片清晰度」。

* 一个型号没有的档位不会发出去：要 1080p 而型号最高 720p，就按 720p 出，账也按 720p 记。
* 项目可以给成片选一档清晰度；只提供这个型号出得了、比样片高、并且价目表里有官方价的档位，
  所以不会出现「片子出了却算不出花了多少」的档位。样片仍按 clip_fixes 的样片档位出。

本模块不调模型；档位表在 data/prompt/video_tiers.json。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Optional

from app.core import prompt_data

_DATA = "video_tiers"


def _fold(name: Any) -> str:
    return re.sub(r"[\s._\-]+", "", str(name or "").lower())


def _order() -> list[str]:
    return [str(tier) for tier in prompt_data.value(_DATA, "order")]


def _spelled(tier: Any) -> str:
    """The table's own spelling of a tier (``4K`` and ``4k`` are one), or '' when it is not a tier."""
    wanted = str(tier or "").strip().lower()
    return next((known for known in _order() if known.lower() == wanted), "")


def tiers(model: str) -> tuple[str, ...]:
    """The tiers this model renders, low to high; empty when the table says nothing about it."""
    folded = _fold(model)
    if not folded:
        return ()
    table: Mapping[str, Any] = prompt_data.value(_DATA, "models")
    matches = [name for name in table if _fold(name) and _fold(name) in folded]
    if not matches:
        return ()
    order = _order()
    return tuple(sorted({_spelled(tier) for tier in table[max(matches, key=len)]} - {""}, key=order.index))


def fit(model: str, wanted: Optional[str]) -> Optional[str]:
    """``wanted`` as this model can render it: its own tier, else the highest one below it, else its lowest."""
    if not wanted:
        return None
    known = tiers(model)
    spelled = _spelled(wanted)
    if not known or not spelled:
        return wanted
    if spelled in known:
        return spelled
    order = _order()
    below = [tier for tier in known if order.index(tier) < order.index(spelled)]
    return below[-1] if below else known[0]


def final_choices(model: str) -> list[str]:
    """What a project may pick as its final resolution on this model."""
    from app.core.providers.pricing import pricing_table

    entry = pricing_table().lookup(model)
    priced = {_spelled(tier) for tier in (entry.by_resolution if entry else {})} - {""}
    order = _order()
    draft = _spelled(prompt_data.text("clip_fixes", "draft_resolution"))
    floor = order.index(draft) if draft else -1
    return [tier for tier in tiers(model) if tier in priced and order.index(tier) > floor]


def final_resolution(config: Mapping[str, Any], model: str) -> Optional[str]:
    """The project's chosen final resolution when this model still offers it; ``None`` leaves the default."""
    chosen = _spelled((config or {}).get("video_resolution"))
    return chosen if chosen and chosen in final_choices(model) else None


def checked_choice(model: str, wanted: Optional[str]) -> Optional[str]:
    """Validate a new choice; ``None`` or '' clears it. A tier that is not offered is refused, with the ones that are."""
    if not str(wanted or "").strip():
        return None
    choices = final_choices(model)
    spelled = _spelled(wanted)
    if spelled and spelled in choices:
        return spelled
    errors: Mapping[str, Any] = prompt_data.value(_DATA, "errors")
    if not choices:
        raise ValueError(str(errors["none_offered"]).format(model=model or "?"))
    raise ValueError(str(errors["not_offered"]).format(model=model or "?", tier=wanted, choices="、".join(choices)))
