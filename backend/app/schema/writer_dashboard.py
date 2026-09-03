# -*- coding: utf-8 -*-
"""Stable API contract for the Writer Agent production dashboard."""

from typing import Literal, Optional

from pydantic import Field

from app.schema.drama import DramaBaseSchema


WriterDashboardState = Literal["WAITING", "INCOMPLETE", "READY"]
WriterEpisodeStatus = Literal["idle", "running", "completed", "failed"]


class WriterOverview(DramaBaseSchema):
    title: str = Field("", max_length=60, description="作品名（由结构化分析得出，不含书名号）")
    synopsis: str = Field("", max_length=4000)
    genre: str = Field("", max_length=120)
    theme: str = Field("", max_length=500)
    world_setting: str = Field("", max_length=4000)


class WriterDashboardStats(DramaBaseSchema):
    total_episodes: int = Field(0, ge=0, le=200)
    scripted_episodes: int = Field(
        0, ge=0, le=200,
        description="剧本正文里实际写出的集数；小于 total_episodes 说明生成被截断",
    )
    missing_episodes: list[int] = Field(
        default_factory=list, max_length=200,
        description="剧本正文里缺失的集号；前端据此高亮断层并一键补写，而不是让用户比对集数差",
    )
    scene_count: int = Field(0, ge=0, le=5000)
    character_count: int = Field(0, ge=0, le=500)
    main_event_count: int = Field(0, ge=0, le=500)
    relationship_count: int = Field(0, ge=0, le=5000)
    total_duration_seconds: int = Field(0, ge=0, le=604800)
    tone: str = Field("", max_length=120)


class WriterDashboardScene(DramaBaseSchema):
    scene_id: str = Field(..., min_length=1, max_length=80)
    episode_index: int = Field(..., ge=1, le=200)
    scene_index: int = Field(..., ge=1, le=5000)
    start_seconds: int = Field(0, ge=0, le=604800)
    duration_seconds: int = Field(0, ge=0, le=86400)
    duration_label: str = Field("", max_length=80)
    content: str = Field("", max_length=6000)
    characters: list[str] = Field(default_factory=list, max_length=100)
    key_event_index: Optional[int] = Field(None, ge=0, le=500)


class WriterDashboardEvent(DramaBaseSchema):
    event_id: str = Field(..., min_length=1, max_length=80)
    order: int = Field(..., ge=1, le=500)
    phase: str = Field("剧情节点", max_length=120)
    title: str = Field(..., min_length=1, max_length=500)
    desc: str = Field("", max_length=4000)
    points: list[str] = Field(default_factory=list, max_length=30)
    scene_id: Optional[str] = Field(None, max_length=80)
    start_seconds: int = Field(0, ge=0, le=604800)


class WriterDashboardRole(DramaBaseSchema):
    name: str = Field(..., min_length=1, max_length=80)
    position: str = Field("剧情角色", max_length=120)


class WriterDashboardRelationship(DramaBaseSchema):
    from_: str = Field(..., min_length=1, max_length=80)
    to: str = Field(..., min_length=1, max_length=80)
    relation: str = Field("剧情关联", max_length=120)
    bidirectional: bool = False


class WriterRelationshipUpdateRequest(DramaBaseSchema):
    """User-authored replacement for the character relationship list."""
    relationships: list[WriterDashboardRelationship] = Field(default_factory=list, max_length=500)


class ScriptDocumentCreateRequest(DramaBaseSchema):
    """A user-managed screenplay reference document (.txt / .md)."""
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=2 * 1024 * 1024)


class ScriptDocumentUpdateRequest(DramaBaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1, max_length=2 * 1024 * 1024)


class WriterDashboardEpisode(DramaBaseSchema):
    index: int = Field(..., ge=1, le=200)
    title: str = Field(..., min_length=1, max_length=500)
    scene_count: int = Field(0, ge=0, le=5000)
    duration_seconds: int = Field(0, ge=0, le=604800)
    status: WriterEpisodeStatus = "idle"
    video_url: Optional[str] = Field(None, max_length=4000)


class WriterDashboardResponse(DramaBaseSchema):
    schema_version: Literal["writer-dashboard.v1"] = "writer-dashboard.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    source_hash: str = Field(..., min_length=64, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    state: WriterDashboardState
    overview: WriterOverview = Field(default_factory=WriterOverview)
    stats: WriterDashboardStats = Field(default_factory=WriterDashboardStats)
    scenes: list[WriterDashboardScene] = Field(default_factory=list, max_length=5000)
    timeline: list[WriterDashboardEvent] = Field(default_factory=list, max_length=500)
    roles: list[WriterDashboardRole] = Field(default_factory=list, max_length=500)
    relationships: list[WriterDashboardRelationship] = Field(default_factory=list, max_length=5000)
    relationships_inferred: bool = Field(
        False,
        description="关系图谱是否为同场共现推断（尚未做人物关系语义分析）",
    )
    episodes: list[WriterDashboardEpisode] = Field(default_factory=list, max_length=200)
    script: str = Field("", max_length=2 * 1024 * 1024)
    script_file_name: Optional[str] = Field(None, max_length=255)


class ScriptDocument(DramaBaseSchema):
    """One stored screenplay document in the project's script library."""
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(0, ge=0)
    updated_at: str = Field("", max_length=64)


class ScriptDocumentDetail(ScriptDocument):
    content: str = Field("", max_length=2 * 1024 * 1024)


class ScriptLibraryResponse(DramaBaseSchema):
    documents: list[ScriptDocument] = Field(default_factory=list, max_length=500)
    total: int = Field(0, ge=0)
