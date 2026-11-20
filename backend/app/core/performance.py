"""Motivation-first acting plan adapted cleanly from observable-performance principles."""

from __future__ import annotations

from app.schema.advanced import PerformanceBeat, PerformancePlan, PerformancePlanRequest
from app.core import prompt_data


_WORDING_FILE = "performance"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/performance.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


class PerformancePlanner:
    _PHASES = (
        (
            "trigger", 0.00, 0.14,
            _text_of("PerformancePlanner.phases"), _text_of("PerformancePlanner.phases.2"),
            _text_of("PerformancePlanner.phases.3"), _text_of("PerformancePlanner.phases.4"),
            _text_of("PerformancePlanner.phases.5"), _text_of("PerformancePlanner.phases.6"),
        ),
        (
            "contain", 0.14, 0.34,
            _text_of("PerformancePlanner.phases.7"), _text_of("PerformancePlanner.phases.8"),
            _text_of("PerformancePlanner.phases.9"), _text_of("PerformancePlanner.phases.10"),
            _text_of("PerformancePlanner.phases.11"), _text_of("PerformancePlanner.phases.12"),
        ),
        (
            "leak", 0.34, 0.55,
            _text_of("PerformancePlanner.phases.13"), _text_of("PerformancePlanner.phases.14"),
            _text_of("PerformancePlanner.phases.15"), _text_of("PerformancePlanner.phases.16"),
            _text_of("PerformancePlanner.phases.17"), _text_of("PerformancePlanner.phases.18"),
        ),
        (
            "decision", 0.55, 0.78,
            _text_of("PerformancePlanner.phases.19"), _text_of("PerformancePlanner.phases.20"),
            _text_of("PerformancePlanner.phases.21"), _text_of("PerformancePlanner.phases.22"),
            _text_of("PerformancePlanner.phases.23"), _text_of("PerformancePlanner.phases.24"),
        ),
        (
            "release", 0.78, 1.00,
            _text_of("PerformancePlanner.phases.25"), _text_of("PerformancePlanner.phases.26"),
            _text_of("PerformancePlanner.phases.27"), _text_of("PerformancePlanner.phases.28"),
            _text_of("PerformancePlanner.phases.29"), _text_of("PerformancePlanner.phases.30"),
        ),
    )

    def build(self, request: PerformancePlanRequest) -> PerformancePlan:
        duration = request.duration_seconds
        beats = [
            PerformanceBeat(
                phase=phase,
                start_seconds=round(duration * start, 3),
                end_seconds=round(duration * end, 3),
                gaze=gaze,
                breath=breath,
                face=face,
                body=body,
                voice=(voice + (_text_of("build.voice").format(request.dialogue) if request.dialogue and phase == "decision" else "")),
                camera_support=camera,
            )
            for phase, start, end, gaze, breath, face, body, voice, camera in self._PHASES
        ]
        return PerformancePlan(
            character=request.character,
            motivation=request.motivation,
            trigger=request.trigger,
            emotion_arc=f"{request.start_emotion} → {request.end_emotion}",
            power_shift=request.power_shift or _text_of("build.power_shift"),
            beats=beats,
            identity_constraints=list(_words_of("build.identity_constraints")),
            negative_constraints=list(_words_of("build.negative_constraints")),
        )
