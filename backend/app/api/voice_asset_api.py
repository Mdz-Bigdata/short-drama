# -*- coding: utf-8 -*-
"""A project's voices: the view the library shows, and the narrator. Character casting stays on /characters/voice."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api import drama_api
from app.service import voice_asset_service
from app.core import prompt_data


_WORDING_FILE = "api_voice_asset_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_voice_asset_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

logger = logging.getLogger("app.api.voice_asset_api")

router = APIRouter(
    prefix="/api/drama",
    tags=list(_words_of("module.tags")),
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)


class NarratorAuditionRequest(BaseModel):
    voice_prompt: str = Field("", max_length=1000)
    seed: int | None = Field(None, ge=0, le=2147483647)


class NarratorCastRequest(BaseModel):
    generated_voice_id: str = Field(min_length=1, max_length=200)


class NarratorChooseRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=200)
    label: str = Field("", max_length=120)


def _answered(result: dict | None) -> dict:
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("_answered.detail"))
    return result


def _guarded(work):
    try:
        return _answered(work())
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if _text_of("_guarded.status_code") in detail else 422, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("旁白音色操作失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("_guarded.detail")) from exc


@router.get("/{task_id}/voices")
def list_voices(task_id: str):
    task = drama_api.service.repo.get_task(task_id)
    return _answered(voice_asset_service.voices_view(task) if task else None)


@router.post("/{task_id}/voices/narrator/audition")
def audition_narrator(task_id: str, req: NarratorAuditionRequest):
    """Render one round of narrator takes (paid); call again to re-roll."""
    return _guarded(lambda: voice_asset_service.audition_narrator(drama_api.service, task_id, voice_prompt=req.voice_prompt, seed=req.seed))


@router.post("/{task_id}/voices/narrator/cast")
def cast_narrator(task_id: str, req: NarratorCastRequest):
    return _guarded(lambda: voice_asset_service.cast_narrator(drama_api.service, task_id, req.generated_voice_id))


@router.put("/{task_id}/voices/narrator")
def choose_narrator(task_id: str, req: NarratorChooseRequest):
    """Use a voice that already exists: a cast character's, or one from the account's library."""
    return _guarded(lambda: voice_asset_service.choose_narrator(drama_api.service, task_id, voice_id=req.voice_id, label=req.label))


@router.delete("/{task_id}/voices/narrator")
def clear_narrator(task_id: str):
    return _guarded(lambda: voice_asset_service.clear_narrator(drama_api.service, task_id))
