# -*- coding: utf-8 -*-
"""Say the stage in the storyboard's own words.

Every sentence here is a reading of the plan: screen regions come from the
projection, distances from the floor, the axis statement from the side the
camera stands on. The shot contract (composition / action_axis / eyeline /
blocking), the director's frame positions, scene landmarks and continuity locks
are all fed from these strings, so the prompt can never claim a blocking the
plan does not hold.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection
from typing import Any

from app.core import prompt_data
from app.core.frame_position import FramePosition, render_frame_positions
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import crowd_lens_names
from app.core.spatial_stage.models import (
    ShotText,
    StageActor,
    StageCamera,
    StageLandmark,
    StagePlan,
    StageShot,
)
from app.core.spatial_stage.projection import CameraView, posture_height
from app.core.spatial_stage.wording import hand_zh, move_zh, phrase, posture_zh

_BRIEF = "stage_brief"
_PROPS = "stage_props"
# Every sentence and word table here: app/data/prompt/stage_panel.json; the marks that join clauses and
# the frame sides shared with the clip brief: stage_brief.json.
_PANEL = "stage_panel"


def _entry(*path: str) -> Any:
    """The entry of the panel's wording table at ``path``: a sentence or a word table."""
    found: Any = prompt_data.load(_PANEL)
    for key in path:
        found = found[key]
    return found


def _say(*path: str, **values: object) -> str:
    """A sentence of the panel's wording table, filled in."""
    return str(_entry(*path)).format(**values)


def _brief(*path: str) -> str:
    """A mark or a frame side of the stage brief's table."""
    found: Any = prompt_data.load(_BRIEF)
    for key in path:
        found = found[key]
    return str(found)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(_brief("marks", "trim")) + _brief("marks", "ellipsis")


# How many pieces of a reference-image blockout a prompt may name. A hundred wall sections would
# push the axis and the cast out of every clipped text, and the picture already shows the set.
_BLOCKOUT_PIECES_IN_PROMPT = 6


def prompt_landmarks(plan: StagePlan) -> list[StageLandmark]:
    """The set pieces prose talks about: all placed by hand, and of a blockout only its biggest."""
    placed = [item for item in plan.landmarks if item.origin != "blockout"]
    built = [item for item in plan.landmarks if item.origin == "blockout" and item.size[2] >= 0.3]
    built.sort(key=lambda item: item.size[0] * item.size[1] * item.size[2], reverse=True)
    return [*placed, *built[:_BLOCKOUT_PIECES_IN_PROMPT]]


def bearing_from(actor: StageActor, point: geo.Vec2) -> tuple[str, float]:
    """``(bearing, meters)`` of ``point`` as the actor would say it: 前方 / 左前方 / 右侧 / 后方 …"""
    origin = (actor.position[0], actor.position[1])
    delta = geo.sub(point, origin)
    meters = geo.length(delta)
    if meters < 0.05:
        return _say("bearing", "beside"), 0.0
    forward = geo.forward_of(actor.yaw_deg)
    ahead = geo.dot(geo.unit(delta), forward)
    to_right = geo.dot(geo.unit(delta), geo.right_of(forward))
    angle = math.degrees(math.atan2(to_right, ahead))
    side = str(_entry("bearing_sides")["right" if angle > 0 else "left"])
    magnitude = abs(angle)
    if magnitude <= 22.5:
        label = _say("bearing", "ahead")
    elif magnitude <= 67.5:
        label = _say("bearing", "side_ahead", side=side)
    elif magnitude <= 112.5:
        label = _say("bearing", "side", side=side)
    elif magnitude <= 157.5:
        label = _say("bearing", "side_behind", side=side)
    else:
        label = _say("bearing", "behind")
    return label, meters


def _anchor_actor(plan: StagePlan) -> StageActor | None:
    return plan.actor(plan.axis.from_name) or next((a for a in plan.actors if a.role != "crowd"), None) or (
        plan.actors[0] if plan.actors else None
    )


def master_camera(plan: StagePlan) -> StageCamera | None:
    """The camera whose frame defines "screen left" for the scene: the first establishing view."""
    return next(
        (camera for camera in plan.cameras if camera.function == "establish"),
        next((camera for camera in plan.cameras if len(camera.subjects) >= 2), plan.cameras[0] if plan.cameras else None),
    )


def _master_side(plan: StagePlan, landmark: StageLandmark) -> str:
    """左侧 / 右侧 / 中央 as the master frame shows ``landmark``; empty when it is behind that lens."""
    master = master_camera(plan)
    if master is None:
        return ""
    x, _, depth = CameraView.of(master).project(
        (landmark.position[0], landmark.elevation_m + landmark.size[2] / 2, landmark.position[1]),
    )
    if depth <= 0.2:
        return ""
    return str(_entry("screen_sides")["left" if x < -0.12 else "right" if x > 0.12 else "centre"])


def landmark_relative_position(plan: StagePlan, landmark: StageLandmark) -> str:
    """Bearing and distance from the scene's anchor character, plus where the master frame shows it."""
    anchor = _anchor_actor(plan)
    point = (landmark.position[0], landmark.position[1])
    if anchor is None:
        centre = geo.centroid([(item.position[0], item.position[1]) for item in plan.landmarks])
        return _clip(_say("landmark", "from_centre", meters=geo.distance(point, centre)), 500)
    bearing, meters = bearing_from(anchor, point)
    text = _say("landmark", "from_anchor", anchor=anchor.name, bearing=bearing, meters=meters)
    if side := _master_side(plan, landmark):
        text += _say("landmark", "master_side", side=side)
    return _clip(text, 500)


def layout_facts(plan: StagePlan, limit: int = 4) -> str:
    """The set as one line of screen sides: 门在画面右侧、窗在画面左侧. Fixtures first, small props last."""
    pieces = sorted(prompt_landmarks(plan), key=lambda item: (item.kind not in {"architecture", "furniture"}, -item.size[2]))
    facts = [_say("landmark", "layout_fact", name=item.name, side=side) for item in pieces if (side := _master_side(plan, item))]
    return _clip(_brief("marks", "list").join(facts[:limit]), 200)


def is_stand_in(landmark: StageLandmark) -> bool:
    """A prop the planner knew no size for stands on the stage as the stand-in box, and that box is not its size."""
    stand_in = [float(value) for value in prompt_data.value(_PROPS, "stand_in_m")]
    return landmark.kind == "prop" and [float(value) for value in landmark.size] == stand_in


def landmark_size(landmark: StageLandmark) -> str:
    """The set piece's real size, so the frame holds one scale: 宽约1.4米、高约2.4米."""
    width, depth, height = landmark.size
    parts = [_say("size", "width", span=_span(width))]
    if depth >= 0.5:
        parts.append(_say("size", "depth", span=_span(depth)))
    parts.append(_say("size", "height", span=_span(height)))
    return _brief("marks", "list").join(parts)


def _span(metres: float) -> str:
    """1.4米, and centimetres for something held in the hand: a pen is not 0.1米 wide and 0.0米 high."""
    return _say("size", "metres", metres=metres) if metres >= 0.3 else _say("size", "centimetres", centimetres=round(metres * 100))


def _body_marks() -> tuple[tuple[float, str], ...]:
    """A standing body in fractions of its height: where the top of a set piece meets it (``{name}`` is the person)."""
    return tuple((float(share), str(text)) for share, text in _entry("scale", "body_marks"))


def _heads_words() -> dict[float, str]:
    """How many heads taller a piece is, in words: 0.5 → 半个头."""
    return {float(heads): str(words) for heads, words in _entry("scale", "heads_words")}


def _scale_piece(plan: StagePlan) -> StageLandmark | None:
    """The set piece a person is measured against: the tallest fixture, a door before a table."""
    pieces = [item for item in prompt_landmarks(plan) if item.kind != "light" and item.size[2] >= 0.3 and not is_stand_in(item)]
    return max(pieces, key=lambda item: (item.kind == "architecture", item.size[2]), default=None)


def scale_reference(plan: StagePlan, actor: StageActor | None = None, landmark: StageLandmark | None = None) -> str:
    """One fixed person-to-set ratio: 林晚身高约168cm；门高约2.4米，林晚站在门旁，头顶比门顶低约0.7米（约三个头）.

    Every shot of the scene says the same ratio, so a door never shrinks to a cupboard between cuts.
    """
    actor = actor or _anchor_actor(plan)
    if actor is None or actor.crowd_id:
        return ""
    head = _say("scale", "height", name=actor.name, centimetres=round(actor.height_m * 100))
    landmark = landmark or _scale_piece(plan)
    if landmark is None:
        return head
    height = landmark.size[2]
    ratio = height / actor.height_m
    if ratio >= 1.08:
        gap = height - actor.height_m
        # 一个头约为身高的 1/7.5。
        heads = _heads_words().get(round(gap / (actor.height_m / 7.5) * 2) / 2)
        # 「站在门旁」 is only said of someone who is: across the room it is the two heights that compare.
        beside = geo.inside_piece(actor.position, landmark, float(prompt_data.value(_BRIEF, "near_piece_m")))
        relation = phrase(
            "scale_beside" if beside else "scale_apart", actor=actor.name, piece=landmark.name, gap=f"{gap:.1f}",
        ) + (_say("scale", "heads", heads=heads) if heads else "")
    else:
        relation = next(
            (
                _say("scale", "body_mark", piece=landmark.name, mark=text.format(name=actor.name))
                for share, text in _body_marks() if ratio >= share
            ),
            _say("scale", "below_knee", piece=landmark.name, name=actor.name),
        )
    return _say("scale", "line", person=head, piece=landmark.name, height=height, relation=relation)


def array_members(plan: StagePlan) -> frozenset[str]:
    """Names of the people who stand in a crowd array: background texture, described as one group."""
    return frozenset(actor.name for actor in plan.actors if actor.crowd_id)


def frame_positions(
    shot: StageShot, camera: StageCamera, grouped: Collection[str] = (),
) -> list[FramePosition]:
    """The visible characters of the shot in screen coordinates: subjects left to right, then bystanders by depth.

    A shot of nobody (an empty frame, a prop insert) lists no one even if a mark happens to fall inside it.
    ``grouped`` (the members of crowd arrays) are never listed one by one unless the shot is about them.
    """
    if not camera.subjects:
        return []
    order = {name: index for index, name in enumerate(camera.subjects)}
    visible = sorted(
        (state for state in shot.screen if state.visible and (state.name in order or state.name not in grouped)),
        key=lambda state: (0, state.x) if state.name in order else (1, state.depth_m),
    )
    positions: list[FramePosition] = []
    for state in visible:
        occlusion, keep = "", ""
        if camera.function == "over_shoulder" and state.name not in order:
            edge = str(_entry("screen_sides")["left" if state.x < 0 else "right"])
            occlusion = _say("frame", "shoulder", edge=edge)
            keep = _say("frame", "keep_face", name=camera.subjects[0]) if camera.subjects else ""
        elif state.occluded_by and camera.function != "over_shoulder":
            occlusion = _say("frame", "occluded", blocker=state.occluded_by)
        positions.append(FramePosition(
            subject=state.name[:120], region=state.region, depth=state.depth_layer,
            facing=state.facing, occlusion=occlusion, keep_visible=keep,
        ))
    return positions[:30]


def _axis_angle(plan: StagePlan, camera: StageCamera) -> float:
    """Degrees between the lens and the axis: 90 is the square-on master, small is down the line."""
    direction = geo.unit(axis_rules.axis_vector(plan.axis), (1.0, 0.0))
    cosine = abs(geo.dot(CameraView.of(camera).ground_forward(), direction))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _axis_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    axis = plan.axis
    if not axis_rules.has_axis(axis):
        return _say("axis", "none")
    left, right = (axis.from_name, axis.to_name) if axis.camera_side >= 0 else (axis.to_name, axis.from_name)
    if axis.kind == "gaze":
        head = _say("axis", "gaze", source=axis.from_name, target=axis.to_name, left=left, right=right)
    elif axis.kind == "motion":
        head = _say("axis", "motion", source=axis.from_name, target=axis.to_name)
    else:
        head = _say("axis", "relation", source=axis.from_name, target=axis.to_name, left=left, right=right)
    crossings = _entry("axis", "crossings")
    if shot.crossing in crossings:
        tail = str(crossings[shot.crossing])
    else:
        tail = _say("axis", "held", angle=_axis_angle(plan, camera))
    return _clip(_brief("marks", "clause").join((head, tail)), 500)


def _eyeline_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    states = {state.name: state for state in shot.screen}
    actors = {actor.name: actor for actor in plan.actors_in(shot)}
    view = CameraView.of(camera)
    clauses: list[str] = []
    for name in camera.subjects:
        state = states.get(name)
        if state is None or not state.visible:
            continue
        clause = _say("eyeline", "gaze", name=name, facing=state.facing)
        partner_name = (
            plan.axis.to_name if name == plan.axis.from_name
            else plan.axis.from_name if name == plan.axis.to_name else ""
        )
        partner = states.get(partner_name)
        # Someone whose back is to the partner is not looking at them: the facing already said is the whole eyeline.
        away = name in actors and partner_name in actors and _turned_from(actors[name], actors[partner_name])
        if away:
            pass
        elif partner is not None and partner_name in actors:
            if partner.visible:
                clause += _say("eyeline", "partner_in_frame", partner=partner_name)
            else:
                side = view.offscreen_side((actors[partner_name].position[0], actors[partner_name].position[1]))
                clause += _say("eyeline", "partner_off_right" if side == "right" else "partner_off_left", partner=partner_name)
        elif partner_name and plan.axis.kind == "gaze":
            clause += _say("eyeline", "partner", partner=partner_name)
        clauses.append(clause)
    if not clauses:
        return _say("eyeline", "none")
    lead = actors.get(camera.subjects[0]) if camera.subjects else None
    if lead is not None:
        delta = camera.position[1] - posture_height(lead) * 0.93
        clauses.append(_say("eyeline", "level" if abs(delta) < 0.18 else "above" if delta > 0 else "below"))
    return _clip(_brief("marks", "clause").join(clauses), 500)


# How squarely one person has to be turned for it to count: within 60 degrees of the line between the two.
_TOWARD = 0.5


def _toward(actor: StageActor, other: StageActor) -> float | None:
    """1 when ``actor`` faces ``other`` squarely, -1 with the back turned; ``None`` when they share a mark."""
    delta = geo.sub((other.position[0], other.position[1]), (actor.position[0], actor.position[1]))
    if geo.length(delta) < 0.05:
        return None
    return geo.dot(geo.forward_of(actor.yaw_deg), geo.unit(delta))


def _turned_from(actor: StageActor, other: StageActor) -> bool:
    toward = _toward(actor, other)
    return toward is not None and toward < -_TOWARD


def _pair_relation(first: StageActor, second: StageActor) -> str:
    """How two people stand to each other, read from where they are and which way each is turned.

    面对面 needs both to face the other, 背对背 both to face away, 同向并肩 the same heading with the other
    at the shoulder. Anything else that is clear is said by name (who faces whom); the rest is left unsaid
    rather than guessed, since each person's screen facing is stated on its own.
    """
    ahead, back = _toward(first, second), _toward(second, first)
    if ahead is None or back is None:
        return ""
    words = prompt_data.value(_BRIEF, "pair_relations")
    if ahead > _TOWARD and back > _TOWARD:
        return str(words["facing"])
    if ahead < -_TOWARD and back < -_TOWARD:
        return str(words["back_to_back"])
    if ahead > _TOWARD or back > _TOWARD:
        facer, other, turn = (first, second, back) if ahead > _TOWARD else (second, first, ahead)
        return str(words["turned_away" if turn < -_TOWARD else "one_faces"]).format(facer=facer.name, other=other.name)
    same_heading = geo.dot(geo.forward_of(first.yaw_deg), geo.forward_of(second.yaw_deg)) > _TOWARD
    return str(words["side_by_side"]) if same_heading and abs(ahead) < _TOWARD and abs(back) < _TOWARD else ""


def _in_view(view: CameraView, piece: StageLandmark) -> bool:
    """Whether the middle of a set piece falls inside the frame."""
    x, y, depth = view.project((piece.position[0], piece.elevation_m + piece.size[2] / 2, piece.position[1]))
    return depth > 0.2 and abs(x) <= 1.0 and abs(y) <= 1.0


def contact_clauses(plan: StagePlan, shot: StageShot, camera: StageCamera) -> list[str]:
    """One clause per contact the frame shows: 林夏右手握着录音笔、周教授坐在扶手椅上、录音笔放在书案上.

    A hold or a sit is shown when its person is in frame (``shot.screen``); a thing at rest when it is.
    """
    current = [contact for contact in plan.contacts if contact.applies_to(shot.shot_id)]
    if not current:
        return []
    seen = {state.name for state in shot.screen if state.visible}
    view = CameraView.of(camera)
    pieces: dict[str, StageLandmark] = {}
    for item in plan.landmarks_in(shot):
        pieces.setdefault(item.name, item)
    clauses: list[str] = []
    for contact in current:
        if contact.kind == "hold" and contact.actor in seen:
            clauses.append(_say("contacts", "hold", actor=contact.actor, hand=hand_zh(contact.hand), target=contact.target))
        elif contact.kind == "sit" and contact.actor in seen:
            clauses.append(_say("contacts", "sit", actor=contact.actor, target=contact.target))
        elif contact.kind == "rest" and contact.target in pieces and _in_view(view, pieces[contact.target]):
            clauses.append(_say("contacts", "rest", target=contact.target, support=contact.support))
    return clauses


def _blocking_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    actors = plan.actors_in(shot)
    by_name = {actor.name: actor for actor in actors}
    parts: list[str] = []
    first, second = by_name.get(plan.axis.from_name), by_name.get(plan.axis.to_name)
    if first is not None and second is not None:
        gap = geo.distance((first.position[0], first.position[1]), (second.position[0], second.position[1]))
        parts.append(_say(
            "blocking", "pair", first=first.name, first_posture=posture_zh(first.posture),
            second=second.name, second_posture=posture_zh(second.posture), gap=gap, relation=_pair_relation(first, second),
        ))
    anchor = first or (actors[0] if actors else None)
    for actor in actors:
        if anchor is None or actor.name in {plan.axis.from_name, plan.axis.to_name} or actor is anchor or actor.crowd_id:
            continue
        bearing, meters = bearing_from(anchor, (actor.position[0], actor.position[1]))
        parts.append(_say(
            "blocking", "other", name=actor.name, posture=posture_zh(actor.posture), anchor=anchor.name, bearing=bearing, meters=meters,
        ))
    for crowd in plan.crowds:
        if anchor is not None:
            bearing, meters = bearing_from(anchor, (crowd.center[0], crowd.center[1]))
            parts.append(_say(
                "blocking", "crowd", label=crowd.label, count=crowd.rows * crowd.columns, anchor=anchor.name, bearing=bearing, meters=meters,
            ))
    if anchor is not None and first is None:
        parts.insert(0, _say("blocking", "centre", name=anchor.name, posture=posture_zh(anchor.posture)))
    for change in shot.overrides:
        if change.reason:
            parts.append(_say("blocking", "override", name=change.name, reason=change.reason))
    parts.extend(contact_clauses(plan, shot, camera))
    lead = by_name.get(camera.subjects[0]) if camera.subjects else anchor
    if lead is not None:
        reach = geo.distance((camera.position[0], camera.position[2]), (lead.position[0], lead.position[1]))
        parts.append(_say("blocking", "lens_clause", name=lead.name, reach=reach, height=camera.position[1]))
    for landmark in prompt_landmarks(plan)[:3]:
        parts.append(_say("blocking", "landmark", name=landmark.name, position=landmark_relative_position(plan, landmark)))
    if lead is not None and plan.landmarks and not lead.crowd_id:
        parts.append(_say("blocking", "scale", scale=scale_reference(plan, lead)))
    return _clip(_brief("marks", "clause").join(parts) or _say("blocking", "empty"), 800)


def without_camera_pose(text: str) -> str:
    """``text`` minus the measured lens-pose clause.

    A blockout clip owns the camera track (blockout rule 3): a sentence that also states where the
    lens stands is a second, competing camera instruction, so it is withheld while a clip is applied.
    The clause is found by ``blocking.lens_clause_pattern``, kept in the table next to the sentence it finds.
    """
    clause = re.compile(str(_entry("blocking", "lens_clause_pattern")))
    return clause.sub("", str(text or "")).lstrip(_brief("marks", "clause"))


def _camera_pose_text(plan: StagePlan, shot: StageShot, camera: StageCamera, *, end: bool) -> str:
    position = camera.move.end_position if end and camera.move.end_position else camera.position
    by_name = {actor.name: actor for actor in plan.actors_in(shot)}
    lead = by_name.get(camera.subjects[0]) if camera.subjects else _anchor_actor(plan)
    where = _say("camera", "height", height=position[1])
    if lead is not None:
        bearing, meters = bearing_from(lead, (position[0], position[2]))
        where = _say("camera", "from_lead", name=lead.name, bearing=bearing, meters=meters, height=where)
    return _clip(_say("camera", "pose", where=where, lens=camera.equivalent_lens_mm, angle=camera.angle), 500)


def shot_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> ShotText:
    positions = frame_positions(shot, camera, array_members(plan))
    placed = render_frame_positions(positions)
    clause = _brief("marks", "clause")
    composition = _say("composition", "frame", size=camera.shot_size, lens=camera.equivalent_lens_mm)
    if placed:
        composition += clause + placed
    else:
        view = CameraView.of(camera)
        seen = []
        # Where each piece is in this shot (a held prop is in the hand), matched by position in the list: names may repeat.
        placed_now = {id(item): now for item, now in zip(plan.landmarks, plan.landmarks_in(shot))}
        for landmark in prompt_landmarks(plan):
            landmark = placed_now.get(id(landmark), landmark)
            x, y, depth = view.project((landmark.position[0], landmark.elevation_m + landmark.size[2] / 2, landmark.position[1]))
            if depth > 0.2 and abs(x) <= 1.0 and abs(y) <= 1.2:
                side = _brief("frame_sides", "left" if x < -0.12 else "right" if x > 0.12 else "centre")
                seen.append(_say("composition", "landmark", name=landmark.name, side=side))
        composition += clause + _say("composition", "empty") + clause + (
            _brief("marks", "comma").join(seen[:4]) if seen else _say("composition", "by_bible")
        )
    move = move_zh(camera.move.kind)
    return ShotText(
        camera_angle=_clip(camera.angle or _say("camera", "default_angle"), 120),
        composition=_clip(composition, 1000),
        action_axis=_axis_text(plan, shot, camera),
        eyeline=_eyeline_text(plan, shot, camera),
        blocking=_blocking_text(plan, shot, camera),
        camera_start=_camera_pose_text(plan, shot, camera, end=False),
        camera_end=(
            _say("camera", "moves_to", move=move, pose=_camera_pose_text(plan, shot, camera, end=True))
            if camera.move.kind != "static" else _say("camera", "holds", move=move)
        )[:500],
    )


def scene_bible(plan: StagePlan) -> str:
    """The scene's spatial bible: one paragraph every shot of the scene inherits."""
    lines = [_say("bible", "head", place=plan.location or plan.scene_id)]
    if plan.formation:
        lines.append(_say("bible", "formation", formation=plan.formation))
    sides = _entry("bible", "sides")
    for actor in plan.actors:
        if actor.crowd_id:
            continue
        side = str(sides.get(actor.screen_side, ""))
        lines.append(_say(
            "bible", "actor", name=actor.name, posture=posture_zh(actor.posture), centimetres=round(actor.height_m * 100),
            x=actor.position[0], z=actor.position[1], side=_say("bible", "actor_side", side=side) if side else "",
        ))
    for crowd in plan.crowds:
        lines.append(_say(
            "bible", "crowd", label=crowd.label, rows=crowd.rows, columns=crowd.columns, count=crowd.rows * crowd.columns,
            x=crowd.center[0], z=crowd.center[1], spacing=crowd.spacing,
        ))
    for landmark in prompt_landmarks(plan):
        size = "" if is_stand_in(landmark) else _say("bible", "landmark_size", size=landmark_size(landmark))
        lines.append(_say("bible", "landmark", name=landmark.name, size=size, position=landmark_relative_position(plan, landmark)))
    if (scale := scale_reference(plan)) and plan.landmarks:
        lines.append(_say("bible", "scale", scale=scale))
    if axis_rules.has_axis(plan.axis):
        lines.append(_say("bible", "axis", source=plan.axis.from_name, target=plan.axis.to_name))
    return _clip("".join(lines), 4000)


def _supporting_places(plan: StagePlan, leads: list[StageActor]) -> list[str]:
    """Where the supporting cast stands from the leads as the master lens sees it: behind, in front, or at their side."""
    named = {actor.name for actor in leads}
    others = [actor for actor in plan.actors if actor.role != "principal" and not actor.crowd_id and actor.name not in named]
    if not leads or not others:
        return []
    centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in leads])
    master = master_camera(plan)
    if master is not None and geo.distance((master.position[0], master.position[2]), centre) > 0.05:
        downstage = geo.unit(geo.sub((master.position[0], master.position[2]), centre))
    elif axis_rules.has_axis(plan.axis):
        downstage = axis_rules.camera_side_normal(plan.axis)
    else:
        downstage = geo.forward_of(leads[0].yaw_deg)
    groups: dict[str, list[str]] = {"behind": [], "front": [], "beside": []}
    for actor in others:
        offset = geo.dot(geo.sub((actor.position[0], actor.position[1]), centre), downstage)
        groups["behind" if offset < -0.3 else "front" if offset > 0.3 else "beside"].append(actor.name)
    words = prompt_data.value(_BRIEF, "table_supporting")
    whom = prompt_data.text(_BRIEF, "table_pair") if len(leads) == 2 else leads[0].name
    return [str(words[key]).format(names=_brief("marks", "list").join(names), leads=whom) for key, names in groups.items() if names]


def table_brief(plan: StagePlan) -> str:
    """What the storyboard table writer must not contradict: sides, distances, set pieces. Kept short."""
    parts: list[str] = []
    if axis_rules.has_axis(plan.axis) and plan.axis.kind == "dialogue":
        left, right = (
            (plan.axis.from_name, plan.axis.to_name) if plan.axis.camera_side >= 0
            else (plan.axis.to_name, plan.axis.from_name)
        )
        gap = geo.distance((plan.axis.start[0], plan.axis.start[1]), (plan.axis.end[0], plan.axis.end[1]))
        formation = plan.formation.split(_brief("marks", "clause"))[0]
        parts.append(_say("table", "pair", left=left, right=right, gap=gap, formation=formation))
        leads = [actor for name in (plan.axis.from_name, plan.axis.to_name) if (actor := plan.actor(name)) is not None]
    elif plan.actors:
        lead = plan.actors[0]
        sides = _entry("table", "sides")
        side = sides["left" if lead.screen_side == "left" else "right" if lead.screen_side == "right" else "center"]
        parts.append(_say("table", "lead", name=lead.name, side=side))
        leads = [lead]
    else:
        leads = []
    parts.extend(_supporting_places(plan, leads))
    for landmark in prompt_landmarks(plan)[:4]:
        parts.append(_say("table", "landmark", name=landmark.name, position=landmark_relative_position(plan, landmark)))
    if plan.crowds and parts:
        # The lenses only a crowd array can place: named so the table may ask for them in the words the solver reads.
        joiner = _brief("marks", "list")
        parts.append(_say(
            "table", "crowd_lenses", labels=joiner.join(crowd.label for crowd in plan.crowds[:4]), lenses=joiner.join(crowd_lens_names()),
        ))
    if not parts:
        return ""
    return _clip(_say("table", "brief", parts=_brief("marks", "clause").join(parts)), 600)


__all__ = [
    "array_members",
    "bearing_from",
    "contact_clauses",
    "frame_positions",
    "is_stand_in",
    "landmark_relative_position",
    "landmark_size",
    "layout_facts",
    "master_camera",
    "scale_reference",
    "scene_bible",
    "shot_text",
    "table_brief",
    "without_camera_pose",
]
