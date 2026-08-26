"""Deterministic universal storyboard-director compiler.

The compiler treats a prompt template as a data contract. It does not execute
template instructions or submit generation jobs to external providers.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP

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


_BRACKET_DIALOGUE = re.compile(r"^【([^】]{1,120})】\s*(.*)$")
_INLINE_DIALOGUE = re.compile(r"^([A-Za-z\u4e00-\u9fff·][A-Za-z0-9\u4e00-\u9fff· ._-]{0,60})[：:]\s*(.+)$")
_UPPER_CHARACTER = re.compile(r"^[A-Z][A-Z0-9 ._'’-]{0,50}(?:\s*\([^)]*\))?$")
_SCENE_LINE = re.compile(
    r"^(?:INT\.?|EXT\.?|INT/EXT\.?|I/E\.?|内景|外景|内外景|场景\s*[零〇一二三四五六七八九十百千万两\d]+)",
    re.IGNORECASE,
)
_META_LABELS = {
    "时间", "地点", "天气", "空间", "空间结构", "道具", "特效", "角色", "人物", "镜头",
    "备注", "注", "场次", "集数", "画面", "声音", "音效", "音乐",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")
_MILLISECOND = Decimal("0.001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MILLISECOND, rounding=ROUND_HALF_UP)


def _seconds(value: Decimal) -> float:
    return float(_q(value))


def _clip(value: str, limit: int = 4_000) -> str:
    text = " ".join(value.replace("\x00", "").split()).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _event_key(event: StoryEvent) -> tuple[str, str, str, str]:
    return event.kind, event.speaker.strip(), event.exact_text.strip(), event.text.strip()


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
                exact = re.sub(r"^[（(][^）)]{1,500}[）)]\s*", "", exact).strip()
                if exact:
                    events.append(StoryEvent(
                        kind="dialogue", speaker=speaker, exact_text=exact,
                        text=f"{speaker}说：{exact}",
                    ))
                pending_speaker = ""
                continue
            inline = _INLINE_DIALOGUE.match(line)
            if inline and inline.group(1).strip() not in _META_LABELS:
                speaker, exact = inline.group(1).strip(), inline.group(2).strip()
                exact = re.sub(r"^[（(][^）)]{1,500}[）)]\s*", "", exact).strip()
                if exact:
                    events.append(StoryEvent(
                        kind="dialogue", speaker=speaker, exact_text=exact,
                        text=f"{speaker}说：{exact}",
                    ))
                pending_speaker = ""
                continue
            if inline and inline.group(1).strip() in _META_LABELS:
                pending_speaker = ""
                continue
            if _UPPER_CHARACTER.fullmatch(line):
                pending_speaker = re.sub(r"\s*\([^)]*\)\s*$", "", line).strip()
                continue
            if pending_speaker and not line.startswith(("（", "(")):
                events.append(StoryEvent(
                    kind="dialogue", speaker=pending_speaker, exact_text=line,
                    text=f"{pending_speaker}说：{line}",
                ))
                pending_speaker = ""
                continue
            if line.startswith(("（", "(")) and line.endswith(("）", ")")):
                continue
            for sentence in _SENTENCE_SPLIT.split(line):
                sentence = sentence.strip()
                if sentence:
                    events.append(StoryEvent(kind="action", text=sentence))
        return events

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
            start_state = previous_end_state or _clip(
                f"镜头开场：{request.shot_visual.base_content}；"
                f"道具初态与位置：{request.continuity.prop_positions}"
            )
            keyframe_state = _clip(
                event.observable_pose or f"在 {event.text} 的动作可读、姿态清楚瞬间"
            )
            end_state = _clip(
                f"事件“{event.text}”完成后的可见状态；"
                f"道具变化：{event.prop_change or '仅保留剧本已发生的变化'}"
            )
            overlapping_lines = [
                f"{line.speaker}：{line.exact_text}"
                for line in request.timed_dialogue
                if line.start_seconds < float(end) and line.end_seconds > float(start)
            ]
            verbatim = (
                f"{event.speaker}：{event.exact_text}"
                if event.exact_text else "｜".join(overlapping_lines)
            )
            if offset == 0:
                color_state = request.color.start_state
            elif offset == len(events) - 1:
                color_state = request.color.end_state
            elif phase == "峰值":
                color_state = request.color.peak_state
            else:
                color_state = (
                    f"从{request.color.start_state}连续过渡，变化只能由"
                    f"{request.color.change_reason}驱动"
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
                    or f"角色以可观察姿态完成“{event.text}”；心理只通过输入的表情、视线、呼吸和重心表现"
                ),
                subject_dynamics=_clip(
                    f"{request.dynamics.subject_direction}；轨迹：{request.dynamics.subject_trajectory}；"
                    f"力量：{request.dynamics.force_source}；速度：{request.dynamics.speed_curve}；"
                    f"重心：{request.dynamics.center_of_gravity}"
                ),
                secondary_dynamics=_clip(
                    f"{request.dynamics.secondary_motion}；惯性与收势："
                    f"{request.dynamics.inertia_and_follow_through}"
                ),
                camera_state=_clip(
                    f"{request.camera.movement_type}；路径：{request.camera.path}；"
                    f"方向：{request.camera.direction}；速度：{request.camera.speed_curve}；"
                    f"构图：{request.camera.composition_change}；对焦：{request.camera.focus_change}"
                ),
                color_state=color_state,
                change_from_previous=(
                    "建立本镜头角色、场景、道具、轴线和光向"
                    if offset == 0 else f"只新增本拍事件：{event.text}"
                ),
                verbatim_line=verbatim,
                environmental_sound=request.scene.environmental_sound,
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
        characters = "；".join(
            f"{item.name}：{item.appearance}；服装{item.costume}；配饰{item.accessories}；"
            f"身体状态{item.physical_state}；心理状态{item.psychological_state}"
            for item in request.characters
        )
        prompt = (
            f"镜头{request.shot_number}第{beat.index}/{total_beats}个关键拍点，"
            f"关键帧时间{beat.keyframe_seconds:g}秒，动作阶段{beat.action_phase}。"
            "只生成一张独立完整画面，不提前呈现下一拍结果。\n"
            f"【当前帧核心画面】{beat.keyframe_state}；核心事件：{beat.core_event}。\n"
            f"【角色与表演】{characters}；当前姿态：{beat.character_pose}。\n"
            f"【空间与道具】{request.scene.spatial_structure}；{request.continuity.prop_positions}。\n"
            f"【画面动势】{beat.subject_dynamics}；次级运动：{beat.secondary_dynamics}；"
            f"动态模糊：{request.dynamics.motion_blur}；稳定区域：{request.dynamics.stable_regions}。\n"
            f"【构图与摄影】{request.shot_visual.shot_size}，{request.shot_visual.lens}，"
            f"{request.shot_visual.camera_angle}，{request.shot_visual.camera_height}，"
            f"{request.shot_visual.depth_of_field}；{request.shot_visual.composition}；"
            f"{request.shot_visual.spatial_layers}。\n"
            f"【光影与色调】主光{request.continuity.key_light_direction}；{beat.color_state}；"
            f"主色{request.color.primary_color}，辅助色{request.color.secondary_color}，"
            f"点缀色{request.color.accent_color}，{request.color.color_temperature}。\n"
            f"【相对上一拍变化】{beat.change_from_previous}。\n"
            f"【连续性锁定】面部{request.continuity.face_anchor}；体态{request.continuity.body_anchor}；"
            f"服装{request.continuity.costume_anchor}；场景{request.continuity.scene_structure}；"
            f"轴线{request.continuity.camera_axis}；屏幕方向{request.continuity.screen_direction}。\n"
            f"【台词表演依据】{beat.verbatim_line or '无'}；不得把台词生成在画面中。\n"
            f"【排除】{'、'.join(request.global_visual.exclusions)}。"
        )
        return StillFramePrompt(
            beat_index=beat.index,
            keyframe_seconds=beat.keyframe_seconds,
            action_phase=beat.action_phase,
            prompt=prompt,
            exclusions=request.global_visual.exclusions,
        )

    @staticmethod
    def _video_segments(
        request: StoryboardDirectorRequest, beats: list[StoryboardTimeBeat]
    ) -> list[VideoSegmentPrompt]:
        segments: list[VideoSegmentPrompt] = []
        exclusions = [
            "镜头漂移", "角色变脸", "服装变化", "肢体畸形", "背景跳动", "速度突变",
            "瞬移", "穿模", "物体闪现", "肢体重置", "新增人物道具动作或特效",
        ]
        for index, (start, end) in enumerate(zip(beats, beats[1:], strict=False), start=1):
            duration = round(end.keyframe_seconds - start.keyframe_seconds, 3)
            dialogue = "｜".join(filter(None, (start.verbatim_line, end.verbatim_line))) or "无"
            prompt = (
                f"视频片段{index}：连续瞬间{start.index}→连续瞬间{end.index}，"
                f"{start.keyframe_seconds:g}秒至{end.keyframe_seconds:g}秒，时长{duration:g}秒。\n"
                f"【起始状态】严格继承关键帧{start.index}：{start.keyframe_state}；{start.end_state}。\n"
                f"【结束状态】准确到达关键帧{end.index}：{end.keyframe_state}。\n"
                f"【主体运动】从“{start.core_event}”自然发展到“{end.core_event}”；"
                f"方向与轨迹：{request.dynamics.subject_direction}，{request.dynamics.subject_trajectory}；"
                f"速度曲线：{request.dynamics.speed_curve}；重心：{request.dynamics.center_of_gravity}；"
                f"惯性与收势：{request.dynamics.inertia_and_follow_through}。\n"
                f"【次级运动】{request.dynamics.secondary_motion}。\n"
                f"【摄影机运动】{request.camera.movement_type}；"
                f"开始机位{request.camera.start_position}；结束机位{request.camera.end_position}；"
                f"路径{request.camera.path}；方向{request.camera.direction}；速度{request.camera.speed_curve}；"
                f"跟随{request.camera.subject_following}；对焦{request.camera.focus_change}；"
                f"稳定性{request.camera.stability}。\n"
                f"【色调变化】从“{start.color_state}”连续过渡到“{end.color_state}”，"
                f"只由“{request.color.change_reason}”驱动。\n"
                f"【声音与台词】逐字台词/旁白：{dialogue}；环境声：{request.scene.environmental_sound}；"
                "台词不得改写、缩写、补写或交换说话者。\n"
                f"【强制连续性】角色、服装、伤痕污渍、场景结构、道具、光向、摄影轴线和"
                f"屏幕方向全部锁定；后一状态必须从前一状态连续到达；禁止行为："
                f"{request.camera.forbidden_behaviors}。若模型自由发挥冲突，以关键帧和本契约为最高优先级。\n"
                f"【排除】{'、'.join(exclusions)}。"
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
                f"第{cell.slot}格："
                + (f"连续瞬间{cell.beat_index}；{cell.still_prompt}" if not cell.empty else "纯留白空格，不复制、不补造拍点")
                for cell in cells
            ]
            composite = (
                f"生成《{request.project_name}》镜头{request.shot_number}第{page_number}/{total_pages}页的"
                f"单张3×3九宫格分镜展示图。严格三行三列、九格等大、从左到右从上到下。"
                f"本页只有{used}个真实拍点，其余{9 - used}格保持纯留白；禁止重复、镜像或补造拍点。"
                "所有已用格保持同一角色身份、服装、伤痕污渍、场景结构、道具状态、摄影轴线、"
                "主光方向和色彩系统。宫格只负责展示，不改变单图内容、时间顺序或构图。\n"
                + "\n".join(cell_lines)
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
        checks = [
            ContinuityCheckItem(
                code="timeline_full_coverage",
                passed=beats[0].start_seconds == 0 and beats[-1].end_seconds == request.duration_seconds,
                detail="时间轴从0秒开始并以镜头总时长结束。",
            ),
            ContinuityCheckItem(
                code="timeline_no_gap_overlap",
                passed=all(
                    left.end_seconds == right.start_seconds
                    for left, right in zip(beats, beats[1:], strict=False)
                ),
                detail="相邻拍点无重叠、无空档。",
            ),
            ContinuityCheckItem(
                code="state_chain_continuous",
                passed=all(
                    left.end_state == right.start_state
                    for left, right in zip(beats, beats[1:], strict=False)
                ),
                detail="后一拍完整继承前一拍结束状态。",
            ),
            ContinuityCheckItem(
                code="keyframes_inside_beats",
                passed=all(
                    beat.start_seconds <= beat.keyframe_seconds <= beat.end_seconds for beat in beats
                ),
                detail="每拍关键帧均位于自身时间范围。",
            ),
            ContinuityCheckItem(
                code="natural_unique_beats",
                passed=len(beats) == len(events)
                and sum(page.used_slots for page in pages) == len(events),
                detail="每个输入叙事事件只生成一个拍点，没有为了填满宫格增加拍点。",
            ),
            ContinuityCheckItem(
                code="verbatim_dialogue_preserved",
                passed=all(line in beat_lines for line in exact_lines),
                detail="所有带时间范围的台词和旁白逐字保留。",
            ),
            ContinuityCheckItem(
                code="video_segment_cardinality",
                passed=len(segments) == max(0, len(beats) - 1),
                detail="N个关键帧对应N−1个相邻关键帧视频片段。",
            ),
            ContinuityCheckItem(
                code="single_frame_prompt_isolation",
                passed=all("生成九宫格" not in item.prompt and "3×3" not in item.prompt for item in stills),
                detail="逐拍静帧提示词不包含正向宫格生成指令。",
            ),
            ContinuityCheckItem(
                code="grid_pages_exact_layout",
                passed=all(len(page.cells) == 9 and page.used_slots + page.empty_slots == 9 for page in pages),
                detail="每页均为九格画布，空位留白且不复制拍点。",
            ),
            ContinuityCheckItem(
                code="axis_light_palette_locked",
                passed=all((
                    request.continuity.camera_axis.strip(),
                    request.continuity.key_light_direction.strip(),
                    request.color.primary_color.strip(),
                )),
                detail="摄影轴线、主光方向和基础色彩已明确锁定。",
            ),
            ContinuityCheckItem(
                code="identity_costume_stain_locked",
                passed=all((
                    request.continuity.face_anchor.strip(),
                    request.continuity.body_anchor.strip(),
                    request.continuity.costume_anchor.strip(),
                    request.continuity.wound_and_stain_anchor.strip(),
                )),
                detail="人物身份、体态、服装、伤痕和污渍均已锁定。",
            ),
            ContinuityCheckItem(
                code="scene_props_continuous",
                passed=bool(request.continuity.scene_structure.strip())
                and bool(request.continuity.prop_positions.strip()),
                detail="场景结构与道具初始位置、运动范围已明确。",
            ),
            ContinuityCheckItem(
                code="physical_dynamics_defined",
                passed=all((
                    request.dynamics.force_source.strip(),
                    request.dynamics.speed_curve.strip(),
                    request.dynamics.center_of_gravity.strip(),
                    request.dynamics.inertia_and_follow_through.strip(),
                )),
                detail="动作力量、速度、重心、惯性与收势符合连续物理过程。",
            ),
            ContinuityCheckItem(
                code="camera_motion_color_continuous",
                passed=all((
                    request.camera.path.strip(),
                    request.camera.speed_curve.strip(),
                    request.color.change_reason.strip(),
                    request.color.end_state.strip(),
                )),
                detail="主体动势、摄影机路径与色调变化均有连续轨迹和明确来源。",
            ),
            ContinuityCheckItem(
                code="transitions_explicit",
                passed=all((
                    request.transitions.entry.visual_handoff.strip(),
                    request.transitions.internal_linkage.strip(),
                    request.transitions.exit.visual_handoff.strip(),
                )),
                detail="入场、拍点内部衔接和出场转场均已定义视觉与声音交接。",
            ),
            ContinuityCheckItem(
                code="video_keyframe_endpoints_locked",
                passed=all(
                    segment.start_keyframe == segment.from_beat
                    and segment.end_keyframe == segment.to_beat
                    for segment in segments
                ),
                detail="每段视频起止状态与对应相邻分镜关键帧一致。",
            ),
            ContinuityCheckItem(
                code="video_no_extra_content",
                passed=all("新增人物道具动作或特效" in segment.exclusions for segment in segments),
                detail="视频排除项禁止添加分镜之外的人物、道具、动作或特效。",
            ),
            ContinuityCheckItem(
                code="grid_story_order_preserved",
                passed=all(
                    page.reading_order == "left_to_right_top_to_bottom"
                    and [cell.beat_index for cell in page.cells if not cell.empty]
                    == sorted(cell.beat_index for cell in page.cells if not cell.empty)
                    for page in pages
                ),
                detail="宫格按拍点顺序从左到右、从上到下排列，没有改变故事顺序。",
            ),
        ]
        if len(beats) == 1:
            checks.append(ContinuityCheckItem(
                code="single_beat_no_connector",
                passed=False,
                severity="warning",
                detail="镜头只有一个真实拍点，因此没有相邻关键帧连接视频；可直接生成静态或单状态视频。",
            ))
        return checks
