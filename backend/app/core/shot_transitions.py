# -*- coding: utf-8 -*-
"""How one shot hands over to the next: the cut plan of a scene.

A storyboard is nine pictures until something says how picture N becomes picture
N+1. This module reads every adjacent pair of shots on six relations and turns
them into a cut plan (what kind of cut, what carries across it, what each side
must do at the cut point) and a set of checks:

1. logic     — time, space and cause run forward; a jump in time gets a transition,
               nobody teleports, an effect does not precede its cause.
2. picture   — shot sizes step rather than leap; the 30-degree rule; a look is
               answered by what is looked at and then by the reaction; an action
               is cut in the middle and picked up in the middle.
               (The 180-degree rule is measured by the spatial stage.)
3. motion    — moving shots join moving shots in the same direction; a move settles
               before it meets a static shot.
4. matching  — a shared shape can carry a change of scene; light and colour do not
               flip across a plain cut.
5. rhythm    — durations breathe; fast material is not held long; emotions do not
               collide without a buffer.
6. device    — hard cut inside a scene, dissolve for time passing and memory, fade for
               chapters and big jumps, match cut where the pictures rhyme.

Everything is deterministic and works from the storyboard table alone; with the
scene's spatial plan it also measures lens directions and where people stand.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import MIN_ANGLE_CHANGE_DEG, bearing_change_deg, move_kind, repeats_the_angle, size_rank
from app.core.spatial_stage.models import StageCamera, StagePlan
from app.core.transition_catalog import transition_label
from app.core.writer_dashboard import parse_duration_seconds

# 「cut」只为读旧数据保留：规划器不再选硬切，同场景用匹配衔接，换场景用推拉(遮挡 / 镜头运动)带入。
CutKind = Literal["cut", "dissolve", "fade", "match_cut", "push_pull"]
Technique = Literal[
    "opening", "plain", "shot_reverse", "action_match", "eyeline_match", "reaction",
    "graphic_match", "time_passage", "flashback", "chapter", "scene_change",
    "action_rhyme", "occlusion", "object_carry",
]
# 声音和画面错开切：J 是下一镜的声音先到，L 是上一镜的声音留下。成片合成时才做，不写进视频提示词。
SoundJoin = Literal["", "j_cut", "l_cut"]
MotionJoin = Literal["static_to_static", "moving_to_moving", "moving_to_static", "static_to_moving"]

# Every sentence, name and word table below is read from app/data/prompt/shot_transitions.json;
# the ids (devices, techniques, motion joins, emotions, tones) stay code values.
_WORDING = "shot_transitions"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the cut plan's wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A word of the cut plan's wording table (a separator, a default name)."""
    return prompt_data.text(_WORDING, key)


def _table(key: str) -> Any:
    return prompt_data.value(_WORDING, key)


def _pattern(key: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(str(_table("patterns")[key]), flags)


# A leap of this many size steps (全景 → 特写 is 5) needs a reason.
MAX_SIZE_STEP = 4
MAX_STATE_JUMP_M = 0.8
_CUT_SECONDS: dict[str, float] = {"cut": 0.0, "match_cut": 0.0, "dissolve": 0.5, "fade": 0.8, "push_pull": 0.5}
# What the compositor calls each device.
COMPOSITOR_TRANSITIONS: dict[str, str] = {
    # 旧数据里的硬切也按短交叉过渡合成，成片里不出现生硬的跳切。
    "cut": "crossfade", "match_cut": "match_cut", "dissolve": "crossfade", "fade": "dip_to_black", "push_pull": "crossfade",
}
_TECHNIQUES: tuple[str, ...] = (
    "opening", "plain", "shot_reverse", "action_match", "eyeline_match", "reaction", "graphic_match",
    "time_passage", "flashback", "chapter", "scene_change", "action_rhyme", "occlusion", "object_carry",
)
_TECHNIQUE_ZH: dict[str, str] = {technique: str(_table("technique_names")[technique]) for technique in _TECHNIQUES}
# 这种接法回看成片时要核对什么。
_WATCH: dict[str, str] = {technique: str(_table("watch")[technique]) for technique in _TECHNIQUES}
_EMPTY_CAST = frozenset(prompt_data.words(_WORDING, "empty_cast"))

_BIG_TIME_JUMP = _pattern("big_time_jump")
_TIME_PASSAGE = _pattern("time_passage")
_FLASHBACK = _pattern("flashback")
_DAY = _pattern("day")
_DUSK = _pattern("dusk")
_NIGHT = _pattern("night")
_LOOK = _pattern("look")
_POV = _pattern("pov", re.IGNORECASE)
_EXIT = _pattern("exit")
# 分镜明说了前景遮过镜头才算遮挡转场：「手撑着墙」不算。group(1) 是遮挡物。
_OCCLUSION = _pattern("occlusion")
# 能跨场景认出来的小物件：同一个物件换了环境，线索就接上了。
_TOKENS = prompt_data.words(_WORDING, "tokens")
_DIRECTION = _pattern("direction")
_TURNED = _pattern("turned")
_EXIT_SIDE = _pattern("exit_side")
_ENTRY_SIDE = _pattern("entry_side")
_DONE = _pattern("done")
_PICKUP = _pattern("pickup")
_FAST_MOVE = _pattern("fast_move")
_SLOW_MOVE = _pattern("slow_move")
_VIOLENT_MOVE = _pattern("violent_move", re.IGNORECASE)
_ENERGY_MOTIVE = _pattern("energy_motive")
# 两镜的描述相似到这个程度，又没有新动作和新台词，切过去就只是换了个机位。
SAME_INFO_RATIO = 0.82
# 同一人物在画面里挪了这么多（画面宽为 100）观众的眼睛就得跨屏重新找人。
MAX_ATTENTION_JUMP = 45.0
STATIC_RUN = 4
# One action, cut in two: a family names the same movement at different moments (first family that hits wins).
_ACTION_FAMILIES: tuple[tuple[str, ...], ...] = tuple(tuple(str(word) for word in family) for family in _table("action_families"))
# (cause words, effect words): the effect on screen before anyone has done the cause.
_CAUSALITY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = tuple(
    (tuple(str(word) for word in causes), tuple(str(word) for word in effects)) for causes, effects in _table("causality")
)
_SHAPES: tuple[tuple[str, tuple[str, ...]], ...] = tuple((str(label), tuple(str(word) for word in words)) for label, words in _table("shapes"))
_WARM = prompt_data.words(_WORDING, "warm_words")
_COOL = prompt_data.words(_WORDING, "cool_words")
# First emotion that hits wins, in this order.
_EMOTION_ORDER: tuple[str, ...] = ("grief", "fear", "rage", "comic", "tender")
_EMOTIONS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (label, tuple(str(word) for word in _table("emotion_words")[label])) for label in _EMOTION_ORDER
)
_COLLISIONS = frozenset({("grief", "comic"), ("comic", "grief"), ("fear", "comic"), ("comic", "fear")})
_FAST_PURPOSES = frozenset({"tension", "shock"})
_BURST = prompt_data.words(_WORDING, "burst_words")
# 人在跑(不是机位在动)：下一镜人停住时，这一镜的尾帧先画减速、快到位。
_RUN = prompt_data.words(_WORDING, "run_words")
_OPPOSITE_MOVES = frozenset({("push", "pull"), ("pull", "push"), ("rise", "fall"), ("fall", "rise")})
_TONE_ZH = {tone: str(_table("tone_names")[tone]) for tone in ("warm", "cool")}
_PAN_LEFT = tuple(str(word) for word in _table("pan_side_words")["left"])
_PAN_RIGHT = tuple(str(word) for word in _table("pan_side_words")["right"])
_HEADING_LEFT = str(_table("heading_words")["left"])
_HEADING_RIGHT = str(_table("heading_words")["right"])
_JOINER = _word("joiner")
_CLIP_TRIM = _word("clip_trim")
_CLIP_MARK = _word("clip_mark")


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(_CLIP_TRIM) + _CLIP_MARK


class TransitionCheck(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{3,80}$")
    passed: bool
    severity: Literal["error", "warning"] = "warning"
    detail: str = Field(max_length=4000)
    shot_ids: list[int] = Field(default_factory=list, max_length=200)


class CutPlan(BaseModel):
    """The cut between two adjacent shots. ``from_shot`` is 0 when nothing precedes the scene."""

    model_config = ConfigDict(extra="forbid")

    from_shot: int = Field(ge=0, le=10_000)
    to_shot: int = Field(ge=1, le=10_000)
    kind: CutKind = "cut"
    technique: Technique = "plain"
    label: str = Field(max_length=60)
    duration_seconds: float = Field(ge=0, le=5)
    motion_join: MotionJoin = "static_to_static"
    size_step: int = Field(0, ge=-8, le=8)
    lens_change_deg: float | None = Field(None, ge=0, le=180)
    carries: str = Field("", max_length=300)
    reasons: list[str] = Field(default_factory=list, max_length=12)
    edit_out: str = Field("", max_length=500)
    edit_in: str = Field("", max_length=500)
    sound_join: SoundJoin = ""
    sound_note: str = Field("", max_length=200)
    # 上一镜人在跑、这一镜人停住：上一镜的尾帧画减速收步，这一镜从停稳接起。
    arrival: bool = False


class TransitionPlan(BaseModel):
    cuts: list[CutPlan] = Field(default_factory=list, max_length=500)
    checks: list[TransitionCheck] = Field(default_factory=list, max_length=20)

    def cut_into(self, shot_id: int) -> CutPlan | None:
        return next((cut for cut in self.cuts if cut.to_shot == int(shot_id)), None)

    def cut_out_of(self, shot_id: int) -> CutPlan | None:
        return next((cut for cut in self.cuts if cut.from_shot == int(shot_id)), None)

    @property
    def summary(self) -> str:
        return _clip(_JOINER.join(
            _says("summary_cut", from_shot=cut.from_shot or _word("scene_entry"), to_shot=cut.to_shot, label=cut.label)
            + (_says("summary_carries", carries=cut.carries) if cut.carries else "")
            for cut in self.cuts
        ), 4000)


@dataclass
class _Shot:
    shot_id: int
    scene_id: str
    location: str
    size: str
    rank: int
    move: str
    move_text: str
    desc: str
    purpose: str
    seconds: int
    subjects: list[str]
    camera: StageCamera | None = None
    dialogue: str = ""

    @property
    def moving(self) -> bool:
        return self.move != "static"

    @property
    def text(self) -> str:
        return f"{self.location} {self.desc}"

    @property
    def is_pov(self) -> bool:
        return bool(_POV.search(f"{self.size} {self.desc}"))

    @property
    def is_insert(self) -> bool:
        return not self.subjects or (self.camera is not None and self.camera.function in {"detail", "empty"})


def _view(raw: Mapping[str, Any], index: int, plan: StagePlan | None) -> _Shot:
    shot_id = int(raw.get("shot_id") or index)
    names = raw.get("characters") if isinstance(raw.get("characters"), list) else []
    camera = None
    if plan is not None:
        staged = plan.shot(shot_id)
        camera = plan.camera(staged.camera_id) if staged is not None else None
    size = str(raw.get("size") or _word("default_size"))
    motion = str(raw.get("motion") or "")
    return _Shot(
        shot_id=shot_id, scene_id=str(raw.get("scene_id") or ""), location=str(raw.get("scene") or ""),
        size=size, rank=size_rank(size), move=move_kind(motion), move_text=motion,
        desc=" ".join(str(raw.get("desc") or "").split()), purpose=str(raw.get("shot_purpose") or "information"),
        seconds=parse_duration_seconds(raw.get("duration")),
        subjects=[str(name).strip() for name in names if str(name).strip() not in _EMPTY_CAST],
        camera=camera, dialogue=str(raw.get("dialogue") or "").strip(),
    )


def _time_of_day(text: str) -> str:
    for label, pattern in (("night", _NIGHT), ("dusk", _DUSK), ("day", _DAY)):
        if pattern.search(text):
            return label
    return ""


def _tone(text: str) -> str:
    warm = sum(text.count(word) for word in _WARM)
    cool = sum(text.count(word) for word in _COOL)
    return "warm" if warm > cool else "cool" if cool > warm else ""


def _emotion(text: str) -> str:
    for label, words in _EMOTIONS:
        if any(word in text for word in words):
            return label
    return ""


def _shape(text: str) -> tuple[str, str]:
    for label, words in _SHAPES:
        hit = next((word for word in words if word in text), "")
        if hit:
            return label, hit
    return "", ""


def _shared_action(first: _Shot, second: _Shot) -> str:
    """The movement both shots show, when they also share whoever performs it (or the second is its result)."""
    if first.subjects and second.subjects and not set(first.subjects) & set(second.subjects):
        return ""
    for family in _ACTION_FAMILIES:
        before = next((word for word in family if word in first.desc), "")
        after = next((word for word in family if word in second.desc), "")
        if before and after:
            return before
    return ""


def _rhyming_action(first: _Shot, second: _Shot) -> tuple[str, str]:
    """两场戏里相似的运动：笔落下、槌落下。谁做的都行，靠的是方向和节奏。"""
    for family in _ACTION_FAMILIES:
        before = next((word for word in family if word in first.desc), "")
        after = next((word for word in family if word in second.desc), "")
        if before and after:
            return before, after
    return "", ""


def _sound_join(first: _Shot | None, second: _Shot, kind: str, technique: str) -> tuple[SoundJoin, str]:
    """这一刀声音和画面要不要错开。淡入淡出是换章的停顿，不错开。"""
    if first is None or kind == "fade" or technique == "opening":
        return "", ""
    moved = first.scene_id != second.scene_id or bool(first.location and second.location and first.location != second.location)
    if first.dialogue and not second.dialogue and (moved or second.is_insert or not set(first.subjects) & set(second.subjects)):
        return "l_cut", _says("l_cut_note")
    if moved:
        return "j_cut", _says("j_cut_note")
    return "", ""


def _motion_join(first: _Shot | None, second: _Shot) -> MotionJoin:
    if first is None or not first.moving:
        return "static_to_moving" if second.moving else "static_to_static"
    return "moving_to_moving" if second.moving else "moving_to_static"


def _pan_side(text: str) -> str:
    return "left" if any(word in text for word in _PAN_LEFT) else (
        "right" if any(word in text for word in _PAN_RIGHT) else ""
    )


def _moves_oppose(first: _Shot, second: _Shot) -> bool:
    if (first.move, second.move) in _OPPOSITE_MOVES:
        return True
    left, right = _pan_side(first.move_text), _pan_side(second.move_text)
    return bool(left and right and left != right and first.move == second.move and first.move in {"pan", "track"})


_MOTION_JOINS: tuple[str, ...] = ("static_to_static", "moving_to_moving", "moving_to_static", "static_to_moving")
_JOIN_OUT: dict[str, str] = {join: str(_table("join_out")[join]) for join in _MOTION_JOINS}
_JOIN_IN: dict[str, str] = {join: str(_table("join_in")[join]) for join in _MOTION_JOINS}


def _cut(case: str, /, **values: object) -> tuple[str, list[str]]:
    """``(what carries across, [why])`` of one case of the cut table, filled in."""
    row = _table("cuts")[case]
    return str(row["carries"]).format(**values), [str(row["reason"]).format(**values)]


def _decide(first: _Shot | None, second: _Shot, *, first_of_episode: bool) -> tuple[CutKind, Technique, str, list[str]]:
    """``(kind, technique, what carries across, why)`` for the cut into ``second``."""
    if first is None:
        if first_of_episode:
            return "fade", "opening", *_cut("episode_opening")
        return "dissolve", "opening", *_cut("scene_opening")
    same_scene = first.scene_id == second.scene_id
    if _FLASHBACK.search(second.text) and not _FLASHBACK.search(first.text):
        return "dissolve", "flashback", *_cut("flashback_in")
    if _FLASHBACK.search(first.text) and not _FLASHBACK.search(second.text) and not same_scene:
        return "dissolve", "flashback", *_cut("flashback_out")
    if _BIG_TIME_JUMP.search(second.text):
        return "fade", "chapter", *_cut("chapter")
    before, after = _time_of_day(first.text), _time_of_day(second.text)
    if _TIME_PASSAGE.search(second.text) or (before and after and before != after):
        return "dissolve", "time_passage", *_cut("time_passage")
    if not same_scene or (first.location and second.location and first.location != second.location):
        shape_a, word_a = _shape(first.desc)
        shape_b, word_b = _shape(second.desc)
        if shape_a and shape_a == shape_b:
            return "match_cut", "graphic_match", *_cut("graphic_match", word_a=word_a, word_b=word_b, shape=shape_a)
        if _EXIT.search(first.desc) and set(first.subjects) & set(second.subjects):
            return "match_cut", "action_match", *_cut("exit")
        token = next((word for word in _TOKENS if word in first.desc and word in second.desc), "")
        if token:
            return "match_cut", "object_carry", *_cut("object_carry", token=token)
        rhyme = _rhyming_action(first, second)
        if all(rhyme):
            return "match_cut", "action_rhyme", *_cut("action_rhyme", before=rhyme[0], after=rhyme[1])
        hidden = _OCCLUSION.search(first.desc)
        if hidden:
            return "push_pull", "occlusion", *_cut("occlusion", occluder=hidden.group(1))
        if (_tone(first.text) and _tone(second.text) and _tone(first.text) != _tone(second.text)) or (before and after and before != after):
            return "dissolve", "scene_change", *_cut("tone_change")
        return "push_pull", "scene_change", *_cut("scene_change")
    if first.subjects and _LOOK.search(first.desc) and (second.is_pov or second.is_insert or not set(first.subjects) & set(second.subjects)):
        return "match_cut", "eyeline_match", *_cut("eyeline_match", looker=first.subjects[0])
    if (first.is_pov or first.is_insert) and second.subjects:
        return "match_cut", "reaction", *_cut("reaction")
    action = _shared_action(first, second)
    if action:
        return "match_cut", "action_match", *_cut("action_match", action=action)
    if len(first.subjects) == 1 and len(second.subjects) == 1 and first.subjects != second.subjects:
        return "match_cut", "shot_reverse", *_cut("shot_reverse")
    return "match_cut", "plain", *_cut("plain")


def _carries_head(technique: str, carries: str) -> str:
    """The thing named at the front of ``carries`` (the shape, the movement, the occluder) for the cut-out wording."""
    rule = _table("carries_heads").get(technique)
    if rule is None:
        return carries
    until = str(rule["until"])
    if "otherwise" in rule and until not in carries:
        return str(rule["otherwise"])
    return carries.split(until)[0]


def _edit_text(cut_kind: str, technique: str, carries: str, first: _Shot | None, second: _Shot, join: str) -> tuple[str, str]:
    label = transition_label(cut_kind)
    if technique == "opening":
        return "", _clip(_says("opening_in_fade" if cut_kind == "fade" else "opening_in", join=_JOIN_IN[join]), 500)
    looker = first.subjects[0] if first is not None and first.subjects else _word("someone")
    values = {
        "carries": carries, "looker": looker, "head": _carries_head(technique, carries),
        "reactor": second.subjects[0] if second.subjects else _word("someone"),
    }
    out_body = str(_table("edit_out")[technique]).format(**values)
    in_key = (
        "time_passage_same_place"
        if technique == "time_passage" and first is not None and first.location and first.location == second.location
        else technique
    )
    in_body = str(_table("edit_in")[in_key]).format(**values)
    # An optical transition needs a settled picture on both sides, whatever the cameras were doing.
    settle = cut_kind in {"dissolve", "fade"}
    join_out = _says("settled_out") if settle else _JOIN_OUT[join]
    join_in = _says("settled_in_moving") if settle and join.endswith("moving") else _says("settled_in") if settle else _JOIN_IN[join]
    return (
        _clip(_says("edit_line", label=label, body=out_body, join=join_out), 500),
        _clip(_says("edit_line", label=label, body=in_body, join=join_in), 500),
    )


def plan_transitions(
    shots: Sequence[Mapping[str, Any]],
    *,
    stage_plan: StagePlan | None = None,
    previous_shot: Mapping[str, Any] | None = None,
    first_of_episode: bool = False,
) -> TransitionPlan:
    """The cut plan and the checks for ``shots`` in order; ``previous_shot`` is the shot the scene follows."""
    views = [_view(raw, index, stage_plan) for index, raw in enumerate(shots, start=1) if isinstance(raw, Mapping)]
    if not views:
        return TransitionPlan()
    lead_in = _view(previous_shot, 0, None) if isinstance(previous_shot, Mapping) else None
    cuts: list[CutPlan] = []
    for index, second in enumerate(views):
        first = views[index - 1] if index else lead_in
        kind, technique, carries, reasons = _decide(first, second, first_of_episode=first_of_episode and index == 0)
        join = _motion_join(first, second)
        lens_change = None
        if first is not None and first.camera is not None and second.camera is not None and index:
            lens_change = bearing_change_deg(first.camera, second.camera, (second.camera.target[0], second.camera.target[2]))
        edit_out, edit_in = _edit_text(kind, technique, carries, first, second, join)
        sound_join, sound_note = _sound_join(first, second, kind, technique)
        cuts.append(CutPlan(
            from_shot=(first.shot_id if first is not None and index else 0), to_shot=second.shot_id,
            kind=kind, technique=technique, label=_says("cut_label", device=transition_label(kind), technique=_TECHNIQUE_ZH[technique])[:60],
            duration_seconds=_CUT_SECONDS[kind], motion_join=join,
            size_step=max(-8, min(8, second.rank - first.rank)) if first is not None else 0,
            lens_change_deg=round(lens_change, 1) if lens_change is not None else None,
            carries=_clip(carries, 300), reasons=reasons, edit_out=edit_out, edit_in=edit_in,
            sound_join=sound_join, sound_note=sound_note,
            arrival=bool(first is not None and index and _runs(first) and not _runs(second)),
        ))
    return TransitionPlan(cuts=cuts, checks=_checks(views, cuts, stage_plan))


def _runs(shot: _Shot) -> bool:
    return any(word in shot.desc for word in _RUN)


def _ids(values: Sequence[int]) -> list[int]:
    return sorted(dict.fromkeys(values))[:200]


def _checks(views: Sequence[_Shot], cuts: Sequence[CutPlan], plan: StagePlan | None) -> list[TransitionCheck]:
    pairs = list(zip(views, views[1:]))
    checks: list[TransitionCheck] = []

    # ---- picture: sizes step, they do not leap
    leaps = [
        (a, b) for a, b in pairs
        if abs(b.rank - a.rank) > MAX_SIZE_STEP and a.scene_id == b.scene_id
        and b.purpose not in {"shock", "reversal"} and not (a.is_insert or b.is_insert or a.is_pov or b.is_pov)
    ]
    checks.append(TransitionCheck(
        code="transition_shot_size_step", passed=not leaps,
        detail=(
            _JOINER.join(_says("size_step_item", a=a.shot_id, a_size=a.size, b=b.shot_id, b_size=b.size) for a, b in leaps)[:1800]
            + _says("size_step_tail")
            if leaps else _says("size_step_passed")
        ),
        shot_ids=_ids([b.shot_id for _, b in leaps]),
    ))

    # ---- picture: the 30-degree rule (needs the lenses, so only with a spatial plan)
    if plan is not None:
        jumps = [
            (a, b) for a, b in pairs
            if a.camera is not None and b.camera is not None and a.scene_id == b.scene_id and repeats_the_angle(a.camera, b.camera)
        ]
        checks.append(TransitionCheck(
            code="transition_thirty_degree", passed=not jumps,
            detail=(
                _JOINER.join(_says("shot_pair", a=a.shot_id, b=b.shot_id) for a, b in jumps)[:1800]
                + _says("thirty_degree_tail", min_angle=MIN_ANGLE_CHANGE_DEG)
                if jumps else _says("thirty_degree_passed", min_angle=MIN_ANGLE_CHANGE_DEG)
            ),
            shot_ids=_ids([b.shot_id for _, b in jumps]),
        ))

    # ---- picture: a look is answered, a point of view has someone looking
    orphans: list[str] = []
    orphan_ids: list[int] = []
    for index, shot in enumerate(views):
        previous = views[index - 1] if index else None
        if shot.is_pov and (previous is None or not previous.subjects):
            orphans.append(_says("pov_orphan", shot=shot.shot_id))
            orphan_ids.append(shot.shot_id)
        following = views[index + 1] if index + 1 < len(views) else None
        after = views[index + 2] if index + 2 < len(views) else None
        if (
            shot.subjects and _LOOK.search(shot.desc) and following is not None and (following.is_pov or following.is_insert)
            and after is not None and after.subjects and not set(shot.subjects) & set(after.subjects)
        ):
            orphans.append(_says("look_unanswered", shot=shot.shot_id, looker=shot.subjects[0], seen=following.shot_id))
            orphan_ids.append(after.shot_id)
    checks.append(TransitionCheck(
        code="transition_eyeline_answered", passed=not orphans,
        detail=_JOINER.join(orphans)[:1900] + _says("sentence_end") if orphans else _says("eyeline_passed"),
        shot_ids=_ids(orphan_ids),
    ))

    # ---- motion: two moves do not pull against each other
    clashes = [(a, b) for a, b in pairs if a.moving and b.moving and a.scene_id == b.scene_id and _moves_oppose(a, b)]
    checks.append(TransitionCheck(
        code="transition_motion_direction", passed=not clashes,
        detail=(
            _JOINER.join(_says("move_pair", a=a.shot_id, a_move=a.move_text, b=b.shot_id, b_move=b.move_text) for a, b in clashes)[:1800]
            + _says("motion_direction_tail")
            if clashes else _says("motion_direction_passed")
        ),
        shot_ids=_ids([b.shot_id for _, b in clashes]),
    ))

    # ---- logic: nobody seen at the end of one shot is somewhere else when the next one starts
    if plan is not None:
        jumped: list[str] = []
        jumped_ids: list[int] = []
        for a, b in pairs:
            staged_a, staged_b = plan.shot(a.shot_id), plan.shot(b.shot_id)
            cut = next((item for item in cuts if item.to_shot == b.shot_id), None)
            if staged_a is None or staged_b is None or a.scene_id != b.scene_id or (cut is not None and cut.kind not in {"cut", "match_cut"}):
                continue
            seen = {state.name for state in staged_a.screen if state.visible}
            ending = {actor.name: actor for actor in plan.actors_in(staged_a, at_end=True)}
            for actor in plan.actors_in(staged_b):
                before = ending.get(actor.name)
                if before is None or actor.role == "crowd" or actor.name not in seen:
                    continue
                gap = geo.distance((before.position[0], before.position[1]), (actor.position[0], actor.position[1]))
                if gap <= MAX_STATE_JUMP_M:
                    continue
                jumped.append(_says("state_jump", name=actor.name, a=a.shot_id, b=b.shot_id, gap=gap))
                jumped_ids.append(b.shot_id)
        checks.append(TransitionCheck(
            code="transition_state_continuous", passed=not jumped,
            detail=_JOINER.join(jumped)[:1800] + _says("state_jump_tail") if jumped
            else _says("state_passed"),
            shot_ids=_ids(jumped_ids),
        ))

    # ---- logic: an effect does not come before its cause
    inverted: list[str] = []
    inverted_ids: list[int] = []
    for index, (a, b) in enumerate(pairs):
        if a.scene_id != b.scene_id or a.purpose in {"shock", "suspense", "reversal"}:
            continue
        earlier = " ".join(item.desc for item in views[: index + 1])
        for causes, effects in _CAUSALITY:
            effect = next((word for word in effects if word in a.desc), "")
            cause = next((word for word in causes if word in b.desc), "")
            if effect and cause and not any(word in earlier for word in causes):
                inverted.append(_says("cause_inverted", a=a.shot_id, effect=effect, b=b.shot_id, cause=cause))
                inverted_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_cause_before_effect", passed=not inverted,
        detail=_JOINER.join(inverted)[:1900] + _says("cause_tail") if inverted
        else _says("cause_passed"),
        shot_ids=_ids(inverted_ids),
    ))

    # ---- matching: light and colour do not flip across a hard cut inside one scene
    flips: list[str] = []
    flip_ids: list[int] = []
    for a, b in pairs:
        cut = next((item for item in cuts if item.to_shot == b.shot_id), None)
        if cut is None or cut.kind not in {"cut", "match_cut"} or a.scene_id != b.scene_id:
            continue
        hours = _time_of_day(a.desc), _time_of_day(b.desc)
        tones = _tone(a.desc), _tone(b.desc)
        if all(hours) and hours[0] != hours[1]:
            flips.append(_says("light_hours", a=a.shot_id, b=b.shot_id))
        elif all(tones) and tones[0] != tones[1]:
            flips.append(_says("light_tones", a=a.shot_id, a_tone=_TONE_ZH[tones[0]], b=b.shot_id, b_tone=_TONE_ZH[tones[1]]))
        else:
            continue
        flip_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_light_continuity", passed=not flips,
        detail=(
            _JOINER.join(flips)[:1800] + _says("light_tail")
            if flips else _says("light_passed")
        ),
        shot_ids=_ids(flip_ids),
    ))

    # ---- rhythm: durations breathe, fast material is not held
    timed = [shot for shot in views if shot.seconds > 0]
    rhythm: list[str] = []
    rhythm_ids: list[int] = []
    if len(timed) >= 5 and len({shot.seconds for shot in timed}) == 1:
        rhythm.append(_says("rhythm_even", seconds=timed[0].seconds))
        rhythm_ids.append(timed[-1].shot_id)
    if len(timed) >= 3:
        typical = median(shot.seconds for shot in timed)
        for shot in timed:
            fast = shot.purpose in _FAST_PURPOSES or any(word in shot.desc for word in _BURST)
            if fast and shot.seconds >= max(8, typical * 1.8):
                rhythm.append(_says("rhythm_slow", shot=shot.shot_id, seconds=shot.seconds))
                rhythm_ids.append(shot.shot_id)
    checks.append(TransitionCheck(
        code="transition_rhythm", passed=not rhythm,
        detail=_JOINER.join(rhythm)[:1900] + _says("sentence_end") if rhythm else _says("rhythm_passed"),
        shot_ids=_ids(rhythm_ids),
    ))

    # ---- rhythm: emotions do not collide
    breaks = [(a, b) for a, b in pairs if (_emotion(a.desc), _emotion(b.desc)) in _COLLISIONS]
    checks.append(TransitionCheck(
        code="transition_emotion_bridge", passed=not breaks,
        detail=(
            _JOINER.join(_says("shot_pair", a=a.shot_id, b=b.shot_id) for a, b in breaks)[:1800]
            + _says("emotion_tail")
            if breaks else _says("emotion_passed")
        ),
        shot_ids=_ids([b.shot_id for _, b in breaks]),
    ))
    checks.extend(_diagnosis_checks(pairs, views, plan))
    return checks


def _diagnosis_checks(pairs: Sequence[tuple[_Shot, _Shot]], views: Sequence[_Shot], plan: StagePlan | None) -> list[TransitionCheck]:
    """单看都好、接起来别扭的那几类：没有新信息、动作重演、方向翻转、能量没来由、眼睛要跨屏、全程不动。"""
    checks: list[TransitionCheck] = []

    # ---- why cut at all: the next shot brings something new
    same = [
        (a, b) for a, b in pairs
        if a.scene_id == b.scene_id and a.subjects and a.subjects == b.subjects and a.rank == b.rank and a.move == b.move
        and (not b.dialogue or b.dialogue == a.dialogue) and SequenceMatcher(None, a.desc, b.desc).ratio() >= SAME_INFO_RATIO
    ]
    checks.append(TransitionCheck(
        code="transition_new_information", passed=not same,
        detail=(
            _JOINER.join(_says("shot_pair", a=a.shot_id, b=b.shot_id) for a, b in same)[:1800]
            + _says("new_information_tail")
            if same else _says("new_information_passed")
        ),
        shot_ids=_ids([b.shot_id for _, b in same]),
    ))

    # ---- action: the next shot picks it up, it does not start it again
    replays: list[tuple[_Shot, _Shot, str]] = []
    for a, b in pairs:
        action = _shared_action(a, b) if a.scene_id == b.scene_id else ""
        if action and _DONE.search(a.desc[a.desc.find(action):]) and not _PICKUP.search(b.desc):
            replays.append((a, b, action))
    checks.append(TransitionCheck(
        code="transition_action_replay", passed=not replays,
        detail=(
            _JOINER.join(_says("action_replay", a=a.shot_id, action=action, b=b.shot_id) for a, b, action in replays)[:1800]
            + _says("action_replay_tail")
            if replays else _says("action_replay_passed")
        ),
        shot_ids=_ids([b.shot_id for _, b, _ in replays]),
    ))

    # ---- direction: someone walking right does not walk left without showing why,
    # and who leaves on one side of the frame comes back in on the other
    flips = [
        (a, b) for a, b in pairs
        if a.scene_id == b.scene_id and set(a.subjects) & set(b.subjects) and _heading(a.desc) and _heading(b.desc)
        and _heading(a.desc) != _heading(b.desc) and not _TURNED.search(f"{a.desc} {b.desc}")
    ]
    crossings = [
        (a, b) for a, b in pairs
        if a.scene_id == b.scene_id and set(a.subjects) & set(b.subjects) and not _TURNED.search(f"{a.desc} {b.desc}")
        and _side_of(_EXIT_SIDE, a.desc) and _side_of(_EXIT_SIDE, a.desc) == _side_of(_ENTRY_SIDE, b.desc)
    ]
    direction_parts = []
    if flips:
        direction_parts.append(_JOINER.join(_says("shot_pair", a=a.shot_id, b=b.shot_id) for a, b in flips) + _says("screen_direction_tail"))
    if crossings:
        direction_parts.append(
            _JOINER.join(_says("exit_entry_pair", a=a.shot_id, b=b.shot_id, side=_side_of(_EXIT_SIDE, a.desc)) for a, b in crossings) + _says("exit_entry_tail")
        )
    checks.append(TransitionCheck(
        code="transition_screen_direction", passed=not flips and not crossings,
        detail=_JOINER.join(direction_parts)[:1800] if direction_parts else _says("screen_direction_passed"),
        shot_ids=_ids([b.shot_id for _, b in [*flips, *crossings]]),
    ))

    # ---- energy: two moves of the same size, and a burst has a reason
    energy: list[str] = []
    energy_ids: list[int] = []
    for a, b in pairs:
        if a.scene_id != b.scene_id:
            continue
        if a.moving and b.moving and ((_FAST_MOVE.search(a.move_text) and _SLOW_MOVE.search(b.move_text)) or (_SLOW_MOVE.search(a.move_text) and _FAST_MOVE.search(b.move_text))):
            energy.append(_says("energy_clash", a=a.shot_id, a_move=a.move_text, b=b.shot_id, b_move=b.move_text))
            energy_ids.append(b.shot_id)
        elif _FAST_MOVE.search(b.move_text) and not a.moving and b.purpose not in _FAST_PURPOSES and not _ENERGY_MOTIVE.search(f"{a.desc} {b.desc}"):
            energy.append(_says("energy_unmotivated", b=b.shot_id, b_move=b.move_text))
            energy_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_motion_energy", passed=not energy,
        detail=_JOINER.join(energy)[:1800] + _says("energy_tail") if energy
        else _says("energy_passed"),
        shot_ids=_ids(energy_ids),
    ))

    # ---- breath: the lens is not locked off for a whole scene, and people are not shaken about
    breath: list[str] = []
    breath_ids: list[int] = []
    scenes: dict[str, list[_Shot]] = {}
    for shot in views:
        scenes.setdefault(shot.scene_id, []).append(shot)
    for scene_id, shots in scenes.items():
        if len(shots) >= STATIC_RUN and not any(shot.moving for shot in shots):
            breath.append(_says("breath_locked", scene=scene_id or _word("this_scene"), count=len(shots)))
            breath_ids.append(shots[-1].shot_id)
    for shot in views:
        if shot.subjects and _VIOLENT_MOVE.search(shot.move_text):
            breath.append(_says("breath_violent", shot=shot.shot_id, move=shot.move_text))
            breath_ids.append(shot.shot_id)
    checks.append(TransitionCheck(
        code="transition_camera_breath", passed=not breath,
        detail=_JOINER.join(breath)[:1900] + _says("sentence_end") if breath else _says("breath_passed"),
        shot_ids=_ids(breath_ids),
    ))

    # ---- attention: the eye lands near where it was (needs the staged frames)
    if plan is not None:
        jumps: list[str] = []
        jump_ids: list[int] = []
        for a, b in pairs:
            staged_a, staged_b = plan.shot(a.shot_id), plan.shot(b.shot_id)
            if staged_a is None or staged_b is None or a.scene_id != b.scene_id or abs(b.rank - a.rank) > 1:
                continue
            before = {state.name: state for state in staged_a.screen if state.visible}
            for state in staged_b.screen:
                held = before.get(state.name)
                if held is not None and state.visible and abs(state.x - held.x) > MAX_ATTENTION_JUMP:
                    jumps.append(_says("attention_jump", name=state.name, a=a.shot_id, b=b.shot_id, span=abs(state.x - held.x)))
                    jump_ids.append(b.shot_id)
                    break
        checks.append(TransitionCheck(
            code="transition_attention_jump", passed=not jumps,
            detail=_JOINER.join(jumps)[:1800] + _says("attention_tail") if jumps
            else _says("attention_passed"),
            shot_ids=_ids(jump_ids),
        ))
    return checks


def _side_of(pattern: re.Pattern[str], text: str) -> str:
    """The side of the frame a shot says someone leaves or enters by (左 / 右), or ``""``."""
    found = pattern.search(text)
    return found.group(1) if found else ""


def _heading(text: str) -> str:
    found = _DIRECTION.search(text)
    return (found.group(1) or (_HEADING_LEFT if found.group(2) == _HEADING_RIGHT else _HEADING_RIGHT)) if found else ""


# The stage-4 table writer's brief on cutting, one rule after another.
TABLE_BRIEF = "".join(prompt_data.words(_WORDING, "table_brief"))


def scene_lead_in(flat_shots: Sequence[Mapping[str, Any]], scene_order: Sequence[str], scene_id: str) -> Mapping[str, Any] | None:
    """The last shot of the nearest earlier scene that has shots: what this scene's first shot cuts from."""
    order = [str(item) for item in scene_order]
    if scene_id not in order:
        return None
    for earlier in reversed(order[: order.index(scene_id)]):
        shots = [shot for shot in flat_shots if isinstance(shot, Mapping) and str(shot.get("scene_id") or "") == earlier]
        if shots:
            return max(shots, key=lambda shot: int(shot.get("shot_id") or 0))
    return None


def panel_fields(plan: TransitionPlan, shot_id: int, *, total: int) -> dict[str, str]:
    """``edit_in / edit_out / continuity_in / continuity_out / start_state / end_state`` of one storyboard panel."""
    into, out_of = plan.cut_into(shot_id), plan.cut_out_of(shot_id)
    fields: dict[str, str] = {}
    if into is not None:
        fields["edit_in"] = into.edit_in or _says("panel_edit_in")
        if into.from_shot:
            step = (
                _says("size_same") if into.size_step == 0
                else _says("size_closer" if into.size_step > 0 else "size_wider", steps=abs(into.size_step))
            )
            fields["continuity_in"] = _clip(_says(
                "continuity_in", shot=into.from_shot, label=into.label, carries=into.carries or _says("continuity_in_carries"), step=step,
            ), 1000)
            fields["start_state"] = _clip(
                _says("start_mid_action") if into.technique == "action_match"
                else _says("start_held", label=into.label), 1000,
            )
        else:
            fields["continuity_in"] = _says("establish")
            fields["start_state"] = _says("establish")
    if out_of is not None:
        fields["edit_out"] = out_of.edit_out
        fields["continuity_out"] = _clip(_says(
            "continuity_out", shot=out_of.to_shot, label=out_of.label, carries=out_of.carries or _says("continuity_out_carries"),
        ), 1000)
        fields["end_state"] = _clip(
            _says("end_mid_action") if out_of.technique == "action_match"
            else _says("end_arriving") if out_of.arrival
            else _says("end_settled") if out_of.motion_join == "moving_to_static"
            else _says("end_held"), 1000,
        )
    elif shot_id and total:
        fields["edit_out"] = _says("scene_last_out")
    return fields


def shot_summary(plan: TransitionPlan, shot_id: int) -> dict[str, Any]:
    """What a storyboard shot records about the cut that leads into it."""
    cut = plan.cut_into(shot_id)
    if cut is None:
        return {}
    return {
        "from_shot": cut.from_shot, "kind": cut.kind, "technique": cut.technique, "label": cut.label,
        "duration_seconds": cut.duration_seconds, "motion_join": cut.motion_join,
        "compositor": COMPOSITOR_TRANSITIONS[cut.kind],
        "sound_join": cut.sound_join, "sound_note": cut.sound_note, "watch": _WATCH[cut.technique],
    }


__all__ = [
    "COMPOSITOR_TRANSITIONS", "MAX_SIZE_STEP", "TABLE_BRIEF", "CutPlan", "TransitionCheck", "TransitionPlan",
    "panel_fields", "plan_transitions", "scene_lead_in", "shot_summary",
]
