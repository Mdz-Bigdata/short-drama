# -*- coding: utf-8 -*-
"""修仙道具和场地出参考图时补的外观：丹药的丹纹丹香、飞剑、储物戒、符箓、玉简、阵盘、丹炉、灵石、各类法宝，
以及法宝品阶(法器 → 灵器 → 宝器 → 灵宝 → 仙器 → 神器)在器身上的光。

钟、镜、扇、剑这类寻常也有的器物，名字或描述里写到法宝、灵器、认主这类词才按法宝画，
宫斗剧的铜镜、武侠剧的长剑照常。表和措辞在 app/data/prompt/xianxia_props.json。
"""

from __future__ import annotations

import re

from app.core import prompt_data

_WORDING = "xianxia_props"


def _bare(name: str) -> str:
    return re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()


def kind_look(name: str, description: str = "") -> str:
    """这件道具按哪一类修仙道具画；不是修仙道具时是空串。"""
    bare = _bare(name)
    if not bare or any(word in bare for word in prompt_data.words(_WORDING, "not_pills")):
        return ""
    treasure = any(word in f"{bare} {description}" for word in prompt_data.words(_WORDING, "treasure_words"))
    # 结尾对得上的里面取最长的那个：「火狼妖丹」是妖丹，不是丹药；「宗门令牌」是宗门令牌，不只是令牌。
    best, best_length = "", 0
    for kind in prompt_data.value(_WORDING, "kinds"):
        if not (kind.get("always") or treasure):
            continue
        for end in kind["ends"]:
            if bare.endswith(str(end)) and len(str(end)) > best_length:
                best, best_length = str(kind["look"]), len(str(end))
    return best


def grade_look(name: str, description: str = "") -> str:
    text = f"{_bare(name)} {description}"
    return next((str(look) for grade, look in prompt_data.value(_WORDING, "grades") if grade in text), "")


def prop_rules(name: str, description: str = "") -> str:
    """补在道具参考图提示词里的一句；不是修仙道具时是空串。"""
    look = kind_look(name, description)
    if not look:
        return ""
    grade = grade_look(name, description)
    return prompt_data.text(_WORDING, "lead") + look + (f"；{grade}" if grade else "") + "。"


def place_rules(name: str, description: str = "") -> str:
    """补在场地参考图提示词里的一句修仙场地外观(仍是空景，不出人)；不是修仙场地时是空串。"""
    bare = _bare(name)
    if not bare:
        return ""
    xianxia = any(word in f"{bare} {description}" for word in prompt_data.words(_WORDING, "place_words"))
    for place in prompt_data.value(_WORDING, "places"):
        ends = sorted((str(end) for end in place["ends"]), key=len, reverse=True)
        if any(bare.endswith(end) for end in ends) and (place.get("always") or xianxia):
            return prompt_data.text(_WORDING, "place_lead") + str(place["look"]) + "。"
    return ""


__all__ = ["grade_look", "kind_look", "place_rules", "prop_rules"]
