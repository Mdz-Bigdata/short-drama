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

# A leap of this many size steps (全景 → 特写 is 5) needs a reason.
MAX_SIZE_STEP = 4
MAX_STATE_JUMP_M = 0.8
_CUT_SECONDS: dict[str, float] = {"cut": 0.0, "match_cut": 0.0, "dissolve": 0.5, "fade": 0.8, "push_pull": 0.5}
# What the compositor calls each device.
COMPOSITOR_TRANSITIONS: dict[str, str] = {
    # 旧数据里的硬切也按短交叉过渡合成，成片里不出现生硬的跳切。
    "cut": "crossfade", "match_cut": "match_cut", "dissolve": "crossfade", "fade": "dip_to_black", "push_pull": "crossfade",
}
_TECHNIQUE_ZH: dict[str, str] = {
    "opening": "开场", "plain": "顺接", "shot_reverse": "正反打", "action_match": "动作匹配",
    "eyeline_match": "视线匹配", "reaction": "回到反应", "graphic_match": "图形匹配",
    "time_passage": "时间流逝", "flashback": "回忆", "chapter": "章节转换", "scene_change": "场景转换",
    "action_rhyme": "动作呼应", "occlusion": "遮挡转场", "object_carry": "同物换境",
}
# 这种接法回看成片时要核对什么。
_WATCH: dict[str, str] = {
    "opening": "空间、人物关系是否一眼读清",
    "plain": "人物姿态、朝向、道具归属；观众的注意力位置有没有跨过整个画面",
    "shot_reverse": "视线高度、轴线同侧、两边焦段是否接近",
    "action_match": "动作阶段、速度、用手、道具状态、重心；后镜不重演前镜做过的部分",
    "eyeline_match": "谁在看、看向哪里、所见之物的方位",
    "reaction": "反应的视线方向与发出时一致",
    "graphic_match": "图形的中心位置、大小、边缘、明暗",
    "time_passage": "机位与陈设不变，只有光线和天气变；观众能读出过了多久",
    "flashback": "色调与现实区分，能读出何时进、何时回",
    "chapter": "新的时间与空间是否一进来就交代",
    "scene_change": "新空间的建立画面；声音来源听得清",
    "action_rhyme": "运动方向、节奏、落点；情节或环境要说明为什么这样接，不等于两场戏同时发生",
    "occlusion": "切点处是否遮满；遮挡边缘的方向和速度；摄影机运动与前景滑动方向分开核对",
    "object_carry": "形状、缺口、颜色等辨识特征不变；后续动作或对白要交代它为何在这里",
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
# 分镜明说了前景遮过镜头才算遮挡转场：「手撑着墙」不算。
_OCCLUSION = re.compile(r"(衣袖|袖口|袖子|披风|斗篷|手掌|门板|屏风|墙面|墙|廊柱|立柱|背影|人群)[^，。；]{0,8}(?:遮住|遮满|挡住|盖住|掠过|扫过|贴近镜头|充满画面|占满画面)")
# 能跨场景认出来的小物件：同一个物件换了环境，线索就接上了。
_TOKENS = ("令牌", "铜牌", "玉佩", "玉坠", "戒指", "钥匙", "信封", "密信", "手帕", "发簪", "怀表", "项链", "吊坠", "地图", "卷轴", "火折子", "香囊")
_DIRECTION = re.compile(r"(?:向|往|朝)(左|右)(?:走|跑|奔|行|冲|飞|驶|移动|前进)|从(左|右)(?:向|往|到|至)(?:左|右)")
_TURNED = re.compile(r"转身|掉头|折返|回身|调头|返回|迎面|相向|对向")
_DONE = re.compile(r"站稳|站直|落定|收势|做完|彻底|完全|已经")
_PICKUP = re.compile(r"继续|接着|后半|余势|顺势")
_FAST_MOVE = re.compile(r"快速|急推|急拉|急摇|猛推|猛拉|甩镜|甩向|极速|高速")
_SLOW_MOVE = re.compile(r"缓慢|缓缓|缓推|缓移|缓拉|慢推|慢移|轻推|微推|微移")
_VIOLENT_MOVE = re.compile(r"剧烈|大幅|猛烈|疯狂|地震|shaky", re.IGNORECASE)
_ENERGY_MOTIVE = re.compile(r"声|响|碎|喊|叫|惊|突然|猛地|骤然|冲|扑|撞|爆|转身|回头")
# 两镜的描述相似到这个程度，又没有新动作和新台词，切过去就只是换了个机位。
SAME_INFO_RATIO = 0.82
# 同一人物在画面里挪了这么多（画面宽为 100）观众的眼睛就得跨屏重新找人。
MAX_ATTENTION_JUMP = 45.0
STATIC_RUN = 4
# One action, cut in two: a family names the same movement at different moments.
_ACTION_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("推门", "推开", "门开", "门被推开", "开门", "拉开门"), ("拔剑", "拔刀", "出鞘", "抽剑", "抽刀"),
    ("挥剑", "挥刀", "劈", "砍", "斩"), ("伸手", "抓住", "握住", "攥住", "接过", "递"), ("转身", "回身", "回头", "扭头"),
    ("起身", "站起", "爬起"), ("坐下", "落座"), ("跪下", "跪倒", "跪地"), ("倒地", "倒下", "摔倒", "栽倒"),
    ("举杯", "饮下", "喝下", "仰头饮"), ("抬手", "扬手", "挥手", "抬起手"), ("奔", "跑", "冲向", "冲进", "冲出"),
    ("跃起", "跳下", "跃下", "腾空"), ("扔", "掷", "抛", "摔碎", "砸"), ("点燃", "烧", "燃起", "火舌"),
    ("展开", "抖开", "摊开", "翻开", "合上"), ("出拳", "挥拳", "踢", "踹", "格挡"), ("落笔", "落槌", "落子", "击鼓", "敲鼓", "捶下"),
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
    ("圆形", ("瞳孔", "眼眸", "月亮", "圆月", "满月", "太阳", "铜镜", "圆镜", "灯笼", "灯罩", "鼓面", "钟表", "车轮", "碗口", "井口", "玉璧", "铜钱", "星球")),
    ("竖线", ("剑身", "长剑", "立柱", "廊柱", "门缝", "烛台", "旗杆", "竹", "塔")),
    ("横线", ("地平线", "案几", "长桥", "城墙", "水面", "屋檐")),
    ("斜线", ("石阶", "扶手", "楼梯", "阶梯", "山脊", "斜坡", "缆绳")),
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
    sound_join: SoundJoin = ""
    sound_note: str = Field("", max_length=200)


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
    size = str(raw.get("size") or "中景")
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
        return "l_cut", "L-cut：上一镜这句话越过切点再留一小段，画面先切过去，别让声音和画面同时断"
    if moved:
        return "j_cut", "J-cut：下一场的声音先进来，再切画面；交接时听得清声音来自哪里"
    return "", ""


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
    "static_to_static": "画面稳住，衔接点落在动作或台词的停顿上",
    "moving_to_moving": "运动中顺势衔接，方向与速度连续，不留落幅",
    "moving_to_static": "运镜在衔接点前约半秒落幅稳住再过渡",
    "static_to_moving": "画面稳住后再过渡",
}
_JOIN_IN: dict[str, str] = {
    "static_to_static": "以稳定画面进入",
    "moving_to_moving": "从运动中起，方向与速度承接上一镜",
    "moving_to_static": "以稳定画面进入，承接上一镜落幅",
    "static_to_moving": "先以起幅稳住约半秒再开始运动",
}


def _decide(first: _Shot | None, second: _Shot, *, first_of_episode: bool) -> tuple[CutKind, Technique, str, list[str]]:
    """``(kind, technique, what carries across, why)`` for the cut into ``second``."""
    if first is None:
        if first_of_episode:
            return "fade", "opening", "", ["本集第一镜：渐显进入"]
        return "dissolve", "opening", "", ["本场第一镜：渐显进入，不硬切"]
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
            return "match_cut", "action_match", "人物穿过门 / 出口的动作", ["人物的出场动作把两个空间连贯接起来，不会像瞬移"]
        token = next((word for word in _TOKENS if word in first.desc and word in second.desc), "")
        if token:
            return "match_cut", "object_carry", f"同一个{token}", ["同物换境：观众认出同一线索，但它为什么在这里要靠后面的动作或对白交代"]
        rhyme = _rhyming_action(first, second)
        if all(rhyme):
            return "match_cut", "action_rhyme", f"{rhyme[0]}与{rhyme[1]}的相似运动", ["相似动作呼应：方向、节奏、落点相近，形成联想；不表示人物到了对方那里，也不说明两场同时发生"]
        hidden = _OCCLUSION.search(first.desc)
        if hidden:
            return "push_pull", "occlusion", f"{hidden.group(1)}遮过镜头", ["前景遮满画面后切，下一镜从相近的色块和质感开始再揭开新空间"]
        if (_tone(first.text) and _tone(second.text) and _tone(first.text) != _tone(second.text)) or (before and after and before != after):
            return "dissolve", "scene_change", "光色由前镜渐变到后镜", ["两个场景的色调不同：用叠化渐变，避免割裂"]
        return "push_pull", "scene_change", "前景遮挡或镜头推进带入新空间，环境声先行", ["换场景：用前景遮挡或镜头推拉带入新空间，声音先行承接，不硬切"]
    if first.subjects and _LOOK.search(first.desc) and (second.is_pov or second.is_insert or not set(first.subjects) & set(second.subjects)):
        return "match_cut", "eyeline_match", f"{first.subjects[0]}投向画外的视线", ["视线匹配：先给视线，镜头顺视线方向带到所看到的"]
    if (first.is_pov or first.is_insert) and second.subjects:
        return "match_cut", "reaction", "所见之物带来的反应", ["看过对象之后顺势回到人物的反应"]
    action = _shared_action(first, second)
    if action:
        return "match_cut", "action_match", f"「{action}」这一个动作", ["动作匹配：在动作进行中衔接，下一镜接同一动作的后半段"]
    if len(first.subjects) == 1 and len(second.subjects) == 1 and first.subjects != second.subjects:
        return "match_cut", "shot_reverse", "两人相接的视线", ["正反打：镜头沿轴线同侧顺势移向对方，视线相接，不硬切"]
    return "match_cut", "plain", "人物姿态、朝向与道具归属", ["同一场景内顺接：姿态、朝向、道具与声音延续，不硬切"]


def _edit_text(cut_kind: str, technique: str, carries: str, first: _Shot | None, second: _Shot, join: str) -> tuple[str, str]:
    label = transition_label(cut_kind)
    if technique == "opening":
        return "", _clip(("渐显进入；" if cut_kind == "fade" else "") + "先建立空间与人物关系；" + _JOIN_IN[join], 500)
    looker = first.subjects[0] if first is not None and first.subjects else "人物"
    out_by_technique = {
        "action_match": f"在{carries}进行到一半时顺势衔接到下一镜，动作不中断",
        "eyeline_match": f"在{looker}视线投向画外时，镜头顺视线方向带向所见之物",
        "reaction": "所见之物读清后，镜头顺势回到人物",
        "shot_reverse": "在台词收音点或视线落点，镜头沿轴线同侧顺势移向对方",
        "graphic_match": f"以{carries.split('与')[0] if '与' in carries else '该图形'}充满画面并稳住后过渡",
        "time_passage": "画面稳住后叠化淡出（约0.5秒）",
        "flashback": "停在人物神态上叠化淡出（约0.5秒）",
        "chapter": "情绪收住后渐隐至黑（约0.8秒）",
        "scene_change": "在动作或台词收束处，前景遮挡物掠过或镜头推进带出本场，环境声先行引出下一场",
        "action_rhyme": f"在{carries.split('的相似运动')[0]}运动到一半时过渡，落点留在画面同一位置",
        "occlusion": f"{carries.split('遮过镜头')[0]}贴近镜头直到遮满画面，半遮藏不住背景的变化",
        "object_carry": f"{carries}停在画面中央、辨识特征看得清时过渡",
        "plain": "在动作接触、视线落点或台词收音点顺势衔接",
    }
    in_by_technique = {
        "action_match": "从同一动作的后半段接续，动作方向与速度与上一镜一致，用手、道具状态和重心不变，不重演已做过的部分",
        "eyeline_match": f"顺着{looker}的视线方向接续其所看的对象",
        "reaction": f"回到{second.subjects[0] if second.subjects else '人物'}的反应，视线方向与发出时一致",
        "shot_reverse": "接续到对方，视线方向与上一镜相对，机位留在轴线同一侧",
        "graphic_match": "以相同位置、相同大小的同形物接续，再拉开交代新场景",
        "time_passage": (
            "叠化淡入，机位与陈设不变，只让光线和天气变化（光线、影子、烛长）"
            if first is not None and first.location and first.location == second.location
            else "叠化淡入，先交代时间变化的可见线索（光线、影子、烛长）"
        ),
        "flashback": "叠化淡入，色调与现实区分",
        "chapter": "自黑渐显，先建立新的时间与空间",
        "scene_change": "遮挡移开或镜头推进后进入新空间的建立画面，由上一镜延续的声音或环境线索承接",
        "action_rhyme": "相同方向、相近节奏的运动落在画面同一位置，再带出这一场的环境与人物",
        "occlusion": "从相近的色块和质感开始，遮挡沿同一方向滑开后揭示新空间，前景滑动方向与摄影机运动方向分开写",
        "object_carry": f"{carries}的形状和特征不变、换到新环境里，先看清物件再交代它为何在此",
        "plain": "承接上一镜的人物姿态、朝向与道具归属自然接续",
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
        sound_join, sound_note = _sound_join(first, second, kind, technique)
        cuts.append(CutPlan(
            from_shot=(first.shot_id if first is not None and index else 0), to_shot=second.shot_id,
            kind=kind, technique=technique, label=f"{transition_label(kind)}·{_TECHNIQUE_ZH[technique]}"[:60],
            duration_seconds=_CUT_SECONDS[kind], motion_join=join,
            size_step=max(-8, min(8, second.rank - first.rank)) if first is not None else 0,
            lens_change_deg=round(lens_change, 1) if lens_change is not None else None,
            carries=_clip(carries, 300), reasons=reasons, edit_out=edit_out, edit_in=edit_in,
            sound_join=sound_join, sound_note=sound_note,
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
                jumped.append(f"{actor.name}从第{a.shot_id}镜结束到第{b.shot_id}镜开始，位置相差{gap:.1f}米")
                jumped_ids.append(b.shot_id)
        checks.append(TransitionCheck(
            code="transition_state_continuous", passed=not jumped,
            detail="；".join(jumped)[:1800] + "：衔接两侧人物不能瞬移；让上一镜交代人物退开 / 起步，或把走位留在同一镜内完成。" if jumped
            else "衔接两侧的人物位置首尾相接，没有瞬移。",
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
        if cut is None or cut.kind not in {"cut", "match_cut"} or a.scene_id != b.scene_id:
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
            "；".join(flips)[:1800] + "：同一场景衔接两侧的光色相反；统一主光色温，或在画面里交代光源变化（点灯、云遮月），否则改用叠化。"
            if flips else "衔接两侧的光线与色调协调；时段变化处已安排叠化或淡入淡出。"
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
            "；".join(f"第{a.shot_id}镜→第{b.shot_id}镜" for a, b in same)[:1800]
            + "：景别、运镜、内容都差不多，切过去只是换了个机位；给后一镜一个新动作、新表情或新信息，或者并成一镜。"
            if same else "每次换镜都带来了新的动作或信息。"
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
            "；".join(f"第{a.shot_id}镜已做完「{action}」，第{b.shot_id}镜又写了一遍" for a, b, action in replays)[:1800]
            + "：人物会像被按回去重来；前镜停在动作进行中，后镜写明从哪个阶段接着做。"
            if replays else "没有把做完的动作重演一遍。"
        ),
        shot_ids=_ids([b.shot_id for _, b, _ in replays]),
    ))

    # ---- direction: someone walking right does not walk left without showing why
    flips = [
        (a, b) for a, b in pairs
        if a.scene_id == b.scene_id and set(a.subjects) & set(b.subjects) and _heading(a.desc) and _heading(b.desc)
        and _heading(a.desc) != _heading(b.desc) and not _TURNED.search(f"{a.desc} {b.desc}")
    ]
    checks.append(TransitionCheck(
        code="transition_screen_direction", passed=not flips,
        detail=(
            "；".join(f"第{a.shot_id}镜→第{b.shot_id}镜" for a, b in flips)[:1800]
            + "：同一人物的行进方向在画面里反了，又没有交代原因，观众会以为他掉头了；补一个转身或全景，或改成同向。"
            if flips else "人物的行进方向连续，方向改变都有交代。"
        ),
        shot_ids=_ids([b.shot_id for _, b in flips]),
    ))

    # ---- energy: two moves of the same size, and a burst has a reason
    energy: list[str] = []
    energy_ids: list[int] = []
    for a, b in pairs:
        if a.scene_id != b.scene_id:
            continue
        if a.moving and b.moving and ((_FAST_MOVE.search(a.move_text) and _SLOW_MOVE.search(b.move_text)) or (_SLOW_MOVE.search(a.move_text) and _FAST_MOVE.search(b.move_text))):
            energy.append(f"第{a.shot_id}镜「{a.move_text}」接第{b.shot_id}镜「{b.move_text}」速度差太多，像撞上减速带")
            energy_ids.append(b.shot_id)
        elif _FAST_MOVE.search(b.move_text) and not a.moving and b.purpose not in _FAST_PURPOSES and not _ENERGY_MOTIVE.search(f"{a.desc} {b.desc}"):
            energy.append(f"第{b.shot_id}镜「{b.move_text}」前面什么都没发生")
            energy_ids.append(b.shot_id)
    checks.append(TransitionCheck(
        code="transition_motion_energy", passed=not energy,
        detail="；".join(energy)[:1800] + "：运动能量要有来由和落点；用一声响动、一个动作带起来，或把两边的速度拉近。" if energy
        else "相邻镜头的运动能量相近，加速都有来由。",
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
            breath.append(f"{scene_id or '本场'}{len(shots)}镜全部固定机位，连起来像幻灯片；挑关键转折处给一个缓推或跟拍")
            breath_ids.append(shots[-1].shot_id)
    for shot in views:
        if shot.subjects and _VIOLENT_MOVE.search(shot.move_text):
            breath.append(f"第{shot.shot_id}镜人物镜头运镜「{shot.move_text}」幅度太大，人物容易崩坏；写成轻微的，大幅运动留给空镜")
            breath_ids.append(shot.shot_id)
    checks.append(TransitionCheck(
        code="transition_camera_breath", passed=not breath,
        detail="；".join(breath)[:1900] + "。" if breath else "运镜有呼吸，人物镜头的运动幅度克制。",
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
                    jumps.append(f"{state.name}从第{a.shot_id}镜到第{b.shot_id}镜在画面里横跨了{abs(state.x - held.x):.0f}%")
                    jump_ids.append(b.shot_id)
                    break
        checks.append(TransitionCheck(
            code="transition_attention_jump", passed=not jumps,
            detail="；".join(jumps)[:1800] + "：景别相近时眼睛要跨屏重新找人，会漏掉后一镜开头的信息；让主体靠近上一镜的落点。" if jumps
            else "相邻镜头的主体位置相近，观众的视线交接得过去。",
            shot_ids=_ids(jump_ids),
        ))
    return checks


def _heading(text: str) -> str:
    found = _DIRECTION.search(text)
    return (found.group(1) or ("左" if found.group(2) == "右" else "右")) if found else ""


TABLE_BRIEF = (
    "【镜头衔接】相邻镜景别逐级变化，远景不直接跳特写（冲击 / 反转镜除外）；连续拍同一人物时，景别拉开两级以上或机位方向变化30度以上；"
    "人物看向画外的下一镜给其所见（主观或物件），再切回该人物的反应；动作在进行中切出，下一镜接同一动作的后半段，先因后果；"
    "运动镜头接运动镜头方向一致，接固定镜头前先落幅；动作戏用短镜头、情绪戏留长镜头，时长要有长短变化，悲喜之间留缓冲镜头；"
    "转场不用硬切，镜与镜之间要连贯、顺畅、自然过渡：同场景用动作匹配、视线引导或镜头顺势运动衔接，"
    "换场景用前景遮挡或镜头推拉带入并让声音先行，时间流逝与回忆用叠化，章节或大跨度时间用淡入淡出，画面同形时用图形匹配。"
    "每次换镜先想清这一切新增了什么信息、要让观众跟住什么；同一动作换景别时后一镜从略往后的阶段接，不重演；"
    "运镜跟着戏走：建立用摇或固定，推进用缓推缓移，冲突用手持或快推，释放用缓拉或固定，慢推是悬念、快推是震惊；人物镜头幅度要轻，空镜可以大一些。"
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
        "sound_join": cut.sound_join, "sound_note": cut.sound_note, "watch": _WATCH[cut.technique],
    }


__all__ = [
    "COMPOSITOR_TRANSITIONS", "MAX_SIZE_STEP", "TABLE_BRIEF", "CutPlan", "TransitionCheck", "TransitionPlan",
    "panel_fields", "plan_transitions", "scene_lead_in", "shot_summary",
]
