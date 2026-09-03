from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.api.auth_api import get_current_user
from app.core.media_compositor import MEDIA_DIR
from app.core.model_gateway import ModelGateway
from app.core.storyboard_assets import MAX_REMOTE_IMAGE_BYTES, fetch_remote_image_bytes
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore, StorageMutationCommittedWithError
from app.platform.uploads import UploadValidationError, inspect_glb_upload, validate_image_upload
from app.repository.task_repo import TaskRepository, TaskStoreUnavailableError
from app.schema.platform import (
    BulkRegenerateElementsRequest,
    ElementCreateRequest,
    ElementKind,
    ElementUpdateRequest,
    RegenerateElementRequest,
)


router = APIRouter(prefix="/api/elements", tags=["演员道具场景特效元素库"])
logger = logging.getLogger(__name__)
element_image_gateway = ModelGateway()
element_task_repository = TaskRepository()

_NON_ACTOR_KINDS = {"scene", "prop", "costume", "effect"}
_generation_jobs: dict[str, dict[str, object]] = {}


def _private_image_storage_root() -> Path:
    root = Path(os.getenv(
        "ELEMENT_IMAGE_STORAGE_DIR",
        str(Path(MEDIA_DIR).parent / "runtime" / "element_images"),
    )).expanduser().resolve()
    public_media_root = Path(MEDIA_DIR).resolve()
    if root == public_media_root or public_media_root in root.parents:
        raise RuntimeError("ELEMENT_IMAGE_STORAGE_DIR must be outside the public media directory")
    return root


# New reference images are never written beneath the public /media mount.  Keep
# the legacy root read-only so existing database rows can still be served by the
# authenticated content endpoint while installations migrate their files.
ELEMENT_MEDIA_ROOT = _private_image_storage_root()
LEGACY_ELEMENT_MEDIA_ROOT = Path(MEDIA_DIR) / "elements"
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
ELEMENT_IMAGE_GENERATION_CONCURRENCY = _integer_setting(
    "ELEMENT_IMAGE_GENERATION_CONCURRENCY", 3, minimum=1, maximum=4
)


_GENERATION_KIND_PROMPTS = {
    "scene": (
        "生成一张影视拍摄场景参考图。完整展现空间结构、出入口、地面、墙体、纵深、主要光源和"
        "剧本指定的时段天气，采用可实际搭建和拍摄的写实电影美术设计。画面是单一宽幅场景定妆照，"
        "不出现抢眼人物，不做拼贴，不裁断关键建筑。"
    ),
    "prop": (
        "生成一张影视道具定妆参考图。只展示一个完整、可制作的核心道具及其剧本状态，清楚呈现"
        "比例、轮廓、材质、颜色、磨损和关键结构，三分之四视角，简洁中性背景，不出现手和人物，"
        "不做拼贴，不裁断物体。"
    ),
    "costume": (
        "生成一张影视服装造型参考图。画面主体只能是悬空陈列的中空立体服装，以隐形支撑塑造"
        "真实穿着体积与自然垂坠；无人物、无模特、无人体模型、无人台、无头部、无脸、无皮肤、"
        "无手脚。完整呈现领口、上装、下装、袖口、下摆、鞋履、材质、纹样、配饰及剧情状态，"
        "正面三分之四全身视角，中性影棚背景，不做拼贴，不裁断服装。"
    ),
    "effect": (
        "生成一张影视视觉特效定帧参考图，画面唯一视觉主体必须是特效现象本身，不是道具，"
        "不是场景，也不是普通环境空镜。准确表现剧本指定特效的形态、尺度、颜色、能量层次、"
        "粒子或流体结构、运动方向、触发点、扩散边界及光影交互；仅保留判断尺度所需的极少中性"
        "环境参照，写实可合成，无人物，无独立陈列物品，单一完整画面，不做拼贴。"
    ),
}


def _element_metadata(item) -> dict:
    return item.metadata_json if isinstance(item.metadata_json, dict) else {}


async def _element_generation_context(item, owner_id: str) -> tuple[str, str]:
    """Resolve the project's selected image model and style without trusting foreign task ids."""
    task_id = str(_element_metadata(item).get("task_id") or "").strip()
    if not task_id:
        return "", ""
    try:
        task = await run_in_threadpool(element_task_repository.get_task, task_id)
    except TaskStoreUnavailableError:
        logger.warning("资产参考图生成时任务库不可用，改用默认图像模型", extra={"task_id": task_id})
        return "", ""
    if not task or str(task.get("owner_user_id") or "") != owner_id:
        return "", ""
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    style_parts = [
        str(config.get("director_style") or "").strip(),
        str(config.get("shot_style") or "").strip(),
        str(config.get("genre") or "").strip(),
    ]
    return str(config.get("image_model") or "").strip(), "，".join(part for part in style_parts if part)


def _element_reference_prompt(item, extra_prompt: str, project_style: str) -> str:
    kind_instruction = _GENERATION_KIND_PROMPTS.get(str(item.kind), "")
    prompt = (
        f"{kind_instruction}\n"
        f"资产名称：{str(item.name).strip()}\n"
        f"剧本依据：{str(item.description or '').strip() or '按资产名称建立清晰、完整、可复用的影视参考设计'}\n"
    )
    if project_style:
        prompt += f"项目视觉基准：{project_style}\n"
    if extra_prompt.strip():
        prompt += f"本次补充要求：{extra_prompt.strip()}\n"
    return (
        prompt
        + "统一要求：主体完整位于画面安全区，结构清晰，透视正确，材质真实，细节丰富，高清写实电影质感；"
        "严禁任何文字、标签、字幕、水印、Logo、边框、九宫格、接触表和重复物体。"
    )


def _load_generated_image_bytes(url: str) -> bytes:
    value = str(url or "").strip()
    if value.startswith("data:image/"):
        try:
            encoded = value.split(",", 1)[1]
            content = base64.b64decode(encoded, validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError("图像模型返回了无效的 data URI") from exc
        if len(content) > MAX_REMOTE_IMAGE_BYTES:
            raise ValueError("生成图片超过 30 MB")
        return content
    if value.startswith(("https://", "http://")):
        return fetch_remote_image_bytes(value)
    raise ValueError("图像模型没有返回可下载的 HTTP(S) 图片地址")


def _validated_generated_image(content: bytes) -> tuple[str, str]:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
        (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
        (b"RIFF", ".webp", "image/webp"),
    )
    detected = next((entry for entry in signatures if content.startswith(entry[0])), None)
    if detected is None:
        raise ValueError("图像模型返回的文件不是受支持的 PNG、JPEG 或 WebP 图片")
    _, suffix, mime = detected
    validate_image_upload(f"generated{suffix}", mime, content, max_bytes=MAX_REMOTE_IMAGE_BYTES)
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValueError("图像模型返回的图片已损坏") from exc
    return suffix, mime


def _file(element_id: str, element_version: int, item) -> dict:
    is_model = item.mime_type == "model/gltf-binary"
    return {
        "id": item.id,
        "slot": item.slot,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "url": (
            None
            if is_model
            else f"/api/elements/{element_id}/files/{item.id}/content?v={element_version}"
        ),
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
        "files": [_file(item.id, item.version, file) for file in item.files],
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


def _owned_reference_path(
    relative_path: Path | str,
    owner_id: str,
    element_id: str,
) -> tuple[Path, Path]:
    """Resolve a private image, falling back to the authenticated legacy root."""
    candidates: list[tuple[Path, Path]] = []
    for root in (ELEMENT_MEDIA_ROOT, LEGACY_ELEMENT_MEDIA_ROOT):
        resolved_root = root.resolve()
        if any(existing_root == resolved_root for _, existing_root in candidates):
            continue
        try:
            candidate = _safe_owned_media_path(
                relative_path,
                resolved_root,
                owner_id,
                element_id,
            )
        except HTTPException:
            continue
        candidates.append((candidate, resolved_root))
        if candidate.is_file():
            return candidate, resolved_root
    if not candidates:
        raise HTTPException(status_code=422, detail="无效存储路径")
    return candidates[0]


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
                try:
                    if item.mime_type == "model/gltf-binary":
                        storage_root = ELEMENT_MODEL_ROOT.resolve()
                        original = _safe_owned_media_path(
                            item.storage_path,
                            storage_root,
                            self.owner_id,
                            self.element_id,
                        )
                    else:
                        original, storage_root = _owned_reference_path(
                            item.storage_path,
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


@router.get("/{element_id}/files/{file_id}/content")
async def get_element_file_content(
    element_id: str,
    file_id: str,
    version: int = Query(..., alias="v", ge=1),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail="元素不存在")
    if version != element.version:
        raise HTTPException(status_code=404, detail="参考图版本已更新")
    reference = next((entry for entry in element.files if entry.id == file_id), None)
    if not reference or reference.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=404, detail="参考图不存在")
    try:
        absolute, _ = _owned_reference_path(
            reference.storage_path,
            user["user_id"],
            element_id,
        )
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail="参考图文件不存在") from exc
    if not absolute.is_file():
        raise HTTPException(status_code=404, detail="参考图文件不存在")
    return FileResponse(
        absolute,
        media_type=reference.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "ETag": f'"{reference.sha256}"',
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


async def _generate_non_actor_reference(
    *,
    item,
    owner_id: str,
    store: PlatformStore,
    extra_prompt: str = "",
) -> dict:
    if str(item.kind) not in _NON_ACTOR_KINDS:
        raise HTTPException(status_code=422, detail="数字演员五视图请在角色设计工作区生成")
    image_model, project_style = await _element_generation_context(item, owner_id)
    prompt = _element_reference_prompt(item, extra_prompt, project_style)
    try:
        generated_url, provider = await run_in_threadpool(
            element_image_gateway.generate_image,
            image_model,
            prompt,
        )
        if not generated_url:
            raise RuntimeError("所有已配置图像模型均未返回图片")
        content = await run_in_threadpool(_load_generated_image_bytes, generated_url)
        suffix, mime = await run_in_threadpool(_validated_generated_image, content)
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "资产参考图生成失败: element=%s kind=%s provider=%s error=%s",
            item.id,
            item.kind,
            locals().get("provider"),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="参考图生成失败，图像模型未返回可验证的图片；请检查模型配置后重试",
        ) from exc
    return await _persist_element_file(
        element_id=item.id,
        owner_id=owner_id,
        slot="reference",
        suffix=suffix,
        mime=mime,
        content=content,
        store=store,
    )


def _public_generation_job(job: dict[str, object]) -> dict[str, object]:
    return {
        "id": job["id"],
        "kind": job["kind"],
        "task_id": job.get("task_id"),
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "succeeded": job["succeeded"],
        "failed": job["failed"],
        "remaining": job["remaining"],
        "errors": list(job.get("errors") or []),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def _prune_generation_jobs() -> None:
    if len(_generation_jobs) < 200:
        return
    completed = sorted(
        (
            job for job in _generation_jobs.values()
            if job.get("status") in {"completed", "partial", "failed"}
        ),
        key=lambda job: float(job.get("updated_at") or 0),
    )
    for job in completed[: max(0, len(_generation_jobs) - 150)]:
        _generation_jobs.pop(str(job["id"]), None)


async def _run_generation_job(
    job_id: str,
    items: list,
    *,
    owner_id: str,
    store: PlatformStore,
) -> None:
    job = _generation_jobs.get(job_id)
    if not job:
        return
    job["status"] = "running"
    job["updated_at"] = time.time()
    semaphore = asyncio.Semaphore(ELEMENT_IMAGE_GENERATION_CONCURRENCY)
    replace_existing = bool(job.get("replace_existing"))

    async def generate_one(item) -> None:
        async with semaphore:
            try:
                current = await store.get_element(item.id, owner_id)
                if not current:
                    raise ValueError("资产不存在")
                if any(file.mime_type.startswith("image/") for file in current.files) and not replace_existing:
                    job["succeeded"] = int(job["succeeded"]) + 1
                else:
                    await _generate_non_actor_reference(
                        item=current,
                        owner_id=owner_id,
                        store=store,
                        extra_prompt="按剧本资产描述生成可直接用于本项目的完整参考图",
                    )
                    job["succeeded"] = int(job["succeeded"]) + 1
            except (Exception, asyncio.CancelledError) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                job["failed"] = int(job["failed"]) + 1
                errors = job.get("errors")
                if isinstance(errors, list) and len(errors) < 20:
                    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    errors.append({"element_id": item.id, "name": item.name, "detail": str(detail)[:300]})
            finally:
                job["processed"] = int(job["succeeded"]) + int(job["failed"])
                job["remaining"] = max(0, int(job["total"]) - int(job["processed"]))
                job["updated_at"] = time.time()

    try:
        await asyncio.gather(*(generate_one(item) for item in items))
    except asyncio.CancelledError:
        job["status"] = "partial" if int(job["succeeded"]) else "failed"
        job["updated_at"] = time.time()
        raise
    else:
        job["status"] = "completed" if int(job["failed"]) == 0 else "partial"
        job["updated_at"] = time.time()


@router.post("/generation-jobs", status_code=202)
async def start_element_generation_job(
    request: BulkRegenerateElementsRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    if request.kind not in _NON_ACTOR_KINDS:
        raise HTTPException(status_code=422, detail="批量参考图生成仅支持场景、道具、服装和特效")
    owner_id = user["user_id"]
    items, _ = await store.list_elements(owner_id, request.kind, 1, 100)
    task_id = str(request.task_id or "").strip()
    candidates = [
        item for item in items
        if (not task_id or str(_element_metadata(item).get("task_id") or "") == task_id)
        and (
            request.replace_existing
            or not any(file.mime_type.startswith("image/") for file in item.files)
        )
    ]
    for existing in _generation_jobs.values():
        if (
            existing.get("owner_id") == owner_id
            and existing.get("kind") == request.kind
            and existing.get("task_id") == (task_id or None)
            and bool(existing.get("replace_existing")) == request.replace_existing
            and existing.get("status") in {"queued", "running"}
        ):
            return _public_generation_job(existing)

    _prune_generation_jobs()
    now = time.time()
    job_id = str(uuid.uuid4())
    job: dict[str, object] = {
        "id": job_id,
        "owner_id": owner_id,
        "kind": request.kind,
        "task_id": task_id or None,
        "replace_existing": request.replace_existing,
        "status": "queued" if candidates else "completed",
        "total": len(candidates),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": len(candidates),
        "errors": [],
        "created_at": now,
        "updated_at": now,
    }
    _generation_jobs[job_id] = job
    if candidates:
        background_tasks.add_task(
            _run_generation_job,
            job_id,
            candidates,
            owner_id=owner_id,
            store=store,
        )
    return _public_generation_job(job)


@router.get("/generation-jobs/{job_id}")
async def get_element_generation_job(
    job_id: str,
    user: dict = Depends(get_current_user),
):
    job = _generation_jobs.get(job_id)
    if not job or job.get("owner_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="图片生成任务不存在")
    return _public_generation_job(job)


@router.post("/{element_id}/regenerate")
async def regenerate_element(
    element_id: str,
    request: RegenerateElementRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail="元素不存在")
    if str(element.kind) in _NON_ACTOR_KINDS:
        return await _generate_non_actor_reference(
            item=element,
            owner_id=user["user_id"],
            store=store,
            extra_prompt=request.prompt,
        )
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
