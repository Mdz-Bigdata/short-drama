"""Generating a scene's panorama and keeping it with the scene's other backdrop pictures.

The file and its record go through the desk's own capture store, kind ``backdrop``, exactly as
an uploaded background picture does: the desk lists it, counts it against the same limit and
can delete it. All this adds is what the picture was asked for and how well it wraps.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.core import media_compositor, panorama
from app.core.storyboard_assets import fetch_remote_image_bytes
from app.service import director_desk_service as desk
from app.service.spatial_stage_service import scene_record

STORE_KEY = "scene_panoramas"
SEAM_NOTE = "全景左右两端差异较大，接缝可能看得出来；可在导演台转动接缝方向把它藏到背后，或重新生成"


def _records(task: Mapping[str, Any], scene_id: str) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    scenes = assets.get(STORE_KEY) if isinstance(assets.get(STORE_KEY), Mapping) else {}
    return [dict(item) for item in scenes.get(scene_id) or [] if isinstance(item, Mapping)]


def scene_view(task: Mapping[str, Any], scene_id: str) -> dict[str, Any]:
    """The scene's panoramas; one whose picture was deleted on the desk is gone from here too."""
    captures = {item.get("id"): item for item in desk.scene_view(task, scene_id)["captures"] if item.get("kind") == "backdrop"}
    items = []
    for record in _records(task, scene_id):
        capture = captures.get(record.get("capture_id"))
        if capture:
            items.append({**record, "url": capture.get("url")})
    return {"task_id": str(task.get("task_id") or ""), "scene_id": scene_id, "panoramas": items}


def _bytes_of(result: str) -> bytes:
    value = str(result or "").strip()
    if value.startswith("data:image/"):
        return base64.b64decode(value.split(",", 1)[1], validate=True)
    local = media_compositor.local_media_path(value)
    if local:
        with open(local, "rb") as handle:
            return handle.read()
    if value.startswith(("http://", "https://")):
        return fetch_remote_image_bytes(value)
    raise ValueError("图像模型没有返回可下载的图片")


def generate(
    service: Any, task_id: str, scene_id: str, *, description: str = "", reference: bytes | None = None, reference_type: str = "",
) -> dict[str, Any] | None:
    """One paid image call. Everything that can refuse does so before it: the scene, the room, the input."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    scene = scene_record(task, scene_id)
    if scene is None:
        raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
    desk.ensure_room(task, scene_id, "backdrop")
    prompt = panorama.panorama_prompt(description, scene=scene, has_reference=bool(reference))
    references = None
    if reference:
        references = [f"data:{reference_type};base64,{base64.b64encode(reference).decode('ascii')}"]
    model = str((task.get("config") or {}).get("image_model") or "")
    url, used = service.gateway.generate_image(
        model, prompt, ref_images=references, size=panorama.PANORAMA_SIZE, enhance_prompt=False,
        # A panorama "from this picture" that silently ignored the picture would be a different place.
        require_reference_support=bool(reference),
    )
    if not url:
        raise RuntimeError("图像模型没有出图")
    fitted = panorama.fit_panorama(_bytes_of(url))
    stored_url = desk.store_media(task_id, scene_id, fitted.content, "image/jpeg")

    def keep(current: dict[str, Any]) -> dict[str, Any]:
        capture = desk.add_capture(current, scene_id, desk.CaptureUpload(
            content=b"", kind="backdrop", shot_id=0, width=fitted.width, height=fitted.height,
        ), stored_url)
        scenes = current.setdefault("assets", {}).setdefault(STORE_KEY, {})
        records = scenes.setdefault(scene_id, [])
        records.append({
            "id": capture["id"], "capture_id": capture["id"], "description": " ".join(description.split())[:panorama.MAX_DESCRIPTION],
            "source": "image" if reference else "text", "model": model, "provider": used or "",
            "width": fitted.width, "height": fitted.height, "seam_delta": fitted.seam_delta,
            "warning": SEAM_NOTE if fitted.seam_delta > panorama.SEAM_WARNING else "",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        # Anything over the desk's limit was refused by add_capture; these are only the live ones.
        live = {item.get("id") for item in desk.scene_view(current, scene_id)["captures"]}
        scenes[scene_id] = [item for item in records if item.get("capture_id") in live]
        return current

    try:
        updated = service.repo.mutate_task(task_id, keep)
    except Exception:
        desk.discard_media(stored_url)  # refused at the last moment (a race for the last slot): the file is nobody's
        raise
    return scene_view(updated, scene_id)
