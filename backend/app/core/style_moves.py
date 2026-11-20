# -*- coding: utf-8 -*-
"""拳种谱：点了名的拳种各自的打法，追加给第 4 阶段的分镜师——只在剧本没有自己把招写出来的打戏里。

打法卡让每个人有自己的拳种(「咏春」「八极」)，但一个名字画不出来：这里把拳种落成看得见的身法、几招看家动作的
身体路径、怎么防、挨打的人怎么反应。两件事都成立才发：本场点了拳种的名(剧本本场文字里写到的，或策划方案里本场
人物那几行打法卡写到的)，并且剧本没有把招写出来。

第二条是比出来的(2026-11-19，盲评两次)：只点了拳种名的场次，带拳种谱的分镜更好(打戏排名 1.5 对 3.5)；剧本已经
写了招的场次，带它反而更差(整体 3.5 对 1.5)——模型拿这里的通用身法(「窄马站稳」「拨离中线」)盖掉了剧本写的
「踏进半步」「粘住来拳」，加一句「剧本写了的照剧本」也没用。所以剧本里接触动作词够多(``scripted_contacts``)就不发。
拳种名、别名和写法在 ``app/data/prompt/style_moves.json``。兵器另有兵器谱(``weapon_moves``)。
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core import prompt_data

_WORDING = "style_moves"


def _styles() -> list[dict[str, Any]]:
    return [item for item in prompt_data.load(_WORDING)["styles"] if isinstance(item, dict)]


def _names_of(cast: Iterable[Any]) -> list[str]:
    names = [str(item.get("name") or "") if isinstance(item, dict) else str(item or "") for item in cast or ()]
    return [name.strip() for name in names if name and name.strip()]


def cast_lines(plan_text: str, cast: Iterable[Any]) -> str:
    """策划方案里提到本场人物的那几行：打法卡写在那里。没有方案或没有人物时是空串。"""
    names = _names_of(cast)
    if not names:
        return ""
    return "\n".join(line for line in str(plan_text or "").splitlines() if any(name in line for name in names))


def styles_in(scene_text: str, plan_text: str = "", cast: Iterable[Any] = ()) -> list[str]:
    """本场点了名的拳种，按拳种谱的顺序。只认拳种名和别名，不从「一拳」「一脚」这类动作猜拳种。"""
    text = f"{scene_text or ''}\n{cast_lines(plan_text, cast)}"
    return [
        str(item["name"]) for item in _styles()
        if str(item["name"]) in text or any(str(alias) and str(alias) in text for alias in item.get("aliases") or [])
    ]


def choreographed(scene_text: str) -> bool:
    """剧本是不是已经自己把招写出来了：本场文字里的接触动作词(一掌、撞向、格开……)够不够多。"""
    text = str(scene_text or "")
    written = sum(1 for verb in prompt_data.words("fight_scene", "contact_verbs") if verb in text)
    return written >= prompt_data.number(_WORDING, "scripted_contacts")


def style_brief(scene_text: str, plan_text: str = "", cast: Iterable[Any] = ()) -> str:
    """本场拳种的打法；没有点名的拳种、或剧本已经把招写出来时是空串。装不下的拳种整条不发，不截半句。"""
    if choreographed(scene_text):
        return ""
    named = set(styles_in(scene_text, plan_text, cast))
    if not named:
        return ""
    budget = prompt_data.number(_WORDING, "budget")
    template = prompt_data.text(_WORDING, "line")
    lead = prompt_data.text(_WORDING, "lead")
    lines: list[str] = []
    length = len(lead)
    for item in _styles():
        if item["name"] not in named:
            continue
        line = template.format(item["name"], item["moves"])
        if length + len(line) + 1 > budget:
            continue
        lines.append(line)
        length += len(line) + 1
    return "\n".join([lead, *lines]) if lines else ""


__all__ = ["cast_lines", "choreographed", "style_brief", "styles_in"]
