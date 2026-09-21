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

import logging
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

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
    append_user_instructions,
    build_anchored_plan_prompt,
    build_asset_inventory_prompt,
    build_outline_plan_prompt,
    build_overview_prompt,
    build_prose_prompt,
    build_script_plan_prompt,
    build_visual_prompt,
)
from app.core.screenwriting.prose import check_prose, normalize_prose, prose_from_scenes, prose_revision_source
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, TextOutputError, call_structured, call_text
from app.core.screenwriting.text_metrics import count_reading_units
from app.core.screenwriting.violations import (
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
# Violations the model is asked to fix on retry, but which a human edit may keep
# (the shot is flagged ``needs_replan`` instead of the whole draft being refused).
_SOFT_ON_HUMAN_EDIT = frozenset({"speech_exceeds_max", "utterance_not_verbatim"})

ProgressFn = Callable[[int, str], None]


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
    ) -> None:
        self.caller = caller
        self.video_model = video_model
        self.language = language
        self.speech_rate_override = speech_rate_override
        self.episode_target_seconds = episode_target_seconds
        self.style = style
        self.style_description = style_description
        self.aspect_ratio = aspect_ratio
        self.system_prompt = system_prompt
        self.instructions = (instructions or "").strip() or None
        self.attempts = max(1, attempts)
        self.progress = progress or (lambda percent, label: None)
        self.plan_batch_size = max(1, plan_batch_size)
        self.visual_batch_size = max(1, visual_batch_size)
        self.max_tokens = max(2000, max_tokens)
        self.planning_window_chars = max(2000, planning_window_chars)
        self.planning_max_episodes = max(1, planning_max_episodes)
        self.director_plan_excerpt_chars = max(500, director_plan_excerpt_chars)
        self.supported_durations = sorted({int(value) for value in supported_durations}) if supported_durations else supported_shot_durations(video_model)

    # ------------------------------------------------------------------ public API

    def write(
        self,
        *,
        title: str,
        director_plan: str,
        episode_count: int,
        source_text: str | None = None,
        source_kind: str | None = None,
    ) -> dict[str, Any]:
        """Run the whole pipeline and return the persisted state dict."""
        kind = source_kind or detect_source_kind(source_text)
        if kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source_kind: {kind!r}")
        if kind != "outline" and not (source_text or "").strip():
            raise ValueError("novel / screenplay 模式需要提供源文")
        episode_count = max(1, int(episode_count))
        normalized_source = normalize_source_text(source_text) if source_text else ""
        analysis_source = normalized_source if kind != "outline" else director_plan

        self.progress(6, "编剧 · 提炼项目概述")
        overview = self._overview(analysis_source, kind, title)
        self.progress(10, "编剧 · 提取角色 / 场景 / 道具资产")
        inventory = self._inventory(analysis_source, kind, overview)

        state: dict[str, Any] = {
            "engine": ENGINE_NAME,
            "version": STATE_VERSION,
            "source_kind": kind,
            "title": title,
            "episode_count": episode_count,
            "stale": False,
            "stale_reason": None,
            "overview": overview,
            "inventory": inventory,
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

        self.progress(14, "编剧 · 规划分集账本（标题 / 钩子 / 故事节点）")
        if kind == "outline":
            state["ledger"] = [entry.model_dump(mode="json") for entry in self._plan_outline(state, 1, episode_count)]
        else:
            state["ledger"] = [entry.model_dump(mode="json") for entry in self._plan_anchored(state)]

        numbers = [int(entry["episode"]) for entry in state["ledger"]]
        self._write_episodes(state, numbers, base_percent=20, span_percent=70)
        state["updated_at"] = _now()
        return state

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
        # A person is the author here: dialogue that overflows the longest clip or
        # departs from an uploaded script is flagged for them, not refused — otherwise a
        # shot already marked needs_replan would block every later save of the episode.
        hard = [violation for violation in check.errors if violation.code not in _SOFT_ON_HUMAN_EDIT]
        if hard:
            raise PlanRejected(hard)
        check.warnings.extend(
            DraftViolation(v.code, v.message, v.label, "warning", v.scene_id)
            for v in check.errors if v.code in _SOFT_ON_HUMAN_EDIT
        )
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
        self._store_episode(state, episode, plan, merged, warnings, flagged, prose)
        state["updated_at"] = _now()
        return state, sorted(rewrite_ids)

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
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=Overview,
                max_tokens=min(self.max_tokens, 3000), attempts=self.attempts, label="overview",
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
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=AssetInventory,
                max_tokens=self.max_tokens, attempts=self.attempts, label="asset_inventory",
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
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=OutlinePlanDraft,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_count_validator], label="episode_outline",
            )
            for offset, draft in enumerate(result.data["episodes"]):
                entries.append(LedgerEntry(episode=cursor + offset, **draft))
            cursor = batch_last + 1
        return entries

    def _plan_anchored(self, state: dict[str, Any]) -> list[LedgerEntry]:
        text = str(state.get("source_text") or "")
        kind = str(state.get("source_kind") or "novel")
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
                entries[-1].source_range["end"] = len(text)
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
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=AnchoredPlanDraft,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_anchor_validator], label="episode_plan",
            )
            ends = resolved.get("ends") or []
            previous = cursor
            for offset, draft in enumerate(result.data["episodes"][: len(ends)]):
                absolute_end = cursor + ends[offset]
                entries.append(LedgerEntry(
                    episode=len(entries) + 1, title=draft["title"], hook=draft["hook"],
                    story_beats=list(draft.get("story_beats") or []), next_episode_teaser=draft.get("next_episode_teaser"),
                    source_range={"start": previous, "end": absolute_end},
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
        total = max(1, len(numbers))
        ceiling = base_percent + span_percent
        step = max(1, span_percent // (3 * total))
        for position, number in enumerate(numbers):
            percent = base_percent + round(span_percent * position / total)
            self.progress(percent, f"编剧 · 第 {number} 集分镜内容规划（共 {len(numbers)} 集）")
            ledger = self._ledger_entry(state, number)
            plan, warnings, flagged = self._script_plan(state, number, ledger)
            if state.get("source_kind") == "outline":
                self.progress(min(ceiling, percent + step), f"编剧 · 第 {number} 集小说体正文")
            prose = self._author_prose(state, number, plan["scenes"], warnings)
            self.progress(min(ceiling, percent + 2 * step), f"编剧 · 第 {number} 集视觉层（画面 / 动作 / 运镜）")
            scenes = self._visual_layer(state, number, plan["scenes"], warnings)
            for scene in scenes:
                scene[ENTRY_REVISION_FIELD] = entry_revision(scene)
            self._store_episode(state, number, plan, scenes, warnings, flagged, prose)
            ledger["ledger_status"] = "written"

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
        if state.get("source_kind") == "outline":
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
            source_text=self._episode_source(state, ledger), source_kind=str(state.get("source_kind") or "outline"),
            episode=episode, overview=state.get("overview"), style=self.style or self.style_description,
            characters=characters, scenes=scenes, props=props, supported_durations=self.supported_durations,
            default_duration=None, episode_target_seconds=self.episode_target_seconds,
            episode_outline=self._outline_of(ledger), next_episode_outline=self._outline_of(self._next_ledger_entry(state, episode)),
            language=self.language, speech_rate_override=self.speech_rate_override,
        )

    def _check_context(self, state: Mapping[str, Any], episode: int) -> PlanCheckContext:
        characters, scenes, props = self._inventory_maps(state)
        ledger = self._ledger_entry(state, episode)
        kind = str(state.get("source_kind") or "outline")
        return PlanCheckContext(
            episode=episode, supported_durations=list(self.supported_durations),
            character_names=list(characters), scene_names=list(scenes), prop_names=list(props),
            source_text=self._episode_source(state, ledger) if kind != "outline" else None,
            source_kind=kind, language=self.language, speech_rate_override=self.speech_rate_override,
        )

    def _register_unknown_assets(self, state: dict[str, Any], check) -> None:
        inventory = state.setdefault("inventory", {"characters": {}, "scenes": {}, "props": {}})
        for name in check.unknown_characters:
            inventory.setdefault("characters", {}).setdefault(name, {"description": "需补充外貌与服装细节", "voice_style": "", "position": "其它角色"})
        for name in check.unknown_scenes:
            inventory.setdefault("scenes", {}).setdefault(name, {"description": "需补充空间与光线描述"})
        for name in check.unknown_props:
            inventory.setdefault("props", {}).setdefault(name, {"description": "需补充外观描述"})

    def _script_plan(self, state: dict[str, Any], episode: int, ledger: Mapping[str, Any]) -> tuple[dict[str, Any], list[DraftViolation], list[str]]:
        prompt = append_user_instructions(self._script_plan_prompt(state, episode, ledger), self.instructions)
        schema = build_script_plan_model(self.supported_durations)
        ctx = self._check_context(state, episode)
        last: dict[str, Any] = {}

        def _plan_validator(data: dict[str, Any]) -> list[str]:
            scenes = data.get("scenes") or []
            check = check_script_plan(scenes, ctx, repair=True)
            last["data"], last["check"] = data, check
            return [str(violation) for violation in check.errors]

        try:
            result = call_structured(
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=schema,
                max_tokens=self.max_tokens, attempts=self.attempts, validators=[_plan_validator], label=f"script_plan_E{episode}",
            )
            data, check = result.data, last["check"]
        except StructuredOutputError as error:
            check = last.get("check")
            if not last.get("data") or check is None or any(v.code not in _SOFT_ON_HUMAN_EDIT for v in check.errors):
                raise ScreenwritingError(f"第 {episode} 集分镜内容规划失败：{error}") from error
            # Only "cannot fit" / verbatim problems remain: keep the draft, flag the shots.
            data = last["data"]
            logger.warning("[Screenwriting] 第 %d 集内容规划保留带违约草稿: %s", episode, error.reasons)
            check.warnings.extend(DraftViolation(v.code, v.message, v.label, "warning", v.scene_id) for v in check.errors)
        scenes = data.get("scenes") or []
        self._register_unknown_assets(state, check)
        flagged = mark_replan_flags(scenes, ctx)
        plan = {"title": str(data.get("title") or ledger.get("title") or f"第{episode}集"), "scenes": scenes}
        return plan, list(check.warnings), flagged

    # ------------------------------------------------------------------ prose body

    def _previous_ending(self, state: Mapping[str, Any], episode: int) -> str:
        entry = (state.get("episodes") or {}).get(_episode_key(episode - 1)) if episode > 1 else None
        prose = str((entry or {}).get("prose") or "") if isinstance(entry, Mapping) else ""
        if len(prose) <= _PREVIOUS_ENDING_CHARS:
            return prose
        tail = prose[-_PREVIOUS_ENDING_CHARS:]
        # Start on a paragraph so the excerpt never opens mid-sentence.
        return tail.split("\n\n", 1)[1] if "\n\n" in tail else tail

    def _prose_prompt(self, state: Mapping[str, Any], episode: int, content_scenes: Sequence[Mapping[str, Any]]) -> str:
        characters, _scenes, _props = self._inventory_maps(state)
        cast = {name for scene in content_scenes if isinstance(scene, Mapping) for name in (scene.get("characters_in_scene") or [])}
        present = {name: entry for name, entry in characters.items() if name in cast}
        return build_prose_prompt(
            episode=episode, overview=state.get("overview"), style=self.style or self.style_description,
            characters=present or characters, content_scenes=content_scenes,
            episode_outline=self._outline_of(self._ledger_entry(state, episode)),
            previous_ending=self._previous_ending(state, episode), language=self.language,
        )

    def _author_prose(self, state: Mapping[str, Any], episode: int, content_scenes: list[dict[str, Any]], warnings: list[DraftViolation]) -> dict[str, Any] | None:
        """Tell the fixed plan of ``episode`` as prose; ``None`` when the episode reads from its own source slice."""
        if state.get("source_kind") != "outline":
            return None
        prompt = append_user_instructions(self._prose_prompt(state, episode, content_scenes), self.instructions)
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
                self.caller, system_prompt=self.system_prompt, user_prompt=prompt, max_tokens=self.max_tokens,
                attempts=self.attempts, normalize=normalize_prose, validators=[_prose_validator], label=f"prose_E{episode}",
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
            last: dict[str, Any] = {}

            def _coverage_validator(data: dict[str, Any], expected: list[str] = expected_ids, last: dict[str, Any] = last) -> list[str]:
                last["scenes"] = list(data.get("scenes") or [])
                got = [str(scene.get("scene_id")) for scene in data.get("scenes") or []]
                missing = [sid for sid in expected if sid not in got]
                orphans = [sid for sid in got if sid not in expected]
                duplicates = sorted({sid for sid in got if got.count(sid) > 1})
                reasons = []
                if missing:
                    reasons.append(f"缺少这些分镜的视觉层：{', '.join(missing)}")
                if orphans:
                    reasons.append(f"出现了分镜内容中不存在的 scene_id：{', '.join(orphans)}")
                if duplicates:
                    reasons.append(f"scene_id 重复：{', '.join(duplicates)}")
                return reasons

            try:
                result = call_structured(
                    self.caller, system_prompt=self.system_prompt, user_prompt=prompt, schema=VisualScript,
                    max_tokens=self.max_tokens, attempts=self.attempts, validators=[_coverage_validator], label=f"visual_E{episode}",
                )
                visuals = result.data.get("scenes") or []
            except StructuredOutputError as error:
                # Keep whatever the last round did cover; only the gaps get a synthesized fallback.
                logger.warning("[Screenwriting] 第 %d 集视觉层生成未完整覆盖，缺失分镜按内容合成兜底: %s", episode, error)
                visuals = list(last.get("scenes") or [])
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
