"""Authenticated studio platform API."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.api.auth_api import get_current_user
from app.platform.access_audit import record_access_from_thread
from app.platform.permissions import authorize
from app.ingest.parsers import SourceIngestError, SourceIngestor
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import (
    CANVAS_MAIN_ID,
    ArtifactCreateRequest,
    AssetReadinessRequest,
    ExportPreviewRequest,
    GenerationJobRequest,
    JobTransitionRequest,
    ProjectCreate,
    AgentKeyCreateRequest,
    CanvasAssessRequest,
    CanvasBoardCreate,
    CanvasBoardPatch,
    CanvasCommitPreviewRequest,
    CanvasCommitRequest,
    CanvasId,
    CanvasPromoteRequest,
    CanvasDuplicateRequest,
    CanvasPutRequest,
    CanvasRestoreRequest,
    CanvasRunCancelRequest,
    CanvasRunRequest,
    CostEventRequest,
    DirectorWorldPutRequest,
    ReviewCreateRequest,
)
from app.service.project_archive import ProjectArchiveService
from app.service.studio_service import MAX_CANVAS_VIDEO_BYTES, StudioService


router = APIRouter(prefix="/api/studio", tags=["可追溯短剧工作室"])


@lru_cache(maxsize=1)
def get_studio_service() -> StudioService:
    return StudioService()


def get_drama_service():
    # Imported here: drama_api builds the whole production service at import time, and every
    # other studio route has no use for it.
    from app.api.drama_api import service

    return service


def _owner(current_user: dict) -> str:
    return str(current_user["user_id"])


def _canvas_id(canvas_id: CanvasId = Query(CANVAS_MAIN_ID)) -> str:
    return canvas_id


def _safe_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=404, detail="资源不存在")
    if isinstance(exc, ConcurrencyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (ValueError, SourceIngestError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="工作室服务暂不可用")


@router.post("/projects")
def create_project(
    request: ProjectCreate,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    return service.create_project(_owner(current_user), request)


@router.get("/projects")
def list_projects(
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    return service.list_projects(_owner(current_user))


@router.post("/projects/{project_id}/sources")
async def ingest_source(
    project_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        content = await file.read(SourceIngestor.MAX_BYTES + 1)
        return service.ingest_source(
            project_id, _owner(current_user), file.filename or "source.txt", content,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/artifacts")
def put_artifact(
    project_id: str,
    request: ArtifactCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.put_artifact(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_artifacts(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/jobs")
def create_job(
    project_id: str,
    request: GenerationJobRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.create_job(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/jobs")
def list_jobs(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_jobs(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.get_job(job_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/jobs/{job_id}/transition")
def transition_job(
    job_id: str,
    request: JobTransitionRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.transition_job(job_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.cancel_job(job_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/assets/readiness")
def asset_readiness(
    request: AssetReadinessRequest,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    return StudioService.asset_readiness(request)


@router.post("/exports/preview")
def export_preview(
    request: ExportPreviewRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    del current_user
    try:
        return service.export_preview(request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/agent-keys")
def issue_agent_key(
    project_id: str,
    request: AgentKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.issue_agent_key(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.delete("/agent-keys/{key_id}")
def revoke_agent_key(
    key_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.revoke_agent_key(key_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/artifacts/{artifact_id}/reviews")
def create_review(
    artifact_id: str,
    request: ReviewCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.create_review(artifact_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/artifacts/{artifact_id}/reviews")
def list_reviews(
    artifact_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_reviews(artifact_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/tasks/{task_id}/canvas-project")
def open_task_canvas_project(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    """The studio project holding this person's canvases for a drama task; ownership as drama_api checks it."""
    task = drama.repo.get_task(task_id)
    user_id = _owner(current_user)
    owner_id = str((task or {}).get("owner_user_id") or "")
    decision = authorize(current_user, owner_id=owner_id, write=True) if task else None
    if not decision or not decision.allowed:
        raise HTTPException(status_code=404, detail="任务不存在")
    if decision.cross_account:
        record_access_from_thread(current_user, resource_id=task_id, owner_id=owner_id, write=True, via="studio.task_canvas")
    title = str((task.get("config") or {}).get("title_suggestion") or "画布")
    try:
        return service.task_canvas_project(task_id, user_id, title)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvases")
def list_canvases(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_canvases(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvases")
def create_canvas(
    project_id: str,
    request: CanvasBoardCreate,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.create_canvas(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.patch("/projects/{project_id}/canvases/{canvas_id}")
def patch_canvas(
    project_id: str,
    canvas_id: CanvasId,
    request: CanvasBoardPatch,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.patch_canvas(project_id, _owner(current_user), canvas_id, request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.delete("/projects/{project_id}/canvases/{canvas_id}")
def delete_canvas(
    project_id: str,
    canvas_id: CanvasId,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.delete_canvas(project_id, _owner(current_user), canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas")
def get_canvas(
    project_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.get_canvas(project_id, _owner(current_user), canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.put("/projects/{project_id}/canvas")
def put_canvas(
    project_id: str,
    request: CanvasPutRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.put_canvas(project_id, _owner(current_user), request, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/promote")
def promote_canvas_node(
    project_id: str,
    request: CanvasPromoteRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.promote_canvas_node(project_id, _owner(current_user), request, canvas_id=canvas_id, drama=drama, user=current_user)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/duplicate")
def duplicate_canvas_nodes(
    project_id: str,
    request: CanvasDuplicateRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.duplicate_canvas_nodes(project_id, _owner(current_user), request, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/outline")
def canvas_outline(
    project_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.canvas_outline(project_id, _owner(current_user), canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/versions")
def list_canvas_versions(
    project_id: str,
    canvas_id: str = Depends(_canvas_id),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_canvas_versions(project_id, _owner(current_user), canvas_id=canvas_id, limit=limit)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/versions/{version}/restore")
def restore_canvas_version(
    project_id: str,
    version: int,
    request: CanvasRestoreRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.restore_canvas_version(project_id, _owner(current_user), version, expected_version=request.expected_version, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/uploads")
async def upload_canvas_media(
    project_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        content = await file.read(MAX_CANVAS_VIDEO_BYTES + 1)
        return service.store_canvas_upload(project_id, _owner(current_user), file.filename or "", file.content_type or "", content)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/run-options")
def canvas_run_options(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.canvas_run_options(project_id, _owner(current_user), drama, current_user)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/shots")
def canvas_shots(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.canvas_shots(project_id, _owner(current_user), drama, current_user)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/runs/assess")
def assess_canvas_run(
    project_id: str,
    request: CanvasAssessRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.assess_canvas_run(
            project_id, _owner(current_user), canvas_id=canvas_id, node_ids=request.node_ids,
            confirmed=[item.model_dump() for item in request.confirmed_request_durations], drama=drama, user=current_user,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/runs")
def start_canvas_run(
    project_id: str,
    request: CanvasRunRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    """Nothing paid starts unless ``confirm`` is true; without it the answer is what would happen and what it costs."""
    try:
        return service.start_canvas_run(
            project_id, _owner(current_user), canvas_id=canvas_id, node_ids=request.node_ids, expected_version=request.expected_version,
            operation_id=request.operation_id, confirm=request.confirm,
            confirmed=[item.model_dump() for item in request.confirmed_request_durations], drama=drama, user=current_user,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/runs/{batch_id}/cancel")
def cancel_canvas_run(
    project_id: str,
    batch_id: str,
    request: CanvasRunCancelRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.cancel_canvas_run(project_id, _owner(current_user), batch_id, request.key)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/outputs")
def canvas_outputs(
    project_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.canvas_outputs(project_id, _owner(current_user), canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/nodes/{node_id}/history")
def canvas_node_history(
    project_id: str,
    node_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.canvas_node_history(project_id, _owner(current_user), node_id, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/nodes/{node_id}/history/{run_id}/restore")
def restore_canvas_run(
    project_id: str,
    node_id: str,
    run_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.restore_canvas_run(project_id, _owner(current_user), node_id, run_id, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.delete("/projects/{project_id}/canvas/nodes/{node_id}/history/{run_id}")
def delete_canvas_run(
    project_id: str,
    node_id: str,
    run_id: str,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.delete_canvas_run(project_id, _owner(current_user), node_id, run_id, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/commit/preview")
def preview_canvas_commit(
    project_id: str,
    request: CanvasCommitPreviewRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.preview_canvas_commit(project_id, _owner(current_user), canvas_id=canvas_id, node_ids=request.node_ids, drama=drama, user=current_user)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/commit")
def commit_canvas_nodes(
    project_id: str,
    request: CanvasCommitRequest,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    drama=Depends(get_drama_service),
):
    try:
        return service.commit_canvas_nodes(
            project_id, _owner(current_user), canvas_id=canvas_id, node_ids=request.node_ids, expected_version=request.expected_version, drama=drama, user=current_user,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/director-world")
def get_director_world(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.get_director_world(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.put("/projects/{project_id}/director-world")
def put_director_world(
    project_id: str,
    request: DirectorWorldPutRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.put_director_world(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/director-world/frame-plan")
def director_frame_plan(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.director_frame_plan(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/costs")
def record_cost(
    project_id: str,
    request: CostEventRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.record_cost(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/costs")
def list_costs(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.list_costs(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/costs/summary")
def cost_summary(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.cost_summary(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/archive")
def export_project_archive(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        content = service.export_project_archive(project_id, _owner(current_user))
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_id}.sdarchive"'},
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/import")
async def import_project_archive(
    file: UploadFile = File(...),
    project_name: str = Query(..., min_length=1, max_length=160),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        content = await file.read(ProjectArchiveService.MAX_ARCHIVE_BYTES + 1)
        return service.import_project_archive(
            content,
            owner_id=_owner(current_user),
            project_name=project_name,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc
