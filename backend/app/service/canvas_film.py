"""The canvas's "one-click film": see what it would take, then put the film's nodes in place for one run.

The plan is :mod:`app.core.canvas_film`; this module reads the task, the canvas and the results the
canvas has, decides which clips need a voice (the project's native-sound rule), and writes the edit as
one canvas version. Running is the canvas's usual quoted run of the node ids it hands back.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.core import canvas_film, media_compositor, prompt_data, studio_canvas
from app.core.video_references import uses_native_soundtrack
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import CanvasPutRequest


class CanvasFilmRequest(BaseModel):
    """Which clips (none: the storyboard's, or all), whether to voice silent lines and add music; the version for a build."""

    node_ids: list[str] = Field(default_factory=list, max_length=500)
    voices: bool = True
    music: bool = False
    music_prompt: str = Field("", max_length=400)
    expected_version: int | None = Field(None, ge=0)


def _state(studio: Any, project_id: str, owner_id: str, canvas_id: str, drama: Any, user: Mapping[str, Any] | None):
    _, task = studio._canvas_task(project_id, owner_id, drama, user)  # noqa: SLF001 - the ownership check every canvas run uses
    canvas = studio.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
    document, version = (canvas.model_dump(mode="json"), canvas.version) if canvas else ({"nodes": [], "edges": []}, 0)
    runs = studio.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id)
    return task, document, version, runs


def _judges(task: Mapping[str, Any], document: Mapping[str, Any], runs: Mapping[str, Any]):
    """``has_output(node id)`` and ``needs_voice(clip)`` for this canvas as it is now."""
    from app.core.model_gateway import ModelGateway

    by_id = {str(node.get("id")): node for node in document.get("nodes") or [] if isinstance(node, Mapping)}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}

    def result(node_id: str) -> Mapping[str, Any] | None:
        node = by_id.get(node_id)
        if node is not None and node.get("kind") in studio_canvas.HOLDS_MEDIA:
            output = (node.get("payload") or {}).get("output")
            return output if isinstance(output, Mapping) and output.get("url") else None
        run = runs.get(node_id)
        output = getattr(run, "output", None) if run is not None else None
        return output if isinstance(output, Mapping) and (output.get("url") or output.get("text")) else None

    def has_output(node_id: str) -> bool:
        return result(node_id) is not None

    def needs_voice(clip: Mapping[str, Any]) -> bool:
        made = result(str(clip.get("id")))
        if made and made.get("url"):
            sound = media_compositor.clip_has_sound(str(made["url"]))
            if sound is not None:
                return not sound
        params = (clip.get("payload") or {}).get("params") or {}
        model = ModelGateway.effective_video_model(str(params.get("model") or config.get("video_model") or ""))
        # A clip still to be made: voiced only when its model makes no sound of its own.
        return not uses_native_soundtrack({**config, "video_model": model})

    return has_output, needs_voice


def _plan(task, document, runs, request: CanvasFilmRequest) -> dict[str, Any]:
    if request.music and not media_compositor._elevenlabs_available():  # noqa: SLF001
        raise ValueError(prompt_data.text("canvas_film", "no_music"))
    has_output, needs_voice = _judges(task, document, runs)
    try:
        return canvas_film.plan(
            task, document, picked=request.node_ids, voices=request.voices, music=request.music, music_prompt=request.music_prompt,
            has_output=has_output, needs_voice=needs_voice,
        )
    except canvas_film.FilmError as error:
        raise ValueError(str(error)) from error


def preview(studio: Any, project_id: str, owner_id: str, request: CanvasFilmRequest, *, canvas_id: str, drama: Any, user=None) -> dict[str, Any]:
    """What the film would be made of and what is still missing; nothing is written and nothing runs."""
    task, document, version, runs = _state(studio, project_id, owner_id, canvas_id, drama, user)
    planned = _plan(task, document, runs, request)
    return {
        "version": version, "shots": canvas_film.describe(task, document, planned["clips"]), "voiced": planned["voiced"],
        "music": planned["music"], "music_available": bool(media_compositor._elevenlabs_available()),  # noqa: SLF001
        "missing": planned["missing"], "to_run": len(planned["run"]),
        # The film already has music of its own: the dialog keeps it unless the person turns it off.
        "had_music": any(
            isinstance(node, Mapping) and ((node.get("payload") or {}).get(canvas_film.MARK) or {}).get("role") == "music"
            for node in document.get("nodes") or []
        ),
    }


def build(
    studio: Any, project_id: str, owner_id: str, request: CanvasFilmRequest, *, canvas_id: str, drama: Any, user=None, client_id: str | None = None,
) -> dict[str, Any]:
    """Put the film's nodes in place as one canvas version and say which nodes to run, compose last."""
    with studio.repository.canvas_write_lock():
        task, document, version, runs = _state(studio, project_id, owner_id, canvas_id, drama, user)
        if request.expected_version is not None and request.expected_version != version:
            raise ConcurrencyError(f"canvas version conflict: expected {request.expected_version}, latest is {version}")
        planned = _plan(task, document, runs, request)
        try:
            changed, refs = studio_canvas.apply_operations(document, planned["operations"]) if planned["operations"] else (document, {})
        except studio_canvas.CanvasOperationError as error:
            raise ValueError(str(error)) from error
        ids = {**{ref: ref for ref in planned["run"]}, **refs}
        by_id = {str(node.get("id")): node for node in changed["nodes"]}
        for ref, mark in planned["marks"].items():
            node = by_id.get(refs.get(ref, ref))
            if node is not None:
                node["payload"] = {**(node.get("payload") or {}), canvas_film.MARK: dict(mark)}
        compose_id = refs.get(planned["compose"], planned["compose"])
        sound = planned["sound_plan"]
        by_id[compose_id]["payload"] = {
            **(by_id[compose_id].get("payload") or {}),
            canvas_film.SOUND_PLAN: {
                "voices": {clip: refs.get(ref, ref) for clip, ref in sound["voices"].items()},
                **({"music": refs.get(sound["music"], sound["music"])} if sound.get("music") else {}),
            },
        }
        record = studio.repository.put_canvas(
            project_id, owner_id, CanvasPutRequest(expected_version=version, nodes=changed["nodes"], edges=changed["edges"]), canvas_id=canvas_id,
        )
    studio._announce_saved(project_id, owner_id, canvas_id, record.version, client_id)  # noqa: SLF001 - the other windows catch up
    return {
        "version": record.version, "compose": compose_id, "run": [ids.get(ref, ref) for ref in planned["run"]],
        "shots": len(planned["clips"]), "voiced": planned["voiced"], "music": planned["music"], "missing": planned["missing"],
        "created": sorted(set(refs.values())),
    }
