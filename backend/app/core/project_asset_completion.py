"""Finish a project's asset library at the end of stage 3.

Files every screenplay asset into the owner's library (reusing same-name assets
from earlier projects), generates the reference images that are still missing
for scenes, props and effects and every character's costume looks, and returns the
readiness snapshot the stage-4 gate reads. Runs in the synchronous stage worker like the other library
helpers; a library failure is reported in the snapshot instead of hiding it.
"""

from __future__ import annotations

import contextvars
import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Awaitable, Callable

from app import settings
from app.core.character_looks import crowd_wardrobe
from app.core.character_variants import is_current_look, is_look, variant_of
from app.core.element_scope import normalized_asset_name
from app.core.production_asset_extractor import extract_production_assets
from app.core.production_asset_readiness import (
    ASSET_KINDS,
    LIBRARY_KINDS,
    NON_ACTOR_KINDS,
    element_summary,
    evaluate_asset_readiness,
)
from app.platform.store import PlatformStore
from app.core import asset_dedupe, contained_assets, prompt_data, storyboard_concurrency


_WORDING_FILE = "project_asset_completion"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/project_asset_completion.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


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


async def merge_duplicate_elements(store: Any, owner_id: str, task_id: str, task: dict) -> list[str]:
    """把本项目里重复的条目并掉(见 contained_assets.duplicate_groups)，返回并掉的名字。

    并掉的名字记进留下那条的别名：剧本、分镜里还写着它的地方照样认到留下的那条，下次归档也不会再建出来。
    只在本项目里的那条直接删；别的项目也在用的，只从本项目拿掉。分镜已经绑了它的 id 的不动(还不出图)。
    """
    from app.api.element_api import delete_element_and_files
    from app.core.asset_dependents import shots_using
    from app.core.element_scope import element_name_keys

    merged: list[str] = []
    for keeper, losers in contained_assets.duplicate_groups(await project_element_summaries(store, owner_id, task_id)):
        losers = [item for item in losers if not shots_using(task, element_id=item["id"], kind=item["kind"], names=())]
        if not losers:
            continue
        aliases = [str(alias) for alias in (keeper.get("metadata") or {}).get("aliases") or [] if isinstance(alias, str)]
        known = element_name_keys(keeper["name"], keeper.get("metadata"))
        for item in losers:
            for name in [item["name"], *((item.get("metadata") or {}).get("aliases") or [])]:
                if isinstance(name, str) and normalized_asset_name(name) not in known:
                    aliases.append(name)
                    known.add(normalized_asset_name(name))
        await store.merge_element_metadata(keeper["id"], owner_id, {"aliases": aliases})
        for item in losers:
            others = [other for other in (item.get("metadata") or {}).get("task_ids") or [] if other != task_id]
            if others:
                await store.unlink_element_from_task(item["id"], owner_id, task_id)
            else:
                await delete_element_and_files(item["id"], owner_id, store)
            merged.append(item["name"])
    return merged


async def _complete(
    task: dict, owner_id: str, task_id: str, generate_missing: bool, ask: Callable[[str, str], str | None] | None = None,
) -> dict[str, Any]:
    # The API-layer helpers own the storage and image-validation rules; they are
    # reused here rather than duplicated so one policy governs both entry points.
    from app.api.drama_api import _file_character_looks, _file_crowd_wardrobe, _import_production_asset_candidates
    from app.api.element_api import _generate_look_image, _generate_non_actor_reference

    store = PlatformStore(settings.database_url())
    generated = 0
    failed: list[str] = []
    try:
        # 群演也归档：成队的戏服和妆效要画在群演图上。
        for kind in (*ASSET_KINDS, "extra"):
            await _import_production_asset_candidates(
                task_id=task_id,
                kind=kind,
                candidates=extract_production_assets(task, kind),
                owner_id=owner_id,
                store=store,
            )
        await _file_character_looks(task=task, task_id=task_id, owner_id=owner_id, store=store)
        await _file_crowd_wardrobe(task=task, task_id=task_id, owner_id=owner_id, store=store)
        # 重复的条目(同名的、同一场景的同一拨群演)并成一条，列表里不再显示，也不重复出图。
        merged = await merge_duplicate_elements(store, owner_id, task_id, task)
        # 字面认不出的换了说法的同一样东西，按描述交给文本模型分组并掉(见 asset_dedupe)；问不到就跳过。
        if ask is not None:
            try:
                groups = asset_dedupe.ask_groups(await project_element_summaries(store, owner_id, task_id), ask)
                merged += [name for row in await asset_dedupe.merge(store, owner_id, task_id, task, groups) for name in row["merged"]]
            except Exception as exc:  # a failed pass leaves the library as it was
                logger.warning("阶段3资产按描述并重复失败（不阻断）: %s", type(exc).__name__)
        if generate_missing:
            limit = max(0, int(os.getenv("STAGE3_ASSET_IMAGE_LIMIT", "60")))
            summaries = await project_element_summaries(store, owner_id, task_id)
            # 定妆图排前面：缺它进不了分镜，上限先让给它。
            crowd = {normalized_asset_name(item["name"]) for item in crowd_wardrobe(task)}
            def later(item: dict) -> bool:
                return bool((variant_of(item) or {}).get("later"))

            covered = contained_assets.skip_ids(summaries)
            pending = [
                *(item for item in summaries if not item["has_image"] and is_current_look(item) and not later(item)),
                # 成队的戏服和妆效画在群演图上，和定妆图一样提前备好。
                *(item for item in summaries if item["kind"] == "extra" and not item["has_image"] and normalized_asset_name(item["name"]) in crowd),
                # 同一类里被另一条名字盖住的(续跑时抽取措辞变了留下的「香头」与「偏殿香头」)不单独出图。
                *(item for item in summaries if item["kind"] in NON_ACTOR_KINDS and not item["has_image"]
                  and item["id"] not in covered),
                # 剧本还没写到的那几集穿的：进分镜用不上，排在最后。
                *(item for item in summaries if not item["has_image"] and is_current_look(item) and later(item)),
            ][:limit]
            # 几张图同时出：一张约 100 秒，挨个出要几十分钟。按上面的先后顺序开工，定妆图先占位；每张图的出法和质检都不变。
            # 这一步是阶段 3 里最长的一段(实测 22 张图、3 张同时出要 11 分钟)，这时没有别的出图在跑，
            # 所以默认用满本进程的出图上限(和分镜同一个 STORYBOARD_IMAGE_CEILING，默认 6)；
            # 供应商限流时网关会等一等再问，不算失败。STAGE3_ASSET_IMAGE_CONCURRENCY 可以调回去。
            from app.api.element_api import ELEMENT_IMAGE_GENERATION_CONCURRENCY

            semaphore = asyncio.Semaphore(settings.env_int(
                "STAGE3_ASSET_IMAGE_CONCURRENCY",
                max(ELEMENT_IMAGE_GENERATION_CONCURRENCY, storyboard_concurrency.image_ceiling()),
                minimum=1,
            ))

            # 配套的两样(「长剑」与「长剑剑鞘」)：后画的那张等先画的画完，再带上它一起出。
            waits = contained_assets.draw_after(pending, summaries)
            finished = {summary["id"]: asyncio.Event() for summary in pending}

            async def draw(summary: dict) -> bool:
                if summary["id"] in waits:
                    await finished[waits[summary["id"]]].wait()
                try:
                    return await draw_one(summary)
                finally:
                    finished[summary["id"]].set()

            async def draw_one(summary: dict) -> bool:
                async with semaphore:
                    item = await store.get_element(summary["id"], owner_id)
                    if item is None:
                        return False
                    try:
                        if is_look(summary):
                            await _generate_look_image(item=item, owner_id=owner_id, store=store)
                        else:
                            await _generate_non_actor_reference(
                                item=item,
                                owner_id=owner_id,
                                store=store,
                                extra_prompt=_text_of("_complete.extra_prompt"),
                            )
                        return True
                    except Exception as exc:  # one failed image must not stop the others
                        failed.append(summary["name"])
                        logger.warning(
                            "阶段3资产参考图生成失败: kind=%s name=%s error=%s",
                            summary["kind"], summary["name"], type(exc).__name__,
                        )
                        return False

            generated += sum(await asyncio.gather(*(draw(summary) for summary in pending)))
        summaries = await project_element_summaries(store, owner_id, task_id)
    finally:
        await store.close()
    readiness = evaluate_asset_readiness(task, summaries)
    readiness["generated"] = generated
    readiness["merged_duplicates"] = merged[:50]
    readiness["generation_failed"] = failed[:50]
    return readiness


def complete_project_assets(
    task: dict, *, generate_missing: bool = True, ask: Callable[[str, str], str | None] | None = None,
) -> dict[str, Any]:
    """Sync + generate + evaluate for the stage worker; never raises. ``ask(system, user)`` is the text model for
    merging differently worded duplicates (asset_dedupe); without it that pass is skipped."""
    owner_id = str(task.get("owner_user_id") or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    if not owner_id or not task_id:
        return evaluate_asset_readiness(task, None)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return evaluate_asset_readiness(task, None, library_error=_text_of("complete_project_assets.library_error"))
    try:
        return asyncio.run(_complete(task, owner_id, task_id, generate_missing, ask))
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
        return pool.submit(contextvars.copy_context().run, lambda: asyncio.run(factory())).result()


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
