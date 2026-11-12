# -*- coding: utf-8 -*-
"""The Chinese names the stage's enum values carry in prose, panels and prompts.

One accessor per table so a check message, a repair label and a prompt sentence can never
call the same posture by different names; the tables themselves are data
(``app/data/prompt/stage_brief.json`` and ``stage_camera_moves.json``).
"""

from __future__ import annotations

from app.core import prompt_data

_BRIEF = "stage_brief"
_MOVES = "stage_camera_moves"


def posture_zh(posture: object) -> str:
    """站立 / 跪地 …; an unknown value reads as standing, the model's default."""
    names = prompt_data.load(_BRIEF)["postures"]
    return str(names.get(str(posture or ""), names["stand"]))


def move_zh(kind: object) -> str:
    """推近 / 横移 …; an unknown kind reads as a fixed camera."""
    names = prompt_data.load(_MOVES)["names"]
    return str(names.get(str(kind or ""), names["static"]))


def hand_zh(hand: object) -> str:
    """右手 / 左手 / 双手 of a hold contact; ``""`` (and anything unknown) is the right hand."""
    names = prompt_data.load(_BRIEF)["contact_hands"]
    return str(names.get(str(hand or ""), names["right"]))


def phrase(key: str, **values: object) -> str:
    """A sentence template of the stage brief, filled in."""
    return prompt_data.text(_BRIEF, key).format(**values)


__all__ = ["hand_zh", "move_zh", "phrase", "posture_zh"]
