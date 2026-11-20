# -*- coding: utf-8 -*-
"""What the new-project form shows for a serial: the genre / tone / ending catalogue and the paywall plan for a length.

Read-only and free: both come from data files and arithmetic; no model is called and nothing is stored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.auth_api import get_current_user
from app.core import paywall_plan, serial_brief

router = APIRouter(prefix="/api/serial-brief", tags=["连载立项"], dependencies=[Depends(get_current_user)])


@router.get("")
def serial_brief_catalog():
    """Genres (stackable), tones, endings and the overseas switch."""
    return {**serial_brief.catalog(), "paywall_min_episodes": paywall_plan.min_episodes()}


@router.get("/paywall")
def paywall_summary(episodes: int = Query(0, ge=0, le=1000), genre: str = Query("", max_length=40)):
    """Where the paywall episodes fall for a serial of ``episodes`` episodes, and the cliff each stops on."""
    lead = (serial_brief.normalize_genres([genre]) or [""])[0]
    return paywall_plan.summary(episodes, lead)
