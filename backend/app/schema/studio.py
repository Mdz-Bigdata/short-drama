"""Canonical platform records independent from any media provider."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.schema.production import FIVE_VIEW_ORDER, FiveViewName


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    description: Annotated[str, Field(max_length=2000)] = ""


class ProjectRecord(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str = ""
    created_at: str
    updated_at: str


class SourceSpan(BaseModel):
    id: str
    source_id: str
    start: int
    end: int
    line_start: int
    line_end: int
    text: str


class SourceDocument(BaseModel):
    id: str
    filename: str
    format: Literal["text", "markdown", "docx", "pdf", "fdx"]
    sha256: str
    text: str
    spans: list[SourceSpan]


class StoryCharacter(BaseModel):
    id: str
    name: str
    evidence_span_ids: list[str]


class StoryScene(BaseModel):
    id: str
    name: str
    evidence_span_ids: list[str]


class StoryEvent(BaseModel):
    id: str
    summary: str
    order: int
    evidence_span_ids: list[str]
    source_fact: bool = True


class StoryGraph(BaseModel):
    source_id: str
    characters: list[StoryCharacter]
    scenes: list[StoryScene]
    events: list[StoryEvent]


class ArtifactKind(str, Enum):
    source = "source"
    story_graph = "story_graph"
    outline = "outline"
    script = "script"
    asset = "asset"
    storyboard = "storyboard"
    shot = "shot"
    clip = "clip"
    audio = "audio"
    edit = "edit"
    export = "export"


class ArtifactRecord(BaseModel):
    id: str
    project_id: str
    owner_id: str
    kind: ArtifactKind
    version: int
    payload: dict[str, Any]
    content_hash: str
    parents: list[str] = Field(default_factory=list)
    stale: bool = False
    status: Literal["draft", "review", "approved", "rejected"] = "draft"
    created_at: str


class ArtifactCreateRequest(BaseModel):
    kind: ArtifactKind
    payload: dict[str, Any]
    parents: Annotated[list[str], Field(max_length=200)] = Field(default_factory=list)
    expected_latest_version: Annotated[int, Field(ge=0)]
    status: Literal["draft", "review", "approved", "rejected"] = "draft"


class GenerationJobRequest(BaseModel):
    provider: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,79}$")]
    operation: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,79}$")]
    idempotency_key: Annotated[str, Field(min_length=3, max_length=200)]
    descriptor: dict[str, Any]
    budget_units: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 3


class GenerationJobRecord(BaseModel):
    id: str
    project_id: str
    owner_id: str
    provider: str
    operation: str
    idempotency_key: str
    descriptor: dict[str, Any]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "accepted", "rejected"]
    provider_task_id: str | None = None
    budget_units: int
    attempts: int
    max_attempts: int
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    cancel_requested: bool = False
    logs: list[dict[str, str]] = Field(default_factory=list)
    created_at: str
    updated_at: str


class JobTransitionRequest(BaseModel):
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "accepted", "rejected"]
    provider_task_id: Annotated[str | None, Field(max_length=300)] = None


ReviewDecision = Literal["request_changes", "approve", "reject"]


class ReviewCreateRequest(BaseModel):
    decision: ReviewDecision
    comment: Annotated[str, Field(min_length=1, max_length=10000)]
    checks: Annotated[dict[str, bool], Field(max_length=200)] = Field(default_factory=dict)

    @field_validator("checks")
    @classmethod
    def safe_check_names(cls, value: dict[str, bool]) -> dict[str, bool]:
        if any(
            not key
            or len(key) > 80
            or not key.replace("_", "").replace("-", "").isalnum()
            for key in value
        ):
            raise ValueError("review check names must be short alphanumeric identifiers")
        return value


class ReviewRecord(BaseModel):
    id: str
    project_id: str
    artifact_id: str
    reviewer_id: str
    decision: ReviewDecision
    comment: str
    checks: dict[str, bool]
    created_at: str


CanvasTrack = Literal["mainline", "freezone"]


class CanvasNode(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    kind: Literal["artifact", "candidate", "media", "note", "group"]
    track: CanvasTrack
    x: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
    y: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
    width: Annotated[float, Field(gt=0, le=100_000)]
    height: Annotated[float, Field(gt=0, le=100_000)]
    artifact_id: Annotated[str | None, Field(max_length=120)] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def artifact_backed_nodes_have_an_artifact(self) -> "CanvasNode":
        if self.kind in {"artifact", "candidate"} and not self.artifact_id:
            raise ValueError("artifact and candidate canvas nodes require artifact_id")
        return self


class CanvasEdge(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    source: str
    target: str
    kind: Literal["lineage", "variant", "continuity", "dependency", "reference"]
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasPutRequest(BaseModel):
    expected_version: Annotated[int, Field(ge=0)]
    nodes: Annotated[list[CanvasNode], Field(max_length=2000)] = Field(default_factory=list)
    edges: Annotated[list[CanvasEdge], Field(max_length=5000)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "CanvasPutRequest":
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("canvas node and edge ids must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("canvas edges must reference existing nodes")
        return self


class CanvasRecord(BaseModel):
    project_id: str
    version: int
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]
    created_at: str


class CanvasPromoteRequest(BaseModel):
    node_id: Annotated[str, Field(min_length=1, max_length=120)]
    target_kind: ArtifactKind
    expected_version: Annotated[int, Field(ge=1)]


class Vec3(BaseModel):
    x: Annotated[float, Field(ge=-100_000, le=100_000)]
    y: Annotated[float, Field(ge=-100_000, le=100_000)]
    z: Annotated[float, Field(ge=-100_000, le=100_000)]


class SpatialAnchor(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    position: Vec3
    rotation: Vec3 = Field(default_factory=lambda: Vec3(x=0, y=0, z=0))


class SpatialActor(BaseModel):
    actor_id: Annotated[str, Field(min_length=1, max_length=120)]
    anchor_id: str
    offset: Vec3 = Field(default_factory=lambda: Vec3(x=0, y=0, z=0))
    gaze_anchor_id: str | None = None
    continuity_state: dict[str, Any] = Field(default_factory=dict)


class SpatialCamera(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    order: Annotated[int, Field(ge=1, le=10_000)]
    anchor_id: str
    position: Vec3
    target: Vec3
    focal_length_mm: Annotated[float, Field(ge=8, le=600)]
    focus_distance_m: Annotated[float, Field(gt=0, le=10_000)]
    axis: Annotated[str, Field(min_length=1, max_length=300)]


class DirectorWorldPutRequest(BaseModel):
    expected_version: Annotated[int, Field(ge=0)]
    unit: Literal["meter"] = "meter"
    anchors: Annotated[list[SpatialAnchor], Field(min_length=1, max_length=5000)]
    actors: Annotated[list[SpatialActor], Field(max_length=1000)] = Field(default_factory=list)
    cameras: Annotated[list[SpatialCamera], Field(min_length=1, max_length=10000)]
    continuity_state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_spatial_references(self) -> "DirectorWorldPutRequest":
        anchor_ids = [anchor.id for anchor in self.anchors]
        camera_ids = [camera.id for camera in self.cameras]
        actor_ids = [actor.actor_id for actor in self.actors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("Director World anchor ids must be unique")
        if len(camera_ids) != len(set(camera_ids)) or len(actor_ids) != len(set(actor_ids)):
            raise ValueError("Director World camera and actor ids must be unique")
        anchors = set(anchor_ids)
        if any(camera.anchor_id not in anchors for camera in self.cameras):
            raise ValueError("every camera must reference an existing spatial anchor")
        if any(
            actor.anchor_id not in anchors
            or (actor.gaze_anchor_id is not None and actor.gaze_anchor_id not in anchors)
            for actor in self.actors
        ):
            raise ValueError("every actor blocking reference must use an existing spatial anchor")
        return self


class DirectorWorldRecord(BaseModel):
    project_id: str
    version: int
    unit: Literal["meter"]
    anchors: list[SpatialAnchor]
    actors: list[SpatialActor]
    cameras: list[SpatialCamera]
    continuity_state: dict[str, Any]
    created_at: str


class DirectorFrame(BaseModel):
    order: int
    camera_id: str
    anchor_id: str
    position: Vec3
    target: Vec3
    focal_length_mm: float
    focus_distance_m: float
    axis: str
    actors: list[SpatialActor]
    continuity_state: dict[str, Any]


class DirectorFramePlan(BaseModel):
    project_id: str
    world_version: int
    unit: Literal["meter"]
    frames: list[DirectorFrame]
    renderer_capability: Literal["spatial_plan_only"] = "spatial_plan_only"


CostPhase = Literal["estimated", "reserved", "actual", "released"]


class CostEventRequest(BaseModel):
    idempotency_key: Annotated[str, Field(min_length=3, max_length=200)]
    phase: CostPhase
    provider: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")]
    operation: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")]
    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
    currency: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{2,11}$")]
    episode_id: Annotated[str | None, Field(max_length=120)] = None
    shot_id: Annotated[str | None, Field(max_length=120)] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostEventRecord(CostEventRequest):
    id: str
    project_id: str
    owner_id: str
    created_at: str


class CurrencyCostSummary(BaseModel):
    currency: str
    estimated: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    actual: Decimal = Decimal("0")
    released: Decimal = Decimal("0")


class ProjectCostSummary(BaseModel):
    project_id: str
    currencies: list[CurrencyCostSummary]


class ExportCaption(BaseModel):
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(gt=0)]
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    speaker: Annotated[str, Field(max_length=100)] = ""


class ExportPreviewRequest(BaseModel):
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5"] = "9:16"
    clips: Annotated[list[dict[str, Any]], Field(max_length=1000)] = Field(default_factory=list)
    captions: Annotated[list[ExportCaption], Field(max_length=10000)] = Field(default_factory=list)
    audio: Annotated[list[dict[str, Any]], Field(max_length=5000)] = Field(default_factory=list)
    transitions: Annotated[list[dict[str, Any]], Field(max_length=1000)] = Field(default_factory=list)


AgentScope = Literal[
    "project.read", "artifact.write", "job.submit", "job.read", "export.read", "provider.submit"
]


class AgentKeyCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: Annotated[list[AgentScope], Field(min_length=1, max_length=6)]

    @model_validator(mode="after")
    def unique_scopes(self) -> "AgentKeyCreateRequest":
        if len(self.scopes) != len(set(self.scopes)):
            raise ValueError("agent key scopes must be unique")
        return self


class AgentKeyRecord(BaseModel):
    id: str
    project_id: str
    owner_id: str
    name: str
    token_prefix: str
    scopes: list[AgentScope]
    revoked: bool
    created_at: str


class IssuedAgentKey(BaseModel):
    key: AgentKeyRecord
    token: str


class AgentAuthorization(BaseModel):
    key_id: str
    project_id: str
    owner_id: str
    scopes: list[AgentScope]


class FiveViewReference(BaseModel):
    view: FiveViewName
    uri: AnyHttpUrl


class CharacterReference(BaseModel):
    id: str
    name: Annotated[str, Field(min_length=1, max_length=100)]
    identity_dna: Annotated[str, Field(min_length=2, max_length=2000)]
    views: Annotated[list[FiveViewReference], Field(min_length=5, max_length=5)]
    approved: bool = False

    @model_validator(mode="after")
    def exact_five_views(self) -> "CharacterReference":
        if tuple(view.view for view in self.views) != FIVE_VIEW_ORDER:
            raise ValueError("character references require the exact ordered five views")
        return self


class SceneReference(BaseModel):
    id: str
    name: str
    layout: str
    entrances: Annotated[list[str], Field(min_length=1)]
    camera_axis: str
    light_direction: str
    time_weather: str
    approved: bool = False


class PropReference(BaseModel):
    id: str
    name: str
    owner: str
    states: Annotated[list[str], Field(min_length=1)]
    approved: bool = False


class EffectReference(BaseModel):
    id: str
    name: str
    source: str
    target: str
    lifecycle: Annotated[list[str], Field(min_length=1)]
    end_state: str
    approved: bool = False


class AssetReadinessReport(BaseModel):
    ready: bool
    missing_categories: list[str]
    unapproved_ids: list[str]


class AssetReadinessRequest(BaseModel):
    characters: list[CharacterReference] = Field(default_factory=list)
    scenes: list[SceneReference] = Field(default_factory=list)
    props: list[PropReference] = Field(default_factory=list)
    effects: list[EffectReference] = Field(default_factory=list)

    def readiness(self) -> AssetReadinessReport:
        categories = {
            "characters": self.characters,
            "scenes": self.scenes,
            "props": self.props,
            "effects": self.effects,
        }
        missing = [name for name, values in categories.items() if not values]
        unapproved = [
            item.id for values in categories.values() for item in values if not item.approved
        ]
        return AssetReadinessReport(
            ready=not missing and not unapproved,
            missing_categories=missing,
            unapproved_ids=unapproved,
        )
