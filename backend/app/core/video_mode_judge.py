# -*- coding: utf-8 -*-
"""让文本模型按戏判定每段视频用首尾帧还是多图参考。

``video_references.plan_video_references`` 的自动路由只看手里有什么素材，判不了「这一段的结尾要不要精确
落定」；这里把这个问题交给模型，答案作为 ``VideoGenerationIntent.preferred_mode`` 交回路由，能否执行仍由
路由按供应商能力和实际素材把关。

只问真有得选的段落：附了视频 / 音频参考的段落走多模态（那是人放上去的素材，不能因为模型一句话丢掉），
供应商只支持一种的、打戏多瞬间（镜头之间硬切，首尾两张图表达不了）都不问。超长片段按瞬间切开的每一段
各有自己的落幅，照常问。模型没答、答错或关掉开关时，这些段落照旧走规则。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app import settings
from app.core import prompt_data

logger = logging.getLogger(__name__)

_DATA = "video_mode_judge"
ENABLED_ENV = "VIDEO_MODE_JUDGE"
FIRST_LAST = "first_last_frame"
MULTI_REFERENCE = "multi_reference"
_CHOICES = (FIRST_LAST, MULTI_REFERENCE)


@dataclass(frozen=True)
class Judgement:
    mode: str
    reason: str


@dataclass(frozen=True)
class Clip:
    """一段视频请求里，判定用得上的那部分戏。"""

    id: str
    beats: tuple[str, ...]
    end_state: str = ""
    motion: str = ""
    seconds: int = 0
    people: int = 0
    spoken: bool = False
    emotion_point: str = ""


def enabled() -> bool:
    return settings.env_flag(ENABLED_ENV, True)


def has_a_choice(provider_modes: Sequence[str], *, beats: int, fight: bool, attached: bool) -> bool:
    """这一段值不值得问：两种方式都能执行，且没有哪一种已经被这段戏排除。"""
    if attached or (fight and beats > 1):
        return False
    return all(mode in provider_modes for mode in _CHOICES)


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _line(clip: Clip) -> str:
    beat_chars, max_beats = prompt_data.number(_DATA, "beat_chars"), prompt_data.number(_DATA, "max_beats")
    record = {
        "id": clip.id, "瞬间数": len(clip.beats), "时长秒": clip.seconds, "人数": clip.people, "有台词": clip.spoken,
        "画面": [_trim(beat, beat_chars) for beat in clip.beats[:max_beats]],
        "落幅": _trim(clip.end_state, prompt_data.number(_DATA, "end_state_chars")),
        "运镜": _trim(clip.motion, beat_chars),
        "可选": list(_CHOICES),
    }
    if clip.emotion_point:
        record["情绪点"] = clip.emotion_point
    return json.dumps(record, ensure_ascii=False)


def parse(answer: str | None, ids: Sequence[str], *, extract: Callable[[str], dict | None]) -> dict[str, Judgement]:
    """答案里能用的判定；编号不在这批里、方式不在可选里的条目不算。"""
    data = extract(answer or "") or {}
    rows = data.get("clips") if isinstance(data, dict) else None
    wanted = set(ids)
    found: dict[str, Judgement] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        clip_id, mode = str(row.get("id") or ""), str(row.get("mode") or "")
        if clip_id in wanted and mode in _CHOICES:
            found[clip_id] = Judgement(mode, _trim(str(row.get("reason") or ""), prompt_data.number(_DATA, "reason_chars")))
    return found


def judge(
    clips: Sequence[Clip], *, ask: Callable[[str, str, Callable[[str], bool]], str | None], extract: Callable[[str], dict | None],
) -> dict[str, Judgement]:
    """逐批问模型。``ask(system, user, accept)`` 负责调用和复用；一批失败只影响这一批，它们照旧走规则。"""
    system = prompt_data.text(_DATA, "system")
    size = prompt_data.number(_DATA, "batch_size")
    judged: dict[str, Judgement] = {}
    for start in range(0, len(clips), size):
        batch = clips[start:start + size]
        ids = [clip.id for clip in batch]
        try:
            answer = ask(system, "\n".join(_line(clip) for clip in batch), lambda text, ids=ids: bool(parse(text, ids, extract=extract)))
        except Exception as error:  # noqa: BLE001 - 判定是加分项，问不到不能让这一阶段失败
            logger.warning("[Stage5] 视频方式判定失败，这批 %s 段按规则选择：%s", len(batch), type(error).__name__)
            continue
        judged.update(parse(answer, ids, extract=extract))
    return judged


def max_tokens() -> int:
    return prompt_data.number(_DATA, "max_tokens")


__all__ = ["ENABLED_ENV", "FIRST_LAST", "MULTI_REFERENCE", "Clip", "Judgement", "enabled", "has_a_choice", "judge", "max_tokens", "parse"]
