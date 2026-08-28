import hashlib
import logging
import os
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, HTTPException, BackgroundTasks, Form, File, UploadFile, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from typing import List, Dict, Any, Optional
from app.schema.drama import (
    DramaCreateRequest,
    DramaTaskResponse,
    DramaTaskSummary,
    ScriptUpdateRequest,
)
from app.service.drama_service import DramaService, ScriptUpdateConflictError
from app.repository.task_repo import TaskRepository
from app.api.auth_api import get_current_user, require_admin
from app.core.media_compositor import MEDIA_DIR
from app.core.production_asset_extractor import extract_production_assets
from app.core.storyboard_assets import compose_nine_grid, fetch_remote_image_bytes
from app.core.writer_dashboard import compile_writer_dashboard
from app.api.element_api import _persist_element_file
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.platform.uploads import validate_image_upload
from starlette.concurrency import run_in_threadpool
from app.core.video_quality import VideoQualityMeasurements
from app.schema.agent_council import CouncilReleaseEvidence
from app.schema.writer_dashboard import (
    ScriptDocument,
    ScriptDocumentCreateRequest,
    ScriptDocumentDetail,
    ScriptDocumentUpdateRequest,
    ScriptLibraryResponse,
    WriterDashboardResponse,
    WriterRelationshipUpdateRequest,
)
from app.schema.character_dashboard import CharacterDashboardResponse

logger = logging.getLogger("app.api.drama_api")
service = DramaService()
repo = TaskRepository()


def require_owned_drama_task(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Enforce per-task ownership for every route containing a task_id."""
    task_id = request.path_params.get("task_id")
    if not task_id:
        return current_user

    task = service.repo.get_task(str(task_id))
    if not task:
        # Fail closed: a transient repository read failure must never let the
        # handler perform a second, unauthorised read that happens to succeed.
        raise HTTPException(status_code=404, detail="任务不存在")

    if current_user.get("role") == "admin":
        return current_user

    user_id = str(current_user.get("user_id") or "")
    owner_user_id = str(task.get("owner_user_id") or "")
    if not user_id or not owner_user_id or user_id != owner_user_id:
        # Hide task existence from users who do not own it.
        raise HTTPException(status_code=404, detail="任务不存在")
    return current_user


# 登录校验与任务归属校验在同一路由边界内统一执行。
router = APIRouter(
    prefix="/api/drama",
    tags=["AI短剧制作"],
    dependencies=[Depends(require_owned_drama_task)],
)

@router.post("/create", response_model=DramaTaskResponse)
def create_new_task(req: DramaCreateRequest, current_user: dict = Depends(get_current_user)):
    """
    新建一个 AI 短剧任务。
    如果是一键成片，则初始化后可直接一键生成。
    """
    try:
        task_data = service.create_task(req, owner_user_id=current_user.get("user_id"))
        return task_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")

@router.get("/list", response_model=List[DramaTaskSummary])
def get_all_tasks(current_user: dict = Depends(get_current_user)):
    """List the caller's projects for the lobby.

    Returns summaries only: the generated assets are the bulk of a task and the
    list is polled, so they are fetched per project through /{task_id}/status.
    """
    tasks = service.repo.list_all_tasks()
    if current_user.get("role") != "admin":
        user_id = str(current_user.get("user_id") or "")
        tasks = (
            [
                task for task in tasks
                if isinstance(task, dict) and str(task.get("owner_user_id") or "") == user_id
            ]
            if user_id else []
        )
    return [task for task in tasks if isinstance(task, dict) and task.get("task_id")]

@router.get("/{task_id}/status", response_model=DramaTaskResponse)
def get_task_status(task_id: str):
    """
    获取单条任务的状态 (提供断点续传的中间结果)
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{task_id}/writer-dashboard/export")
def export_writer_dashboard(task_id: str):
    """Download the normalized Writer Agent dashboard as versioned JSON."""
    dashboard = service.get_writer_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(
        content=dashboard.model_dump(mode="json", by_alias=True),
        headers={"Content-Disposition": 'attachment; filename="writer-dashboard.json"'},
    )


@router.get("/{task_id}/writer-dashboard", response_model=WriterDashboardResponse)
def get_writer_dashboard(task_id: str):
    """Return the Writer Agent timeline, episodes, statistics and relationship graph contract."""
    dashboard = service.get_writer_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dashboard


_EXTRACTABLE_ASSET_KINDS = {"actor", "scene", "prop", "costume", "effect"}
_IMAGE_SUFFIX_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _local_media_bytes(path: str) -> Optional[bytes]:
    """Read a /media/... file without leaving the media root."""
    media_root = os.path.realpath(MEDIA_DIR)
    absolute = os.path.realpath(os.path.join(media_root, unquote(path[len("/media/"):])))
    if not absolute.startswith(media_root + os.sep) or not os.path.isfile(absolute):
        return None
    with open(absolute, "rb") as handle:
        return handle.read()


def _extracted_image_bytes(url: str) -> Optional[bytes]:
    """Fetch one screenplay-derived reference image, local or remote."""
    parsed = urlparse(url)
    if parsed.path.startswith("/media/"):
        return _local_media_bytes(parsed.path)
    if parsed.scheme in {"http", "https"}:
        try:
            return fetch_remote_image_bytes(url)
        except Exception:
            return None
    return None


async def _attach_extracted_image(
    *,
    element_id: str,
    owner_id: str,
    kind: str,
    url: str,
    store: PlatformStore,
) -> bool:
    """Best-effort: a missing image must never fail the whole import."""
    try:
        content = await run_in_threadpool(_extracted_image_bytes, url)
        if not content:
            return False
        suffix = os.path.splitext(urlparse(url).path)[1].lower()
        if suffix == ".jpeg":
            suffix = ".jpg"
        if suffix not in _IMAGE_SUFFIX_BY_MIME.values():
            suffix = ".png"
        mime = next(key for key, value in _IMAGE_SUFFIX_BY_MIME.items() if value == suffix)
        validated = validate_image_upload(f"reference{suffix}", mime, content)
        await _persist_element_file(
            element_id=element_id,
            owner_id=owner_id,
            slot="front" if kind == "actor" else "reference",
            suffix=suffix,
            mime=validated,
            content=content,
            store=store,
        )
        return True
    except Exception:
        logger.warning("提取资产参考图附加失败: element=%s kind=%s", element_id, kind)
        return False


@router.get("/{task_id}/production-assets/{kind}")
def preview_production_assets(task_id: str, kind: str):
    """Preview the shooting assets of one kind that the screenplay names."""
    if kind not in _EXTRACTABLE_ASSET_KINDS:
        raise HTTPException(status_code=404, detail="不支持的资产类型")
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    assets = extract_production_assets(task, kind)
    return {"kind": kind, "items": assets, "total": len(assets)}


@router.post("/{task_id}/production-assets/{kind}/import")
async def import_production_assets(
    task_id: str,
    kind: str,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Import screenplay-derived shooting assets into the user's element library."""
    if kind not in _EXTRACTABLE_ASSET_KINDS:
        raise HTTPException(status_code=404, detail="不支持的资产类型")
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    candidates = extract_production_assets(task, kind)
    if not candidates:
        return {"kind": kind, "created": 0, "skipped": 0, "items": []}

    existing, _ = await store.list_elements(current_user["user_id"], kind, 1, 100)
    known = {str(item.name).strip() for item in existing}
    created: list[dict] = []
    skipped = 0
    with_image = 0
    for candidate in candidates:
        name = candidate["name"].strip()
        if not name or name in known:
            skipped += 1
            continue
        try:
            element = await store.create_element(
                owner_id=current_user["user_id"],
                kind=kind,
                name=name,
                description=candidate["description"],
                metadata={"source": "screenplay-extraction", "task_id": task_id},
            )
        except ValueError as exc:
            # Quota exhaustion stops the import; everything already created stays.
            if created:
                break
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        known.add(name)
        attached = False
        image_url = str(candidate.get("image_url") or "").strip()
        if image_url:
            attached = await _attach_extracted_image(
                element_id=element.id,
                owner_id=current_user["user_id"],
                kind=kind,
                url=image_url,
                store=store,
            )
            if attached:
                with_image += 1
        created.append({"id": element.id, "name": element.name, "image": attached})

    return {
        "kind": kind,
        "created": len(created),
        "skipped": skipped,
        "with_image": with_image,
        "items": created,
    }


@router.get("/{task_id}/script-documents", response_model=ScriptLibraryResponse)
def list_script_documents(task_id: str):
    """List the project's screenplay library (.txt / .md reference documents)."""
    documents = service.list_script_documents(task_id)
    if documents is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ScriptLibraryResponse(documents=documents, total=len(documents))


@router.post("/{task_id}/script-documents", response_model=ScriptDocument, status_code=201)
def create_script_document(task_id: str, req: ScriptDocumentCreateRequest):
    """Add one screenplay document to the project's library."""
    try:
        document = service.create_script_document(task_id, name=req.name, content=req.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return document


@router.get("/{task_id}/script-documents/{document_id}", response_model=ScriptDocumentDetail)
def get_script_document(task_id: str, document_id: str):
    """Read one screenplay document, including its full text."""
    document = service.get_script_document(task_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="剧本文件不存在")
    return document


@router.patch("/{task_id}/script-documents/{document_id}", response_model=ScriptDocumentDetail)
def update_script_document(task_id: str, document_id: str, req: ScriptDocumentUpdateRequest):
    """Rename or rewrite one screenplay document."""
    if req.name is None and req.content is None:
        raise HTTPException(status_code=422, detail="请至少提供文件名或内容")
    try:
        document = service.update_script_document(
            task_id, document_id, name=req.name, content=req.content
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="剧本文件不存在")
    return document


@router.delete("/{task_id}/script-documents/{document_id}")
def delete_script_document(task_id: str, document_id: str):
    """Permanently remove one screenplay document from the library."""
    removed = service.delete_script_document(task_id, document_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not removed:
        raise HTTPException(status_code=404, detail="剧本文件不存在")
    return {"deleted": True, "id": document_id}


@router.put("/{task_id}/relationships", response_model=WriterDashboardResponse)
def update_writer_relationships(task_id: str, req: WriterRelationshipUpdateRequest):
    """Replace the character relationship list with a user-edited version."""
    relationships = [
        item.model_dump(mode="json", by_alias=True)
        for item in req.relationships
        if item.from_.strip() and item.to.strip() and item.from_.strip() != item.to.strip()
    ]
    dashboard = service.update_relationships(task_id, relationships)
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dashboard


_STORYBOARD_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _storyboard_attachment(url: str, filename_base: str):
    """Serve a task-owned storyboard image URL as a file download."""
    parsed = urlparse(url)
    extension = os.path.splitext(parsed.path)[1].lower()
    if extension not in _STORYBOARD_IMAGE_TYPES:
        extension = ".png"
    media_type = _STORYBOARD_IMAGE_TYPES[extension]
    filename = f"{filename_base}{extension}"
    disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"

    if parsed.path.startswith("/media/") and parsed.scheme in {"http", "https", ""}:
        media_root = os.path.realpath(MEDIA_DIR)
        local_path = os.path.realpath(
            os.path.join(media_root, unquote(parsed.path[len("/media/"):]))
        )
        if not local_path.startswith(media_root + os.sep) or not os.path.isfile(local_path):
            raise HTTPException(status_code=404, detail="分镜图文件不存在")
        return FileResponse(
            local_path,
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )

    if parsed.scheme in {"http", "https"}:
        try:
            payload = fetch_remote_image_bytes(url)
        except Exception:
            raise HTTPException(status_code=502, detail="分镜图下载失败，请稍后重试")
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )
    raise HTTPException(status_code=404, detail="分镜图地址无效")


def _scene_grid_attachment(shots: list, scene_id: str):
    """Compose and serve one scene's own 3x3 board so the file matches its name."""
    sources = [
        str(entry.get("image_url")).strip()
        for entry in shots
        if isinstance(entry, dict) and str(entry.get("image_url") or "").strip()
    ][:9]
    if not sources:
        raise HTTPException(status_code=404, detail="该分镜场景尚未生成图片")
    safe_scene = "".join(ch for ch in scene_id if ch.isalnum() or ch in "-_")[:40] or "scene"
    digest = hashlib.sha256("\n".join(sources).encode("utf-8")).hexdigest()[:16]
    target_path = os.path.join(MEDIA_DIR, "storyboards", f"scene_{safe_scene}_{digest}.png")
    if not os.path.isfile(target_path):
        try:
            compose_nine_grid(sources, target_path)
        except Exception:
            raise HTTPException(status_code=502, detail="分镜场景合成失败，请稍后重试")
    filename = f"storyboard-{safe_scene}.png"
    disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    return FileResponse(
        target_path,
        media_type="image/png",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{task_id}/storyboard/download")
def download_storyboard_image(
    task_id: str,
    target: str = "grid",
    shot: int = -1,
    scene: str = "",
):
    """Download the whole board, one scene's own board, or a single frame."""
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}

    if target == "grid":
        grid_url = assets.get("4_grid")
        if not isinstance(grid_url, str) or not grid_url.strip():
            raise HTTPException(status_code=404, detail="分镜合成图尚未生成")
        return _storyboard_attachment(grid_url.strip(), "storyboard-grid")

    if target == "scene":
        scene_id = scene.strip()
        if not scene_id:
            raise HTTPException(status_code=404, detail="缺少分镜场景标识")
        shots = assets.get("4")
        if not isinstance(shots, list):
            raise HTTPException(status_code=404, detail="分镜画格不存在")
        scene_shots = [
            entry for entry in shots
            if isinstance(entry, dict)
            and str(entry.get("scene_id") or entry.get("sceneId") or "").strip() == scene_id
        ]
        if not scene_shots:
            raise HTTPException(status_code=404, detail="该分镜场景不存在")
        return _scene_grid_attachment(scene_shots, scene_id)

    if target != "shot":
        raise HTTPException(status_code=404, detail="不支持的下载目标")
    shots = assets.get("4")
    if not isinstance(shots, list) or not 0 <= shot < len(shots):
        raise HTTPException(status_code=404, detail="分镜画格不存在")
    entry = shots[shot] if isinstance(shots[shot], dict) else {}
    image_url = entry.get("image_url")
    if not isinstance(image_url, str) or not image_url.strip():
        raise HTTPException(status_code=404, detail="该分镜画格尚未生成图片")
    scene_id = str(entry.get("scene_id") or entry.get("sceneId") or "scene").strip() or "scene"
    safe_scene = "".join(ch for ch in scene_id if ch.isalnum() or ch in "-_")[:40] or "scene"
    return _storyboard_attachment(image_url.strip(), f"storyboard-{safe_scene}-{shot + 1:02d}")


@router.patch("/{task_id}/script", response_model=WriterDashboardResponse)
def update_script(
    task_id: str,
    request: ScriptUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save an edited .md/.txt screenplay and return its rebuilt dashboard."""
    try:
        dashboard = service.update_script(
            task_id,
            content=request.content,
            file_name=request.file_name,
            expected_source_hash=request.expected_source_hash,
            confirm_invalidate=request.confirm_invalidate,
            owner_user_id=str(current_user.get("user_id") or ""),
            is_admin=current_user.get("role") == "admin",
        )
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dashboard


@router.get("/{task_id}/character-dashboard/export")
def export_character_dashboard(task_id: str):
    """Download the normalized Character Designer five-view contract as JSON."""
    dashboard = service.get_character_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(
        content=dashboard.model_dump(mode="json", by_alias=True),
        headers={
            "Content-Disposition": 'attachment; filename="character-dashboard.json"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{task_id}/character-dashboard", response_model=CharacterDashboardResponse)
def get_character_dashboard(task_id: str):
    """Return the Character Designer cards, fixed five-view slots and quality state."""
    dashboard = service.get_character_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dashboard

@router.post("/{task_id}/next", response_model=DramaTaskResponse)
async def run_next_stage(task_id: str, current_stage: int):
    """
    一步一步引导模式：启动执行指定步骤阶段
    """
    try:
        updated_task = await service.execute_stage(task_id, current_stage)
        return updated_task
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行第 {current_stage} 阶段出错: {str(e)}")

@router.post("/{task_id}/pause", response_model=DramaTaskResponse)
def pause_running_task(task_id: str):
    """
    暂停正在执行中的一键成片任务 (断点锁定)
    """
    task = service.pause_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@router.post("/{task_id}/resume", response_model=DramaTaskResponse)
def resume_paused_task(task_id: str, background_tasks: BackgroundTasks):
    """
    恢复被暂停的任务，并自动在后台线程中继续一键生成
    """
    task = service.resume_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 异步在后台恢复执行剩下的步骤
    background_tasks.add_task(service.execute_all_stages, task_id)
    return task

@router.post("/{task_id}/run_all", response_model=DramaTaskResponse)
def run_all_stages_one_click(task_id: str, background_tasks: BackgroundTasks):
    """
    一键成片模式：异步在后台连续串行运行 1 到 8 步骤
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task["status"] = "running"
    repo.save_task(task_id, task)
    
    # 异步在后台执行全生命周期
    background_tasks.add_task(service.execute_all_stages, task_id)
    return task

@router.post("/{task_id}/episodes/plan")
def plan_episodes_route(task_id: str):
    """把已生成的完整剧本(阶段2)切分为多集，返回分集清单。需先完成阶段1-3。"""
    try:
        task = service.plan_episodes(task_id)
        return {"status": "success", "sourceHash": compile_writer_dashboard(task).source_hash,
                "totalEpisodes": task.get("total_episodes", 0),
                "episodes": [{"index": e["index"], "title": e["title"], "status": e["status"]}
                             for e in task.get("episodes", [])]}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分集失败: {str(e)}")

@router.get("/{task_id}/episodes")
def list_episodes_route(task_id: str):
    """获取多集制作清单与各集状态、成片地址。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    eps = task.get("episodes", []) or []
    return {
        "sourceHash": compile_writer_dashboard(task).source_hash,
        "totalEpisodes": task.get("total_episodes", len(eps)),
        "currentEpisode": task.get("current_episode", 0),
        "episodes": [{"index": e.get("index"), "title": e.get("title"), "status": e.get("status"),
                      "videoUrl": e.get("video_url"), "shotsCount": len(e.get("shots") or []),
                      "summary": e.get("summary", "")} for e in eps],
    }

@router.post("/{task_id}/episodes/{ep_index}/produce")
def produce_episode_route(task_id: str, ep_index: int, background_tasks: BackgroundTasks):
    """逐集制作：后台异步生成指定集 (分镜->尾帧链式逐镜生成->情绪配音->合成2.5-3min单集)。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.get("episodes"):
        raise HTTPException(status_code=400, detail="请先调用 /episodes/plan 进行分集")
    ep = next((e for e in task["episodes"] if e.get("index") == ep_index), None)
    if not ep:
        raise HTTPException(status_code=404, detail=f"第{ep_index}集不存在")

    async def _run():
        try:
            await service.produce_episode(task_id, ep_index)
        except Exception as e:
            import logging
            logging.getLogger("app.api.drama_api").error(f"制作第{ep_index}集失败: {str(e)}")

    background_tasks.add_task(_run)
    ep["status"] = "running"
    repo.save_task(task_id, task)
    return {"status": "running", "episode": ep_index, "message": f"第{ep_index}集已开始后台制作，请轮询 /episodes 查看进度"}

@router.post("/{task_id}/assistant")
async def assistant_chat(task_id: str, payload: Dict[str, str]):
    """
    自然语言流程助手：意图识别 (执行下一步/重跑阶段N/暂停/查询进度/微调/答疑)，
    执行类动作后台异步启动并立即返回；前端轮询 /status 的 stageProgress 展示调用过程与进度条。
    """
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    try:
        result = await service.assistant_message(task_id, message)
        return {
            "reply": result["reply"],
            "action": result["action"],
            "stage": result["stage"],
            "task": DramaTaskResponse(**result["task"]).model_dump(by_alias=True),
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.post("/{task_id}/chat", response_model=DramaTaskResponse)
async def chat_with_agent(task_id: str, payload: Dict[str, str]):
    """
    通过对话引导智能体进行短剧内容调整与创作
    """
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    try:
        updated_task = await service.chat_instruction(task_id, message)
        return updated_task
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.post("/{task_id}/quality/video", response_model=DramaTaskResponse)
def submit_video_quality(task_id: str, measurements: VideoQualityMeasurements):
    """提交成片多模态或人工复核证据；通过后进入八 Agent 终审。"""
    try:
        return service.submit_video_quality(task_id, measurements)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/quality/council", response_model=DramaTaskResponse)
def submit_council_release(task_id: str, evidence: CouncilReleaseEvidence):
    """提交八 Agent 全量交付证据；只有视频门禁和委员会门禁均通过才完成。"""
    try:
        return service.submit_council_release(task_id, evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/update_config", response_model=DramaTaskResponse)
def update_task_config(task_id: str, req: DramaCreateRequest):
    """
    更新现有短剧任务的参数配置
    """
    try:
        task = service.update_task_config(task_id, req)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

@router.post("/import_skill")
async def import_new_skill(
    import_type: str = Form(..., description="导入类型: github, clawhub, npx, zip"),
    url: Optional[str] = Form(None, description="GitHub或Clawhub链接"),
    package_name: Optional[str] = Form(None, description="NPX包名"),
    file: Optional[UploadFile] = File(None, description="上传的ZIP技能包文件"),
    _admin: dict = Depends(require_admin),
):
    """
    导入并添加外部自定义 Skill 技能包
    """
    try:
        result = await service.import_skill_logic(import_type, url, package_name, file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入Skill失败: {str(e)}")

@router.get("/skills", response_model=List[Dict[str, Any]])
def get_imported_skills():
    """
    获取所有已导入的 Skill 技能列表
    """
    return service.get_all_skills()

@router.delete("/skills/{skill_name}")
def delete_imported_skill(skill_name: str, _admin: dict = Depends(require_admin)):
    """
    删除指定的已导入 Skill 技能包
    """
    try:
        result = service.delete_skill_logic(skill_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除Skill失败: {str(e)}")

@router.delete("/{task_id}")
def delete_drama_task(task_id: str):
    """
    物理删除指定的短剧生成任务
    """
    try:
        success = service.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"status": "success", "message": f"任务 {task_id} 已成功删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")

@router.post("/seedance2_video")
async def seedance2_video_route(payload: Dict[str, Any]):
    """
    Seedance 2.0 多模态生视频统一接口，支持四种能力：
      - 文生视频：{"prompt": "..."}
      - 图生视频-首帧：{"prompt": "...", "first_frame": "<图片URL>"}
      - 图生视频-首尾帧：{"prompt": "...", "first_frame": "<首帧URL>", "last_frame": "<尾帧URL>"}
      - 多模态参考生视频：{"prompt": "...", "ref_images": ["url",...0-9], "ref_videos": [..0-3], "ref_audios": [..0-3]}
    可选 {"optimize": false} 关闭 sd2-pe 提示词优化器。
    """
    prompt = (payload.get("prompt") or "").strip()
    first_frame = payload.get("first_frame")
    last_frame = payload.get("last_frame")
    ref_images = payload.get("ref_images") or []
    ref_videos = payload.get("ref_videos") or []
    ref_audios = payload.get("ref_audios") or []
    optimize = payload.get("optimize", True)
    if not prompt and not first_frame and not ref_images and not ref_videos:
        raise HTTPException(status_code=400, detail="至少需要提供 prompt 或 first_frame 或参考素材之一")
    if ref_audios and not (ref_images or ref_videos or first_frame):
        raise HTTPException(status_code=400, detail="不可单独输入音频，应至少包含 1 个参考视频或图片")
    try:
        result = await service.generate_seedance2_video(
            prompt, first_frame=first_frame, last_frame=last_frame,
            ref_images=ref_images, ref_videos=ref_videos, ref_audios=ref_audios, optimize=optimize
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seedance2.0 生视频失败: {str(e)}")

@router.post("/parse_script")
async def parse_script_file_route(file: UploadFile = File(..., description="上传的剧本文件")):
    """
    手动上传剧本文件解析接口，支持 .txt, .md, .docx, .pdf, .fdx。
    """
    try:
        maximum = 20 * 1024 * 1024
        file_bytes = await file.read(maximum + 1)
        if len(file_bytes) > maximum:
            raise ValueError("剧本文件不能超过 20MB")
        safe_name = file.filename or "script.txt"
        content = service.parse_script_file(safe_name, file_bytes)
        return {
            "status": "success",
            "filename": safe_name,
            "content": content
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析剧本文件失败: {str(e)}")
