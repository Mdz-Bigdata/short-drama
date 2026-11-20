# -*- coding: utf-8 -*-
"""A character's cast voice, carried as reference audio by video models that make their own sound.

Every character keeps one voice for the whole drama. When the video model renders the sound
with the picture (MiniMax H3, Seedance 2.x … — ``video_references.uses_native_soundtrack``),
the voice it invents for a character drifts from clip to clip unless every clip hears the same
sample. Stage 3 casting keeps that sample: the audition take the director chose
(``voice_take.url`` on the character's DNA, a neutral, dry reading of one flat test line).

So a dialogue shot carries the samples of the characters who speak in it, in speaking order,
after the shot's own reference audios and within the model's audio limit — the shot's own
audios are never dropped for a sample. A sample is a soft input: it never changes how a shot is
routed. It rides along only when the routed request already carries reference images (multi
reference becomes multimodal); first-frame and first+last-frame shots go out as before, and the
prompt then says nothing about an audio that is not there (``video_references.renumber_audio_mentions``).

Every voice from the account's library, cast or auto-assigned (``voice_source: "auto"`` or
``3_auto_voices``), also keeps ElevenLabs' public preview of itself (``voice_sample_url`` /
``sample_url``); that one is preferred because a provider can always fetch it.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from app.core import prompt_data, voice_casting
from app.core.video_references import VideoReferencePlan, normalize_video_provider, voice_placeholder

_DATA = "voice_reference"
logger = logging.getLogger(__name__)

VoiceRef = tuple[str, str]


def voice_sample(assets: Mapping[str, Any], name: str) -> str:
    """The voice sample of ``name``, or ``""``.

    The voice's public preview comes first (``voice_sample_url``: ElevenLabs' own recording of the
    cast or library voice, reachable from anywhere); then, for a voice cast in stage 3, the chosen
    audition take saved in our media. An auto-assigned voice without a preview has no sample.
    """
    character = voice_casting.dna_character(assets or {}, name)
    if character is None:
        auto = (assets or {}).get(voice_casting.AUTO_VOICES_KEY)
        entry = auto.get(name) if isinstance(auto, Mapping) else None
        return str(entry.get("sample_url") or "").strip() if isinstance(entry, Mapping) and entry.get("voice_id") else ""
    if not str(character.get("voice_id") or character.get("voiceId") or "").strip():
        return ""
    public = str(character.get("voice_sample_url") or "").strip()
    if public or character.get("voice_source") == "auto":
        return public
    take = character.get("voice_take")
    return str(take.get("url") or "").strip() if isinstance(take, Mapping) else ""


def reachable(url: str) -> bool:
    """Whether a video provider can fetch the sample: a public address whose file still exists.

    Local media are sent the way the rest of stage 5 sends audio and video references — as the
    ``MEDIA_PUBLIC_BASE_URL`` link — so a sample on localhost or a private network is not sent.
    """
    from app.core import media_compositor
    from app.core.clip_fixes import provider_can_fetch

    return bool(url) and provider_can_fetch(url) and media_compositor.media_available(url)


def audio_limit(model: str) -> int:
    """How many reference audios the model takes next to images (0 when it has no multimodal mode)."""
    profile = normalize_video_provider(model)
    return profile.max_reference_audios if "multimodal" in profile.modes else 0


def audio_limits(model: str) -> dict[str, Any]:
    """Seconds per reference audio (min, max), their total, and whether a sample may travel inline, for ``model``."""
    table = prompt_data.value(_DATA, "audio_limits")
    family = normalize_video_provider(model).family if model else ""
    limits = dict(table.get(family) or table["default"])
    # A version of the family proven to take an inline sample (``inline_for``): with no public media
    # address the sample then travels in the request instead of being dropped.
    name = re.sub(r"[\s_.]+", "-", str(model or "").strip().lower())
    if any(str(version) in name for version in limits.pop("inline_for", None) or ()):
        limits["inline"] = True
    return limits


def _source_file(url: str) -> str | None:
    """A local copy of a sample: our own media as they are, a public preview downloaded once into the media folder."""
    from app.core import media_compositor

    local = media_compositor.local_media_path(url)
    if local and os.path.exists(local):
        return local
    if not str(url).startswith(("http://", "https://")):
        return None
    target = os.path.join(media_compositor.MEDIA_DIR, f"voice_src_{hashlib.sha256(url.encode()).hexdigest()[:20]}.mp3")
    if not os.path.exists(target):
        try:
            import httpx

            response = httpx.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
            with open(target + ".tmp", "wb") as handle:
                handle.write(response.content)
            os.replace(target + ".tmp", target)
        except Exception as exc:  # a sample that cannot be fetched is simply not sent
            logger.warning("[VoiceReference] sample download failed: %s", type(exc).__name__)
            return None
    return target


def fit_sample(url: str, seconds: float, limits: Mapping[str, Any]) -> str:
    """``url`` made sendable within the model's audio limits, or ``""``.

    A sample already within [min, ``seconds``] that the provider can fetch goes as it is. A longer
    one is cut to ``seconds`` (with a short fade so it does not end mid-word) into the media folder
    and sent by its public link; with no public link it travels inline when the family allows it.
    Anything that cannot be made to fit is dropped, so a sample never fails the clip.
    """
    from app.core import media_compositor

    source = _source_file(url)
    if not source:
        return url if reachable(url) else ""
    duration = media_compositor._probe_duration(source) or 0.0
    low = float(limits.get("min") or 0)
    if duration and duration < low:
        return ""
    if duration and duration <= seconds and reachable(url):
        return url
    ffmpeg = media_compositor._ffmpeg()
    if not ffmpeg:
        return ""
    cut = max(low, min(float(seconds), duration or float(seconds)))
    name = f"voice_ref_{hashlib.sha256(f'{source}|{cut:.2f}'.encode()).hexdigest()[:20]}.mp3"
    target = os.path.join(media_compositor.MEDIA_DIR, name)
    if not os.path.exists(target):
        fade = min(0.25, cut / 4)
        command = [
            ffmpeg, "-y", "-loglevel", "error", "-i", source, "-t", f"{cut:.2f}",
            "-af", f"afade=t=out:st={cut - fade:.2f}:d={fade:.2f}", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "96k", target + ".tmp.mp3",
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=60)
            os.replace(target + ".tmp.mp3", target)
        except Exception as exc:
            logger.warning("[VoiceReference] sample trim failed: %s", type(exc).__name__)
            return ""
    public = media_compositor.public_url(name)
    if reachable(public):
        return public
    if limits.get("inline"):
        with open(target, "rb") as handle:
            return "data:audio/mpeg;base64," + base64.b64encode(handle.read()).decode()
    return ""


def shot_voice_refs(
    assets: Mapping[str, Any], speakers: Iterable[str], existing_audios: Sequence[str] | None, limit: int,
    *, model: str = "",
) -> list[VoiceRef]:
    """``[(name, url)]``: the samples of the speaking characters that fit next to the shot's own audios.

    In speaking order; the shot's own reference audios count first and are never displaced, a
    speaker without a sample is skipped, and two speakers never send the same file. Each sample is
    cut to its share of the model's total audio time (``audio_limits``, divided over the audio
    slots left) so the request is never refused for a long sample.
    """
    own = list(dict.fromkeys(url for url in existing_audios or () if url))
    room = max(0, int(limit or 0) - len(own))
    wanted: list[VoiceRef] = []
    for name in dict.fromkeys(str(name or "").strip() for name in speakers or ()):
        if len(wanted) >= room:
            break
        url = voice_sample(assets, name) if name else ""
        if not url or url in own or any(url == taken for _, taken in wanted):
            continue
        wanted.append((name, url))
    if not wanted:
        return []
    limits = audio_limits(model)
    # Shared out over every audio slot the clip may fill, so samples merged from several moments of one
    # clip (merge_refs) still stay within the total.
    share = min(float(limits["max"]), float(prompt_data.value(_DATA, "sample_cap_seconds")), float(limits["total"]) / max(1, room))
    chosen: list[VoiceRef] = []
    for name, url in wanted:
        sendable = fit_sample(url, share, limits)
        if sendable:
            chosen.append((name, sendable))
    return chosen


def merge_refs(groups: Iterable[Sequence[VoiceRef]], existing_audios: Sequence[str] | None, limit: int) -> list[VoiceRef]:
    """The samples of several moments sent as one clip: first come, within what is left beside the clip's own audios."""
    own = list(dict.fromkeys(url for url in existing_audios or () if url))
    room = max(0, int(limit or 0) - len(own))
    merged: list[VoiceRef] = []
    for group in groups:
        for name, url in group or ():
            if len(merged) >= room:
                return merged
            if url in own or any(name == seen or url == taken for seen, taken in merged):
                continue
            merged.append((name, url))
    return merged


def with_samples(anchors: Sequence[Any], refs: Sequence[VoiceRef]) -> list[Any]:
    """The speaking anchors, each one with a sample naming it as ``ref_audio`` (a placeholder until routing)."""
    named = {name for name, _ in refs or ()}
    return [replace(anchor, ref_audio=voice_placeholder(anchor.name)) if anchor.name in named else anchor for anchor in anchors]


def carry(
    plan: VideoReferencePlan, refs: Sequence[VoiceRef], *, model: str, executable: Iterable[str] | None = None,
) -> VideoReferencePlan:
    """The routed plan with the voice samples added, when it can take them without changing its route.

    Only a request that already sends reference images (multi reference or multimodal) takes
    audio; frame-anchored and text requests are returned unchanged. The plan's own audios stay
    first; samples fill what is left of the model's audio limit.
    """
    if not refs or plan.mode not in ("multi_reference", "multimodal"):
        return plan
    profile = normalize_video_provider(model)
    if "multimodal" not in profile.modes or (executable is not None and "multimodal" not in set(executable)):
        return plan
    if not (plan.reference_images or plan.reference_videos):
        return plan
    audios = list(plan.reference_audios or [])
    added = [url for _, url in refs if url and url not in audios][: max(0, profile.max_reference_audios - len(audios))]
    if not added:
        return plan
    return plan.model_copy(update={
        "mode": "multimodal",
        "reference_audios": audios + list(dict.fromkeys(added)),
        "reasons": [*plan.reasons, prompt_data.text(_DATA, "route_reason")],
    })


def numbers(plan: VideoReferencePlan, refs: Sequence[VoiceRef]) -> dict[str, int]:
    """``{name: N}``: where each carried sample sits among the request's reference audios."""
    position = {url: index for index, url in enumerate(plan.reference_audios or [], start=1)}
    return {name: position[url] for name, url in refs or () if url in position}


def voice_only(plan: VideoReferencePlan, refs: Sequence[VoiceRef]) -> bool:
    """A multimodal request whose only audio/video inputs are voice samples: otherwise a multi-reference request."""
    samples = {url for _, url in refs or ()}
    return (
        plan.mode == "multimodal" and not plan.reference_videos and bool(plan.reference_audios)
        and all(url in samples for url in plan.reference_audios)
    )


__all__ = [
    "audio_limits", "fit_sample",
    "audio_limit", "carry", "merge_refs", "numbers", "reachable", "shot_voice_refs", "voice_only", "voice_sample",
    "with_samples",
]
