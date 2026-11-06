"""The node canvas's rules, with no I/O: what connects to what, what a run feeds a node, what a commit touches.

A node has one typed output; a connection is legal when the target has an input for
that type, and the edge then says what the connection means (``reference`` feeds a
generation as a reference, ``dependency`` is raw material). The frontend keeps the
same table in ``features/canvas/canvasGraph.ts`` so it can refuse a drag at once; the
server is what decides.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.core import canvas_tools
from app.core.reference_limits import MAX_REFERENCE_AUDIOS, MAX_REFERENCE_IMAGES, MAX_REFERENCE_VIDEOS

RUNNABLE = {"image_gen": "image", "video_gen": "video", "audio_gen": "audio", "video_compose": "video"}
# Kinds an agent (or anyone but the importer) may create.
CREATABLE = frozenset({"media", "note", "group", "image_gen", "video_gen", "audio_gen", "video_compose", "style_ref", "panorama", "previz", "tool"})

# target kind -> output type -> (edge kind, role)
_INPUTS: dict[str, dict[str, tuple[str, str]]] = {
    "image_gen": {"image": ("reference", "ref_image"), "style": ("reference", "style"), "text": ("dependency", "prompt"), "capture": ("reference", "ref_capture")},
    "video_gen": {
        "image": ("reference", "ref_image"), "video": ("reference", "ref_video"), "audio": ("reference", "ref_audio"),
        "style": ("reference", "style"), "text": ("dependency", "prompt"), "capture": ("reference", "ref_capture"),
    },
    "audio_gen": {"text": ("dependency", "prompt")},
    "video_compose": {"video": ("dependency", "clip"), "capture": ("dependency", "clip"), "audio": ("dependency", "soundtrack")},
    "style_ref": {"image": ("reference", "style_image")},
    "panorama": {"image": ("reference", "equirect")},
    "previz": {"image": ("reference", "blockout_image")},
}
# Which roles a person may pick for a connection, per (target kind, output type).
_ROLE_CHOICES = {
    ("video_gen", "image"): frozenset({"ref_image", "first_frame", "last_frame"}),
    # ``continue_from``: the next part of the same continuous shot; its first frame is this clip's last frame.
    ("video_gen", "video"): frozenset({"ref_video", "continue_from"}),
}

DEFAULT_SIZES = {
    "media": (260, 200), "note": (240, 150), "group": (480, 320), "image_gen": (300, 320), "video_gen": (320, 340), "audio_gen": (280, 240),
    "video_compose": (300, 240), "style_ref": (240, 220), "panorama": (340, 260), "previz": (320, 300), "tool": (300, 340),
}
KIND_LABELS = {
    "artifact": "产物", "candidate": "候选", "media": "上传素材", "note": "文本注释", "group": "分组", "image_gen": "图像生成",
    "video_gen": "视频生成", "audio_gen": "音频生成", "video_compose": "视频合成", "style_ref": "风格参考", "panorama": "360° 全景", "previz": "预演", "tool": "工具",
}


class CanvasOperationError(ValueError):
    """An agent's edit names something the canvas cannot do; nothing of the request is applied."""


def _tool_of(node: Mapping[str, Any]) -> canvas_tools.CanvasTool | None:
    try:
        return canvas_tools.tool_of(node)
    except canvas_tools.CanvasToolError:
        return None


def inputs_of(node: Mapping[str, Any]) -> Mapping[str, tuple[str, str]]:
    """What a node takes. A tool node's table depends on which tool it is set to."""
    if node.get("kind") == "tool":
        tool = _tool_of(node)
        return tool.inputs if tool else {}
    return _INPUTS.get(str(node.get("kind") or ""), {})


def medium_of(node: Mapping[str, Any]) -> str | None:
    """What running this node makes; ``None`` when it does not run."""
    if node.get("kind") == "tool":
        tool = _tool_of(node)
        return tool.output if tool else None
    return RUNNABLE.get(str(node.get("kind") or ""))


def output_type(node: Mapping[str, Any]) -> str | None:
    """What this node hands downstream; ``None`` when it has nothing to hand yet."""
    kind = str(node.get("kind") or "")
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    if kind in {"image_gen", "panorama"}:
        return "image"
    if kind in {"video_gen", "video_compose"}:
        return "video"
    if kind == "audio_gen":
        return "audio"
    if kind == "note":
        return "text"
    if kind == "style_ref":
        return "style"
    if kind == "previz":
        return "capture"
    if kind == "group":
        return None
    if kind == "tool":
        tool = _tool_of(node)
        return tool.output if tool else None
    output = payload.get("output") if isinstance(payload.get("output"), Mapping) else {}
    medium = str(output.get("medium") or payload.get("medium") or "")
    return medium if medium in {"image", "video", "audio"} else None


def connection(source: Mapping[str, Any], target: Mapping[str, Any], *, role: str | None = None) -> tuple[str, str]:
    """(edge kind, role) of this connection; raises ``CanvasOperationError`` saying why it is not allowed."""
    if source.get("id") == target.get("id"):
        raise CanvasOperationError("节点不能连接自己")
    produced = output_type(source)
    if produced is None:
        raise CanvasOperationError(f"「{KIND_LABELS.get(str(source.get('kind')), source.get('kind'))}」还没有可以输出的内容")
    inputs = inputs_of(target)
    if not inputs or produced not in inputs:
        raise CanvasOperationError(f"「{KIND_LABELS.get(str(target.get('kind')), target.get('kind'))}」不接受这种输入（{produced}）")
    edge_kind, default_role = inputs[produced]
    if role and role != default_role:
        if role not in _ROLE_CHOICES.get((str(target.get("kind")), produced), ()):
            raise CanvasOperationError(f"这条连接不能用作 {role}")
        return edge_kind, role
    return edge_kind, default_role


def creates_cycle(edges: Iterable[Mapping[str, Any]], source: str, target: str) -> bool:
    """Would ``source -> target`` make a loop? A generation cannot be its own upstream."""
    forward: dict[str, list[str]] = {}
    for edge in edges:
        forward.setdefault(str(edge.get("source")), []).append(str(edge.get("target")))
    stack, seen = [target], set()
    while stack:
        current = stack.pop()
        if current == source:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(forward.get(current, ()))
    return False


def safe_media_url(value: Any) -> str:
    """The URL when it is something we may hand to a provider or a player, else ``''``."""
    text = str(value or "").strip()
    if text.startswith("/media/"):
        return text
    if text.startswith("data:image/"):
        return text
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
        return text
    return ""


def payload_of(node: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = node.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _run_output(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    output = (entry or {}).get("output")
    # A text tool's result has words and no file.
    return dict(output) if isinstance(output, Mapping) and (output.get("url") or output.get("text")) else None


def effective_output(
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    runs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    """What a node shows and hands on: its active generation, else what it holds, else (pass-through kinds) its input."""
    node_id = str(node.get("id"))
    from_run = _run_output(runs.get(node_id))
    if from_run:
        return from_run
    held = payload_of(node).get("output")
    if isinstance(held, Mapping) and held.get("url"):
        return dict(held)
    if node.get("kind") in {"style_ref", "panorama"}:
        for edge in edges:
            if str(edge.get("target")) == node_id and str(edge.get("source")) in nodes:
                upstream = effective_output(nodes[str(edge.get("source"))], {k: v for k, v in nodes.items() if k != node_id}, edges, runs)
                if upstream and upstream.get("medium") == "image":
                    return upstream
    return None


@dataclass
class Inputs:
    prompt_parts: list[str] = field(default_factory=list)
    first_frame: str | None = None
    last_frame: str | None = None
    ref_images: list[str] = field(default_factory=list)
    ref_videos: list[str] = field(default_factory=list)
    # A clip whose last frame this one opens on: the same shot continued, not a cut.
    continue_from: str | None = None
    # What that clip was told to end on, so this one can say it is picking up from there.
    continue_from_prompt: str = ''
    ref_audios: list[str] = field(default_factory=list)
    clips: list[str] = field(default_factory=list)
    soundtrack: str | None = None
    # node ids in this batch whose result is still to come.
    pending: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)

    def has_visual_reference(self) -> bool:
        return bool(self.first_frame or self.ref_images or self.ref_videos or self.continue_from)


def selected_captures(node: Mapping[str, Any], captures_of: Callable[[str], Sequence[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    payload = payload_of(node)
    scene_id = str(payload.get("sceneId") or "")
    wanted = [str(item) for item in payload.get("selectedCaptureIds") or []]
    if not scene_id or not wanted:
        return []
    by_id = {str(item.get("id")): item for item in captures_of(scene_id)}
    return [by_id[item] for item in wanted if item in by_id]


def resolve_inputs(
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    runs: Mapping[str, Mapping[str, Any]],
    captures_of: Callable[[str], Sequence[Mapping[str, Any]]],
    *,
    in_batch: Iterable[str] = (),
) -> Inputs:
    """Everything connected to ``node``, by what the connection means."""
    resolved = Inputs()
    batch = set(in_batch)
    node_id = str(node.get("id"))
    for edge in edges:
        if str(edge.get("target")) != node_id:
            continue
        source = nodes.get(str(edge.get("source")))
        if source is None:
            continue
        source_id = str(source.get("id"))
        edge_payload = edge.get("payload") if isinstance(edge.get("payload"), Mapping) else {}
        produced = output_type(source)
        inputs = inputs_of(node)
        if produced not in inputs:
            # An edge an older canvas drew for its own reasons (lineage, variant): it feeds nothing.
            continue
        role = str(edge_payload.get("role") or inputs[produced][1])
        if produced == "text":
            if source.get("kind") == "tool":
                # Words a tool came up with travel like a note's, once it has come up with them.
                output = _run_output(runs.get(source_id))
                if output and output.get("text"):
                    resolved.prompt_parts.append(str(output["text"]).strip())
                elif source_id in batch:
                    resolved.pending.append(source_id)
                else:
                    resolved.problems.append(f"上游节点 {_label(source)} 还没有结果")
                continue
            text = str(payload_of(source).get("text") or "").strip()
            if text:
                resolved.prompt_parts.append(text)
            continue
        if produced == "capture":
            captures = selected_captures(source, captures_of)
            if not captures:
                resolved.problems.append(f"预演节点 {_label(source)} 没有选中可用的截取")
            for capture in captures:
                _take_capture(resolved, capture, source_id, node)
            continue
        if produced == "style":
            style = str(payload_of(source).get("styleText") or "").strip()
            if style:
                resolved.prompt_parts.append(style)
            output = effective_output(source, nodes, edges, runs)
            if output and output.get("medium") == "image":
                _add_url(resolved, "ref_image", output.get("url"), source_id)
            continue
        output = effective_output(source, nodes, edges, runs)
        if output is None:
            if source_id in batch:
                resolved.pending.append(source_id)
            else:
                resolved.problems.append(f"上游节点 {_label(source)} 还没有结果")
            continue
        _add_url(resolved, role, output.get("url"), source_id)
        if role == "continue_from":
            resolved.continue_from_prompt = str(payload_of(source).get("prompt") or "")
    if len(resolved.ref_images) > MAX_REFERENCE_IMAGES:
        resolved.problems.append(f"参考图最多 {MAX_REFERENCE_IMAGES} 张，现在连了 {len(resolved.ref_images)} 张")
    if len(resolved.ref_videos) > MAX_REFERENCE_VIDEOS:
        resolved.problems.append(f"参考视频最多 {MAX_REFERENCE_VIDEOS} 段，现在连了 {len(resolved.ref_videos)} 段")
    if len(resolved.ref_audios) > MAX_REFERENCE_AUDIOS:
        resolved.problems.append(f"参考音频最多 {MAX_REFERENCE_AUDIOS} 段，现在连了 {len(resolved.ref_audios)} 段")
    return resolved


def _takes_mask(node: Mapping[str, Any]) -> bool:
    tool = _tool_of(node) if node.get("kind") == "tool" else None
    return bool(tool and tool.id == "composite")


def _take_capture(resolved: Inputs, capture: Mapping[str, Any], source_id: str, node: Mapping[str, Any]) -> None:
    capture_kind = str(capture.get("kind") or "")
    if capture.get("stale"):
        resolved.problems.append("所选截取是按旧站位拍的，请回导演台重新截取")
        return
    compose = node.get("kind") == "video_compose"
    if capture_kind == "clip":
        _add_url(resolved, "clip" if compose else "ref_video", capture.get("url"), source_id)
    elif capture_kind == "still" and not compose:
        if capture.get("layer") == "mask" and not _takes_mask(node):
            resolved.problems.append("人物遮罩是黑白控制图，不能作为参考图；请改选普通静帧或空景，或连到「贴回人物」工具")
            return
        if capture.get("depth"):
            # The same refusal the desk gives: a video model would copy a depth picture as a grey frame.
            resolved.problems.append("深度静帧不能作为参考图；请改选普通静帧或深度视频")
            return
        _add_url(resolved, "ref_image", capture.get("url"), source_id)


def _add_url(resolved: Inputs, role: str, value: Any, source_id: str) -> None:
    url = safe_media_url(value)
    if not url:
        resolved.problems.append("上游节点的结果地址不可用")
        return
    resolved.sources.append({"node_id": source_id, "role": role, "url": url})
    if role == "first_frame":
        if resolved.continue_from:
            resolved.problems.append("首帧只能有一个：要么接上一段的尾帧，要么连一张首帧图")
        resolved.first_frame = url
    elif role == "last_frame":
        resolved.last_frame = url
    elif role == "ref_image":
        resolved.ref_images.append(url)
    elif role == "ref_video":
        resolved.ref_videos.append(url)
    elif role == "continue_from":
        if resolved.continue_from or resolved.first_frame:
            resolved.problems.append("首帧只能有一个：要么接上一段的尾帧，要么连一张首帧图")
        resolved.continue_from = url
    elif role == "ref_audio":
        resolved.ref_audios.append(url)
    elif role == "clip":
        resolved.clips.append(url)
    elif role == "soundtrack":
        resolved.soundtrack = url


def _label(node: Mapping[str, Any]) -> str:
    payload = payload_of(node)
    return str(payload.get("label") or payload.get("title") or KIND_LABELS.get(str(node.get("kind")), node.get("id")))[:60]


def batch_order(node_ids: Sequence[str], edges: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, list[str]]]:
    """The batch upstream-first, and for each node the batch members it must wait for."""
    wanted = list(dict.fromkeys(node_ids))
    members = set(wanted)
    upstream: dict[str, list[str]] = {item: [] for item in wanted}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in members and target in members and source != target and source not in upstream[target]:
            upstream[target].append(source)
    ordered: list[str] = []
    placed: set[str] = set()
    remaining = list(wanted)
    while remaining:
        ready = [item for item in remaining if all(dep in placed for dep in upstream[item])]
        if not ready:
            raise ValueError("所选节点之间有环，无法排出运行顺序")
        for item in ready:
            ordered.append(item)
            placed.add(item)
        remaining = [item for item in remaining if item not in placed]
    return ordered, upstream


# ---------------------------------------------------------------------------- version retention


def versions_to_prune(rows: Sequence[tuple[int, str]], *, keep_recent: int = 50, keep_hourly_for: int = 200) -> list[int]:
    """Which old versions to drop: autosave writes a full copy every few seconds, and the archive limit counts them all.

    The newest ``keep_recent`` stay; among the next ``keep_hourly_for`` one per hour stays, beyond
    that one per day. The latest version is always in the first group, so version numbers never go back.
    """
    ordered = sorted(rows, key=lambda row: row[0], reverse=True)
    drop: list[int] = []
    seen: set[str] = set()
    for index, (version, created_at) in enumerate(ordered):
        if index < keep_recent:
            continue
        try:
            stamp = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        bucket = stamp.strftime("%Y-%m-%dT%H" if index < keep_recent + keep_hourly_for else "%Y-%m-%d")
        if bucket in seen:
            drop.append(version)
        else:
            seen.add(bucket)
    return drop


# ---------------------------------------------------------------------------- what a commit touches


def _binding(node: Mapping[str, Any]) -> tuple[str, int | None] | None:
    payload = payload_of(node)
    binding = payload.get("binding") if isinstance(payload.get("binding"), Mapping) else payload if node.get("kind") == "previz" else {}
    scene_id = str((binding or {}).get("sceneId") or "").strip()
    if not scene_id:
        return None
    raw = (binding or {}).get("shotId")
    try:
        shot_id = int(raw) if raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        shot_id = None
    return scene_id, shot_id


def bound_shots(
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    shots: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The project's shots this node's result would land on.

    Its own binding wins; otherwise a previz node connected to it (either side) says which shot
    the work is for. A binding with a scene and no shot means every shot of that scene.
    """
    binding = _binding(node)
    if binding is None:
        node_id = str(node.get("id"))
        for edge in edges:
            source, target = str(edge.get("source")), str(edge.get("target"))
            other = nodes.get(target if source == node_id else source) if node_id in (source, target) else None
            if other is not None and other.get("kind") == "previz" and (binding := _binding(other)):
                break
    if binding is None:
        return []
    scene_id, shot_id = binding
    found = []
    for shot in shots:
        if str(shot.get("scene_id") or "") != scene_id:
            continue
        if shot_id is not None and _as_int(shot.get("shot_id")) != shot_id:
            continue
        found.append({"scene_id": scene_id, "shot_id": _as_int(shot.get("shot_id")), "shot_uid": shot.get("shot_uid"), "desc": str(shot.get("desc") or "")[:60]})
    return found


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def commit_target_kind(node: Mapping[str, Any], medium: str | None) -> str | None:
    """The artifact kind a result becomes in the project."""
    if medium == "image":
        return "asset"
    if medium == "video":
        return "clip"
    if medium == "audio":
        return "audio"
    return None


def commit_source(node: Mapping[str, Any], run: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Where the node's result came from, or ``None`` when nobody can say: such a node is not committed."""
    # The run comes first: a node committed once and generated again has a new result to commit.
    output = _run_output(run)
    if output:
        return {"kind": "run", "run_id": str((run or {}).get("id")), "model": str((run or {}).get("model") or ""),
                "request": dict((run or {}).get("request") or {}), "output": output}
    if node.get("artifact_id"):
        return {"kind": "artifact", "artifact_id": node.get("artifact_id")}
    held = payload_of(node).get("output")
    if isinstance(held, Mapping) and held.get("url") and isinstance(held.get("provenance"), Mapping):
        return {"kind": "output", "provenance": dict(held["provenance"]), "output": dict(held)}
    return None


def slot_for(medium: str | None) -> str | None:
    """The per-shot field stage 5 reads for this medium; the same slots the director desk writes."""
    return {"image": "sequence_images", "video": "reference_videos"}.get(str(medium))


# ---------------------------------------------------------------------------- an agent's edit, as one document change


def _new_id() -> str:
    return f"n_{uuid.uuid4().hex[:16]}"


def _place(nodes: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    """To the right of everything already there, top-aligned, so a chain added in order reads left to right."""
    laid = [item for item in nodes if item.get("kind") != "group"]
    if not laid:
        return 0.0, 0.0
    right = max(float(item.get("x") or 0) + float(item.get("width") or 0) for item in laid)
    top = min(float(item.get("y") or 0) for item in laid)
    return right + 80.0, top


_TEXT_FIELDS = ("label", "prompt", "text", "styleText", "sceneId", "shotId", "medium")


def apply_operations(document: Mapping[str, Any], operations: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply every operation or none: returns the new document and ``ref -> node id`` for what was added."""
    if not operations:
        raise CanvasOperationError("operations 不能为空")
    nodes: list[dict[str, Any]] = [dict(item) for item in document.get("nodes") or []]
    edges: list[dict[str, Any]] = [dict(item) for item in document.get("edges") or []]
    refs: dict[str, str] = {}

    def resolve(value: Any) -> str:
        key = str(value or "")
        return refs.get(key, key)

    def find(value: Any) -> dict[str, Any]:
        node_id = resolve(value)
        for node in nodes:
            if node.get("id") == node_id:
                return node
        raise CanvasOperationError(f"画布上没有节点 {value}")

    for index, operation in enumerate(operations, start=1):
        op = str(operation.get("op") or "")
        try:
            if op == "add_node":
                kind = str(operation.get("kind") or "")
                if kind not in CREATABLE:
                    raise CanvasOperationError(f"不能添加 {kind or '未知'} 类型的节点；可用：{'、'.join(sorted(CREATABLE))}")
                width, height = DEFAULT_SIZES[kind]
                x, y = _place(nodes)
                payload: dict[str, Any] = {key: operation[key] for key in _TEXT_FIELDS if operation.get(key) not in (None, "")}
                if isinstance(operation.get("params"), Mapping):
                    payload["params"] = dict(operation["params"])
                node = {
                    "id": _new_id(), "kind": kind, "track": "freezone",
                    "x": float(operation.get("x", x)), "y": float(operation.get("y", y)),
                    "width": float(operation.get("width", width)), "height": float(operation.get("height", height)),
                    "artifact_id": None, "payload": payload,
                }
                nodes.append(node)
                if operation.get("ref"):
                    refs[str(operation["ref"])] = node["id"]
            elif op == "update_node":
                node = find(operation.get("id"))
                payload = dict(node.get("payload") or {})
                for key in _TEXT_FIELDS:
                    if key in operation:
                        payload[key] = operation[key]
                if isinstance(operation.get("params"), Mapping):
                    payload["params"] = {**(payload.get("params") or {}), **operation["params"]}
                node["payload"] = payload
                for key in ("x", "y", "width", "height"):
                    if key in operation:
                        node[key] = float(operation[key])
            elif op == "delete_node":
                node = find(operation.get("id"))
                removed = node["id"]
                nodes = [item for item in nodes if item.get("id") != removed]
                edges = [item for item in edges if removed not in (item.get("source"), item.get("target"))]
                for item in nodes:
                    if (item.get("payload") or {}).get("groupId") == removed:
                        item["payload"] = {k: v for k, v in item["payload"].items() if k != "groupId"}
            elif op == "connect":
                source, target = find(operation.get("source")), find(operation.get("target"))
                edge_kind, role = connection(source, target, role=operation.get("role"))
                if creates_cycle(edges, source["id"], target["id"]):
                    raise CanvasOperationError("这条连接会形成环")
                if not any(item.get("source") == source["id"] and item.get("target") == target["id"] for item in edges):
                    edges.append({"id": f"e_{uuid.uuid4().hex[:16]}", "source": source["id"], "target": target["id"], "kind": edge_kind, "payload": {"role": role}})
            elif op == "disconnect":
                source_id, target_id = resolve(operation.get("source")), resolve(operation.get("target"))
                kept = [item for item in edges if not (item.get("id") == operation.get("edge_id") or (item.get("source") == source_id and item.get("target") == target_id))]
                if len(kept) == len(edges):
                    raise CanvasOperationError("没有这条连接")
                edges = kept
            elif op == "group":
                members = [find(item) for item in operation.get("ids") or []]
                if not members:
                    raise CanvasOperationError("group 需要 ids")
                if any(item.get("kind") == "group" for item in members):
                    raise CanvasOperationError("分组不能嵌套")
                left = min(float(item["x"]) for item in members) - 40
                top = min(float(item["y"]) for item in members) - 60
                right = max(float(item["x"]) + float(item["width"]) for item in members) + 40
                bottom = max(float(item["y"]) + float(item["height"]) for item in members) + 40
                group = {
                    "id": _new_id(), "kind": "group", "track": "freezone", "x": left, "y": top, "width": right - left, "height": bottom - top,
                    "artifact_id": None, "payload": {"label": str(operation.get("label") or "分组")},
                }
                nodes.insert(0, group)
                for member in members:
                    member["payload"] = {**(member.get("payload") or {}), "groupId": group["id"]}
                if operation.get("ref"):
                    refs[str(operation["ref"])] = group["id"]
            else:
                raise CanvasOperationError(f"未知操作 {op or '（缺 op）'}；可用：add_node、update_node、delete_node、connect、disconnect、group")
        except CanvasOperationError as exc:
            raise CanvasOperationError(f"第 {index} 个操作（{op or '?'}）：{exc}；整批未生效") from exc
        except (TypeError, ValueError) as exc:
            raise CanvasOperationError(f"第 {index} 个操作（{op or '?'}）字段不合法：{exc}；整批未生效") from exc
    return {"nodes": nodes, "edges": edges}, refs


def summarize(document: Mapping[str, Any], runs: Mapping[str, Mapping[str, Any]], *, limit: int = 120) -> dict[str, Any]:
    """A canvas as an assistant reads it: what is on it, what is connected, what has a result."""
    nodes = {str(item.get("id")): item for item in document.get("nodes") or []}
    edges = list(document.get("edges") or [])
    by_kind: dict[str, int] = {}
    rows = []
    for node in nodes.values():
        by_kind[str(node.get("kind"))] = by_kind.get(str(node.get("kind")), 0) + 1
    ordered = sorted(nodes.values(), key=lambda item: (float(item.get("y") or 0), float(item.get("x") or 0), str(item.get("id"))))
    for node in ordered[:limit]:
        payload = payload_of(node)
        output = effective_output(node, nodes, edges, runs)
        run = runs.get(str(node.get("id")))
        rows.append({
            "id": node.get("id"), "kind": node.get("kind"), "label": _label(node), "x": node.get("x"), "y": node.get("y"),
            "prompt": str(payload.get("prompt") or payload.get("text") or "")[:120],
            "inputs": [str(edge.get("source")) for edge in edges if str(edge.get("target")) == str(node.get("id"))],
            "output": {"medium": output.get("medium"), "url": output.get("url")} if output else None,
            "last_run": (run or {}).get("status"),
            "track": node.get("track"),
        })
    return {
        "node_count": len(nodes), "edge_count": len(edges), "by_kind": by_kind, "nodes": rows, "truncated": len(nodes) > limit,
        "edges": [{"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target"), "kind": edge.get("kind"), "role": (edge.get("payload") or {}).get("role")} for edge in edges[:limit * 2]],
    }
