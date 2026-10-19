# -*- coding: utf-8 -*-
"""在真实出图上找到设定集每一格的面板，并认出它是哪一格。

图像模型画设定集时既不守比例也不守网格：栏宽从 1/4 到 1/2 都有，三视图有时三个面板、
有时挤在一个面板里，细节矩阵有 2 列也有 3 列、还有跨两行的大格；背景可能是纯白，
也可能是灰底配白色分隔线。按固定比例或固定网格裁，切出来的格子会带上标题字、切掉半张脸。

这里只依赖 Pillow，分三步：

1. **切面板**：一行/一列沿线几乎没有灰度跳变，就是一条分隔——白缝、白色分隔线、灰底留白、
   由灰到白的渐变底都是这样；穿过人物或物件的线一定会碰上一串边缘。
   乌黑头发、深色衣料也平滑，所以分隔还必须是亮的。在每一栏里沿这些分隔递归横竖切
   (XY-cut)，叶子就是一块块面板，收紧到内容外框后四周留一点余量。
2. **去标题**：每栏顶部那条又矮又靠上的叶子是标题字，丢弃。
3. **认格子**：左栏标题以下的全部面板合起来是主肖像；中栏够高的面板里认出全身立绘和三视图
   (没画单独立绘时正面视图兼任，三视图挤在一个面板里时按宽度均分)，剩下的按阅读顺序是元素拆解；右栏里阅读顺序上
   头三块"像脸"(既有成片肤色又有深色头发)的面板是正脸 / 左侧45° / 右侧45°，剩下的按阅读顺序是细节矩阵。

模型没画的格子不硬凑：元素和细节只返回真的找到的那些。七个身份必需格
(``REQUIRED_CELLS``)找不到面板时退回版面比例给出的预期框，保证下游锚点永远齐全。
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageChops

from app.core.actor_sheet_layout import (
    ACTOR_SHEET_LAYOUT,
    REQUIRED_CELLS,
    ActorSheetLayout,
    actor_sheet_cell_boxes,
)

Box = tuple[int, int, int, int]

# 沿着一条线相隔 JUMP_STEP 像素的两点灰度差超过 JUMP_LEVEL，算一次"跳变"(碰到了画面内容的
# 边缘)。高分辨率出图的边缘会糊开好几个像素，只比相邻像素会把人脸也当成平滑区域。
JUMP_STEP = 6
JUMP_LEVEL = 14
# 一行/一列里跳变像素占比不超过这个值，就是一条分隔。分隔可能是白缝、白色分隔线、
# 灰底留白，也可能是从上到下由灰变白的渐变底(实测 188→244)——它们的共同点不是颜色，
# 而是沿线平滑；任何穿过人物或物件的线都会碰上一串边缘。
SEPARATOR_JUMPS = 0.02
# 分隔还必须是亮的：乌黑的头发、深色衣料同样平滑，竖线穿过它们不是分隔。
# 一条线上灰度低于 DARK_LEVEL 的像素超过 SEPARATOR_DARK 就不算分隔(实测分隔最暗约 149)。
DARK_LEVEL = 120
SEPARATOR_DARK = 0.02
# 收紧到内容后四周留的余量(占画布宽度的比例)，让人物不贴边。
TRIM_MARGIN = 0.004
# 递归深度上限，防止病态图片无限细分。
MAX_DEPTH = 14
# 面板最小尺寸(占画布宽/高的比例)：更小的叶子是标题字、细线或噪点。
MIN_PANEL_WIDTH = 0.02
MIN_PANEL_HEIGHT = 0.04
# 标题叶子：顶边落在画布上部这个比例以内、且高度不超过这个比例。
TITLE_ZONE = 0.16
# 栏界离任何一块标题字至少这么远(占画布宽度)；标题字叶子的高度上限(占画布高度)。
TITLE_TEXT_REACH = 0.015
TITLE_TEXT_MAX_HEIGHT = 0.10
# 标题字叶子的高度下限：贯穿全宽的细横线只有几像素高，不是字。
TITLE_TEXT_MIN_HEIGHT = 0.01
# 三栏分界只在预期位置附近这个范围(占画布宽度)里找。
COLUMN_SEARCH = 0.15
# 中栏里高度达到栏内容高度这个比例的面板，才可能是全身三视图。
VIEW_MIN_HEIGHT = 0.3
# 全身立绘与三视图的最小宽度(占画布宽度)：更窄的竖条是相邻栏没切干净的边。
MIN_VIEW_WIDTH = 0.035
# "像脸"的面板：成片肤色和深色(头发)的占比都落在各自区间里(在五张真实设定集上实测)。
# 肤色判定用 YCbCr 的 Cb / Cr 区间(经典肤色检测范围，Cr 下限抬到 135 以排除偏暖的白布)。
SKIN_CB = (77, 127)
SKIN_CR = (135, 173)
FACE_MIN_SKIN = 0.03
FACE_MAX_SKIN = 0.65
FACE_MIN_DARK = 0.08
FACE_MAX_DARK = 0.55


def _jumps(gray: Image.Image, axis: str) -> Image.Image:
    """沿 ``axis`` 方向相隔 JUMP_STEP 像素灰度差超过 JUMP_LEVEL 的位置(255)，尺寸与原图相同。"""
    width, height = gray.size
    step = JUMP_STEP
    if axis == "y":
        before, after = gray.crop((0, 0, width, height - step)), gray.crop((0, step, width, height))
    else:
        before, after = gray.crop((0, 0, width - step, height)), gray.crop((step, 0, width, height))
    jumps = ImageChops.difference(before, after).point(lambda value: 255 if value > JUMP_LEVEL else 0)
    canvas = Image.new("L", (width, height), 0)
    canvas.paste(jumps, (0, 0))
    return canvas


class _SeparatorMap:
    """一张设定集的"沿线跳变"蒙版，以及在它上面找分隔、切面板的工具。

    列方向的分隔看纵向跳变，行方向的分隔看横向跳变：一列从上到下都平滑，就能从这里竖着切开。
    """

    def __init__(self, image: Image.Image) -> None:
        gray = image.convert("L")
        self.vertical = _jumps(gray, "y")
        self.horizontal = _jumps(gray, "x")
        self.dark = gray.point(lambda value: 255 if value < DARK_LEVEL else 0)
        self.width, self.height = gray.size
        self.margin = max(2, round(self.width * TRIM_MARGIN))

    def separators(self, box: Box, axis: str) -> list[bool]:
        """每一列(``axis == "x"``)或每一行是否是分隔：沿线平滑且不暗。"""
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            return []
        if axis == "x":
            size, jumps = (right - left, 1), self.vertical
        else:
            size, jumps = (1, bottom - top), self.horizontal
        jump_share = jumps.crop(box).resize(size, Image.Resampling.BOX).tobytes()
        dark_share = self.dark.crop(box).resize(size, Image.Resampling.BOX).tobytes()
        return [
            jump <= 255 * SEPARATOR_JUMPS and dark <= 255 * SEPARATOR_DARK
            for jump, dark in zip(jump_share, dark_share)
        ]

    def trim(self, box: Box) -> Box | None:
        """去掉四周平滑的留白；整块都没有内容返回 ``None``。"""
        left, top, right, bottom = box
        columns = self.separators(box, "x")
        rows = self.separators(box, "y")
        if all(columns) or all(rows):
            return None
        x0 = columns.index(False)
        x1 = len(columns) - columns[::-1].index(False)
        y0 = rows.index(False)
        y1 = len(rows) - rows[::-1].index(False)
        return (left + x0, top + y0, left + x1, top + y1)

    def padded(self, box: Box, limit: Box) -> Box:
        """收紧后的框四周放出一点余量，但不超出原来那块区域。"""
        return (
            max(limit[0], box[0] - self.margin), max(limit[1], box[1] - self.margin),
            min(limit[2], box[2] + self.margin), min(limit[3], box[3] + self.margin),
        )

    def panels(self, box: Box, depth: int = 0) -> list[Box]:
        """沿平滑分隔递归切开一块区域，返回所有叶子面板。"""
        trimmed = self.trim(box)
        if trimmed is None:
            return []
        if depth >= MAX_DEPTH:
            return [self.padded(trimmed, box)]
        best: tuple[int, str, list[tuple[int, int]]] | None = None
        for axis in ("y", "x"):
            gaps = _runs(self.separators(trimmed, axis))
            if gaps:
                widest = max(end - start for start, end in gaps)
                if best is None or widest > best[0]:
                    best = (widest, axis, gaps)
        if best is None:
            return [self.padded(trimmed, box)]
        _, axis, gaps = best
        left, top, right, bottom = trimmed
        length = (bottom - top) if axis == "y" else (right - left)
        edges = [0] + [edge for gap in gaps for edge in gap] + [length]
        found: list[Box] = []
        for start, end in zip(edges[::2], edges[1::2]):
            if end <= start:
                continue
            piece = (left, top + start, right, top + end) if axis == "y" else (left + start, top, left + end, bottom)
            found.extend(self.panels(piece, depth + 1))
        return found

    def title_spans(self) -> list[tuple[int, int]]:
        """标题字所在的横向区间：整张图切面板后，顶部附近又矮的那些叶子。

        真面板都很高，不会被算进来；栏顶的英文/中文标题、单词与单词各成一块小叶子。
        """
        leaves = self.panels((0, 0, self.width, self.height))
        tall_tops = [
            box[1] for box in leaves
            if _height(box) >= self.height * VIEW_MIN_HEIGHT and box[2] - box[0] >= self.width * MIN_PANEL_WIDTH
        ]
        if not tall_tops:
            return []
        # 标题字整块在最高面板的顶边之上；面板里的小碎块(发饰、火花)和贯穿全高的细分隔线都不算面板。
        ceiling = min(tall_tops) + self.margin
        return [
            (box[0], box[2])
            for box in leaves
            if box[3] <= ceiling
            and self.height * TITLE_TEXT_MIN_HEIGHT <= _height(box) <= self.height * TITLE_TEXT_MAX_HEIGHT
        ]

    def column_split(self, expected: int, top: int, title_spans: Sequence[tuple[int, int]] = ()) -> int:
        """在预期位置附近找一条贯穿全高的竖向分隔，取离预期最近那条的中线。

        标题字居中在各自栏内，栏界不会穿过标题；中栏内部的竖缝(如立绘与三视图之间)却常在中栏
        标题正下方。所以离任何一块标题字不到 TITLE_TEXT_REACH 的分隔不算栏界——
        否则栏宽画得和版面比例不一样时，最近的那条缝会是中栏内部的缝。
        """
        radius = round(self.width * COLUMN_SEARCH)
        low, high = max(1, expected - radius), min(self.width - 1, expected + radius)
        flags = self.separators((low, top, high, self.height), "x")
        reach = round(self.width * TITLE_TEXT_REACH)
        for left, right in title_spans:
            for position in range(max(low, left - reach), min(high, right + reach)):
                flags[position - low] = False
        runs = _runs(flags, interior_only=False)
        if not runs:
            return expected
        start, end = min(runs, key=lambda run: abs(low + (run[0] + run[1]) / 2 - expected))
        return low + (start + end) // 2


def _runs(flags: list[bool], *, interior_only: bool = True) -> list[tuple[int, int]]:
    """连续为真的区间；``interior_only`` 时去掉贴着两端的(那是外边距，不是分隔)。"""
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(flags):
        if not flags[index]:
            index += 1
            continue
        end = index
        while end < len(flags) and flags[end]:
            end += 1
        if not interior_only or (index > 0 and end < len(flags)):
            runs.append((index, end))
        index = end
    return runs


def _height(box: Box) -> int:
    return box[3] - box[1]


def _reading_order(boxes: list[Box]) -> list[Box]:
    """先按行(顶边相近的归为一行，跨两行的大格算在它开始的那一行)、行内再从左到右。"""
    if not boxes:
        return []
    heights = sorted(_height(box) for box in boxes)
    tolerance = heights[len(heights) // 2] / 2
    rows: list[list[Box]] = []
    for box in sorted(boxes, key=lambda item: item[1]):
        if rows and abs(box[1] - min(b[1] for b in rows[-1])) <= tolerance:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [box for row in rows for box in sorted(row, key=lambda item: item[0])]


def _split_evenly(box: Box, parts: int) -> list[Box]:
    left, top, right, bottom = box
    edges = [left + round((right - left) * index / parts) for index in range(parts + 1)]
    return [(edges[index], top, edges[index + 1], bottom) for index in range(parts)]


def _full_body_and_views(tall: list[Box]) -> tuple[Box | None, list[Box]]:
    """从中栏够高的面板(按 x 排好)里认出全身立绘和三张全身视图。

    - 四块以上：最左一块是全身立绘，接下来三块是正面/侧面/背面；
    - 三块且高度相近：模型没画单独的立绘，三块就是三视图，正面视图兼作全身立绘；
    - 三块但最左一块明显更高：它是立绘，另两块里最宽的那块按宽度均分补成三视图；
    - 两块：一块立绘，另一块是挤在一起的三视图，按宽度均分成三张；
    - 一块：竖长的当立绘(三视图缺失)，横宽的是三视图合板，均分后正面兼作立绘。
    """
    if not tall:
        return None, []
    if len(tall) >= 4:
        return tall[0], tall[1:4]
    if len(tall) == 3:
        heights = [_height(box) for box in tall]
        if max(heights) <= 1.15 * min(heights):
            return tall[0], list(tall)
        return tall[0], _fill_views(tall[1:])
    if len(tall) == 2:
        return tall[0], _fill_views(tall[1:])
    only = tall[0]
    if only[2] - only[0] > 0.8 * _height(only):
        views = _split_evenly(only, 3)
        return views[0], views
    return only, []


def _fill_views(views: list[Box]) -> list[Box]:
    """三视图挤在一两个面板里：把最宽的那块按宽度均分，直到凑够三张。"""
    views = sorted(views, key=lambda box: box[0])
    while views and len(views) < 3:
        widest = max(views, key=lambda box: box[2] - box[0])
        parts = 3 - len(views) + 1
        views.remove(widest)
        views.extend(_split_evenly(widest, parts))
        views.sort(key=lambda box: box[0])
    return views


def _merge_to_fit(boxes: list[Box], capacity: int) -> list[Box]:
    """面板比格子多时(比如一双护腕被白底切成两块)，把同一行里挨得最近的两块并成一块。"""
    boxes = list(boxes)
    while len(boxes) > capacity:
        best: tuple[int, int, int] | None = None
        for i, first in enumerate(boxes):
            for j, second in enumerate(boxes):
                if i == j or first[0] > second[0]:
                    continue
                overlap = min(first[3], second[3]) - max(first[1], second[1])
                if overlap < 0.5 * min(_height(first), _height(second)):
                    continue
                gap = second[0] - first[2]
                if gap >= 0 and (best is None or gap < best[0]):
                    best = (gap, i, j)
        if best is None:
            break
        _, i, j = best
        merged = (
            min(boxes[i][0], boxes[j][0]), min(boxes[i][1], boxes[j][1]),
            max(boxes[i][2], boxes[j][2]), max(boxes[i][3], boxes[j][3]),
        )
        boxes = [box for index, box in enumerate(boxes) if index not in (i, j)] + [merged]
        boxes = _reading_order(boxes)
    return boxes[:capacity]


def _face_measures(image: Image.Image, box: Box) -> tuple[float, float]:
    """(成片肤色占比, 深色占比)。成片肤色 = 上下左右四邻也都是肤色的肤色像素。

    只数成片的，是为了把暗底上的橙色火花、零星光斑排除在外——它们颜色像皮肤，却不成片。
    """
    side = 48
    thumb = image.crop(box).convert("RGB").resize((side, side), Image.Resampling.BOX)
    rgb = thumb.tobytes()
    ycc = thumb.convert("YCbCr").tobytes()
    skin = [False] * (side * side)
    dark = 0
    for index in range(side * side):
        luma, blue_diff, red_diff = ycc[index * 3], ycc[index * 3 + 1], ycc[index * 3 + 2]
        # YCbCr 肤色区间：白皙到深肤色都落在里面，白色布料、灰底(Cr≈128)落在外面。
        skin[index] = luma > 60 and SKIN_CB[0] <= blue_diff <= SKIN_CB[1] and SKIN_CR[0] <= red_diff <= SKIN_CR[1]
        dark += max(rgb[index * 3], rgb[index * 3 + 1], rgb[index * 3 + 2]) < 60
    solid = sum(
        1
        for y in range(1, side - 1)
        for x in range(1, side - 1)
        if skin[y * side + x] and skin[(y - 1) * side + x] and skin[(y + 1) * side + x]
        and skin[y * side + x - 1] and skin[y * side + x + 1]
    )
    total = side * side
    return solid / total, dark / total


def _looks_like_a_face(image: Image.Image, box: Box) -> bool:
    """粗判一块面板是不是脸部特写：有成片肤色，也有深色头发。

    成片肤色过多(几乎整块都是皮肤)的是眼妆/手部微距；深色过多的是暗底火花、护腕；
    没有肤色的是鞋履、面料——都不是脸部身份锚点。
    """
    solid, dark = _face_measures(image, box)
    return FACE_MIN_SKIN <= solid <= FACE_MAX_SKIN and FACE_MIN_DARK <= dark <= FACE_MAX_DARK


def _region_cells(layout: ActorSheetLayout, key: str) -> tuple[str, ...]:
    for region in layout.regions:
        if region.key == key:
            return region.cells
    raise KeyError(key)


def detect_actor_sheet_cell_boxes(
    image: Image.Image, layout: ActorSheetLayout = ACTOR_SHEET_LAYOUT
) -> list[tuple[str, Box]]:
    """返回真的找到的 (格子 key, 像素框)，按 ``ACTOR_SHEET_CELL_ORDER`` 排序。

    ``REQUIRED_CELLS`` 一定在结果里；元素拆解和细节矩阵只包含模型真的画出来的格子。
    """
    seps = _SeparatorMap(image)
    width, height = seps.width, seps.height
    expected = dict(actor_sheet_cell_boxes(width, height, layout))
    body_top = round(height * layout.title_band_ratio)

    # 栏界不穿过任何标题字：中栏内部的竖缝常在中栏标题正下方(见 column_split)。
    titles = seps.title_spans()
    first = seps.column_split(round(width * layout.left_portrait_width), body_top, titles)
    second = seps.column_split(
        round(width * (layout.left_portrait_width + layout.middle_width)), body_top, titles
    )
    if second <= first:
        first, second = round(width / 3), round(width * 2 / 3)

    def column_panels(left: int, right: int) -> list[Box]:
        found = []
        for box in seps.panels((left, 0, right, height)):
            if box[2] - box[0] < width * MIN_PANEL_WIDTH or _height(box) < height * MIN_PANEL_HEIGHT:
                continue
            if box[1] < height * TITLE_ZONE and _height(box) <= height * TITLE_ZONE:
                continue  # 栏顶标题字
            found.append(box)
        return found

    left_panels = column_panels(0, first)
    middle_panels = column_panels(first, second)
    right_panels = column_panels(second, width)
    boxes: dict[str, Box] = {}

    # —— 左栏只有主肖像：标题以下所有叶子的并集(浅色衣料和底色相接处可能被切成几条) ——
    if left_panels:
        boxes["portrait"] = (
            min(box[0] for box in left_panels), min(box[1] for box in left_panels),
            max(box[2] for box in left_panels), max(box[3] for box in left_panels),
        )

    # —— 中栏：全身立绘、三视图、元素拆解 ——
    remaining = list(middle_panels)
    if remaining:
        content_top = min(box[1] for box in middle_panels)
        content_bottom = max(box[3] for box in middle_panels)
        floor = VIEW_MIN_HEIGHT * (content_bottom - content_top)
        # 太窄的竖条(上一栏没切干净留下的边)不是人物视图。
        narrowest = width * MIN_VIEW_WIDTH
        tall = sorted(
            (box for box in remaining if _height(box) >= floor and box[2] - box[0] >= narrowest),
            key=lambda box: box[0],
        )
        for box in tall:
            remaining.remove(box)
        full_body, views = _full_body_and_views(tall)
        if full_body is not None:
            boxes["full_body"] = full_body
        if len(views) == 3:
            boxes.update(zip(_region_cells(layout, "three_view"), views))
        element_cells = _region_cells(layout, "elements")
        elements = _merge_to_fit(_reading_order(remaining), len(element_cells))
        boxes.update(zip(element_cells, elements))

    # —— 右栏：阅读顺序里头三块"像脸"的面板是正脸 / 左侧45° / 右侧45°，其余按顺序是细节 ——
    details = _reading_order(right_panels)
    detail_cells = _region_cells(layout, "detail_matrix")
    face_cells = tuple(cell for cell in detail_cells if cell.startswith("face_") and cell != "face_back_hair")
    other_cells = tuple(cell for cell in detail_cells if cell not in face_cells)
    faces = [box for box in details if _looks_like_a_face(image, box)][: len(face_cells)]
    # 正脸与左侧 45° 是身份锚点，像脸的不够两块时用成片肤色最多的补齐(通常是眼妆微距，至少是脸的一部分)；
    # 右侧 45° 不硬凑，没画就交给补位(左侧 45° 水平翻转)。
    spare = sorted(
        (box for box in details if box not in faces),
        key=lambda box: _face_measures(image, box)[0], reverse=True,
    )
    faces.extend(spare[: max(0, 2 - len(faces))])
    faces.sort(key=details.index)
    boxes.update(zip(face_cells, faces))
    boxes.update(zip(other_cells, [box for box in details if box not in faces]))

    for cell in REQUIRED_CELLS:
        boxes.setdefault(cell, expected[cell])
    return [(cell, boxes[cell]) for cell in expected if cell in boxes]
