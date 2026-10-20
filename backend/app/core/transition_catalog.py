"""Transition vocabulary: classic cut types plus media-driven categories.

Editing-book types (cut, fade, dissolve, flash, wipe, push/pull, match cut,
montage) carry the pacing; media categories (occlusion, camera move, action,
light, time-lapse, emotion, space jump) carry the *how* for AI clips, where a
transition is generated inside the shot rather than in an NLE. Every transition
can be written with one formula: outgoing action + medium + camera move +
incoming scene + light mood.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# value, zh label, en, usage, emotions, pacing
TRANSITION_TYPES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("cut", "硬切", "hard cut", "同场景动作衔接、正反打、节奏推进", "干脆、直接", "any"),
    ("fade", "淡入淡出", "fade in/out", "开场结尾、回忆梦境、时间跳转", "宁和、怅惘、怀念", "slow"),
    ("dissolve", "叠化", "dissolve", "时间流逝、回忆过渡、季节变化", "平实、缱绻、念旧", "slow"),
    ("flash", "闪白/闪黑", "flash white/black", "闪回回忆、打斗冲击后、激烈碰撞", "强烈、惊惧、屏息", "fast"),
    ("wipe", "划像", "wipe", "风格化表达、节奏增强、时空跳跃", "跃动、干脆、摩登", "fast"),
    ("push_pull", "推拉转场", "push/pull", "进入新场景、情绪递进、强调空间关系", "顺滑、连贯、代入", "medium"),
    ("match_cut", "匹配剪辑", "match cut", "创意叙事、隐喻象征、时空跳跃", "机巧、回味、有深意", "medium"),
    ("montage", "蒙太奇", "montage", "时间压缩、场景累积、故事快进", "密实、燃情、激荡", "fast"),
    ("sound_bridge", "声音先行", "sound bridge (J-cut)", "悬疑、回忆、梦境；声音先于画面进入", "暗流、期待", "medium"),
)
# value, zh label, purpose, media examples
TRANSITION_CATEGORIES: tuple[tuple[str, str, str, str], ...] = (
    ("occlusion", "遮挡蒙太奇", "前景物象短暂遮挡镜头，遮挡移开后已是新场景", "衣袖、手掌、门框、雨幕、花瓣、纸页、面具、镜面、雾气、火焰"),
    ("camera_move", "镜头运动", "用镜头位移跨越时空边界", "俯冲、甩镜、下坠、环绕、侧移、抬升、后退、穿隙、推进、拉远、贴地"),
    ("action", "动作叙事", "人物动作的轨迹延续到下一场景", "转身、拔剑、挥刀、跃起、抬手、抬眸、奔袭、起身、闭眼睁眼、伸手触碰、甩袖"),
    ("light", "光影氛围", "光线变化承担切换", "月色漫染、闪电、霓虹闪烁、过曝、金光、烛焰、强光溢散、天光破晓、冷光铺满"),
    ("time", "时空流变", "同一机位内时间流逝", "四季更迭、昼夜流转、城建变迁、器物岁月、人物成长、记忆闪回"),
    ("emotion", "情绪驱动", "情绪节点触发切换", "惊醒、梦境破碎、泪滴垂落、心跳加速、呼出白雾、情绪残影、情绪爆发"),
    ("space", "空间跃迁", "穿越媒介进入另一空间", "冲出海面、推开门、升空、洞穴穿行、镜中世界、云海宫殿、传送门、画中世界"),
    ("narrative", "电影高级叙事", "剪辑语法本身成为转场", "双线平行、视线引导、遮挡物匹配、长镜连贯、虚实景深、声音先行、穿廊长镜、图形匹配"),
    ("opening", "开篇转场", "第一镜就完成世界观交代", "暗影现身、异象降临、瞳眸苏醒、战场残响、雨幕登场、破碎开场、重门启幕、梦境预警"),
)
_TYPE_BY_KEY = {value: value for value, *_ in TRANSITION_TYPES}
_TYPE_SYNONYMS = {
    "cut": ("硬切", "直切", "切", "cut", "hard cut", "动作匹配硬切", "视线匹配硬切", "正反打"),
    "fade": ("淡入", "淡出", "淡入淡出", "fade", "渐黑", "黑场", "fade in", "fade out"),
    "dissolve": ("叠化", "叠画", "溶", "dissolve", "cross dissolve", "交叉叠化"),
    "flash": ("闪白", "闪黑", "flash", "白闪", "黑闪"),
    "wipe": ("划像", "划变", "wipe", "擦除"),
    "push_pull": ("推拉", "推拉转场", "push pull", "推进转场", "拉出转场"),
    "match_cut": ("匹配剪辑", "匹配", "match cut", "图形匹配", "遮挡物匹配", "动作匹配"),
    "montage": ("蒙太奇", "montage", "快切", "快剪"),
    "sound_bridge": ("声音先行", "声音先导", "声桥", "sound bridge", "j cut", "j-cut", "声音延续"),
}
_CATEGORY_LABELS = {value: label for value, label, _, _ in TRANSITION_CATEGORIES}
_CATEGORY_SYNONYMS = {
    "occlusion": ("遮挡", "拂过", "掠过", "覆盖", "吞没", "遮镜", "面具", "镜面置换", "起雾"),
    "camera_move": ("俯冲", "甩镜", "下坠", "环绕", "侧移", "抬升", "后退", "穿隙", "贴地", "旋转镜头"),
    "action": ("转身", "拔剑", "挥刀", "跃起", "抬手", "抬眸", "奔袭", "起身", "睁眼", "触碰", "甩袖", "回身"),
    "light": ("月色", "闪电", "霓虹", "过曝", "金光", "烛", "溢散", "破晓", "冷光", "光晕", "火光"),
    "time": ("四季", "昼夜", "变迁", "岁月", "成长", "闪回", "回溯", "加速"),
    "emotion": ("惊醒", "梦境", "泪", "心跳", "白雾", "残影", "情绪爆发", "入梦"),
    "space": ("冲天", "门后", "升空", "洞穴", "镜中", "云巅", "传送门", "画中", "堕入"),
    "narrative": ("双线", "视线引导", "长镜", "景深", "声音先行", "穿廊", "图形匹配"),
    "opening": ("开篇", "开场", "登场", "现身", "苏醒", "启幕"),
}


def _key(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).casefold()


def normalize_transition_type(value: Any) -> tuple[str, bool]:
    """Canonical editing type for free text such as '声音先行硬切' (sound bridge wins over plain cut)."""
    key = _key(value)
    if not key:
        return "cut", False
    if key in _TYPE_BY_KEY:
        return key, True
    best: tuple[int, str] | None = None
    for canonical, aliases in _TYPE_SYNONYMS.items():
        for alias in aliases:
            alias_key = _key(alias)
            if alias_key and alias_key in key:
                score = (len(alias_key), canonical)
                if best is None or score > best:
                    best = score
    if best:
        return best[1], True
    return "cut", False


def classify_transition_category(value: Any) -> str:
    """Media category suggested by the transition prose, or '' when it names none."""
    key = _key(value)
    best: tuple[int, str] | None = None
    for category, aliases in _CATEGORY_SYNONYMS.items():
        for alias in aliases:
            alias_key = _key(alias)
            if alias_key and alias_key in key and (best is None or len(alias_key) > best[0]):
                best = (len(alias_key), category)
    return best[1] if best else ""


class TransitionSpec(BaseModel):
    """One transition written with the universal formula."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    kind_label: str
    category: str = ""
    category_label: str = ""
    usage: str = ""
    emotions: str = ""
    prompt: str = Field("", max_length=1000)


def transition_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "types": [
            {"value": value, "label": label, "en": en, "usage": usage, "emotions": emotions, "pacing": pacing}
            for value, label, en, usage, emotions, pacing in TRANSITION_TYPES
        ],
        "categories": [
            {"value": value, "label": label, "purpose": purpose, "media": media}
            for value, label, purpose, media in TRANSITION_CATEGORIES
        ],
    }


def compose_transition(
    kind: str,
    *,
    outgoing_action: str = "",
    medium: str = "",
    camera_move: str = "",
    incoming_scene: str = "",
    light: str = "",
    category: str = "",
) -> TransitionSpec:
    """Universal formula: outgoing action + medium + camera move + incoming scene + light mood."""
    canonical, _ = normalize_transition_type(kind)
    _, label, _en, usage, emotions, _pacing = next(row for row in TRANSITION_TYPES if row[0] == canonical)
    category = category if category in _CATEGORY_LABELS else classify_transition_category(medium or outgoing_action)
    parts = [
        f"前镜收尾：{outgoing_action.strip()}" if outgoing_action.strip() else "",
        f"转场媒介：{medium.strip()}" if medium.strip() else "",
        f"镜头运动：{camera_move.strip()}" if camera_move.strip() else "",
        f"切入：{incoming_scene.strip()}" if incoming_scene.strip() else "",
        f"光影氛围：{light.strip()}" if light.strip() else "",
    ]
    prompt = f"{label}（{usage}）；" + "；".join(part for part in parts if part)
    return TransitionSpec(
        kind=canonical,
        kind_label=label,
        category=category,
        category_label=_CATEGORY_LABELS.get(category, ""),
        usage=usage,
        emotions=emotions,
        prompt=prompt.rstrip("；"),
    )


def transition_label(kind: str) -> str:
    return next((label for value, label, *_ in TRANSITION_TYPES if value == kind), "硬切")


def describe_transition(value: Any) -> str:
    """Short catalog note for free-text transition types, used in prompts and checks."""
    canonical, matched = normalize_transition_type(value)
    _, label, _en, usage, emotions, _pacing = next(row for row in TRANSITION_TYPES if row[0] == canonical)
    category = classify_transition_category(value)
    note = f"{label}：{usage}（{emotions}）"
    if category:
        note += f"；媒介类别：{_CATEGORY_LABELS[category]}"
    if not matched:
        note += "；未在转场词典内，按硬切处理"
    return note


TRANSITION_PROMPT_GUIDE = (
    "转场按两层写：剪辑类型（硬切/淡入淡出/叠化/闪白闪黑/划像/推拉/匹配剪辑/蒙太奇/声音先行）决定节奏；"
    "AI 片段内的转场用媒介完成——遮挡（衣袖、手掌、门框、雨幕、花瓣）、镜头运动（俯冲、甩镜、穿隙）、"
    "动作延续（转身、拔剑、跃起）、光影（闪电、过曝、烛焰）、时空流变（四季、昼夜）、情绪节点（惊醒、泪滴）、"
    "空间跃迁（推门、镜中、传送门）。写法固定为：前镜人物动作 + 转场媒介 + 镜头运动 + 新场景 + 光影氛围。"
    "同场景直接硬切；换场景才用穿越、甩镜或叠化；上一镜情绪未结束不炫技。"
)
_FORMULA_PATTERN = re.compile(r"(转场媒介|遮挡|甩镜|穿|叠化|淡入|淡出|闪白|闪黑|划像|匹配|蒙太奇|声音先行)")


def uses_transition_grammar(text: Any) -> bool:
    return bool(_FORMULA_PATTERN.search(str(text or "")))
