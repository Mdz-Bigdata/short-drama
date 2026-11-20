# -*- coding: utf-8 -*-
"""The node canvas and the element library, joined in both directions.

**Take from the library.** An element's pictures are private: they are served only through the
library's authenticated endpoint, a provider cannot fetch them, and a shared canvas strips their
addresses. So a picture taken onto the canvas is *copied* into the canvas's own media storage (the
place and URL shape an upload or a run's result has) and the new ``media`` node holds that copy,
with a note of which element it came from (``payload.output.element``). The copy is what a
connected image or video node is handed as its reference; later changes to the element do not
reach it, and deleting the element does not break the canvas. All the nodes of one request are one
canvas edit: one new version, or nothing (and then the copies are removed again).

**Save to the library.** A node's picture (what a ``media`` node holds, or the active generation
of an image or tool node) becomes a new element of the person's library, through the library's own
"create the element, then store its file" path: its validation, storage root, quota and revision
rules apply unchanged. The new element is not attached to any project.

Ownership is the library's own check throughout: ``PlatformStore.get_element(id, owner)`` answers
only for the owner, and an element that is somebody else's looks exactly like one that does not exist.

Capability after NovaNova Studio's canvas ("My assets" puts a library asset on the canvas, "Save
asset" keeps a node's result); the implementation, node model and wording are this project's own.
Wording and limits: ``app/data/prompt/canvas_elements.json``.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, get_args

from starlette.concurrency import run_in_threadpool

from app.core import media_compositor, prompt_data, studio_canvas
from app.repository.studio_repo import ConcurrencyError
from app.schema.platform import ElementKind

logger = logging.getLogger(__name__)

_DATA = "canvas_elements"
#: The library's kinds, in the order it declares them.
KINDS: tuple[str, ...] = tuple(get_args(ElementKind))
#: What an element picture can be (the same three the library serves), and the extension its copy gets.
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_MAIN_SLOT = "reference"


class ElementNotFound(LookupError):
    """Not in this person's library: somebody else's element and a missing one are told apart nowhere."""


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _library():
    # Imported when used: element_api builds a model gateway at import time, and the library's
    # file helpers (private storage root, validation, quarantine on replace) live there.
    from app.api import element_api

    return element_api


def _owned_project(service: Any, project_id: str, owner_id: str) -> None:
    if not service.repository.get_project(project_id, owner_id):
        raise PermissionError("project not found or not owned by actor")


# ---------------------------------------------------------------------------- what the library holds


def _images(element: Any) -> list[Any]:
    """An element's pictures, the main one first: the main reference when there is one, else the first view."""
    pictures = [item for item in element.files or [] if str(item.mime_type or "") in _EXTENSIONS]
    return sorted(pictures, key=lambda item: item.slot != _MAIN_SLOT)


async def listing(
    service: Any, store: Any, *, project_id: str, owner_id: str, kind: str | None = None, query: str = "", page: int = 1, page_size: int | None = None,
) -> dict[str, Any]:
    """The person's elements that have a picture to take, newest first; ``query`` looks in names and descriptions."""
    await run_in_threadpool(_owned_project, service, project_id, owner_id)
    if kind and kind not in KINDS:
        raise ValueError(_text("bad_kind").format(kind=kind))
    library = _library()
    found = [item for each in ((kind,) if kind else KINDS) for item in await store.list_all_elements(owner_id, each)]
    needle = str(query or "").strip().casefold()
    rows = [
        item for item in found
        if _images(item) and (not needle or needle in str(item.name or "").casefold() or needle in str(item.description or "").casefold())
    ]
    # id first: elements changed in the same instant keep their order from one page to the next.
    rows.sort(key=lambda item: item.id)
    rows.sort(key=lambda item: item.updated_at, reverse=True)
    size = max(1, int(page_size or prompt_data.number(_DATA, "page_size")))
    start = (max(1, int(page)) - 1) * size
    return {
        "items": [
            {
                "id": item.id, "kind": item.kind, "name": item.name,
                "images": [{"id": picture.id, "slot": picture.slot, "url": library._file(item.id, item.version, picture)["url"]} for picture in _images(item)],
            }
            for item in rows[start:start + size]
        ],
        "total": len(rows), "page": max(1, int(page)), "page_size": size, "kinds": list(KINDS), "max_take": prompt_data.number(_DATA, "max_take"),
    }


# ---------------------------------------------------------------------------- library -> canvas


def _keep_copy(content: bytes, extension: str) -> str:
    """Write the copy where the canvas keeps its files, under a name the server made up; returns its URL."""
    os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
    name = f"{_text('copy_prefix')}{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(media_compositor.MEDIA_DIR, name), "wb") as handle:
        handle.write(content)
    return media_compositor.public_url(name)


def _discard_copy(url: str) -> None:
    path = media_compositor.local_media_path(url)
    if path and os.path.basename(path).startswith(_text("copy_prefix")):
        try:
            os.unlink(path)
        except OSError:
            logger.warning("[Canvas] 没用上的元素图片副本没能删掉: %s", os.path.basename(path))


def _read_picture(library: Any, element: Any, picture: Any) -> bytes:
    from fastapi import HTTPException

    try:
        path, _ = library._owned_reference_path(picture.storage_path, element.owner_id, element.id)
    except HTTPException as error:
        raise ValueError(_text("image_missing").format(name=element.name)) from error
    if not path.is_file():
        raise ValueError(_text("image_missing").format(name=element.name))
    content = path.read_bytes()
    # The library checked it on the way in; checked again here because this copy leaves the private store.
    library._validated_generated_image(content)
    return content


def _origin(document: Mapping[str, Any], margin: float) -> tuple[float, float]:
    """To the right of everything already there, top-aligned: the rule ``add_node`` itself places by."""
    laid = [node for node in document.get("nodes") or [] if isinstance(node, Mapping) and node.get("kind") != "group"]
    if not laid:
        return 0.0, 0.0
    right = max(float(node.get("x") or 0) + float(node.get("width") or 0) for node in laid)
    return right + margin, min(float(node.get("y") or 0) for node in laid)


async def take(
    service: Any, store: Any, *, project_id: str, owner_id: str, canvas_id: str, picks: Sequence[tuple[str, str | None]], base_version: int | None = None,
) -> dict[str, Any]:
    """Put the picked pictures on the canvas as media nodes holding copies: one canvas version, or nothing.

    ``picks`` is ``(element id, file id or None)``; no file id means the element's main picture.
    """
    await run_in_threadpool(_owned_project, service, project_id, owner_id)
    library = _library()
    elements: dict[str, Any] = {}
    chosen: list[tuple[Any, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element_id, file_id in picks:
        element_id = str(element_id or "").strip()
        if element_id not in elements:
            element = await store.get_element(element_id, owner_id) if element_id else None
            if element is None:
                raise ElementNotFound(_text("not_found"))
            elements[element_id] = element
        element = elements[element_id]
        pictures = _images(element)
        if not pictures:
            raise ValueError(_text("no_image").format(name=element.name))
        picture = next((item for item in pictures if item.id == file_id), None) if file_id else pictures[0]
        if picture is None:
            raise ValueError(_text("no_such_image").format(name=element.name))
        if (element.id, picture.id) not in seen:
            seen.add((element.id, picture.id))
            chosen.append((element, picture))
    if not chosen:
        raise ValueError(_text("nothing_chosen"))
    limit = prompt_data.number(_DATA, "max_take")
    if len(chosen) > limit:
        raise ValueError(_text("too_many").format(limit=limit, count=len(chosen)))

    canvas = await run_in_threadpool(lambda: service.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id))
    latest = canvas.version if canvas else 0
    if base_version is not None and int(base_version) != latest:
        # Said before anything is copied; edit_canvas checks again under its lock.
        raise ConcurrencyError(f"canvas version conflict: expected {base_version}, latest is {latest}")
    grid = prompt_data.value(_DATA, "layout")
    width, height = studio_canvas.DEFAULT_SIZES["media"]
    left, top = _origin(canvas.model_dump(mode="json") if canvas else {}, float(grid["margin"]))

    copies: list[str] = []
    try:
        operations: list[dict[str, Any]] = []
        for index, (element, picture) in enumerate(chosen):
            content = await run_in_threadpool(_read_picture, library, element, picture)
            url = await run_in_threadpool(_keep_copy, content, _EXTENSIONS[picture.mime_type])
            copies.append(url)
            operations.append({
                "op": "add_node", "ref": f"element{index}", "kind": "media", "label": str(element.name)[:120],
                "output": {
                    "medium": "image", "url": url, "name": element.name,
                    "element": {"id": element.id, "name": element.name, "kind": element.kind, "file_id": picture.id, "slot": picture.slot, "sha256": picture.sha256},
                },
                "x": left + (index % int(grid["columns"])) * (width + float(grid["gap"])),
                "y": top + (index // int(grid["columns"])) * (height + float(grid["gap"])),
            })
        done = await run_in_threadpool(lambda: service.edit_canvas(project_id, owner_id, operations, canvas_id=canvas_id, base_version=base_version))
    except BaseException:
        for url in copies:
            _discard_copy(url)
        raise
    return {
        "version": done["version"],
        "node_ids": [done["created"][f"element{index}"] for index in range(len(chosen))],
        "elements": [
            {"id": element.id, "name": element.name, "file_id": picture.id, "node_id": done["created"][f"element{index}"]}
            for index, (element, picture) in enumerate(chosen)
        ],
    }


# ---------------------------------------------------------------------------- canvas -> library


def _node_picture(service: Any, project_id: str, owner_id: str, canvas_id: str, node_id: str) -> dict[str, Any]:
    """The picture this node shows: its active generation first, else the file it holds."""
    _owned_project(service, project_id, owner_id)
    canvas = service.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
    document = canvas.model_dump(mode="json") if canvas else {"nodes": [], "edges": []}
    nodes = {str(item.get("id")): item for item in document["nodes"]}
    node = nodes.get(str(node_id))
    if node is None:
        raise ValueError(_text("node_missing"))
    runs = {key: run.model_dump(mode="json") for key, run in service.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id).items()}
    output = studio_canvas.effective_output(node, nodes, document["edges"], runs)
    if not output or output.get("medium") != "image" or not str(output.get("url") or "").strip():
        raise ValueError(_text("node_no_image"))
    run = runs.get(str(node_id)) or {}
    return {"url": str(output["url"]).strip(), "run_id": str(run.get("id") or "") if run.get("output") else "", "kind": str(node.get("kind") or "")}


def _inside(path: Path, root: Path) -> bool:
    resolved, base = path.resolve(), root.resolve()
    return resolved == base or base in resolved.parents


def _picture_bytes(library: Any, url: str) -> bytes:
    """The picture behind a node's URL: this server's own media file, or a remote one through the library's guarded fetch."""
    local = media_compositor.local_media_path(url)
    if local:
        if _inside(Path(local), library.LEGACY_ELEMENT_MEDIA_ROOT):
            # Old installations kept element pictures under /media/elements: private, and not this canvas's to copy.
            raise ValueError(_text("result_private"))
        with open(local, "rb") as handle:
            return handle.read()
    if not url.startswith(("https://", "http://", "data:image/")):
        raise ValueError(_text("result_unreadable"))
    try:
        return library._load_generated_image_bytes(url)
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001 - a link that went away is a refusal, not a server fault
        logger.warning("[Canvas] 节点图片没能取回，无法存入元素库: %s", type(error).__name__)
        raise ValueError(_text("result_unreadable")) from error


async def save_node(service: Any, store: Any, *, project_id: str, owner_id: str, canvas_id: str, node_id: str, name: str, kind: str) -> dict[str, Any]:
    """Keep a node's picture as a new element of the person's library; answers the new element."""
    name = str(name or "").strip()
    if not name:
        raise ValueError(_text("name_required"))
    if kind not in KINDS:
        raise ValueError(_text("bad_kind").format(kind=kind))
    library = _library()
    found = await run_in_threadpool(_node_picture, service, project_id, owner_id, canvas_id, node_id)
    content = await run_in_threadpool(_picture_bytes, library, found["url"])
    suffix, mime = await run_in_threadpool(library._validated_generated_image, content)
    slots = prompt_data.value(_DATA, "slots")
    source = {"project_id": project_id, "canvas_id": canvas_id, "node_id": str(node_id), **({"run_id": found["run_id"]} if found["run_id"] else {})}
    element = await store.create_element(owner_id=owner_id, kind=kind, name=name, description="", metadata={"canvas_source": source})
    try:
        view = await library._persist_element_file(
            element_id=element.id, owner_id=owner_id, slot=str(slots.get(kind) or slots["default"]), suffix=suffix, mime=mime, content=content, store=store,
        )
    except BaseException:
        # An element with no picture is not what was asked for: take it back out.
        try:
            await library.delete_element_and_files(element.id, owner_id, store)
        except Exception as error:  # noqa: BLE001 - the refusal the person sees is the one above
            logger.warning("[Canvas] 存入元素库失败后没能清掉空元素: element=%s error=%s", element.id, type(error).__name__)
        raise
    return {"id": view["id"], "name": view["name"], "kind": view["kind"], "version": view["version"], "files": view["files"]}


__all__ = ["ElementNotFound", "KINDS", "listing", "save_node", "take"]
