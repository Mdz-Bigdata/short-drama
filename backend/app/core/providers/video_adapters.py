"""Video job adapters for Kling, xAI Grok Imagine, HappyHorse (fal.ai) and LTX.

Each adapter speaks only its provider's documented job protocol. The router in
``app.core.video_references`` has already chosen the executable mode; an adapter
that cannot express that mode with its documented endpoints refuses before any
paid call instead of quietly submitting something else, and no adapter ever
falls back to another provider.

Documented sources (reviewed 2026-09-08):
- Kling: JWT HS256 (iss=AccessKey, exp=+1800s, nbf=-5s), POST /v1/videos/{text2video,
  image2video,multi-image2video}, GET /v1/videos/{endpoint}/{task_id}.
- xAI: POST /v1/videos/generations (image / last_frame / reference_images<=3),
  GET /v1/videos/{request_id} with status done|failed|expired.
- fal.ai queue: POST https://queue.fal.run/{model}, Authorization: Key, then
  status_url / response_url; HappyHorse 1.1 text-/image-/reference-to-video.
- LTX: POST /v2/{text-to-video,image-to-video} (image_uri, last_frame_uri) -> 202 job,
  GET /v2/{endpoint}/{id} with status pending|processing|completed|failed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.platform.runtime_models import runtime_model_registry


VideoMode = Literal["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"]


class VideoJobRequest(BaseModel):
    model: str = ""
    prompt: str = Field(min_length=1, max_length=20000)
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str] = Field(default_factory=list, max_length=9)
    reference_videos: list[str] = Field(default_factory=list, max_length=3)
    reference_audios: list[str] = Field(default_factory=list, max_length=3)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    aspect_ratio: str = "9:16"
    resolution: str = "1080p"
    seed: int | None = Field(default=None, ge=0, le=2147483647)

    @property
    def inferred_mode(self) -> VideoMode:
        if self.reference_videos or self.reference_audios:
            return "multimodal"
        if self.reference_images:
            return "multi_reference"
        if self.first_frame and self.last_frame:
            return "first_last_frame"
        if self.first_frame:
            return "first_frame"
        return "text"

    def visual_references(self, limit: int) -> list[str]:
        """First frame first, then identity/sequence images, deduplicated."""
        ordered = [value for value in [self.first_frame, *self.reference_images] if value]
        return list(dict.fromkeys(ordered))[:limit]


class VideoJobResult(BaseModel):
    task_id: str | None = None
    status: str = "queued"
    video_url: str | None = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)


def _safe_task_id(task_id: str, label: str) -> str:
    if not task_id or not task_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"invalid {label} task id")
    return task_id


class VideoProviderAdapter:
    family = ""
    provider_label = ""
    default_base_url = ""
    default_model = ""
    supported_modes: frozenset[str] = frozenset()
    success_statuses: frozenset[str] = frozenset()
    failure_statuses: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 180,
    ):
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError(f"{self.provider_label} API key is required on the server")
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self._client = httpx.Client(
            headers=self._headers(key), timeout=timeout_seconds, transport=transport,
        )

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _raise_safe(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        request_id = response.headers.get("x-request-id", "unknown")
        raise RuntimeError(
            f"{self.provider_label} request failed: HTTP {response.status_code}, request_id={request_id}"
        )

    def ensure_mode(self, request: VideoJobRequest) -> VideoMode:
        mode = request.inferred_mode
        if mode not in self.supported_modes:
            raise RuntimeError(
                f"{self.provider_label} adapter cannot execute mode {mode}; "
                f"documented endpoints support {', '.join(sorted(self.supported_modes))}"
            )
        return mode

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        raise NotImplementedError

    def get_task(self, task_id: str) -> VideoJobResult:
        raise NotImplementedError

    def wait_for_video(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 900,
        poll_interval_seconds: float = 5,
    ) -> VideoJobResult:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.get_task(task_id)
            status = result.status.lower()
            if result.video_url or status in self.success_statuses:
                return result
            if status in self.failure_statuses:
                raise RuntimeError(f"{self.provider_label} task ended with status={result.status}")
            time.sleep(min(max(poll_interval_seconds, 0.0), 30))
        raise TimeoutError(f"{self.provider_label} video generation timed out")

    def close(self) -> None:
        self._client.close()


class KlingVideoAdapter(VideoProviderAdapter):
    family = "kling"
    provider_label = "Kling"
    default_base_url = "https://api.klingai.com"
    default_model = "kling-v2-1"
    supported_modes = frozenset({"text", "first_frame", "first_last_frame", "multi_reference"})
    success_statuses = frozenset({"succeed", "succeeded", "success"})
    failure_statuses = frozenset({"failed"})
    # The multi-image reference endpoint documents up to four images.
    MAX_MULTI_IMAGES = 4

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 180,
        model_name: str | None = None,
        generation_mode: str | None = None,
    ):
        access_key, _, secret_key = (api_key or "").strip().partition(":")
        if not access_key or not secret_key:
            raise RuntimeError("Kling credentials must be supplied as ACCESS_KEY:SECRET_KEY")
        self._access_key = access_key
        self._secret_key = secret_key
        self.default_model = model_name or os.getenv("KLING_MODEL_NAME") or self.default_model
        self.generation_mode = generation_mode or os.getenv("KLING_MODE") or "std"
        self._task_path = "/v1/videos/image2video"
        super().__init__(
            api_key=api_key, base_url=base_url, transport=transport, timeout_seconds=timeout_seconds,
        )

    def _headers(self, key: str) -> dict[str, str]:
        # Kling tokens are short-lived JWTs, minted per request rather than pinned.
        return {"Content-Type": "application/json"}

    @staticmethod
    def build_jwt(access_key: str, secret_key: str, *, now: int | None = None, ttl_seconds: int = 1800) -> str:
        issued = int(now if now is not None else time.time())

        def encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = encode(json.dumps(
            {"iss": access_key, "exp": issued + ttl_seconds, "nbf": issued - 5},
            separators=(",", ":"),
        ).encode())
        signing_input = f"{header}.{payload}"
        signature = hmac.new(secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{encode(signature)}"

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.build_jwt(self._access_key, self._secret_key)}"}

    def _model_name(self, request: VideoJobRequest) -> str:
        model = (request.model or "").strip()
        return model if model.lower().startswith("kling-") else self.default_model

    def _payload(self, request: VideoJobRequest, mode: VideoMode) -> tuple[str, dict[str, Any]]:
        body: dict[str, Any] = {
            "model_name": self._model_name(request),
            "prompt": request.prompt,
            "mode": self.generation_mode,
            # Kling only accepts "5" or "10" second clips.
            "duration": "10" if request.duration_seconds > 5 else "5",
            "aspect_ratio": request.aspect_ratio,
        }
        if mode == "text":
            return "/v1/videos/text2video", body
        if mode == "multi_reference":
            body["image_list"] = [
                {"image": url} for url in request.visual_references(self.MAX_MULTI_IMAGES)
            ]
            return "/v1/videos/multi-image2video", body
        body["image"] = request.first_frame
        if request.last_frame:
            body["image_tail"] = request.last_frame
        return "/v1/videos/image2video", body

    @staticmethod
    def _check_code(data: dict[str, Any]) -> None:
        code = data.get("code")
        if code not in (None, 0):
            raise RuntimeError(f"Kling rejected the request: code={code}")

    @staticmethod
    def _result(data: dict[str, Any]) -> VideoJobResult:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        videos = (payload.get("task_result") or {}).get("videos") or []
        video_url = videos[0].get("url") if videos and isinstance(videos[0], dict) else None
        task_id = payload.get("task_id")
        return VideoJobResult(
            task_id=str(task_id) if task_id else None,
            status=str(payload.get("task_status") or "submitted"),
            video_url=str(video_url) if video_url else None,
            provider_payload=data,
        )

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        mode = self.ensure_mode(request)
        path, body = self._payload(request, mode)
        response = self._client.post(self.base_url + path, json=body, headers=self._auth())
        self._raise_safe(response)
        data = response.json()
        self._check_code(data)
        self._task_path = path
        return self._result(data)

    def get_task(self, task_id: str) -> VideoJobResult:
        task_id = _safe_task_id(task_id, "Kling")
        response = self._client.get(f"{self.base_url}{self._task_path}/{task_id}", headers=self._auth())
        self._raise_safe(response)
        data = response.json()
        self._check_code(data)
        return self._result(data)


class GrokImagineAdapter(VideoProviderAdapter):
    family = "grok"
    provider_label = "xAI Grok Imagine"
    default_base_url = "https://api.x.ai"
    default_model = "grok-imagine-video-1.5"
    supported_modes = frozenset({"text", "first_frame", "first_last_frame", "multi_reference"})
    success_statuses = frozenset({"done"})
    failure_statuses = frozenset({"failed", "expired"})
    MAX_REFERENCE_IMAGES = 3
    MAX_DURATION = 15

    def _payload(self, request: VideoJobRequest, mode: VideoMode) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model if request.model.lower().startswith("grok-") else self.default_model,
            "prompt": request.prompt,
            "duration": min(request.duration_seconds, self.MAX_DURATION),
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
        }
        if mode == "multi_reference":
            body["reference_images"] = [
                {"url": url} for url in request.visual_references(self.MAX_REFERENCE_IMAGES)
            ]
            return body
        if request.first_frame:
            body["image"] = {"url": request.first_frame}
        if request.last_frame:
            body["last_frame"] = {"url": request.last_frame}
        return body

    @staticmethod
    def _result(data: dict[str, Any]) -> VideoJobResult:
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        task_id = data.get("request_id") or data.get("id")
        return VideoJobResult(
            task_id=str(task_id) if task_id else None,
            status=str(data.get("status") or "queued"),
            video_url=str(video["url"]) if video.get("url") else None,
            provider_payload=data,
        )

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        mode = self.ensure_mode(request)
        response = self._client.post(f"{self.base_url}/v1/videos/generations", json=self._payload(request, mode))
        self._raise_safe(response)
        return self._result(response.json())

    def get_task(self, task_id: str) -> VideoJobResult:
        task_id = _safe_task_id(task_id, "xAI")
        response = self._client.get(f"{self.base_url}/v1/videos/{task_id}")
        self._raise_safe(response)
        return self._result(response.json())


class HappyHorseFalAdapter(VideoProviderAdapter):
    family = "happyhorse"
    provider_label = "HappyHorse (fal.ai)"
    default_base_url = "https://queue.fal.run"
    default_model = "alibaba/happy-horse/v1.1"
    supported_modes = frozenset({"text", "first_frame", "multi_reference"})
    success_statuses = frozenset({"completed"})
    failure_statuses = frozenset({"failed", "error", "cancelled", "canceled"})
    MAX_REFERENCE_IMAGES = 9

    def __init__(self, **kwargs):
        # fal hands back per-request status/response URLs; keep them per task.
        self._jobs: dict[str, tuple[str, str]] = {}
        super().__init__(**kwargs)

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    def _endpoint(self, request: VideoJobRequest, mode: VideoMode) -> str:
        model = request.model if "/" in request.model else self.default_model
        suffix = {
            "text": "text-to-video",
            "first_frame": "image-to-video",
            "multi_reference": "reference-to-video",
        }[mode]
        return f"{model.strip('/')}/{suffix}"

    def _payload(self, request: VideoJobRequest, mode: VideoMode) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": request.prompt,
            # HappyHorse accepts 3-15 second clips, expressed as an enum string.
            "duration": str(min(max(request.duration_seconds, 3), 15)),
            "resolution": "720p" if request.resolution.lower().startswith("720") else "1080p",
            "aspect_ratio": request.aspect_ratio,
        }
        if mode == "first_frame":
            body["image_url"] = request.first_frame
        elif mode == "multi_reference":
            body["image_urls"] = request.visual_references(self.MAX_REFERENCE_IMAGES)
        if request.seed is not None:
            body["seed"] = request.seed
        return body

    def _same_origin(self, url: str) -> str:
        parsed = urlsplit(url)
        base = urlsplit(self.base_url)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            raise RuntimeError("fal.ai returned a status URL outside the configured queue origin")
        return url

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        mode = self.ensure_mode(request)
        endpoint = self._endpoint(request, mode)
        response = self._client.post(f"{self.base_url}/{endpoint}", json=self._payload(request, mode))
        self._raise_safe(response)
        data = response.json()
        task_id = str(data.get("request_id") or "")
        if not task_id:
            raise RuntimeError("fal.ai did not return a request_id")
        status_url = data.get("status_url") or f"{self.base_url}/{endpoint}/requests/{task_id}/status"
        response_url = data.get("response_url") or f"{self.base_url}/{endpoint}/requests/{task_id}"
        self._jobs[task_id] = (self._same_origin(status_url), self._same_origin(response_url))
        return VideoJobResult(task_id=task_id, status=str(data.get("status") or "IN_QUEUE"), provider_payload=data)

    def get_task(self, task_id: str) -> VideoJobResult:
        task_id = _safe_task_id(task_id, "fal.ai")
        urls = self._jobs.get(task_id)
        if urls is None:
            raise RuntimeError("unknown fal.ai request id for this adapter")
        status_url, response_url = urls
        status_response = self._client.get(status_url)
        self._raise_safe(status_response)
        status_data = status_response.json()
        status = str(status_data.get("status") or "IN_QUEUE")
        if status.upper() != "COMPLETED":
            return VideoJobResult(task_id=task_id, status=status, provider_payload=status_data)
        result_response = self._client.get(response_url)
        self._raise_safe(result_response)
        result_data = result_response.json()
        video = result_data.get("video") if isinstance(result_data.get("video"), dict) else {}
        return VideoJobResult(
            task_id=task_id,
            status="completed",
            video_url=str(video["url"]) if video.get("url") else None,
            provider_payload=result_data,
        )


class LtxVideoAdapter(VideoProviderAdapter):
    family = "ltx_2_3"
    provider_label = "LTX"
    default_base_url = "https://api.ltx.io"
    default_model = "ltx-2-3-pro"
    supported_modes = frozenset({"text", "first_frame", "first_last_frame"})
    success_statuses = frozenset({"completed"})
    failure_statuses = frozenset({"failed"})
    _RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}

    def __init__(self, **kwargs):
        self._job_endpoints: dict[str, str] = {}
        super().__init__(**kwargs)

    @classmethod
    def resolution_for(cls, resolution: str, aspect_ratio: str) -> str:
        width, height = cls._RESOLUTIONS.get(resolution.lower(), cls._RESOLUTIONS["1080p"])
        portrait = aspect_ratio.replace("：", ":").strip() == "9:16"
        return f"{height}x{width}" if portrait else f"{width}x{height}"

    @staticmethod
    def duration_for(model: str, seconds: int) -> int:
        # ltx-2-3-fast documents 6-20s even lengths at 720p/1080p; pro documents 6/8/10.
        allowed = tuple(range(6, 21, 2)) if "fast" in model else (6, 8, 10)
        # On a tie prefer the longer clip: a shot never loses planned content.
        return min(allowed, key=lambda value: (abs(value - seconds), -value))

    def _payload(self, request: VideoJobRequest, mode: VideoMode) -> tuple[str, dict[str, Any]]:
        model = request.model if request.model.lower().startswith("ltx-") else self.default_model
        body: dict[str, Any] = {
            "prompt": request.prompt,
            "model": model,
            "duration": self.duration_for(model, request.duration_seconds),
            "resolution": self.resolution_for(request.resolution, request.aspect_ratio),
            "fps": 24,
            "generate_audio": True,
        }
        if mode == "text":
            return "text-to-video", body
        body["image_uri"] = request.first_frame
        if request.last_frame:
            body["last_frame_uri"] = request.last_frame
        return "image-to-video", body

    @staticmethod
    def _result(data: dict[str, Any]) -> VideoJobResult:
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        task_id = data.get("id")
        return VideoJobResult(
            task_id=str(task_id) if task_id else None,
            status=str(data.get("status") or "pending"),
            video_url=str(result["video_url"]) if result.get("video_url") else None,
            provider_payload=data,
        )

    def create_video(self, request: VideoJobRequest) -> VideoJobResult:
        mode = self.ensure_mode(request)
        endpoint, body = self._payload(request, mode)
        response = self._client.post(f"{self.base_url}/v2/{endpoint}", json=body)
        self._raise_safe(response)
        result = self._result(response.json())
        if result.task_id:
            self._job_endpoints[result.task_id] = endpoint
        return result

    def get_task(self, task_id: str) -> VideoJobResult:
        task_id = _safe_task_id(task_id, "LTX")
        endpoint = self._job_endpoints.get(task_id, "image-to-video")
        response = self._client.get(f"{self.base_url}/v2/{endpoint}/{task_id}")
        self._raise_safe(response)
        return self._result(response.json())


ADAPTERS: dict[str, type[VideoProviderAdapter]] = {
    KlingVideoAdapter.family: KlingVideoAdapter,
    GrokImagineAdapter.family: GrokImagineAdapter,
    HappyHorseFalAdapter.family: HappyHorseFalAdapter,
    LtxVideoAdapter.family: LtxVideoAdapter,
}
# Router family -> provider id used by the model configuration center.
RUNTIME_PROVIDER_FOR_FAMILY = {"kling": "kling", "grok": "xai", "happyhorse": "fal", "ltx_2_3": "ltx"}
ENV_KEY_FOR_FAMILY = {"kling": "KLING_API_KEY", "grok": "XAI_API_KEY", "happyhorse": "FAL_KEY", "ltx_2_3": "LTX_API_KEY"}
ENV_BASE_URL_FOR_FAMILY = {"kling": "KLING_BASE_URL", "grok": "XAI_BASE_URL", "happyhorse": "FAL_QUEUE_URL", "ltx_2_3": "LTX_BASE_URL"}


def adapter_supported_modes(family: str) -> frozenset[str] | None:
    adapter = ADAPTERS.get(family)
    return adapter.supported_modes if adapter else None


def resolve_family_credentials(family: str, model: str = "") -> tuple[str, str] | None:
    """Configured credentials for a routed family: the model's own configuration,
    then any configuration for that provider, then the server environment."""

    provider = RUNTIME_PROVIDER_FOR_FAMILY.get(family)
    if provider is None:
        return None
    runtime = runtime_model_registry.resolve(model, "video") if model else None
    if runtime is not None and runtime.provider != provider:
        runtime = None
    runtime = runtime or runtime_model_registry.first(provider, "video")
    if runtime is not None and runtime.api_key.strip():
        return runtime.api_key, runtime.base_url
    key = os.getenv(ENV_KEY_FOR_FAMILY[family], "").strip()
    if not key or key.startswith("YOUR_"):
        return None
    base_url = os.getenv(ENV_BASE_URL_FOR_FAMILY[family], "").strip() or ADAPTERS[family].default_base_url
    return key, base_url


def family_ready(family: str, model: str = "") -> bool:
    return resolve_family_credentials(family, model) is not None


def build_video_adapter(
    family: str,
    *,
    api_key: str,
    base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> VideoProviderAdapter:
    adapter = ADAPTERS.get(family)
    if adapter is None:
        raise RuntimeError(f"no video adapter for provider family {family}")
    return adapter(api_key=api_key, base_url=base_url, transport=transport)
