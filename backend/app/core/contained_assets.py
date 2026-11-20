# -*- coding: utf-8 -*-
"""被包含的资产条目不单独出图。

第 3 步多次续跑时，抽取的措辞会变，同一个东西在库里留下两条：「香头」和「偏殿香头」、「偏殿木门」和
「偏殿木门与门槛」。用户的规矩是名字被同一类另一条完整包含的，不单独生成——长的那条那张图已经画到它。
第 3 步补图、资产库「补齐图片」和就绪检查都从这里认，规则只有一处；条目本身不删。

字面包含却是另一样东西、两者相关的(「长剑」与「长剑剑鞘」、「刀」与「刀鞘」、「门」与「偏殿门」)画在一张图里，
不分别出图：短的那条不单独出图，长的那条那张图把它一起画进去(:func:`companions`)，形制尺寸对得上(剑鞘刚好装下
这把剑)；短的那条以前已经有图的，当参考图带上(:func:`related_partner`)。

群演另认一条(见 :func:`crowd_key`)：同一个场景里的同一拨人只出一张——「山门围观人群」「山门围观百姓」只是
叫人的词不同。

数字演员(演员本人与定妆图)不在这里比：定妆图由定妆图规划按时间线处理(character_looks：旧伤、残肢这类本来就有的
标记并进长的那张；戏服和妆效都在另一张里的那张也不单列，并进长的那张，那几集用它的图、文字写明图上多出的妆效不画)。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.core import prompt_data
from app.core.element_scope import normalized_asset_name

_DATA = "contained_assets"


def _comparable(summary: Mapping[str, Any]) -> bool:
    """参与比较的条目：数字演员与定妆图除外(由定妆图规划按时间线定)。"""
    return str(summary.get("kind") or "") != "actor"


def _key(name: Any) -> str:
    return normalized_asset_name(name)


def crowd_key(name: Any) -> str:
    """群演的「哪个场景、在做什么」：去掉末尾泛称人的词(人群、百姓…)和「的」；去掉后太短就按原名比。"""
    key = _key(name)
    for word in sorted(prompt_data.words(_DATA, "crowd_people_words"), key=len, reverse=True):
        if key.endswith(word):
            rest = key[: -len(word)]
            for trailing in prompt_data.words(_DATA, "crowd_trailing"):
                rest = rest[: -len(trailing)] if trailing and rest.endswith(trailing) else rest
            return rest if len(rest) >= int(prompt_data.number(_DATA, "min_chars")) else key
    return key


def _same_key(kind: Any, name: Any) -> str:
    """同一样东西的比较键：群演按场景+在做什么(见 :func:`crowd_key`)，其它按去掉空白标点的名字。"""
    return crowd_key(name) if str(kind or "") == prompt_data.text(_DATA, "crowd_kind") else _key(name)


def covered_by(name: Any, other: Any) -> bool:
    """``other`` 把 ``name`` 完整盖住，是同一样东西的更全的叫法：长的 = 别的字 + 短的(「香头」⊂「偏殿香头」)，
    或 短的 + 连接词 + 更多(「偏殿木门」⊂「偏殿木门与门槛」)。只是字面包含不算：「长剑」⊂「长剑剑鞘」是另一样东西。"""
    short, long = _key(name), _key(other)
    if len(short) < int(prompt_data.number(_DATA, "min_chars")) or short == long or short not in long:
        return False
    if long.endswith(short):
        return True
    return any(long.startswith(short + joiner) for joiner in prompt_data.words(_DATA, "joiners"))


def inside(name: Any, other: Any) -> bool:
    """``name`` 一字不差地在 ``other`` 里、又不是同一个名字(「刀」在「刀鞘」里)：要么是同一样东西的更全叫法
    (:func:`covered_by`)，要么是配套的另一样东西——两种都画进长的那条那张图里，不单独出图。"""
    short, long = _key(name), _key(other)
    return bool(short) and short != long and short in long


def contained_in(name: Any, others: Iterable[Any], kind: Any = "") -> bool:
    """``name`` 是否画进了 ``others`` 里某一条的图：被它字面包含(见 :func:`inside`)，或群演同一拨人的别名
    (见 :func:`crowd_key`)。"""
    same = _same_key(kind, name)
    return any(
        inside(name, other) or (_key(other) != _key(name) and _same_key(kind, other) == same)
        for other in others
    )


def duplicate_groups(summaries: Iterable[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]]:
    """同一类里重复的几条：(留下的那条, [重复的几条])。同名(去掉空白标点后一样)算重复，群演同一拨人(见
    :func:`crowd_key`)也算；留已有图的那条，没有就排最前的。名字只是被另一条盖住的(「香头」之于「偏殿香头」)
    不算重复，条目照留。"""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in summaries:
        if _comparable(item):
            kind = str(item.get("kind") or "")
            groups.setdefault((kind, _same_key(kind, item.get("name"))), []).append(item)
    found = []
    for items in groups.values():
        if len(items) < 2:
            continue
        keeper = next((item for item in items if item.get("has_image")), items[0])
        found.append((keeper, [item for item in items if item is not keeper]))
    return found


def skip_ids(summaries: Iterable[Mapping[str, Any]]) -> set[str]:
    """不单独出图的条目 id：同一类里被另一条盖住的；同名的几条(群演：同一拨人的几条)只留一条(已有图的那条，没有就排最前的)。
    ``summaries`` 是一个项目的库条目摘要(production_asset_readiness.element_summary 的形状)。"""
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for item in summaries:
        if _comparable(item):
            by_kind.setdefault(str(item.get("kind") or ""), []).append(item)
    skipped: set[str] = set()
    for items in by_kind.values():
        names = [item.get("name") for item in items]
        keepers: dict[str, Mapping[str, Any]] = {}
        for item in items:
            key = _same_key(item.get("kind"), item.get("name"))
            same = keepers.get(key)
            if same is None or (item.get("has_image") and not same.get("has_image")):
                keepers[key] = item
        for item in items:
            if contained_in(item.get("name"), names) or keepers[_same_key(item.get("kind"), item.get("name"))] is not item:
                skipped.add(str(item.get("id") or ""))
    return skipped


def companions(item: Mapping[str, Any], summaries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """要和 ``item`` 画进同一张图的配套条目：同一类里名字被它字面包含、却是另一样东西的(「长剑」之于「长剑剑鞘」、
    「刀」之于「刀鞘」、「门」之于「偏殿门」)。同一样东西的更全叫法(:func:`covered_by`)不算——那是同一样东西，
    不用另画。同名的几条只列一次，短的在前。数字演员与定妆图不在这里配。"""
    if not _comparable(item):
        return []
    found: dict[str, Mapping[str, Any]] = {}
    for row in summaries:
        if str(row.get("kind") or "") != str(item.get("kind") or "") or str(row.get("id") or "") == str(item.get("id") or ""):
            continue
        if inside(row.get("name"), item.get("name")) and not covered_by(row.get("name"), item.get("name")):
            key = _key(row.get("name"))
            if key not in found or (row.get("has_image") and not found[key].get("has_image")):
                found[key] = row
    return sorted(found.values(), key=lambda row: len(_key(row.get("name"))))


def related_partner(item: Mapping[str, Any], summaries: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """画 ``item`` 时当参考图带上的那一条：一起画进图里的配套条目(:func:`companions`)里以前已经有图的(名字最长的那条)。
    没有就是 None——那就照文字把两样一起画。"""
    drawn = [row for row in companions(item, summaries) if row.get("has_image")]
    return max(drawn, key=lambda row: len(_key(row.get("name"))), default=None)


def draw_after(batch: Iterable[Mapping[str, Any]], summaries: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """一批要出的图里，谁要等谁先画完：``{条目 id: 它参考的那条的 id}``，只列那条也在这一批里的。"""
    rows = list(summaries)
    wanted = list(batch)
    ids = {str(item.get("id") or "") for item in wanted}
    waits: dict[str, str] = {}
    for item in wanted:
        partner = related_partner(item, rows)
        if partner is not None and str(partner.get("id") or "") in ids:
            waits[str(item.get("id") or "")] = str(partner.get("id") or "")
    return waits


__all__ = ["companions", "contained_in", "covered_by", "crowd_key", "draw_after", "duplicate_groups", "inside", "related_partner", "skip_ids"]
