# -*- coding: utf-8 -*-
"""兵器谱：本场用到的兵器各自的打法，追加给第 4 阶段的分镜师。

每种兵器写五件事：轨迹形状、力从哪里来、怎么被格挡、接触时溅出什么、挨了这一下的人怎么反应。
通用的力学与五镜动作链在武打指南里(``fight_scene.martial_guide``)，这里只写兵器之间不一样的地方；
只发本场出现的兵器，总长受 ``budget`` 限制。兵器名、别名和写法在 ``app/data/prompt/weapon_moves.json``。
"""

from __future__ import annotations

from typing import Any

from app.core import prompt_data

_WORDING = "weapon_moves"


def _weapons() -> list[dict[str, Any]]:
    return [item for item in prompt_data.load(_WORDING)["weapons"] if isinstance(item, dict)]


def weapons_in(scene_text: str) -> list[str]:
    """本场出现的兵器，按兵器谱的顺序。只认别名(「长剑」「挥刀」)，单字「剑」「刀」会把剑冢、刀疤也算进来。"""
    text = str(scene_text or "")
    return [
        str(item["name"]) for item in _weapons()
        if any(str(alias) and str(alias) in text for alias in item.get("aliases") or [])
    ]


def weapon_brief(scene_text: str) -> str:
    """本场兵器的打法；本场没有兵器时是空串。装不下的兵器整条不发，不截半句。"""
    named = set(weapons_in(scene_text))
    if not named:
        return ""
    budget = prompt_data.number(_WORDING, "budget")
    template = prompt_data.text(_WORDING, "line")
    lines: list[str] = []
    length = len(prompt_data.text(_WORDING, "lead"))
    for item in _weapons():
        if item["name"] not in named:
            continue
        line = template.format(item["name"], item["moves"])
        if length + len(line) + 1 > budget:
            continue
        lines.append(line)
        length += len(line) + 1
    return "\n".join([prompt_data.text(_WORDING, "lead"), *lines]) if lines else ""


__all__ = ["weapon_brief", "weapons_in"]
