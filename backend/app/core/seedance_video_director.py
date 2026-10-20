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

from app import settings
from app.core import knowledge_registry
from app.core import fight_design

from app.core.video_references import _normalize_model_token


SKILL_NAME = "seedance-2-5-video-director"
SKILL_ROOT = settings.skills_root() / SKILL_NAME

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
# 打戏专用：比 _PHYSICAL_MARKERS 严——"御剑""剑修"里的"剑"不算打斗。
_FIGHT_MARKERS = ("打斗", "交手", "对打", "互打", "拳", "踢", "劈", "砍", "斩", "刺向", "格挡", "对撞", "出招", "厮杀", "击飞", "大招", "连招", "反杀")
# 与编剧阶段共用一份玄幻词表（app.core.fight_design）。
_XIANXIA_MARKERS = fight_design.XIANXIA_MARKERS
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


def _reference(key: str) -> str:
    """A reference file of this skill, by its manifest key, relative to the skill root."""
    item = knowledge_registry.section(key)
    return item.path.relative_to(SKILL_ROOT.resolve()).as_posix() if item is not None else ""


@lru_cache(maxsize=16)
def _read(relative: str) -> str:
    path = SKILL_ROOT / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _registered_text(key: str) -> str:
    """任意技能里按 manifest 键登记的参考文件全文(如 shot-design-master 的 Seedance 中文手册补充)。"""
    item = knowledge_registry.section(key)
    if item is None:
        return ""
    try:
        return item.path.read_text(encoding="utf-8")
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
    limits = _read(_reference("seedance-capabilities-and-limits"))
    blueprints = _read(_reference("seedance-prompt-blueprints"))
    multimodal = _read(_reference("seedance-multimodal-patterns"))
    realistic = _read(_reference("seedance-realistic-direction-patterns"))
    # 中文手册补充(本项目自己整理，见 shot-design-master)：公式与固定说法按镜头形态挑，优先级低于上游技能。
    handbook = _registered_text("seedance25-cn-handbook")
    camera_library = _registered_text("camera-style-library")
    handoff = _registered_text("four-lock-handoff")
    composition = _registered_text("composition-library")
    camera_moves = _registered_text("camera-move-library")
    combat = _registered_text("combat-camera-handbook")
    xianxia = _registered_text("xianxia-combat-vfx")

    corpus = f"{prompt}\n{asset_hint}"
    has_refs = mode in _REF_MODES
    has_audio = "音频" in corpus or "@音频" in corpus or "@Audio" in corpus or "音色" in corpus
    has_dialogue = _has_any(corpus, _DIALOGUE_MARKERS) or _has_any(corpus, _ACTING_MARKERS)
    has_physical = _has_any(corpus, _PHYSICAL_MARKERS)
    has_sports = _has_any(corpus, _SPORTS_MARKERS)
    has_fight = _has_any(corpus, _FIGHT_MARKERS)
    has_xianxia = has_fight and _has_any(corpus, _XIANXIA_MARKERS)

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
    if has_fight:
        # 打戏：镜头贴动作走、命中短停、尾帧留下一击；速度档位词与拼接顺序。
        candidates.append((3, "combat/核心原则", _section(combat, "一、核心原则")))
        candidates.append((4, "combat/速度档位词", _section(combat, "四、速度档位词(写进运镜句)")))
        candidates.append((4, "combat/拼接公式", _section(combat, "五、拼接公式(一段打戏一条 prompt)")))
    if has_xianxia:
        # 玄幻打戏：能量先定形再有光、大招尺度要量得出来、结尾只能四种收法。
        candidates.append((3, "xianxia/能量四态", _section(xianxia, "二、能量四态：先定形，再有光")))
        candidates.append((3, "xianxia/收束协议", _section(xianxia, "五、收束协议：一段打戏只能用四种方式结束")))
        candidates.append((4, "xianxia/尺度四件套", _section(xianxia, "三、尺度四件套：大招必须量得出来")))
    if has_sports:
        candidates.append((4, "realistic/Sports and variety live coverage", _section(realistic, "Sports and variety live coverage")))
    candidates.append((3, "cn-handbook/四种提示词公式", _section(handbook, "一、四种提示词公式")))
    if primary_mode == "timestamp-30s":
        candidates.append((2, "cn-handbook/30 秒长视频的三个模块", _section(handbook, "二、30 秒长视频的三个模块")))
    if "转场" in corpus or "切镜" in corpus:
        candidates.append((3, "cn-handbook/中文转场用语", _section(handbook, "五、中文转场用语")))
    if has_dialogue or has_refs:
        candidates.append((4, "cn-handbook/人物造型细分公式", _section(handbook, "三、人物造型细分公式（真人与动画通用）")))
    candidates.append((4, "cn-handbook/其他可直接用的说法", _section(handbook, "六、其他可直接用的说法")))
    candidates.append((4, "camera-style/选运镜的总规则", _section(camera_library, "一、选运镜的总规则")))
    # 运镜句怎么写(幅度/速度词、单句放最后、给落点)；48 条词条太长，只带总则与组合公式。
    candidates.append((4, "camera-move/写法总则", _section(camera_moves, "一、写法总则")))
    candidates.append((5, "camera-move/组合公式", _section(camera_moves, "三、六个组合公式(整句填入运镜位)")))
    candidates.append((4, "composition/怎么用", _section(composition, "一、怎么用")))
    if has_physical:
        candidates.append((4, "composition/动作张力", _section(composition, "四、动作张力：把速度、压迫与爆点组织清楚")))
    else:
        candidates.append((4, "composition/电影氛围", _section(composition, "三、电影氛围：让光线、天气与遮挡参与叙事")))
    candidates.append((4, "four-lock/动作连贯三原则", _section(handoff, "五、动作连贯三原则")))
    if has_refs:
        candidates.append((3, "four-lock/故事板交给视频模型时的五条设置", _section(handoff, "六、故事板交给视频模型时的五条设置")))

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
