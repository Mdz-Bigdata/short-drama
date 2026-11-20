# -*- coding: utf-8 -*-
"""美术指导：画面由故事背景决定，细节决定故事的真实性。

总导演在策划方案里单列一节「美术设定卡」(时代地域、物产材质、生活习惯、民俗细节、阶层差别、
贯穿小物件、奇幻的现实基底)，后面的环节都照它来：提炼项目概述时写进世界观一栏，剧本与资产清单
读得到；角色设计师按它定服装(身份、处境、性格都落在看得见的细节上)；拆场景与道具时写出地方、
人家和来历。措辞在 app/data/prompt/art_direction.json。
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core import prompt_data

_DATA = "art_direction"
#: 资产目录里由美术指导补规则的几类。
CATALOG_KINDS: tuple[str, ...] = tuple(prompt_data.value(_DATA, "catalog_rules"))


def world_card() -> str:
    """总导演策划里要单列的那一节。"""
    return prompt_data.text(_DATA, "world_card")


def overview_ask() -> str:
    """提炼项目概述时，世界观一栏怎么填。"""
    return prompt_data.text(_DATA, "overview_ask")


def costume_rule() -> str:
    """角色设计师定服装的写法，接在角色块规则之后。"""
    return prompt_data.text(_DATA, "costume_rule")


def asset_rules() -> str:
    """从小说或策划方案提资产清单时，场景与道具的写法；一条一行。"""
    return "\n".join(prompt_data.words(_DATA, "asset_rules"))


def catalog_rules(kinds: Any) -> str:
    """补拍摄资产目录时，``kinds`` 里由美术指导管的几类各一行；没有就是空串。"""
    rules: Mapping[str, str] = prompt_data.value(_DATA, "catalog_rules")
    return "".join(f"{rules[key]}\n" for key in kinds if key in rules)


def catalog_world(world: Any, kinds: Any) -> str:
    """补资产目录时把世界观一栏交给模型；没有世界观，或这一轮不拆场景和道具，就是空串。"""
    text = str(world or "").strip()
    if not text or not any(key in CATALOG_KINDS for key in kinds):
        return ""
    return prompt_data.text(_DATA, "catalog_world").format(world=text)


__all__ = ["CATALOG_KINDS", "asset_rules", "catalog_rules", "catalog_world", "costume_rule", "overview_ask", "world_card"]
