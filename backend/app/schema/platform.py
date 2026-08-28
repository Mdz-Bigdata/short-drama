from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


ElementKind = Literal["actor", "prop", "scene", "costume", "effect"]
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


class ElementCreateRequest(BaseModel):
    kind: ElementKind
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    metadata: dict = Field(default_factory=dict)


class ElementUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class RegenerateElementRequest(BaseModel):
    prompt: str = Field(default="", max_length=4000)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class AdminUserUpdateRequest(BaseModel):
    role: Literal["admin", "editor", "user"] | None = None
    status: Literal["active", "suspended"] | None = None


class OrderCreateRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    provider: Literal["sandbox", "wechat", "alipay"] = "sandbox"
    idempotency_key: str = Field(min_length=8, max_length=120)

    @field_validator("idempotency_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            raise ValueError("幂等键只允许字母、数字、点、横线、下划线和冒号")
        return value


class PaymentWebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=36)
    status: Literal["paid"]
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=12)
