# -*- coding: utf-8 -*-
"""Story directions offered in the new-project form, before a project exists.

One text call proposes a few directions for the creator's idea; nothing is stored here. The one the
creator picks travels with the create request (``story_direction``) together with their no-go lines
(``story_no_go``). The call is billed to the signed-in user like any other provider call; with no
project yet, its usage record carries no task.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import Field

from app.api.auth_api import get_current_user
from app.api.drama_api import service
from app.core import creation_modes, script_structure, story_direction, target_audience, usage_ledger
from app.schema.drama import DEFAULT_LLM_MODEL, DramaBaseSchema, TargetAudience

logger = logging.getLogger("app.api.story_direction_api")
router = APIRouter(prefix="/api/story-directions", tags=["故事方向"], dependencies=[Depends(get_current_user)])
PURPOSE = "story_directions"


class StoryDirectionsRequest(DramaBaseSchema):
    idea: str = Field("", max_length=8000)
    creation_mode: str = Field("drama", max_length=16)
    episode_count: int = Field(1, ge=1, le=500)
    target_audience: Optional[TargetAudience] = None
    script_structure: str = Field("", max_length=40)
    story_no_go: List[str] = Field(default_factory=list, max_length=16)
    # A hot topic the creator typed in to borrow a feeling from; the platform has no trend data of its own.
    trend: str = Field("", max_length=600)
    llm_model: str = Field(DEFAULT_LLM_MODEL, max_length=200)
    count: int = Field(0, ge=0, le=12)


@router.get("")
def story_direction_fields():
    """What a direction is made of and how many no-go lines fit, for the form."""
    limits = story_direction._data()["limits"]
    return {
        "fields": [{"key": key, "label": story_direction.field_labels()[key]} for key in story_direction.fields()],
        "count": int(limits["count_default"]), "no_go_items": int(limits["no_go_items"]), "no_go_chars": int(limits["no_go_chars"]),
    }


@router.post("")
async def propose_story_directions(request: StoryDirectionsRequest):
    """One text call: a few directions that really differ. Nothing is saved; the form sends the chosen one with the create request."""
    mode = request.creation_mode if request.creation_mode in creation_modes.MODES else "drama"
    config = {
        "creation_mode": mode,
        "episode_count": creation_modes.episode_count_for(mode, request.episode_count),
        target_audience.CONFIG_KEY: target_audience.normalize(request.target_audience.model_dump() if request.target_audience else None),
        script_structure.CONFIG_KEY: script_structure.normalize(request.script_structure),
        story_direction.NO_GO_KEY: story_direction.normalize_no_go(request.story_no_go),
    }
    model = request.llm_model.strip()
    try:
        if not model:
            raise story_direction._error("no_model")
        system, user, wanted = story_direction.prompts(idea=request.idea, config=config, count=request.count or None, trend=request.trend)
    except story_direction.StoryDirectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    def ask() -> str:
        with usage_ledger.bind_task(None, PURPOSE):
            answer = service.gateway.call_llm(model, system, user, request.idea.strip()[:40] or PURPOSE, max_tokens=story_direction.max_tokens()) or ""
        # The offline template is not a set of directions; saying nothing came back is the honest answer.
        return "" if service.gateway.last_answer_was_offline() else answer

    answer = await run_in_threadpool(ask)
    try:
        directions = story_direction.parse(answer)
    except story_direction.StoryDirectionError as error:
        logger.warning("故事方向没有可用结果: model=%s reason=%s", model, error)
        raise HTTPException(status_code=422, detail=str(error)) from error
    # With no idea written, the picked direction becomes the idea; ``ideas`` is what the form puts in the box.
    return {
        "directions": directions, "asked": wanted, "model": model, "open": not request.idea.strip(),
        "ideas": [story_direction.idea_from(item) for item in directions],
    }
