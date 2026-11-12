"""Live presence between one account's windows of a canvas, over Server-Sent Events.

GET  .../canvases/{canvas_id}/presence/stream  the window's event stream (peers, cursor, drag, selection, left, saved)
POST .../canvases/{canvas_id}/presence         one cursor / drag / selection / leave message from a window
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app import settings
from app.api.auth_api import get_current_user
from app.api.studio_api import _owner, _safe_error, get_studio_service
from app.schema.studio import CanvasId
from app.service import canvas_presence
from app.service.canvas_presence import (
    CLIENT_ID_PATTERN,
    LABEL_MAX_CHARS,
    PresenceHub,
    PresenceRateLimited,
    PresenceRefused,
    PresenceUnknownClient,
)
from app.service.studio_service import StudioService
from app.core import prompt_data


_WORDING_FILE = "api_canvas_presence_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_canvas_presence_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

router = APIRouter(prefix="/api/studio", tags=list(_words_of("module.tags")))

MAX_BODY_BYTES = 32 * 1024
_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def get_presence_hub() -> PresenceHub:
    return canvas_presence.hub


def get_allowed_origins() -> list[str]:
    return settings.allowed_origins()


class PresenceRect(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=120)
    x: float
    y: float
    width: float
    height: float


class PresenceMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    type: Literal["cursor", "drag", "selection", "leave"]
    x: float | None = None
    y: float | None = None
    rects: list[PresenceRect] | None = Field(None, max_length=100)
    ids: list[Annotated[str, Field(max_length=120)]] | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _fields_for_type(self) -> PresenceMessage:
        if self.type == "cursor" and (self.x is None or self.y is None):
            raise ValueError("cursor needs x and y")
        if self.type == "drag" and self.rects is None:
            raise ValueError("drag needs rects")
        if self.type == "selection" and self.ids is None:
            raise ValueError("selection needs ids")
        return self


async def _owned_board(service: StudioService, project_id: str, owner_id: str, canvas_id: str) -> None:
    """Unknown project, someone else's project and unknown board all answer 404."""
    try:
        boards = await run_in_threadpool(service.list_canvases, project_id, owner_id)
    except Exception as exc:
        raise _safe_error(exc) from exc
    if not any(str(board.get("id")) == canvas_id for board in boards):
        raise HTTPException(status_code=404, detail=_text_of("_owned_board.detail"))


@router.get("/projects/{project_id}/canvases/{canvas_id}/presence/stream")
async def presence_stream(
    project_id: str,
    canvas_id: CanvasId,
    request: Request,
    client_id: str = Query(..., pattern=CLIENT_ID_PATTERN),
    label: str = Query("", max_length=LABEL_MAX_CHARS),
    current_user: dict = Depends(get_current_user),
    service: StudioService = Depends(get_studio_service),
    hub: PresenceHub = Depends(get_presence_hub),
    allowed_origins: list[str] = Depends(get_allowed_origins),
):
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins:
        return JSONResponse(status_code=403, content={"detail": _text_of("presence_stream.content.detail")})
    owner_id = _owner(current_user)
    await _owned_board(service, project_id, owner_id, canvas_id)
    try:
        subscription = hub.open_stream(owner_id, project_id, canvas_id, client_id, label)
    except PresenceRefused as exc:
        return JSONResponse(status_code=429, content={"detail": str(exc)}, headers={"Retry-After": "5"})
    return StreamingResponse(hub.stream(subscription), media_type="text/event-stream", headers=_STREAM_HEADERS)


async def _read_limited(request: Request) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


@router.post("/projects/{project_id}/canvases/{canvas_id}/presence", status_code=204)
async def presence_message(
    project_id: str,
    canvas_id: CanvasId,
    request: Request,
    current_user: dict = Depends(get_current_user),
    hub: PresenceHub = Depends(get_presence_hub),
):
    """No database read: the room is keyed by the caller's own account, so only its own open streams match."""
    body = await _read_limited(request)
    if body is None:
        return JSONResponse(status_code=413, content={"detail": _text_of("presence_message.content.detail")})
    try:
        message = PresenceMessage.model_validate_json(body or b"{}")
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": exc.errors(include_url=False, include_context=False, include_input=False)})
    try:
        hub.publish(_owner(current_user), project_id, canvas_id, message.client_id, message.model_dump(mode="json"))
    except PresenceUnknownClient as exc:
        raise HTTPException(status_code=404, detail=_text_of("presence_message.detail")) from exc
    except PresenceRateLimited:
        return JSONResponse(status_code=429, content={"detail": _text_of("presence_message.content.detail.2")}, headers={"Retry-After": "1"})
    return Response(status_code=204)
