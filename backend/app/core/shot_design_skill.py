# -*- coding: utf-8 -*-
"""Load the universal storyboard-prompt skill for injection into stage prompts.

The skill package lives in ``backend/skills/shot-design-master`` so the existing
``SkillRegistry`` discovers it alongside the other Markdown skills.  Stage prompts
cannot afford the whole package, so callers pull named sections within a character
budget - the same treatment the stage prompts already give the project guides.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence


logger = logging.getLogger("app.core.shot_design_skill")

SKILL_NAME = "shot-design-master"
SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME

# Section key -> reference file, relative to the skill package root.
SHOT_DESIGN_SECTIONS: dict[str, str] = {
    "shot-grammar": "references/shot-grammar.md",
    "prompt-contracts": "references/prompt-contracts.md",
    "blocking-lighting": "references/blocking-lighting.md",
    "continuity-consistency": "references/continuity-consistency.md",
    "performance-action": "references/performance-action.md",
    "choreography-beats": "references/choreography-beats.md",
    "models-failures": "references/models-failures.md",
    "h3-native-contract": "references/h3-native-contract.md",
}

# Section budgets keep a stage prompt inside what small models can actually read;
# the storyboard stage already truncates every guide it loads for the same reason.
# The core budget must stay ABOVE len(SKILL.md) (chars, not bytes) - a truncated core
# silently drops the self-check rules at the bottom; tests guard the uncut invariant.
DEFAULT_CORE_BUDGET = 14_000
# Uniform default; sections whose tested tables sit deeper get a per-section override
# (SECTION_BUDGET_OVERRIDES) so the uncut core + all sections stay inside the stage-4
# prompt cap (26k chars, guarded by tests). Offsets that size these numbers:
# shot-grammar 转场 block ends ~4.76k, blocking-lighting 站位八式 ends ~4.32k,
# continuity 防分身负面词 ends ~4.09k. H3 projects load a 4th section and were
# already over that cap under the old 11k/5k split - a preexisting tradeoff.
DEFAULT_SECTION_BUDGET = 4_100
SECTION_BUDGET_OVERRIDES: dict[str, int] = {"shot-grammar": 4_850, "blocking-lighting": 4_400}

# 阶段四提示词的字符硬顶：技能前缀之外还叠着好几份项目指南，小模型读不完会直接挂起。
# 下面每一档预算都是按「核心不截断 + 各章之和 + 包装文案」倒推出来的，测试逐档钉住。
#
# 两级硬顶：文戏保持原来的 26k 不动，打戏单独放宽到 27.6k。放宽只买两样东西，
# 都是实测证明「不给就等于没有」的内容，且只有打戏场次付这个代价：
#   ① §3.15 的三条边界裁决 + 档位/链/骨架分工（+716 字符）——不给，慢档会写出
#      4 秒成片镜与三连同景别，两条都会被 shot_table_rules 判为问题镜；
#   ② §3.16 里**本场戏命中的那一种**专项骨架（≤ 1020 字符）——整节 4830 字符
#      任何一档都装不下，逐场只装一种才装得下。
# 文戏前缀逐字未变，由 DIALOGUE_PROMPT_CHAR_CAP 单独钉住，防止放宽被顺手用到文戏上。
STAGE_PROMPT_CHAR_CAP = 27_600
DIALOGUE_PROMPT_CHAR_CAP = 26_000

# 长参考文件的正文与附录各写了一遍同一套方法论，附录版更细但排在 5 万字符之后，
# 顺序头部截断永远读不到——打戏要用的攻防轮转/动能运镜/三档速度全在那里。
# 这里按小节标题锚点抽取，锚点是标题里的子串(不含编号)，附录重新编号也不会失配。
# 顺序即优先级：预算不够时从尾部丢，所以必进的内容排在前面。
SECTION_EXCERPTS: dict[str, tuple[str, ...]] = {
    "performance-action": (
        "四、动作戏设计",   # 正文压缩版：七原则/拆镜/打击感五件套/攻防轮转/硬性约束/完整模板
        "出招-受击",        # 三镜拆分法
        "攻防轮转规则",     # 附录展开版：防"单方面挨打"
        "动能运镜",
        "节奏档位",         # 三档速度方案(标准/极速/慢节奏) + 量化节拍(交锋次数/镜数/微动作数)
        "防越轴",           # 打戏场次不装 continuity-consistency，轴线规范只剩这一处
        # SKILL.md 正文明写「打戏防崩坏后缀见 performance-action §3.13」，那一串的权威定义
        # 就在这一节里。前移到危险等级/急救表之前：实测旧顺序 + 7900 预算下它整节被截掉，
        # 核心里的交叉引用因此指向一段永远到不了提示词的内容。
        "动作戏负面词",     # 不能只写"负面词"，那会先命中表情章节的同名小节
        "剧本阶段就标危险等级",
        "翻车急救表",
        "动作戏 Checklist",
        # §3.16 六种专项打戏骨架(4830 字符)：当前任何一档打戏预算都装不下，排在末尾
        # 只是声明优先级——预算一旦放宽它就自动进来，不必再改锚点表。
        "专项打戏骨架",
    ),
}

# scene_kind(+H3 与否) -> {章节: 预算}。空表示沿用 DEFAULT_SECTION_BUDGET 与
# SECTION_BUDGET_OVERRIDES，也就是文戏场次逐字保持改造前的行为(回归安全)。
# H3 项目要多装一章原生字段契约，四章共用同一个预算池，所以单列一档——旧代码
# 无条件用同一套预算，H3 的前缀直接超顶 4077 字符，本表就是那处修复。
SECTION_BUDGET_PROFILES: dict[str, dict[str, int]] = {
    "general": {},
    "general+h3": {
        "shot-grammar": 4_850,
        "blocking-lighting": 3_400,
        "continuity-consistency": 2_300,
        "h3-native-contract": 1_800,
    },
    # 打戏场次：打法与招式翻译占大头，镜头语法只留景别与机位(轴线规范由
    # performance-action 附 §3.8 自带)，连贯性/站位两章让位。
    # 下面两档按抽取块在拼接结果里的**实测**偏移倒推，不是拍脑袋的整数。
    # performance-action 抽取后各块的起始偏移(用 _excerpt 实测，改动前必须重测)：
    #   动能运镜 3982、节奏档位 5093、危险等级 5837、选档决策 7758、
    #   防越轴 8354、动作戏负面词 8787、deformed limbs 8823、不要跳轴 9164。
    # 预算落在哪两个数字之间，就决定了最后一个完整到达提示词的块是谁。
    # 9_200 是让 §3.13 负面词串整段落地的最小值：_truncate 按行边界回退，
    # 9_100 只能带到 deformed limbs，中文负面串「不要跳轴」还在行外。
    "fight": {
        "performance-action": 9_200,
        "choreography-beats": 2_100,
        "shot-grammar": 1_700,
    },
    "fight+h3": {
        # 多一章 h3-native-contract，池子少 1800；performance-action 仍须保住 9_200,
        # 否则 SKILL.md 里「打戏防崩坏后缀见 §3.13」就是一条到不了的死链。
        # 缩的是招式表与镜头语法：招式可按体系抽查，负面词串少一行就等于不设防。
        "performance-action": 9_200,
        "choreography-beats": 900,
        "shot-grammar": 1_100,
        "h3-native-contract": 1_800,
    },
}


def section_budgets(scene_kind: str = "general", *, h3: bool = False) -> dict[str, int]:
    """Per-section budgets for one scene kind; unknown kinds degrade to 文戏 defaults."""
    profile = SECTION_BUDGET_PROFILES.get(f"{scene_kind}+h3" if h3 else scene_kind)
    if profile is None:
        profile = SECTION_BUDGET_PROFILES["general+h3" if h3 else "general"]
    return dict(profile)


def _heading_blocks(text: str) -> list[tuple[int, int, str]]:
    """Every Markdown heading as (offset, level, line)."""
    return [
        (match.start(), len(match.group(1)), match.group(0))
        for match in re.finditer(r"^(#{1,6}) .*$", text, re.MULTILINE)
    ]


def _excerpt(text: str, anchors: Sequence[str]) -> str:
    """Keep only the sections whose heading contains one of the anchors.

    A heading owns everything up to the next heading of the same or higher level,
    so a block is never left without the table it introduces.  An anchor already
    covered by an earlier block skips ahead to its next occurrence, which is how
    the compressed 正文 version and the expanded 附录 version both get in.
    """
    headings = _heading_blocks(text)
    if not headings:
        return ""
    taken: list[tuple[int, int]] = []
    for anchor in anchors:
        for index, (start, level, line) in enumerate(headings):
            if anchor not in line or any(low <= start < high for low, high in taken):
                continue
            end = len(text)
            for next_start, next_level, _ in headings[index + 1:]:
                if next_level <= level:
                    end = next_start
                    break
            taken.append((start, end))
            break
        else:
            logger.warning("[ShotDesignSkill] 锚点未命中: %s", anchor)
    if not taken:
        return ""
    return "\n\n".join(text[start:end].strip() for start, end in taken)


def _truncate(text: str, budget: int) -> str:
    """Cut on a line boundary so a table is never left half-written."""
    if budget <= 0 or len(text) <= budget:
        return text
    head = text[:budget]
    cut = head.rfind("\n")
    return (head[:cut] if cut > budget // 2 else head).rstrip() + "\n\n（本节已按上下文预算截断）"


@lru_cache(maxsize=32)
def _read(relative: str) -> str:
    """Read one file from the skill package; missing files degrade to empty."""
    target = (SKILL_ROOT / relative).resolve()
    root = SKILL_ROOT.resolve()
    if root != target and root not in target.parents:
        logger.warning("[ShotDesignSkill] 拒绝越界读取: %s", relative)
        return ""
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("[ShotDesignSkill] 读取失败 %s: %s", relative, type(error).__name__)
        return ""


def shot_design_skill_installed() -> bool:
    return (SKILL_ROOT / "SKILL.md").is_file()


def load_shot_design_skill(
    sections: Sequence[str] = (),
    *,
    core_budget: int = DEFAULT_CORE_BUDGET,
    section_budget: int = DEFAULT_SECTION_BUDGET,
    section_budgets: Mapping[str, int] | None = None,
) -> str:
    """Compile SKILL.md plus the requested reference sections.

    ``section_budgets`` gives one scene kind its own per-section split (see
    ``section_budgets()``); an explicit ``section_budget`` still speaks for the
    whole package and wins over both it and ``SECTION_BUDGET_OVERRIDES``.
    Returns an empty string when the package is absent, so a stage prompt keeps
    working exactly as before rather than failing on a missing skill.
    """
    core = _read("SKILL.md")
    if not core:
        return ""
    parts = [_truncate(core, core_budget)]
    for key in dict.fromkeys(sections):
        relative = SHOT_DESIGN_SECTIONS.get(key)
        if not relative:
            logger.warning("[ShotDesignSkill] 未知章节: %s", key)
            continue
        body = _read(relative)
        if body:
            anchors = SECTION_EXCERPTS.get(key)
            if anchors:
                # 全文八万多字符，任何阶段预算都装不下；先抽出本场戏真正要用的小节，
                # 抽不到(文件改名/改结构)就退回全文头部截断，不让本章整个消失。
                body = _excerpt(body, anchors) or body
            # Overrides express "this section's tested tables sit deeper than the uniform
            # default"; a caller (or env) that sets its own budget speaks for the whole
            # package, so overrides only apply on top of the default.
            if section_budget == DEFAULT_SECTION_BUDGET:
                budget = (section_budgets or {}).get(key) or SECTION_BUDGET_OVERRIDES.get(key, section_budget)
            else:
                budget = section_budget
            parts.append(_truncate(body, budget))
    return "\n\n".join(parts)


def reset_shot_design_cache() -> None:
    """Drop the file cache; used by tests and after a skill package is replaced."""
    _read.cache_clear()
