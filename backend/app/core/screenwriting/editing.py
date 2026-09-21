# -*- coding: utf-8 -*-
"""Ordered, transactional edits on one episode's script plan.

Operations mirror a batch edit: ``update`` (merge fields into a shot),
``insert_after`` (new shot after an id, or at the front with ``null``),
``remove``, ``move_after`` and ``split`` (one shot into several ``_N`` children).
The whole batch is applied to a copy and validated as one aggregate; the first
failing operation aborts the batch with its index and reason.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.screenwriting.models import SceneContent

_STRICT = ConfigDict(extra="forbid")
_EDITABLE_FIELDS = frozenset({
    "duration_seconds",
    "segment_break",
    "setting",
    "characters_in_scene",
    "scenes",
    "props",
    "scene_description",
    "utterances",
    "source_text",
})


class UpdateOperation(BaseModel):
    model_config = _STRICT
    op: Literal["update"]
    id: str = Field(min_length=1)
    fields: dict[str, Any] = Field(min_length=1)


class InsertAfterOperation(BaseModel):
    model_config = _STRICT
    op: Literal["insert_after"]
    after_id: str | None = None
    item: dict[str, Any]


class MoveAfterOperation(BaseModel):
    model_config = _STRICT
    op: Literal["move_after"]
    id: str = Field(min_length=1)
    after_id: str | None = None


class RemoveOperation(BaseModel):
    model_config = _STRICT
    op: Literal["remove"]
    id: str = Field(min_length=1)


class SplitOperation(BaseModel):
    model_config = _STRICT
    op: Literal["split"]
    id: str = Field(min_length=1)
    parts: list[dict[str, Any]] = Field(min_length=2)


PlanOperation = Annotated[
    UpdateOperation | InsertAfterOperation | MoveAfterOperation | RemoveOperation | SplitOperation,
    Field(discriminator="op"),
]


class PlanEditError(ValueError):
    def __init__(self, message: str, *, operation_index: int | None = None, scene_id: str | None = None):
        super().__init__(message)
        self.operation_index = operation_index
        self.scene_id = scene_id


def _index_of(scenes: list[dict[str, Any]], scene_id: str) -> int:
    for index, scene in enumerate(scenes):
        if str(scene.get("scene_id")) == scene_id:
            return index
    raise PlanEditError(f"未找到分镜 {scene_id}", scene_id=scene_id)


def _next_suffixed_id(base: str, taken: set[str]) -> str:
    root = re.sub(r"_\d+$", "", base)
    counter = 1
    while f"{root}_{counter}" in taken:
        counter += 1
    return f"{root}_{counter}"


def _validate_scene(scene: dict[str, Any], *, index: int) -> dict[str, Any]:
    try:
        return SceneContent.model_validate(scene).model_dump(mode="json")
    except ValidationError as error:
        issues = "; ".join(f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg')}" for item in error.errors()[:5])
        raise PlanEditError(f"分镜结构不合法：{issues}", operation_index=index, scene_id=str(scene.get("scene_id") or "")) from error


def apply_plan_operations(scenes: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new scene list with ``operations`` applied in order; never mutates the input."""
    working = deepcopy(scenes)
    try:
        parsed = [_OperationEnvelope.model_validate({"operation": raw}).operation for raw in operations]
    except ValidationError as error:
        raise PlanEditError(f"操作格式不合法：{error.errors()[0].get('msg') if error.errors() else error}") from error
    for index, operation in enumerate(parsed):
        taken = {str(scene.get("scene_id")) for scene in working}
        if isinstance(operation, UpdateOperation):
            position = _index_of(working, operation.id)
            unknown = sorted(set(operation.fields) - _EDITABLE_FIELDS)
            if unknown:
                raise PlanEditError(f"不可编辑的字段：{', '.join(unknown)}", operation_index=index, scene_id=operation.id)
            updated = {**working[position], **operation.fields}
            updated["scene_id"] = operation.id
            working[position] = _validate_scene(updated, index=index)
        elif isinstance(operation, InsertAfterOperation):
            item = dict(operation.item)
            item_id = str(item.get("scene_id") or "").strip()
            anchor = operation.after_id
            if anchor is None:
                position = -1
                base = str(working[0].get("scene_id")) if working else "E1S01"
            else:
                position = _index_of(working, anchor)
                base = anchor
            if not item_id:
                item_id = _next_suffixed_id(base, taken)
            elif item_id in taken:
                raise PlanEditError(f"scene_id 已存在: {item_id}", operation_index=index, scene_id=item_id)
            item["scene_id"] = item_id
            working.insert(position + 1, _validate_scene(item, index=index))
        elif isinstance(operation, MoveAfterOperation):
            position = _index_of(working, operation.id)
            moving = working.pop(position)
            if operation.after_id is None:
                working.insert(0, moving)
            else:
                if operation.after_id == operation.id:
                    raise PlanEditError("不能把分镜移动到它自己之后", operation_index=index, scene_id=operation.id)
                working.insert(_index_of(working, operation.after_id) + 1, moving)
        elif isinstance(operation, RemoveOperation):
            working.pop(_index_of(working, operation.id))
            if not working:
                raise PlanEditError("不能删除本集最后一个分镜", operation_index=index, scene_id=operation.id)
        elif isinstance(operation, SplitOperation):
            position = _index_of(working, operation.id)
            original = working.pop(position)
            taken.discard(operation.id)
            children: list[dict[str, Any]] = []
            for part in operation.parts:
                child = {**original, **dict(part)}
                child.pop("needs_replan", None)
                child_id = str(child.get("scene_id") or "").strip()
                if not child_id or child_id == operation.id or child_id in taken:
                    child_id = _next_suffixed_id(operation.id, taken)
                child["scene_id"] = child_id
                taken.add(child_id)
                children.append(_validate_scene(child, index=index))
            working[position:position] = children
    return working


class _OperationEnvelope(BaseModel):
    model_config = _STRICT
    operation: PlanOperation


__all__ = [
    "InsertAfterOperation",
    "MoveAfterOperation",
    "PlanEditError",
    "PlanOperation",
    "RemoveOperation",
    "SplitOperation",
    "UpdateOperation",
    "apply_plan_operations",
]
