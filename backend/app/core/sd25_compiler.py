"""Executable clean prompt compiler for the full local sd25-pe contract."""

from __future__ import annotations

from app.schema.production import (
    Sd25Asset,
    Sd25CompileRequest,
    Sd25CompileResult,
    Sd25CompileStep,
)


class Sd25PromptCompiler:
    """Compile canonical input without submitting a provider task.

    The local SKILL.md explicitly separates prompt compilation from generation. This
    class therefore returns prompt text plus separately carried API parameters.
    """

    @staticmethod
    def _asset_line(asset: Sd25Asset) -> str:
        exclusions = {
            "character": "不采用图片背景或未声明身份",
            "scene": "不采用素材中的人物身份",
            "prop": "不采用素材背景或额外道具",
            "effect": "不改变主体身份与场景结构",
            "style": "只采用可见风格，不替换人物、场景和剧情事实",
            "action": "不采用素材中的人物身份、服装和场景",
            "camera": "不采用素材中的人物身份、服装和场景",
            "voice": "只采用音色、语速和情绪，不覆盖文字台词",
            "music": "只用于音乐结构和情绪，不作为对白或环境声",
            "sound": "只用于声明的声音来源",
            "keyframe": "只定义声明的关键状态，不替换未声明的主体、场景或风格",
            "source": "作为唯一母版，保留原始时间线",
        }
        return f"{asset.ref}用于{asset.subject}的{asset.observations}；{exclusions[asset.role]}。"

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
            warnings.append(
                "参数提示：当前任务会由输入素材锁定"
                f"{'、'.join(locked)}；这些冲突参数已从可提交参数中移除。"
            )
        return parameters, warnings

    @staticmethod
    def _dialogue_lines(request: Sd25CompileRequest) -> list[str]:
        lines: list[str] = []
        for entry in request.dialogue:
            audio = f"，音色参考{entry.audio_ref}" if entry.audio_ref else ""
            language = f"使用{entry.language}" if entry.language else "按输入语言"
            spoken = f" {{{entry.text}}}" if entry.text else "；不编造用户未提供的台词原文"
            lines.append(
                f"{entry.position}的{entry.speaker}{language}{audio}，以{entry.delivery}的表达方式说：{spoken}；"
                "其他人物自然闭口聆听。"
            )
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
                request, used, unused, source_override="第一步输出的视频"
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
            prompt = (
                "【有序工作流：不得合并为一次任务】\n第一步：编辑\n"
                f"{edit_prompt}\n\n第二步：延长第一步验收通过的输出\n{extend_prompt}"
            )
            mode = "edit_then_extend"
            parameters = extend_parameters
            warnings = list(dict.fromkeys(edit_warnings + extend_warnings))
        else:
            prompt, mode = self._compile_generation(request, used, unused)

        if request.task != "edit_then_extend":
            parameters, warnings = self._parameters_for(request, mode)
        if request.missing_assets:
            missing = "；".join(
                f"{asset.ref}（原定用于{asset.intended_role}）" for asset in request.missing_assets
            )
            warnings.append(
                f"补充建议：未提供或无法读取{missing}；当前 Prompt 已删除这些引用，补充后可重新绑定。"
            )

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
    ) -> tuple[str, str]:
        parts = ["【生成目标】", request.goal.strip()]
        if used:
            parts.extend(["", "【参考素材职责】", *(self._asset_line(asset) for asset in used)])
        if unused:
            parts.extend([
                "", "【未采用素材】",
                *(f"{asset.ref}未参与本任务，不用于人物、场景、道具、动作、镜头或声音。" for asset in unused),
            ])

        if request.first_frame_ref:
            asset = next(asset for asset in request.assets if asset.ref == request.first_frame_ref)
            parts.extend([
                "", f"{request.first_frame_ref}作为首帧。",
                f"该首帧定义视频开始时的构图、主体位置、姿态、道具状态、场景和镜头方向：{asset.observations}。",
            ])
        if request.last_frame_ref:
            asset = next(asset for asset in request.assets if asset.ref == request.last_frame_ref)
            parts.extend([
                f"{request.last_frame_ref}作为尾帧。",
                f"该尾帧定义视频结束时的构图、主体位置、姿态、道具状态、场景和镜头方向：{asset.observations}。",
            ])

        if request.keyframe_refs:
            parts.extend([
                "", "【有序关键帧】",
                f"以{'、'.join(request.keyframe_refs)}的顺序作为关键帧。",
            ])
            for index, ref in enumerate(request.keyframe_refs, start=1):
                if ref in {request.first_frame_ref, request.last_frame_ref}:
                    continue
                asset = next(asset for asset in request.assets if asset.ref == ref)
                parts.append(
                    f"{ref}定义第{index}个关键帧：{asset.observations}；作为过程中的可见状态锚点，"
                    "不要求静态停留或逐像素复刻。"
                )
            parts.append(
                f"画面依次经过{'、'.join(request.keyframe_refs)}定义的状态，各阶段之间使用连续动作自然过渡。"
            )

        if request.storyboard_ref and request.storyboard:
            parts.extend([
                "", "【九宫格分镜结构】",
                f"{request.storyboard_ref}提供3×3九格展示页，其中有"
                f"{len(request.storyboard.panels)}个真实镜头、{request.storyboard.empty_slots}个留白格；"
                "按照从左到右、从上到下读取，不得把留白格补造成镜头；"
                "不采用图中的线稿画风、文字标注或占位人物。",
            ])
            for panel in request.storyboard.panels:
                parts.append(
                    f"镜头{panel.index}：{panel.shot_size}，{panel.lens_mm}mm {panel.aperture}，"
                    f"{panel.camera_angle}，{panel.camera_movement}；人物{'、'.join(panel.characters)}；"
                    f"动作{panel.subject_action}；表演{panel.expression}；构图{panel.composition}；"
                    f"结束状态{panel.end_state}。"
                )

        if request.blockout_ref and request.blockout_granularity:
            if request.blockout_granularity == "coarse":
                parts.extend([
                    "", "【粗粒度白模】",
                    f"{request.blockout_ref}是粗粒度白模参考，仅提供动作路径、主体站位、进出场、机位、"
                    "运镜、切镜、光影变化、声音节奏和空间关系，不采用其中的白模外观、材质和场景。",
                    "逐个几何体映射到输入已声明的最终人物或道具；轨迹线、坐标轴、控制器、相机锥体和文字标记不进入成片。",
                ])
            else:
                parts.extend([
                    "", "【细粒度白模】",
                    f"{request.blockout_ref}是细粒度白模参考，保持主体结构、动作、空间布局、机位、运镜和切镜，"
                    "不采用原有灰模材质、空白背景、轨迹线、坐标轴、控制器、相机锥体和文字标记。",
                ])

        if request.dialogue:
            parts.extend(["", "【对白账本】", *self._dialogue_lines(request)])
        parts.extend([
            "", "【事件脚本】",
            "开始时清楚呈现人物、场景、道具和特效的可观察状态；按输入因果连续完成事件，先呈现触发原因，再呈现人物反应。",
            "结束时明确人物位置、道具归属、特效状态、运动趋势与声音状态，形成可承接的边界画面。",
            "", "【保持一致】",
            "保持人物身份与数量、服装、身体拓扑、道具数量与归属、场景布局、摄影轴线、光线和声音关系稳定；同一主体不重复、不分裂。",
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
        return "\n".join(parts), mode

    def _compile_edit(
        self,
        request: Sd25CompileRequest,
        used: list[Sd25Asset],
        unused: list[Sd25Asset],
    ) -> str:
        source = request.source_video_ref
        scope_lines = {
            "visual": [
                f"仅修改明确声明的视觉对象；{source}的对白、环境声、音乐、口型时点和声音时间线保持原样。",
            ],
            "audio": [
                f"仅修改明确声明的声音对象；{source}的画面逐帧保持不变，人物身份、表情、动作、镜头、场景、道具和特效均不得重绘。",
                f"新声音严格继承{source}的原始音素时点、口型时点和音画同步，保留说话起止、停顿、呼吸、重音与环境声衔接。",
            ],
            "both": [
                f"只修改明确声明的视觉与声音对象；{source}中未声明的画面层、声音层及其同步关系保持原样。",
            ],
        }[request.edit_scope]
        parts = [
            "【编辑目标】", f"编辑{source}，{request.goal.strip()}", "",
            "【原视频职责】",
            f"{source}是唯一编辑母版，负责原始场景、机位、镜头运动、动作轨迹、遮挡关系、口型时点、声音状态和事件顺序。",
            "", "【目标素材职责】",
            *(self._asset_line(asset) for asset in used if asset.ref != source),
            "", "【编辑对象与范围】",
            request.goal.strip(),
            *scope_lines,
            (
                f"除以上明确保留对象外，删除{source}中的其他可见主体；不新增未指定对象。"
                if request.edit_scope_closure == "delete_unspecified"
                else f"除以上明确修改对象外，{source}中其他可见人物、道具和背景元素保持原样，不参与替换或删除。"
            ),
            "", "【时间线继承】",
            f"目标对象继承{source}中对应对象每次出现、运动、遮挡和离开的时点、路径与速度变化；其他动作、镜头、口型和事件顺序保持原样。",
        ]
        if request.dialogue:
            parts.extend(["", "【对白账本】", *self._dialogue_lines(request)])
        if unused:
            parts.extend(["", "【未采用素材】", *(
                f"{asset.ref}未参与本任务，不用于人物、场景、道具、动作、镜头或声音。"
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
        direction = "向前" if before else "向后"
        boundary = "首帧" if before else "尾帧"
        target = "最后一个画面" if before else "第一个画面"
        parts = [*(self._asset_line(asset) for asset in used if asset.ref != source_ref), ""]
        parts.extend([
            f"{source}是需要{direction}延长的原视频。",
            f"{direction}延长{source}。延长片段的{target}自然衔接{source}的{boundary}，保持主体姿态与朝向、道具位置、背景与空间关系、机位与构图、光线、声音状态和运动趋势连续。",
            request.goal.strip(),
            "延长过程中保持人物身份与服装、关键道具、背景布局、摄影轴线和原有声音环境连续；同一主体始终是一个连续对象，不重复、不分裂，身体结构和部件数量稳定。",
        ])
        if before:
            parts.append("只属于原视频后续的角色、道具或特效不得提前出现。")
        if unused:
            parts.extend(["", "【未采用素材】", *(
                f"{asset.ref}未参与本任务，不用于人物、场景、道具、动作、镜头或声音。"
                for asset in unused
            )])
        return "\n".join(parts)
