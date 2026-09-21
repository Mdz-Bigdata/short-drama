"""Adapt an approved nine-grid board to the universal storyboard prompt contract."""

from __future__ import annotations

import re

from app.core.frame_position import FramePosition, parse_frame_positions
from app.core.storyboard_director import StoryboardDirectorCompiler, landmark_is_anchored
from app.core.transition_catalog import normalize_transition_type, transition_label
from app.core.storyboard_scene_context import EMPTY_ACTOR
from app.schema.production import NineGridStoryboard
from app.schema.storyboard_director import (
    CameraDesign,
    ColorDesign,
    ContinuityCheckItem,
    ContinuityLocks,
    DamageTimelineEntry,
    DirectorCharacter,
    DirectorExtras,
    DirectorProp,
    DirectorScene,
    DynamicsDesign,
    GlobalVisualRules,
    SceneLandmark,
    ShotVisualDesign,
    SoundDesign,
    StoryboardDirectorRequest,
    StoryboardDirectorResult,
    StoryEvent,
    TimedDialogue,
    TimedSound,
    TransitionDesign,
    TransitionEdge,
)


_SPEAKER_LINE = re.compile(r"^([^：:]{1,40})[：:]\s*(.+)$")
# Only multi-character damage terms: a lone 血 also matches titles such as 血碑, and a
# false entry here would invite the model to add stains the script never wrote.
_DAMAGE_TERMS = (
    "血迹", "血痕", "伤口", "裂口", "裂痕", "污渍", "泥渍", "泥点", "水渍", "汗渍", "破损",
    "撕裂", "撕破", "破洞", "烧焦", "焦痕", "灰尘", "尘土", "淤青", "瘀青", "擦伤", "划痕",
    "溅血", "沾血", "染血", "溅上", "沾上", "弄脏", "磨损", "湿透",
)
# Panel character names that denote a group rather than a profiled individual.
_CROWD_MARKERS = (
    "群演", "众", "们", "士兵", "追兵", "路人", "人群", "敌人", "杂兵", "护卫", "侍卫",
    "家丁", "打手", "军士", "士卒", "小兵", "匪徒", "围观", "群众",
)
_EMPTY_NAMES = {EMPTY_ACTOR, "无", "无人", "无人物", "空镜"}


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


def _transition_type(hint: str, *, default: str) -> str:
    """Catalog type named by the panel's edit hint; unnamed hints fall back to a hard cut."""
    kind, matched = normalize_transition_type(hint)
    return _clip(f"{transition_label(kind)}（{hint.strip()}）", 500) if matched and hint.strip() else default


def _narrative_goal(board: NineGridStoryboard) -> str:
    """Summarise the page's causal arc without repeating all nine slot labels."""

    actions = list(dict.fromkeys(_clip(panel.subject_action, 160) for panel in board.panels))
    if len(actions) == 1:
        return actions[0]
    if len(actions) == 2:
        return f"{actions[0]} → {actions[1]}"
    return f"{actions[0]} → {actions[len(actions) // 2]} → {actions[-1]}"


def compile_storyboard_prompt_detail(
    board: NineGridStoryboard,
    *,
    script_text: str,
    visual_style: str,
    episode: str = "第1集",
    character_profiles: dict[str, str] | None = None,
    scene_id: str | None = None,
    production_context: dict | None = None,
) -> StoryboardDirectorResult:
    """Compile every field required by the attached universal prompt template."""

    profiles = character_profiles or {}
    production = production_context or {}
    # The scene's spatial stage, when the storyboard was solved on one: measured positions and
    # locks replace the prose parse and the fixed wording below.
    spatial = production.get("spatial") if isinstance(production.get("spatial"), dict) else {}
    # The scene's cut plan: what kind of cut joins each pair of shots and what carries across it.
    cuts = production.get("transitions") if isinstance(production.get("transitions"), dict) else {}
    panels = board.panels
    first = panels[0]
    last = panels[-1]
    duration = round(sum(panel.duration_seconds for panel in panels), 3)
    active_character_names = list(dict.fromkeys(
        name
        for panel in panels
        for name in panel.characters
        if name.strip() and name not in {EMPTY_ACTOR, "无", "无人", "无人物", "空镜"}
    ))
    characters = [
        DirectorCharacter(
            name=name,
            identity="本场主要角色",
            age_impression="继承已批准角色资产",
            appearance=_clip(profiles.get(name) or f"严格继承{name}的角色五视图、脸型、五官与发型"),
            costume=_clip("；".join(
                f"{item['name']}：{item.get('description', '')}"
                for item in production.get("costumes", [])
                if name in f"{item['name']} {item.get('description', '')}"
            ) or f"严格继承{name}当前场次的服装款式、颜色、材质与污损状态"),
            accessories="继承角色资产中的固定配饰及佩戴位置",
            physical_state="承接剧本与上一镜确定的身体、伤势、污渍和疲劳状态",
            psychological_state="只通过本页各拍点定义的表情、眼神、呼吸和重心呈现",
        )
        for name in active_character_names
    ]
    active_prop_names = list(dict.fromkeys(
        name
        for panel in panels
        for name in panel.props
        if name.strip()
    )) or board.assets.props
    active_effect_names = list(dict.fromkeys(
        name
        for panel in panels
        for name in panel.effects
        if name.strip()
    )) or board.assets.effects
    props = [
        DirectorProp(
            name=name,
            initial_state=_clip(next((item.get("description") for item in production.get("props", []) if item["name"] == name), "") or "保持剧本首次可见状态与材质"),
            initial_position=f"按第1格场景调度锁定{name}的位置与持有者",
            allowed_motion="仅按逐拍动作与连续性定义移动",
        )
        for name in active_prop_names
    ]

    events: list[StoryEvent] = []
    timed_dialogue: list[TimedDialogue] = []
    cursor = 0.0
    fallback_speaker = active_character_names[0] if active_character_names else "旁白"
    for panel in panels:
        panel_end = round(cursor + panel.duration_seconds, 3)
        if panel.dialogue.strip():
            panel_speaker = next(
                (name.strip() for name in panel.characters if name.strip() and name != EMPTY_ACTOR),
                fallback_speaker,
            )
            kind, speaker, exact = _dialogue_parts(panel.dialogue, panel_speaker)
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

    # Article-style timelines: every sound cue and every stain change is dated, and
    # the closure rule forbids anything the table does not list.
    timed_sounds: list[TimedSound] = []
    damage_timeline: list[DamageTimelineEntry] = []
    cursor = 0.0
    for panel in panels:
        panel_end = round(cursor + panel.duration_seconds, 3)
        sound = _clip(panel.sound.strip() or "环境声与动作声连续", 500)
        if timed_sounds and timed_sounds[-1].description == sound:
            # The same cue across neighbouring beats is one span, not a repeated line.
            timed_sounds[-1] = timed_sounds[-1].model_copy(update={"end_seconds": panel_end})
        else:
            timed_sounds.append(TimedSound(
                start_seconds=round(cursor, 3), end_seconds=panel_end, description=sound,
            ))
        if any(term in f"{panel.subject_action} {panel.end_state}" for term in _DAMAGE_TERMS):
            subject = next(
                (name for name in panel.characters if name.strip() and name not in _EMPTY_NAMES),
                panel.props[0] if panel.props else "场景",
            )
            damage_timeline.append(DamageTimelineEntry(
                seconds=round(cursor, 3),
                subject=subject[:120],
                change=_clip(f"第{panel.index}拍：{panel.subject_action}", 500),
            ))
        cursor = panel_end

    crowd_names = [
        name for name in active_character_names
        if name not in profiles and any(marker in name for marker in _CROWD_MARKERS)
    ]
    extras = None
    if crowd_names:
        crowd_panels = [panel for panel in panels if any(name in panel.characters for name in crowd_names)]
        extras = DirectorExtras(
            label=_clip("、".join(crowd_names), 500),
            initial_distribution=_clip(
                f"按首拍画面分布：{crowd_panels[0].blocking}；{crowd_panels[0].composition}"
            ),
            motion_parameters=_clip("；".join(dict.fromkeys(
                f"第{panel.index}拍：{panel.subject_action}" for panel in crowd_panels
            ))),
        )

    # Landmarks are only emitted from descriptions that already carry a bearing and a
    # distance; a placeholder position would be worse than none.
    landmarks = [
        SceneLandmark(
            name=str(item["name"])[:120],
            relative_position=_clip(str(item.get("relative_position") or ""), 500),
            form_and_count=_clip(str(item.get("form_and_count") or "位置固定"), 500),
        )
        for item in spatial.get("landmarks") or []
        if isinstance(item, dict) and item.get("name") and landmark_is_anchored(str(item.get("relative_position") or ""))
    ]
    staged = {item.name for item in landmarks}
    landmarks += [
        SceneLandmark(name=str(item["name"])[:120], relative_position=_clip(str(item.get("description") or ""), 500))
        for kind in ("props", "scenes")
        for item in production.get(kind, [])
        if isinstance(item, dict) and item.get("name") and str(item["name"])[:120] not in staged
        and landmark_is_anchored(str(item.get("description") or ""))
    ]
    landmarks = landmarks[:50]

    # Near / mid / far layers from the panel sound notes; unlabelled cues are "near".
    near_cues, mid_cues, far_cues = [], [], []
    for cue in dict.fromkeys(
        piece.strip() for panel in panels for piece in re.split(r"[、，,；;]", panel.sound) if piece.strip()
    ):
        if any(term in cue for term in ("远处", "远方", "隐约", "远")):
            far_cues.append(cue)
        elif any(term in cue for term in ("环境", "风", "雨", "底噪", "人群", "街", "虫鸣", "水声", "雷")):
            mid_cues.append(cue)
        else:
            near_cues.append(cue)
    sound_design = SoundDesign(
        near=_clip("、".join(near_cues), 500) if near_cues else SoundDesign().near,
        mid=_clip("、".join(mid_cues), 500) if mid_cues else SoundDesign().mid,
        far=_clip("、".join(far_cues), 500) if far_cues else SoundDesign().far,
    )

    # Screen-coordinate positions: measured on the spatial stage, else from the first panel that states them.
    frame_positions = [
        FramePosition.model_validate(item) for item in spatial.get("frame_positions") or [] if isinstance(item, dict)
    ][:30] or next(
        (
            found for found in (
                parse_frame_positions(
                    f"{panel.composition}。{panel.blocking}。{panel.eyeline}", active_character_names,
                )
                for panel in panels
            ) if found
        ),
        [],
    )

    unique_sizes = "→".join(dict.fromkeys(panel.shot_size for panel in panels))
    unique_movements = "、".join(dict.fromkeys(panel.camera_movement for panel in panels))
    unique_angles = "、".join(dict.fromkeys(panel.camera_angle for panel in panels))
    light_plan = "；".join(dict.fromkeys(panel.lighting for panel in panels))
    scene_plan = "；".join(dict.fromkeys(panel.scene for panel in panels))
    if production.get("scenes"):
        scene_plan = "；".join(f"{item['name']}：{item.get('description', '')}" for item in production["scenes"])
    prop_plan = "；".join(
        f"{item.name}：{item.initial_position}，{item.initial_state}" for item in props
    )
    narrative_goal = _narrative_goal(board)
    episode_match = re.search(r"\d+", episode)
    episode_number = int(episode_match.group()) if episode_match else 1

    request = StoryboardDirectorRequest(
        project_name=board.title,
        episode=episode,
        scene_number=board.scene_number,
        shot_number=scene_id or f"E{episode_number}S{board.scene_number:02d}",
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
                f"{scene_plan}；{spatial['scene_bible']}" if spatial.get("scene_bible") else
                f"{scene_plan}；固定前中后景、门窗/出入口、人物站位与摄影机轴线；"
                f"首拍调度：{first.blocking}"
            ),
            landmarks=landmarks,
            props=props,
            environmental_sound=_clip("；".join(dict.fromkeys(panel.sound for panel in panels)), 500),
        ),
        timed_dialogue=timed_dialogue,
        timed_sounds=timed_sounds,
        sound_design=sound_design,
        damage_timeline=damage_timeline,
        extras=extras,
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
            face_anchor="；".join(f"{item.name}：{item.appearance}" for item in characters) or "空镜，无人物，不生成面孔",
            body_anchor="保持角色五视图确定的身高感、肩宽、体型和身体比例" if characters else "空镜，无人物或肢体",
            costume_anchor="；".join(f"{item.name}：{item.costume}" for item in characters) or "空镜，不添加人物服装",
            accessory_anchor="；".join(f"{item.name}：{item.accessories}" for item in characters) or "空镜，无人物配饰",
            wound_and_stain_anchor="伤痕、破损、湿度和污渍严格承接上一拍，不无故增减",
            scene_structure=_clip(scene_plan),
            prop_positions=_clip(prop_plan),
            key_light_direction=_clip(light_plan, 500),
            camera_axis=_clip(spatial.get("camera_axis") or "；".join(dict.fromkeys(panel.action_axis for panel in panels)), 500),
            screen_direction=_clip(spatial.get("screen_direction") or "；".join(dict.fromkeys(panel.eyeline for panel in panels)), 500),
            spatial_orientation=_clip(spatial.get("spatial_orientation") or "；".join(dict.fromkeys(panel.blocking for panel in panels))),
        ),
        shot_visual=ShotVisualDesign(
            base_content=_clip(
                f"角色{'、'.join(active_character_names)}位于{scene_plan}，"
                f"关键道具{'、'.join(active_prop_names)}，特效/环境动态{'、'.join(active_effect_names)}"
            ),
            composition=_clip("；".join(dict.fromkeys(panel.composition for panel in panels))),
            shot_size=_clip(unique_sizes, 500),
            lens=f"{min(panel.lens_mm for panel in panels)}—{max(panel.lens_mm for panel in panels)}mm，按拍点叙事目的连续变化",
            camera_angle=_clip(unique_angles, 500),
            camera_height="保持既定人物视线与拍摄轴线高度，除非拍点明确改变",
            depth_of_field=f"以{first.aperture}为基础，主体与关键道具清晰、空间关系可读",
            spatial_layers="前景遮挡受控；中景承载人物动作；背景保持场景结构和主光方向稳定",
            frame_positions=frame_positions,
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
            start_position=_clip(
                f"第1拍机位：{first.camera_angle}；{spatial['camera_start']}" if spatial.get("camera_start")
                else f"第1拍机位：{first.camera_angle}；{first.composition}"
            ),
            end_position=_clip(
                f"末拍机位：{last.camera_angle}；{spatial['camera_end']}" if spatial.get("camera_end")
                else f"末拍机位：{last.camera_angle}；{last.composition}"
            ),
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
                transition_type=_transition_type(first.edit_in, default="硬切（承接上一镜动作、视线或声音桥）"),
                visual_handoff=first.edit_in,
                audio_handoff=f"以{first.sound}承接入场",
                duration_seconds=0,
                included_in_shot_duration=False,
            ),
            internal_linkage=_clip(
                f"逐镜衔接：{cuts['summary']}。后一拍从上一拍结束姿态自然继续；动作速度、屏幕方向、站位、道具、声音与光影连续"
                if cuts.get("summary") else
                "后一拍从上一拍结束姿态自然继续；动作速度、屏幕方向、站位、道具、声音与光影连续"
            ),
            exit=TransitionEdge(
                adjacent_shot="下一页/下一镜或无",
                transition_type=_transition_type(last.edit_out, default="硬切（在动作接触、视线落点或对白收音点切出）"),
                visual_handoff=last.edit_out,
                audio_handoff=f"以{last.sound}向下一镜交接",
                duration_seconds=0,
                included_in_shot_duration=False,
            ),
        ),
        max_total_beats=90,
        spatial_checks=[
            ContinuityCheckItem(
                code=str(item.get("code")), passed=bool(item.get("passed")),
                severity="warning" if item.get("severity") == "warning" else "error",
                detail=_clip(str(item.get("detail") or ""), 4_000),
            )
            for item in (spatial.get("checks") or [])[:20] if isinstance(item, dict) and item.get("code")
        ],
        transition_checks=[
            ContinuityCheckItem(
                code=str(item.get("code")), passed=bool(item.get("passed")),
                severity="warning" if item.get("severity") == "warning" else "error",
                detail=_clip(str(item.get("detail") or ""), 4_000),
            )
            for item in (cuts.get("checks") or [])[:20] if isinstance(item, dict) and item.get("code")
        ],
    )
    return StoryboardDirectorCompiler().compile(request)
