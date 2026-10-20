"""The music library: beds a person keeps on the server and picks for a film's timeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.auth_api import get_current_user
from app.core import bgm_library

router = APIRouter(prefix="/api/library/bgm", tags=["配乐库"])


def _public(track: dict) -> dict:
    return {key: value for key, value in track.items() if key != "path"}


@router.get("")
def list_bgm(_: dict = Depends(get_current_user)):
    return {"items": [_public(track) for track in bgm_library.list_tracks()]}


@router.post("")
async def upload_bgm(
    file: UploadFile = File(...),
    name: str = Form(""),
    mood: str = Form(""),
    current_user: dict = Depends(get_current_user),
):
    """Add a track; the bytes are checked against the declared type before anything is written."""
    content = await file.read(bgm_library.MAX_BGM_UPLOAD_BYTES + 1)
    try:
        track = bgm_library.add_track(
            name=name, mood=mood, content=content, filename=file.filename or "", content_type=file.content_type or "",
            owner_id=str(current_user.get("user_id") or "") or None,
        )
    except bgm_library.BgmUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _public(track)


@router.get("/{track_id}/audio")
def stream_bgm(track_id: str, _: dict = Depends(get_current_user)):
    track = bgm_library.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="配乐不存在")
    return FileResponse(track["path"], filename=f"{track['name']}{track['path'][track['path'].rfind('.'):]}")


@router.delete("/{track_id}")
def delete_bgm(track_id: str, current_user: dict = Depends(get_current_user)):
    track = bgm_library.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="配乐不存在")
    if track.get("owner_id") and track["owner_id"] != str(current_user.get("user_id")) and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只能删除自己上传的配乐")
    bgm_library.remove_track(track_id)
    return {"id": track_id, "deleted": True}
