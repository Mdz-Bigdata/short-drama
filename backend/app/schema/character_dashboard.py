# -*- coding: utf-8 -*-
"""Stable API contract for the Character Designer actor-sheet dashboard."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from app.schema.drama import DramaBaseSchema
from app.schema.production import (
    IDENTITY_VIEW_ORDER,
    LEGACY_IDENTITY_VIEW_ORDER,
    IdentityViewName,
    identity_view_order_is_valid,
)


#: 看板里所有视图键的类型别名。
IdentityViewKey = IdentityViewName
CharacterAssetState = Literal[
    "MISSING",
    "PARTIAL",
    "NEEDS_REVIEW",
    "FAILED",
    "READY",
]
CharacterDashboardState = Literal["WAITING", "INCOMPLETE", "READY"]
CharacterRiskStatus = Literal["BLOCKED", "PENDING", "PASS"]

#: 五个身份锚点对应的机位角度：三张全身 0°/90°/180°，两张头部 0°(正脸) 和 45°(3-4 侧脸)。
IDENTITY_VIEW_ANGLES: tuple[int, ...] = (0, 90, 180, 0, 45)
#: 旧五视图整板的角度，存量记录按它渲染。
LEGACY_IDENTITY_VIEW_ANGLES: tuple[int, ...] = (0, 45, 90, 135, 180)


class CharacterViewDefinition(DramaBaseSchema):
    key: IdentityViewKey
    order: int = Field(..., ge=1, le=5)
    angle_degrees: int = Field(..., ge=0, le=180)
    label_zh: str = Field(..., min_length=1, max_length=40)
    label_en: str = Field(..., min_length=1, max_length=80)


IDENTITY_VIEW_LABELS: tuple[tuple[str, str], ...] = (
    ("正面全身", "Front full body"),
    ("侧面全身", "Profile full body"),
    ("背面全身", "Back full body"),
    ("正脸特写", "Face front close-up"),
    ("左侧45°侧脸", "Face left 45°"),
)


def _default_view_definitions() -> list[CharacterViewDefinition]:
    return [
        CharacterViewDefinition(
            key=key,
            order=index,
            angle_degrees=angle,
            label_zh=label_zh,
            label_en=label_en,
        )
        for index, (key, angle, (label_zh, label_en)) in enumerate(
            zip(IDENTITY_VIEW_ORDER, IDENTITY_VIEW_ANGLES, IDENTITY_VIEW_LABELS), start=1
        )
    ]


class CharacterViewContract(DramaBaseSchema):
    # 契约版本号保持 five-view.v1：前端按它识别看板协议，锚点仍是五个，改版本号只会
    # 让已发布的前端整体拒绝解析，而结构本身是兼容的。
    version: Literal["five-view.v1"] = "five-view.v1"
    order: list[IdentityViewKey] = Field(
        default_factory=lambda: list(IDENTITY_VIEW_ORDER), min_length=5, max_length=5
    )
    views: list[CharacterViewDefinition] = Field(default_factory=_default_view_definitions, min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_fixed_contract(self) -> "CharacterViewContract":
        order = tuple(self.order)
        if not identity_view_order_is_valid(order):
            raise ValueError("view contract must use the canonical identity view order")
        if tuple(item.key for item in self.views) != order:
            raise ValueError("view definitions must match the declared view order")
        expected_angles = (
            LEGACY_IDENTITY_VIEW_ANGLES if order == LEGACY_IDENTITY_VIEW_ORDER else IDENTITY_VIEW_ANGLES
        )
        if tuple(item.angle_degrees for item in self.views) != expected_angles:
            raise ValueError(f"view definitions must use {'/'.join(str(a) for a in expected_angles)} degrees")
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
    view: IdentityViewKey
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
        if not identity_view_order_is_valid(tuple(anchor.view for anchor in self.anchors)):
            raise ValueError("state anchors must use the canonical identity view order")
        return self


class CharacterQualityIssue(DramaBaseSchema):
    code: str = Field("quality_issue", max_length=120)
    message: str = Field("", max_length=1000)
    # 设定集最多 25 格，逐格质检时这里是格子序号；旧五视图记录仍然只用 1-5。
    view_index: Optional[int] = Field(None, ge=1, le=25)


class CharacterFiveViewQuality(DramaBaseSchema):
    passed: Optional[bool] = None
    palette_similarity: Optional[float] = Field(None, ge=0, le=1)
    unique_view_hashes: Optional[int] = Field(None, ge=0, le=25)
    entropy: list[float] = Field(default_factory=list, max_length=25)
    issues: list[CharacterQualityIssue] = Field(default_factory=list, max_length=50)


class CharacterViewAsset(DramaBaseSchema):
    key: IdentityViewKey
    order: int = Field(..., ge=1, le=5)
    image_url: Optional[str] = Field(None, max_length=4000)
    available: bool = False

    @model_validator(mode="after")
    def validate_availability(self) -> "CharacterViewAsset":
        if self.available != bool(self.image_url):
            raise ValueError("view availability must match imageUrl")
        return self


class CharacterSheetCell(DramaBaseSchema):
    """设定集里的一格。五个身份锚点走 ``views``，其余的走这里。

    key 只做格式校验，不枚举——格子清单归 core.actor_sheet_layout 管，
    schema 层跟着枚举一遍必然漂移。中文标签在前端 assetTabLabels.ts。
    """

    key: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,39}$")
    order: int = Field(..., ge=1, le=25)
    # 与 core.actor_sheet_layout 的区域 key 一一对应。
    group: Literal["main_portrait", "full_body", "three_view", "elements", "detail_matrix"]
    image_url: Optional[str] = Field(None, max_length=4000)
    available: bool = False
    # 模型没画这一格时，从哪个身份面板按部位补裁(full_body / portrait / back)；模型画了的格子为空。
    derived_from: Optional[str] = Field(None, pattern=r"^[a-z][a-z0-9_]{1,39}$")

    @model_validator(mode="after")
    def validate_availability(self) -> "CharacterSheetCell":
        if self.available != bool(self.image_url):
            raise ValueError("cell availability must match imageUrl")
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
    # 设定集的其余格子(元素拆解 + 细节矩阵 + 大正面 + 全身立绘)。旧五视图记录为空列表。
    sheet_cells: list[CharacterSheetCell] = Field(default_factory=list, max_length=25)
    quality: CharacterFiveViewQuality = Field(default_factory=CharacterFiveViewQuality)
    # 单个角色「重新生成设定集」正在后台跑；上一次重新生成失败时的原因(成功或从未重新生成为空)。
    regenerating: bool = False
    regeneration_error: str = Field("", max_length=1000)

    @model_validator(mode="after")
    def validate_view_order(self) -> "CharacterDashboardCharacter":
        if not identity_view_order_is_valid(tuple(view.key for view in self.views)):
            raise ValueError("character views must use the canonical identity view order")
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
