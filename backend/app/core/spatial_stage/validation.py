# -*- coding: utf-8 -*-
"""Numeric checks of a spatial stage.

These are the checks a person does by eye on a 3D director desk — is everyone
the shot is about actually in frame, is anyone hidden behind someone else, did
a cut jump the axis, did two people swap screen sides — done as measurements so
they hold for a plan a person has dragged around as well as for a solved one.
"""

from __future__ import annotations

from collections.abc import Collection

from app.core import prompt_data
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import contacts as contact_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.language import posture_in, travel_in
from app.core.spatial_stage.models import StageCamera, StageCheck, StageLandmark, StagePlan, StageShot
from app.core.spatial_stage.projection import posture_height, screen_states
from app.core.spatial_stage.wording import hand_zh, phrase, posture_zh

MIN_ACTOR_SPACING_M = 0.4
MIN_CAMERA_CLEARANCE_M = 0.3
_WORDING = "stage_checks"
_DETAIL_CHARS = StageCheck.model_fields["detail"].metadata[0].max_length


def pair_relation(key: str) -> str:
    """How two people stand to each other (面对面 / 同向并肩 …): ``app/data/prompt/stage_brief.json`` pair_relations.

    The planner writes a pair's formation with these words and the facing check below reads them back.
    """
    return str(prompt_data.value("stage_brief", "pair_relations")[key])


def _says(code: str, key: str, **values: object) -> str:
    """A sentence of check ``code`` (``app/data/prompt/stage_checks.json``), filled in."""
    return str(prompt_data.load(_WORDING)["checks"][code][key]).format(**values)


def _fit(code: str, findings: str, cut: int) -> str:
    """``findings`` cut to ``cut`` and to the room check ``code``'s fail sentence leaves in a detail.

    The fail sentence is data and may be reworded longer; a crowded scene must not then overflow the detail.
    """
    frame = str(prompt_data.load(_WORDING)["checks"][code]["failed"]).format(findings="")
    return findings[:max(0, min(cut, _DETAIL_CHARS - len(frame)))]


def _ids(values: list[int]) -> list[int]:
    return sorted(dict.fromkeys(values))[:200]


def set_obstructions(
    plan: StagePlan, shot: StageShot, camera: StageCamera, visible: Collection[str] | None = None,
) -> list[tuple[str, StageLandmark]]:
    """What of the set is in this lens's way: ``("", piece)`` for the piece it stands inside, else ``(name, piece)``
    for each subject a piece hides.

    ``visible`` is who the lens has in frame (measured here when not given). Someone out of frame is another
    check's finding, and a crowd is background. A piece built from parts only blocks where a part is.
    """
    pieces = plan.landmarks_in(shot)
    around = next(
        (piece for piece in pieces if piece.shape != "plane" and geo.piece_holds_point(camera.position, piece)),
        None,
    )
    if around is not None:
        return [("", around)]
    staged = plan.actors_in(shot)
    if visible is None:
        visible = {state.name for state in screen_states(staged, camera) if state.visible}
    blocked: list[tuple[str, StageLandmark]] = []
    for actor in staged:
        if actor.name not in camera.subjects or actor.name not in visible or actor.role == "crowd" or actor.crowd_id:
            continue
        chest = (actor.position[0], posture_height(actor) * 0.72, actor.position[1])
        blocker = next((piece for piece in pieces if geo.piece_blocks_sight(camera.position, chest, piece)), None)
        if blocker is not None:
            blocked.append((actor.name, blocker))
    return blocked


def set_blockers(plan: StagePlan, shot: StageShot, camera: StageCamera, visible: Collection[str] | None = None) -> list[str]:
    """``set_obstructions`` in words: 机位在「书案」里面 / 沈砚被布景「柱」挡住."""
    return [
        phrase("set_hides_subject", name=name, piece=piece.name) if name else phrase("set_holds_lens", piece=piece.name)
        for name, piece in set_obstructions(plan, shot, camera, visible)
    ]


def check_plan(plan: StagePlan) -> list[StageCheck]:
    """Every spatial check of ``plan``; expects each shot's ``screen`` / ``axis_side`` / ``crossing`` to be current."""
    checks: list[StageCheck] = []
    cameras = {camera.id: camera for camera in plan.cameras}

    # ---- nobody shares a mark
    crowded: list[str] = []
    solid = [actor for actor in plan.actors if actor.role != "crowd"]
    for index, first in enumerate(solid):
        for second in solid[index + 1:]:
            gap = geo.distance((first.position[0], first.position[1]), (second.position[0], second.position[1]))
            if gap < MIN_ACTOR_SPACING_M:
                crowded.append(_says("spatial_actor_spacing", "pair", first=first.name, second=second.name, gap=gap))
    checks.append(StageCheck(
        code="spatial_actor_spacing",
        passed=not crowded,
        detail=(
            _says("spatial_actor_spacing", "failed", findings=_fit("spatial_actor_spacing", "；".join(crowded), 1900))
            if crowded else _says("spatial_actor_spacing", "passed")
        ),
    ))

    # ---- the people a shot is about are inside its frame, at both ends of a move
    out_of_frame: list[str] = []
    out_ids: list[int] = []
    drift: list[str] = []
    drift_ids: list[int] = []
    hidden: list[str] = []
    hidden_ids: list[int] = []
    # A crowd is background by nature; being partly covered is how it is meant to read.
    crowd_names = {actor.name for actor in plan.actors if actor.role == "crowd"}
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is None:
            continue
        states = {state.name: state for state in shot.screen}
        for name in camera.subjects:
            state = states.get(name)
            if state is None:
                continue
            if not state.visible:
                out_of_frame.append(_says("spatial_subjects_in_frame", "subject", shot=shot.shot_id, name=name))
                out_ids.append(shot.shot_id)
            elif state.occluded_by and camera.function != "over_shoulder" and name not in crowd_names:
                hidden.append(_says("spatial_subject_occlusion", "hidden", shot=shot.shot_id, name=name, blocker=state.occluded_by))
                hidden_ids.append(shot.shot_id)
        if camera.move.kind != "static":
            ending = {state.name: state for state in screen_states(plan.actors_in(shot, at_end=True), camera, end=True)}
            lost = [name for name in camera.subjects if name in ending and not ending[name].visible]
            if camera.move.kind == "pan" and camera.subjects:
                # A pan hands the frame from its subject to whoever it turns to; it only fails when it lands on nobody.
                lost = [] if any(state.visible for name, state in ending.items() if name not in crowd_names) else lost
            if lost:
                drift.append(_says("spatial_move_keeps_subjects", "lost", shot=shot.shot_id, names="、".join(lost)))
                drift_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_subjects_in_frame",
        passed=not out_of_frame,
        detail=(
            _says("spatial_subjects_in_frame", "failed", findings=_fit("spatial_subjects_in_frame", "、".join(out_of_frame), 1800))
            if out_of_frame else _says("spatial_subjects_in_frame", "passed")
        ),
        shot_ids=_ids(out_ids),
    ))
    checks.append(StageCheck(
        code="spatial_move_keeps_subjects",
        passed=not drift,
        severity="warning",
        detail=(
            _says("spatial_move_keeps_subjects", "failed", findings=_fit("spatial_move_keeps_subjects", "；".join(drift), 1900))
            if drift else _says("spatial_move_keeps_subjects", "passed")
        ),
        shot_ids=_ids(drift_ids),
    ))
    checks.append(StageCheck(
        code="spatial_subject_occlusion",
        passed=not hidden,
        severity="warning",
        detail=(
            _says("spatial_subject_occlusion", "failed", findings=_fit("spatial_subject_occlusion", "；".join(hidden), 1900))
            if hidden else _says("spatial_subject_occlusion", "passed")
        ),
        shot_ids=_ids(hidden_ids),
    ))

    # ---- 180-degree rule
    jumps = axis_rules.illegal_crossings(plan.shots) if axis_rules.has_axis(plan.axis) else []
    checks.append(StageCheck(
        code="spatial_axis_consistent",
        passed=not jumps,
        detail=(
            _says("spatial_axis_consistent", "failed", findings=_fit("spatial_axis_consistent", "；".join(
                _says("spatial_axis_consistent", "jump", before=before, after=after) for before, after in jumps
            ), 1800))
            if jumps else _says("spatial_axis_consistent", "passed")
        ),
        shot_ids=_ids([after for _, after in jumps]),
    ))

    # ---- the promised screen sides hold wherever the pair shares a frame
    # On the established side this is true by construction; what it catches is a scene whose marks
    # were swapped under its cameras (it *opens* mirrored: an error) and coverage that carried on
    # from the far side after a legal crossing (mirrored on purpose: worth a warning, not a stop).
    mirrored: list[int] = []
    opens_mirrored = False
    promised = {actor.name: actor.screen_side for actor in plan.actors if actor.screen_side in {"left", "right"}}
    if axis_rules.has_axis(plan.axis) and plan.axis.kind != "motion":
        first, second = plan.axis.from_name, plan.axis.to_name
        seen_pair = False
        for shot in plan.shots:
            states = {state.name: state for state in shot.screen if state.visible}
            if first not in states or second not in states or abs(states[first].x - states[second].x) <= 0.05:
                continue
            left_name = first if states[first].x < states[second].x else second
            right_name = second if left_name == first else first
            if promised.get(left_name) == "right" or promised.get(right_name) == "left":
                mirrored.append(shot.shot_id)
                opens_mirrored = opens_mirrored or not seen_pair
            seen_pair = True
    checks.append(StageCheck(
        code="spatial_screen_sides_stable",
        passed=not mirrored,
        severity="error" if opens_mirrored or not mirrored else "warning",
        detail=(
            _says(
                "spatial_screen_sides_stable", "failed",
                shots="、".join(str(item) for item in _ids(mirrored)), first=plan.axis.from_name, second=plan.axis.to_name,
                reason=_says("spatial_screen_sides_stable", "opens_mirrored" if opens_mirrored else "after_crossing"),
            )
            if mirrored else _says("spatial_screen_sides_stable", "passed")
        ),
        shot_ids=_ids(mirrored),
    ))

    # ---- people playing a scene to each other actually face each other
    averted: list[str] = []
    if plan.axis.kind == "dialogue" and axis_rules.has_axis(plan.axis) and plan.formation.startswith(pair_relation("facing")):
        pair = [plan.actor(plan.axis.from_name), plan.actor(plan.axis.to_name)]
        if all(pair):
            for actor, partner in ((pair[0], pair[1]), (pair[1], pair[0])):
                toward = geo.unit(geo.sub((partner.position[0], partner.position[1]), (actor.position[0], actor.position[1])))
                if geo.dot(geo.forward_of(actor.yaw_deg), toward) < 0.82:
                    averted.append(_says("spatial_facing_partner", "averted", name=actor.name, partner=partner.name))
    checks.append(StageCheck(
        code="spatial_facing_partner",
        passed=not averted,
        severity="warning",
        detail=(
            _says("spatial_facing_partner", "failed", findings="；".join(averted))
            if averted else _says("spatial_facing_partner", "passed")
        ),
    ))

    # ---- the lens is not inside somebody
    inside: list[str] = []
    inside_ids: list[int] = []
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is None:
            continue
        for actor in plan.actors_in(shot):
            gap = geo.distance((camera.position[0], camera.position[2]), (actor.position[0], actor.position[1]))
            if gap < MIN_CAMERA_CLEARANCE_M and camera.position[1] < actor.height_m + 0.2:
                inside.append(_says("spatial_camera_clearance", "inside", shot=shot.shot_id, name=actor.name, gap=gap))
                inside_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_camera_clearance",
        passed=not inside,
        severity="warning",
        detail=(
            _says("spatial_camera_clearance", "failed", findings=_fit("spatial_camera_clearance", "；".join(inside), 1900))
            if inside else _says("spatial_camera_clearance", "passed")
        ),
        shot_ids=_ids(inside_ids),
    ))

    # ---- the set does not stand between the lens and the people the shot is about
    # A warning, not a stop: a deliberately dirty frame (through a lattice, past a pillar) is a choice.
    walled: list[str] = []
    walled_ids: list[int] = []
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is None:
            continue
        blocked = set_blockers(plan, shot, camera, {state.name for state in shot.screen if state.visible})
        if blocked:
            walled.extend(phrase("shot_named", shot=shot.shot_id) + item for item in blocked)
            walled_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_set_clearance",
        passed=not walled,
        severity="warning",
        detail=phrase("set_clearance_failed", findings="；".join(walled)[:1900]) if walled else phrase("set_clearance_passed"),
        shot_ids=_ids(walled_ids),
    ))

    # ---- what the storyboard says someone does is on the stage
    frozen: list[str] = []
    frozen_ids: list[int] = []
    # One mark holds one move: a walk written after someone has already entered or moved stays unstaged.
    walkers = {item.name for shot in plan.shots for item in shot.overrides if item.position is not None and not item.hold}
    for shot in plan.shots:
        changes = {item.name: item for item in shot.overrides}
        for actor in plan.actors_in(shot):
            if actor.role == "crowd":
                continue
            change = changes.get(actor.name)
            moved = change is not None and change.position is not None
            if travel_in(actor.name, shot.action) and actor.name not in walkers:
                frozen.append(_says("spatial_action_changes_state", "walk", shot=shot.shot_id, name=actor.name))
                frozen_ids.append(shot.shot_id)
            implied = posture_in(actor.name, shot.action, None)
            if implied and not moved and implied != actor.posture:
                frozen.append(_says(
                    "spatial_action_changes_state", "posture",
                    shot=shot.shot_id, name=actor.name, wanted=posture_zh(implied), current=posture_zh(actor.posture),
                ))
                frozen_ids.append(shot.shot_id)
    contact_check = _contact_check(plan)
    checks.append(StageCheck(
        code="spatial_action_changes_state",
        passed=not frozen,
        severity="warning",
        detail=(
            _says("spatial_action_changes_state", "failed", findings=_fit("spatial_action_changes_state", "；".join(frozen), 1900))
            if frozen else _says("spatial_action_changes_state", "passed")
        ),
        shot_ids=_ids(frozen_ids),
    ))
    # Only a stage that has contacts is checked for them, so a plan without any reads as it always has.
    if contact_check is not None:
        checks.append(contact_check)
    return checks


def contact_findings(plan: StagePlan) -> list[tuple[str, int | None, str]]:
    """Every contact the stage does not keep, as ``(kind of finding, shot or None, sentence)``.

    A whole-scene contact is held to the stored marks: the held prop at the hand of the actor's mark, the thing
    on its support's top and inside its footprint, the sitter on the seat. A contact limited to some shots is
    the resolver's alone in those shots (the stored marks are where things are in the others), so only what the
    resolver cannot do is reported for it: a seat too high or low to sit on, a holder or sitter not on the set.
    Findings of the first kind are what ``贴合接触`` puts right; the others need a person.
    """
    tolerance, settle = contact_rules.limit("hold_tolerance_m"), contact_rules.limit("settle_tolerance_m")
    pieces = {item.name: item for item in reversed(plan.landmarks)}  # the first piece of a name is the one a contact means
    findings: list[tuple[str, int | None, str]] = []
    for contact in plan.contacts:
        target, support, actor = pieces.get(contact.target), pieces.get(contact.support), plan.actor(contact.actor)
        if target is None or (contact.kind == "rest" and support is None) or (contact.kind != "rest" and actor is None):
            continue
        if contact.kind == "sit" and not contact_rules.is_seat(target):
            findings.append(("manual", None, _says(
                "spatial_contact_kept", "seat", target=target.name, top=contact_rules.seat_top(target),
            )))
        if contact.kind != "rest":
            for shot in plan.shots:
                if not contact.applies_to(shot.shot_id):
                    continue
                if not any(item.name == actor.name for item in plan.actors_in(shot)):
                    findings.append(("manual", shot.shot_id, _says(
                        "spatial_contact_kept", "absent", shot=shot.shot_id, actor=actor.name, target=target.name,
                    )))
        if contact.shot_ids:
            continue
        if contact.kind == "hold":
            sitting = contact_rules.seated_names(contact_rules.in_shot(plan.contacts, None), plan.landmarks)
            hand = contact_rules.hand_point(actor, contact.hand, seated=actor.name in sitting)
            centre = (target.position[0], target.elevation_m + target.size[2] / 2, target.position[1])
            gap = sum((hand[index] - centre[index]) ** 2 for index in range(3)) ** 0.5
            if gap > tolerance:
                findings.append(("settle", None, _says(
                    "spatial_contact_kept", "hold", target=target.name, actor=actor.name, hand=hand_zh(contact.hand), gap=gap,
                )))
        elif contact.kind == "rest":
            placed = contact_rules.rested(target, support)
            if (
                abs(target.elevation_m - placed.elevation_m) > settle
                or geo.distance((target.position[0], target.position[1]), (placed.position[0], placed.position[1])) > settle
            ):
                findings.append(("settle", None, _says(
                    "spatial_contact_kept", "rest", target=target.name, support=support.name,
                )))
        elif contact.kind == "sit":
            off = geo.distance((actor.position[0], actor.position[1]), (target.position[0], target.position[1]))
            if off > settle or actor.posture != "sit":
                findings.append(("settle", None, _says("spatial_contact_kept", "sit", actor=actor.name, target=target.name)))
    return findings


def _contact_check(plan: StagePlan) -> StageCheck | None:
    if not plan.contacts:
        return None
    findings = contact_findings(plan)
    return StageCheck(
        code="spatial_contact_kept",
        passed=not findings,
        severity="warning",
        detail=(
            _says("spatial_contact_kept", "failed", findings=_fit("spatial_contact_kept", "；".join(text for _, _, text in findings), 1900))
            if findings else _says("spatial_contact_kept", "passed")
        ),
        shot_ids=_ids([shot for _, shot, _ in findings if shot is not None]),
    )


def passed(checks: list[StageCheck]) -> bool:
    return not any(not item.passed and item.severity == "error" for item in checks)


__all__ = [
    "MIN_ACTOR_SPACING_M", "MIN_CAMERA_CLEARANCE_M", "check_plan", "contact_findings", "pair_relation", "passed", "set_blockers",
    "set_obstructions",
]
