# -*- coding: utf-8 -*-
"""首镜试拍：整批生成之前先只拍一段，看对了再放开其余的。

一段走样时，变量越少越容易看出是图的问题还是词的问题，所以默认挑人最少、动作最少的一段；
整批翻车重出的钱，远比先验证一段贵。试拍出的片段记在阶段 5 的片段里，内容不改的话整批生成时
原样复用，不花第二次钱。

记录在 ``assets["5_pilot"]``。只要它在，阶段 5 就不算完成(后面的阶段不会只拿一段往下做)，
整批跑成功后删掉。一键成片不走这里：它看到阶段 5 没完成，会直接跑整批。

本模块只做判断和记录，不调模型。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.core.episode_cycle import covered_uids
from app.core.storyboard_scene_context import EMPTY_ACTOR

ASSET_KEY = "5_pilot"
REQUESTED, RUNNING, READY, FAILED = "requested", "running", "ready", "failed"
#: 人工判废看的五项；选中的写进生成反馈，同一模型反复栽在同一处时后面的提示词会绕开。
CHECKS = ("脸", "服装", "人数", "动作", "口型")
_CHECK_WORDS = {
    "脸": "脸和定妆照不一样，变脸了", "服装": "服装和设定不一致", "人数": "画面里的人数不对，多了或少了人",
    "动作": "动作没按描述演", "口型": "口型和台词对不上",
}
_NOBODY = {EMPTY_ACTOR, "无", "无人", "无人物", "空镜"}
_INTERRUPTED = "试拍没有跑完，可以再试一次"


def problem_text(problems: Iterable[str]) -> str:
    """把勾选的判废项写成生成反馈能归类的话；不认识的项不写。"""
    return "首镜试拍不通过：" + "；".join(_CHECK_WORDS[item] for item in problems if item in _CHECK_WORDS)


def requested(shot_uid: int | None = None, reason: str = "") -> dict[str, Any]:
    """``reason`` 是重拍时沿用的上次理由：重拍不是人换了一镜。"""
    return {"state": REQUESTED, "wanted_uid": shot_uid, "reason": reason}


def is_requested(assets: Mapping[str, Any]) -> bool:
    record = assets.get(ASSET_KEY)
    return isinstance(record, Mapping) and record.get("state") == REQUESTED


def holds_batch(assets: Mapping[str, Any]) -> bool:
    """试拍过、还没跑整批：片段不全，阶段 5 不能算完成。"""
    return isinstance(assets.get(ASSET_KEY), Mapping)


def _uids(req: Mapping[str, Any]) -> list[int]:
    beats = (req.get("slice") or {}).get("beats") or []
    return [int(beat["shot_uid"]) for beat in beats if beat.get("shot_uid")] or [int(req["shot_uid"])]


def _cast(req: Mapping[str, Any]) -> list[str]:
    beats = (req.get("slice") or {}).get("beats") or []
    names = [name for beat in beats for name in beat.get("characters") or []] or list(req["contract"].characters)
    return [name for name in dict.fromkeys(names) if name and name not in _NOBODY]


def _actions(req: Mapping[str, Any]) -> int:
    beats = (req.get("slice") or {}).get("beats") or []
    descriptions = [str(beat.get("desc") or "") for beat in beats] or [str(req.get("desc") or "")]
    return sum(1 + text.count("；随后") for text in descriptions)


def _rank(number: int, req: Mapping[str, Any]) -> tuple[int, int, int]:
    people = len(_cast(req))
    # 一个人最好：脸和动作都测得到。空镜排最后，它什么也验证不了。
    return (3 if people == 0 else min(people - 1, 2), _actions(req), number)


def _root(requests: Mapping[int, Mapping[str, Any]], number: int) -> int:
    """接力段要先有前一段的末帧才能开拍，试拍就从这串的第一段开始。"""
    while requests[number].get("chain_from") in requests:
        number = requests[number]["chain_from"]
    return number


def pick(requests: Mapping[int, Mapping[str, Any]], wanted_uid: int | None = None) -> tuple[int, str]:
    """挑要试拍的一段，返回它的编号和给人看的理由。"""
    if wanted_uid:
        chosen = next((number for number, req in requests.items() if int(wanted_uid) in _uids(req)), None)
        if chosen is not None:
            return _root(requests, chosen), "你选的这一镜"
    unchained = {number: req for number, req in requests.items() if not req.get("chain_from")} or dict(requests)
    chosen = min(unchained, key=lambda number: _rank(number, unchained[number]))
    req = unchained[chosen]
    people, actions = len(_cast(req)), _actions(req)
    return chosen, f"这段{f'{people} 个人' if people else '没有人物'}、{actions} 个动作，变量最少，走样时最容易看出问题"


def running(req: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "state": RUNNING, "shot_id": req["shot_id"], "shot_uid": int(req["shot_uid"]), "shot_uids": _uids(req),
        "scene_id": str((req.get("slice") or {}).get("scene_id") or (req.get("shot") or {}).get("scene_id") or ""),
        "label": str((req.get("slice") or {}).get("label") or f"镜头 {req['shot_id']}"), "reason": reason,
    }


def finished(record: Mapping[str, Any]) -> dict[str, Any]:
    return {**record, "state": READY, "error": ""}


def failed(record: Mapping[str, Any] | None, message: str) -> dict[str, Any]:
    return {**(record or {}), "state": FAILED, "error": str(message or _INTERRUPTED)[:400]}


def view(assets: Mapping[str, Any], *, running_now: bool, others_left: int = 0) -> dict[str, Any] | None:
    """工作区要显示的试拍状态；阶段已经不在跑、记录还停在进行中，就是中途断了。"""
    record = assets.get(ASSET_KEY)
    if not isinstance(record, Mapping):
        return None
    shown = dict(record)
    if shown.get("state") in (REQUESTED, RUNNING) and not running_now:
        shown = failed(shown, _INTERRUPTED)
    if shown.get("state") == READY:
        uids = set(shown.get("shot_uids") or [])
        clip = next((
            item for item in assets.get("5") or []
            if isinstance(item, Mapping) and item.get("video_url") and uids & set(covered_uids(item))
        ), None)
        shown["video_url"] = str(clip["video_url"]) if clip else ""
    shown["others_left"] = others_left
    shown["checks"] = list(CHECKS)
    return shown


__all__ = [
    "ASSET_KEY", "CHECKS", "FAILED", "READY", "REQUESTED", "RUNNING", "failed", "finished", "holds_batch", "is_requested", "pick",
    "problem_text", "requested", "running", "view",
]
