# -*- coding: utf-8 -*-
"""数字演员设定集里模型没画出来的元素/细节格，补出一张专门的特写拼板再切开。

设定集一张图塞 25 格，模型常漏画几格「元素拆解」「细节矩阵」。切图时这些格先按
``DERIVED_CELL_SOURCES`` 从全身立绘/主肖像里按比例裁一块补位，但全身立绘四周大片留白，
「面料微距」「手部姿态」这类格常常裁到一片空白。这里以设定集为身份参考，把缺的格子
排成 1–2 行、每格 1:1 的特写拼板一次画出来，切开后逐格查空白，合格的替换补位裁切，
不合格的继续保留补位(补位本身也保证不空白，见 ``complete_actor_sheet_cells``)。
"""

from __future__ import annotations

import io
import math
import os
from typing import Callable

from PIL import Image, ImageStat

from app.core.actor_hd_views import VIEW_MARGIN
from app.core.actor_sheet_cutter import _runs, _SeparatorMap

#: 每个可补画格子的画面要求；顺序即拼板里的先后。右侧 45° 侧脸由高清身份视图负责，不在这里画。
DETAIL_FILL_SUBJECTS: dict[str, str] = {
    "element_shoe": "鞋履特写：一双鞋完整入画，鞋面纹样、鞋口与鞋底材质清晰",
    "element_waist": "腰部配饰特写：腰带、带扣、玉佩或系结",
    "element_wrist": "手腕配饰特写：袖口收口与腕部饰物，带一截手腕",
    "element_collar": "领口肩部刺绣特写：交领层次与肩部纹样",
    "element_fabric": "主服装面料微距：织纹、刺绣针脚与光泽铺满整格",
    "element_hair": "发饰头饰特写：发冠、发簪、步摇等头饰",
    "element_hand": "手部姿态特写：一只手连着袖口自然摆放或持物，五根手指，比例正确",
    "element_hem": "衣摆下摆特写：下摆边缘纹样与垂坠",
    "face_back_hair": "后脑发型特写：从背后看发髻与发饰",
    "detail_collar": "领口肩颈特写",
    "detail_chest": "前襟胸部纹样特写",
    "detail_waist_knot": "腰部束结特写",
    "detail_cuff": "袖口末端特写",
    "detail_texture": "服装材质纹理微距：铺满整格",
    "detail_shoe": "鞋履足部特写：只画脚踝以下的双脚与鞋，不画腿和衣摆以上",
    "detail_eye": "眼部特写：双眼与眉毛、眼妆，眼神清晰",
    "detail_accessory": "随身小配件特写：佩饰、香囊、扇子或手持道具",
}

#: 一张拼板最多画几格：3×3 留一格空位(见 ``padded``)。再多每格就太小，细节会糊。
MAX_CELLS_PER_BOARD = 8
#: 低于这个灰度标准差就算空白(纯背景约 3–10，有内容的特写一般 > 40)。
BLANK_STDDEV = 18.0
#: 每条分割线只在"应在位置"左右这个比例(相对一格宽度)之内找白缝；再远就是别的格子的缝。
GUTTER_RADIUS = 0.35
#: 真实面板比一格大出这个倍数就是并了格(模型少画了缝)，不按它切。
PANEL_MAX_SCALE = 1.3
#: 窄于这个像素数的平滑段只是纹理里的一道亮线，不算白缝。
MIN_GUTTER_PX = 6
# 一格面板至少占「一格应有面积」的这个比例；更小的叶子是碎片。
PANEL_MIN_SHARE = 0.5


def is_blank(image: Image.Image) -> bool:
    """整格几乎是一片背景色：灰度标准差太小。"""
    return ImageStat.Stat(image.convert("L")).stddev[0] < BLANK_STDDEV


def fillable(cells) -> list[str]:
    """能补画的格子，按拼板顺序。"""
    wanted = set(cells)
    return [cell for cell in DETAIL_FILL_SUBJECTS if cell in wanted]


def board_shape(count: int) -> tuple[int, int]:
    """(列, 行)。方格网模型画得最稳；总是比 ``count`` 多留至少一格给 ``padded`` 的空位。"""
    if count <= 3:
        return 2, 2
    if count <= 5:
        return 3, 2
    return 3, 3


def board_size(columns: int, rows: int) -> str:
    """每格 1:1；格子越少每格越大，总像素都在供应商 4096×4096 上限之内。"""
    side = 1536 if columns <= 2 else 1024
    return f"{side * columns}x{side * rows}"


def boards(cells) -> list[list[str]]:
    """缺的格子分成若干张拼板，每张不超过 ``MAX_CELLS_PER_BOARD`` 格。"""
    ordered = fillable(cells)
    return [ordered[index:index + MAX_CELLS_PER_BOARD] for index in range(0, len(ordered), MAX_CELLS_PER_BOARD)]


def padded(cells: list[str]) -> list[str]:
    """拼板凑满整行整列：空位补画别的格子(切完丢掉)，模型画不好"留空格"。

    ``board_shape`` 保证至少有一个空位，而且它总排在最后一格：供应商的 AI 水印盖在整图右下角，
    正好落在最后一格里，丢掉的是空位而不是用户要的格子。
    """
    columns, rows = board_shape(len(cells))
    spare = [cell for cell in DETAIL_FILL_SUBJECTS if cell not in cells]
    return list(cells) + spare[: columns * rows - len(cells)]


def detail_fill_prompt(cells: list[str], *, columns: int, rows: int, name: str, desc: str, style: str) -> str:
    """``cells`` 是补好空位的完整版面(``padded``)，``columns × rows`` 是它的格网。"""
    panels = "；".join(
        f"第{index}格：{DETAIL_FILL_SUBJECTS[cell]}" for index, cell in enumerate(cells, start=1)
    )
    return (
        f"为角色{name}制作服装与造型细节特写拼板。画面横向 {rows} 行、每行 {columns} 格，"
        f"共 {columns * rows} 格，不多不少，不要增加任何额外的格子或人物。"
        "每格 1:1 正方形、大小相同，格与格之间一条纯白细缝，从左到右、从上到下依次为："
        f"{panels}。"
        "每格只画一个局部特写，主体填满格子的大部分面积并且居中，不能留出大片空白背景，背景为干净的浅灰到纯白。"
        "任何一格都不要画完整的人物全身像或半身像，只画指定的局部。"
        "严格参考所给设定集里的同一个人与同一套造型：服装颜色、面料、纹样、刺绣、配饰、发饰、鞋履与肤色完全一致，"
        "不得换装、不得新增设定集里没有的配饰。"
        f"角色设定：{desc}。视觉风格：{style}，写实高清，材质纹理锐利。"
        "禁止出现文字、标签、编号、水印、logo，禁止整张人脸以外的第二个人物，禁止多余手指与畸形肢体。"
    )


def _gutters(separators: list[bool], length: int, parts: int) -> list[int] | None:
    """``parts`` 等分处各找一条真实白缝，返回含两端的分割坐标；格网对不上返回 ``None``。

    对不上的情况都不能切，否则会把「面料」安到「手部」上：
    - 某条应在位置附近没有白缝(有内容横跨这条线)；
    - 同一位置附近有两条以上白缝、或在应在位置之外还有白缝(模型多画了列/行，整个格网错位)。
    某格整格留白时，白缝会和那片空白连成一长段，可能同时盖住两个应在位置：等分点落在段里就直接在等分点切。
    """
    cell = length / parts
    radius = round(cell * GUTTER_RADIUS)
    runs = [run for run in _runs(separators, interior_only=False) if run[1] - run[0] >= MIN_GUTTER_PX]
    interior = [run for run in runs if run[0] > 0 and run[1] < length]
    targets = [round(cell * k) for k in range(1, parts)]

    def distance(run: tuple[int, int], target: int) -> float:
        return 0 if run[0] <= target < run[1] else min(abs(run[0] - target), abs(run[1] - 1 - target))

    edges = [0]
    for target in targets:
        near = [run for run in runs if distance(run, target) <= radius]
        if len(near) != 1:
            return None
        low, high = near[0]
        edges.append(target if low <= target < high else (low + high) // 2)
    edges.append(length)
    if any(all(distance(run, target) > radius for target in targets) for run in interior):
        return None
    return edges if all(b > a for a, b in zip(edges, edges[1:])) else None


def _grid_boxes(panels: list[tuple[int, int, int, int]], width: int, height: int, columns: int, rows: int):
    """真实面板一格一个、大小也像一格时，按它们切；否则返回 ``None`` 走白缝格网。"""
    cell_w, cell_h = width / columns, height / rows
    by_slot: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for box in panels:
        if box[2] - box[0] > cell_w * PANEL_MAX_SCALE or box[3] - box[1] > cell_h * PANEL_MAX_SCALE:
            return None
        slot = (min(rows - 1, int((box[1] + box[3]) / 2 / cell_h)), min(columns - 1, int((box[0] + box[2]) / 2 / cell_w)))
        if slot in by_slot:
            return None
        by_slot[slot] = box
    if len(by_slot) != columns * rows:
        return None
    return [by_slot[(r, c)] for r in range(rows) for c in range(columns)]


def split_board(content: bytes, columns: int, rows: int) -> list[Image.Image]:
    """把 ``columns × rows`` 拼板切成格子(先行后列)；格网对不上(模型多画/少画了格)返回空列表。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    seps = _SeparatorMap(image)
    width, height = image.size
    expected = columns * rows
    share = width * height / expected * PANEL_MIN_SHARE
    panels = [
        box for box in seps.panels((0, 0, width, height))
        if (box[2] - box[0]) * (box[3] - box[1]) >= share
    ]
    boxes = _grid_boxes(panels, width, height, columns, rows) if len(panels) == expected else None
    if boxes is None:
        xs = _gutters(seps.separators((0, 0, width, height), "x"), width, columns)
        ys = _gutters(seps.separators((0, 0, width, height), "y"), height, rows)
        if xs is None or ys is None:
            return []
        boxes = [(xs[c], ys[r], xs[c + 1], ys[r + 1]) for r in range(rows) for c in range(columns)]
    crops = []
    for box in boxes:
        tight = seps.trim(box) or box
        margin_x = round((box[2] - box[0]) * VIEW_MARGIN)
        margin_y = round((box[3] - box[1]) * VIEW_MARGIN)
        crops.append(image.crop((
            max(box[0], tight[0] - margin_x), max(box[1], tight[1] - margin_y),
            min(box[2], tight[2] + margin_x), min(box[3], tight[3] + margin_y),
        )))
    return crops


def generate_detail_cells(
    *,
    generate: Callable[[str, list, str], str | None],
    load: Callable[[str], bytes],
    cells,
    name: str,
    desc: str,
    style: str,
    references: list,
) -> dict[str, Image.Image]:
    """补画 ``cells`` 里能补的格子，返回 {格子 key: 特写图}；空白或切坏的格子不返回。

    ``generate(prompt, references, size)`` 返回图片地址，``load(url)`` 取回字节，由调用方绑定模型与网关。
    """
    filled: dict[str, Image.Image] = {}
    for board in boards(cells):
        # 格网按"要补的格数"定(空位是凑出来的)，提示词、尺寸与切法都用同一个格网。
        columns, rows = board_shape(len(board))
        layout = padded(board)
        try:
            url = generate(
                detail_fill_prompt(layout, columns=columns, rows=rows, name=name, desc=desc, style=style),
                references, board_size(columns, rows),
            )
            if not url:
                continue
            crops = split_board(load(url), columns, rows)
        except Exception:  # noqa: BLE001 - 补画失败就保留补位裁切
            continue
        if len(crops) != len(layout):
            continue
        for cell, crop in zip(layout, crops):
            if cell in board and min(crop.size) >= 64 and not is_blank(crop):
                filled[cell] = crop
    return filled


def detail_fill_enabled() -> bool:
    """缺格补画默认开启(有缺格的角色多一到两张付费图)；CHARACTER_DETAIL_FILL=0 关闭。"""
    return os.getenv("CHARACTER_DETAIL_FILL", "1").strip().lower() not in {"0", "false", "no", "off"}
