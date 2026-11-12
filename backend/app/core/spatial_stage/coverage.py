# -*- coding: utf-8 -*-
"""Turn a shot's intent (who, how tight, from what angle, moving how) into a camera on the stage.

Shot sizes become lens + distance through the framing identity
``covered height = 2 · d · tan(fov / 2)``; angles become a lens height; and the
direction the camera stands in is always taken from the established side of the
axis, so a single, its reverse and the master agree on who is screen left
without anyone having to remember it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core import prompt_data
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import CameraMove, StageActor, StageAxis, StageCamera, StageLandmark
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS, posture_height, screen_states

_SIZE_HEIGHT = dict(SHOT_SIZE_HEIGHTS)
_MOVE_WORDS = "stage_camera_moves"
# Size words, lenses, angle words and camera names: app/data/prompt/stage_vocabulary.json.
_VOCABULARY = "stage_vocabulary"
_SIZES: dict = prompt_data.value(_VOCABULARY, "shot_sizes")
_ANGLES: dict = prompt_data.value(_VOCABULARY, "angles")
# Longest names first so 中近景 is not read as 近景: the table's order is the reading order.
_SIZE_ALIASES: tuple[tuple[str, str], ...] = tuple(
    (str(alias), str(size)) for aliases, size in _SIZES["aliases"] for alias in aliases
)
_SIZE_LENS: dict[str, float] = dict(_SIZES["lens_mm"])
# Where on the subject the lens aims, as a fraction of their height.
_SIZE_AIM: dict[str, float] = dict(_SIZES["aim"])
_TIGHT_SIZES = frozenset(_SIZES["tight"])
_WIDE_SIZES = frozenset(_SIZES["wide"])
_OVER_SHOULDER_WORDS = tuple(str(word) for word in _ANGLES["over_shoulder_words"])
_DEFAULT_SIZE = str(_SIZES["default"])
_DEFAULT_ANGLE = str(_ANGLES["default"])
_HIGH_ANGLE = str(_ANGLES["high"])
# Checked in order: the first mode whose words the angle names decides the pitch.
_PITCH_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (str(mode), tuple(str(word) for word in words)) for mode, words in _ANGLES["pitch_words"]
)
_PITCH_DEG = {"top": 90.0, "ground": 0.0, "high": 28.0, "low": -22.0}
_OPERATOR_HEIGHT_M = 1.45
_SINGLE_OFF_AXIS_DEG = 32.0
_SHOULDER_BACK_M = 1.1
_SHOULDER_SIDE_M = 0.34
_EYE_LINE = 0.93
_OVERHEAD_OFFSET_M = 0.01
_INSERT_CLEARANCE_M = 0.2
_CLEARANCE_M = 0.45
_GROUP_EDGE = 0.95
_PULL_BACK = 1.18
_SIDE_MARGIN_M = 0.3
_GROUP_SWINGS = (0.0, 18.0, -18.0, 35.0, -35.0, 52.0, -52.0)
_SINGLE_ANGLES = (32.0, 45.0, 60.0, 75.0, 90.0, 20.0, 12.0)
_SOLO_SWINGS = (40.0, -40.0, 60.0, -60.0, 25.0, -25.0)
_MIN_LENS_MM, _MAX_LENS_MM = 18.0, 135.0
# The 30-degree rule: two consecutive shots of the same subject need a clearly different lens
# direction (or a clearly different size), or the cut reads as a jump.
MIN_ANGLE_CHANGE_DEG = 30.0
SIZE_RANK: dict[str, int] = {name: rank for rank, (name, _height) in enumerate(reversed(SHOT_SIZE_HEIGHTS))}


@dataclass
class ShotSpec:
    """What the storyboard table says about one shot."""

    shot_id: int
    subjects: list[str] = field(default_factory=list)
    speaker: str = ""
    size: str = _DEFAULT_SIZE
    angle: str = ""
    motion: str = ""
    desc: str = ""
    # 分镜表写的时长(秒)；0 表示没写，动作轨道按默认时长排。
    seconds: float = 0.0


# Shot-list shorthand, matched as whole tokens (a bare "cu" also lives inside "mcu" and "focus").
_SIZE_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"(?<![a-z]){pattern}(?![a-z])"), str(size)) for pattern, size in _SIZES["abbreviations"]
)


def named_size(value: str) -> str | None:
    """The size a text names — a Chinese term first, then shot-list shorthand, then English — or ``None``."""
    text = str(value or "").strip().lower()
    for alias, size in _SIZE_ALIASES:
        if not alias.isascii() and alias in text:
            return size
    for pattern, size in _SIZE_ABBREVIATIONS:
        if pattern.search(text):
            return size
    for alias, size in _SIZE_ALIASES:
        if alias.isascii() and alias in text:
            return size
    return None


def canonical_size(value: str) -> str:
    """The size a table cell names; a cell that names none is a 中景."""
    return named_size(value) or _DEFAULT_SIZE


def size_rank(value: str) -> int:
    """0 for the widest shot (大远景) up to 8 for the tightest (大特写)."""
    return SIZE_RANK[canonical_size(value)]


def lens_bearing(camera: StageCamera, about: Sequence[float] | None = None) -> geo.Vec2 | None:
    """Floor direction from what the camera looks at toward the lens; ``None`` for a straight-down lens."""
    centre = about if about is not None else (camera.target[0], camera.target[2])
    delta = (camera.position[0] - centre[0], camera.position[2] - centre[1])
    return geo.unit(delta) if geo.length(delta) > 0.05 else None


def bearing_change_deg(first: StageCamera, second: StageCamera, about: Sequence[float]) -> float | None:
    """Degrees between two lenses as seen from the point both shots are about."""
    a, b = lens_bearing(first, about), lens_bearing(second, about)
    if a is None or b is None:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, geo.dot(a, b)))))


def repeats_the_angle(previous: StageCamera, current: StageCamera) -> bool:
    """The 30-degree rule: the same people, about the same size, from about the same direction.

    Cutting between two such shots reads as a jump. A change of at least two size steps, a
    different set of people, an over-the-shoulder against a clean shot, or an overhead lens are
    each a clear enough change on their own.
    """
    if not current.subjects or set(previous.subjects) != set(current.subjects):
        return False
    if (previous.function == "over_shoulder") != (current.function == "over_shoulder"):
        return False
    if abs(size_rank(previous.shot_size) - size_rank(current.shot_size)) > 1:
        return False
    change = bearing_change_deg(previous, current, (current.target[0], current.target[2]))
    return change is not None and change < MIN_ANGLE_CHANGE_DEG


def _far_enough(target: geo.Vec3, position: geo.Vec3, avoid: geo.Vec2 | None) -> bool:
    if avoid is None:
        return True
    delta = (position[0] - target[0], position[2] - target[2])
    if geo.length(delta) <= 0.05:
        return True
    cosine = max(-1.0, min(1.0, geo.dot(geo.unit(delta), geo.unit(avoid))))
    return math.degrees(math.acos(cosine)) >= MIN_ANGLE_CHANGE_DEG


def wants_over_shoulder(spec: ShotSpec) -> bool:
    text = f"{spec.size} {spec.angle} {spec.desc}".lower()
    return any(word in text for word in _OVER_SHOULDER_WORDS)


def move_kind(motion: str) -> str:
    """Which way the camera travels for a 运镜 note; the wording table is ``stage_camera_moves.json``.

    Negations (不推拉), what a person does (人物靠近镜头) and terms that keep the camera where it is
    (升格 is slow motion, 跟焦 a focus pull, 摇晃 a shake) are taken out first, then phrases outrank
    single characters so 拉近 pushes in. 靠近 / 逼近 / 后退 are a camera move only where the note says
    the camera does it. Whatever travel word is left decides: 「先固定，后缓推」 still pushes.
    """
    text = str(motion or "").lower()
    table = prompt_data.load(_MOVE_WORDS)
    for expression in table["drop_patterns"]:
        text = re.sub(expression, " ", text)
    for phrase in sorted(table["drop_phrases"], key=len, reverse=True):
        text = text.replace(phrase, " ")
    for words, kind in table["phrases"]:
        if any(word in text for word in words):
            return str(kind)
    for expression, kind in table["camera_patterns"]:
        if re.search(expression, text):
            return str(kind)
    for words, kind in table["words"]:
        if any(word in text for word in words):
            return str(kind)
    return "static"


def _pitch(angle: str) -> tuple[str, float]:
    """``(mode, pitch degrees)``; positive pitch puts the lens above its target."""
    text = str(angle or "")
    for mode, words in _PITCH_WORDS:
        if any(word in text for word in words):
            return mode, _PITCH_DEG[mode]
    return "eye", 0.0


def _lens_for(size: str, aspect: float, group: bool) -> float:
    lens = _SIZE_LENS.get(size, 50.0)
    # A portrait frame is narrow: a group needs the wider end to hold everyone.
    return min(lens, 35.0) if group and aspect < 1 else lens


def _aim_height(size: str, subject_height: float) -> float:
    return round(subject_height * _SIZE_AIM.get(size, 0.69), 3)


def _place(
    target: geo.Vec3, toward_camera: geo.Vec2, reach: float, size: str, angle: str,
    eye_height: float | None = None, footprint: tuple[float, float] | None = None,
    fov: float | None = None, aspect: float | None = None,
) -> geo.Vec3:
    """The lens position ``reach`` meters from ``target`` along ``toward_camera``, at the height the angle asks for.

    An eye-level lens sits at the subject's eye line and tilts to its target, the way an operator
    works; only a wide takes the operator's own standing height. An overhead lens rises until the
    ``footprint`` (width across the frame, depth along it) fits, and sits a centimetre toward the
    camera side so the frame keeps that side's screen left and right.
    """
    mode, pitch = _pitch(angle)
    direction = geo.unit(toward_camera)
    if mode == "top":
        height = max(2.2, reach)
        if footprint is not None and fov and aspect:
            half = math.tan(math.radians(fov) / 2)
            height = max(height, (footprint[1] / 2) / half, (footprint[0] / 2) / (half * aspect))
        return (
            round(target[0] + direction[0] * _OVERHEAD_OFFSET_M, 3),
            round(target[1] + height, 3),
            round(target[2] + direction[1] * _OVERHEAD_OFFSET_M, 3),
        )
    ground_reach = reach * math.cos(math.radians(pitch))
    height = target[1] + reach * math.sin(math.radians(pitch))
    if mode == "ground":
        height = 0.3
    elif mode == "eye":
        height = _OPERATOR_HEIGHT_M if size in _WIDE_SIZES or eye_height is None else eye_height
        ground_reach = math.sqrt(max(reach * reach - (height - target[1]) ** 2, (reach * 0.5) ** 2))
    return (
        round(target[0] + direction[0] * ground_reach, 3),
        round(max(0.2, height), 3),
        round(target[2] + direction[1] * ground_reach, 3),
    )


def keep_side(position: geo.Vec3, axis: StageAxis, target: Sequence[float] | None = None) -> geo.Vec3:
    """Push a lens that ended up on (or too near) the wrong side of the axis back onto the established side.

    A lens looking straight down at ``target`` is left where it is: overhead shows no side at all.
    """
    if not axis_rules.has_axis(axis) or axis.camera_side == 0:
        return position
    if target is not None:
        drop = position[1] - target[1]
        if drop > 0 and math.hypot(position[0] - target[0], position[2] - target[2]) < 0.05 * drop:
            return position
    mid = geo.midpoint((axis.start[0], axis.start[1]), (axis.end[0], axis.end[1]))
    direction = geo.unit(axis_rules.axis_vector(axis), (1.0, 0.0))
    normal = axis_rules.camera_side_normal(axis)
    offset = geo.sub((position[0], position[2]), mid)
    needed = abs(geo.dot(offset, direction)) * math.tan(math.radians(axis_rules.NEUTRAL_ANGLE_DEG + 4.0)) + _SIDE_MARGIN_M
    lateral = geo.dot(offset, normal)
    if lateral >= needed:
        return position
    shift = needed - lateral
    return (round(position[0] + normal[0] * shift, 3), position[1], round(position[2] + normal[1] * shift, 3))


def fit_move(
    camera: StageCamera, start_actors: Sequence[StageActor], end_actors: Sequence[StageActor], axis: StageAxis,
) -> StageCamera:
    """Shorten a move until the people it frames are still in frame when it ends.

    A push-in on a two-shot that would cut one of them out stops where both still fit; a track
    or follow whose subject walks away ends where the subject is still in the picture. A pan is
    left alone: it hands the frame to someone else on purpose.
    """
    if camera.move.kind in {"static", "pan"} or not camera.subjects or camera.move.end_position is None:
        return camera
    names = list(camera.subjects)

    def lands(end_position: Sequence[float], end_target: Sequence[float]) -> bool:
        probe = camera.model_copy(update={"move": camera.move.model_copy(update={
            "end_position": geo.rounded(end_position), "end_target": geo.rounded(end_target),
        })})
        states = screen_states(end_actors, probe, end=True)
        return all(state.visible for state in states if state.name in names)

    start_position, start_target = list(camera.position), list(camera.target)
    end_position = list(camera.move.end_position)
    end_target = list(camera.move.end_target or camera.target)
    if lands(end_position, end_target):
        return camera

    def blend(t: float) -> tuple[list[float], list[float]]:
        return (
            [start_position[i] + (end_position[i] - start_position[i]) * t for i in range(3)],
            [start_target[i] + (end_target[i] - start_target[i]) * t for i in range(3)],
        )

    if lands(*blend(0.0)):
        low, high = 0.0, 1.0
        for _ in range(12):
            middle = (low + high) / 2
            if lands(*blend(middle)):
                low = middle
            else:
                high = middle
        position, target = blend(low)
    else:
        # Even holding still loses someone (they walk out of the composition): end on where they arrive.
        present = [actor for actor in end_actors if actor.name in names]
        if not present:
            return camera
        centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in present])
        target = [centre[0], start_target[1], centre[1]]
        offset = [start_position[i] - start_target[i] for i in range(3)]
        position = [target[i] + offset[i] for i in range(3)]
        for _ in range(12):
            if lands(position, target):
                break
            offset = [value * _PULL_BACK for value in offset]
            position = [target[i] + offset[i] for i in range(3)]
        if not axis_rules.is_overhead(camera):
            position = list(keep_side((position[0], position[1], position[2]), axis))
    return camera.model_copy(update={"move": camera.move.model_copy(update={
        "end_position": geo.rounded(position), "end_target": geo.rounded(target),
    })})


def _probe(position: geo.Vec3, target: geo.Vec3, fov: float, aspect_ratio: str, names: Sequence[str]) -> StageCamera:
    return StageCamera(
        id="probe", label="probe", position=geo.rounded(position), target=geo.rounded(target),
        fov_deg=round(max(1.0, min(170.0, fov)), 2), aspect=aspect_ratio, subjects=list(names),
    )


def _tighter(fov: float, planned_reach: float, position: geo.Vec3, target: geo.Vec3) -> float:
    """The field of view that frames at ``position`` what ``fov`` framed at ``planned_reach``."""
    actual = math.dist(position, target)
    # Rounding a position to the millimetre is not a reason to change the lens.
    if planned_reach <= 1e-3 or actual <= planned_reach * 1.02:
        return fov
    covered = geo.visible_height(planned_reach, fov)
    return math.degrees(2 * math.atan(covered / (2 * actual)))


def _lens_of(fov: float, aspect: float) -> float:
    sensor = geo.SENSOR_LONG_SIDE_MM if aspect < 1 else geo.SENSOR_LONG_SIDE_MM / aspect
    return round(max(_MIN_LENS_MM, min(_MAX_LENS_MM, sensor / (2 * math.tan(math.radians(fov) / 2)))), 1)


def _frames_all(position: geo.Vec3, target: geo.Vec3, fov: float, aspect_ratio: str, subjects: Sequence[StageActor]) -> bool:
    states = screen_states(subjects, _probe(position, target, fov, aspect_ratio, [a.name for a in subjects]))
    return all(state.visible and abs(state.x) <= _GROUP_EDGE for state in states)


def _hides_subject(
    position: geo.Vec3, target: geo.Vec3, fov: float, aspect_ratio: str,
    subjects: Sequence[StageActor], actors: Sequence[StageActor],
) -> bool:
    names = [actor.name for actor in subjects]
    states = screen_states(actors, _probe(position, target, fov, aspect_ratio, names))
    return any(state.name in names and state.occluded_by for state in states)


def _clear_of(position: geo.Vec3, subject: StageActor, actors: Sequence[StageActor], aspect_ratio: str, fov: float, target: geo.Vec3) -> bool:
    """The lens is not inside anyone, and nobody nearer the lens hides the subject."""
    for other in actors:
        if other.name == subject.name:
            continue
        gap = geo.distance((position[0], position[2]), (other.position[0], other.position[1]))
        if gap < _CLEARANCE_M and position[1] < other.height_m + 0.2:
            return False
    states = screen_states(actors, _probe(position, target, fov, aspect_ratio, [subject.name]))
    mine = next((state for state in states if state.name == subject.name), None)
    return mine is not None and mine.visible and not mine.occluded_by


def _with_move(camera: StageCamera, axis: StageAxis, counterpart: StageActor | None) -> StageCamera:
    """The end pose of the camera's move. Only a declared crossing may leave the established side,
    and none of the solved moves is one: an orbit arcs within the side, a track or follow slides along it."""
    kind = camera.move.kind
    if kind == "static":
        return camera
    position, target = tuple(camera.position), tuple(camera.target)
    offset = tuple(position[i] - target[i] for i in range(3))
    overhead = axis_rules.is_overhead(camera)
    look = geo.unit((target[0] - position[0], target[2] - position[2]))
    right = geo.right_of(look)
    end_position, end_target = position, target
    if kind == "push":
        end_position = tuple(target[i] + offset[i] * 0.72 for i in range(3))
    elif kind == "pull":
        end_position = tuple(target[i] + offset[i] * 1.32 for i in range(3))
    elif kind == "rise":
        end_position = (position[0], position[1] + 0.9, position[2])
    elif kind == "fall":
        end_position = (position[0], max(0.3, position[1] - 0.6), position[2])
    elif kind in {"track", "follow"}:
        # A track slides the lens and keeps its subject (parallax); a follow drifts both a little.
        frame_width = geo.visible_height(math.dist(position, target), camera.fov_deg) * geo.parse_aspect(camera.aspect)
        slide = max(0.12, frame_width * (0.35 if kind == "track" else 0.12))
        end_position = (position[0] + right[0] * slide, position[1], position[2] + right[1] * slide)
        if kind == "follow" or overhead:
            end_target = (target[0] + right[0] * slide, target[1], target[2] + right[1] * slide)
    elif kind == "pan":
        if counterpart is not None and not overhead:
            # A pan hands the frame from the subject to the person they play against.
            end_target = (counterpart.position[0], target[1], counterpart.position[1])
        else:
            frame_width = geo.visible_height(math.dist(position, target), camera.fov_deg) * geo.parse_aspect(camera.aspect)
            sweep = max(0.1, frame_width * 0.3)
            end_target = (target[0] + right[0] * sweep, target[1], target[2] + right[1] * sweep)
            if overhead:
                end_position = (position[0] + right[0] * sweep, position[1], position[2] + right[1] * sweep)
    elif kind == "orbit":
        ground = (offset[0], offset[2])
        for degrees in (25.0, -25.0):
            turned = geo.rotate(ground, degrees)
            candidate = (target[0] + turned[0], position[1], target[2] + turned[1])
            if overhead or axis_rules.side_of(axis, (candidate[0], candidate[2])) in {axis.camera_side, 0} or not axis.camera_side:
                end_position = candidate
                break
    if not overhead:
        end_position = keep_side(end_position, axis)
    return camera.model_copy(update={"move": CameraMove(
        kind=kind,
        end_position=geo.rounded(end_position),
        end_target=geo.rounded(end_target),
    )})


def solve_camera(
    spec: ShotSpec,
    actors: Sequence[StageActor],
    axis: StageAxis,
    *,
    aspect_ratio: str,
    principals: Sequence[str] = (),
    landmarks: Sequence[StageLandmark] = (),
    stage_center: geo.Vec2 = (0.0, 0.0),
    first_shot: bool = False,
    avoid_bearing: geo.Vec2 | None = None,
) -> StageCamera:
    """The camera that shoots ``spec`` from the established side of ``axis``.

    ``avoid_bearing`` is the floor direction the previous shot of the same subject was taken
    from; the solver then prefers a lens at least 30 degrees away from it.
    """
    aspect = geo.parse_aspect(aspect_ratio)
    size = canonical_size(spec.size)
    by_name = {actor.name: actor for actor in actors}
    subjects = [by_name[name] for name in dict.fromkeys(spec.subjects) if name in by_name]
    normal = axis_rules.camera_side_normal(axis) if axis_rules.has_axis(axis) else (0.0, 1.0)
    axis_mid = (
        geo.midpoint((axis.start[0], axis.start[1]), (axis.end[0], axis.end[1]))
        if axis_rules.has_axis(axis) else stage_center
    )
    counterpart: StageActor | None = None
    function = "single"
    angle = spec.angle or _DEFAULT_ANGLE

    # The set piece a shot of nobody is about is the one its description names first.
    named = [] if subjects else [item for item in landmarks if item.name and item.name in spec.desc]
    insert = min(named, key=lambda item: spec.desc.index(item.name)) if named else None
    if insert is not None:
        # A shot of nobody that names a set piece is an insert of that piece, not a view of the room.
        function = "detail"
        # An insert with no angle written looks down at the piece; the camera records that, so solving it again gives the same lens.
        angle = spec.angle or _HIGH_ANGLE
        size = size if size in _TIGHT_SIZES else str(_SIZES["insert"])
        lens = _lens_for(size, aspect, False)
        fov = geo.vertical_fov(lens, aspect)
        # The piece is shot where it lies: a cup on a table is a table's height above the floor,
        # and the lens stays above that table top instead of looking up through it.
        surface = insert.elevation_m
        target = (round(insert.position[0], 3), round(surface + insert.size[2] * 0.8, 3), round(insert.position[1], 3))
        covered = max(_SIZE_HEIGHT[size], insert.size[2] * 1.2)
        reach = geo.framing_distance(covered, fov)
        placed = _place(target, normal, reach, size, angle, footprint=(covered, covered), fov=fov, aspect=aspect)
        placed = (placed[0], max(placed[1], round(surface + _INSERT_CLEARANCE_M, 3)), placed[2])
        position = keep_side(placed, axis, target)
        # A lens that ends up farther than the framing distance (sent back out to the camera side by a piece upstage
        # of the axis, or raised over the piece) is lengthened, so the piece still fills the frame the shot asks for.
        # Moving in instead would take it across the axis. Overhead, the height _place rose to so the piece fits
        # across the narrow side of the frame is framing too, not slack to take up with the lens.
        framed = geo.framing_distance(covered / min(1.0, aspect), fov) if _pitch(angle)[0] == "top" else reach
        fov = _tighter(fov, framed, position, target)
        lens = _lens_of(fov, aspect)
        fov = geo.vertical_fov(lens, aspect)
    elif not subjects:
        function = "empty"
        size = size if size in _WIDE_SIZES else str(_SIZES["empty"])
        lens = _lens_for(size, aspect, True)
        fov = geo.vertical_fov(lens, aspect)
        target = (stage_center[0], 1.0, stage_center[1])
        reach = max(3.5, geo.framing_distance(_SIZE_HEIGHT[size] * 1.4, fov))
        position = keep_side(_place(target, normal, reach, size, spec.angle, footprint=(5.0, 5.0), fov=fov, aspect=aspect), axis, target)
    elif len(subjects) >= 2:
        function = "establish" if first_shot or (size in _WIDE_SIZES and all(name in spec.subjects for name in principals)) else "relation"
        # Two people cannot share a close-up: the frame is at least a medium close-up, whatever the table called it.
        framing = size if size not in _SIZES["pair_too_tight"] else str(_SIZES["pair"])
        lens = _lens_for(framing, aspect, True)
        fov = geo.vertical_fov(lens, aspect)
        centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in subjects])
        tallest = max(posture_height(actor) for actor in subjects)
        target = (round(centre[0], 3), _aim_height(framing, tallest), round(centre[1], 3))
        right = geo.right_of(geo.scale(normal, -1.0))
        spans = [geo.dot(geo.sub((actor.position[0], actor.position[1]), centre), right) for actor in subjects]
        depths = [geo.dot(geo.sub((actor.position[0], actor.position[1]), centre), normal) for actor in subjects]
        width = (max(spans) - min(spans)) + 1.0
        footprint = (width, (max(depths) - min(depths)) + 1.0)
        by_width = (width / 2) / math.tan(math.radians(geo.horizontal_fov(fov, aspect)) / 2)
        reach = max(geo.framing_distance(_SIZE_HEIGHT[framing], fov), by_width) + max(0.0, max(depths))
        eye = tallest * _EYE_LINE
        best: geo.Vec3 | None = None
        # Square on to the pair first; swing within the established side when someone stands in line
        # behind someone else, and pull back (or rise, overhead) until every subject is inside the frame.
        for swing in _GROUP_SWINGS:
            approach = geo.rotate(normal, swing)
            local_reach, local_print = reach, footprint
            candidate = keep_side(_place(target, approach, local_reach, framing, spec.angle, eye, local_print, fov, aspect), axis, target)
            for _ in range(12):
                if _frames_all(candidate, target, fov, aspect_ratio, subjects):
                    break
                local_reach *= _PULL_BACK
                local_print = (local_print[0] * _PULL_BACK, local_print[1] * _PULL_BACK)
                candidate = keep_side(_place(target, approach, local_reach, framing, spec.angle, eye, local_print, fov, aspect), axis, target)
            best = best or candidate
            if not _hides_subject(candidate, target, fov, aspect_ratio, subjects, actors) and _far_enough(target, candidate, avoid_bearing):
                best = candidate
                break
            if _pitch(spec.angle)[0] == "top":
                break
        position = best
    else:
        subject = subjects[0]
        ground = (subject.position[0], subject.position[1])
        counterpart = _counterpart(subject, axis, by_name, principals)
        lens = _lens_for(size, aspect, False)
        fov = geo.vertical_fov(lens, aspect)
        target = (round(ground[0], 3), _aim_height(size, posture_height(subject)), round(ground[1], 3))
        reach = geo.framing_distance(_SIZE_HEIGHT[size], fov)
        single_print = (max(_SIZE_HEIGHT[size], 0.7), max(_SIZE_HEIGHT[size], 0.7))
        if size == _SIZES["detail"]:
            function = "detail"
        elif spec.speaker and spec.speaker != subject.name and spec.speaker in by_name:
            function = "reaction"
        if counterpart is not None and wants_over_shoulder(spec) and size not in _WIDE_SIZES:
            function = "over_shoulder"
            other = (counterpart.position[0], counterpart.position[1])
            away = geo.unit(geo.sub(other, ground))
            # Far enough behind that the near shoulder still falls inside a narrow portrait frame,
            # and far enough off the line that the lens is never mistaken for a neutral, on-axis shot.
            behind = _SHOULDER_BACK_M
            lateral = max(_SHOULDER_SIDE_M, 0.12 * (geo.distance(ground, other) / 2 + behind))
            spot = geo.add(geo.add(other, geo.scale(away, behind)), geo.scale(normal, lateral))
            position = (round(spot[0], 3), round(posture_height(counterpart) * 0.88 + 0.12, 3), round(spot[1], 3))
            # The distance is dictated by the shoulder, so the lens is what makes the size; an
            # over-the-shoulder never frames tighter than a medium close-up or the shoulder is lost.
            reach = math.dist(position, target)
            covered = max(_SIZE_HEIGHT[size], _SIZE_HEIGHT[_SIZES["over_shoulder_min"]])
            fov = math.degrees(2 * math.atan(covered / (2 * max(reach, 0.3))))
            lens = _lens_of(fov, aspect)
            fov = geo.vertical_fov(lens, aspect)
        else:
            if counterpart is not None:
                toward = geo.unit(geo.sub((counterpart.position[0], counterpart.position[1]), ground))
            elif axis_rules.has_axis(axis):
                toward = geo.unit(geo.sub(geo.add(axis_mid, geo.scale(normal, 3.0)), ground), normal)
            else:
                toward = geo.forward_of(subject.yaw_deg)
            eye = posture_height(subject) * _EYE_LINE
            first_angle = 25.0 if size in _SIZES["close_up"] else _SINGLE_OFF_AXIS_DEG
            position = None
            # Swing away from the partner (always toward the established side) until the lens stands
            # clear of everyone and nobody nearer the lens hides the subject.
            planned_reach = math.dist(_place(target, normal, reach, size, spec.angle, eye, single_print, fov, aspect), target)
            fallback: geo.Vec3 | None = None
            directions = [
                geo.unit(geo.add(geo.scale(toward, math.cos(math.radians(off_axis))), geo.scale(normal, math.sin(math.radians(off_axis)))), normal)
                for off_axis in (first_angle, *_SINGLE_ANGLES[1:])
            ]
            if counterpart is None:
                # With nobody to play against, the lens already faces the subject square on from the
                # side, and swinging it toward that side changes nothing: swing it around instead.
                directions = [directions[0], *(geo.rotate(directions[0], swing) for swing in _SOLO_SWINGS)]
            for direction in directions:
                candidate = keep_side(_place(target, direction, reach, size, spec.angle, eye, single_print, fov, aspect), axis, target)
                if _clear_of(candidate, subject, actors, aspect_ratio, _tighter(fov, planned_reach, candidate, target), target):
                    fallback = fallback or candidate
                    if _far_enough(target, candidate, avoid_bearing):
                        position = candidate
                        break
            # No clear lens 30 degrees away: a clear one that repeats the angle beats a blocked one.
            position = position or fallback
            if position is None:
                radians = math.radians(first_angle)
                direction = geo.unit(geo.add(geo.scale(toward, math.cos(radians)), geo.scale(normal, math.sin(radians))), normal)
                position = keep_side(_place(target, direction, reach, size, _HIGH_ANGLE, eye, single_print, fov, aspect), axis, target)
            # A lens pushed back to keep its side is lengthened, so the shot keeps the size the table asked for.
            fov = _tighter(fov, planned_reach, position, target)
            lens = _lens_of(fov, aspect)
            fov = geo.vertical_fov(lens, aspect)

    camera = StageCamera(
        id=f"cam-{spec.shot_id:02d}",
        label=_label(spec.shot_id, function, [actor.name for actor in subjects], spec.size or size),
        position=geo.rounded(position),
        target=geo.rounded(target),
        lens_mm=round(lens, 1),
        fov_deg=round(fov, 2),
        aspect=aspect_ratio,
        shot_size=(spec.size or size)[:80],
        angle=angle[:120],
        function=function,
        subjects=[actor.name for actor in subjects],
        move=CameraMove(kind=move_kind(spec.motion)),
    )
    return _with_move(camera, axis, counterpart)


def _counterpart(
    subject: StageActor, axis: StageAxis, by_name: dict[str, StageActor], principals: Sequence[str],
) -> StageActor | None:
    """Who this character is playing the scene against: the other end of the axis, else the other principal."""
    if axis.kind in {"dialogue", "motion"}:
        if subject.name == axis.from_name and axis.to_name in by_name:
            return by_name[axis.to_name]
        if subject.name == axis.to_name and axis.from_name in by_name:
            return by_name[axis.from_name]
    others = [by_name[name] for name in principals if name != subject.name and name in by_name]
    return others[0] if others and subject.name in principals else None


_LABELS: dict = prompt_data.value(_VOCABULARY, "camera_labels")
_FUNCTION_LABELS: dict[str, str] = {str(key): str(word) for key, word in _LABELS["functions"].items()}


def _label(shot_id: int, function: str, names: Sequence[str], size: str) -> str:
    who = str(_LABELS["name_separator"]).join(names[:3]) or str(_LABELS["nobody"])
    return str(_LABELS["template"]).format(
        shot_id=shot_id, function=_FUNCTION_LABELS.get(function, function), who=who, size=size,
    )[:160]


__all__ = [
    "MIN_ANGLE_CHANGE_DEG", "SIZE_RANK", "ShotSpec", "bearing_change_deg", "canonical_size", "fit_move", "keep_side",
    "lens_bearing", "move_kind", "named_size", "repeats_the_angle", "size_rank", "solve_camera", "wants_over_shoulder",
]
