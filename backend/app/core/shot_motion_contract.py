"""One immutable semantic source for storyboard images and motion videos."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.reference_limits import MAX_REFERENCE_AUDIOS, MAX_REFERENCE_IMAGES, MAX_REFERENCE_VIDEOS
from app.schema.production import StoryboardPanel
from app.core import prompt_data


_WORDING_FILE = "shot_motion_contract"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/shot_motion_contract.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


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
    reference_images: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_IMAGES)
    reference_videos: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_VIDEOS)
    reference_audios: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_AUDIOS)

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
            reference_images=list(dict.fromkeys(reference_images or []))[:MAX_REFERENCE_IMAGES],
            reference_videos=list(dict.fromkeys(reference_videos or []))[:MAX_REFERENCE_VIDEOS],
            reference_audios=list(dict.fromkeys(reference_audios or []))[:MAX_REFERENCE_AUDIOS],
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
        _text_of("_invariants.text").format('、'.join(contract.characters), contract.scene, '、'.join(contract.props), '、'.join(contract.effects), contract.shot_size, contract.camera_angle, contract.lens_mm, contract.aperture, contract.composition, contract.action_axis, contract.eyeline, contract.blocking, contract.subject_action, contract.expression, contract.lighting, contract.start_state, contract.end_state, contract.continuity_in or '建立镜头', contract.continuity_out)
    )


def compile_storyboard_image_prompt(
    contract: ShotMotionContract,
    *,
    visual_style: str = _text_of("compile_storyboard_image_prompt.text"),
    frame_state: Literal["start", "end"] = "start",
) -> CompiledShotPrompt:
    state = contract.start_state if frame_state == "start" else contract.end_state
    prompt = (
        _text_of("compile_storyboard_image_prompt.prompt").format(contract.shot_id, '首帧' if frame_state == 'start' else '尾帧', _invariants(contract), state, visual_style)
    )
    return CompiledShotPrompt(
        kind="storyboard_image",
        prompt=prompt,
        contract_fingerprint=contract.contract_fingerprint,
    )


def compile_motion_prompt(contract: ShotMotionContract) -> CompiledShotPrompt:
    prompt = (
        _text_of("compile_motion_prompt.prompt").format(_invariants(contract), contract.camera_movement)
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
