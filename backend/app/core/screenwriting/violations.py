# -*- coding: utf-8 -*-
"""Content-constraint checks for a drafted script plan.

A violation is a machine-readable fact ("this shot's dialogue does not fit its
duration"), not a schema error. Hard violations go back to the model as retry
reasons; soft ones are repaired mechanically where possible and otherwise kept
with the plan as warnings so the dashboard and the editor can show them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.episode_shape import EpisodeShape
from app.core.screenwriting.prose import spoken_verbatim_in
from app.core.screenwriting.speech import speech_problems
from app.core.screenwriting.speech_rate import estimate_spoken_seconds

SCENE_ID_PATTERN = re.compile(r"^E(\d+)S(\d{2,})(?:_(\d+))?$")
Severity = Literal["error", "warning"]


@dataclass
class DraftViolation:
    code: str
    message: str
    label: str = ""
    severity: Severity = "error"
    scene_id: str | None = None

    def __str__(self) -> str:
        prefix = f"{self.label}：" if self.label else ""
        return f"{prefix}{self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "label": self.label,
            "severity": self.severity,
            "scene_id": self.scene_id,
        }


def render_violation_report(violations: Sequence[DraftViolation]) -> str:
    lines = []
    for index, violation in enumerate(violations, start=1):
        lines.append(f"{index}. [{violation.code}] {violation}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


@dataclass
class PlanCheckContext:
    episode: int
    supported_durations: list[int]
    character_names: list[str] = field(default_factory=list)
    scene_names: list[str] = field(default_factory=list)
    prop_names: list[str] = field(default_factory=list)
    source_text: str | None = None
    source_kind: str = "outline"
    language: str | None = None
    speech_rate_override: float | None = None
    # The least an episode may be; ``None`` checks the shots only (a partial plan, not a whole episode).
    episode_shape: EpisodeShape | None = None


# Whole-episode problems: too few shots or too little film. The model is sent back
# to fix them; a person editing a plan is warned instead of refused.
EPISODE_SHAPE_CODES = frozenset({"episode_too_few_scenes", "episode_too_short"})
TOO_FEW_SPOKEN_SHOTS = "too_few_spoken_shots"


def spoken_shot_problem(scenes, spoken_shot_ratio: float) -> str | None:
    """Why an episode is too quiet, or ``None``: fewer than ``spoken_shot_ratio`` of its shots carry speech."""
    ratio = max(0.0, min(1.0, float(spoken_shot_ratio or 0)))
    shots = [scene for scene in scenes if isinstance(scene, dict)]
    if ratio <= 0 or not shots:
        return None
    spoken = [
        scene for scene in shots
        if any(isinstance(item, dict) and str(item.get("text") or "").strip() for item in (scene.get("utterances") or []))
    ]
    needed = int(-(-len(shots) * ratio // 1))  # ceil
    if len(spoken) >= needed:
        return None
    silent = [str(scene.get("scene_id") or "") for scene in shots if scene not in spoken]
    return (
        f"台词太少：{len(shots)} 个分镜只有 {len(spoken)} 个有口播，至少要 {needed} 个（{int(round(ratio * 100))}%）。"
        f"给这些分镜补上人物对白（有来有回的短台词），只有空镜 / 转场可以不说话：{', '.join(silent[:12])}"
    )


@dataclass
class PlanCheckResult:
    errors: list[DraftViolation] = field(default_factory=list)
    warnings: list[DraftViolation] = field(default_factory=list)
    # Names the plan used that are not in the inventory; the engine registers them.
    unknown_characters: list[str] = field(default_factory=list)
    unknown_scenes: list[str] = field(default_factory=list)
    unknown_props: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[DraftViolation]:
        return [*self.errors, *self.warnings]


def spoken_seconds_of(scene: Mapping[str, Any], *, language: str | None, override: float | None) -> float:
    total = 0.0
    for utterance in scene.get("utterances") or []:
        if isinstance(utterance, Mapping):
            total += estimate_spoken_seconds(str(utterance.get("text") or ""), language, override)
    return total


def smallest_tier_at_least(seconds: float, supported: Iterable[int]) -> int | None:
    for tier in sorted(set(int(value) for value in supported)):
        if tier >= seconds:
            return tier
    return None


def check_script_plan(scenes: list[dict[str, Any]], ctx: PlanCheckContext, *, repair: bool = True) -> PlanCheckResult:
    """Validate (and optionally mechanically repair) a script plan in place.

    Repairs performed when ``repair`` is true: scene ids re-prefixed to the current
    episode, dialogue speakers added to the cast list, durations raised to the
    smallest legal tier that fits the dialogue. Anything that cannot be repaired
    becomes an error (retry the model) or a warning (kept with the plan).
    """
    result = PlanCheckResult()
    if not scenes:
        result.errors.append(DraftViolation("empty_plan", "分镜列表为空：至少产出一个分镜"))
        return result

    supported = sorted(set(int(value) for value in ctx.supported_durations)) or [8]
    max_tier = supported[-1]
    known_characters = set(ctx.character_names)
    known_scenes = set(ctx.scene_names)
    known_props = set(ctx.prop_names)
    seen_ids: set[str] = set()
    normalized_source = _normalize(ctx.source_text) if ctx.source_text else ""

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            result.errors.append(DraftViolation("bad_scene", f"scenes[{index - 1}] 必须是分镜对象"))
            continue
        raw_id = str(scene.get("scene_id") or "").strip()
        label = f"分镜 {raw_id or index}"
        match = SCENE_ID_PATTERN.match(raw_id)
        if not match:
            if repair:
                raw_id = f"E{ctx.episode}S{index:02d}"
                scene["scene_id"] = raw_id
                result.warnings.append(
                    DraftViolation("scene_id_rewritten", f"scene_id 不合规范，已改写为 {raw_id}", label, "warning", raw_id)
                )
            else:
                result.errors.append(DraftViolation("scene_id_format", "scene_id 须为 E{集}S{两位序号} 格式", label, scene_id=raw_id))
                continue
        elif int(match.group(1)) != ctx.episode:
            rewritten = f"E{ctx.episode}S{match.group(2)}" + (f"_{match.group(3)}" if match.group(3) else "")
            if repair:
                scene["scene_id"] = rewritten
                raw_id = rewritten
            else:
                result.errors.append(DraftViolation("scene_id_episode", f"scene_id 集号必须是 E{ctx.episode}", label, scene_id=raw_id))
        if raw_id in seen_ids:
            result.errors.append(DraftViolation("scene_id_duplicate", f"scene_id 重复: {raw_id}", label, scene_id=raw_id))
            continue
        seen_ids.add(raw_id)
        label = f"分镜 {raw_id}"

        # ---- asset references
        cast = [name for name in (scene.get("characters_in_scene") or []) if isinstance(name, str) and name.strip()]
        cast = list(dict.fromkeys(name.strip() for name in cast))
        for name in scene.get("scenes") or []:
            if isinstance(name, str) and known_scenes and name not in known_scenes and name not in result.unknown_scenes:
                result.unknown_scenes.append(name)
        for name in scene.get("props") or []:
            if isinstance(name, str) and known_props and name not in known_props and name not in result.unknown_props:
                result.unknown_props.append(name)

        # ---- utterances
        utterances = [item for item in (scene.get("utterances") or []) if isinstance(item, dict)]
        for utterance in utterances:
            if utterance.get("kind") == "dialogue":
                speaker = str(utterance.get("speaker") or "").strip()
                if speaker and speaker not in cast:
                    if repair:
                        cast.append(speaker)
                        result.warnings.append(
                            DraftViolation("speaker_added_to_cast", f"说话人「{speaker}」未列入出场角色，已补入", label, "warning", raw_id)
                        )
                    else:
                        result.errors.append(DraftViolation("speaker_not_in_cast", f"说话人「{speaker}」必须出现在 characters_in_scene", label, scene_id=raw_id))
            text = str(utterance.get("text") or "")
            # A prose script may split one line around an action beat; that is still verbatim.
            if (
                ctx.source_kind == "screenplay" and normalized_source and text
                and _normalize(text) not in normalized_source
                and not spoken_verbatim_in(ctx.source_text or "", text)
            ):
                result.errors.append(
                    DraftViolation("utterance_not_verbatim", f"台词「{text[:24]}…」在原文中找不到，成品剧本的台词必须逐字保留", label, scene_id=raw_id)
                )
        scene["characters_in_scene"] = cast
        # One voice per shot: dialogue on screen or narration over it, never both in one clip.
        for code, message in speech_problems(scene):
            result.errors.append(DraftViolation(code, message, label, scene_id=raw_id))
        for name in cast:
            if known_characters and name not in known_characters and name not in result.unknown_characters:
                result.unknown_characters.append(name)

        # ---- source anchor (best effort)
        anchor = str(scene.get("source_text") or "")
        if anchor and normalized_source and _normalize(anchor) not in normalized_source:
            result.warnings.append(DraftViolation("source_text_unanchored", "source_text 与原文不一致，仅作追溯参考", label, "warning", raw_id))

        # ---- duration vs. dialogue
        raw_duration = scene.get("duration_seconds")
        try:
            duration = int(raw_duration) if raw_duration is not None else None
        except (TypeError, ValueError):
            duration = None
        if duration is None or duration not in supported:
            fallback = smallest_tier_at_least(duration or 0, supported) or max_tier
            if repair:
                scene["duration_seconds"] = fallback
                duration = fallback
                result.warnings.append(
                    DraftViolation("duration_snapped", f"时长 {raw_duration!r} 不在支持档位 {supported}，已改为 {fallback} 秒", label, "warning", raw_id)
                )
            else:
                result.errors.append(DraftViolation("duration_unsupported", f"时长必须取自 {supported}", label, scene_id=raw_id))
                continue
        spoken = spoken_seconds_of(scene, language=ctx.language, override=ctx.speech_rate_override)
        if spoken > duration:
            tier = smallest_tier_at_least(spoken, supported)
            if tier is not None:
                if repair:
                    scene["duration_seconds"] = tier
                    result.warnings.append(
                        DraftViolation("duration_raised_for_speech", f"口播约 {spoken:.1f} 秒超过 {duration} 秒，时长已提到 {tier} 秒", label, "warning", raw_id)
                    )
                else:
                    result.errors.append(DraftViolation("speech_overflow", f"口播约 {spoken:.1f} 秒装不进 {duration} 秒", label, scene_id=raw_id))
            else:
                result.errors.append(
                    DraftViolation(
                        "speech_exceeds_max",
                        f"口播约 {spoken:.1f} 秒超过最长档 {max_tier} 秒，请把这段口播拆成多个分镜（每个分镜的台词不超过 {max_tier} 秒能念完的量）",
                        label,
                        scene_id=raw_id,
                    )
                )

    if ctx.episode_shape is not None:
        durations = [scene.get("duration_seconds") for scene in scenes if isinstance(scene, dict)]
        total_seconds = sum(value for value in durations if isinstance(value, int) and not isinstance(value, bool))
        for issue in ctx.episode_shape.issues(len(durations), total_seconds):
            violation = DraftViolation(issue.code, issue.message, f"第 {ctx.episode} 集", issue.severity)
            (result.errors if issue.severity == "error" else result.warnings).append(violation)

    return result


def mark_replan_flags(scenes: list[dict[str, Any]], ctx: PlanCheckContext) -> list[str]:
    """After retries are exhausted, flag shots whose speech still cannot fit any legal tier."""
    flagged: list[str] = []
    supported = sorted(set(int(value) for value in ctx.supported_durations)) or [8]
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        spoken = spoken_seconds_of(scene, language=ctx.language, override=ctx.speech_rate_override)
        if spoken > supported[-1] or speech_problems(scene):
            scene["needs_replan"] = True
            scene["duration_seconds"] = supported[-1]
            flagged.append(str(scene.get("scene_id")))
        else:
            scene.pop("needs_replan", None)
    return flagged


__all__ = [
    "DraftViolation",
    "EPISODE_SHAPE_CODES",
    "TOO_FEW_SPOKEN_SHOTS",
    "spoken_shot_problem",
    "PlanCheckContext",
    "PlanCheckResult",
    "SCENE_ID_PATTERN",
    "check_script_plan",
    "mark_replan_flags",
    "render_violation_report",
    "smallest_tier_at_least",
    "spoken_seconds_of",
]
