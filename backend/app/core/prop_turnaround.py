# -*- coding: utf-8 -*-
"""拍摄道具的比例参考：按物件决定画几个视图，再加一格手持或人形对比。

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

from app.core.actor_sheet_cutter import _runs, _SeparatorMap

#: 槽位 → (中文名, 给图像模型的角度说明)。顺序即前端展示顺序，与 elementTypes.PROP_VIEW_SLOTS 一致。
PROP_VIEWS: dict[str, tuple[str, str]] = {
    "prop_front": ("正面", "正面平视，无透视"),
    "prop_left_45": ("左侧45°", "向画面左侧转动 45°"),
    "prop_right_45": ("右侧45°", "向画面右侧转动 45°"),
    "prop_side": ("侧面", "正侧面平视，转动 90°，无透视，看得出厚度"),
    "prop_back": ("背面", "转动 180° 的背面平视，无透视"),
    "prop_top": ("顶面", "从正上方垂直俯视"),
    "prop_detail": ("关键细节", "最有辨识度的结构、纹样或磨损的特写"),
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


_FAMILIES: dict[str, _Family] = {
    # 细长的东西一行排开，长轴竖直，长度看得最清楚。
    "slender": _Family(
        ("prop_front", "prop_side", "prop_back"), ("prop_front", "prop_side", "prop_back"), 1, 4, WIDE_SIZE,
        "长轴竖直，从头到尾完整入格",
        {"匕首": 30, "短刀": 35, "短剑": 50, "长剑": 100, "剑": 100, "刀": 90, "刃": 80, "鞘": 85, "枪": 220, "矛": 220,
         "戟": 240, "棍": 180, "杖": 150, "拐": 90, "鞭": 150, "箫": 80, "笛": 60, "伞": 90, "弓": 120, "箭": 80},
    ),
    # 扁平的东西两面都要看，再加一格看厚度。
    "flat": _Family(
        ("prop_front", "prop_back", "prop_side"), ("prop_front", "prop_back"), 2, 2, SQUARE_SIZE,
        "平面正对镜头",
        {"令牌": 10, "牌": 10, "信": 25, "纸": 30, "地图": 60, "图": 60, "卷轴": 60, "书": 25, "册": 25, "账本": 25,
         "画": 80, "符": 18, "帖": 20, "佩": 6, "帕": 30, "布": 40, "巾": 40, "镜": 20, "扇": 30, "盾": 80},
    ),
    # 回转体转到哪一面都一样，要看的是口沿和轮廓。
    "round": _Family(
        ("prop_front", "prop_top", "prop_left_45"), ("prop_front",), 2, 2, SQUARE_SIZE,
        "放正，能看清轮廓",
        {"杯": 8, "盏": 8, "碗": 14, "壶": 18, "瓶": 25, "坛": 40, "罐": 25, "灯笼": 35, "灯": 20, "烛": 15, "炉": 25, "盆": 35},
    ),
    # 小物件放大了画，真实大小靠手来比。
    "tiny": _Family(
        ("prop_front", "prop_side", "prop_left_45"), ("prop_front",), 2, 2, SQUARE_SIZE,
        "放大到占满格子的大部分",
        {"扳指": 3, "戒指": 2.5, "戒": 2.5, "耳环": 3, "耳坠": 4, "簪": 15, "钗": 15, "钥匙": 8, "印": 8, "骰子": 2,
         "丸": 1, "针": 8, "钉": 5, "珠": 2, "铃": 5, "哨": 6, "锁": 8},
    ),
    "box": _Family(
        ("prop_front", "prop_left_45", "prop_back", "prop_top", "prop_detail"), ("prop_front", "prop_back"), 2, 3, WIDE_SIZE,
        "放正，盖子闭合",
        {"匣": 20, "盒": 15, "箱": 60, "奁": 20},
    ),
    "large": _Family(
        ("prop_front", "prop_side", "prop_back", "prop_top", "prop_detail"), ("prop_front", "prop_back"), 2, 3, WIDE_SIZE,
        "放正，整体完整入格",
        {"桌": 120, "案": 150, "椅": 95, "凳": 45, "床": 200, "榻": 190, "屏风": 180, "柜": 180, "棺": 210, "轿": 220,
         "马车": 350, "车": 300, "鼎": 100, "门": 200, "架": 180, "碑": 150, "笼": 100},
        True,
    ),
}
_DEFAULT_FAMILY = _Family(
    ("prop_front", "prop_left_45", "prop_right_45", "prop_back", "prop_detail"), ("prop_front", "prop_back"), 2, 3, WIDE_SIZE,
    "放正，整体完整入格", {},
)
_DEFAULT_LENGTH_CM = 30.0
_BY_NOUN = sorted(
    ((noun, length, family) for family in _FAMILIES.values() for noun, length in family.nouns.items()),
    key=lambda entry: -len(entry[0]),
)

_HAND_WORDS = {"掌心": 8.0, "巴掌": 15.0, "拇指": 3.0, "指甲": 1.5, "拳头": 9.0}
_DIGITS = {"半": 0.5, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NUMBER = r"\d+(?:\.\d+)?|[半一二两三四五六七八九十]+"
_UNITS = {"厘米": 1.0, "公分": 1.0, "cm": 1.0, "毫米": 0.1, "mm": 0.1, "米": 100.0, "m": 100.0, "尺": 33.0, "寸": 3.3}
_UNIT = "|".join(sorted(_UNITS, key=len, reverse=True))
_MEASURE = re.compile(rf"(?:全长|总长|通长|长|高|宽|直径|径|约|尺寸)[^\d半一二两三四五六七八九十，。；]{{0,3}}({_NUMBER})\s*({_UNIT})|({_NUMBER})\s*({_UNIT})(?:长|高|宽)|({_NUMBER})\s*(尺|寸)", re.I)


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

    @property
    def slots(self) -> tuple[str, ...]:
        """按阅读顺序的每一格。"""
        return (*self.views, PROP_REFERENCE_SLOT)


def _number(text: str) -> float:
    if text[0].isdigit():
        return float(text)
    if text == "十":
        return 10.0
    if "十" in text:  # 十二、二十、二十五
        tens, _, ones = text.partition("十")
        return float(_DIGITS.get(tens, 1)) * 10 + float(_DIGITS.get(ones, 0))
    return float(_DIGITS.get(text, 0))


def stated_length_cm(text: str) -> float | None:
    """描述里写明的最长尺寸；只认紧贴尺寸词的数字，「三米外」不是道具的长度。"""
    lengths = []
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
    尺寸依次看：人填的 ``length_cm``、描述里写明的、物件类别的常见大小。
    """
    bare = re.sub(r"[（(][^）)]*[）)]", "", name or "").strip()
    found = next((entry for entry in _BY_NOUN if bare.endswith(entry[0])), None)
    found = found or next((entry for entry in _BY_NOUN if entry[0] in bare), None)
    noun_length, family = (found[1], found[2]) if found else (_DEFAULT_LENGTH_CM, _DEFAULT_FAMILY)
    stated = length_cm or stated_length_cm(description)
    longest = stated or noun_length
    return PropPlan(
        views=family.views, measured=family.measured, rows=family.rows, columns=family.columns, size=family.size,
        pose=family.pose, longest_cm=float(longest), size_stated=stated is not None,
        figure=family.figure or longest >= FIGURE_FROM_CM,
    )


def prop_instruction(plan: PropPlan) -> str:
    """给图像模型的版式说明。只要它画，不要它写字。"""
    cells = "；".join(f"第 {index} 格：{PROP_VIEWS[slot][0]}，{PROP_VIEWS[slot][1]}" for index, slot in enumerate(plan.views, start=1))
    length = f"这件道具最长边约 {plan.longest_cm:g} 厘米"
    last = len(plan.slots)
    # 只说厘米模型容易画走样，把两者的倍数也说出来。
    reference = (
        f"第 {last} 格是比例对照：一具哑光米白、光滑无五官的全身人台站在道具旁，人台不是真人，身高约 {FIGURE_HEIGHT_CM:g} 厘米，"
        f"{length}，道具最长边是人台身高的 {plan.longest_cm / FIGURE_HEIGHT_CM:.1f} 倍，两者同处一个画面、都完整入格。"
        if plan.figure else
        f"第 {last} 格是比例对照：一只成年人的手自然地拿着这件道具，只画到前臂，不出现脸和身体；手长约 {HAND_LENGTH_CM:g} 厘米，"
        f"{length}，道具最长边是手长的 {plan.longest_cm / HAND_LENGTH_CM:.1f} 倍，严格按这个比例画，道具主要部分不被手挡住。"
    )
    return (
        f"生成一张影视道具比例参考图：严格的 {plan.rows} 行 × {plan.columns} 列网格，共 {last} 格，按从左到右、从上到下的顺序，"
        "格与格之间留一条纯白细缝。各格是同一件道具、同一材质颜色与磨损、同一剧本状态，同一中性柔光，"
        "每一格(包括比例对照格)都是纯白背景，产品抠图质感，没有投影、倒影和地面，"
        f"道具{plan.pose}，在格内居中、完整、不裁断、不贴边。"
        f"前 {len(plan.views)} 格同一比例，不出现手和人物。{cells}。{reference}"
        "清楚呈现比例、轮廓、材质、颜色、磨损和关键结构。"
    )


PROP_CLOSING = (
    "项目视觉基准只决定道具的材质与年代感，不改变纯白背景和中性光：不要暗调、色调滤镜、景深虚化和场景。"
    "统一要求：结构清晰，透视正确，材质真实，细节丰富，高清写实电影质感；严禁任何文字、数字、刻度、尺子、标签、编号、字幕、"
    "水印、Logo、边框；格内不出现第二个道具。"
)


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
