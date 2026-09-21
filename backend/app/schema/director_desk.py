# -*- coding: utf-8 -*-
"""API contract of the 3D director desk's hand-off to generation: captures and saved poses."""

from typing import Any, Literal

from pydantic import Field

from app.schema.drama import DramaBaseSchema


class DeskCapture(DramaBaseSchema):
    id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["still", "clip", "backdrop"]
    # 0 is a scene-level背景图: it belongs to the stage, not to one镜头.
    shot_id: int = Field(..., ge=0, le=10_000)
    camera_id: str = Field("", max_length=80)
    url: str = Field(..., max_length=2000, description="绝对 http(s) 地址")
    width: int = Field(0, ge=0, le=8192)
    height: int = Field(0, ge=0, le=8192)
    duration_s: float = Field(0.0, ge=0, le=30)
    fps: int = Field(0, ge=0, le=60)
    plan_revision: int = Field(0, ge=0, description="截取时的 plan.revision")
    shows_limbs: bool = Field(False, description="画面里的替身带四肢；白模规则 2 要求提示词写出分段动作序列")
    warning: str = Field("", max_length=200, description="带四肢的截取附带的提示")
    monochrome: bool = False
    labelled: bool = False
    created_at: str = Field("", max_length=64)
    stale: bool = Field(False, description="截取之后站位已修改")


class DeskAppliedSlots(DramaBaseSchema):
    still: str | None = Field(None, max_length=64, description="已写入该镜 sequence_images 的静帧 capture id")
    clip: str | None = Field(None, max_length=64, description="已写入该镜 reference_videos 的白模视频 capture id")


class DeskCapturesResponse(DramaBaseSchema):
    schema_version: Literal["director-desk.v1"] = "director-desk.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    # 60 stills / clips plus the scene's背景图, which are capped on their own.
    captures: list[DeskCapture] = Field(default_factory=list, max_length=80)
    applied: dict[str, DeskAppliedSlots] = Field(default_factory=dict, description="镜头编号（字符串）→ 已应用的截取")


class DeskSavedPose(DramaBaseSchema):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    pose: dict[str, Any] = Field(..., description="StagePose（字段保持 snake_case）")
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
    pose: dict[str, Any] = Field(..., description="StagePose（字段保持 snake_case）")
    created_at: str = Field("", max_length=64)


class DeskUserPosesResponse(DramaBaseSchema):
    """The saved-pose library of the signed-in person; it is the same in every project."""

    schema_version: Literal["director-desk.v1"] = "director-desk.v1"
    poses: list[DeskUserSavedPose] = Field(default_factory=list, max_length=200)


class DeskUserSavePoseRequest(DramaBaseSchema):
    name: str = Field(..., min_length=1, max_length=40)
    pose: dict[str, Any] = Field(..., description="StagePose：preset / joints / clip / clip_phase")
