"""How many reference assets one video shot may carry.

These are the widest limits any supported provider documents (Seedance's
multimodal reference: nine images, three videos, three audio tracks). Request
schemas, the shot contract, the gateway and the director desk all cap at the
same numbers, so a reference accepted at one layer is never silently dropped
at the next.
"""

from __future__ import annotations

from typing import Final


MAX_REFERENCE_IMAGES: Final = 9
MAX_REFERENCE_VIDEOS: Final = 3
MAX_REFERENCE_AUDIOS: Final = 3
# A storyboard grid is three by three, so a shot's ordered stills share the image cap.
MAX_SEQUENCE_IMAGES: Final = MAX_REFERENCE_IMAGES
