# -*- coding: utf-8 -*-
"""Enforce the shot-design skill's hard rules on a parsed shot table.

The skill (``backend/skills/shot-design-master``) states the rules in the stage
prompt, but a prompt is a request, not a guarantee: models routinely answer with
a 110s "shot", an abstract emotion word, or five identical medium shots in a row.
This module turns the rules that are mechanically checkable into an audit, and
repairs the one that is mechanically repairable - a clip longer than the selected
video model can render in a single generation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.core.camera_motion import normalize_camera_motion
from app.core.camera_recipes import repeated_move_signature
from app.core.frame_position import flipped_subjects, parse_frame_positions, uses_frame_grammar
from app.core.screenwriting.speech_rate import estimate_spoken_seconds
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds, split_shot_seconds
from app.core.writer_dashboard import parse_duration_seconds


logger = logging.getLogger("app.core.shot_table_rules")

# 景别取词表，与 skills/shot-design-master/references/shot-grammar.md 的主表对应。
SHOT_SIZE_TERMS: tuple[str, ...] = (
    "大远景", "远景", "全景", "中远景", "中全景", "中景", "中近景", "近景",
    "特写", "大特写", "极特写", "侧脸特写", "眼部特写", "嘴部特写", "手部特写",
    "局部特写", "道具特写", "背影", "过肩", "双人", "主观", "空镜",
    "EWS", "WS", "LS", "FS", "MLS", "MS", "MCU", "CU", "BCU", "ECU", "OTS", "POV",
)

# 情绪必须写成可观察的身体细节；这些词单独出现说明只写了结论没写画面。
ABSTRACT_EMOTION_TERMS: tuple[str, ...] = (
    "悲伤", "愤怒", "害怕", "感动", "开心", "难过", "生气", "恐惧",
    "紧张", "兴奋", "失望", "绝望", "震惊", "尴尬", "焦虑", "痛苦",
)
# 只要同句出现具象身体线索，就认为情绪已经落地。
PHYSICAL_CUE_TERMS: tuple[str, ...] = (
    "眉", "眼", "唇", "嘴", "下颌", "牙关", "鼻翼", "呼吸", "肩", "手", "指",
    "背", "喉", "脸颊", "泪", "颤", "攥", "握", "咬", "抿", "垂", "瞳",
)
# 心理描写红线：摄影机拍不到的内容。
INNER_MONOLOGUE_TERMS: tuple[str, ...] = (
    "心想", "内心", "心里", "暗想", "回忆起", "想起", "觉得", "认为", "希望",
)

MIN_DESC_CHARS = 50
MAX_SAME_SIZE_RUN = 2
# 张力法则：镜头默认静止，运动只留给开头、呼吸和爆发；一场里带运动的镜头超过这个比例
# 就成了"监控回放"。
MAX_MOVING_SHOT_RATIO = 0.7
# 爆发前要有静置蓄力：前一镜至少停这么久、且镜头不动。
MIN_BUILDUP_SECONDS = 3
BURST_TERMS: tuple[str, ...] = (
    "爆发", "挥剑", "挥刀", "砍", "劈", "冲上", "冲向", "撞", "摔", "怒吼", "开枪", "爆炸", "扑向", "出拳", "踢",
)
# 爆发镜越短越有冲击力：6 秒的爆发像放烟花，不像打人。
MAX_BURST_SECONDS = 4
# 一句台词要在本镜内说完，且两端各留一点静默；同一镜不安排两个人说话。
SPEECH_HEADROOM = 0.7
# 分镜表里台词写成「角色名：台词」；说话人名很短，正文里的冒号句（他说：…）不会被当成第二个说话人。
_SPEAKER_LINE = re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,5})\s*[：:]")
# 竖屏同框能画清楚的人物数；第三人起必须虚化、背影或剪影。
MAX_CLEAR_CHARACTERS_PORTRAIT = 2
# 特写是标点不是正文：一场戏里给得太多，冲击力就贬值了。
MAX_CLOSE_UPS_PER_SCENE = 3
MAX_CLOSE_UPS_PER_FIGHT_SCENE = 2
CLOSE_UP_TERMS: tuple[str, ...] = ("大特写", "极特写", "特写", "ECU", "BCU", "CU")
# 视频模型没有逐帧控制力：写「定格」只会让画面真的停住。冲击靠白闪、震镜、径向模糊做。
FROZEN_FRAME_TERMS: tuple[str, ...] = (
    "定格", "停格", "顿帧", "凝滞", "静滞", "子弹时间", "时间静止", "时停", "画面冻结", "绝对静默", "hit-stop",
)
# 声音一层是底噪、一层是动作；层数堆多了混成一团。
MAX_AMBIENT_LAYERS = 2
MAX_ACTION_SOUNDS = 2
_SOUND_SPLIT = re.compile(r"[·、，,+＋]|以及|还有")


@dataclass
class ShotIssue:
    shot_id: Any
    rule: str
    detail: str
    severity: str = "warning"


@dataclass
class ShotTableAudit:
    shots: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ShotIssue] = field(default_factory=list)
    repaired: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.ok:
            return "分镜表通过全部硬性规则检查"
        by_rule: dict[str, int] = {}
        for issue in self.issues:
            by_rule[issue.rule] = by_rule.get(issue.rule, 0) + 1
        parts = "；".join(f"{rule} × {count}" for rule, count in sorted(by_rule.items()))
        repaired = f"，已自动修复 {self.repaired} 处超长镜头" if self.repaired else ""
        return f"分镜表检查发现 {len(self.issues)} 项问题：{parts}{repaired}"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def speakers_in(dialogue: str, cast: Sequence[str] = ()) -> list[str]:
    """Who the dialogue cell gives lines to, in order.

    With a cast, only labels naming someone in it count, so a colon inside a line
    (「他说：走」) is not mistaken for a second speaker.
    """
    names = [name.strip() for name in _SPEAKER_LINE.findall(dialogue) if name.strip()]
    known = {str(name).strip() for name in cast if str(name).strip()}
    return [name for name in names if name in known] if known else names


def _spoken_text(dialogue: str) -> str:
    """The dialogue without the speaker labels, which are not spoken aloud."""
    return _SPEAKER_LINE.sub(" ", dialogue)


def _sound_layers(sound: str) -> tuple[int, int]:
    """``(ambience layers, action sounds)`` of one shot's sound cell."""
    ambience, action = "", ""
    for part in re.split(r"[；;]", sound):
        label, _, body = part.partition("：")
        if not body:
            label, _, body = part.partition(":")
        if "环境" in label or "底噪" in label:
            ambience = body
        elif "动作" in label or "音效" in label and not ambience:
            action = body
    if not ambience and not action:
        ambience = sound
    def _count(text: str) -> int:
        return len([item for item in _SOUND_SPLIT.split(text) if item.strip() and item.strip() not in {"无", "none"}])
    return _count(ambience), _count(action)


def audit_shot_table(
    shots: Sequence[dict[str, Any]],
    *,
    video_model: str = "",
    repair: bool = True,
    scene_kind: str = "",
) -> ShotTableAudit:
    """Check a parsed shot table against the skill's mechanically checkable rules.

    With ``repair`` the returned shots have over-long durations cut down to the
    model's single-clip ceiling; every other rule is reported, never silently
    rewritten, because only a human can decide how to re-stage a shot.

    ``scene_kind`` tightens the rules a fight scene is judged by (close-up quota).
    """
    cap = max_shot_seconds(video_model)
    fight = "fight" in str(scene_kind or "").lower()
    close_ups = 0
    audit = ShotTableAudit()
    previous_size = ""
    same_size_run = 0
    previous_positions = []
    previous_static = True
    previous_seconds = 0
    previous_shot: dict[str, Any] | None = None
    moving_shots = 0
    motion_declared = 0

    for index, raw in enumerate(shots):
        if not isinstance(raw, dict):
            continue
        shot = dict(raw)
        shot_id = shot.get("shot_id", index + 1)
        desc = _text(shot.get("desc"))
        size = _text(shot.get("size"))

        seconds = parse_duration_seconds(shot.get("duration"))
        if seconds > cap:
            audit.issues.append(ShotIssue(
                shot_id, "时长超模型上限",
                f"{seconds}s 超过 {video_model or '未指定模型'} 的单镜上限 {cap}s",
                "error",
            ))
            if repair:
                slices = split_shot_seconds(seconds, video_model)
                shot["duration"] = f"{slices[0]}s" if slices else f"{cap}s"
                audit.repaired += 1
        elif seconds and seconds < MIN_SHOT_SECONDS:
            audit.issues.append(ShotIssue(
                shot_id, "时长低于下限",
                f"{seconds}s 低于可提交下限 {MIN_SHOT_SECONDS}s",
            ))

        if size and not _has_any(size.upper(), (term.upper() for term in SHOT_SIZE_TERMS)):
            audit.issues.append(ShotIssue(shot_id, "景别不在词典内", f"「{size}」不是标准景别术语"))

        if size and size == previous_size:
            same_size_run += 1
            if same_size_run >= MAX_SAME_SIZE_RUN:
                audit.issues.append(ShotIssue(
                    shot_id, "同景别连续堆叠",
                    f"连续 {same_size_run + 1} 镜都是「{size}」，需远近交替",
                ))
        else:
            same_size_run = 0
        previous_size = size

        if desc and len(desc) < MIN_DESC_CHARS:
            audit.issues.append(ShotIssue(
                shot_id, "画面内容过短", f"{len(desc)} 字，规范要求不少于 {MIN_DESC_CHARS} 字",
            ))

        if _has_any(desc, INNER_MONOLOGUE_TERMS):
            hit = next(term for term in INNER_MONOLOGUE_TERMS if term in desc)
            audit.issues.append(ShotIssue(
                shot_id, "出现心理描写", f"「{hit}」是摄影机拍不到的内容", "error",
            ))

        if _has_any(desc, ABSTRACT_EMOTION_TERMS) and not _has_any(desc, PHYSICAL_CUE_TERMS):
            hit = next(term for term in ABSTRACT_EMOTION_TERMS if term in desc)
            audit.issues.append(ShotIssue(
                shot_id, "情绪未具象化", f"只写了「{hit}」，没有可观察的面部或肢体细节",
            ))

        # 站位与视线写成观众看到的画面坐标，而不是人物自己的左右。
        characters = [
            name.strip() for name in (
                shot.get("characters") if isinstance(shot.get("characters"), list)
                else re.split(r"[、，,/]", _text(shot.get("characters")))
            ) if str(name).strip() and str(name).strip() not in {"无", "空镜"}
        ]
        positions = parse_frame_positions(desc, characters) if characters and desc else []
        if characters and desc and not uses_frame_grammar(desc):
            audit.issues.append(ShotIssue(
                shot_id, "构图未用镜头坐标",
                "人物站位请写成画面区域 + 深度层 + 屏幕朝向（如：画面左侧三分之一的中景，朝向画面右侧）",
            ))
        flipped = flipped_subjects(previous_positions, positions)
        if flipped and not _has_any(desc, ("越轴", "转身", "回身", "中性镜头", "换位")):
            audit.issues.append(ShotIssue(
                shot_id, "视线左右翻转",
                f"{'、'.join(flipped)} 的屏幕朝向与上一镜相反，疑似越轴；要么保持上一镜站位，要么写明转身或中性过渡镜",
            ))
        if positions:
            previous_positions = positions

        # 一句台词必须在本镜说完：按项目统一语速换算，两端各留一点静默。
        dialogue = _text(shot.get("dialogue"))
        speakers = speakers_in(dialogue, characters)
        if len(set(speakers)) > 1:
            audit.issues.append(ShotIssue(
                shot_id, "一镜多个说话人",
                f"本镜写了 {'、'.join(dict.fromkeys(speakers))} 的台词；一镜只留给一个人说话，其余人闭口给反应",
            ))
        spoken = estimate_spoken_seconds(_spoken_text(dialogue))
        if spoken and seconds and spoken > seconds * SPEECH_HEADROOM:
            audit.issues.append(ShotIssue(
                shot_id, "台词超出本镜时长",
                f"台词约需 {spoken:.1f}s，本镜 {seconds}s（可用 {seconds * SPEECH_HEADROOM:.1f}s，两端各留静默）；"
                "请加长本镜或按语气停顿拆句",
            ))

        sound_text = _text(shot.get("sound"))
        if sound_text:
            ambience, action = _sound_layers(sound_text)
            if ambience > MAX_AMBIENT_LAYERS or action > MAX_ACTION_SOUNDS:
                audit.issues.append(ShotIssue(
                    shot_id, "声音层数超标",
                    f"环境音 {ambience} 层、动作音 {action} 个；一镜最多 {MAX_AMBIENT_LAYERS} 层环境音与 "
                    f"{MAX_ACTION_SOUNDS} 个动作音，多了会混成一团",
                ))

        if len(characters) > MAX_CLEAR_CHARACTERS_PORTRAIT:
            audit.issues.append(ShotIssue(
                shot_id, "同框清晰人物过多",
                f"{len(characters)} 人同框；竖屏一镜最多画清 {MAX_CLEAR_CHARACTERS_PORTRAIT} 人，"
                "第三人起请写成虚化、背影或剪影",
            ))

        if size and _has_any(size.upper(), (term.upper() for term in CLOSE_UP_TERMS)):
            close_ups += 1

        if _has_any(desc, FROZEN_FRAME_TERMS):
            hit = next(term for term in FROZEN_FRAME_TERMS if term in desc)
            audit.issues.append(ShotIssue(
                shot_id, "写了模型做不到的定格",
                f"「{hit}」会让画面真的停住；冲击点改用白闪一两帧 + 镜头猛震 + 命中点径向模糊 + 速度线",
            ))

        if _has_any(desc, BURST_TERMS) and seconds > MAX_BURST_SECONDS:
            audit.issues.append(ShotIssue(
                shot_id, "爆发镜过长",
                f"爆发镜 {seconds}s，超过 {MAX_BURST_SECONDS}s 就散了；把余韵拆到下一镜去",
            ))

        motion_text = _text(shot.get("motion"))
        if motion_text:
            motion_declared += 1
            canonical, _ = normalize_camera_motion(motion_text)
            is_static = canonical == "Static"
            if not is_static:
                moving_shots += 1
        else:
            is_static = True
        if _has_any(desc, BURST_TERMS) and index > 0 and (
            not previous_static or (previous_seconds and previous_seconds < MIN_BUILDUP_SECONDS)
        ):
            audit.issues.append(ShotIssue(
                shot_id, "爆发前缺少静置蓄力",
                f"爆发镜前一镜应至少静止 {MIN_BUILDUP_SECONDS}s 蓄力，再用短促急推或骤停放大冲击",
            ))
        previous_static = is_static
        previous_seconds = seconds

        # 防撞镜：画风质感锁死，相邻镜至少换掉运动 / 角度 / 节奏之一。
        current = {**shot, "_seconds": seconds}
        if previous_shot is not None and motion_text:
            shared = repeated_move_signature(previous_shot, current)
            if shared:
                audit.issues.append(ShotIssue(
                    shot_id, "相邻镜运镜撞款",
                    f"与上一镜同为「{shared}」，请换掉运动、角度或节奏中的一项",
                ))
        previous_shot = current

        audit.shots.append(shot)

    if motion_declared >= 4 and moving_shots / motion_declared > MAX_MOVING_SHOT_RATIO:
        audit.issues.append(ShotIssue(
            audit.shots[-1].get("shot_id", len(audit.shots)), "运镜过密",
            f"{moving_shots}/{motion_declared} 镜带镜头运动，超过 {int(MAX_MOVING_SHOT_RATIO * 100)}%；"
            "以固定镜头为主，运动只留给开头、呼吸式微动和爆发瞬间",
        ))

    close_up_cap = MAX_CLOSE_UPS_PER_FIGHT_SCENE if fight else MAX_CLOSE_UPS_PER_SCENE
    if close_ups > close_up_cap and audit.shots:
        audit.issues.append(ShotIssue(
            audit.shots[-1].get("shot_id", len(audit.shots)), "特写超配额",
            f"本场 {close_ups} 个特写，超过{'武戏' if fight else ''}配额 {close_up_cap} 个；"
            "特写是标点，只留给冲击峰值与转折帧",
        ))

    if len(audit.shots) == 1:
        audit.issues.append(ShotIssue(
            audit.shots[0].get("shot_id", 1), "整集仅一个镜头", "一集必须拆成多个镜头", "error",
        ))

    return audit


def audit_and_log(
    shots: Sequence[dict[str, Any]], *, video_model: str, task_id: str = "", scene_kind: str = "",
) -> list[dict[str, Any]]:
    """Audit, log the findings, and return the (possibly repaired) shot list."""
    audit = audit_shot_table(shots, video_model=video_model, scene_kind=scene_kind)
    if audit.issues:
        logger.warning("[Stage4] %s (task=%s)", audit.summary(), task_id or "-")
        for issue in audit.issues[:20]:
            logger.info("[Stage4] 镜%s %s：%s", issue.shot_id, issue.rule, issue.detail)
    return audit.shots
