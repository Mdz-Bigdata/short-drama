# -*- coding: utf-8 -*-
"""The Task Center's view of a project's generation queue, and retry of a failed item."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api import drama_api
from app.core import generation_queue
from app.service import task_center_service

logger = logging.getLogger("app.api.task_center_api")

router = APIRouter(
    prefix="/api/drama",
    tags=["任务中心"],
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)

# asyncio holds tasks weakly; a retry must not be collected halfway through a paid run.
_background: set[asyncio.Task] = set()


@router.get("/{task_id}/tasks")
def list_jobs(task_id: str, status: str = Query("", max_length=80, description="逗号分隔的状态；不给时全部返回")):
    task = drama_api.service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_center_service.jobs_view(task, statuses=[part.strip() for part in status.split(",")])


@router.post("/{task_id}/tasks/{key}/retry", status_code=202)
async def retry_job(task_id: str, key: str):
    """Run stage 5 again for a failed item: it passes admission first, and what is finished is reused."""
    service = drama_api.service
    try:
        claimed = await asyncio.to_thread(task_center_service.claim_retry, service, task_id, key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except generation_queue.RetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except task_center_service.RetryRefused as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc), "admission": exc.admission})

    async def run() -> None:
        try:
            await service.execute_stage(task_id, 5, _claimed_task=claimed)
        except Exception as exc:  # noqa: BLE001 - execute_stage already recorded the failure on the project
            logger.error("[TaskCenter] 重试 %s 的第 5 阶段失败: %s", key, str(exc)[:200])

    background = asyncio.create_task(run())
    _background.add(background)
    background.add_done_callback(_background.discard)
    return task_center_service.jobs_view(claimed)
