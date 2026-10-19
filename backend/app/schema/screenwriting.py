# -*- coding: utf-8 -*-
"""API contract for the Writer Agent's structured screenwriting state."""

from typing import Any, Literal, Optional

from pydantic import Field

from app.schema.drama import DramaBaseSchema

SourceKind = Literal["outline", "novel", "screenplay"]
Severity = Literal["error", "warning"]


class ScreenwritingViolation(DramaBaseSchema):
    code: str = Field(..., max_length=80)
    message: str = Field("", max_length=2000)
    label: str = Field("", max_length=200)
    severity: Severity = "warning"
    scene_id: Optional[str] = Field(None, max_length=80)


class ScreenwritingLedgerEntry(DramaBaseSchema):
    episode: int = Field(..., ge=1, le=200)
    title: str = Field("", max_length=500)
    hook: str = Field("", max_length=4000)
    story_beats: list[str] = Field(default_factory=list, max_length=100)
    next_episode_teaser: Optional[str] = Field(None, max_length=4000)
    source_range: Optional[dict[str, int]] = None
    # cut: a span of the whole source; own: the episode's own upload; none: planned from the outline
    source_origin: Literal["cut", "own", "none"] = "cut"
    source_kind: Optional[Literal["novel", "screenplay"]] = None
    source_name: Optional[str] = Field(None, max_length=255)
    ledger_status: str = Field("planned", max_length=40)


class ScreenwritingOverview(DramaBaseSchema):
    title: str = Field("", max_length=200)
    synopsis: str = Field("", max_length=8000)
    genre: str = Field("", max_length=200)
    theme: str = Field("", max_length=2000)
    world_setting: str = Field("", max_length=8000)


class ScreenwritingDurations(DramaBaseSchema):
    supported: list[int] = Field(default_factory=list, max_length=120)
    default: Optional[int] = None
    episode_target_seconds: Optional[int] = None
    video_model: str = Field("", max_length=200)


ReviewStatus = Literal["missing", "draft", "pending", "changed", "confirmed"]


class ScreenwritingReviewStatus(DramaBaseSchema):
    """Where one episode stands in review; ``draft`` carries the quarantine reasons when it is one."""
    episode: int = Field(..., ge=1, le=200)
    status: ReviewStatus = "pending"
    confirmed_revision: Optional[str] = Field(None, max_length=120)
    confirmed_at: Optional[str] = Field(None, max_length=64)
    confirmed_by: Optional[str] = Field(None, max_length=120)
    draft: Optional[dict[str, Any]] = None


class ScreenwritingReviewSummary(DramaBaseSchema):
    total: int = Field(0, ge=0, le=200)
    confirmed: list[int] = Field(default_factory=list, max_length=200)
    pending: list[int] = Field(default_factory=list, max_length=200)
    changed: list[int] = Field(default_factory=list, max_length=200)
    drafts: list[int] = Field(default_factory=list, max_length=200)
    missing: list[int] = Field(default_factory=list, max_length=200)
    all_confirmed: bool = False
    message: str = Field("", max_length=2000, description="软门提示；全部确认时为空")


class ScreenwritingReviewRequest(DramaBaseSchema):
    action: Literal["confirm", "reopen"]


class ScreenwritingRepairRequest(DramaBaseSchema):
    confirm_invalidate: bool = False


class ScreenwritingEpisodeSummary(DramaBaseSchema):
    episode: int = Field(..., ge=1, le=200)
    title: str = Field("", max_length=500)
    scene_count: int = Field(0, ge=0, le=5000)
    duration_seconds: int = Field(0, ge=0, le=604800)
    plan_revision: str = Field("", max_length=120)
    violation_count: int = Field(0, ge=0)
    needs_replan: list[str] = Field(default_factory=list, max_length=5000)
    written_at: str = Field("", max_length=64)
    review: ScreenwritingReviewStatus = Field(default_factory=lambda: ScreenwritingReviewStatus(episode=1))


class ScreenwritingStateResponse(DramaBaseSchema):
    schema_version: Literal["screenwriting.v1"] = "screenwriting.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    available: bool = Field(True, description="任务是否持有结构化编剧状态（旧任务 / 回退到自由文本引擎时为 false）")
    engine: str = Field("", max_length=80)
    version: int = Field(0, ge=0)
    source_kind: Optional[SourceKind] = None
    stale: bool = False
    stale_reason: Optional[str] = Field(None, max_length=500)
    title: str = Field("", max_length=500)
    episode_count: int = Field(0, ge=0, le=200)
    overview: ScreenwritingOverview = Field(default_factory=ScreenwritingOverview)
    inventory: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)
    ledger: list[ScreenwritingLedgerEntry] = Field(default_factory=list, max_length=200)
    durations: ScreenwritingDurations = Field(default_factory=ScreenwritingDurations)
    episodes: list[ScreenwritingEpisodeSummary] = Field(default_factory=list, max_length=200)
    review_summary: ScreenwritingReviewSummary = Field(default_factory=ScreenwritingReviewSummary)
    warnings: list[str] = Field(default_factory=list, max_length=200)
    updated_at: str = Field("", max_length=64)


LedgerOperation = Literal[
    "split", "move_boundary", "merge_with_next", "cut_unsplit", "clear_after",
    "create", "move", "delete", "update_own_source",
]


class LedgerOperationRequest(DramaBaseSchema):
    """One change to the episode ledger; what each field means depends on ``operation``."""
    operation: LedgerOperation
    episode: Optional[int] = Field(None, ge=1, le=200)
    offset: Optional[int] = Field(None, ge=0, description="split / move_boundary：源文中的绝对字符位置")
    start: Optional[int] = Field(None, ge=0, description="cut_unsplit：起点")
    end: Optional[int] = Field(None, ge=0, description="cut_unsplit：终点")
    after: Optional[int] = Field(None, ge=0, le=200, description="create / move：排在第几集之后，0 为最前，省略为最后")
    title: str = Field("", max_length=200)
    text: str = Field("", max_length=200_000, description="create / update_own_source：该集自己的原文")
    source_kind: Optional[Literal["novel", "screenplay"]] = None
    include_unsplit: bool = Field(False, description="merge_with_next：两集之间的未切分原文一并并入")
    # Written episodes the operation would throw away must be named back to confirm their loss.
    confirm_discard: list[int] = Field(default_factory=list, max_length=200)
    confirm_invalidate: bool = False
    write_now: bool = Field(True, description="操作后立刻写出新规划的集；为假则只改账本，稍后用「补写缺失集」写出")


class ReplanRequest(DramaBaseSchema):
    from_episode: int = Field(..., ge=1, le=200)


class ReplanAdoptRequest(DramaBaseSchema):
    delete_replaced: bool = Field(False, description="被替换且已写出的旧集直接删除，而不是留作无原文的过期集")
    confirm_discard: list[int] = Field(default_factory=list, max_length=200)
    confirm_invalidate: bool = False
    write_now: bool = True


class ScreenwritingEpisodeResponse(DramaBaseSchema):
    schema_version: Literal["screenwriting.v1"] = "screenwriting.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    episode: int = Field(..., ge=1, le=200)
    title: str = Field("", max_length=500)
    hook: Optional[str] = Field(None, max_length=4000)
    next_episode_teaser: Optional[str] = Field(None, max_length=4000)
    plan_revision: str = Field("", max_length=120)
    stale: bool = False
    plan: dict[str, Any] = Field(default_factory=dict, description="{title, scenes[]} 分镜内容层（可编辑）")
    script: dict[str, Any] = Field(default_factory=dict, description="含视觉层的成品分镜 {episode, title, hook, scenes[]}")
    screenplay_text: str = Field("", max_length=2 * 1024 * 1024)
    violations: list[ScreenwritingViolation] = Field(default_factory=list, max_length=5000)
    needs_replan: list[str] = Field(default_factory=list, max_length=5000)
    written_at: str = Field("", max_length=64)
    rewritten_scene_ids: list[str] = Field(default_factory=list, max_length=5000)
    review: ScreenwritingReviewStatus = Field(default_factory=lambda: ScreenwritingReviewStatus(episode=1))
    repair: Optional[dict[str, Any]] = Field(None, description="AI 修复的结果：repaired / before / remaining / improved")


class ScreenwritingPlanPatchRequest(DramaBaseSchema):
    """Ordered edit operations on one episode's script plan."""

    base_revision: str = Field(..., min_length=8, max_length=120, description="编辑前读取到的 planRevision，用于乐观并发")
    operations: list[dict[str, Any]] = Field(..., min_length=1, max_length=200)
    confirm_invalidate: bool = Field(False, description="确认归档并使当前剧本的下游制作资产失效")


class ScreenwritingPromptPreviewResponse(DramaBaseSchema):
    task_id: str = Field(..., min_length=1, max_length=120)
    episode: int = Field(..., ge=1, le=200)
    stage: Literal["plan", "prose", "visual"]
    prompt: str = Field("", max_length=400_000)
