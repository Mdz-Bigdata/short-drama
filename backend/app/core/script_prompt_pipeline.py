"""Clean-room script-to-video prompt pipeline.

The module compiles user-authored text into reviewable artifacts. It never runs
code from a template archive and never submits a paid provider request.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from app.core import prompt_data
from app.core.face_card import audit_face_card, parse_face_card, render_face_card
from app.core.sd25_compiler import Sd25PromptCompiler
from app.core.shot_motion_contract import (
    ShotMotionContract,
    assert_prompt_pair_consistent,
    compile_motion_prompt,
    compile_storyboard_image_prompt,
)
from app.core.storyboard_quality import build_actor_sheet_prompt, validate_storyboard_continuity
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.core.video_references import VideoGenerationIntent, plan_video_references
from app.schema.production import (
    IDENTITY_VIEW_ORDER,
    NineGridStoryboard,
    Sd25CompileRequest,
    Sd25DialogueEntry,
    StoryAssetCatalog,
    StoryboardPanel,
)
from app.schema.script_prompts import (
    CharacterCostumeProfile,
    CharacterPromptProfile,
    ParsedScreenplay,
    ParsedScreenplayScene,
    PromptConsistencyIssue,
    PromptConsistencyReport,
    SceneLightingProfile,
    ScenePromptProfile,
    ScriptElement,
    ScriptPromptCompileRequest,
    ScriptPromptCompileResult,
    ShotPromptBundle,
    ShotReferenceAssignment,
)
from app.schema.storyboard_director import (
    CameraDesign,
    ColorDesign,
    ContinuityLocks,
    DirectorCharacter,
    DirectorProp,
    DirectorScene,
    DynamicsDesign,
    GlobalVisualRules,
    ShotVisualDesign,
    StoryboardDirectorRequest,
    StoryboardDirectorResult,
    StoryEvent,
    TransitionDesign,
    TransitionEdge,
)


# The sentences, templates, word tables and screenplay patterns of this module:
# app/data/prompt/script_prompt_pipeline.json.
_WORDING = "script_prompt_pipeline"


def _entry(key: str) -> Any:
    """The entry at the dotted ``key`` ("section.name") of the wording table."""
    node: Any = prompt_data.load(_WORDING)
    for part in key.split("."):
        node = node[part]
    return node


def _says(key: str, /, **values: object) -> str:
    """A sentence or word of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(_entry(key)).format(**values)


def _table(key: str) -> Any:
    """A word table, a list or a set of model fields of the wording table, used as it stands."""
    return _entry(key)


def _pattern(key: str, flags: int = 0) -> re.Pattern[str]:
    """A screenplay pattern of the wording table, compiled."""
    return re.compile(str(_entry(key)), flags)


_EN_SCENE = _pattern("patterns.en_scene", re.IGNORECASE)
_CN_NUMBERED_SCENE = _pattern("patterns.cn_numbered_scene")
_CN_SCENE = _pattern("patterns.cn_scene")
_HEADING_SPLIT = _pattern("patterns.heading_split")
_TRANSITION = _pattern("patterns.transition", re.IGNORECASE)
_PARENTHETICAL = _pattern("patterns.parenthetical")
_BRACKET_DIALOGUE = _pattern("patterns.bracket_dialogue")
_INLINE_DIALOGUE = _pattern("patterns.inline_dialogue")
_UPPER_CHARACTER = _pattern("patterns.upper_character")
_CUE_EXTENSION = _pattern("patterns.cue_extension")
_CN_ACTION_CHARACTER = _pattern("patterns.cn_action_character")
_DIALOGUE_DIRECTION = _pattern("patterns.dialogue_direction")
_IDENTITY_PARENTHETICAL = _pattern("patterns.identity_parenthetical")
_FACT_SEPARATORS = _pattern("patterns.fact_separators")
_AGE_MARKER = _pattern("patterns.age_marker")
# English heading words that name both sides read as INT/EXT; the Chinese heading words map, in order, to these codes.
_EN_COMBINED = frozenset(_table("heading.en_combined_words"))
_CN_INT_EXT = dict(zip(_table("heading.cn_int_ext_words"), ("INT", "EXT", "INT/EXT"), strict=True))
_NON_CHARACTER_LABELS = set(_table("non_character_labels"))

_APPEARANCE_TERMS = tuple(_table("appearance_terms"))
_COSTUME_TERMS = tuple(_table("costume_terms"))
_PROP_TERMS = tuple(_table("prop_terms"))
_EFFECT_TERMS = tuple(_table("effect_terms"))
_INDOOR_LOCATIONS = tuple(_table("indoor_locations"))
_OUTDOOR_LOCATIONS = tuple(_table("outdoor_locations"))
_COLOR_TERMS = tuple(_table("color_terms"))
_ACCESSORY_TERMS = tuple(_table("accessory_terms"))
# First match wins: the order of these tables is the order they are tried in.
_WEATHER_TERMS = tuple(_table("weather_terms"))
_SEASON_TERMS = tuple(_table("season_terms"))
_DAYLIGHT_WORDS = tuple(_table("daylight_words"))
_NIGHT_WORDS = tuple(_table("night_words"))
_MOOD_VISUALS = dict(_table("mood_visuals"))
_CLAUSE = _says("joiners.clause")
_LIST = _says("joiners.list")
_SPEAKER = _says("joiners.speaker")


@dataclass(frozen=True)
class _Beat:
    text: str
    kind: str
    speaker: str = ""
    dialogue: str = ""


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clip(value: str, limit: int) -> str:
    text = value.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _layered_identity(identity_dna: str) -> str:
    """身份 DNA 写成分层人物资产卡；没解析出长相层(如待补充占位)时原样返回。"""
    card = parse_face_card(identity_dna)
    return render_face_card(card) if card.has_face_layers else identity_dna


def _safe_sheet_text(value: object) -> str:
    text = str(value if value is not None else "").replace("\x00", "")
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _markdown_cell(value: object) -> str:
    return (
        html.escape(_safe_sheet_text(value), quote=False)
        .replace("|", r"\|")
        .replace("\r", " ")
        .replace("\n", "<br>")
    )


def _markdown_text(value: object) -> str:
    return html.escape(_safe_sheet_text(value), quote=False).replace("```", "` ` `")


def _split_parenthetical_dialogue(value: str) -> tuple[str, str]:
    match = _DIALOGUE_DIRECTION.match(value.strip())
    return (match.group(1).strip(), match.group(2).strip()) if match else ("", value.strip())


class ScriptPromptPipeline:
    """Compile a complete, deterministic pre-production package."""

    def __init__(self) -> None:
        self.sd25 = Sd25PromptCompiler()
        self.director = StoryboardDirectorCompiler()

    def compile(self, request: ScriptPromptCompileRequest) -> ScriptPromptCompileResult:
        source_sha256 = request.source_sha256 or hashlib.sha256(
            request.script_text.encode("utf-8")
        ).hexdigest()
        screenplay = self.parse_screenplay(request.script_text, request.title)
        characters, character_warnings = self.extract_characters(
            screenplay, request.character_overrides, request.visual_style
        )
        scenes = self.analyze_scenes(screenplay, request.scene_overrides)
        director_plans: list[StoryboardDirectorResult] = []
        storyboards: list[NineGridStoryboard] = []
        for index, scene in enumerate(screenplay.scenes):
            plan = self.compile_director_plan(
                scene=scene,
                profile=scenes[index],
                characters=characters,
                title=screenplay.title,
                visual_style=request.visual_style,
            )
            director_plans.append(plan)
            storyboards.extend(self.build_storyboards(
                scene=scene,
                profile=scenes[index],
                title=screenplay.title,
                director_plan=plan,
            ))
        assignments = {
            (item.scene_number, item.page_number, item.panel_index): item
            for item in request.reference_assignments
        }
        shot_prompts = self.compile_shot_prompts(
            storyboards=storyboards,
            director_plans=director_plans,
            assignments=assignments,
            visual_style=request.visual_style,
            video_model=request.video_model,
            provider_parameters=request.provider_parameters,
        )
        consistency = self.check_consistency(characters, scenes, storyboards, shot_prompts)
        warnings = list(character_warnings)
        known_targets = {
            (board.scene_number, board.page_number, panel.index)
            for board in storyboards for panel in board.panels
        }
        unknown_assignments = sorted(
            target for target in assignments if target not in known_targets
        )
        if unknown_assignments:
            raise ValueError(
                f"reference assignments target unknown scene/page/panel slots: {unknown_assignments}"
            )
        warnings.extend(
            issue.description for issue in consistency.issues if issue.severity == "warning"
        )
        warnings.extend(
            warning for plan in director_plans for warning in plan.warnings
        )
        submission_ready = (
            consistency.passed
            and all(character.identity_status == "bound" for character in characters)
            and all(plan.submission_ready for plan in director_plans)
        )
        payload = {
            "schema_version": "script-prompts.v1",
            "source_sha256": source_sha256,
            "source_format": request.source_format,
            "prompt_language": request.prompt_language,
            "output_language": request.output_language,
            "screenplay": screenplay.model_dump(mode="json"),
            "characters": [item.model_dump(mode="json") for item in characters],
            "scenes": [item.model_dump(mode="json") for item in scenes],
            "director_plans": [item.model_dump(mode="json") for item in director_plans],
            "storyboards": [item.model_dump(mode="json") for item in storyboards],
            "shot_prompts": [item.model_dump(mode="json") for item in shot_prompts],
            "consistency": consistency.model_dump(mode="json"),
            "warnings": _unique(warnings),
            "submission_ready": submission_ready,
            "template_sources": [
                "script-to-video-prompts", "sd25-pe", "universal-storyboard-prompt"
            ],
        }
        exports = self.render_exports(payload, request.exports)
        return ScriptPromptCompileResult(
            source_sha256=source_sha256,
            source_format=request.source_format,
            prompt_language=request.prompt_language,
            output_language=request.output_language,
            screenplay=screenplay,
            characters=characters,
            scenes=scenes,
            director_plans=director_plans,
            storyboards=storyboards,
            shot_prompts=shot_prompts,
            consistency=consistency,
            exports=exports,
            warnings=_unique(warnings),
            submission_ready=submission_ready,
        )

    @staticmethod
    def _scene_heading(line: str) -> tuple[str, str, str] | None:
        match = _EN_SCENE.match(line)
        if match:
            raw = match.group(1).upper().rstrip(".")
            int_ext = "INT/EXT" if raw in _EN_COMBINED else raw
            return int_ext, match.group(2).strip(), (match.group(3) or _says("heading.en_unknown_time")).strip()
        match = _CN_SCENE.match(line)
        if match:
            int_ext = _CN_INT_EXT[match.group(1)]
            return int_ext, match.group(2).strip(), (match.group(3) or _says("heading.unknown_time")).strip()
        match = _CN_NUMBERED_SCENE.match(line)
        if match:
            body = match.group(1).strip()
            chunks = _HEADING_SPLIT.split(body, maxsplit=1)
            location = chunks[0] or _says("heading.unknown_location")
            time_of_day = chunks[1] if len(chunks) == 2 and chunks[1] else _says("heading.unknown_time")
            int_ext = (
                "EXT" if _says("heading.exterior_mark") in location
                or any(term in location for term in _OUTDOOR_LOCATIONS)
                else "INT" if _says("heading.interior_mark") in location
                or any(term in location for term in _INDOOR_LOCATIONS)
                else "UNKNOWN"
            )
            return int_ext, location, time_of_day
        return None

    def parse_screenplay(self, text: str, title: str) -> ParsedScreenplay:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        scenes: list[ParsedScreenplayScene] = []
        current: dict[str, object] | None = None
        pending_speaker = ""

        def new_scene(heading: str, parsed: tuple[str, str, str] | None = None) -> dict[str, object]:
            int_ext, location, time_of_day = parsed or (
                "UNKNOWN", _says("heading.unknown_location"), _says("heading.unknown_time")
            )
            return {
                "number": len(scenes) + 1,
                "heading": heading,
                "location": location,
                "time_of_day": time_of_day,
                "int_ext": int_ext,
                "characters": [],
                "elements": [],
            }

        def finish_scene() -> None:
            nonlocal current
            if current is None:
                return
            elements: list[ScriptElement] = current["elements"]  # type: ignore[assignment]
            duration = 0.0
            for element in elements:
                if element.type == "dialogue":
                    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", element.content))
                    words = len(element.content.split())
                    duration += max(1.5, chinese_chars / 4.0 if chinese_chars else words / 2.5)
                elif element.type == "action":
                    duration += _bounded(2 + len(element.content) / 35, 2, 8)
                elif element.type == "parenthetical":
                    duration += 0.5
            scenes.append(ParsedScreenplayScene(
                **current,
                estimated_duration_seconds=round(duration, 2),
            ))
            current = None

        for line_number, raw_line in enumerate(normalized.split("\n"), start=1):
            line = raw_line.strip()
            if not line:
                pending_speaker = ""
                continue
            heading = self._scene_heading(line)
            if heading:
                finish_scene()
                current = new_scene(line, heading)
                current["elements"].append(ScriptElement(  # type: ignore[union-attr]
                    type="scene_heading", content=line, line_number=line_number
                ))
                pending_speaker = ""
                continue
            if current is None:
                current = new_scene(_says("heading.opening_heading"))

            elements: list[ScriptElement] = current["elements"]  # type: ignore[assignment]
            characters: list[str] = current["characters"]  # type: ignore[assignment]
            if _TRANSITION.match(line):
                elements.append(ScriptElement(type="transition", content=line, line_number=line_number))
                pending_speaker = ""
                continue
            parenthetical = _PARENTHETICAL.match(line)
            if parenthetical:
                elements.append(ScriptElement(
                    type="parenthetical", content=parenthetical.group(1).strip(),
                    line_number=line_number, speaker=pending_speaker,
                ))
                continue
            bracket = _BRACKET_DIALOGUE.match(line)
            if bracket:
                speaker, dialogue = bracket.group(1).strip(), bracket.group(2).strip()
                if speaker not in characters:
                    characters.append(speaker)
                elements.append(ScriptElement(
                    type="character", content=speaker, line_number=line_number, speaker=speaker
                ))
                if dialogue:
                    direction, dialogue = _split_parenthetical_dialogue(dialogue)
                    if direction:
                        elements.append(ScriptElement(
                            type="parenthetical", content=direction,
                            line_number=line_number, speaker=speaker,
                        ))
                    if dialogue:
                        elements.append(ScriptElement(
                            type="dialogue", content=dialogue, line_number=line_number, speaker=speaker
                        ))
                pending_speaker = speaker
                continue
            inline = _INLINE_DIALOGUE.match(line)
            if inline and inline.group(1).strip() not in _NON_CHARACTER_LABELS:
                speaker, dialogue = inline.group(1).strip(), inline.group(2).strip()
                if speaker not in characters:
                    characters.append(speaker)
                elements.append(ScriptElement(
                    type="character", content=speaker, line_number=line_number, speaker=speaker
                ))
                direction, dialogue = _split_parenthetical_dialogue(dialogue)
                if direction:
                    elements.append(ScriptElement(
                        type="parenthetical", content=direction,
                        line_number=line_number, speaker=speaker,
                    ))
                if dialogue:
                    elements.append(ScriptElement(
                        type="dialogue", content=dialogue, line_number=line_number, speaker=speaker
                    ))
                pending_speaker = speaker
                continue
            if _UPPER_CHARACTER.fullmatch(line) and len(line) <= 52:
                speaker = _CUE_EXTENSION.sub("", line).strip()
                if speaker not in characters:
                    characters.append(speaker)
                elements.append(ScriptElement(
                    type="character", content=speaker, line_number=line_number, speaker=speaker
                ))
                pending_speaker = speaker
                continue
            if pending_speaker:
                elements.append(ScriptElement(
                    type="dialogue", content=line, line_number=line_number, speaker=pending_speaker
                ))
            else:
                described_character = _CN_ACTION_CHARACTER.match(line)
                if described_character:
                    speaker = described_character.group(1).strip()
                    if speaker not in characters:
                        characters.append(speaker)
                elements.append(ScriptElement(type="action", content=line, line_number=line_number))
        finish_scene()

        all_characters = _unique([
            character for scene in scenes for character in scene.characters
        ])
        all_locations = _unique([scene.location for scene in scenes])
        return ParsedScreenplay(
            title=title,
            scenes=scenes,
            all_characters=all_characters,
            all_locations=all_locations,
            total_duration_seconds=round(sum(scene.estimated_duration_seconds for scene in scenes), 2),
        )

    @staticmethod
    def _evidence_for_character(screenplay: ParsedScreenplay, name: str) -> list[tuple[int, int, str]]:
        evidence: list[tuple[int, int, str]] = []
        for scene in screenplay.scenes:
            for element in scene.elements:
                if element.speaker == name or name in element.content:
                    evidence.append((scene.number, element.line_number, element.content))
        return evidence

    @staticmethod
    def _identity_fact_fragments(name: str, content: str) -> list[str]:
        fragments: list[str] = []
        for parenthetical in _IDENTITY_PARENTHETICAL.findall(content):
            if any(term in parenthetical for term in _APPEARANCE_TERMS + _COSTUME_TERMS):
                fragments.append(parenthetical.strip())
        for fragment in _FACT_SEPARATORS.split(content):
            cleaned = fragment.strip().removeprefix(name).strip()
            if cleaned and any(term in cleaned for term in _APPEARANCE_TERMS + _COSTUME_TERMS):
                fragments.append(cleaned)
        return _unique(fragments)

    def extract_characters(
        self,
        screenplay: ParsedScreenplay,
        overrides: dict[str, str],
        visual_style: str,
    ) -> tuple[list[CharacterPromptProfile], list[str]]:
        dialogue_counts = {
            name: sum(
                element.type == "dialogue" and element.speaker == name
                for scene in screenplay.scenes for element in scene.elements
            )
            for name in screenplay.all_characters
        }
        ranked = sorted(dialogue_counts, key=lambda name: (-dialogue_counts[name], name))
        profiles: list[CharacterPromptProfile] = []
        warnings: list[str] = []
        for name in screenplay.all_characters:
            evidence = self._evidence_for_character(screenplay, name)
            descriptive = _unique([
                fragment
                for _scene, _line, content in evidence
                for fragment in self._identity_fact_fragments(name, content)
            ])
            appearance_facts = _unique([
                content for content in descriptive if any(term in content for term in _APPEARANCE_TERMS)
            ])[:20]
            identity_override = overrides.get(name, "").strip()
            if identity_override:
                identity_dna = identity_override
                identity_status = "bound"
            elif appearance_facts:
                identity_dna = _clip(_CLAUSE.join(appearance_facts[:8]), 3_800)
                identity_status = "bound"
            else:
                identity_dna = _says("character.identity_placeholder", name=name)
                identity_status = "needs_review"
                warnings.append(_says("character.missing_dna_warning", name=name))

            costumes: list[CharacterCostumeProfile] = []
            for scene_number in sorted({scene for scene, _line, _content in evidence}):
                descriptions = _unique([
                    fragment
                    for scene, _line, content in evidence
                    if scene == scene_number
                    for fragment in self._identity_fact_fragments(name, content)
                    if any(term in fragment for term in _COSTUME_TERMS)
                ])
                if descriptions:
                    joined = _clip(_CLAUSE.join(descriptions[:5]), 1_800)
                    costumes.append(CharacterCostumeProfile(
                        scene_numbers=[scene_number],
                        description=joined,
                        colors=[color for color in _COLOR_TERMS if color in joined],
                        accessories=[term for term in _ACCESSORY_TERMS if term in joined],
                    ))
            props = _unique([
                term for _scene, _line, content in evidence for term in _PROP_TERMS if term in content
            ])
            expressions = _unique([
                observable for _scene, _line, content in evidence
                for mood, observable in _MOOD_VISUALS.items() if mood in content
            ])
            appearances = sorted({scene for scene, _line, _content in evidence})
            role = (
                "lead" if ranked and name == ranked[0]
                else "supporting" if dialogue_counts.get(name, 0) > 0
                else "extra"
            )
            actor_sheet = build_actor_sheet_prompt(name, identity_dna, visual_style)
            profiles.append(CharacterPromptProfile(
                name=name,
                role=role,
                identity_status=identity_status,
                identity_dna=identity_dna,
                appearance_facts=appearance_facts,
                personality_expressions=expressions,
                costumes=costumes,
                props=props,
                scene_appearances=appearances,
                evidence_lines=sorted({line for _scene, line, _content in evidence}),
                five_view_order=list(IDENTITY_VIEW_ORDER),
                five_view_prompt=actor_sheet,
                consistency_seed=_says(
                    "character.consistency_seed", name=name, identity=_layered_identity(identity_dna)
                ),
            ))
        return profiles, warnings

    @staticmethod
    def _scene_text(scene: ParsedScreenplayScene) -> str:
        return "\n".join(element.content for element in scene.elements)

    def analyze_scenes(
        self, screenplay: ParsedScreenplay, overrides: dict[int, str]
    ) -> list[ScenePromptProfile]:
        results: list[ScenePromptProfile] = []
        for scene in screenplay.scenes:
            text = self._scene_text(scene)
            key_props = _unique([term for term in _PROP_TERMS if term in text])
            effects = _unique([term for term in _EFFECT_TERMS if term in text])
            weather = next((term for term in _WEATHER_TERMS if term in text), "")
            season = next((term for term in _SEASON_TERMS if term in text), "")
            explicit_moods = [mood for mood in _MOOD_VISUALS if mood in text]
            colors = [color for color in _COLOR_TERMS if color in text]
            time_upper = scene.time_of_day.upper()
            if scene.int_ext == "EXT" and any(term in time_upper for term in _DAYLIGHT_WORDS):
                source_type = "natural"
            elif any(term in time_upper for term in _NIGHT_WORDS):
                source_type = "artificial" if scene.int_ext == "INT" else "mixed"
            else:
                source_type = "unspecified"
            spatial = _clip(overrides.get(scene.number, "").strip(), 2_800) or _says(
                "scene.spatial_default", location=scene.location
            )
            lighting = SceneLightingProfile(source_type=source_type, **_table("scene.lighting_fields"))
            visual_parts = [
                _says("scene.visual_place", int_ext=scene.int_ext, location=scene.location),
                _says("scene.visual_time", time_of_day=scene.time_of_day),
                _says("scene.visual_space", spatial=spatial),
            ]
            if key_props:
                visual_parts.append(_says("scene.visual_props", props=_LIST.join(key_props)))
            if effects:
                visual_parts.append(_says("scene.visual_effects", effects=_LIST.join(effects)))
            if explicit_moods:
                visual_parts.append(_says("scene.visual_moods", moods=_LIST.join(explicit_moods)))
            visual_prompt = _CLAUSE.join(visual_parts)
            results.append(ScenePromptProfile(
                scene_number=scene.number,
                heading=scene.heading,
                location=scene.location,
                int_ext=scene.int_ext,
                time_of_day=scene.time_of_day,
                weather=weather,
                season=season,
                spatial_layout=spatial,
                key_props=key_props,
                background_elements=[],
                lighting=lighting,
                color_palette=colors,
                mood_keywords=explicit_moods,
                visual_prompt=visual_prompt,
                consistency_seed=_says(
                    "scene.consistency_seed", number=scene.number, visual_prompt=visual_prompt
                ),
            ))
        return results

    @staticmethod
    def _beats(scene: ParsedScreenplayScene) -> list[_Beat]:
        beats: list[_Beat] = []
        pending_parenthetical: dict[str, str] = {}
        for element in scene.elements:
            if element.type == "parenthetical":
                pending_parenthetical[element.speaker] = element.content
            elif element.type == "dialogue":
                direction = pending_parenthetical.pop(element.speaker, "")
                said = (
                    _says(
                        "beat.dialogue_directed",
                        speaker=element.speaker, direction=direction, line=element.content,
                    )
                    if direction
                    else _says("beat.dialogue", speaker=element.speaker, line=element.content)
                )
                beats.append(_Beat(
                    text=_clip(said, 1_200), kind="dialogue",
                    speaker=element.speaker, dialogue=_clip(element.content, 800),
                ))
            elif element.type in {"action", "transition"}:
                beats.append(_Beat(text=_clip(element.content, 1_200), kind=element.type))
        if not beats:
            beats.append(_Beat(text=_says("beat.opening", location=scene.location), kind="action"))
        return beats

    def compile_director_plan(
        self,
        *,
        scene: ParsedScreenplayScene,
        profile: ScenePromptProfile,
        characters: list[CharacterPromptProfile],
        title: str,
        visual_style: str,
    ) -> StoryboardDirectorResult:
        scene_characters = [
            character for character in characters if scene.number in character.scene_appearances
        ]
        if not scene_characters:
            scene_characters = characters[:1]
        director_characters: list[DirectorCharacter] = []
        costume_locks: list[str] = []
        for character in scene_characters:
            costume = next(
                (
                    item.description for item in character.costumes
                    if scene.number in item.scene_numbers
                ),
                _says("common.unknown_costume"),
            )
            costume_locks.append(_says("director.costume_lock", name=character.name, costume=costume))
            age = next(
                iter(_AGE_MARKER.findall(character.identity_dna)),
                _says("director.age_unknown"),
            )
            director_characters.append(DirectorCharacter(
                name=character.name,
                age_impression=age,
                appearance=character.identity_dna,
                costume=costume,
                psychological_state=(
                    _LIST.join(character.personality_expressions)
                    or _says("director.psychological_default")
                ),
                **_table("director.character_fields"),
            ))
        if not director_characters:
            director_characters.append(DirectorCharacter(
                name=_says("common.unknown_character"),
                appearance=_says("director.unknown_appearance"),
                costume=_says("common.unknown_costume"),
            ))
        props = profile.key_props or [_says("common.no_props")]
        director_props = [
            DirectorProp(name=name, **_table("director.prop_fields"))
            for name in props
        ]
        source_beats = self._beats(scene)
        events = [
            StoryEvent(
                kind=(beat.kind if beat.kind in {"dialogue", "transition"} else "action"),
                text=beat.text,
                speaker=beat.speaker,
                exact_text=beat.dialogue,
            )
            for beat in source_beats
        ]
        palette = profile.color_palette or list(_table("director.palette_fallback"))
        # 面部锚点只锁看得见脸的几层，体态层归体态锚点：两条锁各管各的，不重复堆词。
        cards = {character.name: parse_face_card(character.identity_dna) for character in scene_characters}
        face_anchor = _CLAUSE.join(
            _says(
                "director.face_anchor",
                name=character.name,
                anchor=(
                    render_face_card(cards[character.name], 'close', include_other=False)
                    if cards[character.name].has_face_layers else character.identity_dna
                ),
            )
            for character in scene_characters
        ) or _says("director.face_anchor_missing")
        physiques = _CLAUSE.join(
            _says("director.physique", name=name, physique=_LIST.join(card.physique))
            for name, card in cards.items() if card.physique
        )
        duration = _bounded(
            scene.estimated_duration_seconds or len(events) * 2.0, 0.5, 300
        )
        request = StoryboardDirectorRequest(
            project_name=title,
            scene_number=scene.number,
            shot_number=f"S{scene.number:03d}",
            duration_seconds=round(duration, 3),
            script_text=_clip(self._scene_text(scene), 100_000),
            characters=director_characters,
            scene=DirectorScene(
                time=scene.time_of_day,
                location=profile.location,
                weather=profile.weather or _says("director.weather_unknown"),
                spatial_structure=profile.spatial_layout,
                props=director_props,
                **_table("director.scene_fields"),
            ),
            events=events,
            global_visual=GlobalVisualRules(
                visual_style=visual_style,
                overall_atmosphere=_LIST.join(profile.mood_keywords) or _says("director.atmosphere_default"),
                **_table("director.global_visual_fields"),
            ),
            continuity=ContinuityLocks(
                face_anchor=face_anchor,
                body_anchor=(
                    _says("director.body_anchor")
                    + (_says("director.body_anchor_physiques", physiques=physiques) if physiques else "")
                ),
                costume_anchor=_CLAUSE.join(costume_locks) or _says("director.costume_anchor_missing"),
                scene_structure=profile.spatial_layout,
                prop_positions=_CLAUSE.join(
                    _says(
                        "director.prop_position",
                        name=item.name, position=item.initial_position, state=item.initial_state,
                    )
                    for item in director_props
                ),
                key_light_direction=profile.lighting.direction,
                **_table("director.continuity_fields"),
            ),
            shot_visual=ShotVisualDesign(
                base_content=_says(
                    "director.base_content",
                    location=profile.location,
                    characters=_LIST.join(item.name for item in director_characters),
                    props=_LIST.join(props),
                ),
                spatial_layers=_says("director.spatial_layers", layout=profile.spatial_layout),
                **_table("director.shot_visual_fields"),
            ),
            color=ColorDesign(
                primary_color=palette[0],
                secondary_color=palette[1] if len(palette) > 1 else palette[0],
                accent_color=palette[-1],
                color_temperature=profile.lighting.color_temperature,
                **_table("director.color_fields"),
            ),
            dynamics=DynamicsDesign(**_table("director.dynamics_fields")),
            camera=CameraDesign(**_table("director.camera_fields")),
            transitions=TransitionDesign(
                entry=TransitionEdge(**_table("director.entry_fields")),
                exit=TransitionEdge(**_table("director.exit_fields")),
            ),
            **_table("director.request_fields"),
        )
        return self.director.compile(request)

    def build_storyboards(
        self,
        *,
        scene: ParsedScreenplayScene,
        profile: ScenePromptProfile,
        title: str,
        director_plan: StoryboardDirectorResult,
    ) -> list[NineGridStoryboard]:
        source_beats = self._beats(scene)
        characters = scene.characters or [_says("common.unknown_character")]
        props = profile.key_props or [_says("common.no_props")]
        scene_text = self._scene_text(scene)
        effects = _unique([term for term in _EFFECT_TERMS if term in scene_text]) or [_says("storyboard.no_effects")]
        # Shot size and camera movement per kind of beat; the shot purpose, lens and aperture are codes.
        coverage = _table("storyboard.coverage")
        boards: list[NineGridStoryboard] = []
        for page in director_plan.grid_pages:
            page_beats = [beat for beat in director_plan.beats if beat.page_number == page.page_number]
            panels: list[StoryboardPanel] = []
            for beat in page_beats:
                source = source_beats[beat.index - 1]
                is_first = beat.index == 1
                is_last = beat.index == len(director_plan.beats)
                if is_first:
                    purpose, kind, lens, aperture = "information", "first", 35, "T4.0"
                elif source.kind == "dialogue":
                    purpose, kind, lens, aperture = "tension", "dialogue", 50, "T2.8"
                elif is_last:
                    purpose, kind, lens, aperture = "emotion", "last", 75, "T2.0"
                elif source.kind == "transition":
                    purpose, kind, lens, aperture = "information", "transition", 35, "T4.0"
                else:
                    purpose, kind, lens, aperture = "information", "other", 50, "T2.8"
                size, movement = coverage[kind]["shot_size"], coverage[kind]["movement"]
                panel_characters = _unique([
                    character for character in characters
                    if character in source.text or len(characters) == 1
                ]) or characters[:2]
                expression = next(
                    (observable for mood, observable in _MOOD_VISUALS.items() if mood in source.text),
                    _says("storyboard.expression_default"),
                )
                panels.append(StoryboardPanel(
                    index=beat.page_slot,
                    characters=panel_characters,
                    shot_size=size,
                    camera_movement=_says("storyboard.camera_movement", movement=movement, phase=beat.action_phase),
                    camera_reason=_clip(_says("storyboard.camera_reason", event=beat.core_event), 500),
                    lens_mm=lens,
                    aperture=aperture,
                    shot_purpose=purpose,
                    story_beat=_clip(
                        _says("storyboard.story_beat", phase=beat.action_phase, event=beat.core_event), 500
                    ),
                    duration_seconds=beat.duration_seconds,
                    subject_action=_clip(beat.core_event, 2_000),
                    expression=expression,
                    scene=_clip(profile.visual_prompt, 500),
                    props=props,
                    effects=effects,
                    dialogue=beat.verbatim_line,
                    sound=_says("storyboard.sound", environment=beat.environmental_sound),
                    lighting=_clip(_says(
                        "storyboard.lighting",
                        direction=profile.lighting.direction,
                        intensity=profile.lighting.intensity,
                        color_temperature=profile.lighting.color_temperature,
                        quality=profile.lighting.quality,
                        color_state=beat.color_state,
                    ), 800),
                    edit_in=_clip((
                        _says("storyboard.edit_in_first") if is_first
                        else _says("storyboard.edit_in", state=beat.start_state)
                    ), 500),
                    edit_out=_clip((
                        _says("storyboard.edit_out_last") if is_last
                        else _says("storyboard.edit_out", state=beat.end_state)
                    ), 500),
                    generation_mode="auto",
                    blocking=_clip(profile.spatial_layout, 800),
                    start_state=_clip(beat.start_state, 1_000),
                    end_state=_clip(beat.end_state, 1_000),
                    continuity_in=(
                        "" if is_first
                        else _clip(_says("storyboard.continuity_in", state=beat.start_state), 1_000)
                    ),
                    continuity_out=_clip(beat.end_state, 1_000),
                    **_table("storyboard.panel_fields"),
                ))
            boards.append(NineGridStoryboard(
                title=_clip(
                    _says("storyboard.board_title", title=title, scene=scene.number, page=page.page_number), 200
                ),
                scene_number=scene.number,
                page_number=page.page_number,
                total_pages=len(director_plan.grid_pages),
                rhythm_profile="confrontation",
                assets=StoryAssetCatalog(
                    characters=characters,
                    scenes=[profile.location],
                    props=props,
                    effects=effects,
                ),
                panels=panels,
            ))
        return boards

    @staticmethod
    def _dialogue_entry(panel: StoryboardPanel) -> list[Sd25DialogueEntry]:
        if not panel.dialogue or _SPEAKER not in panel.dialogue:
            return []
        speaker, text = panel.dialogue.split(_SPEAKER, 1)
        if not speaker.strip() or not text.strip():
            return []
        return [Sd25DialogueEntry(
            speaker=speaker.strip(), text=text.strip(),
            delivery=panel.expression, position="画内",
        )]

    def compile_shot_prompts(
        self,
        *,
        storyboards: list[NineGridStoryboard],
        director_plans: list[StoryboardDirectorResult],
        assignments: dict[tuple[int, int, int], ShotReferenceAssignment],
        visual_style: str,
        video_model: str,
        provider_parameters: dict[str, str | int | float | bool],
    ) -> list[ShotPromptBundle]:
        bundles: list[ShotPromptBundle] = []
        plans = {plan.scene_number: plan for plan in director_plans}
        for board in storyboards:
            plan = plans[board.scene_number]
            for panel in board.panels:
                contract = ShotMotionContract.from_panel(panel)
                image_prompt = compile_storyboard_image_prompt(contract, visual_style=visual_style)
                motion_prompt = compile_motion_prompt(contract)
                assert_prompt_pair_consistent(image_prompt, motion_prompt)
                beat_index = (board.page_number - 1) * 9 + panel.index
                director_still = plan.still_prompts[beat_index - 1].prompt
                director_segment = next(
                    (
                        item.prompt for item in plan.video_segments
                        if item.from_beat == beat_index
                    ),
                    "",
                )
                detailed_image_prompt = _says(
                    "shot.image_prompt", still=director_still, contract=image_prompt.prompt
                )
                detailed_motion_prompt = (
                    _says("shot.motion_prompt", segment=director_segment, contract=motion_prompt.prompt)
                    if director_segment else motion_prompt.prompt
                )
                assignment = assignments.get(
                    (board.scene_number, board.page_number, panel.index)
                )
                assets = assignment.assets if assignment else []
                sd25_request = Sd25CompileRequest(
                    goal=detailed_motion_prompt,
                    task="generation",
                    assets=assets,
                    dialogue=self._dialogue_entry(panel),
                    first_frame_ref=assignment.first_frame_ref if assignment else None,
                    last_frame_ref=assignment.last_frame_ref if assignment else None,
                    keyframe_refs=assignment.keyframe_refs if assignment else [],
                    storyboard_ref=assignment.storyboard_ref if assignment else None,
                    storyboard=board if assignment and assignment.storyboard_ref else None,
                    blockout_ref=assignment.blockout_ref if assignment else None,
                    blockout_granularity=assignment.blockout_granularity if assignment else None,
                    parameters=provider_parameters,
                )
                compiled = self.sd25.compile(sd25_request)
                route_plan: dict[str, object] | None = None
                warnings: list[str] = []
                if assignment and assignment.route:
                    route = assignment.route
                    reference_plan = plan_video_references(
                        route.requested_mode,
                        model=route.model or video_model,
                        first_frame=route.first_frame,
                        last_frame=route.last_frame,
                        sequence_images=route.sequence_images,
                        reference_images=route.reference_images,
                        reference_videos=route.reference_videos,
                        reference_audios=route.reference_audios,
                        intent=VideoGenerationIntent(
                            exact_end_frame_required=route.exact_end_frame_required,
                            narrative_image_sequence=route.narrative_image_sequence,
                            identity_consistency_required=route.identity_consistency_required,
                            motion_reference_required=route.motion_reference_required,
                            audio_rhythm_required=route.audio_rhythm_required,
                            multi_shot_output=route.multi_shot_output,
                        ),
                    )
                    route_plan = reference_plan.model_dump(mode="json")
                    if reference_plan.provider_status != "integrated":
                        warnings.append(
                            _says("shot.route_only_warning", family=reference_plan.provider_family)
                        )
                bundles.append(ShotPromptBundle(
                    scene_number=board.scene_number,
                    page_number=board.page_number,
                    panel_index=panel.index,
                    beat_index=beat_index,
                    director_plan_fingerprint=plan.plan_fingerprint,
                    contract_fingerprint=contract.contract_fingerprint,
                    storyboard_image_prompt=detailed_image_prompt,
                    motion_prompt=detailed_motion_prompt,
                    sd25_mode=compiled.mode,
                    sd25_prompt=compiled.prompt,
                    provider_parameters=compiled.parameters,
                    video_reference_plan=route_plan,
                    used_assets=compiled.used_assets,
                    unused_assets=compiled.unused_assets,
                    warnings=warnings + compiled.warnings,
                ))
        return bundles

    @staticmethod
    def check_consistency(
        characters: list[CharacterPromptProfile],
        scenes: list[ScenePromptProfile],
        storyboards: list[NineGridStoryboard],
        shot_prompts: list[ShotPromptBundle],
    ) -> PromptConsistencyReport:
        issues: list[PromptConsistencyIssue] = []
        if not characters:
            issues.append(PromptConsistencyIssue(
                code="missing_character_cast",
                severity="error",
                location=_says("consistency.whole_project"),
                description=_says("consistency.missing_character_cast.description"),
                suggestion=_says("consistency.missing_character_cast.suggestion"),
            ))
        for character in characters:
            if character.identity_status == "needs_review":
                issues.append(PromptConsistencyIssue(
                    code="missing_identity_dna",
                    severity="error",
                    location=_says("consistency.character_location", name=character.name),
                    description=_says("consistency.missing_identity_dna.description"),
                    suggestion=_says("consistency.missing_identity_dna.suggestion"),
                ))
            if character.identity_status == "bound":
                for card_issue in audit_face_card(parse_face_card(character.identity_dna)):
                    issues.append(PromptConsistencyIssue(
                        code=f"face_card_{card_issue.code}",
                        severity="warning",
                        location=_says("consistency.character_location", name=character.name),
                        description=card_issue.message,
                        suggestion=card_issue.suggestion,
                    ))
            if len(character.costumes) > 1:
                issues.append(PromptConsistencyIssue(
                    code="costume_change_tracked",
                    severity="warning",
                    location=_says("consistency.character_location", name=character.name),
                    description=_says("consistency.costume_change_tracked.description"),
                    suggestion=_says("consistency.costume_change_tracked.suggestion"),
                ))
        for board in storyboards:
            report = validate_storyboard_continuity(board.panels)
            for issue in report.issues:
                issues.append(PromptConsistencyIssue(
                    code=f"storyboard_{issue.code}",
                    severity="error",
                    location=_says("consistency.panel_location", title=board.title, panel=issue.panel_index),
                    description=issue.message,
                    suggestion=_says("consistency.storyboard_suggestion"),
                ))
        expected_count = sum(len(board.panels) for board in storyboards)
        if len(shot_prompts) != expected_count:
            issues.append(PromptConsistencyIssue(
                code="shot_prompt_count_mismatch",
                severity="error",
                location=_says("consistency.whole_project"),
                description=_says("consistency.shot_prompt_count_mismatch.description"),
                suggestion=_says("consistency.shot_prompt_count_mismatch.suggestion"),
            ))
        board_panels = {
            (board.scene_number, board.page_number, panel.index): panel
            for board in storyboards
            for panel in board.panels
        }
        for bundle in shot_prompts:
            panel = board_panels.get(
                (bundle.scene_number, bundle.page_number, bundle.panel_index)
            )
            if panel and ShotMotionContract.from_panel(panel).contract_fingerprint != bundle.contract_fingerprint:
                issues.append(PromptConsistencyIssue(
                    code="shot_contract_drift",
                    severity="error",
                    location=_says(
                        "consistency.shot_location",
                        scene=bundle.scene_number, page=bundle.page_number, panel=bundle.panel_index,
                    ),
                    description=_says("consistency.shot_contract_drift.description"),
                    suggestion=_says("consistency.shot_contract_drift.suggestion"),
                ))
        return PromptConsistencyReport(
            passed=not any(issue.severity == "error" for issue in issues),
            character_seeds={character.name: character.consistency_seed for character in characters},
            scene_seeds={str(scene.scene_number): scene.consistency_seed for scene in scenes},
            issues=issues,
        )

    def render_exports(self, payload: dict[str, object], formats: list[str]) -> dict[str, str]:
        exports: dict[str, str] = {}
        if "json" in formats:
            exports["json"] = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        if "markdown" in formats:
            exports["markdown"] = self._render_markdown(payload)
        if "csv" in formats:
            exports["csv"] = self._render_csv(payload)
        if "html" in formats:
            exports["html"] = self._render_html(payload)
        if "xlsx" in formats:
            exports["xlsx_base64"] = base64.b64encode(self._render_xlsx(payload)).decode("ascii")
        return exports

    @staticmethod
    def _render_markdown(payload: dict[str, object]) -> str:
        screenplay: dict = payload["screenplay"]  # type: ignore[assignment]
        lines = [_says("markdown.title", title=_markdown_cell(screenplay["title"])), ""]
        lines.extend([
            _says("markdown.metadata_heading"), "",
            _says("markdown.source_sha256", sha256=payload["source_sha256"]),
            _says("markdown.scene_count", count=len(screenplay["scenes"])),
            _says("markdown.duration", seconds=screenplay["total_duration_seconds"]), "",
            _says("markdown.characters_heading"), "",
        ])
        for character in payload["characters"]:  # type: ignore[index]
            lines.extend([
                f"### {_markdown_cell(character['name'])}", "",
                _says("markdown.identity_status", status=_markdown_cell(character["identity_status"])),
                _says("markdown.identity_dna", dna=_markdown_cell(character["identity_dna"])), "",
                _markdown_text(character["five_view_prompt"]), "",
            ])
        lines.extend([_says("markdown.storyboards_heading"), ""])
        for board in payload["storyboards"]:  # type: ignore[index]
            lines.extend([
                f"### {_markdown_cell(board['title'])}", "",
                _says("markdown.panel_table_header"),
                "|---:|---|---|---|---|---|---|---|",
            ])
            for panel in board["panels"]:
                lines.append(
                    f"| {panel['index']} | {_markdown_cell(panel['shot_purpose'])} | "
                    f"{_markdown_cell(_LIST.join(panel['characters']))} | {_markdown_cell(panel['shot_size'])} | "
                    f"{_markdown_cell(panel['camera_movement'])} | {_markdown_cell(panel['subject_action'])} | "
                    f"{_markdown_cell(panel['start_state'])} | {_markdown_cell(panel['end_state'])} |"
                )
            lines.append("")
        lines.extend([_says("markdown.plans_heading"), ""])
        for plan in payload["director_plans"]:  # type: ignore[index]
            lines.extend([
                _says("markdown.plan_heading", scene=plan["scene_number"], shot=_markdown_cell(plan["shot_number"])), "",
                _says("markdown.plan_beats", count=len(plan["beats"])),
                _says("markdown.plan_pages", count=len(plan["grid_pages"])),
                _says("markdown.plan_segments", count=len(plan["video_segments"])),
                _says("markdown.plan_fingerprint", fingerprint=plan["plan_fingerprint"]), "",
            ])
        lines.extend([_says("markdown.shots_heading"), ""])
        for shot in payload["shot_prompts"]:  # type: ignore[index]
            lines.extend([
                _says(
                    "markdown.shot_heading",
                    scene=shot["scene_number"], page=shot["page_number"],
                    panel=shot["panel_index"], beat=shot["beat_index"],
                ), "",
                _markdown_text(shot["sd25_prompt"]), "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _shot_rows(payload: dict[str, object]) -> list[list[object]]:
        boards = {
            (board["scene_number"], board["page_number"], panel["index"]): panel
            for board in payload["storyboards"]  # type: ignore[index]
            for panel in board["panels"]
        }
        rows: list[list[object]] = []
        for shot in payload["shot_prompts"]:  # type: ignore[index]
            panel = boards[(shot["scene_number"], shot["page_number"], shot["panel_index"])]
            rows.append([
                shot["scene_number"], shot["page_number"], shot["panel_index"], shot["beat_index"],
                _LIST.join(panel["characters"]),
                panel["scene"], _LIST.join(panel["props"]), _LIST.join(panel["effects"]),
                panel["shot_size"], panel["camera_angle"], panel["camera_movement"],
                panel["subject_action"], panel["expression"], panel["dialogue"], panel["sound"],
                panel["duration_seconds"], panel["start_state"], panel["end_state"],
                shot["sd25_mode"], shot["storyboard_image_prompt"], shot["motion_prompt"],
                shot["sd25_prompt"], shot["director_plan_fingerprint"], shot["contract_fingerprint"],
            ])
        return rows

    def _render_csv(self, payload: dict[str, object]) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(list(_table("sheet.headers")))
        for row in self._shot_rows(payload):
            writer.writerow([_safe_sheet_text(value) for value in row])
        return "\ufeff" + output.getvalue()

    @staticmethod
    def _render_html(payload: dict[str, object]) -> str:
        screenplay: dict = payload["screenplay"]  # type: ignore[assignment]
        title = html.escape(str(screenplay["title"]))
        cards: list[str] = []
        for shot in payload["shot_prompts"]:  # type: ignore[index]
            cards.append(
                '<article class="shot">'
                "<h3>"
                + _says(
                    "html.shot_heading",
                    scene=int(shot["scene_number"]), page=int(shot["page_number"]), panel=int(shot["panel_index"]),
                )
                + "</h3>"
                f"<p><strong>{_says('html.mode_label')}</strong>{html.escape(str(shot['sd25_mode']))}</p>"
                f"<pre>{html.escape(str(shot['sd25_prompt']))}</pre>"
                "<small>"
                + _says("html.plan_fingerprint", fingerprint=html.escape(str(shot["director_plan_fingerprint"])))
                + "</small><br>"
                "<small>"
                + _says("html.contract_fingerprint", fingerprint=html.escape(str(shot["contract_fingerprint"])))
                + "</small>"
                "</article>"
            )
        character_cards = "".join(
            '<article class="character">'
            f"<h3>{html.escape(str(character['name']))}</h3>"
            f"<p>{html.escape(str(character['identity_dna']))}</p>"
            f"<pre>{html.escape(str(character['five_view_prompt']))}</pre>"
            "</article>"
            for character in payload["characters"]  # type: ignore[index]
        )
        return (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_says('html.page_title', title=title)}</title><style>"
            "body{font-family:system-ui,sans-serif;max-width:1100px;margin:auto;padding:24px;background:#f6f7f9;color:#18202a}"
            "article{background:white;border:1px solid #dce1e7;border-radius:10px;padding:16px;margin:12px 0}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f7;padding:12px;border-radius:6px}"
            "small{overflow-wrap:anywhere}</style></head><body>"
            f"<h1>{title}</h1><p>"
            + _says(
                "html.summary",
                scenes=len(screenplay["scenes"]), duration=float(screenplay["total_duration_seconds"]),
            )
            + "</p>"
            f"<h2>{_says('html.characters_heading')}</h2>{character_cards}"
            f"<h2>{_says('html.shots_heading')}</h2>{''.join(cards)}"
            "</body></html>"
        )

    def _render_xlsx(self, payload: dict[str, object]) -> bytes:
        headers = list(_table("sheet.headers"))
        rows = [headers] + self._shot_rows(payload)

        def column_name(index: int) -> str:
            value = ""
            while index:
                index, remainder = divmod(index - 1, 26)
                value = chr(65 + remainder) + value
            return value

        row_xml: list[str] = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for col_index, raw in enumerate(row, start=1):
                value = xml_escape(_safe_sheet_text(raw), {'"': '&quot;'})
                ref = f"{column_name(col_index)}{row_index}"
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{value}</t></is></c>')
            row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        worksheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:X{len(rows)}"/><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        sheet_name = xml_escape(_says("sheet.name"), {'"': '&quot;'})
        workbook = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        return output.getvalue()
