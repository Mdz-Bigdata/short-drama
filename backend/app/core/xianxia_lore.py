# -*- coding: utf-8 -*-
"""修仙设定参照：特殊体质、法宝、宗门势力，仙侠玄幻修真类项目才给编剧和总导演看。

参照表在 ``app/data/prompt/xianxia_lore.json``：体质和法宝每条写清作用、代价、戏点和画面上的样子；
宗门势力写层级、势力类型和怎么用势力出戏。判断题材用 ``genre_clusters``(C 类：仙侠玄幻修真)，
和分镜按题材定调用的是同一套；判不出来就不加，都市、甜宠、正剧、武侠的提示词一个字不变。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core import genre_clusters, prompt_data

_DATA = "xianxia_lore"
_CLUSTER = "C"


def applies(genre: str = "", *, text: str = "") -> bool:
    """这部剧是不是仙侠玄幻修真：题材词或剧情文字里认得出就是。"""
    return genre_clusters.cluster_for(genre, text=text).id == _CLUSTER


def names() -> list[str]:
    """特殊体质的名字，按参照表的顺序。"""
    return [str(item["name"]) for item in prompt_data.value(_DATA, "physiques")]


def artifact_names() -> list[str]:
    return [str(item["name"]) for item in prompt_data.value(_DATA, "artifacts")]


def _rows(items: Sequence[Mapping[str, Any]]) -> list[str]:
    line = prompt_data.text(_DATA, "line")
    alias = prompt_data.text(_DATA, "alias")
    return [
        line.format(
            name=item["name"],
            alias=alias.format(names="、".join(item["aliases"])) if item.get("aliases") else "",
            power=item["power"], cost=item["cost"], hook=item["hook"], look=item["look"],
        )
        for item in items
    ]


def reference() -> str:
    """整张参照：原则在前，体质每种一行，再是法宝和宗门势力。"""
    factions = prompt_data.value(_DATA, "factions")
    return "\n".join([
        prompt_data.text(_DATA, "heading"),
        *(f"- {text}" for text in prompt_data.words(_DATA, "principles")),
        *_rows(prompt_data.value(_DATA, "physiques")),
        prompt_data.text(_DATA, "artifact_heading"),
        *_rows(prompt_data.value(_DATA, "artifacts")),
        str(factions["heading"]),
        f"- {factions['ranks']}",
        f"- {factions['kinds']}",
        *(f"- {rule}" for rule in factions["rules"]),
    ])


def block(genre: str = "", *, text: str = "") -> str:
    """仙侠修真题材给整张参照(前面空一行)，别的题材给空串。"""
    return f"\n\n{reference()}" if applies(genre, text=text) else ""


__all__ = ["applies", "artifact_names", "block", "names", "reference"]
