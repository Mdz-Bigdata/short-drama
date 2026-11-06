"""A project's image pool: every image it generated and every cell cut from one, in one index.

The index sits on ``task["assets"]`` and carries a revision, so two tabs cutting at once
cannot overwrite each other unnoticed. It holds nothing that cannot be found again: the
generated images are named by the project's own shots and boards, and a cut cell's file
name says what it was cut from and where, so ``rebuild`` restores the index from those.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.core import media_compositor
from app.core.episode_cycle import shot_uid
from app.core.grid_split import split_grid

POOL_KEY = "4_image_pool"
STORE_VERSION = 1
MAX_CELLS = 600
_DIRECTORY = "image_pool"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
# cell_<source digest>_<rows>x<columns>_<row>_<column>.png, positions 0-based.
_CELL_NAME = re.compile(r"^cell_([0-9a-f]{16})_(\d+)x(\d+)_(\d+)_(\d+)\.png$")


class PoolConflict(ValueError):
    """The index changed since the caller read it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _folder(task_id: str) -> str:
    return os.path.join(media_compositor.MEDIA_DIR, _DIRECTORY, _SAFE.sub("", task_id)[:64] or "task")


def _stored(task: Mapping[str, Any]) -> dict[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(POOL_KEY)
    if isinstance(store, Mapping) and store.get("version") == STORE_VERSION and isinstance(store.get("images"), list):
        return dict(store)
    return {"version": STORE_VERSION, "revision": 0, "images": []}


def _generated(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What the project drew, read from its own stage-4 records: shot frames and scene boards."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    found: dict[str, dict[str, Any]] = {}

    def note(url: Any, kind: str, label: str, **facts: Any) -> None:
        text = str(url or "").strip()
        if text and not text.startswith("data:") and text not in found:
            found[text] = {"id": f"img_{_digest(text)}", "url": text, "kind": kind, "label": label, **facts}

    for index, shot in enumerate(assets.get("4") if isinstance(assets.get("4"), list) else [], start=1):
        if isinstance(shot, Mapping):
            number = int(shot.get("shot_id") or index)
            scene = str(shot.get("scene_id") or "")
            note(shot.get("image_url"), "shot", f"{scene} 镜头 {number}".strip(), scene_id=scene, shot_id=number,
                 shot_uid=shot_uid({**shot, "shot_id": number}))
    boards = assets.get("4_scene_boards")
    for scene, board in (boards.items() if isinstance(boards, Mapping) else ()):
        if isinstance(board, Mapping):
            note(board.get("grid_url"), "board", f"{scene} 九宫格", scene_id=str(scene))
    note(assets.get("4_grid"), "board", "分镜总览")
    return list(found.values())


def _cells_on_disk(task_id: str, sources: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    folder = _folder(task_id)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    cells = []
    for name in names:
        match = _CELL_NAME.match(name)
        if not match:
            continue
        digest, rows, columns, row, column = match.groups()
        source = sources.get(digest)
        cells.append({
            "id": name[:-4],
            "url": media_compositor.public_url(f"{_DIRECTORY}/{os.path.basename(folder)}/{name}"),
            "kind": "cell",
            "label": f"{(source or {}).get('label') or '切图'} · {int(row) + 1}-{int(column) + 1}",
            "parent_id": f"img_{digest}", "grid": [int(rows), int(columns)], "row": int(row), "column": int(column),
        })
    return cells


def _merged(task: Mapping[str, Any], cells: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    # A generated image comes from the project's records every time, so a redrawn shot is never shown stale.
    images = _generated(task)
    known = {image["id"] for image in images}
    return images + [dict(cell) for cell in cells if cell.get("id") not in known]


def view(task: Mapping[str, Any]) -> dict[str, Any]:
    """The pool as of now; a project that never touched it still shows everything it generated."""
    store = _stored(task)
    cells = [item for item in store["images"] if isinstance(item, Mapping) and item.get("kind") == "cell"]
    if not store["revision"]:
        cells = _cells_on_disk(str(task.get("task_id") or ""), {image["id"][4:]: image for image in _generated(task)})
    images = []
    for image in _merged(task, cells):
        # A lost file is not offered; remote images cannot be checked from here and are taken on trust.
        if image.get("kind") == "cell" and not media_compositor.local_media_path(image.get("url")):
            continue
        images.append(image)
    return {
        "task_id": str(task.get("task_id") or ""), "revision": int(store["revision"]), "updated_at": store.get("updated_at"),
        "images": images,
    }


def _assert_revision(task: Mapping[str, Any], expected: int | None) -> dict[str, Any]:
    store = _stored(task)
    if expected is not None and int(expected) != int(store["revision"]):
        raise PoolConflict(f"图片池已被更新（当前版本 {store['revision']}），请刷新后再试")
    return store


def _save(task: dict[str, Any], store: Mapping[str, Any], images: list[Any]) -> dict[str, Any]:
    task.setdefault("assets", {})[POOL_KEY] = {
        "version": STORE_VERSION, "revision": int(store["revision"]) + 1, "updated_at": _now(), "images": images,
    }
    return view(task)


def rebuild(task: dict[str, Any], *, expected_revision: int | None = None) -> dict[str, Any]:
    """Forget the index and find everything again from the project's records and the files on disk."""
    store = _assert_revision(task, expected_revision)
    generated = _generated(task)
    cells = _cells_on_disk(str(task.get("task_id") or ""), {image["id"][4:]: image for image in generated})
    return _save(task, store, _merged(task, cells))


def find(task: Mapping[str, Any], image_id: str) -> dict[str, Any] | None:
    return next((image for image in view(task)["images"] if image.get("id") == image_id), None)


def cut(task_id: str, source: Mapping[str, Any], content: bytes, rows: int, columns: int) -> list[dict[str, Any]]:
    """Write the cells of one image to disk; the same cut again lands on the same names, so it cannot pile up."""
    digest = _digest(str(source.get("url") or ""))
    folder = _folder(task_id)
    os.makedirs(folder, exist_ok=True)
    label = str(source.get("label") or "切图")
    entries = []
    for cell in split_grid(content, rows, columns):
        name = f"cell_{digest}_{rows}x{columns}_{cell.row}_{cell.column}.png"
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(cell.png)
        entries.append({
            "id": name[:-4], "url": media_compositor.public_url(f"{_DIRECTORY}/{os.path.basename(folder)}/{name}"),
            "kind": "cell", "label": f"{label} · {cell.row + 1}-{cell.column + 1}",
            "parent_id": f"img_{digest}", "grid": [rows, columns], "row": cell.row, "column": cell.column,
            "width": cell.box[2] - cell.box[0], "height": cell.box[3] - cell.box[1],
        })
    return entries


def add_cells(task: dict[str, Any], cells: list[dict[str, Any]], *, expected_revision: int | None = None) -> dict[str, Any]:
    store = _assert_revision(task, expected_revision)
    if not store["revision"]:
        # First write: the cells already on disk join the index rather than falling out of view.
        current = view(task)["images"]
    else:
        current = [item for item in store["images"] if isinstance(item, Mapping)]
    fresh = {cell["id"] for cell in cells}
    kept = [item for item in current if item.get("kind") == "cell" and item.get("id") not in fresh]
    merged_cells = [*kept, *cells]
    if len(merged_cells) > MAX_CELLS:
        raise ValueError(f"图片池最多 {MAX_CELLS} 张切图，请先清理")
    return _save(task, store, _merged(task, merged_cells))
