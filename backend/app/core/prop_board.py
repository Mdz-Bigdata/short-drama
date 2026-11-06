# -*- coding: utf-8 -*-
"""道具的比例总览：把切好的视图排成一张板，画上尺寸线、比例尺和手或人形的轮廓。

这张板上的数字和比例都是算出来的。标注的视图共用一个比例，下方对照带里的道具、手或人形和比例尺
也共用一个比例，所以拿尺子量图是对得上的。尺寸是依据描述或物件类别定的，没写明的都标「约」。
"""

from __future__ import annotations

import io
import math
from collections.abc import Mapping

from PIL import Image, ImageChops, ImageDraw, ImageFont

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


def _length_label(plan: PropPlan) -> str:
    return f"{'' if plan.size_stated else '约 '}{plan.longest_cm:g} cm"


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


def _horizontal_ruler(board: Image.Image, x: int, y: int, span_cm: float, px_per_cm: float, font) -> None:
    draw = ImageDraw.Draw(board)
    step, bars = _ruler_length(span_cm)
    for index in range(bars):
        left, right = x + index * step * px_per_cm, x + (index + 1) * step * px_per_cm
        draw.rectangle((left, y, right, y + 14), fill=_INK if index % 2 == 0 else _WHITE, outline=_INK)
    for index in range(bars + 1):
        draw.text((x + index * step * px_per_cm, y + 22), f"{index * step:g}", font=font, fill=_INK, anchor="ma")
    draw.text((x + bars * step * px_per_cm + 40, y + 7), "cm", font=font, fill=_MUTED, anchor="lm")


def _vertical_ruler(board: Image.Image, x: int, base_y: int, span_cm: float, px_per_cm: float, font) -> None:
    draw = ImageDraw.Draw(board)
    step, bars = _ruler_length(span_cm)
    for index in range(bars):
        low, high = base_y - index * step * px_per_cm, base_y - (index + 1) * step * px_per_cm
        draw.rectangle((x, high, x + 14, low), fill=_INK if index % 2 == 0 else _WHITE, outline=_INK)
    for index in range(bars + 1):
        draw.text((x - 10, base_y - index * step * px_per_cm), f"{index * step:g}", font=font, fill=_INK, anchor="rm")
    draw.text((x + 7, base_y - bars * step * px_per_cm - 12), "cm", font=font, fill=_MUTED, anchor="md")


def _hand_strip(front: Image.Image, plan: PropPlan, fonts) -> Image.Image:
    """道具横放，和手、比例尺同一个比例。"""
    label_font, small = fonts
    subject = front.crop(_object_box(front))
    if subject.height > subject.width:
        subject = subject.rotate(90, expand=True, fillcolor=_WHITE)
    usable = _WIDTH - 2 * 70 - 80
    gap_cm = max(plan.longest_cm, HAND_LENGTH_CM) * 0.12
    span = plan.longest_cm + gap_cm + HAND_LENGTH_CM
    short_cm = plan.longest_cm * subject.height / subject.width
    step, bars = _ruler_length(span)
    px_per_cm = min(usable / (step * bars), 300 / max(short_cm, _HAND_HEIGHT_CM))
    strip = Image.new("RGB", (_WIDTH, 470), _WHITE)
    draw = ImageDraw.Draw(strip)
    draw.text((70, 24), "比例对照", font=label_font, fill=_MUTED)
    base = 360
    # 尺和尺上的东西作为一组放在中间。
    left = max(70, round((_WIDTH - step * bars * px_per_cm) / 2))
    size = (max(1, round(plan.longest_cm * px_per_cm)), max(1, round(short_cm * px_per_cm)))
    strip.paste(subject.resize(size, Image.LANCZOS), (left, base - size[1] - 6))
    draw.text((left + size[0] / 2, base - size[1] - 14), _length_label(plan), font=small, fill=_INK, anchor="md")
    hand = _hand(round(HAND_LENGTH_CM * px_per_cm))
    hand_x = left + size[0] + round(gap_cm * px_per_cm)
    _paste_shape(strip, hand, (hand_x, base - hand.height - 6))
    draw.text((hand_x + hand.width / 2, base - hand.height - 14), f"成人手 约 {HAND_LENGTH_CM:g} cm", font=small, fill=_INK, anchor="md")
    _horizontal_ruler(strip, left, base, span, px_per_cm, small)
    return strip


def _figure_strip(front: Image.Image, plan: PropPlan, fonts) -> Image.Image:
    """道具站在基线上，旁边站一个人，共用一个比例。"""
    label_font, small = fonts
    subject = front.crop(_object_box(front))
    long_side = max(subject.size)
    object_w = plan.longest_cm * subject.width / long_side
    object_h = plan.longest_cm * subject.height / long_side
    height_cm = max(FIGURE_HEIGHT_CM, object_h)
    step, bars = _ruler_length(height_cm)
    usable = _WIDTH - 2 * 150
    px_per_cm = min(600 / (step * bars), usable / (object_w + _FIGURE_WIDTH_CM + 60))
    strip = Image.new("RGB", (_WIDTH, 760), _WHITE)
    draw = ImageDraw.Draw(strip)
    draw.text((70, 24), "比例对照", font=label_font, fill=_MUTED)
    base = 720
    size = (max(1, round(object_w * px_per_cm)), max(1, round(object_h * px_per_cm)))
    # 尺、道具、人形作为一组放在中间。
    content = 90 + size[0] + round((60 + _FIGURE_WIDTH_CM) * px_per_cm)
    ruler_x = max(150, (_WIDTH - content) // 2)
    _vertical_ruler(strip, ruler_x, base, height_cm, px_per_cm, small)
    x = ruler_x + 90
    strip.paste(subject.resize(size, Image.LANCZOS), (x, base - size[1]))
    draw.text((x + size[0] / 2, base - size[1] - 10), _length_label(plan), font=small, fill=_INK, anchor="md")
    figure = _figure(round(FIGURE_HEIGHT_CM * px_per_cm))
    figure_x = x + size[0] + round(60 * px_per_cm)
    _paste_shape(strip, figure, (figure_x, base - figure.height))
    draw.text((figure_x + figure.width / 2, base - figure.height - 10), f"人形 约 {FIGURE_HEIGHT_CM:g} cm", font=small, fill=_INK, anchor="md")
    draw.line(((90, base), (_WIDTH - 90, base)), fill=_RULE, width=2)
    return strip


def _views_row(images: Mapping[str, Image.Image], plan: PropPlan, fonts) -> Image.Image:
    label_font, small = fonts
    slots = [*plan.views, PROP_REFERENCE_SLOT]
    columns = len(slots)
    tall = plan.rows == 1
    cell_w = (_WIDTH - _GUTTER * (columns + 1)) // columns
    cell_h = round(cell_w * 2.1) if tall else cell_w + 60
    row = Image.new("RGB", (_WIDTH, cell_h + 2 * _GUTTER), _WHITE)
    draw = ImageDraw.Draw(row)
    room_w, room_h = cell_w - 130, cell_h - 90
    pieces = {slot: images[slot].crop(_object_box(images[slot])) for slot in plan.views}
    # 模型每格放大的程度不一样。按正投影的关系还原：各视图和正面一样高，顶面和正面一样宽；最紧的那张刚好放得下。
    front = pieces[plan.views[0]]
    matched = {
        slot: (front.width / piece.width if slot == "prop_top" else front.height / piece.height)
        for slot, piece in pieces.items() if slot != "prop_detail"
    }
    fit = min(min(room_w / (pieces[slot].width * ratio), room_h / (pieces[slot].height * ratio)) for slot, ratio in matched.items())
    for index, slot in enumerate(slots):
        x = _GUTTER + index * (cell_w + _GUTTER)
        y = _GUTTER
        draw.rectangle((x, y, x + cell_w, y + cell_h), outline=_RULE, width=2)
        name = "比例参照" if slot == PROP_REFERENCE_SLOT else PROP_VIEWS[slot][0]
        draw.text((x + cell_w / 2, y + cell_h - 36), name, font=label_font, fill=_MUTED, anchor="mm")
        # 细节和比例参照格是一整张画面，不收紧。
        piece = pieces.get(slot) if slot in matched else images[slot]
        if slot in matched:
            scale = matched[slot] * fit
        else:
            scale = min((cell_w - 40) / piece.width, (cell_h - 90) / piece.height)
        size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
        left = x + (cell_w - size[0]) // 2 + (30 if slot in plan.measured else 0)
        top = y + (cell_h - 60 - size[1]) // 2
        row.paste(piece.resize(size, Image.LANCZOS), (left, top))
        if slot in plan.measured:
            if size[1] >= size[0]:
                line_x = left - 26
                _draw_dimension(draw, (line_x, top), (line_x, top + size[1]), "", small)
                draw.text((line_x - 12, top + size[1] / 2), _length_label(plan), font=small, fill=_INK, anchor="rm")
            else:
                line_y = top + size[1] + 14
                _draw_dimension(draw, (left, line_y), (left + size[0], line_y), _length_label(plan), small)
    return row


def compose_prop_board(plan: PropPlan, views: Mapping[str, bytes]) -> bytes:
    """一张 PNG：上面一排视图带尺寸线，下面一条按真实比例的对照带。"""
    images = {slot: _on_white(_load(views[slot])) for slot in (*plan.views, PROP_REFERENCE_SLOT)}
    fonts = (_font(30), _font(24))
    row = _views_row(images, plan, fonts)
    strip = (_figure_strip if plan.figure else _hand_strip)(images[plan.views[0]], plan, fonts)
    board = Image.new("RGB", (_WIDTH, row.height + strip.height), _WHITE)
    board.paste(row, (0, 0))
    board.paste(strip, (0, row.height))
    buffer = io.BytesIO()
    board.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
