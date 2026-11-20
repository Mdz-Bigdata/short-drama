# -*- coding: utf-8 -*-
"""刀法谱：剧本点到的刀法各自怎么走、在对打里拿来做什么，追加给第 4 阶段的分镜师。

剧本写「缠头裹脑」「反手一撩」「藏刀诱敌」时，分镜师要知道它们在画面上是什么样：刀刃和刀背朝哪、刀尖走哪条线、
力落在刀的哪一段、空着的那只手在做什么，以及对手通常怎么应。这里只发剧本本场点到的那几种(握、抱、缠头、裹脑、
劈、砍、截、撩、挂、扎、抹、斩、扫、云、崩、藏、推、腕花、架、拖、点、格、按、挑、穿、反刺、背花、换手、收)，后面跟几条激烈对刀的通则。

三件事都成立才发：这一场是打戏(调用方判断)、本场有刀、剧本点了至少一种刀法。它解释的是剧本自己用的词，不替剧本
另编招；一种都没点到、只写了「两人挥刀相斗」的戏走兵器套路(``weapon_forms``)。做法与剑法谱(``sword_techniques``)
相同，名目、别名和写法在 ``app/data/prompt/sabre_techniques.json``。
"""

from __future__ import annotations

from typing import Any

from app.core import prompt_data, weapon_moves

_WORDING = "sabre_techniques"
#: 兵器谱里算「刀」的几种：单刀、双刀、长柄大刀、刀盾。
SABRES = frozenset({"刀", "双刀", "长柄大刀", "刀盾"})


def _techniques() -> list[dict[str, Any]]:
    return [item for item in prompt_data.load(_WORDING)["techniques"] if isinstance(item, dict)]


def sabre_in(scene_text: str) -> bool:
    """本场有没有刀：兵器谱认出了一种刀，或剧本用了只有刀戏才用的词(「一刀」「缠头」「刀鞘」)。"""
    text = str(scene_text or "")
    if SABRES & set(weapon_moves.weapons_in(text)):
        return True
    return any(str(word) and str(word) in text for word in prompt_data.load(_WORDING)["presence"])


def techniques_in(scene_text: str) -> list[str]:
    """本场点到的刀法，按刀法谱的顺序；本场没有刀时一种也不认(「横斩」「架住」别的兵器也用)。"""
    text = str(scene_text or "")
    if not sabre_in(text):
        return []
    # 流派名里带着刀法的字(「通背刀」里的「背刀」)不算点了那种刀法：认之前先拿掉。
    for school in prompt_data.load(_WORDING).get("school_names") or []:
        text = text.replace(str(school), "")
    return [str(item["name"]) for item in _techniques() if any(str(alias) and str(alias) in text for alias in item.get("aliases") or [])]


def technique_brief(scene_text: str) -> str:
    """本场点到的刀法和对刀的通则；一种都没点到是空串。装不下的整条不发，不截半句。"""
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


__all__ = ["SABRES", "sabre_in", "technique_brief", "techniques_in"]
