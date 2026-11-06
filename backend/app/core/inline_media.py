# -*- coding: utf-8 -*-
"""Inline image bytes (``data:`` URIs) belong in a provider request, never in a stored task.

Stage 5 sends private reference views to the video provider as inline images and used to keep
the request's route decision on each clip verbatim — about 1.5 MB per picture, nine pictures a
shot. One 39-shot task grew to 333 MB: every status poll and workspace load parsed all of it,
and the shot workspace never finished loading. A stored record keeps a short marker in the
picture's place instead (the position matters: prompts name pictures by number).
"""

from __future__ import annotations

from typing import Any

INLINE_PREFIX = "data:"
MARKER_PREFIX = "inline:"


def marker(value: str) -> str:
    """``inline:image/png 1184KB`` for ``data:image/png;base64,...``."""
    mime = value[len(INLINE_PREFIX):].split(";", 1)[0].split(",", 1)[0] or "application/octet-stream"
    payload = value.split(",", 1)[1] if "," in value else ""
    return f"{MARKER_PREFIX}{mime} {max(1, len(payload) * 3 // 4 // 1024)}KB"


def without_inline_media(value: Any) -> Any:
    """``value`` with every ``data:`` string replaced by its marker; other values unchanged.

    Returns the same object when nothing inline is inside, so a clean record costs no copy.
    """
    if isinstance(value, str):
        return marker(value) if value.startswith(INLINE_PREFIX) else value
    if isinstance(value, dict):
        cleaned = {key: without_inline_media(item) for key, item in value.items()}
        return value if all(cleaned[key] is value[key] for key in value) else cleaned
    if isinstance(value, list):
        cleaned_list = [without_inline_media(item) for item in value]
        return value if all(new is old for new, old in zip(cleaned_list, value)) else cleaned_list
    return value


def strip_stage_five_routes(task: Any) -> bool:
    """Replace inline bytes in each stage-5 clip's ``video_route_decision``; ``True`` when any were."""
    assets = task.get("assets") if isinstance(task, dict) else None
    clips = assets.get("5") if isinstance(assets, dict) else None
    if not isinstance(clips, list):
        return False
    changed = False
    for clip in clips:
        if isinstance(clip, dict) and isinstance(clip.get("video_route_decision"), dict):
            cleaned = without_inline_media(clip["video_route_decision"])
            if cleaned is not clip["video_route_decision"]:
                clip["video_route_decision"] = cleaned
                changed = True
    return changed


__all__ = ["INLINE_PREFIX", "MARKER_PREFIX", "marker", "strip_stage_five_routes", "without_inline_media"]
