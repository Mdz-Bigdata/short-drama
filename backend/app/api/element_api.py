from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth_api import get_current_user
from app.core.media_compositor import MEDIA_DIR
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore, StorageMutationCommittedWithError
from app.platform.uploads import UploadValidationError, inspect_glb_upload, validate_image_upload
from app.schema.platform import ElementCreateRequest, ElementKind, ElementUpdateRequest, RegenerateElementRequest


router = APIRouter(prefix="/api/elements", tags=["演员道具场景特效元素库"])
logger = logging.getLogger(__name__)
ELEMENT_MEDIA_ROOT = Path(MEDIA_DIR) / "elements"
ELEMENT_MODEL_ROOT = Path(os.getenv(
    "ELEMENT_MODEL_STORAGE_DIR",
    str(Path(MEDIA_DIR).parent / "runtime" / "element_models"),
))


def _integer_setting(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


ELEMENT_STORAGE_MIN_FREE_BYTES = _integer_setting(
    "ELEMENT_STORAGE_MIN_FREE_BYTES", 5 * 1024**3, minimum=512 * 1024**2, maximum=1024**4
)
ELEMENT_STORAGE_MAX_USED_PERCENT = _integer_setting(
    "ELEMENT_STORAGE_MAX_USED_PERCENT", 98, minimum=80, maximum=99
)


def _file(item) -> dict:
    relative = item.storage_path.replace(os.sep, "/")
    is_model = item.mime_type == "model/gltf-binary"
    return {
        "id": item.id,
        "slot": item.slot,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "url": None if is_model else f"/media/elements/{relative}",
        "media_kind": "model" if is_model else "image",
    }


def _model3d(item) -> dict | None:
    model = next((file for file in item.files if file.slot == "model_glb"), None)
    if not model:
        return None
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    stored = metadata.get("model3d") if isinstance(metadata.get("model3d"), dict) else {}
    return {
        "schemaVersion": "element-model.v1",
        "state": "ready",
        "format": "glb",
        "contentUrl": f"/api/elements/{item.id}/model/content?v={item.version}",
        "sha256": model.sha256,
        "sizeBytes": model.size_bytes,
        "stats": stored.get("stats", {}),
        "validation": stored.get("validation", {"passed": True, "warnings": []}),
        "unit": stored.get("unit", "meter"),
        "upAxis": stored.get("upAxis", "Y"),
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
        "model3d": _model3d(item),
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
        safe_metadata = {key: value for key, value in request.metadata.items() if key != "model3d"}
        item = await store.create_element(
            owner_id=user["user_id"], kind=request.kind, name=request.name,
            description=request.description, metadata=safe_metadata,
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
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail="元素不存在")

    filename = file.filename or ""
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        mime = validate_image_upload(filename, file.content_type or "", content)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[mime]
    return await _persist_element_file(
        element_id=element_id,
        owner_id=user["user_id"],
        slot=slot,
        suffix=suffix,
        mime=mime,
        content=content,
        store=store,
    )


def _safe_media_path(relative_path: Path | str, storage_root: Path | None = None) -> Path:
    root = (storage_root or ELEMENT_MEDIA_ROOT).resolve()
    absolute = (root / relative_path).resolve()
    if root not in absolute.parents:
        raise HTTPException(status_code=422, detail="无效存储路径")
    return absolute


def _safe_owned_media_path(
    relative_path: Path | str,
    storage_root: Path,
    owner_id: str,
    element_id: str,
) -> Path:
    root = storage_root.resolve()
    owned_element_root = (root / owner_id / element_id).resolve()
    if root not in owned_element_root.parents:
        raise HTTPException(status_code=422, detail="无效存储路径")
    absolute = _safe_media_path(relative_path, storage_root)
    if owned_element_root not in absolute.parents:
        raise HTTPException(status_code=422, detail="无效存储路径")
    return absolute


def _remove_file(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class _QuarantinedFile:
    original: Path
    quarantined: Path
    manifest: Path


class _DeletionQuarantine:
    """Moves public files aside atomically before their database rows commit."""

    def __init__(self, owner_id: str, element_id: str, *, operation: str = "delete"):
        self.owner_id = owner_id
        self.element_id = element_id
        self.operation = operation
        self.transaction_id = uuid.uuid4().hex
        self._files: list[_QuarantinedFile] = []

    @staticmethod
    def _root(storage_root: Path) -> Path:
        resolved = storage_root.resolve()
        # ELEMENT_MEDIA_ROOT lives directly inside the public StaticFiles
        # mount, so its sibling would still be web-readable. Place quarantine
        # beside that mount instead. os.replace verifies the same-filesystem
        # assumption and fails closed on EXDEV.
        public_container = resolved.parent
        return (
            public_container.parent
            / f".{public_container.name}-{resolved.name}-quarantine"
        )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_manifest(self, item: _QuarantinedFile) -> None:
        item.manifest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = item.manifest.with_suffix(".tmp")
        payload = {
            "schema_version": "element-quarantine.v1",
            "transaction_id": self.transaction_id,
            "owner_id": self.owner_id,
            "element_id": self.element_id,
            "operation": self.operation,
            "original_path": str(item.original),
            "quarantined_path": str(item.quarantined),
        }
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, item.manifest)
            self._fsync_directory(item.manifest.parent)
        except BaseException:
            _remove_file(temporary)
            raise

    @staticmethod
    def _cleanup_empty_directories(item: _QuarantinedFile) -> None:
        for directory in (item.manifest.parent, item.manifest.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass

    @staticmethod
    def _mapping(item: _QuarantinedFile) -> str:
        return f"original={item.original} quarantined={item.quarantined} manifest={item.manifest}"

    def log_stranded(self, message: str) -> None:
        for item in self._files:
            logger.error(
                "%s: %s",
                message,
                self._mapping(item),
                extra={"owner_id": self.owner_id, "element_id": self.element_id},
            )

    async def stage(self, files) -> dict[str, object]:
        skipped_ids: list[str] = []
        missing_ids: list[str] = []
        try:
            for item in files:
                storage_root = (
                    ELEMENT_MODEL_ROOT
                    if item.mime_type == "model/gltf-binary"
                    else ELEMENT_MEDIA_ROOT
                )
                try:
                    original = _safe_owned_media_path(
                        item.storage_path,
                        storage_root,
                        self.owner_id,
                        self.element_id,
                    )
                except HTTPException:
                    skipped_ids.append(item.id)
                    logger.warning(
                        "%s cleanup skipped path outside owned element directory",
                        self.operation,
                        extra={
                            "owner_id": self.owner_id,
                            "element_id": self.element_id,
                            "file_id": item.id,
                        },
                    )
                    continue
                if not original.is_file():
                    missing_ids.append(item.id)
                    continue

                quarantine_root = self._root(storage_root)
                transaction_root = quarantine_root / self.transaction_id
                file_token = uuid.uuid4().hex
                quarantined = transaction_root / f"{file_token}.asset"
                manifest = transaction_root / f"{file_token}.json"
                quarantined_file = _QuarantinedFile(original, quarantined, manifest)
                self._write_manifest(quarantined_file)
                self._files.append(quarantined_file)
                os.replace(original, quarantined)
        except OSError as exc:
            try:
                self.restore()
            except OSError:
                self.log_stranded("failed to restore partially quarantined element files")
            raise HTTPException(status_code=500, detail="资产文件隔离失败，删除未执行") from exc
        return {
            "quarantined_count": len(self._files),
            "skipped_unowned_file_ids": skipped_ids,
            "missing_file_ids": missing_ids,
        }

    def restore(self) -> None:
        failures: list[OSError] = []
        remaining: list[_QuarantinedFile] = []
        for item in reversed(self._files):
            if not item.quarantined.exists() and item.original.exists():
                _remove_file(item.manifest)
                self._cleanup_empty_directories(item)
                continue
            try:
                item.original.parent.mkdir(parents=True, exist_ok=True)
                os.replace(item.quarantined, item.original)
                _remove_file(item.manifest)
                self._cleanup_empty_directories(item)
            except OSError as exc:
                failures.append(exc)
                remaining.append(item)
        self._files = list(reversed(remaining))
        if failures:
            raise OSError("一个或多个隔离文件恢复失败") from failures[0]

    def purge(self) -> None:
        remaining: list[_QuarantinedFile] = []
        for item in self._files:
            if not _remove_file(item.quarantined):
                logger.warning(
                    "failed to purge non-public element quarantine file: %s",
                    self._mapping(item),
                    extra={
                        "owner_id": self.owner_id,
                        "element_id": self.element_id,
                    },
                )
                remaining.append(item)
                continue
            _remove_file(item.manifest)
            self._cleanup_empty_directories(item)
        self._files = remaining


def _restore_quarantine(plan: _DeletionQuarantine, error: BaseException) -> None:
    try:
        plan.restore()
    except OSError as restore_error:
        plan.log_stranded("database mutation failed and quarantined files could not all be restored")
        error.add_note(f"quarantine restore failed: {restore_error}")


def _ensure_disk_capacity(storage_root: Path, incoming_bytes: int) -> None:
    probe = storage_root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    projected_free = usage.free - incoming_bytes
    projected_used_percent = ((usage.used + incoming_bytes) / usage.total) * 100
    if (
        projected_free < ELEMENT_STORAGE_MIN_FREE_BYTES
        or projected_used_percent >= ELEMENT_STORAGE_MAX_USED_PERCENT
    ):
        raise HTTPException(status_code=507, detail="资产存储空间不足，已触发磁盘高水位保护")


async def _persist_element_file(
    *,
    element_id: str,
    owner_id: str,
    slot: str,
    suffix: str,
    mime: str,
    content: bytes,
    store: PlatformStore,
    model_metadata: dict | None = None,
    storage_root: Path | None = None,
) -> dict:
    target_root = storage_root or ELEMENT_MEDIA_ROOT
    relative_dir = Path(owner_id) / element_id
    relative_path = relative_dir / f"{uuid.uuid4().hex}{suffix}"
    absolute = _safe_media_path(relative_path, target_root)
    _ensure_disk_capacity(target_root, len(content))
    absolute.parent.mkdir(parents=True, exist_ok=True)
    try:
        await run_in_threadpool(absolute.write_bytes, content)
    except (Exception, asyncio.CancelledError):
        _remove_file(absolute)
        raise
    quarantine = _DeletionQuarantine(owner_id, element_id, operation="replacement")
    try:
        stored = await store.add_element_file(
            element_id=element_id,
            owner_id=owner_id,
            slot=slot,
            storage_path=str(relative_path),
            mime_type=mime,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            model_metadata=model_metadata,
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        _remove_file(absolute)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        _remove_file(absolute)
        raise
    quarantine.purge()
    return _element(stored.element)


@router.delete("/{element_id}/files/{file_id}")
async def delete_element_file(
    element_id: str,
    file_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    quarantine = _DeletionQuarantine(user["user_id"], element_id)
    try:
        deleted = await store.delete_element_file(
            element_id,
            file_id,
            user["user_id"],
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        raise
    quarantine.purge()
    return _element(deleted.element)


@router.delete("/{element_id}")
async def delete_element(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    quarantine = _DeletionQuarantine(user["user_id"], element_id)
    try:
        deleted = await store.delete_element(
            element_id,
            user["user_id"],
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        raise
    quarantine.purge()
    return {"id": deleted.element_id, "deleted": True}


@router.post("/{element_id}/model")
async def upload_element_model(
    element_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail="元素不存在")
    if element.kind not in {"prop", "scene"}:
        raise HTTPException(status_code=422, detail="只有场景和道具元素可以上传 3D 模型")

    content = await file.read(25 * 1024 * 1024 + 1)
    max_triangles = 1_000_000 if element.kind == "prop" else 2_000_000
    try:
        stats = await run_in_threadpool(
            inspect_glb_upload,
            file.filename or "",
            file.content_type or "",
            content,
            max_triangles=max_triangles,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    recommended_triangles = 150_000 if element.kind == "prop" else 500_000
    warnings = []
    if stats["triangles"] > recommended_triangles:
        warnings.append(f"建议将三角面优化到 {recommended_triangles:,} 以下")
    if len(content) > 5 * 1024 * 1024:
        warnings.append("建议将 Web 展示模型优化到 5 MB 以下")
    sha256 = hashlib.sha256(content).hexdigest()
    return await _persist_element_file(
        element_id=element_id,
        owner_id=user["user_id"],
        slot="model_glb",
        suffix=".glb",
        mime="model/gltf-binary",
        content=content,
        store=store,
        model_metadata={
            "schemaVersion": "element-model.v1",
            "format": "glb",
            "unit": "meter",
            "upAxis": "Y",
            "sourceHash": sha256,
            "stats": stats,
            "validation": {"passed": True, "warnings": warnings},
        },
        storage_root=ELEMENT_MODEL_ROOT,
    )


@router.get("/{element_id}/model/content")
async def get_element_model_content(
    element_id: str,
    version: int | None = Query(default=None, alias="v", ge=1),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail="元素不存在")
    if version is not None and version != element.version:
        raise HTTPException(status_code=404, detail="3D 模型版本已更新")
    model = next((entry for entry in element.files if entry.slot == "model_glb"), None)
    if not model:
        raise HTTPException(status_code=404, detail="3D 模型不存在")
    absolute = _safe_media_path(model.storage_path, ELEMENT_MODEL_ROOT)
    if not absolute.is_file():
        raise HTTPException(status_code=404, detail="3D 模型文件不存在")
    return FileResponse(
        absolute,
        media_type="model/gltf-binary",
        headers={
            # Authenticated model responses must never be retained by a shared
            # browser/proxy cache and replayed after an account switch.
            "Cache-Control": "private, no-store",
            "ETag": f'"{model.sha256}"',
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
