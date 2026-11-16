# -*- coding: utf-8 -*-
"""项目资产库里换了说法的同一样东西，按描述并成一条。

第 3 步多次续跑、拆解的措辞每次不同，同一把剑会在库里留下「带鞘长剑（裴照的剑）」「裴照的带鞘长剑」
「裴照腰佩长剑」几条。名字一字不差的重复和被另一条完整盖住的叫法由 :mod:`app.core.contained_assets`
按字面认；字面认不出的，这里按名字和描述交给文本模型分组(:func:`ask_groups`)，每组留一条(:func:`keeper`)。

并掉的几条：名字记进留下那条的别名(剧本、分镜里还写着旧名字的地方照样认到它，下次归档也不会再建出来)，
条目从本项目摘掉(``unlink``，图和条目都还在资产库里，可以恢复)，元数据记 ``merged_into``。
分镜已经绑了它的不动。数字演员与定妆图不在这里并(定妆图归 character_looks 按时间线规划)。
措辞和参与的资产类型在 ``app/data/prompt/asset_dedupe.json``。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from app.core import prompt_data
from app.core.element_scope import element_name_keys, normalized_asset_name

_DATA = "asset_dedupe"
MERGED_INTO = "merged_into"
_JSON = re.compile(r"\{.*\}", re.S)


def kinds() -> tuple[str, ...]:
    return tuple(prompt_data.words(_DATA, "kinds"))


def _label(kind: str) -> str:
    from app.core.storyboard_scene_context import LABELS

    return LABELS.get(kind, kind)


def prompt(kind: str, items: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """(系统提示, 用户提示)：这一类的清单，编号从 1 起。"""
    lines = [
        prompt_data.text(_DATA, "item").format(
            number=number, name=str(item.get("name") or ""),
            description=" ".join(str(item.get("description") or "").split()) or prompt_data.text(_DATA, "no_description"),
        )
        for number, item in enumerate(items, start=1)
    ]
    return prompt_data.text(_DATA, "system"), prompt_data.text(_DATA, "user").format(label=_label(kind), items="\n".join(lines))


def parse_groups(answer: str | None, count: int) -> list[list[int]]:
    """模型给的分组：只留编号在 1..count 之内、至少两条、互不重叠的组(编号从 0 起返回)。读不出来就是没有。"""
    match = _JSON.search(str(answer or ""))
    if not match:
        return []
    try:
        groups = json.loads(match.group(0)).get("groups")
    except (ValueError, AttributeError):
        return []
    taken: set[int] = set()
    found: list[list[int]] = []
    for group in groups if isinstance(groups, list) else []:
        members = list(dict.fromkeys(
            int(number) - 1 for number in (group if isinstance(group, list) else [])
            if isinstance(number, (int, str)) and str(number).strip().isdigit() and 1 <= int(number) <= count
        ))
        members = [index for index in members if index not in taken]
        if len(members) >= 2:
            taken.update(members)
            found.append(members)
    return found


def keeper(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """一组里留下的那条：画着配套几样的(drawn_together)优先，再是有图的，再是名字最长的，再是排在前面的。"""
    def rank(pair: tuple[int, Mapping[str, Any]]) -> tuple[bool, bool, int, int]:
        index, item = pair
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        return (bool(metadata.get("drawn_together")), bool(item.get("has_image")), len(str(item.get("name") or "")), -index)

    return max(enumerate(items), key=rank)[1]


def ask_groups(
    summaries: Iterable[Mapping[str, Any]], ask: Callable[[str, str], str | None],
) -> list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]]:
    """按类问模型，返回 (留下的那条, [并掉的几条])。``ask(system, user)`` 返回模型的回答；一类少于两条不问。"""
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    wanted = set(kinds())
    for item in summaries:
        kind = str(item.get("kind") or "")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        if kind in wanted and not metadata.get(MERGED_INTO):
            by_kind.setdefault(kind, []).append(item)
    merged: list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]] = []
    for kind, items in by_kind.items():
        if len(items) < 2:
            continue
        system, user = prompt(kind, items)
        for group in parse_groups(ask(system, user), len(items)):
            members = [items[index] for index in group]
            kept = keeper(members)
            merged.append((kept, [item for item in members if item is not kept]))
    return merged


def aliases_after(kept: Mapping[str, Any], losers: Iterable[Mapping[str, Any]]) -> list[str]:
    """留下那条合并后的别名：原有的，加上并掉那几条的名字和它们的别名(和留下那条已认的名字重复的不加)。"""
    metadata = kept.get("metadata") if isinstance(kept.get("metadata"), Mapping) else {}
    aliases = [str(alias) for alias in metadata.get("aliases") or [] if isinstance(alias, str)]
    known = element_name_keys(kept.get("name"), metadata)
    for item in losers:
        own = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        for name in [item.get("name"), *(own.get("aliases") or [])]:
            if isinstance(name, str) and normalized_asset_name(name) and normalized_asset_name(name) not in known:
                aliases.append(name)
                known.add(normalized_asset_name(name))
    return aliases


def rebind_shots(task: Mapping[str, Any], kept: Mapping[str, Any], losers: Iterable[Mapping[str, Any]], *, version: int = 0) -> int:
    """分镜里绑着并掉那几条的，改绑到留下那条(改 ``task`` 本身，调用方负责存)。返回改了几个镜头。

    只改分镜绑定(素材库 id、名字、版本)，不改镜头的画面、动作和道具清单：第 5 阶段复用片段按运动契约的
    指纹认，这里改了也不会让已出的片段判成要重出。一镜里已经绑了留下那条的，并掉那条的绑定直接去掉。
    """
    ids = {str(item.get("id") or "") for item in losers} - {""}
    names = {normalized_asset_name(item.get("name")) for item in losers} - {""}
    kind = str(kept.get("kind") or "")
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    changed = 0
    for shot in assets.get("4") or []:
        bindings = shot.get("asset_bindings") if isinstance(shot, dict) else None
        if not isinstance(bindings, list):
            continue
        has_kept = any(isinstance(item, Mapping) and str(item.get("element_id") or "") == str(kept.get("id") or "") for item in bindings)
        rewritten: list[Any] = []
        touched = False
        for binding in bindings:
            hit = isinstance(binding, Mapping) and str(binding.get("kind") or "") == kind and (
                str(binding.get("element_id") or "") in ids
                or (not binding.get("element_id") and normalized_asset_name(binding.get("name")) in names)
            )
            if not hit:
                rewritten.append(binding)
                continue
            touched = True
            if not has_kept:
                rewritten.append({**binding, "element_id": str(kept.get("id") or ""), "name": str(kept.get("name") or ""), "element_version": int(version)})
                has_kept = True
        if touched:
            shot["asset_bindings"] = rewritten
            changed += 1
    return changed


def remap_clip_versions(task: Mapping[str, Any], kept: Mapping[str, Any], losers: Iterable[Mapping[str, Any]], *, version: int) -> int:
    """已出的片段记着出片时用的资产版本(``asset_versions``，{素材库 id: 版本})，第 5 阶段复用片段要逐项对上。

    并掉之后，剧本里的旧名字认到的是留下那条：把片段记录里并掉那几条的 id 换成留下那条和它现在的版本，
    已出的片子照旧复用，不会因为合并被判成要重出(改 ``task`` 本身，调用方负责存)。返回改了几段。
    """
    ids = {str(item.get("id") or "") for item in losers} - {""}
    kept_id = str(kept.get("id") or "")
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    changed = 0
    for clip in assets.get("5") or []:
        versions = clip.get("asset_versions") if isinstance(clip, dict) else None
        if not isinstance(versions, dict) or not ids & set(versions):
            continue
        clip["asset_versions"] = {
            **{key: value for key, value in versions.items() if key not in ids},
            kept_id: int(version),
        }
        changed += 1
    return changed


async def merge(
    store: Any, owner_id: str, task_id: str, task: Mapping[str, Any],
    groups: Iterable[tuple[Mapping[str, Any], list[Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """把分好的组并掉：别名记到留下那条，其余的从本项目摘掉。分镜已经绑了的不动。返回 [{kept, merged: [名字…]}]。"""
    from app.core.asset_dependents import shots_using

    done: list[dict[str, Any]] = []
    for kept, losers in groups:
        losers = [item for item in losers if not shots_using(task, element_id=str(item.get("id") or ""), kind=str(item.get("kind") or ""), names=())]
        if not losers:
            continue
        await store.merge_element_metadata(kept["id"], owner_id, {"aliases": aliases_after(kept, losers)})
        for item in losers:
            await store.merge_element_metadata(item["id"], owner_id, {MERGED_INTO: str(kept["id"])})
            await store.unlink_element_from_task(item["id"], owner_id, task_id)
        done.append({"kept": str(kept.get("name") or ""), "kind": str(kept.get("kind") or ""), "merged": [str(item.get("name") or "") for item in losers]})
    return done


__all__ = ["MERGED_INTO", "aliases_after", "ask_groups", "keeper", "kinds", "merge", "parse_groups", "prompt", "rebind_shots", "remap_clip_versions"]
