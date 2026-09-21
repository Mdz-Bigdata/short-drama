# -*- coding: utf-8 -*-
"""Glue between the structured screenwriting engine and the task pipeline.

``DramaService`` delegates here so the engine stays I/O free: this module builds
the engine from a task's config (model gateway, video model, knowledge budget),
persists the resulting state under ``assets["2_screenwriting"]`` and projects
it into the artifacts the rest of the pipeline reads (``assets["2"]`` screenplay
text as prose, ``assets["2_breakdown"]``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from app.core.production_knowledge import load_section, stage_lessons_block
from app.core.screenwriting.durations import resolve_episode_target_seconds
from app.core.screenwriting.engine import ENGINE_NAME, ScreenwritingEngine, detect_source_kind
from app.core.screenwriting.renderer import episode_body, episode_scripts, render_breakdown, render_episode_text, render_screenplay
from app.schema.screenwriting import (
    ScreenwritingDurations,
    ScreenwritingEpisodeResponse,
    ScreenwritingEpisodeSummary,
    ScreenwritingLedgerEntry,
    ScreenwritingOverview,
    ScreenwritingStateResponse,
    ScreenwritingViolation,
)

logger = logging.getLogger("app.service.screenwriting")

STATE_KEY = "2_screenwriting"
WRITER_ENGINE_ENV = "WRITER_ENGINE"
STRUCTURED_ENGINE = "structured"
LEGACY_ENGINE = "legacy"

# Knowledge sections the Writer keeps in its system prompt for the structured
# pipeline. The pipeline makes several calls per episode, so each section is
# budgeted instead of injected in full like the single-shot legacy prompt.
WRITER_KNOWLEDGE_SECTIONS: tuple[str, ...] = ("golden-narrative", "dialogue-pacing", "performance-details")

WRITER_METHODOLOGY = (
    "Role: AI 专业短剧编剧智能体 (Writer Agent)\n"
    "Methodology: 只写摄影机能拍到的画面和能听到的声音，杜绝任何心理描写和括号暗示，对话高度口语化、单句不超过 15 个字。\n"
    "每一集都按黄金叙事结构落地：前 3 秒强钩子 → 交代冲突 → 压迫升级 → 反击 / 反转 / 情绪爆点 → 结尾 5 秒悬念钩子；"
    "每集至少命中一个爽 / 燃 / 虐 / 怒 / 甜 / 惊情绪点，结尾留「必须看下一集」的问题。\n"
    "剧本按两段式生产：先定稿分镜内容（边界 / 出场资产 / 逐字口播 / 原文锚），再补视觉层（画面 / 动作 / 运镜 / 环境音）；"
    "定稿的分镜内容另写成给人读的小说体正文（叙述段落 + 引号对白，台词逐字不变）。"
    "给出 JSON Schema 的环节严格按 Schema 输出，小说体正文环节只输出纯文本正文。"
)


def selected_engine() -> str:
    value = (os.getenv(WRITER_ENGINE_ENV) or STRUCTURED_ENGINE).strip().lower()
    return LEGACY_ENGINE if value in {LEGACY_ENGINE, "text", "freeform", "0", "off"} else STRUCTURED_ENGINE


def fallback_enabled() -> bool:
    return (os.getenv("SCREENWRITING_FALLBACK_TO_LEGACY") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name) or default))
    except ValueError:
        return default


def writer_system_prompt(role_prompt: str, shanyin_core: str = "") -> str:
    """The Writer persona plus budgeted creative guidance shared by every structured call."""
    budget = _int_env("SCREENWRITING_KNOWLEDGE_BUDGET", 2500, 0)
    parts = [role_prompt.strip(), WRITER_METHODOLOGY]
    labels = {
        "golden-narrative": "黄金叙事结构（单集模型 / 每集三件事 / 钩子公式）",
        "dialogue-pacing": "台词语速情绪与停顿重音标注规范",
        "performance-details": "表演细节与具象物理动作指导",
    }
    for key in WRITER_KNOWLEDGE_SECTIONS:
        text = load_section(key, budget=budget) if budget else ""
        if text:
            parts.append(f"【{labels[key]}】：\n{text}")
    if shanyin_core and budget:
        parts.append("【山音超级编剧大师核心指导规范（节选）】：\n" + shanyin_core[: budget + 500])
    lessons = stage_lessons_block(2)
    if lessons:
        parts.append(lessons)
    return "\n\n".join(part for part in parts if part)


def build_engine(
    call_llm: Callable[..., str],
    *,
    config: Mapping[str, Any],
    title: str,
    system_prompt: str,
    guidance: str = "",
    progress: Callable[[int, str], None] | None = None,
) -> ScreenwritingEngine:
    """Engine bound to the task's text model, video model and creative style."""
    llm_model = str(config.get("llm_model") or "")
    dir_style = str(config.get("director_style") or "")
    shot_style = str(config.get("shot_style") or "")

    def caller(system: str, user: str, max_tokens: int) -> str:
        return call_llm(llm_model, system, user, title, dir_style, shot_style, user_instruction="", max_tokens=max_tokens) or ""

    return ScreenwritingEngine(
        caller,
        video_model=str(config.get("video_model") or ""),
        language=str(config.get("source_language") or "zh"),
        episode_target_seconds=resolve_episode_target_seconds(config),
        style=dir_style or "真人电影写实",
        style_description=f"运镜风格：{shot_style}" if shot_style else "",
        aspect_ratio=str(config.get("aspect_ratio") or "9:16"),
        system_prompt=system_prompt,
        instructions=guidance,
        attempts=_int_env("SCREENWRITING_ATTEMPTS", 3, 1),
        max_tokens=_int_env("SCREENWRITING_MAX_TOKENS", 8000, 2000),
        plan_batch_size=_int_env("SCREENWRITING_PLAN_BATCH", 10, 1),
        visual_batch_size=_int_env("SCREENWRITING_VISUAL_BATCH", 12, 1),
        progress=progress,
    )


def state_of(task: Mapping[str, Any]) -> dict[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get(STATE_KEY)
    return state if isinstance(state, dict) and state.get("engine") == ENGINE_NAME else None


def is_usable(state: Mapping[str, Any] | None) -> bool:
    return bool(state) and not state.get("stale") and isinstance(state.get("episodes"), Mapping) and bool(state.get("episodes"))


def mark_stale(task: dict[str, Any], reason: str) -> None:
    state = state_of(task)
    if state is not None:
        state["stale"] = True
        state["stale_reason"] = reason


def apply_state(assets: dict[str, Any], state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Persist ``state`` and project it into the screenplay text and breakdown; returns both."""
    text = render_screenplay(state)
    breakdown = render_breakdown(state)
    assets[STATE_KEY] = state
    assets["2"] = text
    assets["2_breakdown"] = breakdown
    return text, breakdown


def written_episode_numbers(state: Mapping[str, Any]) -> list[int]:
    return [int(script.get("episode") or 0) for script in episode_scripts(state)]


def source_for_task(config: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The uploaded script (if any) as the engine's source, with its detected kind."""
    content = str(config.get("script_content") or "")
    if not content.strip():
        return None, None
    return content, detect_source_kind(content)


# ---------------------------------------------------------------------------- API projections


def _summaries(state: Mapping[str, Any]) -> list[ScreenwritingEpisodeSummary]:
    summaries: list[ScreenwritingEpisodeSummary] = []
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    for key in sorted(episodes, key=lambda item: int(item) if str(item).isdigit() else 0):
        entry = episodes[key]
        if not isinstance(entry, Mapping):
            continue
        script = entry.get("script") if isinstance(entry.get("script"), Mapping) else {}
        scenes = [scene for scene in (script.get("scenes") or []) if isinstance(scene, Mapping)]
        summaries.append(ScreenwritingEpisodeSummary(
            episode=int(entry.get("episode") or key),
            title=str(script.get("title") or "")[:500],
            scene_count=len(scenes),
            duration_seconds=sum(int(scene.get("duration_seconds") or 0) for scene in scenes),
            plan_revision=str(entry.get("plan_revision") or ""),
            violation_count=len(entry.get("violations") or []),
            needs_replan=[str(item) for item in (entry.get("needs_replan") or [])],
            written_at=str(entry.get("written_at") or ""),
        ))
    return summaries


def state_response(task: Mapping[str, Any]) -> ScreenwritingStateResponse:
    task_id = str(task.get("task_id") or "unknown-task")
    state = state_of(task)
    if state is None:
        return ScreenwritingStateResponse(task_id=task_id, available=False)
    overview = state.get("overview") if isinstance(state.get("overview"), Mapping) else {}
    durations = state.get("durations") if isinstance(state.get("durations"), Mapping) else {}
    inventory = state.get("inventory") if isinstance(state.get("inventory"), Mapping) else {}
    return ScreenwritingStateResponse(
        task_id=task_id,
        available=True,
        engine=str(state.get("engine") or ""),
        version=int(state.get("version") or 0),
        source_kind=state.get("source_kind"),
        stale=bool(state.get("stale")),
        stale_reason=state.get("stale_reason"),
        title=str(state.get("title") or "")[:500],
        episode_count=int(state.get("episode_count") or 0),
        overview=ScreenwritingOverview(**{key: str(overview.get(key) or "") for key in ("title", "synopsis", "genre", "theme", "world_setting")}),
        inventory={
            bucket: {str(name): dict(entry) if isinstance(entry, Mapping) else {} for name, entry in (inventory.get(bucket) or {}).items()}
            for bucket in ("characters", "scenes", "props")
        },
        ledger=[ScreenwritingLedgerEntry(**entry) for entry in (state.get("ledger") or []) if isinstance(entry, Mapping)],
        durations=ScreenwritingDurations(
            supported=[int(value) for value in (durations.get("supported") or [])],
            default=durations.get("default"),
            episode_target_seconds=durations.get("episode_target_seconds"),
            video_model=str(durations.get("video_model") or ""),
        ),
        episodes=_summaries(state),
        warnings=[str(item) for item in (state.get("warnings") or [])][:200],
        updated_at=str(state.get("updated_at") or ""),
    )


def episode_response(task: Mapping[str, Any], episode: int, *, rewritten: list[str] | None = None) -> ScreenwritingEpisodeResponse | None:
    state = state_of(task)
    if state is None:
        return None
    entry = (state.get("episodes") or {}).get(str(int(episode)))
    if not isinstance(entry, Mapping):
        return None
    script = deepcopy(entry.get("script")) if isinstance(entry.get("script"), Mapping) else {}
    plan = deepcopy(entry.get("plan")) if isinstance(entry.get("plan"), Mapping) else {}
    return ScreenwritingEpisodeResponse(
        task_id=str(task.get("task_id") or "unknown-task"),
        episode=int(episode),
        title=str(script.get("title") or plan.get("title") or "")[:500],
        hook=script.get("hook"),
        next_episode_teaser=script.get("next_episode_teaser"),
        plan_revision=str(entry.get("plan_revision") or ""),
        stale=bool(state.get("stale")),
        plan=plan,
        script=script,
        screenplay_text=render_episode_text(script, episode_body(state, int(episode))) if script else "",
        violations=[ScreenwritingViolation(**item) for item in (entry.get("violations") or []) if isinstance(item, Mapping)],
        needs_replan=[str(item) for item in (entry.get("needs_replan") or [])],
        written_at=str(entry.get("written_at") or ""),
        rewritten_scene_ids=list(rewritten or []),
    )


__all__ = [
    "LEGACY_ENGINE",
    "STATE_KEY",
    "STRUCTURED_ENGINE",
    "WRITER_ENGINE_ENV",
    "apply_state",
    "build_engine",
    "episode_response",
    "fallback_enabled",
    "is_usable",
    "mark_stale",
    "selected_engine",
    "source_for_task",
    "state_of",
    "state_response",
    "writer_system_prompt",
    "written_episode_numbers",
]
