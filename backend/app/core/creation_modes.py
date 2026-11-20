"""What kind of film a project is: a drama, a narrated story, an advertisement, or a single short film.

The kind decides how the writer plans an episode and what the checks ask of it:

- **drama** (剧情) — characters speak on screen; the default and what every
  project was before this existed.
- **narration** (旁白解说) — a narrator tells the story over the pictures; the
  characters act but do not speak, so every spoken line is a voiceover.
- **ad** (广告) — a short spot built from a brief: the hook in the first
  seconds, the product shown plainly, the call to action at the end; episodes
  are seconds long, not minutes.
- **film** (电影短片) — one complete episode: a lead with a visible goal, a hidden
  need and a belief that gives way; an opponent that makes sense; an ending that
  closes instead of selling the next episode. It is always one episode, minutes
  long, and may be quieter than a drama.

The episode frame of a narrated story is the deployment's; an advertisement and
a short film have their own, overridable with ``CREATION_AD_*`` / ``CREATION_FILM_*``.
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

CreationMode = Literal["drama", "narration", "ad", "film"]
MODES: tuple[CreationMode, ...] = ("drama", "narration", "ad", "film")
DEFAULT_MODE: CreationMode = "drama"

# A spot runs a quarter of a minute to a minute, in a handful of shots.
AD_MIN_SCENES = 3
AD_MIN_SECONDS = 15
AD_MAX_SECONDS = 60

# A short film is one episode of two to eight minutes, and need not talk as much as a serial does.
FILM_EPISODES = 1
FILM_MIN_SCENES = 6
FILM_MIN_SECONDS = 120
FILM_MAX_SECONDS = 480
FILM_TARGET_SECONDS = 240
FILM_SPOKEN_SHOT_RATIO = 0.4

# Codes the plan checks raise for a mode; the engine treats them like other speech problems.
NARRATION_DIALOGUE = "mode_dialogue_in_narration"
AD_MISSING_CTA = "ad_missing_call_to_action"
FILM_OPEN_ENDING = "film_open_ending"
FILM_REVERSALS = "film_reversal_count"


@dataclass(frozen=True)
class ModeInfo:
    id: CreationMode
    label: str
    description: str


MODE_INFO: dict[CreationMode, ModeInfo] = {
    "drama": ModeInfo("drama", _text_of("module.mode_info.drama"), _text_of("module.mode_info.drama.2")),
    "narration": ModeInfo("narration", _text_of("module.mode_info.narration"), _text_of("module.mode_info.narration.2")),
    "ad": ModeInfo("ad", _text_of("module.mode_info.ad"), _text_of("module.mode_info.ad.2")),
    "film": ModeInfo("film", _text_of("module.mode_info.film"), _text_of("module.mode_info.film.2")),
}


def mode_of(config: Mapping[str, Any] | None) -> CreationMode:
    value = str((config or {}).get("creation_mode") or "").strip()
    return value if value in MODES else DEFAULT_MODE  # type: ignore[return-value]


AD_STORY_LED = "story"


def ad_brief(config: Mapping[str, Any] | None) -> dict[str, str]:
    """The advertisement's brief: product, selling points, audience, call to action (all optional text)."""
    raw = (config or {}).get("ad_brief")
    brief = raw if isinstance(raw, Mapping) else {}
    found = {key: str(brief.get(key) or "").strip()[:500] for key in ("product", "selling_points", "audience", "call_to_action")}
    # 「剧情带货」：先讲一场小戏，产品在戏里自然出场；其余值都按普通广告短片。
    found["format"] = AD_STORY_LED if str(brief.get("format") or "").strip() == AD_STORY_LED else ""
    return found


def episode_shape_for(config: Mapping[str, Any] | None) -> EpisodeShape:
    """The episode frame this project's kind asks for."""
    if mode_of(config) == "film":
        film_seconds = settings.env_int("CREATION_FILM_MIN_SECONDS", FILM_MIN_SECONDS, minimum=1)
        return EpisodeShape(
            min_scenes=settings.env_int("CREATION_FILM_MIN_SCENES", FILM_MIN_SCENES, minimum=1),
            min_seconds=film_seconds,
            max_seconds=settings.env_int("CREATION_FILM_MAX_SECONDS", FILM_MAX_SECONDS, minimum=film_seconds),
        )
    if mode_of(config) != "ad":
        return configured_episode_shape()
    min_seconds = settings.env_int("CREATION_AD_MIN_SECONDS", AD_MIN_SECONDS, minimum=1)
    return EpisodeShape(
        min_scenes=settings.env_int("CREATION_AD_MIN_SCENES", AD_MIN_SCENES, minimum=1),
        min_seconds=min_seconds,
        max_seconds=settings.env_int("CREATION_AD_MAX_SECONDS", AD_MAX_SECONDS, minimum=min_seconds),
    )


def episode_count_for(mode: Any, requested: int) -> int:
    """How many episodes a project of this kind has: a short film is one, whatever was asked for."""
    return FILM_EPISODES if str(mode or "") == "film" else requested


def episode_target_for(config: Mapping[str, Any] | None, resolved: int | None) -> int | None:
    """The length an episode aims at. A short film that names none aims at four minutes — the serial default
    (a minute and a half) is shorter than a film may be — and one that names less than its frame allows aims at
    the frame's minimum."""
    if mode_of(config) != "film":
        return resolved
    shortest = episode_shape_for(config).min_seconds
    if (config or {}).get("episode_target_duration") is None or resolved is None:
        return max(shortest, settings.env_int("CREATION_FILM_TARGET_SECONDS", FILM_TARGET_SECONDS, minimum=1))
    return max(shortest, resolved)


def spoken_shot_ratio_for(config: Mapping[str, Any] | None, configured: float) -> float:
    """The share of shots that must carry speech: a short film may be quieter than the deployment asks of a serial."""
    if mode_of(config) != "film":
        return configured
    return min(configured, settings.env_float("CREATION_FILM_SPOKEN_SHOT_RATIO", FILM_SPOKEN_SHOT_RATIO, minimum=0.0, maximum=1.0))


def director_frame(config: Mapping[str, Any] | None) -> str:
    """How many episodes a serial has and how long each one is, for the stage-1 director's request.

    Without it the director assumes a long series (60 episodes) and places its motif, tag line and paywall
    on episodes the project does not have. A short film is told its length by ``director_guidance``; an
    advert has its own brief; both get an empty string here."""
    if mode_of(config) not in ("drama", "narration"):
        return ""
    from app.core.screenwriting.durations import resolve_episode_target_seconds

    count = max(1, int((config or {}).get("episode_count") or 1))
    seconds = episode_target_for(config, resolve_episode_target_seconds(config))
    key = "director_frame.serial" if seconds else "director_frame.serial_no_length"
    return _text_of(key).format(count=count, seconds=seconds)


def director_guidance(config: Mapping[str, Any] | None) -> str:
    """What the stage-1 director is told about the kind of film; empty unless the kind changes what a plan is.

    A short film's plan is also told how long the film is: left to itself the director plans nine minutes for a
    frame that ends at eight."""
    if mode_of(config) != "film":
        return ""
    from app.core.screenwriting.durations import resolve_episode_target_seconds

    shape = episode_shape_for(config)
    length = _text_of("director_guidance.film_length").format(
        target=episode_target_for(config, resolve_episode_target_seconds(config)), low=shape.min_seconds, high=shape.max_seconds,
    )
    return _text_of("director_guidance.film") + length


def writer_guidance(config: Mapping[str, Any] | None) -> str:
    """What the planning prompt is told about the kind of film; empty for a drama."""
    mode = mode_of(config)
    if mode == "film":
        return "\n".join(_words_of("writer_guidance.film"))
    if mode == "narration":
        return (
            _text_of("writer_guidance.text")
        )
    if mode == "ad":
        brief = ad_brief(config)
        lines = list(_words_of("writer_guidance.lines"))
        if brief["format"] == AD_STORY_LED:
            lines += list(_words_of("writer_guidance.story_led"))
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
    elif mode == "film":
        shots = [scene for scene in scenes if isinstance(scene, dict)]
        last = shots[-1] if shots else None
        # The ending closes: a last shot the plan itself calls a hook or a question is the first shot of a serial.
        ending = str((last or {}).get("emotion_point") or "").strip()
        if last is not None and ending in _words_of("film_open_ending_kinds"):
            found.append((FILM_OPEN_ENDING, _text_of("plan_problems.film_open_ending").format(ending), str(last.get("scene_id") or ""), "warning"))
        reversal = _text_of("film_reversal_kind")
        turns = sum(1 for scene in shots if str(scene.get("emotion_point") or "").strip() == reversal)
        tagged = any(str(scene.get("emotion_point") or "").strip() for scene in shots)
        if tagged and turns == 0:
            found.append((FILM_REVERSALS, _text_of("plan_problems.film_no_reversal").format(reversal), None, "warning"))
        elif turns > prompt_data.number(_WORDING_FILE, "film_max_reversals"):
            found.append((FILM_REVERSALS, _text_of("plan_problems.film_many_reversals").format(turns, reversal), None, "warning"))
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
    if mode == "film":
        return _text_of("promotion_guidance.film")
    return ""


def options() -> list[dict[str, str]]:
    return [{"id": info.id, "label": info.label, "description": info.description} for info in MODE_INFO.values()]


__all__ = [
    "AD_MISSING_CTA", "DEFAULT_MODE", "FILM_OPEN_ENDING", "FILM_REVERSALS", "MODES", "MODE_INFO", "NARRATION_DIALOGUE", "CreationMode",
    "ad_brief", "director_guidance", "episode_count_for", "episode_shape_for", "episode_target_for", "mode_of", "options", "plan_problems",
    "promotion_guidance", "spoken_shot_ratio_for", "writer_guidance",
]
