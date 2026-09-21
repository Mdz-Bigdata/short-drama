"""Shot camera-motion and shot-type vocabulary for the visual stage.

Clean-room behaviour parity with the ArcReel shot workspace (AGPL upstream; no
code copied): one canonical camera move per shot, taken from the vocabulary the
video providers publish themselves (MiniMax Hailuo ``[command]`` table, Alibaba
Wan basic/advanced motion table, Kling/Seedance natural-language moves), then
rendered in the phrasing each provider documents instead of being re-translated
downstream. Unknown free text degrades to a neutral default and says so.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds

CAMERA_MOTIONS: tuple[tuple[str, str], ...] = (
    ("Static", "固定"),
    ("Pan Left", "左摇"),
    ("Pan Right", "右摇"),
    ("Tilt Up", "上摇"),
    ("Tilt Down", "下摇"),
    ("Zoom In", "推近"),
    ("Zoom Out", "拉远"),
    ("Push In", "推镜"),
    ("Pull Out", "拉镜"),
    ("Truck Left", "左移"),
    ("Truck Right", "右移"),
    ("Pedestal Up", "升镜"),
    ("Pedestal Down", "降镜"),
    ("Orbit", "环绕"),
    ("Tracking Shot", "跟踪"),
    ("Shake", "晃动"),
)
SHOT_TYPES: tuple[tuple[str, str], ...] = (
    ("Extreme Close-up", "大特写"),
    ("Close-up", "特写"),
    ("Medium Close-up", "中特写"),
    ("Medium Shot", "中景"),
    ("Medium Long Shot", "中远景"),
    ("Long Shot", "远景"),
    ("Extreme Long Shot", "大远景"),
    ("Over-the-shoulder", "过肩镜头"),
    ("Point-of-view", "主观镜头"),
)
DEFAULT_CAMERA_MOTION = "Static"
DEFAULT_SHOT_TYPE = "Medium Shot"
CAMERA_MOTION_LABELS = dict(CAMERA_MOTIONS)
SHOT_TYPE_LABELS = dict(SHOT_TYPES)


def _key(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[（(][^）)]*[）)]", " ", text)
    return " ".join(text.replace("_", " ").replace("-", " ").split()).casefold()


_MOTION_BY_KEY = {_key(value): value for value, _ in CAMERA_MOTIONS}
_MOTION_BY_KEY.update({_key(label): value for value, label in CAMERA_MOTIONS})
# Canonical names and labels outrank colloquial synonyms when a phrase contains
# both ("缓慢推近" holds 推近 and 慢推; the label wins).
_CANONICAL_KEYS = set(_MOTION_BY_KEY)
# Storyboard tables and older projects write moves in many spellings; these are
# the ones seen in practice, mapped onto the provider vocabulary.
_MOTION_SYNONYMS = {
    "Static": ("static shot", "fixed", "fixed shot", "locked", "locked off", "固定镜头", "固定机位", "静止",
               "establishing shot", "establishing", "无运镜", "不动"),
    "Pan Left": ("pan l", "左横摇", "向左摇", "左平摇"),
    "Pan Right": ("pan r", "右横摇", "向右摇", "右平摇"),
    "Tilt Up": ("仰摇", "向上摇", "上仰"),
    "Tilt Down": ("俯摇", "向下摇", "下俯"),
    "Zoom In": ("zoom", "变焦推近", "变焦推", "焦距推近", "推特写", "extreme close up dolly", "extreme close-up dolly"),
    "Zoom Out": ("变焦拉远", "变焦拉", "焦距拉远"),
    "Push In": ("dolly in", "slow dolly in", "dolly forward", "push", "推进", "推", "推镜头", "缓推", "慢推",
                "dolly zoom", "希区柯克变焦"),
    "Pull Out": ("dolly out", "slow dolly out", "dolly back", "pull", "pull back", "拉出", "拉", "拉镜头", "缓拉", "慢拉"),
    "Truck Left": ("truck l", "横移左", "向左横移", "左平移", "lateral tracking left"),
    "Truck Right": ("truck r", "横移右", "向右横移", "右平移", "lateral tracking right", "lateral tracking"),
    "Pedestal Up": ("crane up", "boom up", "升", "上升", "摇臂上升", "升起", "升降上"),
    "Pedestal Down": ("crane down", "boom down", "降", "下降", "摇臂下降", "降下", "升降下"),
    "Orbit": ("arc", "arc shot", "orbit shot", "环绕镜头", "弧线", "弧形运动", "围绕", "环拍", "360"),
    "Tracking Shot": ("tracking", "track", "follow", "follow shot", "follow the subject", "跟拍", "跟随", "跟镜",
                      "跟踪拍摄", "跟随拍摄", "steadicam"),
    "Shake": ("handheld", "hand held", "手持", "抖动", "晃镜", "震动"),
}
for _canonical, _aliases in _MOTION_SYNONYMS.items():
    for _alias in _aliases:
        _MOTION_BY_KEY.setdefault(_key(_alias), _canonical)

_SHOT_TYPE_BY_KEY = {_key(value): value for value, _ in SHOT_TYPES}
_SHOT_TYPE_BY_KEY.update({_key(label): value for value, label in SHOT_TYPES})
_CANONICAL_KEYS |= set(_SHOT_TYPE_BY_KEY)
_SHOT_TYPE_SYNONYMS = {
    "Extreme Close-up": ("ecu", "xcu", "extreme closeup", "大特", "极特写"),
    "Close-up": ("cu", "closeup", "close up", "近景", "特写镜头"),
    "Medium Close-up": ("mcu", "medium closeup", "中近景", "中近", "近中景"),
    "Medium Shot": ("ms", "mid shot", "medium", "中景镜头", "半身"),
    "Medium Long Shot": ("mls", "medium wide", "medium wide shot", "中全景", "中远", "七分身"),
    "Long Shot": ("ls", "fs", "full shot", "wide", "wide shot", "全景", "全身", "远景镜头"),
    "Extreme Long Shot": ("els", "ews", "extreme wide", "extreme wide shot", "大全景", "大远", "远景大全景"),
    "Over-the-shoulder": ("ots", "over the shoulder", "over shoulder", "过肩", "过肩镜"),
    "Point-of-view": ("pov", "point of view", "主观", "主观视角", "第一人称"),
}
for _canonical, _aliases in _SHOT_TYPE_SYNONYMS.items():
    for _alias in _aliases:
        _SHOT_TYPE_BY_KEY.setdefault(_key(_alias), _canonical)


def normalize_camera_motion(value: Any) -> tuple[str, bool]:
    """Canonical motion plus whether the input was recognised (else the neutral default)."""
    key = _key(value)
    if not key:
        return DEFAULT_CAMERA_MOTION, False
    hit = _MOTION_BY_KEY.get(key)
    if hit:
        return hit, True
    # A phrase such as "缓慢推近主体" still names exactly one move: the longest
    # alias it contains wins ("推近" over "推"); a tie between different moves is
    # ambiguous and degrades.
    return _longest_alias(key, _MOTION_BY_KEY, DEFAULT_CAMERA_MOTION)


def _longest_alias(key: str, table: dict[str, str], default: str) -> tuple[str, bool]:
    best: tuple[int, int] | None = None
    winners: set[str] = set()
    for alias_key, canonical in table.items():
        if len(alias_key) < 2 or alias_key not in key:
            continue
        score = (len(alias_key), 1 if alias_key in _CANONICAL_KEYS else 0)
        if best is None or score > best:
            best, winners = score, {canonical}
        elif score == best:
            winners.add(canonical)
    if len(winners) == 1:
        return winners.pop(), True
    return default, False


def normalize_shot_type(value: Any) -> tuple[str, bool]:
    key = _key(value)
    if not key:
        return DEFAULT_SHOT_TYPE, False
    hit = _SHOT_TYPE_BY_KEY.get(key)
    if hit:
        return hit, True
    return _longest_alias(key, _SHOT_TYPE_BY_KEY, DEFAULT_SHOT_TYPE)


# MiniMax Hailuo documents fifteen bracketed camera commands; Orbit is the one
# vocabulary entry without a command and is written out in words.
_MINIMAX_COMMANDS = {
    "Static": "[Static shot]", "Pan Left": "[Pan left]", "Pan Right": "[Pan right]",
    "Tilt Up": "[Tilt up]", "Tilt Down": "[Tilt down]", "Zoom In": "[Zoom in]", "Zoom Out": "[Zoom out]",
    "Push In": "[Push in]", "Pull Out": "[Pull out]", "Truck Left": "[Truck left]", "Truck Right": "[Truck right]",
    "Pedestal Up": "[Pedestal up]", "Pedestal Down": "[Pedestal down]", "Tracking Shot": "[Tracking shot]",
    "Shake": "[Shake]",
}
_PHRASES = {
    "Static": "固定机位，镜头保持不动",
    "Pan Left": "镜头向左摇",
    "Pan Right": "镜头向右摇",
    "Tilt Up": "镜头向上摇",
    "Tilt Down": "镜头向下摇",
    "Zoom In": "镜头变焦推近",
    "Zoom Out": "镜头变焦拉远",
    "Push In": "镜头缓慢推进",
    "Pull Out": "镜头缓慢拉出",
    "Truck Left": "镜头向左横移",
    "Truck Right": "镜头向右横移",
    "Pedestal Up": "镜头垂直升起",
    "Pedestal Down": "镜头垂直下降",
    "Orbit": "镜头围绕主体环绕",
    "Tracking Shot": "镜头跟随主体移动",
    "Shake": "轻微手持晃动",
}


def render_camera_motion(motion: str, provider_family: str = "") -> str:
    """Provider-documented phrasing for one move; the rule stays one move per shot."""
    canonical, _ = normalize_camera_motion(motion)
    phrase = _PHRASES[canonical]
    if provider_family == "minimax_h3" and canonical in _MINIMAX_COMMANDS:
        return f"{_MINIMAX_COMMANDS[canonical]} {phrase}"
    return f"{phrase}（{canonical}）"


def duration_options(video_model: str) -> list[int]:
    """Whole seconds the selected video model can render for one clip."""
    return list(range(MIN_SHOT_SECONDS, max_shot_seconds(video_model) + 1))


def vocabulary() -> dict[str, list[dict[str, str]]]:
    return {
        "camera_motions": [{"value": value, "label": label} for value, label in CAMERA_MOTIONS],
        "shot_types": [{"value": value, "label": label} for value, label in SHOT_TYPES],
    }
