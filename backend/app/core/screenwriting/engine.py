# -*- coding: utf-8 -*-
"""The Writer Agent's structured screenwriting engine.

Pipeline (each step is one or more JSON-constrained LLM calls with validation
and reason-carrying retries):

    overview → asset inventory → episode ledger → per episode:
        script plan (content: shots, cast, verbatim utterances, source anchor)
        → prose body (小说体正文: the reading form of the plan, plain text)
        → visual layer (image_prompt / video_prompt, merged by scene_id)

Three source kinds share the pipeline:

- ``outline``    – no prose source; the director plan is turned into an episode
                   ledger (title / hook / beats / teaser) and each episode is
                   *written* from its outline, then told as prose.
- ``novel``      – a prose source is sliced into episodes on verbatim anchors and
                   each slice is *adapted* into shots.
- ``screenplay`` – an author's finished script is sliced on its own episode
                   boundaries and *extracted* verbatim.

Only ``outline`` episodes get an authored prose body: a source-based episode
already has one, its own slice of the source, which the renderer shows verbatim.

The engine is I/O free: it takes a ``caller(system, user, max_tokens) -> str``
and returns/updates a plain ``dict`` state that the service persists.
"""

from __future__ import annotations

import contextvars
import functools
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.core.episode_shape import EpisodeShape
from app.core import creation_modes
from app.core.screenwriting import ledger_ops, review
from app.core.screenwriting.anchors import AnchorRejected, normalize_source_text, resolve_boundaries
from app.core.screenwriting.durations import (
    DEFAULT_EPISODE_TARGET_SECONDS,
    resolve_episode_target_volume,
    supported_shot_durations,
)
from app.core.screenwriting.entries import ENTRY_REVISION_FIELD, entry_revision, evaluate_entry_currency, revision_of
from app.core.screenwriting.models import (
    AnchoredPlanDraft,
    AssetInventory,
    DEFAULT_SCENE_SECONDS,
    LedgerEntry,
    OutlinePlanDraft,
    Overview,
    VisualMergeError,
    VisualScript,
    build_script_plan_model,
    merge_visual_into_scenes,
)
from app.core.screenwriting.prompts import (
    language_scope,
    append_user_instructions,
    build_anchored_plan_prompt,
    build_asset_inventory_prompt,
    build_outline_plan_prompt,
    build_overview_prompt,
    build_prose_prompt,
    build_script_plan_prompt,
    build_visual_prompt,
    sample_source,
)
from app.core.screenwriting.prose import check_prose, normalize_prose, prose_from_scenes, prose_revision_source
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, TextOutputError, call_structured, call_text
from app.core.screenwriting.text_metrics import count_reading_units
from app.core.screenwriting.violations import (
    EPISODE_SHAPE_CODES,
    TOO_FEW_SPOKEN_SHOTS,
    spoken_shot_problem,
    DraftViolation,
    PlanCheckContext,
    check_script_plan,
    mark_replan_flags,
)

logger = logging.getLogger("app.core.screenwriting.engine")

ENGINE_NAME = "screenwriting-master"
STATE_VERSION = 1
SOURCE_KINDS = ("outline", "novel", "screenplay")
PROMPT_STAGES = ("plan", "prose", "visual")
# How much of the previous episode's prose the next one reads for continuity.
_PREVIOUS_ENDING_CHARS = 400

#: Sampling temperature per stage. Extraction and verbatim capture run cool so the JSON
#: and the quoted lines come back exact; prose runs warm; the visual layer sits between.
STAGE_TEMPERATURES: dict[str, float] = {
    "extract": 0.3,      # overview, asset inventory
    "ledger": 0.6,       # episode ledger (outline or anchored)
    "plan": 0.6,         # shot plan written from an outline
    "plan_source": 0.4,  # shot plan cut from a novel / screenplay (verbatim lines)
    "prose": 0.8,        # the episode's prose body
    "visual": 0.5,       # image / video prompts
}


def _in_context(fn, *args):
    """``fn(*args)`` bound to a copy of the calling thread's context (language scope, sampling profile)."""
    context = contextvars.copy_context()
    return lambda: context.run(fn, *args)
# Violations the model is asked to fix on retry, but which a human edit may keep
# (the shot is flagged ``needs_replan`` instead of the whole draft being refused).
_SOFT_ON_HUMAN_EDIT = frozenset({"speech_exceeds_max", "utterance_not_verbatim", "mixed_speech", creation_modes.NARRATION_DIALOGUE})

ProgressFn = Callable[[int, str], None]


def _in_output_language(method):
    """Build every prompt inside the call in the engine's language (zh / en / vi)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with language_scope(self.language):
            return method(self, *args, **kwargs)
    return wrapper


class RepairNotImproved(RuntimeError):
    """The model's repair left as many violations as before; the earlier draft is kept."""

    def __init__(self, episode: int, reasons: list[str]):
        super().__init__(f"第 {episode} 集修复后违约没有减少，保留原草稿：{'; '.join(reasons)}")
        self.episode = episode
        self.reasons = list(reasons)


class ScreenwritingError(RuntimeError):
    """The structured pipeline could not produce a usable result."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _episode_key(number: int) -> str:
    return str(int(number))


def detect_source_kind(source_text: str | None) -> str:
    """``screenplay`` when the text already reads as a script, ``novel`` for prose, ``outline`` for none."""
    if not source_text or not source_text.strip():
        return "outline"
    from app.core.writer_dashboard import EPISODE_HEADING, SCENE_HEADING, SPEAKER_LINE  # local import: avoid a cycle at module load

    sample = source_text[:20000]
    speaker_lines = len(SPEAKER_LINE.findall(sample))
    scene_lines = sum(1 for line in sample.splitlines() if SCENE_HEADING.match(line))
    episode_lines = len(EPISODE_HEADING.findall(sample))
    total_lines = max(1, sample.count("\n") + 1)
    if scene_lines >= 2 or episode_lines >= 2 or speaker_lines / total_lines >= 0.2:
        return "screenplay"
    return "novel"


def _project_kind(kinds: Iterable[str]) -> str:
    """One genre for a project read from several sources: all the same, else the novel reading."""
    found = {kind for kind in kinds if kind}
    return next(iter(found)) if len(found) == 1 else "novel"


def _own_episode_inputs(own_episodes: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalise the own-source episodes handed to ``write``; empty texts are not episodes."""
    result: list[dict[str, Any]] = []
    for item in own_episodes or []:
        text = normalize_source_text(str(item.get("text") or ""))
        if not text.strip():
            continue
        kind = str(item.get("source_kind") or "") or detect_source_kind(text)
        if kind not in ("novel", "screenplay"):
            raise ValueError(f"逐集原文的体裁必须是 novel 或 screenplay，不是 {kind!r}")
        result.append({"text": text, "source_kind": kind, "name": str(item.get("name") or "")})
    return result


class ScreenwritingEngine:
    def __init__(
        self,
        caller: LLMCaller,
        *,
        video_model: str = "",
        language: str | None = "zh",
        speech_rate_override: float | None = None,
        episode_target_seconds: int | None = DEFAULT_EPISODE_TARGET_SECONDS,
        style: str = "",
        style_description: str = "",
        aspect_ratio: str = "9:16",
        system_prompt: str = "",
        instructions: str | None = None,
        attempts: int = 3,
        progress: ProgressFn | None = None,
        plan_batch_size: int = 10,
        visual_batch_size: int = 12,
        max_tokens: int = 8000,
        planning_window_chars: int = 30000,
        planning_max_episodes: int = 20,
        director_plan_excerpt_chars: int = 6000,
        supported_durations: Sequence[int] | None = None,
        episode_shape: EpisodeShape | None = None,
        creation: Mapping[str, Any] | None = None,
        episode_concurrency: int = 1,
        system_prompts: Mapping[str, str] | None = None,
        temperatures: Mapping[str, float] | None = None,
        prose_chain: bool = False,
        analysis_chars: int = 48000,
        spoken_shot_ratio: float = 0.7,
    ) -> None:
        self.caller = caller
        self.video_model = video_model
        self.language = language
        self.speech_rate_override = speech_rate_override
        self.episode_target_seconds = episode_target_seconds
        # The least a drafted episode may be; a draft below it is sent back to the model.
        self.episode_shape = episode_shape or EpisodeShape()
        # The project's kind of film (drama / narration / ad) and its brief: extra plan rules.
        self.creation = dict(creation or {})
        self.style = style
        self.style_description = style_description
        self.aspect_ratio = aspect_ratio
        self.system_prompt = system_prompt
        # A stage may carry its own system prompt (less knowledge for extraction and visuals);
        # a stage without one uses ``system_prompt``.
        self.system_prompts = {str(stage): str(prompt) for stage, prompt in (system_prompts or {}).items() if str(prompt)}
        self.temperatures = {**STAGE_TEMPERATURES, **{str(stage): float(value) for stage, value in (temperatures or {}).items()}}
        # Prose chained on the previous episode's finished prose (serial), or told from the
        # previous plan's ending so every episode's prose runs side by side (default).
        self.prose_chain = bool(prose_chain)
        # The one-shot analysis stages read at most this much of a long source.
        self.analysis_chars = max(1000, int(analysis_chars))
        # Episodes written from an outline must put speech in this share of their shots; the
        # model gets its retries to add dialogue, and a still-quiet last round is kept with a warning.
        self.spoken_shot_ratio = max(0.0, min(1.0, float(spoken_shot_ratio or 0)))
        self.instructions = (instructions or "").strip() or None
        self.attempts = max(1, attempts)
        # Episodes are planned and visualised side by side; progress reports may then arrive from
        # several threads, so they go through one lock and never move backwards.
        self.episode_concurrency = max(1, int(episode_concurrency))
        self._progress_lock = threading.Lock()
        self._progress_high = 0
        report = progress or (lambda percent, label: None)

        def _progress(percent: int, label: str) -> None:
            with self._progress_lock:
                self._progress_high = max(self._progress_high, int(percent))
                report(self._progress_high, label)

        self.progress = _progress
        self.plan_batch_size = max(1, plan_batch_size)
        self.visual_batch_size = max(1, visual_batch_size)
        self.max_tokens = max(2000, max_tokens)
        self.planning_window_chars = max(2000, planning_window_chars)
        self.planning_max_episodes = max(1, planning_max_episodes)
        self.director_plan_excerpt_chars = max(500, director_plan_excerpt_chars)
        self.supported_durations = sorted({int(value) for value in supported_durations}) if supported_durations else supported_shot_durations(video_model)

    def _system(self, stage: str) -> str:
        return self.system_prompts.get(stage) or self.system_prompt

    def _temperature(self, stage: str) -> float | None:
        return self.temperatures.get(stage)

    # ------------------------------------------------------------------ public API

    @_in_output_language
    def write(
        self,
        *,
        title: str,
        director_plan: str,
        episode_count: int,
        source_text: str | None = None,
        source_kind: str | None = None,
        own_episodes: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run the whole pipeline and return the persisted state dict.

        ``source_text`` is the whole source, cut into episodes by the ledger planner.
        ``own_episodes`` are episodes that arrive with their own text (one upload per
        episode: ``{"text", "source_kind", "name"}``); they are not cut, they never
        occupy the whole source, and they follow the planned episodes in broadcast
        order. A project may have both, either, or neither.
        """
        own = _own_episode_inputs(own_episodes)
        kind = source_kind or detect_source_kind(source_text)
        if kind == "outline" and own and not (source_text or "").strip():
            # Nothing to cut and nothing to outline: the project reads as its own episodes do.
            kind = _project_kind(entry["source_kind"] for entry in own)
        if kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source_kind: {kind!r}")
        if kind != "outline" and not (source_text or "").strip() and not own:
            raise ValueError("novel / screenplay 模式需要提供源文")
        episode_count = max(1, int(episode_count))
        normalized_source = normalize_source_text(source_text) if source_text else ""
        own_text = "\n\n".join(entry["text"] for entry in own)
        analysis_source = "\n\n".join(part for part in (normalized_source, own_text) if part) if kind != "outline" else director_plan

        analysis_source = sample_source(analysis_source, self.analysis_chars)

        self.progress(6, "编剧 · 提炼项目概述")
        overview = self._overview(analysis_source, kind, title)

        state: dict[str, Any] = {
            "engine": ENGINE_NAME,
            "version": STATE_VERSION,
            "source_kind": kind,
            "title": title,
            "episode_count": episode_count,
            "stale": False,
            "stale_reason": None,
            "overview": overview,
            "inventory": {"characters": {}, "scenes": {}, "props": {}, "costumes": {}, "effects": {}},
            "ledger": [],
            "episodes": {},
            "warnings": [],
            "durations": {
                "supported": list(self.supported_durations),
                "default": None,
                "episode_target_seconds": self.episode_target_seconds,
                "video_model": self.video_model,
            },
            "language": self.language,
            "director_plan": director_plan,
            "source_text": normalized_source or None,
            "created_at": _now(),
            "updated_at": _now(),
        }

        # The requested count covers the own-source episodes too; whatever is left is planned.
        planned_count = max(0, episode_count - len(own)) if own else episode_count

        def plan_ledger() -> list[LedgerEntry]:
            self.progress(14, "编剧 · 规划分集账本（标题 / 钩子 / 故事节点）")
            if normalized_source:
                return self._plan_anchored(state, planned_count or None)
            if not planned_count:
                return []
            entries = self._plan_outline(state, 1, planned_count)
            for entry in entries:
                entry.source_origin = "none"
            return entries

        # The asset inventory and the ledger both read only the overview and the source, so
        # they are extracted side by side; the serial setting keeps the one-call-at-a-time order.
        self.progress(10, "编剧 · 提取角色 / 场景 / 道具资产")
        if self.episode_concurrency > 1:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="screenwriting-inventory") as pool:
                inventory_future = pool.submit(_in_context(self._inventory, analysis_source, kind, overview))
                planned = plan_ledger()
                state["inventory"] = inventory_future.result()
        else:
            state["inventory"] = self._inventory(analysis_source, kind, overview)
            planned = plan_ledger()
        state["ledger"] = [entry.model_dump(mode="json") for entry in planned]
        state["ledger"].extend(
            self._own_ledger_entry(len(planned) + offset + 1, entry).model_dump(mode="json")
            for offset, entry in enumerate(own)
        )
        if not state["ledger"]:
            raise ScreenwritingError("没有可写的集：既无源文可切分，也无逐集原文")
        state["episode_count"] = max(episode_count, len(state["ledger"]))

        numbers = [int(entry["episode"]) for entry in state["ledger"]]
        self._write_episodes(state, numbers, base_percent=20, span_percent=70)
        state["updated_at"] = _now()
        return state

    @_in_output_language
    def refresh_overview(self, *, source: str, kind: str, title_hint: str) -> dict[str, Any]:
        """Tell the project's overview again from ``source`` (a plan or a sampled source text)."""
        if kind not in SOURCE_KINDS:
            kind = "outline"
        self.progress(6, "编剧 · 重新提炼项目概述")
        return self._overview(sample_source(source, self.analysis_chars), kind, title_hint)

    @_in_output_language
    def plan_replan_candidate(self, state: Mapping[str, Any], from_episode: int) -> list[dict[str, Any]]:
        """Plan the source again from ``from_episode``'s start; the ledger is not touched."""
        start = ledger_ops.replan_start(state, from_episode)
        working = deepcopy(dict(state))
        self.progress(14, f"编剧 · 从第 {from_episode} 集起重新规划分集")
        entries = self._plan_anchored(working, None, start=start)
        return [entry.model_dump(mode="json") for entry in entries]

    @_in_output_language
    def write_missing(self, state: dict[str, Any], missing: Sequence[int]) -> dict[str, Any]:
        """Write the episodes of ``missing`` into ``state`` (planning them first if the ledger lacks them)."""
        state = deepcopy(state)
        wanted = sorted({int(number) for number in missing if int(number) >= 1})
        if not wanted:
            return state
        known = {int(entry["episode"]) for entry in state.get("ledger") or [] if isinstance(entry, Mapping)}
        unplanned = [number for number in wanted if number not in known]
        if unplanned:
            if state.get("source_kind") != "outline":
                raise ScreenwritingError(f"分集账本缺少第 {', '.join(str(n) for n in unplanned)} 集，源文模式下无法凭空补写")
            state["episode_count"] = max(int(state.get("episode_count") or 0), max(unplanned))
            for first, last in _contiguous_runs(unplanned):
                entries = self._plan_outline(state, first, last)
                state["ledger"].extend(entry.model_dump(mode="json") for entry in entries)
            state["ledger"].sort(key=lambda entry: int(entry["episode"]))
        self._write_episodes(state, wanted, base_percent=20, span_percent=70)
        state["updated_at"] = _now()
        return state

    @_in_output_language
    def replace_plan(self, state: dict[str, Any], episode: int, scenes: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
        """Install an edited script plan for ``episode`` and re-author only the shots whose content changed.

        Returns ``(new_state, rewritten_scene_ids)``. Unchanged shots keep their prompts.
        """
        state = deepcopy(state)
        key = _episode_key(episode)
        entry = state.setdefault("episodes", {}).get(key)
        if not isinstance(entry, Mapping):
            raise ScreenwritingError(f"第 {episode} 集尚未写出，无法编辑其分镜规划")
        ctx = self._check_context(state, episode)
        working = deepcopy(scenes)
        check = check_script_plan(working, ctx, repair=True)
        self._apply_mode_rules(working, check, episode)
        # A person is the author here: dialogue that overflows the longest clip or
        # departs from an uploaded script is flagged for them, not refused — otherwise a
        # shot already marked needs_replan would block every later save of the episode.
        # The same goes for an episode that is too short: the editor is told, and may
        # still save the step that gets them from one shot to two.
        soft = _SOFT_ON_HUMAN_EDIT | EPISODE_SHAPE_CODES
        hard = [violation for violation in check.errors if violation.code not in soft]
        if hard:
            raise PlanRejected(hard)
        softened = [v for v in check.errors if v.code in soft]
        check.warnings.extend(DraftViolation(v.code, v.message, v.label, "warning", v.scene_id) for v in softened)
        # The saved plan is a quarantined draft while any of those remain, and a clean one lifts the quarantine.
        draft = review.quarantine([str(v) for v in softened], origin="edit") if softened else None
        self._register_unknown_assets(state, check)
        flagged = mark_replan_flags(working, ctx)
        old_script = entry.get("script") if isinstance(entry.get("script"), Mapping) else {}
        old_scenes = [dict(scene) for scene in (old_script.get("scenes") or []) if isinstance(scene, Mapping)]
        currency = evaluate_entry_currency(working, old_scenes)
        rewrite_ids = set(currency.rewrite_ids)
        to_rewrite = [scene for scene in working if scene.get("scene_id") in rewrite_ids]
        visuals_by_id = {str(scene.get("scene_id")): scene for scene in old_scenes}
        warnings: list[DraftViolation] = list(check.warnings)
        if to_rewrite:
            fresh = self._visual_layer(state, episode, to_rewrite, warnings)
            for scene in fresh:
                visuals_by_id[str(scene["scene_id"])] = scene
        merged: list[dict[str, Any]] = []
        for scene in working:
            sid = str(scene.get("scene_id"))
            previous = visuals_by_id.get(sid) or {}
            finished = dict(scene)
            finished["image_prompt"] = previous.get("image_prompt")
            finished["video_prompt"] = previous.get("video_prompt")
            finished[ENTRY_REVISION_FIELD] = entry_revision(scene)
            merged.append(finished)
        plan = {"title": (entry.get("plan") or {}).get("title") or old_script.get("title") or "", "scenes": working}
        prose = self._prose_after_edit(state, episode, entry, working, warnings)
        self._store_episode(state, episode, plan, merged, warnings, flagged, prose, draft=draft)
        state["updated_at"] = _now()
        return state, sorted(rewrite_ids)

    @_in_output_language
    def dry_run_prompt(self, state: Mapping[str, Any], episode: int, stage: str) -> str:
        """The prompt a stage would send for ``episode`` — for auditing, no model call."""
        ledger = self._ledger_entry(state, episode)
        if stage == "plan":
            return append_user_instructions(self._script_plan_prompt(state, episode, ledger), self.instructions)
        if stage in {"prose", "visual"}:
            entry = (state.get("episodes") or {}).get(_episode_key(episode)) or {}
            plan = entry.get("plan") if isinstance(entry, Mapping) else None
            scenes = list((plan or {}).get("scenes") or [])
            if not scenes:
                raise ScreenwritingError(f"第 {episode} 集尚无分镜规划，无法预览{'小说体正文' if stage == 'prose' else '视觉层'}提示词")
            build = self._prose_prompt if stage == "prose" else self._visual_prompt
            return append_user_instructions(build(state, episode, scenes), self.instructions)
        raise ValueError(f"unknown stage: {stage!r}")

    # ------------------------------------------------------------------ overview / inventory

    def _overview(self, source: str, kind: str, title_hint: str) -> dict[str, Any]:
        prompt = append_user_instructions(build_overview_prompt(source, source_kind=kind, title_hint=title_hint), self.instructions)
        try:
            result = call_structured(
                self.caller, system_prompt=self._system("extract"), user_prompt=prompt, schema=Overview,
                max_tokens=min(self.max_tokens, 3000), attempts=self.attempts, label="overview", temperature=self._temperature("extract"),
            )
        except StructuredOutputError as error:
            logger.warning("[Screenwriting] 概述提炼失败，使用空概述: %s", error)
            return Overview(title=title_hint[:60]).model_dump(mode="json")
        data = result.data
        if not data.get("title"):
            data["title"] = title_hint[:60]
        return data

    def _inventory(self, source: str, kind: str, overview: Mapping[str, Any]) -> dict[str, Any]:
        prompt = append_user_instructions(build_asset_inventory_prompt(source, source_kind=kind, overview=overview), self.instructions)
        try:
            result = call_structured(
                self.caller, system_prompt=self._system("extract"), user_prompt=prompt, schema=AssetInventory,
                max_tokens=self.max_tokens, attempts=self.attempts, label="asset_inventory", temperature=self._temperature("extract"),
            )
        except StructuredOutputError as error:
            logger.warning("[Screenwriting] 资产提取失败，使用空资产表: %s", error)
            return AssetInventory().model_dump(mode="json")
        return result.data

    # ------------------------------------------------------------------ ledger

    def _context_entries(self, state: Mapping[str, Any], before: int, limit: int = 5) -> list[dict[str, Any]]:
        entries = [entry for entry in (state.get("ledger") or []) if isinstance(entry, Mapping) and int(entry.get("episode") or 0) < before]
        entries.sort(key=lambda entry: int(entry.get("episode") or 0))
        return [dict(entry) for entry in entries[-limit:]]

    def _plan_outline(self, state: Mapping[str, Any], first: int, last: int) -> list[LedgerEntry]:
        total = int(state.get("episode_count") or last)
        title = str(state.get("title") or "")
        director_plan = str(state.get("director_plan") or "")
        entries: list[LedgerEntry] = []
        cursor = first
        while cursor <= last:
            batch_last = min(cursor + self.plan_batch_size - 1, last)
            expected = batch_last - cursor + 1
            context = [*self._context_entries(state, cursor), *[entry.model_dump() for entry in entries]][-5:]
            prompt = build_outline_plan_prompt(
                title=title, director_plan=director_plan, overview=state.get("overview"),
                first=cursor, last=batch_last, total=total, context_entries=context,
                target_seconds=self.episode_target_seconds, instructions=self.instructions,
            )

            def _count_validator(data: dict[str, Any], expected: int = expected) -> list[str]:
                got = len(data.get("episodes") or [])
                if got != expected:
                    return [f"episodes 数组长度必须等于 {expected}（对应第 {cursor} 集到第 {batch_last} 集），当前为 {got}"]
                return []

            self.progress(14, f"编剧 · 规划第 {cursor}-{batch_last} 集分集大纲")
            result = call_structured(
                self.caller, system_prompt=self._system("ledger"), user_prompt=prompt, schema=OutlinePlanDraft,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_count_validator], label="episode_outline",
                temperature=self._temperature("ledger"),
            )
            for offset, draft in enumerate(result.data["episodes"]):
                entries.append(LedgerEntry(episode=cursor + offset, **draft))
            cursor = batch_last + 1
        return entries

    def _plan_anchored(self, state: dict[str, Any], episode_count: int | None = None, *, start: int = 0) -> list[LedgerEntry]:
        """Cut the whole source from ``start`` into at most ``episode_count`` episodes (all of it when ``None``).

        Spans are absolute offsets in the whole source; episodes are numbered from 1 and
        the caller places them.
        """
        whole = str(state.get("source_text") or "")
        text = whole[start:]
        kind = str(state.get("source_kind") or "novel")
        if episode_count is None:
            episode_count = int(state.get("episode_count") or 0) or None
        total_units = count_reading_units(text, self.language)
        target_volume = resolve_episode_target_volume(
            language=self.language, target_seconds=self.episode_target_seconds,
            speech_rate_override=self.speech_rate_override, total_units=total_units, episode_count=episode_count,
        )
        entries: list[LedgerEntry] = []
        cursor = 0
        while cursor < len(text) and text[cursor:].strip():
            remaining_episodes = (episode_count - len(entries)) if episode_count else None
            if remaining_episodes is not None and remaining_episodes <= 0:
                # The requested count is exhausted: fold the tail into the last episode.
                entries[-1].source_range["end"] = start + len(text)
                state.setdefault("warnings", []).append(
                    f"源文在第 {len(entries)} 集之后仍有剩余内容，已并入末集（请求集数 {episode_count} 已用尽）"
                )
                break
            remaining_chars = len(text) - cursor
            window_end = len(text) if remaining_chars <= self.planning_window_chars * 1.2 else cursor + self.planning_window_chars
            window = text[cursor:window_end]
            final = window_end >= len(text)
            max_episodes = self.planning_max_episodes if remaining_episodes is None else min(self.planning_max_episodes, remaining_episodes)
            prompt = build_anchored_plan_prompt(
                window=window, window_is_final=final, overview=state.get("overview"), source_kind=kind,
                context_entries=[entry.model_dump() for entry in entries[-5:]], target_volume=target_volume,
                max_episodes=max_episodes, remaining_episodes=remaining_episodes, instructions=self.instructions,
            )
            resolved: dict[str, list[int]] = {}

            def _anchor_validator(data: dict[str, Any], window: str = window, final: bool = final, cap: int = max_episodes) -> list[str]:
                drafts = data.get("episodes") or []
                if len(drafts) > cap:
                    logger.warning("[Screenwriting] 规划输出 %d 集超过每批上限 %d，截断", len(drafts), cap)
                    del drafts[cap:]
                try:
                    resolved["ends"] = resolve_boundaries(window, [draft["end_anchor"] for draft in drafts], snap_whitespace_tail=final)
                except AnchorRejected as error:
                    return error.reasons
                return []

            self.progress(14, f"编剧 · 按原文规划分集（已规划 {len(entries)} 集）")
            result = call_structured(
                self.caller, system_prompt=self._system("ledger"), user_prompt=prompt, schema=AnchoredPlanDraft,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_anchor_validator], label="episode_plan",
                temperature=self._temperature("ledger"),
            )
            ends = resolved.get("ends") or []
            previous = cursor
            for offset, draft in enumerate(result.data["episodes"][: len(ends)]):
                absolute_end = cursor + ends[offset]
                entries.append(LedgerEntry(
                    episode=len(entries) + 1, title=draft["title"], hook=draft["hook"],
                    story_beats=list(draft.get("story_beats") or []), next_episode_teaser=draft.get("next_episode_teaser"),
                    source_range={"start": start + previous, "end": start + absolute_end},
                ))
                previous = absolute_end
            if not ends:
                raise ScreenwritingError("分集规划未产出任何可定位的集")
            cursor = previous
            if final and not text[cursor:].strip():
                break
        if not entries:
            raise ScreenwritingError("源文为空或无法规划分集")
        return entries

    # ------------------------------------------------------------------ per-episode writing

    def _write_episodes(self, state: dict[str, Any], numbers: Sequence[int], *, base_percent: int, span_percent: int) -> None:
        numbers = list(numbers)
        total = max(1, len(numbers))
        ceiling = base_percent + span_percent
        step = max(1, span_percent // (3 * total))
        if self.episode_concurrency <= 1 or len(numbers) <= 1:
            for position, number in enumerate(numbers):
                percent = base_percent + round(span_percent * position / total)
                self.progress(percent, f"编剧 · 第 {number} 集分镜内容规划（共 {len(numbers)} 集）")
                self._write_one(state, number, percent=percent, step=step, ceiling=ceiling)
            return
        self._write_episodes_concurrently(state, numbers, base_percent=base_percent, span_percent=span_percent)

    def _write_episodes_concurrently(self, state: dict[str, Any], numbers: list[int], *, base_percent: int, span_percent: int) -> None:
        """The same episodes as the serial loop, in a fraction of the wall clock.

        Plans only read the ledger and the inventory, and a visual layer only reads its
        plan, so they run side by side. Prose is told per episode as soon as its plan is
        in: it opens on the previous episode's prose when that is already written, else
        on the previous plan's last shots, so no episode waits for another's prose.
        (``prose_chain`` restores the strict chain, one prose after another.) Each plan
        works on its own copy of the state; the asset names it finds are merged in
        episode order, and episode N's prose and visual layer see the inventory as it
        stood after episode N — what the serial loop would have shown them.

        At most ``episode_concurrency`` plans run at once, and at most as many prose /
        visual calls beside them.
        """
        total = len(numbers)
        width = min(self.episode_concurrency, total)
        finished = {"count": 0}
        count_lock = threading.Lock()

        def tick(label: str) -> None:
            with count_lock:
                finished["count"] += 1
                done = finished["count"]
            self.progress(base_percent + round(span_percent * done / (3 * total)), label)

        in_context = _in_context

        def plan_one(number: int) -> dict[str, Any]:
            snapshot = deepcopy(state)
            plan, warnings, flagged, draft = self._script_plan(snapshot, number, self._ledger_entry(snapshot, number))
            tick(f"编剧 · 第 {number} 集分镜内容规划完成")
            return {"plan": plan, "warnings": warnings, "flagged": flagged, "draft": draft, "inventory": snapshot.get("inventory") or {}}

        views: dict[int, dict[str, Any]] = {}
        ready = {number: threading.Event() for number in numbers}
        abort = threading.Event()

        def prose_chain() -> dict[int, dict[str, Any] | None]:
            written: dict[int, dict[str, Any] | None] = {}
            for number in numbers:
                while not ready[number].wait(0.2):
                    if abort.is_set():
                        return written
                previous = str((written[number - 1] or {}).get("text") or "") if number - 1 in written else None
                result = planned[number]
                written[number] = self._author_prose(views[number], number, result["plan"]["scenes"], result["warnings"], previous_prose=previous)
                tick(f"编剧 · 第 {number} 集小说体正文")
            return written

        def prose_one(number: int) -> dict[str, Any] | None:
            previous = planned[number - 1]["plan"]["scenes"] if number - 1 in planned else None
            result = planned[number]
            prose = self._author_prose(views[number], number, result["plan"]["scenes"], result["warnings"], previous_plan=previous)
            tick(f"编剧 · 第 {number} 集小说体正文")
            return prose

        def visual_one(number: int) -> list[dict[str, Any]]:
            scenes = self._visual_layer(views[number], number, deepcopy(planned[number]["plan"]["scenes"]), planned[number]["warnings"])
            tick(f"编剧 · 第 {number} 集视觉层（画面 / 动作 / 运镜）")
            return scenes

        self.progress(base_percent, f"编剧 · 并行编写 {total} 集（{width} 路）")
        planned: dict[int, dict[str, Any]] = {}
        cumulative = deepcopy(state.get("inventory") or {"characters": {}, "scenes": {}, "props": {}, "costumes": {}, "effects": {}})
        # Plans have their own pool; prose and visual layers share a second one of the same
        # width (the chained prose, when chosen, holds one of its workers for the whole run).
        prose_future = None
        prose_futures: dict[int, Any] = {}
        visual_futures: dict[int, Any] = {}
        with ThreadPoolExecutor(max_workers=width, thread_name_prefix="screenwriting-plan") as planners, \
                ThreadPoolExecutor(max_workers=width + (1 if self.prose_chain else 0), thread_name_prefix="screenwriting-tell") as tellers:
            plan_futures = {number: planners.submit(in_context(plan_one, number)) for number in numbers}
            if self.prose_chain:
                prose_future = tellers.submit(in_context(prose_chain))
            try:
                for number in numbers:
                    planned[number] = plan_futures[number].result()
                    for bucket, entries in (planned[number]["inventory"] or {}).items():
                        if isinstance(entries, Mapping):
                            for name, entry in entries.items():
                                cumulative.setdefault(bucket, {}).setdefault(name, entry)
                    views[number] = {**state, "inventory": deepcopy(cumulative)}
                    ready[number].set()
                    if not self.prose_chain:
                        prose_futures[number] = tellers.submit(in_context(prose_one, number))
                    visual_futures[number] = tellers.submit(in_context(visual_one, number))
                prose = prose_future.result() if prose_future is not None else {number: future.result() for number, future in prose_futures.items()}
                visuals = {number: future.result() for number, future in visual_futures.items()}
            except BaseException:
                abort.set()
                for future in [*plan_futures.values(), *([prose_future] if prose_future is not None else []), *prose_futures.values(), *visual_futures.values()]:
                    future.cancel()
                raise

        state["inventory"] = cumulative
        for number in numbers:
            result = planned[number]
            scenes = visuals[number]
            for scene in scenes:
                scene[ENTRY_REVISION_FIELD] = entry_revision(scene)
            self._store_episode(state, number, result["plan"], scenes, result["warnings"], result["flagged"], prose[number], draft=result["draft"])
            self._ledger_entry(state, number)["ledger_status"] = "written"

    def _write_one(self, state: dict[str, Any], number: int, *, percent: int, step: int, ceiling: int, repair: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Plan, tell and visualise one episode; returns the quarantine note when the plan still violates a rule."""
        ledger = self._ledger_entry(state, number)
        plan, warnings, flagged, draft = self._script_plan(state, number, ledger, repair=repair)
        if self.entry_kind(state, ledger) == "outline":
            self.progress(min(ceiling, percent + step), f"编剧 · 第 {number} 集小说体正文")
        prose = self._author_prose(state, number, plan["scenes"], warnings)
        self.progress(min(ceiling, percent + 2 * step), f"编剧 · 第 {number} 集视觉层（画面 / 动作 / 运镜）")
        scenes = self._visual_layer(state, number, plan["scenes"], warnings)
        for scene in scenes:
            scene[ENTRY_REVISION_FIELD] = entry_revision(scene)
        self._store_episode(state, number, plan, scenes, warnings, flagged, prose, draft=draft)
        ledger["ledger_status"] = "written"
        return draft

    @_in_output_language
    def repair_episode(self, state: dict[str, Any], episode: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Ask the model to fix a quarantined draft with its reasons in hand; a repair that does not reduce the violations is refused."""
        state = deepcopy(state)
        entry = (state.get("episodes") or {}).get(_episode_key(episode))
        draft = review.draft_of(entry if isinstance(entry, Mapping) else None)
        if not draft:
            raise ScreenwritingError(f"第 {episode} 集不是带违约的草稿，无需修复")
        previous = entry.get("plan") if isinstance(entry.get("plan"), Mapping) else {}
        self.progress(14, f"编剧 · 修复第 {episode} 集草稿")
        remaining = self._write_one(
            state, episode, percent=14, step=20, ceiling=90,
            repair={"reasons": list(draft["reasons"]), "plan": previous, "error_count": len(draft["reasons"])},
        )
        state["updated_at"] = _now()
        outcome = {"episode": int(episode), "repaired": remaining is None, "before": list(draft["reasons"]), "remaining": list(remaining["reasons"]) if remaining else []}
        return state, outcome

    @staticmethod
    def _own_ledger_entry(number: int, source: Mapping[str, Any]) -> LedgerEntry:
        """A ledger row for an episode that arrived with its own text; its outline is read from that text later."""
        return LedgerEntry(
            episode=number,
            title=str(source.get("name") or f"第{number}集"),
            source_origin="own",
            source_text=str(source["text"]),
            source_kind=str(source["source_kind"]),
            source_name=str(source.get("name") or ""),
        )

    @staticmethod
    def entry_kind(state: Mapping[str, Any], ledger: Mapping[str, Any]) -> str:
        """The genre the planner treats ``ledger``'s text as: its own, else the project's."""
        if ledger.get("source_origin") == "own" and ledger.get("source_kind"):
            return str(ledger["source_kind"])
        if ledger.get("source_origin") == "none":
            return "outline"
        return str(state.get("source_kind") or "outline")

    def _ledger_entry(self, state: Mapping[str, Any], episode: int) -> dict[str, Any]:
        for entry in state.get("ledger") or []:
            if isinstance(entry, dict) and int(entry.get("episode") or 0) == int(episode):
                return entry
        raise ScreenwritingError(f"分集账本中没有第 {episode} 集")

    def _next_ledger_entry(self, state: Mapping[str, Any], episode: int) -> dict[str, Any] | None:
        for entry in state.get("ledger") or []:
            if isinstance(entry, dict) and int(entry.get("episode") or 0) == int(episode) + 1:
                return entry
        return None

    def _episode_source(self, state: Mapping[str, Any], ledger: Mapping[str, Any]) -> str:
        if ledger.get("source_origin") == "own":
            return str(ledger.get("source_text") or "")
        if self.entry_kind(state, ledger) == "outline":
            return str(state.get("director_plan") or "")[: self.director_plan_excerpt_chars]
        source_range = ledger.get("source_range") or {}
        text = str(state.get("source_text") or "")
        start = int(source_range.get("start") or 0)
        end = int(source_range.get("end") or len(text))
        return text[start:end]

    def _inventory_maps(self, state: Mapping[str, Any]) -> tuple[dict, dict, dict]:
        inventory = state.get("inventory") if isinstance(state.get("inventory"), Mapping) else {}
        return (
            dict(inventory.get("characters") or {}),
            dict(inventory.get("scenes") or {}),
            dict(inventory.get("props") or {}),
        )

    def _outline_of(self, entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not entry:
            return None
        return {
            "title": entry.get("title"),
            "hook": entry.get("hook"),
            "story_beats": list(entry.get("story_beats") or []),
            "next_episode_teaser": entry.get("next_episode_teaser"),
        }

    def _script_plan_prompt(self, state: Mapping[str, Any], episode: int, ledger: Mapping[str, Any]) -> str:
        characters, scenes, props = self._inventory_maps(state)
        return build_script_plan_prompt(
            source_text=self._episode_source(state, ledger), source_kind=self.entry_kind(state, ledger),
            episode=episode, overview=state.get("overview"), style=self.style or self.style_description,
            characters=characters, scenes=scenes, props=props, supported_durations=self.supported_durations,
            default_duration=None, episode_target_seconds=self.episode_target_seconds,
            episode_shape=self.episode_shape,
            episode_outline=self._outline_of(ledger), next_episode_outline=self._outline_of(self._next_ledger_entry(state, episode)),
            language=self.language, speech_rate_override=self.speech_rate_override,
            spoken_shot_ratio=self.spoken_shot_ratio, creation_mode=str(self.creation.get("creation_mode") or "drama"),
        )

    def _check_context(self, state: Mapping[str, Any], episode: int) -> PlanCheckContext:
        characters, scenes, props = self._inventory_maps(state)
        ledger = self._ledger_entry(state, episode)
        kind = self.entry_kind(state, ledger)
        return PlanCheckContext(
            episode=episode, supported_durations=list(self.supported_durations),
            character_names=list(characters), scene_names=list(scenes), prop_names=list(props),
            source_text=self._episode_source(state, ledger) if kind != "outline" else None,
            source_kind=kind, language=self.language, speech_rate_override=self.speech_rate_override,
            episode_shape=self.episode_shape,
        )

    def _apply_mode_rules(self, scenes: list[dict[str, Any]], check, episode: int) -> None:
        """What the project's kind of film asks of an episode, added to the plan check."""
        for code, message, scene_id, severity in creation_modes.plan_problems(scenes, self.creation):
            violation = DraftViolation(code, message, f"分镜 {scene_id}" if scene_id else f"第 {episode} 集", severity, scene_id or None)
            (check.errors if severity == "error" else check.warnings).append(violation)

    def _register_unknown_assets(self, state: dict[str, Any], check) -> None:
        inventory = state.setdefault("inventory", {"characters": {}, "scenes": {}, "props": {}, "costumes": {}, "effects": {}})
        for name in check.unknown_characters:
            inventory.setdefault("characters", {}).setdefault(name, {"description": "需补充外貌与服装细节", "voice_style": "", "position": "其它角色"})
        for name in check.unknown_scenes:
            inventory.setdefault("scenes", {}).setdefault(name, {"description": "需补充空间与光线描述"})
        for name in check.unknown_props:
            inventory.setdefault("props", {}).setdefault(name, {"description": "需补充外观描述"})

    def _script_plan(
        self, state: dict[str, Any], episode: int, ledger: Mapping[str, Any], *, repair: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[DraftViolation], list[str], dict[str, Any] | None]:
        prompt = self._script_plan_prompt(state, episode, ledger)
        if repair:
            prompt = f"{prompt.rstrip()}\n\n{_repair_section(repair)}"
        prompt = append_user_instructions(prompt, self.instructions)
        schema = build_script_plan_model(self.supported_durations)
        ctx = self._check_context(state, episode)
        last: dict[str, Any] = {}
        draft: dict[str, Any] | None = None

        rounds = {"count": 0}

        def _plan_validator(data: dict[str, Any]) -> list[str]:
            scenes = data.get("scenes") or []
            check = check_script_plan(scenes, ctx, repair=True)
            self._apply_mode_rules(scenes, check, episode)
            last["data"], last["check"] = data, check
            reasons = [str(violation) for violation in check.errors]
            rounds["count"] += 1
            quiet = spoken_shot_problem(scenes, self.spoken_shot_ratio) if ctx.source_kind == "outline" else None
            if quiet:
                # Every round but the last sends the plan back for more dialogue; the last keeps it, flagged.
                if rounds["count"] < self.attempts:
                    reasons.append(quiet)
                else:
                    check.warnings.append(DraftViolation(TOO_FEW_SPOKEN_SHOTS, quiet, f"第 {episode} 集", "warning"))
            return reasons

        try:
            result = call_structured(
                self.caller, system_prompt=self._system("plan"), user_prompt=prompt, schema=schema,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_plan_validator], label=f"script_plan_E{episode}",
                temperature=self._temperature("plan" if ctx.source_kind == "outline" else "plan_source"),
            )
            data, check = result.data, last["check"]
        except StructuredOutputError as error:
            check = last.get("check")
            # An uploaded script fixes how much there is to film, so its short episode is kept
            # and flagged; an episode the model wrote itself has no such excuse.
            keepable = _SOFT_ON_HUMAN_EDIT if ctx.source_kind == "outline" else _SOFT_ON_HUMAN_EDIT | EPISODE_SHAPE_CODES
            if not last.get("data") or check is None or any(v.code not in keepable for v in check.errors):
                raise ScreenwritingError(f"第 {episode} 集分镜内容规划失败：{error}") from error
            if repair and len(check.errors) >= int(repair.get("error_count") or 0):
                raise RepairNotImproved(episode, [str(v) for v in check.errors])
            # Only "cannot fit" / verbatim problems remain: keep the draft, flag the shots,
            # and quarantine it so it cannot be confirmed until someone repairs it.
            data = last["data"]
            logger.warning("[Screenwriting] 第 %d 集内容规划保留带违约草稿: %s", episode, error.reasons)
            draft = review.quarantine([str(v) for v in check.errors], origin="repair" if repair else "model", attempts=self.attempts)
            check.warnings.extend(DraftViolation(v.code, v.message, v.label, "warning", v.scene_id) for v in check.errors)
        scenes = data.get("scenes") or []
        self._register_unknown_assets(state, check)
        flagged = mark_replan_flags(scenes, ctx)
        plan = {"title": str(data.get("title") or ledger.get("title") or f"第{episode}集"), "scenes": scenes}
        return plan, list(check.warnings), flagged, draft

    # ------------------------------------------------------------------ prose body

    @staticmethod
    def _tail(prose: str) -> str:
        if len(prose) <= _PREVIOUS_ENDING_CHARS:
            return prose
        tail = prose[-_PREVIOUS_ENDING_CHARS:]
        # Start on a paragraph so the excerpt never opens mid-sentence.
        return tail.split("\n\n", 1)[1] if "\n\n" in tail else tail

    def _previous_ending(
        self, state: Mapping[str, Any], episode: int, previous_prose: str | None = None,
        previous_plan: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[str, bool]:
        """How the previous episode closed, and whether that is its plan rather than its prose.

        The previous prose wins whenever it exists (``previous_prose`` or the stored
        episode); an episode told side by side with its predecessor gets that
        predecessor's last shots told plainly instead.
        """
        if previous_prose is not None:
            return self._tail(previous_prose), False
        entry = (state.get("episodes") or {}).get(_episode_key(episode - 1)) if episode > 1 else None
        stored = str((entry or {}).get("prose") or "") if isinstance(entry, Mapping) else ""
        if stored:
            return self._tail(stored), False
        if previous_plan:
            scenes = [scene for scene in previous_plan if isinstance(scene, Mapping)]
            return self._tail(prose_from_scenes(scenes[-2:])), True
        return "", False

    def _prose_prompt(
        self, state: Mapping[str, Any], episode: int, content_scenes: Sequence[Mapping[str, Any]],
        previous_prose: str | None = None, previous_plan: Sequence[Mapping[str, Any]] | None = None,
    ) -> str:
        characters, _scenes, _props = self._inventory_maps(state)
        cast = {name for scene in content_scenes if isinstance(scene, Mapping) for name in (scene.get("characters_in_scene") or [])}
        present = {name: entry for name, entry in characters.items() if name in cast}
        previous_ending, previous_is_plan = self._previous_ending(state, episode, previous_prose, previous_plan)
        return build_prose_prompt(
            episode=episode, overview=state.get("overview"), style=self.style or self.style_description,
            characters=present or characters, content_scenes=content_scenes,
            episode_outline=self._outline_of(self._ledger_entry(state, episode)),
            previous_ending=previous_ending, previous_is_plan=previous_is_plan, language=self.language,
        )

    def _author_prose(
        self, state: Mapping[str, Any], episode: int, content_scenes: list[dict[str, Any]], warnings: list[DraftViolation],
        previous_prose: str | None = None, previous_plan: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Tell the fixed plan of ``episode`` as prose; ``None`` when the episode reads from its own source slice."""
        if self.entry_kind(state, self._ledger_entry(state, episode)) != "outline":
            return None
        prompt = append_user_instructions(self._prose_prompt(state, episode, content_scenes, previous_prose, previous_plan), self.instructions)
        names = list(self._inventory_maps(state)[0])
        label = f"第 {episode} 集"
        last: dict[str, Any] = {"rounds": 0}

        def _prose_validator(text: str) -> list[str]:
            check = check_prose(text, content_scenes, character_names=names)
            last["text"], last["check"] = text, check
            last["rounds"] += 1
            if check.errors:
                return check.reasons
            # A draft with only soft findings earns one retry, not the whole budget.
            return check.warnings if last["rounds"] == 1 else []

        try:
            text = call_text(
                self.caller, system_prompt=self._system("prose"), user_prompt=prompt, max_tokens=self.max_tokens,
                attempts=self.attempts, normalize=normalize_prose, validators=[_prose_validator], label=f"prose_E{episode}",
                temperature=self._temperature("prose"),
            ).text
            check = last.get("check")
        except TextOutputError as error:
            check = last.get("check")
            if check is None or check.errors or not last.get("text"):
                logger.warning("[Screenwriting] 第 %d 集小说体正文未通过校验，按分镜内容合成兜底: %s", episode, error.reasons)
                warnings.append(DraftViolation("prose_fallback", "小说体正文由分镜内容机械合成，建议重写", label, "warning"))
                return {"text": prose_from_scenes(content_scenes), "origin": "synthesized", "revision": revision_of(prose_revision_source(content_scenes))}
            text = last["text"]
        if check is not None and check.warnings:
            warnings.append(DraftViolation("prose_unverified", "小说体正文保留了待核对的内容：" + "；".join(check.warnings)[:600], label, "warning"))
        return {"text": text, "origin": "model", "revision": revision_of(prose_revision_source(content_scenes))}

    def _prose_after_edit(
        self, state: Mapping[str, Any], episode: int, entry: Mapping[str, Any],
        content_scenes: list[dict[str, Any]], warnings: list[DraftViolation],
    ) -> dict[str, Any] | None:
        """Keep the prose of an edited plan when nothing it was written from changed; otherwise tell it again."""
        revision = revision_of(prose_revision_source(content_scenes))
        if entry.get("prose") and entry.get("prose_revision") == revision:
            return {"text": str(entry["prose"]), "origin": str(entry.get("prose_origin") or "model"), "revision": revision}
        return self._author_prose(state, episode, content_scenes, warnings)

    # ------------------------------------------------------------------ visual layer

    def _visual_prompt(self, state: Mapping[str, Any], episode: int, content_scenes: Sequence[Mapping[str, Any]]) -> str:
        characters, scenes, props = self._inventory_maps(state)
        return build_visual_prompt(
            episode=episode, overview=state.get("overview"), style=self.style, style_description=self.style_description,
            characters=characters, scenes=scenes, props=props, content_scenes=content_scenes, aspect_ratio=self.aspect_ratio,
        )

    def _visual_layer(self, state: Mapping[str, Any], episode: int, content_scenes: list[dict[str, Any]], warnings: list[DraftViolation]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for start in range(0, len(content_scenes), self.visual_batch_size):
            batch = content_scenes[start:start + self.visual_batch_size]
            expected_ids = [str(scene.get("scene_id")) for scene in batch]
            prompt = append_user_instructions(self._visual_prompt(state, episode, batch), self.instructions)
            # Shots the rounds so far have covered, by id. A round that leaves gaps keeps what it
            # did cover; the retry is asked for the gaps alone, and whichever round closes the
            # last gap completes the batch — the model never redoes shots it already delivered.
            covered: dict[str, dict[str, Any]] = {}

            def _coverage_validator(data: dict[str, Any], expected: list[str] = expected_ids, covered: dict[str, dict[str, Any]] = covered) -> list[str]:
                orphans: list[str] = []
                for scene in data.get("scenes") or []:
                    sid = str(scene.get("scene_id"))
                    if sid in expected:
                        covered[sid] = scene
                    else:
                        orphans.append(sid)
                missing = [sid for sid in expected if sid not in covered]
                if not missing:
                    data["scenes"] = [covered[sid] for sid in expected]
                    return []
                reasons = [f"缺少这些分镜的视觉层：{', '.join(missing)}（只需补齐这些分镜；已输出的分镜不必重复）"]
                if orphans:
                    reasons.append(f"出现了分镜内容中不存在的 scene_id：{', '.join(sorted(set(orphans)))}，scene_id 必须照抄分镜内容里的编号")
                return reasons

            try:
                result = call_structured(
                    self.caller, system_prompt=self._system("visual"), user_prompt=prompt, schema=VisualScript,
                    max_tokens=self.max_tokens, attempts=self.attempts, validators=[_coverage_validator], label=f"visual_E{episode}",
                    temperature=self._temperature("visual"),
                )
                visuals = result.data.get("scenes") or []
            except StructuredOutputError as error:
                # Keep whatever the rounds did cover; only the gaps get a synthesized fallback.
                logger.warning("[Screenwriting] 第 %d 集视觉层生成未完整覆盖，缺失分镜按内容合成兜底: %s", episode, error)
                visuals = list(covered.values())
            by_id = {str(item.get("scene_id")): item for item in visuals if isinstance(item, Mapping)}
            complete: list[dict[str, Any]] = []
            for scene in batch:
                sid = str(scene.get("scene_id"))
                visual = by_id.get(sid)
                if visual is None or "image_prompt" not in visual or "video_prompt" not in visual:
                    visual = _fallback_visual(scene)
                    warnings.append(DraftViolation("visual_fallback", "视觉层由分镜内容机械合成，建议重写", f"分镜 {sid}", "warning", sid))
                complete.append(visual)
            try:
                merged.extend(merge_visual_into_scenes(batch, complete))
            except VisualMergeError as error:  # pragma: no cover - coverage validator makes this unreachable
                raise ScreenwritingError(f"第 {episode} 集视觉层合并失败：{error}") from error
        return merged

    def _store_episode(
        self,
        state: dict[str, Any],
        episode: int,
        plan: dict[str, Any],
        scenes: list[dict[str, Any]],
        warnings: Sequence[DraftViolation],
        flagged: Sequence[str],
        prose: Mapping[str, Any] | None = None,
        draft: Mapping[str, Any] | None = None,
    ) -> None:
        ledger = self._ledger_entry(state, episode)
        script = {
            "episode": episode,
            "title": plan.get("title") or ledger.get("title") or f"第{episode}集",
            "hook": ledger.get("hook") or None,
            "next_episode_teaser": ledger.get("next_episode_teaser"),
            "scenes": scenes,
        }
        state.setdefault("episodes", {})[_episode_key(episode)] = {
            "episode": episode,
            "plan": plan,
            "plan_revision": revision_of(plan),
            "script": script,
            "violations": [violation.to_dict() for violation in warnings],
            "needs_replan": list(flagged),
            "written_at": _now(),
        }
        if draft:
            state["episodes"][_episode_key(episode)][review.DRAFT_KEY] = dict(draft)
        if prose:
            state["episodes"][_episode_key(episode)].update(
                prose=str(prose.get("text") or ""), prose_origin=str(prose.get("origin") or ""), prose_revision=str(prose.get("revision") or ""),
            )


class PlanRejected(ValueError):
    """An edited plan violates content constraints; ``violations`` explain what to fix."""

    def __init__(self, violations: Sequence[DraftViolation]):
        from app.core.screenwriting.violations import render_violation_report

        super().__init__(render_violation_report(violations))
        self.violations = list(violations)


def _repair_section(repair: Mapping[str, Any]) -> str:
    """The extra ask when a draft is being repaired: the reasons it failed and the draft itself."""
    reasons = "\n".join(f"- {reason}" for reason in repair.get("reasons") or [])
    previous = json.dumps(repair.get("plan") or {}, ensure_ascii=False)
    return (
        "## 修复上一版草稿\n"
        "上一版分镜规划没有通过校验，问题如下；请针对这些问题修改，情节走向、出场人物与台词内容尽量保持不变：\n"
        f"{reasons}\n"
        f"上一版草稿（JSON，仅供对照；本次仍须输出完整规划）：\n{previous}"
    )


def _fallback_visual(scene: Mapping[str, Any]) -> dict[str, Any]:
    description = str(scene.get("scene_description") or scene.get("setting") or "画面").strip() or "画面"
    return {
        "scene_id": str(scene.get("scene_id")),
        "image_prompt": {"scene": description, "composition": {"shot_type": "Medium Shot", "lighting": "", "ambiance": ""}},
        "video_prompt": {"action": "", "camera_motion": "Static", "ambiance_audio": ""},
    }


def _contiguous_runs(numbers: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for number in sorted(set(numbers)):
        if runs and number == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    return runs


def default_scene_seconds(state: Mapping[str, Any]) -> int:
    durations = state.get("durations") if isinstance(state.get("durations"), Mapping) else {}
    supported = durations.get("supported") or []
    return int(supported[0]) if supported else DEFAULT_SCENE_SECONDS


__all__ = [
    "ENGINE_NAME",
    "PROMPT_STAGES",
    "PlanRejected",
    "SOURCE_KINDS",
    "STATE_VERSION",
    "ScreenwritingEngine",
    "ScreenwritingError",
    "default_scene_seconds",
    "detect_source_kind",
]
