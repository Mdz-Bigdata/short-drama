# -*- coding: utf-8 -*-
"""production-knowledge-master 技能装载器：把根部 16 份知识源按章节键喂给各阶段提示词。

唯一事实源原则：16 份 md 只存在于仓库根部（与 drama_service.read_md_file 同一位置），
技能包 backend/skills/production-knowledge-master 里绝不复制正文——复制必然漂移，
且会破坏 agent_council.KNOWLEDGE_SOURCE_FILES 的 SHA-256 指纹校验。
本模块只做三件事：
1. 章节键 → 根部文件名的映射读取（缓存 + 行边界截断，范式复用 shot_design_skill）；
2. 阶段 → 章节的消费矩阵（与 tests/test_knowledge_source_runtime.py 登记的矩阵完全对等）；
3. 从进化引擎(knowledge_evolution)取该阶段 active 教训，组装成可注入提示词的教训块。

import 方向为 production_knowledge → knowledge_evolution 单向；进化引擎绝不 import 本模块。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from app.core import knowledge_evolution


logger = logging.getLogger("app.core.production_knowledge")

SKILL_NAME = "production-knowledge-master"

# 章节键(kebab 英文) → 根部 md 文件名，16 份全收，逐条对照：
SECTION_FILES: dict[str, str] = {
    "consistency-checklist": "AI 生成短剧一致性检查清单.md",        # 一致性检查清单
    "dialogue-pacing": "AI影视剧台词语速情绪提示词总结.md",          # 台词语速情绪
    "negative-prompts": "AI影视剧负面提示词.md",                    # 负面提示词(运行时走模块词表，此处仅登记)
    "golden-narrative": "AI漫剧短剧剧本黄金叙事结构.md",             # 黄金叙事结构
    "director-shot-guide": "AI短剧与漫剧导演级拍摄分镜完全指南.md",   # 导演级拍摄分镜
    "five-view-template": "AI短剧五视图解决人物一致性提示词模板.md",  # 五视图模板
    "production-guidelines": "AI短剧注意事项与关键元素.md",          # 注意事项与关键元素
    "martial-arts": "AI短剧电影级武打镜头设计指南.md",               # 武打镜头设计
    "performance-details": "AI短剧表演细节与提示词指南.md",          # 表演细节
    "continuity-design": "AI短剧连续性设计指南.md",                 # 连续性设计
    "scene-design": "场景设计提示词.md",                            # 场景设计
    "highlight-detection": "影视剧高光时刻识别方案.md",              # 高光时刻识别
    "visual-style": "画质风格类型总结.md",                          # 画质风格
    "emotion-expression": "短剧情绪与面部表情提示词库.md",           # 情绪与面部表情
    "plot-shot-coherence": "短剧情节与镜头连贯性提示词.md",          # 情节与镜头连贯性
    "genre-summary": "短剧题材类型总结.md",                         # 题材类型总结
}

# 阶段 → 章节键（消费矩阵，与 test_knowledge_source_runtime.py 的登记逐条对齐）。
# consistency-checklist 属"全阶段"：由 run_real_consistency_check 单独 load_section，不进本矩阵；
# negative-prompts 经 agent_council.NEGATIVE_MODULE_WORDS 模块词表生效，同样不进本矩阵。
STAGE_SECTIONS: dict[int, tuple[str, ...]] = {
    1: ("production-guidelines", "genre-summary", "golden-narrative"),
    2: ("performance-details", "production-guidelines", "continuity-design",
        "golden-narrative", "dialogue-pacing"),
    3: ("five-view-template", "performance-details"),
    4: ("director-shot-guide", "continuity-design", "plot-shot-coherence",
        "emotion-expression", "martial-arts", "scene-design"),
    5: ("visual-style",),
    6: (),  # 合成阶段无 LLM 提示词，仅接收教训块
    7: (),  # 归档阶段无 LLM 提示词，仅接收教训块
    8: ("highlight-detection", "production-guidelines"),
}

# 其余章节的统一截断值（保持现有各调用点语义）。
DEFAULT_SECTION_BUDGET = 5_000

# 各章节字符预算：保持现有各调用点的截断值；0 表示不截断（全文读入）。
SECTION_BUDGETS: dict[str, int] = {
    "consistency-checklist": 3_500,   # run_real_consistency_check 现值 [:3500]
    "dialogue-pacing": DEFAULT_SECTION_BUDGET,
    "negative-prompts": DEFAULT_SECTION_BUDGET,
    "golden-narrative": DEFAULT_SECTION_BUDGET,
    "director-shot-guide": 8_000,     # 阶段4 现值 8000
    "five-view-template": DEFAULT_SECTION_BUDGET,
    "production-guidelines": DEFAULT_SECTION_BUDGET,
    "martial-arts": DEFAULT_SECTION_BUDGET,
    "performance-details": DEFAULT_SECTION_BUDGET,
    "continuity-design": DEFAULT_SECTION_BUDGET,
    "scene-design": DEFAULT_SECTION_BUDGET,
    "highlight-detection": 6_000,     # 阶段8 现值 6000
    "visual-style": 0,                # 阶段5 全文读入后自行切片 1000 进 img prompt
    "emotion-expression": DEFAULT_SECTION_BUDGET,
    "plot-shot-coherence": DEFAULT_SECTION_BUDGET,
    "genre-summary": DEFAULT_SECTION_BUDGET,
}


def knowledge_root() -> Path:
    """知识源根目录，与 drama_service.read_md_file 完全同源。

    DRAMA_PROMPT_ROOT 优先（部署把提示词放在别处时用），
    否则取本模块上三级——backend/app/core 之上即仓库根部。
    """
    override = os.getenv("DRAMA_PROMPT_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


# 行边界截断后追加的标记；其长度计入预算，保证注入量绝不超过登记预算。
TRUNCATION_MARK = "\n\n（本节已按上下文预算截断）"


def _truncate(text: str, budget: int) -> str:
    """行边界截断，表格绝不留半行（语义复制自 shot_design_skill._truncate）。

    与旧管道 read_md_file(x)[:budget] 的差异是**显式登记的语义**（见
    test_production_knowledge_skill.py 的装载一致性用例）：截断退到最近的行边界并
    追加 TRUNCATION_MARK。标记长度计入预算——len(结果) <= budget 恒成立，
    不会出现"登记 3500、实注 3514"的预算溢出。
    """
    if budget <= 0 or len(text) <= budget:
        return text
    if budget <= len(TRUNCATION_MARK):
        # 预算连标记都装不下（仅防御，登记预算最小 3500 不会走到这）：退化为硬截断
        return text[:budget]
    room = budget - len(TRUNCATION_MARK)
    head = text[:room]
    cut = head.rfind("\n")
    return (head[:cut] if cut > room // 2 else head).rstrip() + TRUNCATION_MARK


@lru_cache(maxsize=64)
def _read_file(path_str: str) -> str:
    """按绝对路径缓存读取；缺失/失败降级为空串，绝不抛异常。"""
    target = Path(path_str)
    if not target.is_file():
        logger.warning("[ProductionKnowledge] 知识源文件不存在: %s", path_str)
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("[ProductionKnowledge] 读取失败 %s: %s", path_str, type(error).__name__)
        return ""


def load_section(key: str, budget: int | None = None) -> str:
    """按章节键读取一份知识源并按预算做行边界截断。

    budget=None 用 SECTION_BUDGETS 的登记值；显式传 0 表示全文不截断。
    未知章节键 / 文件缺失都降级为空串，调用点保留自己的兜底文案。
    """
    filename = SECTION_FILES.get(key)
    if not filename:
        logger.warning("[ProductionKnowledge] 未知章节键: %s", key)
        return ""
    root = knowledge_root().resolve()
    target = (root / filename).resolve()
    # 越界防护：映射值是常量文件名，仍按范式确认目标落在根目录之内。
    if target.parent != root and root not in target.parents:
        logger.warning("[ProductionKnowledge] 拒绝越界读取: %s", filename)
        return ""
    text = _read_file(str(target))
    if not text:
        return ""
    if budget is None:
        budget = SECTION_BUDGETS.get(key, DEFAULT_SECTION_BUDGET)
    return _truncate(text, budget)


def load_stage_sections(stage: int) -> dict[str, str]:
    """按消费矩阵读取某阶段的全部章节；值可能为空串（文件缺失时兜底交给调用点）。"""
    return {key: load_section(key) for key in STAGE_SECTIONS.get(stage, ())}


def stage_lessons_block(stage: int, *, budget: int = 900) -> str:
    """把该阶段 active 状态的历史生产教训组装成可直接追加到 sys_prompt 的文本块。

    教训来自进化引擎(learned/lessons.jsonl)，按 score*hits 降序；无教训返回空串。
    进化引擎任何异常都吞掉——教训注入是增强项，绝不允许拖垮阶段提示词。
    """
    try:
        lessons = knowledge_evolution.active_lessons(stage)
    except Exception as error:  # noqa: BLE001 - fail-soft：进化库损坏不影响流水线
        logger.warning("[ProductionKnowledge] 读取阶段 %s 教训失败: %s", stage, type(error).__name__)
        return ""
    if not lessons:
        return ""
    header = "【历史生产教训(自动进化，按命中率排序)】：\n"
    lines: list[str] = []
    total = len(header)
    for lesson in lessons:
        line = f"- [S{lesson.stage}|命中{lesson.hits}] {lesson.rule}"
        # 整行进出，超预算即停——教训绝不截半句
        if total + len(line) + 1 > budget and lines:
            break
        lines.append(line)
        total += len(line) + 1
    return header + "\n".join(lines)


def reset_knowledge_cache() -> None:
    """清空文件缓存；测试与知识源热更新（含 DRAMA_PROMPT_ROOT 切换）时调用。"""
    _read_file.cache_clear()
