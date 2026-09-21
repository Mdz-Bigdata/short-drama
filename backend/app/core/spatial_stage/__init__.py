# -*- coding: utf-8 -*-
"""The spatial stage: one floor plan per scene that every shot's blocking is measured from.

Behavioral references (see THIRD_PARTY_NOTICES.md):

- jiguang132/storyai-3d-director-desk (MIT) — the director-desk model of a scene as
  characters, set pieces and look-at cameras with a director view and a camera view,
  the pose-preset vocabulary, per-instance scene scoping and project JSON interchange.
- cs68614-hash/costage (no license observed; clean-room) — semantic blocking
  (camera-relative and character-relative placement, facing pairs, line / arc / circle
  / grid formations), FOV-driven framing and the rule that a new action stage must
  really change a character's state.

Neither project computes shot sizes, screen positions, the 180-degree rule, frustum
containment or occlusion; those are this package's own.
"""

from app.core.spatial_stage.coverage import ShotSpec, solve_camera
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.planner import SceneBrief, build_plan, refresh

__all__ = ["SceneBrief", "ShotSpec", "StagePlan", "build_plan", "refresh", "solve_camera"]
