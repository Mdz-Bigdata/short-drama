# -*- coding: utf-8 -*-
"""Genre pacing rules injected into every screenwriting prompt.

The rule text lives in ``backend/skills/screenwriting-master/references`` so the
same wording is read by the prompt builders and by anyone auditing the skill;
the constants below are the fallback when the reference files are missing.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app import settings
from app.core import knowledge_registry

logger = logging.getLogger("app.core.screenwriting.pacing")

SKILL_NAME = "screenwriting-master"
SKILL_DIR = settings.skills_root() / SKILL_NAME
CONTENT_MODES = ("drama", "narration")


def pacing_key(content_mode: str) -> str:
    """The manifest key of a content mode's pacing rules: ``episode-pacing-<mode>``."""
    return f"episode-pacing-{content_mode}"


@lru_cache(maxsize=8)
def render_pacing_section(content_mode: str = "drama") -> str:
    """The pacing paragraph for ``content_mode`` (``drama`` or ``narration``), read from the skill."""
    if content_mode not in CONTENT_MODES:
        raise ValueError(f"unknown content_mode: {content_mode!r}")
    item = knowledge_registry.section(pacing_key(content_mode))
    if item is None:
        logger.error("[Screenwriting] screenwriting-master 的 manifest 没有登记 %s", pacing_key(content_mode))
        return ""
    try:
        return item.path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.error("[Screenwriting] 节奏参考文件缺失: %s", item.path)
        return ""


__all__ = ["CONTENT_MODES", "SKILL_DIR", "pacing_key", "render_pacing_section"]
