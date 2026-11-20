# -*- coding: utf-8 -*-
"""打戏提示词过审：只改会被拦的伤害词，力道一点不减。

- ``clean_gore``：斩首、断肢、喷血这类视频模型几乎一定会拦的词，出片前就换成拍得出的说法(刀光掠过颈侧、
  嘴角溢出一线暗红)。没有这些词的提示词原样返回。
- ``soften``：被审核拒单之后重出那一次才用的宽表：血、杀、伤口、尸体也换掉。
- 重击、砸、踹、震飞、骨裂声、拳、撕这类力道与打击词两张表都不碰：用户要的是激烈、有力量感的打戏。

替换表在 ``app/data/prompt/fight_safety.json``，按顺序替换，长词在前。
"""

from __future__ import annotations

from app.core import prompt_data

_WORDING = "fight_safety"


def _apply(text: str, key: str) -> str:
    for old, new in prompt_data.pairs(_WORDING, key):
        text = text.replace(old, new)
    return text


def clean_gore(text: str) -> str:
    """出片前就改的那几个血腥肢解词；其余一字不动。"""
    return _apply(str(text or ""), "always")


def soften(text: str) -> str:
    """审核拒单后重出用：血腥肢解词加上血、杀、伤口、尸体这些字眼，都换成拍得出的说法。"""
    return _apply(clean_gore(text), "retry")


def force_words() -> tuple[str, ...]:
    return prompt_data.words(_WORDING, "force_words")


__all__ = ["clean_gore", "force_words", "soften"]
