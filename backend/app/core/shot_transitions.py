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
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import MIN_ANGLE_CHANGE_DEG, bearing_change_deg, move_kind, repeats_the_angle, size_rank
from app.core.spatial_stage.models import StageCamera, StagePlan
from app.core.transition_catalog import transition_label
from app.core.writer_dashboard import parse_duration_seconds

CutKind = Literal["cut", "dissolve", "fade", "match_cut"]
Technique = Literal[
    "opening", "plain", "shot_reverse", "action_match", "eyeline_match", "reaction",
    "graphic_match", "time_passage", "flashback", "chapter", "scene_change",
]
MotionJoin = Literal["static_to_static", "moving_to_moving", "moving_to_static", "static_to_moving"]

# A leap of this many size steps (全景 → 特写 is 5) needs a reason.
MAX_SIZE_STEP = 4
MAX_STATE_JUMP_M = 0.8
_CUT_SECONDS: dict[str, float] = {"cut": 0.0, "match_cut": 0.0, "dissolve": 0.5, "fade": 0.8}
# What the compositor calls each device.
COMPOSITOR_TRANSITIONS: dict[str, str] = {
    "cut": "hard_cut", "match_cut": "match_cut", "dissolve": "crossfade", "fade": "dip_to_black",
}
_TECHNIQUE_ZH: dict[str, str] = {
    "opening": "开场", "plain": "顺接", "shot_reverse": "正反打", "action_match": "动作匹配",
    "eyeline_match": "视线匹配", "reaction": "切回反应", "graphic_match": "图形匹配",
    "time_passage": "时间流逝", "flashback": "回忆", "chapter": "章节转换", "scene_change": "场景转换",
}
_EMPTY_CAST = frozenset({"", "无", "无人", "无人物", "空镜", "空镜（无人物）"})

_BIG_TIME_JUMP = re.compile(r"(?:\d+|[一二两三四五六七八九十数几多半]+)\s*(?:年|个月|月|周|星期)\s*(?:后|之后|以后|过去)|多年以?后|数年后|经年")
_TIME_PASSAGE = re.compile(
    r"(?:\d+|[一二两三四五六七八九十数几半]+)\s*(?:天|日|夜|个?时辰|小时|刻钟)\s*(?:后|之后|以后|过去)"
    r"|次日|翌日|第二天|片刻之?后|良久|许久之?后|不知过了多久|转眼|入夜后|天亮后|天色渐|日头西斜"
)
_FLASHBACK = re.compile(r"回忆|闪回|往事|当年|那一年|那一夜|梦中|梦境|记忆里|记忆中|幻象")
_DAY = re.compile(r"清晨|早晨|上午|正午|中午|午后|白天|白昼|阳光|日光|烈日|晴空")
_DUSK = re.compile(r"黄昏|傍晚|夕阳|暮色|日落|晚霞")
_NIGHT = re.compile(r"深夜|夜里|夜晚|入夜|夜色|月光|月色|三更|子时|夜幕|星空")
_LOOK = re.compile(r"看向|望向|盯着|盯住|注视|凝视|瞥见|瞥向|抬头看|低头看|回头看|目光落|目光移|循声望|望去|看去|看见|发现")
_POV = re.compile(r"主观|POV|第一人称|视角镜头", re.IGNORECASE)
_EXIT = re.compile(r"推门而出|出门|走出|冲出|离开|踏出|跨出|转身离去|夺门")
# One action, cut in two: a family names the same movement at different moments.
_ACTION_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("推门", "推开", "门开", "门被推开", "开门", "拉开门"), ("拔剑", "拔刀", "出鞘", "抽剑", "抽刀"),
    ("挥剑", "挥刀", "劈", "砍", "斩"), ("伸手", "抓住", "握住", "攥住", "接过", "递"), ("转身", "回身", "回头", "扭头"),
    ("起身", "站起", "爬起"), ("坐下", "落座"), ("跪下", "跪倒", "跪地"), ("倒地", "倒下", "摔倒", "栽倒"),
    ("举杯", "饮下", "喝下", "仰头饮"), ("抬手", "扬手", "挥手", "抬起手"), ("奔", "跑", "冲向", "冲进", "冲出"),
    ("跃起", "跳下", "跃下", "腾空"), ("扔", "掷", "抛", "摔碎", "砸"), ("点燃", "烧", "燃起", "火舌"),
    ("展开", "抖开", "摊开", "翻开", "合上"), ("出拳", "挥拳", "踢", "踹", "格挡"),
)
# (cause words, effect words): the effect on screen before anyone has done the cause.
_CAUSALITY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("开枪", "扣动扳机", "放箭", "射出"), ("中弹", "中枪", "中箭")),
    (("挥刀", "挥剑", "一刀", "一剑", "刺出", "刺入"), ("血溅", "鲜血喷", "捂住伤口", "应声倒地")),
    (("敲门", "叩门"), ("门应声而开", "门从里面打开")),
    (("点火", "点燃", "引燃"), ("火光冲天", "烈焰吞没", "化为灰烬")),
    (("一推", "猛推", "一脚踹"), ("跌出去", "摔出去", "撞在", "撞翻")),
)
_SHAPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("圆形", ("瞳孔", "眼眸", "月亮", "圆月", "满月", "太阳", "铜镜", "圆镜", "灯笼", "钟表", "车轮", "碗口", "井口", "玉璧", "铜钱", "星球")),
    ("竖线", ("剑身", "长剑", "立柱", "廊柱", "门缝", "烛台", "旗杆", "竹", "塔")),
    ("横线", ("地平线", "案几", "长桥", "城墙", "水面", "屋檐")),
    ("火光", ("烛火", "火舌", "篝火", "火把", "炭火", "烈焰")),
)
_WARM = ("烛", "火光", "炭", "篝火", "夕阳", "暖", "金色", "灯笼", "橘")
_COOL = ("月光", "月色", "雨", "雪", "冷", "蓝", "青灰", "霜", "寒")
_EMOTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("grief", ("泪", "哭", "哽咽", "啜泣", "痛哭", "崩溃", "悲")),
    ("fear", ("惊恐", "恐惧", "发抖", "颤抖", "瑟缩", "魂飞")),
    ("rage", ("怒吼", "暴怒", "咬牙", "厉声", "青筋")),
    ("comic", ("搞笑", "滑稽", "调侃", "嬉皮", "笑出声", "哈哈", "憋笑", "鬼脸", "打趣")),
    ("tender", ("温柔", "相拥", "轻抚", "含笑", "微笑")),
)
_COLLISIONS = frozenset({("grief", "comic"), ("comic", "grief"), ("fear", "comic"), ("comic", "fear")})
_FAST_PURPOSES = frozenset({"tension", "shock"})
_BURST = ("挥剑", "挥刀", "砍", "劈", "冲上", "冲向", "撞", "怒吼", "开枪", "爆炸", "扑向", "出拳", "踢")
_OPPOSITE_MOVES = frozenset({("push", "pull"), ("pull", "push"), ("rise", "fall"), ("fall", "rise")})
_TONE_ZH = {"warm": "暖色", "cool": "冷色"}


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip("，；、 ") + "…"


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


class TransitionPlan(BaseModel):
    cuts: list[CutPlan] = Field(default_factory=list, max_length=500)
    checks: list[TransitionCheck] = Field(default_factory=list, max_length=20)

    def cut_into(self, shot_id: int) -> CutPlan | None:
        return next((cut for cut in self.cuts if cut.to_shot == int(shot_id)), None)

    def cut_out_of(self, shot_id: int) -> CutPlan | None:
        return next((cut for cut in self.cuts if cut.from_shot == int(shot_id)), None)

    @property
    def summary(self) -> str:
        return _clip("；".join(
            f"{cut.from_shot or '入场'}→{cut.to_shot} {cut.label}" + (f"（{cut.carries}）" if cut.carries else "")
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
    size = str(raw.get("size") or "中景")
    motion = str(raw.get("motion") or "")
    return _Shot(
        shot_id=shot_id, scene_id=str(raw.get("scene_id") or ""), location=str(raw.get("scene") or ""),
        size=size, rank=size_rank(size), move=move_kind(motion), move_text=motion,
        desc=" ".join(str(raw.get("desc") or "").split()), purpose=str(raw.get("shot_purpose") or "information"),
        seconds=parse_duration_seconds(raw.get("duration")),
        subjects=[str(name).strip() for name in names if str(name).strip() not in _EMPTY_CAST],
        camera=camera,
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


def _motion_join(first: _Shot | None, second: _Shot) -> MotionJoin:
    if first is None or not first.moving:
        return "static_to_moving" if second.moving else "static_to_static"
    return "moving_to_moving" if second.moving else "moving_to_static"


def _pan_side(text: str) -> str:
    return "left" if any(word in text for word in ("左摇", "向左", "左移", "右至左")) else (
        "right" if any(word in text for word in ("右摇", "向右", "右移", "左至右")) else ""
    )


def _moves_oppose(first: _Shot, second: _Shot) -> bool:
    if (first.move, second.move) in _OPPOSITE_MOVES:
        return True
    left, right = _pan_side(first.move_text), _pan_side(second.move_text)
    return bool(left and right and left != right and first.move == second.move and first.move in {"pan", "track"})


_JOIN_OUT: dict[str, str] = {
    "static_to_static": "画面稳住，切点落在动作或台词的停顿上",
    "moving_to_moving": "运动中直接切出，不留落幅",
    "moving_to_static": "运镜在切点前约半秒落幅稳住再切",
    "static_to_moving": "画面稳住后切出",
}
_JOIN_IN: dict[str, str] = {
    "static_to_static": "以稳定画面切入",
    "moving_to_moving": "从运动中起，方向与速度承接上一镜",
    "moving_to_static": "以稳定画面切入，承接上一镜落幅",
    "static_to_moving": "先以起幅稳住约半秒再开始运动",
}


def _decide(first: _Shot | None, second: _Shot, *, first_of_episode: bool) -> tuple[CutKind, Technique, str, list[str]]:
    """``(kind, technique, what carries across, why)`` for the cut into ``second``."""
    if first is None:
        if first_of_episode:
            return "fade", "opening", "", ["本集第一镜：渐显进入"]
        return "cut", "opening", "", ["本场第一镜，前面没有可承接的镜头"]
    same_scene = first.scene_id == second.scene_id
    if _FLASHBACK.search(second.text) and not _FLASHBACK.search(first.text):
        return "dissolve", "flashback", "同一人物的神态或手中物件", ["进入回忆 / 梦境：用叠化区分时空"]
    if _FLASHBACK.search(first.text) and not _FLASHBACK.search(second.text) and not same_scene:
        return "dissolve", "flashback", "同一人物的神态", ["从回忆回到现实：用叠化收回"]
    if _BIG_TIME_JUMP.search(second.text):
        return "fade", "chapter", "", ["大跨度时间跳跃：淡出再淡入，给观众换章的停顿"]
    before, after = _time_of_day(first.text), _time_of_day(second.text)
    if _TIME_PASSAGE.search(second.text) or (before and after and before != after):
        return "dissolve", "time_passage", "同一空间里光线的变化", ["时间流逝：白天与黑夜、前后时刻之间不能直接硬切"]
    if not same_scene or (first.location and second.location and first.location != second.location):
        shape_a, word_a = _shape(first.desc)
        shape_b, word_b = _shape(second.desc)
        if shape_a and shape_a == shape_b:
            return "match_cut", "graphic_match", f"{word_a}与{word_b}同为{shape_a}", ["前后画面有相同的形状，用图形匹配带过场景转换"]
        if _EXIT.search(first.desc) and set(first.subjects) & set(second.subjects):
            return "cut", "action_match", "人物穿过门 / 出口的动作", ["人物的出场动作把两个空间接起来，不会像瞬移"]
        if (_tone(first.text) and _tone(second.text) and _tone(first.text) != _tone(second.text)) or (before and after and before != after):
            return "dissolve", "scene_change", "光色由前镜渐变到后镜", ["两个场景的色调不同：用叠化渐变，避免割裂"]
        return "cut", "scene_change", "声音先行或环境线索（门、窗、道路）", ["换场景：硬切，由声音或环境线索承接空间"]
    if first.subjects and _LOOK.search(first.desc) and (second.is_pov or second.is_insert or not set(first.subjects) & set(second.subjects)):
        return "cut", "eyeline_match", f"{first.subjects[0]}投向画外的视线", ["视线匹配：先给视线，再给所看到的"]
    if (first.is_pov or first.is_insert) and second.subjects:
        return "cut", "reaction", "所见之物带来的反应", ["看过对象之后切回人物的反应"]
    action = _shared_action(first, second)
    if action:
        return "cut", "action_match", f"「{action}」这一个动作", ["动作匹配：在动作进行中切，下一镜接同一动作的后半段"]
    if len(first.subjects) == 1 and len(second.subjects) == 1 and first.subjects != second.subjects:
        return "cut", "shot_reverse", "两人相接的视线", ["正反打：同侧机位，视线方向相对"]
    return "cut", "plain", "人物姿态、朝向与道具归属", ["同一场景内顺接：硬切"]


def _edit_text(cut_kind: str, technique: str, carries: str, first: _Shot | None, second: _Shot, join: str) -> tuple[str, str]:
    label = transition_label(cut_kind)
    if technique == "opening":
        return "", _clip(("渐显进入；" if cut_kind == "fade" else "") + "先建立空间与人物关系；" + _JOIN_IN[join], 500)
    looker = first.subjects[0] if first is not None and first.subjects else "人物"
    out_by_technique = {
        "action_match": f"在{carries}进行到一半时切出，不把动作做完",
        "eyeline_match": f"停在{looker}视线投向画外的瞬间切出",
        "reaction": "所见之物读清后切出",
        "shot_reverse": "在台词收音点或视线落点切出",
        "graphic_match": f"以{carries.split('与')[0] if '与' in carries else '该图形'}充满画面并稳住后切出",
        "time_passage": "画面稳住后叠化淡出（约0.5秒）",
        "flashback": "停在人物神态上叠化淡出（约0.5秒）",
        "chapter": "情绪收住后渐隐至黑（约0.8秒）",
        "scene_change": "在动作或台词收束处切出，环境声先行引出下一场",
        "plain": "在动作接触、视线落点或台词收音点切出",
    }
    in_by_technique = {
        "action_match": "从同一动作的后半段切入，动作方向与速度与上一镜一致",
        "eyeline_match": f"切入{looker}所看的对象，机位取其视线方向",
        "reaction": f"切回{second.subjects[0] if second.subjects else '人物'}的反应，视线方向与发出时一致",
        "shot_reverse": "切到对方，视线方向与上一镜相对，机位留在轴线同一侧",
        "graphic_match": "以相同位置、相同大小的同形物切入，再拉开交代新场景",
        "time_passage": "叠化淡入，先交代时间变化的可见线索（光线、影子、烛长）",
        "flashback": "叠化淡入，色调与现实区分",
        "chapter": "自黑渐显，先建立新的时间与空间",
        "scene_change": "切入新空间的建立画面，由上一镜延续的声音或环境线索承接",
        "plain": "承接上一镜的人物姿态、朝向与道具归属切入",
    }
    # An optical transition needs a settled picture on both sides, whatever the cameras were doing.
    settle = cut_kind in {"dissolve", "fade"}
    join_out = "画面稳住后再转场" if settle else _JOIN_OUT[join]
    join_in = "转场完成、画面稳住后再开始运动" if settle and join.endswith("moving") else "以稳定画面进入" if settle else _JOIN_IN[join]
    return (
        _clip(f"{label}；{out_by_technique[technique]}；{join_out}", 500),
        _clip(f"{label}；{in_by_technique[technique]}；{join_in}", 500),
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
        cuts.append(CutPlan(
            from_shot=(first.shot_id if first is not None and index else 0), to_shot=second.shot_id,
            kind=kind, technique=technique, label=f"{transition_label(kind)}·{_TECHNIQUE_ZH[technique]}"[:60],
            duration_seconds=_CUT_SECONDS[kind], motion_join=join,
            size_step=max(-8, min(8, second.rank - first.rank)) if first is not None else 0,
            lens_change_deg=round(lens_change, 1) if lens_change is not None else None,
            carries=_clip(carries, 300), reasons=reasons, edit_out=edit_out, edit_in=edit_in,
        ))
    return TransitionPlan(cuts=cuts, checks=_checks(views, cuts, stage_plan))


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
            "；".join(f"第{a.shot_id}镜「{a.size}」直接跳到第{b.shot_id}镜「{b.size}」" for a, b in leaps)[:1800]
            + "：景别跨度过大，中间补一个过渡景别，或把后一镜标为冲击 / 反转镜。"
            if leaps else "相邻镜头的景别逐级过渡，没有无理由的大跨度跳变。"
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
                "；".join(f"第{a.shot_id}镜→第{b.shot_id}镜" for a, b in jumps)[:1800]
                + f"：同样的人物、相近的景别，机位方向变化不足{MIN_ANGLE_CHANGE_DEG:g}度，切过去会像画面抽搐；请换机位方向或拉开两级以上景别。"
                if jumps else f"连续拍同一人物时，机位方向变化不小于{MIN_ANGLE_CHANGE_DEG:g}度或景别明显变化。"
            ),
            shot_ids=_ids([b.shot_id for _, b in jumps]),
        ))

    # ---- picture: a look is answered, a point of view has someone looking
    orphans: list[str] = []
    orphan_ids: list[int] = []
    for index, shot in enumerate(views):
        previous = views[index - 1] if index else None
        if shot.is_pov and (previous is None or not previous.subjects):
            orphans.append(f"第{shot.shot_id}镜是主观镜头，但上一镜没有人发出视线")
            orphan_ids.append(shot.shot_id)
        following = views[index + 1] if index + 1 < len(views) else None
        after = views[index + 2] if index + 2 < len(views) else None
        if (
            shot.subjects and _LOOK.search(shot.desc) and following is not None and (following.is_pov or following.is_insert)
            and after is not None and after.subjects and not set(shot.subjects) & set(after.subjects)
        ):
            orphans.append(f"第{shot.shot_id}镜{shot.subjects[0]}看向画外、第{following.shot_id}镜给出所见，其后没有切回{shot.subjects[0]}的反应")
            orphan_ids.append(after.shot_id)
    checks.append(TransitionCheck(
        code="transition_eyeline_answered", passed=not orphans,
        detail="；".join(orphans)[:1900] + "。" if orphans else "视线镜头前有发出者、后有所见与反应，视线连贯。",
        shot_ids=_ids(orphan_ids),
    ))

    # ---- motion: two moves do not pull against each other
    clashes = [(a, b) for a, b in pairs if a.moving and b.moving and a.scene_id == b.scene_id and _moves_oppose(a, b)]
    checks.append(TransitionCheck(
        code="transition_motion_direction", passed=not clashes,
        detail=(
            "；".join(f"第{a.shot_id}镜「{a.move_text}」接第{b.shot_id}镜「{b.move_text}」" for a, b in clashes)[:1800]
            + "：相邻两镜的运动方向相反，动势会互相抵消；让前镜落幅、后镜起幅后再动，或改成同向运动。"
            if clashes else "相邻运动镜头的方向一致或经落幅 / 起幅衔接。"
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
            if staged_a is None or staged_b is None or a.scene_id != b.scene_id or (cut is not None and cut.kind != "cut"):
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
                jumped.append(f"{actor.name}从第{a.shot_id}镜结束到第{b.shot_id}镜开始，位置相差{gap:.1f}米")
                jumped_ids.append(b.shot_id)
        checks.append(TransitionCheck(
            code="transition_state_continuous", passed=not jumped,
            detail="；".join(jumped)[:1800] + "：硬切两侧人物不能瞬移；让上一镜交代人物退开 / 起步，或把走位留在同一镜内完成。" if jumped
            else "硬切两侧的人物位置首尾相接，没有瞬移。",
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
                inverted.append(f"第{a.shot_id}镜已出现「{effect}」，第{b.shot_id}镜才出现「{cause}」")
                inverted_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_cause_before_effect", passed=not inverted,
        detail="；".join(inverted)[:1900] + "：疑似因果倒置，请调换顺序，或把前一镜标为悬念 / 反转镜。" if inverted
        else "动作的因在前、果在后。",
        shot_ids=_ids(inverted_ids),
    ))

    # ---- matching: light and colour do not flip across a hard cut inside one scene
    flips: list[str] = []
    flip_ids: list[int] = []
    for a, b in pairs:
        cut = next((item for item in cuts if item.to_shot == b.shot_id), None)
        if cut is None or cut.kind != "cut" or a.scene_id != b.scene_id:
            continue
        hours = _time_of_day(a.desc), _time_of_day(b.desc)
        tones = _tone(a.desc), _tone(b.desc)
        if all(hours) and hours[0] != hours[1]:
            flips.append(f"第{a.shot_id}镜→第{b.shot_id}镜光线时段不同")
        elif all(tones) and tones[0] != tones[1]:
            flips.append(f"第{a.shot_id}镜{_TONE_ZH[tones[0]]}、第{b.shot_id}镜{_TONE_ZH[tones[1]]}")
        else:
            continue
        flip_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_light_continuity", passed=not flips,
        detail=(
            "；".join(flips)[:1800] + "：同一场景硬切两侧的光色相反；统一主光色温，或在画面里交代光源变化（点灯、云遮月），否则改用叠化。"
            if flips else "硬切两侧的光线与色调协调；时段变化处已安排叠化或淡入淡出。"
        ),
        shot_ids=_ids(flip_ids),
    ))

    # ---- rhythm: durations breathe, fast material is not held
    timed = [shot for shot in views if shot.seconds > 0]
    rhythm: list[str] = []
    rhythm_ids: list[int] = []
    if len(timed) >= 5 and len({shot.seconds for shot in timed}) == 1:
        rhythm.append(f"全部镜头都是{timed[0].seconds}秒，节奏没有张弛；情绪戏留长、动作与信息镜收短")
        rhythm_ids.append(timed[-1].shot_id)
    if len(timed) >= 3:
        typical = median(shot.seconds for shot in timed)
        for shot in timed:
            fast = shot.purpose in _FAST_PURPOSES or any(word in shot.desc for word in _BURST)
            if fast and shot.seconds >= max(8, typical * 1.8):
                rhythm.append(f"第{shot.shot_id}镜是快节奏内容却长达{shot.seconds}秒")
                rhythm_ids.append(shot.shot_id)
    checks.append(TransitionCheck(
        code="transition_rhythm", passed=not rhythm,
        detail="；".join(rhythm)[:1900] + "。" if rhythm else "镜头时长有长短变化，快节奏内容没有被拖长。",
        shot_ids=_ids(rhythm_ids),
    ))

    # ---- rhythm: emotions do not collide
    breaks = [(a, b) for a, b in pairs if (_emotion(a.desc), _emotion(b.desc)) in _COLLISIONS]
    checks.append(TransitionCheck(
        code="transition_emotion_bridge", passed=not breaks,
        detail=(
            "；".join(f"第{a.shot_id}镜→第{b.shot_id}镜" for a, b in breaks)[:1800]
            + "：悲 / 惧与喜剧情绪直接相接，观众来不及转换；中间补一个缓冲镜头（环境、物件或沉默的反应）。"
            if breaks else "相邻镜头的情绪自然过渡，没有突兀断裂。"
        ),
        shot_ids=_ids([b.shot_id for _, b in breaks]),
    ))
    return checks


TABLE_BRIEF = (
    "【镜头衔接】相邻镜景别逐级变化，远景不直接跳特写（冲击 / 反转镜除外）；连续拍同一人物时，景别拉开两级以上或机位方向变化30度以上；"
    "人物看向画外的下一镜给其所见（主观或物件），再切回该人物的反应；动作在进行中切出，下一镜接同一动作的后半段，先因后果；"
    "运动镜头接运动镜头方向一致，接固定镜头前先落幅；动作戏用短镜头、情绪戏留长镜头，时长要有长短变化，悲喜之间留缓冲镜头；"
    "同场景直接硬切，时间流逝与回忆用叠化，章节或大跨度时间用淡入淡出，画面同形时用匹配剪辑。"
)


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
        fields["edit_in"] = into.edit_in or "以稳定画面切入"
        if into.from_shot:
            step = "景别不变" if into.size_step == 0 else f"景别{'推近' if into.size_step > 0 else '拉开'}{abs(into.size_step)}级"
            fields["continuity_in"] = _clip(
                f"承接第{into.from_shot}镜（{into.label}）：带过来的是{into.carries or '人物姿态与朝向'}；{step}；光向、色温与道具归属不变", 1000,
            )
            fields["start_state"] = _clip(
                "同一动作已进行到一半，从这里继续" if into.technique == "action_match"
                else f"上一镜结束时的人物姿态、朝向与道具归属原样保留（{into.label}）", 1000,
            )
        else:
            fields["continuity_in"] = "建立空间与人物关系"
            fields["start_state"] = "建立空间与人物关系"
    if out_of is not None:
        fields["edit_out"] = out_of.edit_out
        fields["continuity_out"] = _clip(
            f"向第{out_of.to_shot}镜交付（{out_of.label}）：{out_of.carries or '人物朝向、道具归属、情绪强度、光向与色温'}", 1000,
        )
        fields["end_state"] = _clip(
            "动作停在进行中，留给下一镜完成" if out_of.technique == "action_match"
            else "运镜落幅稳住，人物姿态与视线定格在可承接的状态" if out_of.motion_join == "moving_to_static"
            else "人物姿态、视线与道具停在下一镜可以直接承接的状态", 1000,
        )
    elif shot_id and total:
        fields["edit_out"] = "本场最后一镜：在情绪或悬念的落点切出，为下一场留出承接"
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
    }


__all__ = [
    "COMPOSITOR_TRANSITIONS", "MAX_SIZE_STEP", "TABLE_BRIEF", "CutPlan", "TransitionCheck", "TransitionPlan",
    "panel_fields", "plan_transitions", "scene_lead_in", "shot_summary",
]
