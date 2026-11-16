# -*- coding: utf-8 -*-
"""剧本只描述外貌、没写名字的出场角色，按他的定妆图(表演妆造)认出来。

「药白素衣的年轻女子被人从人群里推出半步，腕上一片深色药渍」——这是阿箬(定妆图「药白药堂长衣·右腕药渍」)，
可场景出场名单是空的：分镜师拿不到她，只能把这句描述写进出场栏，分镜检查报「未出场角色」，她的定妆照、
正面大头照和妆效文字也进不了提示词。这里把每个人当前定妆图的名字片段(戏服名、妆效名)拆成两字一组，只用
这个人独有的组，在场景正文里命中够数就把他补进这一场的出场名单。补进名单只是让分镜师能用他的名字和妆造，
镜头里画不画他仍由分镜表定。阈值和常见词在 app/data/prompt/scene_cast.json。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core import prompt_data
from app.core.character_variants import is_look, variant_of
from app.core.element_scope import normalized_asset_name

_DATA = "scene_cast"


def _pieces(look: Mapping[str, Any]) -> list[str]:
    """一张定妆图的戏服名、妆效名(去掉人名前缀)。"""
    facts = variant_of(look) or {}
    label = str(facts.get("label") or "")
    return [normalized_asset_name(piece) for piece in label.split("·") if normalized_asset_name(piece)]


def _grams(text: str) -> set[str]:
    stop = set(prompt_data.words(_DATA, "stopgrams"))
    return {text[index:index + 2] for index in range(len(text) - 1)} - stop


def described(script: str, variants: Mapping[str, Sequence[Mapping[str, Any]]], already: Iterable[str]) -> list[str]:
    """``script`` 里只描述外貌、按定妆图认得出来的出场角色(不在 ``already`` 里的)。

    ``variants`` 是 character_variants.split 给出的「角色 → 他的派生条目」，只看其中的定妆图。
    """
    text = normalized_asset_name(script)
    grams_of = {
        name: set().union(*(_grams(piece) for look in looks if is_look(look) for piece in _pieces(look)))
        for name, looks in variants.items()
    }
    found: list[str] = []
    skip = set(already)
    least = int(prompt_data.number(_DATA, "min_hits"))
    for name, grams in grams_of.items():
        if name in skip or not grams:
            continue
        others = set().union(*(other for owner, other in grams_of.items() if owner != name))
        hits = {gram for gram in grams - others if gram in text}
        if len(hits) >= least:
            found.append(name)
    return found


__all__ = ["described"]
