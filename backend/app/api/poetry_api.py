"""The poetry shelf for people: browse, search and read in full what the Writer may quote."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth_api import get_current_user
from app.core import poetry_library

router = APIRouter(prefix="/api/poetry", tags=["诗词库"])


@router.get("")
def search_poetry(
    q: str = Query("", max_length=100),
    author: str = Query("", max_length=40),
    theme: str = Query("", max_length=40),
    emotion: str = Query("", max_length=40),
    form: Literal["", "诗", "词", "曲", "文", "经"] = "",
    limit: int = Query(30, ge=1, le=200),
    _: dict = Depends(get_current_user),
):
    found = poetry_library.search(q, author=author, theme=theme, emotion=emotion, form=form, limit=limit)
    return {"items": [poetry_library.summary(poem) for poem in found], "count": len(found)}


@router.get("/authors")
def poetry_authors(_: dict = Depends(get_current_user)):
    return {"items": poetry_library.authors(), "themes": poetry_library.themes()[:60]}


@router.get("/{collection}/{entry_id}")
def poetry_entry(collection: str, entry_id: str, _: dict = Depends(get_current_user)):
    try:
        return poetry_library.detail(poetry_library.library().get(f"{collection}/{entry_id}"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
