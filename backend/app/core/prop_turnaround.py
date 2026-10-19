# -*- coding: utf-8 -*-
"""拍摄道具的四视图：正面、左侧 45°、右侧 45°、背面。

一次出图画一张 1:1 的 2×2 四宫格(省钱，也让四张同一光线、同一比例)，再切成四张单独的视图：
分割线从画面中线出发吸附到真实的白缝上(复用设定集切图器的平滑分隔判定)，每格收紧到道具本身、
四周留一点余量。每张视图存进道具元素自己的槽位，正面同时作为道具的主参考图。
"""

from __future__ import annotations

import io

from PIL import Image

from app.core.actor_sheet_cutter import _runs, _SeparatorMap

#: (槽位, 中文名, 角度)。顺序即前端展示顺序。
PROP_VIEWS: tuple[tuple[str, str, int], ...] = (
    ("prop_front", "正面", 0),
    ("prop_left_45", "左侧45°", 45),
    ("prop_right_45", "右侧45°", 45),
    ("prop_back", "背面", 180),
)
PROP_VIEW_SLOTS: tuple[str, ...] = tuple(slot for slot, _, _ in PROP_VIEWS)
#: 四宫格出图尺寸：1:1 方形，每格约 1024px。
PROP_TURNAROUND_SIZE = "2048x2048"
# 分割线最多从中线挪开多少(占边长的比例)；收紧后四周留多少余量(占格子边长的比例)。
SPLIT_SEARCH = 0.15
VIEW_MARGIN = 0.06

PROP_TURNAROUND_INSTRUCTION = (
    "生成一张影视道具四视图定妆参考图：1:1 方形画布，严格的 2 行 × 2 列四宫格，格与格之间留一条纯白细缝。"
    "四格是同一件道具、同一比例、同一材质颜色与磨损、同一剧本状态，同一中性柔光，纯白或浅灰简洁背景，"
    "道具在每格居中、完整、不裁断，不出现手和人物。"
    "左上格：正面；右上格：左侧 45°(道具向画面左侧转动 45°)；左下格：右侧 45°(向画面右侧转动 45°)；右下格：背面。"
    "清楚呈现比例、轮廓、材质、颜色、磨损和关键结构。"
)
PROP_TURNAROUND_CLOSING = (
    "统一要求：每格道具完整位于格内安全区，结构清晰，透视正确，材质真实，细节丰富，高清写实电影质感；"
    "严禁任何文字、标签、编号、字幕、水印、Logo、边框；四格之外不出现第五个道具，格内不出现第二个道具。"
)


def _split(separators: list[bool], start: int, length: int) -> int:
    """在中线附近找一段平滑分隔，取离中线最近那段的中点；找不到就用中线。"""
    middle = length // 2
    radius = round(length * SPLIT_SEARCH)
    runs = [
        (low, high) for low, high in _runs(separators, interior_only=True)
        if abs((low + high) / 2 - middle) <= radius
    ]
    if not runs:
        return start + middle
    low, high = min(runs, key=lambda run: abs((run[0] + run[1]) / 2 - middle))
    return start + (low + high) // 2


def split_prop_turnaround(content: bytes) -> dict[str, bytes]:
    """把 2×2 四视图切成 {槽位: PNG 字节}，顺序为正面、左 45°、右 45°、背面。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    seps = _SeparatorMap(image)
    width, height = image.size
    column = _split(seps.separators((0, 0, width, height), "x"), 0, width)
    row = _split(seps.separators((0, 0, width, height), "y"), 0, height)
    quadrants = (
        (0, 0, column, row), (column, 0, width, row),
        (0, row, column, height), (column, row, width, height),
    )
    views: dict[str, bytes] = {}
    for slot, box in zip(PROP_VIEW_SLOTS, quadrants):
        tight = seps.trim(box) or box
        margin_x = round((box[2] - box[0]) * VIEW_MARGIN)
        margin_y = round((box[3] - box[1]) * VIEW_MARGIN)
        padded = (
            max(box[0], tight[0] - margin_x), max(box[1], tight[1] - margin_y),
            min(box[2], tight[2] + margin_x), min(box[3], tight[3] + margin_y),
        )
        buffer = io.BytesIO()
        image.crop(padded).save(buffer, format="PNG", optimize=True)
        views[slot] = buffer.getvalue()
    return views
