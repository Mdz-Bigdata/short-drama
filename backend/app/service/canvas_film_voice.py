"""The sound side of the canvas's one-click film, kept apart from the runner it plugs into.

``cast_segments`` reads lines the way stage 6 does (``parse_shot_dialogue`` with the project's character genders),
so a voice node made by the film builder speaks each character in the same voice the pipeline would.
``sound_tracks`` turns a compose node's ``soundPlan`` into the per-clip voice paths and the music path the
compositor takes; a compose node without a plan keeps the old meaning of its audio input (one track for the whole film).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import canvas_film, media_compositor, studio_canvas


def cast_segments(text: str, task: Mapping[str, Any]) -> list[tuple]:
    """``[(line, gender, emotion, speaker, notes)]`` for these lines, voiced by the project's characters."""
    from app.core.screenwriting.speech import narration_delivery
    from app.service.drama_service import dialogue_genders, parse_shot_dialogue

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    lead, opponent, genders = dialogue_genders(assets.get("3_characters"), "", "", assets.get("3_dna"))
    return parse_shot_dialogue(
        str(text or ""), "", "", lead, opponent, voice_narration=narration_delivery(config) == "use_tts", genders=genders,
    )


def sound_tracks(node: Mapping[str, Any] | None, inputs: studio_canvas.Inputs) -> tuple[list[str | None] | None, str | None]:
    """(a voice path per clip, in clip order, or None when the node has no plan; the music path or None)."""
    payload = node.get("payload") if isinstance(node, Mapping) and isinstance(node.get("payload"), Mapping) else {}
    plan = payload.get(canvas_film.SOUND_PLAN)
    if not isinstance(plan, Mapping):
        return None, None
    voices = plan.get("voices") if isinstance(plan.get("voices"), Mapping) else {}
    audio = {str(item["node_id"]): str(item["url"]) for item in inputs.sources if item.get("role") == "soundtrack"}
    clip_sources = [str(item["node_id"]) for item in inputs.sources if item.get("role") == "clip"]
    per_clip = [media_compositor.local_media_path(audio.get(str(voices.get(clip) or ""))) if voices.get(clip) else None for clip in clip_sources]
    music_id = str(plan.get("music") or "")
    music = media_compositor.local_media_path(audio[music_id]) if music_id in audio else None
    return per_clip, music
