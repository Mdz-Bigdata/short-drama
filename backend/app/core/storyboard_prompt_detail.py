"""Adapt an approved nine-grid board to the universal storyboard prompt contract."""

from __future__ import annotations

import re

from app.core.storyboard_director import StoryboardDirectorCompiler
from app.schema.production import NineGridStoryboard
from app.schema.storyboard_director import (
    CameraDesign,
    ColorDesign,
    ContinuityLocks,
    DirectorCharacter,
    DirectorProp,
    DirectorScene,
    DynamicsDesign,
    GlobalVisualRules,
    ShotVisualDesign,
    StoryboardDirectorRequest,
    StoryboardDirectorResult,
    StoryEvent,
    TimedDialogue,
    TransitionDesign,
    TransitionEdge,
)


_SPEAKER_LINE = re.compile(r"^([^：:]{1,40})[：:]\s*(.+)$")


def _clip(value: str, limit: int = 4_000) -> str:
    text = " ".join((value or "").replace("\x00", "").split()).strip()
    if not text:
        return "未提供（需确认）"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _dialogue_parts(value: str, fallback_speaker: str) -> tuple[str, str, str]:
    raw = " ".join((value or "").split()).strip()
    match = _SPEAKER_LINE.match(raw)
    speaker = match.group(1).strip() if match else fallback_speaker
    exact = (match.group(2) if match else raw).strip().strip('“”"\'')
    if "旁白" in speaker:
        kind = "narration"
    elif "内心" in speaker or "独白" in speaker:
        kind = "inner_monologue"
    else:
        kind = "dialogue"
    return kind, speaker or fallback_speaker, exact


def compile_storyboard_prompt_detail(
    board: NineGridStoryboard,
    *,
    script_text: str,
    visual_style: str,
    episode: str = "第1集",
    character_profiles: dict[str, str] | None = None,
) -> StoryboardDirectorResult:
    """Compile every field required by the attached universal prompt template."""

    profiles = character_profiles or {}
    panels = board.panels
    first = panels[0]
    last = panels[-1]
    duration = round(sum(panel.duration_seconds for panel in panels), 3)
    characters = [
        DirectorCharacter(
            name=name,
            identity="本场主要角色",
            age_impression="继承已批准角色资产",
            appearance=_clip(profiles.get(name) or f"严格继承{name}的角色五视图、脸型、五官与发型"),
            costume=f"严格继承{name}当前场次的服装款式、颜色、材质与污损状态",
            accessories="继承角色资产中的固定配饰及佩戴位置",
            physical_state="承接剧本与上一镜确定的身体、伤势、污渍和疲劳状态",
            psychological_state="只通过本页各拍点定义的表情、眼神、呼吸和重心呈现",
        )
        for name in board.assets.characters
    ]
    props = [
        DirectorProp(
            name=name,
            initial_state="保持剧本首次可见状态与材质",
            initial_position=f"按第1格场景调度锁定{name}的位置与持有者",
            allowed_motion="仅按逐拍动作与连续性定义移动",
        )
        for name in board.assets.props
    ]

    events: list[StoryEvent] = []
    timed_dialogue: list[TimedDialogue] = []
    cursor = 0.0
    fallback_speaker = board.assets.characters[0]
    for panel in panels:
        panel_end = round(cursor + panel.duration_seconds, 3)
        if panel.dialogue.strip():
            kind, speaker, exact = _dialogue_parts(panel.dialogue, fallback_speaker)
            if exact:
                events.append(StoryEvent(
                    kind=kind,
                    text=panel.subject_action,
                    speaker=speaker,
                    exact_text=exact,
                    observable_pose=f"{panel.subject_action}；{panel.expression}",
                    prop_change=f"道具仅按本拍动作变化：{'、'.join(panel.props)}",
                ))
                timed_dialogue.append(TimedDialogue(
                    kind=kind,
                    speaker=speaker,
                    exact_text=exact,
                    start_seconds=round(cursor, 3),
                    end_seconds=panel_end,
                ))
            else:
                events.append(StoryEvent(
                    kind="action",
                    text=panel.subject_action,
                    observable_pose=f"{panel.subject_action}；{panel.expression}",
                    prop_change=f"道具仅按本拍动作变化：{'、'.join(panel.props)}",
                ))
        else:
            events.append(StoryEvent(
                kind="action",
                text=panel.subject_action,
                observable_pose=f"{panel.subject_action}；{panel.expression}",
                prop_change=f"道具仅按本拍动作变化：{'、'.join(panel.props)}",
            ))
        cursor = panel_end

    unique_sizes = "→".join(dict.fromkeys(panel.shot_size for panel in panels))
    unique_movements = "、".join(dict.fromkeys(panel.camera_movement for panel in panels))
    unique_angles = "、".join(dict.fromkeys(panel.camera_angle for panel in panels))
    light_plan = "；".join(dict.fromkeys(panel.lighting for panel in panels))
    scene_plan = "；".join(dict.fromkeys(panel.scene for panel in panels))
    prop_plan = "；".join(
        f"{item.name}：{item.initial_position}，{item.initial_state}" for item in props
    )
    narrative_goal = _clip("；".join(panel.story_beat for panel in panels))

    request = StoryboardDirectorRequest(
        project_name=board.title,
        episode=episode,
        scene_number=board.scene_number,
        shot_number=f"E1S{board.scene_number:02d}",
        duration_seconds=duration,
        aspect_ratio="9:16",
        fps=24,
        script_text=_clip(script_text, 100_000),
        narrative_goal=narrative_goal,
        characters=characters,
        scene=DirectorScene(
            time="继承剧本当前时段、季节与年代",
            location=_clip(board.assets.scenes[0], 500),
            weather="继承剧本与场景圣经；未说明时保持稳定",
            spatial_structure=_clip(
                f"{scene_plan}；固定前中后景、门窗/出入口、人物站位与摄影机轴线；"
                f"首拍调度：{first.blocking}"
            ),
            props=props,
            environmental_sound=_clip("；".join(dict.fromkeys(panel.sound for panel in panels)), 500),
        ),
        timed_dialogue=timed_dialogue,
        events=events,
        global_visual=GlobalVisualRules(
            visual_style=_clip(visual_style),
            era_and_region="严格继承剧本时代、地域文化和已批准美术资产",
            art_direction="建筑、服装、道具、角色五视图与场景圣经均为硬约束",
            rendering_texture="真人电视剧电影摄影质感，可信材质、自然皮肤纹理、受控景深与细颗粒",
            authenticity="原创虚拟角色，不冒用真人身份；参考图只锁定外观，不复制排版",
            overall_atmosphere=_clip(f"按{board.rhythm_profile}节奏服务本页叙事目标：{narrative_goal}", 500),
        ),
        continuity=ContinuityLocks(
            face_anchor="；".join(f"{item.name}：{item.appearance}" for item in characters),
            body_anchor="保持角色五视图确定的身高感、肩宽、体型和身体比例",
            costume_anchor="；".join(f"{item.name}：{item.costume}" for item in characters),
            accessory_anchor="；".join(f"{item.name}：{item.accessories}" for item in characters),
            wound_and_stain_anchor="伤痕、破损、湿度和污渍严格承接上一拍，不无故增减",
            scene_structure=_clip(scene_plan),
            prop_positions=_clip(prop_plan),
            key_light_direction=_clip(light_plan, 500),
            camera_axis=_clip("；".join(dict.fromkeys(panel.action_axis for panel in panels)), 500),
            screen_direction=_clip("；".join(dict.fromkeys(panel.eyeline for panel in panels)), 500),
            spatial_orientation=_clip("；".join(dict.fromkeys(panel.blocking for panel in panels))),
        ),
        shot_visual=ShotVisualDesign(
            base_content=_clip(
                f"角色{'、'.join(board.assets.characters)}位于{scene_plan}，"
                f"关键道具{'、'.join(board.assets.props)}，特效/环境动态{'、'.join(board.assets.effects)}"
            ),
            composition=_clip("；".join(dict.fromkeys(panel.composition for panel in panels))),
            shot_size=_clip(unique_sizes, 500),
            lens=f"{min(panel.lens_mm for panel in panels)}—{max(panel.lens_mm for panel in panels)}mm，按拍点叙事目的连续变化",
            camera_angle=_clip(unique_angles, 500),
            camera_height="保持既定人物视线与拍摄轴线高度，除非拍点明确改变",
            depth_of_field=f"以{first.aperture}为基础，主体与关键道具清晰、空间关系可读",
            spatial_layers="前景遮挡受控；中景承载人物动作；背景保持场景结构和主光方向稳定",
        ),
        color=ColorDesign(
            primary_color="继承场景主光与环境占比最高的主色",
            secondary_color="继承服装、道具与环境的辅助色",
            accent_color="关键道具、眼神高光或叙事焦点色",
            color_temperature=_clip(light_plan, 500),
            saturation="中低饱和度，保持精品短剧电影质感",
            brightness="按场景圣经保持稳定曝光",
            contrast="主体可读的受控对比度",
            blacks_and_highlights="黑位保留层次，高光不溢出，硬边光仅用于叙事焦点",
            skin_tone_strategy="自然肤色，局部只受既定主辅光影响",
            grading_reference="真人电视剧电影调色，色彩系统统一",
            start_state=_clip(first.lighting, 500),
            change_reason="仅由人物移动、光源变化、遮挡或剧本明确事件驱动",
            peak_state=_clip(panels[min(len(panels) - 1, len(panels) // 2)].lighting, 500),
            end_state=_clip(last.lighting, 500),
        ),
        dynamics=DynamicsDesign(
            subject_direction="服从既定屏幕方向、人物视线和每拍动作目标",
            subject_trajectory="沿场景结构允许的直线、自然弧线或重力轨迹",
            force_source="人物主动发力、重力、接触反作用力或剧本明确环境力",
            speed_curve="准备—缓起—发展—峰值—自然减速—收束",
            center_of_gravity="随动作真实转移，不瞬移、不重置、不无过程换脚",
            visual_flow="观众视线从动作发起者移动至动作目标、道具或反应者",
            secondary_motion="衣摆、发丝、铁链、尘埃和环境动态只响应主体动作或真实环境力",
            inertia_and_follow_through="动作结束保留符合速度、质量和材质的惯性、回落与余振",
            motion_blur="仅快速运动部位允许轻微动态模糊，身份锚点不得模糊",
            stable_regions="角色面部、手部关键姿态、身份锚点和关键道具保持清晰稳定",
        ),
        camera=CameraDesign(
            movement_type=_clip(unique_movements, 500),
            start_position=f"第1拍机位：{first.camera_angle}；{first.composition}",
            end_position=f"末拍机位：{last.camera_angle}；{last.composition}",
            path="沿既定轴线一侧连续移动，不穿越人物、道具或场景实体",
            direction="服从主体动线、视线方向和连续性锁定",
            speed_curve="缓入—随叙事强度调整—缓出；禁止无原因急停或速度跳变",
            subject_following="保持核心角色、动作与关键道具可读，必要时延迟跟随以交付反应",
            composition_change=_clip("；".join(panel.composition for panel in panels)),
            focus_change="按动作信息在人物眼神、手部和关键道具间平滑跟焦或转焦",
            stability="以稳定器/固定机位为基准，仅在剧本明确时使用受控手持微动",
            forbidden_behaviors="禁止随机旋转、突然推近、无动机变焦、越轴、镜像翻转和构图漂移",
        ),
        transitions=TransitionDesign(
            entry=TransitionEdge(
                adjacent_shot="上一页/上一镜或无",
                transition_type="按剧本选择硬切、声音先行或动作匹配",
                visual_handoff=first.edit_in,
                audio_handoff=f"以{first.sound}承接入场",
                duration_seconds=0,
                included_in_shot_duration=False,
            ),
            internal_linkage="后一拍从上一拍结束姿态自然继续；动作速度、屏幕方向、站位、道具、声音与光影连续",
            exit=TransitionEdge(
                adjacent_shot="下一页/下一镜或无",
                transition_type="按剧本选择硬切、声音延续、遮挡或匹配剪辑",
                visual_handoff=last.edit_out,
                audio_handoff=f"以{last.sound}向下一镜交接",
                duration_seconds=0,
                included_in_shot_duration=False,
            ),
        ),
        max_total_beats=90,
    )
    return StoryboardDirectorCompiler().compile(request)
