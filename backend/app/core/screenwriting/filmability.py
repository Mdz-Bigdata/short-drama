# -*- coding: utf-8 -*-
"""Can this shot be filmed by a video model as written? Checked when the script is written, not at the camera.

The video prompt used to restate a page of general rules on every clip — no readable text in the picture, no
sudden transformations, no teleporting, no costume change mid-shot, no posed sheet-style shots, no person twice in
one frame, no CG look. Seedance 2.0 takes 2000 characters for the whole prompt, so those rules no longer fit there;
the script has to satisfy them instead. :func:`writing_rule` goes into the scene-writing instructions, and
:func:`scene_problems` checks each drafted shot. Wording and word lists live in ``app/data/prompt/filmability.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.core import prompt_data

_DATA = "filmability"


@dataclass(frozen=True)
class FilmabilityProblem:
    code: str
    label: str
    severity: str  # "error" sends an authored draft back; "warning" is shown to the writer
    message: str


def writing_rule() -> str:
    return prompt_data.text(_DATA, "writing_rule")


def codes() -> frozenset[str]:
    return frozenset(str(rule["code"]) for rule in prompt_data.value(_DATA, "rules"))


def _visible_text(scene: Mapping[str, object]) -> str:
    """What the camera is asked to show: the shot's description and setting (spoken lines are heard, not seen)."""
    return " ".join(str(scene.get(key) or "") for key in ("scene_description", "setting"))


def scene_problems(scene: Mapping[str, object]) -> list[FilmabilityProblem]:
    text = _visible_text(scene)
    found: list[FilmabilityProblem] = []
    for rule in prompt_data.value(_DATA, "rules"):
        hit = next((word for word in rule["words"] if word in text), None)
        if hit is None or any(word in text for word in rule.get("unless") or []):
            continue
        found.append(FilmabilityProblem(
            code=str(rule["code"]), label=str(rule["label"]), severity=str(rule["severity"]),
            message=str(rule["message"]).replace("{hit}", hit),
        ))
    return found


def beat_problems(beats: list, *, label: str) -> list[str]:
    """The outline's story beats, checked as early as the script exists: error-level problems go back to the planner."""
    reasons = []
    for index, beat in enumerate(beats or [], start=1):
        for problem in scene_problems({"scene_description": str(beat or "")}):
            if problem.severity == "error":
                reasons.append(prompt_data.text(_DATA, "beat_reason").format(label=label, index=index, rule=problem.label, message=problem.message))
    return reasons


__all__ = ["FilmabilityProblem", "beat_problems", "codes", "scene_problems", "writing_rule"]
