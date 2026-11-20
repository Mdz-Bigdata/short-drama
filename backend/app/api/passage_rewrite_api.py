"""Rewrite a passage of an episode's plan with a check of what it breaks; update an episode's sheet.

The proposal is never written: the writer adopts it through ``PATCH …/screenwriting/episodes/{n}/plan``,
which owns revisions, downstream invalidation and re-authoring the changed shots.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api import drama_api
from app.api.drama_api import require_owned_drama_task
from app.core import prompt_data
from app.core.screenwriting.passage_rewrite import PassageError
from app.service import passage_rewrite_service

router = APIRouter(prefix="/api/drama", tags=["screenwriting"], dependencies=[Depends(require_owned_drama_task)])


def _says(key: str) -> str:
    return prompt_data.text("passage_rewrite", key)


class PassageRewriteRequest(BaseModel):
    scene_ids: list[str] = Field(min_length=1, max_length=40)
    instruction: str = Field(min_length=1, max_length=2000)
    keep: list[str] = Field(default_factory=list, max_length=20, description="上一版改丢、这一次要守住的事")


class StateChangesRequest(BaseModel):
    state_changes: list[str] = Field(default_factory=list, max_length=passage_rewrite_service.MAX_STATE_LINES)


@router.post("/{task_id}/screenwriting/episodes/{episode}/rewrite-passage")
def rewrite_passage(task_id: str, episode: int, req: PassageRewriteRequest):
    """Two text calls: the chosen shots rewritten, then what the change breaks in this episode's and later episodes' sheet."""
    try:
        result = passage_rewrite_service.propose(drama_api.service, task_id, episode, scene_ids=req.scene_ids, instruction=req.instruction, keep=req.keep)
    except PassageError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=_says("no_episode").format(episode=episode)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail=_says("no_task"))
    return result


@router.put("/{task_id}/screenwriting/ledger/{episode}/state-changes")
def put_state_changes(task_id: str, episode: int, req: StateChangesRequest):
    """Replace one episode's sheet lines; it guides later planning and checks, so nothing made is invalidated."""
    lines = passage_rewrite_service.set_state_changes(drama_api.service, task_id, episode, req.state_changes)
    if lines is None:
        raise HTTPException(status_code=404, detail=_says("no_episode").format(episode=episode))
    return {"episode": episode, "state_changes": lines}
