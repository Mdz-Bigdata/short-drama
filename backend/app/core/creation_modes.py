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
from app.core import prompt_data


_WORDING_FILE = "creation_modes"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/creation_modes.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

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
    "drama": ModeInfo("drama", _text_of("module.mode_info.drama"), _text_of("module.mode_info.drama.2")),
    "narration": ModeInfo("narration", _text_of("module.mode_info.narration"), _text_of("module.mode_info.narration.2")),
    "ad": ModeInfo("ad", _text_of("module.mode_info.ad"), _text_of("module.mode_info.ad.2")),
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
            _text_of("writer_guidance.text")
        )
    if mode == "ad":
        brief = ad_brief(config)
        lines = list(_words_of("writer_guidance.lines"))
        labelled = (_words_of("writer_guidance.labelled"), _words_of("writer_guidance.labelled.2"), _words_of("writer_guidance.labelled.3"), _words_of("writer_guidance.labelled.4"))
        facts = [f"{label}：{brief[key]}" for key, label in labelled if brief[key]]
        if facts:
            lines.append(_text_of("writer_guidance.text.2") + "；".join(facts))
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
                found.append((NARRATION_DIALOGUE, _text_of("plan_problems.text"), str(scene.get("scene_id") or ""), "error"))
    elif mode == "ad":
        cta = ad_brief(config)["call_to_action"]
        last = next((s for s in reversed(scenes) if isinstance(s, dict)), None)
        if cta and last is not None:
            spoken = " ".join(str(u.get("text") or "") for u in last.get("utterances") or [] if isinstance(u, dict))
            seen = f"{last.get('scene_description') or ''} {spoken}"
            if _core(cta) not in _core(seen):
                found.append((AD_MISSING_CTA, _text_of("plan_problems.text.2").format(cta[:30]), str(last.get("scene_id") or ""), "warning"))
    return found


def _core(text: str) -> str:
    return "".join(ch for ch in str(text) if ch.isalnum()).lower()


def promotion_guidance(config: Mapping[str, Any] | None) -> str:
    """The stage-8 line about the kind of film, so the copy fits it."""
    mode = mode_of(config)
    if mode == "narration":
        return _text_of("promotion_guidance.text")
    if mode == "ad":
        brief = ad_brief(config)
        tail = _text_of("promotion_guidance.tail").format(brief['call_to_action']) if brief["call_to_action"] else ""
        return _text_of("promotion_guidance.text.2").format(('「' + brief['product'] + '」') if brief['product'] else '', tail)
    return ""


def options() -> list[dict[str, str]]:
    return [{"id": info.id, "label": info.label, "description": info.description} for info in MODE_INFO.values()]


__all__ = [
    "AD_MISSING_CTA", "DEFAULT_MODE", "MODES", "MODE_INFO", "NARRATION_DIALOGUE", "CreationMode",
    "ad_brief", "episode_shape_for", "mode_of", "options", "plan_problems", "promotion_guidance", "writer_guidance",
]
