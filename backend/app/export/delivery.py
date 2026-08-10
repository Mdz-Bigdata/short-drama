"""Deterministic caption and editable timeline serializers."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator


class CaptionCue(BaseModel):
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(gt=0)]
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    speaker: Annotated[str, Field(max_length=100)] = ""

    @model_validator(mode="after")
    def ordered(self) -> "CaptionCue":
        if self.end_ms <= self.start_ms:
            raise ValueError("caption end must be after start")
        return self


class DeliveryExporter:
    @staticmethod
    def _srt_time(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @staticmethod
    def _ass_time(milliseconds: int) -> str:
        centiseconds = milliseconds // 10
        hours, remainder = divmod(centiseconds, 360_000)
        minutes, remainder = divmod(remainder, 6_000)
        seconds, centis = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"

    def render_srt(self, cues: list[CaptionCue]) -> str:
        blocks = []
        for index, cue in enumerate(cues, start=1):
            text = cue.text.replace("\r", " ").strip()
            blocks.append(
                f"{index}\n{self._srt_time(cue.start_ms)} --> {self._srt_time(cue.end_ms)}\n{text}"
            )
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def render_ass(self, cues: list[CaptionCue], *, aspect_ratio: str) -> str:
        dimensions = {
            "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350),
        }
        if aspect_ratio not in dimensions:
            raise ValueError("unsupported subtitle aspect ratio")
        width, height = dimensions[aspect_ratio]
        header = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {width}\nPlayResY: {height}\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Noto Sans CJK SC,54,&H00FFFFFF,&H000000FF,&H00101010,&H80000000," 
            "0,0,0,0,100,100,0,0,1,3,0,2,70,70,110,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        rows = []
        for cue in cues:
            safe_text = cue.text.replace("\\", "\\\\").replace("\r", " ").replace("\n", r"\N").replace(",", "，")
            safe_speaker = cue.speaker.replace(",", "，")
            rows.append(
                f"Dialogue: 0,{self._ass_time(cue.start_ms)},{self._ass_time(cue.end_ms)},Default,"
                f"{safe_speaker},0,0,0,,{safe_text}"
            )
        return header + "\n".join(rows) + ("\n" if rows else "")

    @staticmethod
    def render_jianying(
        *,
        clips: list[dict[str, Any]],
        captions: list[CaptionCue],
        audio: list[dict[str, Any]],
        transitions: list[dict[str, Any]] | None = None,
    ) -> str:
        payload = {
            "format": "jianying-compatible-draft-v1",
            "timebase": "milliseconds",
            "tracks": {
                "video": clips,
                "captions": [cue.model_dump() for cue in captions],
                "audio": audio,
                "transitions": transitions or [],
            },
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
