"""How many reference assets one video shot may carry.

Each video model takes its own number (the provider profiles in :mod:`app.core.video_references`):
Seedance 2.0 nine images, three videos, three audio tracks; Seedance 2.5 thirty, ten and ten; 2.5 flash
ten, five and five (Ark's video generation guide). The ``MAX_*`` numbers below are the common cap for
paths that do not know their video model (image generation, the storyboard grid, a shot's stored slots
before a model is chosen); the ``WIDEST_*`` numbers are what any supported model accepts, the bound a
request schema or a shot contract may hold, so a 2.5-sized list is not refused before it reaches the
model that takes it. What one request really carries is cut to its model's own profile.
"""

from __future__ import annotations

from typing import Final, NamedTuple


MAX_REFERENCE_IMAGES: Final = 9
MAX_REFERENCE_VIDEOS: Final = 3
MAX_REFERENCE_AUDIOS: Final = 3
# A storyboard grid is three by three, so a shot's ordered stills share the image cap.
MAX_SEQUENCE_IMAGES: Final = MAX_REFERENCE_IMAGES
# The most any supported video model takes (Seedance 2.5).
WIDEST_REFERENCE_IMAGES: Final = 30
WIDEST_REFERENCE_VIDEOS: Final = 10
WIDEST_REFERENCE_AUDIOS: Final = 10


class ReferenceCaps(NamedTuple):
    images: int
    videos: int
    audios: int


def caps_of(model: str) -> ReferenceCaps:
    """What the named video model takes, from its provider profile."""
    from app.core.video_references import normalize_video_provider

    if not str(model or "").strip():
        # No model named yet: the common cap, not the "unknown model" profile's single picture.
        return ReferenceCaps(MAX_REFERENCE_IMAGES, MAX_REFERENCE_VIDEOS, MAX_REFERENCE_AUDIOS)
    profile = normalize_video_provider(model)
    return ReferenceCaps(profile.max_reference_images, profile.max_reference_videos, profile.max_reference_audios)
