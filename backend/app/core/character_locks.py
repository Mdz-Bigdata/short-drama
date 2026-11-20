# -*- coding: utf-8 -*-
"""角色禁用项：跨镜头绝不能变的东西(剑始终在右手、战袍不变色、头发不散开)。

人物卡里写了「禁用项：……」就照它；没写时按卡里的事实推几条。视频提示词里接在人物外貌后面，
不受外貌字数上限截断——外貌写长了会被截短，这几条不能被截掉。措辞与规则在 data/prompt/character_locks.json。
"""

from __future__ import annotations

import re

from app.core import prompt_data

_DATA = "character_locks"


def _label_pattern() -> re.Pattern[str]:
    labels = "|".join(re.escape(label) for label in prompt_data.words(_DATA, "labels"))
    return re.compile(rf"(?:{labels})[：:]\s*([^；;。\n]*)")


def split_locks(look: str) -> tuple[str, list[str]]:
    """人物卡去掉「禁用项：……」那一段后的文字，和那一段列出的条目。"""
    text = str(look or "")
    written: list[str] = []
    for match in _label_pattern().finditer(text):
        written.extend(item.strip() for item in re.split(r"[、，,/]", match.group(1)) if item.strip())
    rest = _label_pattern().sub("", text)
    return re.sub(r"[；;]{2,}", "；", rest).strip("；; "), written


def derived_locks(look: str) -> list[str]:
    """卡里没写禁用项时，从事实推：束发不散开、哪只手持兵器不换手、标志服装不变色。"""
    text = str(look or "")
    locks: list[str] = []
    if any(word in text for word in prompt_data.words(_DATA, "hair_up_words")):
        locks.append(prompt_data.text(_DATA, "hair_up_lock"))
    for hand, item in re.findall(prompt_data.text(_DATA, "hand_pattern"), text):
        locks.append(prompt_data.text(_DATA, "hand_lock").format(item=item, hand=hand))
    garments = 0
    for colour, garment in re.findall(prompt_data.text(_DATA, "garment_pattern"), text):
        if garments >= prompt_data.number(_DATA, "max_garments"):
            break
        locks.append(prompt_data.text(_DATA, "garment_lock").format(garment=garment, colour=colour))
        garments += 1
    return locks


def locks_of(look: str) -> list[str]:
    """这个人跨镜头不许变的几条：写了的在前，推出来的补在后，去重后最多 max_locks 条。"""
    rest, written = split_locks(look)
    locks = list(dict.fromkeys([*written, *derived_locks(rest)]))
    return locks[: prompt_data.number(_DATA, "max_locks")]


def lock_line(locks: list[str]) -> str:
    return prompt_data.text(_DATA, "line").format("、".join(locks)) if locks else ""


__all__ = ["derived_locks", "lock_line", "locks_of", "split_locks"]
