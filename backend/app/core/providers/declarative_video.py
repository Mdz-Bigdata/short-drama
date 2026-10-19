"""A video provider described in data: where to post, what to send, where the clip comes back.

Many video APIs share one shape — submit a JSON job, read a job id, poll a
status until it says done, read a URL — and differ only in field names. Such a
provider is declared here as a spec instead of a code adapter: the request body
is a JSON template with ``{{placeholders}}``, the job id, status and clip URL are
dotted paths into the responses. The spec is saved in the configuration centre
with its credential; the router then treats its family like any other.

A spec can only say what the person wrote; it never falls back to another
provider, and a mode the spec does not list is refused before any paid call.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.providers.video_adapters import VideoJobRequest, VideoJobResult, VideoProviderAdapter

Mode = Literal["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"]
_PLACEHOLDER = re.compile(r"^\{\{\s*([a-z_]+)\s*\}\}$")
_INLINE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
PLACEHOLDERS = ("prompt", "model", "first_frame", "last_frame", "reference_images", "reference_videos", "reference_audios",
                "duration", "seed", "aspect_ratio", "resolution", "job_id")


class HttpStep(BaseModel):
    method: Literal["GET", "POST"] = "POST"
    path: str = Field(min_length=1, max_length=300)
    body: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class PollStep(HttpStep):
    method: Literal["GET", "POST"] = "GET"
    status_path: str = Field(min_length=1, max_length=120)
    video_url_path: str = Field(min_length=1, max_length=120)
    success: list[str] = Field(default_factory=lambda: ["succeeded", "completed", "done", "success"])
    failure: list[str] = Field(default_factory=lambda: ["failed", "error", "cancelled", "expired"])


class VideoEndpointSpec(BaseModel):
    """Everything the generic adapter needs to drive one provider."""

    family: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=300)
    model_ids: list[str] = Field(min_length=1, max_length=50)
    modes: list[Mode] = Field(min_length=1)
    max_reference_images: int = Field(default=0, ge=0, le=20)
    max_reference_videos: int = Field(default=0, ge=0, le=5)
    max_reference_audios: int = Field(default=0, ge=0, le=5)
    auth_header: str = Field(default="Authorization", max_length=60)
    auth_prefix: str = Field(default="Bearer ", max_length=20)
    submit: HttpStep
    job_id_path: str = Field(default="", max_length=120, description="空表示提交即返回片段地址")
    video_url_path: str = Field(default="", max_length=120, description="提交响应里直接给出片段地址时的路径")
    poll: PollStep | None = None
    max_seconds: int = Field(default=15, ge=1, le=60)

    @field_validator("base_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        clean = value.strip().rstrip("/")
        if not clean.lower().startswith("https://"):
            raise ValueError("声明式视频端点的基础 URL 必须使用 HTTPS")
        return clean

    @field_validator("model_ids")
    @classmethod
    def clean_models(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if not cleaned:
            raise ValueError("至少声明一个模型 ID")
        return list(dict.fromkeys(cleaned))

    def check(self) -> None:
        if not self.job_id_path and not self.video_url_path:
            raise ValueError("提交步骤必须给出 job_id_path 或 video_url_path 之一")
        if self.job_id_path and self.poll is None:
            raise ValueError("给出 job_id_path 时必须声明 poll 步骤")
        if not re.search(_INLINE, json.dumps(self.submit.body, ensure_ascii=False)):
            raise ValueError("提交请求体里至少要有一个 {{prompt}} 之类的占位符")


def _path_get(data: Any, path: str) -> Any:
    current = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _render(value: Any, context: Mapping[str, Any]) -> Any:
    """Fill a template: a bare ``{{name}}`` keeps the value's type, inline ones become text; None drops the key."""
    if isinstance(value, str):
        whole = _PLACEHOLDER.match(value.strip())
        if whole:
            return context.get(whole.group(1))
        return _INLINE.sub(lambda m: "" if context.get(m.group(1)) is None else str(context.get(m.group(1))), value)
    if isinstance(value, list):
        rendered = [_render(item, context) for item in value]
        return [item for item in rendered if item is not None]
    if isinstance(value, Mapping):
        rendered = {key: _render(item, context) for key, item in value.items()}
        return {key: item for key, item in rendered.items() if item is not None}
    return value


class DeclarativeVideoAdapter(VideoProviderAdapter):
    """The generic adapter: one spec, one provider."""

    def __init__(self, spec: VideoEndpointSpec, *, api_key: str, base_url: str | None = None, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 180):
        self.spec = spec
        self.family = spec.family
        self.provider_label = spec.label
        self.default_base_url = spec.base_url
        self.supported_modes = frozenset(spec.modes)
        self.success_statuses = frozenset(s.lower() for s in (spec.poll.success if spec.poll else []))
        self.failure_statuses = frozenset(s.lower() for s in (spec.poll.failure if spec.poll else []))
        super().__init__(api_key=api_key, base_url=base_url, transport=transport, timeout_seconds=timeout_seconds)

    def _headers(self, key: str) -> dict[str, str]:
        return {self.spec.auth_header: f"{self.spec.auth_prefix}{key}", "Content-Type": "application/json"}

    def _context(self, request: VideoJobRequest, job_id: str | None = None) -> dict[str, Any]:
        return {
            "prompt": request.prompt, "model": request.model or self.spec.model_ids[0],
            "first_frame": request.first_frame, "last_frame": request.last_frame,
            "reference_images": request.reference_images[: self.spec.max_reference_images] or None,
            "reference_videos": request.reference_videos[: self.spec.max_reference_videos] or None,
            "reference_audios": request.reference_audios[: self.spec.max_reference_audios] or None,
            "duration": min(request.duration_seconds, self.spec.max_seconds), "seed": request.seed,
            "aspect_ratio": request.aspect_ratio, "resolution": request.resolution, "job_id": job_id,
        }

    def _call(self, step: HttpStep, context: Mapping[str, Any]) -> Any:
        url = self.base_url + _render(step.path, context)
        headers = {k: _render(v, context) for k, v in step.headers.items()}
        if step.method == "GET":
            response = self._client.get(url, headers=headers)
        else:
            response = self._client.post(url, json=_render(step.body, context), headers=headers)
        self._raise_safe(response)
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"{self.provider_label} returned a non-JSON response") from exc

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        self.ensure_mode(request)
        payload = self._call(self.spec.submit, self._context(request))
        url = _path_get(payload, self.spec.video_url_path) if self.spec.video_url_path else None
        job_id = _path_get(payload, self.spec.job_id_path) if self.spec.job_id_path else None
        if isinstance(url, str) and url.startswith("http"):
            return VideoJobResult(task_id=str(job_id) if job_id else None, status="succeeded", video_url=url)
        if job_id is None:
            raise RuntimeError(f"{self.provider_label} response carried neither a job id nor a video url")
        self._last_request = request
        return VideoJobResult(task_id=str(job_id), status="queued")

    def get_task(self, task_id: str) -> VideoJobResult:
        if self.spec.poll is None:
            raise RuntimeError(f"{self.provider_label} has no poll step declared")
        request = getattr(self, "_last_request", None) or VideoJobRequest(prompt="-")
        payload = self._call(self.spec.poll, self._context(request, job_id=task_id))
        status = str(_path_get(payload, self.spec.poll.status_path) or "").lower() or "running"
        url = _path_get(payload, self.spec.poll.video_url_path)
        return VideoJobResult(task_id=task_id, status=status, video_url=url if isinstance(url, str) and url.startswith("http") else None)


# ---------------------------------------------------------------------------- registry


class _Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._specs: dict[str, VideoEndpointSpec] = {}
        self._keys: dict[str, str] = {}

    def replace(self, entries: list[tuple[VideoEndpointSpec, str]]) -> None:
        with self._lock:
            self._specs = {spec.family: spec for spec, _ in entries}
            self._keys = {spec.family: key for spec, key in entries}

    def spec(self, family: str) -> VideoEndpointSpec | None:
        with self._lock:
            return self._specs.get(family)

    def families(self) -> list[str]:
        with self._lock:
            return list(self._specs)

    def api_key(self, family: str) -> str:
        with self._lock:
            return self._keys.get(family, "")

    def family_for_model(self, model: str) -> str | None:
        wanted = (model or "").strip().lower()
        with self._lock:
            for family, spec in self._specs.items():
                if wanted and wanted in [m.lower() for m in spec.model_ids]:
                    return family
        return None

    def ready(self, family: str) -> bool:
        return bool(self.spec(family)) and bool(self.api_key(family).strip())

    def build(self, family: str, *, transport: httpx.BaseTransport | None = None) -> DeclarativeVideoAdapter:
        spec = self.spec(family)
        if spec is None:
            raise RuntimeError(f"no declared video endpoint for family {family}")
        return DeclarativeVideoAdapter(spec, api_key=self.api_key(family), transport=transport)


declared_video_endpoints = _Registry()

__all__ = ["PLACEHOLDERS", "DeclarativeVideoAdapter", "HttpStep", "PollStep", "VideoEndpointSpec", "declared_video_endpoints"]
