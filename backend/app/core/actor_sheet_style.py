# -*- coding: utf-8 -*-
"""数字演员设定集提示词里的风格词与时代服饰句，读 ``app/data/prompt/actor_sheet.json``。

第 3 阶段真正出图(``ModelGateway._generate_character_sheet_unmetered``)和捏脸页不花钱看一眼的
sheet-prompt(``api/face_sculpt_api``)拼的是同一段：措辞只在数据文件里有一份，两边读这里。
"""

from __future__ import annotations

from app.core import prompt_data

_DATA = "actor_sheet"


def style_word(dir_style: str, era_costume: str = "") -> str:
    """题材带时代服饰约束时不再用「现代都市」基调；否则按导演视听风格取词，表里没有的用默认词。"""
    data = prompt_data.load(_DATA)
    if era_costume:
        return str(data["style_era"])
    return str(data["style_words"].get(str(dir_style or ""), data["style_default"]))


def era_clause(era_costume: str) -> str:
    """时代服饰硬约束句(原样跟在画面描述后面)；没有约束就是空串。"""
    if not era_costume:
        return ""
    return prompt_data.text(_DATA, "era_clause").replace("{era_costume}", str(era_costume))


__all__ = ["era_clause", "style_word"]
