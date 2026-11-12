# -*- coding: utf-8 -*-
"""API contract of the 3D director desk's hand-off to generation: captures and saved poses."""

from typing import Any, Literal

from pydantic import Field

from app.schema.drama import DramaBaseSchema
from app.core import prompt_data


_WORDING_FILE = "schema_director_desk"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_director_desk.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


class DeskCapture(DramaBaseSchema):
    id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["still", "clip", "backdrop"]
    # 0 is a scene-level背景图: it belongs to the stage, not to one镜头.
    shot_id: int = Field(..., ge=0, le=10_000)
    camera_id: str = Field("", max_length=80)
    url: str = Field(..., max_length=2000, description=_text_of("DeskCapture.description"))
    width: int = Field(0, ge=0, le=8192)
    height: int = Field(0, ge=0, le=8192)
    duration_s: float = Field(0.0, ge=0, le=30)
    fps: int = Field(0, ge=0, le=60)
    plan_revision: int = Field(0, ge=0, description=_text_of("DeskCapture.description.2"))
    shows_limbs: bool = Field(False, description=_text_of("DeskCapture.description.3"))
    warning: str = Field("", max_length=200, description=_text_of("DeskCapture.description.4"))
    monochrome: bool = False
    labelled: bool = False
    layer: str = Field("", max_length=20, description=_text_of("DeskCapture.description.5"))
    depth: bool = Field(False, description=_text_of("DeskCapture.description.6"))
    created_at: str = Field("", max_length=64)
    stale: bool = Field(False, description=_text_of("DeskCapture.description.7"))


class DeskAppliedSlots(DramaBaseSchema):
    still: str | None = Field(None, max_length=64, description=_text_of("DeskAppliedSlots.description"))
    clip: str | None = Field(None, max_length=64, description=_text_of("DeskAppliedSlots.description.2"))


class DeskCapturesResponse(DramaBaseSchema):
    schema_version: Literal["director-desk.v1"] = "director-desk.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    # 60 stills / clips plus the scene's背景图, which are capped on their own.
    captures: list[DeskCapture] = Field(default_factory=list, max_length=80)
    applied: dict[str, DeskAppliedSlots] = Field(default_factory=dict, description=_text_of("DeskCapturesResponse.description"))


class DeskSavedPose(DramaBaseSchema):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    pose: dict[str, Any] = Field(..., description=_text_of("DeskSavedPose.description"))
    created_at: str = Field("", max_length=64)


class DeskPosesResponse(DramaBaseSchema):
    schema_version: Literal["director-desk.v1"] = "director-desk.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    poses: list[DeskSavedPose] = Field(default_factory=list, max_length=200)


class DeskSavePoseRequest(DramaBaseSchema):
    name: str = Field(..., min_length=1, max_length=80)
    pose: dict[str, Any] = Field(..., description="StagePose：preset / joints / clip / clip_phase")


class DeskUserSavedPose(DramaBaseSchema):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=40)
    pose: dict[str, Any] = Field(..., description=_text_of("DeskUserSavedPose.description"))
    created_at: str = Field("", max_length=64)


class DeskUserPosesResponse(DramaBaseSchema):
    """The saved-pose library of the signed-in person; it is the same in every project."""

    schema_version: Literal["director-desk.v1"] = "director-desk.v1"
    poses: list[DeskUserSavedPose] = Field(default_factory=list, max_length=200)


class DeskUserSavePoseRequest(DramaBaseSchema):
    name: str = Field(..., min_length=1, max_length=40)
    pose: dict[str, Any] = Field(..., description="StagePose：preset / joints / clip / clip_phase")
