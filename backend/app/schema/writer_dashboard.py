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


class WriterDashboardLine(DramaBaseSchema):
    """One spoken item of a shot; ``verbatim`` means the words are the source text's own."""

    kind: Literal["dialogue", "voiceover"] = "voiceover"
    speaker: str = Field("", max_length=80)
    text: str = Field(..., min_length=1, max_length=500)
    verbatim: bool = False
    delivery: str = Field("", max_length=120, description="表演标注：情绪-强度 / 语速 / 停顿重音 / 生理表现")


class WriterDashboardScene(DramaBaseSchema):
    scene_id: str = Field(..., min_length=1, max_length=80)
    episode_index: int = Field(..., ge=1, le=200)
    scene_index: int = Field(..., ge=1, le=5000)
    start_seconds: int = Field(0, ge=0, le=604800)
    duration_seconds: int = Field(0, ge=0, le=86400)
    duration_label: str = Field("", max_length=80)
    duration_estimated: bool = Field(False, description="时长不是规划出来的，而是按台词与视频模型支持的时长估算")
    content: str = Field("", max_length=6000)
    # The shot table: a short place / time tag, the picture text alone, the spoken lines, the storyboard frame when one exists.
    label: str = Field("", max_length=40)
    description: str = Field("", max_length=6000)
    dialogue: list[WriterDashboardLine] = Field(default_factory=list, max_length=30)
    image_url: Optional[str] = Field(None, max_length=4000)
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


class WriterTimelineEventInput(DramaBaseSchema):
    phase: str = Field("剧情节点", max_length=120)
    title: str = Field(..., min_length=1, max_length=500)
    desc: str = Field("", max_length=4000)
    points: list[str] = Field(default_factory=list, max_length=30)


class WriterTimelineUpdateRequest(DramaBaseSchema):
    """User-authored replacement for the story event timeline (add / edit / delete nodes)."""
    events: list[WriterTimelineEventInput] = Field(default_factory=list, max_length=500)


class WriterRolesUpdateRequest(DramaBaseSchema):
    """The cast as the person set it: each role's position, plus names to keep out of the cast."""
    roles: list[WriterDashboardRole] = Field(default_factory=list, max_length=500)
    hidden: list[str] = Field(default_factory=list, max_length=500)


class WriterOverviewUpdateRequest(DramaBaseSchema):
    title: Optional[str] = Field(None, max_length=60)
    synopsis: Optional[str] = Field(None, max_length=4000)
    genre: Optional[str] = Field(None, max_length=120)
    theme: Optional[str] = Field(None, max_length=500)
    world_setting: Optional[str] = Field(None, max_length=4000)


class WriterScriptVersion(DramaBaseSchema):
    """A named snapshot of the screenplay, its breakdown and its structured state."""
    version_id: str = Field(..., min_length=1, max_length=40)
    label: str = Field("", max_length=120)
    created_at: str = Field("", max_length=64)
    source_hash: str = Field("", max_length=64)
    episode_count: int = Field(0, ge=0, le=500)
    scene_count: int = Field(0, ge=0, le=5000)


class WriterVersionCreateRequest(DramaBaseSchema):
    label: str = Field("", max_length=120)


class WriterVersionRestoreRequest(DramaBaseSchema):
    expected_source_hash: str = Field(..., min_length=64, max_length=64)
    confirm_invalidate: bool = False


# What a library document is to the project. reference: read by people only;
# source: one file of the whole source, cut into episodes; episode: one episode's own text.
ScriptDocumentRole = Literal["reference", "source", "episode"]
ScriptSourceKind = Literal["novel", "screenplay"]


class ScriptDocumentCreateRequest(DramaBaseSchema):
    """A user-managed screenplay document (.txt / .md); the role defaults from the file name."""
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=2 * 1024 * 1024)
    role: Optional[ScriptDocumentRole] = None
    source_kind: Optional[ScriptSourceKind] = None


class ScriptDocumentUpdateRequest(DramaBaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1, max_length=2 * 1024 * 1024)
    role: Optional[ScriptDocumentRole] = None
    source_kind: Optional[ScriptSourceKind] = None
    # Reading order among documents of the same role; unset falls back to the number in the name, then upload order.
    order: Optional[int] = Field(None, ge=0, le=500)


class AssetIdentityRequest(DramaBaseSchema):
    """Rename an asset (``new_name`` is free) or merge it into another (``new_name`` names the survivor)."""
    kind: Literal["character", "scene", "prop"]
    name: str = Field(..., min_length=1, max_length=80)
    new_name: str = Field(..., min_length=1, max_length=80)
    # Count what would change without changing it.
    dry_run: bool = False


class WriterEpisodeIssue(DramaBaseSchema):
    """Why an episode is not yet well formed: too few shots, or outside the running-time frame."""

    code: str = Field(..., min_length=1, max_length=80)
    message: str = Field(..., min_length=1, max_length=500)
    severity: Literal["error", "warning"] = "error"


class WriterDashboardEpisode(DramaBaseSchema):
    index: int = Field(..., ge=1, le=200)
    title: str = Field(..., min_length=1, max_length=500)
    scene_count: int = Field(0, ge=0, le=5000)
    duration_seconds: int = Field(0, ge=0, le=604800)
    issues: list[WriterEpisodeIssue] = Field(default_factory=list, max_length=8)
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
    timeline_authored: bool = Field(False, description="剧情事件时间轴是否经人手编辑（编辑后不再随分集账本重新生成）")
    creation_mode: str = Field("drama", max_length=40)
    versions: list[WriterScriptVersion] = Field(default_factory=list, max_length=50)
    # name → portrait url, once stage 3 drew the character; the board renders initials without one.
    portraits: dict[str, str] = Field(default_factory=dict)
    episodes: list[WriterDashboardEpisode] = Field(default_factory=list, max_length=200)
    script: str = Field("", max_length=2 * 1024 * 1024)
    script_file_name: Optional[str] = Field(None, max_length=255)


class ScriptDocument(DramaBaseSchema):
    """One stored screenplay document in the project's script library."""
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(0, ge=0)
    updated_at: str = Field("", max_length=64)
    role: ScriptDocumentRole = "reference"
    source_kind: Optional[ScriptSourceKind] = None
    order: Optional[int] = None
    # Own-source documents: their place in broadcast order, and the episode number the ledger gave them.
    position: Optional[int] = None
    episode: Optional[int] = None


class ScriptDocumentDetail(ScriptDocument):
    content: str = Field("", max_length=2 * 1024 * 1024)


class ScriptLibraryResponse(DramaBaseSchema):
    documents: list[ScriptDocument] = Field(default_factory=list, max_length=500)
    total: int = Field(0, ge=0)
