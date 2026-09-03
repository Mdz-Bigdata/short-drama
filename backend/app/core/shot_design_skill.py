# -*- coding: utf-8 -*-
"""Load the universal storyboard-prompt skill for injection into stage prompts.

The skill package lives in ``backend/skills/shot-design-master`` so the existing
``SkillRegistry`` discovers it alongside the other Markdown skills.  Stage prompts
cannot afford the whole package, so callers pull named sections within a character
budget - the same treatment the stage prompts already give the project guides.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Sequence


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
) -> str:
    """Compile SKILL.md plus the requested reference sections.

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
            # Overrides express "this section's tested tables sit deeper than the uniform
            # default"; a caller (or env) that sets its own budget speaks for the whole
            # package, so overrides only apply on top of the default.
            budget = (SECTION_BUDGET_OVERRIDES.get(key, section_budget)
                      if section_budget == DEFAULT_SECTION_BUDGET else section_budget)
            parts.append(_truncate(body, budget))
    return "\n\n".join(parts)


def reset_shot_design_cache() -> None:
    """Drop the file cache; used by tests and after a skill package is replaced."""
    _read.cache_clear()
