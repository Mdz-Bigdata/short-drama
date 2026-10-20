# -*- coding: utf-8 -*-
"""Structured two-stage screenwriting for the Writer Agent.

Behavioral reference: ArcReel (https://github.com/ArcReel/ArcReel) — the episode
ledger with hooks and outlines, the script-plan / visual-layer split, verbatim
utterances with source anchors, model-bound shot durations, speech-rate duration
bounds and violation-driven repair loops are reimplemented here as original code
(see THIRD_PARTY_NOTICES.md).
"""

from app.core.screenwriting.engine import (
    ENGINE_NAME,
    PlanRejected,
    ScreenwritingEngine,
    ScreenwritingError,
    detect_source_kind,
)
from app.core.screenwriting.renderer import render_breakdown, render_screenplay

__all__ = [
    "ENGINE_NAME",
    "PlanRejected",
    "ScreenwritingEngine",
    "ScreenwritingError",
    "detect_source_kind",
    "render_breakdown",
    "render_screenplay",
]
