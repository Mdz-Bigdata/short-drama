# -*- coding: utf-8 -*-
"""一场戏是不是高张力场次：对峙、逼问、埋伏、清算、悬疑揭露。

是的话，分镜师拿到高张力镜头章节(skills/shot-design-master/references/high-tension-shots.md)：
静大于动、失衡构图、暗多亮少、细节藏情。日常戏、甜宠戏不给，免得每一场都拍得又暗又静。
判据是场景正文里出现的信号词，词表和门槛在 app/data/prompt/scene_tension.json。
"""

from __future__ import annotations

from app.core import prompt_data

_WORDING = "scene_tension"


def tension_hits(text: str) -> list[str]:
    """正文里出现了哪些高张力信号词(不重复)。"""
    body = str(text or "")
    return [word for word in prompt_data.words(_WORDING, "words") if word in body]


def looks_tense(text: str) -> bool:
    return len(tension_hits(text)) >= prompt_data.number(_WORDING, "min_hits")


__all__ = ["looks_tense", "tension_hits"]
