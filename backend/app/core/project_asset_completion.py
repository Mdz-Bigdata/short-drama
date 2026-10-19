"""Finish a project's asset library at the end of stage 3.

Files every screenplay asset into the owner's library (reusing same-name assets
from earlier projects), generates the reference images that are still missing
for scenes, props, costumes and effects, and returns the readiness snapshot the
stage-4 gate reads. Runs in the synchronous stage worker like the other library
helpers; a library failure is reported in the snapshot instead of hiding it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Awaitable, Callable

from app import settings
from app.core.production_asset_extractor import extract_production_assets
from app.core.production_asset_readiness import (
    ASSET_KINDS,
    LIBRARY_KINDS,
    NON_ACTOR_KINDS,
    element_summary,
    evaluate_asset_readiness,
)
from app.platform.store import PlatformStore

logger = logging.getLogger(__name__)
_PAGE_SIZE = 100


async def project_element_summaries(store: Any, owner_id: str, task_id: str) -> list[dict[str, Any]]:
    """Project-scoped summaries for every kind, paging like the storyboard loader."""
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind in LIBRARY_KINDS:
        page = 1
        while True:
            items, total = await store.list_elements(owner_id, kind, page, _PAGE_SIZE)
            if not items:
                break
            for item in items:
                summary = element_summary(item, owner_id, task_id)
                if summary and summary["kind"] == kind and summary["id"] not in seen:
                    seen.add(summary["id"])
                    summaries.append(summary)
            if page * _PAGE_SIZE >= total:
                break
            page += 1
    return summaries


async def _complete(task: dict, owner_id: str, task_id: str, generate_missing: bool) -> dict[str, Any]:
    # The API-layer helpers own the storage and image-validation rules; they are
    # reused here rather than duplicated so one policy governs both entry points.
    from app.api.drama_api import _import_production_asset_candidates
    from app.api.element_api import _generate_non_actor_reference

    store = PlatformStore(settings.database_url())
    generated = 0
    failed: list[str] = []
    try:
        for kind in ASSET_KINDS:
            await _import_production_asset_candidates(
                task_id=task_id,
                kind=kind,
                candidates=extract_production_assets(task, kind),
                owner_id=owner_id,
                store=store,
            )
        if generate_missing:
            limit = max(0, int(os.getenv("STAGE3_ASSET_IMAGE_LIMIT", "60")))
            pending = [
                summary for summary in await project_element_summaries(store, owner_id, task_id)
                if summary["kind"] in NON_ACTOR_KINDS and not summary["has_image"]
            ][:limit]
            for summary in pending:
                item = await store.get_element(summary["id"], owner_id)
                if item is None:
                    continue
                try:
                    await _generate_non_actor_reference(
                        item=item,
                        owner_id=owner_id,
                        store=store,
                        extra_prompt="按剧本资产描述生成可直接用于本项目的完整参考图",
                    )
                    generated += 1
                except Exception as exc:  # one failed image must not stop the others
                    failed.append(summary["name"])
                    logger.warning(
                        "阶段3资产参考图生成失败: kind=%s name=%s error=%s",
                        summary["kind"], summary["name"], type(exc).__name__,
                    )
        summaries = await project_element_summaries(store, owner_id, task_id)
    finally:
        await store.close()
    readiness = evaluate_asset_readiness(task, summaries)
    readiness["generated"] = generated
    readiness["generation_failed"] = failed[:50]
    return readiness


def complete_project_assets(task: dict, *, generate_missing: bool = True) -> dict[str, Any]:
    """Sync + generate + evaluate for the stage worker; never raises."""
    owner_id = str(task.get("owner_user_id") or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    if not owner_id or not task_id:
        return evaluate_asset_readiness(task, None)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return evaluate_asset_readiness(task, None, library_error="必须在同步阶段工作线程中完成资产库同步")
    try:
        return asyncio.run(_complete(task, owner_id, task_id, generate_missing))
    except Exception as exc:
        logger.warning("阶段3资产库同步失败: %s", type(exc).__name__)
        return evaluate_asset_readiness(task, None, library_error=type(exc).__name__)


def _run_blocking(factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run a private-store coroutine from sync code, even under a running loop.

    Stage claiming happens inside API coroutines; the gate must still consult the
    library there instead of trusting a possibly stale snapshot, so the read gets
    its own thread and event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


async def _read(owner_id: str, task_id: str) -> list[dict[str, Any]]:
    store = PlatformStore(settings.database_url())
    try:
        return await project_element_summaries(store, owner_id, task_id)
    finally:
        await store.close()


def evaluate_project_assets(task: dict) -> dict[str, Any]:
    """Read-only readiness for the stage-4 gate; a library failure fails closed."""
    owner_id = str(task.get("owner_user_id") or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    if not owner_id or not task_id:
        return evaluate_asset_readiness(task, None)
    try:
        summaries = _run_blocking(lambda: _read(owner_id, task_id))
    except Exception as exc:
        logger.warning("阶段4前置资产检查读取资产库失败: %s", type(exc).__name__)
        return evaluate_asset_readiness(task, None, library_error=type(exc).__name__)
    return evaluate_asset_readiness(task, summaries)
