# -*- coding: utf-8 -*-
"""数字演员设定集(Actor Sheet)的唯一版面事实源。

一张 21:9 超宽横版设定集被切成 25 个格子。提示词生成器(storyboard_quality.
build_actor_sheet_prompt)和切图器(storyboard_assets.split_actor_sheet)都只读本模块的
``ACTOR_SHEET_LAYOUT``——两边共用同一组比例，就永远不会出现"提示词说 4 行 3 列、切图器
按 3 行 4 列裁"这种错位。要按真实出图调版面时，改这里的数字即可，两侧同时生效。

版面对照(左→右)::

    ┌──────────────┬───────────────────────────────┬──────────────────────────────┐
    │ MAIN PORTRAIT│ FULL BODY & ELEMENTS          │ DETAIL MATRIX                │
    │    20%       │            40%                │            40%               │
    │              │  40% of mid │ 60% of mid      │                              │
    │  1 大正面    │  1 全身立绘 │ 上: 1×3 三视图  │  4 行 × 3 列 = 12 格         │
    │  近景特写    │             │ 下: 2×4 元素    │                              │
    └──────────────┴─────────────┴─────────────────┴──────────────────────────────┘

已知局限(见 docs/actor-sheet/IMPLEMENTATION.md)：图像模型不会严格遵守 25 格网格，
固定比例裁切必然有漂移；区域标题带也被算进各区顶部格子里。宽高比闸门(2.0–2.6)挡掉
彻底没按 21:9 出的图，逐格空白检查挡掉最严重的漂移，其余靠肉眼看首批真实产出后调常量。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActorSheetRegion:
    """设定集里的一个矩形区域，以及它内部的等分网格。

    坐标都是 0–1 的归一化比例，(x0, y0) 为左上角、(x1, y1) 为右下角。
    ``cells`` 按"先行后列"(左→右、上→下)排列，长度必须等于 rows × columns。
    """

    key: str
    title: str          # 画在该区顶部居中的深灰无衬线标题；空串表示该子区不单独立标题
    x0: float
    x1: float
    y0: float
    y1: float
    rows: int
    columns: int
    cells: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.cells) != self.rows * self.columns:
            raise ValueError(f"区域 {self.key} 的格子数与 {self.rows}×{self.columns} 网格不符")


@dataclass(frozen=True)
class ActorSheetLayout:
    """25 格设定集的全部版面常量。每个数字都对应画面里的一段距离。"""

    # —— 画布 ——
    aspect_ratio_label: str = "21:9"
    # 21:9 超宽横版的标称宽高比 3360/1440 ≈ 2.333。
    target_aspect_ratio: float = 3360 / 1440
    # 出图模型不会精确给到 21:9；这一对是"还能按本版面裁"的容差边界，
    # 越界说明模型根本没按超宽横版画，切出来只会是垃圾，直接拒绝。
    min_aspect_ratio: float = 2.0
    max_aspect_ratio: float = 2.6
    # 默认出图尺寸(CHARACTER_SHEET_SIZE 的默认值)，3360×1440 即 21:9。
    default_width: int = 3360
    default_height: int = 1440

    # —— 三个纵向区域的宽度占比，三者相加必须为 1.0 ——
    left_portrait_width: float = 0.20    # 左区 MAIN PORTRAIT：一张正面近景特写
    middle_width: float = 0.40           # 中区 FULL BODY & ELEMENTS
    right_details_width: float = 0.40    # 右区 DETAIL MATRIX

    # 中区内部再左右一分为二：中左放单张全身立绘，中右放三视图 + 元素拆解。
    middle_inner_split: float = 0.40     # 中左占中区宽度的 40%，中右占 60%
    # 中右上下分界：上面 64% 高度给 1×3 全身三视图，下面 36% 给 2×4 元素拆解。
    mid_right_top_ratio: float = 0.64

    # —— 各网格形状(行, 列)，和提示词里写给模型的网格描述一一对应 ——
    three_view_grid: tuple[int, int] = (1, 3)      # 中右上：正面 / 90°侧面 / 背面 全身
    element_grid: tuple[int, int] = (2, 4)         # 中右下：8 格元素拆解
    detail_matrix_grid: tuple[int, int] = (4, 3)   # 右区：12 格细节矩阵

    regions: tuple[ActorSheetRegion, ...] = field(default_factory=tuple)


def _build_regions(layout: ActorSheetLayout) -> tuple[ActorSheetRegion, ...]:
    """把宽度占比换算成三个区域的绝对横坐标，并挂上各自的网格。"""
    left_end = layout.left_portrait_width                       # 0.20
    middle_end = left_end + layout.middle_width                 # 0.60
    mid_split = left_end + layout.middle_width * layout.middle_inner_split  # 0.36
    mid_right_split = layout.mid_right_top_ratio                # 中右区内部的上下分界线
    return (
        ActorSheetRegion(
            key="main_portrait",
            title="MAIN PORTRAIT",
            x0=0.0, x1=left_end, y0=0.0, y1=1.0,
            rows=1, columns=1,
            cells=("portrait",),
        ),
        ActorSheetRegion(
            key="full_body",
            title="FULL BODY & ELEMENTS",
            x0=left_end, x1=mid_split, y0=0.0, y1=1.0,
            rows=1, columns=1,
            cells=("full_body",),
        ),
        ActorSheetRegion(
            key="three_view",
            title="",  # 与中左同属 FULL BODY & ELEMENTS 区，不再单独立标题
            x0=mid_split, x1=middle_end, y0=0.0, y1=mid_right_split,
            rows=layout.three_view_grid[0], columns=layout.three_view_grid[1],
            cells=("front", "profile", "back"),
        ),
        ActorSheetRegion(
            key="elements",
            title="",
            x0=mid_split, x1=middle_end, y0=mid_right_split, y1=1.0,
            rows=layout.element_grid[0], columns=layout.element_grid[1],
            cells=(
                # 第 1 行：鞋履 / 腰部扣环 / 护腕手部配饰 / 领口肩部刺绣
                "element_shoe", "element_waist", "element_wrist", "element_collar",
                # 第 2 行：面料微距 / 发饰拆解 / 手部姿态 / 裙摆刺绣
                "element_fabric", "element_hair", "element_hand", "element_hem",
            ),
        ),
        ActorSheetRegion(
            key="detail_matrix",
            title="DETAIL MATRIX",
            x0=middle_end, x1=1.0, y0=0.0, y1=1.0,
            rows=layout.detail_matrix_grid[0], columns=layout.detail_matrix_grid[1],
            cells=(
                # 第 1 行：正脸 / 3-4 侧脸 / 后脑发饰
                "face_front", "face_three_quarter", "face_back_hair",
                # 第 2 行：领口肩颈 / 前襟胸部纹样 / 腰部束结
                "detail_collar", "detail_chest", "detail_waist_knot",
                # 第 3 行：袖口末端 / 材质微距 / 背部暗扣系带
                "detail_cuff", "detail_texture", "detail_back_tie",
                # 第 4 行：鞋履足部 / 眼妆微距 / 动态姿态或小配件
                "detail_shoe", "detail_eye", "detail_accessory",
            ),
        ),
    )


_BASE_LAYOUT = ActorSheetLayout()
ACTOR_SHEET_LAYOUT = ActorSheetLayout(regions=_build_regions(_BASE_LAYOUT))

# 切图顺序 = 区域顺序内再按"先行后列"展开；文件名 NN_<key>.png 的 NN 就是这里的序号。
ACTOR_SHEET_CELL_ORDER: tuple[str, ...] = tuple(
    cell for region in ACTOR_SHEET_LAYOUT.regions for cell in region.cells
)

# 三张全身视图必须互不相同，是"真的转面了"的最低证据。
FULL_BODY_CELLS: tuple[str, ...] = ("front", "profile", "back")

# 前端「细节」页签的两个分组：元素拆解 8 格 + 细节矩阵 12 格 = 20 格。
ELEMENT_CELLS: tuple[str, ...] = tuple(
    cell for region in ACTOR_SHEET_LAYOUT.regions if region.key == "elements" for cell in region.cells
)
DETAIL_MATRIX_CELLS: tuple[str, ...] = tuple(
    cell for region in ACTOR_SHEET_LAYOUT.regions if region.key == "detail_matrix" for cell in region.cells
)

REGION_TITLES: tuple[str, ...] = tuple(
    region.title for region in ACTOR_SHEET_LAYOUT.regions if region.title
)


def actor_sheet_cell_boxes(
    width: int, height: int, layout: ActorSheetLayout = ACTOR_SHEET_LAYOUT
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """按版面把 ``width × height`` 的画布切成 25 个 (key, (left, top, right, bottom)) 像素框。

    纯几何，不读图；切图器和几何回归测试共用同一份计算，所以测试覆盖的就是线上行为。
    边界一律用同一个 ``round`` 规则从归一化比例算出，相邻格子共用边界值——
    因此 25 个框严格铺满画布、互不重叠、不留缝。
    """
    if width <= 0 or height <= 0:
        raise ValueError("画布尺寸必须为正")
    boxes: list[tuple[str, tuple[int, int, int, int]]] = []
    for region in layout.regions:
        left = round(width * region.x0)
        right = round(width * region.x1)
        top = round(height * region.y0)
        bottom = round(height * region.y1)
        column_edges = [
            left + round((right - left) * index / region.columns)
            for index in range(region.columns + 1)
        ]
        row_edges = [
            top + round((bottom - top) * index / region.rows)
            for index in range(region.rows + 1)
        ]
        for position, cell in enumerate(region.cells):
            row, column = divmod(position, region.columns)
            boxes.append((cell, (
                column_edges[column], row_edges[row],
                column_edges[column + 1], row_edges[row + 1],
            )))
    return boxes
