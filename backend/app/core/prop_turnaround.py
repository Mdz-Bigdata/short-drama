# -*- coding: utf-8 -*-
"""拍摄道具的设定图：正面、背面、侧面、顶面、3/4 五个视图，再加一格手持或人台对比，排成 2 行 × 3 列。

一次出图画一张网格(省钱，也让各格同一光线、同一比例)，再切成单独的视图：分割线从等分位置出发吸附到
真实的白缝上(复用设定集切图器的平滑分隔判定)，每格收紧到道具本身、四周留一点余量。每张视图存进道具
元素自己的槽位，正面同时作为道具的主参考图，所以送给视频模型的参考图上没有手、刻度和文字。
刻度、尺寸线和比例对照图由 ``prop_board`` 按算出来的尺寸画：图像模型写不准数字。
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass

from PIL import Image

from app.core import prompt_data, prop_scale
from app.core.actor_sheet_cutter import _runs, _SeparatorMap

_SHEET = "prop_sheet"
# 各类道具的摆放说法和名词表、手比的说法、中文数字、长度单位和认尺寸的正则：app/data/prompt/prop_turnaround.json。
_WORDING = "prop_turnaround"
#: 槽位 → (中文名, 给图像模型的角度说明)。顺序即前端展示顺序，与 elementTypes.PROP_VIEW_SLOTS 一致；说法在 app/data/prompt/prop_sheet.json。
PROP_VIEWS: dict[str, tuple[str, str]] = {
    slot: (str(name), str(angle)) for slot, (name, angle) in prompt_data.value(_SHEET, "views").items()
}
PROP_REFERENCE_SLOT = "prop_in_use"
#: 带刻度和尺寸标注的比例总览，是程序画的，不是模型出的。
PROP_BOARD_SLOT = "prop_board"
#: 这几张里有手、人台或文字，不能拿去锁定道具的样子。
PROP_DISPLAY_ONLY_SLOTS = frozenset({PROP_REFERENCE_SLOT, PROP_BOARD_SLOT})
PROP_ALL_SLOTS: tuple[str, ...] = (*PROP_VIEWS, PROP_REFERENCE_SLOT, PROP_BOARD_SLOT)

SQUARE_SIZE = "2048x2048"
WIDE_SIZE = "2848x1600"
# 分割线最多从等分位置挪开多少(占一格的比例)；收紧后四周留多少余量(占格子边长的比例)。
SPLIT_SEARCH = 0.3
VIEW_MARGIN = 0.06

HAND_LENGTH_CM = 18.0
FIGURE_HEIGHT_CM = 170.0
# 比这长的东西，手比不出大小，要站一个人。
FIGURE_FROM_CM = 150.0


@dataclass(frozen=True)
class _Family:
    views: tuple[str, ...]
    measured: tuple[str, ...]
    rows: int
    columns: int
    size: str
    pose: str
    nouns: dict[str, float]
    figure: bool = False
    # 长轴水平横放：各视图的长度一样，按宽对齐比例(高是刃宽或厚度，各面不同)。
    lying: bool = False


def _word(key: str) -> str:
    return prompt_data.text(_WORDING, key)


def _lengths(key: str) -> dict[str, float]:
    """词 → 厘米的表，按表里的顺序(先认先得)。数值照表里的写法，整数仍是整数。"""
    return {str(word): length for word, length in prompt_data.value(_WORDING, key).items()}


def _family_words(name: str) -> dict[str, object]:
    """这一类道具的摆放说法(写进版式说明)和认它的名词表。"""
    entry = prompt_data.value(_WORDING, "families")[name]
    return {"pose": str(entry["pose"]), "nouns": {str(noun): length for noun, length in entry["nouns"].items()}}


# 每件道具都是 2 行 × 3 列：五个视图加一格手持 / 人台对照，像专业道具设定图那样一张看全。
# 正投影的四个视图(正面、背面、侧面、顶面)标长宽高；3/4 透视和细节只看样子，不标尺寸。
_ORTHOGRAPHIC = ("prop_front", "prop_back", "prop_side", "prop_top")
_STANDARD_VIEWS = (*_ORTHOGRAPHIC, "prop_left_45")
_GRID = dict(rows=2, columns=3, size=WIDE_SIZE)

_FAMILIES: dict[str, _Family] = {
    # 细长的东西横放，长轴水平，长度看得最清楚。
    "slender": _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, **_family_words("slender"), lying=True),
    # 扁平的东西两面都要看，侧面看厚度。
    "flat": _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, **_family_words("flat")),
    # 回转体侧面和正面一样，换成细节特写；要看的是口沿和轮廓。
    "round": _Family(
        ("prop_front", "prop_back", "prop_top", "prop_left_45", "prop_detail"), ("prop_front", "prop_back", "prop_top"), **_GRID,
        **_family_words("round"),
    ),
    # 小物件放大了画，真实大小靠手来比。丹药：「九转还魂丹」是一粒丹丸；「牡丹」是花，按花朵算。
    "tiny": _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, **_family_words("tiny")),
    "box": _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, **_family_words("box")),
    "large": _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, **_family_words("large"), figure=True),
}
_DEFAULT_FAMILY = _Family(_STANDARD_VIEWS, _ORTHOGRAPHIC, **_GRID, pose=_word("default_pose"), nouns={})
_DEFAULT_LENGTH_CM = 30.0
# 按形状认出来的类别：名字结尾就是这种形状时，参照表的类别不改它的排版。
_SHAPE_FAMILIES = (_FAMILIES["flat"], _FAMILIES["round"], _FAMILIES["tiny"], _FAMILIES["box"])
_BY_NOUN = sorted(
    ((noun, length, family) for family in _FAMILIES.values() for noun, length in family.nouns.items()),
    key=lambda entry: -len(entry[0]),
)

_HAND_WORDS = _lengths("hand_words")
_DIGITS = _lengths("digits")
_TEN = _word("ten")
_NUMBER = _word("number_pattern")
_UNITS = _lengths("units")
_CHI, _CUN = _word("chi"), _word("cun")
_UNIT = "|".join(sorted(_UNITS, key=len, reverse=True))
# 「三尺二寸」是一个长度：尺和寸要加起来，不能只认前面的三尺。
_CHI_CUN = re.compile(_word("chi_cun_pattern").format(number=_NUMBER))
_MEASURE = re.compile(_word("measure_pattern").format(number=_NUMBER, unit=_UNIT), re.I)
_BRACKETS = re.compile(_word("bracket_pattern"))


@dataclass(frozen=True)
class PropPlan:
    views: tuple[str, ...]
    measured: tuple[str, ...]
    rows: int
    columns: int
    size: str
    pose: str
    longest_cm: float
    size_stated: bool
    figure: bool
    # 尺寸从哪来：manual 人填的 / description 描述里写的 / table 道具标尺参照表 / estimate 按物件类别估的。
    size_source: str = "estimate"
    # 参照表里的长宽高说法(「长100×宽4×高2厘米」)；不是从表里查到的为空。
    size_text: str = ""
    # 参照表里的长宽高(厘米)；比例总览上算出来的尺寸靠近其中一个时，标这个整数。
    dims_cm: tuple[float, ...] = ()
    lying: bool = False

    @property
    def slots(self) -> tuple[str, ...]:
        """按阅读顺序的每一格。"""
        return (*self.views, PROP_REFERENCE_SLOT)


def _number(text: str) -> float:
    if text[0].isdigit():
        return float(text)
    if text == _TEN:
        return 10.0
    if _TEN in text:  # 十二、二十、二十五
        tens, _, ones = text.partition(_TEN)
        return float(_DIGITS.get(tens, 1)) * 10 + float(_DIGITS.get(ones, 0))
    return float(_DIGITS.get(text, 0))


def stated_length_cm(text: str) -> float | None:
    """描述里写明的最长尺寸；只认紧贴尺寸词的数字，「三米外」不是道具的长度。"""
    lengths = [_number(chi) * _UNITS[_CHI] + _number(cun) * _UNITS[_CUN] for chi, cun in _CHI_CUN.findall(text or "")]
    for match in _MEASURE.finditer(text or ""):
        groups = [group for group in match.groups() if group]
        lengths.append(_number(groups[0]) * _UNITS[groups[1].lower()])
    lengths = [length for length in lengths if 0.5 <= length <= 2000]
    if lengths:
        return max(lengths)
    return next((length for word, length in _HAND_WORDS.items() if word in (text or "")), None)


def plan_prop(name: str, description: str = "", *, length_cm: float | None = None) -> PropPlan:
    """这件道具该画哪几个视图、用手还是人形比、最长边多长。

    名字的结尾说的才是这是什么(「拭剑旧布」是布，不是剑)，结尾认不出再看名字里有没有。
    尺寸依次看：人填的 ``length_cm``、描述里写明的、道具标尺参照表里的真实尺寸、物件类别的常见大小。
    参照表认出了类别(车辆、动物、饰品……)就按类别排版；名字结尾是扁的、圆的、小的东西(盾、杯、戒指)仍按形状排。
    """
    bare = _BRACKETS.sub("", name or "").strip()
    by_end = next((entry for entry in _BY_NOUN if bare.endswith(entry[0])), None)
    found = by_end or next((entry for entry in _BY_NOUN if entry[0] in bare), None)
    noun_length, family = (found[1], found[2]) if found else (_DEFAULT_LENGTH_CM, _DEFAULT_FAMILY)
    scale = prop_scale.lookup(bare)
    if scale is not None and scale.family and not (by_end and by_end[2] in _SHAPE_FAMILIES):
        family = _DEFAULT_FAMILY if scale.family == "default" else _FAMILIES[scale.family]
    stated = length_cm or stated_length_cm(description)
    longest = stated or (scale.longest_cm if scale is not None else noun_length)
    source = "manual" if length_cm else "description" if stated else "table" if scale is not None else "estimate"
    return PropPlan(
        views=family.views, measured=family.measured, rows=family.rows, columns=family.columns, size=family.size,
        pose=family.pose, longest_cm=float(longest), size_stated=stated is not None,
        figure=family.figure or longest >= FIGURE_FROM_CM,
        size_source=source, size_text=scale.size_text() if scale is not None and not stated else "",
        dims_cm=tuple(scale.dims_cm) if scale is not None and not stated else (),
        lying=family.lying,
    )


def prop_instruction(plan: PropPlan) -> str:
    """给图像模型的版式说明。只要它画，不要它写字；说法在 app/data/prompt/prop_sheet.json。"""
    cells = _word("cell_separator").join(
        prompt_data.text(_SHEET, "cell").format(index=index, name=PROP_VIEWS[slot][0], angle=PROP_VIEWS[slot][1])
        for index, slot in enumerate(plan.views, start=1)
    )
    length = prompt_data.text(_SHEET, "length").format(length=f"{plan.longest_cm:g}") + (
        prompt_data.text("prop_scale", "board_size").format(plan.size_text) if plan.size_text else ""
    )
    last = len(plan.slots)
    # 只说厘米模型容易画走样，把两者的倍数也说出来。
    reference = (
        prompt_data.text(_SHEET, "figure_reference").format(
            cell=last, figure=f"{FIGURE_HEIGHT_CM:g}", length=length, ratio=f"{plan.longest_cm / FIGURE_HEIGHT_CM:.1f}",
        ) if plan.figure else prompt_data.text(_SHEET, "hand_reference").format(
            cell=last, hand=f"{HAND_LENGTH_CM:g}", length=length, ratio=f"{plan.longest_cm / HAND_LENGTH_CM:.1f}",
        )
    )
    return prompt_data.text(_SHEET, "instruction").format(
        rows=plan.rows, columns=plan.columns, cells=last, pose=plan.pose, views=len(plan.views), cell_list=cells, reference=reference,
    )


PROP_CLOSING = prompt_data.text(_SHEET, "closing")


def _split_at(separators: list[bool], length: int, parts: int) -> list[tuple[int, int]]:
    """每一份的 (起, 止)。等分线吸附到附近最近的一段平滑分隔，白缝本身不算进任何一份；找不到就切在等分线上。"""
    radius = length / parts * SPLIT_SEARCH
    runs = _runs(separators, interior_only=True)
    spans = []
    start = 0
    for index in range(1, parts):
        target = length * index / parts
        near = [run for run in runs if abs((run[0] + run[1]) / 2 - target) <= radius]
        low, high = min(near, key=lambda run: abs((run[0] + run[1]) / 2 - target)) if near else (round(target), round(target))
        spans.append((start, low))
        start = high
    return [*spans, (start, length)]


def split_prop_sheet(content: bytes, plan: PropPlan) -> dict[str, bytes]:
    """把网格切成 {槽位: PNG 字节}。多出来的空格不要。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    seps = _SeparatorMap(image)
    width, height = image.size
    columns = _split_at(seps.separators((0, 0, width, height), "x"), width, plan.columns)
    rows = _split_at(seps.separators((0, 0, width, height), "y"), height, plan.rows)
    boxes = [(left, top, right, bottom) for top, bottom in rows for left, right in columns]
    views: dict[str, bytes] = {}
    for slot, box in zip(plan.slots, boxes):
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


def nice_step(span: float, marks: int = 10) -> float:
    """比例尺的一格：把 span 分成不多于 marks 段的 1、2、5 系列整数。"""
    raw = max(span, 1e-6) / marks
    power = 10 ** math.floor(math.log10(raw))
    return next((step * power for step in (1, 2, 5, 10) if step * power >= raw), 10 * power)
