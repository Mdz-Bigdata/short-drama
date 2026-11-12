# -*- coding: utf-8 -*-
"""Physical contact on the stage: a prop in a hand, someone on a seat, a thing lying on a table.

A lock only keeps an object from being dragged; contact between a body and an object is its own
constraint. One resolver, used wherever a shot's positions are read (projection, checks, prompts,
clip briefs, camera solving), and mirrored by the director desk:

* ``hold`` — the prop is at the actor's hand: right hand ``hand_side_m`` to the actor's right and
  ``hand_forward_m`` ahead, the left hand mirrored, both hands ``both_forward_m`` ahead on the centre
  line. Hand height is standing height times the posture's ``hand_height`` factor; the prop's underside
  is half its own height below that, and it turns with the actor.
* ``sit`` — the actor stands on the seat's centre with posture ``sit``; facing is kept.
* ``rest`` — the target's underside is the support's top, its ground point clamped into the support's
  footprint (yaw aware) with ``rest_margin_m`` to spare.

The numbers are data (``app/data/prompt/stage_props.json``, section ``contacts``). Every function here is
pure: it returns new models and never touches the plan it reads.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StageActor, StageContact, StageLandmark

_PROPS = "stage_props"


def _geometry(key: str) -> Any:
    return prompt_data.value(_PROPS, "contacts")[key]


def limit(key: str) -> float:
    """One of the contact table's numbers (``hold_tolerance_m``, ``settle_tolerance_m`` …)."""
    return float(_geometry(key))


def _posture_of(actor: StageActor) -> str:
    # The pose preset's posture first, as the projection reads it (a lazy import: projection imports models).
    from app.core.spatial_stage.projection import pose_posture

    return (pose_posture(actor.pose.preset) if actor.pose is not None else "") or actor.posture


def hand_height(actor: StageActor, *, seated: bool = False) -> float:
    """Height of the hand above the floor: standing height times the posture's factor.

    ``seated``: the actor is on a seat by a sit contact this shot, and sits whatever posture a pose preset implies
    (a pose shaped joint by joint is the desk's to draw; only the preset's posture gives way).
    """
    factors = _geometry("hand_height")
    posture = "sit" if seated else _posture_of(actor)
    return actor.height_m * float(factors.get(posture, factors["stand"]))


def hand_point(actor: StageActor, hand: str = "", *, seated: bool = False) -> geo.Vec3:
    """``(x, height, z)`` of the hand that holds: ``hand`` is ``left`` / ``right`` / ``both`` (``""`` is right).

    ``seated`` as in :func:`hand_height`.
    """
    forward = geo.forward_of(actor.yaw_deg)
    right = geo.right_of(forward)
    if hand == "both":
        offset = geo.scale(forward, float(_geometry("both_forward_m")))
    else:
        side = float(_geometry("hand_side_m")) * (-1.0 if hand == "left" else 1.0)
        offset = geo.add(geo.scale(right, side), geo.scale(forward, float(_geometry("hand_forward_m"))))
    ground = geo.add((actor.position[0], actor.position[1]), offset)
    return (ground[0], hand_height(actor, seated=seated), ground[1])


def held(prop: StageLandmark, actor: StageActor, hand: str = "", *, seated: bool = False) -> StageLandmark:
    """``prop`` in ``actor``'s hand: centred on the hand point, turned the way the actor faces."""
    x, height, z = hand_point(actor, hand, seated=seated)
    return prop.model_copy(update={
        "position": geo.rounded((x, z)),
        "elevation_m": round(max(0.0, height - prop.size[2] / 2), 3),
        "yaw_deg": geo.normalize_yaw(actor.yaw_deg),
    })


def seat_top(seat: StageLandmark) -> float:
    return seat.elevation_m + seat.size[2]


def seat_range() -> tuple[float, float]:
    """The lowest and highest seat top (metres) someone can sit on."""
    low, high = (float(value) for value in _geometry("seat_top_m"))
    return low, high


def is_seat(piece: StageLandmark) -> bool:
    """A piece whose top is at a height someone can sit on."""
    low, high = seat_range()
    return low - 1e-6 <= seat_top(piece) <= high + 1e-6


def seated(actor: StageActor, seat: StageLandmark) -> StageActor:
    """``actor`` on the seat's centre, sitting, facing as before."""
    return actor.model_copy(update={"position": geo.rounded(seat.position), "posture": "sit"})


def clamped_into(point: Sequence[float], support: StageLandmark) -> geo.Vec2:
    """``point`` (x, z) moved into the support's footprint, ``rest_margin_m`` inside its edges."""
    margin = float(_geometry("rest_margin_m"))
    local = geo.local_point(point, support)
    half_x, half_z = max(0.0, support.size[0] / 2 - margin), max(0.0, support.size[1] / 2 - margin)
    inside = (max(-half_x, min(half_x, local[0])), max(-half_z, min(half_z, local[1])))
    return geo.add((support.position[0], support.position[1]), geo.rotate(inside, support.yaw_deg))


def rested(target: StageLandmark, support: StageLandmark) -> StageLandmark:
    """``target`` lying on top of ``support``, inside its footprint."""
    return target.model_copy(update={
        "position": geo.rounded(clamped_into(target.position, support)),
        "elevation_m": round(seat_top(support), 3),
    })


def in_shot(contacts: Iterable[StageContact], shot_id: int | None) -> list[StageContact]:
    """The contacts that hold in shot ``shot_id`` (``None``: those that hold for the whole scene)."""
    return [contact for contact in contacts if contact.applies_to(shot_id)]


def _by_name(landmarks: Sequence[StageLandmark]) -> dict[str, int]:
    """Where each name first stands in ``landmarks``: a contact names a piece, and the first piece of that name is it."""
    found: dict[str, int] = {}
    for index, item in enumerate(landmarks):
        found.setdefault(item.name, index)
    return found


def _rest_all(pieces: list[StageLandmark], where: dict[str, int], rests: Sequence[StageContact]) -> None:
    # A thing can rest on a thing that rests on something else: settle until nothing moves (a cycle stops anyway).
    for _ in range(max(1, len(rests))):
        moved = False
        for contact in rests:
            if contact.target not in where or contact.support not in where:
                continue
            target = pieces[where[contact.target]]
            placed = rested(target, pieces[where[contact.support]])
            if placed != target:
                pieces[where[contact.target]] = placed
                moved = True
        if not moved:
            break


def seat_actors(
    actors: Sequence[StageActor], landmarks: Sequence[StageLandmark], contacts: Sequence[StageContact], shot_id: int | None,
) -> list[StageActor]:
    """``actors`` with whoever sits in this shot moved onto their seat; nobody else changes."""
    sits = [contact for contact in in_shot(contacts, shot_id) if contact.kind == "sit"]
    if not sits:
        return list(actors)
    pieces, where = list(landmarks), _by_name(landmarks)
    _rest_all(pieces, where, [contact for contact in in_shot(contacts, shot_id) if contact.kind == "rest"])
    seats = {contact.actor: pieces[where[contact.target]] for contact in sits if contact.target in where}
    return [seated(actor, seat) if (seat := seats.get(actor.name)) is not None else actor for actor in actors]


def seated_names(contacts: Sequence[StageContact], landmarks: Sequence[StageLandmark]) -> set[str]:
    """Who of ``contacts`` (those of one shot) sits on a seat that is on the stage."""
    pieces = {item.name for item in landmarks}
    return {contact.actor for contact in contacts if contact.kind == "sit" and contact.target in pieces}


def place_landmarks(
    landmarks: Sequence[StageLandmark], actors: Sequence[StageActor], contacts: Sequence[StageContact], shot_id: int | None,
) -> list[StageLandmark]:
    """``landmarks`` as they stand in this shot: held props at the hand, rested things on their support.

    ``actors`` is the cast as staged for the shot (overrides and seats applied); a prop whose holder is not on
    the set this shot stays where it is stored.
    """
    current = in_shot(contacts, shot_id)
    if not current:
        return list(landmarks)
    pieces, where = list(landmarks), _by_name(landmarks)
    people = {actor.name: actor for actor in actors}
    sitting = seated_names(current, landmarks)
    for contact in current:
        actor = people.get(contact.actor)
        if contact.kind == "hold" and contact.target in where and actor is not None:
            pieces[where[contact.target]] = held(
                pieces[where[contact.target]], actor, contact.hand, seated=actor.name in sitting,
            )
    _rest_all(pieces, where, [contact for contact in current if contact.kind == "rest"])
    return pieces


def settle(
    actors: Sequence[StageActor], landmarks: Sequence[StageLandmark], contacts: Sequence[StageContact],
) -> tuple[list[StageActor], list[StageLandmark]]:
    """The stored marks with every whole-scene contact applied, so what is stored agrees with what is shown.

    A contact limited to some shots leaves the stored marks alone: they are where things are in the other shots.
    """
    scene = in_shot(contacts, None)
    if not scene:
        return list(actors), list(landmarks)
    staged = seat_actors(actors, landmarks, scene, None)
    return staged, place_landmarks(landmarks, staged, scene, None)


def without_shots(
    contacts: Sequence[StageContact], target: str, shot_ids: Sequence[int], all_shot_ids: Sequence[int],
) -> list[StageContact]:
    """``contacts`` with those on ``target`` taken out of ``shot_ids`` (empty: out of every shot).

    A whole-scene contact taken out of some shots keeps the rest of the scene's shots; one left with no shot is gone.
    """
    kept: list[StageContact] = []
    dropped = set(int(item) for item in shot_ids)
    for contact in contacts:
        if contact.target != target:
            kept.append(contact)
            continue
        if not dropped:
            continue
        covered = list(contact.shot_ids or all_shot_ids)
        remaining = [item for item in covered if item not in dropped]
        if remaining == covered:
            kept.append(contact)
        elif remaining:
            kept.append(contact.model_copy(update={"shot_ids": remaining}))
    return kept


def next_id(contacts: Sequence[StageContact]) -> str:
    """``contact-NN``, one past the highest number in use."""
    numbers = [int(tail) for contact in contacts if (tail := contact.id.rsplit("-", 1)[-1]).isdigit()]
    return f"contact-{1 + max(numbers, default=0):02d}"


def resolvable(contacts: Sequence[StageContact], actors: Iterable[str], landmarks: Iterable[str]) -> list[StageContact]:
    """The contacts whose names are all still on the stage."""
    people, pieces = set(actors), set(landmarks)
    return [
        contact for contact in contacts
        if contact.target in pieces and (not contact.support or contact.support in pieces)
        and (not contact.actor or contact.actor in people)
    ]


__all__ = [
    "clamped_into",
    "hand_height",
    "hand_point",
    "held",
    "in_shot",
    "is_seat",
    "limit",
    "next_id",
    "place_landmarks",
    "resolvable",
    "rested",
    "seat_actors",
    "seat_range",
    "seated_names",
    "seat_top",
    "seated",
    "settle",
    "without_shots",
]
