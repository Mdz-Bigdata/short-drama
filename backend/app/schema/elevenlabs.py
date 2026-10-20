"""Validated request contracts for ElevenLabs resource and utility APIs."""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VoiceDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_description: Annotated[str, Field(min_length=20, max_length=1000)]
    text: Annotated[str | None, Field(min_length=100, max_length=1000)] = None
    auto_generate_text: bool = False
    model_id: Literal["eleven_multilingual_ttv_v2", "eleven_ttv_v3"] = "eleven_ttv_v3"
    seed: Annotated[int | None, Field(ge=0, le=2147483647)] = None
    guidance_scale: Annotated[float, Field(ge=0, le=100)] = 5
    should_enhance: bool = False

    @model_validator(mode="after")
    def require_preview_text_strategy(self) -> "VoiceDesignRequest":
        if self.text is None and not self.auto_generate_text:
            raise ValueError("text 或 auto_generate_text=true 至少提供一项")
        return self


class VoiceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_name: Annotated[str, Field(min_length=1, max_length=100)]
    voice_description: Annotated[str, Field(min_length=20, max_length=1000)]
    generated_voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 20 or any(
            not key.strip() or len(key) > 80 or not value.strip() or len(value) > 200
            for key, value in values.items()
        ):
            raise ValueError("声音标签最多 20 项，且键值必须是短文本")
        return {key.strip(): value.strip() for key, value in values.items()}


class SpeechEngineCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)] = "Short Drama Speech Engine"
    ws_url: Annotated[str, Field(min_length=8, max_length=500)]
    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_id: Literal[
        "eleven_flash_v2_5", "eleven_flash_v2", "eleven_multilingual_v2"
    ] = "eleven_flash_v2_5"
    language: Annotated[str, Field(min_length=2, max_length=16)] = "zh"
    tags: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)

    @field_validator("ws_url")
    @classmethod
    def validate_public_websocket_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "wss" or not parsed.hostname:
            raise ValueError("Speech Engine ws_url 必须是绝对 WSS 地址")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Speech Engine ws_url 格式无效")
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError("Speech Engine ws_url 必须指向公网服务")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Speech Engine ws_url 必须指向公网服务")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 80 for value in cleaned):
            raise ValueError("Speech Engine 标签必须是 1 到 80 个字符")
        return list(dict.fromkeys(cleaned))


class PronunciationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["alias", "phoneme"]
    string_to_replace: Annotated[str, Field(min_length=1, max_length=300)]
    alias: Annotated[str | None, Field(min_length=1, max_length=300)] = None
    phoneme: Annotated[str | None, Field(min_length=1, max_length=300)] = None
    alphabet: Literal["ipa", "cmu-arpabet"] | None = None
    case_sensitive: bool = True
    word_boundaries: bool = True

    @model_validator(mode="after")
    def validate_variant(self) -> "PronunciationRule":
        if self.type == "alias":
            if self.alias is None or self.phoneme is not None or self.alphabet is not None:
                raise ValueError("alias 规则只能提供 alias")
        elif self.phoneme is None or self.alphabet is None or self.alias is not None:
            raise ValueError("phoneme 规则必须提供 phoneme 和 alphabet")
        return self


class PronunciationDictionaryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=1000)] = ""
    workspace_access: Literal["admin", "editor", "commenter", "viewer"] | None = None
    rules: Annotated[list[PronunciationRule], Field(min_length=1, max_length=1000)]
