"""The platform submission pack (剧本附件) of a project: write its model items, then download it.

``POST`` writes the items the project's text model fills (audience, world, category, paywall episode,
synopsis, outline, main characters) unless the kept ones still match the script; ``GET`` lays the
attachment out from the project as it stands, as JSON, Markdown or a Word document, without a model call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from app.api import drama_api
from app.api.drama_api import require_owned_drama_task
from app.core import submission_pack
from app.service import submission_pack_service

router = APIRouter(prefix="/api/drama", tags=["submission"], dependencies=[Depends(require_owned_drama_task)])

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SubmissionPackRequest(BaseModel):
    refresh: bool = False


@router.post("/{task_id}/submission-pack")
async def build_submission_pack(task_id: str, req: SubmissionPackRequest | None = None):
    """Text-model calls (one for the details, one per ten episodes of outline) unless the kept items still match."""
    try:
        pack = await run_in_threadpool(submission_pack_service.build, drama_api.service, task_id, refresh=bool(req and req.refresh))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if pack is None:
        raise HTTPException(status_code=404, detail=submission_pack.not_found_text())
    return pack


@router.get("/{task_id}/submission-pack")
def download_submission_pack(task_id: str, format: str = Query("json", pattern="^(json|md|docx)$")):
    pack = submission_pack_service.current(drama_api.service, task_id)
    if pack is None:
        raise HTTPException(status_code=404, detail=submission_pack.not_found_text())
    if format == "md":
        return Response(
            content=submission_pack.render_markdown(pack), media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="submission-pack.md"'},
        )
    if format == "docx":
        return Response(
            content=submission_pack.render_docx(pack), media_type=_DOCX,
            headers={"Content-Disposition": 'attachment; filename="submission-pack.docx"'},
        )
    return pack
