"""Running canvas nodes and committing their results: the part of the canvas that spends money and touches the project.

A run goes the way stage 5 does: every requested node is assessed together (video
through :func:`app.core.video_admission.assess_video_batch`, all or none), nothing
paid starts without ``confirm``, and what was admitted becomes a
:class:`~app.core.generation_queue.Queue` run by the generation pool, with a provider's
ceiling per bucket and queued items that can still be withdrawn. Results are written to the
append-only ``canvas_node_runs`` history and never into the canvas document: a job
finishing must not bump the revision a person is editing from.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from PIL import Image

from app import settings
from app.platform.billing_book import BillingRefused
from app.core import action_grammar, canvas_tools, canvas_versions, generation_queue, media_compositor, seam_check, studio_canvas, usage_ledger
from app.core.video_admission import WITHHELD, assess_video_batch
from app.repository.studio_repo import ConcurrencyError, StudioRepository
from app.service import canvas_tool_ops
from app.service import canvas_presence
from app.schema.studio import (
    CANVAS_MAIN_ID,
    ArtifactKind,
    CanvasNode,
    CanvasNodeRun,
    CanvasPutRequest,
    CanvasRecord,
)
from app.core import prompt_data


_WORDING_FILE = "studio_canvas_runs"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/studio_canvas_runs.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

logger = logging.getLogger("app.service.studio_canvas_runs")

LEASE_SECONDS = 90
_HEARTBEAT_SECONDS = 30
_MAX_PROMPT_CHARS = 8000
def frames_ratio_problem(first: Any, last: Any) -> str:
    """首尾帧比例不同，模型只能裁或拉，过渡一定跑形。只看本机的图：远程图要下载才知道，不在估价时做。"""
    paths = [media_compositor.local_media_path(url) for url in (first, last)]
    if not all(paths):
        return ""
    try:
        sizes = []
        for path in paths:
            with Image.open(path) as picture:
                sizes.append(picture.size)
    except OSError:
        return ""
    ratios = [width / max(1, height) for width, height in sizes]
    if abs(ratios[0] - ratios[1]) <= FRAME_RATIO_TOLERANCE:
        return ""
    return _text_of("frames_ratio_problem.text").format(sizes[0][0], sizes[0][1], sizes[1][0], sizes[1][1])


FRAME_RATIO_TOLERANCE = 0.02
CONTINUATION_LINE = _text_of("module.continuation_line")

# generation_queue.run bounds one run; two batches started side by side must still share a provider's ceiling.
_gates: dict[str, threading.BoundedSemaphore] = {}
_gates_lock = threading.Lock()


def _public_error(text: Any) -> str | None:
    """What a person reads on the node: the queue records "ValueError: reason", and only the reason means anything to them."""
    return re.sub(r"^[A-Z][A-Za-z0-9_]*: ", "", str(text)) if text else None


def _publish_run(owner_id: str, project_id: str, canvas_id: str, **event: Any) -> None:
    """Over the board's presence room, the route ``saved`` takes (StudioService._announce_saved); the hub is looked up when called."""
    hub = canvas_presence.hub
    if hub is not None:
        hub.run_changed(owner_id, project_id, canvas_id, **event)


def _seam_report(handoff: str, clip_url: str) -> dict[str, Any] | None:
    """How well the new clip opens on the frame it was handed; never the reason a paid clip is lost."""
    try:
        opening = media_compositor.extract_first_frame_b64(media_compositor.local_media_path(clip_url) or clip_url)
        return seam_check.compare(handoff, opening).as_dict() if opening else None
    except Exception as error:  # noqa: BLE001
        logger.warning("[Canvas] 接缝质检没能运行：%s", str(error)[:120])
        return None


def _camera_recipes() -> list[dict[str, str]]:
    from app.core.camera_recipes import recipe_catalog

    return recipe_catalog()


def _with_camera_move(prompt: str, params: Mapping[str, Any], model: str) -> str:
    """The prompt with a camera template written in, in the words this model's provider reads; what the person wrote stays the action."""
    category = str(params.get("cameraRecipe") or "")
    if not category:
        return prompt
    from app.core.camera_recipes import compose_recipe
    from app.core.video_references import normalize_video_provider

    return compose_recipe(
        category, str(params.get("cameraIntensity") or "medium"), subject_action=prompt, provider_family=normalize_video_provider(model).family,
    ).prompt_zh


def _gate(bucket: str) -> threading.BoundedSemaphore:
    with _gates_lock:
        gate = _gates.get(bucket)
        if gate is None:
            gate = _gates[bucket] = threading.BoundedSemaphore(generation_queue.ceiling_for(bucket))
        return gate


def _lease_until(now: datetime | None = None) -> str:
    return ((now or datetime.now(timezone.utc)) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def _document(canvas: CanvasRecord | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if canvas is None:
        return {}, []
    return ({node.id: node.model_dump(mode="json") for node in canvas.nodes}, [edge.model_dump(mode="json") for edge in canvas.edges])


def _run_maps(runs: Mapping[str, CanvasNodeRun]) -> dict[str, dict[str, Any]]:
    return {node_id: run.model_dump(mode="json") for node_id, run in runs.items()}


def _captures_reader(task: Mapping[str, Any]) -> Callable[[str], list[dict[str, Any]]]:
    from app.service import director_desk_service

    return lambda scene_id: director_desk_service.scene_view(task, scene_id)["captures"]


def _clean_size(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if text and len(text) <= 16 and all(ch.isdigit() or ch == "x" for ch in text) else None


def _prompt_of(node: Mapping[str, Any], parts: list[str]) -> str:
    own = str(studio_canvas.payload_of(node).get("prompt") or "").strip()
    return "\n".join(item for item in [own, *parts] if item)[:_MAX_PROMPT_CHARS]


def _reference_caps(node: Mapping[str, Any], config: Mapping[str, Any], drama: Any) -> Any:
    """How many references a video node may carry: what the model that will run it takes. ``None`` for other nodes."""
    if str(node.get("kind")) != "video_gen":
        return None
    from app.core.reference_limits import caps_of

    model = str(_params(node).get("model") or (config or {}).get("video_model") or "")
    probe = getattr(getattr(drama, "gateway", None), "video_reference_model", None)
    try:
        renders = probe(model) if callable(probe) else ""
    except (TypeError, ValueError):
        renders = ""
    return caps_of(renders if isinstance(renders, str) and renders.strip() else model)


def _params(node: Mapping[str, Any]) -> Mapping[str, Any]:
    params = studio_canvas.payload_of(node).get("params")
    return params if isinstance(params, Mapping) else {}


def _keep_media(url: Any, medium: str, tag: str) -> dict[str, Any]:
    """A provider's URL is signed and expires; history is only worth keeping if the file stays. Copy it under /media."""
    value = str(url or "").strip()
    if not value:
        raise RuntimeError(_text_of("_keep_media.text"))
    if media_compositor.local_media_path(value):
        return {"url": value}
    os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
    stem = f"canvas_{tag}_{uuid.uuid4().hex[:12]}"
    if value.startswith("data:"):
        header, _, encoded = value.partition(",")
        try:
            content = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise RuntimeError(_text_of("_keep_media.text.2")) from exc
        extension = "jpg" if "jpeg" in header else "webp" if "webp" in header else "png"
        name = f"{stem}.{extension}"
        with open(os.path.join(media_compositor.MEDIA_DIR, name), "wb") as handle:
            handle.write(content)
        return {"url": media_compositor.public_url(name)}
    extension = {"image": "png", "video": "mp4", "audio": "mp3"}.get(medium, "bin")
    name = f"{stem}.{extension}"
    destination = os.path.join(media_compositor.MEDIA_DIR, name)
    if media_compositor._download(value, destination):
        return {"url": media_compositor.public_url(name)}
    # The result exists and was paid for: keep the link and say it may not last, rather than lose it.
    logger.warning("[Canvas] 结果没能存到本地，保留供应商链接")
    return {"url": value, "remote": True}


class CanvasRunner:
    def __init__(
        self, repository: StudioRepository, *, spawn: Callable[[Callable[[], None]], None] | None = None,
        publish_run: Callable[..., None] | None = None,
    ):
        self.repository = repository
        self._spawn = spawn or self._spawn_thread
        self._publish_run = publish_run or _publish_run

    def _announce_run(
        self, project_id: str, owner_id: str, canvas_id: str, batch_id: str, status: str, *, run_id: str | None = None, node_id: str | None = None,
    ) -> None:
        """The board's open windows hear a run changed state (ids and status only) and read the outputs at once.

        The poll is still what they rely on, so this is never the reason a run fails or waits.
        """
        try:
            self._publish_run(owner_id, project_id, canvas_id, batch_id=batch_id, status=status, run_id=run_id, node_id=node_id)
        except Exception as error:  # noqa: BLE001
            logger.warning("[Canvas] run event not published (%s): %s", status, str(error)[:120])

    @staticmethod
    def _spawn_thread(work: Callable[[], None]) -> None:
        threading.Thread(target=usage_ledger.carrying_context(work), name="canvas-run", daemon=True).start()

    # ------------------------------------------------------------------ what can run

    @staticmethod
    def options(task: Mapping[str, Any]) -> dict[str, Any]:
        from app.core.model_gateway import ModelGateway
        from app.platform.runtime_models import runtime_model_registry
        from app.core.camera_recipes import recipe_catalog
        from app.core.screenwriting.durations import renderable_shot_durations

        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        video_model = ModelGateway.effective_video_model(str(config.get("video_model") or ""))
        elevenlabs = media_compositor._elevenlabs_available()
        ffmpeg = bool(media_compositor._ffmpeg())
        return {
            "models": {
                # The text model a text tool uses unless it picks its own: the project's, else the model centre's first.
                "text": str(config.get("llm_model") or "") or next((model for item in runtime_model_registry.list("text") for model in item.model_ids), ""),
                "image": str(config.get("image_model") or ""), "video": video_model,
                "audio": media_compositor.effective_audio_model(str(config.get("tts_model") or ""))[1],
            },
            "enabled": {
                category: list(dict.fromkeys(model_id for item in runtime_model_registry.list(category) for model_id in item.model_ids))
                for category in ("text", "image", "video", "audio")
            },
            "video_durations": renderable_shot_durations(video_model) if video_model else [],
            "versions": {"max": canvas_versions.MAX_VERSIONS, "kinds": sorted(canvas_versions.VERSIONED_KINDS)},
            "camera_recipes": recipe_catalog(),
            "tools": {
                "styles": [look.model_dump(mode="json") for look in canvas_tools.style_wall()],
                "engines": {
                    "image": bool(str(config.get("image_model") or "")) or bool(runtime_model_registry.list("image")),
                    "vision": runtime_model_registry.vision_model(str(config.get("llm_model") or "")) is not None,
                    "text": bool(str(config.get("llm_model") or "")) or bool(runtime_model_registry.list("text")),
                    "local": ffmpeg,
                    "voice": elevenlabs,
                },
            },
            "kinds": {
                "image_gen": {"runnable": True, "reason": ""},
                "video_gen": {"runnable": True, "reason": _text_of("options.kinds.video_gen.reason")},
                "audio_gen": {"runnable": True, "reason": "" if elevenlabs else _text_of("options.kinds.audio_gen.reason"),
                              "modes": {"speech": True, "music": elevenlabs, "sfx": elevenlabs}},
                "tool": {"runnable": True, "reason": ""},
                "video_compose": {"runnable": ffmpeg, "reason": _text_of("options.kinds.video_compose.reason") if ffmpeg else _text_of("options.kinds.video_compose.reason.2")},
            },
        }

    # ------------------------------------------------------------------ admission

    def assess(
        self, *, project_id: str, owner_id: str, canvas_id: str, node_ids: list[str], task: Mapping[str, Any], drama: Any,
        confirmed: list[dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        """Assess the nodes together, the way stage 5 assesses its shots: if one cannot run, none starts."""
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        nodes, edges = _document(canvas)
        runs = _run_maps(self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id))
        captures_of = _captures_reader(task)
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        missing = [item for item in node_ids if item not in nodes]
        if missing:
            raise ValueError(_text_of("assess.text").format('、'.join(missing)))
        ordered, _ = studio_canvas.batch_order(node_ids, edges)
        rows: dict[str, dict[str, Any]] = {}
        video_groups: dict[str, list[str]] = {}
        for node_id in ordered:
            node = nodes[node_id]
            kind = str(node.get("kind"))
            row: dict[str, Any] = {
                "node_id": node_id, "kind": kind, "label": studio_canvas._label(node), "medium": studio_canvas.medium_of(node),
                "model": "", "quote": "generate", "problems": [], "requested_seconds": 0, "scripted_seconds": 0, "paid": kind != "video_compose",
                # How many results this run asks for; the estimate below is for all of them.
                "versions": canvas_versions.versions_of(node),
                "estimate": {"priced": True, "cost": 0.0, "currency": None},
            }
            rows[node_id] = row
            if kind != "tool" and kind not in studio_canvas.RUNNABLE:
                row["problems"].append({"code": "not_runnable", "message": _text_of("assess.message"), "blocking": True})
                row["paid"] = False
                continue
            inputs = studio_canvas.resolve_inputs(node, nodes, edges, runs, captures_of, in_batch=node_ids, caps=_reference_caps(node, config, drama))
            for message in inputs.problems:
                row["problems"].append({"code": "input", "message": message, "blocking": True})
            prompt = _prompt_of(node, inputs.prompt_parts)
            if kind == "tool":
                self._assess_tool(row, node, config, prompt, inputs, drama)
            elif kind == "image_gen":
                self._assess_image(row, node, config, prompt, inputs, drama)
            elif kind == "video_gen":
                model = str(_params(node).get("model") or config.get("video_model") or "")
                from app.core.model_gateway import ModelGateway

                row["model"] = ModelGateway.effective_video_model(model)
                video_groups.setdefault(row["model"], []).append(node_id)
                recipe = str(_params(node).get("cameraRecipe") or "")
                if recipe and recipe not in {item["value"] for item in _camera_recipes()}:
                    row["problems"].append({"code": "camera_recipe", "message": _text_of("assess.message.2").format(recipe), "blocking": True})
                if not prompt:
                    row["problems"].append({"code": "no_prompt", "message": _text_of("assess.message.3"), "blocking": True})
                if not inputs.has_visual_reference() and not inputs.pending:
                    row["problems"].append({"code": "no_reference", "message": _text_of("assess.message.4"), "blocking": True})
                ratio_problem = frames_ratio_problem(inputs.first_frame, inputs.last_frame) if inputs.first_frame and inputs.last_frame else ""
                if ratio_problem:
                    row["problems"].append({"code": "frame_ratio", "message": ratio_problem, "blocking": True})
            elif kind == "audio_gen":
                self._assess_audio(row, node, config, prompt)
            elif kind == "video_compose":
                if not media_compositor._ffmpeg():
                    row["problems"].append({"code": "no_ffmpeg", "message": _text_of("assess.message.5"), "blocking": True})
                if not inputs.clips and not inputs.pending:
                    row["problems"].append({"code": "no_clips", "message": _text_of("assess.message.6"), "blocking": True})
        confirmations = self._assess_videos(rows, nodes, video_groups, config, confirmed, drama)
        return self._decide(rows, ordered, confirmations)

    @staticmethod
    def _assess_tool(row: dict[str, Any], node: Mapping[str, Any], config: Mapping[str, Any], prompt: str, inputs: studio_canvas.Inputs, drama: Any) -> None:
        """Who does this tool's work and whether it costs anything: a local tool is free, a model is paid and confirmed like any other."""
        from app.platform.runtime_models import runtime_model_registry

        problems = row["problems"]
        try:
            tool = canvas_tools.tool_of(node)
        except canvas_tools.CanvasToolError as error:
            problems.append({"code": "tool", "message": str(error), "blocking": True})
            row["paid"] = False
            return
        row["tool"] = tool.id
        pictures = len(inputs.ref_images) + (1 if inputs.first_frame else 0)
        waiting = len(inputs.pending)
        if pictures + waiting < tool.images:
            problems.append({"code": "no_image", "message": _text_of("_assess_tool.message").format(tool.label, tool.images, pictures), "blocking": True})
        if len(inputs.ref_videos) + waiting < tool.videos:
            problems.append({"code": "no_video", "message": _text_of("_assess_tool.message.2").format(tool.label), "blocking": True})
        if tool.needs_prompt and not prompt and not waiting:
            problems.append({"code": "no_prompt", "message": _text_of("_assess_tool.message.3"), "blocking": True})
        params = _params(node)
        if tool.id == "character_extract" and not pictures and not waiting:
            # Words only: the text model rewrites them, so it is asked for and priced like a text tool.
            if not prompt:
                problems.append({"code": "no_prompt", "message": _text_of("_assess_tool.no_character"), "blocking": True})
            row["model"] = str(params.get("model") or config.get("llm_model") or "")
            if not row["model"]:
                problems.append({"code": "model", "message": _text_of("_assess_tool.message.8"), "blocking": True})
            row["estimate"] = usage_ledger.estimate(row["model"], "text", {"input_chars": len(prompt)})
            return
        if tool.engine == "image":
            # What would not run anyway is said now, before anyone is asked to pay for it.
            if tool.id != "scene_360" and not waiting:
                try:
                    canvas_tools.image_prompt(tool, params, prompt)
                except canvas_tools.CanvasToolError as error:
                    problems.append({"code": "params", "message": str(error), "blocking": True})
            CanvasRunner._assess_model_image(row, params, config, [*inputs.ref_images, *([inputs.first_frame] if inputs.first_frame else [])], drama)
            return
        if tool.id == "voice_isolate":
            row["model"] = "elevenlabs/audio-isolation"
            if not media_compositor._elevenlabs_available():
                problems.append({"code": "no_provider", "message": _text_of("_assess_tool.message.4"), "blocking": True})
            if not media_compositor._ffmpeg():
                problems.append({"code": "no_ffmpeg", "message": _text_of("_assess_tool.message.5"), "blocking": True})
            row["estimate"] = usage_ledger.estimate("elevenlabs/audio-isolation", "audio", {"files": 1})
            return
        if tool.engine == "vision":
            choice = runtime_model_registry.vision_model(str(params.get("model") or config.get("llm_model") or ""))
            if choice is None:
                problems.append({"code": "no_vision", "message": _text_of("_assess_tool.message.6"), "blocking": True})
            row["model"] = choice[1] if choice else ""
            row["estimate"] = usage_ledger.estimate(row["model"], "text", {"images": 1})
            if tool.id == "shot_analysis" and not media_compositor._ffmpeg():
                problems.append({"code": "no_ffmpeg", "message": _text_of("_assess_tool.message.7"), "blocking": True})
            return
        if tool.engine == "text":
            row["model"] = str(params.get("model") or config.get("llm_model") or "")
            if not row["model"]:
                problems.append({"code": "model", "message": _text_of("_assess_tool.message.8"), "blocking": True})
            row["estimate"] = usage_ledger.estimate(row["model"], "text", {"input_chars": len(prompt)})
            return
        row["paid"] = False
        row["model"] = "local"
        if tool.id == "reference_remake" and not waiting:
            try:
                canvas_tools.remake_prompt(params, prompt)
            except canvas_tools.CanvasToolError as error:
                problems.append({"code": "params", "message": str(error), "blocking": True})
        if tool.videos and not media_compositor._ffmpeg():
            problems.append({"code": "no_ffmpeg", "message": _text_of("_assess_tool.message.9"), "blocking": True})

    @staticmethod
    def _assess_image(row: dict[str, Any], node: Mapping[str, Any], config: Mapping[str, Any], prompt: str, inputs: studio_canvas.Inputs, drama: Any) -> None:
        if not prompt:
            row["problems"].append({"code": "no_prompt", "message": _text_of("_assess_image.message"), "blocking": True})
        CanvasRunner._assess_model_image(row, _params(node), config, [*inputs.ref_images, *([inputs.first_frame] if inputs.first_frame else [])], drama)

    @staticmethod
    def _assess_model_image(row: dict[str, Any], params: Mapping[str, Any], config: Mapping[str, Any], references: list[str], drama: Any) -> None:
        model = str(params.get("model") or config.get("image_model") or "")
        row["model"] = model
        try:
            drama.gateway.validate_image_request(model, references, require_reference_support=bool(references))
        except ValueError as exc:
            row["problems"].append({"code": "model", "message": str(exc), "blocking": True})
        row["estimate"] = usage_ledger.estimate(model, "image", {"images": int(row.get("versions") or 1), "resolution": _clean_size(params.get("size")) or ""})

    @staticmethod
    def _assess_audio(row: dict[str, Any], node: Mapping[str, Any], config: Mapping[str, Any], prompt: str) -> None:
        params = _params(node)
        mode = str(params.get("mode") or "speech")
        provider, model = media_compositor.effective_audio_model(str(params.get("model") or config.get("tts_model") or ""))
        row["model"] = model or provider
        if mode not in {"speech", "music", "sfx"}:
            row["problems"].append({"code": "mode", "message": _text_of("_assess_audio.message").format(mode), "blocking": True})
            return
        if not prompt:
            row["problems"].append({"code": "no_prompt", "message": _text_of("_assess_audio.message.2"), "blocking": True})
        if mode != "speech" and not media_compositor._elevenlabs_available():
            row["problems"].append({"code": "no_provider", "message": _text_of("_assess_audio.message.3"), "blocking": True})
        if mode == "speech":
            row["estimate"] = usage_ledger.estimate(model, "audio", {"characters": len(prompt)})
            return
        # Music and effects are billed by the second of sound made, by their own models, not the voice's per-character price;
        # the lengths are the ones _synthesize asks for.
        priced = prompt_data.value(_WORDING_FILE, "audio_pricing")[mode]
        try:
            seconds = float(params.get("durationSeconds") or priced["default_seconds"])
        except (TypeError, ValueError):
            seconds = float(priced["default_seconds"])
        row["model"] = priced["model"]
        row["requested_seconds"] = int(round(seconds))
        row["estimate"] = usage_ledger.estimate(priced["model"], "audio", {"seconds": seconds})

    @staticmethod
    def _assess_videos(
        rows: dict[str, dict[str, Any]], nodes: Mapping[str, Mapping[str, Any]], groups: Mapping[str, list[str]],
        config: Mapping[str, Any], confirmed: list[dict[str, int]] | None, drama: Any,
    ) -> list[dict[str, Any]]:
        from app.core.model_gateway import ModelGateway

        confirmations: dict[tuple[int, int], dict[str, Any]] = {}
        for model, members in groups.items():
            # The gate takes a project's shots; a canvas's video nodes are shots with no script behind them.
            # Slicing is about storyboard beats, so it is off: one node is one request.
            shots = [
                {"shot_id": index, "scene_id": "", "visual": {"duration_seconds": int(_params(nodes[node_id]).get("durationSeconds") or 5), "candidates": canvas_versions.versions_of(nodes[node_id])}}
                for index, node_id in enumerate(members, start=1)
            ]
            probe = getattr(drama, "_video_clip_ceiling", None)
            admission = assess_video_batch(
                {"config": {"video_model": model, "video_granularity": "shot", "confirmed_request_durations": config.get("confirmed_request_durations") or []},
                 "assets": {"4": shots}},
                provider_ready=ModelGateway.video_family_ready, provider_problem=ModelGateway.video_model_problem,
                confirmed_request_durations=confirmed or None,
                clip_ceiling=probe(model) if callable(probe) else None,
            )
            for node_id, shot in zip(members, admission.shots):
                row = rows[node_id]
                row["requested_seconds"] = shot.requested_seconds
                row["scripted_seconds"] = shot.scripted_seconds
                row["estimate"] = dict(shot.estimate) if shot.estimate else row["estimate"]
                row["problems"].extend(problem.as_dict() for problem in shot.problems if problem.code != WITHHELD)
            for item in admission.confirmations:
                key = (int(item["scripted_seconds"]), int(item["requested_seconds"]))
                merged = confirmations.setdefault(key, {**item, "shot_count": 0, "shot_ids": [], "node_ids": []})
                merged["shot_count"] += int(item["shot_count"])
                merged["node_ids"].extend(members[int(shot_id) - 1] for shot_id in item["shot_ids"])
        return [confirmations[key] for key in sorted(confirmations)]

    @staticmethod
    def _decide(rows: Mapping[str, dict[str, Any]], ordered: list[str], confirmations: list[dict[str, Any]]) -> dict[str, Any]:
        blocked = [node_id for node_id in ordered if any(problem.get("blocking") for problem in rows[node_id]["problems"])]
        totals: dict[str, float] = {}
        unpriced = 0
        paid = 0
        for node_id in ordered:
            row = rows[node_id]
            if node_id in blocked:
                row["quote"] = "blocked"
                continue
            if blocked:
                row["problems"].append({"code": WITHHELD, "message": _text_of("_decide.message"), "blocking": False})
            if not row["paid"]:
                continue
            paid += 1
            estimate = row["estimate"]
            if estimate.get("priced") and estimate.get("currency"):
                currency = str(estimate["currency"])
                totals[currency] = round(totals.get(currency, 0.0) + float(estimate.get("cost") or 0.0), 6)
            else:
                unpriced += 1
        decision = "blocked" if blocked else "confirmation_required" if confirmations else "admitted"
        return {
            "decision": decision,
            "nodes": [rows[node_id] for node_id in ordered],
            "confirmations": confirmations,
            # Currencies are never added together; an unpriced item is counted, not guessed.
            "estimate": {"items": len(ordered), "paid_items": paid, "unpriced_items": unpriced,
                         "totals": [{"currency": currency, "cost": cost} for currency, cost in sorted(totals.items())]},
        }

    # ------------------------------------------------------------------ start

    def start(
        self, *, project_id: str, owner_id: str, canvas_id: str, node_ids: list[str], expected_version: int, operation_id: str, confirm: bool,
        task: Mapping[str, Any], task_id: str, drama: Any, confirmed: list[dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        existing = self.repository.find_canvas_batch(project_id, operation_id)
        if existing:
            # A retried request (double click, flaky network) is the same order, not a second bill.
            runs = [run for run in self.repository.list_canvas_runs(project_id, owner_id, canvas_id=str(existing["canvas_id"])) if run.batch_id == existing["id"]]
            return {"status": "started", "reused": True, "batch_id": existing["id"], "runs": [run.model_dump(mode="json") for run in runs]}
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        latest = canvas.version if canvas else 0
        if latest != expected_version:
            raise ConcurrencyError(f"canvas version conflict: expected {expected_version}, latest is {latest}")
        assessment = self.assess(project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, task=task, drama=drama, confirmed=confirmed)
        if assessment["decision"] == "blocked":
            return {"status": "blocked", "assessment": assessment}
        if assessment["decision"] == "confirmation_required" or (assessment["estimate"]["paid_items"] and not confirm):
            return {"status": "needs_confirmation", "assessment": assessment}

        nodes, edges = _document(canvas)
        rows = {row["node_id"]: row for row in assessment["nodes"]}
        order, upstream = studio_canvas.batch_order(node_ids, edges)
        entries = []
        for node_id in order:
            node, row = nodes[node_id], rows[node_id]
            versions = int(row.get("versions") or 1)
            # Each result asked for is a run of its own: its own place in the history, its own bill.
            for index in range(1, versions + 1):
                entries.append({
                    "node_id": node_id, "medium": row["medium"], "model": row["model"],
                    "request": {"prompt": str(studio_canvas.payload_of(node).get("prompt") or "")[:_MAX_PROMPT_CHARS], "params": dict(_params(node)),
                                "requested_seconds": row["requested_seconds"], "estimate": canvas_versions.share_of(row["estimate"], versions),
                                "canvas_version": latest, **({"version": index, "versions": versions} if versions > 1 else {})},
                })
        batch_id, records = self.repository.create_canvas_batch(
            project_id, owner_id, canvas_id=canvas_id, task_id=task_id, operation_id=operation_id, entries=entries, lease_expires_at=_lease_until(),
        )
        for record in records:
            self._announce_run(project_id, owner_id, canvas_id, batch_id, record.status, run_id=record.id, node_id=record.node_id)
        self._spawn(lambda: self._execute(
            project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, task_id=task_id, batch_id=batch_id, records=records,
            nodes=nodes, edges=edges, upstream=upstream, rows=rows, drama=drama,
        ))
        return {"status": "started", "reused": False, "batch_id": batch_id, "runs": [record.model_dump(mode="json") for record in records], "assessment": assessment}

    # ------------------------------------------------------------------ execute

    def _execute(
        self, *, project_id: str, owner_id: str, canvas_id: str, task_id: str, batch_id: str, records: list[CanvasNodeRun],
        nodes: Mapping[str, dict[str, Any]], edges: list[dict[str, Any]], upstream: Mapping[str, list[str]], rows: Mapping[str, dict[str, Any]], drama: Any,
    ) -> None:
        runs_of_node: dict[str, list[CanvasNodeRun]] = {}
        for record in records:
            runs_of_node.setdefault(record.node_id, []).append(record)
        node_of_run = {record.id: record.node_id for record in records}
        queue = generation_queue.Queue()
        for record in records:
            row = rows[record.node_id]
            queue.add(generation_queue.Item(
                key=record.id,
                label=canvas_versions.label_of(str(row.get("label") or record.node_id), int(record.request.get("version") or 1), len(runs_of_node[record.node_id])),
                family=self._family_of(record, row), medium=record.medium,
                # A node waits for every result of the node it reads from.
                depends_on=[run.id for dep in upstream.get(record.node_id, []) for run in runs_of_node.get(dep, [])],
                meta={"node_id": record.node_id, "seconds": row.get("requested_seconds")},
            ))

        synced: dict[str, str] = {}
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(_HEARTBEAT_SECONDS):
                self.repository.renew_canvas_batch_lease(project_id, batch_id, _lease_until())

        threading.Thread(target=heartbeat, name="canvas-run-lease", daemon=True).start()

        def holder() -> dict[str, Any]:
            batch = self.repository.get_canvas_batch(project_id, batch_id) or {}
            return {"assets": {generation_queue.QUEUE_KEY: json.loads(batch.get("snapshot") or "{}")}}

        def persist(snapshot: dict[str, Any]) -> None:
            with self.repository.canvas_write_lock():
                # store_snapshot keeps cancel requests recorded while the run was going.
                held = holder()
                generation_queue.store_snapshot(held, snapshot)
                self.repository.save_canvas_batch_snapshot(project_id, batch_id, held["assets"][generation_queue.QUEUE_KEY], lease_expires_at=_lease_until())
            for item in snapshot.get("items") or []:
                key, status = str(item.get("key")), str(item.get("status"))
                if synced.get(key) != status:
                    synced[key] = status
                    self.repository.update_canvas_run(project_id, key, status=status, error=_public_error(item.get("error") or item.get("reason")))
                    # Waiting was said when the batch was written (start); every later state is said here, once it is on record.
                    if status != generation_queue.QUEUED and key in node_of_run:
                        self._announce_run(project_id, owner_id, canvas_id, batch_id, status, run_id=key, node_id=node_of_run[key])

        def withdrawn() -> set[str]:
            return generation_queue.withdrawn_in(holder())

        def work(item: generation_queue.Item) -> dict[str, Any]:
            with _gate(item.bucket):
                record = next(entry for entry in records if entry.id == item.key)
                return self._run_one(project_id, owner_id, canvas_id, task_id, record, nodes, edges, upstream, rows[record.node_id], drama)

        try:
            with usage_ledger.bind_task(task_id, "canvas"):
                try:
                    generation_queue.run(queue, work, persist=persist, withdrawn=withdrawn, run_id=batch_id)
                except generation_queue.RunCancelled:
                    # What finished is kept, what was withdrawn says so; persist already wrote both.
                    pass
        except (Exception, BillingRefused):  # noqa: BLE001 - a broken run must end visibly on every node, not keep spinning
            logger.exception("[Canvas] 批次 %s 中断", batch_id)
            for item in queue.items():
                if item.status not in generation_queue.FINAL:
                    self.repository.update_canvas_run(project_id, item.key, status="failed", error=_text_of("_execute.error"))
                    self._announce_run(project_id, owner_id, canvas_id, batch_id, "failed", run_id=item.key, node_id=node_of_run.get(item.key))
        finally:
            stop.set()
            self._announce_run(project_id, owner_id, canvas_id, batch_id, "finished")

    @staticmethod
    def _family_of(record: CanvasNodeRun, row: Mapping[str, Any]) -> str:
        if row.get("kind") == "video_compose" or record.model == "local":
            return "local"
        if row.get("kind") == "tool":
            return (record.model or "tool").split("/")[0]
        if record.medium == "video":
            from app.core.video_references import normalize_video_provider

            return normalize_video_provider(record.model).family
        return (record.model or record.medium).split("/")[0]

    def _run_one(
        self, project_id: str, owner_id: str, canvas_id: str, task_id: str, record: CanvasNodeRun, nodes: Mapping[str, dict[str, Any]],
        edges: list[dict[str, Any]], upstream: Mapping[str, list[str]], row: Mapping[str, Any], drama: Any,
    ) -> dict[str, Any]:
        node = nodes[record.node_id]
        task = drama.repo.get_task(task_id) or {}
        # Upstream results are read now: a node in the same batch has only just finished.
        runs = _run_maps(self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id))
        inputs = studio_canvas.resolve_inputs(
            node, nodes, edges, runs, _captures_reader(task), caps=_reference_caps(node, task.get("config") or {}, drama),
        )
        if inputs.problems:
            raise ValueError("；".join(inputs.problems))
        prompt = _prompt_of(node, inputs.prompt_parts)
        params = _params(node)
        kind = str(node.get("kind"))
        tag = record.id[-8:]
        seam: dict[str, Any] | None = None
        if kind == "tool":
            return self._finish_tool(project_id, record, node, inputs, params, prompt, tag, task, drama)
        if kind == "image_gen":
            references = [*([inputs.first_frame] if inputs.first_frame else []), *inputs.ref_images]
            url, _ = drama.gateway.generate_image(record.model, prompt, ref_images=references or None, size=_clean_size(params.get("size")), require_reference_support=bool(references))
        elif kind == "video_gen":
            style_pack = str((task.get("config") or {}).get("style_pack") or "") or None
            first_frame = inputs.first_frame
            if inputs.continue_from:
                # The seam of one continuous shot: the last frame is read now, from the clip as it is, and refused rather than guessed.
                first_frame = media_compositor.extract_last_frame_b64(media_compositor.local_media_path(inputs.continue_from) or inputs.continue_from)
                if not first_frame:
                    raise RuntimeError(_text_of("_run_one.text"))
                # The picture carries the pose, light and tone across; the words say what that pose is and what comes next.
                prompt = f"{CONTINUATION_LINE}\n{action_grammar.continuation_text(inputs.continue_from_prompt, prompt)}"
            url = drama.gateway.generate_video(
                record.model, first_frame, _with_camera_move(prompt, params, record.model), None, inputs.last_frame, inputs.ref_images or None, inputs.ref_videos or None, inputs.ref_audios or None,
                duration=int(row.get("requested_seconds") or 5), style_pack=style_pack,
            )
            if not url:
                probe = getattr(drama.gateway, "last_video_failure", None)
                raise RuntimeError((probe() if callable(probe) else "") or _text_of("_run_one.text.2"))
            if inputs.continue_from:
                seam = _seam_report(first_frame, url)
        elif kind == "audio_gen":
            url = self._synthesize(params, record.model, prompt, tag, str((task.get("config") or {}).get("tts_model") or ""), task=task)
        elif kind == "video_compose":
            url = self._compose(inputs, tag, node=node)
        else:
            raise ValueError(_text_of("_run_one.text.3"))
        kept = _keep_media(url, record.medium, tag)
        output = {
            "medium": record.medium, **kept, **({"seam": seam} if seam else {}),
            "provenance": {"origin": "canvas_run", "run_id": record.id, "node_id": record.node_id, "model": record.model, "inputs": inputs.sources},
        }
        self.repository.update_canvas_run(project_id, record.id, output=output)
        return output

    def _finish_tool(
        self, project_id: str, record: CanvasNodeRun, node: Mapping[str, Any], inputs: studio_canvas.Inputs, params: Mapping[str, Any],
        prompt: str, tag: str, task: Mapping[str, Any], drama: Any,
    ) -> dict[str, Any]:
        tool = canvas_tools.tool_of(node)
        made = canvas_tool_ops.run_tool(tool, inputs=inputs, params=params, prompt=prompt, model=record.model, tag=tag, task=task, drama=drama)
        held = {"url": "", "text": made["text"]} if "text" in made else _keep_media(made.get("url"), tool.output, tag)
        output = {
            "medium": tool.output, **held, **{key: made[key] for key in ("beats", "shots", "cast", "asked", "line_order", "cuts", "html", "zip", "sprite") if key in made},
            "provenance": {"origin": "canvas_run", "run_id": record.id, "node_id": record.node_id, "model": record.model, "tool": tool.id, "inputs": inputs.sources},
        }
        self.repository.update_canvas_run(project_id, record.id, output=output)
        return output

    @staticmethod
    def _synthesize(params: Mapping[str, Any], model: str, text: str, tag: str, project_tts: str, *, task: Mapping[str, Any] | None = None) -> str:
        mode = str(params.get("mode") or "speech")
        # 收费的服务在 providers 里记账；本地 TTS 不收费。
        if mode == "music":
            url, _path = media_compositor.synthesize_elevenlabs_music(text, float(params.get("durationSeconds") or prompt_data.value(_WORDING_FILE, "audio_pricing")["music"]["default_seconds"]), tag=f"canvas_bgm_{tag}")
        elif mode == "sfx":
            url, _path = media_compositor.synthesize_elevenlabs_sfx(text, float(params.get("durationSeconds") or prompt_data.value(_WORDING_FILE, "audio_pricing")["sfx"]["default_seconds"]), tag=f"canvas_sfx_{tag}")
        elif params.get("castLines") and task is not None:
            # Lines written as 「名字：台词」, voiced the way stage 6 voices a shot: each speaker in the project's voice for them.
            from app.service.canvas_film_voice import cast_segments

            segments = cast_segments(text, task)
            if not segments:
                raise RuntimeError(_text_of("_synthesize.text"))
            url, _path = media_compositor.synthesize_preferred_dialogue_track(segments, tts_model=str(params.get("model") or project_tts), tag=f"canvas_{tag}")
        else:
            gender = "male" if params.get("gender") == "male" else "female"
            url, _path = media_compositor.synthesize_preferred_dialogue_track(
                [(text, gender, str(params.get("emotion") or "neutral"))], tts_model=str(params.get("model") or project_tts), tag=f"canvas_{tag}",
            )
        if not url:
            raise RuntimeError(_text_of("_synthesize.text"))
        return url

    @staticmethod
    def _compose(inputs: studio_canvas.Inputs, tag: str, *, node: Mapping[str, Any] | None = None) -> str:
        prefix = settings.MEDIA_PREFIX
        clips = [media_compositor.public_url(url[len(prefix):]) if url.startswith(prefix) else url for url in inputs.clips]
        soundtrack = media_compositor.local_media_path(inputs.soundtrack) if inputs.soundtrack else None
        # 原声优先：片段自己带着声音的（视频模型出的对白与环境声）合成时留着，不再一律去掉。
        own_sound = [media_compositor.clip_has_sound(url) is True for url in clips]
        # 一键成片(app/core/canvas_film.py)记下了哪段配音属于哪一镜、哪一路是配乐：配音逐镜对齐，只垫在没出声的片段下面。
        from app.service.canvas_film_voice import sound_tracks

        voices, music = sound_tracks(node, inputs)
        if voices is not None:
            soundtrack = None
        url = media_compositor.compose_film(
            clips, [""] * len(clips), soundtrack, tag=f"canvas_{tag}", title=None, bgm=False, native_audio=own_sound,
            shot_voices=voices, bgm_path=music,
        )
        if not url:
            raise RuntimeError(_text_of("_compose.text"))
        return url

    def cancel(self, project_id: str, batch_id: str, key: str | None) -> dict[str, Any]:
        with self.repository.canvas_write_lock():
            batch = self.repository.get_canvas_batch(project_id, batch_id)
            if not batch:
                raise PermissionError("canvas batch not found")
            held = {"assets": {generation_queue.QUEUE_KEY: json.loads(batch.get("snapshot") or "{}")}}
            try:
                data = generation_queue.request_cancel(held, key) if key else generation_queue.request_cancel_queued(held)
            except generation_queue.CancelError as exc:
                raise ValueError(str(exc)) from exc
            self.repository.save_canvas_batch_snapshot(project_id, batch_id, dict(data))
            return dict(data)

    # ------------------------------------------------------------------ commit back to the project

    def preview_commit(self, *, project_id: str, owner_id: str, canvas_id: str, node_ids: list[str], task: Mapping[str, Any] | None) -> dict[str, Any]:
        """What a commit would do, per node, without doing it: how many shots each result lands on, and what gets skipped."""
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        nodes, edges = _document(canvas)
        runs = _run_maps(self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id))
        shots = [shot for shot in ((task or {}).get("assets") or {}).get("4") or [] if isinstance(shot, Mapping)]
        rows = []
        impacted: set[tuple[str, int]] = set()
        counts = {"ready": 0, "no_provenance": 0, "already": 0, "no_result": 0}
        for node_id in dict.fromkeys(node_ids):
            node = nodes.get(node_id)
            if node is None:
                raise ValueError(_text_of("preview_commit.text").format(node_id))
            row = self._commit_row(node, nodes, edges, runs, shots)
            rows.append(row)
            counts[row["state"]] += 1
            if row["state"] == "ready":
                impacted.update((shot["scene_id"], shot["shot_id"]) for shot in row["impact"]["shots"])
        return {"version": canvas.version if canvas else 0, "nodes": rows, "counts": counts, "impacted_shots": len(impacted)}

    @staticmethod
    def _commit_row(
        node: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]], edges: list[dict[str, Any]], runs: Mapping[str, Mapping[str, Any]], shots: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        node_id = str(node.get("id"))
        run = runs.get(node_id)
        source = studio_canvas.commit_source(node, run)
        output = (source or {}).get("output") if source else None
        medium = str((output or {}).get("medium") or "") or None
        impacted = studio_canvas.bound_shots(node, nodes, edges, shots)
        row: dict[str, Any] = {
            "node_id": node_id, "label": studio_canvas._label(node), "kind": node.get("kind"), "medium": medium,
            "url": (output or {}).get("url"), "target_kind": studio_canvas.commit_target_kind(node, medium),
            "impact": {"count": len(impacted), "shots": impacted}, "state": "ready", "reason": "",
            "applies_to_shots": bool(impacted and studio_canvas.slot_for(medium)),
        }
        held = studio_canvas.payload_of(node).get("output")
        has_result = bool(run and run.get("output")) or node.get("artifact_id") or (isinstance(held, Mapping) and held.get("url"))
        if medium == "text":
            row["state"] = "no_result"
            row["reason"] = _text_of("_commit_row.text")
            row["impact"] = {"count": 0, "shots": []}
            return row
        if source is None:
            row["state"] = "no_provenance" if has_result else "no_result"
            row["reason"] = _text_of("_commit_row.text.2") if has_result else _text_of("_commit_row.text.3")
            row["impact"] = {"count": 0, "shots": []}
            return row
        committed = studio_canvas.payload_of(node).get("committed")
        marker = source.get("run_id") or source.get("artifact_id") or (output or {}).get("url")
        if isinstance(committed, Mapping) and committed.get("marker") == marker:
            row["state"] = "already"
            row["reason"] = _text_of("_commit_row.text.4")
        return row

    def commit(
        self, *, project_id: str, owner_id: str, canvas_id: str, node_ids: list[str], expected_version: int, task: Mapping[str, Any] | None, task_id: str | None, drama: Any,
    ) -> dict[str, Any]:
        """Commit each ready node; one version of the canvas records all of them, and a node that failed can simply be sent again."""
        with self.repository.canvas_write_lock():
            canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
            latest = canvas.version if canvas else 0
            if latest != expected_version:
                raise ConcurrencyError(f"canvas version conflict: expected {expected_version}, latest is {latest}")
            preview = self.preview_commit(project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, task=task)
            nodes, edges = _document(canvas)
            runs = _run_maps(self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id))
            results = []
            updates: dict[str, dict[str, Any]] = {}
            for row in preview["nodes"]:
                node_id = row["node_id"]
                if row["state"] != "ready":
                    results.append({"node_id": node_id, "label": row["label"], "status": "skipped", "state": row["state"], "reason": row["reason"]})
                    continue
                try:
                    update, applied = self._commit_one(project_id, owner_id, nodes[node_id], nodes, edges, runs, row, task_id, drama)
                except Exception as exc:  # noqa: BLE001 - one node's failure is reported for retry; the others still land
                    logger.warning("[Canvas] 提交节点 %s 失败：%s", node_id, str(exc)[:200])
                    results.append({"node_id": node_id, "label": row["label"], "status": "failed", "reason": str(exc)[:300] or _text_of("commit.reason")})
                    continue
                updates[node_id] = update
                results.append({"node_id": node_id, "label": row["label"], "status": "committed", "artifact_id": update["artifact_id"], "applied_shots": applied})
            record = canvas
            if updates and canvas is not None:
                changed: list[CanvasNode] = []
                for node in canvas.nodes:
                    extra = updates.get(node.id)
                    if extra:
                        node = node.model_copy(update={
                            "track": "mainline", "artifact_id": extra["artifact_id"],
                            "payload": {**node.payload, "committed": extra["committed"]},
                        })
                    changed.append(node)
                record = self.repository.put_canvas(
                    project_id, owner_id, CanvasPutRequest(expected_version=canvas.version, nodes=changed, edges=canvas.edges), canvas_id=canvas_id,
                )
        return {
            "version": record.version if record else 0,
            "canvas": record.model_dump(mode="json") if record else None,
            "results": results,
            "counts": {
                "committed": sum(1 for item in results if item["status"] == "committed"),
                "failed": sum(1 for item in results if item["status"] == "failed"),
                "skipped": sum(1 for item in results if item["status"] == "skipped"),
                "no_provenance": sum(1 for item in results if item.get("state") == "no_provenance"),
            },
        }

    def _commit_one(
        self, project_id: str, owner_id: str, node: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]], edges: list[dict[str, Any]],
        runs: Mapping[str, Mapping[str, Any]], row: Mapping[str, Any], task_id: str | None, drama: Any,
    ) -> tuple[dict[str, Any], int]:
        source = studio_canvas.commit_source(node, runs.get(str(node.get("id")))) or {}
        artifact_id = source.get("artifact_id")
        marker = source.get("run_id") or artifact_id or (source.get("output") or {}).get("url")
        if not artifact_id:
            kind = row.get("target_kind")
            if not kind:
                raise ValueError(_text_of("_commit_one.text"))
            artifact_kind = ArtifactKind(kind)
            parents = [
                str(nodes[str(edge["source"])].get("artifact_id"))
                for edge in edges
                if str(edge.get("target")) == str(node.get("id")) and str(edge.get("source")) in nodes and nodes[str(edge["source"])].get("artifact_id")
            ]
            artifact = self.repository.put_artifact(
                project_id, owner_id, artifact_kind,
                {"url": row.get("url"), "medium": row.get("medium"), "source": source, "canvas_node_id": node.get("id"), "shots": row["impact"]["shots"]},
                parents=parents, expected_latest_version=self.repository.latest_artifact_version(project_id, owner_id, artifact_kind), status="review",
            )
            artifact_id = artifact.id
        applied = 0
        if row.get("applies_to_shots") and row.get("url") and task_id and drama is not None:
            applied = self._apply_to_shots(drama, task_id, row)
        return {"artifact_id": artifact_id, "committed": {"marker": marker, "artifact_id": artifact_id, "shots": row["impact"]["count"]}}, applied

    @staticmethod
    def _apply_to_shots(drama: Any, task_id: str, row: Mapping[str, Any]) -> int:
        """Write the result into the slots stage 5 reads, at the front; the same two the desk's「应用至分镜」writes."""
        from app.core.reference_limits import MAX_REFERENCE_VIDEOS, MAX_SEQUENCE_IMAGES

        medium = str(row.get("medium"))
        slot = studio_canvas.slot_for(medium)
        limit = MAX_REFERENCE_VIDEOS if medium == "video" else MAX_SEQUENCE_IMAGES
        if medium == "video":
            # As many reference clips as the project's rendering model takes (Seedance 2.5: ten).
            current = drama.repo.get_task(task_id) or {}
            caps = _reference_caps({"kind": "video_gen"}, current.get("config") or {}, drama)
            limit = caps.videos if caps else limit
        wanted = {(shot["scene_id"], int(shot["shot_id"])) for shot in row["impact"]["shots"]}
        url = str(row.get("url"))

        def mutate(task: dict[str, Any]) -> int:
            count = 0
            for shot in (task.get("assets") or {}).get("4") or []:
                if not isinstance(shot, dict):
                    continue
                try:
                    key = (str(shot.get("scene_id") or ""), int(shot.get("shot_id") or 0))
                except (TypeError, ValueError):
                    continue
                if key in wanted:
                    current = [item for item in (shot.get(slot) if isinstance(shot.get(slot), list) else []) if item != url]
                    shot[slot] = [url, *current][:limit]
                    if medium == "video":
                        from app.core import canvas_shot_candidates

                        canvas_shot_candidates.offer(task.get("assets") or {}, shot, url)
                    count += 1
            return count

        applied = drama.repo.mutate_task(task_id, mutate)
        if applied is None:
            raise RuntimeError(_text_of("_apply_to_shots.text"))
        return int(applied)


__all__ = ["CANVAS_MAIN_ID", "CanvasRunner", "LEASE_SECONDS"]
