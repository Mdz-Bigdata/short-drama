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
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from app import settings
from app.core.production_knowledge import load_section, stage_lessons_block
from app.core import creation_modes
from app.core.screenwriting import review
from app.core.screenwriting.durations import resolve_episode_target_seconds
from app.core.screenwriting.engine import ENGINE_NAME, ScreenwritingEngine, detect_source_kind
from app.core.screenwriting.renderer import episode_body, episode_scripts, render_breakdown, render_episode_text, render_screenplay
from app.schema.screenwriting import (
    ScreenwritingDurations,
    ScreenwritingEpisodeResponse,
    ScreenwritingEpisodeSummary,
    ScreenwritingReviewStatus,
    ScreenwritingReviewSummary,
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
WRITER_KNOWLEDGE_SECTIONS: tuple[str, ...] = (
    "cinema-craft-redlines", "golden-narrative", "episode-hook-ladder", "dialogue-pacing", "performance-details",
)

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
    return settings.env_flag("SCREENWRITING_FALLBACK_TO_LEGACY", True)


def _int_env(name: str, default: int, minimum: int) -> int:
    return settings.env_int(name, default, minimum=minimum)


# Which knowledge each kind of call carries. Writing calls (ledger, shot plan, prose) get
# every section; the visual layer only needs the performance guide; the one-shot
# extraction calls (overview, asset inventory) get the persona alone. The system
# prompt is resent with every call, so a stage that cannot use a section should not pay for it.
STAGE_KNOWLEDGE: dict[str, tuple[str, ...]] = {
    "write": WRITER_KNOWLEDGE_SECTIONS,
    "visual": ("performance-details",),
    "extract": (),
}
ENGINE_STAGES_BY_KNOWLEDGE = {"ledger": "write", "plan": "write", "prose": "write", "visual": "visual", "extract": "extract"}


def writer_system_prompt(role_prompt: str, shanyin_core: str = "", *, stage: str = "write") -> str:
    """The Writer persona plus the budgeted creative guidance a ``stage`` of the structured pipeline uses."""
    budget = _int_env("SCREENWRITING_KNOWLEDGE_BUDGET", 2500, 0)
    parts = [role_prompt.strip(), WRITER_METHODOLOGY]
    labels = {
        "cinema-craft-redlines": "写作红线与 S 级三冲击（情绪 / 视觉 / 场景顶点）",
        "golden-narrative": "黄金叙事结构（单集模型 / 每集三件事 / 钩子公式）",
        "episode-hook-ladder": "前三集钩子阶梯（E1 引爆 / E2 升级 / E3 反转）、集尾悬念五型与付费墙前三步",
        "dialogue-pacing": "台词语速情绪与停顿重音标注规范",
        "performance-details": "表演细节与具象物理动作指导",
    }
    sections = STAGE_KNOWLEDGE.get(stage, WRITER_KNOWLEDGE_SECTIONS)
    for key in sections:
        text = load_section(key, budget=budget) if budget else ""
        if text:
            parts.append(f"【{labels[key]}】：\n{text}")
    if shanyin_core and budget and stage == "write":
        parts.append("【山音超级编剧大师核心指导规范（节选）】：\n" + shanyin_core[: budget + 500])
    if stage != "extract":
        lessons = stage_lessons_block(2)
        if lessons:
            parts.append(lessons)
    return "\n\n".join(part for part in parts if part)


def writer_system_prompts(role_prompt: str, shanyin_core: str = "") -> dict[str, str]:
    """One system prompt per engine stage (``ledger`` / ``plan`` / ``prose`` / ``visual`` / ``extract``)."""
    by_kind = {kind: writer_system_prompt(role_prompt, shanyin_core, stage=kind) for kind in STAGE_KNOWLEDGE}
    return {stage: by_kind[kind] for stage, kind in ENGINE_STAGES_BY_KNOWLEDGE.items()}


def build_engine(
    call_llm: Callable[..., str],
    *,
    config: Mapping[str, Any],
    title: str,
    system_prompt: str,
    guidance: str = "",
    progress: Callable[[int, str], None] | None = None,
    system_prompts: Mapping[str, str] | None = None,
) -> ScreenwritingEngine:
    """Engine bound to the task's text model, video model and creative style.

    ``system_prompts`` (see ``writer_system_prompts``) gives each stage its own system
    prompt; a stage it leaves out falls back to ``system_prompt``.
    """
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
        system_prompts=system_prompts,
        # The kind of film comes first; the person's own instructions follow and may refine it.
        instructions="\n\n".join(part for part in (creation_modes.writer_guidance(config), guidance) if part.strip()),
        attempts=_int_env("SCREENWRITING_ATTEMPTS", 3, 1),
        # Reasoning models spend part of the budget thinking; 8000 cut episode shot plans off mid-JSON.
        # 1M by default: reasoning models think first, and a tight limit left whole answers empty.
        # The gateway lowers it to what each provider actually accepts (and remembers that).
        max_tokens=_int_env("SCREENWRITING_MAX_TOKENS", 1_000_000, 2000),
        plan_batch_size=_int_env("SCREENWRITING_PLAN_BATCH", 10, 1),
        visual_batch_size=_int_env("SCREENWRITING_VISUAL_BATCH", 12, 1),
        # Episodes planned / visualised side by side; 1 restores the strictly serial order.
        episode_concurrency=_int_env("SCREENWRITING_EPISODE_CONCURRENCY", 3, 1),
        # Prose told side by side from each plan (default), or chained on the previous episode's prose.
        prose_chain=settings.env_flag("SCREENWRITING_PROSE_CHAIN", False),
        # How much of a long source the one-shot analysis stages read (opening, spaced excerpts, ending).
        analysis_chars=_int_env("SCREENWRITING_ANALYSIS_CHARS", 48000, 4000),
        # Talk-heavy episodes: this share of an outline-written episode's shots must carry speech (0 turns it off).
        spoken_shot_ratio=settings.env_float("SCREENWRITING_MIN_SPOKEN_SHOT_RATIO", 0.7, minimum=0.0, maximum=1.0),
        episode_shape=creation_modes.episode_shape_for(config),
        creation={"creation_mode": creation_modes.mode_of(config), "ad_brief": creation_modes.ad_brief(config)},
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


# Breakdown keys a person may have authored in the writer board. A re-projection of the
# structured state regenerates everything else; these survive it.
AUTHORED_BREAKDOWN_KEYS = ("relationships", "relationships_authored", "hidden_roles", "role_positions")


def carry_authored(previous: Mapping[str, Any] | None, breakdown: dict[str, Any]) -> dict[str, Any]:
    """``breakdown`` with the person's edits from ``previous`` laid over it.

    Relations and hidden names come across as they were; role positions set by hand
    override the state's; an authored timeline replaces the one rendered from the ledger.
    """
    if not isinstance(previous, Mapping):
        return breakdown
    # Relations a person edited or asked the analyser for win; ones the inventory produced are
    # re-read from the state, so a newer inventory is not shadowed by an older projection.
    if previous.get("relationships") and (previous.get("relationships_authored") or not breakdown.get("relationships")):
        breakdown["relationships"] = list(previous["relationships"])
        breakdown["relationships_authored"] = bool(previous.get("relationships_authored"))
    if previous.get("hidden_roles"):
        breakdown["hidden_roles"] = list(previous["hidden_roles"])
    positions = previous.get("role_positions") if isinstance(previous.get("role_positions"), Mapping) else {}
    if positions:
        breakdown["role_positions"] = dict(positions)
        known = {str(role.get("name")): role for role in breakdown.get("roles") or [] if isinstance(role, Mapping)}
        for name, position in positions.items():
            if name in known:
                known[name]["position"] = str(position)
            else:
                breakdown.setdefault("roles", []).append({"name": str(name), "position": str(position)})
    if previous.get("timeline_authored") and isinstance(previous.get("timeline"), list):
        breakdown["timeline"] = list(previous["timeline"])
        breakdown["timeline_authored"] = True
    return breakdown


def apply_state(assets: dict[str, Any], state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Persist ``state`` and project it into the screenplay text and breakdown; returns both.

    What a person authored on the previous breakdown (relations, cast positions, hidden
    names, an edited event timeline) is carried over: the projection never undoes an edit.
    """
    text = render_screenplay(state)
    breakdown = carry_authored(assets.get("2_breakdown"), render_breakdown(state))
    assets[STATE_KEY] = state
    assets["2"] = text
    assets["2_breakdown"] = breakdown
    return text, breakdown


def written_episode_numbers(state: Mapping[str, Any]) -> list[int]:
    return [int(script.get("episode") or 0) for script in episode_scripts(state)]


# A library document's part in the project. ``source``: one file of the whole source,
# cut into episodes in library order; ``episode``: one episode's own text, appended
# after the planned episodes in library order; ``reference``: read by people only.
DOCUMENT_ROLES = ("reference", "source", "episode")
DOCUMENT_KINDS = ("novel", "screenplay")
EPISODE_NUMBER_IN_NAME = re.compile(r"(?:第\s*(\d{1,3})\s*集|(?:episode|ep|e)[\s_-]*(\d{1,3})|(\d{1,3}))", re.IGNORECASE)


def document_role_for_name(name: str) -> str:
    """The role a freshly imported file most likely plays, from its name; people may change it."""
    lowered = str(name or "").lower()
    if re.search(r"episode|\bep\d|第\s*\d+\s*集|分集|逐集", lowered):
        return "episode"
    if re.search(r"story|novel|script|screenplay|全本|整本|小说|剧本|完整|全文", lowered):
        return "source"
    return "reference"


def episode_number_in_name(name: str) -> int | None:
    """``episode_3.txt`` → 3: the natural order of own-source files when every name carries a number."""
    stem = str(name or "").rsplit(".", 1)[0]
    match = EPISODE_NUMBER_IN_NAME.search(stem)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def ordered_documents(documents: Sequence[Mapping[str, Any]], role: str) -> list[Mapping[str, Any]]:
    """Library documents of ``role`` in reading order: explicit order, else episode numbers in names, else upload order."""
    chosen = [item for item in documents if isinstance(item, Mapping) and item.get("role") == role]
    def key(pair):
        position, document = pair
        explicit = document.get("order")
        if isinstance(explicit, int) and not isinstance(explicit, bool):
            return (0, explicit, position)
        numbered = episode_number_in_name(str(document.get("name") or ""))
        return (1, numbered if numbered is not None else 10_000, position)
    return [document for _, document in sorted(enumerate(chosen), key=key)]


def document_kind(document: Mapping[str, Any]) -> str:
    kind = str(document.get("source_kind") or "")
    return kind if kind in DOCUMENT_KINDS else ("screenplay" if detect_source_kind(str(document.get("content") or "")) == "screenplay" else "novel")


def library_sources(task: Mapping[str, Any]) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """What the script library contributes: the whole source (with its kind) and the own-source episodes."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    documents = assets.get("2_documents") if isinstance(assets.get("2_documents"), list) else []
    whole = ordered_documents(documents, "source")
    own = [
        {"text": str(item.get("content") or ""), "source_kind": document_kind(item), "name": str(item.get("name") or "")}
        for item in ordered_documents(documents, "episode")
        if str(item.get("content") or "").strip()
    ]
    whole_text = "\n\n".join(str(item.get("content") or "").strip() for item in whole if str(item.get("content") or "").strip())
    if not whole_text:
        return None, None, own
    kinds = {document_kind(item) for item in whole}
    whole_kind = next(iter(kinds)) if len(kinds) == 1 else "novel"
    return whole_text, whole_kind, own


def source_for_task(task: Mapping[str, Any]) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """The engine's sources: the library's whole-source files and own-source episodes, else the single uploaded script."""
    whole_text, whole_kind, own = library_sources(task)
    if whole_text or own:
        return whole_text, whole_kind, own
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    content = str(config.get("script_content") or "")
    if not content.strip():
        return None, None, []
    return content, detect_source_kind(content), []


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
            review=ScreenwritingReviewStatus(**review.status_of(state, int(entry.get("episode") or key))),
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
        review_summary=ScreenwritingReviewSummary(**review.summary(state)),
        warnings=[str(item) for item in (state.get("warnings") or [])][:200],
        updated_at=str(state.get("updated_at") or ""),
    )


def episode_response(
    task: Mapping[str, Any], episode: int, *, rewritten: list[str] | None = None, repair: Mapping[str, Any] | None = None,
) -> ScreenwritingEpisodeResponse | None:
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
        review=ScreenwritingReviewStatus(**review.status_of(state, int(episode))),
        repair=dict(repair) if repair else None,
    )


__all__ = [
    "LEGACY_ENGINE",
    "STATE_KEY",
    "STRUCTURED_ENGINE",
    "WRITER_ENGINE_ENV",
    "AUTHORED_BREAKDOWN_KEYS",
    "apply_state",
    "build_engine",
    "carry_authored",
    "episode_response",
    "fallback_enabled",
    "is_usable",
    "mark_stale",
    "selected_engine",
    "source_for_task",
    "state_of",
    "state_response",
    "writer_system_prompt",
    "writer_system_prompts",
    "written_episode_numbers",
]
