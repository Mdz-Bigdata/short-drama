"""ComfyUI as a self-hosted image / video provider, driven by the person's own workflow.

ComfyUI runs a workflow graph, not a model name, so nothing can be generated
until a workflow is supplied: a JSON export in the API format, with bindings
that say which node inputs take the prompt, the first frame and the seed. The
server address and the workflow are server configuration (environment), never
user input — a ComfyUI usually sits on a private network the public URL rules
would refuse. Without a workflow the provider reports itself as configurable
but not ready, and no stage will route to it.

Protocol (ComfyUI's documented HTTP API): POST /prompt with {prompt, client_id}
answers {prompt_id}; GET /history/{prompt_id} lists outputs per node with
{filename, subfolder, type}; GET /view?filename=…&subfolder=…&type=… serves them.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx

from app import settings

FAMILY = "comfyui"
ENV_BASE_URL = "COMFYUI_BASE_URL"
ENV_WORKFLOW = "COMFYUI_WORKFLOW_PATH"
ENV_BINDINGS = "COMFYUI_BINDINGS"
ENV_API_KEY = "COMFYUI_API_KEY"
DEFAULT_BINDINGS = {"prompt": "", "negative_prompt": "", "image": "", "seed": "", "video_frames": ""}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".gif")


def status() -> dict[str, Any]:
    """Whether ComfyUI can be used, and what is missing when it cannot."""
    base_url = os.getenv(ENV_BASE_URL, "").strip()
    workflow_path = os.getenv(ENV_WORKFLOW, "").strip()
    bindings = _bindings_from_env()
    problems: list[str] = []
    if not base_url:
        problems.append(f"未设置 {ENV_BASE_URL}")
    workflow_state = "missing"
    if not workflow_path:
        problems.append(f"未提供工作流：设置 {ENV_WORKFLOW} 指向 ComfyUI 导出的 API 格式 JSON")
    elif not Path(workflow_path).is_file():
        problems.append(f"工作流文件不存在：{workflow_path}")
    else:
        try:
            load_workflow(workflow_path)
            workflow_state = "loaded"
        except ValueError as exc:
            problems.append(str(exc))
            workflow_state = "invalid"
    if workflow_state == "loaded" and not bindings.get("prompt"):
        problems.append(f"{ENV_BINDINGS} 里缺少 prompt 绑定（形如 {{\"prompt\": \"6.inputs.text\"}}）")
    return {
        "family": FAMILY,
        "label": "ComfyUI（自托管工作流）",
        "configured": bool(base_url),
        "workflow": workflow_state,
        "ready": not problems,
        "problems": problems,
        "base_url_set": bool(base_url),
        "bindings": {key: bool(value) for key, value in bindings.items()},
        "how_to": "导出 ComfyUI 工作流（Save (API Format)），设置 COMFYUI_WORKFLOW_PATH 与 COMFYUI_BINDINGS 后重启；无工作流时不会向 ComfyUI 发送任何请求。",
    }


def ready() -> bool:
    return bool(status()["ready"])


def _bindings_from_env() -> dict[str, str]:
    raw = os.getenv(ENV_BINDINGS, "").strip()
    bindings = dict(DEFAULT_BINDINGS)
    if not raw:
        return bindings
    try:
        parsed = json.loads(raw)
    except ValueError:
        return bindings
    if isinstance(parsed, dict):
        for key in bindings:
            if isinstance(parsed.get(key), str):
                bindings[key] = parsed[key].strip()
    return bindings


def load_workflow(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"工作流文件无法读取或不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict) or not data or not all(isinstance(node, dict) and "class_type" in node for node in data.values()):
        raise ValueError("工作流必须是 ComfyUI 的 API 格式（节点号 → {class_type, inputs}），请用「Save (API Format)」导出")
    return data


def bind(workflow: dict[str, Any], bindings: dict[str, str], values: dict[str, Any]) -> dict[str, Any]:
    """A copy of the workflow with each bound input set; a binding is ``node.inputs.field``."""
    filled = deepcopy(workflow)
    for name, path in bindings.items():
        if not path or values.get(name) is None:
            continue
        node_id, _, field = path.partition(".inputs.")
        node = filled.get(node_id)
        if not isinstance(node, dict) or not field:
            raise ValueError(f"绑定 {name}={path} 指向的节点或输入不存在")
        node.setdefault("inputs", {})[field] = values[name]
    return filled


class ComfyUIClient:
    def __init__(self, *, base_url: str, workflow: dict[str, Any], bindings: dict[str, str], api_key: str = "",
                 transport: httpx.BaseTransport | None = None, timeout_seconds: float = 120):
        self.base_url = base_url.rstrip("/")
        self.workflow = workflow
        self.bindings = bindings
        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        self._client = httpx.Client(headers=headers, timeout=timeout_seconds, transport=transport)
        self.client_id = uuid.uuid4().hex

    @classmethod
    def from_environment(cls, transport: httpx.BaseTransport | None = None) -> "ComfyUIClient":
        view = status()
        if not view["ready"]:
            raise RuntimeError("ComfyUI 未就绪：" + "；".join(view["problems"]))
        return cls(
            base_url=os.getenv(ENV_BASE_URL, ""), workflow=load_workflow(os.getenv(ENV_WORKFLOW, "")),
            bindings=_bindings_from_env(), api_key=os.getenv(ENV_API_KEY, ""), transport=transport,
        )

    def queue(self, *, prompt: str, negative_prompt: str = "", image: str | None = None, seed: int | None = None, video_frames: int | None = None) -> str:
        graph = bind(self.workflow, self.bindings, {
            "prompt": prompt, "negative_prompt": negative_prompt or None, "image": image, "seed": seed, "video_frames": video_frames,
        })
        response = self._client.post(f"{self.base_url}/prompt", json={"prompt": graph, "client_id": self.client_id})
        if not response.is_success:
            raise RuntimeError(f"ComfyUI /prompt failed: HTTP {response.status_code}")
        prompt_id = str(response.json().get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt_id")
        return prompt_id

    def outputs(self, prompt_id: str) -> list[str]:
        """Served URLs of every image / video the finished prompt produced; empty while it runs."""
        response = self._client.get(f"{self.base_url}/history/{prompt_id}")
        if not response.is_success:
            raise RuntimeError(f"ComfyUI /history failed: HTTP {response.status_code}")
        entry = (response.json() or {}).get(prompt_id)
        if not isinstance(entry, dict):
            return []
        status_block = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        if status_block.get("status_str") == "error":
            raise RuntimeError("ComfyUI workflow ended with an error")
        urls: list[str] = []
        for node_output in (entry.get("outputs") or {}).values():
            if not isinstance(node_output, dict):
                continue
            for kind in ("images", "gifs", "videos"):
                for item in node_output.get(kind) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        query = httpx.QueryParams({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                        urls.append(f"{self.base_url}/view?{query}")
        return urls

    def wait(self, prompt_id: str, *, timeout_seconds: float = 600, poll_interval_seconds: float = 3) -> list[str]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            urls = self.outputs(prompt_id)
            if urls:
                return urls
            time.sleep(max(0.0, min(poll_interval_seconds, 30)))
        raise TimeoutError("ComfyUI workflow timed out")

    def generate(self, *, prompt: str, image: str | None = None, seed: int | None = None, want: str = "image") -> str | None:
        """One run of the workflow; returns the first output of the wanted kind."""
        prompt_id = self.queue(prompt=prompt, image=image, seed=seed)
        urls = self.wait(
            prompt_id,
            timeout_seconds=settings.env_float("COMFYUI_WAIT_SECONDS", 600, minimum=1),
            poll_interval_seconds=settings.env_float("COMFYUI_POLL_SECONDS", 3, minimum=0),
        )
        suffixes = VIDEO_SUFFIXES if want == "video" else IMAGE_SUFFIXES
        for url in urls:
            name = url.split("filename=", 1)[-1].split("&", 1)[0].lower()
            if name.endswith(suffixes):
                return url
        return None

    def close(self) -> None:
        self._client.close()


__all__ = ["FAMILY", "ComfyUIClient", "bind", "load_workflow", "ready", "status"]
