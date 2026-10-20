"""Read project-owned element-library references for synchronous storyboard jobs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app import settings
from app.core import character_variants
from app.core.element_scope import element_in_task
from app.core.media_compositor import MEDIA_DIR
from app.core.storyboard_scene_context import compile_scene_context
from app.platform.store import PlatformStore

logger = logging.getLogger(__name__)
_KINDS = ("actor", "scene", "prop", "costume", "effect", "product")
_IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_PAGE_SIZE = 100


def _identifier(value: object) -> str:
    text = str(value or "").strip()
    if (
        not text
        or text in {".", ".."}
        or any(char in text for char in ("/", "\\", "\x00"))
    ):
        return ""
    return text


def _image_roots() -> tuple[Path, ...]:
    media = Path(MEDIA_DIR).resolve()
    private = settings.private_storage_dir("ELEMENT_IMAGE_STORAGE_DIR", "element_images", media)
    # Mirror the element API's prohibition against new public reference storage.
    roots = [] if private == media or media in private.parents else [private]
    legacy = (media / "elements").resolve()
    if legacy not in roots:
        roots.append(legacy)
    return tuple(roots)


def _image_data_uri(
    reference: Any, owner_id: str, element_id: str, roots: tuple[Path, ...]
) -> str:
    mime = str(getattr(reference, "mime_type", "") or "")
    if mime not in _IMAGE_FORMATS:
        return ""
    stored = str(getattr(reference, "storage_path", "") or "")
    if not stored:
        return ""
    for root in roots:
        try:
            root = root.resolve()
            # A symlinked owner/element directory cannot confer access to another
            # owner's image, even if that target is elsewhere inside the root.
            declared_owned = root / owner_id / element_id
            owned = declared_owned.resolve()
            if owned != declared_owned or root not in owned.parents:
                continue
            candidate = (root / stored).resolve()
            if owned not in candidate.parents or not candidate.is_file():
                continue
            if not 0 < candidate.stat().st_size <= _MAX_IMAGE_BYTES:
                continue
            with candidate.open("rb") as handle:
                content = handle.read(_MAX_IMAGE_BYTES + 1)
            if not content or len(content) > _MAX_IMAGE_BYTES:
                continue
            expected_hash = str(getattr(reference, "sha256", "") or "")
            if expected_hash and hashlib.sha256(content).hexdigest() != expected_hash:
                continue
            with Image.open(io.BytesIO(content)) as image:
                if (
                    image.format != _IMAGE_FORMATS[mime]
                    or image.width * image.height > _MAX_IMAGE_PIXELS
                ):
                    continue
                image.verify()
            return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
        except (
            OSError,
            ValueError,
            RuntimeError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ):
            continue
    return ""


async def _load_project_elements(
    task: dict,
    owner_id: str,
    task_id: str,
    scene: dict | None,
) -> list[dict]:
    # Stage workers run in their own thread. The API's cached async engine must
    # never be reused from this temporary event loop.
    store = PlatformStore(settings.database_url())
    result: list[dict] = []
    files_by_id: dict[str, list] = {}
    seen: set[str] = set()
    try:
        for kind in _KINDS:
            page = 1
            while True:
                items, total = await store.list_elements(
                    owner_id, kind, page, _PAGE_SIZE
                )
                if not items:
                    break
                for item in items:
                    element_id = _identifier(getattr(item, "id", ""))
                    metadata = getattr(item, "metadata_json", None)
                    if (
                        not element_id
                        or element_id in seen
                        or str(getattr(item, "owner_id", "")) != owner_id
                        or str(getattr(item, "kind", "")) != kind
                        or not isinstance(metadata, dict)
                        or not element_in_task(metadata, task_id)
                    ):
                        continue
                    seen.add(element_id)
                    files_by_id[element_id] = list(getattr(item, "files", None) or [])
                    result.append(
                        {
                            "id": element_id,
                            "kind": kind,
                            "name": str(getattr(item, "name", "") or ""),
                            "description": str(getattr(item, "description", "") or ""),
                            "metadata": dict(metadata),
                            "image_url": "",
                        }
                    )
                if page * _PAGE_SIZE >= total:
                    break
                page += 1
    finally:
        await store.close()

    # Scene selection needs names/descriptions only. Do not open or base64-encode
    # the entire show's reference library on every scene-generation request.
    if scene is not None:
        context = compile_scene_context(task, scene, result)
        selected = [
            item
            for key in ("actors", "scenes", "props", "costumes", "effects", "products")
            for item in context.get(key, [])
        ]
        selected_ids = {item["id"] for item in selected if item.get("id")}
        selected_names = {
            (item.get("kind"), item.get("name"))
            for item in selected
            if not item.get("id")
        }
        # The derived looks of a selected character come along: a shot may still call for one.
        cast = {item.get("name") for item in context.get("actors", [])}
        result = [
            item
            for item in result
            if item["id"] in selected_ids
            or (item["kind"], item["name"]) in selected_names
            or (item["kind"] == "actor" and (character_variants.variant_of(item) or {}).get("of") in cast)
        ]
    roots = _image_roots()
    for item in result:
        preferred_slot = "front" if item["kind"] == "actor" else "reference"
        references = sorted(
            files_by_id[item["id"]],
            key=lambda entry: getattr(entry, "slot", "") != preferred_slot,
        )
        for reference in references:
            item["image_url"] = _image_data_uri(reference, owner_id, item["id"], roots)
            if item["image_url"]:
                break
    return result


def load_storyboard_elements(task: dict, scene: dict | None = None) -> list[dict]:
    """Load all five libraries, strictly limited to this task and its owner.

    Invoke from the synchronous stage worker. The returned image references are
    validated private bytes; authenticated element URLs are never sent upstream.
    Storage failures stop owned production jobs instead of silently discarding
    their configured asset library. Legacy ownerless tasks have no library scope.
    With a scene, only its matched assets are returned and their images read.
    """
    owner_id = _identifier(task.get("owner_user_id"))
    task_id = str(task.get("task_id") or "").strip()
    if not owner_id or not task_id:
        return []
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "load_storyboard_elements must run in a synchronous stage worker"
        )
    try:
        return asyncio.run(_load_project_elements(task, owner_id, task_id, scene))
    except Exception as exc:
        logger.warning("分镜元素库读取失败: %s", type(exc).__name__)
        raise RuntimeError("当前项目的元素库读取失败，请稍后重试分镜生成") from None
