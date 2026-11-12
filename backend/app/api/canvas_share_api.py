"""Read-only canvas share links: the owner's controls and the anonymous viewer's read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth_api import get_current_user
from app.api.studio_api import _owner, _safe_error, get_studio_service
from app.schema.studio import CanvasId, CanvasShareCreate, CanvasShareRecord
from app.service.canvas_share_service import (
    PUBLIC_SHARE_LIMITER,
    CanvasShareNotFound,
    CanvasShareService,
    SlidingWindowLimiter,
)
from app.service.studio_service import StudioService

router = APIRouter(prefix="/api/studio", tags=["画布分享"])
public_router = APIRouter(prefix="/api/public", tags=["画布分享"])

# A share page is someone's unpublished work behind a capability URL: never cached, never indexed.
_PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
# One body for unknown, expired and stopped tokens, so a token cannot be probed for having existed.
_NOT_FOUND = {"detail": "Not Found"}


def get_canvas_share_service(studio: StudioService = Depends(get_studio_service)) -> CanvasShareService:
    return CanvasShareService(studio.repository)


def get_share_rate_limiter() -> SlidingWindowLimiter:
    return PUBLIC_SHARE_LIMITER


@router.get("/projects/{project_id}/canvases/{canvas_id}/share", response_model=CanvasShareRecord | None)
def get_canvas_share(
    project_id: str,
    canvas_id: CanvasId,
    current_user: dict = Depends(get_current_user),
    shares: CanvasShareService = Depends(get_canvas_share_service),
):
    try:
        return shares.get_share(project_id, _owner(current_user), canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.post("/projects/{project_id}/canvases/{canvas_id}/share", response_model=CanvasShareRecord)
def create_canvas_share(
    project_id: str,
    canvas_id: CanvasId,
    request: CanvasShareCreate | None = None,
    current_user: dict = Depends(get_current_user),
    shares: CanvasShareService = Depends(get_canvas_share_service),
):
    try:
        return shares.create_share(project_id, _owner(current_user), canvas_id, (request or CanvasShareCreate()).expires_days)
    except Exception as exc:
        raise _safe_error(exc) from exc


@router.delete("/projects/{project_id}/canvases/{canvas_id}/share")
def stop_canvas_share(
    project_id: str,
    canvas_id: CanvasId,
    current_user: dict = Depends(get_current_user),
    shares: CanvasShareService = Depends(get_canvas_share_service),
):
    try:
        return shares.stop_share(project_id, _owner(current_user), canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


@public_router.get("/canvas-shares/{token}")
def read_canvas_share(
    token: str,
    request: Request,
    shares: CanvasShareService = Depends(get_canvas_share_service),
    limiter: SlidingWindowLimiter = Depends(get_share_rate_limiter),
):
    """No login: the token is the permission. Counted per client address before the token is even looked at."""
    client = f"ip:{request.client.host if request.client else 'unknown'}"
    if not limiter.allow(client):
        return JSONResponse(
            status_code=429, content={"detail": "访问过于频繁，请稍后再试"},
            headers={**_PUBLIC_HEADERS, "Retry-After": str(limiter.retry_after(client))},
        )
    try:
        body = shares.public_canvas(token)
    except CanvasShareNotFound:
        return JSONResponse(status_code=404, content=_NOT_FOUND, headers=_PUBLIC_HEADERS)
    return JSONResponse(content=body, headers=_PUBLIC_HEADERS)
