import hashlib
import json
import logging
import os
from urllib.parse import quote, unquote, urlparse

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, BackgroundTasks, Form, File, Query, UploadFile, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from typing import List, Dict, Any, Optional
from app.schema.shot_visual import (
    DraftModeUpdate,
    SpendLimitsUpdate,
    ShotHdRequest,
    ShotRepairRequest,
    ShotRetakeRequest,
    ShotRegenerateRequest,
    ShotVideoPromptUpdate,
    ProjectVideoModelUpdate,
    VideoAdmissionRequest,
    ShotCandidateSelection,
    ShotRecipeRequest,
    ShotVisualSettings,
    ShotVisualWorkspaceResponse,
)
from app.core.production_asset_readiness import READINESS_KEY, evaluate_asset_readiness
from app.core.project_asset_completion import project_element_summaries
from app.core.element_scope import element_in_task, element_name_keys, element_task_ids, link_task, normalized_asset_name
from app.schema.drama import (
    DramaCreateRequest,
    DramaTaskResponse,
    DramaTaskSummary,
    ScriptUpdateRequest,
    ShotFeedbackRequest,
)
from app.service.drama_service import DramaService, ScriptUpdateConflictError, StagePrerequisiteError
from app.service.acquisition_service import AcquisitionService
from app.repository.task_repo import TaskRepository
from app.api.auth_api import get_current_user, require_permission
from app.platform.access_audit import record_access
from app.platform.billing_book import active_book
from app.platform.permissions import PROJECT_READ_ANY, PROJECT_WRITE_ANY, SKILL_MANAGE, authorize, has_permission
from app.core.media_compositor import MEDIA_DIR
from app.core.production_asset_extractor import extract_production_assets
from app.core.storyboard_assets import compose_nine_grid, fetch_remote_image_bytes
from app.core.writer_dashboard import compile_writer_dashboard
from app.api.element_api import (
    LOOK_LAYOUT, NEEDS_REDRAW, _first_image_bytes, _persist_element_file, _persist_look_views, sync_project_actor_to_library,
)
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app import settings
from app.core import breakdown_kinds, character_variants, script_breakdown, asset_identity
from app.core.character_looks import crowd_wardrobe, plan_looks, timing_is_readable, untimed_makeup
from app.core import creation_modes, edit_timeline, generation_queue, style_analysis
from app.core.spatial_stage import blockout as stage_blockout
from app.core.screenwriting import ledger_ops
from app.core.screenwriting.review import ReviewError
from app.ingest.parsers import SourceIngestor
from app.platform.uploads import validate_image_upload
from starlette.concurrency import run_in_threadpool

from app.platform.uploads import MAX_IMAGE_UPLOAD_BYTES, UploadValidationError
from app.core.video_quality import VideoQualityMeasurements
from app.schema.agent_council import CouncilReleaseEvidence
from app.schema.writer_dashboard import (
    AssetIdentityRequest,
    ScriptDocument,
    ScriptDocumentCreateRequest,
    ScriptDocumentDetail,
    ScriptDocumentUpdateRequest,
    ScriptLibraryResponse,
    WriterDashboardResponse,
    WriterOverviewUpdateRequest,
    WriterRelationshipUpdateRequest,
    WriterRolesUpdateRequest,
    WriterTimelineUpdateRequest,
    WriterVersionCreateRequest,
    WriterVersionRestoreRequest,
)
from app.schema.character_dashboard import CharacterDashboardResponse
from app.schema.production import RightsNoteRequest, TimelineOperationRequest, TimelineRenderRequest
from app.schema.screenwriting import (
    DialoguePolishRequest,
    PronunciationsUpdate,
    ScreenwritingReviewRequest,
    ScreenwritingRepairRequest,
    ReplanRequest,
    ReplanAdoptRequest,
    LedgerOperationRequest,
    ScreenwritingEpisodeResponse,
    ScreenwritingPlanPatchRequest,
    ScreenwritingPromptPreviewResponse,
    ScreenwritingStateResponse,
)
from app.core.screenwriting.editing import PlanEditError
from app.core.screenwriting.engine import PROMPT_STAGES, PlanRejected, ScreenwritingError
from app.core.spatial_stage.director_ai import DirectorAIError
from app.core.spatial_stage.interchange import InterchangeError
from app.core.spatial_stage.model_kit import ModelKitError
from app.core.spatial_stage.operations import StageEditError
from app.schema.spatial_stage import (
    SpatialExportResponse,
    SpatialImportRequest,
    SpatialOverviewResponse,
    SpatialPlanPatchRequest,
    SpatialPlanResponse,
    SpatialRepairsResponse,
    SpatialRevisionRequest,
)
from app.schema.director_desk import DeskCapture, DeskCapturesResponse, DeskPosesResponse, DeskSavePoseRequest
from app.service.director_desk_service import MAX_CLIP_BYTES, CaptureError, CaptureUpload
from app.service.spatial_stage_service import StageConflict
from app.service import stage_director_service as stage_director
from app.core import project_memory
from app.core import prompt_data


_WORDING_FILE = "drama_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/drama_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

logger = logging.getLogger("app.api.drama_api")
service = DramaService()
# 项目里重新生成的数字演员新图，同步给资产库里挂在本项目的同名演员。
service.character_regenerated_hook = sync_project_actor_to_library
repo = TaskRepository()


async def require_owned_drama_task(
    request: Request,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
) -> dict:
    """Enforce per-task ownership for every route containing a task_id."""
    task_id = request.path_params.get("task_id")
    if not task_id:
        return current_user

    task = await run_in_threadpool(service.repo.get_task, str(task_id))
    if not task:
        # Fail closed: a transient repository read failure must never let the
        # handler perform a second, unauthorised read that happens to succeed.
        raise HTTPException(status_code=404, detail=_text_of("require_owned_drama_task.detail"))

    write = request.method not in {"GET", "HEAD", "OPTIONS"}
    owner_user_id = str(task.get("owner_user_id") or "")
    decision = authorize(current_user, owner_id=owner_user_id, write=write)
    if not decision.allowed:
        # Hide task existence from users who do not own it.
        raise HTTPException(status_code=404, detail=_text_of("require_owned_drama_task.detail.2"))
    if decision.cross_account:
        await record_access(
            store, current_user, resource_id=str(task_id), owner_id=owner_user_id, write=write,
            via=f"{request.method} {request.url.path}",
        )
    return current_user


# 登录校验与任务归属校验在同一路由边界内统一执行。
router = APIRouter(
    prefix="/api/drama",
    tags=list(_words_of("module.tags")),
    dependencies=[Depends(require_owned_drama_task)],
)

@router.post("/create", response_model=DramaTaskResponse)
def create_new_task(req: DramaCreateRequest, current_user: dict = Depends(get_current_user)):
    """
    新建一个 AI 短剧任务。
    如果是一键成片，则初始化后可直接一键生成。
    """
    try:
        book = active_book()
        if book is not None:
            owner_id = str(current_user.get("user_id") or "")
            owned = sum(1 for task in service.repo.list_all_tasks() if isinstance(task, dict) and task.get("owner_user_id") == owner_id)
            book.require_feature(owner_id, "project.max", current=owned)
        task_data = service.create_task(req, owner_user_id=current_user.get("user_id"))
        return task_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("create_new_task.detail").format(str(e)))

@router.get("/list", response_model=List[DramaTaskSummary])
def get_all_tasks(current_user: dict = Depends(get_current_user)):
    """List the caller's projects for the lobby.

    Returns summaries only: the generated assets are the bulk of a task and the
    list is polled, so they are fetched per project through /{task_id}/status.
    """
    tasks = service.repo.list_all_tasks()
    if not has_permission(current_user, PROJECT_READ_ANY):
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
def get_task_status(task_id: str, request: Request):
    """Return one task with every generated asset, revalidated by ETag.

    The workbench polls this every 1.5s while a stage runs, but a stage takes
    far longer than one tick, so most polls carry an unchanged body of several
    hundred kilobytes. Tagging the payload lets the browser revalidate and get
    an empty 304 whenever nothing has moved.
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("get_task_status.detail"))

    payload = DramaTaskResponse.model_validate(task).model_dump(mode="json", by_alias=True)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    etag = f'W/"{hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]}"'
    # Revalidate on every poll, but skip the body when the task has not moved.
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Cookie"}

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=payload, headers=headers)


@router.get("/{task_id}/writer-dashboard/export")
def export_writer_dashboard(task_id: str):
    """Download the normalized Writer Agent dashboard as versioned JSON."""
    dashboard = service.get_writer_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("export_writer_dashboard.detail"))
    return JSONResponse(
        content=dashboard.model_dump(mode="json", by_alias=True),
        headers={"Content-Disposition": 'attachment; filename="writer-dashboard.json"'},
    )


@router.get("/{task_id}/script-breakdown")
def download_script_breakdown(task_id: str, format: str = Query("json", pattern="^(json|csv|md)$")):
    """The scene-by-scene breakdown: JSON to read, CSV for a spreadsheet, Markdown to hand around."""
    breakdown = service.script_breakdown(task_id)
    if breakdown is None:
        raise HTTPException(status_code=404, detail=_text_of("download_script_breakdown.detail"))
    if format == "csv":
        return Response(
            content=script_breakdown.render_csv(breakdown), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="script-breakdown.csv"'},
        )
    if format == "md":
        return Response(
            content=script_breakdown.render_markdown(breakdown), media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="script-breakdown.md"'},
        )
    return breakdown


@router.get("/{task_id}/writer-dashboard", response_model=WriterDashboardResponse)
def get_writer_dashboard(task_id: str):
    """Return the Writer Agent timeline, episodes, statistics and relationship graph contract."""
    dashboard = service.get_writer_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("get_writer_dashboard.detail"))
    return dashboard


_EXTRACTABLE_ASSET_KINDS = {"actor", "scene", "prop", "costume", "effect", "product", *breakdown_kinds.KINDS}
_IMAGE_SUFFIX_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _local_media_bytes(path: str) -> Optional[bytes]:
    """Read a /media/... file without leaving the media root."""
    media_root = os.path.realpath(MEDIA_DIR)
    absolute = os.path.realpath(os.path.join(media_root, unquote(path[len(settings.MEDIA_PREFIX):])))
    if not absolute.startswith(media_root + os.sep) or not os.path.isfile(absolute):
        return None
    with open(absolute, "rb") as handle:
        return handle.read()


def _extracted_image_bytes(url: str) -> Optional[bytes]:
    """Fetch one screenplay-derived reference image, local or remote."""
    parsed = urlparse(url)
    if parsed.path.startswith(settings.MEDIA_PREFIX):
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


def _has_image(element) -> bool:
    return any(str(file.mime_type or "").startswith("image/") for file in (element.files or []))


def _actor_metadata_patch(kind: str, candidate: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Approved five-view data a library actor does not hold yet."""
    if kind != "actor" or not candidate.get("quality_passed"):
        return {}
    views = [item for item in (candidate.get("views") or []) if isinstance(item, dict)]
    if len({item.get("view") for item in views}) < 5 or metadata.get("views") == views:
        return {}
    patch: Dict[str, Any] = {"views": views, "five_view_passed": True}
    if candidate.get("sheet_url"):
        patch["sheet_url"] = candidate["sheet_url"]
    if candidate.get("role"):
        patch["role"] = candidate["role"]
    return patch


async def _import_production_asset_candidates(
    *,
    task_id: str,
    kind: str,
    candidates: List[Dict[str, Any]],
    owner_id: str,
    store: PlatformStore,
) -> Dict[str, Any]:
    """Idempotently file one extracted asset category into the element library.

    A same-name asset that another project already produced is linked to this
    project (reused) rather than created again; only genuinely new names are
    created and, later, generated from the screenplay.
    """
    if not candidates:
        return {"kind": kind, "created": 0, "reused": 0, "skipped": 0, "with_image": 0, "items": [], "reused_items": []}

    by_name: Dict[str, Any] = {}
    for item in await store.list_all_elements(owner_id, kind):
        for key in element_name_keys(item.name, item.metadata_json):
            by_name.setdefault(key, item)
    created: List[Dict[str, Any]] = []
    reused: List[Dict[str, Any]] = []
    skipped = 0
    with_image = 0
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        image_url = str(candidate.get("image_url") or "").strip()
        match = by_name.get(normalized_asset_name(name))
        if match is not None:
            metadata = match.metadata_json if isinstance(match.metadata_json, dict) else {}
            patch = _actor_metadata_patch(kind, candidate, metadata)
            already_linked = element_in_task(metadata, task_id)
            if already_linked and not patch and (_has_image(match) or not image_url):
                skipped += 1
                continue
            if not already_linked:
                match = await store.link_element_to_task(match.id, owner_id, task_id)
            if patch:
                match = await store.merge_element_metadata(match.id, owner_id, patch)
            attached = _has_image(match)
            if not attached and image_url:
                attached = await _attach_extracted_image(
                    element_id=match.id, owner_id=owner_id, kind=kind, url=image_url, store=store,
                )
            if already_linked:
                skipped += 1
            else:
                if attached:
                    with_image += 1
                reused.append({"id": match.id, "name": match.name, "image": attached})
            continue
        try:
            element = await store.create_element(
                owner_id=owner_id,
                kind=kind,
                name=name,
                description=str(candidate.get("description") or ""),
                metadata={
                    "source": "screenplay-extraction",
                    **link_task({}, task_id),
                    **_actor_metadata_patch(kind, candidate, {}),
                },
            )
        except ValueError as exc:
            # Quota exhaustion stops this category; assets already created stay.
            if created:
                break
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        by_name[normalized_asset_name(name)] = element
        attached = False
        if image_url:
            attached = await _attach_extracted_image(
                element_id=element.id,
                owner_id=owner_id,
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
        "reused": len(reused),
        "skipped": skipped,
        "with_image": with_image,
        "items": created,
        "reused_items": reused,
    }


async def _copy_first_image(source: Any, element_id: str, owner_id: str, store: PlatformStore) -> bool:
    """同一身戏服的图不重画：别的项目已经画过，只是穿的集数不一样。"""
    content = await run_in_threadpool(_first_image_bytes, source)
    if not content:
        return False
    file = next(entry for entry in source.files if str(entry.mime_type or "").startswith("image/"))
    await _persist_element_file(
        element_id=element_id, owner_id=owner_id, slot="front",
        suffix=_IMAGE_SUFFIX_BY_MIME.get(str(file.mime_type), ".png"), mime=str(file.mime_type), content=content, store=store,
    )
    # 定妆图展示板连同切出来的单张一起带过来，版式也跟着。
    await _persist_look_views(element_id, owner_id, store, content)
    layout = (getattr(source, "metadata_json", None) or {}).get(LOOK_LAYOUT)
    if layout:
        await store.merge_element_metadata(element_id, owner_id, {LOOK_LAYOUT: layout})
    return True


async def _file_character_looks(*, task: Dict[str, Any], task_id: str, owner_id: str, store: PlatformStore) -> Dict[str, Any]:
    """Keep each character's looks in step with the script's outfits and makeup; no image is drawn here.

    A look belongs to its project: another project's look of the same name is shared only while it says the
    same thing. When only the episodes differ this project gets its own entry with a copy of the picture.
    """
    # 剧本还没写到的那几集穿的也登记：每套戏服都有定妆图可出，写到那几集时不用再补登。
    looks = plan_looks(task, include_later=True)
    planned = {normalized_asset_name(look["name"]) for look in looks}
    actors = await store.list_all_elements(owner_id, "actor")
    created: List[Dict[str, Any]] = []
    reused: List[Dict[str, Any]] = []
    skipped = with_image = 0

    def named(key: str) -> List[Any]:
        return [item for item in actors if key in element_name_keys(item.name, item.metadata_json)]

    async def create(look: Dict[str, Any], source: Any = None) -> None:
        nonlocal with_image
        element = await store.create_element(
            owner_id=owner_id, kind="actor", name=look["name"], description=look["description"],
            metadata={"source": "screenplay-extraction", **link_task({}, task_id), character_variants.VARIANT_KEY: look["facts"]},
        )
        copied = await _copy_first_image(source, element.id, owner_id, store) if source is not None else False
        with_image += int(copied)
        created.append({"id": element.id, "name": element.name, "image": copied})

    for look in looks:
        same_name = named(normalized_asset_name(look["name"]))
        mine = next((item for item in same_name if element_in_task(item.metadata_json, task_id)), None)
        if mine is None:
            twin = next((item for item in same_name if str(item.description or "") == look["description"] and _has_image(item)), None)
            current = character_variants.variant_of({"metadata": twin.metadata_json}) if twin is not None else None
            if twin is not None and current == look["facts"]:
                await store.link_element_to_task(twin.id, owner_id, task_id)
                with_image += 1
                reused.append({"id": twin.id, "name": twin.name, "image": True})
            else:
                await create(look, twin)
            continue
        current = character_variants.variant_of({"metadata": mine.metadata_json})
        # 手工设的衍生形象和用户改过的换装依据不动；其余跟着剧本走。
        if current is not None and (current.get("source") != character_variants.LOOK_SOURCE or current.get("edited")):
            skipped += 1
            continue
        same_words = str(mine.description or "") == look["description"]
        if current == look["facts"] and same_words:
            skipped += 1
        elif len(element_task_ids(mine.metadata_json)) > 1:
            # 别的项目也在用它：这个项目另起一条，别的项目不受影响。
            await store.unlink_element_from_task(mine.id, owner_id, task_id)
            await create(look, mine if same_words else None)
        else:
            await store.set_element_variant(mine.id, owner_id, look["facts"])
            if not same_words:
                await store.update_element(mine.id, owner_id, name=None, description=look["description"])
                # 图是按旧写法画的：不自动花钱重画，提示一下。
                if _has_image(mine):
                    await store.merge_element_metadata(mine.id, owner_id, {NEEDS_REDRAW: True})
            skipped += 1
    # 剧本不再需要的定妆图：只有这个项目用就留着图但不再穿，否则它和新的那张抢同一段集数；别的项目也在用就只退出这个项目。
    for item in actors:
        current = character_variants.variant_of({"metadata": item.metadata_json})
        if (
            current and current.get("source") == character_variants.LOOK_SOURCE and not current.get("edited") and not current.get("retired")
            and element_in_task(item.metadata_json, task_id) and not element_name_keys(item.name, item.metadata_json) & planned
        ):
            if len(element_task_ids(item.metadata_json)) > 1:
                await store.unlink_element_from_task(item.id, owner_id, task_id)
            else:
                await store.set_element_variant(item.id, owner_id, {**current, "retired": True})
    return {
        "kind": "look", "created": len(created), "reused": len(reused), "skipped": skipped, "with_image": with_image,
        "items": created, "reused_items": reused,
    }


async def _file_crowd_wardrobe(*, task: Dict[str, Any], task_id: str, owner_id: str, store: PlatformStore) -> None:
    """已经入库的群演补上后来才写的戏服和妆效；已有的图不自动重画，提示一下。"""
    crowd = {normalized_asset_name(item["name"]): item["parts"] for item in crowd_wardrobe(task)}
    if not crowd:
        return
    for item in await store.list_all_elements(owner_id, "extra"):
        if not element_in_task(item.metadata_json, task_id):
            continue
        description = str(item.description or "")
        missing = [part for part in crowd.get(normalized_asset_name(item.name), []) if part not in description]
        if missing:
            await store.update_element(item.id, owner_id, name=None, description="；".join(part for part in (description, *missing) if part))
            if _has_image(item):
                await store.merge_element_metadata(item.id, owner_id, {NEEDS_REDRAW: True})


class _LookTimingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    episodes: str = Field(min_length=1, max_length=60)


@router.get("/{task_id}/character-looks/untimed")
def untimed_character_makeup(task_id: str):
    """定不下时间的妆效：角色页列出来，人可以补上集数。"""
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("untimed_character_makeup.detail"))
    return {"items": untimed_makeup(task)}


@router.post("/{task_id}/character-looks/sync")
async def sync_character_looks(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """按拆解目录把每套戏服和妆效登记成定妆图(包括剧本还没写到的那几集)；不出图。"""
    task = await run_in_threadpool(service.repo.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("sync_character_looks.detail"))
    return await _file_character_looks(task=task, task_id=task_id, owner_id=current_user["user_id"], store=store)


@router.put("/{task_id}/character-looks/timing")
async def set_character_look_timing(
    task_id: str,
    request: _LookTimingRequest,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """人给一处妆效定时间；这处妆效随即合进当时穿的那身。不出图，出图还是用户点。"""
    words = request.episodes.strip()
    if not timing_is_readable(words):
        raise HTTPException(status_code=422, detail=_text_of("set_character_look_timing.detail"))
    name = request.name.strip()

    def record(current: Dict[str, Any]) -> bool:
        catalog = ((current.get("assets") or {}).get("2_breakdown") or {}).get("production_assets") or {}
        entry = next((item for item in catalog.get("makeup") or [] if isinstance(item, dict) and str(item.get("name") or "").strip() == name), None)
        if entry is None:
            return False
        entry["timing"] = words
        return True

    if not await run_in_threadpool(service.repo.mutate_task, task_id, record):
        raise HTTPException(status_code=404, detail=_text_of("set_character_look_timing.detail.2"))
    task = await run_in_threadpool(service.repo.get_task, task_id)
    await _file_character_looks(task=task, task_id=task_id, owner_id=current_user["user_id"], store=store)
    return {"readiness": await _persist_asset_readiness(task_id, task, current_user["user_id"], store)}


# Before the {kind} route, or "readiness" is read as a kind and answers 404.
@router.get("/{task_id}/production-assets/readiness")
async def production_asset_readiness(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Whether every actor, costume look, scene, prop and effect has a reference image."""
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("production_asset_readiness.detail"))
    return await _persist_asset_readiness(task_id, task, current_user["user_id"], store)


@router.get("/{task_id}/production-assets/{kind}")
def preview_production_assets(task_id: str, kind: str):
    """Preview the shooting assets of one kind that the screenplay names."""
    if kind not in _EXTRACTABLE_ASSET_KINDS:
        raise HTTPException(status_code=404, detail=_text_of("preview_production_assets.detail"))
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("preview_production_assets.detail.2"))
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
        raise HTTPException(status_code=404, detail=_text_of("import_production_assets.detail"))
    if kind in ("costume", "makeup"):
        # 不单独入库：拆解目录里的服装和化妆由 _file_character_looks 登记成表演妆造。
        raise HTTPException(status_code=422, detail=_text_of("import_production_assets.detail.2"))
    if kind == "effect":
        # The writer may never have listed these; read them off the screenplay first.
        try:
            await run_in_threadpool(service.ensure_production_asset_catalog, task_id)
        except Exception as exc:  # a failed analysis still imports whatever is already listed
            logger.warning("特效清单补全失败: task_id=%s error=%s", task_id, type(exc).__name__)
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("import_production_assets.detail.3"))

    return await _import_production_asset_candidates(
        task_id=task_id,
        kind=kind,
        candidates=extract_production_assets(task, kind),
        owner_id=current_user["user_id"],
        store=store,
    )


@router.post("/{task_id}/production-assets/sync")
async def sync_production_assets(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Extract and idempotently synchronize all non-actor shooting assets."""
    try:
        catalog = await run_in_threadpool(service.ensure_production_asset_catalog, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("拍摄资产目录同步失败: task_id=%s", task_id)
        raise HTTPException(status_code=502, detail=_text_of("sync_production_assets.detail")) from exc
    if catalog is None:
        raise HTTPException(status_code=404, detail=_text_of("sync_production_assets.detail.2"))

    # Reload after the repair pass so the shared extractor sees the persisted
    # structured catalog and keeps preview/import behavior identical.
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("sync_production_assets.detail.3"))

    # Actors are filed too, so a finished five-view set becomes reusable by the
    # next project instead of living only inside this task's assets.
    by_kind: Dict[str, Dict[str, Any]] = {}
    # An ad's product comes from its brief; other projects have none to file.
    kinds = ("actor", "scene", "prop", "effect", *breakdown_kinds.FILED_KINDS) + (("product",) if creation_modes.mode_of(task.get("config")) == "ad" else ())
    for kind in kinds:
        by_kind[kind] = await _import_production_asset_candidates(
            task_id=task_id,
            kind=kind,
            candidates=extract_production_assets(task, kind),
            owner_id=current_user["user_id"],
            store=store,
        )
    by_kind["look"] = await _file_character_looks(task=task, task_id=task_id, owner_id=current_user["user_id"], store=store)
    await _file_crowd_wardrobe(task=task, task_id=task_id, owner_id=current_user["user_id"], store=store)

    return {
        "created": sum(result["created"] for result in by_kind.values()),
        "reused": sum(result["reused"] for result in by_kind.values()),
        "skipped": sum(result["skipped"] for result in by_kind.values()),
        "with_image": sum(result["with_image"] for result in by_kind.values()),
        "kinds": {
            kind: result["created"] + result["reused"] + result["skipped"]
            for kind, result in by_kind.items()
        },
        "results": by_kind,
        "readiness": await _persist_asset_readiness(task_id, task, current_user["user_id"], store),
    }


async def _persist_asset_readiness(task_id: str, task: Dict[str, Any], owner_id: str, store: PlatformStore) -> Dict[str, Any]:
    """Compute the five-kind readiness from the project library and record it on the task."""
    summaries = await project_element_summaries(store, owner_id, task_id)
    readiness = evaluate_asset_readiness(task, summaries)

    def record(current: Dict[str, Any]) -> Dict[str, Any]:
        current.setdefault("assets", {})[READINESS_KEY] = readiness
        return current

    await run_in_threadpool(service.repo.mutate_task, task_id, record)
    return readiness


@router.get("/{task_id}/script-documents", response_model=ScriptLibraryResponse)
def list_script_documents(task_id: str):
    """List the project's screenplay library (.txt / .md reference documents)."""
    documents = service.list_script_documents(task_id)
    if documents is None:
        raise HTTPException(status_code=404, detail=_text_of("list_script_documents.detail"))
    return ScriptLibraryResponse(documents=documents, total=len(documents))


@router.post("/{task_id}/script-documents", response_model=ScriptDocument, status_code=201)
def create_script_document(task_id: str, req: ScriptDocumentCreateRequest):
    """Add one screenplay document to the project's library."""
    try:
        document = service.create_script_document(
            task_id, name=req.name, content=req.content, role=req.role, source_kind=req.source_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail=_text_of("create_script_document.detail"))
    return document


@router.get("/{task_id}/script-documents/{document_id}", response_model=ScriptDocumentDetail)
def get_script_document(task_id: str, document_id: str):
    """Read one screenplay document, including its full text."""
    document = service.get_script_document(task_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=_text_of("get_script_document.detail"))
    return document


@router.patch("/{task_id}/script-documents/{document_id}", response_model=ScriptDocumentDetail)
def update_script_document(task_id: str, document_id: str, req: ScriptDocumentUpdateRequest):
    """Rename or rewrite one screenplay document."""
    if req.name is None and req.content is None and req.role is None and req.source_kind is None and req.order is None:
        raise HTTPException(status_code=422, detail=_text_of("update_script_document.detail"))
    try:
        document = service.update_script_document(
            task_id, document_id, name=req.name, content=req.content,
            role=req.role, source_kind=req.source_kind, order=req.order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail=_text_of("update_script_document.detail.2"))
    return document


@router.delete("/{task_id}/script-documents/{document_id}")
def delete_script_document(task_id: str, document_id: str):
    """Permanently remove one screenplay document from the library."""
    removed = service.delete_script_document(task_id, document_id)
    if removed is None:
        raise HTTPException(status_code=404, detail=_text_of("delete_script_document.detail"))
    if not removed:
        raise HTTPException(status_code=404, detail=_text_of("delete_script_document.detail.2"))
    return {"deleted": True, "id": document_id}


@router.get("/{task_id}/mentionable")
async def list_mentionable(
    task_id: str,
    q: str = Query("", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    store: PlatformStore = Depends(get_platform_store),
):
    """「@」的候选：项目角色、挂在本项目的资产库元素和分镜里的场，按 actor、scene、prop、其他排。"""
    from app.core import mention_catalog

    task = await run_in_threadpool(service.repo.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("list_mentionable.detail"))
    task = {**task, "task_id": str(task.get("task_id") or task_id)}
    return {"items": await mention_catalog.mentionable_async(store, task, query=q, limit=limit)}


@router.post("/{task_id}/assets/rename")
def rename_asset(task_id: str, req: AssetIdentityRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Rename a character, scene or prop everywhere it is referenced; ``dry_run`` only counts."""
    return _change_identity(task_id, "rename", req, current_user)


@router.post("/{task_id}/assets/merge")
def merge_asset(task_id: str, req: AssetIdentityRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Merge ``name`` into the existing ``new_name``; the merged name stays as an alias."""
    return _change_identity(task_id, "merge", req, current_user)


def _change_identity(task_id: str, operation: str, req: AssetIdentityRequest, current_user: dict):
    try:
        result = service.change_asset_identity(
            task_id, operation=operation, kind=req.kind, name=req.name, new_name=req.new_name, dry_run=req.dry_run,
            owner_user_id=current_user.get("user_id"), is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except asset_identity.AssetIdentityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("_change_identity.detail"))
    return result


@router.post("/{task_id}/shots/admission")
def assess_shots_admission(task_id: str, req: VideoAdmissionRequest):
    """Admit every shot to stage 5 together: admitted, confirmation required, or blocked with per-shot problems."""
    result = service.assess_video_admission(
        task_id, confirmed_request_durations=req.confirmed_request_durations, persist_confirmations=req.persist,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("assess_shots_admission.detail"))
    return result


class ProjectMemoryAddRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)
    kind: str = Field("decision", pattern="^(preference|decision|fact)$")
    pinned: bool = False


class ProjectMemoryPatchRequest(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=200)
    kind: Optional[str] = Field(None, pattern="^(preference|decision|fact)$")
    pinned: Optional[bool] = None


class PromptProfileRequest(BaseModel):
    profile: str = Field(..., pattern="^(standard|lean)$")


def _memory_call(call):
    try:
        view = call()
    except project_memory.MemoryError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if view is None:
        raise HTTPException(status_code=404, detail=_text_of("_memory_call.detail"))
    return view


@router.get("/{task_id}/memory")
def get_project_memory(task_id: str):
    """What the project remembers, the prompt profile, and the tokens used and saved."""
    return _memory_call(lambda: service.project_memory_view(task_id))


@router.post("/{task_id}/memory")
def add_project_memory(task_id: str, req: ProjectMemoryAddRequest):
    return _memory_call(lambda: service.edit_project_memory(
        task_id, lambda task: project_memory.add(task, req.text, kind=req.kind, source="user", pinned=req.pinned),
    ))


@router.patch("/{task_id}/memory/{memory_id}")
def edit_project_memory(task_id: str, memory_id: str, req: ProjectMemoryPatchRequest):
    return _memory_call(lambda: service.edit_project_memory(
        task_id, lambda task: project_memory.update(task, memory_id, text=req.text, pinned=req.pinned, kind=req.kind),
    ))


@router.delete("/{task_id}/memory/{memory_id}")
def delete_project_memory(task_id: str, memory_id: str):
    return _memory_call(lambda: service.edit_project_memory(task_id, lambda task: project_memory.remove(task, memory_id)))


@router.put("/{task_id}/memory/prompt-profile")
def set_prompt_profile(task_id: str, req: PromptProfileRequest):
    """省 token 模式：分镜阶段的指南减半。"""
    return _memory_call(lambda: service.set_prompt_profile(task_id, req.profile))


@router.get("/{task_id}/usage")
def get_usage(task_id: str, limit: int = Query(50, ge=1, le=500)):
    """Provider calls this project has made, with their reference cost."""
    result = service.usage_summary(task_id, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_usage.detail"))
    return result


@router.get("/{task_id}/subtitles")
def get_subtitles(task_id: str, episode: int = Query(..., ge=1, le=200), format: str = Query("json", pattern="^(json|srt)$")):
    """A subtitle draft for one planned episode, as cues or as SubRip text."""
    try:
        result = service.episode_subtitles(task_id, episode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_subtitles.detail"))
    if format == "srt":
        filename = f"episode_{episode}.srt"
        return Response(
            content=result["srt"], media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
        )
    return result


class PublishPrepareRequest(BaseModel):
    platforms: list[str] = Field(min_length=1, max_length=12)


@router.get("/{task_id}/publish")
def get_publish_preparation(task_id: str):
    """The share panel: the platforms on offer and the last prepared packages."""
    result = service.get_publish_preparation(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_publish_preparation.detail"))
    return result


@router.post("/{task_id}/publish/prepare")
def prepare_publish(task_id: str, req: PublishPrepareRequest):
    """Prepare each selected platform's upload package; nothing is posted."""
    try:
        result = service.prepare_publish(task_id, req.platforms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("prepare_publish.detail"))
    return result


# ---------------- 宣发 · 自动获客：作品 → 评论 → 线索 → 联系 → 跟进 ----------------

acquisition = AcquisitionService(service.repo, service.gateway)


def _acquired(call, *args, **kwargs):
    try:
        result = call(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("_acquired.detail"))
    return result


class AcquisitionWorkRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=8, max_length=600)
    episode: Optional[int] = Field(default=None, ge=1, le=999)
    title: str = Field(default="", max_length=80)


class AcquisitionMetricsRequest(BaseModel):
    views: Optional[int] = Field(default=None, ge=0)
    likes: Optional[int] = Field(default=None, ge=0)
    comments: Optional[int] = Field(default=None, ge=0)
    shares: Optional[int] = Field(default=None, ge=0)
    favorites: Optional[int] = Field(default=None, ge=0)


class AcquisitionImportRequest(BaseModel):
    work_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=200_000)


class AcquisitionLeadRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    reply: Optional[str] = Field(default=None, max_length=1500)
    dm: Optional[str] = Field(default=None, max_length=1500)
    note: Optional[str] = Field(default=None, max_length=1500)


class AcquisitionSendResultRequest(BaseModel):
    sent: bool


class AcquisitionFollowUpRequest(BaseModel):
    when: str = Field(min_length=1, max_length=60)
    reason: str = Field(default="", max_length=200)


class AcquisitionFollowUpStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=20)


class AcquisitionInboxRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    author: str = Field(default="", max_length=40)
    text: str = Field(min_length=1, max_length=2000)


class AcquisitionSettingsRequest(BaseModel):
    auto_sync: bool


@router.get("/{task_id}/acquisition")
def get_acquisition(task_id: str):
    """Published works, leads, follow-ups and today's review."""
    return _acquired(acquisition.get, task_id)


@router.post("/{task_id}/acquisition/works")
def add_acquisition_work(task_id: str, req: AcquisitionWorkRequest):
    return _acquired(acquisition.add_work, task_id, req.platform, req.url, episode=req.episode, title=req.title)


@router.delete("/{task_id}/acquisition/works/{work_id}")
def remove_acquisition_work(task_id: str, work_id: str):
    return _acquired(acquisition.remove_work, task_id, work_id)


@router.patch("/{task_id}/acquisition/works/{work_id}/metrics")
def update_acquisition_metrics(task_id: str, work_id: str, req: AcquisitionMetricsRequest):
    return _acquired(acquisition.update_metrics, task_id, work_id, req.model_dump(exclude_none=True))


@router.post("/{task_id}/acquisition/comments/import")
def import_acquisition_comments(task_id: str, req: AcquisitionImportRequest):
    return _acquired(acquisition.import_comments, task_id, req.work_id, req.text)


@router.post("/{task_id}/acquisition/sync")
def sync_acquisition(task_id: str):
    """Pull new comments and statistics through official APIs (YouTube) and judge them."""
    return _acquired(acquisition.sync, task_id)


@router.patch("/{task_id}/acquisition/leads/{lead_id}")
def update_acquisition_lead(task_id: str, lead_id: str, req: AcquisitionLeadRequest):
    return _acquired(acquisition.update_lead, task_id, lead_id, req.model_dump(exclude_none=True))


@router.post("/{task_id}/acquisition/leads/{lead_id}/send")
def send_acquisition_reply(task_id: str, lead_id: str):
    """Post this lead's reply under its YouTube comment; one click, one reply."""
    return _acquired(acquisition.send_reply, task_id, lead_id)


@router.post("/{task_id}/acquisition/leads/{lead_id}/send-result")
def resolve_acquisition_send(task_id: str, lead_id: str, req: AcquisitionSendResultRequest):
    return _acquired(acquisition.resolve_send, task_id, lead_id, req.sent)


@router.post("/{task_id}/acquisition/leads/{lead_id}/follow-up")
def schedule_acquisition_follow_up(task_id: str, lead_id: str, req: AcquisitionFollowUpRequest):
    return _acquired(acquisition.schedule_follow_up, task_id, lead_id, req.when, req.reason)


@router.patch("/{task_id}/acquisition/follow-ups/{follow_up_id}")
def update_acquisition_follow_up(task_id: str, follow_up_id: str, req: AcquisitionFollowUpStatusRequest):
    return _acquired(acquisition.update_follow_up, task_id, follow_up_id, req.status)


@router.post("/{task_id}/acquisition/inbox")
def answer_acquisition_inbox(task_id: str, req: AcquisitionInboxRequest):
    """Draft the reply to a message someone sent the account and keep them as a lead."""
    return _acquired(acquisition.answer_inbox, task_id, req.platform, req.author, req.text)


@router.patch("/{task_id}/acquisition/settings")
def update_acquisition_settings(task_id: str, req: AcquisitionSettingsRequest):
    return _acquired(acquisition.set_auto_sync, task_id, req.auto_sync)


class CharacterRegenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # sheet：重出整张设定集；hd：只补高清的六个身份视图(两张付费图，保留现有设定集)；
    # details：只把补位裁切的元素/细节格真正画出来(一到两张付费图)。
    mode: str = Field("sheet", pattern="^(sheet|hd|hd_body|details)$")


@router.post("/{task_id}/characters/regenerate", status_code=202)
def regenerate_character(task_id: str, req: CharacterRegenerateRequest):
    """Redraw one character's actor sheet in the background (paid); its current portrait is the identity reference."""
    try:
        dashboard = service.regenerate_character(task_id, req.name, mode=req.mode)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if (_text_of("regenerate_character.status_code") in detail) else 422, detail=detail) from exc
    if dashboard is None:
        raise HTTPException(status_code=404, detail=_text_of("regenerate_character.detail"))
    return dashboard.model_dump(mode="json", by_alias=True)


class CharacterVoiceAuditionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # 留空用角色 DNA 里的 voice_prompt；填了就用它试听，并存回角色 DNA。
    voice_prompt: str = Field("", max_length=1000)
    seed: Optional[int] = Field(None, ge=0, le=2147483647)


class CharacterVoiceCastRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    generated_voice_id: str = Field(min_length=1, max_length=200)


@router.post("/{task_id}/characters/voice/audition")
def audition_character_voice(task_id: str, req: CharacterVoiceAuditionRequest):
    """Render one round of voice previews from the character's voice prompt (paid); call again to re-roll."""
    try:
        result = service.audition_character_voice(task_id, req.name, voice_prompt=req.voice_prompt, seed=req.seed)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if (_text_of("audition_character_voice.status_code") in detail) else 422, detail=detail) from exc
    except Exception as exc:
        logger.warning("角色音色试听失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("audition_character_voice.detail")) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("audition_character_voice.detail.2"))
    return result


@router.post("/{task_id}/characters/voice/cast")
def cast_character_voice(task_id: str, req: CharacterVoiceCastRequest):
    """Keep one auditioned preview as the character's voice_id."""
    try:
        dashboard = service.cast_character_voice(task_id, req.name, req.generated_voice_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if (_text_of("cast_character_voice.status_code") in detail) else 422, detail=detail) from exc
    except Exception as exc:
        logger.warning("角色音色定版失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("cast_character_voice.detail")) from exc
    if dashboard is None:
        raise HTTPException(status_code=404, detail=_text_of("cast_character_voice.detail.2"))
    return dashboard.model_dump(mode="json", by_alias=True)


@router.get("/{task_id}/characters/{name}/voice-relink-preview")
def preview_character_voice_relink(task_id: str, name: str, voice: str = Query("", max_length=200)):
    """What recasting this character's voice would re-dub across the drama (read-only, nothing is paid for)."""
    from app.service import voice_relink

    try:
        result = voice_relink.preview_of(service, task_id, name, voice=voice)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("preview_character_voice_relink.detail"))
    return result


@router.get("/{task_id}/shots/visual", response_model=ShotVisualWorkspaceResponse)
def get_shot_visual_workspace(task_id: str):
    """Stage-5 shot workspace: camera motion, shot type, duration, media and prompts per shot."""
    workspace = service.get_shot_visual_workspace(task_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("get_shot_visual_workspace.detail"))
    return workspace


@router.put("/{task_id}/shots/{shot_id}/visual", response_model=ShotVisualWorkspaceResponse)
def update_shot_visual(
    task_id: str, shot_id: int, req: ShotVisualSettings,
    scene_id: str = Query("", max_length=40, description=_text_of("update_shot_visual.description")),
    shot_uid: int | None = Query(None, ge=1, description=_text_of("update_shot_visual.description.2")),
):
    """Persist one shot's camera settings; the workflow stays at its current stage."""
    try:
        workspace = service.update_shot_visual(task_id, shot_id, req, scene_id=scene_id, shot_uid=shot_uid)
    except ValueError as exc:
        raise HTTPException(status_code=409 if _text_of("update_shot_visual.status_code") in str(exc) else 422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("update_shot_visual.detail"))
    return workspace


@router.put("/{task_id}/shots/{shot_id}/video-prompt", response_model=ShotVisualWorkspaceResponse)
def update_shot_video_prompt(
    task_id: str, shot_id: int, req: ShotVideoPromptUpdate,
    scene_id: str = Query("", max_length=40, description=_text_of("update_shot_video_prompt.description")),
    shot_uid: int | None = Query(None, ge=1, description=_text_of("update_shot_video_prompt.description.2")),
):
    """Save a hand-edited video prompt for one shot (empty restores the compiled one); its clip goes stale."""
    try:
        workspace = service.set_shot_video_prompt(task_id, shot_id, req.prompt, scene_id=scene_id, shot_uid=shot_uid)
    except ValueError as exc:
        raise HTTPException(status_code=409 if _text_of("update_shot_video_prompt.status_code") in str(exc) else 422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("update_shot_video_prompt.detail"))
    return workspace


@router.put("/{task_id}/video-model", response_model=ShotVisualWorkspaceResponse)
def set_project_video_model(task_id: str, req: ProjectVideoModelUpdate):
    """Switch the project's video model to one enabled in the model centre; rendered clips stay reusable."""
    try:
        workspace = service.set_project_video_model(task_id, req.video_model)
    except ValueError as exc:
        raise HTTPException(status_code=409 if _text_of("set_project_video_model.status_code") in str(exc) else 422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("set_project_video_model.detail"))
    return workspace


@router.post("/{task_id}/shots/seeds/assign", response_model=ShotVisualWorkspaceResponse)
def assign_shot_seeds(task_id: str):
    """Fixed per-shot seeds, neighbouring within each scene; clips are marked stale."""
    try:
        workspace = service.assign_shot_seeds(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409 if _text_of("assign_shot_seeds.status_code") in str(exc) else 422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("assign_shot_seeds.detail"))
    return workspace


@router.put("/{task_id}/shots/{shot_id}/visual/select", response_model=ShotVisualWorkspaceResponse)
def select_shot_candidate(
    task_id: str, shot_id: int, req: ShotCandidateSelection,
    scene_id: str = Query("", max_length=40, description=_text_of("select_shot_candidate.description")),
    shot_uid: int | None = Query(None, ge=1, description=_text_of("select_shot_candidate.description.2")),
):
    """Choose one of the rendered candidates as the shot's clip."""
    try:
        workspace = service.select_shot_candidate(task_id, shot_id, req.video_url, scene_id=scene_id, shot_uid=shot_uid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("select_shot_candidate.detail"))
    return workspace


class PilotShotRequest(BaseModel):
    shot_uid: Optional[int] = Field(None, ge=1, description=_text_of("PilotShotRequest.description"))
    redo: bool = False
    problems: List[str] = Field(default_factory=list, max_length=8)


@router.post("/{task_id}/shots/pilot", response_model=ShotVisualWorkspaceResponse, status_code=202)
async def start_pilot_shot(task_id: str, req: Optional[PilotShotRequest] = None):
    """Generate one clip before the batch; it is reused when the batch runs."""
    try:
        workspace = await service.start_pilot_shot(
            task_id, shot_uid=req.shot_uid if req else None, redo=bool(req and req.redo), problems=req.problems if req else (),
        )
    except StagePrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if workspace is None:
        raise HTTPException(status_code=404, detail=_text_of("start_pilot_shot.detail"))
    return workspace


@router.post("/{task_id}/shots/{shot_id}/regenerate", response_model=ShotVisualWorkspaceResponse)
def regenerate_shot(
    task_id: str, shot_id: int, req: ShotRegenerateRequest | None = None,
    scene_id: str = Query("", max_length=40, description=_text_of("regenerate_shot.description")),
    shot_uid: int | None = Query(None, ge=1, description=_text_of("regenerate_shot.description.2")),
):
    """Mark one shot's clip (its whole board clip) for regeneration; the next stage-5 run redoes only it."""
    try:
        workspace = service.regenerate_shot(
            task_id, shot_id, reason=(req.reason if req else ""), scene_id=scene_id, shot_uid=shot_uid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("regenerate_shot.detail"))
    return workspace


def _shot_fix(call) -> dict:
    try:
        workspace = call()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not workspace:
        raise HTTPException(status_code=404, detail=_text_of("_shot_fix.detail"))
    return workspace


_SCENE_QUERY = Query("", max_length=40, description=_text_of("module.description"))
_UID_QUERY = Query(None, ge=1, description=_text_of("module.description.2"))


@router.put("/{task_id}/shots/spend-limits", response_model=ShotVisualWorkspaceResponse)
def set_spend_limits(task_id: str, req: SpendLimitsUpdate):
    """本轮视频预算上限(元)和每镜最多尝试次数；留空就是不限。"""
    return _shot_fix(lambda: service.set_spend_limits(task_id, budget_cap=req.budget_cap, max_attempts=req.max_attempts))


@router.put("/{task_id}/shots/draft-mode", response_model=ShotVisualWorkspaceResponse)
def set_draft_mode(task_id: str, req: DraftModeUpdate):
    """样片模式：第 5 阶段按 480p 出片，看过再逐镜出高清。"""
    return _shot_fix(lambda: service.set_draft_mode(task_id, req.enabled))


@router.post("/{task_id}/shots/{shot_id}/hd", response_model=ShotVisualWorkspaceResponse)
def shot_to_hd(task_id: str, shot_id: int, req: ShotHdRequest, scene_id: str = _SCENE_QUERY, shot_uid: int | None = _UID_QUERY):
    """样片转高清：upscale 当场本地放大；regenerate 标记这一镜，重跑第 5 阶段时按全分辨率、同提示词同种子重出。"""
    if req.mode == "upscale":
        return _shot_fix(lambda: service.upscale_shot(task_id, shot_id, scene_id=scene_id, shot_uid=shot_uid))
    return _shot_fix(lambda: service.regenerate_shot(task_id, shot_id, scene_id=scene_id, shot_uid=shot_uid, hd=True))


@router.post("/{task_id}/shots/{shot_id}/retake", response_model=ShotVisualWorkspaceResponse)
def retake_shot(task_id: str, shot_id: int, req: ShotRetakeRequest, scene_id: str = _SCENE_QUERY, shot_uid: int | None = _UID_QUERY):
    """从第几秒往后重做：之前的画面保留，重跑第 5 阶段时只重出后面这几秒再接回去。"""
    return _shot_fix(lambda: service.regenerate_shot(
        task_id, shot_id, scene_id=scene_id, shot_uid=shot_uid, retake_from=req.from_seconds, note=req.note,
    ))


@router.post("/{task_id}/shots/{shot_id}/repair", response_model=ShotVisualWorkspaceResponse)
def repair_shot(task_id: str, shot_id: int, req: ShotRepairRequest, scene_id: str = _SCENE_QUERY, shot_uid: int | None = _UID_QUERY):
    """区域修补：只改框出来的那一块，其余原样；后台跑，进度看本镜的 repair 字段。"""
    return _shot_fix(lambda: service.repair_shot(
        task_id, shot_id, box=req.box.model_dump(), note=req.note, start=req.start, end=req.end, scene_id=scene_id, shot_uid=shot_uid,
    ))


@router.post("/{task_id}/shots/{shot_id}/visual/recipe")
def compose_shot_recipe(
    task_id: str, shot_id: int, req: ShotRecipeRequest,
    scene_id: str = Query("", max_length=40, description=_text_of("compose_shot_recipe.description")),
    shot_uid: int | None = Query(None, ge=1, description=_text_of("compose_shot_recipe.description.2")),
):
    """Compose a camera-move recipe for one shot; nothing is persisted until the user saves."""
    try:
        recipe = service.compose_shot_recipe(
            task_id, shot_id, req.category, req.intensity, scene_id=scene_id, shot_uid=shot_uid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not recipe:
        raise HTTPException(status_code=404, detail=_text_of("compose_shot_recipe.detail"))
    return recipe


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
        raise HTTPException(status_code=404, detail=_text_of("update_writer_relationships.detail"))
    return dashboard


@router.patch("/{task_id}/overview", response_model=WriterDashboardResponse)
def update_writer_overview(task_id: str, req: WriterOverviewUpdateRequest):
    """Edit the project overview (synopsis / genre / theme / world setting) by hand."""
    dashboard = service.update_overview(task_id, req.model_dump(exclude_none=True))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("update_writer_overview.detail"))
    return dashboard


@router.post("/{task_id}/overview/regenerate", response_model=WriterDashboardResponse)
def regenerate_writer_overview(task_id: str):
    """Tell the overview again from the source with one model call."""
    try:
        dashboard = service.regenerate_overview(task_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except Exception:
        logger.exception("[Writer] 概述重新创作失败 task_id=%s", task_id)
        raise HTTPException(status_code=502, detail=_text_of("regenerate_writer_overview.detail"))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("regenerate_writer_overview.detail.2"))
    return dashboard


@router.put("/{task_id}/timeline", response_model=WriterDashboardResponse)
def update_writer_timeline(task_id: str, req: WriterTimelineUpdateRequest):
    """Replace the story event timeline with the person's arrangement of nodes."""
    dashboard = service.update_timeline(task_id, [event.model_dump(mode="json") for event in req.events])
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("update_writer_timeline.detail"))
    return dashboard


@router.put("/{task_id}/roles", response_model=WriterDashboardResponse)
def update_writer_roles(task_id: str, req: WriterRolesUpdateRequest):
    """Set the cast: positions, added names, names kept out."""
    dashboard = service.update_roles(task_id, [role.model_dump(mode="json") for role in req.roles], list(req.hidden))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("update_writer_roles.detail"))
    return dashboard


@router.get("/{task_id}/script/versions")
def list_writer_script_versions(task_id: str):
    versions = service.list_script_versions(task_id)
    if versions is None:
        raise HTTPException(status_code=404, detail=_text_of("list_writer_script_versions.detail"))
    return {"items": versions}


@router.post("/{task_id}/script/versions", response_model=WriterDashboardResponse)
def save_writer_script_version(task_id: str, req: WriterVersionCreateRequest):
    """Keep the current screenplay as a named version."""
    try:
        dashboard = service.save_script_version(task_id, req.label)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("save_writer_script_version.detail"))
    return dashboard


@router.post("/{task_id}/script/versions/{version_id}/restore", response_model=WriterDashboardResponse)
def restore_writer_script_version(
    task_id: str, version_id: str, req: WriterVersionRestoreRequest, current_user: dict = Depends(get_current_user),
):
    """Bring a saved version back; like applying an edited script, it archives later-stage work on confirmation."""
    try:
        dashboard = service.restore_script_version(
            task_id, version_id, expected_source_hash=req.expected_source_hash, confirm_invalidate=req.confirm_invalidate,
            owner_user_id=str(current_user.get("user_id") or ""), is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except ScriptUpdateConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("restore_writer_script_version.detail"))
    return dashboard


@router.post("/{task_id}/script/continue", response_model=WriterDashboardResponse)
def continue_writer_script(task_id: str):
    """Append the episodes a truncated screenplay is still missing."""
    try:
        dashboard = service.continue_script(task_id)
    except (ValueError, ScriptUpdateConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error))
    except Exception:
        logger.exception("[Writer] 剧本补写失败 task_id=%s", task_id)
        raise HTTPException(status_code=502, detail=_text_of("continue_writer_script.detail"))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("continue_writer_script.detail.2"))
    return dashboard


@router.get("/{task_id}/screenwriting/ledger")
def get_screenwriting_ledger(task_id: str):
    """The episode ledger as the Episodes view shows it: entries, unsplit source, any candidate replan."""
    try:
        result = service.get_ledger(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_screenwriting_ledger.detail"))
    return result


@router.get("/{task_id}/screenwriting/ledger/source")
def get_ledger_source_slice(task_id: str, start: int = Query(0, ge=0), end: int = Query(0, ge=0)):
    """The whole source between two offsets, for choosing where an episode boundary falls."""
    try:
        result = service.ledger_source_slice(task_id, start, end)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_ledger_source_slice.detail"))
    return result


@router.post("/{task_id}/screenwriting/ledger/impact")
def preview_ledger_impact(task_id: str, episodes: list[int] = Query(..., alias="episode")):
    """What the named episodes would lose if an operation discarded them."""
    try:
        result = service.preview_ledger_impact(task_id, episodes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("preview_ledger_impact.detail"))
    return result


@router.post("/{task_id}/screenwriting/ledger/ops")
def apply_ledger_operation(task_id: str, req: LedgerOperationRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Split, merge, cut, create, move or delete episodes; written episodes it would discard must be confirmed."""
    try:
        result = service.apply_ledger_operation(
            task_id, req, owner_user_id=current_user.get("user_id"), is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except ledger_ops.LedgerOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("apply_ledger_operation.detail"))
    return result


@router.post("/{task_id}/screenwriting/replan")
def plan_replan(task_id: str, req: ReplanRequest):
    """Plan the source again from one episode on; the result is a candidate beside the ledger."""
    try:
        result = service.plan_replan_candidate(task_id, req.from_episode)
    except ledger_ops.LedgerOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("plan_replan.detail"))
    return result


@router.post("/{task_id}/screenwriting/replan/adopt")
def adopt_replan(task_id: str, req: ReplanAdoptRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Replace the cut episodes from the replan point with the candidate's."""
    try:
        result = service.adopt_replan_candidate(
            task_id, req, owner_user_id=current_user.get("user_id"), is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except ledger_ops.LedgerOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("adopt_replan.detail"))
    return result


@router.post("/{task_id}/screenwriting/replan/discard")
def discard_replan(task_id: str):
    try:
        result = service.discard_replan_candidate(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("discard_replan.detail"))
    return result


@router.get("/{task_id}/style/reference")
def get_style_reference(task_id: str):
    """The last analysed reference image's style, and the lock the project uses now."""
    result = service.get_style_reference(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_style_reference.detail"))
    return result


@router.post("/{task_id}/style/reference")
async def analyze_style_reference(
    task_id: str,
    file: UploadFile = File(...),
    hint: str = Form(""),
    model: str = Form(""),
    current_user: dict = Depends(require_owned_drama_task),
):
    """Read a reference image's look into a style lock; it is shown, not applied."""
    content = await file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    try:
        result = await run_in_threadpool(
            service.analyze_style_reference, task_id,
            content=content, filename=file.filename or "", content_type=file.content_type or "", hint=hint, model=model,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except style_analysis.StyleAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("analyze_style_reference.detail"))
    return result


@router.post("/{task_id}/style/reference/apply")
def apply_style_reference(task_id: str, current_user: dict = Depends(require_owned_drama_task)):
    try:
        result = service.apply_style_reference(task_id)
    except style_analysis.StyleAnalysisError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("apply_style_reference.detail"))
    return result


@router.post("/{task_id}/style/reference/revert")
def revert_style_reference(task_id: str, current_user: dict = Depends(require_owned_drama_task)):
    try:
        result = service.revert_style_reference(task_id)
    except style_analysis.StyleAnalysisError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("revert_style_reference.detail"))
    return result


@router.put("/{task_id}/rights/note")
def note_rights(task_id: str, req: RightsNoteRequest, current_user: dict = Depends(require_owned_drama_task)):
    """给成片里一样素材记下授权说明(来源、授权范围、凭证在哪)；返回新的剪辑台数据。"""
    result = service.note_rights(task_id, req.key, req.note)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.get("/{task_id}/timeline")
def get_timeline(task_id: str):
    """The edit timeline the final cut is rendered from, plus the music library to pick from."""
    result = service.get_timeline(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_timeline.detail"))
    return result


@router.post("/{task_id}/timeline/ops")
def edit_timeline_route(task_id: str, req: TimelineOperationRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Trim, re-subtitle, mute, change a transition, pick a candidate, review a clip, set the title or the music."""
    try:
        result = service.edit_timeline(task_id, req.operation, req.model_dump(exclude={"operation"}, exclude_none=True))
    except edit_timeline.TimelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("edit_timeline_route.detail"))
    return result


@router.post("/{task_id}/timeline/render")
def render_timeline(task_id: str, req: Optional[TimelineRenderRequest] = None, current_user: dict = Depends(require_owned_drama_task)):
    """Render the film again from the timeline as edited, without re-running stage 7; ``episode`` picks a finished episode."""
    try:
        result = service.render_timeline(task_id, episode=req.episode if req else None)
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("render_timeline.detail"))
    return result


@router.get("/{task_id}/timeline/jianying.zip")
def download_jianying_draft(task_id: str, current_user: dict = Depends(require_owned_drama_task)):
    """The timeline as a JianYing draft folder with its media, zipped."""
    book = active_book()
    if book is not None:
        book.require_feature(str(current_user.get("user_id") or ""), "export.jianying")
    result = service.jianying_draft(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("download_jianying_draft.detail"))
    payload, info = result
    headers = {
        "Content-Disposition": f'attachment; filename="jianying_{task_id[:8]}.zip"',
        "X-Draft-Skipped": str(len(info["skipped"])), "X-Draft-Seconds": str(info["duration_seconds"]),
        "X-Draft-Sound-Offsets": str(sum(1 for join in info["sound_joins"] if join["applied"])),
    }
    return Response(content=payload, media_type="application/zip", headers=headers)


@router.get("/{task_id}/queue")
def get_generation_queue(task_id: str):
    """The generation queue of the current or last stage-5 run: items, buckets and their ceilings."""
    result = service.get_generation_queue(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_generation_queue.detail"))
    return result


@router.post("/{task_id}/queue/cancel-queued")
def cancel_queued_generation(task_id: str, current_user: dict = Depends(require_owned_drama_task)):
    """Withdraw every item still waiting; the ones already running finish and keep their result."""
    try:
        result = service.cancel_generation_item(task_id, None)
    except generation_queue.CancelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("cancel_queued_generation.detail"))
    return result


@router.post("/{task_id}/queue/{key}/cancel")
def cancel_generation_item(task_id: str, key: str, current_user: dict = Depends(require_owned_drama_task)):
    """Withdraw one queued item; a running one cannot be taken back."""
    try:
        result = service.cancel_generation_item(task_id, key)
    except generation_queue.CancelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("cancel_generation_item.detail"))
    return result


@router.get("/{task_id}/screenwriting/review")
def get_screenwriting_review(task_id: str):
    """Which episodes are confirmed, pending, changed since confirmation, or quarantined drafts."""
    try:
        result = service.get_screenwriting_review(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("get_screenwriting_review.detail"))
    return result


@router.post("/{task_id}/screenwriting/episodes/{episode}/review", response_model=ScreenwritingEpisodeResponse)
def review_screenwriting_episode(task_id: str, episode: int, req: ScreenwritingReviewRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Confirm the episode as it stands (binds to its plan fingerprint) or reopen it."""
    try:
        result = service.review_screenwriting_episode(task_id, episode, req.action, by=str(current_user.get("user_id") or "") or None)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("review_screenwriting_episode.detail"))
    return result


@router.post("/{task_id}/screenwriting/episodes/{episode}/repair", response_model=ScreenwritingEpisodeResponse)
def repair_screenwriting_episode(task_id: str, episode: int, req: ScreenwritingRepairRequest, current_user: dict = Depends(require_owned_drama_task)):
    """Let the model repair a quarantined draft with its violation reasons; never accepts a worse result."""
    try:
        result = service.repair_screenwriting_episode(
            task_id, episode, confirm_invalidate=req.confirm_invalidate,
            owner_user_id=current_user.get("user_id"), is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScreenwritingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("repair_screenwriting_episode.detail"))
    return result


@router.get("/{task_id}/screenwriting", response_model=ScreenwritingStateResponse)
def get_screenwriting_state(task_id: str):
    """Episode ledger, asset inventory, duration constraints and per-episode status."""
    state = service.get_screenwriting_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=_text_of("get_screenwriting_state.detail"))
    return state


@router.get("/{task_id}/screenwriting/episodes/{episode}", response_model=ScreenwritingEpisodeResponse)
def get_screenwriting_episode(task_id: str, episode: int):
    """One episode's editable shot plan plus its authored visual layer."""
    try:
        payload = service.get_screenwriting_episode(task_id, episode)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("get_screenwriting_episode.detail"))
    return payload


@router.get("/{task_id}/screenwriting/episodes/{episode}/prompt", response_model=ScreenwritingPromptPreviewResponse)
def preview_screenwriting_prompt(task_id: str, episode: int, stage: str = "plan"):
    """The exact prompt the Writer would send for this episode; no model call, no cost."""
    if stage not in PROMPT_STAGES:
        raise HTTPException(status_code=422, detail=_text_of("preview_screenwriting_prompt.detail"))
    try:
        prompt = service.preview_screenwriting_prompt(task_id, episode, stage)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except (ScreenwritingError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error))
    if prompt is None:
        raise HTTPException(status_code=404, detail=_text_of("preview_screenwriting_prompt.detail.2"))
    return ScreenwritingPromptPreviewResponse(task_id=task_id, episode=episode, stage=stage, prompt=prompt)


@router.get("/{task_id}/pronunciations")
def get_pronunciations(task_id: str):
    """项目读音表：这部剧里这个词配音时念什么。"""
    result = service.get_pronunciations(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.put("/{task_id}/pronunciations")
def set_pronunciations(task_id: str, req: PronunciationsUpdate):
    """整张读音表一起存：配音时把词换成登记的念法(同音字)，字幕不动。"""
    readings = service.set_pronunciations(task_id, [row.model_dump() for row in req.readings])
    if readings is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"readings": readings}


@router.post("/{task_id}/screenwriting/episodes/{episode}/polish-dialogue")
def polish_dialogue(task_id: str, episode: int, req: DialoguePolishRequest):
    """润色台词(一次文本模型调用)：逐句给出改前改后，不写回；采纳后用分镜规划的编辑接口写回。"""
    try:
        result = service.polish_dialogue(task_id, episode, scene_ids=req.scene_ids, scene_kind=req.scene_kind, extra=req.extra)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("polish_dialogue.detail"))
    return result


@router.patch("/{task_id}/screenwriting/episodes/{episode}/plan", response_model=ScreenwritingEpisodeResponse)
def patch_screenwriting_plan(
    task_id: str,
    episode: int,
    req: ScreenwritingPlanPatchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Apply ordered edits to a shot plan and re-author only the shots whose content changed."""
    try:
        payload = service.patch_screenwriting_plan(
            task_id,
            episode,
            base_revision=req.base_revision,
            operations=req.operations,
            confirm_invalidate=req.confirm_invalidate,
            owner_user_id=str(current_user.get("user_id") or ""),
            is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except PlanEditError as error:
        where = []
        if error.operation_index is not None:
            where.append(_text_of("patch_screenwriting_plan.text").format(error.operation_index + 1))
        if error.scene_id:
            where.append(_text_of("patch_screenwriting_plan.text.2").format(error.scene_id))
        suffix = f"（{'，'.join(where)}）" if where else ""
        raise HTTPException(status_code=422, detail=f"{error}{suffix}")
    except PlanRejected as error:
        raise HTTPException(status_code=409, detail=_text_of("patch_screenwriting_plan.detail").format(error))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except (ScriptUpdateConflictError, ScreenwritingError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error))
    except Exception:
        logger.exception("[Writer] 分镜规划编辑失败 task_id=%s episode=%s", task_id, episode)
        raise HTTPException(status_code=502, detail=_text_of("patch_screenwriting_plan.detail.2"))
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("patch_screenwriting_plan.detail.3"))
    return payload


@router.get("/{task_id}/spatial", response_model=SpatialOverviewResponse)
def get_spatial_overview(task_id: str):
    """Every scene's spatial stage at a glance, plus the cross-scene side and location memories."""
    overview = service.get_spatial_overview(task_id)
    if not overview:
        raise HTTPException(status_code=404, detail=_text_of("get_spatial_overview.detail"))
    return overview


def _spatial_call(task_id: str, scene_id: str, call):
    try:
        payload = call()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except StageConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    except (StageEditError, InterchangeError, CaptureError, UploadValidationError, stage_blockout.BlockoutError, DirectorAIError, ModelKitError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        logger.exception("[Spatial] 空间调度操作失败 task_id=%s scene_id=%s", task_id, scene_id)
        raise HTTPException(status_code=502, detail=_text_of("_spatial_call.detail"))
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("_spatial_call.detail.2"))
    return payload


class BlenderRenderRequest(BaseModel):
    shot_ids: Optional[List[int]] = None
    long_edge: int = Field(1920, ge=480, le=3840)


class BlenderOptionsRequest(BaseModel):
    handheld_shots: Optional[List[int]] = None
    reserved: Optional[List[Dict[str, Any]]] = None


class BlenderAttachRequest(BaseModel):
    shot_ids: Optional[List[int]] = None


class BlenderPullRequest(BaseModel):
    apply: bool = False


def _previz_call(task_id: str, scene_id: str, call):
    from app.core.blender_previz.runner import BlenderUnavailable
    from app.service.blender_previz_service import PrevizError

    def guarded():
        try:
            return call()
        except (PrevizError, BlenderUnavailable) as error:
            raise HTTPException(status_code=422, detail=str(error))

    return _spatial_call(task_id, scene_id, guarded)


@router.get("/{task_id}/spatial/scenes/{scene_id}/blender")
def get_blender_previz(task_id: str, scene_id: str):
    """最近一次 Blender 白模预演、是否过期，以及手持/空段设置。"""
    from app.service import blender_previz_service

    return _previz_call(task_id, scene_id, lambda: blender_previz_service.get_previz(service.repo.get_task(task_id) or {}, scene_id))


@router.post("/{task_id}/spatial/scenes/{scene_id}/blender/render")
async def render_blender_previz(task_id: str, scene_id: str, req: BlenderRenderRequest):
    """在本机 Blender 里把这场的站位、机位与切镜渲染成白模预演(整段视频 + 每镜首帧)。"""
    from app.service import blender_previz_service

    return await run_in_threadpool(_previz_call, task_id, scene_id, lambda: blender_previz_service.render_scene(
        service, task_id, scene_id, shot_ids=req.shot_ids, long_edge=req.long_edge))


@router.put("/{task_id}/spatial/scenes/{scene_id}/blender/options")
def set_blender_previz_options(task_id: str, scene_id: str, req: BlenderOptionsRequest):
    from app.service import blender_previz_service

    return _previz_call(task_id, scene_id, lambda: blender_previz_service.set_options(
        service, task_id, scene_id, handheld_shots=req.handheld_shots, reserved=req.reserved))


@router.post("/{task_id}/spatial/scenes/{scene_id}/blender/attach")
async def attach_blender_previz(task_id: str, scene_id: str, req: BlenderAttachRequest):
    """按镜头切片并登记为这些镜的运动参考视频，第 5 阶段出片时用它管机位、切点与时间。"""
    from app.service import blender_previz_service

    return await run_in_threadpool(_previz_call, task_id, scene_id, lambda: blender_previz_service.attach_to_shots(
        service, task_id, scene_id, shot_ids=req.shot_ids))


@router.post("/{task_id}/spatial/scenes/{scene_id}/blender/push")
async def push_blender_previz(task_id: str, scene_id: str):
    """在本机打开的 Blender(已启用桥接插件)里重建这场的预演场景。"""
    from app.service import blender_previz_service

    return await run_in_threadpool(_previz_call, task_id, scene_id, lambda: blender_previz_service.push_live(service, task_id, scene_id))


@router.post("/{task_id}/spatial/scenes/{scene_id}/blender/pull")
async def pull_blender_previz(task_id: str, scene_id: str, req: BlenderPullRequest):
    """读回在 Blender 里拖过的站位与机位；apply=true 时写回方案。"""
    from app.service import blender_previz_service

    return await run_in_threadpool(_previz_call, task_id, scene_id, lambda: blender_previz_service.pull_live(
        service, task_id, scene_id, apply=req.apply))


@router.post("/{task_id}/shots/{shot_id}/feedback")
def report_shot_feedback(task_id: str, shot_id: str, req: ShotFeedbackRequest):
    """报告一镜的生成结果：翻车的归类成失败类型并给出修正方案，成功的沉淀为项目经验。"""
    try:
        payload = service.report_shot_failure(
            task_id, shot_id, result=req.result, text=req.text,
            category=req.category, applied_fix=req.applied_fix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("report_shot_feedback.detail"))
    return payload


@router.get("/{task_id}/feedback")
def get_generation_feedback(task_id: str):
    """本项目的翻车台账：各类失败次数、该模型已确认的弱点、已验证有效的修正手段。"""
    payload = service.get_generation_feedback(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("get_generation_feedback.detail"))
    return payload


@router.get("/{task_id}/prompt-packages")
def get_prompt_packages(
    task_id: str,
    scene_id: str = Query("", max_length=80, description=_text_of("get_prompt_packages.description")),
    package_seconds: int = Query(15, description=_text_of("get_prompt_packages.description.2")),
    variant: str = Query("standard", pattern="^(standard|continuous|fight|script_doc)$"),
    delivery: str = Query(_text_of("get_prompt_packages.text"), pattern=_text_of("get_prompt_packages.pattern"), description=_text_of("get_prompt_packages.description.3")),
):
    """把已定稿的分镜重新切成可直接粘贴的 Seedance 提示词分包（或分段脚本文档）。"""
    try:
        payload = service.compile_prompt_packages(
            task_id, scene_id=scene_id, package_seconds=package_seconds, variant=variant, delivery=delivery,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("get_prompt_packages.detail"))
    return payload


@router.get("/{task_id}/asset-sheets")
def get_asset_sheets(task_id: str):
    """人物 / 场景 / 道具 / 色板四类设定图：每项都带稳定识别锚点、可直接生成的提示词与固定版式。"""
    payload = service.compile_asset_sheets(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail=_text_of("get_asset_sheets.detail"))
    return payload


@router.get("/{task_id}/spatial/scenes/{scene_id}", response_model=SpatialPlanResponse)
def get_spatial_plan(task_id: str, scene_id: str):
    """One scene's stage: marks, set pieces, axis, one solved camera per shot, and the checks."""
    return _spatial_call(task_id, scene_id, lambda: service.get_spatial_plan(task_id, scene_id))


@router.patch("/{task_id}/spatial/scenes/{scene_id}", response_model=SpatialPlanResponse)
def patch_spatial_plan(task_id: str, scene_id: str, req: SpatialPlanPatchRequest):
    """Apply ordered semantic edits (place relative, face pair, formations, axis, cameras, per-shot moves)."""
    return _spatial_call(task_id, scene_id, lambda: service.patch_spatial_plan(
        task_id, scene_id, base_revision=req.base_revision, operations=req.operations, solve=req.solve,
    ))


@router.get("/{task_id}/spatial/scenes/{scene_id}/repairs", response_model=SpatialRepairsResponse)
def get_spatial_repairs(task_id: str, scene_id: str):
    """The edits that would clear the scene's failing checks; submit them through PATCH, or send `repair_checks`."""
    return _spatial_call(task_id, scene_id, lambda: service.get_spatial_repairs(task_id, scene_id))


@router.post("/{task_id}/spatial/scenes/{scene_id}/rebuild", response_model=SpatialPlanResponse)
def rebuild_spatial_plan(task_id: str, scene_id: str, req: SpatialRevisionRequest):
    """Discard edits and plan the scene again from the script and the storyboard table."""
    return _spatial_call(task_id, scene_id, lambda: service.rebuild_spatial_plan(
        task_id, scene_id, base_revision=req.base_revision,
    ))


@router.post("/{task_id}/spatial/scenes/{scene_id}/redraw", response_model=SpatialPlanResponse)
def redraw_spatial_scene(task_id: str, scene_id: str):
    """Send a finished scene back to stage 4 so its panels are drawn from the current blocking."""
    return _spatial_call(task_id, scene_id, lambda: service.redraw_spatial_scene(task_id, scene_id))


@router.get("/{task_id}/spatial/scenes/{scene_id}/export", response_model=SpatialExportResponse)
def export_spatial_plan(task_id: str, scene_id: str, format: str = "director-desk"):
    """The stage as a 3D director-desk project or a CoStage document."""
    if format not in {"director-desk", "costage"}:
        raise HTTPException(status_code=422, detail=_text_of("export_spatial_plan.detail"))
    return _spatial_call(task_id, scene_id, lambda: service.export_spatial_plan(task_id, scene_id, format))


@router.post("/{task_id}/spatial/scenes/{scene_id}/import", response_model=SpatialPlanResponse)
def import_spatial_plan(task_id: str, scene_id: str, req: SpatialImportRequest):
    """Bring back positions, facings and camera poses edited in a 3D director desk (matched by name / camera id)."""
    return _spatial_call(task_id, scene_id, lambda: service.import_spatial_plan(
        task_id, scene_id, base_revision=req.base_revision, document=req.document,
    ))


class StagePlanRequest(BaseModel):
    base_revision: int = Field(..., ge=0)
    count: int = Field(3, ge=1, le=3)
    goal: str = Field("", max_length=2000)
    model: str = Field("", max_length=160)


class StageAdoptRequest(BaseModel):
    base_revision: int = Field(..., ge=0)
    candidate_id: str = Field(..., min_length=1, max_length=40)


class StageChatRequest(BaseModel):
    base_revision: int = Field(..., ge=0)
    message: str = Field("", max_length=2000)
    names: List[str] = Field(default_factory=list, max_length=40)
    shot_id: Optional[int] = Field(None, ge=1)
    model: str = Field("", max_length=160)


class StageRevertRequest(BaseModel):
    base_revision: int = Field(..., ge=0)
    snapshot_id: str = Field(..., min_length=1, max_length=40)


class StageBlockoutRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    width_m: Optional[float] = Field(None, gt=0, le=500)
    model: str = Field("", max_length=160)


class StagePlannerModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(model|rules)$")


@router.get("/{task_id}/director-desk/scenes/{scene_id}/director")
def get_stage_director(task_id: str, scene_id: str):
    """The director panel of one scene: the conversation, what can be undone, candidates not yet adopted, the current score."""
    return _spatial_call(task_id, scene_id, lambda: stage_director.state(service, task_id, scene_id))


@router.put("/{task_id}/director-desk/planner")
def set_stage_planner(task_id: str, req: StagePlannerModeRequest):
    """Whether the storyboard stage asks a model for each scene's blocking (the default), or uses the rules alone."""
    return _spatial_call(task_id, "", lambda: stage_director.set_pipeline_planner(service, task_id, req.mode))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/plan")
async def plan_stage_with_model(task_id: str, scene_id: str, req: StagePlanRequest):
    """Several complete stagings from the model, ranked against the rule plan. Costs one or two text calls each; the stage does not change."""
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: stage_director.plan_scene(
        service, task_id, scene_id, base_revision=req.base_revision, count=req.count, goal=req.goal, model=req.model,
    ))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/adopt", response_model=None)
def adopt_stage_candidate(task_id: str, scene_id: str, req: StageAdoptRequest):
    return _spatial_call(task_id, scene_id, lambda: stage_director.adopt_candidate(
        service, task_id, scene_id, candidate_id=req.candidate_id, base_revision=req.base_revision,
    ))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/chat")
async def chat_with_stage_director(task_id: str, scene_id: str, req: StageChatRequest):
    """One message: the model edits a copy, reads back what that did, and goes again up to three times; then it is saved as one undoable step."""
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: stage_director.chat(
        service, task_id, scene_id, message=req.message, base_revision=req.base_revision, names=req.names, shot_id=req.shot_id, model=req.model,
    ))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/optimize")
async def optimize_stage(task_id: str, scene_id: str, req: StageChatRequest):
    """Rules first, then the model; a result that scores lower than what was there is not kept."""
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: stage_director.optimize(
        service, task_id, scene_id, base_revision=req.base_revision, goal=req.message, names=req.names, shot_id=req.shot_id, model=req.model,
    ))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/revert")
def revert_stage_step(task_id: str, scene_id: str, req: StageRevertRequest):
    return _spatial_call(task_id, scene_id, lambda: stage_director.revert(
        service, task_id, scene_id, snapshot_id=req.snapshot_id, base_revision=req.base_revision,
    ))


class StageRestoreRequest(BaseModel):
    snapshot_id: str = Field(..., min_length=1, max_length=40)
    base_revision: Optional[int] = Field(None, ge=0)


@router.post("/{task_id}/director-desk/scenes/{scene_id}/director/restore")
def restore_stage_snapshot(task_id: str, scene_id: str, req: StageRestoreRequest, current_user: dict = Depends(require_owned_drama_task)):
    """侧栏卡片上的「撤销这一步」：回到某个快照(含钉住的)，换下来的舞台另存一步，可以再撤回来。不调模型。"""
    from app.service import stage_director_ops

    return _spatial_call(task_id, scene_id, lambda: stage_director_ops.restore_snapshot(
        service, task_id, scene_id, snapshot_id=req.snapshot_id, base_revision=req.base_revision,
    ))


@router.delete("/{task_id}/director-desk/scenes/{scene_id}/director/chat")
def clear_stage_chat(task_id: str, scene_id: str):
    return _spatial_call(task_id, scene_id, lambda: stage_director.clear_chat(service, task_id, scene_id))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/blockout/describe")
async def describe_desk_blockout(task_id: str, scene_id: str, req: StageBlockoutRequest):
    """Propose a grey-box set from words. Costs one text call; nothing changes until the desk applies it."""
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: stage_director.describe_blockout(
        service, task_id, scene_id, description=req.description, width_m=req.width_m, model=req.model,
    ))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/models/propose")
async def propose_stage_model(
    task_id: str,
    scene_id: str,
    description: str = Form("", max_length=2000),
    width_m: Optional[float] = Form(None, gt=0, le=200),
    depth_m: Optional[float] = Form(None, gt=0, le=200),
    height_m: Optional[float] = Form(None, gt=0, le=200),
    model: str = Form("", max_length=160),
    file: Optional[UploadFile] = File(None, description=_text_of("propose_stage_model.description")),
):
    """One object built from words or a picture. A library model named exactly costs nothing; the stage does not change."""
    image = None
    if file is not None:
        image = await file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        validate_image_upload(file.filename or "", file.content_type or "", image)
    given = (width_m, depth_m, height_m)
    size = list(given) if all(value is not None for value in given) else None
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: stage_director.propose_model(
        service, task_id, scene_id, description=description, size=size, model=model, image=image,
        content_type=file.content_type if file is not None else "",
    ))


@router.get("/{task_id}/director-desk/scenes/{scene_id}/models/{landmark_id}.glb")
def export_stage_model(task_id: str, scene_id: str, landmark_id: str):
    """A set piece as a binary glTF file, at its real size."""
    name, content = _spatial_call(task_id, scene_id, lambda: stage_director.export_model(service, task_id, scene_id, landmark_id))
    return Response(
        content=content, media_type="model/gltf-binary",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.post("/{task_id}/director-desk/scenes/{scene_id}/blockout/analyze")
async def analyze_desk_blockout(
    task_id: str,
    scene_id: str,
    file: UploadFile = File(..., description=_text_of("analyze_desk_blockout.description")),
    hint: str = Form("", max_length=300),
    width_m: Optional[float] = Form(None, gt=0, le=500),
    model: str = Form("", max_length=160),
    current_user: dict = Depends(require_owned_drama_task),
):
    """Propose a grey-box set from a reference image. Costs one vision call; nothing changes until the desk applies it."""
    content = await file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    return await run_in_threadpool(_spatial_call, task_id, scene_id, lambda: service.analyze_stage_blockout(
        task_id, scene_id, content=content, filename=file.filename or "", content_type=file.content_type or "",
        hint=hint, width_m=width_m, model=model,
    ))


@router.get("/{task_id}/director-desk/scenes/{scene_id}/captures", response_model=DeskCapturesResponse)
def list_desk_captures(task_id: str, scene_id: str):
    """The stills and blockout clips taken of one scene's stage, and which of them each shot uses."""
    return _spatial_call(task_id, scene_id, lambda: service.get_desk_captures(task_id, scene_id))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/captures", response_model=DeskCapture)
async def upload_desk_capture(
    task_id: str,
    scene_id: str,
    file: UploadFile = File(..., description=_text_of("upload_desk_capture.description")),
    shot_id: int = Form(...),
    kind: str = Form(...),
    camera_id: str = Form(""),
    plan_revision: int = Form(0),
    shows_limbs: bool = Form(False),
    monochrome: bool = Form(False),
    labelled: bool = Form(False),
    depth: bool = Form(False),
    layer: str = Form("", max_length=20),
    width: int = Form(0),
    height: int = Form(0),
    duration_s: float = Form(0.0),
    fps: int = Form(0),
):
    """Store one capture under the task. The file's own bytes decide what it is, never the declared type."""
    # One byte past the largest thing we accept: enough to know it is too big without holding all of it.
    content = await file.read(MAX_CLIP_BYTES + 1)
    upload = CaptureUpload(
        content=content, kind=kind, shot_id=shot_id, camera_id=camera_id, plan_revision=plan_revision,
        shows_limbs=shows_limbs, monochrome=monochrome, labelled=labelled, depth=depth, layer=layer, width=width, height=height,
        duration_s=duration_s, fps=fps,
    )
    return await run_in_threadpool(
        _spatial_call, task_id, scene_id, lambda: service.add_desk_capture(task_id, scene_id, upload),
    )


@router.delete("/{task_id}/director-desk/scenes/{scene_id}/captures/{capture_id}", response_model=DeskCapturesResponse)
def delete_desk_capture(task_id: str, scene_id: str, capture_id: str):
    """Delete a capture; one a shot was using is taken out of that shot first."""
    return _spatial_call(task_id, scene_id, lambda: service.delete_desk_capture(task_id, scene_id, capture_id))


@router.post("/{task_id}/director-desk/scenes/{scene_id}/captures/{capture_id}/apply", response_model=DeskCapturesResponse)
def apply_desk_capture(task_id: str, scene_id: str, capture_id: str):
    """Hand a capture to stage 5: a still leads the shot's sequence_images, a clip leads its reference_videos."""
    return _spatial_call(task_id, scene_id, lambda: service.apply_desk_capture(task_id, scene_id, capture_id))


# DELETE …/apply is the same request spelled the REST way; the desk client uses it.
@router.delete("/{task_id}/director-desk/scenes/{scene_id}/captures/{capture_id}/apply", response_model=DeskCapturesResponse)
@router.post("/{task_id}/director-desk/scenes/{scene_id}/captures/{capture_id}/unapply", response_model=DeskCapturesResponse)
def unapply_desk_capture(task_id: str, scene_id: str, capture_id: str):
    return _spatial_call(task_id, scene_id, lambda: service.apply_desk_capture(task_id, scene_id, capture_id, applied=False))


@router.get("/{task_id}/director-desk/poses", response_model=DeskPosesResponse)
def list_desk_poses(task_id: str):
    return _spatial_call(task_id, "", lambda: service.get_desk_poses(task_id))


@router.post("/{task_id}/director-desk/poses", response_model=DeskPosesResponse)
def save_desk_pose(task_id: str, req: DeskSavePoseRequest):
    """Save a pose under a name; saving the same name again replaces it."""
    return _spatial_call(task_id, "", lambda: service.save_desk_pose(task_id, req.name, req.pose))


@router.delete("/{task_id}/director-desk/poses/{pose_id}", response_model=DeskPosesResponse)
def delete_desk_pose(task_id: str, pose_id: str):
    return _spatial_call(task_id, "", lambda: service.delete_desk_pose(task_id, pose_id))


@router.post("/{task_id}/relationships/analyze", response_model=WriterDashboardResponse)
def analyze_writer_relationships(task_id: str):
    """Re-derive real character relations from the screenplay with one LLM pass."""
    try:
        dashboard = service.analyze_relationships(task_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except Exception:
        logger.exception("[Writer] 人物关系分析失败 task_id=%s", task_id)
        raise HTTPException(status_code=502, detail=_text_of("analyze_writer_relationships.detail"))
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("analyze_writer_relationships.detail.2"))
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

    if parsed.path.startswith(settings.MEDIA_PREFIX) and parsed.scheme in {"http", "https", ""}:
        media_root = os.path.realpath(MEDIA_DIR)
        local_path = os.path.realpath(
            os.path.join(media_root, unquote(parsed.path[len(settings.MEDIA_PREFIX):]))
        )
        if not local_path.startswith(media_root + os.sep) or not os.path.isfile(local_path):
            raise HTTPException(status_code=404, detail=_text_of("_storyboard_attachment.detail"))
        return FileResponse(
            local_path,
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )

    if parsed.scheme in {"http", "https"}:
        try:
            payload = fetch_remote_image_bytes(url)
        except Exception:
            raise HTTPException(status_code=502, detail=_text_of("_storyboard_attachment.detail.2"))
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )
    raise HTTPException(status_code=404, detail=_text_of("_storyboard_attachment.detail.3"))


def _scene_grid_attachment(shots: list, scene_id: str):
    """Compose and serve one scene's own 3x3 board so the file matches its name."""
    sources = [
        str(entry.get("image_url")).strip()
        for entry in shots
        if isinstance(entry, dict) and str(entry.get("image_url") or "").strip()
    ][:9]
    if not sources:
        raise HTTPException(status_code=404, detail=_text_of("_scene_grid_attachment.detail"))
    safe_scene = "".join(ch for ch in scene_id if ch.isalnum() or ch in "-_")[:40] or "scene"
    digest = hashlib.sha256("\n".join(sources).encode("utf-8")).hexdigest()[:16]
    target_path = os.path.join(MEDIA_DIR, "storyboards", f"scene_{safe_scene}_{digest}.png")
    if not os.path.isfile(target_path):
        try:
            compose_nine_grid(sources, target_path)
        except Exception:
            raise HTTPException(status_code=502, detail=_text_of("_scene_grid_attachment.detail.2"))
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
        raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail"))
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}

    if target == "grid":
        grid_url = assets.get("4_grid")
        if not isinstance(grid_url, str) or not grid_url.strip():
            raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.2"))
        return _storyboard_attachment(grid_url.strip(), "storyboard-grid")

    if target == "scene":
        scene_id = scene.strip()
        if not scene_id:
            raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.3"))
        shots = assets.get("4")
        if not isinstance(shots, list):
            raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.4"))
        scene_shots = [
            entry for entry in shots
            if isinstance(entry, dict)
            and str(entry.get("scene_id") or entry.get("sceneId") or "").strip() == scene_id
        ]
        if not scene_shots:
            raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.5"))
        return _scene_grid_attachment(scene_shots, scene_id)

    if target != "shot":
        raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.6"))
    shots = assets.get("4")
    if not isinstance(shots, list) or not 0 <= shot < len(shots):
        raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.7"))
    entry = shots[shot] if isinstance(shots[shot], dict) else {}
    image_url = entry.get("image_url")
    if not isinstance(image_url, str) or not image_url.strip():
        raise HTTPException(status_code=404, detail=_text_of("download_storyboard_image.detail.8"))
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
            is_admin=has_permission(current_user, PROJECT_WRITE_ANY),
        )
    except ScriptUpdateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("update_script.detail"))
    return dashboard


@router.get("/{task_id}/character-dashboard/export")
def export_character_dashboard(task_id: str):
    """Download the normalized Character Designer five-view contract as JSON."""
    dashboard = service.get_character_dashboard(task_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail=_text_of("export_character_dashboard.detail"))
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
        raise HTTPException(status_code=404, detail=_text_of("get_character_dashboard.detail"))
    return dashboard

@router.post("/{task_id}/next", response_model=DramaTaskResponse)
async def run_next_stage(task_id: str, current_stage: int):
    """
    一步一步引导模式：启动执行指定步骤阶段
    """
    try:
        await service.execute_stage(task_id, current_stage)
        return service.get_task_status(task_id)
    except StagePrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("run_next_stage.detail").format(current_stage, str(e)))

@router.post("/{task_id}/pause", response_model=DramaTaskResponse)
def pause_running_task(task_id: str):
    """
    暂停正在执行中的一键成片任务 (断点锁定)
    """
    task = service.pause_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("pause_running_task.detail"))
    return task

@router.post("/{task_id}/resume", response_model=DramaTaskResponse)
async def resume_paused_task(task_id: str, background_tasks: BackgroundTasks):
    """
    恢复被暂停的任务，并自动在后台线程中继续一键生成
    """
    if not service.repo.get_task(task_id):
        raise HTTPException(status_code=404, detail=_text_of("resume_paused_task.detail"))
    return (await service.assistant_message(task_id, _text_of("resume_paused_task.text")))["task"]

@router.post("/{task_id}/run_all", response_model=DramaTaskResponse)
async def run_all_stages_one_click(task_id: str, background_tasks: BackgroundTasks):
    """
    一键成片模式：异步在后台连续串行运行 1 到 8 步骤
    """
    if not service.repo.get_task(task_id):
        raise HTTPException(status_code=404, detail=_text_of("run_all_stages_one_click.detail"))
    return (await service.assistant_message(task_id, _text_of("run_all_stages_one_click.text")))["task"]

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
        raise HTTPException(status_code=500, detail=_text_of("plan_episodes_route.detail").format(str(e)))

@router.get("/{task_id}/episodes")
def list_episodes_route(task_id: str):
    """获取多集制作清单与各集状态、成片地址。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("list_episodes_route.detail"))
    eps = task.get("episodes", []) or []
    return {
        "sourceHash": compile_writer_dashboard(task).source_hash,
        "totalEpisodes": task.get("total_episodes", len(eps)),
        "currentEpisode": task.get("current_episode", 0),
        "episodes": [{"index": e.get("index"), "title": e.get("title"), "status": e.get("status"),
                      "videoUrl": e.get("video_url"), "shotsCount": len(e.get("shots") or []),
                      "summary": e.get("summary", ""), "failReason": e.get("fail_reason")} for e in eps],
    }

@router.post("/{task_id}/episodes/{ep_index}/produce")
def produce_episode_route(task_id: str, ep_index: int, background_tasks: BackgroundTasks):
    """逐集制作：后台异步生成指定集 (分镜->尾帧链式逐镜生成->情绪配音->合成2.5-3min单集)。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("produce_episode_route.detail"))
    if not task.get("episodes"):
        raise HTTPException(status_code=400, detail=_text_of("produce_episode_route.detail.2"))
    ep = next((e for e in task["episodes"] if e.get("index") == ep_index), None)
    if not ep:
        raise HTTPException(status_code=404, detail=_text_of("produce_episode_route.detail.3").format(ep_index))

    async def _run():
        try:
            await service.produce_episode(task_id, ep_index)
        except Exception as e:
            import logging
            logging.getLogger("app.api.drama_api").error(f"制作第{ep_index}集失败: {str(e)}")

    background_tasks.add_task(_run)
    ep["status"] = "running"
    repo.save_task(task_id, task)
    return {"status": "running", "episode": ep_index, "message": _text_of("produce_episode_route.message").format(ep_index)}

@router.post("/{task_id}/assistant")
async def assistant_chat(task_id: str, payload: Dict[str, Any], current_user: dict = Depends(require_owned_drama_task)):
    """
    自然语言流程助手：意图识别 (执行下一步/重跑阶段N/暂停/查询进度/微调/答疑)，
    执行类动作后台异步启动并立即返回；前端轮询 /status 的 stageProgress 展示调用过程与进度条。
    payload.context 是侧栏带来的界面状态(scene_id / shot_id / character / view / stage)，只告诉工具助手当前打开了什么。
    """
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail=_text_of("assistant_chat.detail"))
    raw_context = payload.get("context")
    context = {
        key: value for key, value in (raw_context.items() if isinstance(raw_context, dict) else ())
        if key in ("scene_id", "shot_id", "character", "view", "stage") and isinstance(value, (str, int)) and not isinstance(value, bool)
    } or None
    try:
        result = await service.assistant_message(task_id, message, user=current_user, context=context)
        return {
            "reply": result["reply"],
            "action": result["action"],
            "stage": result["stage"],
            "task": DramaTaskResponse(**result["task"]).model_dump(by_alias=True),
            "tool_calls": result.get("tool_calls") or [],
            "proposal": result.get("proposal"),
        }
    except StagePrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("assistant_chat.detail.2").format(str(e)))


@router.post("/{task_id}/chat", response_model=DramaTaskResponse)
async def chat_with_agent(task_id: str, payload: Dict[str, str]):
    """
    通过对话引导智能体进行短剧内容调整与创作
    """
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail=_text_of("chat_with_agent.detail"))
    try:
        updated_task = await service.chat_instruction(task_id, message)
        return updated_task
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("chat_with_agent.detail.2").format(str(e)))


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
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("update_task_config.detail").format(str(e)))
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("update_task_config.detail.2"))
    return task

@router.post("/import_skill")
async def import_new_skill(
    import_type: str = Form(..., description=_text_of("import_new_skill.description")),
    url: Optional[str] = Form(None, description=_text_of("import_new_skill.description.2")),
    package_name: Optional[str] = Form(None, description=_text_of("import_new_skill.description.3")),
    file: Optional[UploadFile] = File(None, description=_text_of("import_new_skill.description.4")),
    _admin: dict = Depends(require_permission(SKILL_MANAGE)),
):
    """
    导入并添加外部自定义 Skill 技能包
    """
    try:
        result = await service.import_skill_logic(import_type, url, package_name, file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("import_new_skill.detail").format(str(e)))

@router.get("/skills", response_model=List[Dict[str, Any]])
def get_imported_skills():
    """
    获取所有已导入的 Skill 技能列表
    """
    return service.get_all_skills()

@router.delete("/skills/{skill_name}")
def delete_imported_skill(skill_name: str, _admin: dict = Depends(require_permission(SKILL_MANAGE))):
    """
    删除指定的已导入 Skill 技能包
    """
    try:
        result = service.delete_skill_logic(skill_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("delete_imported_skill.detail").format(str(e)))

@router.delete("/{task_id}")
def delete_drama_task(task_id: str):
    """
    物理删除指定的短剧生成任务
    """
    try:
        success = service.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail=_text_of("delete_drama_task.detail"))
        return {"status": "success", "message": _text_of("delete_drama_task.message").format(task_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("delete_drama_task.detail.2").format(str(e)))

@router.post("/seedance2_video")
async def seedance2_video_route(payload: Dict[str, Any]):
    """
    Seedance 2.0 多模态生视频统一接口(禁止文生视频：至少要有首帧、参考图或参考视频)：
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
    if not (first_frame or ref_images or ref_videos):
        # 禁止文生视频：只有提示词、没有首帧或参考素材的请求不提交。
        raise HTTPException(status_code=400, detail=_text_of("seedance2_video_route.detail"))
    if ref_audios and not (ref_images or ref_videos or first_frame):
        raise HTTPException(status_code=400, detail=_text_of("seedance2_video_route.detail.2"))
    try:
        result = await service.generate_seedance2_video(
            prompt, first_frame=first_frame, last_frame=last_frame,
            ref_images=ref_images, ref_videos=ref_videos, ref_audios=ref_audios, optimize=optimize
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=_text_of("seedance2_video_route.detail.3").format(str(e)))

@router.post("/parse_script")
async def parse_script_file_route(file: UploadFile = File(..., description=_text_of("parse_script_file_route.description"))):
    """
    手动上传剧本文件解析接口，支持 .txt, .md, .docx, .pdf, .fdx, .fountain, .spmd。
    """
    try:
        # 与解析器同一个上限：接口先于解析器拦截，两边数字不一致时会出现“接口放行、解析拒绝”
        maximum = SourceIngestor.MAX_BYTES
        file_bytes = await file.read(maximum + 1)
        if len(file_bytes) > maximum:
            raise ValueError(_text_of("parse_script_file_route.text").format(maximum // (1024 * 1024)))
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
        raise HTTPException(status_code=500, detail=_text_of("parse_script_file_route.detail").format(str(e)))
