# -*- coding: utf-8 -*-
"""可用镜头单价：视频生成一共花了多少 ÷ 审看通过了几镜。

只看预览惊不惊艳会误判一个方案；真正的账是「每条能用的镜头花了多少钱」。花费取用量台账里
成功并计了价的视频调用(全项目)；可用镜头取各集剪辑台上审看通过的镜头(同一镜只算一次)。一条都
没通过就不算单价，直说还没跑通。措辞在 data/prompt/unit_cost.json。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "unit_cost"
_VIDEO = "video"


def _says(key: str, **values: Any) -> str:
    return str(prompt_data.value(_DATA, "says")[key]).format(**values)


def _timelines(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    from app.core import episode_cycle

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    found = [assets.get(episode_cycle.TIMELINE_KEY)]
    cycle = assets.get(episode_cycle.CYCLE_KEY) if isinstance(assets.get(episode_cycle.CYCLE_KEY), Mapping) else {}
    episodes = cycle.get("episodes") if isinstance(cycle.get("episodes"), Mapping) else {}
    found += [entry.get("timeline") for entry in episodes.values() if isinstance(entry, Mapping)]
    return [item for item in found if isinstance(item, Mapping)]


def usable_clips(task: Mapping[str, Any]) -> int:
    """各集剪辑台上审看通过的镜头数；同一镜(全剧镜头编号)只算一次。"""
    approved: set[Any] = set()
    for timeline in _timelines(task):
        for clip in timeline.get("clips") or []:
            if isinstance(clip, Mapping) and (clip.get("review") or {}).get("decision") == "approved":
                approved.add(clip.get("shot_uid") or (clip.get("scene_id"), clip.get("shot_id")))
    return len(approved)


def video_spend(records: Any) -> dict[str, Any]:
    """台账里视频生成的调用次数、失败次数和按币种的花费。"""
    calls = failed = 0
    spent: dict[str, float] = {}
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, Mapping) or item.get("media_type") != _VIDEO or (item.get("units") or {}).get("reused"):
            continue
        calls += 1
        if item.get("status") == "failed":
            failed += 1
        elif item.get("priced") and item.get("currency"):
            currency = str(item["currency"])
            spent[currency] = round(spent.get(currency, 0.0) + float(item.get("cost") or 0.0), 4)
    return {"calls": calls, "failed": failed, "spent": spent}


def _money(amounts: Mapping[str, float]) -> str:
    units = prompt_data.value(_DATA, "currency_units")
    return _says("join").join(
        _says("money", amount=f"{amount:.2f}", unit=units.get(currency, f" {currency}")) for currency, amount in amounts.items()
    )


def summary(task: Mapping[str, Any]) -> dict[str, Any]:
    """{spent, calls, failed, usable, per_usable(None 表示还没跑通), line}。"""
    spend = video_spend(task.get("usage_records"))
    usable = usable_clips(task)
    per = {currency: round(amount / usable, 4) for currency, amount in spend["spent"].items()} if usable and spend["spent"] else None
    if not spend["calls"]:
        line = _says("nothing")
    elif per is None:
        line = _says("not_yet", spent=_money(spend["spent"]) or _money({"CNY": 0.0}), calls=spend["calls"], failed=spend["failed"])
    else:
        line = _says("line", spent=_money(spend["spent"]), calls=spend["calls"], failed=spend["failed"], usable=usable, per=_money(per))
    return {**spend, "usable": usable, "per_usable": per, "line": line}


__all__ = ["summary", "usable_clips", "video_spend"]
