# -*- coding: utf-8 -*-
"""创作者打「@」能点名的东西：这个项目的角色、场景、道具和资产库里挂在本项目的元素。

候选来自三处：项目角色(``assets.3_characters``)、资产库里挂在本项目的元素(按 ``element_in_task``)、
分镜里的场(``stage_locator.scenes_of``)。同一类里名字相同(去掉空格标点、不分大小写)只留一条，
资产库的那条优先：它有 element_id 和缩略图。名字超过 40 个字的放不进 ``@[名字]``，不列。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any

from app.core import stage_locator
from app.core.asset_mentions import MENTION_NAME_LIMIT
from app.core.element_scope import element_in_task, element_name_keys, normalized_asset_name

logger = logging.getLogger(__name__)

#: 资产库里能被 @ 的元素类型，也是同序时的排序次序(actor、scene、prop 之后按这个顺序)。
LIBRARY_KINDS: tuple[str, ...] = ("actor", "scene", "prop", "costume", "effect", "product", "extra", "vehicle", "set_dressing")
DESCRIPTION_LIMIT = 80
_PAGE_SIZE = 100
_ORDER = {kind: index for index, kind in enumerate(LIBRARY_KINDS)}


def _text(value: Any) -> str:
    return str(value or "").strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _aliases(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[、，,/]", value)
    found: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else ():
        text = _text(item)
        if text and text not in found:
            found.append(text)
    return found


def _entry(name: str, kind: str, *, element_id: str = "", aliases: Any = (), description: Any = "", thumb_url: str = "") -> dict[str, Any]:
    clean = [alias for alias in _aliases(aliases) if alias != name]
    return {
        "name": name, "kind": kind, "element_id": element_id, "aliases": clean,
        "description": _text(description)[:DESCRIPTION_LIMIT], "thumb_url": thumb_url,
    }


def _usable(name: str) -> bool:
    return bool(name) and len(name) <= MENTION_NAME_LIMIT and not re.search(r"[\[\]\n]", name)


def _character_thumb(record: Mapping[str, Any]) -> str:
    views = {_text(v.get("view")): _text(v.get("image_url")) for v in record.get("views") or [] if isinstance(v, Mapping)}
    cells = {_text(c.get("cell")): _text(c.get("image_url")) for c in record.get("sheet_cells") or [] if isinstance(c, Mapping)}
    for url in (views.get("face_front"), views.get("front"), cells.get("portrait"), _text(record.get("image_url")), _text(record.get("sheet"))):
        if url:
            return url
    return ""


def _project_characters(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    raw = assets.get("3_characters")
    found: list[dict[str, Any]] = []
    for record in raw if isinstance(raw, list) else ():
        if not isinstance(record, Mapping):
            continue
        name = _text(record.get("name"))
        if _usable(name):
            found.append(_entry(
                name, "actor", aliases=record.get("aliases"),
                description=record.get("desc") or record.get("description"), thumb_url=_character_thumb(record),
            ))
    return found


def _storyboard_scenes(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for scene in stage_locator.scenes_of(task):
        name = _text(scene.get("name"))
        scene_id = _text(scene.get("scene_id"))
        if _usable(name):
            found.append(_entry(name, "scene", aliases=[scene_id] if scene_id else (), description=scene_id))
    return found


def _thumb(item: Any) -> str:
    element_id = _text(getattr(item, "id", ""))
    version = getattr(item, "version", 1) or 1
    for file in getattr(item, "files", None) or []:
        if str(getattr(file, "mime_type", "") or "").startswith("image/") and _text(getattr(file, "id", "")):
            return f"/api/elements/{element_id}/files/{file.id}/content?v={version}"
    return ""


async def _library(store: Any, owner_id: str, task_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind in LIBRARY_KINDS:
        page = 1
        while True:
            items, total = await store.list_elements(owner_id, kind, page, _PAGE_SIZE)
            if not items:
                break
            for item in items:
                element_id = _text(getattr(item, "id", ""))
                metadata = getattr(item, "metadata_json", None)
                name = _text(getattr(item, "name", ""))
                if (
                    not element_id or element_id in seen
                    or str(getattr(item, "owner_id", owner_id) or "") != owner_id
                    or str(getattr(item, "kind", kind) or "") != kind
                    or not element_in_task(metadata, task_id) or not _usable(name)
                ):
                    continue
                seen.add(element_id)
                found.append(_entry(
                    name, kind, element_id=element_id, aliases=(metadata or {}).get("aliases"),
                    description=getattr(item, "description", ""), thumb_url=_thumb(item),
                ))
            if page * _PAGE_SIZE >= int(total or 0):
                break
            page += 1
    return found


def _keys(entry: Mapping[str, Any]) -> set[str]:
    return element_name_keys(entry.get("name"), {"aliases": list(entry.get("aliases") or [])})


def _merge(project: list[dict[str, Any]], library: list[dict[str, Any]], scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同类同名合成一条，资产库优先，位置按先出现的(项目角色、资产库、分场)。
    项目角色的名字或别名对上资产库演员的名字或别名(element_name_keys)也算同一个人。"""
    merged: list[dict[str, Any]] = []

    def absorb(target: dict[str, Any], other: Mapping[str, Any]) -> None:
        for alias in [other.get("name"), *(other.get("aliases") or [])]:
            alias = _text(alias)
            if alias and alias != target["name"] and alias not in target["aliases"]:
                target["aliases"].append(alias)
        for key in ("description", "thumb_url"):
            if not target.get(key) and other.get(key):
                target[key] = other[key]

    def find(entry: Mapping[str, Any], *, by_alias: bool) -> int | None:
        name = normalized_asset_name(entry["name"])
        for position, item in enumerate(merged):
            if item["kind"] == entry["kind"] and normalized_asset_name(item["name"]) == name:
                return position
        if by_alias:
            keys = _keys(entry)
            for position, item in enumerate(merged):
                if item["kind"] == entry["kind"] and not item["element_id"] and keys & _keys(item):
                    return position
        return None

    for entry in project:
        position = find(entry, by_alias=False)
        if position is None:
            merged.append(entry)
        else:
            absorb(merged[position], entry)
    for entry in library:
        position = find(entry, by_alias=entry["kind"] == "actor")
        if position is None:
            merged.append(entry)
        elif merged[position]["element_id"]:
            absorb(merged[position], entry)
        else:
            # 资产库那条顶替项目里的同名条目，项目条目的别名和简介补进来。
            absorb(entry, merged[position])
            merged[position] = entry
    for entry in scenes:
        position = find(entry, by_alias=False)
        if position is None:
            merged.append(entry)
        else:
            absorb(merged[position], entry)
    return merged


def _matches(entry: Mapping[str, Any], query: str) -> bool:
    needle = normalized_asset_name(query)
    return not needle or any(needle in normalized_asset_name(name) for name in [entry.get("name"), *(entry.get("aliases") or [])])


def _arrange(project: list[dict[str, Any]], library: list[dict[str, Any]], scenes: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    # sorted 稳定：同类里保持先出现的顺序(项目角色、资产库、分场)。
    ordered = sorted(_merge(project, library, scenes), key=lambda entry: _ORDER.get(entry["kind"], len(_ORDER)))
    picked = [entry for entry in ordered if _matches(entry, query)]
    return picked[:max(0, int(limit))]


async def mentionable_async(store: Any, task: Mapping[str, Any], *, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """@ 候选：``[{name, kind, element_id, aliases, description, thumb_url}]``，按 actor、scene、prop、其他排。

    ``store`` 是 PlatformStore(或同接口的东西)；没有 store、任务没有主人或资产库读失败时只列项目里的角色和场。"""
    task = task if isinstance(task, Mapping) else {}
    project = _project_characters(task)
    try:
        scenes = _storyboard_scenes(task)
    except Exception:  # noqa: BLE001 - 坏数据不该让候选列表整个失败
        logger.warning("@ 候选：分镜场次读取失败", exc_info=True)
        scenes = []
    owner_id = _text(task.get("owner_user_id"))
    task_id = _text(task.get("task_id"))
    library: list[dict[str, Any]] = []
    if store is not None and owner_id and task_id:
        try:
            library = await _library(store, owner_id, task_id)
        except Exception as exc:  # noqa: BLE001 - 资产库不可用时项目里的名字照样能 @
            logger.warning("@ 候选：资产库读取失败: %s", type(exc).__name__)
    return _arrange(project, library, scenes, query, limit)


def _fresh_store() -> Any:
    # 工作线程有自己的事件循环，不能复用 API 那份缓存的异步引擎。
    from app import settings
    from app.platform.store import PlatformStore

    return PlatformStore(settings.database_url())


async def _with_fresh_store(task: Mapping[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    store = _fresh_store()
    try:
        return await mentionable_async(store, task, query=query, limit=limit)
    finally:
        await store.close()


def mentionable(task: Mapping[str, Any], *, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """同步版，给工作线程用：新开一个 store，在 asyncio.run 里读。在事件循环里调用会抛 RuntimeError。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("mentionable must run in a worker thread; use mentionable_async in async code")
    task = task if isinstance(task, Mapping) else {}
    if not (_text(task.get("owner_user_id")) and _text(task.get("task_id"))):
        return asyncio.run(mentionable_async(None, task, query=query, limit=limit))
    return asyncio.run(_with_fresh_store(task, query, limit))
