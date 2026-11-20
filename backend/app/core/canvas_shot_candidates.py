"""A clip committed from the canvas joins the shot's stage-5 versions, so the user can pick it there.

Committing already puts the clip in the shot's ``reference_videos`` (stage 5 then generates with it as
guidance). When the shot already has its own stage-5 clip, the canvas clip is also added at the end of that
clip's ``candidates``: the shot workspace lists it beside the model's versions, and choosing it goes
through ``select_shot_candidate`` like any other version, own sound included. Nothing switches by itself.

Only a clip that covers this one shot takes it: a segment clip spans several shots, and a one-shot canvas
clip in its place would drop the others. A shot with no stage-5 clip yet gets no made-up record either:
stage 5 would regenerate it as soon as its request fingerprint differed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import episode_cycle, media_compositor


def offer(assets: Mapping[str, Any], shot: Mapping[str, Any], url: str) -> bool:
    """Add ``url`` to the versions of the shot's own clip; ``True`` when it is now among them."""
    if not url:
        return False
    clips = assets.get("5") if isinstance(assets.get("5"), list) else []
    clip = episode_cycle.clip_for(shot, clips)
    if not isinstance(clip, dict) or not clip.get("video_url"):
        return False
    if episode_cycle.covered_uids(clip) != [episode_cycle.shot_uid(shot)] and (clip.get("scene_id") or clip.get("shot_uids")):
        return False
    # The clip in use leads the list; a provider link that has expired cannot be previewed or picked, so it goes.
    current = str(clip["video_url"])
    others = [str(item) for item in clip.get("candidates") or [] if item and str(item) != current and media_compositor.media_available(str(item))]
    versions = [current, *others]
    clip["candidates"] = versions if url in versions else [*versions, url]
    return True


__all__ = ["offer"]
