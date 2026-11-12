# -*- coding: utf-8 -*-
"""A character's voice changed after dubbing: re-dub everything they said, everywhere, with the new voice.

One character, one voice for the whole drama, and no two characters on one voice. A recast
voice is therefore never just stored: every dubbed shot in which the character speaks is
dubbed again with the current cast (a shot's track mixes all its speakers, so the whole
track is redone), every copy of that track is replaced (the clip, stage 6's audio, the
episode's audio record, the edit timelines), and every native-sound shot in which the
character speaks is switched to dubbing on the timeline, because the old voice is baked
into the clip itself. Films already composed with the old voice are marked for a re-render,
never re-rendered here.

Who speaks in a shot is read with the same parser and the same inputs stage 6 dubs with,
so the shots found here are exactly the ones whose tracks carry the character's voice.
The new tracks are made first and written in one ``mutate_task``: a shot that fails to
dub leaves every stored track and timeline as it was.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from app.core import edit_timeline, episode_cycle, media_compositor, post_production, prompt_data, usage_ledger, voice_casting
from app.core.screenwriting.speech import narration_delivery

logger = logging.getLogger(__name__)

_DATA = "voice_relink"
#: ``assets[STATUS_KEY][name]``: the last relink of each character (queued / running / done / failed) and its summary.
STATUS_KEY = "3_voice_relink"
#: On an episode record (and on ``assets["7"]``): the characters whose new voice that film does not have yet.
MARK_KEY = "needs_render_for_voice"
PURPOSE = "voice_relink"

_locks_guard = threading.Lock()
_task_locks: dict[str, threading.Lock] = {}


def _text(key: str, **values: Any) -> str:
    return prompt_data.text(_DATA, key).format(**values)


def _task_lock(task_id: str) -> threading.Lock:
    """Relinks of one project run one after another: each plans from what the one before wrote."""
    with _locks_guard:
        return _task_locks.setdefault(str(task_id), threading.Lock())


# ---------------------------------------------------------------------------- reading


def _parser(task: Mapping[str, Any]) -> Callable[[str], list]:
    """The shot-dialogue parser with the inputs stage 6 gives it (leads, carded genders, narration)."""
    from app.service import drama_service as ds

    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    lead, _look, opponent, _look2 = ds.project_leads(assets)
    lead_gender, opponent_gender, carded = ds.dialogue_genders(assets.get("3_characters"), lead, opponent, assets.get("3_dna"))
    narration = narration_delivery(config) == "use_tts"

    def parse(cell: str) -> list:
        return ds.parse_shot_dialogue(cell, lead, opponent, lead_gender, opponent_gender, voice_narration=narration, genders=carded)

    return parse


def _units(task: Mapping[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """``(episode, view)`` for every dubbed run: each episode's audio record, or the whole-film run (0)."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    cycle = assets.get(episode_cycle.CYCLE_KEY) if isinstance(assets.get(episode_cycle.CYCLE_KEY), Mapping) else {}
    stored = cycle.get("episodes") if isinstance(cycle.get("episodes"), Mapping) else {}
    numbers = sorted(
        int(key) for key, entry in stored.items()
        if str(key).isdigit() and isinstance(entry, Mapping) and isinstance(entry.get("audio"), Mapping) and entry["audio"]
    )
    units = [(number, episode_cycle.episode_view(task, number)) for number in numbers]
    live = assets.get("6")
    if not units and isinstance(live, Mapping) and live and not live.get("episode"):
        units.append((0, dict(task)))
    return units


def _scan(view: Mapping[str, Any], name: str, parse: Callable[[str], list]) -> dict[str, list[dict[str, Any]]]:
    """The dubbed and the native-sound shots of one run in which ``name`` speaks.

    ``index`` is the shot's place in the run's stage-5 clips, which is how stage 6 lines up ``shot_voices``.
    """
    assets = view.get("assets") if isinstance(view.get("assets"), Mapping) else {}
    clips = assets.get("5") if isinstance(assets.get("5"), list) else []
    audio = assets.get("6") if isinstance(assets.get("6"), Mapping) else {}
    voices = list(audio.get("shot_voices") or [])
    native = list(audio.get("native_audio_shots") or [])
    dubbed: list[dict[str, Any]] = []
    natives: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        if not isinstance(clip, Mapping):
            continue
        segments = parse(str(clip.get("dialogue") or ""))
        mine = sum(1 for segment in segments if str(segment[3]).strip() == name)
        if not mine:
            continue
        entry = {"index": index, "shot_uid": episode_cycle.shot_uid(clip), "shot_id": clip.get("shot_id"), "lines": mine}
        if index < len(native) and native[index] and not clip.get("voice_path"):
            natives.append(entry)
        elif index < len(voices) and voices[index]:
            dubbed.append({**entry, "segments": segments, "old_path": voices[index]})
    return {"dubbed": dubbed, "native": natives}


def _plan(task: Mapping[str, Any], name: str) -> list[tuple[int, dict[str, list[dict[str, Any]]]]]:
    parse = _parser(task)
    plan = []
    for number, view in _units(task):
        scan = _scan(view, name, parse)
        if scan["dubbed"] or scan["native"]:
            plan.append((number, scan))
    return plan


def _has_film(task: Mapping[str, Any], number: int) -> bool:
    """Whether a composed film of this run exists (the episode record, stage 7's record or the version list)."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    if number and episode_cycle.film_of(task, number):
        return True
    final = assets.get("7") if isinstance(assets.get("7"), Mapping) else {}
    if final.get("final_video_url") and int(final.get("episode") or 0) == number:
        return True
    return any(
        isinstance(version, Mapping) and version.get("url") and int(version.get("episode") or 0) == number
        for version in assets.get(post_production.FILM_VERSIONS_KEY) or []
    )


def provider(task: Mapping[str, Any]) -> tuple[str, bool]:
    """(provider, billed) of a re-dub: the same choice ``synthesize_preferred_dialogue_track`` makes."""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    vendor, model = media_compositor.effective_audio_model(str(config.get("tts_model") or ""))
    paid = vendor == "elevenlabs" or "eleven" in str(model or "").lower()
    return ("elevenlabs" if paid else "local"), paid


def status_of(task: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """The last relink of ``name``; one left running long past its time was cut off by a restart."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(STATUS_KEY) if isinstance(assets.get(STATUS_KEY), Mapping) else {}
    record = store.get(name)
    if not isinstance(record, Mapping):
        return None
    record = dict(record)
    started = record.get("started_epoch")
    if record.get("status") in {"queued", "running"} and isinstance(started, (int, float)) \
            and time.time() - started > prompt_data.number(_DATA, "stale_after_seconds"):
        record.update(status="failed", error=_text("interrupted", name=name))
    return record


def stage_refusal(task: Mapping[str, Any], stage: int) -> str:
    """Why stage ``stage`` may not start now, or ``""``: a re-dub still running would be overwritten by it."""
    if int(stage) not in (5, 6, 7):
        return ""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(STATUS_KEY) if isinstance(assets.get(STATUS_KEY), Mapping) else {}
    busy = [name for name in store if (status_of(task, name) or {}).get("status") in {"queued", "running"}]
    if not busy:
        return ""
    return _text("stage_blocked", names=_text("list_separator").join(busy), stage=int(stage))


def taken_by(assets: Mapping[str, Any], name: str, voice: str) -> str:
    """Who else already has ``voice``: by its voice_id, or by the auditioned take another character was cast from."""
    voice = str(voice or "").strip()
    if not voice:
        return ""
    other = voice_casting.voice_taken_by(assets, name, voice)
    if other:
        return other
    return next((
        str(character.get("name") or "").strip() for character in voice_casting.dna_characters(assets)
        if str(character.get("name") or "").strip() != name
        and isinstance(character.get("voice_take"), Mapping)
        and str(character["voice_take"].get("generated_voice_id") or "") == voice
    ), "")


def preview(task: Mapping[str, Any], name: str, *, voice: str = "") -> dict[str, Any]:
    """What a new voice for ``name`` would change, per run and in total.

    ``lines`` counts this character's lines that would be dubbed again: now in the dubbed shots,
    at the next render in the native-sound shots switched to dubbing. ``billed`` is true when that
    dubbing goes to a paid provider. ``voice`` (optional) is the voice about to be cast: the same
    voice changes nothing; one another character has comes back as ``taken_by``.
    """
    name = str(name or "").strip()
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    current = voice_casting.speaker_voice_map(assets).get(name, "")
    unchanged = bool(voice) and str(voice).strip() == current
    per_episode = []
    for number, scan in ([] if unchanged else _plan(task, name)):
        per_episode.append({
            "episode": number,
            "dubbed_shots": len(scan["dubbed"]), "dubbed_lines": sum(entry["lines"] for entry in scan["dubbed"]),
            "native_shots": len(scan["native"]), "native_lines": sum(entry["lines"] for entry in scan["native"]),
            "film": _has_film(task, number),
        })
    vendor, paid = provider(task)
    lines = sum(row["dubbed_lines"] + row["native_lines"] for row in per_episode)
    result: dict[str, Any] = {
        "name": name,
        "lines": lines,
        "episodes": [row["episode"] for row in per_episode],
        "native_shots": sum(row["native_shots"] for row in per_episode),
        "billed": paid and lines > 0,
        "provider": vendor,
        "films_to_rerender": [row["episode"] for row in per_episode if row["film"]],
        "dubbed_shots": sum(row["dubbed_shots"] for row in per_episode),
        "dubbed_lines": sum(row["dubbed_lines"] for row in per_episode),
        "per_episode": per_episode,
        "current_voice_id": current,
        "unchanged": unchanged,
        "relink": status_of(task, name),
    }
    other = taken_by(assets, name, voice)
    if other:
        result["taken_by"] = other
    return result


def preview_of(service: Any, task_id: str, name: str, *, voice: str = "") -> dict[str, Any] | None:
    """``preview`` for a stored task; ``None`` if there is no task, ``LookupError`` for a name not in the cast."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    name = str(name or "").strip()
    if not voice_casting.is_cast_member(task.get("assets") or {}, name):
        raise LookupError(_text("unknown_character", name=name))
    return preview(task, name, voice=voice)


# ---------------------------------------------------------------------------- relinking


def _where(number: int, entry: Mapping[str, Any]) -> str:
    shot = entry.get("shot_id") if entry.get("shot_id") is not None else entry.get("shot_uid")
    return _text("where_episode_shot", episode=number, shot=shot) if number else _text("where_shot", shot=shot)


def _set_status(service: Any, task_id: str, name: str, *, fresh: bool = False, **fields: Any) -> None:
    """Write ``name``'s relink status; ``fresh`` starts a new record instead of updating the last one."""
    def put(task: dict[str, Any]) -> dict[str, Any]:
        store = task.setdefault("assets", {}).setdefault(STATUS_KEY, {})
        previous = store.get(name) if isinstance(store.get(name), dict) and not fresh else {}
        store[name] = {**previous, **fields}
        return task

    service.repo.mutate_task(task_id, put)


def _relinked_timeline(
    timeline: Mapping[str, Any], view: Mapping[str, Any], native_uids: list[int], speaking: set[int], switched: set[int],
) -> dict[str, Any]:
    """Native-sound clips of the character set to a dub, then the run's new sound laid in.

    ``with_new_sound`` takes every clip's voice from stage 6; a dub made on the cut itself (a clip
    switched to dubbing before) is kept unless the character speaks in it, so it is redone at render.
    """
    new: dict[str, Any] = dict(timeline)
    for uid in native_uids:
        clip = next((c for c in new.get("clips") or [] if isinstance(c, Mapping) and str(c.get("shot_uid")) == str(uid)), None)
        if clip is None or edit_timeline.audio_source(clip) != "native":
            continue
        new = edit_timeline.set_audio_source(new, None, "tts", shot_uid=uid)
        switched.add(uid)
    refreshed = edit_timeline.with_new_sound(new, view)
    before = {str(c.get("fingerprint")): c for c in new.get("clips") or [] if isinstance(c, Mapping)}
    for clip in refreshed.get("clips") or []:
        old = before.get(str(clip.get("fingerprint"))) if isinstance(clip, dict) else None
        if old and old.get("voice_path") and not clip.get("voice_path") and clip.get("shot_uid") not in speaking:
            clip["voice_path"] = old["voice_path"]
    return refreshed


def _mark(record: dict[str, Any], name: str) -> None:
    record[MARK_KEY] = sorted({*(record.get(MARK_KEY) or []), name})


def clear_render_marks(task: dict[str, Any], episode: int | None) -> None:
    """A film was rendered again from its timeline: it now has every voice it was marked for."""
    assets = task.setdefault("assets", {})
    if isinstance(assets.get("7"), dict):
        assets["7"].pop(MARK_KEY, None)
    if episode:
        cycle = assets.get(episode_cycle.CYCLE_KEY) if isinstance(assets.get(episode_cycle.CYCLE_KEY), dict) else {}
        record = (cycle.get("episodes") or {}).get(str(episode)) if isinstance(cycle.get("episodes"), dict) else None
        if isinstance(record, dict):
            record.pop(MARK_KEY, None)


def _summary_message(name: str, summary: Mapping[str, Any]) -> str:
    if not (summary["shots_redubbed"] or summary["native_switched"]):
        return _text("summary_nothing", name=name)
    message = _text("summary", name=name, shots=summary["shots_redubbed"], lines=summary["lines_redubbed"], native=summary["native_switched"])
    films = summary["films_to_rerender"]
    if films:
        labels = [_text("episode_label", episode=n) if n else _text("whole_film_label") for n in films]
        message += _text("summary_films", films=prompt_data.text(_DATA, "list_separator").join(labels))
    return message


def _empty_summary(name: str, voice: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "voice_id": voice, "applied": False, "lines_redubbed": 0, "shots_redubbed": 0, "native_switched": 0,
        "episodes": [], "films_to_rerender": [], "failures": [], "skipped": [], **extra,
    }


def _current_voice(service: Any, task: Mapping[str, Any], name: str) -> str:
    """The voice ``name`` dubs with now, after the same checks casting makes."""
    if service._has_running_generation(task):
        raise ValueError(_text("refuse_running"))
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    if not voice_casting.is_cast_member(assets, name):
        raise ValueError(_text("unknown_character", name=name))
    voice = voice_casting.speaker_voice_map(assets).get(name, "")
    if not voice:
        raise ValueError(_text("no_voice", name=name))
    other = voice_casting.voice_taken_by(assets, name, voice)
    if other:
        raise ValueError(_text("voice_taken", other=other, name=name))
    return voice


def _preview_with(task: Mapping[str, Any], task_id: str, number: int, entry: Mapping[str, Any], voice_path: str, suffix: str) -> str:
    """The shot's clip with the new dub laid on it (local ffmpeg, free), or ``""`` when it cannot be made.

    Stage 5 baked the old dub into the preview the shot workbench plays; this replaces only what it hears.
    """
    clips = (episode_cycle.episode_view(task, number) if number else task).get("assets", {}).get("5") or []
    index = int(entry["index"])
    clip = clips[index] if index < len(clips) and isinstance(clips[index], Mapping) else {}
    video_url = str(clip.get("video_url") or "")
    if not video_url:
        return ""
    try:
        made = media_compositor.attach_audio_to_clip(
            video_url, voice_path, bgm=False, tag=f"shotav_{task_id[:8]}_s{entry['shot_uid']}_v{suffix}",
        )
    except Exception as exc:  # a missing preview must not stop the re-dub itself
        logger.warning("[VoiceRelink] preview for shot %s: %s", entry["shot_uid"], type(exc).__name__)
        return ""
    return str(made) if made and made != video_url else ""


def relink(service: Any, task_id: str, name: str) -> dict[str, Any] | None:
    """Re-dub ``name``'s shots with the voice now cast and update every copy; ``None`` if there is no task.

    Refused (``ValueError``) while a stage runs, for a name not in the cast, a character with no
    voice, or a voice another character has. Returns ``{lines_redubbed, shots_redubbed,
    native_switched, episodes, films_to_rerender, failures, skipped, applied, message}``; with any
    failure nothing is written but the status.
    """
    name = str(name or "").strip()
    with _task_lock(task_id):
        return _relink(service, task_id, name)


def _relink(service: Any, task_id: str, name: str) -> dict[str, Any] | None:
    task = service.repo.get_task(task_id)
    if not task:
        return None
    voice = _current_voice(service, task, name)
    assets = task.get("assets") or {}
    plan = _plan(task, name)
    jobs = [(number, entry) for number, scan in plan for entry in scan["dubbed"]]
    started = time.time()
    _set_status(service, task_id, name, fresh=True, status="running", voice_id=voice, total=len(jobs), done=0, started_epoch=started)
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    suffix = uuid.uuid4().hex[:6]
    made: dict[tuple[int, int], tuple[str | None, str]] = {}
    previews: dict[tuple[int, int], str] = {}
    failures: list[dict[str, Any]] = []
    with usage_ledger.bind_task(task_id, PURPOSE), media_compositor.bind_speaker_voices(voice_casting.speaker_voice_map(assets)):
        for done, (number, entry) in enumerate(jobs, start=1):
            try:
                url, path = media_compositor.synthesize_preferred_dialogue_track(
                    entry["segments"], tts_model=str(config.get("tts_model") or ""),
                    tag=f"voice_{task_id[:8]}_e{number}_s{entry['index']}_r{suffix}",
                )
            except Exception as exc:  # one shot failing must not stop the rest from being tried
                logger.warning("[VoiceRelink] %s shot %s: %s", name, entry["shot_uid"], type(exc).__name__)
                url, path = None, None
            if path:
                made[(number, entry["index"])] = (url, path)
                previews[(number, entry["index"])] = _preview_with(task, task_id, number, entry, path, suffix)
            else:
                failures.append({"episode": number, "shot_uid": entry["shot_uid"], "shot_id": entry.get("shot_id"),
                                 "reason": _text("synthesis_failed", where=_where(number, entry))})
            if done < len(jobs):
                _set_status(service, task_id, name, status="running", done=done)

    if failures:
        summary = _empty_summary(name, voice, failures=failures)
        summary["message"] = _text("failed_untouched", name=name)
        _set_status(service, task_id, name, status="failed", done=len(jobs), finished_epoch=time.time(),
                    error=summary["message"], summary=summary)
        return summary

    outcome: dict[str, Any] = {}

    def apply(current: dict[str, Any]) -> dict[str, Any]:
        if service._has_running_generation(current):
            raise ValueError(_text("stage_started_meanwhile", name=name))
        current_assets = current.setdefault("assets", {})
        if voice_casting.speaker_voice_map(current_assets).get(name, "") != voice:
            raise ValueError(_text("voice_changed_meanwhile", name=name))
        live_audio = current_assets.get("6") if isinstance(current_assets.get("6"), dict) else None
        lines = shots = 0
        skipped: list[dict[str, Any]] = []
        switched: set[tuple[int, int]] = set()
        touched: list[int] = []
        films: list[int] = []
        for number, scan in plan:
            record = episode_cycle.writable_record(current, number) if number else None
            audio = record.get("audio") if record is not None else live_audio
            audio = audio if isinstance(audio, dict) else {}
            mirror = live_audio if (
                live_audio is not None and live_audio is not audio and int(live_audio.get("episode") or 0) == number
            ) else None
            clips = (episode_cycle.episode_view(current, number) if number else current)["assets"].get("5") or []
            voices = audio.get("shot_voices") if isinstance(audio.get("shot_voices"), list) else []
            for entry in scan["dubbed"]:
                index = entry["index"]
                clip = clips[index] if index < len(clips) else None
                if not isinstance(clip, dict) or episode_cycle.shot_uid(clip) != entry["shot_uid"] \
                        or index >= len(voices) or voices[index] != entry["old_path"]:
                    skipped.append({"episode": number, "shot_uid": entry["shot_uid"], "shot_id": entry.get("shot_id"),
                                    "reason": _text("shot_moved", where=_where(number, entry))})
                    continue
                url, path = made[(number, index)]
                voices[index] = path
                mirrored = mirror.get("shot_voices") if mirror is not None else None
                if isinstance(mirrored, list) and index < len(mirrored) and mirrored[index] == entry["old_path"]:
                    mirrored[index] = path
                if clip.get("voice_path"):
                    clip["voice_path"] = path
                    if "voice_url" in clip:
                        clip["voice_url"] = url
                # The workbench plays preview_url when present; video_url stays, so the cut keeps this clip's edits.
                if previews.get((number, index)):
                    clip["preview_url"] = previews[(number, index)]
                shots += 1
                lines += entry["lines"]
            view = episode_cycle.episode_view(current, number) if number else current
            native_uids = [entry["shot_uid"] for entry in scan["native"]]
            speaking = {entry["shot_uid"] for entry in (*scan["dubbed"], *scan["native"])}
            switched_here: set[int] = set()
            if record is not None:
                timeline = record.get("timeline") if isinstance(record.get("timeline"), dict) else None
                if timeline is None and native_uids:
                    timeline = _built_timeline(service, view, number)
                if timeline is not None:
                    record["timeline"] = _relinked_timeline(timeline, view, native_uids, speaking, switched_here)
            live = current_assets.get(edit_timeline.TIMELINE_KEY)
            if isinstance(live, dict) and int(live.get("episode") or 0) == number:
                current_assets[edit_timeline.TIMELINE_KEY] = _relinked_timeline(live, view, native_uids, speaking, switched_here)
            elif not number and live is None and native_uids:
                current_assets[edit_timeline.TIMELINE_KEY] = _relinked_timeline(
                    _built_timeline(service, view, None), view, native_uids, speaking, switched_here,
                )
            switched.update((number, uid) for uid in switched_here)
            touched.append(number)
            if _has_film(current, number):
                films.append(number)
                if record is not None:
                    _mark(record, name)
                final = current_assets.get("7")
                if isinstance(final, dict) and int(final.get("episode") or 0) == number:
                    _mark(final, name)
        summary = _empty_summary(
            name, voice, applied=True, lines_redubbed=lines, shots_redubbed=shots, native_switched=len(switched),
            episodes=touched, films_to_rerender=films, skipped=skipped,
        )
        summary["message"] = _summary_message(name, summary)
        current_assets.setdefault(STATUS_KEY, {})[name] = {
            "status": "done", "voice_id": voice, "total": len(jobs), "done": len(jobs), "started_epoch": started,
            "finished_epoch": time.time(), "summary": summary,
        }
        outcome.update(summary)
        return current

    try:
        service.repo.mutate_task(task_id, apply)
    except ValueError as exc:
        summary = _empty_summary(name, voice, failures=[{"reason": str(exc)}])
        summary["message"] = str(exc)
        _set_status(service, task_id, name, status="failed", done=len(jobs), finished_epoch=time.time(), error=str(exc), summary=summary)
        return summary
    return outcome


def _built_timeline(service: Any, view: Mapping[str, Any], number: int | None) -> dict[str, Any]:
    """The cut a render would build for this run, so a clip on it can be switched to dubbing before the render."""
    config = view.get("config") if isinstance(view.get("config"), Mapping) else {}
    timeline, _reports = service._current_timeline_of(dict(view), str(config.get("title_suggestion") or ""))
    if number:
        timeline["episode"] = number
    return timeline


def _worker(service: Any, task_id: str, name: str) -> None:
    try:
        relink(service, task_id, name)
    except ValueError as exc:
        _set_status(service, task_id, name, status="failed", finished_epoch=time.time(), error=str(exc))
    except Exception as exc:  # the thread has nobody to raise to: the status is what the page reads
        logger.exception("[VoiceRelink] %s failed: %s", name, type(exc).__name__)
        _set_status(service, task_id, name, status="failed", finished_epoch=time.time(), error=_text("worker_failed"))


def start(service: Any, task_id: str, name: str, *, background: bool | None = None) -> dict[str, Any]:
    """Relink after a recast: inline when only a few shots need dubbing, otherwise in a background thread.

    ``background`` forces one or the other. A background run answers at once with its queued status;
    its progress and final summary are on the task under ``assets[STATUS_KEY][name]``.
    """
    name = str(name or "").strip()
    task = service.repo.get_task(task_id) or {}
    if background is None:
        dubbed = sum(len(scan["dubbed"]) for _number, scan in _plan(task, name))
        background = dubbed > prompt_data.number(_DATA, "inline_max_shots")
    if not background:
        try:
            summary = relink(service, task_id, name) or {}
            return {"status": "done" if summary.get("applied") else "failed", **summary}
        except Exception as exc:  # the voice is already cast: report the relink, do not fail the cast
            message = str(exc) if isinstance(exc, ValueError) else _text("worker_failed")
            if not isinstance(exc, ValueError):
                logger.exception("[VoiceRelink] %s failed: %s", name, type(exc).__name__)
            _set_status(service, task_id, name, status="failed", finished_epoch=time.time(), error=message)
            return {"status": "failed", "name": name, "message": message}
    queued = {"status": "queued", "started_epoch": time.time()}
    _set_status(service, task_id, name, fresh=True, **queued)
    threading.Thread(
        target=usage_ledger.carrying_context(_worker), args=(service, task_id, name), daemon=True,
        name=f"voice-relink-{str(task_id)[:8]}",
    ).start()
    return {"name": name, **queued, "preview": preview(task, name)}


__all__ = [
    "MARK_KEY", "STATUS_KEY", "clear_render_marks", "preview", "preview_of", "provider", "relink", "stage_refusal", "start", "status_of", "taken_by",
]
