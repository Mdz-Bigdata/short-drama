# -*- coding: utf-8 -*-
"""道具的真实尺寸：按名字查道具标尺参照表(app/data/props/scale_reference.json)。

查法：名字(去掉括号注释)和表里的中文名完全一样最好；不一样就找名字里包含的最长的表名
(「旧式半自动手枪」→ 半自动手枪)。只有一个字的表名(马、枪、戟)只认完全一样，免得「马车」当成马、
「手枪」当成长枪。表名末尾的「二型、三型」不算，「主战坦克二型」也是主战坦克的尺寸。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).resolve().parents[1] / "data" / "props" / "scale_reference.json"
_TYPE_SUFFIX = re.compile(r"[二三四五六七八九十]型$")


@dataclass(frozen=True)
class PropScale:
    name: str
    category: str
    dims_cm: tuple[float, ...]
    diameter: bool
    family: str | None

    @property
    def longest_cm(self) -> float:
        return max(self.dims_cm)

    def size_text(self) -> str:
        """「长100×宽4×高2厘米」「直径15厘米」「约200厘米」这样的说法。"""
        numbers = [f"{value:g}" for value in self.dims_cm]
        if self.diameter:
            return f"直径{numbers[0]}厘米"
        if len(numbers) == 3:
            return f"长{numbers[0]}×宽{numbers[1]}×高{numbers[2]}厘米"
        if len(numbers) == 2:
            return f"{numbers[0]}×{numbers[1]}厘米"
        return f"约{numbers[0]}厘米"


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, PropScale], tuple[str, ...]]:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    families = data.get("category_family") or {}
    by_name: dict[str, PropScale] = {}
    for entry in data.get("entries") or []:
        name = _TYPE_SUFFIX.sub("", str(entry["name"]).strip())
        if name in by_name:
            continue
        by_name[name] = PropScale(
            name=name, category=str(entry.get("category") or ""), dims_cm=tuple(float(value) for value in entry["dims_cm"]),
            diameter=bool(entry.get("diameter")), family=families.get(str(entry.get("category") or "")),
        )
    # 长名字先比，「主战坦克」先于「坦克」。
    return by_name, tuple(sorted(by_name, key=len, reverse=True))


def lookup(name: str) -> PropScale | None:
    """这件道具在参照表里的尺寸；查不到返回 None。"""
    bare = _TYPE_SUFFIX.sub("", re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip())
    if not bare:
        return None
    by_name, longest_first = _table()
    if bare in by_name:
        return by_name[bare]
    # 名字的结尾说的才是这是什么：先找结尾对得上的表名，再找名字里包含的。
    candidates = [key for key in longest_first if len(key) >= 2]
    return next(
        (by_name[key] for key in candidates if bare.endswith(key)),
        next((by_name[key] for key in candidates if key in bare), None),
    )


__all__ = ["PropScale", "TABLE", "lookup"]
