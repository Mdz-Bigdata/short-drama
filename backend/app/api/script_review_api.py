"""The review report of a project's script: read the kept one, ask for a new one, download it.

``GET`` returns the kept report (or none), whether the script changed since, the facts counted from the
script and how many text-model calls a new report takes; no model is called. ``POST`` reads the script
with the project's text model, one call per block of episodes, and keeps the report. The report is
advice: it changes nothing in the script.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api import drama_api
from app.api.drama_api import require_owned_drama_task
from app.core import script_review
from app.service import script_review_service

router = APIRouter(prefix="/api/drama", tags=["script-review"], dependencies=[Depends(require_owned_drama_task)])


_FOCUS = Query("", max_length=40, pattern="^[a-z_]*$", description="A focused check instead of the full review; see ``focuses`` in the answer.")


def _found(shown: dict | None) -> dict:
    if shown is None:
        raise HTTPException(status_code=404, detail=str(script_review.error("no_script")))
    return shown


@router.get("/{task_id}/script-review")
def read_script_review(task_id: str, format: str = Query("json", pattern="^(json|md)$"), focus: str = _FOCUS):
    try:
        shown = _found(script_review_service.current(drama_api.service, task_id, focus))
    except script_review.ScriptReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if format == "md":
        if not shown["report"]:
            raise HTTPException(status_code=404, detail=str(script_review.error("not_found")))
        return Response(
            content=script_review.render_markdown(shown), media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="script-review.md"'},
        )
    return shown


@router.post("/{task_id}/script-review")
async def build_script_review(task_id: str, focus: str = _FOCUS):
    """Text-model calls: one per block of episodes (``calls_needed`` of the GET says how many)."""
    try:
        return _found(await run_in_threadpool(script_review_service.build, drama_api.service, task_id, focus))
    except script_review.ScriptReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
