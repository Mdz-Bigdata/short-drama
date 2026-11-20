# -*- coding: utf-8 -*-
"""Build the spatial stage of a scene from what the script and the storyboard table say.

Deterministic on purpose: the same cast, location and shot table always give the
same marks, so a re-run does not shuffle who stands where. The rules are the
staging conventions the shot-design skill already teaches — principals play
across one axis, a third person closes an inverted triangle upstage, groups arc
behind, cameras live on one side — turned into coordinates. However a pair
stands (face to face, shoulder to shoulder, back to back, one a step behind the
other), both stay on that axis: a shape is a distance and two headings, so the
cameras, the set and whoever stands upstage never have to know which it is.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.core import prompt_data, prop_scale
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import contacts as contact_rules
from app.core.spatial_stage import crowds as crowd_arrays
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage import performance
from app.core.spatial_stage.coverage import ShotSpec, fit_move, solve_camera
from app.core.spatial_stage.cutting import carry_camera, vary_angle
from app.core.spatial_stage.language import enters_in, posture_in, travel_in
from app.core.spatial_stage.models import (
    ActorOverride,
    StageActor,
    StageAxis,
    StageBackdrop,
    StageCamera,
    StageContact,
    StageEffect,
    StageCrowd,
    StageLandmark,
    StagePlan,
    StageShot,
)
from app.core.spatial_stage.projection import screen_states
from app.core.spatial_stage.prompting import scene_bible, shot_text
from app.core.spatial_stage.validation import MIN_ACTOR_SPACING_M, check_plan, pair_relation, set_obstructions

# Who counts as nobody or as a crowd, how far apart a pair stands, the reasons and the formation
# sentences: app/data/prompt/stage_planner.json.
_WORDING = "stage_planner"


def _words(*path: str) -> Any:
    """The entry of the planner's wording table at ``path``."""
    found: Any = prompt_data.load(_WORDING)
    for key in path:
        found = found[key]
    return found


def _phrase(key: str, **values: object) -> str:
    """A formation sentence, filled in."""
    return str(_words("formations", key)).format(**values)


EMPTY_CAST = frozenset(str(name) for name in _words("empty_cast"))
CROWD_MARKERS: tuple[str, ...] = tuple(str(word) for word in _words("crowd_markers"))
_PLACEHOLDER_PROPS = tuple(str(word) for word in _words("placeholder_props"))
_SEPARATION_RULES: tuple[tuple[tuple[str, ...], float, str], ...] = tuple(
    (tuple(str(word) for word in rule["words"]), float(rule["metres"]), str(rule["label"]))
    for rule in _words("separation_rules")
)
_DEFAULT_SEPARATION: tuple[float, str] = (
    float(_words("default_separation", "metres")), str(_words("default_separation", "label")),
)
_SIDE_BY_SIDE = tuple(str(word) for word in _words("side_by_side"))
# Shoulder to shoulder is a distance of its own: what the scene's words say about mood does not widen it.
_SIDE_BY_SIDE_M = float(_words("side_by_side_metres"))


@dataclass(frozen=True)
class _PairShape:
    """A way two people stand that is neither face to face nor shoulder to shoulder."""

    words: tuple[str, ...]
    label: str
    relation: str = ""            # the planner's own name for the shape …
    relation_key: str = ""        # … or the entry of stage_brief.json pair_relations that names it
    apart_m: float | None = None  # each turned away from the other, this far apart
    back_m: float = 0.0           # same heading: the one behind stands this far back …
    side_m: float = 0.0           # … and this far to the side
    subject_in_front: bool = True  # the person the word's clause is about is the one in front

    def name(self) -> str:
        return pair_relation(self.relation_key) if self.relation_key else self.relation


_PAIR_SHAPES: tuple[_PairShape, ...] = tuple(
    _PairShape(
        words=tuple(str(word) for word in shape["words"]), label=str(shape["label"]),
        relation=str(shape.get("relation") or ""), relation_key=str(shape.get("relation_key") or ""),
        apart_m=float(shape["metres"]) if "metres" in shape else None,
        back_m=float(shape.get("back_m") or 0.0), side_m=float(shape.get("side_m") or 0.0),
        subject_in_front=str(shape.get("subject") or "front") != "behind",
    )
    for shape in _words("pair_shapes")
)
# How many characters may stand between a principal's name and the word that says how the pair stands.
_SUBJECT_GAP = int(_words("pair_subject_gap"))
_TIME_OF_DAY = re.compile("(" + "|".join(re.escape(str(word)) for word in _words("time_of_day_suffixes")) + ")$")
# Set dressing a prop list or the script text names (a door, a window, a desk): app/data/prompt/stage_set_pieces.json.
_SET_PIECES = "stage_set_pieces"
_PROP_SLOTS = ("between", "near_left", "near_right", "upstage_left", "upstage_right", "upstage_far")
_UPSTAGE_SLOTS = ("upstage_left", "upstage_right", "upstage_far")
# A prop with a side longer than this is furniture-sized: it stands upstage, never among the cast.
_BIG_PROP_M = 1.0
# How big a prop stands on the stage and what it may rest on: app/data/prompt/stage_props.json.
_PROPS = "stage_props"
_NOTE_IN_BRACKETS = re.compile(r"[（(][^）)]*[）)]")
# A set piece keeps this much air around anyone's mark: half a body and a little more.
_CLEAR_OF_CAST_M = 0.3
_CLEAR_STEP_M = 0.6
_CLEAR_STEPS = 8
# Why the planner itself puts someone off their mark for a shot.
ENTRANCE_REASON = str(_words("reasons", "entrance"))
APPROACH_REASON = str(_words("reasons", "approach"))
RETREAT_REASON = str(_words("reasons", "retreat"))
_HOLD_REASONS = {APPROACH_REASON: str(_words("reasons", "hold_approach")), RETREAT_REASON: str(_words("reasons", "hold_retreat"))}
# What a shot's words say someone holds or sits on: the verbs, the hand words, and how many characters may stand
# between the name and the verb and between the verb and the thing (one clause; the clause marks are the
# blocking vocabulary's).
_HOLD_VERBS = tuple(sorted((str(word) for word in _words("contact_verbs", "hold")), key=len, reverse=True))
_SIT_VERBS = tuple(sorted((str(word) for word in _words("contact_verbs", "sit")), key=len, reverse=True))
_CONTACT_HANDS = tuple((str(word), str(hand)) for word, hand in _words("contact_hands"))
_NAME_GAP = int(_words("contact_gaps", "name"))
_OBJECT_GAP = int(_words("contact_gaps", "object"))
_CLAUSE_STOPS = str(prompt_data.value("stage_vocabulary", "blocking_verbs")["clause_stops"])
# A seat already on the set (from the location, an earlier plan, a person) is only sat on from this close to the mark.
_SEAT_REACH_M = float(_words("seat_reach_m"))


@dataclass
class SceneBrief:
    scene_id: str
    location: str = ""
    text: str = ""
    characters: list[str] = field(default_factory=list)
    props: list[str] = field(default_factory=list)
    shots: list[ShotSpec] = field(default_factory=list)
    aspect_ratio: str = "9:16"
    # Standing heights in meters the character profiles state ("身高168cm"); the rest stand 1.7 m.
    heights: dict[str, float] = field(default_factory=dict)


_HEIGHT = re.compile(r"(?<!\d)(1[2-9]\d|2[0-2]\d)\s*(?:cm|CM|厘米|公分)|身高\s*(1\.\d{1,2}|2\.[0-2]\d?)\s*(?:米|m(?![a-z]))")


def height_from_text(text: str) -> float | None:
    """The standing height a profile states, in meters: 168cm / 身高1.68米 → 1.68."""
    match = _HEIGHT.search(str(text or ""))
    if match is None:
        return None
    return round(int(match.group(1)) / 100, 2) if match.group(1) else round(float(match.group(2)), 2)


def location_key(location: str) -> str:
    """Two scenes share a set when their location reads the same once time of day and INT/EXT are dropped."""
    text = re.sub(r"[\s/／|｜·,，;；:：\-—]+", "", str(location or ""))
    while len(text) > 1 and _TIME_OF_DAY.search(text):
        text = _TIME_OF_DAY.sub("", text)
    return text[:200]


def is_crowd(name: str) -> bool:
    return any(marker in name for marker in CROWD_MARKERS)


def cast_fingerprint(characters: Sequence[str], location: str) -> str:
    names = sorted({name.strip() for name in characters if name.strip() not in EMPTY_CAST})
    return hashlib.sha1(("|".join(names) + "@" + location_key(location)).encode("utf-8")).hexdigest()[:16]


def speaker_of(dialogue: str, cast: Sequence[str]) -> str:
    """The character a storyboard dialogue cell attributes its line to."""
    text = str(dialogue or "").strip()
    match = re.match(r"^[【\[]?([^：:】\]]{1,20})[】\]]?\s*[（(]?[^：:）)]{0,20}[）)]?\s*[：:]", text)
    if not match:
        return ""
    head = match.group(1).strip()
    return next((name for name in cast if name and (name == head or name in head)), "")


def _slug(index: int) -> str:
    return f"actor-{index:02d}"


def _principals(cast: Sequence[str], shots: Sequence[ShotSpec]) -> list[str]:
    people = [name for name in cast if not is_crowd(name)]
    weight = {name: (len(people) - index) * 0.01 for index, name in enumerate(people)}
    for shot in shots:
        for name in shot.subjects:
            if name in weight:
                weight[name] += 1
        if shot.speaker in weight:
            weight[shot.speaker] += 2
    # The two the scene is about are chosen by how much of it they carry; which of them stands
    # screen left is not a matter of weight but of who the script names first.
    chosen = set(sorted(people, key=lambda name: -weight[name])[:2])
    return [name for name in people if name in chosen]


def _separation(text: str) -> tuple[float, str]:
    for words, meters, label in _SEPARATION_RULES:
        if any(word in text for word in words):
            return meters, label
    return _DEFAULT_SEPARATION


def _posture(name: str, text: str, default: str = "stand") -> str:
    return posture_in(name, text, default) or default


def _clause_subject(pair: Sequence[str], words: Sequence[str], text: str, others: Sequence[str]) -> str | None:
    """Which of the ``pair`` a clause with one of ``words`` is about, when it says how the two stand to each other.

    "柳烟跟在沈砚身后" is about 柳烟, named before the word; "他护着柳烟" is about whoever is not 柳烟, named
    right after it. With both named before the word the nearer one is the subject ("柳烟被沈砚护在身后"),
    unless the word goes on to one of the ``others`` ("沈砚和柳烟跟在管家身后" places neither against the other).
    """
    pattern = "(?:" + "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True)) + ")"
    gap = "[^" + _CLAUSE_STOPS + "]{0,%d}?" % _SUBJECT_GAP
    before = {
        name: len(found.group(1)) for name in pair
        if (found := re.search(re.escape(name) + "(" + gap + ")" + pattern, text)) is not None
    }
    if len(before) == 1:
        return next(iter(before))
    if before:
        if any(re.search(pattern + gap + re.escape(name), text) for name in others if name):
            return None
        return min(before, key=before.__getitem__)
    after = [name for name in pair if re.search(pattern + gap + re.escape(name), text)]
    return next(name for name in pair if name != after[0]) if len(after) == 1 else None


def _side_by_side(pair: Sequence[str], others: Sequence[str], text: str) -> bool:
    """Whether the scene's words put the two principals shoulder to shoulder.

    A clause with a side-by-side word counts when it names one of the ``pair`` ("沈砚与柳烟并肩走在长街上") or
    nobody of the cast ("两人并肩而行"). One that names only ``others`` is about them: "卫长老和何管事并肩站在
    旗杆下" leaves the pair where the rest of the scene puts it (a kneeling one stays a kneeling one's distance away).
    """
    for clause in re.split("[" + _CLAUSE_STOPS + "]", text):
        if not any(word in clause for word in _SIDE_BY_SIDE):
            continue
        if any(name in clause for name in pair) or not any(name and name in clause for name in others):
            return True
    return False


def _pair_shape(first: str, second: str, others: Sequence[str], text: str) -> tuple[_PairShape, str] | None:
    """The shape the scene's words put the two principals in and, for a same-heading one, who is in front."""
    for shape in _PAIR_SHAPES:
        if shape.apart_m is not None:
            if any(word in text for word in shape.words):
                return shape, ""
            continue
        subject = _clause_subject((first, second), shape.words, text, others)
        if subject:
            return shape, subject if shape.subject_in_front else (second if subject == first else first)
    return None


def _shared_heading(front: geo.Vec2, behind: geo.Vec2, back: float, side: float, normal: geo.Vec2) -> float:
    """The yaw two people on the axis share when whoever is on ``behind`` stands ``back`` behind and ``side`` beside the other.

    The heading is the line from the one behind to the one in front, turned toward the camera side
    (``normal``) by as much as the sideways step asks: nobody walks away from the lens, and with no step
    back at all the two simply face it, shoulder to shoulder.
    """
    along = geo.unit(geo.sub(front, behind), (1.0, 0.0))
    tilt = math.atan2(side, back)
    heading = geo.add(geo.scale(along, math.cos(tilt)), geo.scale(normal, math.sin(tilt)))
    return geo.normalize_yaw(math.degrees(math.atan2(heading[0], heading[1])))


def _group_shape(text: str) -> str:
    """``"ring"`` / ``"rows"`` when the scene's words seat the whole group one of those ways."""
    if any(str(word) in text for word in _words("group_shapes", "ring", "words")):
        return "ring"
    if any(str(word) in text for word in _words("group_shapes", "rows", "words")):
        return "rows"
    return ""


def _ring_marks(count: int, radius: float) -> list[geo.Vec2]:
    """Upstage marks of a half circle that opens toward the camera, evenly between its two ends at ±``radius``."""
    return [
        (-radius * math.cos(math.pi * index / (count + 1)), -radius * math.sin(math.pi * index / (count + 1)))
        for index in range(1, count + 1)
    ]


def _row_marks(count: int, spacing: float, depth: float) -> tuple[list[geo.Vec2], list[geo.Vec2]]:
    """Marks for ``count`` more people around a pair seated ``spacing`` apart: who joins the front row, who stands behind.

    The two rows share the group as evenly as they can, the front one taking the odd person. The front row
    grows outward from the pair, right then left; the back row is centred ``depth`` behind it.
    """
    front_extra = (count + 2 + 1) // 2 - 2
    front = [
        ((1 if index % 2 == 0 else -1) * spacing * (index // 2 + 1.5), 0.0)
        for index in range(front_extra)
    ]
    return front, geo.line_positions(count - front_extra, (0.0, -depth), (1.0, 0.0), spacing)


def _slot(slot: str, left: geo.Vec2, right: geo.Vec2, normal: geo.Vec2, index: int = 0) -> geo.Vec2:
    centre = geo.midpoint(left, right)
    along = geo.unit(geo.sub(right, left), (1.0, 0.0))
    upstage = geo.scale(normal, -1.0)
    spots: dict[str, geo.Vec2] = {
        "between": geo.add(centre, geo.scale(upstage, 0.9)),
        "near_left": geo.add(geo.add(left, geo.scale(along, -0.7)), geo.scale(upstage, 0.6)),
        "near_right": geo.add(geo.add(right, geo.scale(along, 0.7)), geo.scale(upstage, 0.6)),
        "upstage_left": geo.add(geo.add(centre, geo.scale(along, -2.2)), geo.scale(upstage, 2.0)),
        "upstage_right": geo.add(geo.add(centre, geo.scale(along, 2.2)), geo.scale(upstage, 2.0)),
        "stage_right": geo.add(geo.add(centre, geo.scale(along, 3.0)), geo.scale(upstage, 1.2)),
        "upstage_far": geo.add(centre, geo.scale(upstage, 3.4)),
        "upstage_left_far": geo.add(geo.add(centre, geo.scale(along, -2.8)), geo.scale(upstage, 3.4)),
        "upstage_right_far": geo.add(geo.add(centre, geo.scale(along, 2.8)), geo.scale(upstage, 3.4)),
        "upstage_deep": geo.add(centre, geo.scale(upstage, 4.4)),
    }
    base = spots.get(slot, spots["upstage_far"])
    return geo.add(base, geo.scale(along, 1.1 * index)) if index else base


def _set_piece(name: str) -> Mapping[str, Any] | None:
    """The set piece a prop name names, read from the end of the name (the longest ending wins), or ``None``.

    A name is what its ending says it is: 档案 and 图案 are not a 书案, 门牌 is not a 门, 灯笼 is not a 灯火.
    """
    table = prompt_data.load(_SET_PIECES)
    bare = _NOTE_IN_BRACKETS.sub("", name).strip()
    readings: list[tuple[str, Mapping[str, Any] | None]] = [(word, None) for word in table["not_pieces"] if bare.endswith(word)]
    for piece in table["pieces"]:
        readings.extend((word, piece) for word in piece["names"] if word == bare)
        readings.extend((word, piece) for word in piece["endings"] if bare.endswith(word))
    return max(readings, key=lambda reading: len(reading[0]), default=("", None))[1]


def _prop_size(name: str) -> tuple[float, float, float]:
    """Width, depth and height (metres, lying flat) of a prop the set-piece table does not name.

    Its real size from the prop scale table, else the usual size of a thing of that name, else the stand-in box.
    A character that also ends the names of other things (牌 in 招牌, 坛 in 祭坛) only counts as the whole name.
    """
    table = prompt_data.load(_PROPS)
    stand_in = tuple(float(value) for value in table["stand_in_m"])
    scale = prop_scale.lookup(name)
    if scale is None:
        bare = _NOTE_IN_BRACKETS.sub("", name).strip()
        endings = sorted(((word, size) for words, size in table["by_ending"] for word in words), key=lambda item: -len(item[0]))
        size = next(
            (size for words, size in table["by_name"] if bare in words),
            next((size for word, size in endings if bare.endswith(word)), stand_in),
        )
    elif scale.longest_cm / 100 > float(table["stage_limit_m"]):
        size = stand_in
    else:
        metres = [value / 100 for value in scale.dims_cm]
        if scale.diameter:
            size = (metres[0], metres[0], metres[-1])
        elif len(metres) >= 3:
            size = metres[:3]
        elif len(metres) == 2 and any(scale.name.endswith(word) for word in table["sheets"]):
            # The two sides of something flat: a sheet of paper, a shield. The floor thickness is added below.
            size = (metres[0], metres[1], 0.0)
        elif len(metres) == 2:
            # Length and girth: a bottle, a bomb, a gourd.
            size = (metres[0], metres[1], metres[1])
        else:
            # Only the length is known: a pen, a sword, a hairpin.
            size = (metres[0], metres[0] / 10, metres[0] / 10)
    floor = float(table["floor_m"])
    return tuple(round(max(floor, float(value)), 3) for value in size)  # type: ignore[return-value]


def _piece_size(piece: Mapping[str, Any]) -> tuple[float, float, float]:
    width, depth, height = (float(value) for value in piece["size_m"])
    return (width, depth, height)


def _rests_on_a_table(kind: str, size: Sequence[float]) -> bool:
    return kind == "prop" and max(size) <= float(prompt_data.load(_PROPS)["hand_prop_m"])


def _is_table(name: str, size: Sequence[float]) -> bool:
    """Something with a top at table height, wide enough to lay a prop on, and named as a table."""
    table = prompt_data.load(_PROPS)
    low, high = table["table_height_m"]
    bare = _NOTE_IN_BRACKETS.sub("", name).strip()
    return (
        float(low) <= size[2] <= float(high) and size[0] >= float(table["table_min_width_m"])
        and (bare in table["table_names"] or any(bare.endswith(word) for word in table["tables"]))
    )


def _clear_of_cast(point: geo.Vec2, size: Sequence[float], actors: Sequence[StageActor], normal: geo.Vec2) -> geo.Vec2:
    """Step a piece upstage until nobody's mark is inside its footprint: nothing is dressed onto someone."""
    for _ in range(_CLEAR_STEPS):
        footprint = SimpleNamespace(position=point, size=size, yaw_deg=0.0)
        if not any(geo.inside_piece(actor.position, footprint, _CLEAR_OF_CAST_M) for actor in actors):
            break
        point = geo.add(point, geo.scale(normal, -_CLEAR_STEP_M))
    return point


def _on_table(table: StageLandmark, size: Sequence[float], index: int) -> geo.Vec2:
    """Where the ``index``-th small prop lies on the table top: the middle first, then alternating toward the ends."""
    reach = max(0.0, table.size[0] / 2 - size[0] / 2 - 0.05)
    step = (index + 1) // 2 * (1 if index % 2 else -1)
    lanes = max(1, int(reach // 0.3))
    along = reach * max(-1.0, min(1.0, step / lanes))
    return geo.add((table.position[0], table.position[1]), geo.rotate((along, 0.0), table.yaw_deg))


def _landmarks(
    brief: SceneBrief, left: geo.Vec2, right: geo.Vec2, normal: geo.Vec2,
    actors: Sequence[StageActor], inherited: Sequence[StageLandmark],
) -> list[StageLandmark]:
    """Set pieces: what the location already holds from an earlier scene, then this scene's props and named set dressing.

    A prop small enough to hold lies on the scene's table when there is one, not on the floor between the cast.
    """
    placed: dict[str, StageLandmark] = {item.name: item for item in inherited}
    text = f"{brief.location} {brief.text}"
    wanted: list[tuple[str, str, tuple[float, float, float], str]] = []
    covered: set[str] = set()
    for prop in brief.props:
        name = str(prop or "").strip()
        if not name or any(marker in name for marker in _PLACEHOLDER_PROPS) or name in EMPTY_CAST:
            continue
        match = _set_piece(name)
        if match is None:
            wanted.append((name[:120], "prop", _prop_size(name), ""))
            continue
        covered.add(str(match["name"]))
        wanted.append((name[:120], str(match["kind"]), _piece_size(match), str(match["slot"])))
    for match in prompt_data.load(_SET_PIECES)["pieces"]:
        piece = str(match["name"])
        already = piece in covered or any((found := _set_piece(name)) is not None and found["name"] == piece for name in placed)
        if not already and any(phrase in text for phrase in match["phrases"]):
            wanted.append((piece, str(match["kind"]), _piece_size(match), str(match["slot"])))
    used: dict[str, int] = {}
    free = list(_PROP_SLOTS)

    def place(name: str, kind: str, size: Sequence[float], point: geo.Vec2, elevation: float = 0.0) -> None:
        taken = {item.id for item in placed.values()}
        number = len(placed) + 1
        while f"mark-{number:02d}" in taken:
            number += 1
        placed[name] = StageLandmark(
            id=f"mark-{number:02d}", name=name, kind=kind, position=geo.rounded(point), size=list(size), elevation_m=elevation,
        )

    has_table = any(_is_table(item.name, item.size) for item in placed.values()) or any(
        _is_table(name, size) for name, _kind, size, _slot_name in wanted
    )
    small: list[tuple[str, str, tuple[float, float, float]]] = []
    for name, kind, size, slot in wanted:
        if name in placed or len(placed) >= 24:
            continue
        if has_table and not slot and _rests_on_a_table(kind, size):
            small.append((name, kind, size))
            continue
        # A horse or a car is not parked between the principals and the lens: it takes a slot upstage.
        open_slots = [item for item in free if item in _UPSTAGE_SLOTS] if max(size) > _BIG_PROP_M else free
        chosen = slot or (open_slots[0] if open_slots else "upstage_far")
        if chosen in free:
            free.remove(chosen)
        point = _slot(chosen, left, right, normal, used.get(chosen, 0))
        used[chosen] = used.get(chosen, 0) + 1
        place(name, kind, size, _clear_of_cast(point, size, actors, normal))
    table = next((item for item in placed.values() if _is_table(item.name, item.size)), None)
    for index, (name, kind, size) in enumerate(small):
        if name in placed or len(placed) >= 24:
            continue
        if table is not None:
            place(name, kind, size, _on_table(table, size, index), round(table.elevation_m + table.size[2], 3))
            continue
        chosen = free.pop(0) if free else "upstage_far"
        point = _slot(chosen, left, right, normal, used.get(chosen, 0))
        used[chosen] = used.get(chosen, 0) + 1
        place(name, kind, size, _clear_of_cast(point, size, actors, normal))
    return list(placed.values())


def _riders(landmarks: Sequence[StageLandmark], piece: StageLandmark) -> set[str]:
    """Ids of what lies on top of ``piece``; it goes wherever the piece goes."""
    top = round(piece.elevation_m + piece.size[2], 3)
    return {
        item.id for item in landmarks
        if item.id != piece.id and item.elevation_m == top and geo.inside_piece(item.position, piece)
    }


def _carried(landmarks: Sequence[StageLandmark], ids: Collection[str], shift: geo.Vec2) -> list[StageLandmark]:
    """``landmarks`` with the named pieces moved by ``shift`` on the floor."""
    return [
        item.model_copy(update={"position": geo.rounded(geo.add((item.position[0], item.position[1]), shift))})
        if item.id in ids else item
        for item in landmarks
    ]


def _contact_words(name: str, verbs: Sequence[str], thing: str, text: str, others: Collection[str]) -> list[tuple[str, int, int]]:
    """Each place the clause naming ``name`` says verb + ``thing``: the words between the name and the verb, and where
    ``thing`` stands in ``text``.

    A clause where someone else is named between the person and the verb is that someone's, not theirs.
    """
    if not name or not thing:
        return []
    pattern = (
        re.escape(name) + f"([^{_CLAUSE_STOPS}]{{0,{_NAME_GAP}}}?)(?:" + "|".join(re.escape(verb) for verb in verbs)
        + f")[^{_CLAUSE_STOPS}]{{0,{_OBJECT_GAP}}}?" + re.escape(thing)
    )
    return [
        (match.group(1), match.end() - len(thing), match.end())
        for match in re.finditer(pattern, str(text or ""))
        if not any(other and other in match.group(1) for other in others)
    ]


def _named_after(name: str, verbs: Sequence[str], pieces: Sequence[StageLandmark], text: str, others: Collection[str]):
    """``(piece, words before the verb)`` for each piece the clause says ``name`` acts on.

    Where a name is part of a longer one named at the same place (笔 in 录音笔), the longer one is meant.
    """
    found = {id(piece): _contact_words(name, verbs, piece.name, text, others) for piece in pieces}
    spans = [(piece.name, start, end) for piece in pieces for _, start, end in found[id(piece)]]
    named: list[tuple[StageLandmark, str]] = []
    for piece in pieces:
        own = [
            between for between, start, end in found[id(piece)]
            if not any(other != piece.name and len(other) > len(piece.name) and low <= start and end <= high for other, low, high in spans)
        ]
        if own:
            named.append((piece, own[0]))
    return named


def derive_contacts(
    specs: Sequence[ShotSpec], actors: Sequence[StageActor], landmarks: Sequence[StageLandmark],
    kept: Sequence[StageContact] = (),
    movable: Collection[str] = (),
) -> tuple[list[StageContact], dict[str, str]]:
    """The contacts the shot table implies, after the ``kept`` (a person's own, which win any clash), and the seats
    this run dresses that go under their sitter: ``{seat name: sitter}``.

    - hold: a hold verb after a character's name and before a prop of the stage: 林夏右手握着录音笔.
      The hand is the hand word written before the verb (左手 / 右手 / 双手), else the right.
    - sit: a sit verb before a piece someone can sit on: 周教授坐在扶手椅上. They stay seated in the shots after
      it until a shot gives them another posture, a walk, or another seat. A seat this run dresses (named in
      ``movable``) is set under its first sitter's mark, so the sitter keeps their place and facing; a seat already on
      the set stays put and is only sat on by someone whose mark is within ``seat_reach_m`` of it.
    - rest: a prop small enough for the hand lying on a table's top stays on it, except in the shots it is held.

    A prop only named (林夏看着桌上的录音笔) is in no contact. There is no limit on how many contacts a shot has.
    """
    names = [actor.name for actor in actors if actor.role != "crowd"]
    props = [piece for piece in landmarks if piece.kind == "prop"]
    seats = [piece for piece in landmarks if contact_rules.is_seat(piece)]
    shot_ids = [spec.shot_id for spec in specs]
    taken: dict[str, set[int]] = {}
    holds: dict[tuple[str, str, str], list[int]] = {}
    sits: dict[tuple[str, str], list[int]] = {}

    def claim(target: str, shot_id: int) -> bool:
        if shot_id in taken.setdefault(target, set()):
            return False
        taken[target].add(shot_id)
        return True

    for spec in specs:
        for name in names:
            others = [other for other in names if other != name]
            for piece, between in _named_after(name, _HOLD_VERBS, props, spec.desc, others):
                hand = next((value for word, value in _CONTACT_HANDS if word in between), "")
                if claim(piece.name, spec.shot_id):
                    holds.setdefault((name, piece.name, hand), []).append(spec.shot_id)
    marks = {actor.name: (actor.position[0], actor.position[1]) for actor in actors}
    standing = {piece.name: (piece.position[0], piece.position[1]) for piece in seats}
    owners: dict[str, str] = {}
    for name in names:
        others = [other for other in names if other != name]
        seat: StageLandmark | None = None
        for spec in specs:
            named = _named_after(name, _SIT_VERBS, seats, spec.desc, others)
            if named:
                chosen = named[0][0]
                if chosen.name in movable and chosen.name not in owners:
                    owners[chosen.name] = name
                    standing[chosen.name] = marks[name]
                # Too far to reach: the seat stays where it is and the person stays on their mark.
                seat = chosen if geo.distance(standing[chosen.name], marks[name]) <= _SEAT_REACH_M else None
            elif seat is not None and (
                posture_in(name, spec.desc, "sit") != "sit" or travel_in(name, spec.desc) or enters_in(name, spec.desc)
            ):
                seat = None
            if seat is not None and claim(seat.name, spec.shot_id):
                sits.setdefault((name, seat.name), []).append(spec.shot_id)
    tables = [piece for piece in landmarks if _is_table(piece.name, piece.size)]
    rests: list[tuple[str, str, list[int]]] = []
    for piece in landmarks:
        table = next((table for table in tables if piece.id in _riders(landmarks, table)), None)
        if table is None or not _rests_on_a_table(piece.kind, piece.size):
            continue
        held_in = taken.get(piece.name, set())
        free = [] if not held_in else [shot_id for shot_id in shot_ids if shot_id not in held_in]
        if free or not held_in:
            rests.append((piece.name, table.name, free))

    contacts = list(kept)
    derived: list[StageContact] = []
    for (name, target, hand), shots in holds.items():
        derived.append(StageContact(id="pending", kind="hold", actor=name, target=target, hand=hand, shot_ids=shots))
    for (name, target), shots in sits.items():
        derived.append(StageContact(id="pending", kind="sit", actor=name, target=target, shot_ids=shots))
    for target, support, shots in rests:
        derived.append(StageContact(id="pending", kind="rest", target=target, support=support, shot_ids=shots))
    for person in kept:
        derived = contact_rules.without_shots(derived, person.target, person.shot_ids or shot_ids, shot_ids)
    for contact in derived:
        contacts.append(contact.model_copy(update={"id": contact_rules.next_id(contacts)}))
    sat = {contact.target for contact in contacts if contact.kind == "sit"}
    return contacts, {seat: sitter for seat, sitter in owners.items() if seat in sat}


def _seats_under_sitters(landmarks: Sequence[StageLandmark], actors: Sequence[StageActor], owners: Mapping[str, str]) -> list[StageLandmark]:
    """Each seat this run dressed set on its sitter's mark, turned the way they face; what lies on it goes along."""
    people = {actor.name: actor for actor in actors}
    placed = list(landmarks)
    for seat_name, sitter in owners.items():
        seat = next((item for item in placed if item.name == seat_name), None)
        if seat is None or sitter not in people:
            continue
        actor = people[sitter]
        riders = _riders(placed, seat)
        shift = geo.sub((actor.position[0], actor.position[1]), (seat.position[0], seat.position[1]))
        placed = [
            item.model_copy(update={"position": geo.rounded(actor.position), "yaw_deg": geo.normalize_yaw(actor.yaw_deg)})
            if item.id == seat.id else item
            for item in _carried(placed, riders, shift)
        ]
    return placed


def _kept_contacts(plan: StagePlan | None, specs: Sequence[ShotSpec]) -> list[StageContact]:
    """A person's contacts of an earlier plan, in the shots this one still has; one left with none of its shots is gone."""
    if plan is None:
        return []
    known = {spec.shot_id for spec in specs}
    kept: list[StageContact] = []
    for contact in plan.contacts:
        if contact.source != "manual":
            continue
        shots = [shot_id for shot_id in contact.shot_ids if shot_id in known]
        if contact.shot_ids and not shots:
            continue
        kept.append(contact.model_copy(update={"shot_ids": shots}))
    return kept


def _kept_effects(plan: StagePlan | None, specs: Sequence[ShotSpec], names: Collection[str]) -> list[StageEffect]:
    """A person's effect markers of an earlier plan, in the shots this one still has; a sender no longer cast is dropped from it."""
    if plan is None:
        return []
    known = {spec.shot_id for spec in specs}
    kept: list[StageEffect] = []
    for effect in plan.effects:
        shots = [shot_id for shot_id in effect.shot_ids if shot_id in known]
        if effect.shot_ids and not shots:
            continue
        kept.append(effect.model_copy(update={"shot_ids": shots, "source": effect.source if effect.source in names else ""}))
    return kept


def _clear_the_lenses(
    plan: StagePlan, movable: Collection[str], normal: geo.Vec2 = (0.0, 1.0),
    reshoot: Callable[[StagePlan, Collection[str]], StagePlan] | None = None,
) -> StagePlan:
    """Set dressing this run placed gives way to the lens.

    A piece that hides a shot's subject, or that a camera was solved into, steps upstage (with whatever lies on
    it) until no shot is troubled by it; a piece that cannot get clear within a few steps stays where it was.
    ``reshoot`` solves again the shots that are about a piece that moved (given by name), so an insert of the
    piece follows it instead of framing the floor it left.
    """
    def in_the_way(staged: StagePlan) -> set[str]:
        cameras = {camera.id: camera for camera in staged.cameras}
        return {
            piece.id for shot in staged.shots if shot.camera_id in cameras
            for _name, piece in set_obstructions(staged, shot, cameras[shot.camera_id])
        }

    tried: set[str] = set()
    # One piece at a time: a lens can sit in two pieces at once, and only the first of them shows until it moves.
    while pending := sorted((in_the_way(plan) & set(movable)) - tried):
        tried.add(pending[0])
        piece = next(item for item in plan.landmarks if item.id == pending[0])
        going = {piece.id, *_riders(plan.landmarks, piece)}
        names = {item.name for item in plan.landmarks if item.id in going}
        point = (piece.position[0], piece.position[1])
        for _ in range(_CLEAR_STEPS):
            point = _clear_of_cast(geo.add(point, geo.scale(normal, -_CLEAR_STEP_M)), piece.size, plan.actors, normal)
            shift = geo.sub(point, (piece.position[0], piece.position[1]))
            moved = plan.model_copy(update={"landmarks": _carried(plan.landmarks, going, shift)})
            if reshoot is not None:
                moved = reshoot(moved, names)
            if not in_the_way(moved) & going:
                plan = moved
                break
    return plan


def _supporting_marks(count: int, separation: float) -> list[geo.Vec2]:
    """Upstage marks that close an inverted triangle, then flank it, never hidden behind a principal.

    Seen from the master (which looks at the pair from +Z), screen x is world x, so every slot keeps
    at least a body width of x clear of both principals.
    """
    half = separation / 2
    depth = max(1.6, half + 1.0)
    slots: list[geo.Vec2] = [(0.0, -depth)] if half >= 0.3 else []
    ring = 1
    while len(slots) < count:
        lateral = half + 1.1 * ring
        slots.extend([(-lateral, -depth * (0.55 if ring == 1 else 1.0)), (lateral, -depth * (0.55 if ring == 1 else 1.0))])
        if ring > 1:
            slots.append((0.0, -depth * ring))
        ring += 1
    return slots[:count]


def _audience(names: Sequence[str], focus: geo.Vec2) -> tuple[list[StageCrowd], list[StageActor]]:
    """A hall's audience for the crowd(s) called ``names``: two seated blocks either side of a centre aisle, facing ``focus``.

    The blocks sit on the camera side (+Z) of the stage, so the aisle between them is also the lane a wide
    lens looks down, and the audience is seen from behind unless a shot turns round to it. Each cast name
    goes to one of the people nearest the stage: a shot that names the crowd is a shot of that person.
    """
    rows, columns = int(_words("venue", "rows")), int(_words("venue", "columns"))
    spacing, aisle, front = float(_words("venue", "spacing_m")), float(_words("venue", "aisle_m")), float(_words("venue", "front_m"))
    arrays: list[StageCrowd] = []
    people: list[StageActor] = []
    for index, (label, side) in enumerate(((str(_words("venue", "left")), -1.0), (str(_words("venue", "right")), 1.0))):
        crowd = StageCrowd(
            id=f"crowd-{index + 1:02d}", label=label.format(name=names[0])[:40], rows=rows, columns=columns, spacing=spacing,
            center=geo.rounded((focus[0] + side * (aisle / 2 + (columns - 1) * spacing / 2), focus[1] + front + (rows - 1) * spacing / 2)),
            # Turned to the stage; every member then looks at the 主位 itself, keeping the small turn of their own.
            yaw_deg=180.0, seed=index * rows * columns,
        )
        arrays.append(crowd)
        for member in crowd_arrays.members(crowd):
            spot = (member.position[0], member.position[1])
            people.append(member.model_copy(update={
                "yaw_deg": geo.normalize_yaw(geo.yaw_toward(spot, focus) + member.yaw_deg - crowd.yaw_deg), "posture": "sit",
            }))
    nearest = sorted(range(len(people)), key=lambda index: geo.distance((people[index].position[0], people[index].position[1]), focus))
    for name, index in zip(names, nearest):
        people[index] = people[index].model_copy(update={"name": name})
    return arrays, people


def _stage_actors(
    brief: SceneBrief, principals: Sequence[str], side_memory: Mapping[str, str],
) -> tuple[list[StageActor], StageAxis, str, list[StageCrowd]]:
    cast = [name for name in dict.fromkeys(name.strip() for name in brief.characters) if name not in EMPTY_CAST]
    separation, mood = _separation(brief.text)
    normal: geo.Vec2 = (0.0, 1.0)
    actors: list[StageActor] = []
    axis = StageAxis()
    formation = _phrase("empty")
    arrays: list[StageCrowd] = []
    crowds = [name for name in cast if is_crowd(name)]
    # A hall: the crowd is an audience in rows that watches whoever stands at the front.
    venue = bool(crowds and principals) and any(str(word) in f"{brief.location}{brief.text}" for word in _words("venue", "words"))

    supporting = [name for name in cast if name not in principals and not is_crowd(name)]
    # How the whole group sits, when the words say so: only a pair with company has a ring or rows to close.
    group = _group_shape(brief.text) if supporting and len(principals) >= 2 else ""
    seated = group == "rows" or (group == "ring" and any(str(word) in brief.text for word in _words("group_shapes", "ring", "seated")))
    sitting = "sit" if seated else "stand"
    spacing = float(_words("group_shapes", "ring", "spacing_m")) if group == "ring" else float(_words("group_shapes", "rows", "spacing_m"))

    if len(principals) >= 2:
        first, second = principals[0], principals[1]
        # A promise made in an earlier scene outranks the default "first named stands screen left".
        if side_memory.get(first) == "right" or (side_memory.get(second) == "left" and side_memory.get(first) != "left"):
            first, second = second, first
        company = [name for name in cast if name not in (first, second)]
        shaped = None if group else _pair_shape(first, second, company, brief.text)
        heading: float | None = None   # the yaw both share; None when each is turned by where the other stands
        if group == "ring":
            # Neighbours on the half circle stand ``spacing`` apart; the pair closes its two ends.
            separation = spacing / math.sin(math.pi / (2 * (len(supporting) + 1)))
        elif group == "rows":
            separation, heading = spacing, 0.0
        elif shaped is not None:
            mood = shaped[0].label
            separation = shaped[0].apart_m if shaped[0].apart_m is not None else math.hypot(shaped[0].back_m, shaped[0].side_m)
        elif _side_by_side((first, second), company, brief.text):
            separation, heading = _SIDE_BY_SIDE_M, 0.0
        left_mark, right_mark = geo.pair_positions((0.0, 0.0), (1.0, 0.0), separation)
        marks = {first: left_mark, second: right_mark}
        turned_away = shaped is not None and shaped[0].apart_m is not None
        if shaped is not None and not turned_away:
            front = shaped[1]
            behind = second if front == first else first
            heading = _shared_heading(marks[front], marks[behind], shaped[0].back_m, shaped[0].side_m, normal)
        for name, mark, other, side in ((first, left_mark, right_mark, "left"), (second, right_mark, left_mark, "right")):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=heading if heading is not None else geo.yaw_toward(other, mark) if turned_away else geo.yaw_toward(mark, other),
                posture=_posture(name, brief.text, sitting), role="principal", screen_side=side,
            ))
        axis = StageAxis(
            kind="dialogue", from_name=first, to_name=second,
            start=geo.rounded(left_mark), end=geo.rounded(right_mark), camera_side=1,
        )
        if shaped is not None and not turned_away:
            formation = _phrase(
                "pair_ahead", relation=shaped[0].name(), mood=mood, front=front, behind=behind,
                back=shaped[0].back_m, side=shaped[0].side_m,
            )
        elif shaped is not None:
            formation = _phrase("pair", relation=shaped[0].name(), mood=mood, separation=separation)
        else:
            # The same words the facing check reads (stage_brief.json pair_relations), so the two cannot drift apart.
            relation = pair_relation("side_by_side" if heading is not None else "facing")
            formation = _phrase("pair", relation=relation, mood=mood, separation=separation)
    elif len(principals) == 1:
        name = principals[0]
        actors.append(StageActor(
            # Alone on a set the lead plays across the frame; alone before an audience, out to it.
            id=_slug(1), name=name, position=[0.0, 0.0], yaw_deg=0.0 if venue else 90.0,
            posture=_posture(name, brief.text), role="principal",
            screen_side="center" if venue else side_memory.get(name) if side_memory.get(name) in {"left", "right"} else "left",
        ))
        formation = _phrase("venue_single" if venue else "single")

    centre = (0.0, 0.0)
    joiner = str(_words("formations", "name_joiner"))
    if group == "rows":
        depth = float(_words("group_shapes", "rows", "depth_m"))
        front_marks, back_marks = _row_marks(len(supporting), spacing, depth)
        front_row = supporting[:len(front_marks)]
        for name, mark in zip(supporting, [*front_marks, *back_marks]):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark), yaw_deg=0.0,
                posture=_posture(name, brief.text, "sit" if name in front_row else "stand"), role="supporting",
            ))
        # Read left to right as the camera sees the front row.
        seats = sorted([first, second, *front_row], key=lambda name: next(actor.position[0] for actor in actors if actor.name == name))
        formation += _phrase(
            "rows", front=joiner.join(seats), back=joiner.join(supporting[len(front_marks):]), spacing=spacing, depth=depth,
        )
    elif supporting:
        marks_upstage = _ring_marks(len(supporting), separation / 2) if group == "ring" else _supporting_marks(len(supporting), separation)
        for name, mark in zip(supporting, marks_upstage):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=geo.yaw_toward(mark, centre), posture=_posture(name, brief.text, sitting), role="supporting",
            ))
        if group == "ring":
            formation += _phrase("ring", names=joiner.join(supporting), spacing=spacing)
        else:
            shape = _words("formations", "supporting_shapes", "one" if len(supporting) == 1 else "many")
            formation += _phrase("supporting", names=joiner.join(supporting), shape=shape)
    if venue:
        arrays, audience = _audience(crowds, centre)
        formation += _phrase(
            "audience", names=joiner.join(crowds), rows=arrays[0].rows, columns=arrays[0].columns, spacing=arrays[0].spacing,
        )
    elif crowds:
        depth = max(3.4, separation / 2 + 2.8)
        # Off the centre line, so a crowd is never hidden exactly behind whoever closes the triangle.
        anchor = geo.add(geo.scale(normal, -depth), (1.5 if supporting else 0.0, 0.0))
        marks = geo.line_positions(len(crowds), anchor, (1.0, 0.0), 1.6)
        for name, mark in zip(crowds, marks):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=geo.yaw_toward(mark, centre), role="crowd", note=str(_words("crowd_note")),
            ))
        formation += _phrase("crowd", names=joiner.join(crowds))
    if len(actors) > 1:
        apart = geo.separate([(actor.position[0], actor.position[1]) for actor in actors], 0.6)
        actors = [actor.model_copy(update={"position": geo.rounded(mark)}) for actor, mark in zip(actors, apart)]
    actors = [
        actor.model_copy(update={"height_m": brief.heights[actor.name]}) if actor.name in brief.heights else actor
        for actor in actors
    ]
    if venue:
        # Seated after the cast has been spread: the rows keep their own spacing.
        actors.extend(audience)
    return actors, axis, formation[:200], arrays


def _shot_overrides(plan: StagePlan, specs: Sequence[ShotSpec]) -> dict[int, list[ActorOverride]]:
    """Where the table puts someone off their mark for a shot.

    - A character the table shows arriving is off the set until that shot, and starts it
      2.2 m behind their mark on the side away from their partner.
    - A posture a shot gives a character (kneels, falls, sits) holds in the shots after it
      until another shot stands them up again.
    """
    overrides: dict[int, dict[str, ActorOverride]] = {}
    moved: set[str] = set()
    first_seen: dict[str, int] = {}
    for index, spec in enumerate(specs):
        for name in spec.subjects:
            first_seen.setdefault(name, index)
    for name, index in first_seen.items():
        actor, spec = plan.actor(name), specs[index]
        if actor is None or actor.role == "crowd":
            continue
        if not enters_in(name, spec.desc):
            continue
        mark = (actor.position[0], actor.position[1])
        partner = plan.actor(plan.axis.to_name if name == plan.axis.from_name else plan.axis.from_name)
        away = (
            geo.unit(geo.sub(mark, (partner.position[0], partner.position[1])), (1.0, 0.0))
            if partner is not None and partner.name != name else (1.0, 0.0)
        )
        start = geo.add(mark, geo.scale(away, 2.2))
        for earlier in specs[:index]:
            overrides.setdefault(earlier.shot_id, {})[name] = ActorOverride(
                name=name, offstage=True, reason=str(_words("reasons", "offstage")),
            )
        overrides.setdefault(spec.shot_id, {})[name] = ActorOverride(
            name=name, position=geo.rounded(start), yaw_deg=geo.yaw_toward(start, mark, actor.yaw_deg),
            posture="walk", reason=ENTRANCE_REASON,
        )
        moved.add(name)

    # Someone who walks up to / backs away from their partner inside a shot starts it off the mark
    # and ends it on the mark, so the move is on the stage and the next shot still finds them there.
    # One mark holds one move: whoever already entered or moved in this scene is not staged again
    # (a second start off the mark would jump them across the floor at the cut into it).
    retreating = {actor.name for spec in specs for actor in plan.actors if travel_in(actor.name, spec.desc) == "retreat"}
    for spec_index, spec in enumerate(specs):
        for actor in plan.actors:
            if actor.role == "crowd" or actor.name in moved or actor.name in overrides.get(spec.shot_id, {}):
                continue
            travel = travel_in(actor.name, spec.desc)
            if not travel:
                continue
            mark = (actor.position[0], actor.position[1])
            partner = plan.actor(plan.axis.to_name if actor.name == plan.axis.from_name else plan.axis.from_name)
            toward = (
                geo.unit(geo.sub((partner.position[0], partner.position[1]), mark), geo.forward_of(actor.yaw_deg))
                if partner is not None and partner.name != actor.name else geo.forward_of(actor.yaw_deg)
            )
            retreat = travel == "retreat"
            step = 1.2
            if retreat:
                # Backing off starts nearer the partner, never past them: of two people who both back
                # off in the scene, each takes half of the room left above arm's length.
                paired = partner is not None and partner.name != actor.name
                gap = geo.distance(mark, (partner.position[0], partner.position[1])) if paired else 2.0
                step = min(0.6, (gap - MIN_ACTOR_SPACING_M - 0.1) / (2 if paired and partner.name in retreating else 1))
                if step < 0.15:
                    continue
            start = geo.add(mark, geo.scale(toward, step if retreat else -step))
            walk = ActorOverride(
                name=actor.name, position=geo.rounded(start),
                yaw_deg=actor.yaw_deg if retreat else geo.yaw_toward(start, mark, actor.yaw_deg),
                posture="stand" if retreat else "walk",
                reason=RETREAT_REASON if retreat else APPROACH_REASON,
            )
            overrides.setdefault(spec.shot_id, {})[actor.name] = walk
            moved.add(actor.name)
            # They have been standing where the walk starts: the shots before it hold them there.
            for earlier in specs[:spec_index]:
                overrides.setdefault(earlier.shot_id, {})[actor.name] = ActorOverride(
                    name=actor.name, position=walk.position, yaw_deg=actor.yaw_deg, hold=True,
                    reason=_HOLD_REASONS[walk.reason],
                )

    held: dict[str, str] = {actor.name: actor.posture for actor in plan.actors}
    for spec in specs:
        for actor in plan.actors:
            held[actor.name] = _posture(actor.name, spec.desc, held[actor.name])
            if held[actor.name] == actor.posture:
                continue
            existing = overrides.setdefault(spec.shot_id, {}).get(actor.name)
            if existing is None:
                overrides[spec.shot_id][actor.name] = ActorOverride(name=actor.name, posture=held[actor.name])
            elif not existing.offstage and (existing.position is None or existing.hold):
                overrides[spec.shot_id][actor.name] = existing.model_copy(update={"posture": held[actor.name]})
    return {shot_id: list(changes.values()) for shot_id, changes in overrides.items() if changes}


def fit_moves(plan: StagePlan) -> StagePlan:
    """Every moving camera ends with the people it frames still in frame."""
    cameras = {camera.id: camera for camera in plan.cameras}
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is not None and camera.move.kind != "static":
            cameras[camera.id] = fit_move(camera, plan.actors_in(shot), plan.actors_in(shot, at_end=True), plan.axis)
    return plan.model_copy(update={"cameras": [cameras[camera.id] for camera in plan.cameras]})


def template_shots(principals: Sequence[str], cast: Sequence[str]) -> list[ShotSpec]:
    """Standard coverage for a scene that has no storyboard table yet."""
    people = [name for name in cast if name not in EMPTY_CAST]
    if not people:
        return [ShotSpec(shot_id=1, size="全景", desc=str(_words("empty_scene_shot")))]
    if len(principals) < 2:
        lead = principals[0] if principals else people[0]
        return [
            ShotSpec(shot_id=1, subjects=[lead], size="全景"),
            ShotSpec(shot_id=2, subjects=[lead], size="中景"),
            ShotSpec(shot_id=3, subjects=[lead], size="特写"),
        ]
    first, second = principals[0], principals[1]
    shots = [
        ShotSpec(shot_id=1, subjects=list(people), size="全景"),
        ShotSpec(shot_id=2, subjects=[first, second], size="中景"),
        ShotSpec(shot_id=3, subjects=[first], speaker=first, size="近景", angle="过肩"),
        ShotSpec(shot_id=4, subjects=[second], speaker=second, size="近景", angle="过肩"),
        ShotSpec(shot_id=5, subjects=[first], speaker=first, size="特写"),
        ShotSpec(shot_id=6, subjects=[second], speaker=second, size="特写"),
    ]
    others = [name for name in people if name not in principals and not is_crowd(name)]
    shots.extend(
        ShotSpec(shot_id=len(shots) + index + 1, subjects=[name], speaker=first, size="近景")
        for index, name in enumerate(others[:3])
    )
    return shots


def sync_axis(plan: StagePlan) -> StagePlan:
    """Keep the axis on the two things it joins when either of them has moved; drop it when one is gone."""
    if plan.axis.kind == "none":
        return plan
    points: dict[str, list[float]] = {actor.name: list(actor.position) for actor in plan.actors}
    points.update({item.name: list(item.position) for item in plan.landmarks if item.name not in points})
    start, end = points.get(plan.axis.from_name), points.get(plan.axis.to_name)
    if start is None or end is None:
        return plan.model_copy(update={"axis": StageAxis()})
    return plan.model_copy(update={"axis": plan.axis.model_copy(update={"start": start, "end": end})})


def refresh(plan: StagePlan) -> StagePlan:
    """Recompute everything a plan *derives* (screen states, axis sides, prose, checks) from what it *states*."""
    plan = sync_axis(plan)
    cameras = {camera.id: camera for camera in plan.cameras}
    principals = [name for name in (plan.axis.from_name, plan.axis.to_name) if plan.actor(name)]
    shots: list[StageShot] = []
    for shot in plan.shots:
        camera = cameras[shot.camera_id]
        staged = plan.actors_in(shot)
        measured = shot.model_copy(update={
            "subjects": list(camera.subjects),
            "function": camera.function,
            "screen": screen_states(staged, camera),
            "axis_side": (
                axis_rules.camera_side(plan.axis, camera, end=camera.move.kind in {"orbit", "track", "follow"})
                if axis_rules.has_axis(plan.axis) else 0
            ),
            "crossing": axis_rules.crossing_kind(plan.axis, camera, principals) if axis_rules.has_axis(plan.axis) else "none",
        })
        shots.append(measured)
    staged_plan = plan.model_copy(update={"shots": shots})
    worded = [
        shot.model_copy(update={"text": shot_text(staged_plan, shot, cameras[shot.camera_id])})
        for shot in staged_plan.shots
    ]
    staged_plan = staged_plan.model_copy(update={"shots": worded})
    return staged_plan.model_copy(update={
        "checks": check_plan(staged_plan),
        "scene_bible": scene_bible(staged_plan),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def build_plan(
    brief: SceneBrief,
    *,
    side_memory: Mapping[str, str] | None = None,
    location_landmarks: Sequence[StageLandmark] = (),
    blocking_from: StagePlan | None = None,
) -> StagePlan:
    """The stage of ``brief``.

    ``blocking_from`` is an earlier plan for the same cast and set (a person's edit, or the
    blocking the storyboard table was written against): its marks, set pieces and axis are
    kept and only the cameras and per-shot changes are solved again for the new shots.
    """
    cast = [name for name in dict.fromkeys(name.strip() for name in brief.characters) if name not in EMPTY_CAST]
    specs = list(brief.shots)
    coverage = "storyboard"
    principals = _principals(cast, specs)
    if not specs:
        specs, coverage = template_shots(principals, cast), "template"

    kept_crowds = list(blocking_from.crowds) if blocking_from is not None else []
    # Set pieces this run places itself; what the location or an earlier plan already holds stays put.
    dressed: set[str] = set()
    backdrop = blocking_from.backdrop if blocking_from is not None else StageBackdrop()
    if blocking_from is not None:
        actors, axis, formation = list(blocking_from.actors), blocking_from.axis, blocking_from.formation
        landmarks = list(blocking_from.landmarks)
    else:
        actors, axis, formation, kept_crowds = _stage_actors(brief, principals, side_memory or {})
        left = (axis.start[0], axis.start[1]) if axis_rules.has_axis(axis) else (-0.75, 0.0)
        right = (axis.end[0], axis.end[1]) if axis_rules.has_axis(axis) else (0.75, 0.0)
        landmarks = _landmarks(brief, left, right, (0.0, 1.0), actors, location_landmarks)
        dressed = {item.id for item in landmarks} - {item.id for item in location_landmarks}
        # A lone character plays to the first thing on the set: that gaze is the scene's axis.
        # Before an audience the lead plays to the hall instead, and keeps facing it.
        if len(principals) == 1 and landmarks and actors and not kept_crowds:
            lead, focus = actors[0], landmarks[0]
            point = (focus.position[0], focus.position[1])
            if geo.distance((lead.position[0], lead.position[1]), point) > 0.3:
                # Keep the character screen left of what they look at.
                if point[0] < lead.position[0]:
                    point = (lead.position[0] + abs(point[0] - lead.position[0]) + 0.8, point[1])
                    # What lies on the piece crosses the stage with it.
                    shift = geo.sub(point, (focus.position[0], focus.position[1]))
                    landmarks = _carried(landmarks, {focus.id, *_riders(landmarks, focus)}, shift)
                actors[0] = lead.model_copy(update={"yaw_deg": geo.yaw_toward((lead.position[0], lead.position[1]), point)})
                axis = StageAxis(
                    kind="gaze", from_name=lead.name, to_name=focus.name,
                    start=list(lead.position), end=geo.rounded(point), camera_side=1,
                )

    centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in actors if actor.role != "crowd"])
    known = {actor.name for actor in actors}
    # Who holds what and sits where, from the shot table; a person's own contacts from the plan re-planned are kept.
    kept = contact_rules.resolvable(
        _kept_contacts(blocking_from, specs), (actor.name for actor in actors), (item.name for item in landmarks),
    )
    dressed_names = {item.name for item in landmarks if item.id in dressed}
    contacts, owners = derive_contacts(specs, actors, landmarks, kept, dressed_names)
    if owners:
        # A seat dressed for someone to sit on is set under them, not in a prop slot across the room; it is theirs,
        # so it no longer steps aside for the lens or the cast.
        landmarks = _seats_under_sitters(landmarks, actors, owners)
        dressed = dressed - {item.id for item in landmarks if item.name in owners}
    cameras: list[StageCamera] = []
    shots: list[StageShot] = []
    pair = [name for name in (axis.from_name, axis.to_name) if name in known] or principals

    def solve(
        index: int, spec: ShotSpec, staged: Sequence[StageActor], avoid: geo.Vec2 | None = None,
        pieces: Sequence[StageLandmark] | None = None,
    ) -> StageCamera:
        # A held prop is framed where the hand is.
        placed = contact_rules.place_landmarks(landmarks, staged, contacts, spec.shot_id) if pieces is None else pieces
        return solve_camera(
            spec, staged, axis, aspect_ratio=brief.aspect_ratio, principals=pair,
            landmarks=placed, stage_center=centre, first_shot=index == 0, avoid_bearing=avoid,
        )

    def reshoot(staged: StagePlan, names: Collection[str]) -> StagePlan:
        """A shot of nobody that names a piece that moved is solved again where the piece now is."""
        again = {
            shot.camera_id: solve(index, spec, staged.actors_in(shot), pieces=staged.landmarks_in(shot))
            for index, (spec, shot) in enumerate(zip(specs, staged.shots))
            if not spec.subjects and any(name and name in spec.desc for name in names)
        }
        return staged.model_copy(update={"cameras": [again.get(camera.id, camera) for camera in staged.cameras]}) if again else staged

    for index, spec in enumerate(specs):
        spec.subjects = [name for name in dict.fromkeys(spec.subjects) if name in known]
        cameras.append(solve(index, spec, contact_rules.seat_actors(actors, landmarks, contacts, spec.shot_id)))
        shots.append(StageShot(
            shot_id=spec.shot_id, camera_id=cameras[-1].id, subjects=list(spec.subjects),
            speaker=spec.speaker[:120], action=spec.desc[:1000],
        ))

    plan = StagePlan(
        scene_id=brief.scene_id, location=brief.location[:500], location_key=location_key(brief.location),
        aspect_ratio=brief.aspect_ratio, formation=formation, coverage=coverage,
        # A crowd array is carried with its members: an actor that names a crowd the plan does not
        # hold is not a valid stage, so dropping the record would refuse the re-plan outright.
        actors=actors, crowds=kept_crowds, landmarks=landmarks, axis=axis, backdrop=backdrop, contacts=contacts,
        effects=_kept_effects(blocking_from, specs, known),
        planner=blocking_from.planner if blocking_from is not None else "rules",
        planner_note=blocking_from.planner_note if blocking_from is not None else "",
        cameras=cameras, shots=shots,
        source=blocking_from.source if blocking_from is not None else "auto",
        revision=(blocking_from.revision + 1) if blocking_from is not None else 1,
        cast_fingerprint=cast_fingerprint(cast, brief.location),
    )
    changes = _shot_overrides(plan, specs)
    if changes:
        plan = plan.model_copy(update={"shots": [
            shot.model_copy(update={"overrides": changes.get(shot.shot_id, [])}) for shot in plan.shots
        ]})
        # Someone off their mark is shot where they actually are, and a moving camera goes with them.
        resolved = []
        for index, (spec, camera, shot) in enumerate(zip(specs, plan.cameras, plan.shots)):
            if shot.overrides:
                camera = carry_camera(solve(index, spec, plan.actors_in(shot)), shot, plan)
            resolved.append(camera)
        plan = plan.model_copy(update={"cameras": resolved})

    # The 30-degree rule: a shot that would repeat the previous one's people, size and direction
    # is taken from somewhere else on the same side instead, so the cut does not read as a jump.
    varied = list(plan.cameras)
    for index in range(1, len(varied)):
        shot = plan.shots[index]
        varied[index] = vary_angle(
            varied[index - 1], varied[index],
            lambda avoid, index=index, shot=shot: carry_camera(solve(index, specs[index], plan.actors_in(shot), avoid), shot, plan),
        )
    plan = plan.model_copy(update={"cameras": varied})
    # 站位和机位定了，再按画面文字排每个人的姿势与动作轨道；人在导演台上排过的镜照旧。
    # 机位都落定之后，本次自己摆的陈设给镜头让路。
    return refresh(_clear_the_lenses(fit_moves(performance.stage(plan, specs, keep=blocking_from)), dressed, reshoot=reshoot))


__all__ = [
    "CROWD_MARKERS",
    "EMPTY_CAST",
    "SceneBrief",
    "build_plan",
    "cast_fingerprint",
    "derive_contacts",
    "fit_moves",
    "is_crowd",
    "location_key",
    "refresh",
    "speaker_of",
    "template_shots",
]
