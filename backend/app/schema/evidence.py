"""Immutable readiness, failure and production analytics contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schema.production import NineGridStoryboard
from app.schema.studio import AssetReadinessRequest


class ProductionReadinessRequest(BaseModel):
    assets: AssetReadinessRequest
    storyboard: NineGridStoryboard | None = None
    storyboard_approved: bool = False
    provider: Annotated[str, Field(min_length=1, max_length=80)]
    operation: Annotated[str, Field(min_length=1, max_length=80)]
    generation_mode: Annotated[str, Field(min_length=1, max_length=80)]
    reference_images: Annotated[int, Field(ge=0, le=100)] = 0
    reference_videos: Annotated[int, Field(ge=0, le=100)] = 0
    reference_audios: Annotated[int, Field(ge=0, le=100)] = 0
    duration_seconds: Annotated[float, Field(gt=0, le=3600)]


class ReadinessCheck(BaseModel):
    code: str
    passed: bool
    severity: Literal["blocking", "warning"] = "blocking"
    detail: str


class ProductionReadinessReport(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]
    blocking_codes: list[str]
    fingerprint: str


FailureCategory = Literal[
    "provider", "policy", "technical_media", "semantic_quality", "continuity",
    "budget", "cancelled", "unknown",
]


class FailureEvidence(BaseModel):
    stage: Annotated[str, Field(min_length=1, max_length=100)]
    entity_id: Annotated[str, Field(min_length=1, max_length=160)]
    attempt: Annotated[int, Field(ge=1, le=100)]
    category: FailureCategory
    failed_dimensions: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    request_fingerprint: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]
    provider_code: Annotated[str, Field(max_length=160)] = ""
    provider_message: Annotated[str, Field(max_length=2000)] = ""
    retryable: bool = False
    retry_scope: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    evidence_urls: Annotated[list[str], Field(max_length=30)] = Field(default_factory=list)


class GenerationOutcome(BaseModel):
    provider: Annotated[str, Field(min_length=1, max_length=80)]
    operation: Annotated[str, Field(min_length=1, max_length=80)]
    mode: Annotated[str, Field(min_length=1, max_length=80)]
    accepted: bool
    attempts: Annotated[int, Field(ge=1, le=100)]
    latency_ms: Annotated[int, Field(ge=0)]
    cost_amount: Annotated[float, Field(ge=0)] = 0
    currency: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{2,11}$")] = "USD"
    failure_category: FailureCategory | None = None


class ProductionAnalyticsSummary(BaseModel):
    total: int
    accepted: int
    rejected: int
    acceptance_rate: float
    retry_rate: float
    average_attempts: float
    average_latency_ms: int
    cost_by_currency: dict[str, float]
    failures_by_category: dict[str, int]
