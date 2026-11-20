"""Characters, scenes and props extracted chapter by chapter into a pending list, confirmed into the asset library."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.drama_api import require_owned_drama_task, service
from app.core import chapter_assets, usage_ledger
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore

logger = logging.getLogger("app.api.chapter_assets_api")
router = APIRouter(prefix="/api/drama", tags=["chapter-assets"], dependencies=[Depends(require_owned_drama_task)])
PURPOSE = "chapter_assets"


class ExtractRequest(BaseModel):
    chapter_id: str = Field(min_length=1, max_length=200)


class SettleRequest(BaseModel):
    action: str = Field(min_length=1, max_length=16)


async def _task(task_id: str) -> dict:
    task = await run_in_threadpool(service.repo.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not Found")
    return task


def _refused(error: chapter_assets.ChapterAssetError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


@router.get("/{task_id}/chapter-assets")
async def chapter_assets_view(task_id: str):
    return chapter_assets.view(await _task(task_id))


@router.post("/{task_id}/chapter-assets/extract")
async def extract_chapter(task_id: str, request: ExtractRequest):
    """One text call reads one chapter. An answer without all three lists is reported and records nothing."""
    task = await _task(task_id)
    try:
        target = chapter_assets.chapter(task, request.chapter_id)
    except chapter_assets.ChapterAssetError as error:
        raise _refused(error) from error
    system, user = chapter_assets.prompt(task, target)
    config = task.get("config") if isinstance(task.get("config"), dict) else {}

    def ask() -> str:
        with usage_ledger.bind_task(task_id, PURPOSE):
            return service.gateway.call_llm(
                str(config.get("llm_model") or ""), system, user, str(config.get("title_suggestion") or ""),
                str(config.get("director_style") or ""), str(config.get("shot_style") or ""),
            ) or ""

    answer = await run_in_threadpool(ask)
    try:
        lists = chapter_assets.parse(answer)
    except chapter_assets.ChapterAssetError as error:
        logger.warning("章节资产提取没有成功: task=%s chapter=%s reason=%s", task_id, target.id, error)
        raise _refused(error) from error

    def keep(current: dict) -> dict:
        added = chapter_assets.record(current, target, lists)
        return {"added": added, "view": chapter_assets.view(current)}

    kept = await run_in_threadpool(service.repo.mutate_task, task_id, keep)
    if kept is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return {**kept["view"], "added": kept["added"], "chapter_id": target.id}


@router.post("/{task_id}/chapter-assets/items/{item_id}")
async def settle_item(
    task_id: str,
    item_id: str,
    request: SettleRequest,
    store: PlatformStore = Depends(get_platform_store),
):
    """Confirm (into the asset library, linked to this project), dismiss, or bring back a dismissed entry."""
    task = await _task(task_id)
    try:
        entry = chapter_assets.item(task, item_id)
        chapter_assets.check_action(entry, request.action)
    except chapter_assets.ChapterAssetError as error:
        raise _refused(error) from error
    element_id = ""
    owner = str(task.get("owner_user_id") or "")
    if request.action == "confirm":
        if not owner:
            raise _refused(chapter_assets._error("no_owner"))
        aliases = [str(alias) for alias in entry.get("aliases") or []]
        try:
            element = await store.create_element(
                owner_id=owner, kind=chapter_assets.element_kind(str(entry["list"])), name=str(entry["name"]),
                description=str(entry.get("description") or ""),
                metadata={"aliases": aliases, "source": PURPOSE} if aliases else {"source": PURPOSE},
            )
            await store.link_element_to_task(element.id, owner, task_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        element_id = element.id

    def settle(current: dict) -> dict:
        chapter_assets.settle(current, item_id, request.action, element_id=element_id)
        return chapter_assets.view(current)

    try:
        shown = await run_in_threadpool(service.repo.mutate_task, task_id, settle)
    except chapter_assets.ChapterAssetError as error:
        if element_id:
            # Someone settled it in the meantime: the asset just made must not stay behind as a duplicate.
            await store.delete_element(element_id, owner)
        raise _refused(error) from error
    if shown is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return shown
