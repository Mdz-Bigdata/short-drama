# -*- coding: utf-8 -*-
"""数字演员设定集(Actor Sheet)的唯一版面事实源。

一张 21:9 超宽横版设定集最多切成 25 个格子。提示词生成器(storyboard_quality.
build_actor_sheet_prompt)和切图器(actor_sheet_cutter / storyboard_assets.split_actor_sheet)
都只读本模块的 ``ACTOR_SHEET_LAYOUT``。要调版面时，改这里的数字即可，两侧同时生效。

版面对照(左→右，顶部各有一条中文标题带，每个子格下方一行编号中文标注)::

    ┌──────────────┬───────────────────────────────┬──────────────────────────────┐
    │   主肖像     │         全身与元素            │          细节矩阵            │
    │    20%       │            40%                │            40%               │
    │              │  40% of mid │ 60% of mid      │                              │
    │  1 大正面    │  1 全身立绘 │ 上: 1×3 三视图  │  4 行 × 3 列 = 12 格         │
    │  近景特写    │             │ 下: 2×4 元素    │                              │
    └──────────────┴─────────────┴─────────────────┴──────────────────────────────┘

这是写给模型的版面，取自用户给定的设定集提示词。真实出图常会偏离(栏宽不均、格子跨行、
三视图挤在一个面板里、元素画成 2×3)，所以切图器不按比例硬裁，而是从画面里找出真实面板
再按位置认格子(见 actor_sheet_cutter)；模型没画的元素/细节格不硬凑。
``actor_sheet_cell_boxes`` 给出的纯比例框只在某个身份必需格找不到面板时兜底。
"""

from __future__ import annotations

import re
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
    # 默认出图尺寸(CHARACTER_SHEET_SIZE 的默认值)，5040×2160 即 21:9(约 1090 万像素，在供应商
    # 4096×4096 总像素上限之内)。25 格挤在一张图里，3360×1440 时脸部格子只有 300px 上下，放大就糊。
    default_width: int = 5040
    default_height: int = 2160
    # 供应商不接受大尺寸时退回的尺寸。
    fallback_width: int = 3360
    fallback_height: int = 1440

    # —— 三个纵向区域的宽度占比，三者相加必须为 1.0 ——
    left_portrait_width: float = 0.20    # 左区「主肖像」：一张正面近景特写
    middle_width: float = 0.40           # 中区「全身与元素」
    right_details_width: float = 0.40    # 右区「细节矩阵」

    # 每栏顶部的标题带高度占比。切图器会在画面里找标题下方的白色间隔，找不到才用它。
    title_band_ratio: float = 0.10

    # 中区内部再左右一分为二：中左放单张全身立绘，中右放三视图 + 元素拆解。
    middle_inner_split: float = 0.40     # 中左占中区宽度的 40%，中右占 60%
    # 中右上下分界：上面 62% 高度给 1×3 全身三视图，下面 38% 给 2×4 元素拆解。
    mid_right_top_ratio: float = 0.62

    # —— 各网格形状(行, 列)，和提示词里写给模型的网格描述一一对应 ——
    three_view_grid: tuple[int, int] = (1, 3)      # 中右上：正面 / 90°侧面 / 背面 全身
    element_grid: tuple[int, int] = (2, 4)         # 中右下：8 格元素拆解
    detail_matrix_grid: tuple[int, int] = (4, 3)   # 右区：12 格细节矩阵

    regions: tuple[ActorSheetRegion, ...] = field(default_factory=tuple)


def _build_regions(layout: ActorSheetLayout) -> tuple[ActorSheetRegion, ...]:
    """把宽度占比换算成三个区域的绝对坐标，并挂上各自的网格。

    纵向一律从标题带下沿算起：标题带不属于任何格子。
    """
    left_end = layout.left_portrait_width
    middle_end = left_end + layout.middle_width
    mid_split = left_end + layout.middle_width * layout.middle_inner_split
    top = layout.title_band_ratio
    mid_right_split = top + (1.0 - top) * layout.mid_right_top_ratio  # 中右区内部的上下分界线
    return (
        ActorSheetRegion(
            key="main_portrait",
            title="主肖像",
            x0=0.0, x1=left_end, y0=top, y1=1.0,
            rows=1, columns=1,
            cells=("portrait",),
        ),
        ActorSheetRegion(
            key="full_body",
            title="全身与元素",
            x0=left_end, x1=mid_split, y0=top, y1=1.0,
            rows=1, columns=1,
            cells=("full_body",),
        ),
        ActorSheetRegion(
            key="three_view",
            title="",  # 与中左同属「全身与元素」区，不再单独立标题
            x0=mid_split, x1=middle_end, y0=top, y1=mid_right_split,
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
            title="细节矩阵",
            x0=middle_end, x1=1.0, y0=top, y1=1.0,
            rows=layout.detail_matrix_grid[0], columns=layout.detail_matrix_grid[1],
            cells=(
                # 第 1 行：正脸 / 左侧 45° 侧脸 / 右侧 45° 侧脸(三张脸部特写，前端身份选择器直接展示)
                "face_front", "face_three_quarter", "face_three_quarter_right",
                # 第 2 行：后脑发饰 / 领口肩颈 / 前襟胸部纹样
                "face_back_hair", "detail_collar", "detail_chest",
                # 第 3 行：腰部束结 / 袖口末端 / 材质微距
                "detail_waist_knot", "detail_cuff", "detail_texture",
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

# 全身图的人体比例：参考图多是大脸近景，模型会把那张脸原尺寸搬进全身格，画成大头小身。
# 头高只算下巴到头顶，发髻与头饰另算，否则高髻古装会被"合法地"画得头重脚轻。
FULL_BODY_PROPORTION_RULE = (
    "人体比例按真实成年演员：约7.5到8头身，下巴到头顶的头高约占身高的八分之一(发髻与头饰不计入)，"
    "肩宽约两个头宽，腿长约占身高一半；参考图只用来锁定五官与发型，不照搬参考图里的头部大小。"
    "禁止大头小身、Q版、娃娃比例、头饰夸张放大和短腿。"
)

# 前端「细节」页签的两个分组：元素拆解 8 格 + 细节矩阵 12 格(按模型真实画出的格子数落库)。
ELEMENT_CELLS: tuple[str, ...] = tuple(
    cell for region in ACTOR_SHEET_LAYOUT.regions if region.key == "elements" for cell in region.cells
)
DETAIL_MATRIX_CELLS: tuple[str, ...] = tuple(
    cell for region in ACTOR_SHEET_LAYOUT.regions if region.key == "detail_matrix" for cell in region.cells
)

# 七个身份必需格：切图器一定产出它们(找不到面板时退回预期框)，质检也只强制要求它们。
# 元素拆解和细节矩阵按模型真实画出的格子数落库，没画的格子不硬凑。
REQUIRED_CELLS: tuple[str, ...] = (
    "portrait", "full_body", "front", "profile", "back", "face_front", "face_three_quarter",
)


def actor_sheet_cell_key(path: object) -> str | None:
    """从切图文件名 ``NN_<key>.png`` 或 ``NN_<key>-<内容哈希>.png`` 里认出格子 key；认不出返回 ``None``。

    内容哈希让重新切图后的文件名跟着变，浏览器不会拿缓存里的旧裁切冒充新图。
    """
    stem = getattr(path, "stem", None) or str(path).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    prefix, _, key = stem.partition("_")
    key = re.sub(r"-[0-9a-f]{8}$", "", key)
    return key if prefix.isdigit() and key in ACTOR_SHEET_CELL_ORDER else None


def actor_sheet_cell_paths(paths: list) -> dict[str, object]:
    """把切图路径列表认成 {格子 key: 路径}。

    优先认文件名；文件名认不出时(旧调用方)按 ACTOR_SHEET_CELL_ORDER 的位置对应。
    """
    named = [actor_sheet_cell_key(path) for path in paths]
    if all(named) and len(set(named)) == len(named):
        return {str(cell): path for cell, path in zip(named, paths)}
    return dict(zip(ACTOR_SHEET_CELL_ORDER, paths))


# 模型没画的元素/细节格，从已经画出来的身份面板里按部位裁一块补上，保证每个数字演员 25 张图齐全。
# 值是 (来源格, (左, 上, 右, 下))，坐标是来源格图片的 0–1 比例。来源都是七个必需格之一，
# 切图器保证它们一定存在；全身类面板已收紧到人物外框，所以按人体比例取部位是稳的。
DERIVED_CELL_SOURCES: dict[str, tuple[str, tuple[float, float, float, float]]] = {
    "element_shoe": ("full_body", (0.05, 0.86, 0.95, 1.00)),
    "element_waist": ("full_body", (0.15, 0.34, 0.85, 0.50)),
    "element_wrist": ("full_body", (0.00, 0.40, 1.00, 0.60)),
    "element_collar": ("portrait", (0.10, 0.58, 0.90, 1.00)),
    "element_fabric": ("full_body", (0.25, 0.56, 0.75, 0.74)),
    "element_hair": ("portrait", (0.08, 0.00, 0.92, 0.32)),
    "element_hand": ("full_body", (0.00, 0.44, 1.00, 0.62)),
    "element_hem": ("full_body", (0.00, 0.72, 1.00, 0.92)),
    "face_back_hair": ("back", (0.12, 0.00, 0.88, 0.22)),
    "detail_collar": ("portrait", (0.15, 0.55, 0.85, 0.90)),
    "detail_chest": ("full_body", (0.15, 0.16, 0.85, 0.38)),
    "detail_waist_knot": ("full_body", (0.20, 0.36, 0.80, 0.50)),
    "detail_cuff": ("full_body", (0.00, 0.42, 0.50, 0.58)),
    "detail_texture": ("full_body", (0.30, 0.60, 0.70, 0.76)),
    "detail_shoe": ("full_body", (0.10, 0.90, 0.90, 1.00)),
    "detail_eye": ("portrait", (0.18, 0.26, 0.82, 0.48)),
    "detail_accessory": ("full_body", (0.00, 0.30, 1.00, 0.58)),
}


# 右侧 45° 侧脸没画出来时(旧版设定集只有一张 3/4 侧脸)，把左侧 45° 侧脸水平翻转补上。
# 翻转会把痣、疤、分缝换到另一侧，所以它只用来展示、标成补位，不进身份锚点、不当视频参考。
MIRRORED_CELL_SOURCES: dict[str, str] = {"face_three_quarter_right": "face_three_quarter"}


REGION_TITLES: tuple[str, ...] = tuple(
    region.title for region in ACTOR_SHEET_LAYOUT.regions if region.title
)


def actor_sheet_cell_boxes(
    width: int, height: int, layout: ActorSheetLayout = ACTOR_SHEET_LAYOUT
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """按版面把 ``width × height`` 的画布切成 25 个 (key, (left, top, right, bottom)) 像素框。

    纯几何，不读图：这是各格的"预期位置"。切图器在画面里找不到某个身份必需格的
    面板时，就用这里的框兜底。边界一律用同一个 ``round`` 规则从归一化比例算出，
    相邻格子共用边界值——因此标题带以下的 25 个框严格铺满、互不重叠、不留缝。
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
