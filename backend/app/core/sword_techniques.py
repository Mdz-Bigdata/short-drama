# -*- coding: utf-8 -*-
"""剑法谱：剧本点到的剑法各自怎么走、在对打里拿来做什么，追加给第 4 阶段的分镜师。

剧本写「反手一撩」「粘住来剑一带」时，分镜师要知道撩和带在画面上是什么样：刃朝哪、剑尖走哪条线、手臂和剑
成不成一条直线、力落在剑的哪一段，以及对手通常怎么应。这里只发剧本本场点到的那几种(刺、劈、点、撩、崩、绞、
挂、扫、带、截、云、架、抱、穿、斩、腕花，连同握剑、起势、收势)，后面跟几条激烈对剑的通则。

三件事都成立才发：这一场是打戏(调用方判断)、本场有剑(``weapon_moves`` 认出「剑」)、剧本点了至少一种剑法。
它解释的是剧本自己用的词，不替剧本另编招，所以不看剧本有没有把招写出来；一种都没点到、只写了「两人持剑相斗」
的戏走兵器套路(``weapon_forms``)。名目、别名和写法在 ``app/data/prompt/sword_techniques.json``。
"""

from __future__ import annotations

from typing import Any

from app.core import prompt_data, weapon_moves

_WORDING = "sword_techniques"
_SWORD = "剑"


def _techniques() -> list[dict[str, Any]]:
    return [item for item in prompt_data.load(_WORDING)["techniques"] if isinstance(item, dict)]


def techniques_in(scene_text: str) -> list[str]:
    """本场点到的剑法，按剑法谱的顺序；本场没有剑时一种也不认(「横扫」「架住」别的兵器也用)。"""
    text = str(scene_text or "")
    if _SWORD not in weapon_moves.weapons_in(text):
        return []
    return [str(item["name"]) for item in _techniques() if any(str(alias) and str(alias) in text for alias in item.get("aliases") or [])]


def technique_brief(scene_text: str) -> str:
    """本场点到的剑法和对剑的通则；一种都没点到是空串。装不下的整条不发，不截半句。"""
    named = set(techniques_in(scene_text))
    if not named:
        return ""
    data = prompt_data.load(_WORDING)
    lead, usage, template = str(data["lead"]), str(data["usage"]), str(data["line"])
    budget = prompt_data.number(_WORDING, "budget")
    lines: list[str] = []
    length = len(lead) + len(usage) + 1
    for item in _techniques():
        if item["name"] not in named:
            continue
        line = template.format(name=item["name"], how=item["how"], use=item["use"])
        if length + len(line) + 1 > budget:
            continue
        lines.append(line)
        length += len(line) + 1
    return "\n".join([lead, *lines, usage]) if lines else ""


__all__ = ["technique_brief", "techniques_in"]
