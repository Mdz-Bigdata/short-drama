# -*- coding: utf-8 -*-
"""表演妆造定妆图展示板切成单张：左边四格全身、右边三格特写，各自能点开放大看。

展示板按 ``character_looks`` 的版式出图：左侧约四分之三宽横排四格全身(正面、左侧面、背面、右前方三分之四侧面)，
右侧约四分之一宽竖排三格特写。版式要求格间一条纯白细缝，但模型常只在左右两块之间留缝，四格全身之间
直接拼在一起、只是背景深浅不同。所以先按「这一列/行几乎全是白」找缝(不用平滑度：灰背景也平滑，会把人物两边的
空背景当成缝)，找不到就找背景的明暗台阶(全身格看头顶上方那一条背景，特写看整行)，再找不到才按版式等分。
整板仍是分镜取的参考图，切出来的七张只给人看。
"""

from __future__ import annotations

import io

from PIL import Image

#: (槽位, 中文名)。顺序即展示顺序，也是展示板的阅读顺序。三格特写的名字随版式不同，见 ``closeup_labels``。
LOOK_VIEWS: tuple[tuple[str, str], ...] = (
    ("look_front", "正面全身"),
    ("look_left", "左侧面"),
    ("look_back", "背面"),
    ("look_three_quarter", "三分之四侧面"),
    ("look_closeup_1", "特写一"),
    ("look_closeup_2", "特写二"),
    ("look_closeup_3", "特写三"),
)
LOOK_VIEW_SLOTS: tuple[str, ...] = tuple(slot for slot, _ in LOOK_VIEWS)
#: 版式：有妆效的展示板第二格特写拍妆效所在的部位；较早的、没有妆效的拍腰带和袖口。
LAYOUT_MAKEUP = "makeup"
LAYOUT_PLAIN = "plain"
CLOSEUP_LABELS = {
    LAYOUT_MAKEUP: ("正脸胸像", "妆效部位", "腰带与配饰"),
    LAYOUT_PLAIN: ("正脸胸像", "腰带与配饰", "袖口或下摆"),
}

# 一列(行)里至少这么多像素是白的才算白缝；白的门槛是灰度值。
WHITE_LEVEL = 236
WHITE_SHARE = 0.94
# 左右两块的分界在宽度的这个位置附近找；四格之间、三格之间的缝在等分点附近找。
SPLIT_AT = 0.75
SPLIT_SEARCH = 0.12
CELL_SEARCH = 0.35
# 切出来的格子窄于(矮于)期望大小的这个比例，就当切错了。
MIN_CELL_SHARE = 0.4
# 明暗台阶：隔着 STEP_GAP 个像素的两条线平均灰度差到这个数，才算两格的分界。
STEP_GAP = 3
STEP_LEVEL = 18
# 全身格看头顶上方的背景：这一条是高度的这个范围(脚下有影子，不看)。
HEAD_BAND = (0.01, 0.04)


def closeup_labels(layout: str) -> tuple[str, str, str]:
    return CLOSEUP_LABELS.get(layout, CLOSEUP_LABELS[LAYOUT_PLAIN])


def _white_lines(gray: Image.Image, box: tuple[int, int, int, int], axis: str) -> list[bool]:
    """``box`` 里每一列(``axis == "x"``)或每一行是不是几乎全白。"""
    left, top, right, bottom = box
    region = gray.crop(box).point(lambda value: 255 if value >= WHITE_LEVEL else 0)
    size = (right - left, 1) if axis == "x" else (1, bottom - top)
    shares = region.resize(size, Image.Resampling.BOX).tobytes()
    return [share >= 255 * WHITE_SHARE for share in shares]


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """连续为真的区间 [起, 止)。"""
    runs, start = [], None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _content_span(flags: list[bool]) -> tuple[int, int]:
    """去掉两头的白边之后的范围；整条都白时原样返回。"""
    if all(flags):
        return 0, len(flags)
    start = flags.index(False)
    end = len(flags) - flags[::-1].index(False)
    return start, end


def _seam_near(runs: list[tuple[int, int]], target: float, radius: float) -> tuple[int, int] | None:
    near = [run for run in runs if abs((run[0] + run[1]) / 2 - target) <= radius]
    return min(near, key=lambda run: abs((run[0] + run[1]) / 2 - target)) if near else None


def _steps(gray: Image.Image, box: tuple[int, int, int, int], axis: str) -> list[float]:
    """``box`` 里每一列(``axis == "x"``)或每一行和它隔 ``STEP_GAP`` 的那条线的平均灰度差。"""
    left, top, right, bottom = box
    size = (right - left, 1) if axis == "x" else (1, bottom - top)
    means = list(gray.crop(box).resize(size, Image.Resampling.BOX).tobytes())
    return [
        abs(means[index + STEP_GAP] - means[index - STEP_GAP]) if STEP_GAP <= index < len(means) - STEP_GAP else 0.0
        for index in range(len(means))
    ]


def _step_near(steps: list[float], target: float, radius: float) -> int | None:
    low, high = max(0, round(target - radius)), min(len(steps), round(target + radius) + 1)
    best = max(range(low, high), key=lambda index: steps[index], default=None)
    return best if best is not None and steps[best] >= STEP_LEVEL else None


def _cuts(flags: list[bool], start: int, end: int, parts: int, steps: list[float] | None = None) -> list[tuple[int, int]]:
    """把 [start, end) 切成 ``parts`` 段：分界吸附到附近的白缝上，没有白缝就吸附到明暗台阶上，都没有就等分。"""
    length = end - start
    runs = [(low, high) for low, high in _runs(flags[start:end]) if low > 0 and high < length]
    local = steps[start:end] if steps else []
    edges: list[tuple[int, int]] = []
    for index in range(1, parts):
        target = length * index / parts
        radius = length / parts * CELL_SEARCH
        seam = _seam_near(runs, target, radius)
        step = None if seam or not local else _step_near(local, target, radius)
        edges.append(seam if seam else (step, step) if step is not None else (round(target), round(target)))
    bounds, cursor = [], 0
    for low, high in edges:
        bounds.append((start + cursor, start + low))
        cursor = high
    bounds.append((start + cursor, end))
    if any(high - low < length / parts * MIN_CELL_SHARE for low, high in bounds):
        raise ValueError("定妆图展示板切分得到过窄的格子")
    return bounds


def split_look_board(content: bytes) -> dict[str, bytes]:
    """把一张展示板切成 {槽位: PNG 字节}：四格全身，再三格特写。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    gray = image.convert("L")
    width, height = image.size
    columns = _white_lines(gray, (0, 0, width, height), "x")
    left_edge, right_edge = _content_span(columns)
    span = right_edge - left_edge
    inner = [(low, high) for low, high in _runs(columns) if low > left_edge and high < right_edge]
    middle = _seam_near(inner, left_edge + span * SPLIT_AT, span * SPLIT_SEARCH)
    split_low, split_high = middle if middle else (round(left_edge + span * SPLIT_AT),) * 2

    def rows_of(left: int, right: int) -> tuple[list[bool], int, int]:
        flags = _white_lines(gray, (left, 0, right, height), "y")
        top, bottom = _content_span(flags)
        return flags, top, bottom

    _flags, body_top, body_bottom = rows_of(left_edge, split_low)
    band = (0, body_top + round((body_bottom - body_top) * HEAD_BAND[0]), width, body_top + max(2, round((body_bottom - body_top) * HEAD_BAND[1])))
    bodies = _cuts(columns, left_edge, split_low, 4, _steps(gray, band, "x"))
    close_flags, close_top, close_bottom = rows_of(split_high, right_edge)
    closeups = _cuts(close_flags, close_top, close_bottom, 3, _steps(gray, (split_high, 0, right_edge, height), "y"))
    boxes = [(low, body_top, high, body_bottom) for low, high in bodies]
    boxes += [(split_high, low, right_edge, high) for low, high in closeups]
    views: dict[str, bytes] = {}
    for slot, box in zip(LOOK_VIEW_SLOTS, boxes):
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("定妆图展示板切分得到空白格")
        buffer = io.BytesIO()
        image.crop(box).save(buffer, format="PNG", optimize=True)
        views[slot] = buffer.getvalue()
    return views


__all__ = [
    "CLOSEUP_LABELS", "LAYOUT_MAKEUP", "LAYOUT_PLAIN", "LOOK_VIEWS", "LOOK_VIEW_SLOTS", "closeup_labels", "split_look_board",
]
