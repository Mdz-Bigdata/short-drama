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
from typing import Any

from app.core.element_scope import normalized_asset_name

#: ``@[名字]`` 里名字最多几个字；更长的名字放不进引用。
MENTION_NAME_LIMIT = 40
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


def resolve_mention_refs(text: str, entries: Iterable[Mapping[str, Any]]) -> dict[str, list]:
    """把正文里的 ``@[名字]`` 对上候选(mention_catalog 的条目：name、kind、element_id、aliases)。

    名字和别名都去掉空格标点、不分大小写比。同一个名字对上两类东西(演员「林夏」和场景「林夏」)算有歧义，
    不替人挑；同一类里对上几条时取名字正好相同的那条，没有就取第一条。
    返回 ``{refs: [{name, kind, element_id}], ambiguous: [{name, kinds}], unknown: [name]}``，按首次出现排序。
    """
    pool = [entry for entry in entries or () if isinstance(entry, Mapping) and str(entry.get("name") or "").strip()]
    refs: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []
    unknown: list[str] = []
    for typed in parse_mentions(text):
        key = normalized_asset_name(typed)
        exact: list[Mapping[str, Any]] = []
        aliased: list[Mapping[str, Any]] = []
        for entry in pool:
            if normalized_asset_name(entry.get("name")) == key:
                exact.append(entry)
            elif any(normalized_asset_name(alias) == key for alias in entry.get("aliases") or () if isinstance(alias, str)):
                aliased.append(entry)
        found = exact + aliased
        kinds = list(dict.fromkeys(str(entry.get("kind") or "") for entry in found))
        if not key or not found:
            unknown.append(typed)
        elif len(kinds) > 1:
            ambiguous.append({"name": typed, "kinds": kinds})
        else:
            hit = found[0]
            ref = {"name": str(hit.get("name") or "").strip(), "kind": kinds[0], "element_id": str(hit.get("element_id") or "")}
            if ref not in refs:
                refs.append(ref)
    return {"refs": refs, "ambiguous": ambiguous, "unknown": unknown}
