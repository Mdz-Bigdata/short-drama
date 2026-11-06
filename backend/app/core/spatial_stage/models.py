# -*- coding: utf-8 -*-
"""The spatial stage of one scene: who stands where, what the set holds, where
every camera is, and what each shot therefore shows.

One plan per scene is the scene's spatial truth. Shots do not describe blocking
on their own; they name a camera on this stage, and the screen positions,
eyelines and axis statement of the shot are *computed* from it. That is what
keeps left/right, distance and eyeline identical across the nine panels of a
board and across every scene shot in the same location.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PLAN_VERSION = 1

Meters = Annotated[float, Field(ge=-500, le=500)]
GroundPoint = Annotated[list[Meters], Field(min_length=2, max_length=2)]
SpacePoint = Annotated[list[Meters], Field(min_length=3, max_length=3)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")]
Name = Annotated[str, Field(min_length=1, max_length=120)]

ActorRole = Literal["principal", "supporting", "crowd"]
# The posture vocabulary follows the pose presets a 3D director desk offers
# (stand / walk / run / sit / crouch / kneel / fight …) so a stage exported to
# one maps onto its presets without a lookup table.
Posture = Literal["stand", "walk", "run", "sit", "crouch", "kneel", "lie", "fight", "bow", "lean"]
ScreenSide = Literal["left", "right", "center"]
LandmarkKind = Literal["prop", "furniture", "architecture", "light"]
AxisKind = Literal["dialogue", "gaze", "motion", "none"]
ShotFunction = Literal["establish", "relation", "single", "over_shoulder", "reaction", "detail", "empty"]
CameraMoveKind = Literal["static", "push", "pull", "pan", "track", "orbit", "rise", "fall", "follow"]
Crossing = Literal["none", "neutral", "moving", "reestablish"]
Severity = Literal["error", "warning"]
PlanSource = Literal["auto", "edited"]
# Who decided the blocking: the rule planner, or a text model the rules then checked.
PlanPlanner = Literal["rules", "model"]
# The three figures of the director desk. A stand-in has no limbs on purpose: a video model copies
# a white model's pose, so limbs are opt-in (mannequin / humanoid) and flagged when a clip shows them.
FigureKind = Literal["standin", "mannequin", "humanoid"]
LandmarkShape = Literal["box", "cylinder", "sphere", "cone", "wedge", "plane"]
# "blockout": built from a reference image, replaced as a set and kept out of prompts except its largest pieces.
LandmarkOrigin = Literal["", "blockout"]
BackdropKind = Literal["none", "color", "image", "panorama"]
Easing = Literal["linear", "smooth", "ease-in", "ease-out", "hold", "whip"]
HexColor = Annotated[str, Field(pattern=r"^(?:#[0-9A-Fa-f]{6})?$")]
JointKey = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,59}$")]
JointDegrees = Annotated[float, Field(ge=-180, le=180)]
Yaw = Annotated[float, Field(ge=-360, le=360)]
KeyTime = Annotated[float, Field(ge=0, le=30)]

MAX_ACTORS = 200
MAX_POSE_JOINTS = 120
MAX_TRACK_KEYS = 120
# A reference image turned into a blockout is many pieces; a hand-dressed set rarely passes a few dozen.
MAX_LANDMARKS = 240
MAX_TRACK_CLIPS = 40
MAX_LANDMARK_PARTS = 64
# Every piece of a stage together: plans are stored and sent whole on each edit.
MAX_STAGE_PARTS = 2400


class StageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StagePose(StageModel):
    """Joint angles of a posed figure, in degrees, keyed by the desk's control names."""

    preset: Annotated[str, Field(max_length=60)] = ""
    joints: Annotated[dict[JointKey, JointDegrees], Field(max_length=MAX_POSE_JOINTS)] = Field(default_factory=dict)
    clip: Annotated[str, Field(max_length=80)] = ""
    clip_phase: Annotated[float, Field(ge=0, le=1)] = 0.0


class StageActor(StageModel):
    id: Identifier
    name: Name
    position: GroundPoint
    yaw_deg: Annotated[float, Field(ge=-360, le=360)] = 0.0
    height_m: Annotated[float, Field(ge=0.4, le=3.0)] = 1.7
    posture: Posture = "stand"
    role: ActorRole = "supporting"
    # Which side of the frame this character keeps whenever the pair is on screen.
    screen_side: ScreenSide = "center"
    note: Annotated[str, Field(max_length=300)] = ""
    figure: FigureKind = "standin"
    body_type: Annotated[str, Field(min_length=1, max_length=40)] = "standard"
    color: HexColor = ""
    # Members of one crowd array share it; empty for everyone else.
    crowd_id: Annotated[str, Field(max_length=80)] = ""
    pose: StagePose | None = None


class StageCrowd(StageModel):
    """How a crowd array was laid out, kept so it can be moved, turned and re-spaced as one piece."""

    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=40)]
    rows: Annotated[int, Field(ge=1, le=20)]
    columns: Annotated[int, Field(ge=1, le=20)]
    spacing: Annotated[float, Field(ge=0.3, le=10)] = 1.0
    center: GroundPoint
    yaw_deg: Yaw = 0.0
    body_type: Annotated[str, Field(min_length=1, max_length=40)] = "standard"
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)] = 0


class LandmarkPart(StageModel):
    """One volume of a set piece built from several, in fractions of the piece's size so it scales with it.

    ``center`` is [x, y, z] from the piece's ground centre (y up, +z its front); ``size`` is [width, depth,
    height]; ``rotation`` is degrees about x, y, z. Drawn with the rotation applied after the scale, so a wheel
    lying on its side stays a wheel when the piece is stretched.
    """

    shape: LandmarkShape = "box"
    center: Annotated[list[Annotated[float, Field(ge=-4, le=4)]], Field(min_length=3, max_length=3)]
    size: Annotated[list[Annotated[float, Field(gt=0, le=4)]], Field(min_length=3, max_length=3)]
    rotation: Annotated[list[Annotated[float, Field(ge=-360, le=360)]], Field(min_length=3, max_length=3)] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
    )
    # Darker or lighter than the piece's own colour, so its parts read apart in a grey render.
    tone: Literal["", "dark", "light"] = ""


class StageLandmark(StageModel):
    id: Identifier
    name: Name
    kind: LandmarkKind = "prop"
    position: GroundPoint
    size: Annotated[list[Annotated[float, Field(ge=0.02, le=200)]], Field(min_length=3, max_length=3)] = Field(
        default_factory=lambda: [0.6, 0.6, 0.8]
    )
    note: Annotated[str, Field(max_length=300)] = ""
    yaw_deg: Yaw = 0.0
    shape: LandmarkShape = "box"
    # Empty means "the colour of its kind".
    color: HexColor = ""
    # Element-library GLB drawn in place of the primitive.
    element_id: Annotated[str, Field(max_length=120)] = ""
    # Height of the piece's underside above the floor: a roof on a wall, a shelf on a counter.
    elevation_m: Annotated[float, Field(ge=0, le=100)] = 0.0
    origin: LandmarkOrigin = ""
    # Which built-in model this piece was made from, when one was named.
    kit: Annotated[str, Field(max_length=60)] = ""
    # Empty: the piece is the single volume ``shape`` describes.
    parts: Annotated[list[LandmarkPart], Field(max_length=MAX_LANDMARK_PARTS)] = Field(default_factory=list)


class StageBackdrop(StageModel):
    """The scene's reference backdrop: what the *lens* sees behind the stage, and nothing more.

    It is a reference underlay for framing, not set dressing: the director view never draws it,
    it is excluded from a delivered still or clip unless the operator asks for it, and nothing
    about it reaches a prompt.
    """

    kind: BackdropKind = "none"
    # A flat colour behind the stage; empty falls back to the viewport's own background.
    color: HexColor = ""
    # http(s) only: the desk uploads the picture and stores the URL the server hands back.
    url: Annotated[str, Field(max_length=2000)] = ""
    # Where the seam of a panorama sits. A flat image hangs square to the lens, so it ignores this.
    yaw_deg: Yaw = 0.0
    opacity: Annotated[float, Field(ge=0, le=1)] = 1.0

    @model_validator(mode="after")
    def source_matches_kind(self) -> "StageBackdrop":
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError("a backdrop url must be an http(s) address")
        if self.kind in {"image", "panorama"} and not self.url:
            raise ValueError("an image or panorama backdrop needs a url")
        return self


class StageAxis(StageModel):
    """The line cameras must stay on one side of."""

    kind: AxisKind = "none"
    from_name: Annotated[str, Field(max_length=120)] = ""
    to_name: Annotated[str, Field(max_length=120)] = ""
    start: GroundPoint = Field(default_factory=lambda: [0.0, 0.0])
    end: GroundPoint = Field(default_factory=lambda: [0.0, 0.0])
    # +1 / -1: the side of start→end the coverage was established on; 0 when there is no axis.
    camera_side: Literal[-1, 0, 1] = 0


class CameraMove(StageModel):
    kind: CameraMoveKind = "static"
    end_position: SpacePoint | None = None
    end_target: SpacePoint | None = None


class StageCamera(StageModel):
    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=160)]
    position: SpacePoint
    target: SpacePoint
    lens_mm: Annotated[float, Field(ge=8, le=600)] = 50.0
    # The long side of the sensor; a lens is only a field of view once it is known.
    sensor_mm: Annotated[float, Field(ge=4, le=80)] = 36.0
    fov_deg: Annotated[float, Field(ge=1, le=170)] = 39.6
    aspect: Annotated[str, Field(pattern=r"^\d{1,3}(?:\.\d+)?:\d{1,3}(?:\.\d+)?$")] = "9:16"
    shot_size: Annotated[str, Field(max_length=80)] = "中景"
    angle: Annotated[str, Field(max_length=120)] = "平视"
    function: ShotFunction = "single"
    subjects: Annotated[list[Name], Field(max_length=40)] = Field(default_factory=list)
    move: CameraMove = Field(default_factory=CameraMove)

    @property
    def equivalent_lens_mm(self) -> float:
        """The full-frame lens with this field of view: what a prompt's millimetres are read as."""
        return round(self.lens_mm * 36.0 / self.sensor_mm, 1)


class ScreenState(StageModel):
    """Where one character lands in the frame of one shot."""

    name: Name
    visible: bool
    x: Annotated[float, Field(ge=-50, le=50)]
    y: Annotated[float, Field(ge=-50, le=50)]
    depth_m: Annotated[float, Field(ge=-500, le=500)]
    height_fraction: Annotated[float, Field(ge=0, le=100)]
    region: Annotated[str, Field(max_length=60)] = ""
    depth_layer: Annotated[str, Field(max_length=40)] = ""
    facing: Annotated[str, Field(max_length=60)] = ""
    occluded_by: Annotated[str, Field(max_length=120)] = ""


class ShotText(StageModel):
    """The prose a shot contract receives; every sentence is derived from the geometry."""

    camera_angle: Annotated[str, Field(max_length=120)] = ""
    composition: Annotated[str, Field(max_length=1000)] = ""
    action_axis: Annotated[str, Field(max_length=500)] = ""
    eyeline: Annotated[str, Field(max_length=500)] = ""
    blocking: Annotated[str, Field(max_length=800)] = ""
    camera_start: Annotated[str, Field(max_length=500)] = ""
    camera_end: Annotated[str, Field(max_length=500)] = ""


class ActorOverride(StageModel):
    """Where a character is for one shot when that differs from their mark (an entrance, a fall)."""

    name: Name
    # A position here is where the character *starts* the shot; they end it on their mark.
    position: GroundPoint | None = None
    yaw_deg: Annotated[float, Field(ge=-360, le=360)] | None = None
    posture: Posture | None = None
    # Not on the set yet: the character enters in a later shot.
    offstage: bool = False
    # The position holds for the whole shot: the move onto the mark comes in a later shot.
    hold: bool = False
    reason: Annotated[str, Field(max_length=200)] = ""
    pose: StagePose | None = None


class StageShot(StageModel):
    shot_id: Annotated[int, Field(ge=1, le=10_000)]
    camera_id: Identifier
    subjects: Annotated[list[Name], Field(max_length=40)] = Field(default_factory=list)
    speaker: Annotated[str, Field(max_length=120)] = ""
    # What the storyboard says happens, kept so a blocking edit can be re-checked against it.
    action: Annotated[str, Field(max_length=1000)] = ""
    overrides: Annotated[list[ActorOverride], Field(max_length=60)] = Field(default_factory=list)
    function: ShotFunction = "single"
    axis_side: Literal[-1, 0, 1] = 0
    crossing: Crossing = "none"
    screen: Annotated[list[ScreenState], Field(max_length=MAX_ACTORS)] = Field(default_factory=list)
    text: ShotText = Field(default_factory=ShotText)
    # Candidate lenses a person is comparing; ``camera_id`` stays the one that films.
    alt_camera_ids: Annotated[list[Identifier], Field(max_length=8)] = Field(default_factory=list)

    @model_validator(mode="after")
    def candidates_are_distinct(self) -> "StageShot":
        if len(self.alt_camera_ids) != len(set(self.alt_camera_ids)) or self.camera_id in self.alt_camera_ids:
            raise ValueError("a shot's candidate cameras must be distinct and exclude the camera that films it")
        return self


def _strictly_increasing(keys: list, duration_s: float, label: str) -> None:
    times = [key.time for key in keys]
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError(f"{label} keys must be strictly increasing in time")
    if times and times[-1] > duration_s + 1e-6:
        raise ValueError(f"{label} keys must lie within the timeline's duration")


class CameraKey(StageModel):
    time: KeyTime
    position: SpacePoint
    target: SpacePoint
    lens_mm: Annotated[float, Field(ge=8, le=600)] = 50.0
    easing: Easing = "linear"

    @model_validator(mode="after")
    def looks_somewhere(self) -> "CameraKey":
        if sum((self.position[i] - self.target[i]) ** 2 for i in range(3)) < 1e-4:
            raise ValueError("a camera key's position and target must differ")
        return self


class ActorKey(StageModel):
    """A whole-figure key: any of place, facing and pose; what a key leaves out is carried from the key before."""

    time: KeyTime
    position: GroundPoint | None = None
    yaw_deg: Yaw | None = None
    pose: StagePose | None = None
    easing: Easing = "linear"

    @model_validator(mode="after")
    def says_something(self) -> "ActorKey":
        if self.position is None and self.yaw_deg is None and self.pose is None:
            raise ValueError("an actor key needs a position, a yaw or a pose")
        return self


def _in_order_without_overlap(clips: list, duration_s: float, label: str) -> None:
    ordered = sorted(clips, key=lambda clip: clip.start)
    if any(later.start < earlier.end - 1e-6 for earlier, later in zip(ordered, ordered[1:])):
        raise ValueError(f"{label} clips must not overlap")
    if ordered and max(clip.end for clip in ordered) > duration_s + 1e-6:
        raise ValueError(f"{label} clips must lie within the timeline's duration")


class ActionClip(StageModel):
    """One named motion on an actor's action track: what the figure does from ``start`` to ``end``."""

    id: Identifier
    clip: Annotated[str, Field(min_length=1, max_length=80)]
    start: KeyTime
    end: KeyTime
    speed: Annotated[float, Field(ge=0.1, le=4)] = 1.0
    # Where in the motion the block opens, so a trimmed head skips rather than squeezes.
    offset: Annotated[float, Field(ge=0, le=1)] = 0.0

    @model_validator(mode="after")
    def runs_forward(self) -> "ActionClip":
        if self.end <= self.start:
            raise ValueError("a clip's end must come after its start")
        return self


class FollowClip(StageModel):
    """The filming lens tied to a character for a stretch of the shot.

    ``offset`` is ``[right, up, back]`` in metres. In the character's own frame when ``relative`` is
    ``"actor"`` (the lens swings round as they turn), along the world axes when ``"world"``.
    """

    id: Identifier
    actor: Name
    start: KeyTime
    end: KeyTime
    offset: SpacePoint = Field(default_factory=lambda: [0.0, 0.3, 1.2])
    relative: Literal["actor", "world"] = "actor"
    # Where on the body the lens aims, as a fraction of standing height: 0.9 is the head, 0.55 the waist.
    aim: Annotated[float, Field(ge=0, le=1.2)] = 0.9
    # The lens lags by averaging the character over this window, so a jerky walk does not shake the frame.
    damping_s: Annotated[float, Field(ge=0, le=2)] = 0.3
    # The way in and out of the clip; 0 is a hard cut.
    blend_s: Annotated[float, Field(ge=0, le=3)] = 0.0
    lens_mm: Annotated[float, Field(ge=8, le=600)] | None = None

    @model_validator(mode="after")
    def runs_forward(self) -> "FollowClip":
        if self.end <= self.start:
            raise ValueError("a clip's end must come after its start")
        return self


class CameraCut(StageModel):
    """A stretch of the shot filmed through one of its candidate lenses: a cut inside the shot, without a second shot."""

    id: Identifier
    camera_id: Identifier
    start: KeyTime
    end: KeyTime

    @model_validator(mode="after")
    def runs_forward(self) -> "CameraCut":
        if self.end <= self.start:
            raise ValueError("a cut's end must come after its start")
        return self


class ShotTimeline(StageModel):
    duration_s: Annotated[float, Field(ge=1, le=30)] = 5.0
    fps: Literal[24, 25, 30] = 24
    camera: Annotated[list[CameraKey], Field(max_length=MAX_TRACK_KEYS)] = Field(default_factory=list)
    actors: Annotated[
        dict[Name, Annotated[list[ActorKey], Field(max_length=MAX_TRACK_KEYS)]], Field(max_length=MAX_ACTORS)
    ] = Field(default_factory=dict)
    clips: Annotated[
        dict[Name, Annotated[list[ActionClip], Field(max_length=MAX_TRACK_CLIPS)]], Field(max_length=MAX_ACTORS)
    ] = Field(default_factory=dict)
    follow: Annotated[list[FollowClip], Field(max_length=MAX_TRACK_CLIPS)] = Field(default_factory=list)
    cuts: Annotated[list[CameraCut], Field(max_length=MAX_TRACK_CLIPS)] = Field(default_factory=list)

    @model_validator(mode="after")
    def keys_are_ordered(self) -> "ShotTimeline":
        _strictly_increasing(self.camera, self.duration_s, "camera")
        for name, keys in self.actors.items():
            _strictly_increasing(keys, self.duration_s, f"actor {name}")
        for name, clips in self.clips.items():
            _in_order_without_overlap(clips, self.duration_s, f"actor {name}")
        _in_order_without_overlap(self.follow, self.duration_s, "follow")
        _in_order_without_overlap(self.cuts, self.duration_s, "cuts")
        return self


class StageCheck(StageModel):
    code: Annotated[str, Field(pattern=r"^[a-z0-9_]{3,80}$")]
    passed: bool
    severity: Severity = "error"
    detail: Annotated[str, Field(max_length=2000)]
    shot_ids: Annotated[list[int], Field(max_length=200)] = Field(default_factory=list)


class StagePlan(StageModel):
    version: Literal[1] = PLAN_VERSION
    scene_id: Annotated[str, Field(min_length=1, max_length=80)]
    location: Annotated[str, Field(max_length=500)] = ""
    location_key: Annotated[str, Field(max_length=200)] = ""
    unit: Literal["meter"] = "meter"
    up_axis: Literal["Y"] = "Y"
    aspect_ratio: Annotated[str, Field(pattern=r"^\d{1,3}(?:\.\d+)?:\d{1,3}(?:\.\d+)?$")] = "9:16"
    formation: Annotated[str, Field(max_length=200)] = ""
    # "storyboard": one camera per storyboard shot; "template": standard coverage shown before shots exist.
    coverage: Literal["storyboard", "template"] = "storyboard"
    # 60 was the cast; crowd arrays are what need the room above it.
    actors: Annotated[list[StageActor], Field(max_length=MAX_ACTORS)] = Field(default_factory=list)
    crowds: Annotated[list[StageCrowd], Field(max_length=20)] = Field(default_factory=list)
    landmarks: Annotated[list[StageLandmark], Field(max_length=MAX_LANDMARKS)] = Field(default_factory=list)
    axis: StageAxis = Field(default_factory=StageAxis)
    backdrop: StageBackdrop = Field(default_factory=StageBackdrop)
    cameras: Annotated[list[StageCamera], Field(max_length=200)] = Field(default_factory=list)
    shots: Annotated[list[StageShot], Field(max_length=200)] = Field(default_factory=list)
    checks: Annotated[list[StageCheck], Field(max_length=40)] = Field(default_factory=list)
    # Keyed by shot id as a string (JSON object keys are strings).
    timelines: Annotated[dict[str, ShotTimeline], Field(max_length=200)] = Field(default_factory=dict)
    scene_bible: Annotated[str, Field(max_length=4000)] = ""
    source: PlanSource = "auto"
    planner: PlanPlanner = "rules"
    planner_note: Annotated[str, Field(max_length=600)] = ""
    revision: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    cast_fingerprint: Annotated[str, Field(max_length=80)] = ""
    updated_at: Annotated[str, Field(max_length=64)] = ""

    @model_validator(mode="after")
    def references_resolve(self) -> "StagePlan":
        for label, ids in (
            ("actor", [actor.id for actor in self.actors]),
            ("landmark", [item.id for item in self.landmarks]),
            ("camera", [camera.id for camera in self.cameras]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"spatial stage {label} ids must be unique")
        names = [actor.name for actor in self.actors]
        if len(names) != len(set(names)):
            raise ValueError("spatial stage actor names must be unique")
        cameras = {camera.id for camera in self.cameras}
        if any(shot.camera_id not in cameras for shot in self.shots):
            raise ValueError("every spatial stage shot must name a camera on the stage")
        shot_ids = [shot.shot_id for shot in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("spatial stage shot ids must be unique")
        if any(camera_id not in cameras for shot in self.shots for camera_id in shot.alt_camera_ids):
            raise ValueError("every candidate camera of a shot must be on the stage")
        if any(key not in {str(shot_id) for shot_id in shot_ids} for key in self.timelines):
            raise ValueError("every timeline must belong to a shot of the scene")
        crowd_ids = [crowd.id for crowd in self.crowds]
        if len(crowd_ids) != len(set(crowd_ids)):
            raise ValueError("spatial stage crowd ids must be unique")
        if any(actor.crowd_id and actor.crowd_id not in crowd_ids for actor in self.actors):
            raise ValueError("every crowd member must belong to a crowd of the stage")
        if any(clip.actor not in names for timeline in self.timelines.values() for clip in timeline.follow):
            raise ValueError("every follow clip must name a character on the stage")
        for shot in self.shots:
            timeline = self.timelines.get(str(shot.shot_id))
            if timeline and any(cut.camera_id not in {shot.camera_id, *shot.alt_camera_ids} for cut in timeline.cuts):
                raise ValueError("every camera cut must use the shot's own lens or one of its candidates")
        return self

    def actor(self, name: str) -> StageActor | None:
        return next((actor for actor in self.actors if actor.name == name), None)

    def camera(self, camera_id: str) -> StageCamera | None:
        return next((camera for camera in self.cameras if camera.id == camera_id), None)

    def shot(self, shot_id: int) -> StageShot | None:
        return next((shot for shot in self.shots if shot.shot_id == int(shot_id)), None)

    def actors_in(self, shot: StageShot, *, at_end: bool = False) -> list[StageActor]:
        """The cast as it stands during ``shot``: marks, with that shot's overrides applied.

        ``at_end`` gives the cast when the shot finishes: whoever started it off their mark has
        walked onto it (unless the shot holds them there), keeping the posture the shot gave them.
        """
        changes = {item.name: item for item in shot.overrides}
        staged: list[StageActor] = []
        for actor in self.actors:
            change = changes.get(actor.name)
            if change is None:
                staged.append(actor)
                continue
            if change.offstage:
                continue
            moved = (("position", change.position), ("yaw_deg", change.yaw_deg)) if not at_end or change.hold else ()
            staged.append(actor.model_copy(update={
                key: value for key, value in (*moved, ("posture", change.posture), ("pose", change.pose)) if value is not None
            }))
        return staged


__all__ = [
    "PLAN_VERSION",
    "MAX_ACTORS",
    "MAX_POSE_JOINTS",
    "MAX_TRACK_KEYS",
    "MAX_TRACK_CLIPS",
    "MAX_LANDMARKS",
    "ActionClip",
    "ActorKey",
    "CameraCut",
    "FollowClip",
    "ActorOverride",
    "CameraKey",
    "CameraMove",
    "Easing",
    "ScreenState",
    "ShotText",
    "ShotTimeline",
    "StageActor",
    "StageAxis",
    "StageBackdrop",
    "StageCamera",
    "StageCheck",
    "StageCrowd",
    "StageLandmark",
    "StagePlan",
    "StagePose",
    "StageShot",
]
