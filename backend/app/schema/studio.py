"""Canonical platform records independent from any media provider."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.schema.production import (
    IDENTITY_VIEW_ORDER,
    LEGACY_IDENTITY_VIEW_ORDER,
    IdentityViewName,
    identity_view_order_is_valid,
)
from app.core import prompt_data


_WORDING_FILE = "schema_studio"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_studio.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


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
    format: Literal["text", "markdown", "docx", "pdf", "fdx", "fountain"]
    # Only formats with a title page know it; the body text never carries it, or it would read as a scene.
    title: str | None = None
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

# The node canvas is infinite: positions only have to stay finite and sane, not inside a page.
CANVAS_COORD_LIMIT = 1_000_000_000
CANVAS_SIZE_LIMIT = 1_000_000
CANVAS_BOOKMARK_LIMIT = 10_000_000_000
CANVAS_ZOOM_MIN, CANVAS_ZOOM_MAX = 0.01, 16
CANVAS_MAX_NODES, CANVAS_MAX_EDGES = 5000, 12000
# A group may hold a group, which may not hold another: a member's chain of groups is at most two long.
CANVAS_GROUP_DEPTH = 2
_CanvasCoord = Annotated[float, Field(ge=-CANVAS_COORD_LIMIT, le=CANVAS_COORD_LIMIT, allow_inf_nan=False)]
_CanvasSize = Annotated[float, Field(gt=0, le=CANVAS_SIZE_LIMIT, allow_inf_nan=False)]


def canvas_group_parents(nodes: list[dict[str, Any]] | list["CanvasNode"]) -> dict[str, str]:
    """node id -> the group it sits in. A ``groupId`` naming no group (left over from a deletion) is ignored."""
    rows = [item.model_dump() if isinstance(item, BaseModel) else item for item in nodes]
    groups = {str(row.get("id")) for row in rows if row.get("kind") == "group"}
    parents = {}
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        parent = str(payload.get("groupId") or "")
        if parent in groups:
            parents[str(row.get("id"))] = parent
    return parents


def canvas_group_problem(nodes: list[dict[str, Any]] | list["CanvasNode"]) -> str | None:
    """Why this nesting is not allowed, or ``None``: no group inside itself or its own member, at most one level of nesting."""
    rows = [item.model_dump() if isinstance(item, BaseModel) else item for item in nodes]
    kinds = {str(row.get("id")): row.get("kind") for row in rows}
    parents = canvas_group_parents(rows)
    for node_id, parent in parents.items():
        if parent == node_id:
            return _text_of("canvas_group_problem.text").format(node_id)
        seen, chain, current = {node_id}, 0, parent
        while current:
            if current in seen:
                return _text_of("canvas_group_problem.text.2").format(current)
            seen.add(current)
            chain += 1
            current = parents.get(current, "")
        limit = CANVAS_GROUP_DEPTH - 1 if kinds.get(node_id) == "group" else CANVAS_GROUP_DEPTH
        if chain > limit:
            return _text_of("canvas_group_problem.text.3")
    return None


class CanvasNode(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    # media = an upload, note = text / annotation; the rest were added for the node canvas.
    kind: Literal[
        "artifact", "candidate", "media", "note", "group",
        "image_gen", "video_gen", "audio_gen", "video_compose", "style_ref", "panorama", "previz", "tool",
    ]
    track: CanvasTrack
    x: _CanvasCoord
    y: _CanvasCoord
    width: _CanvasSize
    height: _CanvasSize
    artifact_id: Annotated[str | None, Field(max_length=120)] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def artifact_backed_nodes_have_an_artifact(self) -> "CanvasNode":
        if self.kind in {"artifact", "candidate"} and not self.artifact_id:
            raise ValueError("artifact and candidate canvas nodes require artifact_id")
        return self

    @model_validator(mode="after")
    def group_fold_state_is_well_formed(self) -> "CanvasNode":
        if self.kind != "group":
            return self
        if "collapsed" in self.payload and not isinstance(self.payload["collapsed"], bool):
            raise ValueError("group payload.collapsed must be a boolean")
        size = self.payload.get("expandedSize")
        if size is not None:
            if not (isinstance(size, (list, tuple)) and len(size) == 2 and all(
                isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) and 0 < item <= CANVAS_SIZE_LIMIT for item in size
            )):
                raise ValueError("group payload.expandedSize must be [width, height] with positive finite sizes")
        return self


class CanvasEdge(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
    source: str
    target: str
    kind: Literal["lineage", "variant", "continuity", "dependency", "reference"]
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasPutRequest(BaseModel):
    expected_version: Annotated[int, Field(ge=0)]
    nodes: Annotated[list[CanvasNode], Field(max_length=CANVAS_MAX_NODES)] = Field(default_factory=list)
    edges: Annotated[list[CanvasEdge], Field(max_length=CANVAS_MAX_EDGES)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "CanvasPutRequest":
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("canvas node and edge ids must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("canvas edges must reference existing nodes")
        problem = canvas_group_problem(self.nodes)
        if problem:
            raise ValueError(problem)
        return self


# The canvas a project always had lives in `canvas_versions`; further ones are named boards beside it.
CANVAS_MAIN_ID = "main"
CanvasId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]


class CanvasRecord(BaseModel):
    project_id: str
    version: int
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]
    created_at: str
    canvas_id: str = CANVAS_MAIN_ID


class CanvasPromoteRequest(BaseModel):
    node_id: Annotated[str, Field(min_length=1, max_length=120)]
    target_kind: ArtifactKind
    expected_version: Annotated[int, Field(ge=1)]


class CanvasDuplicateRequest(BaseModel):
    expected_version: Annotated[int, Field(ge=1)]
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,119}$")]
    node_ids: Annotated[list[str], Field(min_length=1, max_length=200)]
    offset_x: Annotated[float, Field(ge=-100_000, le=100_000)] = 48
    offset_y: Annotated[float, Field(ge=-100_000, le=100_000)] = 48

    @model_validator(mode="after")
    def unique_nodes(self) -> "CanvasDuplicateRequest":
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("canvas duplicate node_ids must be unique")
        return self


class CanvasBookmark(BaseModel):
    slot: Annotated[int, Field(ge=1, le=9)]
    x: Annotated[float, Field(ge=-CANVAS_BOOKMARK_LIMIT, le=CANVAS_BOOKMARK_LIMIT, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=-CANVAS_BOOKMARK_LIMIT, le=CANVAS_BOOKMARK_LIMIT, allow_inf_nan=False)]
    zoom: Annotated[float, Field(ge=CANVAS_ZOOM_MIN, le=CANVAS_ZOOM_MAX, allow_inf_nan=False)]
    label: Annotated[str, Field(max_length=60)] = ""


class CanvasBoardCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]


class CanvasBoardPatch(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    bookmarks: Annotated[list[CanvasBookmark] | None, Field(max_length=9)] = None

    @model_validator(mode="after")
    def unique_slots(self) -> "CanvasBoardPatch":
        slots = [item.slot for item in self.bookmarks or []]
        if len(slots) != len(set(slots)):
            raise ValueError("canvas bookmark slots must be unique")
        return self


class CanvasBoardRecord(BaseModel):
    id: str
    project_id: str
    title: str
    bookmarks: list[CanvasBookmark] = Field(default_factory=list)
    version: int = 0
    created_at: str = ""
    updated_at: str = ""


class CanvasVersionSummary(BaseModel):
    version: int
    created_at: str
    node_count: int
    edge_count: int


class CanvasRestoreRequest(BaseModel):
    expected_version: Annotated[int, Field(ge=0)]


class CanvasTierConfirmation(BaseModel):
    scripted_seconds: Annotated[int, Field(ge=0, le=3600)]
    requested_seconds: Annotated[int, Field(ge=0, le=3600)]


class CanvasRunRequest(BaseModel):
    # What is run is the saved canvas; a stale copy must not spend money on prompts nobody can see.
    expected_version: Annotated[int, Field(ge=0)]
    node_ids: Annotated[list[str], Field(min_length=1, max_length=50)]
    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,119}$")]
    confirm: bool = False
    confirmed_request_durations: Annotated[list[CanvasTierConfirmation], Field(max_length=50)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_nodes(self) -> "CanvasRunRequest":
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("canvas run node_ids must be unique")
        return self


class CanvasAssessRequest(BaseModel):
    node_ids: Annotated[list[str], Field(min_length=1, max_length=50)]
    confirmed_request_durations: Annotated[list[CanvasTierConfirmation], Field(max_length=50)] = Field(default_factory=list)


class CanvasRunCancelRequest(BaseModel):
    # Omitted withdraws everything still waiting in the batch.
    key: Annotated[str | None, Field(max_length=200)] = None


class CanvasCommitPreviewRequest(BaseModel):
    node_ids: Annotated[list[str], Field(min_length=1, max_length=200)]


class CanvasStoryboardRequest(BaseModel):
    """Lay storyboard scenes out on the canvas; no scene named means every scene."""

    scene_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=400)] = []
    preview: bool = False
    expected_version: Annotated[int, Field(ge=0)] | None = None


class CanvasElementPick(BaseModel):
    """One picture of a library element; no file means the element's main picture."""

    element_id: Annotated[str, Field(min_length=1, max_length=64)]
    file_id: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class CanvasTakeElementsRequest(BaseModel):
    """Library elements to put on the canvas as media nodes: ``element_ids`` take each one's main picture, ``picks`` name pictures."""

    element_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=64)]], Field(max_length=200)] = []
    picks: Annotated[list[CanvasElementPick], Field(max_length=200)] = []
    expected_version: Annotated[int, Field(ge=0)] | None = None


class CanvasSaveElementRequest(BaseModel):
    """Keep a node's picture in the element library under this name and kind (the library says which kinds exist)."""

    name: Annotated[str, Field(min_length=1, max_length=160)]
    kind: Annotated[str, Field(min_length=1, max_length=24)]


class CanvasCropRequest(BaseModel):
    """Cut a rectangle out of a node's picture into a new media node; the rectangle is in 0–1 units of the picture.

    What the numbers may be is ``app/service/canvas_image_ops.py``'s to say, in its own words.
    """

    x: float
    y: float
    w: float
    h: float
    expected_version: Annotated[int, Field(ge=0)] | None = None


class CanvasGridSplitRequest(BaseModel):
    """Cut a node's picture into rows × columns cells, one new media node each."""

    rows: int = 2
    columns: int = 2
    expected_version: Annotated[int, Field(ge=0)] | None = None


class CanvasCommitRequest(BaseModel):
    node_ids: Annotated[list[str], Field(min_length=1, max_length=200)]
    expected_version: Annotated[int, Field(ge=1)]


class CanvasNodeRun(BaseModel):
    """One generation of one node: the append-only history behind its thumbnails."""

    id: str
    project_id: str
    canvas_id: str
    node_id: str
    batch_id: str
    medium: str
    status: Literal["queued", "running", "done", "failed", "cancelled", "skipped"]
    model: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class CanvasShareCreate(BaseModel):
    """A read-only link to one canvas; null days = it lasts until stopped or rotated."""

    expires_days: Literal[1, 7, 30] | None = None


class CanvasShareRecord(BaseModel):
    """What the owner sees of the link: the token and its viewer path are theirs to copy again."""

    token: str
    url_path: str
    expires_at: str | None = None
    created_at: str


class CanvasShareOutput(BaseModel):
    medium: str = ""
    url: str | None = None
    text: str | None = None
    filename: str | None = None


class PublicCanvasShare(BaseModel):
    """The canvas as an anonymous viewer gets it: layout and words, no bindings or provenance."""

    title: str
    canvas_id: str
    version: int
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    outputs: dict[str, CanvasShareOutput]
    expires_at: str | None = None


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
    view: IdentityViewName
    uri: AnyHttpUrl


class CharacterReference(BaseModel):
    id: str
    name: Annotated[str, Field(min_length=1, max_length=100)]
    identity_dna: Annotated[str, Field(min_length=2, max_length=2000)]
    views: Annotated[list[FiveViewReference], Field(min_length=5, max_length=5)]
    approved: bool = False

    @model_validator(mode="after")
    def exact_identity_views(self) -> "CharacterReference":
        # 新契约的五个身份锚点，或存量记录的旧五视图顺序——两者都放行。
        if not identity_view_order_is_valid(tuple(view.view for view in self.views)):
            raise ValueError(
                _text_of("exact_identity_views.text").format(', '.join(IDENTITY_VIEW_ORDER), ', '.join(LEGACY_IDENTITY_VIEW_ORDER))
            )
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
