"""Deterministic universal storyboard-director compiler.

The compiler treats a prompt template as a data contract. It does not execute
template instructions or submit generation jobs to external providers.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core import prompt_data
from app.core.face_card import fit_face_text_to_framing
from app.core.frame_position import render_frame_positions
from app.core.transition_catalog import describe_transition, normalize_transition_type, smooth_text
from app.schema.storyboard_director import (
    ContinuityCheckItem,
    StoryboardDirectorRequest,
    StoryboardDirectorResult,
    StoryboardGridCell,
    StoryboardGridPage,
    StoryboardTimeBeat,
    StillFramePrompt,
    StoryEvent,
    VideoSegmentPrompt,
)

# The sentences of every prompt and check below, the script labels and the patterns that read a
# script: app/data/prompt/storyboard_director.json.
_WORDING = "storyboard_director"


def _template(entry: Any) -> str:
    """A template as written (an array of lines is joined with newlines)."""
    return "\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)


def _says(key: str, /, **values: object) -> str:
    """A prompt sentence of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return _template(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _check(key: str, /, **values: object) -> str:
    """The detail line of a continuity check, filled in."""
    return _template(prompt_data.load(_WORDING)["checks"][key]).format(**values)


def _word(key: str) -> str:
    """A separator or a fallback phrase, used as it stands."""
    return str(prompt_data.load(_WORDING)["words"][key])


_BRACKET_DIALOGUE = prompt_data.pattern(_WORDING, "bracket_dialogue")
# A landmark only anchors left/right when it states a bearing AND a distance from
# the character ("西偏西南约15米"); a bare place ("路边") lets the frame mirror.
LANDMARK_BEARING = prompt_data.pattern(_WORDING, "landmark_bearing")
LANDMARK_DISTANCE = prompt_data.pattern(_WORDING, "landmark_distance")


def landmark_is_anchored(relative_position: str) -> bool:
    return bool(LANDMARK_BEARING.search(relative_position) and LANDMARK_DISTANCE.search(relative_position))
_INLINE_DIALOGUE = prompt_data.pattern(_WORDING, "inline_dialogue")
_UPPER_CHARACTER = re.compile(r"^[A-Z][A-Z0-9 ._'’-]{0,50}(?:\s*\([^)]*\))?$")
_SCENE_LINE = prompt_data.pattern(_WORDING, "scene_line", re.IGNORECASE)
_META_LABELS = set(prompt_data.words(_WORDING, "meta_labels"))
_LEADING_ASIDE = prompt_data.pattern(_WORDING, "leading_aside")
_ASIDE_OPENS = prompt_data.words(_WORDING, "aside_opens")
_ASIDE_CLOSES = prompt_data.words(_WORDING, "aside_closes")
_SENTENCE_SPLIT = prompt_data.pattern(_WORDING, "sentence_split")
_MILLISECOND = Decimal("0.001")


# A continuation chain keeps only the last few segments in view (Seedance 2.5: about 4–6).
# The space is written out once, then only "同一<场所>" + what changes, and every
# SPACE_SNAPSHOT_EVERY-th segment restates a compact snapshot before the memory runs out.
SPACE_SNAPSHOT_EVERY = 4


def space_restatement(index: int) -> str:
    """``full`` / ``snapshot`` / ``same``: how much of the space segment ``index`` (1-based) restates."""
    if index <= 1:
        return "full"
    return "snapshot" if index % SPACE_SNAPSHOT_EVERY == 0 else "same"


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MILLISECOND, rounding=ROUND_HALF_UP)


def _seconds(value: Decimal) -> float:
    return float(_q(value))


def _clip(value: str, limit: int = 4_000) -> str:
    text = " ".join(value.replace("\x00", "").split()).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class StoryboardDirectorCompiler:
    """Compile one shot into natural beats, still prompts and video segments."""

    def compile(self, request: StoryboardDirectorRequest) -> StoryboardDirectorResult:
        events = self._events(request)
        beats = self._beats(request, events)
        still_prompts = [self._still_prompt(request, beat, len(beats)) for beat in beats]
        video_segments = self._video_segments(request, beats)
        grid_pages = self._grid_pages(request, beats, still_prompts)
        checks = self._continuity_checks(
            request, events, beats, still_prompts, video_segments, grid_pages
        )
        foundation = self._foundation(request)
        canonical = json.dumps(
            {
                "foundation": foundation,
                "beats": [beat.model_dump(mode="json") for beat in beats],
                "still_prompts": [item.model_dump(mode="json") for item in still_prompts],
                "video_segments": [item.model_dump(mode="json") for item in video_segments],
                "grid_pages": [item.model_dump(mode="json") for item in grid_pages],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        warnings = [item.detail for item in checks if not item.passed and item.severity == "warning"]
        return StoryboardDirectorResult(
            project_name=request.project_name,
            episode=request.episode,
            scene_number=request.scene_number,
            shot_number=request.shot_number,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            fps=request.fps,
            foundation=foundation,
            beats=beats,
            still_prompts=still_prompts,
            video_segments=video_segments,
            grid_pages=grid_pages,
            continuity_checks=checks,
            plan_fingerprint=fingerprint,
            submission_ready=not any(
                not item.passed and item.severity == "error" for item in checks
            ),
            warnings=warnings,
        )

    @staticmethod
    def _foundation(request: StoryboardDirectorRequest) -> dict[str, object]:
        return {
            "shot_information": {
                "project_name": request.project_name,
                "episode": request.episode,
                "scene_number": request.scene_number,
                "shot_number": request.shot_number,
                "duration_seconds": request.duration_seconds,
                "aspect_ratio": request.aspect_ratio,
                "fps": request.fps,
                "grid_spec": request.grid_spec,
                "grid_capacity": 9,
                "max_total_beats": request.max_total_beats,
            },
            "narrative_goal": request.narrative_goal,
            "script_text": request.script_text,
            "characters": [item.model_dump(mode="json") for item in request.characters],
            "scene_and_props": request.scene.model_dump(mode="json"),
            "verbatim_dialogue": [item.model_dump(mode="json") for item in request.timed_dialogue],
            "timed_sounds": [item.model_dump(mode="json") for item in request.timed_sounds],
            "sound_design": request.sound_design.model_dump(mode="json"),
            "damage_timeline": [item.model_dump(mode="json") for item in request.damage_timeline],
            # 没有群演就整块不出现，不留空段落。
            **({"extras_and_crowd": request.extras.model_dump(mode="json")} if request.extras else {}),
            "global_visual_rules": request.global_visual.model_dump(mode="json"),
            "continuity_locks": request.continuity.model_dump(mode="json"),
            "shot_visual_design": request.shot_visual.model_dump(mode="json"),
            "color_design": request.color.model_dump(mode="json"),
            "dynamics_design": request.dynamics.model_dump(mode="json"),
            "camera_design": request.camera.model_dump(mode="json"),
            "transition_design": request.transitions.model_dump(mode="json"),
        }

    def _events(self, request: StoryboardDirectorRequest) -> list[StoryEvent]:
        source = request.events or self._parse_script_events(request.script_text)
        events = list(source)
        if not events:
            raise ValueError("script contains no observable action, dialogue, narration, or transition")
        if len(events) > request.max_total_beats:
            raise ValueError("natural narrative beat count exceeds max_total_beats")
        return events

    @staticmethod
    def _parse_script_events(script_text: str) -> list[StoryEvent]:
        events: list[StoryEvent] = []
        pending_speaker = ""
        for raw_line in script_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                pending_speaker = ""
                continue
            if _SCENE_LINE.match(line):
                continue
            bracket = _BRACKET_DIALOGUE.match(line)
            if bracket:
                speaker, exact = bracket.group(1).strip(), bracket.group(2).strip()
                exact = _LEADING_ASIDE.sub("", exact).strip()
                if exact:
                    events.append(StoryEvent(
                        kind="dialogue", speaker=speaker, exact_text=exact,
                        text=_says("dialogue_event", speaker=speaker, exact=exact),
                    ))
                pending_speaker = ""
                continue
            inline = _INLINE_DIALOGUE.match(line)
            if inline and inline.group(1).strip() not in _META_LABELS:
                speaker, exact = inline.group(1).strip(), inline.group(2).strip()
                exact = _LEADING_ASIDE.sub("", exact).strip()
                if exact:
                    events.append(StoryEvent(
                        kind="dialogue", speaker=speaker, exact_text=exact,
                        text=_says("dialogue_event", speaker=speaker, exact=exact),
                    ))
                pending_speaker = ""
                continue
            if inline and inline.group(1).strip() in _META_LABELS:
                pending_speaker = ""
                continue
            if _UPPER_CHARACTER.fullmatch(line):
                pending_speaker = re.sub(r"\s*\([^)]*\)\s*$", "", line).strip()
                continue
            if pending_speaker and not line.startswith(_ASIDE_OPENS):
                events.append(StoryEvent(
                    kind="dialogue", speaker=pending_speaker, exact_text=line,
                    text=_says("dialogue_event", speaker=pending_speaker, exact=line),
                ))
                pending_speaker = ""
                continue
            if line.startswith(_ASIDE_OPENS) and line.endswith(_ASIDE_CLOSES):
                continue
            for sentence in _SENTENCE_SPLIT.split(line):
                sentence = sentence.strip()
                if sentence:
                    events.append(StoryEvent(kind="action", text=sentence))
        return events

    @staticmethod
    def _landmarks(request: StoryboardDirectorRequest) -> str:
        return _word("list_separator").join(
            _says("landmark", name=item.name, relative_position=item.relative_position, form_and_count=item.form_and_count)
            for item in request.scene.landmarks
        )

    @staticmethod
    def _space_snapshot(request: StoryboardDirectorRequest) -> str:
        """Landmark sides and distances without their form notes: the compact restatement of the set."""
        return _word("list_separator").join(
            _says("landmark_snapshot", name=item.name, relative_position=item.relative_position)
            for item in request.scene.landmarks
        )

    @staticmethod
    def _key_light(request: StoryboardDirectorRequest) -> str:
        return _says(
            "key_light", direction=request.continuity.key_light_direction,
            color_temperature=request.color.color_temperature,
        )

    @staticmethod
    def _damage_until(request: StoryboardDirectorRequest, seconds: float) -> str:
        return _word("list_separator").join(
            _says("damage_entry", seconds=entry.seconds, subject=entry.subject, change=entry.change)
            for entry in request.damage_timeline
            if entry.seconds <= seconds
        )

    @staticmethod
    def _damage_between(request: StoryboardDirectorRequest, start: float, end: float) -> str:
        return _word("list_separator").join(
            _says("damage_entry", seconds=entry.seconds, subject=entry.subject, change=entry.change)
            for entry in request.damage_timeline
            if start < entry.seconds <= end
        )

    @staticmethod
    def _sounds_between(request: StoryboardDirectorRequest, start: float, end: float) -> str:
        return _word("list_separator").join(
            _says("sound_cue", start=sound.start_seconds, end=sound.end_seconds, description=sound.description)
            for sound in request.timed_sounds
            if sound.start_seconds < end and sound.end_seconds > start
        )

    @staticmethod
    def _extras_line(request: StoryboardDirectorRequest) -> str:
        extras = request.extras
        if extras is None:
            return ""
        return _says(
            "extras_line", label=extras.label, initial_distribution=extras.initial_distribution,
            motion_parameters=extras.motion_parameters, hit_reaction_rules=extras.hit_reaction_rules,
            stagger_seconds=extras.stagger_seconds, reference_note=extras.reference_note,
        ) + "\n"

    @staticmethod
    def _weights(events: list[StoryEvent]) -> list[Decimal]:
        weights: list[Decimal] = []
        for event in events:
            spoken = event.exact_text if event.kind in {"dialogue", "narration", "inner_monologue"} else ""
            visible_length = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", spoken or event.text))
            base = max(1, min(12, round(visible_length / (6 if spoken else 12))))
            weights.append(Decimal(base))
        return weights

    @staticmethod
    def _phase(index: int, count: int) -> str:
        if count == 1:
            return "发展"
        if count == 2:
            return ("开始", "结果")[index]
        if count == 3:
            return ("开始", "峰值", "结果")[index]
        ratio = index / (count - 1)
        if ratio == 0:
            return "准备"
        if ratio <= 0.25:
            return "开始"
        if ratio < 0.6:
            return "发展"
        if ratio < 0.8:
            return "峰值"
        if ratio < 1:
            return "结果"
        return "收束"

    def _beats(
        self, request: StoryboardDirectorRequest, events: list[StoryEvent]
    ) -> list[StoryboardTimeBeat]:
        total = Decimal(str(request.duration_seconds))
        weights = self._weights(events)
        weight_total = sum(weights, Decimal(0))
        boundaries = [Decimal(0)]
        cumulative = Decimal(0)
        for weight in weights[:-1]:
            cumulative += weight
            boundaries.append(_q(total * cumulative / weight_total))
        boundaries.append(total)

        beats: list[StoryboardTimeBeat] = []
        previous_end_state = ""
        for offset, event in enumerate(events):
            start = boundaries[offset]
            end = boundaries[offset + 1]
            keyframe = _q(start + (end - start) / Decimal(2))
            page_number = offset // 9 + 1
            page_slot = offset % 9 + 1
            phase = self._phase(offset, len(events))
            start_state = previous_end_state or _clip(_says(
                "opening_state", base_content=request.shot_visual.base_content,
                prop_positions=request.continuity.prop_positions,
            ))
            keyframe_state = _clip(
                event.observable_pose or _says("keyframe_state", event=event.text)
            )
            end_state = _clip(_says(
                "end_state", event=event.text, prop_change=event.prop_change or _word("prop_change_default"),
            ))
            overlapping_lines = [
                _says("spoken_line", speaker=line.speaker, exact=line.exact_text)
                for line in request.timed_dialogue
                if line.start_seconds < float(end) and line.end_seconds > float(start)
            ]
            verbatim = (
                _says("spoken_line", speaker=event.speaker, exact=event.exact_text)
                if event.exact_text else _word("line_separator").join(overlapping_lines)
            )
            if offset == 0:
                color_state = request.color.start_state
            elif offset == len(events) - 1:
                color_state = request.color.end_state
            elif phase == "峰值":
                color_state = request.color.peak_state
            else:
                color_state = _says(
                    "color_transition", start_state=request.color.start_state,
                    change_reason=request.color.change_reason,
                )
            beats.append(StoryboardTimeBeat(
                index=offset + 1,
                page_number=page_number,
                page_slot=page_slot,
                start_seconds=_seconds(start),
                keyframe_seconds=_seconds(keyframe),
                end_seconds=_seconds(end),
                duration_seconds=_seconds(end - start),
                action_phase=phase,
                core_event=event.text,
                start_state=start_state,
                keyframe_state=keyframe_state,
                end_state=end_state,
                character_pose=_clip(
                    event.observable_pose
                    or _says("character_pose", event=event.text)
                ),
                subject_dynamics=_clip(_says(
                    "subject_dynamics", subject_direction=request.dynamics.subject_direction,
                    subject_trajectory=request.dynamics.subject_trajectory, force_source=request.dynamics.force_source,
                    speed_curve=request.dynamics.speed_curve, center_of_gravity=request.dynamics.center_of_gravity,
                )),
                secondary_dynamics=_clip(_says(
                    "secondary_dynamics", secondary_motion=request.dynamics.secondary_motion,
                    inertia_and_follow_through=request.dynamics.inertia_and_follow_through,
                )),
                camera_state=_clip(_says(
                    "camera_state", movement_type=request.camera.movement_type, path=request.camera.path,
                    direction=request.camera.direction, speed_curve=request.camera.speed_curve,
                    composition_change=request.camera.composition_change, focus_change=request.camera.focus_change,
                )),
                color_state=color_state,
                change_from_previous=(
                    _says("change_first")
                    if offset == 0 else _says("change_next", event=event.text)
                ),
                verbatim_line=verbatim,
                environmental_sound=_clip(
                    request.scene.environmental_sound
                    + (
                        _says("sound_cues_suffix", cues=cues)
                        if (cues := self._sounds_between(request, float(start), float(end))) else ""
                    ),
                    500,
                ),
                linkage=(
                    request.transitions.internal_linkage
                    if offset < len(events) - 1 else request.transitions.exit.visual_handoff
                ),
            ))
            previous_end_state = end_state
        return beats

    @staticmethod
    def _still_prompt(
        request: StoryboardDirectorRequest, beat: StoryboardTimeBeat, total_beats: int
    ) -> StillFramePrompt:
        compiler = StoryboardDirectorCompiler
        landmarks = compiler._landmarks(request)
        damage_so_far = compiler._damage_until(request, beat.keyframe_seconds)
        # 构图裁到哪，长相词写到哪：半身不写体态比例，远景不写毛孔细纹；否定词与防混血锚点进排除项。
        fitted = [
            fit_face_text_to_framing(item.appearance, request.shot_visual.shot_size)
            for item in request.characters
        ]
        characters = _word("list_separator").join(
            _says(
                "still_character", name=item.name, appearance=appearance, costume=item.costume,
                accessories=item.accessories, physical_state=item.physical_state,
                psychological_state=item.psychological_state,
            )
            for item, (appearance, _negatives) in zip(request.characters, fitted)
        ) or _word("empty_shot")
        exclusions = list(request.global_visual.exclusions)
        for _appearance, negatives in fitted:
            exclusions.extend(term for term in negatives if term not in exclusions)
        scene, continuity, shot, color = request.scene, request.continuity, request.shot_visual, request.color
        prompt = _says(
            "still_prompt",
            shot_number=request.shot_number, beat_index=beat.index, total_beats=total_beats,
            keyframe_seconds=beat.keyframe_seconds, action_phase=beat.action_phase,
            keyframe_state=beat.keyframe_state, core_event=beat.core_event,
            characters=characters, character_pose=beat.character_pose,
            spatial_structure=scene.spatial_structure, prop_positions=continuity.prop_positions,
            landmarks=landmarks or _word("landmarks_fallback"), ground_material=scene.ground_material,
            initial_environment_state=scene.initial_environment_state, mirror_lock=continuity.mirror_lock,
            extras=compiler._extras_line(request),
            subject_dynamics=beat.subject_dynamics, secondary_dynamics=beat.secondary_dynamics,
            motion_blur=request.dynamics.motion_blur, stable_regions=request.dynamics.stable_regions,
            shot_size=shot.shot_size, lens=shot.lens, camera_angle=shot.camera_angle, camera_height=shot.camera_height,
            depth_of_field=shot.depth_of_field, composition=shot.composition, spatial_layers=shot.spatial_layers,
            frame_positions=render_frame_positions(shot.frame_positions) or _word("still_frame_positions_fallback"),
            key_light_direction=continuity.key_light_direction, light_ratio=color.light_ratio,
            color_state=beat.color_state, primary_color=color.primary_color, secondary_color=color.secondary_color,
            accent_color=color.accent_color, color_temperature=color.color_temperature,
            change_from_previous=beat.change_from_previous,
            face_anchor=continuity.face_anchor, body_anchor=continuity.body_anchor,
            costume_anchor=continuity.costume_anchor, scene_structure=continuity.scene_structure,
            camera_axis=continuity.camera_axis, screen_direction=continuity.screen_direction,
            wound_and_stain_anchor=continuity.wound_and_stain_anchor,
            damage_so_far=damage_so_far or _word("no_change"), damage_closure=continuity.damage_closure,
            verbatim_line=beat.verbatim_line or _word("none"),
            reference_image_policy=request.global_visual.reference_image_policy,
            reference_video_policy=request.global_visual.reference_video_policy,
            exclusions=_word("enum_separator").join(exclusions),
        )
        return StillFramePrompt(
            beat_index=beat.index,
            keyframe_seconds=beat.keyframe_seconds,
            action_phase=beat.action_phase,
            prompt=prompt,
            exclusions=exclusions[:50],
        )

    @staticmethod
    def _video_segments(
        request: StoryboardDirectorRequest, beats: list[StoryboardTimeBeat]
    ) -> list[VideoSegmentPrompt]:
        segments: list[VideoSegmentPrompt] = []
        # Faces, costume, background and camera path are already stated as locks in the same
        # prompt; naming them again as things to avoid only puts the words back in front of the
        # model. What stays here has no positive line of its own.
        exclusions = list(prompt_data.words(_WORDING, "video_exclusions"))
        compiler = StoryboardDirectorCompiler
        landmarks = compiler._landmarks(request)
        frame_positions = render_frame_positions(request.shot_visual.frame_positions)
        for index, (start, end) in enumerate(zip(beats, beats[1:], strict=False), start=1):
            duration = round(end.keyframe_seconds - start.keyframe_seconds, 3)
            dialogue = _word("line_separator").join(filter(None, (start.verbatim_line, end.verbatim_line))) or _word("none")
            damage_before = compiler._damage_until(request, start.keyframe_seconds)
            damage_within = compiler._damage_between(request, start.keyframe_seconds, end.keyframe_seconds)
            cues = compiler._sounds_between(request, start.keyframe_seconds, end.keyframe_seconds)
            entry = request.transitions.entry
            exit_edge = request.transitions.exit
            transition_lines = ""
            if index == 1:
                transition_lines += _says(
                    "transition_in", transition=describe_transition(entry.transition_type),
                    adjacent_shot=entry.adjacent_shot, visual_handoff=smooth_text(entry.visual_handoff),
                    audio_handoff=smooth_text(entry.audio_handoff),
                ) + "\n"
            if index == len(beats) - 1:
                transition_lines += _says(
                    "transition_out", transition=describe_transition(exit_edge.transition_type),
                    adjacent_shot=exit_edge.adjacent_shot, visual_handoff=smooth_text(exit_edge.visual_handoff),
                    audio_handoff=smooth_text(exit_edge.audio_handoff),
                ) + "\n"
            dynamics, camera, sound = request.dynamics, request.camera, request.sound_design
            prompt = _says(
                "video_prompt",
                segment_index=index, from_beat=start.index, to_beat=end.index,
                start_seconds=start.keyframe_seconds, end_seconds=end.keyframe_seconds, duration=duration,
                transitions=transition_lines,
                start_keyframe_state=start.keyframe_state, start_end_state=start.end_state,
                end_keyframe_state=end.keyframe_state,
                start_event=start.core_event, end_event=end.core_event,
                subject_direction=dynamics.subject_direction, subject_trajectory=dynamics.subject_trajectory,
                speed_curve=dynamics.speed_curve, center_of_gravity=dynamics.center_of_gravity,
                inertia_and_follow_through=dynamics.inertia_and_follow_through,
                secondary_motion=dynamics.secondary_motion,
                movement_type=camera.movement_type, start_position=camera.start_position,
                end_position=camera.end_position, path=camera.path, direction=camera.direction,
                camera_speed_curve=camera.speed_curve, subject_following=camera.subject_following,
                focus_change=camera.focus_change, stability=camera.stability,
                space=compiler._space_line(request, index, end, landmarks, frame_positions),
                key_light=compiler._key_light(request), light_ratio=request.color.light_ratio,
                extras=compiler._extras_line(request),
                start_color=start.color_state, end_color=end.color_state, change_reason=request.color.change_reason,
                damage_before=damage_before or request.continuity.wound_and_stain_anchor,
                damage_within=damage_within or _word("none"), damage_closure=request.continuity.damage_closure,
                dialogue=dialogue, environmental_sound=request.scene.environmental_sound, cues=cues or _word("none"),
                near=sound.near, mid=sound.mid, far=sound.far, music_entry=sound.music_entry, silence=sound.silence,
                sound_policy=request.scene.sound_policy,
                forbidden_behaviors=camera.forbidden_behaviors,
                reference_image_policy=request.global_visual.reference_image_policy,
                reference_video_policy=request.global_visual.reference_video_policy,
                exclusions=_word("enum_separator").join(exclusions),
            )
            segments.append(VideoSegmentPrompt(
                segment_index=index,
                from_beat=start.index,
                to_beat=end.index,
                start_seconds=start.keyframe_seconds,
                end_seconds=end.keyframe_seconds,
                duration_seconds=duration,
                start_keyframe=start.index,
                end_keyframe=end.index,
                prompt=prompt,
                exclusions=exclusions,
            ))
        return segments

    @staticmethod
    def _space_line(
        request: StoryboardDirectorRequest, index: int, end: StoryboardTimeBeat, landmarks: str, frame_positions: str,
    ) -> str:
        """The space, said once in full; later segments say 同一<场所> and what changes, with a snapshot every few."""
        mode = space_restatement(index)
        place = request.scene.location
        if mode == "full":
            return _says(
                "space_full", place=place, spatial_structure=request.scene.spatial_structure,
                landmarks=landmarks or _word("landmarks_fallback"),
                frame_positions=frame_positions or _word("video_frame_positions_fallback"),
                ground_material=request.scene.ground_material, mirror_lock=request.continuity.mirror_lock,
            ) + "\n"
        if mode == "snapshot":
            # The light line follows every segment, so the snapshot itself carries only the set.
            snapshot = StoryboardDirectorCompiler._space_snapshot(request)
            return _says(
                "space_snapshot", place=place, snapshot=snapshot or request.scene.spatial_structure,
                frame_positions=frame_positions or _word("video_frame_positions_fallback"),
                mirror_lock=request.continuity.mirror_lock,
            ) + "\n"
        return _says(
            "space_same", place=place, change=end.change_from_previous, mirror_lock=request.continuity.mirror_lock,
        ) + "\n"

    @staticmethod
    def _grid_pages(
        request: StoryboardDirectorRequest,
        beats: list[StoryboardTimeBeat],
        prompts: list[StillFramePrompt],
    ) -> list[StoryboardGridPage]:
        prompt_by_beat = {item.beat_index: item.prompt for item in prompts}
        pages: list[StoryboardGridPage] = []
        total_pages = (len(beats) + 8) // 9
        for page_number in range(1, total_pages + 1):
            page_beats = [beat for beat in beats if beat.page_number == page_number]
            cells: list[StoryboardGridCell] = []
            for slot in range(1, 10):
                beat = next((item for item in page_beats if item.page_slot == slot), None)
                cells.append(StoryboardGridCell(
                    slot=slot,
                    beat_index=beat.index if beat else None,
                    still_prompt=prompt_by_beat[beat.index] if beat else "",
                    empty=beat is None,
                ))
            used = len(page_beats)
            cell_lines = [
                _says("grid_cell_used", slot=cell.slot, beat_index=cell.beat_index, still_prompt=cell.still_prompt)
                if not cell.empty else _says("grid_cell_empty", slot=cell.slot)
                for cell in cells
            ]
            composite = _says(
                "grid_page", project_name=request.project_name, shot_number=request.shot_number,
                page_number=page_number, total_pages=total_pages, used=used, empty=9 - used,
                cells="\n".join(cell_lines),
            )
            pages.append(StoryboardGridPage(
                page_number=page_number,
                cells=cells,
                used_slots=used,
                empty_slots=9 - used,
                composite_prompt=composite,
            ))
        return pages

    @staticmethod
    def _continuity_checks(
        request: StoryboardDirectorRequest,
        events: list[StoryEvent],
        beats: list[StoryboardTimeBeat],
        stills: list[StillFramePrompt],
        segments: list[VideoSegmentPrompt],
        pages: list[StoryboardGridPage],
    ) -> list[ContinuityCheckItem]:
        exact_lines = [line.exact_text for line in request.timed_dialogue]
        beat_lines = "\n".join(beat.verbatim_line for beat in beats)
        grid_markers = prompt_data.words(_WORDING, "grid_markers")
        checks = [
            ContinuityCheckItem(
                code="timeline_full_coverage",
                passed=beats[0].start_seconds == 0 and beats[-1].end_seconds == request.duration_seconds,
                detail=_check("timeline_full_coverage"),
            ),
            ContinuityCheckItem(
                code="timeline_no_gap_overlap",
                passed=all(
                    left.end_seconds == right.start_seconds
                    for left, right in zip(beats, beats[1:], strict=False)
                ),
                detail=_check("timeline_no_gap_overlap"),
            ),
            ContinuityCheckItem(
                code="state_chain_continuous",
                passed=all(
                    left.end_state == right.start_state
                    for left, right in zip(beats, beats[1:], strict=False)
                ),
                detail=_check("state_chain_continuous"),
            ),
            ContinuityCheckItem(
                code="keyframes_inside_beats",
                passed=all(
                    beat.start_seconds <= beat.keyframe_seconds <= beat.end_seconds for beat in beats
                ),
                detail=_check("keyframes_inside_beats"),
            ),
            ContinuityCheckItem(
                code="natural_unique_beats",
                passed=len(beats) == len(events)
                and sum(page.used_slots for page in pages) == len(events),
                detail=_check("natural_unique_beats"),
            ),
            ContinuityCheckItem(
                code="verbatim_dialogue_preserved",
                passed=all(line in beat_lines for line in exact_lines),
                detail=_check("verbatim_dialogue_preserved"),
            ),
            ContinuityCheckItem(
                code="video_segment_cardinality",
                passed=len(segments) == max(0, len(beats) - 1),
                detail=_check("video_segment_cardinality"),
            ),
            ContinuityCheckItem(
                code="single_frame_prompt_isolation",
                passed=all(not any(marker in item.prompt for marker in grid_markers) for item in stills),
                detail=_check("single_frame_prompt_isolation"),
            ),
            ContinuityCheckItem(
                code="grid_pages_exact_layout",
                passed=all(len(page.cells) == 9 and page.used_slots + page.empty_slots == 9 for page in pages),
                detail=_check("grid_pages_exact_layout"),
            ),
            ContinuityCheckItem(
                code="axis_light_palette_locked",
                passed=all((
                    request.continuity.camera_axis.strip(),
                    request.continuity.key_light_direction.strip(),
                    request.color.primary_color.strip(),
                )),
                detail=_check("axis_light_palette_locked"),
            ),
            ContinuityCheckItem(
                code="identity_costume_stain_locked",
                passed=all((
                    request.continuity.face_anchor.strip(),
                    request.continuity.body_anchor.strip(),
                    request.continuity.costume_anchor.strip(),
                    request.continuity.wound_and_stain_anchor.strip(),
                )),
                detail=_check("identity_costume_stain_locked"),
            ),
            ContinuityCheckItem(
                code="scene_props_continuous",
                passed=bool(request.continuity.scene_structure.strip())
                and bool(request.continuity.prop_positions.strip()),
                detail=_check("scene_props_continuous"),
            ),
            ContinuityCheckItem(
                code="physical_dynamics_defined",
                passed=all((
                    request.dynamics.force_source.strip(),
                    request.dynamics.speed_curve.strip(),
                    request.dynamics.center_of_gravity.strip(),
                    request.dynamics.inertia_and_follow_through.strip(),
                )),
                detail=_check("physical_dynamics_defined"),
            ),
            ContinuityCheckItem(
                code="camera_motion_color_continuous",
                passed=all((
                    request.camera.path.strip(),
                    request.camera.speed_curve.strip(),
                    request.color.change_reason.strip(),
                    request.color.end_state.strip(),
                )),
                detail=_check("camera_motion_color_continuous"),
            ),
            ContinuityCheckItem(
                code="transition_types_in_catalog",
                passed=all(
                    normalize_transition_type(edge.transition_type)[1]
                    for edge in (request.transitions.entry, request.transitions.exit)
                ),
                severity="warning",
                detail=_check("transition_types_in_catalog"),
            ),
            ContinuityCheckItem(
                code="transitions_explicit",
                passed=all((
                    request.transitions.entry.visual_handoff.strip(),
                    request.transitions.internal_linkage.strip(),
                    request.transitions.exit.visual_handoff.strip(),
                )),
                detail=_check("transitions_explicit"),
            ),
            ContinuityCheckItem(
                code="video_keyframe_endpoints_locked",
                passed=all(
                    segment.start_keyframe == segment.from_beat
                    and segment.end_keyframe == segment.to_beat
                    for segment in segments
                ),
                detail=_check("video_keyframe_endpoints_locked"),
            ),
            ContinuityCheckItem(
                code="video_no_extra_content",
                passed=all(_word("no_extra_content") in segment.exclusions for segment in segments),
                detail=_check("video_no_extra_content"),
            ),
            ContinuityCheckItem(
                code="grid_story_order_preserved",
                passed=all(
                    page.reading_order == "left_to_right_top_to_bottom"
                    and [cell.beat_index for cell in page.cells if not cell.empty]
                    == sorted(cell.beat_index for cell in page.cells if not cell.empty)
                    for page in pages
                ),
                detail=_check("grid_story_order_preserved"),
            ),
        ]
        unanchored = [
            item.name for item in request.scene.landmarks
            if not landmark_is_anchored(item.relative_position)
        ]
        checks.extend([
            ContinuityCheckItem(
                code="frame_positions_in_screen_coordinates",
                passed=bool(request.shot_visual.frame_positions),
                severity="warning",
                detail=(
                    _check("frame_positions_set")
                    if request.shot_visual.frame_positions
                    else _check("frame_positions_missing")
                ),
            ),
            ContinuityCheckItem(
                code="landmarks_relative_to_character",
                passed=not unanchored,
                severity="warning",
                detail=(
                    _check("landmarks_unanchored", names=_word("enum_separator").join(unanchored))
                    if unanchored
                    else _check("landmarks_anchored")
                    if request.scene.landmarks
                    else _check("landmarks_none")
                ),
            ),
            ContinuityCheckItem(
                code="damage_timeline_closed",
                passed=bool(request.continuity.damage_closure.strip()),
                detail=_check("damage_timeline_closed"),
            ),
            ContinuityCheckItem(
                code="timed_sounds_inside_shot",
                passed=all(sound.end_seconds <= request.duration_seconds for sound in request.timed_sounds)
                and bool(request.scene.sound_policy.strip()),
                detail=_check("timed_sounds_inside_shot"),
            ),
            ContinuityCheckItem(
                code="reference_material_scoped",
                passed=bool(request.global_visual.reference_image_policy.strip())
                and bool(request.global_visual.reference_video_policy.strip()),
                detail=(
                    _check("reference_motion")
                    if request.global_visual.reference_video_role == "motion_trajectory" else
                    _check("reference_appearance")
                ),
            ),
        ])
        checks.extend(request.spatial_checks)
        checks.extend(request.transition_checks)
        if request.extras is not None:
            checks.append(ContinuityCheckItem(
                code="crowd_motion_staggered",
                passed=request.extras.stagger_seconds > 0,
                severity="warning",
                detail=(
                    _check("crowd_staggered", label=request.extras.label, stagger_seconds=request.extras.stagger_seconds)
                    if request.extras.stagger_seconds > 0
                    else _check("crowd_synchronous", label=request.extras.label)
                ),
            ))
        if len(beats) == 1:
            checks.append(ContinuityCheckItem(
                code="single_beat_no_connector",
                passed=False,
                severity="warning",
                detail=_check("single_beat_no_connector"),
            ))
        return checks
