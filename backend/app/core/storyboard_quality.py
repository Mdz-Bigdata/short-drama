"""Deterministic prompt compilation and storyboard continuity checks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.actor_sheet_layout import ACTOR_SHEET_LAYOUT, FULL_BODY_PROPORTION_RULE
from app.schema.production import NineGridStoryboard, StoryboardPanel


class ContinuityIssue(BaseModel):
    panel_index: int = Field(ge=1, le=9)
    code: str
    message: str


class StoryboardContinuityReport(BaseModel):
    passed: bool
    issues: list[ContinuityIssue]


# 每个子格下方的编号中文标注(画在图上，让每一格自带说明)。顺序与 ACTOR_SHEET_LAYOUT 的格子顺序一致。
_ELEMENT_CAPTIONS = (
    ("鞋履特写", "腰部配饰扣环", "护腕手部配饰", "领口肩部刺绣"),
    ("面料纹理微距", "发饰头饰拆解", "手部姿态", "裙摆下摆刺绣"),
)
_DETAIL_CAPTIONS = (
    ("正脸特写", "左侧45°侧脸", "右侧45°侧脸"),
    ("后脑发饰", "领口肩颈", "前襟胸部纹样"),
    ("腰部束结", "袖口末端", "材质纹理微距"),
    ("鞋履足部", "眼部妆容微距", "动态姿态或小配件"),
)


def _numbered(rows: tuple[tuple[str, ...], ...]) -> list[str]:
    """把各行标注编成「第一行：1. A、2. B；」的连续编号。"""
    lines, number = [], 1
    ordinals = "一二三四五六七八九"
    for index, row in enumerate(rows):
        items = []
        for caption in row:
            items.append(f"{number}. {caption}")
            number += 1
        lines.append(f"第{ordinals[index]}行：" + "、".join(items))
    return lines


def build_actor_sheet_prompt(name: str, identity_dna: str, visual_style: str) -> str:
    """把数字演员设定集写成一段可执行的画面描述。

    版面数字、网格形状和三栏标题全部取自 ACTOR_SHEET_LAYOUT，切图器读的是同一份常量。
    结构按用户给定的设定集提示词组织：全局画布 → 左栏主肖像 → 中栏全身与元素(中左全身立绘、
    中右三视图与 2×4 元素) → 右栏 4×3 细节矩阵 → 全局排版规则；每个子格下方一行编号中文标注。

    刻意只写画面本身：没有 markdown、没有元指令、不引用任何文档。
    原因见 model_gateway.generate_character_sheet 的注释——把方法论文档塞进文生图
    模型会被内容审核判 content_policy_violation，整批设定图直接全灭。
    """
    layout = ACTOR_SHEET_LAYOUT
    portrait_title, middle_title, details_title = (
        region.title for region in layout.regions if region.title
    )
    left = round(layout.left_portrait_width * 100)
    middle = round(layout.middle_width * 100)
    right = round(layout.right_details_width * 100)
    mid_left = round(layout.middle_inner_split * 100)
    mid_right = 100 - mid_left
    three_rows, three_columns = layout.three_view_grid
    element_rows, element_columns = layout.element_grid
    detail_rows, detail_columns = layout.detail_matrix_grid
    element_lines = "；".join(_numbered(_ELEMENT_CAPTIONS))
    detail_lines = "；".join(_numbered(_DETAIL_CAPTIONS))
    return (
        f"【全局画布与背景】为角色{name}制作一张{layout.aspect_ratio_label}超宽横向全景的数字演员设定集，"
        "专业角色设计参考图风格，同一人物、同一服装、同一发型、同一体型。"
        "背景为平滑的高级灰白渐变，边缘浅灰向中心纯白过渡，无任何环境杂物。"
        "画面采用严格的网格化排版，用极细的纯白间隔线精准分割各个区域；"
        "左、中、右三栏顶部各居中一行深灰色无衬线中文标题，"
        f"依次为「{portrait_title}」「{middle_title}」「{details_title}」，标题只写中文，不写英文，"
        "标题下方留一条白色间隔再开始画格子。"
        f"【左栏：{portrait_title}】占画面最左侧约{left}%宽度，垂直贯穿上下，右侧由一条细白竖线与中栏分隔。"
        "只放一张超大尺寸的人物正面近景特写，头部到胸部以上，主体绝对居中，"
        "重点展现五官、妆容、发型结构和头饰正面效果；静态标准展示，眼神平视镜头，光影立体柔和，"
        "头顶和下巴完整留在画面里。"
        f"【中栏：{middle_title}】占画面中央约{middle}%宽度，垂直贯穿上下，"
        "内部由一条细白竖线分为中左与中右两个子板块。"
        f"中左占中栏宽度约{mid_left}%：一张完整的正面全身立绘，人物自然站立，"
        "完整展示服装垂坠感、鞋履与手持道具，头顶到双脚完整，脚底对齐画面底部基准线。"
        f"中右占中栏宽度约{mid_right}%，由一条细白横线分为上下两部分。"
        f"上部是{three_rows}行×{three_columns}列三格等宽的全身视图，从左到右依次为正面全身、90度标准侧面全身、背面全身，"
        "三张与中左立绘比例尺严格一致，脚底在同一条基线上、头顶在同一高度，"
        f"全身立绘与三视图的{FULL_BODY_PROPORTION_RULE}"
        "每张下方居中一行小号深灰中文标注：正视图、侧视图、背视图。"
        f"下部是{element_rows}行×{element_columns}列共{element_rows * element_columns}个等尺寸子格的元素拆解特写，"
        f"行列之间以细白线均匀分隔，内容与每格下方的编号标注依次为：{element_lines}。"
        f"【右栏：{details_title}】占画面最右侧约{right}%宽度，垂直贯穿上下，左侧由一条细白竖线与中栏分隔。"
        f"严格的{detail_rows}行×{detail_columns}列网格，共{detail_rows * detail_columns}个等尺寸子格，"
        f"行列之间以细白线均匀分隔，内容与每格下方的编号标注依次为：{detail_lines}。"
        "第一行三张脸部特写同一景别、同一光线：正脸直视镜头，左侧45°是人物脸转向画面左侧，"
        "右侧45°是人物脸转向画面右侧，三张都完整露出五官与发际线。"
        "【全局排版规则】三栏高度统一对齐，所有子图与子格之间保留均匀的纯白间隙，不重叠、不粘连、不合并、不错位；"
        "每格里的人物或物件完整落在格子内，不被格子边缘切断脸部；"
        "每个子格的编号标注写在该格图片下方的白色间隙里，不压在图片上。"
        "视觉流向从左到右、从上到下逻辑递进，呈现严谨专业的标准化设定集风格，高质量，高分辨率，极致细节。"
        f"身份DNA：{identity_dna}。视觉风格：{visual_style}。"
        "全部格子必须是同一个人物，不得改变脸型、五官比例、痣与疤的位置、发际线、"
        "发型、服装、配饰和身材；同焦段、同相机高度、同中性光。"
        "除三栏标题和各格编号标注外，禁止出现任何文字、标签、水印和 logo；"
        "禁止出现第二个人物、额外肢体、多余手指、裁切脚部和场景道具。"
    )


def build_nine_grid_prompt(board: NineGridStoryboard) -> str:
    """Compile a board to a single precise 3x3 generation prompt."""
    assets = board.assets
    lines = [
        f"生成《{board.title}》的单张3×3九宫格电影分镜图。",
        f"这是第{board.page_number}/{board.total_pages}页；严格三行三列、九格等大、边界清晰，"
        f"按照从左到右、从上到下读取。本页只有{len(board.panels)}个真实拍点，"
        f"其余{board.empty_slots}格保持纯留白；禁止合并格子、重复、镜像或补造拍点。",
        "每格只呈现一个新的叙事信息或情绪强度；先建立地点，再建立人物关系，最后靠近关键情绪；默认远景→中景→近景，但以叙事目的优先。",
        f"【节奏类型】{board.rhythm_profile}。对峙使用慢→快→慢并在爆点后停顿；反转先稳定铺垫、证据加速、反应停留；"
        "悬疑慢揭细节并延迟真相；动作先建立空间再快切并慢放关键击打；喜剧保留反应停顿；线索须尽早出现。",
        "【目的选镜】information用远/中/双人；emotion用近/极近/慢推；suspense用遮挡/POV/物件插入；"
        "tension用手持/反应切/低机位；reversal用证据极近、停顿与反应；shock用空镜/长廊剪影/切黑；clue用手部极近与前后对比。",
        f"【角色】{ '、'.join(assets.characters) }",
        f"【场景】{ '、'.join(assets.scenes) }",
        f"【道具】{ '、'.join(assets.props) }",
        f"【特效】{ '、'.join(assets.effects) }",
        "九格统一角色身份、服装、场景布局、摄影轴线、道具归属、光向与色温；写实真人电影质感，皮肤纹理和微表情自然。",
    ]
    for panel in board.panels:
        mode_label = {
            "auto": "模型自动判断",
            "text": "文本",
            "first_frame": "首帧",
            "last_frame": "尾帧",
            "first_last_frame": "首尾帧",
            "reference": "多模态参考",
        }[panel.generation_mode]
        lines.append(
            f"第{panel.index}格｜目的:{panel.shot_purpose}｜节拍:{panel.story_beat}｜{panel.duration_seconds:g}秒｜"
            f"人物：{'、'.join(panel.characters)}｜{panel.shot_size}｜{panel.lens_mm}mm {panel.aperture}｜"
            f"{panel.camera_angle}｜{panel.camera_movement}；运镜动机：{panel.camera_reason}；"
            f"构图：{panel.composition}；轴线：{panel.action_axis}；视线：{panel.eyeline}；"
            f"场景：{panel.scene}；动作：{panel.subject_action}；表演：{panel.expression}；"
            f"道具：{'、'.join(panel.props)}；特效：{'、'.join(panel.effects)}；"
            f"调度：{panel.blocking}；灯光：{panel.lighting}；生成模式：{mode_label}；"
            f"开始状态：{panel.start_state}；结束状态：{panel.end_state}；"
            f"声音意图：{panel.sound}；入剪：{panel.edit_in}；出剪：{panel.edit_out}；"
            f"入格连续性：{panel.continuity_in or '建立镜头'}；"
            f"出格连续性：{panel.continuity_out}。"
        )
    for index in range(len(board.panels) + 1, 10):
        lines.append(f"第{index}格｜纯留白空格；不得复制、延伸或补造任何叙事拍点。")
    lines.append(
        "不要在画面内生成镜号、说明文字或字幕；用清晰分隔线表达九宫格结构。"
    )
    return "\n".join(lines)


def validate_storyboard_continuity(
    panels: list[StoryboardPanel],
) -> StoryboardContinuityReport:
    issues: list[ContinuityIssue] = []
    for panel in panels:
        if panel.index > 1 and not panel.continuity_in.strip():
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_continuity_in",
                message="非首格必须声明如何承接上一格的动作、站位或视线。",
            ))
        if not panel.props:
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_prop_state",
                message="每格必须声明关键道具，确无道具时显式写‘无关键道具’。",
            ))
        if not panel.effects:
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_effect_state",
                message="每格必须声明特效/环境动态，确无特效时显式写‘无特效’。",
            ))
    return StoryboardContinuityReport(passed=not issues, issues=issues)
