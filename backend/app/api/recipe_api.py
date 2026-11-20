# -*- coding: utf-8 -*-
"""The recipe catalog: list what exists, and fill one in. Rendering is text only; nothing here calls a model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth_api import get_current_user
from app.core import recipe_catalog
from app.core import prompt_data


_WORDING_FILE = "api_recipe_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_recipe_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

router = APIRouter(prefix="/api/recipes", tags=list(_words_of("module.tags")), dependencies=[Depends(get_current_user)])


class RecipeRenderRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=24)


@router.get("")
def list_recipes(
    category: str = Query("", max_length=40),
    output_type: str = Query("", max_length=20),
    q: str = Query("", max_length=80),
):
    return recipe_catalog.catalog().describe(category=category, output_type=output_type, query=q)


@router.get("/{recipe_id}")
def get_recipe(recipe_id: str):
    try:
        return recipe_catalog.describe_recipe(recipe_catalog.catalog().get(recipe_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{recipe_id}/render")
def render_recipe(recipe_id: str, req: RecipeRenderRequest | None = None):
    try:
        return recipe_catalog.render(recipe_id, req.inputs if req else {})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except recipe_catalog.RecipeInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
