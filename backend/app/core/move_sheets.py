# -*- coding: utf-8 -*-
"""招式分解图：同一个人逐格摆出一组招式的参考图，给后面的图像或视频节点当动作参考。

一场打戏先要有看得清的姿态：棍横在哪、剑尖指哪、脚落在哪。这张图把选中的一组招式(棍、剑、刀、枪、徒手、
轻功各八式，群战、追逐、破阵、弓箭、法术、大招各五式)按顺序排成画格，每格一个定住的全身姿态，人物照连进来
的那张图；兵器每格同一个长度和形制，握点看得清，图上不出字。画布工具 ``move_sheet`` 用它(``canvas_tools.image_prompt``)。

招式组、每一招看得见的写法、要守的几条和画格排法都在 ``app/data/prompt/move_sheets.json``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "move_sheets"


class UnknownSet(ValueError):
    """The chosen move set is not in the table."""


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def sets() -> list[dict[str, Any]]:
    return [dict(item) for item in _data()["sets"]]


def default_set() -> str:
    return str(_data()["default"])


def sheet_size() -> str:
    """The picture size sent to the image model (3:4, ``WxH``): saying 「竖版 3:4」 in words alone leaves the model on its default ratio."""
    return str(_data()["size"])


def catalog() -> list[dict[str, Any]]:
    """What a picker shows: ``[{id, label, moves}]`` in the table's order."""
    return [{"id": str(item["id"]), "label": str(item["label"]), "moves": [str(move["name"]) for move in item["moves"]]}
            for item in sets()]


def get(set_id: str) -> dict[str, Any]:
    wanted = str(set_id or "").strip() or default_set()
    for item in sets():
        if item["id"] == wanted:
            return item
    raise UnknownSet(str(_data()["unknown"]).format(wanted))


def prompt(params: Mapping[str, Any] | None, extra: str = "", closing: str = "") -> str:
    """The image request for the set chosen in ``params["set"]``; ``extra`` is what the user added."""
    data = _data()
    chosen = get(str((params or {}).get("set") or ""))
    moves = chosen["moves"]
    listed = str(data["move_separator"]).join(
        str(data["move"]).format(index=index, name=move["name"], how=move["how"]) for index, move in enumerate(moves, start=1))
    words = " ".join(str(extra or "").split())
    return str(data["prompt"]).format(
        holding=chosen["holding"], count=len(moves), layout=data["layouts"][str(len(moves))], moves=listed,
        rules="".join(str(data["rules"][key]) for key in chosen["rules"]),
        extra=str(data["extra"]).format(words.rstrip("。")) if words else "", closing=closing,
    )


__all__ = ["UnknownSet", "catalog", "default_set", "get", "prompt", "sets", "sheet_size"]
