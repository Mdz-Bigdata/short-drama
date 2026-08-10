"""Typed contracts for acting direction, provider negotiation and audio mixing."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class PerformancePlanRequest(BaseModel):
    character: Annotated[str, Field(min_length=1, max_length=100)]
    duration_seconds: Annotated[float, Field(ge=2, le=30)]
    motivation: Annotated[str, Field(min_length=2, max_length=1000)]
    trigger: Annotated[str, Field(min_length=2, max_length=1000)]
    start_emotion: Annotated[str, Field(min_length=1, max_length=200)]
    end_emotion: Annotated[str, Field(min_length=1, max_length=200)]
    dialogue: Annotated[str, Field(max_length=1000)] = ""
    power_shift: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def dialogue_has_breathing_room(self) -> "PerformancePlanRequest":
        # Conservative CJK/word reading estimate plus reaction head/tail handles.
        units = len(self.dialogue.strip())
        minimum = 2.0 + units / 8.0 if units else 2.0
        if self.duration_seconds < minimum:
            raise ValueError("duration is too short for natural dialogue, pauses and reaction handles")
        return self


class PerformanceBeat(BaseModel):
    phase: Literal["trigger", "contain", "leak", "decision", "release"]
    start_seconds: float
    end_seconds: float
    gaze: str
    breath: str
    face: str
    body: str
    voice: str
    camera_support: str


class PerformancePlan(BaseModel):
    character: str
    motivation: str
    trigger: str
    emotion_arc: str
    power_shift: str
    beats: list[PerformanceBeat]
    identity_constraints: list[str]
    negative_constraints: list[str]


class AudioTrack(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,99}$")]
    kind: Literal["dialogue", "voiceover", "sfx", "ambience", "bgm"]
    uri: Annotated[str, Field(min_length=1, max_length=2000)]
    start_ms: Annotated[int, Field(ge=0)]
    duration_ms: Annotated[int, Field(gt=0)]
    gain_db: Annotated[float, Field(ge=-60, le=12)] = 0.0
    fade_in_ms: Annotated[int, Field(ge=0, le=10000)] = 80
    fade_out_ms: Annotated[int, Field(ge=0, le=10000)] = 120


class AudioMixRequest(BaseModel):
    duration_ms: Annotated[int, Field(gt=0, le=7_200_000)]
    tracks: Annotated[list[AudioTrack], Field(min_length=1, max_length=1000)]
    target_lufs: Annotated[float, Field(ge=-24, le=-9)] = -16.0
    true_peak_db: Annotated[float, Field(ge=-6, le=-0.1)] = -1.0

    @model_validator(mode="after")
    def tracks_fit_timeline(self) -> "AudioMixRequest":
        ids = [track.id for track in self.tracks]
        if len(ids) != len(set(ids)):
            raise ValueError("audio track IDs must be unique")
        if any(track.start_ms + track.duration_ms > self.duration_ms for track in self.tracks):
            raise ValueError("audio track exceeds the mix timeline")
        return self


class DialogueWindow(BaseModel):
    start_ms: int
    end_ms: int
    track_ids: list[str]


class AudioMixPlan(BaseModel):
    duration_ms: int
    tracks: list[AudioTrack]
    dialogue_windows: list[DialogueWindow]
    target_lufs: float
    true_peak_db: float
    ffmpeg_filter_complex: str
    output_label: str = "mixout"
