"""One immutable semantic source for storyboard images and motion videos."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schema.production import StoryboardPanel


class CompiledShotPrompt(BaseModel):
    kind: Literal["storyboard_image", "motion_video"]
    prompt: str
    contract_fingerprint: str


class ShotMotionContract(BaseModel):
    """Fields that image and video generation are forbidden to reinterpret."""

    model_config = ConfigDict(extra="forbid")

    shot_id: Annotated[int, Field(ge=1, le=9999)]
    characters: Annotated[list[str], Field(min_length=1)]
    scene: Annotated[str, Field(min_length=1, max_length=1000)]
    props: Annotated[list[str], Field(min_length=1)]
    effects: Annotated[list[str], Field(min_length=1)]
    shot_size: Annotated[str, Field(min_length=1, max_length=80)]
    camera_angle: Annotated[str, Field(min_length=1, max_length=500)]
    camera_movement: Annotated[str, Field(min_length=1, max_length=500)]
    camera_reason: Annotated[str, Field(min_length=2, max_length=1000)]
    lens_mm: Annotated[int, Field(ge=8, le=600)]
    aperture: Annotated[str, Field(min_length=2, max_length=20)]
    composition: Annotated[str, Field(min_length=2, max_length=1500)]
    action_axis: Annotated[str, Field(min_length=2, max_length=1000)]
    eyeline: Annotated[str, Field(min_length=2, max_length=1000)]
    blocking: Annotated[str, Field(min_length=1, max_length=1000)]
    subject_action: Annotated[str, Field(min_length=2, max_length=3000)]
    expression: Annotated[str, Field(min_length=2, max_length=1500)]
    lighting: Annotated[str, Field(min_length=2, max_length=1000)]
    dialogue: str = ""
    sound: Annotated[str, Field(min_length=1, max_length=1000)]
    start_state: Annotated[str, Field(min_length=1, max_length=1500)]
    end_state: Annotated[str, Field(min_length=1, max_length=1500)]
    continuity_in: Annotated[str, Field(max_length=1500)] = ""
    continuity_out: Annotated[str, Field(min_length=2, max_length=1500)]
    storyboard_image: str | None = None
    reference_images: list[str] = Field(default_factory=list, max_length=9)
    reference_videos: list[str] = Field(default_factory=list, max_length=3)
    reference_audios: list[str] = Field(default_factory=list, max_length=3)

    @classmethod
    def from_panel(
        cls,
        panel: StoryboardPanel,
        *,
        storyboard_image: str | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
    ) -> "ShotMotionContract":
        return cls(
            shot_id=panel.index,
            characters=panel.characters,
            scene=panel.scene,
            props=panel.props,
            effects=panel.effects,
            shot_size=panel.shot_size,
            camera_angle=panel.camera_angle,
            camera_movement=panel.camera_movement,
            camera_reason=panel.camera_reason,
            lens_mm=panel.lens_mm,
            aperture=panel.aperture,
            composition=panel.composition,
            action_axis=panel.action_axis,
            eyeline=panel.eyeline,
            blocking=panel.blocking,
            subject_action=panel.subject_action,
            expression=panel.expression,
            lighting=panel.lighting,
            dialogue=panel.dialogue,
            sound=panel.sound,
            start_state=panel.start_state,
            end_state=panel.end_state,
            continuity_in=panel.continuity_in,
            continuity_out=panel.continuity_out,
            storyboard_image=storyboard_image,
            reference_images=list(dict.fromkeys(reference_images or []))[:9],
            reference_videos=list(dict.fromkeys(reference_videos or []))[:3],
            reference_audios=list(dict.fromkeys(reference_audios or []))[:3],
        )

    @property
    def contract_fingerprint(self) -> str:
        # Provider URLs are replaceable locators. The semantic contract remains
        # stable while a storyboard image is regenerated from the same fields.
        payload = self.model_dump(
            mode="json",
            exclude={
                "storyboard_image",
                "reference_images",
                "reference_videos",
                "reference_audios",
            },
        )
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def artifact_fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _invariants(contract: ShotMotionContract) -> str:
    return (
        f"角色：{'、'.join(contract.characters)}；场景：{contract.scene}；"
        f"道具：{'、'.join(contract.props)}；特效：{'、'.join(contract.effects)}；"
        f"景别：{contract.shot_size}；机位：{contract.camera_angle}；"
        f"镜头：{contract.lens_mm}mm {contract.aperture}；构图：{contract.composition}；"
        f"动作轴线：{contract.action_axis}；视线：{contract.eyeline}；调度：{contract.blocking}；"
        f"动作：{contract.subject_action}；表情：{contract.expression}；灯光：{contract.lighting}；"
        f"开始状态：{contract.start_state}；结束状态：{contract.end_state}；"
        f"入镜连续性：{contract.continuity_in or '建立镜头'}；出镜连续性：{contract.continuity_out}。"
    )


def compile_storyboard_image_prompt(
    contract: ShotMotionContract,
    *,
    visual_style: str = "写实真人电影质感，9:16竖屏",
    frame_state: Literal["start", "end"] = "start",
) -> CompiledShotPrompt:
    state = contract.start_state if frame_state == "start" else contract.end_state
    prompt = (
        f"镜头{contract.shot_id}的{'首帧' if frame_state == 'start' else '尾帧'}分镜图片。"
        f"{_invariants(contract)}当前必须呈现：{state}。视觉风格：{visual_style}。"
        "严格锁定角色五视图、场景布局、道具归属、特效规则、摄影轴线、光向与色温；"
        "禁止变脸、换装、道具换手、镜像翻转、文字、水印和无关人物。"
    )
    return CompiledShotPrompt(
        kind="storyboard_image",
        prompt=prompt,
        contract_fingerprint=contract.contract_fingerprint,
    )


def compile_motion_prompt(contract: ShotMotionContract) -> CompiledShotPrompt:
    prompt = (
        f"镜头{contract.shot_id}，严格依据对应分镜契约生成连续运镜视频。{_invariants(contract)}"
        f"相机以“{contract.camera_movement}”运动；运镜只为“{contract.camera_reason}”服务。"
        f"从“{contract.start_state}”自然运动到“{contract.end_state}”，"
        f"并向下一镜交付“{contract.continuity_out}”。"
        "角色、场景、道具、特效、景别、机位、焦段、构图、轴线、视线和灯光均为硬约束；"
        "保持真实物理运动、稳定面部、手指和服装纹理，禁止无动机切镜、瞬移、变脸、"
        "道具换手、轴线翻转或新增画面元素。"
    )
    return CompiledShotPrompt(
        kind="motion_video",
        prompt=prompt,
        contract_fingerprint=contract.contract_fingerprint,
    )


def assert_prompt_pair_consistent(
    storyboard_prompt: CompiledShotPrompt,
    motion_prompt: CompiledShotPrompt,
) -> None:
    if storyboard_prompt.contract_fingerprint != motion_prompt.contract_fingerprint:
        raise ValueError("storyboard image and motion prompts were compiled from different shot contracts")
