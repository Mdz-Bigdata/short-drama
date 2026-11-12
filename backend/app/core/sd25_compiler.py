"""Executable clean prompt compiler for the full local sd25-pe contract."""

from __future__ import annotations

import re
from typing import Any

from app.core import prompt_data
from app.core.storyboard_director import space_restatement
from app.schema.production import (
    Sd25Asset,
    Sd25CompileRequest,
    Sd25CompileResult,
    Sd25CompileStep,
)


# The headings, sentences, per-role exclusions and the camera words below: app/data/prompt/sd25_compiler.json.
_WORDING = "sd25_compiler"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the wording table, filled in (``key`` is positional; an array of lines is joined with newlines)."""
    entry: Any = prompt_data.load(_WORDING)["says"][key]
    template = "\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)
    return template.format(**values)


def _heading(key: str) -> str:
    """A section heading of the prompt (【…】)."""
    return str(prompt_data.load(_WORDING)["headings"][key])


def _word(key: str) -> str:
    """A separator or a fallback phrase, used as it stands."""
    return str(prompt_data.load(_WORDING)["words"][key])


# Camera language in the prompt body competes with the blockout's own camera track,
# so in blockout mode its presence is reported rather than silently merged.
_CAMERA_LANGUAGE = re.compile("|".join(prompt_data.words(_WORDING, "camera_language")))
_TIME_SPAN = prompt_data.pattern(_WORDING, "time_span")


class Sd25PromptCompiler:
    """Compile canonical input without submitting a provider task.

    The local SKILL.md explicitly separates prompt compilation from generation. This
    class therefore returns prompt text plus separately carried API parameters.
    """

    @staticmethod
    def _asset_line(asset: Sd25Asset) -> str:
        exclusions = prompt_data.value(_WORDING, "asset_exclusions")
        # 参考音频里的语速和情绪会原样带进生成，所以 voice 只借音色，节奏与情绪按本句的表达方式走。
        overhead = _word("overhead_view") if asset.overhead_view else ""
        return _says(
            "asset_line", ref=asset.ref, subject=asset.subject, observations=asset.observations,
            exclusion=exclusions[asset.role], overhead=overhead,
        )

    @staticmethod
    def _missing_asset_lines(
        request: Sd25CompileRequest,
        *,
        exclude_refs: set[str | None] | None = None,
    ) -> list[str]:
        excluded = exclude_refs or set()
        return [
            _says("missing_asset_line", ref=asset.ref, intended_role=asset.intended_role)
            for asset in request.missing_assets
            if asset.ref not in excluded
        ]

    @staticmethod
    def _observation_for(request: Sd25CompileRequest, ref: str) -> str:
        for asset in request.assets:
            if asset.ref == ref:
                return asset.observations
        for asset in request.missing_assets:
            if asset.ref == ref:
                return asset.intended_role
        raise KeyError(f"unknown sd25 reference: {ref}")

    @staticmethod
    def _used_refs(request: Sd25CompileRequest) -> set[str]:
        anchored = {ref for ref in (
            request.first_frame_ref, request.last_frame_ref, request.source_video_ref,
            request.storyboard_ref, request.blockout_ref,
        ) if ref}
        anchored.update(request.keyframe_refs)
        anchored.update(entry.audio_ref for entry in request.dialogue if entry.audio_ref)
        return anchored | {asset.ref for asset in request.assets if asset.required}

    @staticmethod
    def _parameters_for(
        request: Sd25CompileRequest,
        mode: str,
    ) -> tuple[dict[str, str | int | float | bool], list[str]]:
        parameters = dict(request.parameters)
        locked: list[str] = []
        if mode == "edit":
            locked = [key for key in ("aspect_ratio", "duration_seconds") if key in parameters]
        elif mode.startswith("extend_"):
            locked = [key for key in ("aspect_ratio",) if key in parameters]
        elif mode in {
            "generation_first_frame", "generation_first_last_frame", "generation_keyframes"
        }:
            locked = [key for key in ("aspect_ratio",) if key in parameters]
        for key in locked:
            parameters.pop(key, None)
        warnings = []
        if locked:
            warnings.append(_says("locked_parameters", keys=_word("enum_separator").join(locked)))
        return parameters, warnings

    @staticmethod
    def _dialogue_lines(request: Sd25CompileRequest) -> list[str]:
        lines: list[str] = []
        for entry in request.dialogue:
            audio = _says("dialogue_audio", ref=entry.audio_ref) if entry.audio_ref else ""
            language = _says("dialogue_language", language=entry.language) if entry.language else _word("input_language")
            spoken = _says("dialogue_spoken", text=entry.text) if entry.text else _word("no_text")
            lines.append(_says(
                "dialogue_line", position=entry.position, speaker=entry.speaker, language=language, audio=audio,
                delivery=entry.delivery, spoken=spoken,
            ))
        return lines

    def compile(self, request: Sd25CompileRequest) -> Sd25CompileResult:
        used_refs = self._used_refs(request)
        used = [asset for asset in request.assets if asset.ref in used_refs]
        unused = [asset for asset in request.assets if asset.ref not in used_refs]

        steps: list[Sd25CompileStep] = []
        if request.task == "edit":
            prompt, mode = self._compile_edit(request, used, unused), "edit"
        elif request.task == "extend":
            prompt, mode = self._compile_extend(request, used, unused), f"extend_{request.extension_direction}"
        elif request.task == "edit_then_extend":
            edit_prompt = self._compile_edit(request, used, unused)
            extend_prompt = self._compile_extend(
                request, used, unused, source_override=_word("first_step_output")
            )
            used_asset_refs = [asset.ref for asset in used]
            unused_asset_refs = [asset.ref for asset in unused]
            edit_parameters, edit_warnings = self._parameters_for(request, "edit")
            extend_mode = f"extend_{request.extension_direction}"
            extend_parameters, extend_warnings = self._parameters_for(request, extend_mode)
            steps = [
                Sd25CompileStep(
                    mode="edit", prompt=edit_prompt, used_assets=used_asset_refs,
                    unused_assets=unused_asset_refs, parameters=edit_parameters,
                ),
                Sd25CompileStep(
                    mode=extend_mode, prompt=extend_prompt,
                    used_assets=used_asset_refs, unused_assets=unused_asset_refs,
                    parameters=extend_parameters,
                ),
            ]
            prompt = _says("edit_then_extend", edit_prompt=edit_prompt, extend_prompt=extend_prompt)
            mode = "edit_then_extend"
            parameters = extend_parameters
            warnings = list(dict.fromkeys(edit_warnings + extend_warnings))
        else:
            prompt, mode, generation_warnings = self._compile_generation(request, used, unused)

        if request.task != "edit_then_extend":
            parameters, warnings = self._parameters_for(request, mode)
            if request.task == "generation":
                warnings = list(dict.fromkeys(generation_warnings + warnings))
        return Sd25CompileResult(
            mode=mode,
            prompt=prompt,
            used_assets=[asset.ref for asset in used],
            unused_assets=[asset.ref for asset in unused],
            parameters=parameters,
            warnings=warnings,
            steps=steps,
        )

    def _compile_generation(
        self,
        request: Sd25CompileRequest,
        used: list[Sd25Asset],
        unused: list[Sd25Asset],
    ) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        parts = [_heading("generation_goal"), request.goal.strip()]
        if used or request.missing_assets:
            parts.extend([
                "", _heading("asset_roles"),
                *(self._asset_line(asset) for asset in used),
                *self._missing_asset_lines(request),
            ])
        if unused:
            parts.extend([
                "", _heading("unused_assets"),
                *(_says("unused_asset", ref=asset.ref) for asset in unused),
            ])

        if request.first_frame_ref:
            parts.extend([
                "", _says("first_frame", ref=request.first_frame_ref),
                _says("first_frame_defines", observation=self._observation_for(request, request.first_frame_ref)),
            ])
        if request.last_frame_ref:
            parts.extend([
                _says("last_frame", ref=request.last_frame_ref),
                _says("last_frame_defines", observation=self._observation_for(request, request.last_frame_ref)),
            ])

        keyframes = _word("enum_separator").join(request.keyframe_refs)
        if request.keyframe_refs and request.blockout_ref:
            stages = (
                _word("list_separator").join(
                    _says("stage_span", start=0 if index == 0 else request.keyframe_stage_ends[index - 1], end=end, ref=ref)
                    for index, (ref, end) in enumerate(zip(request.keyframe_refs, request.keyframe_stage_ends, strict=True))
                )
                if request.keyframe_stage_ends
                else _word("list_separator").join(
                    _says("stage_ordinal", index=index, ref=ref) for index, ref in enumerate(request.keyframe_refs, start=1)
                )
            )
            parts.extend([
                "", _heading("blockout_keyframes"),
                _says("blockout_keyframes", blockout=request.blockout_ref, keyframes=keyframes, stages=stages),
            ])
            if not request.keyframe_stage_ends:
                warnings.append(_says("stage_ends_advice"))
            for index, ref in enumerate(request.keyframe_refs, start=1):
                parts.append(_says("stage_frame", ref=ref, index=index, observation=self._observation_for(request, ref)))
        elif request.keyframe_refs:
            parts.extend([
                "", _heading("ordered_keyframes"),
                _says("keyframe_order", keyframes=keyframes),
            ])
            for index, ref in enumerate(request.keyframe_refs, start=1):
                if ref in {request.first_frame_ref, request.last_frame_ref}:
                    continue
                parts.append(_says("keyframe_state", ref=ref, index=index, observation=self._observation_for(request, ref)))
            parts.append(_says("keyframe_passage", keyframes=keyframes))

        if request.storyboard_ref and request.storyboard:
            parts.extend([
                "", _heading("storyboard"),
                _says(
                    "storyboard_page", ref=request.storyboard_ref, panels=len(request.storyboard.panels),
                    empty_slots=request.storyboard.empty_slots,
                ),
            ])
            for panel in request.storyboard.panels:
                parts.append(_says(
                    "storyboard_panel", index=panel.index, shot_size=panel.shot_size, lens_mm=panel.lens_mm,
                    aperture=panel.aperture, camera_angle=panel.camera_angle, camera_movement=panel.camera_movement,
                    characters=_word("enum_separator").join(panel.characters), subject_action=panel.subject_action,
                    expression=panel.expression, composition=panel.composition, end_state=panel.end_state,
                ))

        if request.blockout_ref and request.blockout_granularity:
            ref = request.blockout_ref
            if request.blockout_granularity == "coarse":
                parts.extend(["", _heading("blockout_coarse"), _says("blockout_coarse", ref=ref)])
            else:
                parts.extend(["", _heading("blockout_fine"), _says("blockout_fine", ref=ref)])
            parts.append(_says("blockout_only_camera", ref=ref))
            if request.blockout_standin_limbs:
                parts.append(_says("standin_limbs"))
                if not _TIME_SPAN.search(request.goal):
                    warnings.append(_says("standin_limbs_warning"))
            camera_words = list(dict.fromkeys(_CAMERA_LANGUAGE.findall(request.goal)))
            if camera_words:
                warnings.append(_says(
                    "camera_words_warning", words=_word("enum_separator").join(camera_words), ref=ref,
                ))

        if request.dialogue:
            parts.extend(["", _heading("dialogue"), *self._dialogue_lines(request)])
        parts.extend([
            "", _heading("event_script"),
            _says("event_script"),
            "", _heading("consistency"),
            _says("consistency"),
        ])
        if request.storyboard_ref:
            mode = "generation_storyboard"
        elif request.blockout_ref:
            mode = f"generation_blockout_{request.blockout_granularity}"
        elif request.keyframe_refs:
            mode = "generation_keyframes"
        elif request.first_frame_ref and request.last_frame_ref:
            mode = "generation_first_last_frame"
        elif request.first_frame_ref:
            mode = "generation_first_frame"
        elif request.last_frame_ref:
            mode = "generation_last_frame"
        elif used:
            mode = "generation_reference"
        else:
            mode = "generation_text"
        return "\n".join(parts), mode, warnings

    def _compile_edit(
        self,
        request: Sd25CompileRequest,
        used: list[Sd25Asset],
        unused: list[Sd25Asset],
    ) -> str:
        source = request.source_video_ref
        scope_lines = {
            "visual": _says("edit_scope_visual", source=source),
            "audio": _says("edit_scope_audio", source=source),
            "both": _says("edit_scope_both", source=source),
        }[request.edit_scope]
        parts = [
            _heading("edit_goal"), _says("edit_goal", source=source, goal=request.goal.strip()), "",
            _heading("source_role"),
            _says("source_role", source=source),
            "", _heading("target_assets"),
            *(self._asset_line(asset) for asset in used if asset.ref != source),
            *self._missing_asset_lines(request, exclude_refs={source}),
            "", _heading("edit_scope"),
            request.goal.strip(),
            scope_lines,
            (
                _says("delete_unspecified", source=source)
                if request.edit_scope_closure == "delete_unspecified"
                else _says("preserve_unspecified", source=source)
            ),
            "", _heading("timeline"),
            _says("timeline", source=source),
        ]
        if request.dialogue:
            parts.extend(["", _heading("dialogue"), *self._dialogue_lines(request)])
        if unused:
            parts.extend(["", _heading("unused_assets"), *(
                _says("unused_asset", ref=asset.ref)
                for asset in unused
            )])
        return "\n".join(parts)

    def _compile_extend(
        self,
        request: Sd25CompileRequest,
        used: list[Sd25Asset],
        unused: list[Sd25Asset],
        *,
        source_override: str | None = None,
    ) -> str:
        source_ref = request.source_video_ref
        source = source_override or source_ref
        before = request.extension_direction == "before"
        edge = prompt_data.value(_WORDING, "extension")["before" if before else "after"]
        direction, boundary, target = edge["direction"], edge["boundary"], edge["target"]
        parts = [
            *(self._asset_line(asset) for asset in used if asset.ref != source_ref),
            *self._missing_asset_lines(request, exclude_refs={source_ref}),
            "",
        ]
        parts.extend([
            _says("extend_source", source=source, direction=direction),
            _says("extend_join", direction=direction, source=source, target=target, boundary=boundary),
            request.goal.strip(),
            _says("extend_continuity"),
        ])
        if request.key_light.strip():
            parts.append(_says("extend_light", key_light=request.key_light.strip()))
        # 续写链只在第一段和每隔几段写一次空间快照，其余段落只写同一场所里的动作与变化。
        if request.space_snapshot.strip() and request.chain_index and space_restatement(request.chain_index) != "same":
            parts.append(_says("extend_snapshot", snapshot=request.space_snapshot.strip()))
        if before:
            parts.append(_says("extend_before_only"))
        if unused:
            parts.extend(["", _heading("unused_assets"), *(
                _says("unused_asset", ref=asset.ref)
                for asset in unused
            )])
        return "\n".join(parts)
