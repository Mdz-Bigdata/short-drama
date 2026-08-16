"""MiniMax H3 video-generation adapter with FL2VA and Ref2VA routing."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.schema.production import H3VideoRequest


class H3TaskResult(BaseModel):
    task_id: str | None = None
    status: str
    video_url: str | None = None
    file_id: str | None = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)


def _find_key(data: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(data, dict):
        for key in keys:
            if data.get(key) not in (None, ""):
                return data[key]
        for value in data.values():
            found = _find_key(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_key(value, keys)
            if found not in (None, ""):
                return found
    return None


def _result_identifier(data: dict[str, Any]) -> Any:
    for container in (data, data.get("data"), data.get("task"), data.get("result")):
        if not isinstance(container, dict):
            continue
        for key in ("task_id", "taskId", "id"):
            if container.get(key) not in (None, ""):
                return container[key]
    return _find_key(data, ("task_id", "taskId"))


def _result_video_url(data: dict[str, Any]) -> Any:
    # A generic recursive `url` can point to an echoed reference input. Only
    # accept explicit video fields or a URL nested in an output-like container.
    explicit = _find_key(data, ("video_url", "download_url", "file_url"))
    if explicit:
        return explicit
    for key in ("output", "result", "video", "file", "data", "task"):
        container = data.get(key)
        if isinstance(container, dict):
            if container.get("url"):
                return container["url"]
            content = container.get("content")
            if isinstance(content, dict) and content.get("url"):
                return content["url"]
        if isinstance(container, list):
            for item in container:
                if isinstance(item, dict) and item.get("url") and (
                    item.get("type") in {None, "video"}
                    or str(item.get("mime_type", "")).startswith("video/")
                ):
                    return item["url"]
    return None


class MiniMaxH3Client:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        status_url_template: str | None = None,
        files_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 180,
    ):
        key = (api_key or os.getenv("MINIMAX_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("MINIMAX_API_KEY is required on the server")
        self.endpoint = (
            endpoint
            or os.getenv("MINIMAX_H3_ENDPOINT")
            or "https://api.minimaxi.com/v2/video_generation"
        ).rstrip("/")
        parsed_endpoint = urlsplit(self.endpoint)
        api_origin = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
        self.status_url_template = (
            status_url_template
            or os.getenv("MINIMAX_H3_STATUS_URL_TEMPLATE")
            or (api_origin + "/v2/query/video_generation/{task_id}")
        )
        self.files_url = (
            files_url
            or os.getenv("MINIMAX_FILES_URL")
            or (api_origin + "/v1/files/retrieve")
        )
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    @staticmethod
    def _raise_safe(response: httpx.Response) -> None:
        if response.is_success:
            return
        request_id = response.headers.get("x-request-id", "unknown")
        raise RuntimeError(f"MiniMax H3 request failed: HTTP {response.status_code}, request_id={request_id}")

    @staticmethod
    def _payload(request: H3VideoRequest) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {"type": "text", "text": request.prompt},
        ]

        def add_reference(media_type: str, url: str, role: str) -> None:
            content_type = f"{media_type}_url"
            content.append({
                "type": content_type,
                content_type: {"url": str(url)},
                "role": role,
            })

        if request.first_frame:
            add_reference("image", request.first_frame, "first_frame")
        if request.last_frame:
            add_reference("image", request.last_frame, "last_frame")
        for url in request.reference_images:
            add_reference("image", url, "reference_image")
        for url in request.reference_videos:
            add_reference("video", url, "reference_video")
        for url in request.reference_audios:
            add_reference("audio", url, "reference_audio")
        for binding in request.reference_bindings:
            add_reference(
                binding.media_type,
                binding.uri,
                f"reference_{binding.media_type}",
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "content": content,
            "duration": request.duration_seconds,
            "resolution": request.resolution.upper(),
        }
        # H3 derives image/reference aspect ratios from the supplied media.
        # Only pure text generation requires an explicit non-adaptive ratio.
        if request.inferred_mode == "text":
            payload["ratio"] = request.aspect_ratio
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    @staticmethod
    def _result(data: dict[str, Any]) -> H3TaskResult:
        task_id = _result_identifier(data)
        status = str(_find_key(data, ("status", "state", "task_status")) or "queued")
        video_url = _result_video_url(data)
        file_id = _find_key(data, ("file_id", "fileId"))
        return H3TaskResult(
            task_id=str(task_id) if task_id is not None else None,
            status=status,
            video_url=str(video_url) if video_url else None,
            file_id=str(file_id) if file_id else None,
            provider_payload=data,
        )

    def create_video(self, request: H3VideoRequest) -> H3TaskResult:
        response = self._client.post(self.endpoint, json=self._payload(request))
        self._raise_safe(response)
        return self._result(response.json())

    def get_task(self, task_id: str) -> H3TaskResult:
        if not task_id or not task_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid MiniMax task id")
        has_placeholder = "{task_id}" in self.status_url_template
        url = self.status_url_template.format(task_id=task_id)
        response = self._client.get(url, params=None if has_placeholder else {"task_id": task_id})
        self._raise_safe(response)
        result = self._result(response.json())
        if result.file_id and not result.video_url:
            result.video_url = self.retrieve_file(result.file_id)
        return result

    def retrieve_file(self, file_id: str) -> str:
        if not file_id or not file_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid MiniMax file id")
        response = self._client.get(self.files_url, params={"file_id": file_id})
        self._raise_safe(response)
        download_url = _find_key(response.json(), ("download_url", "file_url"))
        if not download_url:
            raise RuntimeError("MiniMax file response did not contain a download URL")
        return str(download_url)

    def wait_for_video(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 900,
        poll_interval_seconds: float = 5,
    ) -> H3TaskResult:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.get_task(task_id)
            status = result.status.lower()
            if result.video_url or status in {"success", "succeeded", "completed", "done"}:
                return result
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"MiniMax H3 task ended with status={result.status}")
            time.sleep(min(max(poll_interval_seconds, 0.2), 30))
        raise TimeoutError("MiniMax H3 video generation timed out")

    def close(self) -> None:
        self._client.close()
