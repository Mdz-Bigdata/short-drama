# -*- coding: utf-8 -*-
"""Turn a finished shot table into Seedance prompt packages a person can paste.

A storyboard shot is a unit of story; a generation shot is a unit of what the model
can actually hold — around four seconds of one continuous action. So a package is
built in two steps:

1. **Re-cut.** Every storyboard shot is split into generation shots at its own beats,
   never longer than :data:`MAX_GENERATED_SECONDS`, and never into equal slices — an
   entrance, the action and the landing are not the same length.
2. **Pack.** Generation shots are filled into packages of the requested length
   (10 / 15 / 20 / 30 seconds). Each package is self-contained: it repeats its own
   style lock, cast lock, light lock, carried physical state, spatial lock and
   negatives, and its clock restarts at ``00:00`` — the model never saw the package
   before it.

Four shapes come out of the same plan: the default package, a continuous-take
variant, a fight variant whose shots are short and deliberately uneven, and a
segmented short-drama script document.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core import prompt_data
from app.core.h3_sound_design import PACE_BY_DELIVERY
from app.core.style_packs import StylePack, negatives_for
from app.core.writer_dashboard import parse_duration_seconds

Variant = Literal["standard", "continuous", "fight", "script_doc"]

# 分包的全部措辞(各段重心、四种写法的标签与固定句、缺省补写的话、排期提醒)：app/data/prompt/prompt_packages.json。
_WORDING = "prompt_packages"


def _says(key: str, /, **values: object) -> str:
    """A sentence template of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A fixed word, sentence or separator of the wording table."""
    return prompt_data.text(_WORDING, key)


def _pattern(key: str) -> re.Pattern[str]:
    """A regular expression of the wording table."""
    return re.compile(str(prompt_data.load(_WORDING)["patterns"][key]))


# One generated shot holds about this much continuous action; past it the model drifts.
MAX_GENERATED_SECONDS = 4.0
MIN_GENERATED_SECONDS = 1.0
# How many generation shots a package of each length carries, as a sanity range.
PACKAGE_SHOT_RANGE: dict[int, tuple[int, int]] = {10: (2, 4), 15: (3, 5), 20: (4, 6), 30: (5, 8)}
SUPPORTED_PACKAGE_SECONDS = tuple(sorted(PACKAGE_SHOT_RANGE))
# A script document's segment, which is a different unit from a prompt package.
MAX_SEGMENT_SECONDS = 15
MAX_SEGMENT_SHOTS = 8
DIVIDER = "-" * 38
# What a package's locks emphasise, by where it falls in the scene.
_PHASES = prompt_data.words(_WORDING, "phases")
_BEAT_SPLIT = _pattern("beat_split")
_SPOKEN_CHAR = _pattern("spoken_char")
# 人物栏里这些写法表示「没有人」，不算出场人物。
_NO_CAST = frozenset(prompt_data.words(_WORDING, "no_cast_words"))
# 节拍里出现这些字的那一拍说台词。
_SPEECH_WORDS = prompt_data.words(_WORDING, "speech_words")
_WALK_WORDS = prompt_data.words(_WORDING, "walk_words")
_FIGHT_NEGATIVES = prompt_data.words(_WORDING, "fight_negative_words")


@dataclass
class GeneratedShot:
    """One unit of generation: a slice of a storyboard shot the model can hold."""

    source_shot_id: int
    beat: int                           # which beat of the storyboard shot this is
    seconds: float
    size: str
    motion: str
    action: str
    index: int = 0                      # position inside its package, set when the package closes
    dialogue: str = ""
    speaker: str = ""
    sound: str = ""
    characters: tuple[str, ...] = ()
    start_seconds: float = 0.0          # within its package

    @property
    def end_seconds(self) -> float:
        return round(self.start_seconds + self.seconds, 1)


@dataclass
class PromptPackage:
    index: int
    shots: list[GeneratedShot]
    episode_start: float
    phase: str

    @property
    def seconds(self) -> float:
        return round(sum(shot.seconds for shot in self.shots), 1)

    @property
    def episode_end(self) -> float:
        return round(self.episode_start + self.seconds, 1)

    @property
    def cast(self) -> list[str]:
        return list(dict.fromkeys(name for shot in self.shots for name in shot.characters))


@dataclass
class PackagePlan:
    packages: list[PromptPackage]
    variant: Variant
    package_seconds: int
    total_seconds: float
    delivery: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "variant": self.variant, "package_seconds": self.package_seconds,
            "total_seconds": self.total_seconds, "delivery": self.delivery,
            "packages": [
                {
                    "index": package.index, "seconds": package.seconds,
                    "episode_span": [package.episode_start, package.episode_end],
                    "phase": package.phase,
                    "shots": [
                        {
                            "source_shot_id": shot.source_shot_id, "beat": shot.beat, "index": shot.index,
                            "seconds": shot.seconds, "size": shot.size, "motion": shot.motion,
                            "action": shot.action, "dialogue": shot.dialogue,
                        }
                        for shot in package.shots
                    ],
                }
                for package in self.packages
            ],
            "warnings": list(self.warnings),
        }


def _clock(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _clauses(text: str) -> list[str]:
    """The beats of a shot description, in order."""
    parts = [part.strip() for part in _BEAT_SPLIT.split(str(text or "")) if part.strip()]
    return parts or [str(text or "").strip() or _word("beat_fallback")]


def recut(shot: Mapping[str, object], *, max_seconds: float = MAX_GENERATED_SECONDS) -> list[GeneratedShot]:
    """Split one storyboard shot into generation shots at its own beats.

    The slices follow the weight of each beat's description, so they come out uneven —
    a glance and a door slamming are not both two seconds.
    """
    seconds = float(parse_duration_seconds(shot.get("duration")) or max_seconds)
    beats = _clauses(str(shot.get("desc") or ""))
    wanted = max(1, min(len(beats), math.ceil(seconds / max_seconds)))
    if wanted < len(beats):
        # Merge neighbouring beats until there are as many as the length allows.
        merged: list[str] = list(beats)
        while len(merged) > wanted:
            shortest = min(range(len(merged) - 1), key=lambda index: len(merged[index]) + len(merged[index + 1]))
            merged[shortest : shortest + 2] = [merged[shortest] + _word("beat_join") + merged[shortest + 1]]
        beats = merged

    weights = [max(len(beat), 6) for beat in beats]
    total_weight = sum(weights)
    shot_id = int(shot.get("shot_id") or 0)
    characters = tuple(
        str(name).strip() for name in (shot.get("characters") or []) if str(name).strip() not in _NO_CAST
    )
    dialogue = str(shot.get("dialogue") or "").strip()
    pieces: list[GeneratedShot] = []
    for index, (beat, weight) in enumerate(zip(beats, weights), start=1):
        share = seconds * weight / total_weight
        length = round(max(MIN_GENERATED_SECONDS, min(max_seconds, share)), 1)
        pieces.append(GeneratedShot(
            source_shot_id=shot_id, beat=index, seconds=length,
            size=str(shot.get("size") or _word("default_size")), motion=str(shot.get("motion") or _word("default_motion")),
            action=beat, sound=str(shot.get("sound") or ""), characters=characters,
            # A line is spoken inside one generation shot, never split across two.
            dialogue=dialogue if index == _dialogue_slot(beats) else "",
        ))
    return pieces


def _dialogue_slot(beats: Sequence[str]) -> int:
    """Which beat carries the line: the one that mentions speaking, else the longest."""
    for index, beat in enumerate(beats, start=1):
        if any(word in beat for word in _SPEECH_WORDS):
            return index
    return max(range(1, len(beats) + 1), key=lambda index: len(beats[index - 1]))


def plan_packages(
    shots: Sequence[Mapping[str, object]],
    *,
    package_seconds: int = 15,
    variant: Variant = "standard",
    delivery: str = "正常",
    max_generated_seconds: float | None = None,
) -> PackagePlan:
    """Re-cut ``shots`` and fill them into self-contained packages."""
    if package_seconds not in PACKAGE_SHOT_RANGE:
        raise ValueError(f"package length must be one of {SUPPORTED_PACKAGE_SECONDS} seconds")
    if delivery not in PACE_BY_DELIVERY:
        raise ValueError(f"delivery must be one of {tuple(PACE_BY_DELIVERY)}")
    ceiling = max_generated_seconds or (3.0 if variant == "fight" else MAX_GENERATED_SECONDS)

    generated: list[GeneratedShot] = []
    for raw in shots:
        if isinstance(raw, Mapping):
            generated.extend(recut(raw, max_seconds=ceiling))
    if not generated:
        return PackagePlan(packages=[], variant=variant, package_seconds=package_seconds, total_seconds=0.0, delivery=delivery)

    packages: list[PromptPackage] = []
    current: list[GeneratedShot] = []
    elapsed = 0.0
    low, high = PACKAGE_SHOT_RANGE[package_seconds]

    def close(shots_in: list[GeneratedShot], start: float) -> PromptPackage:
        clock = 0.0
        # Inside a package the shots are numbered 1..N: the model is reading this
        # package alone and has never seen the storyboard's own numbering.
        for position, shot in enumerate(shots_in, start=1):
            shot.index = position
            shot.start_seconds = round(clock, 1)
            clock += shot.seconds
        phase = _PHASES[min(len(packages), len(_PHASES) - 1)]
        return PromptPackage(index=len(packages) + 1, shots=list(shots_in), episode_start=round(start, 1), phase=phase)

    package_start = 0.0
    for shot in generated:
        filled = sum(item.seconds for item in current)
        if current and (filled + shot.seconds > package_seconds or len(current) >= high):
            packages.append(close(current, package_start))
            package_start = round(package_start + filled, 1)
            current = []
        current.append(shot)
        elapsed += shot.seconds
    if current:
        packages.append(close(current, package_start))

    warnings: list[str] = []
    for package in packages[:-1]:
        if len(package.shots) < low:
            warnings.append(_says(
                "few_shots", package=package.index, count=len(package.shots), seconds=package_seconds, low=low, high=high,
            ))
    rate = PACE_BY_DELIVERY[delivery]
    for package in packages:
        for shot in package.shots:
            spoken = len(_SPOKEN_CHAR.findall(shot.dialogue)) / rate if shot.dialogue else 0.0
            if spoken and spoken > shot.seconds:
                warnings.append(_says(
                    "slow_line", package=package.index, shot=shot.index, source=shot.source_shot_id, delivery=delivery,
                    spoken=spoken, seconds=shot.seconds,
                ))
    return PackagePlan(
        packages=packages, variant=variant, package_seconds=package_seconds,
        total_seconds=round(elapsed, 1), delivery=delivery, warnings=warnings,
    )


def package_count(total_seconds: float, package_seconds: int) -> int:
    """How many packages an episode of this length needs; the last one may be short."""
    if package_seconds <= 0:
        raise ValueError("package length must be positive")
    return max(1, math.ceil(max(0.0, total_seconds) / package_seconds))


# ---------------------------------------------------------------------------------------------
# Rendering


@dataclass
class PackageContext:
    """What every package restates: who, where, in what light, carrying what."""

    pack: StylePack
    scene: str = ""
    spatial_lock: str = ""
    lighting: str = ""
    cast_locks: Mapping[str, str] = field(default_factory=dict)
    carried_state: str = ""
    extra_negatives: Sequence[str] = ()


def render_package(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """One pasteable Seedance package in the default shape."""
    cast = _word("cast_sep").join(
        _says("cast_item", name=name, lock=context.cast_locks.get(name, _word("cast_lock_default"))) for name in package.cast
    ) or _word("no_cast")
    negatives = negatives_for(context.pack, ["multi_person"] if len(package.cast) >= 2 else [], context.extra_negatives)
    lines = [
        _says("package_head", index=package.index, start=_clock(package.episode_start), end=_clock(package.episode_end)),
        "<Asset_Setup>",
        _says("style_lock", style=context.pack.style_caption, phase=package.phase),
        _says("cast_lock", cast=cast),
        _says("light_lock", lighting=context.lighting or _word("lighting_default")),
        _says("carried_lock", state=context.carried_state or _word("carried_default")),
        "</Asset_Setup>",
        _says("spatial_lock", lock=context.spatial_lock or context.scene or _word("spatial_default")),
    ]
    for shot in package.shots:
        lines.append(_says(
            "package_shot", index=shot.index, start=_clock(shot.start_seconds), end=_clock(shot.end_seconds),
            size=shot.size, motion=shot.motion, action=shot.action,
            line=_says("package_line", dialogue=shot.dialogue) if shot.dialogue else _word("package_no_line"),
        ))
    lines.append(_says("negatives_base", negatives=" + ".join(negatives[:8])))
    lines.append(_says("negatives_dynamic", risks=_dynamic_negatives(package)))
    lines.append(DIVIDER)
    return "\n".join(lines)


def _dynamic_negatives(package: PromptPackage) -> str:
    """What this particular段 is most likely to drift on."""
    risks = list(prompt_data.words(_WORDING, "risk_always"))
    if len(package.cast) >= 2:
        risks.append(_word("risk_two"))
    if any(shot.dialogue for shot in package.shots):
        risks.append(_word("risk_dialogue"))
    if any(any(word in shot.action for word in _WALK_WORDS) for shot in package.shots):
        risks.append(_word("risk_walk"))
    return " + ".join(risks)


def render_continuous(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """The continuous-take variant: one unbroken action chain, no cut language."""
    cast = _word("cast_sep").join(
        _says("cast_item", name=name, lock=context.cast_locks.get(name, _word("cast_lock_plain"))) for name in package.cast
    ) or _word("no_cast")
    lines = [
        _says("continuous_head", index=package.index, seconds=package.seconds, phase=package.phase),
        _word("continuous_lock_head"),
        _says("continuous_cast", cast=cast),
        _says("continuous_space", space=context.spatial_lock or context.scene or _word("continuous_space_default")),
        _says("continuous_light", light=context.lighting or _word("continuous_light_default")),
        _says("continuous_style", style=context.pack.style_caption),
    ]
    for shot in package.shots:
        lines.append(_says(
            "continuous_shot", start=_clock(shot.start_seconds), end=_clock(shot.end_seconds), size=shot.size,
            motion=shot.motion, action=shot.action,
            line=_says("continuous_line", dialogue=shot.dialogue) if shot.dialogue else "",
        ))
    lines.extend([
        _word("continuous_rules"),
        _says("continuous_negatives", negatives=" + ".join(negatives_for(context.pack, ["extension"], context.extra_negatives)[:10])),
        DIVIDER,
    ])
    return "\n".join(lines)


def render_fight(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """The fight variant: the whole fight's rules once, then short uneven beats."""
    fighters = _word("fighter_sep").join(
        _says("cast_item", name=name, lock=context.cast_locks.get(name, _word("cast_lock_plain"))) for name in package.cast
    ) or _word("no_fighters")
    lines = [
        _says("fight_head", index=package.index, count=len(plan.packages), phase=package.phase),
        _says("fight_style", style=context.pack.style_caption),
        _says("fight_cast", fighters=fighters),
        _says("fight_ground", scene=context.scene or _word("fight_ground_default")),
        _word("fight_motion_rules"),
        _word("fight_board_head"),
    ]
    for shot in package.shots:
        lines.append(_says(
            "fight_shot", start=_clock(shot.start_seconds), end=_clock(shot.end_seconds), seconds=shot.seconds,
            size=shot.size, motion=shot.motion, action=shot.action,
        ))
    lines.extend([
        _says("fight_negatives", negatives=" + ".join(_FIGHT_NEGATIVES)),
        DIVIDER,
    ])
    return "\n".join(lines)


def render_script_document(plan: PackagePlan, context: PackageContext, *, title: str = "") -> str:
    """The segmented short-drama script: assets, the whole dialogue, then Shot rows."""
    shots = [shot for package in plan.packages for shot in package.shots]
    cast = list(dict.fromkeys(name for shot in shots for name in shot.characters))
    lines = [_says("script_title", title=title or _word("script_title_default")), "", _word("script_assets_head")]
    lines.extend(_says("script_cast", name=name, lock=context.cast_locks.get(name, _word("cast_lock_film"))) for name in cast)
    lines.append(_says(
        "script_scene", scene=context.scene or _word("script_scene_default"), lock=context.spatial_lock or _word("script_spatial_default"),
    ))
    lines.append(_says("script_light", light=context.lighting or _word("script_light_default")))
    lines.append("")
    lines.append(_word("script_lines_head"))
    spoken = [shot for shot in shots if shot.dialogue]
    for order, shot in enumerate(spoken, start=1):
        lines.append(_says("script_line", order=order, shot=shot.source_shot_id, dialogue=shot.dialogue))
    lines.append(_says("script_line_count", count=len(spoken)))
    lines.append("")

    segments = _segments(shots)
    lines.append(_says("script_board_head", seconds=plan.total_seconds))
    for order, segment in enumerate(segments, start=1):
        seconds = round(sum(shot.seconds for shot in segment), 1)
        lines.extend([
            "",
            _says("segment_head", order=order, seconds=seconds),
            _says(
                "segment_light", scene=context.scene or _word("script_scene_default"),
                light=context.lighting or _word("segment_light_default"),
            ),
        ])
        for position, shot in enumerate(segment, start=1):
            lines.extend([
                _says("shot_head", order=order, position=position, seconds=shot.seconds, size=shot.size),
                _says("shot_scene", scene=context.scene or _word("script_scene_default")),
                _says("shot_cast", cast=_word("list_sep").join(_says("mention", name=name) for name in shot.characters) or _word("no_one")),
                _says("shot_subject", subject=_says("mention", name=shot.characters[0]) if shot.characters else _word("no_subject")),
                _says("shot_action", action=shot.action),
                _says("shot_line", dialogue=shot.dialogue or _word("no_line")),
                _says("shot_motion", motion=shot.motion),
                _says("shot_light", light=context.lighting or _word("shot_light_default")),
                _says("shot_sound", sound=shot.sound or _word("shot_sound_default")),
                _says("shot_style", style=context.pack.style_caption),
                _says("shot_bridge", landing=_landing(shot)),
            ])
        lines.append(_says(
            "segment_check", count=len(segment), seconds=seconds, max_shots=MAX_SEGMENT_SHOTS, max_seconds=MAX_SEGMENT_SECONDS,
        ))
    return "\n".join(lines)


def _segments(shots: Sequence[GeneratedShot]) -> list[list[GeneratedShot]]:
    segments: list[list[GeneratedShot]] = []
    current: list[GeneratedShot] = []
    for shot in shots:
        filled = sum(item.seconds for item in current)
        if current and (filled + shot.seconds > MAX_SEGMENT_SECONDS or len(current) >= MAX_SEGMENT_SHOTS):
            segments.append(current)
            current = []
        current.append(shot)
    if current:
        segments.append(current)
    return segments


def _landing(shot: GeneratedShot) -> str:
    tail = shot.action.split(_word("beat_join"))[-1].strip()
    return tail or _word("landing_default")


_RENDERERS = {"standard": render_package, "continuous": render_continuous, "fight": render_fight}


def render(plan: PackagePlan, context: PackageContext, *, title: str = "") -> str:
    """The whole deliverable: every package, or the script document for that variant."""
    if plan.variant == "script_doc":
        return render_script_document(plan, context, title=title)
    renderer = _RENDERERS[plan.variant]
    header = _says(
        "render_head", title=title or _word("render_title_default"), variant=plan.variant, seconds=plan.package_seconds,
        count=len(plan.packages), total=plan.total_seconds, delivery=plan.delivery,
    )
    body = "\n".join(renderer(package, context, plan) for package in plan.packages)
    return f"{header}\n\n{body}"


__all__ = [
    "DIVIDER", "MAX_GENERATED_SECONDS", "MAX_SEGMENT_SECONDS", "MAX_SEGMENT_SHOTS",
    "PACKAGE_SHOT_RANGE", "SUPPORTED_PACKAGE_SECONDS", "GeneratedShot", "PackageContext",
    "PackagePlan", "PromptPackage", "package_count", "plan_packages", "recut", "render",
    "render_continuous", "render_fight", "render_package", "render_script_document",
]
