"""The project's models, seen and changed from the canvas: text, image, video and audio (voice).

They are the project's own configuration (``config.llm_model`` / ``image_model`` / ``video_model`` /
``tts_model``), the same the pipeline's stages read, and what every canvas node uses unless it picks its own.
Only models enabled in the model centre can be chosen; an empty choice means "the centre's first of that kind"
(video excepted: it always names one). Changing the video model goes through the project's own switch, which
also drops the admission it worked out for the old one. Wording: ``canvas_models.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.core import media_compositor, prompt_data

_DATA = "canvas_models"
#: category -> the project's config key.
FIELDS = {"text": "llm_model", "image": "image_model", "video": "video_model", "audio": "tts_model"}


class CanvasModelsRequest(BaseModel):
    """The categories to change; a field left out stays as it is, an empty one goes back to the centre's default."""

    text: str | None = Field(None, max_length=160)
    image: str | None = Field(None, max_length=160)
    video: str | None = Field(None, max_length=160)
    audio: str | None = Field(None, max_length=160)


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def choices(category: str) -> list[str]:
    """The models of this category enabled in the model centre, in the centre's order."""
    from app.platform.runtime_models import runtime_model_registry

    return list(dict.fromkeys(model for item in runtime_model_registry.list(category) for model in item.model_ids))


def effective(category: str, chosen: str) -> str:
    """The model that would actually run for this choice, by the same rules the runners use."""
    from app.core.model_gateway import ModelGateway

    if category == "video":
        return ModelGateway.effective_video_model(chosen)
    if category == "audio":
        return media_compositor.effective_audio_model(chosen)[1]
    listed = choices(category)
    return chosen if not listed or chosen in listed else listed[0]


def view_of(task: Mapping[str, Any]) -> dict[str, Any]:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    models = {}
    for category, key in FIELDS.items():
        chosen = str(config.get(key) or "")
        models[category] = {"chosen": chosen, "effective": effective(category, chosen), "choices": choices(category)}
    available = bool(media_compositor._elevenlabs_available())  # noqa: SLF001
    return {"models": models, "extras": {"music": available, "sfx": available}}


def view(studio: Any, project_id: str, owner_id: str, *, drama: Any, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
    _, task = studio._canvas_task(project_id, owner_id, drama, user)  # noqa: SLF001
    return {**view_of(task), "running": bool(drama._has_running_generation(task))}  # noqa: SLF001


def update(studio: Any, project_id: str, owner_id: str, request: CanvasModelsRequest, *, drama: Any, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Change the asked categories, all checked before any is written."""
    task_id, task = studio._canvas_task(project_id, owner_id, drama, user)  # noqa: SLF001
    names = prompt_data.value(_DATA, "categories")
    wanted = {category: str(value).strip() for category in FIELDS if (value := getattr(request, category)) is not None}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    for category, model in wanted.items():
        listed = choices(category)
        if not model:
            if category == "video":
                raise ValueError(_text("video_required"))
            continue
        if not listed:
            raise ValueError(_text("none_enabled").format(category=names[category]))
        if model not in listed:
            raise ValueError(_text("not_enabled").format(category=names[category], model=model, choices="、".join(listed)))
    if drama._has_running_generation(task):  # noqa: SLF001
        raise ValueError(_text("running"))
    video = wanted.pop("video", None)
    if video is not None and video != str(config.get("video_model") or ""):
        if drama.set_project_video_model(task_id, video) is None:
            raise PermissionError("task not found")
    others = {FIELDS[category]: model for category, model in wanted.items() if model != str(config.get(FIELDS[category]) or "")}
    if others:
        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            if drama._has_running_generation(current):  # noqa: SLF001
                raise ValueError(_text("running"))
            current.setdefault("config", {}).update(others)
            return current

        if not drama.repo.mutate_task(task_id, mutate):
            raise PermissionError("task not found")
    return view(studio, project_id, owner_id, drama=drama, user=user)
