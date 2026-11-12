# -*- coding: utf-8 -*-
"""捏脸后把新描述写回元素库里这位数字演员：下一个项目复用这张脸时读到的也是捏过的那一版。

只认绑定到本项目(``metadata.task_id`` / ``task_ids``)、名字对得上(忽略大小写与空格标点，别名也算)的 actor 元素；
找不到就 ``updated=False``。元素库出错从不打断保存：记一条日志，把原因放进 ``error`` 返回。

同步调用方(第 5 阶段工人、Agent 工具)用 ``sync_actor_description``：它像 ``load_storyboard_elements`` 一样新开一个
``PlatformStore``、在自己的事件循环里跑完就关；已经在事件循环里时它拒绝运行，请改用 ``sync_actor_description_async``。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from app import settings
from app.core.element_scope import element_in_task, element_name_keys, normalized_asset_name

logger = logging.getLogger(__name__)
_KIND = "actor"
_PAGE_SIZE = 100


def _owner_and_task(task: Mapping[str, Any]) -> tuple[str, str]:
    return str(task.get("owner_user_id") or "").strip(), str(task.get("task_id") or "").strip()


def _wanted_keys(task: Mapping[str, Any], name: str) -> set[str]:
    """这个人的名字和第一个别名，按元素库的归一化规则。"""
    from app.core.face_sculpt import _split_names

    keys = {normalized_asset_name(name)}
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    for item in assets.get("3_characters") or []:
        if isinstance(item, Mapping) and str(item.get("name") or "").strip() == str(name or "").strip():
            keys.update(normalized_asset_name(alias) for alias in _split_names(item.get("aliases"))[:1])
            break
    keys.discard("")
    return keys


async def _find_actor(store: Any, owner_id: str, task_id: str, keys: set[str]) -> Any:
    page = 1
    while True:
        items, total = await store.list_elements(owner_id, _KIND, page, _PAGE_SIZE)
        if not items:
            return None
        for item in items:
            metadata = getattr(item, "metadata_json", None)
            if (
                str(getattr(item, "owner_id", "")) != owner_id
                or str(getattr(item, "kind", "")) != _KIND
                or not element_in_task(metadata, task_id)
            ):
                continue
            if keys & element_name_keys(getattr(item, "name", ""), metadata):
                return item
        if page * _PAGE_SIZE >= int(total or 0):
            return None
        page += 1


async def sync_actor_description_async(store: Any, task: Mapping[str, Any], name: str, description: str) -> dict[str, Any]:
    """把 ``description`` 写进元素库里本项目的同名数字演员。返回 {updated, element_id[, error]}，从不抛。"""
    owner_id, task_id = _owner_and_task(task)
    if not owner_id or not task_id or not str(name or "").strip():
        return {"updated": False, "element_id": ""}
    try:
        element = await _find_actor(store, owner_id, task_id, _wanted_keys(task, name))
        if element is None:
            return {"updated": False, "element_id": ""}
        element_id = str(getattr(element, "id", "") or "")
        await store.update_element(element_id, owner_id, name=None, description=str(description or ""))
        return {"updated": True, "element_id": element_id}
    except Exception as exc:  # noqa: BLE001 - 元素库的毛病不该让捏脸保存失败
        logger.warning("捏脸写回元素库失败(%s): %s", name, type(exc).__name__)
        return {"updated": False, "element_id": "", "error": f"{type(exc).__name__}: {exc}"[:200]}


def sync_actor_description(task: Mapping[str, Any], name: str, description: str) -> dict[str, Any]:
    """同步版：新开一个 PlatformStore 在自己的事件循环里跑；已在事件循环里时抛 ``RuntimeError``，请用异步版。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("sync_actor_description must run outside the event loop; use sync_actor_description_async")

    async def run() -> dict[str, Any]:
        from app.platform.store import PlatformStore

        # 与 load_storyboard_elements 同一条规矩：工作线程不复用接口层缓存的异步引擎。
        store = PlatformStore(settings.database_url())
        try:
            return await sync_actor_description_async(store, task, name, description)
        finally:
            await store.close()

    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - 连库都开不了也只是没同步成
        logger.warning("捏脸写回元素库失败(%s): %s", name, type(exc).__name__)
        return {"updated": False, "element_id": "", "error": f"{type(exc).__name__}: {exc}"[:200]}


__all__ = ["sync_actor_description", "sync_actor_description_async"]
