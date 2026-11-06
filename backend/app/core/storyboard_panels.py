"""分镜表落成画格：用尽量少的格子讲清一场戏，没有变化的重复格不画。

一格画面就是阶段五的一段视频(4 秒起，单段不超过模型上限)。模型给的分镜表常常是逐秒节拍
(一两秒一行，几十行)，按行出图既浪费，也交不了视频。所以先合并：同一组人物、同一地点里
连续发生的动作，只要景别靠运镜够得着、合起来不超过一段视频的时长，就并进同一格，后面的
动作、台词和声音原样写进这一格，一个字不丢；换地点、换人物组合、反转揭露这类拍点另起一格。
再去掉与上一格没有变化的格；仍然超过九格时，把整场按时间顺序分成九段，每段取一格——第一段
取开场，最后一段取收尾，中间各段取与上一格变化最大的那一镜。

格数还有一道按时长的上限(``panel_limit``)：每 5 秒一格，一场几秒就只给几格；画多了只能生成
4 秒、成片剪成不到 2 秒，图和视频都白做。超出上限时(``fit_panels``)把变化最小的
相邻两格并起来，动作和台词一字不丢。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app import settings
from app.core.camera_motion import motion_problem
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds, preferred_shot_seconds
from app.core.writer_dashboard import parse_duration_seconds

MAX_PANELS = 9
# 一场戏每这么多秒才给一格(STORYBOARD_SECONDS_PER_PANEL)：图和视频都按格算，宁少勿多。
SECONDS_PER_PANEL = 5
# 一格视频里最多推进几个动作：再多模型就会漏拍或糊成一团。
MAX_BEATS_PER_PANEL = 4
# 单段视频超过这个时长容易漂脸、漂场景，模型上限更长也按这个自动合并；
# 只有超出本场格数上限时(fit_panels)才并到模型上限，如 Seedance 2.5 的 30 秒。
STEADY_CLIP_SECONDS = 15
# 没写时长的行按这个估。
DEFAULT_BEAT_SECONDS = 3
# 这些拍点要单独一张图让观众看清，不并进上一格。
_STANDALONE = ("反转", "揭露", "真相", "转场", "时间跳", "闪回", "回忆", "插叙")
# 正反打与过肩是换到对面去拍：一段视频里转不过去，必须切。
_REVERSE_SETUPS = ("过肩", "反打", "越轴", "OTS", "OVER")
# 景别从远到近的刻度；同一格里靠推拉够得着的跨度。
_SIZE_RANKS = (
    (("大特写", "局部特写", "ECU", "EXTREME CLOSE"), 7), (("中近景", "MCU"), 4), (("特写", "CU", "CLOSE"), 6),
    (("近景",), 5), (("远中景", "中全景", "MLS", "MWS"), 2), (("中景", "MS", "MEDIUM"), 3),
    (("大远景", "ELS", "EWS"), 0), (("远景", "LS", "WS", "LONG", "WIDE"), 0), (("全景", "FS", "FULL"), 1),
)
MAX_SIZE_REACH = 3
# 画面描述的字面相似度达到这个值，就算景别、机位都换了也是同一个画面。
SAME_PICTURE = 0.85
# 景别、机位、入镜人物都没变时，画面描述相似到这个程度就算重复。
SAME_SETUP_PICTURE = 0.6

_NO_LINE = ("无", "-", "—", "（无）", "(无)")
_FILM_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[（(]?\s*成片|成片\s*[:：]?\s*(\d+(?:\.\d+)?)", re.I)
_NOISE = re.compile(r"[\s，,。；;：:、！!？?“”\"'（）()【】\[\]《》<>·\-—_/|]+")


def _norm(value: Any) -> str:
    return _NOISE.sub("", str(value or "")).lower()


def _bigrams(text: str) -> set[str]:
    text = _norm(text)
    return {text[index:index + 2] for index in range(len(text) - 1)} or ({text} if text else set())


def picture_similarity(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
    """两格画面描述的字面相似度(0–1)。"""
    a, b = _bigrams(first.get("desc")), _bigrams(second.get("desc"))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cast(shot: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(_norm(name) for name in shot.get("characters") or [] if _norm(name)))


def _same_setup(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return (
        _norm(first.get("size")) == _norm(second.get("size"))
        and _norm(first.get("angle")) == _norm(second.get("angle"))
        and _cast(first) == _cast(second)
    )


def repeats(previous: Mapping[str, Any], shot: Mapping[str, Any]) -> bool:
    """这一格与上一格相比没有新的机位、景别、人物或动作：画出来是同一张图。"""
    similarity = picture_similarity(previous, shot)
    if similarity >= SAME_PICTURE:
        return True
    return _same_setup(previous, shot) and similarity >= SAME_SETUP_PICTURE


def _change(previous: Mapping[str, Any], shot: Mapping[str, Any]) -> float:
    """这一格相对上一格变了多少：画面描述、景别、机位、入镜人物各计一份。"""
    return (
        (1 - picture_similarity(previous, shot))
        + 0.3 * (_norm(previous.get("size")) != _norm(shot.get("size")))
        + 0.3 * (_norm(previous.get("angle")) != _norm(shot.get("angle")))
        + 0.2 * (_cast(previous) != _cast(shot))
    )


def select_panels(shots: Sequence[Mapping[str, Any]], limit: int = MAX_PANELS) -> list[dict[str, Any]]:
    """把分镜表压成一页画格：去重复格，超过 ``limit`` 时按时间分段各取一格。顺序不变。"""
    distinct: list[dict[str, Any]] = []
    for shot in shots:
        if is_vacant(shot):
            continue
        if distinct and repeats(distinct[-1], shot):
            continue
        distinct.append(dict(shot))
    if len(distinct) <= limit:
        return distinct
    total = len(distinct)
    picks: list[dict[str, Any]] = []
    for part in range(limit):
        run = distinct[part * total // limit:(part + 1) * total // limit]
        if part == 0:
            picks.append(run[0])
        elif part == limit - 1:
            picks.append(run[-1])
        else:
            picks.append(max(run, key=lambda shot: _change(picks[-1], shot)))
    return picks


def _size_rank(size: Any) -> int | None:
    text = str(size or "").upper()
    for terms, rank in _SIZE_RANKS:
        if any(term.upper() in text for term in terms):
            return rank
    return None


_SLIGHT = re.compile(r"(略|微|稍|偏)[仰俯高低]")
# 模型把「其余格留白」写成了表格行：这些行没有画面，不出图。
_VACANT = ("留白", "空格", "待补", "空位")


def is_vacant(shot: Mapping[str, Any]) -> bool:
    desc = str(shot.get("desc") or "").strip()
    if not desc:
        return True
    head = desc[:6]
    return any(word in head for word in _VACANT) or any(word == str(shot.get("size") or "").strip() for word in _VACANT)


def _camera_height(angle: Any) -> str:
    """机位高度：仰拍、俯拍、平视。换高度就是换机位，一段视频里不升降过去；「略仰、略俯」仍算平视。"""
    text = _SLIGHT.sub("", str(angle or ""))
    if any(word in text for word in ("仰", "低机位", "低角度")):
        return "low"
    if any(word in text for word in ("俯", "高机位", "顶拍", "鸟瞰")):
        return "high"
    return "eye" if text.strip() else ""


def _seconds(shot: Mapping[str, Any]) -> int:
    return parse_duration_seconds(shot.get("duration")) or DEFAULT_BEAT_SECONDS


def _place(shot: Mapping[str, Any]) -> str:
    return _norm(shot.get("scene_id")) or _norm(shot.get("scene"))


def _can_join(panel: Mapping[str, Any], shot: Mapping[str, Any], *, seconds: int, cap: int) -> bool:
    if panel["_seconds"] + seconds > cap:
        return False
    if _place(panel) and _place(shot) and _place(panel) != _place(shot):
        return False
    # 只能推近到上一拍画面里已经有的人(或其局部：手、眼)；新人物入画、切到对面那个人，都另起一格。
    if not set(_cast(shot)) <= set(panel["_last_cast"]):
        return False
    if any(word.upper() in str(shot.get("angle") or "").upper() for word in _REVERSE_SETUPS):
        return False
    if panel["_beats"] >= MAX_BEATS_PER_PANEL:
        return False
    last, rank = panel["_last_rank"], _size_rank(shot.get("size"))
    if last is not None and rank is not None and abs(last - rank) > MAX_SIZE_REACH:
        return False
    # 不到一段视频下限的格交不了视频：机位高度略有起落、或这一拍本身是反应，也带着一起拍。
    if _must_join(panel, seconds):
        return True
    # 景别变了要在这一格里补一段推 / 拉；补上就成了推了又拉、或三种运镜叠在一起，就另起一格。
    move = _size_move(panel, shot)
    if move and motion_problem(_join(str(panel.get("motion") or ""), move, "，随后")):
        return False
    height, last_height = _camera_height(shot.get("angle")), panel["_last_height"]
    if height and last_height and height != last_height:
        return False
    return not any(word in str(shot.get("narrative_purpose") or "") for word in _STANDALONE)


def _must_join(panel: Mapping[str, Any], seconds: int) -> bool:
    return panel["_seconds"] < MIN_SHOT_SECONDS or seconds < MIN_SHOT_SECONDS / 2


def _size_move(panel: Mapping[str, Any], shot: Mapping[str, Any]) -> str:
    """并进这一拍时格里要补的推 / 拉(景别没变就是空串)。"""
    rank, last = _size_rank(shot.get("size")), panel["_last_rank"]
    if rank is None or last is None or rank == last:
        return ""
    return f"{'推近至' if rank > last else '拉远至'}{shot.get('size')}"


def _join(text: str, extra: str, joiner: str) -> str:
    extra = str(extra or "").strip()
    if not extra:
        return text
    return f"{text}{joiner}{extra}" if text else extra


def _join_lines(text: Any, extra: Any) -> str:
    """把两格的台词接起来；「无」不是台词，不写进去。"""
    lines = [str(line or "").strip() for line in (text, extra)]
    return "；".join(line for line in lines if line and line not in _NO_LINE) or str(text or "")


def consolidate_panels(shots: Sequence[Mapping[str, Any]], *, video_model: str = "") -> list[dict[str, Any]]:
    """把同一机位组、同一组人物里连续的动作并成一格视频；合并后的动作、台词与声音全部保留。"""
    cap = min(max_shot_seconds(video_model), STEADY_CLIP_SECONDS)
    panels: list[dict[str, Any]] = []
    for raw in shots:
        if is_vacant(raw):
            continue
        shot = dict(raw)
        seconds = _seconds(shot)
        if panels and _can_join(panels[-1], shot, seconds=seconds, cap=cap):
            panel = panels[-1]
            panel["desc"] = _join(str(panel.get("desc") or ""), str(shot.get("desc") or ""), "；随后")
            panel["dialogue"] = _join_lines(panel.get("dialogue"), shot.get("dialogue"))
            if str(shot.get("sound") or "") not in str(panel.get("sound") or ""):
                panel["sound"] = _join(str(panel.get("sound") or ""), str(shot.get("sound") or ""), "；")
            panel["narrative_purpose"] = _join(str(panel.get("narrative_purpose") or ""), str(shot.get("narrative_purpose") or ""), "→")
            rank = _size_rank(shot.get("size"))
            joined = _join(str(panel.get("motion") or ""), _size_move(panel, shot), "，随后")
            # 太短只能并进来的那一拍：补的推 / 拉会和格里的运镜对冲，就不补，景别交给画面描述。
            if not motion_problem(joined):
                panel["motion"] = joined
            if rank is not None:
                panel["_last_rank"] = rank
            panel["_last_cast"] = _cast(shot) or panel["_last_cast"]
            panel["_last_height"] = _camera_height(shot.get("angle")) or panel["_last_height"]
            panel["_seconds"] += seconds
            panel["_beats"] += 1
            panel["duration"] = f"{panel['_seconds']}s"
            panel["merged_shots"] = [*panel.get("merged_shots", []), shot.get("shot_id")]
            continue
        shot["_seconds"], shot["_beats"], shot["_last_rank"], shot["_last_cast"] = seconds, 1, _size_rank(shot.get("size")), _cast(shot)
        shot["_last_height"] = _camera_height(shot.get("angle"))
        panels.append(shot)
    for panel in panels:
        for key in ("_seconds", "_beats", "_last_rank", "_last_cast", "_last_height"):
            panel.pop(key, None)
    return panels


def panel_limit(scene_duration: Any, *, video_model: str = "") -> int:
    """这场戏最多几格：时长除以每格秒数，1–9 格。

    每格秒数默认取 5 秒与所选模型宜用下限中较大的(Seedance 2.5 是 10 秒，30 秒的场 3 格)；
    STORYBOARD_SECONDS_PER_PANEL 设了就按它，调大格数更少。

    没写时长的场次(旧任务)估不出，只受每页九格的限制。
    """
    seconds = parse_duration_seconds(scene_duration)
    if not seconds:
        return MAX_PANELS
    default = max(SECONDS_PER_PANEL, preferred_shot_seconds(video_model)[0])
    per_panel = settings.env_int("STORYBOARD_SECONDS_PER_PANEL", default, minimum=MIN_SHOT_SECONDS, maximum=30)
    return max(1, min(MAX_PANELS, seconds // per_panel))


def _film_seconds(shot: Mapping[str, Any]) -> float:
    """这一格成片里占几秒：模型写了「生成 4 秒｜成片 1.8 秒」就取后者，并起来才不会把场戏拉长。"""
    if "_film_seconds" in shot:
        return float(shot["_film_seconds"])
    match = _FILM_SECONDS.search(str(shot.get("duration") or ""))
    if match:
        return float(match.group(1) or match.group(2))
    return float(_seconds(shot))


def _beats(panel: Mapping[str, Any]) -> int:
    return 1 + len(panel.get("merged_shots") or [])


def _fit_cost(first: Mapping[str, Any], second: Mapping[str, Any], *, cap: int) -> float | None:
    """把这两格并成一格的代价，越小越该并；``None`` 是不能并：一段视频装不下，或后一格要单独看清。"""
    if _film_seconds(first) + _film_seconds(second) > cap or _beats(first) + _beats(second) > MAX_BEATS_PER_PANEL:
        return None
    if any(word in str(second.get("narrative_purpose") or "") for word in _STANDALONE):
        return None
    reverse = any(word.upper() in str(second.get("angle") or "").upper() for word in _REVERSE_SETUPS)
    return _change(first, second) + 0.5 * (not set(_cast(second)) <= set(_cast(first))) + 0.3 * reverse


def _combine(first: Mapping[str, Any], second: Mapping[str, Any], *, cap: int) -> dict[str, Any]:
    """后一格并进前一格：机位和起幅沿用前一格，动作、台词、声音、入镜人物全部留下。"""
    panel = dict(first)
    panel["desc"] = _join(str(first.get("desc") or ""), str(second.get("desc") or ""), "；随后")
    panel["dialogue"] = _join_lines(first.get("dialogue"), second.get("dialogue"))
    if str(second.get("sound") or "") not in str(first.get("sound") or ""):
        panel["sound"] = _join(str(first.get("sound") or ""), str(second.get("sound") or ""), "；")
    panel["narrative_purpose"] = _join(str(first.get("narrative_purpose") or ""), str(second.get("narrative_purpose") or ""), "→")
    joined = _join(str(first.get("motion") or ""), str(second.get("motion") or ""), "，随后")
    if not motion_problem(joined):
        panel["motion"] = joined
    panel["characters"] = list(dict.fromkeys([*(first.get("characters") or []), *(second.get("characters") or [])]))
    # 并了几次都从原始秒数累加，不让每次取整和下限一路抬高这一格的时长。
    panel["_film_seconds"] = _film_seconds(first) + _film_seconds(second)
    panel["duration"] = f"{min(cap, max(MIN_SHOT_SECONDS, math.ceil(panel['_film_seconds'])))}s"
    panel["merged_shots"] = [*(first.get("merged_shots") or []), second.get("shot_id"), *(second.get("merged_shots") or [])]
    return panel


def fit_panels(panels: Sequence[Mapping[str, Any]], limit: int, *, video_model: str = "") -> list[dict[str, Any]]:
    """把超出 ``limit`` 的格并回去，每次并变化最小的相邻两格。再没有能并的就停，宁可多一格也不塞坏一段视频。"""
    cap = max_shot_seconds(video_model)
    fitted = [dict(panel) for panel in panels]
    while len(fitted) > max(1, limit):
        costs = [(_fit_cost(fitted[index], fitted[index + 1], cap=cap), index) for index in range(len(fitted) - 1)]
        legal = [(cost, index) for cost, index in costs if cost is not None]
        if not legal:
            break
        _, index = min(legal)
        fitted[index:index + 2] = [_combine(fitted[index], fitted[index + 1], cap=cap)]
    for panel in fitted:
        panel.pop("_film_seconds", None)
    return fitted


__all__ = [
    "MAX_PANELS", "consolidate_panels", "fit_panels", "is_vacant", "panel_limit", "picture_similarity", "repeats", "select_panels",
]
