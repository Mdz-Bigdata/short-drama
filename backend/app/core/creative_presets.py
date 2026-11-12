"""Callable, clean-room creative presets derived from the audited source capabilities."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.core import prompt_data


class CreativePreset(BaseModel):
    id: str
    name: str
    source_id: str
    purpose: str
    instructions: tuple[str, ...]


class CompiledCreativePrompt(BaseModel):
    preset_id: str
    source_id: str
    prompt: str
    required_gates: list[str] = Field(default_factory=list)


# The presets (in listing order), the production contract every preset carries and the lines a
# compiled prompt is made of: app/data/prompt/creative_presets.json.
_WORDING = "creative_presets"


def _says(key: str, /, **values: object) -> str:
    """A line of the compiled prompt, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["compile"][key]).format(**values)


_PRESETS: tuple[CreativePreset, ...] = tuple(
    CreativePreset(
        id=str(item["id"]), name=str(item["name"]), source_id=str(item["source_id"]), purpose=str(item["purpose"]),
        instructions=tuple(str(rule) for rule in item["instructions"]),
    )
    for item in prompt_data.value(_WORDING, "presets")
)


_GLOBAL_GATES = prompt_data.words(_WORDING, "global_gates")


class CreativePresetRegistry:
    def __init__(self) -> None:
        self._presets = {preset.id: preset for preset in _PRESETS}

    def list(self) -> list[CreativePreset]:
        return list(_PRESETS)

    def get(self, preset_id: str) -> CreativePreset:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", preset_id or ""):
            raise KeyError(f"unknown creative preset: {preset_id}")
        try:
            return self._presets[preset_id]
        except KeyError as exc:
            raise KeyError(f"unknown creative preset: {preset_id}") from exc

    def compile(
        self,
        preset_id: str,
        content: str,
        *,
        asset_context: str = "",
        language: str = "zh-CN",
    ) -> CompiledCreativePrompt:
        preset = self.get(preset_id)
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("content must not be empty")
        if len(clean_content) > 30000 or len(asset_context) > 20000:
            raise ValueError("creative input is too large")

        prompt = "\n".join(
            [
                _says("mode", name=preset.name),
                _says("goal", purpose=preset.purpose),
                _says("language", language=language),
                _says("rules_head"),
                *(_says("rule", rule=rule) for rule in preset.instructions),
                _says("gates_head"),
                *(_says("gate", gate=gate) for gate in _GLOBAL_GATES),
                _says("assets", context=asset_context.strip() or _says("assets_missing")),
                _says("input_head"),
                clean_content,
                _says("closing"),
            ]
        )
        return CompiledCreativePrompt(
            preset_id=preset.id,
            source_id=preset.source_id,
            prompt=prompt,
            required_gates=list(_GLOBAL_GATES),
        )

