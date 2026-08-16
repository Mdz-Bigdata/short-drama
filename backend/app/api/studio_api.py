"""Authenticated studio platform API."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.api.auth_api import get_current_user
from app.ingest.parsers import SourceIngestError, SourceIngestor
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import (
    ArtifactCreateRequest,
    AssetReadinessRequest,
    ExportPreviewRequest,
    GenerationJobRequest,
    JobTransitionRequest,
    ProjectCreate,
    AgentKeyCreateRequest,
    CanvasPromoteRequest,
    CanvasDuplicateRequest,
    CanvasPutRequest,
    CostEventRequest,
    DirectorWorldPutRequest,
    ReviewCreateRequest,
)
from app.service.project_archive import ProjectArchiveService
from app.service.studio_service import StudioService


router = APIRouter(prefix="/api/studio", tags=["可追溯短剧工作室"])


@lru_cache(maxsize=1)
def get_studio_service() -> StudioService:
    return StudioService()


def _owner(current_user: dict) -> str:
    return str(current_user["user_id"])


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


@router.get("/projects/{project_id}/canvas")
def get_canvas(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.get_canvas(project_id, _owner(current_user))
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.put("/projects/{project_id}/canvas")
def put_canvas(
    project_id: str,
    request: CanvasPutRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.put_canvas(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/promote")
def promote_canvas_node(
    project_id: str,
    request: CanvasPromoteRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.promote_canvas_node(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvas/duplicate")
def duplicate_canvas_nodes(
    project_id: str,
    request: CanvasDuplicateRequest,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.duplicate_canvas_nodes(project_id, _owner(current_user), request)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/projects/{project_id}/canvas/outline")
def canvas_outline(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
):
    try:
        return service.canvas_outline(project_id, _owner(current_user))
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
