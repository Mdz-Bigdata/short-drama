"""Typed contracts for the eight-agent short-drama production council."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentRole(str, Enum):
    EXECUTIVE_DIRECTOR = "executive_director"
    WRITER = "writer"
    CHARACTER_DESIGNER = "character_designer"
    STORYBOARD_ARTIST = "storyboard_artist"
    VISUAL_DIRECTOR = "visual_director"
    AUDIO_DIRECTOR = "audio_director"
    COMPOSER_PUBLISHER = "composer_publisher"
    PR_AGENT = "pr_agent"


ALL_AGENT_ROLES: tuple[AgentRole, ...] = tuple(AgentRole)
# 负面提示词的作用域：编剧之后的全部角色 (stage 3-8)。
# 总导演与编剧只产出文本，画面/成片层的负面词不进入它们的契约。
POST_WRITER_ROLES: tuple[AgentRole, ...] = ALL_AGENT_ROLES[2:]
CORE_SCORE_DIMENSIONS: tuple[str, ...] = (
    "story", "character", "continuity", "storyboard",
    "visual", "audio", "delivery", "compliance",
)


class CouncilCompileRequest(BaseModel):
    """Creator-approved project facts used to compile all eight agent briefs."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=300)]
    premise: Annotated[str, Field(min_length=1, max_length=20_000)]
    genre: Annotated[str, Field(min_length=1, max_length=120)] = "auto"
    audience: Annotated[str, Field(min_length=1, max_length=500)] = "18-35 岁短剧观众"
    platform: Literal[
        "douyin", "kuaishou", "wechat_channels", "bilibili", "tiktok", "reelshort", "other"
    ] = "douyin"
    format: Literal["live_action", "animation", "motion_comic", "hybrid"] = "live_action"
    episode_count: Annotated[int, Field(ge=1, le=150)] = 3
    episode_duration_seconds: Annotated[int, Field(ge=15, le=900)] = 90
    output_language: Annotated[str, Field(min_length=2, max_length=40)] = "zh-CN"
    visual_style: Annotated[str, Field(min_length=1, max_length=2000)] = "写实电影感"
    action_intensity: Literal["low", "medium", "high"] = "medium"
    content_rating: Literal["general", "teen", "mature"] = "teen"
    commercial_use: bool = True


class KnowledgeSourceRecord(BaseModel):
    filename: str
    project_relative_path: str
    sha256: str
    byte_size: int
    capability_ids: list[str]


class CapabilityRecord(BaseModel):
    id: str
    label: str
    owners: Annotated[list[AgentRole], Field(min_length=1)]
    source_files: Annotated[list[str], Field(min_length=1)]
    executable_policy: str
    validator: str
    required_artifacts: Annotated[list[str], Field(min_length=1)]


class DeliveryProfile(BaseModel):
    aspect_ratio: Literal["9:16", "16:9"]
    width: int
    height: int
    fps: Literal[24, 25, 30]
    video_codec: Literal["h264", "h265"] = "h264"
    audio_sample_rate_hz: Literal[44100, 48000] = 48000
    subtitle_safe_zone: str


class ProductionConstitution(BaseModel):
    opening_hook_deadline_seconds: float = 3.0
    ending_hook_window_seconds: float = 5.0
    reversal_interval_seconds: tuple[int, int]
    dialogue_max_han_characters: int = 15
    dialogue_default_cpm: tuple[int, int] = (270, 320)
    shot_duration_seconds: tuple[float, float]
    action_shot_duration_seconds: tuple[float, float] = (1.5, 2.5)
    character_view_order: tuple[str, ...] = (
        "front", "front_three_quarter", "profile", "rear_three_quarter", "back",
    )
    storyboard_rows: Literal[3] = 3
    storyboard_columns: Literal[3] = 3
    storyboard_reading_order: Literal["left_to_right_top_to_bottom"] = "left_to_right_top_to_bottom"
    video_generation_modes: tuple[str, ...] = (
        "first_frame", "first_last_frame", "multi_reference", "multimodal",
    )
    release_threshold: int = 85
    core_dimension_minimum: float = 4.0
    unresolved_b_limit: int = 3
    severity_policy: str = "S=0、A=0、B<=3；任一结构性硬门禁失败即禁止发布"


class AgentBlueprint(BaseModel):
    stage: Annotated[int, Field(ge=1, le=8)]
    role: AgentRole
    name_zh: str
    name_en: str
    mission: str
    capability_ids: Annotated[list[str], Field(min_length=1)]
    knowledge_sources: Annotated[list[str], Field(min_length=1)]
    required_inputs: Annotated[list[str], Field(min_length=1)]
    required_outputs: Annotated[list[str], Field(min_length=1)]
    quality_gates: Annotated[list[str], Field(min_length=1)]
    handoff_to: list[AgentRole]
    system_prompt: Annotated[str, Field(min_length=100)]


class AgentHandoff(BaseModel):
    producer: AgentRole
    consumer: AgentRole
    required_artifacts: Annotated[list[str], Field(min_length=1)]
    acceptance_rules: Annotated[list[str], Field(min_length=1)]
    fail_closed: bool = True


class CouncilPlan(BaseModel):
    plan_id: str
    request_fingerprint: str
    request: CouncilCompileRequest
    delivery: DeliveryProfile
    constitution: ProductionConstitution
    # 全局词表：本项目允许使用的负面词模块全集，老调用方按扁平清单消费。
    negative_prompt_modules: list[str]
    # 配药单：编剧之后每个角色按自己的产出形态从词表中筛出的子集。
    # 键用 AgentRole 而非 str，输入侧写错角色名直接校验失败；
    # model_dump(mode="json") 会把键序列化成 "character_designer" 这类字符串，
    # 因此 drama_service 可以直接按 role.value 查表。
    negative_prompt_by_role: dict[AgentRole, list[str]]
    agents: Annotated[list[AgentBlueprint], Field(min_length=8, max_length=8)]
    handoffs: Annotated[list[AgentHandoff], Field(min_length=7)]
    source_records: Annotated[list[KnowledgeSourceRecord], Field(min_length=1)]
    capabilities: Annotated[list[CapabilityRecord], Field(min_length=1)]
    coverage: dict[str, int | bool]

    @model_validator(mode="after")
    def validate_complete_council(self) -> "CouncilPlan":
        roles = tuple(agent.role for agent in self.agents)
        if roles != ALL_AGENT_ROLES:
            raise ValueError("the council must contain all eight agents in canonical stage order")
        if not bool(self.coverage.get("all_sources_mapped")):
            raise ValueError("every supplied knowledge source must map to executable capabilities")
        if not bool(self.coverage.get("all_capabilities_owned")):
            raise ValueError("every capability must have at least one owning agent")

        # 负面词必须覆盖编剧之后的每一个角色，缺一个即视为漏配。
        missing = [role.value for role in POST_WRITER_ROLES if not self.negative_prompt_by_role.get(role)]
        if missing:
            raise ValueError(f"negative prompt modules must cover every post-writer role: {missing}")
        # 负面词是画面/成片层约束，不得污染总导演与编剧的文本阶段。
        upstream = sorted(
            role.value for role in (AgentRole.EXECUTIVE_DIRECTOR, AgentRole.WRITER)
            if role in self.negative_prompt_by_role
        )
        if upstream:
            raise ValueError(f"negative prompt modules must not be routed to pre-production roles: {upstream}")
        # 配药单只能从词表里筛，不得凭空造词。
        catalog = set(self.negative_prompt_modules)
        unknown = sorted({m for mods in self.negative_prompt_by_role.values() for m in mods} - catalog)
        if unknown:
            raise ValueError(f"role-scoped negative modules must come from the global catalog: {unknown}")
        # 知识源第一条使用原则：不要一次性把所有负面词堆满，应按场景筛选。
        piled = sorted(
            role.value for role, mods in self.negative_prompt_by_role.items() if set(mods) == catalog
        )
        if piled:
            raise ValueError(f"role-scoped negative modules must be filtered, not the full catalog: {piled}")
        return self


class AgentArtifactEvidence(BaseModel):
    role: AgentRole
    artifact_ids: Annotated[list[str], Field(min_length=1)]
    approved: bool = False

    @field_validator("artifact_ids")
    @classmethod
    def unique_artifacts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("artifact_ids must be unique")
        return value


class CouncilIssue(BaseModel):
    code: Annotated[str, Field(min_length=2, max_length=160)]
    severity: Literal["S", "A", "B", "C"]
    owner: AgentRole
    detail: Annotated[str, Field(min_length=2, max_length=1000)]
    resolved: bool = False


class CouncilReleaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: Annotated[list[AgentArtifactEvidence], Field(min_length=1, max_length=8)]
    issues: list[CouncilIssue] = Field(default_factory=list)
    dimension_scores: Annotated[dict[str, float], Field(min_length=8)]
    five_view_order: list[str]
    storyboard_rows: int
    storyboard_columns: int
    storyboard_panel_count: int
    storyboard_motion_fingerprints_match: bool
    video_route_accepted: bool
    unsupported_references_dropped: bool = False
    dialogue_timing_approved: bool
    audio_mix_approved: bool
    final_media_present: bool
    subtitles_approved: bool
    rights_and_provenance_approved: bool
    platform_compliance_approved: bool
    human_final_review: bool

    @field_validator("dimension_scores")
    @classmethod
    def score_range(cls, value: dict[str, float]) -> dict[str, float]:
        if any(score < 1 or score > 5 for score in value.values()):
            raise ValueError("dimension scores must be between 1 and 5")
        missing = sorted(set(CORE_SCORE_DIMENSIONS) - set(value))
        if missing:
            raise ValueError(f"missing required core score dimensions: {missing}")
        return value


class ReleaseCheck(BaseModel):
    code: str
    passed: bool
    detail: str
    owner: AgentRole | None = None


class CouncilReleaseReport(BaseModel):
    releasable: bool
    total_score: float
    core_average: float
    severity_counts: dict[str, int]
    checks: list[ReleaseCheck]
    blocking_codes: list[str]
    missing_artifacts: dict[str, list[str]]
    evidence_fingerprint: str
