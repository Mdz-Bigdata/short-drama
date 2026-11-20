"""The canvas's "sync from project": review what would change, then apply what the person kept.

The rules are in :mod:`app.core.canvas_project_sync`; this module reads the task and the canvas,
and writes the result as one new canvas version that every open window hears about.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.core import canvas_project_sync, studio_canvas
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import CanvasPutRequest


class CanvasProjectSyncRequest(BaseModel):
    """The review answered: the version and token it was made for, the differences to take from the project, and whether to lay out new shots."""

    expected_version: int = Field(ge=0)
    token: str = Field(min_length=1, max_length=64)
    accept: list[str] = Field(default_factory=list, max_length=5000)
    add_new: bool = True


def _document(studio: Any, project_id: str, owner_id: str, canvas_id: str) -> tuple[dict[str, Any], int]:
    canvas = studio.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
    return (canvas.model_dump(mode="json"), canvas.version) if canvas else ({"nodes": [], "edges": []}, 0)


def review(studio: Any, project_id: str, owner_id: str, *, canvas_id: str, drama: Any, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What syncing this canvas with its project would change; nothing is written."""
    _, task = studio._canvas_task(project_id, owner_id, drama, user)  # noqa: SLF001 - the same ownership check every canvas run uses
    document, version = _document(studio, project_id, owner_id, canvas_id)
    return {**canvas_project_sync.review(task, document), "version": version}


def apply(
    studio: Any, project_id: str, owner_id: str, request: CanvasProjectSyncRequest, *, canvas_id: str, drama: Any, user: Mapping[str, Any] | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Apply the answered review as one canvas version, or nothing; refused when the canvas or the project moved since.

    ``client_id`` is the window that asked: it loads the new version itself, so the saved event skips it.
    """
    _, task = studio._canvas_task(project_id, owner_id, drama, user)  # noqa: SLF001
    with studio.repository.canvas_write_lock():
        document, latest = _document(studio, project_id, owner_id, canvas_id)
        if request.expected_version != latest:
            raise ConcurrencyError(f"canvas version conflict: expected {request.expected_version}, latest is {latest}")
        try:
            done = canvas_project_sync.apply(task, document, token=request.token, accept=request.accept, add_new=request.add_new)
        except canvas_project_sync.SyncOutdated as error:
            raise ConcurrencyError(str(error)) from error
        except studio_canvas.CanvasOperationError as error:
            raise ValueError(str(error)) from error
        summary = {key: done[key] for key in ("shots", "updated", "kept", "node_ids")}
        if not done["changed"]:
            return {**summary, "applied": False, "version": latest}
        written = done["document"]
        record = studio.repository.put_canvas(
            project_id, owner_id, CanvasPutRequest(expected_version=latest, nodes=written["nodes"], edges=written["edges"]), canvas_id=canvas_id,
        )
    studio._announce_saved(project_id, owner_id, canvas_id, record.version, client_id)  # noqa: SLF001 - every other open window catches up at once
    return {**summary, "applied": True, "version": record.version}
