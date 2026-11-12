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

from app.core import prompt_data

from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds

# The vocabulary's Chinese labels, aliases, phrasings and lint sentences: app/data/prompt/camera_amounts.json
# (alongside the move amounts it already held). The English ids below are the provider vocabulary: code values.
_WORDING = "camera_amounts"


def _table(key: str) -> Any:
    return prompt_data.value(_WORDING, key)


def _says(key: str, /, **values: object) -> str:
    """A sentence of the motion lint's wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(_table("problems")[key]).format(**values)


_MOTION_IDS: tuple[str, ...] = (
    "Static", "Pan Left", "Pan Right", "Tilt Up", "Tilt Down", "Zoom In", "Zoom Out", "Push In", "Pull Out",
    "Truck Left", "Truck Right", "Pedestal Up", "Pedestal Down", "Orbit", "Tracking Shot", "Shake",
)
_SHOT_TYPE_IDS: tuple[str, ...] = (
    "Extreme Close-up", "Close-up", "Medium Close-up", "Medium Shot", "Medium Long Shot", "Long Shot",
    "Extreme Long Shot", "Over-the-shoulder", "Point-of-view",
)
CAMERA_MOTIONS: tuple[tuple[str, str], ...] = tuple((value, str(_table("motion_labels")[value])) for value in _MOTION_IDS)
SHOT_TYPES: tuple[tuple[str, str], ...] = tuple((value, str(_table("shot_type_labels")[value])) for value in _SHOT_TYPE_IDS)
DEFAULT_CAMERA_MOTION = "Static"
FIGHT_DEFAULT_CAMERA_MOTION = "Tracking Shot"
DEFAULT_SHOT_TYPE = "Medium Shot"
CAMERA_MOTION_LABELS = dict(CAMERA_MOTIONS)
SHOT_TYPE_LABELS = dict(SHOT_TYPES)


# A bracketed aside (「推近（Push In）」) is not part of the name.
_KEY_ASIDE = re.compile(str(_table("key_aside")))


def _key(value: Any) -> str:
    text = str(value or "")
    text = _KEY_ASIDE.sub(" ", text)
    return " ".join(text.replace("_", " ").replace("-", " ").split()).casefold()


_MOTION_BY_KEY = {_key(value): value for value, _ in CAMERA_MOTIONS}
_MOTION_BY_KEY.update({_key(label): value for value, label in CAMERA_MOTIONS})
# Canonical names and labels outrank colloquial synonyms when a phrase contains
# both ("缓慢推近" holds 推近 and 慢推; the label wins).
_CANONICAL_KEYS = set(_MOTION_BY_KEY)
# Storyboard tables and older projects write moves in many spellings; these are
# the ones seen in practice, mapped onto the provider vocabulary.
_MOTION_SYNONYMS = {canonical: tuple(str(alias) for alias in _table("motion_synonyms")[canonical]) for canonical in _MOTION_IDS}
for _canonical, _aliases in _MOTION_SYNONYMS.items():
    for _alias in _aliases:
        _MOTION_BY_KEY.setdefault(_key(_alias), _canonical)

_SHOT_TYPE_BY_KEY = {_key(value): value for value, _ in SHOT_TYPES}
_SHOT_TYPE_BY_KEY.update({_key(label): value for value, label in SHOT_TYPES})
_CANONICAL_KEYS |= set(_SHOT_TYPE_BY_KEY)
_SHOT_TYPE_SYNONYMS = {
    canonical: tuple(str(alias) for alias in _table("shot_type_synonyms")[canonical]) for canonical in _SHOT_TYPE_IDS
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
_MINIMAX_COMMANDS = {canonical: str(command) for canonical, command in _table("minimax_commands").items()}
_PHRASES = {canonical: str(_table("phrases")[canonical]) for canonical in _MOTION_IDS}


def render_camera_motion(motion: str, provider_family: str = "") -> str:
    """Provider-documented phrasing for one move; the rule stays one move per shot."""
    canonical, _ = normalize_camera_motion(motion)
    # 幅度写成落幅时画面变了多少，不写副词也不写秒数(见 data/prompt/camera_amounts.json)。
    amount = _table("amounts").get(canonical, "")
    render = _table("render")
    phrase = str(render["with_amount"]).format(phrase=_PHRASES[canonical], amount=amount) if amount else _PHRASES[canonical]
    if provider_family == "minimax_h3" and canonical in _MINIMAX_COMMANDS:
        return str(render["minimax"]).format(command=_MINIMAX_COMMANDS[canonical], phrase=phrase)
    return str(render["named"]).format(phrase=phrase, canonical=canonical)


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
_MOVE_CLASSES = tuple((str(name), re.compile(str(pattern))) for name, pattern in _table("move_classes"))
# 括注(英文术语、指纹)和否定句(「不拉回」「全程无甩镜」)不是运镜；「无人机」不是否定。
_MOTION_ASIDE = re.compile(str(_table("motion_aside")))
# 移焦(「焦点由剑鞘拉回手部」「拉回焦点」)动的是焦平面，机身没有后退。
_FOCUS_PULL = re.compile(str(_table("focus_pull")))
_PUSH_CLASS, _PULL_CLASS = (str(name) for name in _table("opposed_classes"))
_ORBIT_CLASS = str(_table("orbit_class"))
MAX_MOVE_CLASSES = 2


def move_classes(motion: Any) -> list[str]:
    """一句运镜里出现的运动种类(推近 / 拉远 / 摇 / 移 / 升降 / 环绕 / 手持)，按表内顺序。"""
    text = _FOCUS_PULL.sub(" ", _MOTION_ASIDE.sub(" ", str(motion or "")))
    return [name for name, pattern in _MOVE_CLASSES if pattern.search(text)]


# 一镜到底的武戏按节拍接力(「0–2秒…2–4秒…」)：每个节拍各算一镜。
_BEAT_SPAN = re.compile(str(_table("beat_span")))


# 环绕超过 180 度就自动越轴：两人的左右关系在片内翻转。整圈、一周、360 都是超了。
_FULL_ORBIT = re.compile(str(_table("full_orbit")))


def motion_problem(motion: Any) -> str:
    """这句运镜违反一镜一主运镜、或环绕越轴的地方；没问题时为空串。"""
    for beat in _BEAT_SPAN.split(str(motion or "")):
        classes = move_classes(beat)
        if _PUSH_CLASS in classes and _PULL_CLASS in classes:
            return _says("opposed")
        if len(classes) > MAX_MOVE_CLASSES:
            return _says("stacked", classes=_says("class_joiner").join(classes), count=len(classes))
        if _ORBIT_CLASS in classes and _FULL_ORBIT.search(beat):
            return _says("orbit")
    return ""
