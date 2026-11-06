"""A project's voices in one place: every character's, the narrator's, and the takes heard so far.

Character casting already lives in ``DramaService``; what is here is the view the
library shows and the narrator, who has the same audition-and-keep cycle but is not
a character, so it must not end up in the cast or the character dashboard.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import voice_casting
from app.core.screenwriting.speech import narration_delivery
from app.schema.elevenlabs import VoiceCreateRequest


def _rounds(assets: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    stored = (assets.get(voice_casting.AUDITIONS_KEY) or {}).get(name) or []
    return [
        {
            "seed": entry.get("seed"), "voice_prompt": entry.get("voice_prompt"),
            "previews": [
                {key: preview.get(key) for key in ("generated_voice_id", "url", "duration_secs", "language") if preview.get(key) is not None}
                for preview in entry.get("previews") or [] if isinstance(preview, Mapping)
            ],
        }
        for entry in stored if isinstance(entry, Mapping)
    ]


def voices_view(task: Mapping[str, Any]) -> dict[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    names: list[str] = []
    for character in [*voice_casting.dna_characters(assets), *[c for c in assets.get("3_characters") or [] if isinstance(c, Mapping)]]:
        name = str(character.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    characters = []
    for name in names:
        dna = voice_casting.dna_character(assets, name) or {}
        characters.append({
            "name": name,
            "voice_id": str(dna.get("voice_id") or dna.get("voiceId") or ""),
            "voice_prompt": voice_casting.voice_prompt_of(assets, name),
            "voice_desc": str(dna.get("voice_desc") or ""),
            "take": dna.get("voice_take") if isinstance(dna.get("voice_take"), Mapping) else None,
            "rounds": _rounds(assets, name),
        })
    narrator = voice_casting.narrator_voice(assets)
    return {
        "task_id": str(task.get("task_id") or ""),
        "characters": characters,
        "narrator": {
            "voice_id": str(narrator.get("voice_id") or ""),
            "source": narrator.get("source") or "",
            "label": narrator.get("label") or "",
            "voice_prompt": narrator.get("voice_prompt") or voice_casting.DEFAULT_NARRATOR_PROMPT,
            "take": narrator.get("take"),
            "rounds": _rounds(assets, voice_casting.NARRATOR_NAME),
        },
        # "post_production" means the narration is not dubbed here at all; the person should see that.
        "narration_delivery": narration_delivery(task.get("config") if isinstance(task.get("config"), Mapping) else {}),
    }


def _idle_task(service: Any, task_id: str, *, action: str) -> dict[str, Any] | None:
    task = service.repo.get_task(task_id)
    if task and service._has_running_generation(task):
        raise ValueError(f"任务正在执行阶段，等它结束后再{action}")
    return task


def audition_narrator(service: Any, task_id: str, *, voice_prompt: str = "", seed: int | None = None) -> dict[str, Any] | None:
    """One round of narrator takes (a paid provider call); calling again re-rolls."""
    task = _idle_task(service, task_id, action="试听旁白音色")
    if not task:
        return None
    assets = task.get("assets") or {}
    prompt = " ".join(voice_prompt.split()) or voice_casting.narrator_voice(assets).get("voice_prompt") or voice_casting.DEFAULT_NARRATOR_PROMPT
    request = voice_casting.audition_request(prompt, voice_casting.NARRATOR_NAME, seed=seed)
    result = service._voice_studio().design_voice(request)

    def keep(current: dict[str, Any]) -> dict[str, Any]:
        voice_casting.record_round(current.setdefault("assets", {}), voice_casting.NARRATOR_NAME, request=request, result=result)
        return current

    return voices_view(service.repo.mutate_task(task_id, keep))


def cast_narrator(service: Any, task_id: str, generated_voice_id: str) -> dict[str, Any] | None:
    """Keep one auditioned take as the narrator's voice."""
    task = _idle_task(service, task_id, action="定旁白音色")
    if not task:
        return None
    found = voice_casting.find_preview(task.get("assets") or {}, voice_casting.NARRATOR_NAME, generated_voice_id)
    if found is None:
        raise ValueError("旁白没有试听过这一版声音，请先试听再选")
    entry, preview = found
    title = str((task.get("config") or {}).get("title_suggestion") or "").strip()
    created = service._voice_studio().create_designed_voice(VoiceCreateRequest(
        voice_name=f"{title}·{voice_casting.NARRATOR_NAME}"[:100] if title else voice_casting.NARRATOR_NAME,
        voice_description=str(entry.get("voice_prompt") or "")[:1000],
        generated_voice_id=str(generated_voice_id),
        labels={"character": voice_casting.NARRATOR_NAME},
    ))
    voice_id = str((created or {}).get("voice_id") or "").strip()
    if not voice_id:
        raise RuntimeError("音色设计服务没有返回 voice_id")

    def save(current: dict[str, Any]) -> dict[str, Any]:
        voice_casting.set_narrator_voice(
            current.setdefault("assets", {}), voice_id=voice_id, source="designed",
            voice_prompt=str(entry.get("voice_prompt") or ""), take=preview,
        )
        return current

    return voices_view(service.repo.mutate_task(task_id, save))


def choose_narrator(service: Any, task_id: str, *, voice_id: str, label: str = "") -> dict[str, Any] | None:
    """Narrate in a voice the project or the account already has; free, nothing is designed."""
    if not _idle_task(service, task_id, action="定旁白音色"):
        return None

    def save(current: dict[str, Any]) -> dict[str, Any]:
        voice_casting.set_narrator_voice(current.setdefault("assets", {}), voice_id=voice_id, source="existing", label=label)
        return current

    return voices_view(service.repo.mutate_task(task_id, save))


def clear_narrator(service: Any, task_id: str) -> dict[str, Any] | None:
    if not _idle_task(service, task_id, action="定旁白音色"):
        return None

    def forget(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("assets", {}).pop(voice_casting.NARRATOR_KEY, None)
        return current

    return voices_view(service.repo.mutate_task(task_id, forget))
