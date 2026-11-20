# -*- coding: utf-8 -*-
"""Give a character a voice the account already has (the voice library), instead of designing one.

Designing a voice (audition → cast) creates a new voice at the provider; a library voice is used as it is, so
nothing is paid here. Everything else is as when a designed voice is cast: a voice another character already
uses is refused (one voice per character, each unique), and if the character has spoken in a dubbed or a
native-sound shot, every one of those lines is re-dubbed with the new voice (``voice_relink``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core import prompt_data, voice_casting
from app.core.character_dashboard import compile_character_dashboard
from app.service import voice_relink


def choose(service: Any, task_id: str, name: str, voice_id: str, *, sample_url: str = "") -> Optional[Any]:
    """Store ``voice_id`` as ``name``'s voice and start the re-dub when needed; the refreshed character dashboard."""
    name = (name or "").strip()
    voice_id = (voice_id or "").strip()
    task = service.repo.get_task(task_id)
    if not task:
        return None
    if service._has_running_generation(task):  # noqa: SLF001 - the same guard casting uses
        raise ValueError(prompt_data.text("voice_relink", "busy"))
    previous: Dict[str, str] = {}

    def save(task: Dict[str, Any]) -> Dict[str, Any]:
        if service._has_running_generation(task):  # noqa: SLF001
            raise ValueError(prompt_data.text("voice_relink", "busy"))
        assets = task.setdefault("assets", {})
        other = voice_casting.voice_taken_by(assets, name, voice_id)
        if other:
            raise ValueError(prompt_data.text("voice_relink", "voice_taken").format(other=other, name=name))
        previous["voice_id"] = voice_casting.speaker_voice_map(assets).get(name, "")
        # A library voice has no designed take; its public sample is the reference native-sound models hear.
        voice_casting.set_voice(assets, name, voice_id=voice_id, sample_url=sample_url)
        character = voice_casting.dna_character(assets, name) or {}
        character.pop("voice_take", None)
        assets["3_character_dashboard"] = compile_character_dashboard(task).model_dump(mode="json", by_alias=True)
        return task

    saved = service.repo.mutate_task(task_id, save)
    if not saved:
        return None
    relinked = None
    if previous.get("voice_id") != voice_id:
        changes = voice_relink.preview(saved, name)
        if changes["dubbed_shots"] or changes["native_shots"]:
            relinked = voice_relink.start(service, task_id, name, background=service.voice_relink_background)
    dashboard = service.get_character_dashboard(task_id)
    if dashboard is not None and relinked is not None:
        dashboard = dashboard.model_copy(update={"voice_relink": relinked})
    return dashboard


__all__ = ["choose"]
