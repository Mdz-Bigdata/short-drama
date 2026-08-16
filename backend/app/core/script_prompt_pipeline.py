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
from xml.sax.saxutils import escape as xml_escape

from app.core.sd25_compiler import Sd25PromptCompiler
from app.core.shot_motion_contract import (
    ShotMotionContract,
    assert_prompt_pair_consistent,
    compile_motion_prompt,
    compile_storyboard_image_prompt,
)
from app.core.storyboard_quality import build_five_view_prompt, validate_storyboard_continuity
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.core.video_references import VideoGenerationIntent, plan_video_references
from app.schema.production import (
    FIVE_VIEW_ORDER,
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


_EN_SCENE = re.compile(
    r"^(INT\.?|EXT\.?|INT/EXT\.?|I/E\.?)\s*(.+?)(?:\s*[-–—]\s*(.+))?$",
    re.IGNORECASE,
)
_CN_NUMBERED_SCENE = re.compile(
    r"^(?:场景\s*[零〇一二三四五六七八九十百千万两\d]+|第\s*[零〇一二三四五六七八九十百千万两\d]+\s*[场幕])"
    r"\s*[：:]?\s*(.+)$"
)
_CN_SCENE = re.compile(r"^(内景|外景|内外景)\s*[：:]\s*(.+?)(?:\s*[-–—]\s*(.+))?$")
_TRANSITION = re.compile(
    r"^(?:FADE\s+IN:|FADE\s+OUT\.?|CUT\s+TO:|DISSOLVE\s+TO:|SMASH\s+CUT(?:\s+TO)?:|"
    r"MATCH\s+CUT(?:\s+TO)?:|淡入|淡出|切至|转场)",
    re.IGNORECASE,
)
_PARENTHETICAL = re.compile(r"^[（(](.+)[）)]$")
_BRACKET_DIALOGUE = re.compile(r"^【([^】]{1,120})】\s*(.*)$")
_INLINE_DIALOGUE = re.compile(r"^([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff· ._-]{0,40})[：:]\s*(.+)$")
_UPPER_CHARACTER = re.compile(r"^[A-Z][A-Z0-9 ._'’-]{0,50}(?:\s*\([^)]*\))?$")
_CN_ACTION_CHARACTER = re.compile(
    r"^([\u4e00-\u9fff·]{2,12})[（(]([^）)]*(?:岁|男性|女性|男|女|发|穿着|身穿)[^）)]*)[）)]"
)
_NON_CHARACTER_LABELS = {
    "场景", "内景", "外景", "内外景", "备注", "注", "时间", "地点", "动作", "镜头",
    "道具", "特效", "场景描述", "人物", "角色", "对白", "旁白", "音效", "音乐",
}

_APPEARANCE_TERMS = (
    "岁", "青年", "少年", "中年", "老年", "男人", "女人", "男孩", "女孩", "男性", "女性",
    "高挑", "矮小", "瘦", "苗条", "微胖", "健壮", "魁梧", "长发", "短发", "卷发", "直发",
    "马尾", "丸子头", "寸头", "光头", "黑发", "白发", "灰发", "金发", "棕发", "脸", "眼",
    "眉", "鼻", "唇", "痣", "疤", "雀斑", "眼镜", "胡须", "肤色", "身高", "体型",
)
_COSTUME_TERMS = (
    "穿着", "身穿", "换上", "脱下", "外套", "风衣", "西装", "衬衫", "裙", "裤", "鞋", "帽",
    "围巾", "制服", "校服", "礼服", "睡衣", "夹克", "毛衣", "背心", "盔甲", "披风", "围裙",
)
_PROP_TERMS = (
    "手机", "信封", "信", "钥匙", "杯", "咖啡", "伞", "书", "文件", "箱", "包", "戒指", "项链",
    "手表", "照片", "刀", "剑", "枪", "棍", "车", "桌", "椅", "门", "电脑", "录音笔", "存储卡",
)
_EFFECT_TERMS = (
    "雨", "雪", "雾", "烟", "火", "爆炸", "闪电", "魔法", "能量", "光束", "粒子", "全息", "风沙",
)
_INDOOR_LOCATIONS = (
    "办公室", "卧室", "客厅", "厨房", "餐厅", "咖啡厅", "酒吧", "医院", "教室", "会议室", "电梯", "走廊",
)
_OUTDOOR_LOCATIONS = (
    "街道", "公园", "海滩", "森林", "山", "天台", "停车场", "校园", "广场",
)
_COLOR_TERMS = (
    "黑色", "白色", "灰色", "红色", "橙色", "黄色", "绿色", "蓝色", "紫色", "粉色", "棕色",
    "金色", "银色", "青色", "米白", "藏蓝", "酒红",
)
_MOOD_VISUALS = {
    "克制": "呼吸受控、动作幅度收小、情绪只通过眼神和细微肌肉变化外露",
    "紧张": "肩颈收紧、呼吸变浅、视线短促移动",
    "焦虑": "手指轻微反复动作、呼吸不稳、视线回避",
    "愤怒": "眉间收紧、下颌绷紧、目光固定",
    "悲伤": "眼睑下垂、呼吸放慢、肩部略微下沉",
    "恐惧": "瞳孔方向骤变、呼吸急促、身体后撤",
    "温柔": "眼神放松、嘴角轻微上扬、动作幅度收小",
    "开心": "眼角与嘴角同步上扬、身体姿态打开",
    "冷静": "呼吸均匀、视线稳定、动作节制",
}


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
    match = re.match(r"^[（(]([^）)]{1,500})[）)]\s*(.*)$", value.strip())
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
            int_ext = "INT/EXT" if raw in {"INT/EXT", "I/E"} else raw
            return int_ext, match.group(2).strip(), (match.group(3) or "UNSPECIFIED").strip()
        match = _CN_SCENE.match(line)
        if match:
            int_ext = {"内景": "INT", "外景": "EXT", "内外景": "INT/EXT"}[match.group(1)]
            return int_ext, match.group(2).strip(), (match.group(3) or "未注明时段").strip()
        match = _CN_NUMBERED_SCENE.match(line)
        if match:
            body = match.group(1).strip()
            chunks = re.split(r"\s*[-–—]\s*", body, maxsplit=1)
            location = chunks[0] or "未注明地点"
            time_of_day = chunks[1] if len(chunks) == 2 and chunks[1] else "未注明时段"
            int_ext = (
                "EXT" if "外" in location or any(term in location for term in _OUTDOOR_LOCATIONS)
                else "INT" if "内" in location or any(term in location for term in _INDOOR_LOCATIONS)
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
            int_ext, location, time_of_day = parsed or ("UNKNOWN", "未注明地点", "未注明时段")
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
                current = new_scene("SCENE 1")

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
                speaker = re.sub(r"\s*\([^)]*\)\s*$", "", line).strip()
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
        for parenthetical in re.findall(r"[（(]([^）)]{1,500})[）)]", content):
            if any(term in parenthetical for term in _APPEARANCE_TERMS + _COSTUME_TERMS):
                fragments.append(parenthetical.strip())
        for fragment in re.split(r"[，,。；;]", content):
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
                identity_dna = _clip("；".join(appearance_facts[:8]), 3_800)
                identity_status = "bound"
            else:
                identity_dna = (
                    f"仅锁定角色名{name}；剧本未提供足够外貌、发型、服装和体型事实，"
                    "生成前必须补充身份DNA或绑定已批准参考图"
                )
                identity_status = "needs_review"
                warnings.append(f"角色{name}缺少可验证身份DNA，五视图提示词已保留待补充边界")

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
                    joined = _clip("；".join(descriptions[:5]), 1_800)
                    costumes.append(CharacterCostumeProfile(
                        scene_numbers=[scene_number],
                        description=joined,
                        colors=[color for color in _COLOR_TERMS if color in joined],
                        accessories=[term for term in ("眼镜", "项链", "耳环", "手表", "帽", "围巾") if term in joined],
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
            five_view = build_five_view_prompt(name, identity_dna, visual_style)
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
                five_view_order=list(FIVE_VIEW_ORDER),
                five_view_prompt=five_view,
                consistency_seed=(
                    f"[CHARACTER:{name}] {identity_dna}；保持同一人物、同一面部结构、同一发型与当前场次服装"
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
            weather = next((term for term in ("暴风雨", "雨", "雪", "雾", "晴", "阴天") if term in text), "")
            season = next((term for term in ("春季", "夏季", "秋季", "冬季", "春天", "夏天", "秋天", "冬天") if term in text), "")
            explicit_moods = [mood for mood in _MOOD_VISUALS if mood in text]
            colors = [color for color in _COLOR_TERMS if color in text]
            time_upper = scene.time_of_day.upper()
            if scene.int_ext == "EXT" and any(term in time_upper for term in ("DAY", "MORNING", "AFTERNOON", "白天", "早", "下午")):
                source_type = "natural"
            elif any(term in time_upper for term in ("NIGHT", "EVENING", "夜", "傍晚")):
                source_type = "artificial" if scene.int_ext == "INT" else "mixed"
            else:
                source_type = "unspecified"
            spatial = _clip(overrides.get(scene.number, "").strip(), 2_800) or (
                f"以{scene.location}为固定空间；门窗、稳定家具、人物站位、关键道具位置与前中后景层次"
                "以剧本首次可见状态为场景圣经，后续镜头不得镜像翻转或随机迁移"
            )
            lighting = SceneLightingProfile(
                source_type=source_type,
                direction="锁定本场首次建立镜头的主光方向",
                intensity="保持本场时段与天气对应的可见亮度",
                color_temperature="保持本场首次建立镜头的色温",
                quality="人物与环境受光连续，阴影方向一致",
            )
            visual_parts = [
                f"{scene.int_ext} {scene.location}",
                f"时段：{scene.time_of_day}",
                f"空间：{spatial}",
            ]
            if key_props:
                visual_parts.append(f"关键道具：{'、'.join(key_props)}")
            if effects:
                visual_parts.append(f"环境动态或特效：{'、'.join(effects)}")
            if explicit_moods:
                visual_parts.append(f"剧本明确氛围：{'、'.join(explicit_moods)}")
            visual_prompt = "；".join(visual_parts)
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
                consistency_seed=(
                    f"[SCENE:{scene.number}] {visual_prompt}；保持空间布局、道具位置、主光方向和色温一致"
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
                prefix = f"{element.speaker}{f'（{direction}）' if direction else ''}说"
                beats.append(_Beat(
                    text=_clip(f"{prefix}：{element.content}", 1_200), kind="dialogue",
                    speaker=element.speaker, dialogue=_clip(element.content, 800),
                ))
            elif element.type in {"action", "transition"}:
                beats.append(_Beat(text=_clip(element.content, 1_200), kind=element.type))
        if not beats:
            beats.append(_Beat(text=f"建立{scene.location}的剧本开场状态", kind="action"))
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
                "剧本未提供本场服装（需确认）",
            )
            costume_locks.append(f"{character.name}：{costume}")
            age = next(
                iter(re.findall(r"\d{1,3}岁|少年|青年|中年|老年", character.identity_dna)),
                "年龄感未注明（需确认）",
            )
            director_characters.append(DirectorCharacter(
                name=character.name,
                identity="按角色档案与剧本身份",
                age_impression=age,
                appearance=character.identity_dna,
                costume=costume,
                accessories="仅保留角色档案和剧本明确配饰",
                physical_state="保持本场剧本已明确的伤痕、污渍、湿度与疲劳状态",
                psychological_state=(
                    "、".join(character.personality_expressions)
                    or "只用可观察表情、视线、呼吸和姿态呈现"
                ),
            ))
        if not director_characters:
            director_characters.append(DirectorCharacter(
                name="未识别角色（需确认）",
                appearance="剧本未提供可绑定的角色外貌（需确认）",
                costume="剧本未提供本场服装（需确认）",
            ))
        props = profile.key_props or ["无关键道具"]
        director_props = [
            DirectorProp(
                name=name,
                initial_state="保持剧本首次可见状态",
                initial_position="锁定剧本首次可见位置与持有者",
            )
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
        palette = profile.color_palette or ["场景既定主色", "场景既定辅助色"]
        face_anchor = "；".join(
            f"{character.name}：{character.identity_dna}" for character in scene_characters
        ) or "角色身份信息缺失（需确认）"
        duration = _bounded(
            scene.estimated_duration_seconds or len(events) * 2.0, 0.5, 300
        )
        request = StoryboardDirectorRequest(
            project_name=title,
            episode="由项目集数元数据继承",
            scene_number=scene.number,
            shot_number=f"S{scene.number:03d}",
            duration_seconds=round(duration, 3),
            script_text=_clip(self._scene_text(scene), 100_000),
            narrative_goal="逐字保留剧本信息，以可见动作、反应和声音完成本场叙事功能",
            characters=director_characters,
            scene=DirectorScene(
                time=scene.time_of_day,
                location=profile.location,
                weather=profile.weather or "未注明天气",
                spatial_structure=profile.spatial_layout,
                props=director_props,
                environmental_sound="保持本场连续环境声与剧本明确动作声，不编造对白",
            ),
            events=events,
            global_visual=GlobalVisualRules(
                visual_style=visual_style,
                era_and_region="严格继承剧本时代、地域和已批准美术资产",
                art_direction="场景圣经、角色五视图、服装和道具版本为硬约束",
                rendering_texture="电影摄影质感、可信材质、自然景深与皮肤纹理",
                overall_atmosphere="、".join(profile.mood_keywords) or "按本场剧本氛围",
            ),
            continuity=ContinuityLocks(
                face_anchor=face_anchor,
                body_anchor="保持角色五视图确定的身高感、肩宽、体型与比例",
                costume_anchor="；".join(costume_locks) or "本场服装版本待确认",
                scene_structure=profile.spatial_layout,
                prop_positions="；".join(
                    f"{item.name}：{item.initial_position}，{item.initial_state}"
                    for item in director_props
                ),
                key_light_direction=profile.lighting.direction,
                camera_axis="沿首次建立的180度动作轴线，除非明确展示越轴过程",
                screen_direction="角色朝向、视线和出入画方向连续",
                spatial_orientation="人物、摄影机、门窗、家具和道具的左右前后远近关系保持连续",
            ),
            shot_visual=ShotVisualDesign(
                base_content=f"{profile.location}中的{'、'.join(item.name for item in director_characters)}；关键道具{'、'.join(props)}",
                composition="主体与关键道具位于叙事视觉中心，前中后景和留白服务当前事件",
                shot_size="按事件信息量从建立景别连续过渡到关键反应景别",
                lens="35—75mm范围内按叙事目的选择，镜头内不得无原因跳变",
                camera_angle="遵守既定轴线的平视机位",
                camera_height="角色视线高度",
                depth_of_field="主体清晰、空间关系可读的受控景深",
                spatial_layers=f"前景遮挡受控；中景为角色动作；背景保持{profile.spatial_layout}",
            ),
            color=ColorDesign(
                primary_color=palette[0],
                secondary_color=palette[1] if len(palette) > 1 else palette[0],
                accent_color=palette[-1],
                color_temperature=profile.lighting.color_temperature,
                start_state="本场首次建立的曝光、色温和主辅色状态",
                change_reason="人物移动、门窗开合或剧本明确光源变化；没有依据时不变化",
                peak_state="叙事峰值仍保持同一调色系统，仅允许有来源的明暗变化",
                end_state="承接下一镜所需的最终曝光、色温和色彩状态",
            ),
            dynamics=DynamicsDesign(
                subject_direction="按剧本动作与已建立屏幕方向",
                subject_trajectory="只执行剧本可见动作所需的直线或自然弧线",
                force_source="人物主动发力、重力或剧本明确的环境力",
                speed_curve="缓起—发展—峰值—自然减速或收势",
                center_of_gravity="随动作真实转移，不瞬移、不重置",
                visual_flow="观众视线从动作发起者移动到动作目标或反应者",
                secondary_motion="衣摆、发丝和环境只响应主体动作或真实环境力",
                inertia_and_follow_through="动作结束保留符合质量和速度的惯性、回落与余振",
                motion_blur="仅快速运动部位允许轻微动态模糊",
                stable_regions="角色面部、身份锚点和关键道具保持清晰稳定",
            ),
            camera=CameraDesign(
                movement_type="由叙事事件自动选择固定、推拉、摇移或跟拍",
                start_position="既定轴线一侧的建立机位",
                end_position="同轴线一侧、能够交付最终事件状态的机位",
                path="连续直线或受控弧线，不穿越角色和场景实体",
                direction="服从主体动线和屏幕方向",
                speed_curve="缓入、按事件发展调整、缓出；禁止无原因急停",
                subject_following="保持核心主体可读，必要时延迟跟随以交付反应",
                composition_change="景别和主体位置随叙事信息连续变化，不跳切、不漂移",
                focus_change="跟焦主体；只有明确视线或线索转移时才转焦",
                stability="稳定器质感；仅剧情要求时允许轻微手持",
                forbidden_behaviors="禁止无动机旋转、突然推近、越轴、镜像翻转和随机变焦",
            ),
            transitions=TransitionDesign(
                entry=TransitionEdge(
                    visual_handoff="从上一镜构图、动作、颜色或光源承接；无上一镜时建立本场",
                    audio_handoff="保留环境声桥；无声音依据时不添加",
                ),
                exit=TransitionEdge(
                    visual_handoff="以最终姿势、视线、运动方向、光影或构图交给下一镜",
                    audio_handoff="保留尾音或明确的下一镜声音先入",
                ),
            ),
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
        characters = scene.characters or ["未识别角色（需确认）"]
        props = profile.key_props or ["无关键道具"]
        scene_text = self._scene_text(scene)
        effects = _unique([term for term in _EFFECT_TERMS if term in scene_text]) or ["无额外视觉特效"]
        boards: list[NineGridStoryboard] = []
        for page in director_plan.grid_pages:
            page_beats = [beat for beat in director_plan.beats if beat.page_number == page.page_number]
            panels: list[StoryboardPanel] = []
            for beat in page_beats:
                source = source_beats[beat.index - 1]
                is_first = beat.index == 1
                is_last = beat.index == len(director_plan.beats)
                if is_first:
                    purpose, size, movement, lens, aperture = (
                        "information", "全景", "受控建立或缓慢推进", 35, "T4.0"
                    )
                elif source.kind == "dialogue":
                    purpose, size, movement, lens, aperture = (
                        "tension", "中近景", "轴线内轻微推近或稳定跟随", 50, "T2.8"
                    )
                elif is_last:
                    purpose, size, movement, lens, aperture = (
                        "emotion", "近景", "稳定停留或缓慢拉远", 75, "T2.0"
                    )
                elif source.kind == "transition":
                    purpose, size, movement, lens, aperture = (
                        "information", "远景", "连续转场运动", 35, "T4.0"
                    )
                else:
                    purpose, size, movement, lens, aperture = (
                        "information", "中景", "按主体动线稳定跟随", 50, "T2.8"
                    )
                panel_characters = _unique([
                    character for character in characters
                    if character in source.text or len(characters) == 1
                ]) or characters[:2]
                expression = next(
                    (observable for mood, observable in _MOOD_VISUALS.items() if mood in source.text),
                    "自然表演；情绪只通过剧本可见的眼神、呼吸、姿态和肌肉变化呈现",
                )
                panels.append(StoryboardPanel(
                    index=beat.page_slot,
                    characters=panel_characters,
                    shot_size=size,
                    camera_angle="遵守180度轴线的平视机位",
                    camera_movement=f"{movement}（{beat.action_phase}阶段）",
                    camera_reason=_clip(
                        f"清楚交付唯一事件“{beat.core_event}”，不做无动机炫技", 500
                    ),
                    lens_mm=lens,
                    aperture=aperture,
                    composition="主体、动作目标和关键道具构成清晰视觉动线，前中后景保持场景圣经布局",
                    action_axis="沿本场已建立的180度轴线；人物左右关系和出入画方向连续",
                    eyeline="说话人、聆听者与动作目标的视线方向、高度和反打关系连续",
                    shot_purpose=purpose,
                    story_beat=_clip(f"{beat.action_phase}｜{beat.core_event}", 500),
                    duration_seconds=beat.duration_seconds,
                    subject_action=_clip(beat.core_event, 2_000),
                    expression=expression,
                    scene=_clip(profile.visual_prompt, 500),
                    props=props,
                    effects=effects,
                    dialogue=beat.verbatim_line,
                    sound=f"{beat.environmental_sound}；台词逐字保留且只作时间与表演依据",
                    lighting=_clip((
                        f"{profile.lighting.direction}；{profile.lighting.intensity}；"
                        f"{profile.lighting.color_temperature}；{profile.lighting.quality}；"
                        f"本拍状态：{beat.color_state}"
                    ), 800),
                    edit_in=_clip((
                        "按入场转场建立本镜头" if is_first else f"从上一拍结束状态连续进入：{beat.start_state}"
                    ), 500),
                    edit_out=_clip((
                        "按出场转场交付下一镜" if is_last else f"在关键状态可读后连续进入下一拍：{beat.end_state}"
                    ), 500),
                    generation_mode="auto",
                    blocking=_clip(profile.spatial_layout, 800),
                    start_state=_clip(beat.start_state, 1_000),
                    end_state=_clip(beat.end_state, 1_000),
                    continuity_in=(
                        "" if is_first
                        else _clip(f"承接上一拍结束状态：{beat.start_state}", 1_000)
                    ),
                    continuity_out=_clip(beat.end_state, 1_000),
                ))
            boards.append(NineGridStoryboard(
                title=_clip(f"{title}｜场景{scene.number}｜第{page.page_number}页", 200),
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
        if not panel.dialogue or "：" not in panel.dialogue:
            return []
        speaker, text = panel.dialogue.split("：", 1)
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
                detailed_image_prompt = (
                    f"{director_still}\n【共享镜头契约】{image_prompt.prompt}"
                )
                detailed_motion_prompt = (
                    f"{director_segment}\n【共享镜头契约】{motion_prompt.prompt}"
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
                            f"{reference_plan.provider_family}需要适配器或运行时能力探测，当前仅生成路由计划"
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
                location="全项目",
                description="未识别到任何角色，无法满足角色五视图和人物一致性要求。",
                suggestion="使用标准角色名/对白格式或补充角色档案后重新编译。",
            ))
        for character in characters:
            if character.identity_status == "needs_review":
                issues.append(PromptConsistencyIssue(
                    code="missing_identity_dna",
                    severity="error",
                    location=f"角色 {character.name}",
                    description="剧本没有提供足够身份事实，无法安全锁定同一人物。",
                    suggestion="补充角色身份DNA或绑定已批准参考图后再提交生成。",
                ))
            if len(character.costumes) > 1:
                issues.append(PromptConsistencyIssue(
                    code="costume_change_tracked",
                    severity="warning",
                    location=f"角色 {character.name}",
                    description="检测到跨场次服装描述，已按场次保留而未合并为同一套服装。",
                    suggestion="生成每场镜头前确认对应服装版本和参考图。",
                ))
        for board in storyboards:
            report = validate_storyboard_continuity(board.panels)
            for issue in report.issues:
                issues.append(PromptConsistencyIssue(
                    code=f"storyboard_{issue.code}",
                    severity="error",
                    location=f"{board.title} 第{issue.panel_index}格",
                    description=issue.message,
                    suggestion="补全分镜状态后重新编译图片和运镜 Prompt。",
                ))
        expected_count = sum(len(board.panels) for board in storyboards)
        if len(shot_prompts) != expected_count:
            issues.append(PromptConsistencyIssue(
                code="shot_prompt_count_mismatch",
                severity="error",
                location="全项目",
                description="分镜数量与镜头 Prompt 数量不一致。",
                suggestion="重新编译完整项目，禁止跳过任一九宫格面板。",
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
                    location=(
                        f"场景 {bundle.scene_number} / 第{bundle.page_number}页 / "
                        f"镜头 {bundle.panel_index}"
                    ),
                    description="分镜图片与运镜提示词不再来自同一语义契约。",
                    suggestion="废弃该镜头缓存并从对应九宫格面板重新编译。",
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
        lines = [f"# {_markdown_cell(screenplay['title'])} - AI视频提示词生产包", ""]
        lines.extend([
            "## 项目元数据", "",
            f"- 源文件 SHA-256：`{payload['source_sha256']}`",
            f"- 场景数：{len(screenplay['scenes'])}",
            f"- 预估时长：{screenplay['total_duration_seconds']} 秒", "",
            "## 角色五视图", "",
        ])
        for character in payload["characters"]:  # type: ignore[index]
            lines.extend([
                f"### {_markdown_cell(character['name'])}", "",
                f"- 身份状态：{_markdown_cell(character['identity_status'])}",
                f"- 身份DNA：{_markdown_cell(character['identity_dna'])}", "",
                _markdown_text(character["five_view_prompt"]), "",
            ])
        lines.extend(["## 九宫格分镜与运镜", ""])
        for board in payload["storyboards"]:  # type: ignore[index]
            lines.extend([
                f"### {_markdown_cell(board['title'])}", "",
                "| 格 | 目的 | 人物 | 景别 | 运镜 | 动作 | 开始状态 | 结束状态 |",
                "|---:|---|---|---|---|---|---|---|",
            ])
            for panel in board["panels"]:
                lines.append(
                    f"| {panel['index']} | {_markdown_cell(panel['shot_purpose'])} | "
                    f"{_markdown_cell('、'.join(panel['characters']))} | {_markdown_cell(panel['shot_size'])} | "
                    f"{_markdown_cell(panel['camera_movement'])} | {_markdown_cell(panel['subject_action'])} | "
                    f"{_markdown_cell(panel['start_state'])} | {_markdown_cell(panel['end_state'])} |"
                )
            lines.append("")
        lines.extend(["## 分镜师时间拍点与连续性自检", ""])
        for plan in payload["director_plans"]:  # type: ignore[index]
            lines.extend([
                f"### 场景 {plan['scene_number']} / 镜头 {_markdown_cell(plan['shot_number'])}", "",
                f"- 实际拍点：{len(plan['beats'])}",
                f"- 分页数：{len(plan['grid_pages'])}",
                f"- 相邻关键帧视频段：{len(plan['video_segments'])}",
                f"- 计划指纹：`{plan['plan_fingerprint']}`", "",
            ])
        lines.extend(["## 可提交 SD25 Prompt", ""])
        for shot in payload["shot_prompts"]:  # type: ignore[index]
            lines.extend([
                f"### 场景 {shot['scene_number']} / 第{shot['page_number']}页 / "
                f"镜头 {shot['panel_index']} / 连续瞬间 {shot['beat_index']}", "",
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
                "、".join(panel["characters"]),
                panel["scene"], "、".join(panel["props"]), "、".join(panel["effects"]),
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
        writer.writerow([
            "场景编号", "页码", "镜头编号", "全局拍点编号", "角色", "场景", "道具", "特效", "景别", "机位", "运镜",
            "动作", "表演", "对白", "声音", "时长(秒)", "开始状态", "结束状态", "SD25模式",
            "分镜图片提示词", "运镜提示词", "SD25可提交提示词", "分镜计划指纹", "契约指纹",
        ])
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
                f"<h3>场景 {int(shot['scene_number'])} / 第{int(shot['page_number'])}页 / "
                f"镜头 {int(shot['panel_index'])}</h3>"
                f"<p><strong>模式：</strong>{html.escape(str(shot['sd25_mode']))}</p>"
                f"<pre>{html.escape(str(shot['sd25_prompt']))}</pre>"
                f"<small>分镜计划指纹：{html.escape(str(shot['director_plan_fingerprint']))}</small><br>"
                f"<small>契约指纹：{html.escape(str(shot['contract_fingerprint']))}</small>"
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
            f"<title>{title} - AI视频提示词</title><style>"
            "body{font-family:system-ui,sans-serif;max-width:1100px;margin:auto;padding:24px;background:#f6f7f9;color:#18202a}"
            "article{background:white;border:1px solid #dce1e7;border-radius:10px;padding:16px;margin:12px 0}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f7;padding:12px;border-radius:6px}"
            "small{overflow-wrap:anywhere}</style></head><body>"
            f"<h1>{title}</h1><p>场景数：{len(screenplay['scenes'])}；"
            f"预估时长：{float(screenplay['total_duration_seconds']):g} 秒</p>"
            f"<h2>角色五视图</h2>{character_cards}<h2>镜头提示词</h2>{''.join(cards)}"
            "</body></html>"
        )

    def _render_xlsx(self, payload: dict[str, object]) -> bytes:
        headers = [
            "场景编号", "页码", "镜头编号", "全局拍点编号", "角色", "场景", "道具", "特效", "景别", "机位", "运镜",
            "动作", "表演", "对白", "声音", "时长(秒)", "开始状态", "结束状态", "SD25模式",
            "分镜图片提示词", "运镜提示词", "SD25可提交提示词", "分镜计划指纹", "契约指纹",
        ]
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
        workbook = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="分镜提示词" sheetId="1" r:id="rId1"/></sheets></workbook>'
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
