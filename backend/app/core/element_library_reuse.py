"""Reuse approved actors from the shared library before paying for new ones.

Stage 3 calls this from its synchronous worker. A library actor qualifies when a
previous project filed a passed identity-view set — the current five anchors, or
the legacy five-view angles for records filed before the actor-sheet relayout —
with every image still on local media. The match is linked to the current project so the storyboard
stage can read the same asset. Any failure here degrades to "generate as usual":
reuse is an optimisation and must never block production.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import unquote, urlparse

from app.core.element_scope import element_in_task, element_name_keys, normalized_asset_name
from app.core.media_compositor import MEDIA_DIR
from app.platform.dependencies import DEFAULT_DATABASE_URL
from app.platform.store import PlatformStore
from app.schema.production import IDENTITY_VIEW_ORDER, LEGACY_IDENTITY_VIEW_ORDER

logger = logging.getLogger(__name__)
#: 当前契约的五个身份锚点。
REQUIRED_VIEWS = IDENTITY_VIEW_ORDER
#: 旧五视图整板的五个角度；存量资产按它入库，复用时同样认。
LEGACY_REQUIRED_VIEWS = LEGACY_IDENTITY_VIEW_ORDER


def _local_media_exists(url: str) -> bool:
    """Only locally stored renders are reusable; provider URLs expire."""
    path = urlparse(str(url or "")).path
    if not path.startswith("/media/"):
        return False
    media_root = os.path.realpath(MEDIA_DIR)
    absolute = os.path.realpath(os.path.join(media_root, unquote(path[len("/media/"):])))
    return absolute.startswith(media_root + os.sep) and os.path.isfile(absolute)


def _approved_views(metadata: dict) -> list[dict[str, str]]:
    raw = metadata.get("views")
    if not metadata.get("five_view_passed") or not isinstance(raw, list):
        return []
    by_view: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        view = str(item.get("view") or "").strip()
        url = str(item.get("image_url") or "").strip()
        if view and url and view not in by_view:
            by_view[view] = url
    # 新契约的锚点优先；整套齐不了就退回旧五视图角度，两代资产都能复用。
    for wanted in (REQUIRED_VIEWS, LEGACY_REQUIRED_VIEWS):
        if all(view in by_view and _local_media_exists(by_view[view]) for view in wanted):
            return [{"view": view, "image_url": by_view[view]} for view in wanted]
    return []


def _sheet_type(views: list[dict[str, str]]) -> str:
    """复用来的资产是哪一代排版——旧五视图整板不要冒充 25 格设定集。"""
    matched = tuple(item["view"] for item in views)
    return "actor_sheet_25_cell" if matched == REQUIRED_VIEWS else "ordered_five_view_turnaround"


async def _find(owner_id: str, task_id: str, names: list[str]) -> dict[str, dict[str, Any]]:
    store = PlatformStore(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
    wanted = {normalized_asset_name(name): name for name in names if str(name or "").strip()}
    found: dict[str, dict[str, Any]] = {}
    try:
        for item in await store.list_all_elements(owner_id, "actor"):
            metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
            name = next(
                (wanted[key] for key in element_name_keys(item.name, metadata) if key in wanted),
                None,
            )
            if not name or name in found:
                continue
            views = _approved_views(metadata)
            if not views:
                continue
            sheet = str(metadata.get("sheet_url") or "").strip()
            if sheet and not _local_media_exists(sheet):
                sheet = ""
            if not element_in_task(metadata, task_id):
                await store.link_element_to_task(item.id, owner_id, task_id)
            found[name] = {
                "name": name,
                "role": str(metadata.get("role") or ""),
                "desc": str(item.description or ""),
                "sheet": sheet,
                "sheet_type": _sheet_type(views),
                "views": views,
                "five_view_quality": {
                    "passed": True,
                    "entropy": [],
                    "palette_similarity": 0,
                    "unique_view_hashes": len(views),
                    "issues": [],
                    "reused_from_library": str(item.id),
                },
            }
    finally:
        await store.close()
    return found


def find_library_characters(task: dict, names: list[str]) -> dict[str, dict[str, Any]]:
    """Approved library actors for ``names``, keyed by the requested name."""
    owner_id = str(task.get("owner_user_id") or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    if not owner_id or not task_id or not names:
        return {}
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        logger.warning("角色资产库复用只能在同步阶段工作线程中执行，本次跳过复用")
        return {}
    try:
        return asyncio.run(_find(owner_id, task_id, list(names)))
    except Exception as exc:
        logger.warning("角色资产库复用读取失败，按剧本重新生成: %s", type(exc).__name__)
        return {}
