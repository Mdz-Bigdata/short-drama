# -*- coding: utf-8 -*-
"""视频提示词里的资产引用：``@[名字]``。

镜头提示词给人看、也给人改：角色、场景、道具写成 ``@[名字]``，编辑器把它们标成不同颜色的引用，
一眼就能看出这一镜锁了哪些资产、每个名字有没有对应的参考图。

发给视频模型之前再解析：``@[名字]`` 换成「名字（参考图N）」——N 是这一镜随请求上传的第几张参考图；
没有对应参考图的名字只留下名字本身。模型从不看到 ``@[...]`` 记号。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

MENTION = re.compile(r"@\[([^\[\]\n]{1,40})\]")


def mention(name: str) -> str:
    return f"@[{name}]"


def mark_mentions(text: str, names: Iterable[str]) -> str:
    """把正文里出现的资产名字标成 ``@[名字]``；已经标过的不重复标，长名字优先(「姜照工位」先于「姜照」)。"""
    candidates = sorted({name.strip() for name in names if name and name.strip()}, key=len, reverse=True)
    if not text or not candidates:
        return text
    pattern = re.compile("|".join(re.escape(name) for name in candidates))
    pieces: list[str] = []
    cursor = 0
    for marked in MENTION.finditer(text):
        pieces.append(pattern.sub(lambda match: mention(match.group(0)), text[cursor:marked.start()]))
        pieces.append(marked.group(0))
        cursor = marked.end()
    pieces.append(pattern.sub(lambda match: mention(match.group(0)), text[cursor:]))
    return "".join(pieces)


def parse_mentions(text: str) -> list[str]:
    """提示词里引用到的资产名字，按首次出现的顺序去重。"""
    return list(dict.fromkeys(match.group(1).strip() for match in MENTION.finditer(text or "")))


def resolve_mentions(text: str, reference_numbers: Mapping[str, int]) -> str:
    """发给模型前把 ``@[名字]`` 换成「名字（参考图N）」；没有参考图的名字只留名字。"""
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        number = reference_numbers.get(name)
        return f"{name}（参考图{number}）" if number else name

    return MENTION.sub(replace, text or "")
