from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app import settings


ElementKind = Literal["actor", "prop", "scene", "costume", "effect", "product", "extra", "vehicle", "stunt", "set_dressing", "makeup"]
ModelCategory = Literal["text", "image", "video", "audio"]


class CapabilityToggleRequest(BaseModel):
    enabled: bool


class ProjectSkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    description: str = Field(default="", max_length=4000)
    markdown_content: str = Field(min_length=1, max_length=131072)
    enabled: bool = True


class ProjectSkillUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    markdown_content: str | None = Field(default=None, min_length=1, max_length=131072)


class CommandRequest(BaseModel):
    command: str = Field(min_length=2, max_length=4200)


class ModelDiscoveryRequest(BaseModel):
    category: ModelCategory
    provider: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    base_url: str = Field(min_length=8, max_length=500)
    api_key: SecretStr | None = None
    configuration_id: str | None = Field(default=None, min_length=36, max_length=36)

    @model_validator(mode="after")
    def require_credentials(self):
        if not self.api_key and not self.configuration_id:
            raise ValueError("API Key 或已有配置 ID 至少提供一项")
        return self


class ModelTestRequest(ModelDiscoveryRequest):
    selected_model_ids: list[str] = Field(min_length=1)

    @field_validator("selected_model_ids")
    @classmethod
    def validate_model_ids(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 200 or any(ord(char) < 32 for char in value) for value in cleaned):
            raise ValueError("模型 ID 无效")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("模型 ID 不能重复")
        return cleaned


class ModelSaveRequest(ModelTestRequest):
    pass


class ModelCredentialCreateRequest(BaseModel):
    label: str = Field(default="", max_length=80)
    api_key: SecretStr
    buckets: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("buckets")
    @classmethod
    def known_buckets(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip().lower() for v in values if v and v.strip()]
        unknown = [v for v in cleaned if v not in {"text", "image", "video", "audio"}]
        if unknown:
            raise ValueError("任务类型桶只能是 text / image / video / audio")
        return list(dict.fromkeys(cleaned))


class ModelCredentialUpdateRequest(BaseModel):
    enabled: bool | None = None
    buckets: list[str] | None = Field(default=None, max_length=4)

    @field_validator("buckets")
    @classmethod
    def known_buckets(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return ModelCredentialCreateRequest.known_buckets(values)


class VideoEndpointSaveRequest(BaseModel):
    spec: dict
    api_key: SecretStr | None = None
    enabled: bool = True


class ElementCreateRequest(BaseModel):
    kind: ElementKind
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    metadata: dict = Field(default_factory=dict)


class ElementUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class PropSizeRequest(BaseModel):
    """A prop's longest side in centimetres; null goes back to what the description or the kind of object says."""

    length_cm: float | None = Field(default=None, ge=0.5, le=5000)


class ElementFolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    cover_element_id: str | None = Field(default=None, max_length=36)


class ElementFolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    # Absent keeps the cover; null clears it.
    cover_element_id: str | None = Field(default="", max_length=36)


class ElementFolderMoveRequest(BaseModel):
    element_ids: list[str] = Field(min_length=1, max_length=200)
    folder_id: str | None = Field(default=None, max_length=36)


class ElementVariantRequest(BaseModel):
    """Mark an actor element as a derived look of another character."""
    of: str = Field(min_length=1, max_length=160)
    label: str = Field(default="", max_length=40)
    triggers: list[str] | str = Field(default_factory=list)
    episode_from: int | None = Field(default=None, ge=1, le=500)
    episode_to: int | None = Field(default=None, ge=1, le=500)


class RegenerateElementRequest(BaseModel):
    prompt: str = Field(default="", max_length=4000)


class RealPersonRequest(BaseModel):
    """真人演员：照片上是谁、授权用途与期限、火山方舟真人人像库素材；``confirmed`` 是确认持有本人肖像授权。"""

    person: str = Field(min_length=1, max_length=60)
    scope: str = Field(default="", max_length=200)
    expires: str = Field(default="", max_length=10)
    ark_assets: list[str] = Field(default_factory=list, max_length=9)
    confirmed: bool = False


class BulkRegenerateElementsRequest(BaseModel):
    kind: ElementKind
    task_id: str | None = Field(default=None, max_length=160)
    replace_existing: bool = False
    # With kind "actor": the characters' costume looks rather than their actor sheets.
    looks: bool = False


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=settings.PASSWORD_MIN_LENGTH, max_length=settings.PASSWORD_MAX_LENGTH)


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "suspended"]


class PointRateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=160)
    resolution: str = Field(default="", max_length=24)
    kind: Literal["per_million_tokens", "per_image", "per_second", "per_thousand_characters", "per_call"]
    input: Decimal = Field(default=Decimal(0), ge=0)
    cached_input: Decimal = Field(default=Decimal(0), ge=0)
    output: Decimal = Field(default=Decimal(0), ge=0)
    price: Decimal = Field(default=Decimal(0), ge=0)
    effective_from: datetime | None = None


class UserRolesRequest(BaseModel):
    roles: list[str] = Field(default_factory=list, max_length=8)


class OrderCreateRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    provider: Literal["sandbox", "wechat", "alipay"] | None = None
    idempotency_key: str = Field(min_length=8, max_length=120)

    @field_validator("idempotency_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            raise ValueError("幂等键只允许字母、数字、点、横线、下划线和冒号")
        return value


class OrderPayRequest(BaseModel):
    provider: Literal["wechat", "alipay"]


class RefundCreateRequest(BaseModel):
    note: str = Field(min_length=1, max_length=500)
    points: Decimal | None = Field(default=None, ge=0)
    amount_minor: int | None = Field(default=None, gt=0)


class RefundApproveRequest(BaseModel):
    amount_minor: int | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=500)


class DecisionRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class WalletAdjustmentRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    points: Decimal
    reason: str = Field(min_length=1, max_length=500)


class ReconResolveRequest(BaseModel):
    status: Literal["resolved", "ignored"]
    resolution: str = Field(min_length=1, max_length=500)
