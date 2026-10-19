"""Admission of a batch of shots to video generation: all of them, or none.

Video is the expensive step, so before stage 5 submits anything every shot is
assessed together against the same facts the request will use. One assessment
has one of three outcomes:

* ``admitted`` — every shot can be generated as it stands;
* ``confirmation_required`` — the only open points are shots whose scripted
  length is not a length the video model offers, so a nearby tier will be
  requested; the person confirms the tiers (and sees their cost) first;
* ``blocked`` — at least one shot cannot be generated; nothing is submitted,
  nothing is charged, and every shot reports its own problems. Shots that were
  fine are listed as withheld, naming the shots that held them back.

A shot that already has a usable clip is quoted as ``reuse`` and costs nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core import usage_ledger
from app.core.screenwriting.durations import renderable_shot_durations
from app.core.screenwriting.speech import speech_problems
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds, normalize_video_provider

Decision = Literal["admitted", "confirmation_required", "blocked"]
Quote = Literal["generate", "reuse", "blocked"]

# Problem codes; the first group blocks, the last asks for a confirmation.
NEEDS_REPLAN = "needs_replan"
MIXED_SPEECH = "mixed_speech"
MISSING_ASSETS = "missing_assets"
UNRESOLVABLE_MODEL = "unresolvable_model"
PROVIDER_NOT_READY = "provider_not_ready"
ACTIVE_TASK = "active_task"
WITHHELD = "generation_batch_admission_withheld"
DURATION_CONFIRMATION = "duration_confirmation_required"
BLOCKING_CODES = frozenset({NEEDS_REPLAN, MIXED_SPEECH, MISSING_ASSETS, UNRESOLVABLE_MODEL, PROVIDER_NOT_READY, ACTIVE_TASK})


@dataclass
class ShotProblem:
    code: str
    message: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "blocking": self.blocking}


@dataclass
class ShotAssessment:
    shot_id: int
    scene_id: str
    quote: Quote
    scripted_seconds: int
    requested_seconds: int
    tier_adjustment: Literal["exact", "up", "down"]
    candidates: int
    problems: list[ShotProblem] = field(default_factory=list)
    withheld_by: list[int] = field(default_factory=list)
    estimate: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "quote": self.quote,
            "scripted_seconds": self.scripted_seconds,
            "requested_seconds": self.requested_seconds,
            "tier_adjustment": self.tier_adjustment,
            "candidates": self.candidates,
            "problems": [problem.as_dict() for problem in self.problems],
            "withheld_by": list(self.withheld_by),
            "estimate": dict(self.estimate),
        }


@dataclass
class BatchAdmission:
    decision: Decision
    video_model: str
    provider_family: str
    shots: list[ShotAssessment]
    confirmations: list[dict[str, Any]]
    estimate: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "video_model": self.video_model,
            "provider_family": self.provider_family,
            "counts": {
                "generate": sum(1 for shot in self.shots if shot.quote == "generate"),
                "reuse": sum(1 for shot in self.shots if shot.quote == "reuse"),
                "blocked": sum(1 for shot in self.shots if shot.quote == "blocked"),
                "withheld": sum(1 for shot in self.shots if shot.withheld_by),
            },
            "shots": [shot.as_dict() for shot in self.shots],
            "confirmations": list(self.confirmations),
            "estimate": dict(self.estimate),
        }

    @property
    def blocking_shot_ids(self) -> list[int]:
        return [shot.shot_id for shot in self.shots if shot.quote == "blocked"]

    def summary(self) -> str:
        """One line for a refusal message."""
        if self.decision == "blocked":
            parts = []
            for shot in self.shots:
                if shot.quote == "blocked":
                    parts.append(f"镜头 {shot.shot_id}：" + "；".join(problem.message for problem in shot.problems if problem.blocking))
            return "批量视频准入受阻，未提交任何镜头：" + " / ".join(parts[:8]) + ("…" if len(parts) > 8 else "")
        if self.decision == "confirmation_required":
            tiers = "、".join(f"{item['scripted_seconds']}s→{item['requested_seconds']}s×{item['shot_count']}" for item in self.confirmations)
            return f"有镜头的剧本时长不在模型支持的档位内，需先确认请求档位：{tiers}"
        return "批量视频准入通过"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def request_tier(scripted: int, supported: Sequence[int]) -> tuple[int, str]:
    """The tier a request uses for a scripted length: the smallest that holds it, else the longest."""
    tiers = sorted({int(value) for value in supported}) or [scripted]
    if scripted in tiers:
        return scripted, "exact"
    for tier in tiers:
        if tier >= scripted:
            return tier, "up"
    return tiers[-1], "down"


def scripted_seconds(shot: Mapping[str, Any], model: str) -> int:
    """The length the script gives this shot, the way stage 5 reads it (workspace edit first, then the heuristic)."""
    ceiling = max_shot_seconds(model)
    visual = shot.get("visual") if isinstance(shot.get("visual"), Mapping) else {}
    explicit = _int(visual.get("duration_seconds")) if visual else 0
    if explicit > 0:
        return max(MIN_SHOT_SECONDS, min(ceiling, explicit))
    dialogue = str(shot.get("dialogue") or "")
    desc = str(shot.get("desc") or "")
    seconds = _int(len(dialogue) / 3.5) + 2 if dialogue else _int(len(desc) / 8) + 2
    stated = _int(str(shot.get("duration") or "").rstrip("s秒"))
    if stated > 0:
        seconds = stated
    return max(MIN_SHOT_SECONDS, min(ceiling, seconds))


def _characters_in(shot: Mapping[str, Any]) -> list[str]:
    names = shot.get("characters")
    if isinstance(names, list):
        return [str(name).strip() for name in names if str(name).strip() and str(name).strip() not in {"无", "-"}]
    return []


def _clip_reusable(clip: Mapping[str, Any] | None) -> bool:
    return bool(clip and clip.get("video_url") and not clip.get("stale"))


def assess_video_batch(
    task: Mapping[str, Any],
    *,
    provider_ready: Any = None,
    confirmed_request_durations: Sequence[Mapping[str, Any]] | None = None,
) -> BatchAdmission:
    """Assess every stage-4 shot of ``task`` for stage 5.

    ``provider_ready(family, model) -> bool`` says whether the routed provider has
    credentials; ``confirmed_request_durations`` is the list of
    ``{"scripted_seconds", "requested_seconds"}`` pairs the person has accepted.
    """
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    model = str(config.get("video_model") or "")
    profile = normalize_video_provider(model)
    shots = [shot for shot in (assets.get("4") or []) if isinstance(shot, Mapping)]
    clips = {str(clip.get("shot_id")): clip for clip in (assets.get("5") or []) if isinstance(clip, Mapping)}
    sheets = assets.get("3_sheets") if isinstance(assets.get("3_sheets"), Mapping) else {}
    # Admission asks what the model can render, not what the writer prefers to plan: a 4 s shot from an
    # older script is still a valid request for a model whose preferred range starts at 5 s.
    supported = renderable_shot_durations(model)
    confirmed = {
        (_int(item.get("scripted_seconds")), _int(item.get("requested_seconds")))
        for item in (confirmed_request_durations or config.get("confirmed_request_durations") or [])
        if isinstance(item, Mapping)
    }
    scenes = _screenwriting_scenes(assets)
    stage_running = (
        task.get("status") == "running"
        and _int((task.get("stage_progress") or {}).get("stage")) == 5
    )
    model_problem: ShotProblem | None = None
    if not model:
        model_problem = ShotProblem(UNRESOLVABLE_MODEL, "项目未选择视频模型，无法决定提交给谁")
    elif provider_ready is not None and not provider_ready(profile.family, model):
        model_problem = ShotProblem(PROVIDER_NOT_READY, f"视频模型族 {profile.family} 没有可用的运行时凭据")

    assessments: list[ShotAssessment] = []
    for index, shot in enumerate(shots, start=1):
        shot_id = _int(shot.get("shot_id"), index)
        scene_id = str(shot.get("scene_id") or "")
        scripted = scripted_seconds(shot, model) if model else max(MIN_SHOT_SECONDS, _int(shot.get("duration"), MIN_SHOT_SECONDS))
        requested, adjustment = request_tier(scripted, supported) if model else (scripted, "exact")
        visual = shot.get("visual") if isinstance(shot.get("visual"), Mapping) else {}
        candidates = max(1, min(4, _int(visual.get("candidates"), 1))) if visual else 1
        problems: list[ShotProblem] = []
        if model_problem:
            problems.append(model_problem)
        if stage_running:
            problems.append(ShotProblem(ACTIVE_TASK, "第 5 阶段正在运行，等它结束再提交"))
        scene = scenes.get(scene_id)
        if scene is not None:
            if scene.get("needs_replan"):
                problems.append(ShotProblem(NEEDS_REPLAN, f"分镜 {scene_id} 的台词装不进任何时长档位，需先在分镜规划里重拆"))
            for code, message in speech_problems(scene):
                problems.append(ShotProblem(code, message))
        missing = [name for name in _characters_in(shot) if sheets and name not in sheets]
        if missing:
            problems.append(ShotProblem(MISSING_ASSETS, "出场角色尚无身份视图：" + "、".join(missing)))
        clip = clips.get(str(shot_id))
        if any(problem.blocking for problem in problems):
            quote: Quote = "blocked"
        elif _clip_reusable(clip):
            quote = "reuse"
        else:
            quote = "generate"
        if quote == "generate" and adjustment != "exact" and (scripted, requested) not in confirmed:
            problems.append(ShotProblem(
                DURATION_CONFIRMATION,
                f"剧本时长 {scripted} 秒不在模型档位内，将按 {requested} 秒请求（不裁剪）",
                blocking=False,
            ))
        estimate = usage_ledger.estimate(model, "video", {"seconds": requested * candidates}) if quote == "generate" else {"priced": True, "cost": 0.0, "currency": None}
        assessments.append(ShotAssessment(
            shot_id=shot_id, scene_id=scene_id, quote=quote, scripted_seconds=scripted,
            requested_seconds=requested, tier_adjustment=adjustment, candidates=candidates,
            problems=problems, estimate=estimate,
        ))

    blocking_ids = [shot.shot_id for shot in assessments if shot.quote == "blocked"]
    if blocking_ids:
        for shot in assessments:
            if shot.quote != "blocked":
                shot.withheld_by = list(blocking_ids)
                shot.problems.append(ShotProblem(WITHHELD, "本镜本可生成，但同批有镜头受阻，整批未提交", blocking=False))
        decision: Decision = "blocked"
    elif any(problem.code == DURATION_CONFIRMATION for shot in assessments for problem in shot.problems):
        decision = "confirmation_required"
    else:
        decision = "admitted"

    confirmations = _tier_confirmations(assessments)
    return BatchAdmission(
        decision=decision, video_model=model, provider_family=profile.family,
        shots=assessments, confirmations=confirmations, estimate=_batch_estimate(assessments),
    )


def _screenwriting_scenes(assets: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Structured scenes by id, when the writer stage produced them."""
    state = assets.get("2_screenwriting")
    scenes: dict[str, Mapping[str, Any]] = {}
    if not isinstance(state, Mapping):
        return scenes
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    for entry in episodes.values():
        script = entry.get("script") if isinstance(entry, Mapping) and isinstance(entry.get("script"), Mapping) else {}
        for scene in script.get("scenes") or []:
            if isinstance(scene, Mapping) and scene.get("scene_id"):
                scenes[str(scene["scene_id"])] = scene
    return scenes


def _tier_confirmations(assessments: Sequence[ShotAssessment]) -> list[dict[str, Any]]:
    """Open tier changes grouped by (scripted, requested): what the person confirms in one go."""
    groups: dict[tuple[int, int], dict[str, Any]] = {}
    for shot in assessments:
        if not any(problem.code == DURATION_CONFIRMATION for problem in shot.problems):
            continue
        key = (shot.scripted_seconds, shot.requested_seconds)
        group = groups.setdefault(key, {
            "scripted_seconds": key[0], "requested_seconds": key[1], "adjustment": shot.tier_adjustment,
            "shot_ids": [], "shot_count": 0, "cost": 0.0, "currency": None, "priced": True,
        })
        group["shot_ids"].append(shot.shot_id)
        group["shot_count"] += 1
        if shot.estimate.get("priced") and shot.estimate.get("currency"):
            group["cost"] = round(group["cost"] + float(shot.estimate.get("cost") or 0.0), 6)
            group["currency"] = shot.estimate["currency"]
        else:
            # One unpriced shot means the tier shows no total rather than a low one.
            group["priced"] = False
            group["cost"] = None
    return [groups[key] for key in sorted(groups)]


def _batch_estimate(assessments: Sequence[ShotAssessment]) -> dict[str, Any]:
    cost = 0.0
    currency: str | None = None
    priced = True
    generate = [shot for shot in assessments if shot.quote == "generate"]
    for shot in generate:
        if shot.estimate.get("priced") and shot.estimate.get("currency"):
            cost = round(cost + float(shot.estimate.get("cost") or 0.0), 6)
            currency = shot.estimate["currency"]
        else:
            priced = False
    seconds = sum(shot.requested_seconds * shot.candidates for shot in generate)
    return {
        "shots_to_generate": len(generate),
        "requested_seconds": seconds,
        "priced": priced and bool(generate),
        "cost": cost if priced and generate else None,
        "currency": currency if priced and generate else None,
    }


