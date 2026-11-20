"""Typed contracts for the universal storyboard-director capability."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.frame_position import FramePosition
from app.core import prompt_data


_WORDING_FILE = "schema_storyboard_director"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_storyboard_director.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


BoundedText = Annotated[str, Field(min_length=1, max_length=4_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class DirectorCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    identity: ShortText = _text_of("DirectorCharacter.identity")
    age_impression: ShortText = _text_of("DirectorCharacter.age_impression")
    appearance: BoundedText
    costume: BoundedText
    accessories: ShortText = _text_of("DirectorCharacter.accessories")
    physical_state: ShortText = _text_of("DirectorCharacter.physical_state")
    psychological_state: ShortText = _text_of("DirectorCharacter.psychological_state")


class DirectorProp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    initial_state: ShortText
    initial_position: ShortText
    allowed_motion: ShortText = _text_of("DirectorProp.allowed_motion")


class SceneLandmark(BaseModel):
    """A fixed spatial anchor written relative to the character, never as a bare place.

    "摩托车在路边" lets the model mirror the frame; "角色西偏西南约15米，道路南侧"
    is what keeps left/right stable across beats.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    relative_position: ShortText
    form_and_count: ShortText = _text_of("SceneLandmark.form_and_count")


class DirectorScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: ShortText
    location: ShortText
    weather: ShortText = _text_of("DirectorScene.weather")
    spatial_structure: BoundedText
    landmarks: Annotated[list[SceneLandmark], Field(max_length=50)] = Field(default_factory=list)
    ground_material: ShortText = _text_of("DirectorScene.ground_material")
    initial_environment_state: ShortText = _text_of("DirectorScene.initial_environment_state")
    props: Annotated[list[DirectorProp], Field(min_length=1, max_length=100)]
    environmental_sound: ShortText = _text_of("DirectorScene.environmental_sound")
    sound_policy: ShortText = _text_of("DirectorScene.sound_policy")


class SoundDesign(BaseModel):
    """Near / mid / far sound layers plus music entry and deliberate silence."""

    model_config = ConfigDict(extra="forbid")

    near: ShortText = _text_of("SoundDesign.near")
    mid: ShortText = _text_of("SoundDesign.mid")
    far: ShortText = _text_of("SoundDesign.far")
    music_entry: ShortText = _text_of("SoundDesign.music_entry")
    silence: ShortText = _text_of("SoundDesign.silence")


class DirectorExtras(BaseModel):
    """Enemies or background performers. Omit the whole block when the shot has none."""

    model_config = ConfigDict(extra="forbid")

    label: ShortText = _text_of("DirectorExtras.label")
    reference_note: ShortText = _text_of("DirectorExtras.reference_note")
    initial_distribution: BoundedText
    motion_parameters: BoundedText
    hit_reaction_rules: ShortText = _text_of("DirectorExtras.hit_reaction_rules")
    stagger_seconds: Annotated[float, Field(ge=0, le=10)] = 0.3


class DamageTimelineEntry(BaseModel):
    """One dated change to wounds, tears or stains; anything outside the table is forbidden."""

    model_config = ConfigDict(extra="forbid")

    seconds: Annotated[float, Field(ge=0, le=300)]
    subject: Annotated[str, Field(min_length=1, max_length=120)]
    change: ShortText

    @model_validator(mode="after")
    def millisecond_precision(self) -> "DamageTimelineEntry":
        if round(self.seconds, 3) != self.seconds:
            raise ValueError("damage timeline times support at most millisecond precision")
        return self


class TimedSound(BaseModel):
    """A synchronous sound effect pinned to a time range; music is never generated here."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: Annotated[float, Field(ge=0, le=300)]
    end_seconds: Annotated[float, Field(gt=0, le=300)]
    description: ShortText

    @model_validator(mode="after")
    def ordered_range(self) -> "TimedSound":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("timed sound end_seconds must be greater than start_seconds")
        if any(round(value, 3) != value for value in (self.start_seconds, self.end_seconds)):
            raise ValueError("timed sound times support at most millisecond precision")
        return self


class TimedDialogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dialogue", "narration", "inner_monologue"]
    speaker: Annotated[str, Field(min_length=1, max_length=120)]
    exact_text: Annotated[str, Field(min_length=1, max_length=2_000)]
    start_seconds: Annotated[float, Field(ge=0, le=300)]
    end_seconds: Annotated[float, Field(gt=0, le=300)]

    @model_validator(mode="after")
    def ordered_range(self) -> "TimedDialogue":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("dialogue end_seconds must be greater than start_seconds")
        if any(round(value, 3) != value for value in (self.start_seconds, self.end_seconds)):
            raise ValueError("dialogue times support at most millisecond precision")
        return self


class StoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["action", "dialogue", "narration", "inner_monologue", "transition"] = "action"
    text: BoundedText
    speaker: Annotated[str, Field(max_length=120)] = ""
    exact_text: Annotated[str, Field(max_length=2_000)] = ""
    observable_pose: Annotated[str, Field(max_length=2_000)] = ""
    prop_change: Annotated[str, Field(max_length=2_000)] = ""

    @model_validator(mode="after")
    def dialogue_is_verbatim(self) -> "StoryEvent":
        if self.kind in {"dialogue", "narration", "inner_monologue"} and not self.exact_text.strip():
            raise ValueError("spoken events require exact_text so dialogue cannot be invented")
        return self


APPEARANCE_REFERENCE_VIDEO_POLICY = _text_of("module.appearance_reference_video_policy")
# A user-supplied motion reference (a stunt take, a rehearsal clip) is the opposite job: it lends the
# body's path and the timing of the force, and nothing that belongs to the approved assets.
MOTION_REFERENCE_VIDEO_POLICY = (
    _text_of("module.motion_reference_video_policy")
)


class GlobalVisualRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_style: BoundedText = _text_of("GlobalVisualRules.visual_style")
    era_and_region: ShortText = _text_of("GlobalVisualRules.era_and_region")
    art_direction: BoundedText = _text_of("GlobalVisualRules.art_direction")
    rendering_texture: BoundedText = _text_of("GlobalVisualRules.rendering_texture")
    authenticity: ShortText = _text_of("GlobalVisualRules.authenticity")
    overall_atmosphere: ShortText = _text_of("GlobalVisualRules.overall_atmosphere")
    reference_image_policy: ShortText = (
        _text_of("GlobalVisualRules.reference_image_policy")
    )
    # What a reference video is for: the default locks appearance; "motion_trajectory" is the
    # user's own motion reference, which locks only the body's path and force timing.
    reference_video_role: Literal["appearance", "motion_trajectory"] = "appearance"
    reference_video_policy: ShortText = APPEARANCE_REFERENCE_VIDEO_POLICY
    exclusions: Annotated[list[str], Field(min_length=1, max_length=50)] = Field(default_factory=lambda: list(_words_of("GlobalVisualRules.default_factory")))

    @model_validator(mode="after")
    def motion_reference_policy(self) -> "GlobalVisualRules":
        # Only the untouched default follows the role; a policy written by hand stays as written.
        if self.reference_video_role == "motion_trajectory" and self.reference_video_policy == APPEARANCE_REFERENCE_VIDEO_POLICY:
            self.reference_video_policy = MOTION_REFERENCE_VIDEO_POLICY
        return self


class ContinuityLocks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    face_anchor: BoundedText
    body_anchor: BoundedText
    costume_anchor: BoundedText
    accessory_anchor: ShortText = _text_of("ContinuityLocks.accessory_anchor")
    wound_and_stain_anchor: ShortText = _text_of("ContinuityLocks.wound_and_stain_anchor")
    damage_closure: ShortText = _text_of("ContinuityLocks.damage_closure")
    mirror_lock: ShortText = _text_of("ContinuityLocks.mirror_lock")
    scene_structure: BoundedText
    prop_positions: BoundedText
    key_light_direction: ShortText
    camera_axis: ShortText
    screen_direction: ShortText
    spatial_orientation: BoundedText


class ShotVisualDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_content: BoundedText
    composition: BoundedText
    shot_size: ShortText = _text_of("ShotVisualDesign.shot_size")
    lens: ShortText = _text_of("ShotVisualDesign.lens")
    camera_angle: ShortText = _text_of("ShotVisualDesign.camera_angle")
    camera_height: ShortText = _text_of("ShotVisualDesign.camera_height")
    depth_of_field: ShortText = _text_of("ShotVisualDesign.depth_of_field")
    spatial_layers: BoundedText
    # Subjects in screen coordinates: region, depth layer, facing, occlusion, forbidden zone.
    frame_positions: Annotated[list[FramePosition], Field(max_length=30)] = Field(default_factory=list)


class ColorDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: ShortText
    secondary_color: ShortText
    accent_color: ShortText
    color_temperature: ShortText
    saturation: ShortText = _text_of("ColorDesign.saturation")
    brightness: ShortText = _text_of("ColorDesign.brightness")
    contrast: ShortText = _text_of("ColorDesign.contrast")
    blacks_and_highlights: ShortText = _text_of("ColorDesign.blacks_and_highlights")
    # Tension handbook: dark share and hard-light ratio decide how much the frame withholds.
    light_ratio: ShortText = _text_of("ColorDesign.light_ratio")
    skin_tone_strategy: ShortText = _text_of("ColorDesign.skin_tone_strategy")
    grading_reference: ShortText = _text_of("ColorDesign.grading_reference")
    start_state: ShortText
    change_reason: ShortText = _text_of("ColorDesign.change_reason")
    peak_state: ShortText
    end_state: ShortText


class DynamicsDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_direction: ShortText
    subject_trajectory: ShortText
    force_source: ShortText
    speed_curve: ShortText
    center_of_gravity: ShortText
    visual_flow: ShortText
    secondary_motion: ShortText
    inertia_and_follow_through: ShortText
    motion_blur: ShortText
    stable_regions: ShortText


class CameraDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    movement_type: ShortText
    start_position: BoundedText
    end_position: BoundedText
    path: ShortText
    direction: ShortText
    speed_curve: ShortText
    subject_following: ShortText
    composition_change: BoundedText
    focus_change: ShortText
    stability: ShortText
    forbidden_behaviors: BoundedText


class TransitionEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjacent_shot: ShortText = _text_of("TransitionEdge.adjacent_shot")
    transition_type: ShortText = _text_of("TransitionEdge.transition_type")
    visual_handoff: BoundedText
    audio_handoff: BoundedText
    duration_seconds: Annotated[float, Field(ge=0, le=30)] = 0
    included_in_shot_duration: bool = False


class TransitionDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: TransitionEdge
    internal_linkage: BoundedText = _text_of("TransitionDesign.internal_linkage")
    exit: TransitionEdge


class StoryboardDirectorRequest(BaseModel):
    """Complete user-authored foundation for one continuous camera shot."""

    model_config = ConfigDict(extra="forbid")

    project_name: Annotated[str, Field(min_length=1, max_length=300)]
    episode: ShortText = _text_of("StoryboardDirectorRequest.episode")
    scene_number: Annotated[int, Field(ge=1, le=10_000)] = 1
    shot_number: ShortText
    duration_seconds: Annotated[float, Field(ge=0.5, le=300)]
    aspect_ratio: Literal["9:16", "16:9", "2.39:1"] = "9:16"
    fps: Literal[24, 25, 30] = 24
    grid_spec: Literal["3x3"] = "3x3"
    script_text: Annotated[str, Field(min_length=1, max_length=100_000)]
    narrative_goal: BoundedText
    characters: Annotated[list[DirectorCharacter], Field(max_length=100)]
    scene: DirectorScene
    timed_dialogue: Annotated[list[TimedDialogue], Field(max_length=100)] = Field(default_factory=list)
    timed_sounds: Annotated[list[TimedSound], Field(max_length=100)] = Field(default_factory=list)
    sound_design: SoundDesign = Field(default_factory=SoundDesign)
    damage_timeline: Annotated[list[DamageTimelineEntry], Field(max_length=100)] = Field(default_factory=list)
    extras: DirectorExtras | None = None
    events: Annotated[list[StoryEvent], Field(max_length=90)] = Field(default_factory=list)
    global_visual: GlobalVisualRules
    continuity: ContinuityLocks
    shot_visual: ShotVisualDesign
    color: ColorDesign
    dynamics: DynamicsDesign
    camera: CameraDesign
    transitions: TransitionDesign
    max_total_beats: Annotated[int, Field(ge=1, le=90)] = 90
    # Measurements of the scene's spatial stage (who is in frame, axis, screen sides); they join
    # the continuity checks, so an error-level spatial failure holds the scene back from stage 5.
    spatial_checks: Annotated[list["ContinuityCheckItem"], Field(max_length=20)] = Field(default_factory=list)
    # How each shot hands over to the next (size steps, 30-degree rule, eyelines, motion joins, rhythm).
    transition_checks: Annotated[list["ContinuityCheckItem"], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeline_inputs(self) -> "StoryboardDirectorRequest":
        if round(self.duration_seconds, 3) != self.duration_seconds:
            raise ValueError("duration_seconds supports at most millisecond precision")
        if any(line.end_seconds > self.duration_seconds for line in self.timed_dialogue):
            raise ValueError("timed dialogue must stay inside the shot duration")
        if any(sound.end_seconds > self.duration_seconds for sound in self.timed_sounds):
            raise ValueError("timed sounds must stay inside the shot duration")
        if any(entry.seconds > self.duration_seconds for entry in self.damage_timeline):
            raise ValueError("damage timeline entries must stay inside the shot duration")
        if any(
            left.seconds > right.seconds
            for left, right in zip(self.damage_timeline, self.damage_timeline[1:], strict=False)
        ):
            raise ValueError("damage timeline entries must be listed in time order")
        if len(self.events) > self.max_total_beats:
            raise ValueError("event count exceeds max_total_beats")
        return self


class StoryboardTimeBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: Annotated[int, Field(ge=1, le=90)]
    page_number: Annotated[int, Field(ge=1, le=10)]
    page_slot: Annotated[int, Field(ge=1, le=9)]
    start_seconds: Annotated[float, Field(ge=0, le=300)]
    keyframe_seconds: Annotated[float, Field(ge=0, le=300)]
    end_seconds: Annotated[float, Field(gt=0, le=300)]
    duration_seconds: Annotated[float, Field(gt=0, le=300)]
    action_phase: Literal["准备", "开始", "发展", "峰值", "结果", "收束"]
    core_event: BoundedText
    start_state: BoundedText
    keyframe_state: BoundedText
    end_state: BoundedText
    character_pose: BoundedText
    subject_dynamics: BoundedText
    secondary_dynamics: BoundedText
    camera_state: BoundedText
    color_state: BoundedText
    change_from_previous: BoundedText
    verbatim_line: Annotated[str, Field(max_length=2_000)] = ""
    environmental_sound: ShortText
    linkage: BoundedText

    @model_validator(mode="after")
    def valid_time_order(self) -> "StoryboardTimeBeat":
        if not self.start_seconds <= self.keyframe_seconds <= self.end_seconds:
            raise ValueError("each beat requires start <= keyframe <= end")
        if round(self.end_seconds - self.start_seconds, 3) != round(self.duration_seconds, 3):
            raise ValueError("beat duration must equal end_seconds - start_seconds")
        return self


class StillFramePrompt(BaseModel):
    beat_index: int
    keyframe_seconds: float
    action_phase: str
    prompt: Annotated[str, Field(min_length=1, max_length=30_000)]
    exclusions: Annotated[list[str], Field(min_length=1, max_length=50)]


class VideoSegmentPrompt(BaseModel):
    segment_index: Annotated[int, Field(ge=1, le=89)]
    from_beat: Annotated[int, Field(ge=1, le=89)]
    to_beat: Annotated[int, Field(ge=2, le=90)]
    start_seconds: Annotated[float, Field(ge=0, le=300)]
    end_seconds: Annotated[float, Field(gt=0, le=300)]
    duration_seconds: Annotated[float, Field(gt=0, le=300)]
    start_keyframe: Annotated[int, Field(ge=1, le=89)]
    end_keyframe: Annotated[int, Field(ge=2, le=90)]
    prompt: Annotated[str, Field(min_length=1, max_length=40_000)]
    exclusions: Annotated[list[str], Field(min_length=1, max_length=50)]


class StoryboardGridCell(BaseModel):
    slot: Annotated[int, Field(ge=1, le=9)]
    beat_index: Annotated[int | None, Field(ge=1, le=90)] = None
    still_prompt: Annotated[str, Field(max_length=30_000)] = ""
    empty: bool

    @model_validator(mode="after")
    def empty_cell_has_no_content(self) -> "StoryboardGridCell":
        if self.empty and (self.beat_index is not None or self.still_prompt):
            raise ValueError("empty grid cells cannot contain a beat or prompt")
        if not self.empty and (self.beat_index is None or not self.still_prompt):
            raise ValueError("used grid cells require a beat and still prompt")
        return self


class StoryboardGridPage(BaseModel):
    page_number: Annotated[int, Field(ge=1, le=10)]
    rows: Literal[3] = 3
    columns: Literal[3] = 3
    reading_order: Literal["left_to_right_top_to_bottom"] = "left_to_right_top_to_bottom"
    cells: Annotated[list[StoryboardGridCell], Field(min_length=9, max_length=9)]
    used_slots: Annotated[int, Field(ge=1, le=9)]
    empty_slots: Annotated[int, Field(ge=0, le=8)]
    composite_prompt: Annotated[str, Field(min_length=1, max_length=100_000)]

    @model_validator(mode="after")
    def exact_grid(self) -> "StoryboardGridPage":
        if [cell.slot for cell in self.cells] != list(range(1, 10)):
            raise ValueError("grid cells must be ordered exactly from 1 through 9")
        used = sum(not cell.empty for cell in self.cells)
        if used != self.used_slots or 9 - used != self.empty_slots:
            raise ValueError("grid used/empty slot counts do not match cells")
        return self


class ContinuityCheckItem(BaseModel):
    code: Annotated[str, Field(pattern=r"^[a-z0-9_]{3,80}$")]
    passed: bool
    severity: Literal["error", "warning"] = "error"
    detail: BoundedText


class StoryboardDirectorResult(BaseModel):
    schema_version: Literal["storyboard-director.v1"] = "storyboard-director.v1"
    project_name: str
    episode: str
    scene_number: int
    shot_number: str
    duration_seconds: float
    aspect_ratio: str
    fps: int
    grid_spec: Literal["3x3"] = "3x3"
    foundation: dict[str, object]
    beats: Annotated[list[StoryboardTimeBeat], Field(min_length=1, max_length=90)]
    still_prompts: Annotated[list[StillFramePrompt], Field(min_length=1, max_length=90)]
    video_segments: Annotated[list[VideoSegmentPrompt], Field(max_length=89)]
    grid_pages: Annotated[list[StoryboardGridPage], Field(min_length=1, max_length=10)]
    continuity_checks: Annotated[list[ContinuityCheckItem], Field(min_length=1, max_length=50)]
    plan_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    submission_ready: bool
    warnings: list[str] = Field(default_factory=list, max_length=100)


StoryboardDirectorRequest.model_rebuild()
