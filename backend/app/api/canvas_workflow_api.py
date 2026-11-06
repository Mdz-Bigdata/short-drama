# -*- coding: utf-8 -*-
"""Canvas workflows: a brief becomes a draft, a draft goes onto the canvas, and the canvas's own runs do the rest."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.auth_api import get_current_user
from app.api.studio_api import _canvas_id, _owner, _safe_error, get_drama_service, get_studio_service
from app.service.canvas_workflow_service import MAX_BRIEF_CHARS, CanvasWorkflowService
from app.service.studio_service import StudioService

router = APIRouter(prefix="/api/studio/projects/{project_id}/canvas/workflows", tags=["画布工作流"])


class WorkflowPlanRequest(BaseModel):
    brief: Annotated[str, Field(min_length=1, max_length=MAX_BRIEF_CHARS)]


class WorkflowCreateRequest(BaseModel):
    brief: Annotated[str, Field(max_length=MAX_BRIEF_CHARS)] = ""
    plan: dict[str, Any]


class WorkflowUpdateRequest(BaseModel):
    plan: dict[str, Any]


class WorkflowApplyRequest(BaseModel):
    # The canvas this person is looking at; if it has moved on they should see that before adding to it.
    expected_version: Annotated[int, Field(ge=0)] | None = None


def _workflows(service: StudioService = Depends(get_studio_service)) -> CanvasWorkflowService:
    return CanvasWorkflowService(service)


@router.get("")
def list_workflows(
    project_id: str, canvas_id: str = Depends(_canvas_id), current_user: dict = Depends(get_current_user), workflows: CanvasWorkflowService = Depends(_workflows),
):
    try:
        return workflows.list(project_id, _owner(current_user), canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/plan")
async def plan_workflow(
    project_id: str, request: WorkflowPlanRequest, canvas_id: str = Depends(_canvas_id), current_user: dict = Depends(get_current_user),
    workflows: CanvasWorkflowService = Depends(_workflows), drama=Depends(get_drama_service),
):
    """One text-model call (more if its answer has to be corrected). Writes a draft, not the canvas."""
    try:
        return await run_in_threadpool(
            workflows.plan, project_id, _owner(current_user), canvas_id=canvas_id, brief=request.brief, drama=drama, user=current_user,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("")
def create_workflow(
    project_id: str, request: WorkflowCreateRequest, canvas_id: str = Depends(_canvas_id), current_user: dict = Depends(get_current_user),
    workflows: CanvasWorkflowService = Depends(_workflows),
):
    try:
        return workflows.create(project_id, _owner(current_user), canvas_id=canvas_id, brief=request.brief, plan=request.plan)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.get("/{workflow_id}")
def get_workflow(
    project_id: str, workflow_id: str, current_user: dict = Depends(get_current_user), workflows: CanvasWorkflowService = Depends(_workflows),
):
    try:
        return workflows.status(project_id, _owner(current_user), workflow_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.put("/{workflow_id}")
def update_workflow(
    project_id: str, workflow_id: str, request: WorkflowUpdateRequest, current_user: dict = Depends(get_current_user), workflows: CanvasWorkflowService = Depends(_workflows),
):
    try:
        return workflows.update(project_id, _owner(current_user), workflow_id, request.plan)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/{workflow_id}/apply")
def apply_workflow(
    project_id: str, workflow_id: str, request: WorkflowApplyRequest, current_user: dict = Depends(get_current_user), workflows: CanvasWorkflowService = Depends(_workflows),
):
    """Every step goes on as one canvas version, or none does. Running it is a separate, confirmed step."""
    try:
        return workflows.apply(project_id, _owner(current_user), workflow_id, base_version=request.expected_version)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.delete("/{workflow_id}")
def delete_workflow(
    project_id: str, workflow_id: str, current_user: dict = Depends(get_current_user), workflows: CanvasWorkflowService = Depends(_workflows),
):
    try:
        return workflows.delete(project_id, _owner(current_user), workflow_id)
    except Exception as exc:
        raise _safe_error(exc) from exc

