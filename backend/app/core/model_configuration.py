"""Dynamic provider model discovery and server-side credential protection."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field


ModelCategory = Literal["text", "image", "video", "audio"]


PROVIDER_OPTIONS: dict[ModelCategory, tuple[dict[str, str], ...]] = {
    "text": (
        {"id": "deepseek", "label": "DeepSeek", "default_base_url": "https://api.deepseek.com"},
        {"id": "volcengine", "label": "火山引擎", "default_base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        {"id": "qwen", "label": "通义千问", "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        {"id": "gemini", "label": "Gemini", "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
        {"id": "openai", "label": "OpenAI", "default_base_url": "https://api.openai.com/v1"},
    ),
    "image": (
        {"id": "volcengine", "label": "火山引擎", "default_base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        {"id": "qwen", "label": "通义千问", "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        {"id": "gemini", "label": "Gemini", "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
        {"id": "openai", "label": "OpenAI", "default_base_url": "https://api.openai.com/v1"},
    ),
    "video": (
        {"id": "minimax", "label": "MiniMax H3", "default_base_url": "https://api.minimaxi.com"},
        {"id": "seedance", "label": "Seedance", "default_base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        {"id": "kling", "label": "Kling", "default_base_url": "https://api-singapore.klingai.com"},
    ),
    "audio": (
        {"id": "elevenlabs", "label": "ElevenLabs", "default_base_url": "https://api.elevenlabs.io"},
    ),
}

_PROVIDER_HOSTS: dict[str, tuple[str, ...]] = {
    "deepseek": ("api.deepseek.com",),
    "volcengine": ("volces.com",),
    "seedance": ("volces.com",),
    "qwen": ("aliyuncs.com",),
    "gemini": ("generativelanguage.googleapis.com",),
    "openai": ("api.openai.com",),
    "minimax": ("api.minimaxi.com", "api.minimax.io", "api.minimaxi.chat"),
    "kling": ("api.klingai.com", "api-singapore.klingai.com"),
    "elevenlabs": ("api.elevenlabs.io",),
}

_IMAGE_PATTERN = re.compile(r"(?:^|[-_.])(image|imagen|seedream|dall[-_.]?e|paint|render)(?:$|[-_.])", re.I)
_VIDEO_PATTERN = re.compile(r"(?:^|[-_.])(video|seedance|kling|hailuo|h3)(?:$|[-_.])", re.I)
_AUDIO_PATTERN = re.compile(r"(?:^|[-_.])(audio|speech|voice|tts|stt|asr|scribe|music|sound|sfx|bgm)(?:$|[-_.])", re.I)
_MULTIMODAL_PATTERN = re.compile(r"vision|multimodal|omni|视觉|多模态|image input|video input|(?:^|[-_.])vl(?:$|[-_.])", re.I)


class DiscoveredModel(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    category: ModelCategory
    subcategory: Literal["asr", "tts", "bgm", "music"] | None = None
    capabilities: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class DiscoveryResult:
    models: list[DiscoveredModel]
    source_endpoint: str


class ModelSecretCipher:
    def __init__(self, key: bytes | str):
        raw = key.encode("ascii") if isinstance(key, str) else key
        self._fernet = Fernet(raw)

    def encrypt(self, plaintext: str) -> str:
        clean = plaintext.strip()
        if not clean:
            raise ValueError("API Key 不能为空")
        return self._fernet.encrypt(clean.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise RuntimeError("模型凭据无法解密，请由管理员重新配置") from exc

    @classmethod
    def from_environment(cls, runtime_dir: Path) -> "ModelSecretCipher":
        configured = (os.getenv("MODEL_CONFIG_MASTER_KEY") or "").strip()
        if configured:
            return cls(configured)
        if (os.getenv("ENVIRONMENT") or "development").lower() in {"prod", "production"}:
            raise RuntimeError("生产环境必须配置 MODEL_CONFIG_MASTER_KEY")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        key_path = runtime_dir / "model-config.key"
        if key_path.exists():
            return cls(key_path.read_bytes().strip())
        key = Fernet.generate_key()
        temporary = runtime_dir / f".{key_path.name}.{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, key + b"\n")
        finally:
            os.close(descriptor)
        os.replace(temporary, key_path)
        os.chmod(key_path, 0o600)
        return cls(key)


def provider_options() -> list[dict]:
    return [
        {"category": category, "providers": [dict(item) for item in providers]}
        for category, providers in PROVIDER_OPTIONS.items()
    ]


def provider_label(provider: str) -> str:
    for providers in PROVIDER_OPTIONS.values():
        for item in providers:
            if item["id"] == provider:
                return item["label"]
    return provider


def _safe_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = " ".join(text.split())
    return text[:limit]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item, 80).lower() for item in value[:24] if isinstance(item, str)]


def _model_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "models", "items", "model_list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _model_rows(value)
            if nested:
                return nested
    return []


def _identifier(row: dict) -> str:
    for key in ("id", "model_id", "modelId", "model_name", "baseModelId", "name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            result = value.strip()
            if result.startswith("models/"):
                result = result.split("/", 1)[1]
            if 1 <= len(result) <= 200 and not any(ord(char) < 32 for char in result):
                return result
    return ""


def _classify(
    row: dict,
    model_id: str,
    requested: ModelCategory,
    provider: str | None,
) -> tuple[ModelCategory, str | None, list[str]]:
    name = _safe_text(row.get("displayName") or row.get("display_name") or row.get("name") or model_id, 200)
    description = _safe_text(row.get("description"), 1000)
    haystack = f"{model_id} {name} {description}".lower()
    inputs = _string_list(row.get("input_modalities") or row.get("inputModalities"))
    outputs = _string_list(row.get("output_modalities") or row.get("outputModalities"))
    actions = _string_list(row.get("supportedGenerationMethods") or row.get("supported_actions"))

    if row.get("can_do_text_to_speech") is True:
        category: ModelCategory = "audio"
        subcategory = "tts"
    elif any("image" in value for value in outputs) or _IMAGE_PATTERN.search(haystack):
        category, subcategory = "image", None
    elif any("video" in value for value in outputs) or _VIDEO_PATTERN.search(haystack):
        category, subcategory = "video", None
    elif any(value in {"audio", "speech", "music"} for value in outputs) or _AUDIO_PATTERN.search(haystack):
        category = "audio"
        if re.search(r"scribe|transcri|speech[- ]?to[- ]?text|(?:^|[-_.])(asr|stt)(?:$|[-_.])", haystack):
            subcategory = "asr"
        elif re.search(r"music|compose|song", haystack):
            subcategory = "music"
        elif re.search(r"sound|sfx|bgm|effect", haystack):
            subcategory = "bgm"
        else:
            subcategory = "tts"
    else:
        category, subcategory = "text", None

    capabilities = [category]
    if category == "text":
        multimodal = (
            len(set(inputs)) > 1
            or any(value in {"image", "video", "audio"} for value in inputs)
            or bool(_MULTIMODAL_PATTERN.search(haystack))
            or any("generatecontent" in value for value in actions) and "image" in description.lower()
        )
        if multimodal:
            capabilities.append("multimodal")
        else:
            capabilities.append("text-only")
    elif subcategory:
        capabilities.append(subcategory)

    # Category-specific provider catalogs may return minimal IDs without modality
    # metadata. Never apply this fallback to a global catalog (for example
    # OpenAI /models), otherwise an ordinary text model would be relabelled as
    # an image/video/audio model merely because that tab initiated discovery.
    provider_catalog_category = {
        "minimax": "video",
        "seedance": "video",
        "kling": "video",
        "elevenlabs": "audio",
    }.get(provider or "")
    if category == "text" and requested == provider_catalog_category:
        category = requested
        capabilities = [requested]
        if requested == "audio":
            subcategory = "tts"
            capabilities.append("tts")
    return category, subcategory, capabilities


def normalize_models(
    payload: object,
    requested: ModelCategory,
    provider: str | None = None,
) -> list[DiscoveredModel]:
    rows = _model_rows(payload)
    if len(rows) > 1000:
        raise ValueError("供应商返回的模型数量超过 1000 条安全上限")
    found: dict[tuple[str, str | None], DiscoveredModel] = {}
    for row in rows:
        model_id = _identifier(row)
        if not model_id:
            continue
        category, subcategory, capabilities = _classify(
            row, model_id, requested, provider
        )
        if category != requested:
            continue
        display = _safe_text(
            row.get("displayName") or row.get("display_name") or row.get("name") or model_id,
            200,
        ) or model_id
        model = DiscoveredModel(
            model_id=model_id,
            display_name=display,
            description=_safe_text(row.get("description"), 1000),
            category=category,
            subcategory=subcategory,
            capabilities=capabilities,
        )
        found[(model_id, subcategory)] = model
    return sorted(found.values(), key=lambda item: (item.subcategory or "", item.model_id.lower()))


def _host_allowed(host: str, provider: str) -> bool:
    return any(host == allowed or host.endswith("." + allowed) for allowed in _PROVIDER_HOSTS.get(provider, ()))


def _assert_public_addresses(host: str) -> None:
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("供应商域名无法解析") from exc
    for address in {item[4][0] for item in addresses}:
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global:
            raise ValueError("供应商域名解析到了非公网地址")


def validate_provider_url(category: ModelCategory, provider: str, base_url: str, *, resolve_dns: bool = True) -> str:
    if provider not in {item["id"] for item in PROVIDER_OPTIONS.get(category, ())}:
        raise ValueError("所选分类不支持该模型供应商")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError("基础 URL 必须使用 HTTPS")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not _host_allowed(host, provider):
        raise ValueError("基础 URL 必须使用所选供应商的官方域名")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("基础 URL 格式无效")
    if parsed.port not in (None, 443):
        raise ValueError("基础 URL 只允许标准 HTTPS 端口")
    if resolve_dns:
        _assert_public_addresses(host)
    clean_path = re.sub(r"/{2,}", "/", parsed.path or "").rstrip("/")
    return urlunsplit(("https", parsed.netloc.lower(), clean_path, "", ""))


def _candidate_urls(base_url: str, provider: str) -> list[str]:
    parsed = urlsplit(base_url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    path = parsed.path.rstrip("/")
    urls: list[str] = []

    if path.endswith("/models"):
        urls.append(base_url)
    else:
        urls.append(base_url.rstrip("/") + "/models")

    protocol_paths = {
        "volcengine": ("/api/v3/models",),
        "seedance": ("/api/v3/models",),
        "gemini": ("/v1beta/models", "/v1beta/openai/models"),
        "elevenlabs": ("/v1/models",),
        "minimax": ("/v2/models", "/v1/models", "/models"),
        "kling": ("/v1/models", "/models"),
    }.get(provider, ("/v1/models", "/models"))
    for protocol_path in protocol_paths:
        urls.append(origin + protocol_path)
    return list(dict.fromkeys(urls))


class ModelDiscoveryClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        timeout_seconds: float = 12,
        resolve_dns: bool | None = None,
    ):
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.resolve_dns = (transport is None) if resolve_dns is None else resolve_dns

    async def discover(
        self,
        *,
        category: ModelCategory,
        provider: str,
        base_url: str,
        api_key: str,
    ) -> DiscoveryResult:
        key = api_key.strip()
        if len(key) < 6 or len(key) > 1000:
            raise ValueError("API Key 格式无效")
        normalized_url = validate_provider_url(
            category, provider, base_url, resolve_dns=self.resolve_dns
        )
        headers = {"Accept": "application/json"}
        if provider == "elevenlabs":
            headers["xi-api-key"] = key
        elif provider == "gemini":
            headers["x-goog-api-key"] = key
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["Authorization"] = f"Bearer {key}"

        last_status: int | None = None
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
            trust_env=False,
        ) as client:
            for endpoint in _candidate_urls(normalized_url, provider):
                try:
                    response = await client.get(endpoint)
                except httpx.HTTPError:
                    continue
                last_status = response.status_code
                if response.status_code in {301, 302, 303, 307, 308}:
                    raise ValueError("供应商模型接口不允许重定向")
                if response.status_code in {401, 403}:
                    raise ValueError("API Key 无效或无权读取模型列表")
                if response.status_code == 404:
                    continue
                if not response.is_success:
                    continue
                if len(response.content) > 2 * 1024 * 1024:
                    raise ValueError("供应商模型响应超过 2MB 安全上限")
                try:
                    payload = json.loads(response.content)
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise ValueError("供应商模型接口未返回有效 JSON") from exc
                models = normalize_models(payload, category, provider)
                if models:
                    return DiscoveryResult(models=models, source_endpoint=endpoint)

        status_hint = f"（最后状态 HTTP {last_status}）" if last_status else ""
        raise ValueError(f"供应商未提供可枚举的{category}模型列表{status_hint}")
