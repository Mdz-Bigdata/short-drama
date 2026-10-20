# -*- coding: utf-8 -*-
"""数字演员的高清身份视图：三张脸、三张全身各出一张专门的高清图，再切成六张。

设定集一张图里塞了 25 格，正脸特写这类格子只有 300px 上下，放大到身份视图主画面就糊。
设定集通过质检后，再以它(或现有主肖像)为身份参考出两张图：

- 头像三联：横排三格 1:1，左正脸、中左侧 45°、右右侧 45°，每格约 1024px；
- 全身三联：横排三格 1:2，左正面、中 90° 侧面、右背面，每格约 1024×2048。

切法与道具四视图相同：分割线从 1/3、2/3 处吸附到真实白缝，每格收紧到人物并留余量。
三张脸必须真的转了面(差分哈希互不相同)，否则这一组不采用，保留设定集里的裁切。
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from app.core.actor_sheet_cutter import _runs, _SeparatorMap
from app.core.actor_sheet_layout import FULL_BODY_PROPORTION_RULE

#: 头像三联、全身三联的出图尺寸(总像素都在供应商 4096×4096 上限之内)。
HD_FACE_SIZE = "3072x1024"
HD_BODY_SIZE = "3072x2048"
#: 每组切出的格子 key，顺序即横排从左到右。
HD_FACE_CELLS: tuple[str, ...] = ("face_front", "face_three_quarter", "face_three_quarter_right")
HD_BODY_CELLS: tuple[str, ...] = ("front", "profile", "back")
SPLIT_SEARCH = 0.15
# 一格面板至少占整张图的这个比例；更小的叶子是碎片。
PANEL_MIN_AREA = 0.08
VIEW_MARGIN = 0.05


@dataclass(frozen=True)
class HdGroup:
    cells: tuple[str, ...]
    size: str
    layout: str
    # 三格必须明显不同才采用：模型常把三张脸都画成正脸，这一组就要查；全身三视图轮廓差异本就大。
    require_distinct: bool = False


HD_GROUPS: tuple[HdGroup, ...] = (
    HdGroup(
        cells=HD_FACE_CELLS,
        size=HD_FACE_SIZE,
        layout=(
            "横向 1 行 3 格的头肩特写三联，格与格之间一条纯白细缝，浅灰到纯白的干净背景。"
            "三格是同一个人、同一光线、同一景别(头顶到锁骨完整入画)、同一高度。"
            "左格：正脸，直视镜头；中格：整个头部向画面左侧转 45°，露出右侧脸颊与右耳；"
            "右格：整个头部向画面右侧转 45°，露出左侧脸颊与左耳。三格的朝向必须明显不同。"
            "五官、皮肤纹理、发丝、发饰与领口高清锐利，焦点落在眼睛上。"
        ),
        require_distinct=True,
    ),
    HdGroup(
        cells=HD_BODY_CELLS,
        size=HD_BODY_SIZE,
        layout=(
            "横向 1 行 3 格的全身三视图，格与格之间一条纯白细缝，纯白干净背景。"
            "左格：正面全身；中格：90 度标准侧面全身；右格：背面全身。"
            "三格同一比例，脚底在同一条基线上，头顶在同一高度，头顶到双脚完整入画。"
            f"{FULL_BODY_PROPORTION_RULE}"
            "服装面料、纹样、配饰与鞋履高清锐利。"
        ),
    ),
)


def hd_prompt(group: HdGroup, *, name: str, desc: str, style: str) -> str:
    return (
        f"为角色{name}制作高清身份视图。{group.layout}"
        f"严格参考所给参考图里的同一个人：脸型、五官比例、痣与疤的位置、发际线、发型发色、发饰、服装与配饰完全一致。"
        f"角色设定：{desc}。视觉风格：{style}。"
        "禁止出现文字、标签、编号、水印、logo，禁止第二个人物、额外肢体、多余手指和场景道具。"
    )


def _snap(separators: list[bool], length: int, fraction: float) -> int:
    target = round(length * fraction)
    radius = round(length * SPLIT_SEARCH)
    runs = [
        (low, high) for low, high in _runs(separators, interior_only=True)
        if abs((low + high) / 2 - target) <= radius
    ]
    if not runs:
        return target
    low, high = min(runs, key=lambda run: abs((run[0] + run[1]) / 2 - target))
    return (low + high) // 2


def split_triptych(content: bytes) -> list[Image.Image]:
    """横排三联切成三张：分割线吸附白缝，每格收紧到人物并留余量。"""
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    seps = _SeparatorMap(image)
    width, height = image.size
    # 先按真实面板切：三格画得不等宽、又没留明显白缝时，按三等分切会把邻格的半张脸带进来。
    panels = sorted(
        (box for box in seps.panels((0, 0, width, height))
         if (box[2] - box[0]) * (box[3] - box[1]) >= width * height * PANEL_MIN_AREA),
        key=lambda box: box[0],
    )
    if len(panels) == 3:
        boxes = [(left, 0, right, height) for left, _, right, _ in panels]
    else:
        columns = seps.separators((0, 0, width, height), "x")
        first, second = _snap(columns, width, 1 / 3), _snap(columns, width, 2 / 3)
        if second <= first:
            first, second = width // 3, width * 2 // 3
        boxes = [(0, 0, first, height), (first, 0, second, height), (second, 0, width, height)]
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


def _distinct(images: list[Image.Image]) -> bool:
    """三张必须真的不同(转了面)：缩成 16×16 灰度后两两差异够大。"""
    thumbs = [list(image.convert("L").resize((16, 16), Image.Resampling.BOX).tobytes()) for image in images]
    for i in range(len(thumbs)):
        for j in range(i + 1, len(thumbs)):
            diff = sum(abs(a - b) for a, b in zip(thumbs[i], thumbs[j])) / len(thumbs[i])
            if diff < 6:
                return False
    return True


def generate_hd_views(
    *,
    generate: Callable[[str, str, list, str], str | None],
    load: Callable[[str], bytes],
    name: str,
    desc: str,
    style: str,
    references: list,
) -> dict[str, Image.Image]:
    """出两张三联并切开，返回 {格子 key: 高清图}；某一组失败或没转面就整组跳过。

    ``generate(model 之外的) (prompt, references, size)`` 返回图片地址，``load(url)`` 取回字节——
    由调用方绑定模型与网关，这里只管提示词、切图和取舍。
    """
    views: dict[str, Image.Image] = {}
    for group in HD_GROUPS:
        try:
            url = generate(hd_prompt(group, name=name, desc=desc, style=style), references, group.size)
            if not url:
                continue
            crops = split_triptych(load(url))
        except Exception:  # noqa: BLE001 - 高清视图是锦上添花，失败就保留设定集裁切
            continue
        if len(crops) == len(group.cells) and (not group.require_distinct or _distinct(crops)):
            views.update(zip(group.cells, crops))
    return views


def hd_identity_views_enabled() -> bool:
    """高清身份视图默认开启(每个角色多两张付费图)；CHARACTER_HD_VIEWS=0 关闭。"""
    return os.getenv("CHARACTER_HD_VIEWS", "1").strip().lower() not in {"0", "false", "no", "off"}
