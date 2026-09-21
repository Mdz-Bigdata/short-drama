# -*- coding: utf-8 -*-
"""API contract of the per-scene spatial stage (站位 / 地标 / 轴线 / 机位)."""

from typing import Any, Literal, Optional

from pydantic import Field

from app.schema.drama import DramaBaseSchema


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
    side_memory: dict[str, str] = Field(default_factory=dict, description="人物 → 首次确立的画左 / 画右")
    locations: dict[str, int] = Field(default_factory=dict, description="地点 → 已固定的地标数")


class SpatialPlanResponse(DramaBaseSchema):
    schema_version: Literal["spatial-stage.v1"] = "spatial-stage.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    persisted: bool = Field(True, description="false 表示该场尚未保存空间方案，返回的是按当前剧本即时规划的预览")
    board_status: str = Field("", max_length=40)
    board_stale: bool = Field(False, description="站位已修改，已完成的九宫格仍按旧站位绘制")
    plan: dict[str, Any] = Field(default_factory=dict, description="StagePlan（字段保持 snake_case）")


class SpatialPlanPatchRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0, description="编辑前读取到的 plan.revision，用于乐观并发")
    operations: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)
    solve: Optional[bool] = Field(
        None, description="false：本次编辑不得顺带重解任何机位（视口拖拽时用）；true：操作完成后重解全部机位；省略：由操作本身决定",
    )


class SpatialRevisionRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0)


class SpatialImportRequest(DramaBaseSchema):
    base_revision: int = Field(..., ge=0)
    document: dict[str, Any] = Field(..., description="3D 导演台工程（version 1）或 CoStage 文档（version 2）")


class SpatialExportResponse(DramaBaseSchema):
    task_id: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., max_length=80)
    format: Literal["director-desk", "costage"]
    file_name: str = Field(..., max_length=200)
    document: dict[str, Any]
    note: Optional[str] = Field(None, max_length=500)
