"""Least-privilege API for external production agents and automations."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.studio_api import get_studio_service
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import (
    AgentAuthorization,
    ArtifactCreateRequest,
    GenerationJobRequest,
)
from app.service.studio_service import StudioService


router = APIRouter(prefix="/api/agent", tags=["作用域外部 Agent API"])


def require_agent_scope(scope: str) -> Callable:
    def dependency(
        authorization: str | None = Header(None),
        service: StudioService = Depends(get_studio_service),
    ) -> AgentAuthorization:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="缺少外部 Agent 凭据")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            return service.repository.verify_agent_key(token, required_scope=scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="凭据无效、已撤销或权限不足") from exc

    return dependency


def _assert_project(auth: AgentAuthorization, project_id: str) -> None:
    if auth.project_id != project_id:
        raise HTTPException(status_code=403, detail="凭据不属于该项目")


def _agent_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=404, detail="资源不存在")
    if isinstance(exc, ConcurrencyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="外部 Agent 服务暂不可用")


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(
    project_id: str,
    auth: AgentAuthorization = Depends(require_agent_scope("project.read")),
    service: StudioService = Depends(get_studio_service),
):
    _assert_project(auth, project_id)
    try:
        return service.list_artifacts(project_id, auth.owner_id)
    except Exception as exc:
        raise _agent_error(exc) from exc


@router.post("/projects/{project_id}/artifacts")
def put_artifact(
    project_id: str,
    request: ArtifactCreateRequest,
    auth: AgentAuthorization = Depends(require_agent_scope("artifact.write")),
    service: StudioService = Depends(get_studio_service),
):
    _assert_project(auth, project_id)
    try:
        return service.put_artifact(project_id, auth.owner_id, request)
    except Exception as exc:
        raise _agent_error(exc) from exc


@router.post("/projects/{project_id}/jobs")
def create_job(
    project_id: str,
    request: GenerationJobRequest,
    auth: AgentAuthorization = Depends(require_agent_scope("job.submit")),
    service: StudioService = Depends(get_studio_service),
):
    _assert_project(auth, project_id)
    try:
        return service.create_job(project_id, auth.owner_id, request)
    except Exception as exc:
        raise _agent_error(exc) from exc


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    auth: AgentAuthorization = Depends(require_agent_scope("job.read")),
    service: StudioService = Depends(get_studio_service),
):
    try:
        job = service.get_job(job_id, auth.owner_id)
        if job["project_id"] != auth.project_id:
            raise HTTPException(status_code=403, detail="凭据不属于该任务项目")
        return job
    except HTTPException:
        raise
    except Exception as exc:
        raise _agent_error(exc) from exc
