"""Camera-move recipes: narrative category + intensity → one composed move.

A recipe is assembled from six slots — camera move, camera angle, subject
action, environment change, light mood, image texture — plus a negative line,
so a shot's move is written the way video models read it instead of as a bare
verb. Moves come from the provider vocabulary in ``camera_motion`` so the
contract stays executable; the phrasing here is the project's own.

The anti-repeat rule: lock style and texture, rotate exactly one of move,
angle, rhythm or environment between adjacent shots.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core import prompt_data
from app.core.camera_motion import CAMERA_MOTION_LABELS, normalize_camera_motion, render_camera_motion

Intensity = str  # "strong" | "medium" | "soft"

# The angle and rhythm words, the recipe table, the quality and negative lines and the prompt
# templates: app/data/prompt/camera_recipes.json.
_WORDING = "camera_recipes"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the recipes' wording, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _rows(table: str) -> tuple[tuple[str, str, str], ...]:
    """An ``[[id, zh, en], …]`` table of the recipes' data, in file order."""
    return tuple((str(name), str(zh), str(en)) for name, zh, en in prompt_data.value(_WORDING, table))


ANGLES: tuple[tuple[str, str, str], ...] = _rows("angles")
RHYTHMS: tuple[tuple[str, str, str], ...] = _rows("rhythms")
_ANGLE_ZH = {key: zh for key, zh, _ in ANGLES}
_ANGLE_EN = {key: en for key, _, en in ANGLES}
_RHYTHM_ZH = {key: zh for key, zh, _ in RHYTHMS}
_RHYTHM_EN = {key: en for key, _, en in RHYTHMS}

# category -> (label, purpose, {intensity: (move, angle, rhythm, zh_action_hint, en_action_hint)})
RECIPE_CATEGORIES: dict[str, dict[str, Any]] = {
    str(category): {
        "label": str(entry["label"]),
        "purpose": str(entry["purpose"]),
        "levels": {str(level): tuple(str(part) for part in row) for level, row in entry["levels"].items()},
    }
    for category, entry in prompt_data.value(_WORDING, "categories").items()
}
INTENSITIES: tuple[tuple[str, str], ...] = prompt_data.pairs(_WORDING, "intensities")
QUALITY_ZH = prompt_data.text(_WORDING, "quality_zh")
QUALITY_EN = prompt_data.text(_WORDING, "quality_en")
NEGATIVE_EN = prompt_data.text(_WORDING, "negative_en")


class CameraRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    category_label: str
    intensity: str
    camera_motion: str
    camera_motion_label: str
    angle: str
    angle_label: str
    rhythm: str
    rhythm_label: str
    prompt_zh: str = Field(max_length=2000)
    prompt_en: str = Field(max_length=2000)
    negative: str = Field(max_length=500)
    provider_phrase: str = Field(max_length=200)


def recipe_catalog() -> list[dict[str, str]]:
    return [
        {"value": key, "label": entry["label"], "purpose": entry["purpose"]}
        for key, entry in RECIPE_CATEGORIES.items()
    ]


def compose_recipe(
    category: str,
    intensity: str = "medium",
    *,
    subject_action: str = "",
    environment: str = "",
    lighting: str = "",
    provider_family: str = "",
) -> CameraRecipe:
    entry = RECIPE_CATEGORIES.get(category)
    if entry is None:
        raise ValueError(_says("unknown_category", category=category))
    level = intensity if intensity in entry["levels"] else "medium"
    move, angle, rhythm, zh_hint, en_hint = entry["levels"][level]
    canonical, _ = normalize_camera_motion(move)
    action_zh = subject_action.strip() or zh_hint
    env_zh = environment.strip() or _says("default_environment")
    light_zh = lighting.strip() or _says("default_lighting")
    prompt_zh = _says(
        "prompt_zh", move=render_camera_motion(canonical, provider_family), angle=_ANGLE_ZH[angle],
        rhythm=_RHYTHM_ZH[rhythm], action=action_zh, environment=env_zh, lighting=light_zh, quality=QUALITY_ZH,
    )
    prompt_en = _says(
        "prompt_en", move=canonical.lower(), angle=_ANGLE_EN[angle], rhythm=_RHYTHM_EN[rhythm], action=en_hint,
        quality=QUALITY_EN,
    )
    return CameraRecipe(
        category=category,
        category_label=entry["label"],
        intensity=level,
        camera_motion=canonical,
        camera_motion_label=CAMERA_MOTION_LABELS[canonical],
        angle=angle,
        angle_label=_ANGLE_ZH[angle],
        rhythm=rhythm,
        rhythm_label=_RHYTHM_ZH[rhythm],
        prompt_zh=prompt_zh,
        prompt_en=prompt_en,
        negative=NEGATIVE_EN,
        provider_phrase=render_camera_motion(canonical, provider_family),
    )


def _angle_key(text: str) -> str:
    haystack = str(text or "")
    for key, zh, en in ANGLES:
        if zh in haystack or en in haystack.lower():
            return key
    return "eye_level"


def repeated_move_signature(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """Empty when adjacent shots differ in at least one of move / angle / rhythm; else the shared signature.

    Rhythm is read from duration (≤3s fast, ≥6s slow) so a table without an
    explicit rhythm column still gets checked.
    """
    def signature(shot: dict[str, Any]) -> tuple[str, str, str]:
        move, _ = normalize_camera_motion(shot.get("motion"))
        angle = _angle_key(shot.get("angle"))
        seconds = shot.get("_seconds")
        rhythm = "fast" if seconds and seconds <= 3 else "slow" if seconds and seconds >= 6 else "steady"
        return move, angle, rhythm

    before, after = signature(previous), signature(current)
    if before == after and before[0] != "Static":
        return _says(
            "signature", move=CAMERA_MOTION_LABELS[after[0]], angle=_ANGLE_ZH[after[1]], rhythm=_RHYTHM_ZH.get(after[2], after[2]),
        )
    return ""
