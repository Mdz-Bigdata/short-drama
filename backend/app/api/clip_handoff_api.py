"""The handoff check between neighbouring clips of one episode (free: local ffmpeg only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api import drama_api
from app.api.drama_api import require_owned_drama_task
from app.core import prompt_data
from app.service import clip_handoff_service

router = APIRouter(prefix="/api/drama", tags=["production"], dependencies=[Depends(require_owned_drama_task)])


@router.get("/{task_id}/episodes/{episode}/handoff")
def episode_handoff(task_id: str, episode: int):
    """Each cut of the episode: motion direction across it, whether the ending suits the next shot, exit and entry sides."""
    result = clip_handoff_service.episode_report(drama_api.service, task_id, episode)
    if result is None:
        raise HTTPException(status_code=404, detail=prompt_data.text("clip_handoff", "no_task"))
    return result
