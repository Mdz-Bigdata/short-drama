# -*- coding: utf-8 -*-
"""Production knowledge for the eight stages, read through the skills that own it.

Each guide lives inside the skill it belongs to and is registered in that skill's
``manifest.json`` with a key, a title, a default budget and the stages that take it
(see :mod:`app.core.knowledge_registry`). This module only:

1. reads a section by key, with the line-boundary truncation every stage relies on;
2. exposes the stage → section matrix, which the manifests define;
3. builds the block of evolved lessons a stage appends to its prompt.

Nothing here names a guide's file or path. The import direction is
production_knowledge → knowledge_evolution; the evolution engine never imports this module.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.core import knowledge_evolution, knowledge_registry


logger = logging.getLogger("app.core.production_knowledge")

SKILL_NAME = "production-knowledge-master"

# The budget a section gets when its manifest entry is missing one.
DEFAULT_SECTION_BUDGET = 5_000


def section_files() -> dict[str, str]:
    """Section key → its file, relative to the skills root (``<skill>/references/<key>.md``)."""
    return {key: item.relative_path for key, item in knowledge_registry.sections().items()}


def section_budgets() -> dict[str, int]:
    """Section key → its default budget in characters (0 = the whole text)."""
    return {key: item.budget for key, item in knowledge_registry.sections().items()}


def stage_sections() -> dict[int, tuple[str, ...]]:
    """Stage → the section keys its prompts take, as the manifests declare."""
    return knowledge_registry.stage_sections()


# 行边界截断后追加的标记；其长度计入预算，保证注入量绝不超过登记预算。
TRUNCATION_MARK = "\n\n（本节已按上下文预算截断）"


def _truncate(text: str, budget: int) -> str:
    """行边界截断，表格绝不留半行（语义复制自 shot_design_skill._truncate）。

    与直接切片 text[:budget] 的差异是**显式登记的语义**（见
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

    budget=None 用该章节在技能 manifest 里登记的预算；显式传 0 表示全文不截断。
    未知章节键 / 文件缺失 / manifest 不合法都降级为空串，调用点保留自己的兜底文案。
    """
    try:
        item = knowledge_registry.section(key)
    except knowledge_registry.KnowledgeManifestError as error:
        logger.error("[ProductionKnowledge] 技能 manifest 不合法: %s", error)
        return ""
    if item is None:
        logger.warning("[ProductionKnowledge] 未知章节键: %s", key)
        return ""
    text = _read_file(str(item.path))
    if not text:
        return ""
    return _truncate(text, item.budget if budget is None else budget)


def load_stage_sections(stage: int) -> dict[str, str]:
    """按消费矩阵读取某阶段的全部章节；值可能为空串（文件缺失时兜底交给调用点）。"""
    return {key: load_section(key) for key in stage_sections().get(stage, ())}


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


# 统一负面词表在负面提示词指南里的位置：标题含 UNIFIED_NEGATIVE_HEADING 的二级节，
# 其下标题含「视频」/「静帧」的三级节各有一个 ```text 代码块。词表本身只写在指南里。
NEGATIVE_GUIDE_KEY = "negative-prompts"
UNIFIED_NEGATIVE_HEADING = "终极统一负面提示词"
_UNIFIED_NEGATIVE_MEDIA = {"video": "视频", "image": "静帧"}


def _fenced_terms(block: str) -> tuple[str, ...]:
    """一个小节里第一个代码块的词条，按中英文顿号/逗号/换行切开，去重保序。"""
    start = block.find("```")
    if start < 0:
        return ()
    body_start = block.find("\n", start)
    end = block.find("```", body_start + 1)
    if body_start < 0 or end < 0:
        return ()
    raw = block[body_start + 1:end]
    for separator in ("，", ",", "\n"):
        raw = raw.replace(separator, "、")
    return tuple(dict.fromkeys(term.strip() for term in raw.split("、") if term.strip()))


def global_negatives(medium: str) -> tuple[str, ...]:
    """全局强制负面词：``medium`` 为 ``"video"``(全量) 或 ``"image"``(单帧子集)。

    读负面提示词指南里「终极统一负面提示词」一节，不在代码里另存一份；
    指南缺失或改了结构就返回空元组，调用点照常出图，只是少了这层兜底。
    """
    label = _UNIFIED_NEGATIVE_MEDIA.get(medium)
    if not label:
        raise ValueError(f"未知媒介: {medium}")
    text = load_section(NEGATIVE_GUIDE_KEY, budget=0)
    heading = text.find(UNIFIED_NEGATIVE_HEADING)
    if heading < 0:
        return ()
    section_end = text.find("\n## ", heading)
    section = text[heading: section_end if section_end >= 0 else len(text)]
    for part in section.split("\n### ")[1:]:
        title = part.split("\n", 1)[0]
        if label in title:
            return _fenced_terms(part)
    return ()


def global_negative_text(medium: str) -> str:
    """全局强制负面词拼成一串(顿号分隔)，可直接追加进提示词的负面约束。"""
    return "、".join(global_negatives(medium))


def reset_knowledge_cache() -> None:
    """清空文件缓存与章节索引；测试与知识源热更新（含 SKILLS_DIR 切换、manifest 改动）时调用。"""
    _read_file.cache_clear()
    knowledge_registry.reset()
