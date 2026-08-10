from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.auth_api import get_current_user, require_admin
from app.core.project_skill_import import (
    MAX_ARCHIVE_BYTES,
    MAX_MARKDOWN_BYTES,
    parse_markdown_upload,
    parse_skill_archive,
    read_upload_limited,
)
from app.platform.dependencies import get_platform_store
from app.platform.runtime_skills import hydrate_runtime_skill_registry
from app.platform.store import PlatformStore
from app.schema.platform import (
    CapabilityToggleRequest,
    ProjectSkillCreateRequest,
    ProjectSkillUpdateRequest,
)


router = APIRouter(prefix="/api/project-skills", tags=["项目 Markdown Skills"])


def _serialize(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "markdown_content": item.markdown_content,
        "source_type": item.source_type,
        "command": item.command,
        "content_sha256": item.content_sha256,
        "version": item.version,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _refresh(store: PlatformStore) -> None:
    await hydrate_runtime_skill_registry(store)


@router.get("")
async def list_project_skills(
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items = await store.list_project_skills()
    return {
        "items": [_serialize(item) for item in items],
        "total": len(items),
        "enabled_count": sum(1 for item in items if item.enabled),
    }


@router.post("")
async def create_project_skill(
    request: ProjectSkillCreateRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.create_project_skill(
            name=request.name,
            slug=request.slug,
            description=request.description,
            markdown_content=request.markdown_content,
            source_type="created",
            enabled=request.enabled,
            actor_id=admin["user_id"],
        )
        await _refresh(store)
        return _serialize(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload")
async def upload_project_skill_markdown(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        parsed = parse_markdown_upload(
            file.filename or "", await read_upload_limited(file, MAX_MARKDOWN_BYTES)
        )
        item = await store.create_project_skill(
            name=parsed.name,
            slug=parsed.slug,
            description=parsed.description,
            markdown_content=parsed.markdown_content,
            source_type="markdown_upload",
            enabled=True,
            actor_id=admin["user_id"],
        )
        await _refresh(store)
        return _serialize(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("/import")
async def import_project_skill_package(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        parsed = parse_skill_archive(
            file.filename or "", await read_upload_limited(file, MAX_ARCHIVE_BYTES)
        )
        item = await store.create_project_skill(
            name=parsed.name,
            slug=parsed.slug,
            description=parsed.description,
            markdown_content=parsed.markdown_content,
            source_type="skill_package",
            enabled=True,
            actor_id=admin["user_id"],
        )
        await _refresh(store)
        return _serialize(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@router.patch("/{skill_id}")
async def update_project_skill(
    skill_id: str,
    request: ProjectSkillUpdateRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.update_project_skill(
            skill_id,
            name=request.name,
            description=request.description,
            markdown_content=request.markdown_content,
            actor_id=admin["user_id"],
        )
        await _refresh(store)
        return _serialize(item)
    except ValueError as exc:
        status = 404 if str(exc) == "Skill 不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.patch("/{skill_id}/enabled")
async def toggle_project_skill(
    skill_id: str,
    request: CapabilityToggleRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.set_project_skill_enabled(
            skill_id, request.enabled, actor_id=admin["user_id"]
        )
        await _refresh(store)
        return _serialize(item)
    except ValueError as exc:
        status = 404 if str(exc) == "Skill 不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
