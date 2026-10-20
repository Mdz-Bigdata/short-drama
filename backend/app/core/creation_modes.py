"""What kind of film a project is: a drama, a narrated story, or an advertisement.

The kind decides how the writer plans an episode and what the checks ask of it:

- **drama** (剧情) — characters speak on screen; the default and what every
  project was before this existed.
- **narration** (旁白解说) — a narrator tells the story over the pictures; the
  characters act but do not speak, so every spoken line is a voiceover.
- **ad** (广告) — a short spot built from a brief: the hook in the first
  seconds, the product shown plainly, the call to action at the end; episodes
  are seconds long, not minutes.

The episode frame of a narrated story is the deployment's; an advertisement has
its own, overridable with ``CREATION_AD_*``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app import settings
from app.core.episode_shape import EpisodeShape, configured_episode_shape

CreationMode = Literal["drama", "narration", "ad"]
MODES: tuple[CreationMode, ...] = ("drama", "narration", "ad")
DEFAULT_MODE: CreationMode = "drama"

# A spot runs a quarter of a minute to a minute, in a handful of shots.
AD_MIN_SCENES = 3
AD_MIN_SECONDS = 15
AD_MAX_SECONDS = 60

# Codes the plan checks raise for a mode; the engine treats them like other speech problems.
NARRATION_DIALOGUE = "mode_dialogue_in_narration"
AD_MISSING_CTA = "ad_missing_call_to_action"


@dataclass(frozen=True)
class ModeInfo:
    id: CreationMode
    label: str
    description: str


MODE_INFO: dict[CreationMode, ModeInfo] = {
    "drama": ModeInfo("drama", "剧情短剧", "角色在画面里说话，按集推进剧情"),
    "narration": ModeInfo("narration", "旁白解说", "旁白讲述故事，角色只表演不开口，适合小说解说与故事号"),
    "ad": ModeInfo("ad", "广告短片", "按产品简报做 15–60 秒的短片：开场抓人、产品清楚、结尾行动号召"),
}


def mode_of(config: Mapping[str, Any] | None) -> CreationMode:
    value = str((config or {}).get("creation_mode") or "").strip()
    return value if value in MODES else DEFAULT_MODE  # type: ignore[return-value]


def ad_brief(config: Mapping[str, Any] | None) -> dict[str, str]:
    """The advertisement's brief: product, selling points, audience, call to action (all optional text)."""
    raw = (config or {}).get("ad_brief")
    brief = raw if isinstance(raw, Mapping) else {}
    return {key: str(brief.get(key) or "").strip()[:500] for key in ("product", "selling_points", "audience", "call_to_action")}


def episode_shape_for(config: Mapping[str, Any] | None) -> EpisodeShape:
    """The episode frame this project's kind asks for."""
    if mode_of(config) != "ad":
        return configured_episode_shape()
    min_seconds = settings.env_int("CREATION_AD_MIN_SECONDS", AD_MIN_SECONDS, minimum=1)
    return EpisodeShape(
        min_scenes=settings.env_int("CREATION_AD_MIN_SCENES", AD_MIN_SCENES, minimum=1),
        min_seconds=min_seconds,
        max_seconds=settings.env_int("CREATION_AD_MAX_SECONDS", AD_MAX_SECONDS, minimum=min_seconds),
    )


def writer_guidance(config: Mapping[str, Any] | None) -> str:
    """What the planning prompt is told about the kind of film; empty for a drama."""
    mode = mode_of(config)
    if mode == "narration":
        return (
            "创作类型：旁白解说。整部作品由旁白讲述——每个有口播的分镜只用 voiceover（旁白）一种口播，"
            "角色在画面里只做动作与表情、不开口说台词；旁白用第三人称，交代人物心思与前因后果，"
            "画面负责把旁白说的事演出来。没有旁白的分镜可以只有画面。"
        )
    if mode == "ad":
        brief = ad_brief(config)
        lines = [
            "创作类型：广告短片。这是一支短片而不是连续剧：",
            "1. 第一个分镜在 3 秒内抛出痛点或悬念，让人停下来；",
            "2. 中段让产品清楚出现，演示卖点带来的变化，不要只靠口播夸；",
            "3. 最后一个分镜给出行动号召，画面与口播都要落在它上面；",
            "4. 口播短而有力，一个分镜一句话；不得编造产品没有的功效或数据。",
        ]
        labelled = (("product", "产品"), ("selling_points", "卖点"), ("audience", "目标人群"), ("call_to_action", "行动号召"))
        facts = [f"{label}：{brief[key]}" for key, label in labelled if brief[key]]
        if facts:
            lines.append("产品简报（以此为准）：" + "；".join(facts))
        return "\n".join(lines)
    return ""


def plan_problems(scenes: list[dict[str, Any]], config: Mapping[str, Any] | None) -> list[tuple[str, str, str | None, str]]:
    """Mode rules a planned episode breaks: (code, message, scene_id, severity)."""
    from app.core.screenwriting.speech import utterance_kinds

    mode = mode_of(config)
    found: list[tuple[str, str, str | None, str]] = []
    if mode == "narration":
        for scene in scenes:
            if isinstance(scene, dict) and utterance_kinds(scene)[0]:
                found.append((NARRATION_DIALOGUE, "旁白解说模式下角色不开口：把这句台词改写成旁白，或删去", str(scene.get("scene_id") or ""), "error"))
    elif mode == "ad":
        cta = ad_brief(config)["call_to_action"]
        last = next((s for s in reversed(scenes) if isinstance(s, dict)), None)
        if cta and last is not None:
            spoken = " ".join(str(u.get("text") or "") for u in last.get("utterances") or [] if isinstance(u, dict))
            seen = f"{last.get('scene_description') or ''} {spoken}"
            if _core(cta) not in _core(seen):
                found.append((AD_MISSING_CTA, f"最后一个分镜要落在行动号召「{cta[:30]}」上（画面或口播里出现它）", str(last.get("scene_id") or ""), "warning"))
    return found


def _core(text: str) -> str:
    return "".join(ch for ch in str(text) if ch.isalnum()).lower()


def promotion_guidance(config: Mapping[str, Any] | None) -> str:
    """The stage-8 line about the kind of film, so the copy fits it."""
    mode = mode_of(config)
    if mode == "narration":
        return "这是一部旁白解说作品：文案突出故事悬念与讲述感，不要写成角色对白体。"
    if mode == "ad":
        brief = ad_brief(config)
        tail = f"行动号召必须是「{brief['call_to_action']}」。" if brief["call_to_action"] else ""
        return f"这是一支广告短片：文案围绕产品{('「' + brief['product'] + '」') if brief['product'] else ''}的真实卖点，结尾给出行动号召，不得夸大功效。{tail}"
    return ""


def options() -> list[dict[str, str]]:
    return [{"id": info.id, "label": info.label, "description": info.description} for info in MODE_INFO.values()]


__all__ = [
    "AD_MISSING_CTA", "DEFAULT_MODE", "MODES", "MODE_INFO", "NARRATION_DIALOGUE", "CreationMode",
    "ad_brief", "episode_shape_for", "mode_of", "options", "plan_problems", "promotion_guidance", "writer_guidance",
]
