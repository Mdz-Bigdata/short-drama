# -*- coding: utf-8 -*-
"""拍摄场地的四视角：主场景全景、45°斜角、纵深视角、关键细节。

一次出图画一张 16:9 的 2×2 四宫格(省钱，也让四格同一光线、同一陈设)，再切成四张单独的视角：
分割线从画面中线出发吸附到真实的白缝上(与道具四视图同一套分隔判定)。场景铺满整格，不像道具那样
收紧到主体，只去掉白缝本身。四张都是空景底板，主场景全景同时作为场地的主参考图。

反打视角不在四宫格里：它以切好的主场景全景为参考另出一张单图，从全景画面的深处拍回主机位一侧，
正反打的反打镜头照它定背景(措辞在 data/prompt/scene_views.json)。
"""

from __future__ import annotations

import io

from PIL import Image

from app.core import prompt_data
from app.core.actor_sheet_cutter import _runs, _SeparatorMap
from app.core.asset_sheets import EMPTY_SCENE_PREFIX, EMPTY_SCENE_SUFFIX

# 视角的中文名与用途、四宫格出图说明和报错：app/data/prompt/scene_turnaround.json。
_WORDING = "scene_turnaround"


def _says(key: str, /, **values: object) -> str:
    """场地四视角措辞表里的一句，填好值(长句在表里按行存，直接相连)。"""
    body = prompt_data.load(_WORDING)["says"][key]
    return ("".join(body) if isinstance(body, list) else str(body)).format(**values)


#: 槽位的顺序即前端展示顺序，也是宫格的阅读顺序；与 elementTypes 的场地槽位一致。
_SLOTS: tuple[str, ...] = ("scene_main", "scene_45", "scene_depth", "scene_detail", "scene_reverse")
_VIEW_WORDS: dict[str, list[str]] = prompt_data.value(_WORDING, "views")
#: (槽位, 中文名, 拍摄时用来做什么)。
SCENE_VIEWS: tuple[tuple[str, str, str], ...] = tuple(
    (slot, str(_VIEW_WORDS[slot][0]), str(_VIEW_WORDS[slot][1])) for slot in _SLOTS
)
SCENE_VIEW_SLOTS: tuple[str, ...] = tuple(slot for slot, _, _ in SCENE_VIEWS)
#: 四宫格切出来的四张；反打视角另出一张。
SCENE_GRID_SLOTS: tuple[str, ...] = SCENE_VIEW_SLOTS[:4]
SCENE_REVERSE_SLOT = "scene_reverse"
SCENE_VIEW_LABELS: dict[str, str] = {slot: label for slot, label, _ in SCENE_VIEWS}
SCENE_VIEW_PURPOSES: dict[str, str] = {slot: purpose for slot, _, purpose in SCENE_VIEWS}
#: 四宫格出图尺寸：16:9 横向，每格仍是 16:9；不超过图像模型单张约 462 万像素的上限。
SCENE_TURNAROUND_SIZE = "2848x1600"
# 分割线最多从中线挪开多少(占边长的比例)。
SPLIT_SEARCH = 0.15

SCENE_TURNAROUND_INSTRUCTION = _says("instruction", prefix=EMPTY_SCENE_PREFIX)
SCENE_TURNAROUND_CLOSING = _says("closing", suffix=EMPTY_SCENE_SUFFIX)


def _seam(separators: list[bool], length: int) -> tuple[int, int]:
    """中线附近那条白缝的起止；找不到就在中线上一刀切开。"""
    middle = length // 2
    radius = round(length * SPLIT_SEARCH)
    runs = [
        (low, high) for low, high in _runs(separators, interior_only=True)
        if abs((low + high) / 2 - middle) <= radius
    ]
    if not runs:
        return middle, middle
    return min(runs, key=lambda run: abs((run[0] + run[1]) / 2 - middle))


def split_scene_turnaround(content: bytes) -> dict[str, bytes]:
    """把 2×2 四视角切成 {槽位: PNG 字节}，顺序为全景、45°、纵深、细节。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    seps = _SeparatorMap(image)
    width, height = image.size
    left, right = _seam(seps.separators((0, 0, width, height), "x"), width)
    top, bottom = _seam(seps.separators((0, 0, width, height), "y"), height)
    quadrants = (
        (0, 0, left, top), (right, 0, width, top),
        (0, bottom, left, height), (right, bottom, width, height),
    )
    views: dict[str, bytes] = {}
    for slot, box in zip(SCENE_GRID_SLOTS, quadrants):
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError(_says("empty_quadrant"))
        buffer = io.BytesIO()
        image.crop(box).save(buffer, format="PNG", optimize=True)
        views[slot] = buffer.getvalue()
    return views
