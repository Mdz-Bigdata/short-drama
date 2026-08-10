from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.auth_api import get_current_user
from app.core.media_compositor import MEDIA_DIR
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.platform.uploads import UploadValidationError, validate_image_upload
from app.schema.platform import ElementCreateRequest, ElementKind, ElementUpdateRequest, RegenerateElementRequest


router = APIRouter(prefix="/api/elements", tags=["演员道具场景特效元素库"])
ELEMENT_MEDIA_ROOT = Path(MEDIA_DIR) / "elements"


def _file(item) -> dict:
    relative = item.storage_path.replace(os.sep, "/")
    return {
        "id": item.id,
        "slot": item.slot,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "url": f"/media/elements/{relative}",
    }


def _element(item) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "version": item.version,
        "metadata": item.metadata_json,
        "files": [_file(file) for file in item.files],
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("")
async def list_elements(
    kind: ElementKind,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items, total = await store.list_elements(user["user_id"], kind, page, page_size)
    return {"items": [_element(item) for item in items], "page": page, "page_size": page_size, "total": total}


@router.post("")
async def create_element(
    request: ElementCreateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.create_element(
            owner_id=user["user_id"], kind=request.kind, name=request.name,
            description=request.description, metadata=request.metadata,
        )
        item = await store.get_element(item.id, user["user_id"])
        return _element(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{element_id}")
async def get_element(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    item = await store.get_element(element_id, user["user_id"])
    if not item:
        raise HTTPException(status_code=404, detail="元素不存在")
    return _element(item)


@router.patch("/{element_id}")
async def update_element(
    element_id: str,
    request: ElementUpdateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return _element(await store.update_element(
            element_id, user["user_id"], name=request.name, description=request.description
        ))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{element_id}/files")
async def upload_element_file(
    element_id: str,
    slot: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        mime = validate_image_upload(file.filename or "", file.content_type or "", content)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
    relative_dir = Path(user["user_id"]) / element_id
    relative_path = relative_dir / f"{uuid.uuid4().hex}{suffix}"
    absolute = (ELEMENT_MEDIA_ROOT / relative_path).resolve()
    root = ELEMENT_MEDIA_ROOT.resolve()
    if root not in absolute.parents:
        raise HTTPException(status_code=422, detail="无效存储路径")
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(content)
    try:
        item = await store.add_element_file(
            element_id=element_id,
            owner_id=user["user_id"],
            slot=slot,
            storage_path=str(relative_path),
            mime_type=mime,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        return _element(item)
    except ValueError as exc:
        absolute.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{element_id}/regenerate")
async def regenerate_element(
    element_id: str,
    request: RegenerateElementRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        job = await store.request_regeneration(element_id, user["user_id"], request.prompt)
        return {
            "id": job.id,
            "element_id": job.element_id,
            "status": job.status,
            "paid_submission_approved": job.paid_submission_approved,
            "created_at": job.created_at,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
