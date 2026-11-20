# -*- coding: utf-8 -*-
"""API contract of the per-scene spatial stage (站位 / 地标 / 轴线 / 机位)."""

from typing import Any, Literal, Optional

from pydantic import Field

from app.schema.drama import DramaBaseSchema
from app.core import prompt_data


_WORDING_FILE = "schema_spatial_stage"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_spatial_stage.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


class SpatialSceneSummary(DramaBaseSchema):
    scene_id: str = Field(..., max_length=80)
    location: str = Field("", max_length=500)
    formation: str = Field("", max_length=200)
    actor_count: int = Field(0, ge=0)
    camera_count: int = Field(0, ge=0)
    source: Literal["auto", "edited"] = "auto"
    revision: int = Field(0, ge=0)
    coverage: Literal["storyboard", "template"] = "storyboard"
    errors: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=40)
    stale: bool = False


class SpatialOverviewResponse(DramaBaseSchema):
    schema_version: Literal["spatial-stage.v1"] = "spatial-stage.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scenes: list[SpatialSceneSummary] = Field(default_factory=list, max_length=5000)
    side_memory: dict[str, str] = Field(default_factory=dict, description=_text_of("SpatialOverviewResponse.description"))
    locations: dict[str, int] = Field(default_factory=dict, description=_text_of("SpatialOverviewResponse.description.2"))


class SpatialPlanResponse(DramaBaseSchema):
    schema_version: Literal["spatial-stage.v1"] = "spatial-stage.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    persisted: bool = Field(True, description=_text_of("SpatialPlanResponse.description"))
    board_status: str = Field("", max_length=40)
    board_stale: bool = Field(False, description=_text_of("SpatialPlanResponse.description.2"))
    plan: dict[str, Any] = Field(default_factory=dict, description=_text_of("SpatialPlanResponse.description.3"))


class SpatialPlanPatchRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0, description=_text_of("SpatialPlanPatchRequest.description"))
    operations: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)
    solve: Optional[bool] = Field(
        None, description=_text_of("SpatialPlanPatchRequest.description.2"),
    )


class SpatialRevisionRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0)


class SpatialImportRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0)
    document: dict[str, Any] = Field(..., description=_text_of("SpatialImportRequest.description"))


class SpatialRepair(DramaBaseSchema):
    code: str = Field(..., max_length=80)
    label: str = Field(..., max_length=40)
    detail: str = Field("", max_length=2000)
    shot_ids: list[int] = Field(default_factory=list, max_length=200)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=100, description=_text_of("SpatialRepair.description"))
    manual: str = Field("", max_length=2000, description=_text_of("SpatialRepair.description.2"))
    automatic: bool = False


class SpatialRepairsResponse(DramaBaseSchema):
    schema_version: Literal["spatial-stage.v1"] = "spatial-stage.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    revision: int = Field(0, ge=0, description=_text_of("SpatialRepairsResponse.description"))
    repairs: list[SpatialRepair] = Field(default_factory=list, max_length=40)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=100, description=_text_of("SpatialRepairsResponse.description.2"))
    automatic: int = Field(0, ge=0)
    manual: int = Field(0, ge=0)


class SpatialExportResponse(DramaBaseSchema):
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    format: Literal["director-desk", "costage"]
    file_name: str = Field(..., max_length=200)
    document: dict[str, Any]
    note: Optional[str] = Field(None, max_length=500)
