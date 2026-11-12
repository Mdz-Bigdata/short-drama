# -*- coding: utf-8 -*-
"""道具设定图的比例总览：五个视图排成 2 × 3，正投影视图各标长宽两条尺寸线，下方一条比例带。

这张板上的数字和比例都是算出来的。正投影视图共用一个比例，每条尺寸线的数字就是按这个比例量出来的
(靠近道具标尺参照表的长宽高时取表里的整数)；下方比例带里的比例尺、道具、手或人形也共用一个比例，
所以拿尺子量图是对得上的。1 米以上标米，以下标厘米；尺寸是按描述或物件类别定的，没写明的都标「约」。
文字说法在 app/data/prompt/prop_sheet.json。
"""

from __future__ import annotations

import io
import math
from collections.abc import Mapping

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.core import prompt_data
from app.core.media_compositor import _font_path
from app.core.prop_turnaround import (
    FIGURE_HEIGHT_CM,
    HAND_LENGTH_CM,
    PROP_REFERENCE_SLOT,
    PROP_VIEWS,
    PropPlan,
    nice_step,
)

_WIDTH = 2400
_GUTTER = 28
_WHITE = (255, 255, 255)
_INK = (28, 31, 38)
_MUTED = (112, 118, 128)
_RULE = (214, 217, 223)
_SKIN = (190, 195, 204)
_SUPERSAMPLE = 4
_HAND_HEIGHT_CM = 8.5
_FIGURE_WIDTH_CM = 48.0
_LIGHT_BACKGROUND = 170
_OBJECT_DIFFERENCE = 30


def _font(size: int) -> ImageFont.ImageFont:
    path = _font_path()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _background(image: Image.Image) -> tuple[int, int, int]:
    corners = [image.getpixel(point) for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1))]
    return tuple(sorted(channel)[1] for channel in zip(*corners))


def _on_white(image: Image.Image) -> Image.Image:
    """把偏灰的浅色底提到纯白，贴到白板上才没有一块块灰底。深色底(模型画成了场景)不动。"""
    background = _background(image)
    if min(background) < _LIGHT_BACKGROUND:
        return image
    return Image.merge("RGB", [
        band.point(lambda value, floor=floor: min(255, round(value * 255 / floor)))
        for band, floor in zip(image.split(), background)
    ])


def _object_box(image: Image.Image) -> tuple[int, int, int, int]:
    """道具在图里占的范围：和四角底色差得够多的像素(淡淡的投影不算)；什么都没找到就是整张图。"""
    background = Image.new("RGB", image.size, _background(image))
    mask = ImageChops.difference(image, background).convert("L").point(lambda value: 255 if value > _OBJECT_DIFFERENCE else 0)
    return mask.getbbox() or (0, 0, image.width, image.height)


_SHEET = "prop_sheet"


def _board_text(key: str) -> str:
    return str(prompt_data.value(_SHEET, "board")[key])


def format_length(cm: float, *, estimate: bool = False) -> str:
    """1 米以上标米(2.00 m)，以下标厘米(15 cm、2.5 cm)；估计值前面加「约」。"""
    if cm >= 100:
        text = f"{cm / 100:.2f} m"
    elif cm >= 10:
        text = f"{round(cm):g} cm"
    else:
        text = f"{round(cm, 1):g} cm"
    return f"{_board_text('estimate') if estimate else ''}{text}"


def _length_label(plan: PropPlan) -> str:
    return format_length(plan.longest_cm, estimate=not plan.size_stated)


def _snap(cm: float, plan: PropPlan) -> float:
    """量出来的尺寸靠近参照表里的长宽高之一时取表里的数：图像模型画的比例差一点，表里的数才是真的。"""
    tolerance = float(prompt_data.value(_SHEET, "snap_tolerance"))
    near = [value for value in plan.dims_cm if value and abs(cm - value) / value <= tolerance]
    return min(near, key=lambda value: abs(cm - value)) if near else cm


def _load(content: bytes) -> Image.Image:
    with Image.open(io.BytesIO(content)) as opened:
        return opened.convert("RGB")


def _draw_dimension(draw: ImageDraw.ImageDraw, start, end, label: str, font) -> None:
    (x0, y0), (x1, y1) = start, end
    draw.line((start, end), fill=_INK, width=2)
    if x0 == x1:  # 竖线：两端短横
        for y in (y0, y1):
            draw.line(((x0 - 10, y), (x0 + 10, y)), fill=_INK, width=2)
        draw.text((x0 + 14, (y0 + y1) / 2), label, font=font, fill=_INK, anchor="lm")
    else:
        for x in (x0, x1):
            draw.line(((x, y0 - 10), (x, y0 + 10)), fill=_INK, width=2)
        draw.text(((x0 + x1) / 2, y0 + 14), label, font=font, fill=_INK, anchor="ma")


def _hand(length_px: int) -> Image.Image:
    """手的侧影，指尖朝左；只用来比大小，画得像个标志就够了。"""
    scale = max(1, length_px) * _SUPERSAMPLE / 100
    canvas = Image.new("L", (round(100 * scale), round(47 * scale)), 0)
    draw = ImageDraw.Draw(canvas)

    def bar(x0, y0, x1, y1):
        draw.rounded_rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale), radius=min(x1 - x0, y1 - y0) / 2 * scale, fill=255)

    # 手腕到指根约占一半；四根手指长短不一，指缝很窄；拇指从掌根斜着伸出去。
    bar(48, 4, 90, 34)
    draw.rectangle((78 * scale, 11 * scale, 100 * scale, 28 * scale), fill=255)  # 手腕，平着切断
    for top, tip in ((4, 12), (11.5, 0), (19, 5), (26.5, 18)):
        bar(tip, top, 54, top + 6.8)
    draw.line(((70 * scale, 30 * scale), (46 * scale, 41 * scale)), fill=255, width=round(8 * scale))
    draw.ellipse((42 * scale, 37 * scale, 50 * scale, 45 * scale), fill=255)
    return canvas.resize((max(1, length_px), max(1, round(47 * length_px / 100))), Image.LANCZOS)


def _figure(height_px: int) -> Image.Image:
    """站立的人形轮廓。"""
    scale = max(1, height_px) * _SUPERSAMPLE / 170
    canvas = Image.new("L", (round(48 * scale), round(170 * scale)), 0)
    draw = ImageDraw.Draw(canvas)

    def bar(x0, y0, x1, y1):
        draw.rounded_rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale), radius=min(x1 - x0, y1 - y0) / 2 * scale, fill=255)

    draw.ellipse((15 * scale, 0, 33 * scale, 22 * scale), fill=255)
    bar(12, 26, 36, 92)   # 躯干
    bar(2, 28, 10, 90)    # 手臂
    bar(38, 28, 46, 90)
    bar(13, 84, 23, 170)  # 腿
    bar(25, 84, 35, 170)
    return canvas.resize((max(1, round(48 * height_px / 170)), max(1, height_px)), Image.LANCZOS)


def _paste_shape(board: Image.Image, shape: Image.Image, at: tuple[int, int]) -> None:
    board.paste(Image.new("RGB", shape.size, _SKIN), at, shape)


def _ruler_length(span_cm: float) -> tuple[float, int]:
    """比例尺的一格多长、一共几格：总长取整到一格，刻度才是整数。"""
    step = nice_step(span_cm)
    return step, math.ceil(span_cm / step - 1e-9)


_COLUMNS = 3
_ORTHOGRAPHIC = frozenset({"prop_front", "prop_back", "prop_side", "prop_top"})
_CELL_HEIGHT = 640
_LABEL_ROOM = 64
_DIMENSION_ROOM = 120


def _views_grid(images: Mapping[str, Image.Image], plan: PropPlan, fonts) -> tuple[Image.Image, dict[str, tuple[float, float]]]:
    """五个视图加对照格排成 2 × 3；返回板和每个正投影视图量出来的 (宽, 高) 厘米。"""
    label_font, small = fonts
    slots = list(plan.slots)
    rows = math.ceil(len(slots) / _COLUMNS)
    cell_w = (_WIDTH - _GUTTER * (_COLUMNS + 1)) // _COLUMNS
    cell_h = _CELL_HEIGHT
    grid = Image.new("RGB", (_WIDTH, rows * (cell_h + _GUTTER) + _GUTTER), _WHITE)
    draw = ImageDraw.Draw(grid)
    # 右边留出竖向尺寸线和它的数字(「约 7.4 cm」)，下边留出横向尺寸线。
    room_w, room_h = cell_w - _DIMENSION_ROOM - 150, cell_h - _LABEL_ROOM - _DIMENSION_ROOM
    pieces = {slot: images[slot].crop(_object_box(images[slot])) for slot in plan.views}
    # 模型每格放大的程度不一样。按正投影的关系还原：各视图和正面一样高，顶面和正面一样宽(横放的长物件各面一样长，
    # 都按宽对齐)；最紧的那张刚好放得下。3/4 透视和细节不是正投影，各自放满格子。
    front = pieces[plan.views[0]]
    matched = {
        slot: (front.width / piece.width if slot == "prop_top" or plan.lying else front.height / piece.height)
        for slot, piece in pieces.items() if slot in _ORTHOGRAPHIC
    }
    fit = min(min(room_w / (pieces[slot].width * ratio), room_h / (pieces[slot].height * ratio)) for slot, ratio in matched.items())
    measured = [slot for slot in plan.measured if slot in matched]
    sizes = {slot: (pieces[slot].width * matched[slot] * fit, pieces[slot].height * matched[slot] * fit) for slot in matched}
    # 正投影视图里最长的那一边就是道具的最长边：由它定每像素多少厘米，其余尺寸按同一比例量。
    longest_px = max((max(sizes[slot]) for slot in measured), default=0) or 1
    cm_per_px = plan.longest_cm / longest_px
    dimensions = {slot: (_snap(sizes[slot][0] * cm_per_px, plan), _snap(sizes[slot][1] * cm_per_px, plan)) for slot in measured}
    estimate = not plan.size_stated
    for index, slot in enumerate(slots):
        row, column = divmod(index, _COLUMNS)
        x = _GUTTER + column * (cell_w + _GUTTER)
        y = _GUTTER + row * (cell_h + _GUTTER)
        draw.rectangle((x, y, x + cell_w, y + cell_h), outline=_RULE, width=2)
        if slot == PROP_REFERENCE_SLOT:
            name = _board_text("reference_figure" if plan.figure else "reference_hand")
        else:
            name = PROP_VIEWS[slot][0]
        draw.text((x + 22, y + 18), name, font=label_font, fill=_MUTED)
        if slot in matched:
            piece = pieces[slot]
            size = (max(1, round(sizes[slot][0])), max(1, round(sizes[slot][1])))
        else:
            # 3/4 和细节收紧到道具本身再放满格子；比例参照格是一整张画面，不收紧。
            piece = pieces.get(slot) or images[slot]
            scale = min((cell_w - 40) / piece.width, (cell_h - _LABEL_ROOM - 20) / piece.height)
            size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
        shift = -(_DIMENSION_ROOM + 110) // 2 if slot in dimensions else 0
        left = x + (cell_w - size[0]) // 2 + shift
        top = y + _LABEL_ROOM + (cell_h - _LABEL_ROOM - size[1] - (_DIMENSION_ROOM - 30 if slot in dimensions else 0)) // 2
        grid.paste(piece.resize(size, Image.LANCZOS), (left, top))
        if slot in dimensions:
            width_cm, height_cm = dimensions[slot]
            line_y = top + size[1] + 30
            _draw_dimension(draw, (left, line_y), (left + size[0], line_y), format_length(width_cm, estimate=estimate), small)
            line_x = left + size[0] + 30
            _draw_dimension(draw, (line_x, top), (line_x, top + size[1]), format_length(height_cm, estimate=estimate), small)
    return grid, dimensions


def _ruler_unit(span_cm: float) -> tuple[str, float]:
    """比例尺用米还是厘米：一米以上的东西用米，刻度才不会是 0、50、100……400。"""
    return ("m", 100.0) if span_cm >= 100 else ("cm", 1.0)


def _scale_bar(draw: ImageDraw.ImageDraw, x: int, y: int, span_cm: float, px_per_cm: float, font) -> int:
    """黑白相间的比例尺；返回右端的 x。"""
    unit, divisor = _ruler_unit(span_cm)
    step, bars = _ruler_length(span_cm / divisor)
    step_px = step * divisor * px_per_cm
    for index in range(bars):
        draw.rectangle((x + index * step_px, y, x + (index + 1) * step_px, y + 18), fill=_INK if index % 2 == 0 else _WHITE, outline=_INK)
    for index in range(bars + 1):
        draw.text((x + index * step_px, y + 28), f"{index * step:g}", font=font, fill=_INK, anchor="ma")
    draw.text((x, y + 66), _board_text("scale_bar").format(unit=unit), font=font, fill=_MUTED)
    return round(x + bars * step_px)


def _scale_band(view: Image.Image, plan: PropPlan, view_cm: tuple[float, float] | None, fonts) -> Image.Image:
    """比例带：比例尺、道具最长的那个视图、手或人形，同一个比例；人形标身高、手标长度，最后一句写明倍数。

    ``view_cm`` 是这个视图在板上量出来的 (宽, 高)；没有时按最长边和图的长宽比推。
    """
    label_font, small = fonts
    subject = view.crop(_object_box(view))
    figure = plan.figure
    if view_cm and all(view_cm):
        object_w, object_h = view_cm
    else:
        long_side = max(subject.size)
        object_w = plan.longest_cm * subject.width / long_side
        object_h = plan.longest_cm * subject.height / long_side
    if not figure and object_h > object_w:
        subject = subject.rotate(90, expand=True, fillcolor=_WHITE)
        object_w, object_h = object_h, object_w
    reference_cm = FIGURE_HEIGHT_CM if figure else HAND_LENGTH_CM
    reference_w = _FIGURE_WIDTH_CM if figure else HAND_LENGTH_CM
    reference_h = FIGURE_HEIGHT_CM if figure else _HAND_HEIGHT_CM
    tallest = max(object_h, reference_h)
    gap_cm = max(object_w, reference_w) * 0.12
    # 比例尺盖住道具的长度(人形格至少和人一样长)；道具就躺在比例尺上，从 0 刻度开始，量起来一目了然。
    ruler_cm = max(object_w, reference_cm if figure else reference_w)
    content_w_cm = max(ruler_cm, object_w + gap_cm + reference_w)
    px_per_cm = min((_WIDTH - 2 * 80 - 640) / content_w_cm, (560 if figure else 260) / tallest)
    base = 90 + round(tallest * px_per_cm)
    band_h = base + 120
    band = Image.new("RGB", (_WIDTH, band_h), _WHITE)
    draw = ImageDraw.Draw(band)
    draw.line(((_GUTTER, 0), (_WIDTH - _GUTTER, 0)), fill=_RULE, width=2)
    x = 80
    _scale_bar(draw, x, base + 6, ruler_cm, px_per_cm, small)
    size = (max(1, round(object_w * px_per_cm)), max(1, round(object_h * px_per_cm)))
    band.paste(subject.resize(size, Image.LANCZOS), (x, base - size[1]))
    draw.text((x + size[0] / 2, base - size[1] - 12), format_length(object_w, estimate=not plan.size_stated), font=small, fill=_INK, anchor="md")
    x += size[0] + round(gap_cm * px_per_cm)
    if figure:
        shape = _figure(round(FIGURE_HEIGHT_CM * px_per_cm))
        _paste_shape(band, shape, (x, base - shape.height))
        arrow_x = x + shape.width + 26
        _draw_dimension(draw, (arrow_x, base - shape.height), (arrow_x, base), "", small)
        draw.text((arrow_x + 18, base - shape.height / 2 - 18), format_length(FIGURE_HEIGHT_CM), font=label_font, fill=_INK, anchor="lm")
        draw.text((arrow_x + 18, base - shape.height / 2 + 22), _board_text("figure"), font=small, fill=_MUTED, anchor="lm")
        text_x = arrow_x + 200
    else:
        shape = _hand(round(HAND_LENGTH_CM * px_per_cm))
        _paste_shape(band, shape, (x, base - shape.height))
        _draw_dimension(draw, (x, base - shape.height - 30), (x + shape.width, base - shape.height - 30), "", small)
        draw.text((x + shape.width / 2, base - shape.height - 44), f"{_board_text('hand')} {format_length(HAND_LENGTH_CM)}", font=small, fill=_INK, anchor="md")
        text_x = x + shape.width + 60
    ratio_key = "ratio_figure" if figure else "ratio_hand"
    ratio = _board_text(ratio_key).format(length=_length_label(plan), ratio=f"{plan.longest_cm / reference_cm:.2f}")
    widest = max(draw.textlength(ratio, font=small), draw.textlength(_board_text("note"), font=small) if not plan.size_stated else 0)
    text_x = min(max(text_x, _WIDTH - 600), _WIDTH - 60 - round(widest))
    draw.text((text_x, base - 40), ratio, font=small, fill=_INK, anchor="ls")
    if not plan.size_stated:
        draw.text((text_x, base), _board_text("note"), font=small, fill=_MUTED, anchor="ls")
    return band


def compose_prop_board(plan: PropPlan, views: Mapping[str, bytes]) -> bytes:
    """一张 PNG：上面 2 × 3 的视图带长宽尺寸线，下面一条按真实比例的比例带。"""
    images = {slot: _on_white(_load(views[slot])) for slot in (*plan.views, PROP_REFERENCE_SLOT)}
    fonts = (_font(30), _font(24))
    grid, dimensions = _views_grid(images, plan, fonts)
    # 比例带放最能看出长度的那个正投影视图(马车放侧面、汇票放正面)。
    longest_view = max(dimensions, key=lambda slot: max(dimensions[slot]), default=plan.views[0])
    band = _scale_band(images[longest_view], plan, dimensions.get(longest_view), fonts)
    board = Image.new("RGB", (_WIDTH, grid.height + band.height), _WHITE)
    board.paste(grid, (0, 0))
    board.paste(band, (0, grid.height))
    buffer = io.BytesIO()
    board.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
