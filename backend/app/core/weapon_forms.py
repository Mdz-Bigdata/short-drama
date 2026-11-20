# -*- coding: utf-8 -*-
"""兵器套路：棍、剑、刀、枪、弓箭从起势到收势的一条顺序，追加给第 4 阶段的分镜师——只在剧本没有把招写出来的打戏里。

兵器谱(``weapon_moves``)写每种兵器怎么走、怎么挡、打中了什么反应；一场只写了「两人持枪大战」的戏还缺先后：
先立定、再出手、怎么回身、最后怎么收。这里给这条顺序，连同握持与朝向上要守的事(握点不换边、剑不换手、
刀刃不凭空翻面、枪杆是一条直线、每一箭都有抽箭搭弦)。

发不发与拳种谱同一条(``style_moves.choreographed``)：剧本已经把招写出来的场次，参考招式会盖掉剧本的写法
(2026-11-19 两次盲评的结论)，所以不发。顺序和措辞在 ``app/data/prompt/weapon_forms.json``。
"""

from __future__ import annotations

from app.core import prompt_data, style_moves, weapon_moves

_WORDING = "weapon_forms"


def forms_in(scene_text: str) -> list[str]:
    """本场出现、并且有套路可给的兵器，按兵器谱的顺序。"""
    known = prompt_data.load(_WORDING)["forms"]
    return [name for name in weapon_moves.weapons_in(scene_text) if name in known]


def forms_brief(scene_text: str) -> str:
    """本场兵器的套路；没有这几种兵器、或剧本已经把招写出来时是空串。装不下的整条不发，不截半句。"""
    if style_moves.choreographed(scene_text):
        return ""
    forms = prompt_data.load(_WORDING)["forms"]
    budget = prompt_data.number(_WORDING, "budget")
    template = prompt_data.text(_WORDING, "line")
    lead = prompt_data.text(_WORDING, "lead")
    lines: list[str] = []
    length = len(lead)
    for name in forms_in(scene_text):
        line = template.format(name, forms[name])
        if length + len(line) + 1 > budget:
            continue
        lines.append(line)
        length += len(line) + 1
    return "\n".join([lead, *lines]) if lines else ""


__all__ = ["forms_brief", "forms_in"]
