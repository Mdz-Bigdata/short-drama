# -*- coding: utf-8 -*-
"""Genre pacing rules injected into every screenwriting prompt.

The rule text lives in ``backend/skills/screenwriting-master/references`` so the
same wording is read by the prompt builders and by anyone auditing the skill;
the constants below are the fallback when the reference files are missing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("app.core.screenwriting.pacing")

SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "screenwriting-master"
REFERENCE_DIR = SKILL_DIR / "references"

PACING_RULE_FILES: dict[str, str] = {
    "drama": "episode-pacing-drama.md",
    "narration": "episode-pacing-narration.md",
}

_FALLBACK: dict[str, str] = {
    "drama": (
        "分集节奏（短剧体裁建议）：\n"
        "- 开篇约 4 秒承担钩子职能：用强冲击、悬念或危机切入，避免介绍性远景与铺垫。\n"
        "- 中段每约 15 秒安排一次转折点（动作转折、情绪反差、关系撕裂、异常事件），"
        "通过画面权重与景别变化呈现，避免长段平铺。\n"
        "- 末镜停在情绪极致瞬间，景别倾向近景或特写，把「必须看下一集」的问题留在画面上。"
    ),
    "narration": (
        "分集节奏（旁白/解说建议）：\n"
        "- 开篇约 4 秒直接抛出本集最抓人的信息点，不做背景铺垫。\n"
        "- 中段按信息密度切分，每个分镜承载一个完整语义单元，每约 15 秒换一次画面重心。\n"
        "- 末镜停在悬而未决的信息上，为下一集留出追看动机。"
    ),
}


@lru_cache(maxsize=8)
def render_pacing_section(content_mode: str = "drama") -> str:
    """The pacing paragraph for ``content_mode`` (``drama`` or ``narration``)."""
    try:
        file_name = PACING_RULE_FILES[content_mode]
    except KeyError:
        raise ValueError(f"unknown content_mode: {content_mode!r}") from None
    path = REFERENCE_DIR / file_name
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        logger.debug("[Screenwriting] 节奏参考文件缺失，回退内置文本: %s", path)
    return _FALLBACK[content_mode]


__all__ = ["PACING_RULE_FILES", "REFERENCE_DIR", "SKILL_DIR", "render_pacing_section"]
