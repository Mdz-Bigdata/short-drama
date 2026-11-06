"""Shot camera-motion and shot-type vocabulary for the visual stage.

Clean-room behaviour parity with the ArcReel shot workspace (AGPL upstream; no
code copied): one canonical camera move per shot, taken from the vocabulary the
video providers publish themselves (MiniMax Hailuo ``[command]`` table, Alibaba
Wan basic/advanced motion table, Kling/Seedance natural-language moves), then
rendered in the phrasing each provider documents instead of being re-translated
downstream. Unknown free text degrades to a neutral default and says so; in a fight
that default is a follow move, because a locked-off camera is what makes a fight look static.
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
FIGHT_DEFAULT_CAMERA_MOTION = "Tracking Shot"
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


def normalize_camera_motion(value: Any, *, fight: bool = False) -> tuple[str, bool]:
    """Canonical motion plus whether the input was recognised (else the neutral default).

    ``fight`` changes only the fallback: an unrecognised move in a fight shot follows the
    action instead of silently locking off. A move the table names is kept as written.
    """
    default = FIGHT_DEFAULT_CAMERA_MOTION if fight else DEFAULT_CAMERA_MOTION
    key = _key(value)
    if not key:
        return default, False
    hit = _MOTION_BY_KEY.get(key)
    if hit:
        return hit, True
    # A phrase such as "缓慢推近主体" still names exactly one move: the longest
    # alias it contains wins ("推近" over "推"); a tie between different moves is
    # ambiguous and degrades.
    return _longest_alias(key, _MOTION_BY_KEY, default)


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


# 一镜一主运镜(《运镜库》第 1 条)：复合最多两个不冲突的方向(推 + 轻手持、环绕 + 微升)。
# 推了又拉、三种以上叠在一起，视频模型只会保一个、其余拍成抖动或变形。
_MOVE_CLASSES = (
    ("推近", re.compile(r"推近|推进|推至|推向|缓推|轻推|慢推|急推|前推")),
    ("拉远", re.compile(r"拉远|后拉|拉开|拉回|拉出")),
    ("摇", re.compile(r"横摇|[左右上下]摇|摇起|摇向|摇至|跟摇|甩镜|甩向")),
    # 「移向」单独出现常是人物或道具在动(「随右掌移向木砧」)：只有主语是镜头才算。
    ("移", re.compile(r"横移|平移|侧移|缓移|微移|跟移|移镜|(?:镜头|机位|机身|摄影机|相机)[^，。；,;→]{0,6}移向")),
    ("升降", re.compile(r"升镜|微升|上升|升起|降镜|下降|下沉|微降")),
    ("环绕", re.compile(r"环绕|绕拍|弧形")),
    ("手持", re.compile(r"手持")),
)
# 括注(英文术语、指纹)和否定句(「不拉回」「全程无甩镜」)不是运镜；「无人机」不是否定。
_MOTION_ASIDE = re.compile(r"[（(][^）)]*[）)]|`[^`]*`|\[[^\]]*\]|(?:不|无(?!人机))[^，。；,;、`\[（(]{0,8}")
# 移焦(「焦点由剑鞘拉回手部」「拉回焦点」)动的是焦平面，机身没有后退。
_FOCUS_PULL = re.compile(r"焦点[^，。；,;→]{0,24}(?:拉回|拉开|拉远|拉出)|拉回焦点|拉焦")
MAX_MOVE_CLASSES = 2


def move_classes(motion: Any) -> list[str]:
    """一句运镜里出现的运动种类(推近 / 拉远 / 摇 / 移 / 升降 / 环绕 / 手持)，按表内顺序。"""
    text = _FOCUS_PULL.sub(" ", _MOTION_ASIDE.sub(" ", str(motion or "")))
    return [name for name, pattern in _MOVE_CLASSES if pattern.search(text)]


# 一镜到底的武戏按节拍接力(「0–2秒…2–4秒…」)：每个节拍各算一镜。
_BEAT_SPAN = re.compile(r"\d+(?:\.\d+)?\s*[-–~～至]\s*\d+(?:\.\d+)?\s*秒")


# 环绕超过 180 度就自动越轴：两人的左右关系在片内翻转。整圈、一周、360 都是超了。
_FULL_ORBIT = re.compile(r"360|一周|一圈|整圈|全周|绕到(?:对面|背后)")


def motion_problem(motion: Any) -> str:
    """这句运镜违反一镜一主运镜、或环绕越轴的地方；没问题时为空串。"""
    for beat in _BEAT_SPAN.split(str(motion or "")):
        classes = move_classes(beat)
        if "推近" in classes and "拉远" in classes:
            return "同一镜里推近又拉远，方向对冲"
        if len(classes) > MAX_MOVE_CLASSES:
            return f"同一镜叠了{'、'.join(classes)}{len(classes)}种运镜"
        if "环绕" in classes and _FULL_ORBIT.search(beat):
            return "环绕超过180度就越轴，人物左右关系会翻转；限定在半圈以内"
    return ""
