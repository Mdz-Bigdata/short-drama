# -*- coding: utf-8 -*-
"""拍摄场地的四视角：主场景全景、45°斜角、纵深视角、关键细节。

一次出图画一张 16:9 的 2×2 四宫格(省钱，也让四格同一光线、同一陈设)，再切成四张单独的视角：
分割线从画面中线出发吸附到真实的白缝上(与道具四视图同一套分隔判定)。场景铺满整格，不像道具那样
收紧到主体，只去掉白缝本身。四张都是空景底板，主场景全景同时作为场地的主参考图。
"""

from __future__ import annotations

import io

from PIL import Image

from app.core.actor_sheet_cutter import _runs, _SeparatorMap
from app.core.asset_sheets import EMPTY_SCENE_PREFIX, EMPTY_SCENE_SUFFIX

#: (槽位, 中文名, 拍摄时用来做什么)。顺序即前端展示顺序，也是宫格的阅读顺序。
SCENE_VIEWS: tuple[tuple[str, str, str], ...] = (
    ("scene_main", "主场景全景", "整体空间布局与左右关系"),
    ("scene_45", "45°斜角", "走位与转身时的透视"),
    ("scene_depth", "纵深视角", "纵深调度：走廊、门洞与前后景"),
    ("scene_detail", "关键细节", "特写与插入镜头的陈设材质"),
)
SCENE_VIEW_SLOTS: tuple[str, ...] = tuple(slot for slot, _, _ in SCENE_VIEWS)
SCENE_VIEW_LABELS: dict[str, str] = {slot: label for slot, label, _ in SCENE_VIEWS}
SCENE_VIEW_PURPOSES: dict[str, str] = {slot: purpose for slot, _, purpose in SCENE_VIEWS}
#: 四宫格出图尺寸：16:9 横向，每格仍是 16:9；不超过图像模型单张约 462 万像素的上限。
SCENE_TURNAROUND_SIZE = "2848x1600"
# 分割线最多从中线挪开多少(占边长的比例)。
SPLIT_SEARCH = 0.15

SCENE_TURNAROUND_INSTRUCTION = (
    f"{EMPTY_SCENE_PREFIX}"
    "生成一张影视拍摄场地四视角定妆参考图：16:9 横向画布，严格的 2 行 × 2 列四宫格，格与格之间留一条纯白细缝。"
    "四格是同一个空场景：同一时段、同一主光方向与色温、同一陈设位置、同一材质颜色，是可直接拍摄的空景底板；"
    "全场无人，不出现任何人物、人影、剪影、镜面倒影里的人或人体局部。"
    "左上格：主场景全景，主机位平视，交代整体布局与出入口；"
    "右上格：45°斜角，从主机位一侧转 45° 看同一空间，呈现走位与转身时的透视；"
    "左下格：纵深视角，沿空间最长的方向看向深处，交代走廊、门洞与前中后景层次；"
    "右下格：关键细节，近距离拍场景里最有辨识度的陈设或材质。"
    "写清并画准：空间类型与剧情功能；以左上全景格为准的左右布局(画面左侧是什么、右侧是什么、出入口在哪)；"
    "主光从画面哪一侧来、色温与时段；墙、地、主要陈设的颜色与材质；"
    "尺度按真实尺寸——门高约2米、桌面高约0.75米、椅面高约0.45米，四格比例一致。"
)
SCENE_TURNAROUND_CLOSING = (
    "统一要求：四格是同一空间，陈设位置、光向、色温与材质完全一致，45°与纵深两格里能认出全景格中的同一批陈设；"
    "结构清晰，透视正确，材质真实，细节丰富，高清写实电影质感；"
    "严禁任何文字、标签、编号、字幕、水印、Logo；四格里都不出现任何人物。"
    f"{EMPTY_SCENE_SUFFIX}"
)


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
    for slot, box in zip(SCENE_VIEW_SLOTS, quadrants):
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("场景四视角切分得到空白格")
        buffer = io.BytesIO()
        image.crop(box).save(buffer, format="PNG", optimize=True)
        views[slot] = buffer.getvalue()
    return views
