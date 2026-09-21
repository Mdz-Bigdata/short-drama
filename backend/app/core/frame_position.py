"""Frame-coordinate positions for subjects in a shot.

"The woman stands to the man's left" has four readings (hers, his, the camera's,
the mirrored render). A storyboard needs the one the audience sees, so positions
are written in screen coordinates: picture region, depth layer, screen-facing
direction, quantified occlusion and forbidden zones. This module parses that
grammar out of prose, renders it back as the five-part position sentence, and
compares adjacent shots so a flipped eyeline is caught before generation.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REGIONS: tuple[str, ...] = (
    "画面左侧三分之一", "画面右侧三分之一", "画面左侧", "画面右侧", "画面中央", "画面中心",
    "中央轴线", "画面上方", "画面下方", "画面左下角", "画面右下角", "画面左上角", "画面右上角",
    "画面左下方", "画面右下方", "画面左上方", "画面右上方", "画面中右侧", "画面中左侧",
    "画面左后方", "画面右后方", "画面下方中央",
)
DEPTHS: tuple[str, ...] = ("极近前景", "近前景", "前景", "中景", "中远景", "背景", "远景")
FACINGS: tuple[str, ...] = (
    "朝向画面右侧", "朝向画面左侧", "朝画面右侧", "朝画面左侧", "朝画面内侧", "朝向画面内侧",
    "面向画面右侧", "面向画面左侧", "面向镜头", "正对镜头", "背对镜头", "视线朝向画面右侧",
    "视线朝向画面左侧", "视线指向左侧", "视线指向右侧", "看向画面右侧", "看向画面左侧",
    "看向镜头", "望向画面右侧", "望向画面左侧",
)
_OCCLUSION = re.compile(r"(遮挡[^，。；]{0,30}?(?:约)?[一二三四五六七八九十\d分之]+[^，。；]{0,20})")
_FORBIDDEN = re.compile(r"((?:不要|不得|禁止|不放置)[^，。；]{2,40})")
_SENTENCE_SPLIT = re.compile(r"[。；;\n]")


class FramePosition(BaseModel):
    """Where one subject sits in the frame the audience will see."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=120)
    region: str = Field("", max_length=60)
    depth: str = Field("", max_length=40)
    facing: str = Field("", max_length=60)
    occlusion: str = Field("", max_length=200)
    keep_visible: str = Field("", max_length=120)
    forbidden_zone: str = Field("", max_length=200)

    def is_anchored(self) -> bool:
        return bool(self.region or self.depth)


def uses_frame_grammar(text: str) -> bool:
    """True when prose positions subjects in screen coordinates at all."""
    haystack = str(text or "")
    return any(token in haystack for token in (*REGIONS, *DEPTHS)) and (
        "画面" in haystack or any(depth in haystack for depth in DEPTHS)
    )


def _first(tokens: tuple[str, ...], text: str) -> str:
    """Earliest token in the text; on the same position the longer one wins
    (画面左侧三分之一 over 画面左侧)."""
    found = [(text.find(token), -len(token), token) for token in tokens if token in text]
    return min(found)[2] if found else ""


def _without_facings(text: str) -> str:
    # "视线朝向画面左侧" names a direction, not a region; strip it before the region search.
    for facing in sorted(FACINGS, key=len, reverse=True):
        text = text.replace(facing, " ")
    return text


def parse_frame_positions(text: str, subjects: list[str]) -> list[FramePosition]:
    """Best-effort extraction: one position per subject from the sentence that names it."""
    positions: list[FramePosition] = []
    prose = str(text or "")
    sentences = [part for part in _SENTENCE_SPLIT.split(prose) if part.strip()]
    for subject in dict.fromkeys(name.strip() for name in subjects if name and name.strip()):
        # Prefer the sentence where the subject opens a clause (it is the topic there);
        # "保留女人的眼睛" mentions her without positioning her.
        located = None
        for sentence in sentences:
            clauses = [clause.strip() for clause in re.split(r"[，,]", sentence)]
            topic = next((index for index, clause in enumerate(clauses) if clause.startswith(subject)), None)
            if topic is not None:
                located = (clauses, topic)
                break
        if located is None:
            sentence = next((part for part in sentences if subject in part), "")
            if not sentence:
                continue
            clauses = [clause.strip() for clause in re.split(r"[，,]", sentence)]
            located = (clauses, next(index for index, clause in enumerate(clauses) if subject in clause))
        clauses, start = located
        # Attributes belong to the clause naming the subject and the clauses right after it,
        # up to the next subject mention.
        scope: list[str] = []
        for clause in clauses[start:]:
            if scope and any(other in clause for other in subjects if other != subject):
                break
            scope.append(clause)
        window = "，".join(scope)
        occlusion = _OCCLUSION.search(window)
        forbidden = _FORBIDDEN.search("，".join(clauses))
        keep = re.search(r"保留[^，。；]{1,30}", window)
        position = FramePosition(
            subject=subject[:120],
            region=_first(REGIONS, _without_facings(window)),
            depth=_first(DEPTHS, window),
            facing=_first(FACINGS, window),
            occlusion=occlusion.group(1)[:200] if occlusion else "",
            keep_visible=keep.group(0)[:120] if keep else "",
            forbidden_zone=forbidden.group(1)[:200] if forbidden else "",
        )
        if position.is_anchored() or position.facing:
            positions.append(position)
    return positions


def render_frame_positions(positions: list[FramePosition]) -> str:
    """The five-part position sentence: region, depth, facing, occlusion, forbidden zone."""
    parts: list[str] = []
    for item in positions:
        where = "".join(filter(None, [item.region, f"的{item.depth}" if item.depth and item.region else item.depth]))
        clause = f"{item.subject}位于{where}" if where else item.subject
        if item.facing:
            clause += f"，{item.facing}"
        if item.occlusion:
            clause += f"，{item.occlusion}"
        if item.keep_visible:
            clause += f"，{item.keep_visible}"
        parts.append(clause)
    forbidden = "；".join(dict.fromkeys(item.forbidden_zone for item in positions if item.forbidden_zone))
    text = "；".join(parts)
    if forbidden:
        text += f"；{forbidden}"
    return text


ScreenSide = Literal["left", "right", "camera", "away", ""]


def facing_side(facing: str) -> ScreenSide:
    text = str(facing or "")
    if "背对" in text:
        return "away"
    if "镜头" in text:
        return "camera"
    if "右" in text:
        return "right"
    if "左" in text:
        return "left"
    return ""


def flipped_subjects(previous: list[FramePosition], current: list[FramePosition]) -> list[str]:
    """Subjects whose screen facing swapped left/right between two adjacent shots."""
    before = {item.subject: facing_side(item.facing) for item in previous}
    flipped = []
    for item in current:
        side = facing_side(item.facing)
        prior = before.get(item.subject, "")
        if side in {"left", "right"} and prior in {"left", "right"} and side != prior:
            flipped.append(item.subject)
    return flipped
