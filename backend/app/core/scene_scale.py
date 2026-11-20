# -*- coding: utf-8 -*-
"""拍摄场地的人物比例参照：主场景全景下面接一条白底对照带。

对照带上有三样：比例尺(米)、按同一比例画的成年人人形、场地的主要尺寸。比例尺和人形共用一个比例，
所以拿人形去比比例尺是对得上的。全景本身透视有远近，比例尺不对应画面里的某一处，只给出「多大」的感觉。

尺寸先取描述里写明的(「宫门高约14米」)；没写就按场地类型查表，都对不上按室内 / 室外给一组常见尺寸，
这两种都标成估算。这张图上有字和人形，只给人看，不拿去当分镜或视频的参考图。

表、措辞和人形身高在 app/data/prompt/scene_scale.json。
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw

from app.core import prompt_data
from app.core.prop_board import _figure, _font
from app.core.prop_turnaround import nice_step

_WORDING = "scene_scale"
#: 对照带的槽位；和四视角分开存，不进参考图。
SCENE_SCALE_SLOT = "scene_scale"
_WHITE = (255, 255, 255)
_INK = (28, 31, 38)
_MUTED = (112, 118, 128)
_MIN_WIDTH = 1600


@dataclass(frozen=True)
class Dimension:
    part: str
    measure: str
    meters: float

    def text(self) -> str:
        return f"{self.part}{self.measure}约{self.meters:g}米"


@dataclass(frozen=True)
class ScenePlan:
    dimensions: tuple[Dimension, ...]
    #: description / table / indoor / outdoor
    source: str
    kind: str = ""

    @property
    def stated(self) -> bool:
        return self.source == "description"

    def text(self) -> str:
        return "、".join(item.text() for item in self.dimensions)

    def bar_meters(self) -> float:
        """比例尺总长：最大尺寸取整，夹在 bar_min_m 与 bar_max_m 之间。"""
        largest = max((item.meters for item in self.dimensions), default=0.0)
        low, high = float(prompt_data.value(_WORDING, "bar_min_m")), float(prompt_data.value(_WORDING, "bar_max_m"))
        return float(min(high, max(low, math.ceil(largest))))


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern[str]:
    return re.compile(prompt_data.text(_WORDING, "dimension_pattern"))


_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _number(text: str) -> float:
    """「3.5」「两」「十二」「三十」「半」。"""
    try:
        return float(text)
    except ValueError:
        pass
    if text == "半":
        return 0.5
    if "十" in text:
        tens, _, ones = text.partition("十")
        return float(_DIGITS.get(tens, 1) * 10 + _DIGITS.get(ones, 0))
    return float(_DIGITS.get(text, 0))


def _meters(number: str, unit: str) -> float:
    return round(_number(number) * float(prompt_data.value(_WORDING, "unit_meters").get(unit, 1)), 1)


def _stated(description: str) -> tuple[Dimension, ...]:
    found, previous = [], ""
    for part, measure, number, unit in _pattern().findall(description):
        # 「密道宽约1.2米、高约1.8米」：没写是什么的高，就是前一个说到的那样东西。
        part = part.lstrip("的") or previous
        previous = part
        item = Dimension(part, measure, _meters(number, unit))
        if item.meters > 0 and item not in found:
            found.append(item)
    # 「约两丈见方」：面宽和进深都是这么长。
    square = re.search(prompt_data.text(_WORDING, "square_pattern"), description)
    if square:
        meters = _meters(*square.groups())
        found += [Dimension(str(part), str(measure), meters) for part, measure in prompt_data.value(_WORDING, "square_parts") if meters > 0]
    return tuple(found[:6])


def _rows(rows) -> tuple[Dimension, ...]:
    return tuple(Dimension(str(part), str(measure), float(meters)) for part, measure, meters in rows)


def plan(name: str, description: str = "") -> ScenePlan:
    """这处场地按什么尺寸画比例参照。"""
    name, description = str(name or "").strip(), str(description or "")
    stated = _stated(description)
    if stated:
        return ScenePlan(stated, "description")
    types = prompt_data.value(_WORDING, "types")
    # 名字的结尾说的才是这是什么地方：「客栈暗室」是暗室，不是客栈大堂。
    for matches in (
        lambda word: name.endswith(word),
        lambda word: word in name,
        lambda word: word in description,
    ):
        for kind, words, rows in types:
            if any(matches(word) for word in words):
                return ScenePlan(_rows(rows), "table", str(kind))
    outdoor = any(word in name for word in prompt_data.words(_WORDING, "outdoor_words"))
    key = "outdoor" if outdoor else "indoor"
    return ScenePlan(_rows(prompt_data.value(_WORDING, key)), key)


def prompt_line(scene: ScenePlan) -> str:
    """给图像模型的一句尺寸要求。"""
    return prompt_data.text(_WORDING, "prompt_line").format(scene.text())


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for char in text:
        if draw.textlength(current + char, font=font) > width and current:
            lines.append(current)
            current = char.lstrip("、")
        else:
            current += char
    return [*lines, current] if current else lines


def compose(main: bytes, scene: ScenePlan) -> bytes:
    """主场景全景在上，下面接一条对照带：左比例尺、中人形、右尺寸。返回 PNG。"""
    with Image.open(io.BytesIO(main)) as opened:
        image = opened.convert("RGB")
    if image.width < _MIN_WIDTH:
        image = image.resize((_MIN_WIDTH, round(image.height * _MIN_WIDTH / image.width)), Image.LANCZOS)
    width = image.width
    unit = width / 1600  # 字号、线宽随宽度放大
    font, small = _font(round(26 * unit)), _font(round(20 * unit))
    figure_m = float(prompt_data.value(_WORDING, "figure_height_m"))
    bar_m = scene.bar_meters()
    bar_px = width * 0.36
    px_per_m = bar_px / bar_m
    figure_px = max(round(figure_m * px_per_m), round(40 * unit))
    px_per_m = figure_px / figure_m
    bar_px = bar_m * px_per_m
    strip_h = round(figure_px + 120 * unit)
    board = Image.new("RGB", (width, image.height + strip_h), _WHITE)
    board.paste(image, (0, 0))
    draw = ImageDraw.Draw(board)
    margin = round(48 * unit)
    base = image.height + strip_h - round(56 * unit)

    # 比例尺：黑白相间的格子，刻度在上，标题在下。
    step = nice_step(bar_m, marks=5)
    bars = math.ceil(bar_m / step - 1e-9)
    bar_h = round(14 * unit)
    for index in range(bars):
        left = margin + index * step * px_per_m
        draw.rectangle(
            (left, base - bar_h, left + step * px_per_m, base),
            fill=_INK if index % 2 == 0 else _WHITE, outline=_INK, width=max(1, round(2 * unit)),
        )
    for index in range(bars + 1):
        draw.text((margin + index * step * px_per_m, base - bar_h - 8 * unit), f"{index * step:g}", font=small, fill=_INK, anchor="md")
    draw.text((margin, base + 10 * unit), prompt_data.text(_WORDING, "bar_title"), font=small, fill=_INK, anchor="la")

    # 人形：站在基线上，和比例尺一个比例；旁边一条身高标线。
    figure = _figure(figure_px)
    figure_x = round(width / 2 - figure.width / 2)
    _paste_shape_dark(board, figure, (figure_x, base - figure.height))
    line_x = figure_x + figure.width + round(12 * unit)
    draw.line(((line_x, base - figure.height), (line_x, base)), fill=_INK, width=max(1, round(2 * unit)))
    for y in (base - figure.height, base):
        draw.line(((line_x - 6 * unit, y), (line_x + 6 * unit, y)), fill=_INK, width=max(1, round(2 * unit)))
    draw.text(
        (line_x + 10 * unit, base - figure.height / 2), prompt_data.text(_WORDING, "figure_label").format(f"{figure_m:g}"),
        font=small, fill=_INK, anchor="lm",
    )
    draw.text((width / 2, base + 10 * unit), prompt_data.text(_WORDING, "figure_caption"), font=small, fill=_INK, anchor="ma")

    # 尺寸：右侧，按宽度折行；估算的在下面注一句。
    right_left = round(width / 2 + 160 * unit)
    text_width = width - margin - right_left
    lines = _wrap(draw, scene.text(), font, text_width)
    if not scene.stated:
        lines += _wrap(draw, prompt_data.text(_WORDING, "estimated_note"), small, text_width)
    line_h = round(36 * unit)
    top = image.height + (strip_h - line_h * len(lines)) / 2
    for index, line in enumerate(lines):
        is_note = not scene.stated and index >= len(lines) - len(_wrap(draw, prompt_data.text(_WORDING, "estimated_note"), small, text_width))
        draw.text((width - margin, top + index * line_h), line, font=small if is_note else font, fill=_MUTED if is_note else _INK, anchor="ra")

    buffer = io.BytesIO()
    board.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _paste_shape_dark(board: Image.Image, shape: Image.Image, at: tuple[int, int]) -> None:
    """人形用深色剪影，在白底上一眼看得出是人。"""
    board.paste(Image.new("RGB", shape.size, _INK), at, shape)


__all__ = ["Dimension", "SCENE_SCALE_SLOT", "ScenePlan", "compose", "plan", "prompt_line"]
