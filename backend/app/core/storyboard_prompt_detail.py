"""Adapt an approved nine-grid board to the universal storyboard prompt contract."""

from __future__ import annotations

import re

from app.core import fight_design, prompt_data
from app.core.frame_position import FramePosition, parse_frame_positions
from app.core.storyboard_director import StoryboardDirectorCompiler, landmark_is_anchored
from app.core.transition_catalog import normalize_transition_type, transition_label, smooth_text
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


# Every sentence, word table and pattern this adapter writes into the template's fields:
# app/data/prompt/storyboard_prompt_detail.json. The code only picks values off the board.
_DATA = "storyboard_prompt_detail"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_DATA)["says"][key]).format(**values)


def _mark(key: str) -> str:
    return str(prompt_data.load(_DATA)["marks"][key])


def _pattern(key: str) -> re.Pattern[str]:
    return re.compile(str(prompt_data.load(_DATA)["patterns"][key]))


_SPEAKER_LINE = _pattern("speaker_line")
_SOUND_SPLIT = _pattern("sound_split")
# Only multi-character damage terms: a lone 血 also matches titles such as 血碑, and a
# false entry here would invite the model to add stains the script never wrote.
_DAMAGE_TERMS = prompt_data.words(_DATA, "damage_terms")
# Panel character names that denote a group rather than a profiled individual.
_CROWD_MARKERS = prompt_data.words(_DATA, "crowd_markers")
_EMPTY_NAMES = {EMPTY_ACTOR, *prompt_data.words(_DATA, "empty_names")}
_NARRATION_MARKERS = prompt_data.words(_DATA, "narration_markers")
_INNER_MARKERS = prompt_data.words(_DATA, "inner_markers")
_FAR_SOUND_TERMS = prompt_data.words(_DATA, "far_sound_terms")
_MID_SOUND_TERMS = prompt_data.words(_DATA, "mid_sound_terms")
_DEFAULT_EPISODE = _says("default_episode")
_LIST = _mark("list")
_CLAUSES = _mark("clause")


def _clip(value: str, limit: int = 4_000) -> str:
    text = " ".join((value or "").replace("\x00", "").split()).strip()
    if not text:
        return _says("missing")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _dialogue_parts(value: str, fallback_speaker: str) -> tuple[str, str, str]:
    raw = " ".join((value or "").split()).strip()
    match = _SPEAKER_LINE.match(raw)
    speaker = match.group(1).strip() if match else fallback_speaker
    exact = (match.group(2) if match else raw).strip().strip('“”"\'')
    if any(marker in speaker for marker in _NARRATION_MARKERS):
        kind = "narration"
    elif any(marker in speaker for marker in _INNER_MARKERS):
        kind = "inner_monologue"
    else:
        kind = "dialogue"
    return kind, speaker or fallback_speaker, exact


def _transition_type(hint: str, *, default: str) -> str:
    """Catalog type named by the panel's edit hint; unnamed hints fall back to a continuous match transition."""
    kind, matched = normalize_transition_type(hint)
    return _clip(_says("transition_named", label=transition_label(kind), hint=smooth_text(hint.strip())), 500) if matched and hint.strip() else default


def _narrative_goal(board: NineGridStoryboard) -> str:
    """Summarise the page's causal arc without repeating all nine slot labels."""

    actions = list(dict.fromkeys(_clip(panel.subject_action, 160) for panel in board.panels))
    if len(actions) == 1:
        return actions[0]
    if len(actions) == 2:
        return f"{actions[0]} → {actions[1]}"
    return f"{actions[0]} → {actions[len(actions) // 2]} → {actions[-1]}"


# 第 5 阶段按分镜表重新编译视频提示词，这几段从不发给任何模型；留在场景板上只会让人照着不会生效的内容审稿。
UNSENT_DETAIL_SECTIONS = ("still_prompts", "video_segments", "grid_pages")


def storable_prompt_detail(detail: object) -> object:
    """场景板上要留的那部分：拍点、基础设定和连续性检查。"""
    if not isinstance(detail, dict):
        return detail
    return {key: value for key, value in detail.items() if key not in UNSENT_DETAIL_SECTIONS}


def compile_storyboard_prompt_detail(
    board: NineGridStoryboard,
    *,
    script_text: str,
    visual_style: str,
    episode: str = _DEFAULT_EPISODE,
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
        if name.strip() and name not in _EMPTY_NAMES
    ))
    characters = [
        DirectorCharacter(
            name=name,
            identity=_says("character_identity"),
            age_impression=_says("character_age"),
            appearance=_clip(profiles.get(name) or _says("character_appearance", name=name)),
            costume=_clip(_CLAUSES.join(
                _says("named_item", name=item["name"], description=item.get("description", ""))
                for item in production.get("costumes", [])
                if name in f"{item['name']} {item.get('description', '')}"
            ) or _says("character_costume", name=name)),
            accessories=_says("character_accessories"),
            physical_state=_says("character_physical_state"),
            psychological_state=_says("character_psychological_state"),
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
            initial_state=_clip(
                next((item.get("description") for item in production.get("props", []) if item["name"] == name), "") or _says("prop_initial_state")
            ),
            initial_position=_says("prop_initial_position", name=name),
            allowed_motion=_says("prop_allowed_motion"),
        )
        for name in active_prop_names
    ]

    events: list[StoryEvent] = []
    timed_dialogue: list[TimedDialogue] = []
    cursor = 0.0
    fallback_speaker = active_character_names[0] if active_character_names else _says("narrator")
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
                    observable_pose=_says("observable_pose", action=panel.subject_action, expression=panel.expression),
                    prop_change=_says("prop_change", props=_LIST.join(panel.props)),
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
                    observable_pose=_says("observable_pose", action=panel.subject_action, expression=panel.expression),
                    prop_change=_says("prop_change", props=_LIST.join(panel.props)),
                ))
        else:
            events.append(StoryEvent(
                kind="action",
                text=panel.subject_action,
                observable_pose=_says("observable_pose", action=panel.subject_action, expression=panel.expression),
                prop_change=_says("prop_change", props=_LIST.join(panel.props)),
            ))
        cursor = panel_end

    # Article-style timelines: every sound cue and every stain change is dated, and
    # the closure rule forbids anything the table does not list.
    timed_sounds: list[TimedSound] = []
    damage_timeline: list[DamageTimelineEntry] = []
    cursor = 0.0
    for panel in panels:
        panel_end = round(cursor + panel.duration_seconds, 3)
        sound = _clip(panel.sound.strip() or _says("default_sound"), 500)
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
                panel.props[0] if panel.props else _says("damage_subject_default"),
            )
            damage_timeline.append(DamageTimelineEntry(
                seconds=round(cursor, 3),
                subject=subject[:120],
                change=_clip(_says("beat_action", index=panel.index, action=panel.subject_action), 500),
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
            label=_clip(_LIST.join(crowd_names), 500),
            initial_distribution=_clip(
                _says("extras_distribution", blocking=crowd_panels[0].blocking, composition=crowd_panels[0].composition)
            ),
            motion_parameters=_clip(_CLAUSES.join(dict.fromkeys(
                _says("beat_action", index=panel.index, action=panel.subject_action) for panel in crowd_panels
            ))),
        )

    # Landmarks are only emitted from descriptions that already carry a bearing and a
    # distance; a placeholder position would be worse than none.
    landmarks = [
        SceneLandmark(
            name=str(item["name"])[:120],
            relative_position=_clip(str(item.get("relative_position") or ""), 500),
            form_and_count=_clip(str(item.get("form_and_count") or _says("landmark_form_default")), 500),
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
        piece.strip() for panel in panels for piece in _SOUND_SPLIT.split(panel.sound) if piece.strip()
    ):
        if any(term in cue for term in _FAR_SOUND_TERMS):
            far_cues.append(cue)
        elif any(term in cue for term in _MID_SOUND_TERMS):
            mid_cues.append(cue)
        else:
            near_cues.append(cue)
    sound_design = SoundDesign(
        near=_clip(_LIST.join(near_cues), 500) if near_cues else SoundDesign().near,
        mid=_clip(_LIST.join(mid_cues), 500) if mid_cues else SoundDesign().mid,
        far=_clip(_LIST.join(far_cues), 500) if far_cues else SoundDesign().far,
    )

    # Screen-coordinate positions: measured on the spatial stage, else from the first panel that states them.
    frame_positions = [
        FramePosition.model_validate(item) for item in spatial.get("frame_positions") or [] if isinstance(item, dict)
    ][:30] or next(
        (
            found for found in (
                parse_frame_positions(
                    _says("frame_position_text", composition=panel.composition, blocking=panel.blocking, eyeline=panel.eyeline),
                    active_character_names,
                )
                for panel in panels
            ) if found
        ),
        [],
    )

    unique_sizes = "→".join(dict.fromkeys(panel.shot_size for panel in panels))
    unique_movements = _LIST.join(dict.fromkeys(panel.camera_movement for panel in panels))
    unique_angles = _LIST.join(dict.fromkeys(panel.camera_angle for panel in panels))
    light_plan = _CLAUSES.join(dict.fromkeys(panel.lighting for panel in panels))
    scene_plan = _CLAUSES.join(dict.fromkeys(panel.scene for panel in panels))
    if production.get("scenes"):
        scene_plan = _CLAUSES.join(_says("named_item", name=item["name"], description=item.get("description", "")) for item in production["scenes"])
    prop_plan = _CLAUSES.join(
        _says("prop_plan_item", name=item.name, position=item.initial_position, state=item.initial_state) for item in props
    )
    narrative_goal = _narrative_goal(board)
    # A fight page swaps the locked-off camera for one that follows the action: the generic
    # 稳定器/固定机位 stance and the ban on sudden push-ins are what make fights look static.
    fight = board.rhythm_profile == "action" or fight_design.looks_like_fight(
        "\n".join([script_text, *(panel.subject_action for panel in panels)])
    )
    reference_video_role = production.get("reference_video_role")
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
            time=_says("scene_time"),
            location=_clip(board.assets.scenes[0], 500),
            weather=_says("scene_weather"),
            spatial_structure=_clip(
                _says("spatial_structure_bible", scene_plan=scene_plan, bible=spatial["scene_bible"]) if spatial.get("scene_bible") else
                _says("spatial_structure", scene_plan=scene_plan, blocking=first.blocking)
            ),
            landmarks=landmarks,
            props=props,
            environmental_sound=_clip(_CLAUSES.join(dict.fromkeys(panel.sound for panel in panels)), 500),
        ),
        timed_dialogue=timed_dialogue,
        timed_sounds=timed_sounds,
        sound_design=sound_design,
        damage_timeline=damage_timeline,
        extras=extras,
        events=events,
        global_visual=GlobalVisualRules(
            visual_style=_clip(visual_style),
            era_and_region=_says("era_and_region"),
            art_direction=_says("art_direction"),
            rendering_texture=_says("rendering_texture"),
            authenticity=_says("authenticity"),
            **({"reference_video_role": reference_video_role} if reference_video_role in {"appearance", "motion_trajectory"} else {}),
            overall_atmosphere=_clip(_says("overall_atmosphere", rhythm=board.rhythm_profile, goal=narrative_goal), 500),
        ),
        continuity=ContinuityLocks(
            face_anchor=_CLAUSES.join(
                _says("named_item", name=item.name, description=item.appearance) for item in characters
            ) or _says("face_anchor_empty"),
            body_anchor=_says("body_anchor") if characters else _says("body_anchor_empty"),
            costume_anchor=_CLAUSES.join(
                _says("named_item", name=item.name, description=item.costume) for item in characters
            ) or _says("costume_anchor_empty"),
            accessory_anchor=_CLAUSES.join(
                _says("named_item", name=item.name, description=item.accessories) for item in characters
            ) or _says("accessory_anchor_empty"),
            wound_and_stain_anchor=_says("wound_and_stain_anchor"),
            scene_structure=_clip(scene_plan),
            prop_positions=_clip(prop_plan),
            key_light_direction=_clip(light_plan, 500),
            camera_axis=_clip(spatial.get("camera_axis") or _CLAUSES.join(dict.fromkeys(panel.action_axis for panel in panels)), 500),
            screen_direction=_clip(spatial.get("screen_direction") or _CLAUSES.join(dict.fromkeys(panel.eyeline for panel in panels)), 500),
            spatial_orientation=_clip(spatial.get("spatial_orientation") or _CLAUSES.join(dict.fromkeys(panel.blocking for panel in panels))),
        ),
        shot_visual=ShotVisualDesign(
            base_content=_clip(_says(
                "base_content", characters=_LIST.join(active_character_names), scene_plan=scene_plan,
                props=_LIST.join(active_prop_names), effects=_LIST.join(active_effect_names),
            )),
            composition=_clip(_CLAUSES.join(dict.fromkeys(panel.composition for panel in panels))),
            shot_size=_clip(unique_sizes, 500),
            lens=_says("lens", shortest=min(panel.lens_mm for panel in panels), longest=max(panel.lens_mm for panel in panels)),
            camera_angle=_clip(unique_angles, 500),
            camera_height=_says("camera_height"),
            depth_of_field=_says("depth_of_field", aperture=first.aperture),
            spatial_layers=_says("spatial_layers"),
            frame_positions=frame_positions,
        ),
        color=ColorDesign(
            primary_color=_says("primary_color"),
            secondary_color=_says("secondary_color"),
            accent_color=_says("accent_color"),
            color_temperature=_clip(light_plan, 500),
            saturation=_says("saturation"),
            brightness=_says("brightness"),
            contrast=_says("contrast"),
            blacks_and_highlights=_says("blacks_and_highlights"),
            skin_tone_strategy=_says("skin_tone_strategy"),
            grading_reference=_says("grading_reference"),
            start_state=_clip(first.lighting, 500),
            change_reason=_says("color_change_reason"),
            peak_state=_clip(panels[min(len(panels) - 1, len(panels) // 2)].lighting, 500),
            end_state=_clip(last.lighting, 500),
        ),
        dynamics=DynamicsDesign(
            subject_direction=_says("subject_direction"),
            subject_trajectory=_says("subject_trajectory"),
            force_source=_says("force_source"),
            speed_curve=_says("motion_speed_curve_fight") if fight else _says("motion_speed_curve"),
            center_of_gravity=_says("center_of_gravity"),
            visual_flow=_says("visual_flow"),
            secondary_motion=_says("secondary_motion"),
            inertia_and_follow_through=_says("inertia_and_follow_through"),
            motion_blur=_says("motion_blur_fight") if fight else _says("motion_blur"),
            stable_regions=_says("stable_regions"),
        ),
        camera=CameraDesign(
            movement_type=_clip(unique_movements, 500),
            start_position=_clip(_says(
                "camera_start", angle=first.camera_angle,
                position=spatial["camera_start"] if spatial.get("camera_start") else first.composition,
            )),
            end_position=_clip(_says(
                "camera_end", angle=last.camera_angle,
                position=spatial["camera_end"] if spatial.get("camera_end") else last.composition,
            )),
            path=_says("camera_path"),
            direction=_says("camera_direction"),
            speed_curve=_says("camera_speed_curve_fight") if fight else _says("camera_speed_curve"),
            subject_following=_says("subject_following"),
            composition_change=_clip(_CLAUSES.join(panel.composition for panel in panels)),
            focus_change=_says("focus_change"),
            stability=_says("stability_fight") if fight else _says("stability"),
            forbidden_behaviors=_says("forbidden_behaviors_fight") if fight else _says("forbidden_behaviors"),
        ),
        transitions=TransitionDesign(
            entry=TransitionEdge(
                adjacent_shot=_says("entry_adjacent"),
                transition_type=_transition_type(first.edit_in, default=_says("entry_transition")),
                visual_handoff=smooth_text(first.edit_in),
                audio_handoff=_says("entry_audio", sound=first.sound),
                duration_seconds=0,
                included_in_shot_duration=False,
            ),
            internal_linkage=_clip(
                (_says("cut_summary", summary=cuts["summary"]) if cuts.get("summary") else "") + _says("internal_linkage")
            ),
            exit=TransitionEdge(
                adjacent_shot=_says("exit_adjacent"),
                transition_type=_transition_type(last.edit_out, default=_says("exit_transition")),
                visual_handoff=smooth_text(last.edit_out),
                audio_handoff=_says("exit_audio", sound=last.sound),
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
