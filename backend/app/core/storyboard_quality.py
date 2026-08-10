"""Deterministic prompt compilation and storyboard continuity checks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schema.production import NineGridStoryboard, StoryboardPanel


class ContinuityIssue(BaseModel):
    panel_index: int = Field(ge=1, le=9)
    code: str
    message: str


class StoryboardContinuityReport(BaseModel):
    passed: bool
    issues: list[ContinuityIssue]


def build_five_view_prompt(name: str, identity_dna: str, visual_style: str) -> str:
    """Build one strict five-panel turnaround prompt for a single identity."""
    return (
        f"为角色{name}制作同一人物、同一服装、同一发型、同一体型的五视图角色设定板。"
        "画布严格横向等宽五栏，五个视图按从左到右固定顺序："
        "正面、正面四分之三、标准侧面、背面四分之三、背面。"
        f"身份DNA：{identity_dna}。视觉风格：{visual_style}。"
        "五个视图必须是同一人物，不得改变脸型、五官比例、痣/疤位置、发际线、发型、服装、配饰和身材；"
        "同焦段、同相机高度、同中性光、同纯色背景、完整全身、自然站姿、无遮挡。"
        "禁止重复角度、镜像脸、多人、额外肢体、裁切脚部、文字水印和场景道具。"
    )


def build_nine_grid_prompt(board: NineGridStoryboard) -> str:
    """Compile a board to a single precise 3x3 generation prompt."""
    assets = board.assets
    lines = [
        f"生成《{board.title}》的单张3×3九宫格电影分镜图。",
        "严格三行三列、九格等大、边界清晰，按照从左到右、从上到下读取；禁止合并格子、禁止缺格、禁止重复格。",
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
