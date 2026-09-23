"""Deterministic prompt compilation and storyboard continuity checks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.actor_sheet_layout import ACTOR_SHEET_LAYOUT
from app.schema.production import NineGridStoryboard, StoryboardPanel


class ContinuityIssue(BaseModel):
    panel_index: int = Field(ge=1, le=9)
    code: str
    message: str


class StoryboardContinuityReport(BaseModel):
    passed: bool
    issues: list[ContinuityIssue]


def build_actor_sheet_prompt(name: str, identity_dna: str, visual_style: str) -> str:
    """把 25 格数字演员设定集写成一段可执行的画面描述。

    版面数字全部取自 ACTOR_SHEET_LAYOUT，切图器读的是同一份常量，
    所以"提示词里描述的格子"和"切图器裁出来的格子"不可能对不上。

    刻意只写画面本身：没有 markdown、没有元指令、不引用任何文档。
    原因见 model_gateway.generate_character_sheet 的注释——把方法论文档塞进文生图
    模型会被内容审核判 content_policy_violation，整批设定图直接全灭。
    """
    layout = ACTOR_SHEET_LAYOUT
    left = round(layout.left_portrait_width * 100)
    middle = round(layout.middle_width * 100)
    right = round(layout.right_details_width * 100)
    mid_left = round(layout.middle_inner_split * 100)
    mid_right = 100 - mid_left
    three_rows, three_columns = layout.three_view_grid
    element_rows, element_columns = layout.element_grid
    detail_rows, detail_columns = layout.detail_matrix_grid
    return (
        f"为角色{name}制作一张{layout.aspect_ratio_label}超宽横向全景的数字演员设定集，"
        "同一人物、同一服装、同一发型、同一体型。"
        "背景为高级灰白渐变，边缘浅灰向中心纯白过渡，无环境杂物、无地面家具、无场景道具。"
        "整张画面用极细纯白分隔线划成左中右三个等高竖栏，"
        f"左栏占画面宽度{left}%、中栏占{middle}%、右栏占{right}%。"
        "三栏顶部各居中一行深灰色无衬线大写标题："
        "左栏 MAIN PORTRAIT，中栏 FULL BODY & ELEMENTS，右栏 DETAIL MATRIX。"
        "左栏 MAIN PORTRAIT 只放一张正面近景特写，头部到胸部以上，居中、直视镜头。"
        f"中栏内部再用极细纯白分隔线左右分开，左侧占中栏宽度{mid_left}%、右侧占{mid_right}%。"
        "中栏左侧只放一张正面全身立绘，双脚完整、脚底对齐该栏底部基线。"
        f"中栏右侧上半部是{three_rows}行×{three_columns}列共3格全身视图，"
        "从左到右依次是正面全身、90度标准侧面全身、背面全身；"
        "这三张与中栏左侧的立绘同一比例、脚底在同一条基线上、头顶在同一高度。"
        f"中栏右侧下半部是{element_rows}行×{element_columns}列共"
        f"{element_rows * element_columns}格元素拆解特写，"
        "第一行从左到右：鞋履、腰部扣环、护腕与手部配饰、领口与肩部刺绣；"
        "第二行从左到右：面料微距、发饰拆解、手部姿态、裙摆刺绣。"
        f"右栏 DETAIL MATRIX 是{detail_rows}行×{detail_columns}列共"
        f"{detail_rows * detail_columns}格细节特写，"
        "第一行：正脸特写、四分之三侧脸、后脑发饰；"
        "第二行：领口与肩颈、前襟胸部纹样、腰部束结；"
        "第三行：袖口末端、材质微距、背部暗扣与系带；"
        "第四行：鞋履足部、眼妆微距、动态姿态或小配件。"
        "三栏等高，所有子格之间保留均匀的极细白色间隙，格子不重叠、不粘连、不合并、不错位。"
        f"身份DNA：{identity_dna}。视觉风格：{visual_style}。"
        "全部格子必须是同一个人物，不得改变脸型、五官比例、痣与疤的位置、发际线、"
        "发型、服装、配饰和身材；同焦段、同相机高度、同中性光。"
        "禁止出现第二个人物、额外肢体、多余手指、裁切脚部、文字、标注、水印、logo 和场景道具。"
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
