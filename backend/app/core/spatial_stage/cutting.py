# -*- coding: utf-8 -*-
"""What a solved lens still owes the cut it sits in.

``coverage.solve_camera`` frames one shot on its own. Two things depend on the shots around
it and on who walks during it: a moving camera goes with a subject who walks onto their mark,
and a shot does not repeat the people, size and direction of the one before it (the 30-degree
rule). Building a stage and re-solving a lens on an existing one take the same two steps from
here, so a re-solve does not undo what the plan had.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import keep_side, lens_bearing, repeats_the_angle
from app.core.spatial_stage.models import StageCamera, StagePlan, StageShot


def carry_camera(camera: StageCamera, shot: StageShot, plan: StagePlan) -> StageCamera:
    """A moving camera on a subject who walks to their mark travels with them and lands on the mark."""
    if camera.move.kind == "static" or not camera.subjects:
        return camera
    change = next((item for item in shot.overrides if item.name == camera.subjects[0] and item.position and not item.hold), None)
    actor = plan.actor(camera.subjects[0])
    if change is None or actor is None:
        return camera
    shift = geo.sub((actor.position[0], actor.position[1]), (change.position[0], change.position[1]))
    end_target = camera.move.end_target or camera.target
    end_position = camera.move.end_position or camera.position
    target = [end_target[0] + shift[0], end_target[1], end_target[2] + shift[1]]
    position = list(end_position) if camera.move.kind == "pan" else [
        end_position[0] + shift[0], end_position[1], end_position[2] + shift[1],
    ]
    if not axis_rules.is_overhead(camera):
        position = list(keep_side(tuple(position), plan.axis))
    return camera.model_copy(update={"move": camera.move.model_copy(update={
        "end_position": geo.rounded(position), "end_target": geo.rounded(target),
    })})


def vary_angle(
    previous: StageCamera | None, camera: StageCamera, solve: Callable[[geo.Vec2 | None], StageCamera],
) -> StageCamera:
    """The 30-degree rule: a shot that would repeat the one before it is taken from somewhere else on the same side.

    ``solve`` solves the shot again, away from the floor direction it is given.
    """
    if previous is None or not repeats_the_angle(previous, camera):
        return camera
    return solve(lens_bearing(previous, (camera.target[0], camera.target[2])))


__all__ = ["carry_camera", "vary_angle"]
