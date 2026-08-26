# -*- coding: utf-8 -*-
"""Stable API contract for the Character Designer five-view dashboard."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from app.schema.drama import DramaBaseSchema
from app.schema.production import FIVE_VIEW_ORDER, FiveViewName


FiveViewKey = FiveViewName
CharacterAssetState = Literal[
    "MISSING",
    "PARTIAL",
    "NEEDS_REVIEW",
    "FAILED",
    "READY",
]
CharacterDashboardState = Literal["WAITING", "INCOMPLETE", "READY"]
CharacterRiskStatus = Literal["BLOCKED", "PENDING", "PASS"]

FIVE_VIEW_ANGLES: tuple[int, ...] = (0, 45, 90, 135, 180)


class CharacterViewDefinition(DramaBaseSchema):
    key: FiveViewKey
    order: int = Field(..., ge=1, le=5)
    angle_degrees: int = Field(..., ge=0, le=180)
    label_zh: str = Field(..., min_length=1, max_length=40)
    label_en: str = Field(..., min_length=1, max_length=80)


def _default_view_definitions() -> list[CharacterViewDefinition]:
    labels = (
        ("正面", "Front view"),
        ("正面四分之三", "Front three-quarter view"),
        ("标准侧面", "Standard profile view"),
        ("背面四分之三", "Rear three-quarter view"),
        ("背面", "Back view"),
    )
    return [
        CharacterViewDefinition(
            key=key,
            order=index,
            angle_degrees=angle,
            label_zh=label_zh,
            label_en=label_en,
        )
        for index, (key, angle, (label_zh, label_en)) in enumerate(
            zip(FIVE_VIEW_ORDER, FIVE_VIEW_ANGLES, labels), start=1
        )
    ]


class CharacterViewContract(DramaBaseSchema):
    version: Literal["five-view.v1"] = "five-view.v1"
    order: list[FiveViewKey] = Field(default_factory=lambda: list(FIVE_VIEW_ORDER), min_length=5, max_length=5)
    views: list[CharacterViewDefinition] = Field(default_factory=_default_view_definitions, min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_fixed_contract(self) -> "CharacterViewContract":
        if tuple(self.order) != FIVE_VIEW_ORDER:
            raise ValueError("view contract must use the canonical five-view order")
        if tuple(item.key for item in self.views) != FIVE_VIEW_ORDER:
            raise ValueError("view definitions must use the canonical five-view order")
        if tuple(item.angle_degrees for item in self.views) != FIVE_VIEW_ANGLES:
            raise ValueError("view definitions must use 0/45/90/135/180 degrees")
        if tuple(item.order for item in self.views) != (1, 2, 3, 4, 5):
            raise ValueError("view definitions must use sequential slots 1-5")
        return self


class CharacterProjectProfile(DramaBaseSchema):
    genre: str = Field("", max_length=160)
    platform: str = Field("", max_length=300)
    delivery_spec: str = Field("", max_length=300)
    constraints: str = Field("", max_length=2000)


class CharacterRisk(DramaBaseSchema):
    item: str = Field(..., min_length=1, max_length=300)
    status: CharacterRiskStatus = "PENDING"
    note: str = Field("", max_length=2000)


class CharacterColor(DramaBaseSchema):
    name: str = Field("", max_length=80)
    hex: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class CharacterStateAnchor(DramaBaseSchema):
    view: FiveViewKey
    detail: str = Field("", max_length=1000)


class CharacterDesignState(DramaBaseSchema):
    state_id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    dna: str = Field("", max_length=4000)
    hair: str = Field("", max_length=1000)
    body: str = Field("", max_length=1000)
    clothing: str = Field("", max_length=2000)
    accessories: str = Field("", max_length=1000)
    style: str = Field("", max_length=1000)
    anchors: list[CharacterStateAnchor] = Field(default_factory=list, min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_anchor_order(self) -> "CharacterDesignState":
        if tuple(anchor.view for anchor in self.anchors) != FIVE_VIEW_ORDER:
            raise ValueError("state anchors must use the canonical five-view order")
        return self


class CharacterQualityIssue(DramaBaseSchema):
    code: str = Field("quality_issue", max_length=120)
    message: str = Field("", max_length=1000)
    view_index: Optional[int] = Field(None, ge=1, le=5)


class CharacterFiveViewQuality(DramaBaseSchema):
    passed: Optional[bool] = None
    palette_similarity: Optional[float] = Field(None, ge=0, le=1)
    unique_view_hashes: Optional[int] = Field(None, ge=0, le=5)
    entropy: list[float] = Field(default_factory=list, max_length=5)
    issues: list[CharacterQualityIssue] = Field(default_factory=list, max_length=50)


class CharacterViewAsset(DramaBaseSchema):
    key: FiveViewKey
    order: int = Field(..., ge=1, le=5)
    image_url: Optional[str] = Field(None, max_length=4000)
    available: bool = False

    @model_validator(mode="after")
    def validate_availability(self) -> "CharacterViewAsset":
        if self.available != bool(self.image_url):
            raise ValueError("view availability must match imageUrl")
        return self


class CharacterDashboardCharacter(DramaBaseSchema):
    character_id: str = Field(..., pattern=r"^character-[a-f0-9]{16}$")
    name: str = Field(..., min_length=1, max_length=80)
    role: str = Field("剧情角色", max_length=120)
    description: str = Field("", max_length=4000)
    identity: str = Field("", max_length=1000)
    voice_id: str = Field("", max_length=160)
    colors: list[CharacterColor] = Field(default_factory=list, max_length=20)
    states: list[CharacterDesignState] = Field(default_factory=list, max_length=50)
    sheet_url: Optional[str] = Field(None, max_length=4000)
    asset_state: CharacterAssetState
    views: list[CharacterViewAsset] = Field(default_factory=list, min_length=5, max_length=5)
    quality: CharacterFiveViewQuality = Field(default_factory=CharacterFiveViewQuality)

    @model_validator(mode="after")
    def validate_view_order(self) -> "CharacterDashboardCharacter":
        if tuple(view.key for view in self.views) != FIVE_VIEW_ORDER:
            raise ValueError("character views must use the canonical five-view order")
        if tuple(view.order for view in self.views) != (1, 2, 3, 4, 5):
            raise ValueError("character views must use sequential slots 1-5")
        if self.asset_state == "READY":
            if not all(view.available for view in self.views) or self.quality.passed is not True:
                raise ValueError("READY requires five available views and passed quality")
        return self


class CharacterDashboardStats(DramaBaseSchema):
    character_count: int = Field(0, ge=0, le=500)
    ready_count: int = Field(0, ge=0, le=500)
    needs_review_count: int = Field(0, ge=0, le=500)
    partial_count: int = Field(0, ge=0, le=500)
    missing_count: int = Field(0, ge=0, le=500)
    failed_count: int = Field(0, ge=0, le=500)
    available_view_count: int = Field(0, ge=0, le=2500)
    expected_view_count: int = Field(0, ge=0, le=2500)


class CharacterDashboardResponse(DramaBaseSchema):
    schema_version: Literal["character-dashboard.v1"] = "character-dashboard.v1"
    task_id: str = Field(..., min_length=1, max_length=120)
    source_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    title: str = Field(..., min_length=1, max_length=500)
    state: CharacterDashboardState
    view_contract: CharacterViewContract
    stats: CharacterDashboardStats = Field(default_factory=CharacterDashboardStats)
    project: CharacterProjectProfile = Field(default_factory=CharacterProjectProfile)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    risks: list[CharacterRisk] = Field(default_factory=list, max_length=100)
    characters: list[CharacterDashboardCharacter] = Field(default_factory=list, max_length=500)
    raw_text: str = Field("", max_length=2_000_000)
