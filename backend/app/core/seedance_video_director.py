# -*- coding: utf-8 -*-
"""seedance-2-5-video-director 的运行时装载层。

上游技能（MIT，逐字 vendored 在 backend/skills/seedance-2-5-video-director/）是写给
聊天 Agent 的「视频导演」：会提问、出导演方案、做诊断。本项目把它接进 Seedance 2.5
的提示词优化链路（ModelGateway.optimize_video_prompt）时，只取对提示词正文有约束力
的部分——模式上限与素材要求、时序/引用规则、所选主模式的蓝图、素材锁表、真人表演
与物理因果模式——再按预算裁剪；安装引导、追问策略、导演方案/诊断输出模式一概不接。

只在目标模型判定为 Seedance 2.5 时生效。上游 SKILL.md 自己写明 provider-specific，
这套上限和语法不能套到 2.0 或其它视频模型上，所以判定不到 2.5 时返回空串。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.video_references import _normalize_model_token


SKILL_NAME = "seedance-2-5-video-director"
SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME

# 导演层是追加在 sd25-pe 主规范之后的第三段系统提示；34k 的主规范之外再放这么多，
# 对 doubao-seed / deepseek 这类 128k 上下文的文本模型仍有余量，但不能无限长——
# 超过就按优先级从低到高丢整段，绝不留半张表。
DIRECTOR_LAYER_CHAR_CAP = 24_000

# 本项目视频产线只产 4-30s 的单镜；上游其余主模式（续写/编辑/白模/无缝转场/
# 多格分镜）不在这条链路上，这里只登记会被选中的两种。
PRIMARY_MODES = ("basic-multimodal", "timestamp-30s")

_REF_MODES = frozenset({"first_frame", "first_last_frame", "multi_ref"})

_DIALOGUE_MARKERS = ("台词", "对白", "说道", "说：", "喊道", "低声", "旁白", "独白", "「", "“")
_ACTING_MARKERS = ("表情", "眼神", "哭", "笑", "颤抖", "情绪", "愤怒", "泪", "拥抱", "吻", "对峙")
_PHYSICAL_MARKERS = ("打", "踢", "摔", "撞", "碰撞", "推开", "拳", "刀", "剑", "跌", "坠", "扑", "劈", "砍", "格挡", "冲刺")
_SPORTS_MARKERS = ("比赛", "综艺", "赛道", "障碍", "直播", "解说", "观众席")
_TIMESTAMP_PATTERN = re.compile(r"(?<!\d)\d{1,2}\s*[-–~至]\s*\d{1,2}\s*(?:s|秒)")

# 项目自写的接入说明：放在导演层最前面，讲清它与 sd25-pe 的分工，免得模型把
# 上游的「提问 / 导演方案」输出模式当成本次任务的输出。
_PRECEDENCE_NOTE = """# 导演层：seedance-2-5-video-director（仅 Seedance 2.5 生效）

下面几段来自 MIT 授权的 seedance-2-5-video-director 技能，只作为 Seedance 2.5 的
模式上限、素材要求、时序/引用规则与真人表演约束；接口参数分离（画幅、总时长、
分辨率、帧率、声音开关不进 Prompt）与素材引用保真仍以上文 sd25-pe 主规范为准。
主模式已由项目按镜头时长与提示词形态选定（见「当前调用约定」），不要再提问、
不要输出导演方案或诊断，只把这些约束体现在最终的中文提示词正文里。"""


@dataclass(frozen=True)
class DirectorLayer:
    """一次装载的结果：正文 + 选定的主模式 + 实际进入的章节（供日志与测试断言）。"""

    text: str
    primary_mode: str
    sections: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applied(self) -> bool:
        return bool(self.text)


def is_seedance_25(*candidates: str | None) -> bool:
    """任一候选模型名解析为 Seedance 2.5 即为真。

    与 video_references 的时长表同一套归一化：``seedance2.5`` / ``seedance-2.5`` /
    ``doubao-seedance-2-5-260128`` 都算，``seedance2.0`` 与 ``doubao-seedance-2-0-...`` 不算。
    """
    for candidate in candidates:
        normalized = _normalize_model_token(str(candidate or ""))
        if "seedance" in normalized and re.search(r"seedance[^0-9]*2-?5(?![0-9])", normalized):
            return True
    return False


def select_primary_mode(*, duration: int = 0, prompt: str = "") -> str:
    """精确 30 秒或提示词里已带秒级时间段 → timestamp-30s；其余走 basic-multimodal。

    上游明写「不要把普通的 30 秒请求自动升级成 Long Video」，本产线单镜上限正是 30s，
    所以 30s 只会落到 timestamp-30s，永远不会选 long-video。
    """
    if int(duration or 0) >= 30 or _TIMESTAMP_PATTERN.search(prompt or ""):
        return "timestamp-30s"
    return "basic-multimodal"


def skill_installed() -> bool:
    return (SKILL_ROOT / "SKILL.md").is_file()


@lru_cache(maxsize=16)
def _read(relative: str) -> str:
    path = SKILL_ROOT / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def reset_seedance_director_cache() -> None:
    _read.cache_clear()


def _section(text: str, heading: str) -> str:
    """取出一个二级标题段（含其下所有 ### 子节），到下一个 ``## `` 为止。"""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).rstrip()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def build_director_layer(
    *,
    video_model: str = "",
    duration: int = 0,
    mode: str = "first_frame",
    prompt: str = "",
    asset_hint: str = "",
    fallback_model: str = "",
) -> DirectorLayer:
    """按镜头形态挑章节、按预算打包。不是 2.5、或技能未安装，返回空层。"""
    if not is_seedance_25(video_model, fallback_model) or not skill_installed():
        return DirectorLayer(text="", primary_mode="", sections=())

    primary_mode = select_primary_mode(duration=duration, prompt=prompt)
    skill = _read("SKILL.md")
    limits = _read("references/capabilities-and-limits.md")
    blueprints = _read("references/prompt-blueprints.md")
    multimodal = _read("references/multimodal-patterns.md")
    realistic = _read("references/realistic-direction-patterns.md")

    corpus = f"{prompt}\n{asset_hint}"
    has_refs = mode in _REF_MODES
    has_audio = "音频" in corpus or "@音频" in corpus or "@Audio" in corpus or "音色" in corpus
    has_dialogue = _has_any(corpus, _DIALOGUE_MARKERS) or _has_any(corpus, _ACTING_MARKERS)
    has_physical = _has_any(corpus, _PHYSICAL_MARKERS)
    has_sports = _has_any(corpus, _SPORTS_MARKERS)

    # (优先级, 章节名, 正文)。优先级越小越先保住；同优先级按出现顺序。
    blueprint_heading = (
        "Exact 30-second timestamp video" if primary_mode == "timestamp-30s" else "Basic multimodal"
    )
    candidates: list[tuple[int, str, str]] = [
        (0, "precedence-note", _PRECEDENCE_NOTE),
        (1, "limits/Mode limits", _section(limits, "Mode limits")),
        (1, "skill/Timing and reference rules", _section(skill, "Timing and reference rules")),
        (1, f"blueprints/{blueprint_heading}", _section(blueprints, blueprint_heading)),
        (2, "blueprints/Shared assembly order", _section(blueprints, "Shared assembly order")),
        (2, "limits/Validation behavior", _section(limits, "Validation behavior")),
        (3, "skill/Final audit", _section(skill, "Final audit")),
        (3, "realistic/Contradiction audit", _section(realistic, "Contradiction audit")),
    ]
    if has_refs:
        candidates.extend((
            (2, "multimodal/Asset lock table", _section(multimodal, "Asset lock table")),
            (2, "multimodal/Reference grammar", _section(multimodal, "Reference grammar")),
            (2, "multimodal/Person-reference scope", _section(multimodal, "Person-reference scope")),
            (3, "multimodal/Realistic people", _section(multimodal, "Realistic people")),
            (3, "multimodal/Multiple people", _section(multimodal, "Multiple people")),
            (4, "limits/Input requirements", _section(limits, "Input requirements")),
            (4, "limits/Stability guidance", _section(limits, "Stability guidance")),
        ))
    if has_audio or has_dialogue:
        candidates.append((3, "multimodal/Timbre and dialogue", _section(multimodal, "Timbre and dialogue")))
    if has_dialogue:
        candidates.extend((
            (2, "realistic/Natural human performance", _section(realistic, "Natural human performance")),
            (3, "realistic/Dialogue and emotional conflict", _section(realistic, "Dialogue and emotional conflict")),
            (4, "realistic/Relationship-drama camera grammar", _section(realistic, "Relationship-drama camera grammar")),
        ))
    if has_physical:
        candidates.append((2, "realistic/Physical causality", _section(realistic, "Physical causality")))
    if has_sports:
        candidates.append((4, "realistic/Sports and variety live coverage", _section(realistic, "Sports and variety live coverage")))

    # 按预算打包：从高优先级往下装，装不下的整段丢弃，保持原相对顺序。
    ordered = sorted(
        ((priority, index, name, body) for index, (priority, name, body) in enumerate(candidates) if body),
        key=lambda item: (item[0], item[1]),
    )
    kept: list[tuple[int, str, str]] = []
    used = 0
    for priority, index, name, body in ordered:
        cost = len(body) + 2
        if used + cost > DIRECTOR_LAYER_CHAR_CAP:
            continue
        kept.append((index, name, body))
        used += cost
    kept.sort(key=lambda item: item[0])

    text = "\n\n".join(body for _, _, body in kept).strip()
    return DirectorLayer(
        text=text,
        primary_mode=primary_mode,
        sections=tuple(name for _, name, _ in kept),
    )


def load_director_layer(**kwargs) -> str:
    """便捷入口：只要正文。参数与 build_director_layer 相同。"""
    return build_director_layer(**kwargs).text
