# -*- coding: utf-8 -*-
import logging
import uuid
import asyncio
import contextlib
import json
import re
import os
import hashlib
import threading
from pathlib import Path
import time
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional, List, Tuple

from app import settings
from app.repository.task_repo import StaleTaskWriteError, TaskRepository
from app.core.model_gateway import ModelGateway
from app.core import usage_ledger, video_jobs
from app.core.providers.pricing import pricing_table
from app.core.video_admission import assess_video_batch
from app.core.subtitles import episode_cues, render_srt
from app.core import asset_identity
from app.core.screenwriting.speech import is_narrator, narration_delivery
from app.core.providers.defaults import GATEWAY_DEFAULT_MODELS
from app.core import media_compositor
from app.core.storyboard_assets import complete_actor_sheet_cells, compose_nine_grid, split_actor_sheet
from app.core.storyboard_assets import _open_image as storyboard_assets_open_image, _save_cell as save_actor_cell
from app.core.actor_detail_fill import detail_fill_enabled, fillable, generate_detail_cells
from app.core.actor_hd_views import generate_hd_views, hd_identity_views_enabled
from app.core.storyboard_quality import build_nine_grid_prompt, validate_storyboard_continuity
from app.core.shot_motion_contract import (
    ShotMotionContract,
    assert_prompt_pair_consistent,
    compile_motion_prompt,
    compile_storyboard_image_prompt,
)
from app.core.continuity import ContinuityState, plan_transition
from app.core.actor_sheet_layout import ACTOR_SHEET_CELL_ORDER, actor_sheet_cell_paths
from app.core.image_quality import validate_actor_sheet_images
from app.core.video_quality import VideoQualityMeasurements, evaluate_video_quality
from app.core.emotion_table import read_emotion
from app.core.video_references import (
    renumber_reference_mentions,
    VideoGenerationIntent,
    MIN_SHOT_SECONDS,
    max_shot_seconds,
    normalize_video_provider,
    normalize_video_reference_mode,
    plan_video_references,
    split_shot_seconds,
)
from app.core.agent_council import AgentCouncilCompiler, compile_negative_prompt
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt
from app.core.workflow_prompts import STORYBOARD_SCRIPT_PROMPT
from app.core.workflow_guide import (
    append_stage_guidance,
    assistant_intent,
    build_workflow_snapshot,
    find_chat_message,
    stage_event_id,
)
from app.core.storyboard_prompt_detail import compile_storyboard_prompt_detail
from app.core.asset_mentions import resolve_mentions
from app.core.storyboard_scene_context import compile_scene_context, merge_video_references, panel_context, video_reference_entries
from app.core.camera_recipes import compose_recipe, recipe_catalog
from app.core.shot_seeds import assign_scene_seeds, candidate_seed
from app.core.camera_motion import (
    duration_options as shot_duration_options,
    normalize_camera_motion,
    normalize_shot_type,
    render_camera_motion,
    vocabulary as camera_vocabulary,
)
from app.core.element_library_reuse import find_library_characters
from app.core.project_asset_completion import complete_project_assets, evaluate_project_assets
from app.core import fight_design
from app.core.production_asset_readiness import READINESS_KEY, readiness_reasons
from app.core.storyboard_element_context import load_storyboard_elements
from app.core.storyboard_concurrency import (
    character_sheet_concurrency,
    map_character_sheets,
    map_script_analysis,
    map_storyboard_images,
)
from app.core.continuity_audit import (
    aggregate_scene_boards, audit_markdown, audit_prompt_detail, gate_reasons,
)
from app.core.shot_design_skill import (
    load_shot_design_skill,
    section_budgets as shot_design_section_budgets,
    DEFAULT_CORE_BUDGET,
    DEFAULT_SECTION_BUDGET,
)
from app.core.shot_table_rules import audit_and_log, speakers_in
from app.core.writer_dashboard import (
    version_summaries,
    compile_writer_dashboard,
    episode_from_scene_id,
    episode_label_number,
    episode_target,
    fallback_scenes_from_script,
    parse_duration_seconds,
    reconcile_breakdown_scenes,
    script_episode_gaps,
    script_episode_indexes,
    split_script_by_episode,
)
from app.core.element_scope import normalized_asset_name
from app.core.character_dashboard import (
    REGENERATION_KEY,
    compile_character_dashboard,
    regenerating as character_regenerating,
)
from app.core.episode_shape import configured_episode_shape
# production-knowledge-master 技能装载器：16 份根部知识源按章节键读取(唯一事实源，绝不复制正文)；
# knowledge_evolution 是质检报告→生产教训的进化引擎，全程 fail-soft 旁路。
from app.core.knowledge_registry import section_title
from app.core.production_knowledge import load_section, stage_lessons_block
from app.platform.runtime_models import runtime_model_registry
from app.core.sd25_skill_bundle import BUNDLED_SKILLS_DIR, skill_registry_roots
from app.core import knowledge_evolution
from app.schema.drama import (
    DEFAULT_DIRECTOR_STYLE,
    DEFAULT_EPISODE_COUNT,
    EPISODE_COUNT_MAX,
    EPISODE_COUNT_MIN,
    DramaCreateRequest,
)
from app.schema.production import (
    IDENTITY_VIEW_ORDER,
    LEGACY_IDENTITY_VIEW_ORDER,
    NineGridStoryboard,
    StoryAssetCatalog,
    StoryboardPanel,
)
from app.schema.agent_council import AgentRole, CouncilCompileRequest, CouncilReleaseEvidence
from app.schema.writer_dashboard import WriterDashboardResponse
from app.schema.screenwriting import (
    LedgerOperationRequest,
    ReplanAdoptRequest,
    ScreenwritingEpisodeResponse,
    ScreenwritingStateResponse,
)
from app.core.screenwriting.editing import apply_plan_operations
from app.core import bgm_library, creation_modes, edit_timeline, embedded_agent, generation_queue, style_analysis
from app.export import jianying
from app.core.screenwriting import ledger_ops, review
from app.core.screenwriting.engine import RepairNotImproved
from app.core.screenwriting.engine import ScreenwritingError
from app.core.screenwriting.renderer import render_breakdown
from app.service import screenwriting_service as screenwriting
from app.service import director_desk_service as director_desk
from app.service import spatial_stage_service as spatial_stage
from app.core.spatial_stage.prompting import table_brief as spatial_table_brief
from app.core.spatial_stage import interchange as spatial_interchange
from app.core import (
    asset_sheets,
    generation_feedback,
    genre_clusters,
    h3_sound_design,
    prompt_packages,
    shot_transitions,
    style_packs,
)
from app.schema.character_dashboard import CharacterDashboardResponse


class ScriptUpdateConflictError(RuntimeError):
    """The screenplay changed or has active derivatives that require confirmation."""


class ScriptUpdateTaskNotFoundError(LookupError):
    """The task is missing or does not belong to the editor."""


class StagePrerequisiteError(ValueError):
    """A later production stage was requested before its input contract was complete."""


class _ClaimedStageExecutionError(RuntimeError):
    """Carry the revision actually claimed by the worker with its provider failure."""

    def __init__(self, claimed_revision: int, cause: Exception) -> None:
        super().__init__(str(cause))
        self.claimed_revision = claimed_revision
        self.cause = cause


logger = logging.getLogger("app.service.drama_service")

_LOG_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|xi-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret)\b"
    r"\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+"
)
_LOG_BARE_SECRET = re.compile(r"(?i)\b(?:sk|ark)[_-][A-Za-z0-9_-]{16,}\b")
_SCRIPT_ARCHIVE_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_SCRIPT_ARCHIVE_MAX_ENTRIES = 256


def _task_script_revision(task: object) -> int:
    if not isinstance(task, dict):
        return 0
    try:
        return max(0, int(task.get("script_revision", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_episode_count(value: object) -> int:
    return max(EPISODE_COUNT_MIN, min(EPISODE_COUNT_MAX, int(value or DEFAULT_EPISODE_COUNT)))


def _bounded_shot_duration(value: object, default: float = 2.0) -> float:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    parsed = float(match.group()) if match else default
    return max(0.5, min(15.0, parsed))


def _safe_skill_name(value: str) -> str:
    name = re.sub(r"[^\w.-]+", "-", value or "", flags=re.UNICODE).strip(".-")
    if not name or not re.fullmatch(r"[\w.-]{1,120}", name, flags=re.UNICODE):
        raise ValueError("Skill 名称无效")
    return name

def extract_character_info(director_outline: str) -> tuple:
    """
    辅助方法：从导演策划大纲中自动提取角色名字与视觉描述
    """
    # 大纲没写外观时保持为空：凭空补一套服装会被写进每一张分镜图，古装、仙侠、动画项目都会穿帮
    char1_name = "主角"
    char1_desc = ""
    char2_name = "反派"
    char2_desc = ""
    
    if not director_outline:
        return char1_name, char1_desc, char2_name, char2_desc
        
    # 非角色名黑名单：导演大纲/角色卡里大量加粗项是“元信息/属性标签/结构条目”而非人物名，
    # 必须过滤，否则会把 导演备注/画面/台词/题材/核心冲突/三幕结构/面部/发型… 误当成角色名，
    # 进而污染下游：给非角色生成五视图、配音性别误判、镜头提示词张冠李戴。
    NON_CHARACTER_LABELS = (
        "题材", "平台", "卖点", "爽点", "虐点", "笑点", "hook", "钩子", "冲突", "结构",
        "三幕", "开端", "发展", "高潮", "结局", "主旋律", "节奏", "时长", "导演", "备注",
        "画面", "台词", "对白", "声音", "景别", "运镜", "机位", "面部", "发型", "体型",
        "服饰", "服装", "表情", "眼神", "五维", "dna", "场景", "环境", "调度", "目标",
        "定位", "大纲", "概要", "概述", "说明", "维度", "want", "need", "核心", "角色",
    )

    def _is_character_name(name: str) -> bool:
        n = (name or "").strip().strip("：:　 ")
        # 人物名：2-8 字、含中文、且不命中任何元信息/属性标签
        if not n or len(n) < 2 or len(n) > 8 or not re.search(r'[一-龥]', n):
            return False
        return not any(lbl in n.lower() for lbl in NON_CHARACTER_LABELS)

    parsed_chars = []

    # 1) 优先用“角色身份标签 + 人名”显式头匹配（最可靠，兼容总导演大纲与角色卡 DNA 写法）：
    #    如「核心角色：顾沉渊」「对手角色：林婉儿」「主角 顾沉渊」「反派(对手)：王霸天」
    header_pat = re.compile(
        r'(?:核心角色|主角|男主|女主|对手角色|反派对手|反派|男配|女配|大反派|对手)'
        r'[^\n：:（）()]{0,6}[：:]\s*([一-龥·]{2,8})'
    )
    for m in header_pat.finditer(director_outline):
        nm = m.group(1).strip("：:　 ")
        if _is_character_name(nm) and nm not in [c[0] for c in parsed_chars]:
            parsed_chars.append((nm, ""))

    # 2) 回退：扫描加粗项目符号「- **名字**：描述」，但用黑名单过滤掉元信息/属性标签
    if len(parsed_chars) < 2:
        char_blocks = re.findall(r'-\s*\*\*([^*]+)\*\*：?\s*\n?(.*?)(?=-\s*\*\*|\n\n|###|$)', director_outline, re.DOTALL)
        for name, body in char_blocks:
            name = name.strip().strip("：:　 ")
            if not _is_character_name(name) or name in [c[0] for c in parsed_chars]:
                continue
            desc_match = re.search(r'特征描述：([^\n]+)', body)
            desc = desc_match.group(1).strip() if desc_match else body.strip()
            parsed_chars.append((name, desc))

    if len(parsed_chars) >= 2:
        char1_name, char1_desc = parsed_chars[0][0], (parsed_chars[0][1] or char1_desc)
        char2_name, char2_desc = parsed_chars[1][0], (parsed_chars[1][1] or char2_desc)
    elif len(parsed_chars) == 1:
        char1_name, char1_desc = parsed_chars[0][0], (parsed_chars[0][1] or char1_desc)

    return char1_name, char1_desc, char2_name, char2_desc

def _character_clause(name: str, description: str) -> str:
    """One character's mention in an image prompt; the look is added only when the script gave one."""
    clause = f", featuring character {name}"
    return f"{clause} who is: {description}" if description else clause


def extract_speech(script: str) -> str:
    """
    辅助方法：从编剧对白脚本中动态提取主要台词；剧本没有对白时返回空串，不替它编一句
    """
    if not script:
        return ""
    lines = re.findall(r'[\u4e00-\u9fa5\w]+\s*：\s*([^\n]+)', script)
    if lines:
        for line in lines:
            cleaned = line.strip()
            if len(cleaned) > 5 and "环境" not in cleaned and "调度" not in cleaned:
                return cleaned
        return lines[0].strip()
    return ""

_CHARACTER_ROLE_LABELS = (
    "核心角色", "对手角色", "反派对手", "大反派", "男配角", "女配角",
    "主角", "男主", "女主", "反派", "男配", "女配", "配角", "角色卡", "角色",
)
_CHARACTER_NAME_RESERVED = {
    "主角", "男主", "女主", "反派", "对手", "配角", "男配", "女配", "核心角色", "对手角色",
    "角色", "角色卡", "角色档案", "角色设定", "角色设计", "角色方案", "角色清单",
    "角色总表", "人物总表", "总表", "清单", "列表", "章节标题", "人物关系", "五视图",
}
_CHARACTER_NAME_METADATA = (
    "总表", "目录", "章节", "标题", "清单", "列表", "方案", "设计", "设定", "档案", "卡片", "UID",
)
_CHARACTER_NAME_PATTERN = r"[㐀-鿿][㐀-鿿·]{1,7}"
_CHARACTER_ROLE_PATTERN = "|".join(re.escape(label) for label in _CHARACTER_ROLE_LABELS)


def _valid_character_name(value: object) -> Optional[str]:
    """只接受可作为制作资产键的真实中文角色名。"""
    name = str(value or "").strip().strip("·：:|｜ ")
    if not re.fullmatch(_CHARACTER_NAME_PATTERN, name):
        return None
    if name in _CHARACTER_NAME_RESERVED or any(token in name.upper() for token in _CHARACTER_NAME_METADATA):
        return None
    return name


def _canonical_character_role(value: str) -> str:
    role = (value or "").strip()
    if role in {"核心角色", "主角", "男主", "女主"}:
        return "主角"
    if role in {"对手角色", "反派对手", "大反派", "反派"}:
        return "反派"
    return "配角"


def _character_card_header(line: str) -> Optional[tuple[str, str, int]]:
    """识别严格锚定的角色卡标题，拒绝表格、章节名和类型标签。"""
    raw = (line or "").strip()
    if not raw or raw.startswith("|"):
        return None
    heading = re.match(r"^#{1,6}\s+", raw)
    heading_level = len(heading.group(0).split()[0]) if heading else 0
    whole_bold = bool(re.fullmatch(r"(?:[-*+]\s*)?\*\*.+\*\*\s*", raw))
    plain_role = bool(re.match(rf"^(?:[-*+]\s*)?(?:\*\*)?(?:{_CHARACTER_ROLE_PATTERN})", raw))
    if not (heading or whole_bold or plain_role):
        return None

    title = raw[heading.end():] if heading else raw
    title = re.sub(r"^[-*+]\s+", "", title).strip().replace("**", "")
    direct = re.fullmatch(
        rf"[^㐀-鿿]{{0,20}}(?P<role>{_CHARACTER_ROLE_PATTERN})"
        rf"\s*(?:[（(][^）)\n]{{0,16}}[）)])?\s*[:：|｜]\s*"
        rf"(?P<name>{_CHARACTER_NAME_PATTERN})(?:\s*[（(][^）)\n]{{0,80}}[）)])?\s*",
        title,
    )
    if not direct:
        direct = re.fullmatch(
            rf"[^㐀-鿿]{{0,20}}角色卡\s*[|｜]\s*(?P<role>{_CHARACTER_ROLE_PATTERN})"
            rf"\s*[|｜]\s*(?P<name>{_CHARACTER_NAME_PATTERN})\s*",
            title,
        )
    if not direct:
        return None
    name = _valid_character_name(direct.group("name"))
    if not name:
        return None
    return _canonical_character_role(direct.group("role")), name, heading_level


def _parse_character_cards(res: str) -> "OrderedDict[str, dict]":
    cards: "OrderedDict[str, dict]" = OrderedDict()
    current: Optional[str] = None
    current_heading_level = 0
    for line in (res or "").splitlines():
        header = _character_card_header(line)
        if header:
            role, name, current_heading_level = header
            cards.setdefault(name, {"role": role, "description": ""})
            current = name
            continue
        heading = re.match(r"^\s*(#{1,6})\s+", line)
        if heading and current and current_heading_level and len(heading.group(1)) <= current_heading_level:
            current = None
            current_heading_level = 0
            continue
        if current and line.strip():
            cards[current]["description"] += line.strip() + "\n"
    return cards


def parse_characters(res: str, fallback_chars: dict) -> dict:
    """解析主角/反派卡片；只信任严格锚定的角色卡标题。"""
    cards = _parse_character_cards(res)
    by_role: dict[str, tuple[str, dict]] = {}
    for name, card in cards.items():
        by_role.setdefault(card["role"], (name, card))
    ordered = list(cards.items())
    protagonist = by_role.get("主角") or (ordered[0] if ordered else None)
    antagonist = by_role.get("反派")
    if antagonist is None:
        antagonist = next((item for item in ordered if not protagonist or item[0] != protagonist[0]), None)
    result = dict(fallback_chars)
    if protagonist:
        result["主角"] = f"**{protagonist[0]}**:\n" + protagonist[1]["description"].strip()
    if antagonist:
        result["反派"] = f"**{antagonist[0]}**:\n" + antagonist[1]["description"].strip()
    return result

def parse_all_characters(res: str) -> "OrderedDict":
    """提取全部严格锚定的角色卡，并按文档出现顺序返回。"""
    return OrderedDict(
        (name, card["description"].strip())
        for name, card in _parse_character_cards(res).items()
    )


def parse_storyboard_table(markdown_table: str, fallback_shots: list) -> list:
    """
    辅助方法：将分镜师输出的 Markdown 分镜表格自动解析为 structured 镜头对象列表
    """
    def _clean_cell(text: str) -> str:
        # 清洗真实 LLM 单元格里的 Markdown 修饰：去 **加粗**、<br> 换行、多余空白
        text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
        text = text.replace('**', '').replace('*', '')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    shots = []
    lines = markdown_table.strip().split('\n')
    for line in lines:
        if '|' in line:
            # 兼容两种 Markdown 表格写法：有首尾竖线 (| a | b |) 与无首尾竖线 (a | b)。
            # 仅去掉因首尾竖线产生的空单元格，避免误删第一列(镜号)与最后一列(叙事目的)。
            parts = [p.strip() for p in line.split('|')]
            if parts and parts[0] == '':
                parts = parts[1:]
            if parts and parts[-1] == '':
                parts = parts[:-1]
            if not parts or len(parts) < 2:
                continue
            # 跳过分隔行 (支持 ---、:---、:---: 等带冒号写法)
            if all(re.match(r'^:?-{2,}:?$', p) for p in parts if p):
                continue
            p0 = parts[0]
            if re.match(r'^:?-+:?$', p0) or '镜号' in p0 or '镜头' in p0 or '序号' in p0 or 'Shot' in p0:
                continue
            try:
                shot_id_str = re.search(r'\d+', p0)
                shot_id = int(shot_id_str.group()) if shot_id_str else len(shots) + 1

                size = "MS"
                angle = ""
                motion = "Dolly In"
                desc = ""
                dialogue = ""
                sound = ""
                duration = ""
                narrative_purpose = ""
                characters: list[str] = []
                scene_id = ""
                scene = ""
                if len(parts) >= 5:
                    size = _clean_cell(parts[1])
                    angle = _clean_cell(parts[2])
                    motion = _clean_cell(parts[3])
                    desc = _clean_cell(parts[4])
                    if len(parts) >= 6:
                        dialogue = _clean_cell(parts[5])
                    if len(parts) >= 7:
                        sound = _clean_cell(parts[6])
                    if len(parts) >= 8:
                        duration = _clean_cell(parts[7])
                    if len(parts) >= 9:
                        narrative_purpose = _clean_cell(parts[8])
                    if len(parts) >= 10:
                        characters = [
                            item.strip()
                            for item in re.split(r"[，,、/]", _clean_cell(parts[9]))
                            if item.strip()
                        ]
                    if len(parts) >= 11:
                        raw_scene = _clean_cell(parts[10])
                        scene_match = re.match(r"^(E\d+S\d+)\s*[-—:：]?\s*(.*)$", raw_scene, flags=re.I)
                        if scene_match:
                            scene_id = scene_match.group(1).upper()
                            scene = scene_match.group(2).strip() or scene_id
                        else:
                            scene = raw_scene
                else:
                    desc = _clean_cell(" | ".join(parts[1:]))

                shots.append({
                    "shot_id": shot_id,
                    "size": size,
                    "angle": angle,
                    "motion": motion,
                    "desc": desc,
                    "dialogue": dialogue,
                    "sound": sound,
                    "duration": duration,
                    "narrative_purpose": narrative_purpose,
                    "characters": characters,
                    "characters_explicit": len(parts) >= 10,
                    "scene_id": scene_id,
                    "scene": scene,
                })
            except Exception:
                continue
    if not shots:
        return fallback_shots
    return shots

def guess_gender(name: str) -> str:
    """根据角色名/称谓粗略判定性别，用于配音男女声分配。默认女声(female)。"""
    if not name:
        return "female"
    female_kw = ["妃", "后", "母", "妈", "女", "姐", "妹", "娘", "夫人", "小姐", "公主", "皇后", "贵妃",
                 "曼", "雪", "歌", "鸾", "美", "婷", "莉", "姬", "媛", "颜", "妍", "茹", "婉", "兰",
                 "琳", "芳", "燕", "梅", "霜", "月", "若", "嫣", "蓉", "菲", "宝", "甜", "心"]
    male_kw = ["王", "霸", "龙", "帝", "君", "少爷", "总裁", "先生", "公子", "战", "虎", "豹", "雄",
               "刚", "强", "渊", "逸", "霆", "枭", "凡", "尘", "峰", "轩", "天", "豪", "雷", "鹰",
               "向东", "建国", "大少", "爷", "哥", "兄", "父", "叔", "帅", "将", "侯", "皇", "宗"]
    for k in female_kw:
        if k in name:
            return "female"
    for k in male_kw:
        if k in name:
            return "male"
    return "female"


_PARENTHETICAL = re.compile(r"[（(]([^（）()]{1,16})[）)]")


def detect_emotion(text: str, notes: str = "") -> str:
    """判定一句台词 / 一个镜头的情绪，用于配音的情绪与节奏 (对应 media_compositor.EMOTION_PRESETS)。

    明确写下的表演标注优先：``notes``（分镜规划的 delivery、镜头表情）与台词里的括注
    「（冷笑）」按情绪表读取，具体词先于泛化词（冷笑不会被读成笑）；都没有时才按台词
    内容的关键词粗略猜测。台词正文里出现的情绪词（「你别生气」）不作数。
    """
    t = text or ""
    explicit = " ".join([str(notes or ""), *_PARENTHETICAL.findall(t)]).strip()
    if explicit:
        reading = read_emotion(explicit)
        if reading.matched:
            return reading.voice
    if any(k in t for k in ["滚", "废物", "凭什么", "怎么敢", "给我", "住手", "！！", "可恶", "混蛋", "放肆", "找死"]):
        return "shout" if t.count("！") >= 2 else "angry"
    if any(k in t for k in ["求求", "对不起", "别走", "别这样", "呜", "泪", "我错了", "求你", "好痛", "救我", "没用了"]):
        return "sad"
    if any(k in t for k in ["不过是", "也配", "呵", "哼", "可笑", "天真", "幼稚", "区区", "就凭你", "螳臂"]):
        return "cold"
    if any(k in t for k in ["快", "危险", "小心", "来不及", "糟了", "快走", "追", "拦住"]):
        return "tense"
    if any(k in t for k in ["哈哈", "太好了", "终于", "赢了", "成功", "真棒", "开心"]):
        return "happy"
    if any(k in t for k in ["我爱你", "想你", "陪着你", "别怕", "有我在", "傻瓜", "宝贝"]):
        return "tender"
    return "neutral"


def dialogue_delivery_profile(text: str, emotion: str) -> dict:
    """Compile observable voice direction without changing the verbatim line."""
    profiles = {
        "neutral": (285, 1.00, "句间0.3-0.5秒，长句中段保留一次自然换气", "语义关键词"),
        "angry": (330, 1.10, "短促碎停顿，命中重音后立即收束", "指责或权力词"),
        "shout": (350, 1.15, "少停顿，爆发后保留0.3秒呼气尾巴", "爆发词"),
        "cold": (235, 0.92, "关键词前停半拍，句尾不拖腔", "威胁或否定词"),
        "sad": (210, 0.86, "句中0.2秒换气，句尾0.4-0.6秒留白", "失去或请求词"),
        "tense": (325, 1.08, "不规则0.15-0.25秒碎停顿", "危险与行动词"),
        "happy": (315, 1.05, "轻快短停顿，音高有自然起伏", "结果与称赞词"),
        "tender": (245, 0.94, "轻柔换气，关键词后停0.2秒", "称呼与承诺词"),
    }
    cpm, speed, pause, stress = profiles.get(emotion, profiles["neutral"])
    han_count = len(re.findall(r"[一-龥]", text or ""))
    estimated_seconds = round(max(0.35, han_count / max(1, cpm) * 60), 3)
    return {
        "verbatim_text": text,
        "emotion": emotion,
        "emotion_intensity": "high" if emotion in {"shout", "angry"} else "medium",
        "characters_per_minute": cpm,
        "speed": speed,
        "pause": pause,
        "stress": stress,
        "breath": "起句前自然吸气；句末闭口0.2秒并保留呼气",
        "estimated_seconds": estimated_seconds,
        "max_15_han_characters_passed": han_count <= 15,
    }


# 记录用户导入的 Skill 的清单文件，位于 skills 目录下
IMPORTED_SKILL_REGISTRY = "registry.json"

# 早期版本写进任务的占位视频所在域名；回退选片时据此跳过，只取真实生成的片段
LEGACY_PLACEHOLDER_MEDIA_HOST = "volccdn.com"

# 非角色发声体，配音时跳过 (不为音效/旁白标记等生成人声)
SKIP_SPEAKERS = ("音效", "环境音", "背景音", "特效音", "音乐", "声音", "bgm", "ost")


def parse_shot_dialogue(cell: str, char1_name: str, char2_name: str,
                        char1_gender: str, char2_gender: str, *, voice_narration: bool = True) -> list:
    """
    把一个镜头的台词单元格解析为 [(台词, 性别, 情绪)]，供逐句情绪配音。
    步骤5(预览音轨)与步骤6(成片配音)共用，避免解析逻辑重复发散。
    ``voice_narration`` 为假时跳过旁白（项目把旁白留给后期配音）。
    """
    out = []
    cell = (cell or "").strip()
    if not cell:
        return out
    pairs = re.findall(r'([一-龥A-Za-z][一-龥A-Za-z·]{0,7})[：:]\s*([^：:]+?)(?=(?:[一-龥A-Za-z][一-龥A-Za-z·]{0,7}[：:])|$)', cell)
    if pairs:
        for speaker, line in pairs:
            line = line.strip().strip('“”"\'（）()')
            if not line or len(re.findall(r'[一-龥]', line)) < 1:
                continue
            if any(k in speaker.lower() for k in SKIP_SPEAKERS):
                continue
            if is_narrator(speaker) and not voice_narration:
                continue
            if char1_name and char1_name in speaker:
                g = char1_gender
            elif char2_name and char2_name in speaker:
                g = char2_gender
            elif is_narrator(speaker):
                g = "female"
            else:
                g = guess_gender(speaker)
            out.append((line, g, detect_emotion(line), speaker))
    else:
        clean = re.sub(r'[^：:]{1,8}[：:]', '', cell).strip().strip('“”"\'（）()')
        if len(re.findall(r'[一-龥]', clean)) >= 1:
            out.append((clean, char1_gender, detect_emotion(clean), char1_name or "主角"))
    return out


def extract_json_object(text: str) -> Optional[dict]:
    """从 LLM 输出中提取第一个 JSON 对象：优先 ```json 代码块，其次首个 { 到末尾 } 的片段。"""
    if not text or not text.strip():
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fence:
        candidates.append(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            continue
    return None


def split_episodes(script: str, *, max_episodes: int = 200) -> list:
    """
    将编剧输出的完整分集剧本按「第N集 / 第N幕 / Episode N」切分为多集。
    返回 [{"index":1, "title":"...", "script":"..."}, ...]；无法切分时整体作为 1 集。
    """
    if not script or not script.strip():
        return []
    # 匹配集数标题行
    pattern = re.compile(r'(?:^|\n)\s*(?:#+\s*)?(?:【?\s*)?(?:第\s*([0-9一二三四五六七八九十]+)\s*集|Episode\s*([0-9]+)|第\s*([0-9一二三四五六七八九十]+)\s*幕)[^\n]*', re.IGNORECASE)
    marks = []
    for match in pattern.finditer(script):
        marks.append(match)
        if len(marks) >= max(1, min(200, max_episodes)):
            break
    episodes = []
    if marks:
        for i, m in enumerate(marks):
            start = m.start()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(script)
            seg = script[start:end].strip()
            title_line = seg.split('\n', 1)[0].strip(' #【】*')
            title = re.sub(
                r"^(?:第\s*[0-9一二三四五六七八九十]+\s*(?:集|幕)|Episode\s*[0-9]+)\s*[】]?[：:\-—]?\s*",
                "",
                title_line,
                flags=re.IGNORECASE,
            ).strip()
            episodes.append({
                "index": i + 1,
                "title": (title or f"第{i + 1}集")[:40],
                "script": seg,
            })
    else:
        episodes.append({"index": 1, "title": "第1集", "script": script.strip()})
    return episodes


_PLANNED_COMPOSITOR_TRANSITIONS = frozenset({"hard_cut", "match_cut", "crossfade", "dip_to_black"})


def final_cut_transitions(shots: list) -> tuple[list, list]:
    """``(transition specs, reports)`` for the cuts between consecutive clips of the final film.

    The continuity gate judges every cut first and stops the film on one it rejects (a crossed
    axis does not pass because the cut became a dissolve). A cut the stage-4 cut plan designed
    (hard cut / match cut / dissolve / fade) is then composed that way; otherwise the gate's own
    choice is used.
    """
    specs: list = []
    reports: list = []
    for previous_shot, current_shot in zip(shots, shots[1:]):
        previous_state = previous_shot.get("continuity_state") if isinstance(previous_shot, dict) else None
        current_state = current_shot.get("continuity_state") if isinstance(current_shot, dict) else None
        if not previous_state or not current_state:
            specs.append({"type": "crossfade", "duration": 0.22})
            reports.append({"accepted": True, "score": 0.75, "reasons": ["缺少旧任务结构化状态，使用保守短叠化。"]})
            continue
        plan = plan_transition(
            ContinuityState.model_validate(previous_state),
            ContinuityState.model_validate(current_state),
        )
        reports.append(plan.model_dump())
        if not plan.accepted:
            raise RuntimeError(
                f"镜头 {previous_shot.get('shot_id')}→{current_shot.get('shot_id')} 连续性质检失败："
                + "；".join(plan.reasons)
            )
        planned = current_shot.get("cut_in") if isinstance(current_shot.get("cut_in"), dict) else None
        if planned and planned.get("compositor") in _PLANNED_COMPOSITOR_TRANSITIONS:
            specs.append({
                "type": planned["compositor"],
                "duration": float(planned.get("duration_seconds") or 0) or plan.duration_seconds,
            })
            reports[-1]["planned_cut"] = planned.get("label")
        else:
            specs.append({"type": plan.video_transition, "duration": plan.duration_seconds})
    return specs, reports


def parse_pr_info(pr_text: str, default_title: str, default_body: str) -> tuple:
    """
    辅助方法：从宣发文案中提取爆款标题与引流正文
    """
    title = default_title
    body = default_body
    if not pr_text:
        return title, body

    def _zh_count(s: str) -> int:
        return len(re.findall(r'[一-龥]', s))

    # 标题：依次尝试 《》书名号 -> 引用块加粗(> **标题**) -> "标题："后正文
    title_match = re.search(r'《([^》\n]+)》', pr_text)
    if not title_match:
        title_match = re.search(r'>\s*\*\*([^*\n]{2,30})\*\*', pr_text)
    if not title_match:
        title_match = re.search(r'(?:封面大字标题|爆款标题|大字标题|标题)[】：:\s]*([^》【\n：#*]{2,30})', pr_text)
    if title_match:
        cand = title_match.group(1).strip(' *>　')
        if cand and _zh_count(cand) >= 2:
            title = cand

    # 正文：引号文案 -> "引流文案/文案："后正文 -> 首条干净广告语；均需含足够中文方采纳
    chosen = None
    m = re.search(r'[‘\'""]\s*([^’\'""]{15,})\s*[’\'""]', pr_text)
    if m:
        chosen = m.group(1).strip()
    if not chosen or _zh_count(chosen) < 8:
        m = re.search(r'(?:黄金引流文案|引流文案|文案内容)[】：:\s]+([^\n#]{12,})', pr_text)
        if m and _zh_count(m.group(1)) >= 8:
            chosen = m.group(1).strip()
    if not chosen or _zh_count(chosen) < 8:
        skip_kw = ('设计', '原则', '策略', '核心逻辑', '针对', '选项', 'Scripts', 'Cover', 'Visual', 'Audio',
                   '我是', '为你', '定制', '方案', '理论', '以下', '你好', 'Agnes', 'gnes')
        for raw in pr_text.split('\n'):
            line = raw.strip().strip('>*　 ')
            if not line or line.startswith(('#', '|', '-', '+')):
                continue
            if re.match(r'^[\d]+[\.、)]', line) or re.match(r'^[一二三四五六七八九十]+、', line):
                continue
            if any(k in line for k in skip_kw):
                continue
            if _zh_count(line) >= 12:
                chosen = re.sub(r'\s+', ' ', line)
                break
    if chosen and _zh_count(chosen) >= 8:
        body = chosen
    return title, body

class _HdDone(Exception):
    """高清身份视图补完：把结果带出 try 块，交给统一的落库逻辑。"""

    def __init__(self, result: Dict[str, Any]):
        super().__init__("hd views done")
        self.result = result


class DramaService:
    """
    AI 短剧 8-Agent 协同与断点状态控制业务服务类 (Service)
    """
    def __init__(self):
        self.repo = TaskRepository()
        self.gateway = ModelGateway()
        self.agent_council = AgentCouncilCompiler()
        # Provider calls made while a project's stage runs are written onto that project.
        usage_ledger.configure_sink(self._record_usage)
        # So are the video jobs the providers accept, so a restart can continue rather than re-pay them.
        video_jobs.configure_sink(self._record_video_job)
        self.script_archive_max_total_bytes = _SCRIPT_ARCHIVE_MAX_TOTAL_BYTES
        self.script_archive_max_entries = _SCRIPT_ARCHIVE_MAX_ENTRIES

    # ---------------- 风格参考图：看图拆出风格锁，确认后成为本片风格 ----------------

    STYLE_REFERENCE_KEY = "style_reference"

    @staticmethod
    def _reference_image_uri(content: bytes, content_type: str) -> str:
        """The image as a data URI a vision model accepts, scaled so its long side is at most 1536 px."""
        import base64
        import io

        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1536, 1536))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    def analyze_style_reference(
        self, task_id: str, *, content: bytes, filename: str, content_type: str, hint: str = "", model: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Read a reference image into a style profile and the lock it would become; nothing is applied yet."""
        import hashlib

        from app.platform.uploads import validate_image_upload

        task = self.repo.get_task(task_id)
        if not task:
            return None
        validate_image_upload(filename, content_type, content)  # UploadValidationError → 422
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        system, user = style_analysis.analysis_prompt(hint)
        with usage_ledger.bind_task(task_id, "style_reference"):
            answer, used = self.gateway.describe_image(
                model or str(config.get("llm_model") or ""), system, user, self._reference_image_uri(content, content_type),
            )
        if not used:
            raise style_analysis.StyleAnalysisError("没有可看图的文本模型：请在模型配置里启用一个标为「多模态」的文本模型")
        if not answer:
            raise style_analysis.StyleAnalysisError(f"模型 {used} 没有返回结果（可能不支持图片输入或请求失败），请稍后重试或换一个多模态模型")
        profile = style_analysis.parse_profile(answer)
        pack = style_analysis.to_pack(profile, task_id=task_id)
        record = {
            **style_analysis.preview(profile, pack),
            "pack_definition": pack.model_dump(mode="json"),
            "model": used, "filename": filename[:160], "sha256": hashlib.sha256(content).hexdigest(),
            "hint": hint[:300], "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "applied": False,
        }
        self.repo.mutate_task(task_id, lambda current: current.setdefault("assets", {}).__setitem__(self.STYLE_REFERENCE_KEY, record))
        return self.get_style_reference(task_id)

    def get_style_reference(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        record = (task.get("assets") or {}).get(self.STYLE_REFERENCE_KEY)
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        current = style_packs.resolve_pack(config)
        return {
            "task_id": task_id,
            "reference": {k: v for k, v in record.items() if k != "pack_definition"} if isinstance(record, dict) else None,
            "current_pack": {"id": current.id, "name": current.name, "custom": current.id.startswith("custom_")},
            "previous_pack": config.get("style_pack_before_reference"),
        }

    def apply_style_reference(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Make the analysed lock this project's style; images already made keep their old look until remade."""
        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            record = (task.get("assets") or {}).get(self.STYLE_REFERENCE_KEY)
            if not isinstance(record, dict) or not isinstance(record.get("pack_definition"), dict):
                raise style_analysis.StyleAnalysisError("还没有分析过风格参考图")
            config = task.setdefault("config", {})
            pack = style_packs.StylePack.model_validate(record["pack_definition"])
            if not str(config.get("style_pack") or "").startswith("custom_"):
                config["style_pack_before_reference"] = style_packs.resolve_pack(config).id
            config["custom_style_pack"] = pack.model_dump(mode="json")
            config["style_pack"] = pack.id
            record["applied"] = True
            style_packs.register_custom(pack)
            return task

        task = self.repo.mutate_task(task_id, mutation)
        if task is None:
            return None
        assets = task.get("assets") or {}
        made = [stage for stage, key in ((3, "3_sheets"), (4, "4"), (5, "5")) if assets.get(key)]
        return {**(self.get_style_reference(task_id) or {}), "stages_with_old_look": made}

    def revert_style_reference(self, task_id: str) -> Optional[Dict[str, Any]]:
        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            config = task.setdefault("config", {})
            if not str(config.get("style_pack") or "").startswith("custom_"):
                raise style_analysis.StyleAnalysisError("本片当前用的不是参考图风格")
            config["style_pack"] = config.pop("style_pack_before_reference", None) or style_packs.DEFAULT_PACK_ID
            config.pop("custom_style_pack", None)
            record = (task.get("assets") or {}).get(self.STYLE_REFERENCE_KEY)
            if isinstance(record, dict):
                record["applied"] = False
            return task

        if self.repo.mutate_task(task_id, mutation) is None:
            return None
        return self.get_style_reference(task_id)

    # ---------------- 剪辑时间线：成片照它剪，剪映草稿照它写 ----------------

    @staticmethod
    def _film_title(title: str) -> str:
        return re.sub(r'^(请帮我?|帮我?)?(生成|制作|来)?(一个|一部)?', '', title or "").strip() or title

    def _current_timeline(self, task: Dict[str, Any], title: str) -> tuple[Dict[str, Any], list]:
        """The project's timeline, built or refreshed against the clips stage 5 holds now."""
        shots = [s for s in (task.get("assets", {}).get("5") or []) if isinstance(s, dict) and s.get("video_url")]
        specs, reports = final_cut_transitions(shots)
        existing = task.get("assets", {}).get(edit_timeline.TIMELINE_KEY)
        if isinstance(existing, dict) and edit_timeline.is_current(existing, task):
            return existing, reports
        if isinstance(existing, dict):
            return edit_timeline.refresh(existing, task, transitions=specs, title=self._film_title(title)), reports
        return edit_timeline.build(task, transitions=specs, title=self._film_title(title)), reports

    def get_timeline(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        timeline, _ = self._current_timeline(task, str(config.get("title_suggestion") or ""))
        if timeline is not task.get("assets", {}).get(edit_timeline.TIMELINE_KEY):
            self.repo.mutate_task(task_id, lambda current: current.setdefault("assets", {}).__setitem__(edit_timeline.TIMELINE_KEY, timeline))
        return self._timeline_response(task_id, timeline)

    @staticmethod
    def _timeline_response(task_id: str, timeline: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task_id, "timeline": timeline, "summary": edit_timeline.summary(timeline),
            "transitions": list(edit_timeline.TRANSITIONS), "bgm_library": [
                {k: v for k, v in track.items() if k != "path"} for track in bgm_library.list_tracks()
            ],
        }

    def edit_timeline(self, task_id: str, operation: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """One edit on the timeline; the film is not re-rendered until asked."""
        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            config = task.get("config") if isinstance(task.get("config"), dict) else {}
            timeline, _ = self._current_timeline(task, str(config.get("title_suggestion") or ""))
            shot_id = payload.get("shot_id")
            if operation == "trim":
                timeline = edit_timeline.trim(timeline, shot_id, start=float(payload.get("start") or 0), end=payload.get("end"))
            elif operation == "transition":
                timeline = edit_timeline.set_transition(timeline, shot_id, kind=str(payload.get("kind") or "crossfade"), duration=float(payload.get("duration") or 0.22))
            elif operation == "subtitle":
                timeline = edit_timeline.set_subtitle(timeline, shot_id, str(payload.get("text") or ""))
            elif operation == "mute":
                timeline = edit_timeline.set_muted(timeline, shot_id, bool(payload.get("muted")))
            elif operation == "candidate":
                timeline = edit_timeline.choose_candidate(timeline, shot_id, str(payload.get("video_url") or ""))
            elif operation == "review":
                timeline = edit_timeline.review(timeline, shot_id, decision=str(payload.get("decision") or "pending"), note=str(payload.get("note") or ""))
            elif operation == "title":
                timeline = edit_timeline.set_title(timeline, payload.get("text"))
            elif operation == "bgm":
                source = str(payload.get("source") or "none")
                track = None
                if source == "library":
                    track = bgm_library.get_track(str(payload.get("library_id") or ""))
                    if not track:
                        raise edit_timeline.TimelineError("配乐库里没有这条音乐")
                audio = task.get("assets", {}).get("6") if isinstance(task.get("assets", {}).get("6"), dict) else {}
                timeline = edit_timeline.set_bgm(
                    timeline, source=source,
                    path=track["path"] if track else (audio.get("bgm_path") if source == "generated" else None),
                    url=f"/api/library/bgm/{track['id']}/audio" if track else (audio.get("bgm_url") if source == "generated" else None),
                    library_id=track["id"] if track else None, name=track["name"] if track else ("阶段 6 生成" if source == "generated" else None),
                    volume=payload.get("volume"), duck=payload.get("duck"),
                )
            else:
                raise edit_timeline.TimelineError(f"未知的时间线操作：{operation}")
            task.setdefault("assets", {})[edit_timeline.TIMELINE_KEY] = timeline
            return task

        updated = self.repo.mutate_task(task_id, mutation)
        if updated is None:
            return None
        return self._timeline_response(task_id, updated["assets"][edit_timeline.TIMELINE_KEY])

    def render_timeline(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Re-render the film from the timeline as it is now; stage 7's record is updated in place."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待结束后再合成")
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        timeline, reports = self._current_timeline(task, str(config.get("title_suggestion") or ""))
        plan = edit_timeline.render_plan(timeline)
        if not plan["shot_video_urls"]:
            raise ValueError("时间线上没有可用的镜头片段（都被打回或尚未生成）")
        composed = media_compositor.compose_film(
            plan["shot_video_urls"], plan["subtitles"], plan["audio_path"], tag=f"film_{task_id[:8]}", title=plan["title"], bgm=plan["bgm"],
            shot_voices=plan["shot_voices"] if any(plan["shot_voices"]) else None, bgm_path=plan["bgm_path"], sfx_path=plan["sfx_path"],
            transition_plans=plan["transition_plans"], trims=plan["trims"], bgm_volume=plan["bgm_volume"],
        )
        if not composed:
            raise ValueError("成片合成失败（缺 ffmpeg 或片段不可用）")

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            current.setdefault("assets", {})[edit_timeline.TIMELINE_KEY] = timeline
            record = current["assets"].get("7") if isinstance(current["assets"].get("7"), dict) else {}
            record.update({
                "final_video_url": composed, "shot_clips": plan["shot_video_urls"], "transition_quality": reports,
                "timeline_revision": timeline.get("revision"), "timeline_summary": edit_timeline.summary(timeline),
                "compose_mode": "按剪辑时间线重新合成", "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            current["assets"]["7"] = record
            current["video_url"] = composed
            return current

        self.repo.mutate_task(task_id, mutation)
        return {"task_id": task_id, "final_video_url": composed, "summary": edit_timeline.summary(timeline)}

    def jianying_draft(self, task_id: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """The timeline as a JianYing draft folder, zipped with its media."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        timeline, _ = self._current_timeline(task, str(config.get("title_suggestion") or ""))
        name = self._film_title(str(config.get("title_suggestion") or "")) or f"short-drama-{task_id[:8]}"
        draft = jianying.build_draft(timeline, name=name, resolve_local=media_compositor._local_media_source)
        folder = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name)[:40] or f"draft_{task_id[:8]}"
        return jianying.pack(draft, folder_name=folder), {"name": name, "skipped": draft["skipped"], "duration_seconds": draft["duration_seconds"], "files": len(draft["files"])}

    # ---------------- 生成队列：排队中的可取消，运行中的让它跑完 ----------------

    def get_generation_queue(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        snapshot = generation_queue.snapshot_of(task) or {"items": [], "counts": {}, "buckets": {}, "run_id": None, "updated_at": None}
        running = task.get("status") == "running" and int((task.get("stage_progress") or {}).get("stage") or 0) == 5
        return {"task_id": task_id, "running": running, **snapshot}

    def cancel_generation_item(self, task_id: str, key: Optional[str]) -> Optional[Dict[str, Any]]:
        """Withdraw one queued item (or every queued one when ``key`` is None); running items keep going."""
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            return generation_queue.request_cancel(task, key) if key else generation_queue.request_cancel_queued(task)

        if self.repo.mutate_task(task_id, mutate) is None:
            return None
        return self.get_generation_queue(task_id)

    def reconcile_generation_queues(self) -> Dict[str, int]:
        """After a restart: items a dead process left running go back to queued unless a provider job still holds them."""
        requeued = 0
        for task in self.repo.list_all_tasks():
            if not generation_queue.snapshot_of(task):
                continue
            keys = self.repo.mutate_task(task["task_id"], generation_queue.reconcile_after_restart) or []
            requeued += len(keys)
        return {"requeued": requeued}

    def _record_video_job(self, task_id: str, entry: Dict[str, Any]) -> None:
        self.repo.mutate_task(task_id, lambda task: video_jobs.apply_to_task(task, entry))

    def resume_interrupted_video_jobs(self) -> Dict[str, int]:
        """After a restart: finish polling every accepted video job, recording its clip or its failure.

        Nothing is re-submitted. A job whose provider cannot be asked again is marked
        failed with the reason, so the next stage-5 run generates that shot afresh.
        """
        resumed = {"downloaded": 0, "failed": 0}
        for task in self.repo.list_all_tasks():
            if not isinstance(task, dict) or not task.get("task_id"):
                continue
            for job in video_jobs.pending_jobs(task):
                outcome = video_jobs.resume_outcome(job, self.gateway.resume_video_job)
                self.repo.mutate_task(task["task_id"], lambda current, outcome=outcome: video_jobs.apply_to_task(current, outcome))
                resumed["downloaded" if outcome["status"] == video_jobs.DOWNLOADED else "failed"] += 1
                logger.info("[VideoJobs] 续查 task=%s key=%s -> %s %s", task["task_id"], job.get("key"), outcome["status"], outcome.get("error") or "")
        return resumed

    def _record_usage(self, task_id: str, entry: Dict[str, Any]) -> None:
        self.repo.mutate_task(task_id, lambda task: usage_ledger.append_to_task(task, entry))

    def change_asset_identity(
        self, task_id: str, *, operation: str, kind: str, name: str, new_name: str, dry_run: bool,
        owner_user_id: Optional[str] = None, is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Rename or merge an asset across the script plan, breakdown, sheets and shots; dry runs only count."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        preview = asset_identity.preview_merge if operation == "merge" else asset_identity.preview_rename
        if dry_run:
            return preview(task, kind, name, new_name).as_dict()
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待结束后再改资产名")
        apply = asset_identity.merge_assets if operation == "merge" else asset_identity.rename_asset
        holder: Dict[str, Any] = {}

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            holder["impact"] = apply(current, kind, name, new_name)
            current_assets = current.setdefault("assets", {})
            if screenwriting.state_of(current) is not None:
                # References moved; the text and breakdown the rest of the pipeline reads are re-projected.
                screenwriting.apply_state(current_assets, screenwriting.state_of(current))
            current_assets["2_writer_dashboard"] = compile_writer_dashboard(current).model_dump(mode="json", by_alias=True)
            if current_assets.get("3_characters") is not None or current_assets.get("3_sheets"):
                current_assets["3_character_dashboard"] = compile_character_dashboard(current).model_dump(mode="json", by_alias=True)
            return current

        self.repo.mutate_task(task_id, mutation)
        return holder["impact"].as_dict()

    def episode_subtitles(self, task_id: str, episode: int) -> Optional[Dict[str, Any]]:
        """A subtitle draft for one planned episode, timed by reading length within each shot."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        entry = (state or {}).get("episodes", {}).get(str(int(episode))) if state else None
        if not isinstance(entry, dict):
            raise LookupError(f"第 {episode} 集没有结构化编剧记录，无法生成字幕草稿")
        script = entry.get("script") if isinstance(entry.get("script"), dict) else {}
        scenes = [scene for scene in (script.get("scenes") or []) if isinstance(scene, dict)]
        cues = episode_cues(scenes, language=str(state.get("language") or "zh"))
        return {
            "task_id": task_id, "episode": int(episode), "cues": [cue.as_dict() for cue in cues],
            "srt": render_srt(cues), "total_seconds": sum(int(scene.get("duration_seconds") or 0) for scene in scenes),
        }

    def usage_summary(self, task_id: str, *, limit: int = 50) -> Optional[Dict[str, Any]]:
        """What a project has spent on provider calls, with its newest records."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        records = task.get("usage_records") if isinstance(task.get("usage_records"), list) else []
        return {
            "task_id": task_id,
            "summary": usage_ledger.summarize(records),
            "records": list(reversed(records[-max(0, int(limit)):])),
            "pricing_entries": len(pricing_table()),
        }

    def assess_video_admission(self, task_id: str, *, confirmed_request_durations: Optional[List[Dict[str, Any]]] = None,
                               persist_confirmations: bool = False) -> Optional[Dict[str, Any]]:
        """Admission of the project's shots to stage 5; optionally record the confirmed duration tiers."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        if persist_confirmations and confirmed_request_durations is not None:
            pairs = [
                {"scripted_seconds": int(item.get("scripted_seconds") or 0), "requested_seconds": int(item.get("requested_seconds") or 0)}
                for item in confirmed_request_durations if isinstance(item, dict)
            ]

            def remember(current: Dict[str, Any]) -> Dict[str, Any]:
                config = current.setdefault("config", {})
                known = {(p["scripted_seconds"], p["requested_seconds"]) for p in (config.get("confirmed_request_durations") or []) if isinstance(p, dict)}
                config["confirmed_request_durations"] = [
                    {"scripted_seconds": a, "requested_seconds": b} for a, b in sorted(known | {(p["scripted_seconds"], p["requested_seconds"]) for p in pairs})
                ]
                return current

            task = self.repo.mutate_task(task_id, remember) or task
        admission = assess_video_batch(
            task, provider_ready=ModelGateway.video_family_ready,
            confirmed_request_durations=confirmed_request_durations if not persist_confirmations else None,
        )
        payload = admission.as_dict()
        self.repo.mutate_task(task_id, lambda current: current.setdefault("assets", {}).__setitem__("5_admission", payload))
        return payload

    def _ensure_agent_council(self, task: Dict[str, Any]) -> dict:
        """Return the typed eight-agent plan, compiling it for legacy tasks when needed."""
        assets = task.setdefault("assets", {})
        existing = assets.get("agent_council")
        if isinstance(existing, dict) and existing.get("agents"):
            return existing
        config = task.get("config") or {}
        title = str(config.get("title_suggestion") or "未命名短剧")
        request = CouncilCompileRequest(
            title=title[:300],
            premise=str(config.get("script_content") or title)[:20_000],
            genre=self.gateway.get_genre(title),
            audience="18-35 岁移动端短剧观众",
            platform="douyin",
            format="live_action",
            episode_count=_bounded_episode_count(config.get("episode_count")),
            episode_duration_seconds=90,
            output_language="zh-CN",
            visual_style=str(config.get("director_style") or "写实电影感"),
            action_intensity=(
                "high" if self.gateway.get_genre(title) in self.FIGHT_GENRES
                else "medium"
            ),
        )
        compiled = self.agent_council.compile(request).model_dump(mode="json")
        assets["agent_council"] = compiled
        return compiled

    def _role_negative_modules(self, task: Dict[str, Any], role: AgentRole) -> list:
        """取该角色的负面词配药单(委员会按角色产出形态筛好的模块 id 列表)。"""
        plan = self._ensure_agent_council(task)
        by_role = plan.get("negative_prompt_by_role") or {}
        return list(by_role.get(role.value) or [])

    def _role_negative_suffix(self, task: Dict[str, Any], role: AgentRole,
                              exclude: tuple = ()) -> str:
        """把配药单编译成可拼进生成提示词的负面词串；exclude 用于图像侧剔除时序模块。"""
        modules = [m for m in self._role_negative_modules(task, role) if m not in exclude]
        return compile_negative_prompt(modules)

    def _agent_role_prompt(self, task: Dict[str, Any], role: AgentRole) -> str:
        plan = self._ensure_agent_council(task)
        for agent in plan.get("agents", []):
            if agent.get("role") == role.value:
                return str(agent.get("system_prompt") or "")
        raise RuntimeError(f"八 Agent 计划缺少角色：{role.value}")

    def split_shot_action(self, desc: str, creative_title: str) -> tuple:
        """
        将一个镜头的动作描述拆解为前后两个阶段的画面描述，分别用于生成多组图片
        """
        sys_prompt = "You are a storyboard artist. Split the given visual description into two consecutive keyframe visual prompts for image generation. Output format: Part 1: [prompt for keyframe 1] | Part 2: [prompt for keyframe 2]. Do not output anything else."
        user_prompt = f"Please split this action description: {desc}"
        try:
            res = self.gateway.call_llm(GATEWAY_DEFAULT_MODELS["deepseek"], sys_prompt, user_prompt, creative_title)
            if "|" in res:
                parts = res.split("|")
                p1 = parts[0].replace("Part 1:", "").strip()
                p2 = parts[1].replace("Part 2:", "").strip()
                return p1, p2
        except Exception:
            pass
        return desc, desc

    def concatenate_video_clips(self, clip_urls: List[str], tag: str) -> Optional[str]:
        from app.core import media_compositor
        import hashlib
        import subprocess
        import shutil
        import os
        
        # 过滤掉 None 和非字符串类型，仅保留有效的视频直链
        clip_urls = [url for url in clip_urls if url and isinstance(url, str)]
        
        ff = media_compositor._ffmpeg()
        if not ff or not clip_urls:
            return None
            
        # 若只有一个片段有效，直接返回，避免 ffmpeg 重复拼接转码
        if len(clip_urls) == 1:
            return clip_urls[0]
            
        media_compositor._ensure_dir()
        
        # 将整个处理和拼接逻辑移入 try-except 块中，防止任何解析/计算错误导致上游崩溃
        try:
            h = hashlib.md5(("|".join(clip_urls)).encode("utf-8")).hexdigest()[:16]
            work = os.path.join(media_compositor.MEDIA_DIR, f"_concat_{tag}_{h}")
            os.makedirs(work, exist_ok=True)
            local_files = []
            for i, url in enumerate(clip_urls):
                local_path = os.path.join(work, f"part_{i}.mp4")
                if media_compositor._download(url, local_path):
                    norm_path = os.path.join(work, f"norm_{i}.mp4")
                    scale_pad = f"scale={media_compositor.OUT_W}:-2,pad={media_compositor.OUT_W}:{media_compositor.OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
                    cmd = [ff, "-y", "-i", local_path, "-vf", scale_pad, "-r", str(media_compositor.OUT_FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", norm_path]
                    subprocess.run(cmd, check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    local_files.append(norm_path)
            
            if not local_files:
                return None
            
            list_txt = os.path.join(work, "list.txt")
            with open(list_txt, "w", encoding="utf-8") as f:
                for lf in local_files:
                    f.write(f"file '{lf}'\n")
                    
            out_name = f"concat_{tag}_{h}.mp4"
            out_path = os.path.join(media_compositor.MEDIA_DIR, out_name)
            subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", list_txt, "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path],
                           check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return media_compositor.public_url(out_name)
        except Exception as e:
            logger.warning(f"拼接视频子片段失败: {e}")
            return None
        finally:
            if 'work' in locals():
                shutil.rmtree(work, ignore_errors=True)

    QC_REPORT_MAX_ROWS = 12

    @staticmethod
    def qc_max_tokens() -> int:
        """Output budget of one self-check (QC_MAX_TOKENS); reasoning models spend part of it thinking."""
        return settings.env_int("QC_MAX_TOKENS", 2500, minimum=500, maximum=8000)

    def run_real_consistency_check(self, stage: int, stage_name: str, assets: dict, config: dict, creative_title: str,
                                   task_id: str = "") -> str:
        """
        读取 consistency-checklist（production-knowledge-master 技能里的一致性检查清单）内容，使用大模型对当前阶段的 assets 进行真实的自检和核验，并输出打分表格。
        task_id 供知识进化钩子做审计溯源；不传时进化日志记空串，质检本身不受影响。
        """
        # 经 production-knowledge-master 装载器读取(同一根部文件，登记预算 3500，行边界截断)
        checklist_cut = load_section("consistency-checklist") or "一致性检查指南"
        
        sys_prompt = (
            "Role: AI 短剧终极质检专家 (Quality Control Hook Agent)\n"
            f"Methodology: 遵循《{section_title('consistency-checklist')}》质检准则，对当前阶段生成的真实资产进行客观审查打分。\n"
            "输出格式：标准的 Markdown 质检自检报告表格。表格必须包含列：检查维面 | 质检内容 | 状态得分 | 状态说明。\n"
            f"只列与本阶段资产相关的检查项，表格不超过 {self.QC_REPORT_MAX_ROWS} 行，每格一句话；"
            "最后用不超过 120 字给出总体结论和一致性评分。不要复述清单原文。"
        )
        
        # 提取当前阶段的资产特征
        asset_info = str(assets.get(str(stage)) or assets.get(stage) or "")[:2000]
        # 阶段四先把机器可判定的连续性自检结果交给质检模型：它不该重新猜时间轴有没有空档，
        # 该项已由 storyboard_director 算过并落在 4_continuity_audit；进化引擎也据此采收教训。
        machine_audit = ""
        if int(stage) == 4 and isinstance(assets, dict):
            table = audit_markdown(assets.get("4_continuity_audit"))
            if table:
                machine_audit = f"【机器连续性自检（管线内已自动执行，先于本次质检）】\n{table}\n\n"

        user_prompt = (
            f"当前短剧：《{creative_title}》\n"
            f"当前阶段：第 {stage} 阶段 — {stage_name}\n"
            f"当前已生成资产：\n{asset_info}\n\n"
            + machine_audit +
            f"请参考以下一致性检查清单，对上述资产进行核验打分，输出自检表格和结论：\n\n{checklist_cut}"
        )
        
        try:
            llm_model = config.get("llm_model", GATEWAY_DEFAULT_MODELS["deepseek"])
            # The report is a gate, not a deliverable: an uncapped "100+ 项" table on a reasoning
            # model ran past six minutes after every stage, longer than the stage's own work.
            res = self.gateway.call_llm(llm_model, sys_prompt, user_prompt, creative_title, max_tokens=self.qc_max_tokens())
            if res and "|" in res:
                report = f"🪝 **[HOOK 拦截器触发] `PostAgentCallHook ({stage_name}质检)`**\n\n{res}"
                # 知识进化钩子：从真实质检报告蒸馏候选教训并按命中晋升/退休。
                # 进化是旁路增强，任何失败只记 warning，绝不影响质检返回值。
                try:
                    knowledge_evolution.harvest_from_qc(
                        stage, report, task_id,
                        llm=lambda sys, user: self.gateway.call_llm(llm_model, sys, user, creative_title),
                    )
                    knowledge_evolution.promote_and_prune()
                except Exception as evo_error:
                    logger.warning(f"知识进化钩子失败 (不影响质检返回): {evo_error}")
                return report
        except Exception as e:
            logger.warning(f"真实一致性 Hook 质检失败: {e}")
            
        return (
            "🪝 **[HOOK 拦截器触发] `PostAgentCallHook`**\n"
            "#### ⚠️ 一致性质检未完成（禁止视为通过）\n"
            "| 检查维面 | 质检内容 | 状态得分 | 状态 |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| 规范核验 | 质检模型未返回可验证报告，需重试或人工复核 | 0.0% | ❌ UNVERIFIED |"
        )


    async def generate_seedance2_video(self, prompt: str, mode: str = "auto",
                                       first_frame: Optional[str] = None, last_frame: Optional[str] = None,
                                       ref_images: Optional[List[str]] = None,
                                       ref_videos: Optional[List[str]] = None,
                                       ref_audios: Optional[List[str]] = None,
                                       optimize: bool = True) -> Dict[str, Any]:
        """
        直接调用 Seedance 2.0 生视频，支持四种能力：
          - text_to_video：仅 prompt
          - first_frame：prompt + first_frame
          - first_last_frame：prompt + first_frame + last_frame
          - multi_ref：prompt + ref_images(0-9)/ref_videos(0-3)/ref_audios(0-3)(可叠加 first_frame)
        prompt 默认先经 sd2-pe 优化器工程化重写。阻塞式 I/O 放线程池执行。
        """
        # 临时按 optimize 开关控制优化器
        prev = self.gateway.seedance_prompt_opt
        self.gateway.seedance_prompt_opt = bool(optimize)
        try:
            video_url = await asyncio.to_thread(
                self.gateway.generate_video, "seedance", first_frame, prompt,
                None, last_frame, ref_images, ref_videos, ref_audios
            )
        finally:
            self.gateway.seedance_prompt_opt = prev
        # 推断实际生效的模式
        if last_frame:
            eff_mode = "first_last_frame"
        elif ref_images or ref_videos or ref_audios:
            eff_mode = "multi_ref"
        elif first_frame:
            eff_mode = "first_frame"
        else:
            eff_mode = "text_to_video"
        return {
            "status": "success",
            "mode": eff_mode,
            "model": self.gateway.seedance_model_name,
            "video_url": video_url,
            "prompt_optimized": bool(optimize),
        }

    def create_task(
        self,
        req: DramaCreateRequest,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        初始化创建一个短剧生成任务，生成唯一的 taskId，并将初始状态写入仓储
        """
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "owner_user_id": str(owner_user_id) if owner_user_id else None,
            "current_stage": 0,
            "stage_name": "初始化选题",
            "status": "idle",
            "config": {
                "title_suggestion": req.title_suggestion,
                "director_style": req.director_style,
                "style_pack": style_packs.resolve_pack({"style_pack": req.style_pack or "", "director_style": req.director_style}).id,
                "shot_style": req.shot_style,
                "llm_model": req.llm_model,
                "image_model": req.image_model,
                "video_model": req.video_model,
                "tts_model": req.tts_model,
                "video_reference_mode": req.video_reference_mode,
                "narration_delivery": req.narration_delivery,
                "creation_mode": req.creation_mode,
                # The engine reads source_language; content_language is what the person chose.
                "content_language": req.content_language,
                "source_language": req.content_language,
                "ad_brief": req.ad_brief.model_dump() if req.ad_brief else {},
                "one_click": req.one_click,
                "episode_count": _bounded_episode_count(getattr(req, "episode_count", None)),
                "guidance_instruction": "",
                "script_content": req.script_content,
                "script_name": req.script_name
            },
            "chat_history": [],
            "assets": {},
            "logs": {},
            "video_url": None,
            "short_link": None,
            "pr_content": None
        }
        self._ensure_agent_council(task_data)
        self.repo.save_task(task_id, task_data)
        return task_data

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务当前状态与所有已生成的中间资产 (用于断点续传)
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return self.hydrate_task_status(task)

    def hydrate_task_status(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in compatibility assets on an already-loaded task.

        Listing endpoints hold every task in memory already; going back through
        ``get_task_status`` would re-read and re-parse the whole task database
        once per task, which is the dominant cost of the polled task list.
        """
        assets = task.setdefault("assets", {})
        if assets.get("2"):
            breakdown = assets.setdefault("2_breakdown", {})
            if isinstance(breakdown, dict):
                breakdown["scenes"] = self._breakdown_scenes(task)
        board_payload = assets.get("4_storyboard")
        if isinstance(board_payload, dict) and not assets.get("4_prompt_detail"):
            try:
                board = NineGridStoryboard.model_validate(board_payload)
                profiles = {
                    str(item.get("name")): str(item.get("desc") or "")
                    for item in (assets.get("3_characters") or [])
                    if isinstance(item, dict) and item.get("name")
                }
                # Legacy boards do not carry an ID. Match their visible actions
                # against persisted scene shots; never substitute the whole show.
                actions = [panel.subject_action for panel in board.panels]
                grouped: Dict[str, list] = {}
                for shot in assets.get("4") or []:
                    if isinstance(shot, dict) and shot.get("scene_id"):
                        grouped.setdefault(str(shot["scene_id"]), []).append(shot.get("desc"))
                matching = [key for key, descriptions in grouped.items() if descriptions == actions]
                source_scene = next((scene for scene in self._breakdown_scenes(task) if len(matching) == 1 and scene["scene_id"] == matching[0]), None)
                current_scene_id = matching[0] if len(matching) == 1 else None
                detail = compile_storyboard_prompt_detail(
                    board,
                    script_text=compile_scene_context(task, source_scene)["script"] if source_scene else "\n".join(actions),
                    visual_style=f"{(task.get('config') or {}).get('director_style') or '真人电影写实'}，精品短剧画风，大师级构图",
                    episode=f"第{episode_from_scene_id(current_scene_id)}集" if current_scene_id else "第1集",
                    scene_id=current_scene_id,
                    character_profiles=profiles,
                )
                assets["4_prompt_detail"] = detail.model_dump(mode="json")
            except Exception as exc:
                logger.warning("分镜提示词详情兼容编译失败: %s", type(exc).__name__)
        task["workflow"] = self.workflow_snapshot(task)
        task["chat_history"] = [
            {"id": str(item.get("id") or f"legacy-{index}"),
             "role": item.get("role") or ("user" if item.get("sender") == "user" else "assistant"),
             "content": item.get("content", item.get("text", ""))}
            for index, item in enumerate(task.get("chat_history") or []) if isinstance(item, dict)
        ]
        return task

    # ---------- 视觉阶段：逐镜运镜工作区 ----------

    @staticmethod
    def _derive_shot_visual(shot: Dict[str, Any], clip: Dict[str, Any], options: list[int]) -> tuple[Dict[str, Any], list[str]]:
        """Settings for a shot that has never been edited, from the storyboard table and clip."""
        from app.schema.shot_visual import ShotVisualSettings

        notes: list[str] = []
        motion, matched = normalize_camera_motion(shot.get("motion"))
        if not matched:
            notes.append(f"分镜表运镜「{shot.get('motion') or ''}」不在词表内，已按「固定」处理")
        shot_type, matched = normalize_shot_type(shot.get("size"))
        if not matched:
            notes.append(f"分镜表景别「{shot.get('size') or ''}」不在词表内，已按「中景」处理")
        raw_duration = clip.get("duration") if isinstance(clip.get("duration"), (int, float)) else shot.get("duration")
        parsed = _bounded_shot_duration(raw_duration, default=float(options[0]))
        duration = min(max(int(round(parsed)), options[0]), options[-1])
        if duration != parsed:
            notes.append(f"时长已按视频模型可用范围调整为 {duration} 秒")
        settings = ShotVisualSettings(
            camera_motion=motion, shot_type=shot_type, duration_seconds=duration,
            ambiance_audio="", action="",
        )
        return settings.model_dump(), notes

    def get_shot_visual_workspace(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Every stage-4 shot with its camera settings, media and prompts for the visual stage."""
        from app.schema.shot_visual import ShotVisualRecord, ShotVisualSettings, ShotVisualWorkspaceResponse

        task = self.repo.get_task(task_id)
        if not task:
            return None
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        video_model = str(config.get("video_model") or "")
        options = shot_duration_options(video_model)
        clips = {
            str(clip.get("shot_id")): clip
            for clip in (assets.get("5") or []) if isinstance(clip, dict)
        }
        # 没出过片的镜头也要能给 @[名字] 着色：项目里的角色先按数字演员认。
        character_kinds = {
            str(item.get("name") or ""): "actor"
            for item in (assets.get("3_characters") or []) if isinstance(item, dict) and item.get("name")
        }
        records = []
        for index, shot in enumerate(assets.get("4") or [], start=1):
            if not isinstance(shot, dict):
                continue
            shot_id = int(shot.get("shot_id") or index)
            clip = clips.get(str(shot_id)) or {}
            prompt_override = str(shot.get("video_prompt_override") or "").strip()
            edited = shot.get("visual") if isinstance(shot.get("visual"), dict) else None
            notes: list[str] = []
            if edited:
                try:
                    settings = ShotVisualSettings.model_validate(edited)
                except Exception:
                    edited = None
            if not edited:
                derived, notes = self._derive_shot_visual(shot, clip, options)
                settings = ShotVisualSettings.model_validate(derived)
            records.append(ShotVisualRecord(
                shot_id=shot_id,
                scene_id=str(shot.get("scene_id") or ""),
                desc=str(shot.get("desc") or ""),
                dialogue=str(shot.get("dialogue") or ""),
                sound=str(shot.get("sound") or ""),
                settings=settings,
                settings_source="edited" if edited else "derived",
                derived_notes=notes,
                image_url=shot.get("image_url") or clip.get("image_url"),
                end_frame_url=clip.get("end_frame_url"),
                video_url=clip.get("video_url"),
                candidate_urls=[str(url) for url in (clip.get("candidates") or []) if url],
                image_prompt=str(shot.get("storyboard_prompt") or ""),
                video_prompt=prompt_override or str(clip.get("motion_prompt") or clip.get("contract_motion_prompt") or ""),
                contract_fingerprint=str(shot.get("contract_fingerprint") or ""),
                route=clip.get("video_route_decision") if isinstance(clip.get("video_route_decision"), dict) else None,
                stale=bool(clip.get("stale")),
                stale_reason=str(clip.get("stale_reason") or ""),
                video_prompt_edited=bool(prompt_override),
                mention_kinds={**character_kinds, **{
                    str(name): str(kind) for name, kind in (clip.get("mention_kinds") or {}).items()
                }},
                reference_numbers={
                    str(name): int(number) for name, number in (clip.get("reference_numbers") or {}).items()
                    if isinstance(number, int)
                },
            ))
        vocab = camera_vocabulary()
        return ShotVisualWorkspaceResponse(
            task_id=task_id,
            current_stage=int(task.get("current_stage") or 0),
            running=self._has_running_generation(task),
            video_model=video_model,
            provider_family=normalize_video_provider(video_model).family,
            duration_options=options,
            camera_motions=vocab["camera_motions"],
            shot_types=vocab["shot_types"],
            recipe_categories=recipe_catalog(),
            shots=records,
        ).model_dump(mode="json")

    def assign_shot_seeds(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Give every stage-4 shot a fixed seed, neighbouring within a scene; clips go stale."""
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            if self._has_running_generation(task):
                raise ValueError("任务正在执行阶段，暂不能分配种子")
            assets = task.setdefault("assets", {})
            shots = [shot for shot in (assets.get("4") or []) if isinstance(shot, dict)]
            if not shots:
                raise LookupError("尚无分镜镜头，请先完成第 4 阶段")
            options = shot_duration_options(str((task.get("config") or {}).get("video_model") or ""))
            clips = {str(clip.get("shot_id")): clip for clip in (assets.get("5") or []) if isinstance(clip, dict)}
            for index, (shot, seed) in enumerate(zip(shots, assign_scene_seeds(shots).values(), strict=True), start=1):
                visual = shot.get("visual") if isinstance(shot.get("visual"), dict) else None
                if visual is None:
                    visual, _ = self._derive_shot_visual(shot, clips.get(str(shot.get("shot_id") or index)) or {}, options)
                visual["seed"] = seed
                shot["visual"] = visual
                clip = clips.get(str(shot.get("shot_id") or index))
                if clip is not None:
                    clip["stale"] = True
                    clip["stale_reason"] = "已分配固定种子，需重跑第 5 阶段后生效"
            return task

        try:
            updated = self.repo.mutate_task(task_id, mutate)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not updated:
            return None
        return self.get_shot_visual_workspace(task_id)

    def select_shot_candidate(self, task_id: str, shot_id: int, video_url: str) -> Optional[Dict[str, Any]]:
        """Promote one rendered candidate to the shot's clip; the user is the selection criterion."""
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.setdefault("assets", {})
            clip = next(
                (item for item in (assets.get("5") or []) if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id)),
                None,
            )
            if clip is None:
                raise LookupError("该镜头尚未生成视频")
            candidates = [str(url) for url in (clip.get("candidates") or []) if url]
            if video_url not in candidates:
                raise LookupError("所选版本不在该镜头的候选列表中")
            chosen = video_url
            if clip.get("voice_path"):
                chosen = media_compositor.attach_audio_to_clip(
                    video_url, clip["voice_path"], bgm=False, tag=f"shotav_{task_id[:8]}_s{shot_id}_pick",
                )
            clip["video_url"] = chosen
            clip["selected_candidate"] = video_url
            return task

        try:
            updated = self.repo.mutate_task(task_id, mutate)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not updated:
            return None
        return self.get_shot_visual_workspace(task_id)

    def regenerate_shot(self, task_id: str, shot_id: int, *, reason: str = "") -> Optional[Dict[str, Any]]:
        """Ask for one shot's clip to be made again: it is marked stale, the rest stay reused on the next run."""
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.setdefault("assets", {})
            if task.get("status") == "running" and int((task.get("stage_progress") or {}).get("stage") or 0) == 5:
                raise LookupError("第 5 阶段正在运行，等它结束后再要求重做")
            clip = next(
                (item for item in (assets.get("5") or []) if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id)),
                None,
            )
            if clip is None:
                raise LookupError("该镜头尚未生成视频，重跑第 5 阶段即可生成")
            clip["stale"] = True
            clip["stale_reason"] = (reason.strip() or "人工要求重新生成") + "，重跑第 5 阶段时只重做本镜，其余镜头沿用"
            # A resumed or recorded job for this shot must not be handed back as the "same request".
            jobs = assets.get(video_jobs.JOBS_KEY)
            if isinstance(jobs, dict):
                for key in list(jobs):
                    if str(key).split(":")[0] == str(shot_id):
                        jobs.pop(key, None)
            return task

        try:
            updated = self.repo.mutate_task(task_id, mutate)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not updated:
            return None
        return self.get_shot_visual_workspace(task_id)

    def compose_shot_recipe(self, task_id: str, shot_id: int, category: str, intensity: str) -> Optional[Dict[str, Any]]:
        """A category/intensity camera recipe filled with this shot's action, scene and light."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        shots = assets.get("4") if isinstance(assets.get("4"), list) else []
        target = next(
            (shot for index, shot in enumerate(shots, start=1)
             if isinstance(shot, dict) and int(shot.get("shot_id") or index) == shot_id),
            None,
        )
        if target is None:
            raise ValueError("镜头不存在，请先完成第 4 阶段分镜")
        video_model = str((task.get("config") or {}).get("video_model") or "")
        recipe = compose_recipe(
            category, intensity,
            subject_action=str(target.get("desc") or ""),
            environment=str(target.get("scene") or ""),
            lighting=str((target.get("motion_contract") or {}).get("lighting") or ""),
            provider_family=normalize_video_provider(video_model).family,
        )
        return recipe.model_dump()

    def _render_actor_sheet(
        self, *, name: str, desc: str, image_model: str, dir_style: str, genre: str,
        extra_negative: str, max_attempts: int, ref_images: list | None = None,
    ) -> Dict[str, Any]:
        """一名角色的设定集付费调用：生成 → 拆成各个格子 → 补齐缺格 → 逐格质检，失败按次数重试。

        只读 gateway 与入参，不碰 task，所以第 3 阶段可以并发调用；单个角色的「重新生成」走的也是它。
        返回 {sheet, views, cells, quality, phase, error}。
        """
        sheet_url = None
        views: list = []
        cells: list = []
        quality_payload = None
        failure_phase = "generation_error"
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            sheet_url = None
            views = []
            cells = []
            quality_payload = None
            failure_phase = "generation_error"
            try:
                sheet_url = self.gateway.generate_character_sheet(
                    image_model, name, desc, dir_style, genre=genre,
                    ref_images=ref_images, extra_negative=extra_negative,
                )
                if not sheet_url:
                    raise RuntimeError(f"角色「{name}」设定集生成失败")

                failure_phase = "split_error"
                view_digest = hashlib.sha256(f"{name}|{sheet_url}".encode("utf-8")).hexdigest()[:16]
                view_dir = os.path.join(media_compositor.MEDIA_DIR, "character_views", view_digest)
                # 一张设定集拆成最多 25 个独立资产，全部落库——用户要的是每一格都能单看。
                cell_paths = split_actor_sheet(sheet_url, view_dir)
                # 模型没画的元素/细节格从已画出的身份面板里按部位补裁：数字演员 25 张图一张不缺。
                cell_paths, derived_cells = complete_actor_sheet_cells(cell_paths)
                # 其中五格是身份锚点：看板、资产库复用与后续阶段读的就是它们。
                cells, views = self._actor_cell_records(cell_paths, derived_cells, set())

                failure_phase = "quality_error"
                sheet_quality = validate_actor_sheet_images(cell_paths)
                quality_payload = sheet_quality.model_dump()
                if not sheet_quality.passed:
                    raise RuntimeError(
                        f"角色「{name}」设定集质检失败："
                        + "；".join(issue.message for issue in sheet_quality.issues)
                    )
                # 设定集里的身份格只有几百像素，放大就糊：再出两张高清三联替换六个身份视图(失败就保留原裁切)。
                hd_cells: set[str] = set()
                if hd_identity_views_enabled():
                    hd_paths, hd_replaced = self._apply_hd_identity_views(
                        name=name, desc=desc, image_model=image_model, dir_style=dir_style,
                        references=[sheet_url], cell_paths=cell_paths,
                    )
                    hd_quality = validate_actor_sheet_images(hd_paths) if hd_replaced else None
                    if hd_quality is not None and hd_quality.passed:
                        cell_paths, quality_payload, hd_cells = hd_paths, hd_quality.model_dump(), hd_replaced
                        for cell in hd_cells:
                            derived_cells.pop(cell, None)
                # 模型漏画、只能补位裁切的元素/细节格，再出一张特写拼板真正画出来(失败就保留补位)。
                if detail_fill_enabled() and fillable(derived_cells):
                    fill_paths, filled = self._apply_detail_fill(
                        name=name, desc=desc, image_model=image_model, dir_style=dir_style,
                        references=[sheet_url], cell_paths=cell_paths, cells=list(derived_cells),
                    )
                    fill_quality = validate_actor_sheet_images(fill_paths) if filled else None
                    if fill_quality is not None and fill_quality.passed:
                        cell_paths, quality_payload = fill_paths, fill_quality.model_dump()
                        for cell in filled:
                            derived_cells.pop(cell, None)
                cells, views = self._actor_cell_records(cell_paths, derived_cells, hd_cells)
                last_error = None
                break
            except Exception as char_error:  # noqa: BLE001 - 每次失败都记下阶段，按次数重试
                last_error = char_error
                if attempt < max_attempts:
                    logger.warning(
                        "[Stage3] 数字演员设定集生成重试: character=%s attempt=%s/%s phase=%s",
                        name, attempt, max_attempts, failure_phase,
                    )
        return {"sheet": sheet_url, "views": views, "cells": cells,
                "quality": quality_payload, "phase": failure_phase, "error": last_error}

    def set_shot_video_prompt(self, task_id: str, shot_id: int, prompt: str | None) -> Optional[Dict[str, Any]]:
        """保存人工改写的视频提示词(空串/None 恢复自动编译)；本镜已出的片标记为待重做。"""
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            if self._has_running_generation(task):
                raise ValueError("任务正在执行阶段，暂不能修改提示词")
            assets = task.setdefault("assets", {})
            shots = assets.get("4") if isinstance(assets.get("4"), list) else []
            target = next(
                (shot for index, shot in enumerate(shots, start=1)
                 if isinstance(shot, dict) and int(shot.get("shot_id") or index) == shot_id),
                None,
            )
            if target is None:
                raise LookupError("镜头不存在，请先完成第 4 阶段分镜")
            text = (prompt or "").strip()
            if text:
                target["video_prompt_override"] = text
            else:
                target.pop("video_prompt_override", None)
            for clip in assets.get("5") or []:
                if isinstance(clip, dict) and str(clip.get("shot_id")) == str(shot_id):
                    clip["stale"] = True
                    clip["stale_reason"] = (
                        "视频提示词已人工修改，重新生成本镜后生效" if text else "已恢复自动编译的提示词，重新生成本镜后生效"
                    )
            return task

        try:
            updated = self.repo.mutate_task(task_id, mutate)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not updated:
            return None
        return self.get_shot_visual_workspace(task_id)

    def update_shot_visual(self, task_id: str, shot_id: int, settings) -> Optional[Dict[str, Any]]:
        """Persist one shot's camera settings onto its stage-4 record and motion contract.

        Editing never advances the workflow: the clip already rendered for the shot
        is only marked stale so the visual stage (5) must be rerun to honour it.
        """
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            if self._has_running_generation(task):
                raise ValueError("任务正在执行阶段，暂不能修改运镜")
            assets = task.setdefault("assets", {})
            shots = assets.get("4") if isinstance(assets.get("4"), list) else []
            target = next(
                (shot for index, shot in enumerate(shots, start=1)
                 if isinstance(shot, dict) and int(shot.get("shot_id") or index) == shot_id),
                None,
            )
            if target is None:
                raise LookupError("镜头不存在，请先完成第 4 阶段分镜")
            options = shot_duration_options(str((task.get("config") or {}).get("video_model") or ""))
            if settings.duration_seconds not in options:
                raise ValueError(
                    f"当前秒数 {settings.duration_seconds} 不在模型支持范围 [{options[0]}-{options[-1]}] 内"
                )
            target["visual"] = settings.model_dump()
            target["motion"] = settings.camera_motion
            target["size"] = settings.shot_type
            target["duration"] = str(settings.duration_seconds)
            raw_contract = target.get("motion_contract")
            if isinstance(raw_contract, dict):
                contract = ShotMotionContract.model_validate(raw_contract).model_copy(update={
                    "camera_movement": settings.camera_motion,
                    "shot_size": settings.shot_type,
                })
                target["motion_contract"] = contract.model_dump(mode="json")
                target["contract_fingerprint"] = contract.contract_fingerprint
            for clip in assets.get("5") or []:
                if isinstance(clip, dict) and str(clip.get("shot_id")) == str(shot_id):
                    clip["stale"] = True
                    clip["stale_reason"] = "运镜、景别或时长已修改，需重跑第 5 阶段后生效"
            return task

        try:
            updated = self.repo.mutate_task(task_id, mutate)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not updated:
            return None
        return self.get_shot_visual_workspace(task_id)

    # ---------------- 空间调度：每场一份站位 / 地标 / 轴线 / 机位方案 ----------------

    def _spatial_response(self, task: Dict[str, Any], scene_id: str, plan, *, persisted: bool) -> Dict[str, Any]:
        boards = (task.get("assets") or {}).get("4_scene_boards")
        board = boards.get(scene_id) if isinstance(boards, dict) and isinstance(boards.get(scene_id), dict) else {}
        return {
            "task_id": str(task.get("task_id") or ""),
            "scene_id": scene_id,
            "persisted": persisted,
            "board_status": str(board.get("status") or ""),
            "board_stale": bool(board.get("spatial_stale")),
            "plan": plan.model_dump(mode="json"),
        }

    def compile_prompt_packages(
        self,
        task_id: str,
        *,
        scene_id: str = "",
        package_seconds: int = 15,
        variant: str = "standard",
        delivery: str = "正常",
    ) -> Optional[Dict[str, Any]]:
        """Re-cut a scene's finished shots into self-contained Seedance packages.

        The shots are already approved at this point, so this only regroups them: no
        model is called and nothing is written back to the task.
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        flat = task["assets"].get("4") if isinstance(task["assets"].get("4"), list) else []
        shots = [
            shot for shot in flat
            if isinstance(shot, dict) and (not scene_id or str(shot.get("scene_id") or "") == scene_id)
        ]
        if not shots:
            raise ValueError("还没有可用的分镜表：先完成第4阶段")

        config = task.get("config") or {}
        pack = style_packs.resolve_pack(config)
        scene_record = next(
            (item for item in self._breakdown_scenes(task) if str(item.get("scene_id") or "") == str(shots[0].get("scene_id") or "")),
            {},
        )
        plan = prompt_packages.plan_packages(
            shots, package_seconds=package_seconds, variant=variant, delivery=delivery,
        )
        spatial_plan = spatial_stage.load_plan(task, str(shots[0].get("scene_id") or "")) if scene_id else None
        context = prompt_packages.PackageContext(
            pack=pack,
            scene=str(shots[0].get("scene") or scene_record.get("content") or ""),
            spatial_lock=spatial_table_brief(spatial_plan) if spatial_plan is not None else "",
            lighting=str(shots[0].get("lighting") or ""),
            cast_locks={
                str(item.get("name")): str(item.get("desc") or item.get("description") or "按设定图渲染，不可改造")
                for item in (task["assets"].get("3_characters") or [])
                if isinstance(item, dict) and item.get("name")
            },
        )
        title = f"{config.get('title_suggestion') or '本片'}{f' · {scene_id}' if scene_id else ''}"
        return {
            "task_id": task_id,
            "scene_id": scene_id,
            "plan": plan.as_dict(),
            "text": prompt_packages.render(plan, context, title=title),
        }

    def report_shot_failure(
        self,
        task_id: str,
        shot_id: Any,
        *,
        result: str = "failed",
        text: str = "",
        category: str = "",
        applied_fix: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Take one "this shot came back wrong" report and answer with what to do next.

        The report is written into the project's ledger, so the same failure twice on the
        same model becomes a weakness the later stages design around.
        """
        if result not in {"success", "partial", "failed"}:
            raise ValueError("result 只能是 success、partial 或 failed")

        outcome: Dict[str, Any] = {}

        def change(task: Dict[str, Any]) -> Dict[str, Any]:
            model = str((task.get("config") or {}).get("video_model") or "")
            written = generation_feedback.record(
                task, shot_id=shot_id, result=result, text=text, category=category,
                model=model, applied_fix=applied_fix,
            )
            outcome.update({
                "task_id": task_id,
                "shot_id": shot_id,
                "result": result,
                "attempt": written["attempt"],
                "plan": written["plan"],
                "summary": generation_feedback.summary(task),
            })
            return task

        if self.repo.mutate_task(task_id, change) is None:
            return None
        return outcome

    def get_generation_feedback(self, task_id: str) -> Optional[Dict[str, Any]]:
        """The project's failure ledger: what broke, how often, and on which model."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        model = str((task.get("config") or {}).get("video_model") or "")
        return {
            "task_id": task_id,
            "summary": generation_feedback.summary(task),
            "preventive_notes": generation_feedback.preventive_notes(task, model),
            "catalog": generation_feedback.describe(),
        }

    def compile_asset_sheets(self, task_id: str) -> Optional[Dict[str, Any]]:
        """The design sheets a production needs locked before anything is generated."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        config = task.get("config") or {}
        pack = style_packs.resolve_pack(config)
        sheets = asset_sheets.extract_sheets(
            task, pack=pack, project=str(config.get("title_suggestion") or "本片"),
        )
        return {
            "task_id": task_id,
            "sheets": sheets.as_dict(),
            "markdown": asset_sheets.render_markdown(sheets, title=f"{config.get('title_suggestion') or '本片'} 资产设定图"),
        }

    def get_spatial_overview(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        store = (task.get("assets") or {}).get(spatial_stage.ASSET_KEY)
        store = store if isinstance(store, dict) else {}
        return {
            "task_id": task_id,
            "scenes": spatial_stage.summaries(task),
            "side_memory": {str(k): str(v) for k, v in (store.get("side_memory") or {}).items() if v in {"left", "right"}},
            "locations": {str(k): len(v) for k, v in (store.get("locations") or {}).items() if isinstance(v, list)},
        }

    def get_spatial_plan(self, task_id: str, scene_id: str) -> Optional[Dict[str, Any]]:
        """The stored plan, or a preview planned from the current script (nothing is written)."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        stored = spatial_stage.load_plan(task, scene_id)
        if stored is not None:
            return self._spatial_response(task, scene_id, stored, persisted=True)
        preview = spatial_stage.ensure_plan(deepcopy(task), scene_id)
        if preview is None:
            raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
        return self._spatial_response(task, scene_id, preview, persisted=False)

    def get_spatial_repairs(self, task_id: str, scene_id: str) -> Optional[Dict[str, Any]]:
        """What would clear the scene's failing checks, as operations; nothing is written."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        plan = spatial_stage.load_plan(task, scene_id) or spatial_stage.ensure_plan(deepcopy(task), scene_id)
        if plan is None:
            raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
        from app.core.spatial_stage import repair as stage_repair

        proposals = stage_repair.propose(plan)
        return {"task_id": task_id, "scene_id": scene_id, "revision": plan.revision, **stage_repair.summary(proposals)}

    def _mutate_spatial(self, task_id: str, scene_id: str, change) -> Optional[Dict[str, Any]]:
        def mutate(task: Dict[str, Any]) -> Dict[str, Any]:
            if self._has_running_generation(task):
                raise spatial_stage.StageConflict("任务正在执行阶段，暂不能修改空间调度")
            plan = change(task)
            return self._spatial_response(task, scene_id, plan, persisted=True)

        return self.repo.mutate_task(task_id, mutate)

    def patch_spatial_plan(
        self, task_id: str, scene_id: str, *, base_revision: int, operations: List[Dict[str, Any]],
        solve: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._mutate_spatial(task_id, scene_id, lambda task: spatial_stage.edit_plan(
            task, scene_id, base_revision=base_revision, operations=operations, solve=solve,
        ))

    def rebuild_spatial_plan(self, task_id: str, scene_id: str, *, base_revision: int) -> Optional[Dict[str, Any]]:
        def change(task: Dict[str, Any]):
            current = spatial_stage.load_plan(task, scene_id)
            if current is not None and current.revision != int(base_revision):
                raise spatial_stage.StageConflict("空间方案已在其他页面更新，请刷新后重试")
            return spatial_stage.rebuild_plan(task, scene_id)

        return self._mutate_spatial(task_id, scene_id, change)

    def import_spatial_plan(self, task_id: str, scene_id: str, *, base_revision: int, document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        def change(task: Dict[str, Any]):
            plan = spatial_stage.ensure_plan(task, scene_id)
            if plan is None:
                raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
            operations = spatial_interchange.import_operations(plan, document)
            return spatial_stage.edit_plan(task, scene_id, base_revision=base_revision, operations=operations)

        return self._mutate_spatial(task_id, scene_id, change)

    def redraw_spatial_scene(self, task_id: str, scene_id: str) -> Optional[Dict[str, Any]]:
        """Send a finished scene back to stage 4 so its nine panels are drawn from the current blocking."""
        def change(task: Dict[str, Any]):
            plan = spatial_stage.ensure_plan(task, scene_id)
            if plan is None:
                raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
            # A clip's first frame is its storyboard panel, so the panels being withdrawn name the clips.
            withdrawn = {
                str(shot.get("image_url")) for shot in spatial_stage.scene_shots(task, scene_id) if shot.get("image_url")
            }
            if not spatial_stage.request_redraw(task, scene_id):
                raise spatial_stage.StageConflict("该场景还没有分镜记录，直接运行第 4 阶段即可按当前站位生成")
            assets = task["assets"]
            boards = assets.get("4_scene_boards") or {}
            assets["4_progress"] = self._storyboard_progress(boards)
            assets["4_continuity_audit"] = aggregate_scene_boards(boards)
            for clip in assets.get("5") or []:
                if isinstance(clip, dict) and str(clip.get("image_url") or "") in withdrawn:
                    clip["stale"] = True
                    clip["stale_reason"] = "所属场景的站位已修改并重排分镜，需重跑第 5 阶段后生效"
            if int(task.get("current_stage") or 0) > 4:
                task["current_stage"] = 4
                task["stage_name"] = "分镜师分镜拆解"
            return plan

        return self._mutate_spatial(task_id, scene_id, change)

    def export_spatial_plan(self, task_id: str, scene_id: str, fmt: str) -> Optional[Dict[str, Any]]:
        response = self.get_spatial_plan(task_id, scene_id)
        if response is None:
            return None
        from app.core.spatial_stage.models import StagePlan

        plan = StagePlan.model_validate(response["plan"])
        if fmt == "costage":
            document = spatial_interchange.to_costage(plan)
            note = "CoStage 导演台文档：在 CoStage 中替换 director-stage.json 或按场景导入。"
        else:
            document = spatial_interchange.to_director_desk(plan)
            note = "3D 导演台工程：在导演台右侧「导入工程」中打开。"
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", scene_id)[:60] or "scene"
        return {
            "task_id": task_id, "scene_id": scene_id, "format": fmt,
            "file_name": f"{safe}-{'costage' if fmt == 'costage' else 'director-desk'}.json",
            "document": document, "note": note,
        }

    # ---------------- 3D 导演台：截取的静帧 / 白模视频，以及保存的姿态 ----------------

    def get_desk_captures(self, task_id: str, scene_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        return director_desk.scene_view(task, scene_id) if task else None

    def _mutate_desk(self, task_id: str, change):
        def mutate(task: Dict[str, Any]):
            # A running stage holds its own copy of the shots and writes it back when it finishes.
            if self._has_running_generation(task):
                raise spatial_stage.StageConflict("任务正在执行阶段，暂不能修改导演台截取")
            return change(task)

        return self.repo.mutate_task(task_id, mutate)

    def add_desk_capture(self, task_id: str, scene_id: str, upload: "director_desk.CaptureUpload") -> Optional[Dict[str, Any]]:
        media_type = director_desk.validate_upload(upload)
        task = self.repo.get_task(task_id)
        if not task:
            return None
        if spatial_stage.scene_record(task, scene_id) is None:
            raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
        # Checked before the file is written and again under the lock: the first spares the disk, the second is the rule.
        director_desk.ensure_room(task, scene_id, upload.kind)
        url = director_desk.store_media(task_id, scene_id, upload.content, media_type)
        try:
            capture = self._mutate_desk(task_id, lambda locked: director_desk.add_capture(locked, scene_id, upload, url))
        except Exception:
            director_desk.discard_media(url)
            raise
        if capture is None:
            director_desk.discard_media(url)
        return capture

    def delete_desk_capture(self, task_id: str, scene_id: str, capture_id: str) -> Optional[Dict[str, Any]]:
        result = self._mutate_desk(task_id, lambda task: director_desk.delete_capture(task, scene_id, capture_id))
        if result is None:
            return None
        view, url = result
        director_desk.discard_media(url)
        return view

    def apply_desk_capture(self, task_id: str, scene_id: str, capture_id: str, *, applied: bool = True) -> Optional[Dict[str, Any]]:
        change = director_desk.apply_capture if applied else director_desk.unapply_capture
        return self._mutate_desk(task_id, lambda task: change(task, scene_id, capture_id))

    def get_desk_poses(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        return {"task_id": task_id, "poses": director_desk.list_poses(task)} if task else None

    def save_desk_pose(self, task_id: str, name: str, pose: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from app.core.spatial_stage.models import StagePose

        try:
            validated = StagePose.model_validate(pose)
        except ValueError as error:
            raise director_desk.CaptureError("姿态数据不合法：关节角度须在 ±180° 内、最多 120 个关节，clip_phase 在 0 到 1 之间") from error

        def change(task: Dict[str, Any]) -> Dict[str, Any]:
            director_desk.save_pose(task, name, validated)
            return {"task_id": task_id, "poses": director_desk.list_poses(task)}

        # Poses do not touch the shots, so a running stage is no reason to refuse them.
        return self.repo.mutate_task(task_id, change)

    def delete_desk_pose(self, task_id: str, pose_id: str) -> Optional[Dict[str, Any]]:
        def change(task: Dict[str, Any]) -> Dict[str, Any]:
            director_desk.delete_pose(task, pose_id)
            return {"task_id": task_id, "poses": director_desk.list_poses(task)}

        return self.repo.mutate_task(task_id, change)

    def repair_outline(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Persist source-only missing episodes atomically, without paid regeneration."""
        def repair(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.setdefault("assets", {})
            if not assets.get("2"):
                return task
            breakdown = assets.setdefault("2_breakdown", {})
            if not isinstance(breakdown, dict):
                return task
            scenes = self._breakdown_scenes(task)
            if scenes != breakdown.get("scenes"):
                breakdown["scenes"] = scenes
                assets["2_writer_dashboard"] = compile_writer_dashboard(task).model_dump(mode="json", by_alias=True)
            return task
        return self.repo.mutate_task(task_id, repair)

    def get_writer_dashboard(self, task_id: str) -> Optional[WriterDashboardResponse]:
        """Compile the current Writer Agent assets into the stable dashboard contract."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return compile_writer_dashboard(task)

    _CATALOG_KEYS = ("scenes", "props", "costumes", "effects")
    # A screenplay may truly have no costume note or no effect; these are asked for once per
    # version of the script instead of on every page open.
    _OPTIONAL_CATALOG_KEYS = ("costumes", "effects")
    _CATALOG_CHECKED_KEY = "production_assets_checked"

    @staticmethod
    def _catalog_script(task: Dict[str, Any]) -> str:
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        return str(assets.get("2") or config.get("script_content") or "")

    def _catalog_kinds_to_fill(self, task: Dict[str, Any]) -> List[str]:
        """Catalog lists the screenplay analysis still owes this task, in catalog order."""
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
        existing = breakdown.get("production_assets")
        if (
            not isinstance(existing, dict)
            or not all(isinstance(existing.get(key), list) for key in self._CATALOG_KEYS)
            or not existing.get("scenes")
        ):
            return list(self._CATALOG_KEYS)
        checked = breakdown.get(self._CATALOG_CHECKED_KEY)
        fingerprint = hashlib.sha1(self._catalog_script(task).encode("utf-8")).hexdigest()[:16]
        done = set(checked.get("kinds") or []) if isinstance(checked, dict) and checked.get("fingerprint") == fingerprint else set()
        return [key for key in self._OPTIONAL_CATALOG_KEYS if not existing.get(key) and key not in done]

    def _analyze_production_catalog(self, task: Dict[str, Any], kinds: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """One screenplay-grounded analysis pass for the catalog lists in ``kinds``."""
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        script = self._catalog_script(task)
        if not script.strip():
            raise ValueError("剧本尚未生成，无法提取拍摄资产")
        shapes = {
            "scenes": '"scenes": [{"name": "实际拍摄地点名", "description": "时段、内外景、空间布局和剧情用途"}]',
            "props": '"props": [{"name": "具体道具名", "description": "外观、状态、持有人和出现情节"}]',
            "costumes": '"costumes": [{"name": "角色名·造型名", "character": "穿着者", "description": "款式、颜色、材质、配饰和穿着的剧情阶段"}]',
            "effects": '"effects": [{"name": "具体特效名", "description": "视觉形态、颜色、运动方式、触发时机和出现的场次"}]',
        }
        rules = {
            "costumes": (
                "服装（costumes）：为每位具名角色登记剧中可辨认的每一套造型，换装（喜服、囚衣、战甲、夜行衣、前世/今生两身）另登记一套；"
                "name 写「角色名·造型名」，如「沈知微·素白医官袍」；description 写款式、颜色、材质、配饰（发饰、腰带、鞋履）和在哪段剧情穿，"
                "必须与下方角色视觉设定里写的服装一致；剧本与设定都没写服装的角色，按时代与身份登记一套主造型，description 末尾注明「（按身份推定）」。"
            ),
            "effects": (
                "特效（effects）：收录需要合成或现场效果配合的视觉现象——暴雨雨幕、大雪、浓雾、火焰烟尘、爆炸破碎、血迹飞溅、"
                "法术光效、符咒剑气、超自然现象、全息屏幕等；name 写具体，如「九霄殿金色神光」；普通布光、景别、运镜不算特效。"
            ),
        }
        sys_prompt = (
            "你是影视制片资产拆解师。逐段阅读剧本，只输出一个合法 JSON 对象，禁止输出解释或 markdown。\n"
            "结构必须为：\n{\n  " + ",\n  ".join(shapes[key] for key in kinds) + "\n}\n"
            "只收录剧本有明确文字依据、需要实际拍摄准备或视觉生成的资产；同物异名必须合并。"
            "不要把人物、情绪、抽象主题、普通动作或摄影术语当作资产。"
            "火焰、烟雾、雨雪、破碎、飞溅等需要合成或现场效果配合的内容归入 effects。\n"
            + "".join(rules[key] + "\n" for key in kinds if key in rules)
            + "每类最多 60 项；没有内容时必须输出空数组。"
        )
        cast_block = ""
        if "costumes" in kinds:
            state = screenwriting.state_of(task) or {}
            inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
            looks = {
                str(name): str((entry or {}).get("description") or "")
                for name, entry in (inventory.get("characters") or {}).items()
                if isinstance(entry, dict)
            }
            for character in assets.get("3_characters") or []:
                if isinstance(character, dict) and character.get("name") and len(str(character.get("desc") or "")) > 12:
                    looks.setdefault(str(character["name"]), str(character["desc"]))
            lines = [f"- {name}：{look[:600]}" for name, look in looks.items() if look.strip()]
            if lines:
                cast_block = "【角色视觉设定】：\n" + "\n".join(lines[:20]) + "\n\n"
        title = str(config.get("title_suggestion") or "未命名短剧")
        result = self.gateway.call_llm(
            str(config.get("llm_model") or ""),
            sys_prompt,
            f"【短剧标题】：{title}\n\n{cast_block}【剧本原文】：\n{script}",
            title,
            str(config.get("director_style") or ""),
            str(config.get("shot_style") or ""),
        )
        parsed = extract_json_object(result)
        if not isinstance(parsed, dict):
            raise ValueError("拍摄资产分析未返回可用结果，请稍后重试")

        normalized: Dict[str, List[Dict[str, str]]] = {}
        for key in kinds:
            items: List[Dict[str, str]] = []
            seen_names = set()
            for item in parsed.get(key) or []:
                if not isinstance(item, dict):
                    continue
                name = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()[:60]
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                description = re.sub(r"\s+", " ", str(item.get("description") or "")).strip()[:2000]
                entry = {"name": name, "description": description}
                wearer = re.sub(r"\s+", " ", str(item.get("character") or "")).strip()[:80]
                if key == "costumes" and wearer:
                    entry["character"] = wearer
                    if wearer not in description:
                        entry["description"] = f"{wearer}穿着；{description}".rstrip("；")[:2000]
                items.append(entry)
                if len(items) >= 60:
                    break
            normalized[key] = items
        return normalized

    def _fill_production_catalog(self, task: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, str]]], bool]:
        """Fill what the catalog still lacks on ``task`` in place; returns (catalog, changed)."""
        kinds = self._catalog_kinds_to_fill(task)
        assets = task.setdefault("assets", {})
        breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
        existing = breakdown.get("production_assets") if isinstance(breakdown.get("production_assets"), dict) else {}
        if not kinds:
            return {key: list(existing.get(key) or []) for key in self._CATALOG_KEYS}, False
        found = self._analyze_production_catalog(task, kinds)
        catalog = {key: found[key] if key in found else list(existing.get(key) or []) for key in self._CATALOG_KEYS}
        fingerprint = hashlib.sha1(self._catalog_script(task).encode("utf-8")).hexdigest()[:16]
        checked = breakdown.get(self._CATALOG_CHECKED_KEY)
        earlier = set(checked.get("kinds") or []) if isinstance(checked, dict) and checked.get("fingerprint") == fingerprint else set()
        breakdown["production_assets"] = catalog
        breakdown[self._CATALOG_CHECKED_KEY] = {
            "fingerprint": fingerprint,
            "kinds": sorted(earlier | {key for key in kinds if key in self._OPTIONAL_CATALOG_KEYS}),
        }
        assets["2_breakdown"] = breakdown
        return catalog, True

    def ensure_production_asset_catalog(self, task_id: str) -> Optional[Dict[str, List[Dict[str, str]]]]:
        """Return and persist a complete screenplay-grounded shooting-asset catalog.

        New stage-2 runs produce this catalog as part of their normal breakdown.
        Older projects, and ones whose writer never listed costumes or effects,
        are repaired with one focused analysis pass for just the missing lists,
        so those libraries do not remain permanently empty.
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        working = deepcopy(task)
        catalog, changed = self._fill_production_catalog(working)
        if not changed:
            return catalog
        filled = working["assets"]["2_breakdown"]

        def mutation(current: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
            current_assets = current.get("assets")
            if not isinstance(current_assets, dict):
                current_assets = {}
                current["assets"] = current_assets
            current_breakdown = current_assets.get("2_breakdown")
            if not isinstance(current_breakdown, dict):
                current_breakdown = {}
            current_breakdown["production_assets"] = filled["production_assets"]
            current_breakdown[self._CATALOG_CHECKED_KEY] = filled[self._CATALOG_CHECKED_KEY]
            current_assets["2_breakdown"] = current_breakdown
            return catalog

        return self.repo.mutate_task(task_id, mutation)

    def analyze_relationships(self, task_id: str) -> Optional[WriterDashboardResponse]:
        """Derive real character relations from the screenplay with one LLM pass.

        Stage 2 already asks for ``relationships`` alongside the rest of the
        breakdown, but that pass fails or returns nothing on some projects, and
        the dashboard then falls back to co-occurrence edges ("同场互动 · N 场")
        which state no dramatic intent.  This re-runs just the relationship half
        so the graph can be repaired without regenerating the whole breakdown.
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        script = str(assets.get("2") or config.get("script_content") or "")
        if not script.strip():
            raise ValueError("剧本尚未生成，无法分析人物关系")

        title = str(config.get("title_suggestion") or "未命名短剧")
        sys_prompt = (
            "你是短剧制片系统的人物关系分析器。阅读剧本，只输出一个合法 JSON 对象"
            "（不要输出 JSON 之外的任何解释文字），字段如下：\n"
            "{\n"
            '  "roles": [{"name": "角色名", "position": "女主角|男主角|反派|男配角|女配角|其它角色"}],\n'
            '  "relationships": [{"from": "角色A", "to": "角色B",'
            ' "relation": "2-6字具体关系，从常规关系里选最贴切的，如 君臣/父子/母子/父女/母女/夫妻/兄弟/兄妹/姐弟/姐妹/主仆/师徒/亦师亦友/惺惺相惜/宿敌/敌对/背叛/暗恋/青梅竹马/结义兄弟/先祖与后裔/祭司辅佐首领/托孤之臣/辅政大臣/效忠/利用/追杀/救命恩人",'
            ' "bidirectional": false}]\n'
            "}\n"
            "要求：relation 必须写明两人之间真实的身份关系或戏剧关系，"
            "禁止输出「同场互动」「共同出场」这类只描述同场次数的占位说法；"
            "关系不对等时 bidirectional 为 false，并让 from 指向关系的发起方；"
            "角色名必须与剧本中的称呼完全一致，不要把「双轨节奏」「情绪钩子」这类"
            "结构标签当成角色；只保留剧情中真实成立的关系，最多 60 条。"
        )
        user_prompt = f"【短剧标题】：{title}\n\n【剧本原文】：\n{script}"
        res = self.gateway.call_llm(
            config.get("llm_model") or "",
            sys_prompt,
            user_prompt,
            title,
            str(config.get("director_style") or ""),
            str(config.get("shot_style") or ""),
        )
        parsed = extract_json_object(res)
        relationships = parsed.get("relationships") if isinstance(parsed, dict) else None
        # A same-scene count is not a relation: whatever the model calls one is dropped.
        relationships = [
            edge for edge in (relationships if isinstance(relationships, list) else [])
            if isinstance(edge, dict)
            and str(edge.get("from") or "").strip() and str(edge.get("to") or "").strip()
            and str(edge.get("relation") or "").strip()
            and not any(word in str(edge.get("relation")) for word in ("同场", "共同出场", "共现", "剧情关联", "有关联"))
        ]
        if not relationships:
            raise ValueError("人物关系分析未返回可用结果，请稍后重试")
        roles = parsed.get("roles") if isinstance(parsed, dict) else None

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            current_assets = current.get("assets")
            if not isinstance(current_assets, dict):
                current_assets = {}
                current["assets"] = current_assets
            breakdown = current_assets.get("2_breakdown")
            if not isinstance(breakdown, dict):
                breakdown = {}
            breakdown["relationships"] = relationships
            breakdown["relationships_authored"] = True
            # Only fill roles that the breakdown does not already carry, so a
            # repaired graph never overwrites richer stage-2 casting.
            if isinstance(roles, list) and roles and not breakdown.get("roles"):
                breakdown["roles"] = roles
            current_assets["2_breakdown"] = breakdown
            return current

        updated = self.repo.mutate_task(task_id, mutation)
        if not updated:
            return None
        return compile_writer_dashboard(updated)

    @staticmethod
    def _has_running_generation(task: Dict[str, Any]) -> bool:
        progress = task.get("stage_progress") or {}
        return bool(
            task.get("status") == "running"
            or (task.get("workflow_control") or {}).get("active")
            or (isinstance(progress, dict) and progress.get("status") == "running")
            or any(isinstance(item, dict) and item.get("status") == "running"
                   for item in task.get("episodes") or [])
        )

    def continue_script(self, task_id: str) -> Optional[WriterDashboardResponse]:
        """Write the episodes a truncated screenplay is still missing, in place.

        A project generated before batching stopped at whatever one LLM call could
        emit - 15 episodes of a 30 episode plan.  Regenerating the whole script
        would throw away finished work and invalidate the downstream assets of the
        episodes that are already fine, so the missing episodes are appended and
        only the structural breakdown is recompiled.
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        script = str(assets.get("2") or "")
        if not script.strip():
            raise ValueError("剧本尚未生成，请先执行第 2 阶段")

        # Appending while stage 2 is rewriting assets["2"] would race the generator.
        if self._has_running_generation(task):
            raise ValueError("项目仍有生成任务运行，请等待当前生成结束后再补写剧本")

        existing = self._split_script_by_episode(script)
        requested = episode_target(existing.keys(), config.get("episode_count"))
        missing = [index for index in range(1, requested + 1) if index not in existing]
        if not missing:
            raise ValueError(f"剧本已包含全部 {requested} 集，无需补写")
        # Writing takes minutes; pin the version it is based on so a concurrent
        # script edit is refused instead of being silently overwritten.
        base_source_hash = compile_writer_dashboard(task).source_hash
        if screenwriting.is_usable(screenwriting.state_of(task)):
            # The structured ledger knows every episode's hook and outline, so the
            # gap is written from the same plan instead of a free-text continuation.
            return self._continue_structured_script(task, task_id, missing, requested, base_source_hash)

        title = str(config.get("title_suggestion") or "未命名短剧")
        dir_style = str(config.get("director_style") or "")
        shot_style = str(config.get("shot_style") or "")
        sys_prompt = self._continuation_system_prompt(config, requested)
        director_plan = str(assets.get("1") or "")

        written: Dict[int, str] = dict(existing)
        # Batch by CONTIGUOUS run: chunking [3, 17, 25] positionally would ask for
        # "第3集到第25集" and re-request 20 episodes that already exist.
        for group in self._contiguous_batches(missing, self.SCRIPT_EPISODES_PER_BATCH):
            batch = self._write_script_batch(
                config, title, dir_style, shot_style, sys_prompt,
                director_plan, group[0], group[-1], requested, written, "",
            )
            for number, text in self._split_script_by_episode(batch).items():
                # Never overwrite an episode that already exists.
                if 1 <= number <= requested and number not in written:
                    written[number] = text
        added = sorted(set(written) - set(existing))
        if not added:
            raise ValueError("补写未返回任何新集数，请稍后重试")

        merged_script = "\n\n".join(written[index] for index in sorted(written))
        # Analyse new or not-yet-structured episodes only. Existing scene IDs,
        # edits and linked media remain authoritative. An old task with no
        # breakdown still receives the full analysis rather than losing it.
        old_breakdown = assets.get("2_breakdown")
        old_breakdown = old_breakdown if isinstance(old_breakdown, dict) else {}
        covered = {episode_from_scene_id(str(scene["scene_id"]))
                   for scene in old_breakdown.get("scenes") or []
                   if isinstance(scene, dict) and scene.get("scene_id")}
        analyze = set(added) | (set(existing) - covered)
        added_script = "\n\n".join(written[index] for index in sorted(analyze))
        addition = self._extract_script_breakdown(
            config, title, dir_style, shot_style, added_script, director_plan,
        )
        breakdown = deepcopy(old_breakdown)
        for key in ("scenes", "timeline", "roles", "relationships"):
            if not isinstance(breakdown.get(key), list):
                breakdown[key] = []
        if not isinstance(breakdown.get("production_assets"), dict):
            breakdown["production_assets"] = {}
        for key in ("scenes", "props", "costumes", "effects"):
            if not isinstance(breakdown["production_assets"].get(key), list):
                breakdown["production_assets"][key] = []
        if isinstance(addition, dict):
            # A malformed answer must never insert another copy of an old shot.
            part = {**addition, "scenes": [
                scene for scene in addition.get("scenes") or []
                if isinstance(scene, dict)
                and episode_from_scene_id(str(scene.get("scene_id") or "")) in analyze
            ]}
            self._merge_breakdown_part(
                part, breakdown,
                {str(item.get("name") or "").strip() for item in breakdown["roles"] if isinstance(item, dict)},
                {(str(item.get("from") or "").strip(), str(item.get("to") or "").strip())
                 for item in breakdown["relationships"] if isinstance(item, dict)},
                {key: {str(item.get("name") or "").strip() for item in values if isinstance(item, dict)}
                 for key, values in breakdown["production_assets"].items() if isinstance(values, list)},
            )
            for key, value in addition.items():
                if key not in breakdown:
                    breakdown[key] = deepcopy(value)
        breakdown["scenes"] = reconcile_breakdown_scenes(breakdown["scenes"], merged_script)

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            # Runs inside the row lock: refuse if the screenplay moved underneath us,
            # so a concurrent edit is never clobbered by a stale merge.
            if compile_writer_dashboard(current).source_hash != base_source_hash:
                raise ScriptUpdateConflictError("剧本已在其他页面更新，请刷新后重试补写")
            if self._has_running_generation(current):
                raise ScriptUpdateConflictError("项目已开始生成，请等待结束后再补写，已有剧本未被覆盖")
            current_assets = current.get("assets")
            if not isinstance(current_assets, dict):
                current_assets = {}
                current["assets"] = current_assets
            current_assets["2"] = merged_script
            current_assets["2_breakdown"] = breakdown
            current["scripted_episode_count"] = len(written)
            current_assets["2_writer_dashboard"] = compile_writer_dashboard(current).model_dump(
                mode="json", by_alias=True
            )
            return current

        updated = self.repo.mutate_task(task_id, mutation)
        if not updated:
            return None
        logger.info("[Writer] 补写完成：新增 %s 集，现共 %s/%s 集 (task=%s)",
                    len(added), len(written), requested, task_id)
        return compile_writer_dashboard(updated)

    @staticmethod
    def _contiguous_batches(indexes: List[int], size: int) -> List[List[int]]:
        """Group sorted indexes into runs of consecutive numbers, each at most ``size`` long."""
        batches: List[List[int]] = []
        current: List[int] = []
        for index in sorted(indexes):
            if current and (index != current[-1] + 1 or len(current) >= size):
                batches.append(current)
                current = []
            current.append(index)
        if current:
            batches.append(current)
        return batches

    # ---------------- 阶段2：结构化两段式编剧引擎 (screenwriting-master) ----------------

    def _structured_writer_engine(self, task: Dict[str, Any], config: Dict[str, Any], title: str,
                                  guidance: str = "", progress=None):
        """Bind the structured screenwriting engine to this task's models and Writer persona."""
        system_prompts = screenwriting.writer_system_prompts(
            self._agent_role_prompt(task, AgentRole.WRITER),
            self.get_shanyin_screenplay_skill(),
        )
        return screenwriting.build_engine(
            self.gateway.call_llm, config=config, title=title,
            system_prompt=system_prompts["plan"], system_prompts=system_prompts, guidance=guidance, progress=progress,
        )

    def _run_structured_writer(self, task: Dict[str, Any], config: Dict[str, Any], title: str,
                               dir_style: str, shot_style: str, guidance: str, task_id: Any = None) -> bool:
        """Write the screenplay with the structured engine; ``False`` means "fall back to the text engine"."""
        ep_count = _bounded_episode_count(config.get("episode_count"))
        source_text, source_kind, own_episodes = screenwriting.source_for_task(task)

        def progress(percent: int, label: str) -> None:
            self._progress_step(task, max(8, min(92, percent)), label)

        try:
            engine = self._structured_writer_engine(task, config, title, guidance, progress)
            state = engine.write(
                title=title,
                director_plan=str(task["assets"].get("1") or ""),
                episode_count=ep_count,
                source_text=source_text,
                source_kind=source_kind,
                own_episodes=own_episodes,
            )
        except (ScreenwritingError, ValueError) as error:
            if not screenwriting.fallback_enabled():
                raise
            logger.warning("[Stage2] 结构化编剧引擎失败，回退自由文本引擎: %s: %s", type(error).__name__, error)
            task["assets"].pop(screenwriting.STATE_KEY, None)
            return False
        except Exception as error:  # noqa: BLE001 - provider failures degrade to the legacy path
            if not screenwriting.fallback_enabled():
                raise
            logger.warning("[Stage2] 结构化编剧引擎异常，回退自由文本引擎: %s", type(error).__name__)
            task["assets"].pop(screenwriting.STATE_KEY, None)
            return False

        text, _breakdown = screenwriting.apply_state(task["assets"], state)
        task["scripted_episode_count"] = self._audit_scripted_episodes(text, ep_count, task_id)
        self._progress_step(task, 93, "剧本一致性质检自检")
        task["logs"]["2"] = self.run_real_consistency_check(2, "编剧剧本创作", task["assets"], config, title, task_id=task_id)
        written = screenwriting.written_episode_numbers(state)
        logger.info("[Stage2] 结构化编剧完成：%s 模式，%s/%s 集 (task=%s)", state.get("source_kind"), len(written), ep_count, task_id)
        return True

    def _continue_structured_script(self, task: Dict[str, Any], task_id: str, missing: List[int],
                                    requested: int, base_source_hash: str) -> Optional[WriterDashboardResponse]:
        """Append missing episodes through the structured engine and re-project every artifact."""
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        title = str(config.get("title_suggestion") or "未命名短剧")
        state = screenwriting.state_of(task)
        engine = self._structured_writer_engine(task, config, title)
        updated_state = engine.write_missing(state, missing)

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            if compile_writer_dashboard(current).source_hash != base_source_hash:
                raise ScriptUpdateConflictError("剧本已在其他页面更新，请刷新后重试补写")
            if self._has_running_generation(current):
                raise ScriptUpdateConflictError("项目已开始生成，请等待结束后再补写，已有剧本未被覆盖")
            current_assets = current.setdefault("assets", {})
            text, _breakdown = screenwriting.apply_state(current_assets, updated_state)
            current["scripted_episode_count"] = len(self._script_episode_indexes(text))
            current_assets["2_writer_dashboard"] = compile_writer_dashboard(current).model_dump(mode="json", by_alias=True)
            return current

        updated = self.repo.mutate_task(task_id, mutation)
        if not updated:
            return None
        logger.info("[Writer] 结构化补写完成：新增 %s 集，目标 %s 集 (task=%s)", len(missing), requested, task_id)
        return compile_writer_dashboard(updated)

    def get_screenwriting_state(self, task_id: str) -> Optional[ScreenwritingStateResponse]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return screenwriting.state_response(task)

    def get_screenwriting_episode(self, task_id: str, episode: int) -> Optional[ScreenwritingEpisodeResponse]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        response = screenwriting.episode_response(task, episode)
        if response is None:
            raise LookupError(f"第 {episode} 集没有结构化编剧记录")
        return response

    def preview_screenwriting_prompt(self, task_id: str, episode: int, stage: str) -> Optional[str]:
        """The prompt the structured Writer would send for ``episode`` at ``stage`` — no model call."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        engine = self._structured_writer_engine(task, config, str(config.get("title_suggestion") or "未命名短剧"))
        return engine.dry_run_prompt(state, episode, stage)

    def patch_screenwriting_plan(
        self,
        task_id: str,
        episode: int,
        *,
        base_revision: str,
        operations: List[Dict[str, Any]],
        confirm_invalidate: bool = False,
        owner_user_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Optional[ScreenwritingEpisodeResponse]:
        """Edit one episode's shot plan; only the shots whose content changed get a new visual layer."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        if state.get("stale"):
            raise ScriptUpdateConflictError("剧本正文已被手动修改，结构化分镜规划不再与正文一致；请重新执行第 2 阶段后再编辑")
        entry = (state.get("episodes") or {}).get(str(int(episode)))
        if not isinstance(entry, dict):
            raise LookupError(f"第 {episode} 集没有结构化编剧记录")
        if str(entry.get("plan_revision") or "") != base_revision:
            raise ScriptUpdateConflictError("分镜规划已在其他页面更新，请刷新后重试")
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待当前生成结束后再修改分镜规划")
        plan_scenes = [dict(scene) for scene in ((entry.get("plan") or {}).get("scenes") or []) if isinstance(scene, dict)]
        edited = apply_plan_operations(plan_scenes, operations)  # PlanEditError → 422 at the router
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        engine = self._structured_writer_engine(task, config, str(config.get("title_suggestion") or "未命名短剧"))
        new_state, rewritten = engine.replace_plan(state, episode, edited)  # PlanRejected → 409 at the router
        expected_hash = compile_writer_dashboard(task).source_hash
        dashboard = self.update_script(
            task_id,
            content=screenwriting.render_screenplay(new_state),
            expected_source_hash=expected_hash,
            confirm_invalidate=confirm_invalidate,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
            structured_state=new_state,
            expected_plan_revision=(int(episode), base_revision),
        )
        if dashboard is None:
            return None
        refreshed = self.repo.get_task(task_id)
        return screenwriting.episode_response(refreshed or task, episode, rewritten=rewritten)

    # ---------------- 审核确认与草稿修复：确认绑定规划指纹，草稿修好才能确认 ----------------

    def get_screenwriting_review(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        return {"task_id": task_id, **review.summary(state), "episodes": [review.status_of(state, int(e["episode"])) for e in state.get("ledger") or [] if isinstance(e, dict)]}

    def review_screenwriting_episode(self, task_id: str, episode: int, action: str, *, by: Optional[str] = None) -> Optional[ScreenwritingEpisodeResponse]:
        """Confirm an episode as it stands, or take the confirmation back; neither touches the script."""
        task = self.repo.get_task(task_id)
        if not task:
            return None

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            state = screenwriting.state_of(current)
            if state is None:
                raise LookupError("该任务没有结构化编剧记录")
            new_state = review.confirm(state, episode, by=by) if action == "confirm" else review.reopen(state, episode)
            current["assets"][screenwriting.STATE_KEY] = new_state
            return current

        updated = self.repo.mutate_task(task_id, mutation)
        return screenwriting.episode_response(updated or task, episode)

    def repair_screenwriting_episode(
        self, task_id: str, episode: int, *, confirm_invalidate: bool = False, owner_user_id: Optional[str] = None, is_admin: bool = False,
    ) -> Optional[ScreenwritingEpisodeResponse]:
        """Have the model fix a quarantined draft; a repair that is no better leaves the draft as it was."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待结束后再修复")
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        engine = self._structured_writer_engine(task, config, str(config.get("title_suggestion") or "未命名短剧"))
        try:
            with usage_ledger.bind_task(task_id, "episode_repair"):
                new_state, outcome = engine.repair_episode(state, episode)
        except RepairNotImproved as exc:
            return screenwriting.episode_response(task, episode, repair={"episode": int(episode), "repaired": False, "improved": False, "remaining": exc.reasons})
        dashboard = self.update_script(
            task_id, content=screenwriting.render_screenplay(new_state), expected_source_hash=compile_writer_dashboard(task).source_hash,
            confirm_invalidate=confirm_invalidate, owner_user_id=owner_user_id, is_admin=is_admin, structured_state=new_state,
        )
        if dashboard is None:
            return None
        return screenwriting.episode_response(self.repo.get_task(task_id) or task, episode, repair={**outcome, "improved": True})

    # ---------------- 分集账本操作：人的手直接改账本，模型只在写出新集时参与 ----------------

    def get_ledger(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        return {"task_id": task_id, **ledger_ops.describe(state)}

    def _persist_ledger_change(
        self, task_id: str, task: Dict[str, Any], change: ledger_ops.LedgerChange, *,
        confirm_discard: List[int], confirm_invalidate: bool, write_now: bool,
        owner_user_id: Optional[str], is_admin: bool,
    ) -> Dict[str, Any]:
        """Write the planned episodes a change left unwritten, then store the state as a script revision."""
        unconfirmed = [number for number in change.discarded if number not in set(confirm_discard)]
        if unconfirmed:
            raise ScriptUpdateConflictError(
                "这一步会丢掉已写出的集：" + "、".join(f"第 {n} 集" for n in unconfirmed) + "；在 confirm_discard 里列出它们以确认"
            )
        new_state = change.state
        if write_now:
            unwritten = [int(e["episode"]) for e in new_state.get("ledger") or [] if isinstance(e, dict) and not ledger_ops.is_written(new_state, int(e["episode"]))]
            if unwritten:
                config = task.get("config") if isinstance(task.get("config"), dict) else {}
                engine = self._structured_writer_engine(task, config, str(config.get("title_suggestion") or "未命名短剧"))
                new_state = engine.write_missing(new_state, unwritten)
        expected_hash = compile_writer_dashboard(task).source_hash
        dashboard = self.update_script(
            task_id, content=screenwriting.render_screenplay(new_state), expected_source_hash=expected_hash,
            confirm_invalidate=confirm_invalidate, owner_user_id=owner_user_id, is_admin=is_admin, structured_state=new_state,
        )
        if dashboard is None:
            raise LookupError("任务不存在")

        def align(current: Dict[str, Any]) -> Dict[str, Any]:
            # The ledger, not the rendered text, says how many episodes the project has.
            state = screenwriting.state_of(current)
            if state is not None:
                current.setdefault("config", {})["episode_count"] = len(state.get("ledger") or [])
                current["total_episodes"] = len(state.get("ledger") or [])
            return current

        self.repo.mutate_task(task_id, align)
        return {
            "task_id": task_id,
            "discarded": list(change.discarded), "created": list(change.created), "notes": list(change.notes),
            "renumbered": {str(k): v for k, v in change.renumbered.items() if k != v},
            **ledger_ops.describe(screenwriting.state_of(self.repo.get_task(task_id) or task) or new_state),
        }

    def apply_ledger_operation(
        self, task_id: str, request: LedgerOperationRequest, *, owner_user_id: Optional[str] = None, is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待结束后再改分集")
        op = request.operation
        if op == "split":
            change = ledger_ops.split_episode(state, int(request.episode or 0), int(request.offset or 0), request.title)
        elif op == "move_boundary":
            change = ledger_ops.move_boundary(state, int(request.episode or 0), int(request.offset or 0))
        elif op == "merge_with_next":
            change = ledger_ops.merge_with_next(state, int(request.episode or 0), include_unsplit=request.include_unsplit)
        elif op == "cut_unsplit":
            change = ledger_ops.cut_unsplit(state, int(request.start or 0), int(request.end or 0), request.title)
        elif op == "clear_after":
            change = ledger_ops.clear_after(state, int(request.episode or 0))
        elif op == "create":
            change = ledger_ops.create_episode(state, title=request.title, text=request.text, source_kind=request.source_kind, after=request.after)
        elif op == "move":
            change = ledger_ops.move_episode(state, int(request.episode or 0), after=request.after)
        elif op == "delete":
            change = ledger_ops.delete_episode(state, int(request.episode or 0))
        elif op == "update_own_source":
            change = ledger_ops.update_own_source(state, int(request.episode or 0), text=request.text, source_kind=request.source_kind)
        else:
            raise ledger_ops.LedgerOperationError(f"未知的账本操作：{op}")
        return self._persist_ledger_change(
            task_id, task, change, confirm_discard=request.confirm_discard, confirm_invalidate=request.confirm_invalidate,
            write_now=request.write_now, owner_user_id=owner_user_id, is_admin=is_admin,
        )

    def ledger_source_slice(self, task_id: str, start: int, end: int) -> Optional[Dict[str, Any]]:
        """A stretch of the whole source, so the person sees the text a boundary cuts through."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        text = str(state.get("source_text") or "")
        start = max(0, min(int(start), len(text)))
        end = max(start, min(int(end), len(text)))
        return {"task_id": task_id, "start": start, "end": end, "text": text[start:end]}

    def preview_ledger_impact(self, task_id: str, episodes: List[int]) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        return {"task_id": task_id, "episodes": ledger_ops.impact(state, episodes)}

    def plan_replan_candidate(self, task_id: str, from_episode: int) -> Optional[Dict[str, Any]]:
        """Plan the source again from one episode on, as a candidate the person compares before adopting."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        if state.get(ledger_ops.CANDIDATE_KEY):
            raise ScriptUpdateConflictError("已有一份候选重规划，请先采纳或放弃它")
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        engine = self._structured_writer_engine(task, config, str(config.get("title_suggestion") or "未命名短剧"))
        with usage_ledger.bind_task(task_id, "episode_replan"):
            entries = engine.plan_replan_candidate(state, from_episode)
        new_state = ledger_ops.store_candidate(state, from_episode, entries)

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            live = screenwriting.state_of(current)
            if live is None:
                raise LookupError("该任务没有结构化编剧记录")
            if ledger_ops.layout_revision(live) != new_state[ledger_ops.CANDIDATE_KEY]["layout_revision"]:
                raise ScriptUpdateConflictError("分集账本在规划期间变过，请重新发起")
            live[ledger_ops.CANDIDATE_KEY] = new_state[ledger_ops.CANDIDATE_KEY]
            return current

        self.repo.mutate_task(task_id, mutation)
        return {"task_id": task_id, **ledger_ops.describe(new_state)}

    def adopt_replan_candidate(
        self, task_id: str, request: ReplanAdoptRequest, *, owner_user_id: Optional[str] = None, is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = screenwriting.state_of(task)
        if state is None:
            raise LookupError("该任务没有结构化编剧记录")
        if self._has_running_generation(task):
            raise ScriptUpdateConflictError("项目仍有生成任务运行，请等待结束后再采纳")
        change = ledger_ops.adopt_candidate(state, delete_replaced=request.delete_replaced)
        return self._persist_ledger_change(
            task_id, task, change, confirm_discard=request.confirm_discard, confirm_invalidate=request.confirm_invalidate,
            write_now=request.write_now, owner_user_id=owner_user_id, is_admin=is_admin,
        )

    def discard_replan_candidate(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None

        def mutation(current: Dict[str, Any]) -> Dict[str, Any]:
            live = screenwriting.state_of(current)
            if live is None:
                raise LookupError("该任务没有结构化编剧记录")
            live.pop(ledger_ops.CANDIDATE_KEY, None)
            return current

        updated = self.repo.mutate_task(task_id, mutation)
        return {"task_id": task_id, **ledger_ops.describe(screenwriting.state_of(updated or task) or {})}

    def _continuation_system_prompt(self, config: Dict[str, Any], ep_count: int) -> str:
        """Rebuild the writing rules so appended episodes match the existing ones."""
        shot_cap = max_shot_seconds(str(config.get("video_model") or ""))
        return (
            "Role: AI 专业短剧编剧智能体 (Writer Agent)\n"
            "Methodology: 遵循山音超级编剧大师核心理念。只写摄影机能拍到的画面和能听到的声音，"
            "杜绝任何心理描写和括号暗示，对话高度口语化。\n"
            "每一集都必须按黄金叙事结构落地：前3秒强钩子→交代冲突→压迫升级→反击/反转/情绪爆点→"
            "结尾5秒悬念钩子。\n\n"
            f"【强制分集格式要求】：全剧共 {ep_count} 集，每一集**必须**以独立成行的「第N集 副标题」"
            "作为该集起始分隔标题（务必使用中文'第N集'字样）。"
            "本次是在已有剧本上续写，人物、场景、服装、时间线必须与前文完全连贯，"
            "不要重述前文已经发生的情节。\n\n"
            "【强制分镜格式要求】：每一集内部**必须**再切分为多个镜头，"
            "每个镜头以独立成行的「场景N：地点 时间 内景/外景」开头（N 在本集内从 1 连续编号），"
            "并在该行下一行用「镜头：景别 + 运镜」标注。"
            f"单个镜头时长**不得超过 {shot_cap} 秒**"
            f"（当前视频模型 {config.get('video_model') or '未指定'} 单次生成的上限），"
            "切成几个镜头由你根据戏剧节奏自行判断；只写摄影机拍得到的画面动作与角色对白"
            "（对白用'角色名：台词'格式）。"
        )

    _MAX_SCRIPT_DOCUMENTS = 500
    _MAX_SCRIPT_DOCUMENT_BYTES = 2 * 1024 * 1024

    @staticmethod
    def _script_document_name(value: str) -> str:
        """Keep a plain, extension-bearing file name with no path components."""
        cleaned = str(value or "").replace("\x00", "").strip()
        cleaned = cleaned.replace("\\", "/").split("/")[-1]
        cleaned = re.sub(r'[<>:"|?*\r\n\t]', "", cleaned).strip(" .")[:255]
        if not cleaned:
            cleaned = "script.txt"
        if not cleaned.lower().endswith((".txt", ".md")):
            cleaned = f"{cleaned}.txt"
        return cleaned

    @staticmethod
    def _script_documents(task: Dict[str, Any]) -> List[Dict[str, Any]]:
        assets = task.get("assets")
        if not isinstance(assets, dict):
            assets = {}
            task["assets"] = assets
        documents = assets.get("2_documents")
        if not isinstance(documents, list):
            documents = []
            assets["2_documents"] = documents
        return documents

    @staticmethod
    def _script_document_summary(document: Dict[str, Any]) -> Dict[str, Any]:
        role = str(document.get("role") or "reference")
        order = document.get("order")
        return {
            "id": str(document.get("id") or ""),
            "name": str(document.get("name") or ""),
            "size_bytes": len(str(document.get("content") or "").encode("utf-8")),
            "updated_at": str(document.get("updated_at") or ""),
            "role": role if role in screenwriting.DOCUMENT_ROLES else "reference",
            "source_kind": screenwriting.document_kind(document) if role in ("source", "episode") else None,
            "order": order if isinstance(order, int) and not isinstance(order, bool) else None,
        }

    @staticmethod
    def _validate_document_role(role: Optional[str], source_kind: Optional[str]) -> None:
        if role is not None and role not in screenwriting.DOCUMENT_ROLES:
            raise ValueError("文件角色只能是 reference（参考资料）、source（整本源文）或 episode（逐集原文）")
        if source_kind is not None and source_kind not in screenwriting.DOCUMENT_KINDS:
            raise ValueError("源文体裁只能是 novel（小说）或 screenplay（成品剧本）")

    def _annotate_library_episodes(self, task: Dict[str, Any], documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add each own-source document's episode number, as the ledger assigned it; ``None`` until stage 2 ran."""
        state = screenwriting.state_of(task)
        by_name: Dict[str, int] = {}
        for entry in (state or {}).get("ledger") or []:
            if isinstance(entry, dict) and entry.get("source_origin") == "own" and entry.get("source_name"):
                by_name.setdefault(str(entry["source_name"]), int(entry.get("episode") or 0))
        own_in_order = screenwriting.ordered_documents(documents, "episode")
        positions = {str(item.get("id")): index + 1 for index, item in enumerate(own_in_order)}
        summaries = []
        for item in documents:
            if not isinstance(item, dict):
                continue
            summary = self._script_document_summary(item)
            if summary["role"] == "episode":
                summary["position"] = positions.get(summary["id"])
                summary["episode"] = by_name.get(summary["name"])
            summaries.append(summary)
        return summaries

    def list_script_documents(self, task_id: str) -> Optional[List[Dict[str, Any]]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return self._annotate_library_episodes(task, self._script_documents(task))

    def get_script_document(self, task_id: str, document_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        for document in self._script_documents(task):
            if isinstance(document, dict) and str(document.get("id")) == document_id:
                return {
                    **self._script_document_summary(document),
                    "content": str(document.get("content") or ""),
                }
        return None

    def create_script_document(
        self,
        task_id: str,
        *,
        name: str,
        content: str,
        role: Optional[str] = None,
        source_kind: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        safe_name = self._script_document_name(name)
        safe_content = str(content or "").replace("\x00", "")
        if len(safe_content.encode("utf-8")) > self._MAX_SCRIPT_DOCUMENT_BYTES:
            raise ValueError("剧本文件不能超过 2 MB")
        self._validate_document_role(role, source_kind)
        # An unnamed role is read from the file name; an unnamed genre from the text.
        chosen_role = role or screenwriting.document_role_for_name(safe_name)
        chosen_kind = source_kind if chosen_role != "reference" else None
        if chosen_role != "reference" and not chosen_kind:
            chosen_kind = "screenplay" if screenwriting.detect_source_kind(safe_content) == "screenplay" else "novel"
        timestamp = datetime.now(timezone.utc).isoformat()

        def mutation(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            documents = self._script_documents(task)
            if len(documents) >= self._MAX_SCRIPT_DOCUMENTS:
                raise ValueError("剧本文库已达到 500 个文件上限")
            document = {
                "id": uuid.uuid4().hex,
                "name": safe_name,
                "content": safe_content,
                "updated_at": timestamp,
                "role": chosen_role,
                "source_kind": chosen_kind,
            }
            documents.append(document)
            if chosen_role != "reference":
                screenwriting.mark_stale(task, f"剧本文库新增了{'整本源文' if chosen_role == 'source' else '逐集原文'}《{safe_name}》，请重新执行第 2 阶段")
            return document

        document = self.repo.mutate_task(task_id, mutation)
        return self._script_document_summary(document) if document else None

    def update_script_document(
        self,
        task_id: str,
        document_id: str,
        *,
        name: Optional[str] = None,
        content: Optional[str] = None,
        role: Optional[str] = None,
        source_kind: Optional[str] = None,
        order: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        safe_name = self._script_document_name(name) if name is not None else None
        safe_content = str(content).replace("\x00", "") if content is not None else None
        if safe_content is not None and len(safe_content.encode("utf-8")) > self._MAX_SCRIPT_DOCUMENT_BYTES:
            raise ValueError("剧本文件不能超过 2 MB")
        self._validate_document_role(role, source_kind)
        if order is not None and not 0 <= int(order) <= self._MAX_SCRIPT_DOCUMENTS:
            raise ValueError("文件顺序越界")
        timestamp = datetime.now(timezone.utc).isoformat()

        def mutation(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            for document in self._script_documents(task):
                if not isinstance(document, dict) or str(document.get("id")) != document_id:
                    continue
                was_feeding = document.get("role") in ("source", "episode")
                if safe_name is not None:
                    document["name"] = safe_name
                if safe_content is not None:
                    document["content"] = safe_content
                if role is not None:
                    document["role"] = role
                if source_kind is not None:
                    document["source_kind"] = source_kind
                if order is not None:
                    document["order"] = int(order)
                if document.get("role") == "reference":
                    document["source_kind"] = None
                elif not document.get("source_kind"):
                    document["source_kind"] = "screenplay" if screenwriting.detect_source_kind(str(document.get("content") or "")) == "screenplay" else "novel"
                document["updated_at"] = timestamp
                # Anything that changes what stage 2 would read from makes the written plan stale.
                feeds_now = document.get("role") in ("source", "episode")
                if (was_feeding or feeds_now) and (safe_content is not None or role is not None or source_kind is not None or order is not None):
                    screenwriting.mark_stale(task, f"剧本文库的《{document.get('name')}》已变更，请重新执行第 2 阶段")
                return document
            return None

        document = self.repo.mutate_task(task_id, mutation)
        if not document:
            return None
        return {**self._script_document_summary(document), "content": str(document.get("content") or "")}

    def delete_script_document(self, task_id: str, document_id: str) -> Optional[bool]:
        def mutation(task: Dict[str, Any]) -> bool:
            documents = self._script_documents(task)
            remaining = [
                item for item in documents
                if not (isinstance(item, dict) and str(item.get("id")) == document_id)
            ]
            removed = len(remaining) != len(documents)
            if removed and any(
                isinstance(item, dict) and str(item.get("id")) == document_id and item.get("role") in ("source", "episode")
                for item in documents
            ):
                screenwriting.mark_stale(task, "剧本文库删除了一份源文，请重新执行第 2 阶段")
            task["assets"]["2_documents"] = remaining
            return removed

        return self.repo.mutate_task(task_id, mutation)

    # ---------------- Writer board: overview, story events, cast, versions ----------------

    def _mutate_breakdown(self, task_id: str, change) -> Optional[WriterDashboardResponse]:
        """Apply ``change(task, breakdown)`` to the stage-2 breakdown and return the rebuilt dashboard."""

        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.get("assets")
            if not isinstance(assets, dict):
                assets = {}
                task["assets"] = assets
            breakdown = assets.get("2_breakdown")
            if not isinstance(breakdown, dict):
                breakdown = {}
            change(task, breakdown)
            assets["2_breakdown"] = breakdown
            return task

        task = self.repo.mutate_task(task_id, mutation)
        return compile_writer_dashboard(task) if task else None

    def update_overview(self, task_id: str, fields: Dict[str, Optional[str]]) -> Optional[WriterDashboardResponse]:
        """Edit the project overview by hand; the structured state's copy follows."""
        clean = {key: str(value).strip() for key, value in fields.items() if value is not None}

        def change(task: Dict[str, Any], breakdown: Dict[str, Any]) -> None:
            overview = breakdown.get("overview") if isinstance(breakdown.get("overview"), dict) else {}
            overview.update(clean)
            breakdown["overview"] = overview
            state = screenwriting.state_of(task)
            if state is not None:
                current = state.get("overview") if isinstance(state.get("overview"), dict) else {}
                current.update(clean)
                state["overview"] = current

        return self._mutate_breakdown(task_id, change)

    def regenerate_overview(self, task_id: str) -> Optional[WriterDashboardResponse]:
        """Tell the overview again from the project's source (or its plan) with one model call."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        title = str(config.get("title_suggestion") or "未命名短剧")
        source_text, source_kind, own_episodes = screenwriting.source_for_task(task)
        if source_text or own_episodes:
            source = "\n\n".join(part for part in [source_text or "", *[entry["text"] for entry in own_episodes]] if part.strip())
            kind = source_kind or "novel"
        else:
            source, kind = str(assets.get("1") or assets.get("2") or ""), "outline"
        if not source.strip():
            raise ValueError("没有可供提炼概述的内容：请先上传源文，或完成总导演策划")
        engine = self._structured_writer_engine(task, config, title)
        overview = engine.refresh_overview(source=source, kind=kind, title_hint=title)
        if not any(str(overview.get(key) or "").strip() for key in ("synopsis", "genre", "theme", "world_setting")):
            raise ValueError("模型没有返回可用的概述，请稍后重试")

        def change(current: Dict[str, Any], breakdown: Dict[str, Any]) -> None:
            breakdown["overview"] = {**(breakdown.get("overview") if isinstance(breakdown.get("overview"), dict) else {}), **overview}
            state = screenwriting.state_of(current)
            if state is not None:
                state["overview"] = {**(state.get("overview") if isinstance(state.get("overview"), dict) else {}), **overview}

        return self._mutate_breakdown(task_id, change)

    def update_timeline(self, task_id: str, events: List[Dict[str, Any]]) -> Optional[WriterDashboardResponse]:
        """Replace the story event timeline with what the person arranged; it then stops following the ledger."""

        def change(_task: Dict[str, Any], breakdown: Dict[str, Any]) -> None:
            breakdown["timeline"] = [dict(event) for event in events]
            breakdown["timeline_authored"] = True

        return self._mutate_breakdown(task_id, change)

    def update_roles(self, task_id: str, roles: List[Dict[str, Any]], hidden: List[str]) -> Optional[WriterDashboardResponse]:
        """Set the cast: each role's position, new names, and names kept out of the cast."""
        positions = {str(role.get("name")).strip(): str(role.get("position") or "其它角色").strip() for role in roles if str(role.get("name") or "").strip()}
        requested_hidden = {str(name).strip() for name in hidden if str(name).strip()}

        def change(task: Dict[str, Any], breakdown: Dict[str, Any]) -> None:
            # Names removed earlier stay removed; a name listed again comes back.
            previous_hidden = {str(name) for name in (breakdown.get("hidden_roles") or []) if str(name).strip()}
            hidden_names = sorted((previous_hidden | requested_hidden) - set(positions))
            breakdown["roles"] = [{"name": name, "position": position} for name, position in positions.items()]
            breakdown["role_positions"] = dict(positions)
            breakdown["hidden_roles"] = hidden_names
            state = screenwriting.state_of(task)
            if state is not None:
                inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
                characters = inventory.get("characters") if isinstance(inventory.get("characters"), dict) else {}
                for name, position in positions.items():
                    entry = characters.get(name) if isinstance(characters.get(name), dict) else {"description": "需补充外貌与服装细节", "voice_style": ""}
                    entry["position"] = position
                    characters[name] = entry
                for name in hidden_names:
                    characters.pop(name, None)
                inventory["characters"] = characters
                state["inventory"] = inventory

        return self._mutate_breakdown(task_id, change)

    script_version_max_entries = 20

    def list_script_versions(self, task_id: str) -> Optional[List[Dict[str, Any]]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return version_summaries(task.get("assets") if isinstance(task.get("assets"), dict) else {})

    def save_script_version(self, task_id: str, label: str = "") -> Optional[WriterDashboardResponse]:
        """Keep a named snapshot of the screenplay, its breakdown and its structured state."""

        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.setdefault("assets", {})
            config = task.get("config") if isinstance(task.get("config"), dict) else {}
            dashboard = compile_writer_dashboard(task)
            if not dashboard.script.strip():
                raise ValueError("剧本尚未生成，没有可保存的版本")
            versions = [item for item in (assets.get("2_versions") if isinstance(assets.get("2_versions"), list) else []) if isinstance(item, dict)]
            versions.append({
                "version_id": uuid.uuid4().hex[:12],
                "label": str(label or "").strip()[:120] or f"版本 {len(versions) + 1}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_hash": dashboard.source_hash,
                "episode_count": dashboard.stats.total_episodes,
                "scene_count": dashboard.stats.scene_count,
                "payload": {
                    "2": str(assets.get("2") or ""),
                    "2_breakdown": deepcopy(assets.get("2_breakdown")) if isinstance(assets.get("2_breakdown"), dict) else None,
                    screenwriting.STATE_KEY: deepcopy(assets.get(screenwriting.STATE_KEY)) if isinstance(assets.get(screenwriting.STATE_KEY), dict) else None,
                    "script_name": str(config.get("script_name") or ""),
                },
            })
            assets["2_versions"] = versions[-self.script_version_max_entries:]
            return task

        task = self.repo.mutate_task(task_id, mutation)
        return compile_writer_dashboard(task) if task else None

    def restore_script_version(
        self, task_id: str, version_id: str, *, expected_source_hash: str, confirm_invalidate: bool,
        owner_user_id: Optional[str], is_admin: bool,
    ) -> Optional[WriterDashboardResponse]:
        """Bring a saved version back as the current screenplay (the same path as applying an edited script)."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        version = next((item for item in (assets.get("2_versions") or []) if isinstance(item, dict) and item.get("version_id") == version_id), None)
        if version is None:
            raise ValueError("没有这个版本")
        payload = version.get("payload") if isinstance(version.get("payload"), dict) else {}
        state = payload.get(screenwriting.STATE_KEY) if isinstance(payload.get(screenwriting.STATE_KEY), dict) else None
        breakdown = payload.get("2_breakdown") if isinstance(payload.get("2_breakdown"), dict) else None
        dashboard = self.update_script(
            task_id, content=str(payload.get("2") or ""), file_name=str(payload.get("script_name") or "") or None,
            expected_source_hash=expected_source_hash, confirm_invalidate=confirm_invalidate,
            owner_user_id=owner_user_id, is_admin=is_admin, structured_state=state, breakdown_override=breakdown,
        )
        return dashboard

    def update_relationships(
        self,
        task_id: str,
        relationships: List[Dict[str, Any]],
    ) -> Optional[WriterDashboardResponse]:
        """Atomically replace the user-editable character relationship list."""

        def mutation(task: Dict[str, Any]) -> Dict[str, Any]:
            assets = task.get("assets")
            if not isinstance(assets, dict):
                assets = {}
                task["assets"] = assets
            breakdown = assets.get("2_breakdown")
            if not isinstance(breakdown, dict):
                breakdown = {}
            breakdown["relationships"] = relationships
            breakdown["relationships_authored"] = True
            assets["2_breakdown"] = breakdown
            return task

        task = self.repo.mutate_task(task_id, mutation)
        if not task:
            return None
        return compile_writer_dashboard(task)

    def update_script(
        self,
        task_id: str,
        *,
        content: str,
        file_name: Optional[str] = None,
        expected_source_hash: str,
        confirm_invalidate: bool = False,
        owner_user_id: Optional[str] = None,
        is_admin: bool = False,
        structured_state: Optional[Dict[str, Any]] = None,
        expected_plan_revision: Optional[tuple] = None,
        breakdown_override: Optional[Dict[str, Any]] = None,
    ) -> Optional[WriterDashboardResponse]:
        """Atomically apply a user-authored screenplay revision without calling an LLM.

        ``breakdown_override`` is a breakdown to store as is (a restored version brings its
        own, edits included) instead of deriving one from the state.

        ``structured_state`` is the structured screenwriting state a plan edit rendered
        ``content`` from: it is stored alongside the text and its breakdown is derived
        from it. Without it a changed text marks any existing structured state stale.

        A changed screenplay invalidates every later production stage. Existing media
        is never silently discarded: projects with derived work require explicit
        confirmation and their previous active state is retained until explicit deletion.
        """

        def stage_key(value: object, *, minimum: int) -> bool:
            match = re.match(r"^([0-9]+)(?:$|_)", str(value))
            return bool(match and minimum <= int(match.group(1)) <= 8)

        def mutate(task: Dict[str, Any]) -> WriterDashboardResponse:
            if not is_admin:
                owner = str(task.get("owner_user_id") or "")
                if not owner_user_id or owner != str(owner_user_id):
                    raise ScriptUpdateTaskNotFoundError("任务不存在")

            current_dashboard = compile_writer_dashboard(task)
            if current_dashboard.source_hash != expected_source_hash.lower():
                raise ScriptUpdateConflictError("剧本已在其他页面更新，请刷新后再保存")

            assets = task.setdefault("assets", {})
            config = task.setdefault("config", {})
            old_content = str(assets.get("2") or "")
            old_file_name = str(config.get("script_name") or "")
            next_file_name = file_name if file_name is not None else old_file_name
            content_changed = content != old_content
            file_name_changed = next_file_name != old_file_name
            # A plan edit can leave the rendered text identical (it changed a field the
            # text does not show, e.g. the source anchor); the new structured state must
            # still be stored, so it counts as a change of its own.
            if not content_changed and not file_name_changed and structured_state is None and breakdown_override is None:
                return current_dashboard
            previous_breakdown = deepcopy(assets.get("2_breakdown")) if isinstance(assets.get("2_breakdown"), dict) else None

            if structured_state is not None and expected_plan_revision is not None:
                plan_episode, plan_revision = expected_plan_revision
                current_state = screenwriting.state_of(task) or {}
                current_entry = (current_state.get("episodes") or {}).get(str(int(plan_episode))) or {}
                if str(current_entry.get("plan_revision") or "") != plan_revision:
                    raise ScriptUpdateConflictError("分镜规划已在其他页面更新，请刷新后重试")
                # Cast and scene / prop references are not rendered into the text, so an
                # edit to them leaves ``content`` identical while the breakdown that stage 3+
                # consumed has changed. The plan revision is the honest change signal.
                next_entry = (structured_state.get("episodes") or {}).get(str(int(plan_episode))) or {}
                if str(next_entry.get("plan_revision") or "") != plan_revision:
                    content_changed = True

            episodes = task.get("episodes") if isinstance(task.get("episodes"), list) else []
            stage_progress = task.get("stage_progress")
            actively_running = (
                task.get("status") == "running"
                or (
                    isinstance(stage_progress, dict)
                    and stage_progress.get("status") == "running"
                )
            ) or any(
                isinstance(episode, dict) and episode.get("status") == "running"
                for episode in episodes
            )
            if actively_running:
                raise ScriptUpdateConflictError(
                    "项目仍有生成任务运行，请等待当前生成结束后再修改剧本"
                )

            downstream_asset_keys = [key for key in assets if stage_key(key, minimum=3)]
            logs = task.setdefault("logs", {})
            downstream_log_keys = [key for key in logs if stage_key(key, minimum=3)]
            has_produced_episodes = any(
                isinstance(episode, dict)
                and (
                    episode.get("status") not in {None, "idle"}
                    or bool(episode.get("shots"))
                    or bool(episode.get("video_url"))
                    or bool(episode.get("summary"))
                )
                for episode in episodes
            )
            has_outputs = any(task.get(key) for key in ("video_url", "short_link", "pr_content"))
            try:
                current_stage = int(task.get("current_stage", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                current_stage = 0
            has_later_stage = current_stage > 2
            requires_archive = content_changed and bool(
                downstream_asset_keys
                or downstream_log_keys
                or has_produced_episodes
                or has_outputs
                or has_later_stage
                or task.get("status") == "completed"
            )
            if requires_archive and not confirm_invalidate:
                raise ScriptUpdateConflictError(
                    "应用新剧本会归档当前角色、分镜或成片；确认后可安全创建新版本"
                )

            if requires_archive:
                archive = {
                    "archive_id": uuid.uuid4().hex,
                    "source_hash": current_dashboard.source_hash,
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                    "script_file_name": old_file_name or None,
                    "assets": {
                        key: deepcopy(value)
                        for key, value in assets.items()
                        if key in {"2", "2_breakdown", screenwriting.STATE_KEY} or key in downstream_asset_keys
                    },
                    "logs": {
                        key: deepcopy(value)
                        for key, value in logs.items()
                        if stage_key(key, minimum=2)
                    },
                    "episodes": deepcopy(episodes),
                    "workflow": {
                        "current_stage": task.get("current_stage"),
                        "stage_name": task.get("stage_name"),
                        "status": task.get("status"),
                        "video_url": task.get("video_url"),
                        "short_link": task.get("short_link"),
                        "pr_content": task.get("pr_content"),
                    },
                }
                archives = task.get("script_archives")
                if not isinstance(archives, list):
                    archives = []
                archive["payload_bytes"] = len(
                    json.dumps(archive, ensure_ascii=False, sort_keys=True).encode("utf-8")
                )
                candidate_archives = [*archives, archive]
                archive_total_bytes = len(
                    json.dumps(
                        candidate_archives,
                        ensure_ascii=False,
                        indent=4,
                    ).encode("utf-8")
                )
                if len(candidate_archives) > self.script_archive_max_entries:
                    raise ScriptUpdateConflictError(
                        "剧本历史归档容量上限已达到，当前剧本和下游资产均未修改；"
                        "请先导出并删除不再需要的项目历史后重试"
                    )
                if archive_total_bytes > self.script_archive_max_total_bytes:
                    raise ScriptUpdateConflictError(
                        "剧本历史归档容量上限已达到，当前剧本和下游资产均未修改；"
                        "请先导出并删除不再需要的项目历史后重试"
                    )
                task["script_archives"] = candidate_archives
                task["script_archive_retention"] = {
                    "policy": "bounded_reject_before_write",
                    "max_entries": self.script_archive_max_entries,
                    "max_total_bytes": self.script_archive_max_total_bytes,
                    "current_entries": len(candidate_archives),
                    "current_total_bytes": archive_total_bytes,
                    "on_limit": "reject_with_409",
                }


            if content_changed:
                for key in [*downstream_asset_keys, "2_breakdown", "2_writer_dashboard"]:
                    assets.pop(key, None)
                if structured_state is None:
                    screenwriting.mark_stale(task, "剧本正文已手动修改，结构化分镜规划不再与正文一致")
                for key in list(logs):
                    if stage_key(key, minimum=2):
                        logs.pop(key, None)

                parsed_episodes = split_episodes(content, max_episodes=EPISODE_COUNT_MAX)
                task["episodes"] = [
                    {
                        "index": episode["index"],
                        "title": episode["title"],
                        "script": episode["script"],
                        "status": "idle",
                        "shots": [],
                        "video_url": None,
                        "summary": "",
                    }
                    for episode in parsed_episodes
                ]
                task["total_episodes"] = len(parsed_episodes)
                config["episode_count"] = len(parsed_episodes)
                task["current_episode"] = 0
                task["current_stage"] = 2
                task["stage_name"] = "编剧剧本创作"
                task["status"] = "idle"
                task["stage_progress"] = None
                task["fail_reason"] = None
                task["video_url"] = None
                task["short_link"] = None
                task["pr_content"] = None

            if structured_state is not None:
                # The caller rendered ``content`` from this state, so both are stored
                # together and the breakdown is derived from the state, not re-analysed;
                # what a person authored on the previous breakdown is carried over.
                assets[screenwriting.STATE_KEY] = structured_state
                assets["2_breakdown"] = screenwriting.carry_authored(previous_breakdown, render_breakdown(structured_state))
            if breakdown_override is not None:
                assets["2_breakdown"] = deepcopy(breakdown_override)

            assets["2"] = content
            config["script_content"] = content
            if file_name is not None:
                config["script_name"] = file_name
            try:
                script_revision = int(task.get("script_revision", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                script_revision = 0
            task["script_revision"] = max(0, script_revision) + 1

            dashboard = compile_writer_dashboard(task)
            assets["2_writer_dashboard"] = dashboard.model_dump(mode="json", by_alias=True)
            return dashboard

        try:
            return self.repo.mutate_task(task_id, mutate)
        except ScriptUpdateTaskNotFoundError:
            return None

    def get_character_dashboard(self, task_id: str) -> Optional[CharacterDashboardResponse]:
        """Compile persisted Stage 3 assets into the stable five-view contract."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return compile_character_dashboard(task)

    # ---------------- 单个数字演员重新生成设定集 ----------------

    #: 角色重新生成成功后调用 (task, name)；drama_api 把它接到资产库同步上，服务本身不碰资产库。
    character_regenerated_hook: Optional[Callable[[Dict[str, Any], str], Any]] = None

    def regenerate_character(
        self, task_id: str, name: str, *, mode: str = "sheet", background: bool = True,
    ) -> Optional[CharacterDashboardResponse]:
        """为一名角色重新出一张设定集(付费)，以它现在的主肖像为身份参考，通过质检才替换旧图。

        不重跑第 3 阶段、不动其他角色；后台跑完前看板里该角色标着 regenerating。
        失败时旧图原样保留，失败原因写进 regeneration_error。
        ``mode="hd"`` 不重出设定集，只用现有图做身份参考补出高清的六个身份视图(两张付费图)。
        ``mode="details"`` 只把补位裁切的元素/细节格真正画出来(一到两张付费图)。
        """
        name = (name or "").strip()
        if mode not in {"sheet", "hd", "details"}:
            raise ValueError("重新生成方式只能是 sheet、hd 或 details")

        def claim(task: Dict[str, Any]) -> Dict[str, Any]:
            if self._has_running_generation(task):
                raise ValueError("任务正在执行阶段，等它结束后再重新生成角色")
            assets = task.setdefault("assets", {})
            if not any(
                isinstance(item, dict) and str(item.get("name") or "").strip() == name
                for item in assets.get("3_characters") or []
            ):
                raise LookupError(f"没有名为「{name}」的角色")
            progress = assets.setdefault(REGENERATION_KEY, {})
            if character_regenerating(progress.get(name)):
                raise ValueError(f"「{name}」正在重新生成，请稍候")
            progress[name] = {"status": "running", "mode": mode, "started_epoch": time.time()}
            assets["3_character_dashboard"] = compile_character_dashboard(task).model_dump(mode="json", by_alias=True)
            return task

        try:
            claimed = self.repo.mutate_task(task_id, claim)
        except LookupError as exc:
            raise ValueError(str(exc)) from exc
        if not claimed:
            return None
        if background:
            threading.Thread(
                target=self._regenerate_character_worker, args=(task_id, name, mode), daemon=True,
                name=f"regen-character-{task_id[:8]}",
            ).start()
        else:
            self._regenerate_character_worker(task_id, name, mode)
        return self.get_character_dashboard(task_id)

    def _apply_hd_identity_views(
        self, *, name: str, desc: str, image_model: str, dir_style: str, references: list, cell_paths: list,
    ) -> tuple[list, set[str]]:
        """出头像三联与全身三联，切成高清的六个身份视图存进同一目录；返回 (全部格子路径, 换成高清的格子)。"""
        by_cell = actor_sheet_cell_paths(list(cell_paths))
        directory = Path(next(iter(by_cell.values()))).parent if by_cell else None
        if directory is None:
            return list(cell_paths), set()

        def generate(prompt: str, refs: list, size: str) -> str | None:
            url, _ = self.gateway.generate_image(image_model, prompt, ref_images=refs, size=size, enhance_prompt=False)
            return url

        def load(url: str) -> bytes:
            import io
            buffer = io.BytesIO()
            storyboard_assets_open_image(url).save(buffer, format="PNG")
            return buffer.getvalue()

        views = generate_hd_views(
            generate=generate, load=load, name=name, desc=desc, style=dir_style,
            references=[ref for ref in references if ref],
        )
        for cell, image in views.items():
            by_cell[cell] = save_actor_cell(image, directory, cell)
        ordered = [by_cell[cell] for cell in ACTOR_SHEET_CELL_ORDER if cell in by_cell]
        if views:
            logger.info("[CharacterHD] %s 高清身份视图 %s 张", name, len(views))
        return ordered, set(views)

    @staticmethod
    def _actor_cell_records(cell_paths: list, derived: Dict[str, str], hd_cells: set) -> tuple[list, list]:
        """格子文件 → (sheet_cells 记录, 五个身份锚点 views)；地址按实际文件算(内容哈希文件名，不吃旧缓存)。"""
        urls = {
            cell: media_compositor.public_url(
                os.path.relpath(str(path), media_compositor.MEDIA_DIR).replace(os.sep, "/")
            )
            for cell, path in actor_sheet_cell_paths(cell_paths).items()
        }
        cells = [
            {"cell": cell, "image_url": urls[cell],
             **({"derived_from": derived[cell]} if cell in derived else {}),
             **({"hd": True} if cell in hd_cells else {})}
            for cell in ACTOR_SHEET_CELL_ORDER if cell in urls
        ]
        views = [{"view": view, "image_url": urls[view]} for view in IDENTITY_VIEW_ORDER if view in urls]
        return cells, views

    def _apply_detail_fill(
        self, *, name: str, desc: str, image_model: str, dir_style: str, references: list,
        cell_paths: list, cells: list,
    ) -> tuple[list, set[str]]:
        """把补位格真正画出来，存进同一目录；返回 (全部格子路径, 换成补画的格子)。"""
        by_cell = actor_sheet_cell_paths(list(cell_paths))
        directory = Path(next(iter(by_cell.values()))).parent if by_cell else None
        if directory is None:
            return list(cell_paths), set()

        def generate(prompt: str, refs: list, size: str) -> str | None:
            url, _ = self.gateway.generate_image(image_model, prompt, ref_images=refs, size=size, enhance_prompt=False)
            return url

        def load(url: str) -> bytes:
            import io
            buffer = io.BytesIO()
            storyboard_assets_open_image(url).save(buffer, format="PNG")
            return buffer.getvalue()

        filled = generate_detail_cells(
            generate=generate, load=load, cells=cells, name=name, desc=desc, style=dir_style,
            references=[ref for ref in references if ref],
        )
        for cell, image in filled.items():
            by_cell[cell] = save_actor_cell(image, directory, cell)
        if filled:
            logger.info("[CharacterDetails] %s 补画细节格 %s 张", name, len(filled))
        return [by_cell[cell] for cell in ACTOR_SHEET_CELL_ORDER if cell in by_cell], set(filled)

    def _regenerate_hd_views(self, record: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """只补高清身份视图：用现有主肖像、正面全身、正脸做参考出两张三联，替换六个身份格。"""
        return self._regenerate_cells(record, config, "hd")

    def _regenerate_cells(self, record: Dict[str, Any], config: Dict[str, Any], mode: str) -> Dict[str, Any]:
        """不重出设定集，只替换一部分格子：``hd`` 换六个身份视图，``details`` 把补位格真正画出来。"""
        media_root = Path(media_compositor.MEDIA_DIR).resolve()

        def local(url: str) -> Path | None:
            relative = url.split(settings.MEDIA_PREFIX, 1)[-1] if settings.MEDIA_PREFIX in url else ""
            path = (media_root / relative).resolve() if relative else None
            return path if path and path.is_file() and media_root in path.parents else None

        cells = [item for item in record.get("sheet_cells") or [] if isinstance(item, dict)]
        paths = [path for item in cells if (path := local(str(item.get("image_url") or "")))]
        if not paths:
            return {}
        by_key = {str(item.get("cell")): item for item in cells}
        references = []
        reference_keys = ("portrait", "front", "face_front") if mode == "hd" else ("portrait", "full_body", "front")
        for key in reference_keys:
            path = local(str((by_key.get(key) or {}).get("image_url") or ""))
            if path:
                references.append(self._reference_image_uri(path.read_bytes(), "image/png"))
        common = dict(
            name=str(record.get("name") or ""),
            desc=str(record.get("desc") or record.get("description") or ""),
            image_model=str(config.get("image_model") or ""),
            dir_style=str(config.get("director_style") or "真人电影写实"),
            references=references, cell_paths=paths,
        )
        if mode == "details":
            missing = fillable(key for key, item in by_key.items() if item.get("derived_from"))
            if not missing:
                return {}
            ordered, replaced = self._apply_detail_fill(**common, cells=missing)
            hd_cells: set[str] = set()
        else:
            ordered, replaced = self._apply_hd_identity_views(**common)
            hd_cells = replaced
        if not replaced:
            return {}
        quality = validate_actor_sheet_images(ordered)
        if not quality.passed:
            return {}
        # 没换的格子沿用原地址；换成高清的格子按实际文件算出新地址(内容哈希文件名，浏览器不会读到旧缓存)。
        urls = {
            cell: (
                media_compositor.public_url(os.path.relpath(str(Path(path).resolve()), str(media_root)).replace(os.sep, "/"))
                if cell in replaced else str((by_key.get(cell) or {}).get("image_url") or "")
            )
            for cell, path in actor_sheet_cell_paths(ordered).items()
        }
        derived = {key: item.get("derived_from") for key, item in by_key.items() if item.get("derived_from")}
        return {
            "sheet": record.get("sheet"),
            "cells": [
                {"cell": cell, "image_url": urls[cell],
                 **({"derived_from": derived[cell]} if cell in derived and cell not in replaced else {}),
                 **({"hd": True} if cell in hd_cells or (by_key.get(cell) or {}).get("hd") else {})}
                for cell in ACTOR_SHEET_CELL_ORDER if cell in urls
            ],
            "views": [{"view": view, "image_url": urls[view]} for view in IDENTITY_VIEW_ORDER if view in urls],
            "quality": quality.model_dump(),
            "error": None,
        }

    def _character_identity_reference(self, record: Dict[str, Any]) -> str | None:
        """角色现在的主肖像(或正脸)做身份参考：本地文件内联成 data URI，供应商取不到 localhost。"""
        cells = {str(item.get("cell")): str(item.get("image_url") or "") for item in record.get("sheet_cells") or [] if isinstance(item, dict)}
        views = {str(item.get("view")): str(item.get("image_url") or "") for item in record.get("views") or [] if isinstance(item, dict)}
        for url in (cells.get("portrait"), views.get("face_front"), views.get("front")):
            if not url:
                continue
            relative = url.split(settings.MEDIA_PREFIX, 1)[-1] if settings.MEDIA_PREFIX in url else ""
            path = (Path(media_compositor.MEDIA_DIR) / relative).resolve() if relative else None
            if path and path.is_file() and Path(media_compositor.MEDIA_DIR).resolve() in path.parents:
                return self._reference_image_uri(path.read_bytes(), "image/png")
        return None

    def _regenerate_character_worker(self, task_id: str, name: str, mode: str = "sheet") -> None:
        task = self.repo.get_task(task_id)
        error = ""
        result: Dict[str, Any] = {}
        try:
            if not task:
                raise RuntimeError("任务不存在")
            assets = task.get("assets") or {}
            record = next(
                item for item in assets.get("3_characters") or []
                if isinstance(item, dict) and str(item.get("name") or "").strip() == name
            )
            config = task.get("config") or {}
            if mode == "hd":
                result = self._regenerate_hd_views(record, config)
                if not result:
                    raise RuntimeError(f"角色「{name}」高清身份视图没有生成成功，已保留原图")
                raise _HdDone(result)
            if mode == "details":
                result = self._regenerate_cells(record, config, "details")
                if not result:
                    raise RuntimeError(f"角色「{name}」没有需要补画的细节格，或补画没有成功，已保留原图")
                raise _HdDone(result)
            reference = self._character_identity_reference(record)
            authorized = self.gateway.resolve_authorized_face(name, str(record.get("role") or ""))
            result = self._render_actor_sheet(
                name=name,
                desc=str(record.get("desc") or record.get("description") or ""),
                image_model=str(config.get("image_model") or ""),
                dir_style=str(config.get("director_style") or "真人电影写实"),
                genre=self.gateway.get_genre(str(config.get("title_suggestion") or "")),
                extra_negative=self._role_negative_suffix(task, AgentRole.CHARACTER_DESIGNER),
                max_attempts=max(1, min(3, int(os.getenv("CHARACTER_SHEET_MAX_ATTEMPTS", "2")))),
                ref_images=[ref for ref in (reference, authorized) if ref] or None,
            )
            if result.get("error") is not None:
                error = self._safe_error_text(result["error"])
            elif not (result.get("quality") or {}).get("passed"):
                error = f"角色「{name}」设定集重新生成未通过质检"
        except _HdDone as done:
            result = done.result
        except Exception as exc:  # noqa: BLE001 - 失败只记在该角色名下，旧图不动
            logger.exception("[CharacterRegen] %s 重新生成失败", name)
            error = self._safe_error_text(exc) or f"角色「{name}」设定集重新生成失败"

        def finish(current: Dict[str, Any]) -> Dict[str, Any]:
            assets = current.setdefault("assets", {})
            if not error:
                for item in assets.get("3_characters") or []:
                    if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
                        item.update({
                            "sheet": result["sheet"], "views": result["views"], "sheet_cells": result["cells"],
                            "five_view_quality": result["quality"], "sheet_type": "actor_sheet_25_cell",
                        })
                assets.setdefault("3_sheets", {})[name] = result["sheet"]
            progress = assets.setdefault(REGENERATION_KEY, {})
            progress[name] = {"status": "failed", "error": error, "finished_epoch": time.time()} if error else {
                "status": "done", "finished_epoch": time.time(),
            }
            assets["3_character_dashboard"] = compile_character_dashboard(current).model_dump(mode="json", by_alias=True)
            return current

        finished = self.repo.mutate_task(task_id, finish)
        # 新图同步给资产库里挂在本项目的同名数字演员；钩子由 API 层装上，失败不影响项目里的新图。
        if not error and finished and self.character_regenerated_hook is not None:
            try:
                self.character_regenerated_hook(finished, name)
            except Exception:  # noqa: BLE001
                logger.warning("[CharacterRegen] %s 新图同步到资产库失败", name, exc_info=True)

    def regenerate_library_actor(
        self, *, owner_id: str, name: str, name_keys: set[str], desc: str,
        task_ids: tuple[str, ...], reference: bytes | None = None,
    ) -> Dict[str, Any]:
        """资产库里的数字演员重出一张设定集(付费、同步阻塞，调用方放后台线程)。

        演员挂在某个本人项目里、项目里也有这名角色：走该项目的 ``regenerate_character``，
        项目与资产库换的是同一套图。原项目已删或角色不在任何项目里：按资产库里的描述独立出图，
        现有身份视图做参考。返回 {views, sheet, quality}；失败抛 RuntimeError(旧图由调用方保留)。
        """
        for task_id in task_ids:
            task = self.repo.get_task(task_id)
            if not task or str(task.get("owner_user_id") or "") != owner_id:
                continue
            record = next((
                item for item in (task.get("assets") or {}).get("3_characters") or []
                if isinstance(item, dict) and normalized_asset_name(item.get("name")) in name_keys
            ), None)
            if record is None:
                continue
            character = str(record.get("name") or "").strip()
            try:
                self.regenerate_character(task_id, character, mode="sheet", background=False)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            current = self.repo.get_task(task_id) or {}
            assets = current.get("assets") or {}
            progress = (assets.get(REGENERATION_KEY) or {}).get(character) or {}
            if progress.get("status") != "done":
                raise RuntimeError(str(progress.get("error") or f"角色「{character}」设定集重新生成失败"))
            updated = next((
                item for item in assets.get("3_characters") or []
                if isinstance(item, dict) and str(item.get("name") or "").strip() == character
            ), {})
            return {
                "views": list(updated.get("views") or []),
                "sheet": str(updated.get("sheet") or ""),
                "quality": updated.get("five_view_quality") or {},
                "task_id": task_id,
            }

        try:
            ref_images = [self._reference_image_uri(reference, "image/png")] if reference else None
        except Exception:  # noqa: BLE001 - 旧图读不出来就不带参考出图，不挡重新生成
            ref_images = None
        result = self._render_actor_sheet(
            name=name,
            desc=desc,
            image_model="",
            dir_style="真人电影写实",
            genre=self.gateway.get_genre(f"{name} {desc}"),
            extra_negative="",
            max_attempts=max(1, min(3, int(os.getenv("CHARACTER_SHEET_MAX_ATTEMPTS", "2")))),
            ref_images=ref_images,
        )
        if result.get("error") is not None:
            raise RuntimeError(self._safe_error_text(result["error"]) or f"角色「{name}」设定集重新生成失败")
        if not (result.get("quality") or {}).get("passed"):
            raise RuntimeError(f"角色「{name}」设定集重新生成未通过质检")
        return {"views": list(result["views"]), "sheet": str(result["sheet"] or ""), "quality": result["quality"], "task_id": ""}

    def pause_task(self, task_id: str, *, stop: bool = False) -> Optional[Dict[str, Any]]:
        """
        暂停当前正在运行 of 短剧任务
        """
        def pause(task: Dict[str, Any]) -> Dict[str, Any]:
            control = task.setdefault("workflow_control", {})
            if task.get("status") in {"failed", "interrupted"}:
                control["retry_stage"] = task.get("current_stage")
            control["pause_requested"] = True
            control["stop_requested"] = stop
            if not control.get("active"):
                task["status"] = "stopped" if stop else "paused"
            return task
        task = self.repo.mutate_task(task_id, pause)
        return self.hydrate_task_status(task) if task else None

    def resume_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        恢复暂停的短剧任务状态
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        task["status"] = "running"
        self.repo.save_task(task_id, task)
        return task

    async def execute_stage(self, task_id: str, stage: int, *, _claimed_task: Optional[Dict[str, Any]] = None, _automatic: bool = False) -> Dict[str, Any]:
        """
        执行特定步骤 (异步包装)。真实大模型调用是阻塞式 I/O (文本/图片/视频轮询可达数分钟)，
        故放入线程池执行，避免阻塞 FastAPI 事件循环导致前端状态轮询无响应。
        执行异常时把异常信息写入 stage_progress 并标记任务 failed，供前端对话面板抛错展示。
        """
        claimed = _claimed_task or await asyncio.to_thread(self._claim_stage_task, task_id, stage)
        run_id = (claimed.get("workflow_control") or {}).get("run_id")
        try:
            return await asyncio.to_thread(self._execute_claimed_stage_blocking, task_id, stage, claimed)
        except _ClaimedStageExecutionError as execution_error:
            claimed_revision = execution_error.claimed_revision
            safe_error = self._safe_error_text(
                f"{type(execution_error.cause).__name__}: {execution_error.cause}"
            )

            def mark_claimed_revision_failed(task: Dict[str, Any]) -> bool:
                if _task_script_revision(task) != claimed_revision:
                    raise StaleTaskWriteError(
                        "任务剧本已更新，忽略旧版本阶段结果"
                    )
                self._progress_fail(task, safe_error)
                task["status"] = "failed"
                task["fail_reason"] = f"阶段{stage}失败: {safe_error[:200]}"
                return True

            try:
                self.repo.mutate_task(task_id, mark_claimed_revision_failed)
            except StaleTaskWriteError:
                logger.info(
                    "[Task %s] 阶段 %s 执行期间剧本已更新，忽略旧任务异常",
                    task_id,
                    stage,
                )
                raise
            raise execution_error.cause
        except StaleTaskWriteError:
            logger.info(
                "[Task %s] 阶段 %s 的旧剧本快照已失效，忽略旧任务结果",
                task_id,
                stage,
            )
            raise

        finally:
            if not _automatic:
                self._finish_workflow_run(task_id, run_id)

    @staticmethod
    def _adopt_selected_text_model(task: Dict[str, Any]) -> None:
        """A project whose text model was removed or disabled runs on the globally selected one, and says so.

        The configuration centre's current text model is the first enabled one; the project's
        saved choice is replaced with it (persisted with the claim) so every call of the stage,
        the log and the workbench agree on one model.
        """
        config = task.setdefault("config", {})
        chosen = str(config.get("llm_model") or "")
        if chosen and runtime_model_registry.resolve(chosen, "text") is not None:
            return
        selected = runtime_model_registry.first_for_category("text")
        if selected is None:
            return
        config["llm_model"] = selected.model_ids[0]
        logger.info("[Models] 项目 %s 的文本模型 %s 未启用，改用全局选择的 %s",
                    task.get("task_id"), chosen or "（未选择）", selected.model_ids[0])

    def _claim_stage_task(self, task_id: str, stage: int, *, run_id: Optional[str] = None, automatic: bool = False, guidance: Optional[str] = None) -> Dict[str, Any]:
        """Atomically mark and return the exact script revision a worker will execute."""

        def claim(task: Dict[str, Any]) -> Dict[str, Any]:
            control = task.get("workflow_control") or {}
            if control.get("active") and task.get("status") != "interrupted" and control.get("run_id") != run_id:
                raise StagePrerequisiteError("当前制作正在执行，请等待完成或请求暂停，不会重复启动。")
            progress = task.get("stage_progress") or {}
            if not control.get("active") and task.get("status") == "running" and progress.get("status") == "running":
                raise StagePrerequisiteError("当前阶段正在执行，请等待完成后再继续。")
            if run_id and control.get("pause_requested"):
                raise StagePrerequisiteError("已请求暂停，不再启动后续阶段。")
            self._assert_stage_prerequisites(task, stage)
            self._discard_later_stage_outputs(task, stage)
            task["workflow_control"] = {"run_id": run_id or uuid.uuid4().hex, "active": True,
                                        "automatic": automatic, "pause_requested": False}
            task["status"] = "running"
            task["current_stage"] = stage
            task["fail_reason"] = None
            task["stage_progress"] = {"stage": stage, "stage_label": self.STAGE_LABELS[stage],
                                      "status": "running", "percent": 0, "label": "等待执行", "calls": []}
            if guidance is not None:
                task.setdefault("config", {})["guidance_instruction"] = guidance
            self._adopt_selected_text_model(task)
            # The reservation is what starts a stage, so it owns the single
            # "started" message; the worker and the chat reply reuse it instead
            # of writing their own near-identical bubble.
            append_stage_guidance(task, "start", self.STAGE_LABELS)
            return task

        claimed_task = self.repo.mutate_task(task_id, claim)
        if claimed_task is None:
            raise ValueError("任务不存在")
        return claimed_task

    def _finish_workflow_run(self, task_id: str, run_id: Optional[str]) -> None:
        def finish(task: Dict[str, Any]) -> None:
            control = task.get("workflow_control") or {}
            if not run_id or control.get("run_id") != run_id:
                return
            control["active"] = False
            if control.get("pause_requested") and task.get("status") not in {"failed", "completed"}:
                task["status"] = "stopped" if control.get("stop_requested") else "paused"
            elif task.get("status") == "running":
                task["status"] = "idle"
            if control.get("pause_requested"):
                event_id = f"workflow-stopped:{run_id}"
                history = task.setdefault("chat_history", [])
                if not any(item.get("id") == event_id for item in history if isinstance(item, dict)):
                    history.append({"id": event_id, "role": "assistant", "content": self._next_step_hint(task)})
        self.repo.mutate_task(task_id, finish)

    @staticmethod
    def _discard_later_stage_outputs(task: Dict[str, Any], stage: int) -> None:
        """Remove orphaned downstream results before an earlier stage is run again."""
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        for key in list(assets):
            match = re.match(r"^([1-8])(?:$|_)", str(key))
            if match and int(match.group(1)) > stage:
                assets.pop(key, None)

        logs = task.get("logs") if isinstance(task.get("logs"), dict) else {}
        for key in list(logs):
            if str(key).isdigit() and int(key) >= stage:
                logs.pop(key, None)

        completions = task.get("stage_completions")
        if isinstance(completions, dict):
            for key in list(completions):
                if str(key).isdigit() and int(key) >= stage:
                    completions.pop(key, None)

        if stage <= 7:
            task["video_url"] = None
        if stage <= 8:
            task["short_link"] = None
            task["pr_content"] = None

    @staticmethod
    def _missing_stage_outputs(task: Dict[str, Any], stage: int) -> list[str]:
        assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
        required = {
            1: ("1",),
            2: ("2",),
            3: ("3", "3_sheets", "3_character_dashboard"),
            4: ("4", "4_storyboard", "4_grid", "4_quality"),
            5: ("5",),
            6: ("6",),
            7: ("7",),
            8: ("8",),
        }.get(stage, ())
        missing = [key for key in required if not assets.get(key)]
        progress = task.get("stage_progress") or {}
        unsuccessful = (task.get("status") in {"failed", "interrupted"}
                        or (progress.get("stage") == stage and progress.get("status") in {"running", "error"})
                        or (task.get("workflow_control") or {}).get("retry_stage") == stage)
        # A stage that already reported success for this script revision stays
        # done even when the task later failed, was interrupted by a restart, or
        # is retried: re-running it would redo finished work and loop the chat
        # on the same step. Claiming a stage clears its own completion record.
        completion = (task.get("stage_completions") or {}).get(str(stage))
        completed_here = (
            isinstance(completion, dict)
            and completion.get("status") == "success"
            and int(completion.get("script_revision") or 0) == _task_script_revision(task)
        )
        if unsuccessful and not completed_here and task.get("current_stage") == stage:
            missing.append("当前执行尚未成功完成")
        if stage == 2 and isinstance(assets.get("2"), str):
            gaps = script_episode_gaps(assets["2"], (task.get("config") or {}).get("episode_count", 0))
            if gaps:
                missing.append("剧本缺少第" + "、".join(map(str, gaps)) + "集")
        if stage == 3:
            dashboard = assets.get("3_character_dashboard")
            if isinstance(dashboard, dict) and dashboard.get("state") != "READY":
                missing.append("3_character_dashboard.state=READY")
            # 数字演员、场地、道具、服装、特效全部有参考图，分镜师才有东西可锁；
            # 快照由阶段3收尾、资产同步接口和阶段4前置检查刷新。
            readiness = assets.get(READINESS_KEY)
            if isinstance(readiness, dict) and readiness.get("complete") is False:
                missing.extend(readiness_reasons(readiness))
        if stage == 8:
            promotion = assets.get("8") if isinstance(assets.get("8"), dict) else {}
            for field in ("pr_content", "short_link"):
                if not promotion.get(field):
                    missing.append("8." + field)
        if stage == 5:
            clips = assets.get("5")
            if not isinstance(clips, list) or not clips or any(not isinstance(clip, dict) or not clip.get("video_url") for clip in clips):
                missing.append("5.video_url")
        if stage == 6:
            audio = assets.get("6") if isinstance(assets.get("6"), dict) else {}
            if not any(audio.get(field) for field in ("audio_url", "audio_path", "bgm_url", "bgm_path", "sfx_url", "sfx_path")) and not any(audio.get("shot_voices") or []):
                missing.append("6.audio")
        if stage == 7:
            video = assets.get("7") if isinstance(assets.get("7"), dict) else {}
            if not (video.get("final_video_url") or task.get("video_url")):
                missing.append("7.final_video_url")
        if stage == 4:
            quality = assets.get("4_quality")
            if isinstance(quality, dict) and quality.get("passed") is not True:
                missing.append("4_quality.passed=true")
            # 项目级连续性自检：任一场景有 error 级失败即不放行 (旧任务无此键不参与判定)
            missing.extend(gate_reasons(assets.get("4_continuity_audit")))
            # 逐场分镜引擎：所有集全部 complete 后阶段4才算整体完成 (旧任务无 4_progress 时不参与判定)
            progress = assets.get("4_progress")
            if isinstance(progress, dict) and isinstance(progress.get("episodes"), list):
                incomplete = [
                    str(item.get("number"))
                    for item in progress["episodes"]
                    if isinstance(item, dict) and not item.get("complete")
                ]
                if incomplete:
                    missing.append("4_progress.episodes[" + ",".join(incomplete) + "].complete=true")
                expected = {episode_from_scene_id(scene["scene_id"]) for scene in DramaService._breakdown_scenes(task)}
                covered = {item.get("number") for item in progress["episodes"] if isinstance(item, dict)}
                if expected - covered:
                    missing.append("4_progress 尚未覆盖全部剧本集数")
        return missing

    def _assert_stage_prerequisites(self, task: Dict[str, Any], stage: int) -> None:
        if stage < 1 or stage > 8:
            raise ValueError("阶段必须介于 1 到 8")
        if stage == 1:
            return
        previous = stage - 1
        missing = self._missing_stage_outputs(task, previous)
        if missing:
            raise StagePrerequisiteError(
                f"第{previous}阶段尚未完整完成，不能进入第{stage}阶段；缺少或未通过："
                + "、".join(missing)
            )
        if stage == 4:
            # The persisted snapshot may be stale; the storyboard stage checks the
            # library itself and refuses to start on anything less than all five kinds.
            readiness = evaluate_project_assets(task)
            task.setdefault("assets", {})[READINESS_KEY] = readiness
            reasons = readiness_reasons(readiness)
            if reasons:
                raise StagePrerequisiteError(
                    "第3阶段的拍摄资产尚未全部生成，不能进入第4阶段；" + "、".join(reasons)
                )
        if stage == 3:
            # The review gate is soft: production starts anyway, but the episodes nobody
            # confirmed and the drafts still breaking a rule are named on the task.
            state = screenwriting.state_of(task)
            if state is not None:
                record = review.gate_record(state, stage=3)
                task.setdefault("assets", {})[review.GATE_KEY] = record
                if not record["passed"] and record["message"]:
                    logger.warning("[Stage3] 剧本审核软门未全部通过 task=%s：%s", task.get("task_id"), record["message"])
        if stage == 5:
            # Video is where the money goes: every shot is admitted together, or none is submitted.
            admission = assess_video_batch(task, provider_ready=ModelGateway.video_family_ready)
            task.setdefault("assets", {})["5_admission"] = admission.as_dict()
            if admission.decision != "admitted":
                raise StagePrerequisiteError(admission.summary())

        for earlier in range(1, previous):
            missing = self._missing_stage_outputs(task, earlier)
            if missing:
                raise StagePrerequisiteError(f"第{earlier}阶段尚未完整完成，不能跳过进入第{stage}阶段；" + "、".join(missing))

    def _execute_claimed_stage_blocking(self, task_id: str, stage: int, claimed_task: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Claim a revision in the worker thread and attach it to any provider failure."""
        claimed_task = claimed_task or self._claim_stage_task(task_id, stage)
        claimed_revision = _task_script_revision(claimed_task)
        try:
            with usage_ledger.bind_task(task_id, f"stage_{stage}"):
                return self._execute_stage_blocking(
                    task_id,
                    stage,
                    _claimed_task=claimed_task,
                )
        except StaleTaskWriteError:
            raise
        except Exception as exc:
            raise _ClaimedStageExecutionError(claimed_revision, exc) from exc

    # ---------------- 阶段执行进度上报 (供前端对话面板进度条/调用过程展示轮询) ----------------
    STAGE_LABELS = {
        1: "总导演策划", 2: "编剧剧本创作", 3: "角色设计师造型", 4: "分镜师分镜拆解",
        5: "视觉总监多镜头多帧生成", 6: "音频总监配音音效", 7: "合成发布渲染合流", 8: "宣发Agent引流",
    }

    def _progress_save(self, task: Dict[str, Any]):
        self.repo.save_task(task["task_id"], task)

    @staticmethod
    def _progress_timestamp() -> tuple[str, float]:
        now_epoch = time.time()
        return datetime.fromtimestamp(now_epoch, timezone.utc).isoformat(timespec="milliseconds"), now_epoch

    @staticmethod
    def _safe_error_text(error: object, limit: int = 260) -> str:
        text = " ".join(str(error or "未知异常").replace("\x00", "").split())
        text = _LOG_SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        text = _LOG_BARE_SECRET.sub("[REDACTED]", text)
        return text[:limit]

    @staticmethod
    def _close_running_progress_calls(sp: Dict[str, Any], completed_at: str, completed_epoch: float, status: str):
        for call in sp.get("calls", []):
            if call.get("status") == "running":
                call["status"] = status
                call["completed_at"] = completed_at
                call["duration_ms"] = max(0, round((completed_epoch - float(call.get("started_epoch") or completed_epoch)) * 1000))

    @staticmethod
    def _emit_task_progress(task: Dict[str, Any], event: str, **fields: Any):
        sp = task.get("stage_progress") or {}
        payload = {
            "event": event,
            "timestamp": sp.get("updated_at"),
            "task_id": task.get("task_id"),
            "stage": sp.get("stage"),
            "stage_label": sp.get("stage_label"),
            "status": sp.get("status"),
            "percent": sp.get("percent"),
            "step": sp.get("label"),
            "elapsed_ms": sp.get("elapsed_ms", 0),
            **fields,
        }
        logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def _progress_begin(self, task: Dict[str, Any], stage: int):
        """阶段开始：重置进度条与调用过程列表。"""
        timestamp, epoch = self._progress_timestamp()
        task["stage_progress"] = {
            "stage": stage,
            "stage_label": self.STAGE_LABELS.get(stage, f"阶段{stage}"),
            "percent": 3,
            "label": "初始化阶段上下文",
            "status": "running",
            "error": None,
            "started_at": timestamp,
            "started_epoch": epoch,
            "updated_at": timestamp,
            "elapsed_ms": 0,
            "calls": [{
                "name": "初始化阶段上下文",
                "status": "running",
                "started_at": timestamp,
                "started_epoch": epoch,
            }],
        }
        append_stage_guidance(task, "start", self.STAGE_LABELS)
        self._progress_save(task)
        self._emit_task_progress(task, "task_stage_started", step_index=1)

    def _progress_step(self, task: Dict[str, Any], percent: int, label: str):
        """进入一个新的调用步骤：上一步标记完成，追加新调用记录并推进百分比。"""
        sp = task.get("stage_progress")
        if not isinstance(sp, dict):
            return
        timestamp, epoch = self._progress_timestamp()
        self._close_running_progress_calls(sp, timestamp, epoch, "done")
        sp.setdefault("calls", []).append({
            "name": label,
            "status": "running",
            "started_at": timestamp,
            "started_epoch": epoch,
        })
        sp["percent"] = max(int(sp.get("percent", 0)), min(99, int(percent)))
        sp["label"] = label
        sp["updated_at"] = timestamp
        sp["elapsed_ms"] = max(0, round((epoch - float(sp.get("started_epoch") or epoch)) * 1000))
        self._progress_save(task)
        self._emit_task_progress(task, "task_stage_progress", step_index=len(sp["calls"]))

    def _progress_done(self, task: Dict[str, Any]):
        sp = task.get("stage_progress")
        if not isinstance(sp, dict):
            return
        timestamp, epoch = self._progress_timestamp()
        self._close_running_progress_calls(sp, timestamp, epoch, "done")
        sp["percent"] = 100
        sp["label"] = "阶段执行完成"
        sp["status"] = "success"
        sp["updated_at"] = timestamp
        sp["completed_at"] = timestamp
        sp["elapsed_ms"] = max(0, round((epoch - float(sp.get("started_epoch") or epoch)) * 1000))
        task.setdefault("stage_completions", {})[str(sp.get("stage"))] = {
            "status": "success",
            "completed_at": timestamp,
            "script_revision": _task_script_revision(task),
        }
        # Evaluate actual outputs at the stage boundary; the live reservation
        # remains active until the scheduler chooses the next stage or stops.
        finished = {**task, "workflow_control": {**(task.get("workflow_control") or {}), "active": False}}
        if finished.get("status") == "running":
            finished["status"] = "idle"
        append_stage_guidance(task, "done", self.STAGE_LABELS, self.workflow_snapshot(finished))
        self._emit_task_progress(task, "task_stage_completed", step_count=len(sp.get("calls", [])))

    def _progress_fail(self, task: Dict[str, Any], error: str):
        sp = task.get("stage_progress")
        if not isinstance(sp, dict):
            return
        error = self._safe_error_text(error)
        timestamp, epoch = self._progress_timestamp()
        self._close_running_progress_calls(sp, timestamp, epoch, "error")
        sp["status"] = "error"
        sp["label"] = "阶段执行异常"
        sp["error"] = error
        sp["updated_at"] = timestamp
        sp["completed_at"] = timestamp
        sp["elapsed_ms"] = max(0, round((epoch - float(sp.get("started_epoch") or epoch)) * 1000))
        append_stage_guidance(task, "failed", self.STAGE_LABELS)
        self._emit_task_progress(task, "task_stage_failed", error=error[:260])

    # 单次 LLM 调用的输出长度是硬约束（见 ModelGateway._http_chat 的 max_tokens 注释）。
    # 一次写完 30 集会在中途被截断，看板于是显示「总集数 30」却只有 15 集正文。
    # 分批生成把总集数从单次输出长度里解耦出来：新建项目选了多少集就写多少集。
    SCRIPT_EPISODES_PER_BATCH = max(1, int(os.getenv("SCRIPT_EPISODES_PER_BATCH", "4")))
    SCRIPT_BATCH_MAX_TOKENS = max(2000, int(os.getenv("SCRIPT_BATCH_MAX_TOKENS", "8000")))
    SCRIPT_REPAIR_ROUNDS = max(0, int(os.getenv("SCRIPT_REPAIR_ROUNDS", "2")))
    # 批次失败绝大多数是限流/超时/网关抖动，立刻原样重试只会撞进同一个坏窗口，
    # 于是「首批失败=缺 4 集」这种洞两轮补写全废。补写轮次之间按 2^轮次 退避，
    # 给上游一点恢复时间；模型只是无视了跨集要求（没有抛异常）时不等，白等没有意义。
    SCRIPT_REPAIR_BACKOFF_SECONDS = max(0.0, float(os.getenv("SCRIPT_REPAIR_BACKOFF_SECONDS", "5")))
    BREAKDOWN_EPISODES_PER_BATCH = max(1, int(os.getenv("BREAKDOWN_EPISODES_PER_BATCH", "4")))
    # 结构化分批失败后按半批递归重试；连续这么多次仍失败就判定上游不可用，
    # 剩余集数直接走「以剧本正文为准」的兜底，避免对着已宕机的模型空转几十次。
    BREAKDOWN_FAILURE_STREAK = max(2, int(os.getenv("BREAKDOWN_FAILURE_STREAK", "8")))
    # One parser for the whole pipeline: the dashboard's episode count and this
    # module's batching must agree, or a complete script reads as truncated and
    # offers a repair that can never succeed.
    _episode_label_number = staticmethod(episode_label_number)
    _script_episode_indexes = staticmethod(script_episode_indexes)
    _split_script_by_episode = staticmethod(split_script_by_episode)
    _script_episode_gaps = staticmethod(script_episode_gaps)

    def _write_script_batch(self, config: Dict[str, Any], title: str, dir_style: str, shot_style: str,
                            sys_prompt: str, director_plan: str, first: int, last: int,
                            ep_count: int, written: Dict[int, str], guidance: str) -> str:
        """Write one contiguous run of episodes with the earlier ones as context."""
        recap = ""
        if written:
            previous = [written[index] for index in sorted(written) if index < first]
            # Only the tail matters for continuity, and it must stay inside the context window.
            tail = "\n\n".join(previous)[-4000:]
            titles = "、".join(
                f"第{index}集"
                for index in sorted(written)
                if index < first
            )
            recap = (
                f"\n\n【已完成的集数】：{titles}\n"
                f"【前文结尾原文（仅供衔接，不要重复输出）】：\n{tail}\n"
            )
        span = f"第 {first} 集" if first == last else f"第 {first} 集到第 {last} 集"
        user_prompt = (
            f"请基于导演策划大纲为短剧《{title}》编写分集剧本。\n\n"
            f"【导演策划】：\n{director_plan}{recap}\n\n"
            f"【本次只写 {span}】：全剧共 {ep_count} 集，本次**只输出 {span}** 的正文，"
            f"不要输出其它集，不要写任何前言、总结或「以下是」之类的说明文字。"
            f"从「第{first}集」这一行直接开始输出。"
        )
        return self.gateway.call_llm(
            config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style,
            user_instruction=guidance, max_tokens=self.SCRIPT_BATCH_MAX_TOKENS,
        ) or ""

    @classmethod
    def _audit_scripted_episodes(cls, script: str, ep_count: int, task_id: Any = None) -> int:
        """How many episodes the screenplay actually contains, and is that usable.

        The requested count stays authoritative; a shortfall is recorded so the
        dashboard can say so.  Zero parseable episodes for a multi-episode request
        is a different thing entirely - the model returned a refusal or a preamble,
        which would read downstream as a one-episode script and get a whole
        production built on it.
        """
        produced = len(cls._script_episode_indexes(script))
        if produced and produced < ep_count:
            # 断层集号要落到日志里：只报「15/30」时谁也说不出断在哪一段，
            # 而看板/前端拿到的是同一份集号（stats.missing_episodes），两边对得上。
            gaps = cls._script_episode_gaps(script, ep_count)
            logger.warning(
                "[Stage2] 请求 %s 集，实际生成 %s 集，缺第 %s 集 (task=%s)",
                ep_count, produced, "、".join(str(index) for index in gaps[:20]), task_id,
            )
        elif not produced and ep_count > 1:
            logger.error("[Stage2] 请求 %s 集，剧本未解析出任何分集标题 (task=%s)", ep_count, task_id)
            raise RuntimeError(
                f"剧本生成失败：请求 {ep_count} 集，但模型返回的内容里没有任何「第N集」分集正文"
            )
        return produced

    def _generate_full_script(self, task: Dict[str, Any], config: Dict[str, Any], title: str,
                              dir_style: str, shot_style: str, sys_prompt: str,
                              director_plan: str, ep_count: int, guidance: str) -> str:
        """Generate every requested episode, batching so nothing is truncated away."""
        written: Dict[int, str] = {}
        failures: List[BaseException] = []

        def attempt(first: int, last: int) -> None:
            """Run one batch; a provider error costs that batch, never the whole run."""
            try:
                batch = self._write_script_batch(
                    config, title, dir_style, shot_style, sys_prompt,
                    director_plan, first, last, ep_count, written, guidance,
                )
            except Exception as error:  # noqa: BLE001 - upstream failures are per-batch
                failures.append(error)
                logger.warning(
                    "[Stage2] 第 %s-%s 集批次生成失败(%s)，留待补写轮次重试",
                    first, last, type(error).__name__,
                )
                return
            for number, text in self._split_script_by_episode(batch).items():
                if 1 <= number <= ep_count and number not in written:
                    written[number] = text

        batches = [
            (start, min(start + self.SCRIPT_EPISODES_PER_BATCH - 1, ep_count))
            for start in range(1, ep_count + 1, self.SCRIPT_EPISODES_PER_BATCH)
        ]
        for position, (first, last) in enumerate(batches):
            self._progress_step(
                task,
                15 + round(45 * position / max(len(batches), 1)),
                f"调用 LLM · 分集剧本创作 ({first}-{last} 集 / 共 {ep_count} 集)",
            )
            attempt(first, last)

        # A batch can come back short or renumbered; ask again for whatever is missing.
        # 上一轮（初始批次或上一次补写）是否撞到过上游报错，决定这一轮要不要先退避。
        errors_last_pass = len(failures)
        for attempt_round in range(self.SCRIPT_REPAIR_ROUNDS):
            missing = [index for index in range(1, ep_count + 1) if index not in written]
            if not missing:
                break
            delay = self.SCRIPT_REPAIR_BACKOFF_SECONDS * (2 ** attempt_round) if errors_last_pass else 0.0
            if delay > 0:
                logger.warning(
                    "[Stage2] 仍缺 %s 集且上一轮有 %s 次上游报错，退避 %.1fs 后再补写 (task=%s)",
                    len(missing), errors_last_pass, delay, task.get("task_id"),
                )
                self._progress_step(task, 62, f"上游异常，等待 {round(delay)}s 后重试补写 ({len(missing)} 集)")
                self._wait_before_repair(delay)
            before = len(failures)
            self._progress_step(
                task, 62,
                f"补写缺失集数 ({len(missing)} 集：{'、'.join(str(index) for index in missing[:8])}…)"
                if len(missing) > 8 else
                f"补写缺失集数 ({'、'.join(str(index) for index in missing)} 集)",
            )
            for index in missing[:self.SCRIPT_EPISODES_PER_BATCH * 4]:
                attempt(index, index)
            errors_last_pass = len(failures) - before

        if not written:
            logger.warning("[Stage2] 分集剧本未解析出任何「第N集」分隔，回退为单次生成结果")
            try:
                single = self._write_script_batch(
                    config, title, dir_style, shot_style, sys_prompt,
                    director_plan, 1, ep_count, ep_count, {}, guidance,
                )
            except Exception as error:  # noqa: BLE001
                failures.append(error)
                single = ""
            if single.strip():
                return single
            # Nothing survived. An empty screenplay must fail the stage loudly
            # rather than flow on as a project with no script at all.
            if failures:
                raise failures[-1]
            return single
        produced = len(written)
        if produced < ep_count:
            logger.warning("[Stage2] 剧本仅生成 %s/%s 集，缺失集数补写已耗尽重试", produced, ep_count)
        return "\n\n".join(written[index] for index in sorted(written))

    @staticmethod
    def _wait_before_repair(seconds: float) -> None:
        """补写轮次之间的退避等待。单独一个方法，测试里可以直接桩掉，不必真等。"""
        time.sleep(seconds)

    @staticmethod
    def _breakdown_contract(cap_seconds: int, video_model: str) -> str:
        """The structuring contract, bound to what the chosen video model can render."""
        return (
        "你是短剧制片系统的剧本结构化分析器。阅读给定剧本，只输出一个合法 JSON 对象（UTF-8，"
        "不要输出 markdown 代码块之外的任何解释文字），字段如下：\n"
        "{\n"
        '  "overview": {"title": "作品名，4-12字，不含书名号；剧本已有片名就照抄，没有就据剧情起一个",'
        ' "synopsis": "150-250字剧情概述", "genre": "题材类型(如 现代都市励志)",'
        ' "theme": "一句话主题", "world_setting": "世界观与时代背景设定，100-200字"},\n'
        '  "scenes": [{"scene_id": "E{集数}S{镜头序号，两位数}，如 E1S01", "duration": "预估时长如 8s",'
        ' "content": "该镜头可见画面与动作概述，2-4句", "characters": ["出场角色名"]}],\n'
        '  "timeline": [{"phase": "故事开始|进展纠葛|危机|高潮|结局 之一", "title": "事件短标题",'
        ' "desc": "2-3句事件描述", "points": ["该事件的叙事作用要点，2-3条"]}],\n'
        '  "relationships": [{"from": "角色A", "to": "角色B",'
        ' "relation": "2-6字具体关系，如 君臣/父子/主仆/师徒/暗中背叛"}],\n'
        '  "roles": [{"name": "角色名", "position": "女主角|男主角|反派|男配角|女配角|其它角色"}],\n'
        '  "production_assets": {\n'
        '    "scenes": [{"name": "实际拍摄地点名", "description": "时段、内外景、空间布局和剧情用途"}],\n'
        '    "props": [{"name": "具体道具名", "description": "外观、状态、持有人和出现情节"}],\n'
        '    "costumes": [{"name": "具体服装造型名", "description": "角色、款式、材质、颜色和剧情阶段"}],\n'
        '    "effects": [{"name": "具体特效名", "description": "视觉形态、触发时机、环境交互和镜头用途"}]\n'
        '  }\n'
        "}\n"
        # 一集一条记录的分镜表没有镜头语言可用，成片阶段无法逐镜头出图。
        "要求：scenes 是**镜头级**清单，不是每集一条——每一集都必须切分为多个镜头，"
        "具体切成几个镜头由你根据戏剧节奏、地点变化和情绪转折自行判断，不要凑数也不要合并；"
        f"但**单个镜头时长不得超过 {cap_seconds} 秒**"
        f"（这是当前所选视频模型 {video_model or '未指定'} 单次生成的最大时长，超过就无法出片），"
        f"也不要短于 {MIN_SHOT_SECONDS} 秒；"
        "scene_id 里的镜头序号在本集内从 01 连续编号，按剧情顺序排列，"
        "整集时长等于该集各镜头时长之和；"
        f"{configured_episode_shape().rule()}；"
        "timeline 提炼 5-8 个关键节点按时间顺序；relationships 写明真实的身份或戏剧关系，"
        "禁止输出「同场互动」这类只描述同场次数的占位说法；"
        "角色名必须与剧本中的称呼完全一致，不要把「双轨节奏」「情绪钩子」这类结构标签当成角色；"
        "production_assets 必须覆盖剧本明确出现、实际拍摄或生成需要的场地、道具、服装和特效，"
        "同一资产的别名要合并，人物不能当成道具，普通动作不能当成特效；"
        "没有剧本依据的资产禁止补写，每一类没有内容时输出空数组。"
        )

    @staticmethod
    def _enforce_shot_durations(scenes: List[Dict[str, Any]], video_model: str) -> List[Dict[str, Any]]:
        """Cut every shot down to something the video model can render in one call.

        The prompt asks for it, but a model that answers with a single 110s "shot"
        would otherwise flow straight through to a generation request that cannot
        be fulfilled.  Splitting preserves the episode's total runtime.
        """
        cap = max_shot_seconds(video_model)
        result: List[Dict[str, Any]] = []
        sequence: Dict[int, int] = {}
        # Shots are renumbered per episode, so an episode that reappears later in
        # the list (a re-analysed batch, a relabelled answer) would otherwise leave
        # the shot list running E1S08, E2S01, E1S09.  Group by episode first - a
        # stable sort, so the order inside an episode is still the story's order.
        ordered_scenes = sorted(
            (scene for scene in scenes if isinstance(scene, dict)),
            key=lambda scene: episode_from_scene_id(str(scene.get("scene_id") or "")),
        )
        for scene in ordered_scenes:
            scene_id = str(scene.get("scene_id") or "")
            episode = episode_from_scene_id(scene_id)
            seconds = parse_duration_seconds(scene.get("duration"))
            slices = split_shot_seconds(seconds, video_model) or [seconds]
            for position, part in enumerate(slices):
                sequence[episode] = sequence.get(episode, 0) + 1
                shot = dict(scene)
                shot["scene_id"] = f"E{episode}S{sequence[episode]:02d}"
                shot["duration"] = f"{part}s" if part else str(scene.get("duration") or "")
                if len(slices) > 1:
                    shot["content"] = f"{scene.get('content') or ''}（分段 {position + 1}/{len(slices)}）"
                result.append(shot)
        if any(parse_duration_seconds(scene.get("duration")) > cap for scene in scenes if isinstance(scene, dict)):
            logger.info("[Stage2] 已按视频模型上限 %ss 拆分超长镜头 (model=%s)", cap, video_model or "未指定")
        return result

    # 分镜阶段用到的章节；技能本身是项目里那几份原始指南的蒸馏版，放在最前面作为最高优先级契约。
    STORYBOARD_SKILL_SECTIONS = ("shot-grammar", "continuity-consistency", "blocking-lighting")
    # 打戏场次换一套章节：表演/动作设计与招式翻译表进来，连贯性与站位让位。
    # 阶段四预算是定额的，无条件装载三章文戏内容时，仓库里那十几万字符的打戏
    # 资料一个字都进不了提示词——打戏场次改装它们，文戏场次不被武打表格挤占。
    # 打戏同样要景别与机位，所以 shot-grammar 保留；轴线规范由 performance-action
    # 附 §3.8「防越轴硬锚定」自带，不必再叠一份 continuity-consistency。
    FIGHT_STORYBOARD_SKILL_SECTIONS = ("performance-action", "choreography-beats", "shot-grammar")

    # 判定打戏用的词表。强信号=只在打戏里出现的动作术语；弱信号=文戏也常见的冲突词，
    # 单独出现不作数，只在已经命中强信号时用来加权。宁可漏判成文戏，也不要把一场
    # 对峙戏判成打戏——那会让它丢掉连贯性与站位两章。
    FIGHT_STRONG_SIGNALS = fight_design.STRONG_SIGNALS
    FIGHT_WEAK_SIGNALS = fight_design.WEAK_SIGNALS
    # 题材本身不构成判据(古装武侠里照样有大段文戏)，只在已经命中强信号时补一分。
    # 词表与打分在 app.core.fight_design，编剧阶段判定本集是否含打戏也用同一套。
    FIGHT_GENRES = fight_design.FIGHT_GENRES
    # 逐集制作的默认节奏，可用 SHOTS_PER_EPISODE / REANCHOR_EVERY / SHOT_DURATION 调整
    EPISODE_SHOTS_DEFAULT = 16
    EPISODE_SHOTS_MAX = 60
    EPISODE_REANCHOR_DEFAULT = 4
    EPISODE_SHOT_SECONDS_DEFAULT = 10
    FIGHT_INTENSITY_HIGH = frozenset({"high", "extreme", "intense", "高", "强", "很强", "激烈", "高强度"})
    FIGHT_INTENSITY_LOW = frozenset({"low", "none", "无", "低", "弱", "无动作"})

    @staticmethod
    def _detect_scene_kind(scene_content: str, genre: str = "", action_intensity: Any = None) -> str:
        """本场戏该按打戏还是文戏装载技能章节；返回 "fight" 或 "general"。

        判据可解释、可单测：剧本明确标了动作强度就直接采信；否则数场景正文里的
        强/弱信号词并加权，题材只做加分项。评分不到线一律回落 "general"——误判成
        打戏的代价(文戏丢掉连贯性与站位两章)比漏判(打戏少一点资料)大得多。

        ``action_intensity`` 只接受**本场戏**的标注。委员会那份项目级
        ``action_intensity`` 对武侠/军旅题材整体给 high，拿来逐场判定会把全剧
        每一场文戏都判成打戏，正是这里要避免的误判。
        """
        intensity = str(action_intensity).strip().lower() if action_intensity is not None else ""
        if intensity in DramaService.FIGHT_INTENSITY_LOW:
            return "general"
        if intensity in DramaService.FIGHT_INTENSITY_HIGH:
            return "fight"
        if intensity:
            # 数值型强度：1-5 制看 >=4，更大的量程(1-10 制)看 >=7。
            try:
                value = float(intensity)
            except ValueError:
                value = None
            if value is not None:
                return "fight" if (value >= 4 if value <= 5 else value >= 7) else "general"
        # 3 分 = 一个强信号 + (一个弱信号或动作题材)，或两个强信号。
        return "fight" if fight_design.looks_like_fight(scene_content or "", genre) else "general"

    @staticmethod
    def storyboard_skill_sections(video_model: str, *, scene_kind: str = "general") -> tuple:
        """Sections stage 4 loads for this scene kind, plus the model's own contract.

        H3 has a field-level contract of its own (English field names, <Subject N>
        labels, (S1) speaker ids), so a project targeting it needs that downstream
        format while the shot table is still being written.
        """
        sections = (
            DramaService.FIGHT_STORYBOARD_SKILL_SECTIONS if scene_kind == "fight"
            else DramaService.STORYBOARD_SKILL_SECTIONS
        )
        if normalize_video_provider(video_model).family == "minimax_h3":
            sections = sections + ("h3-native-contract",)
        return sections

    @classmethod
    def storyboard_skill_prefix(cls, config: Dict[str, Any], *, scene_kind: str = "general") -> str:
        """The shot-design skill plus this project's per-model clip ceiling."""
        video_model = str(config.get("video_model") or "")
        cap = max_shot_seconds(video_model)
        skill = load_shot_design_skill(
            cls.storyboard_skill_sections(video_model, scene_kind=scene_kind),
            # SKILL.md carries the highest-leverage craft rules (词序即权重、崩坏风险
            # 曲线、竖屏修正…), so the core must never be cut; only sections are.
            # 预算默认值以 shot_design_skill 模块常量为唯一权威源，避免双处硬编码漂移。
            core_budget=int(os.getenv("SHOT_DESIGN_CORE_BUDGET", str(DEFAULT_CORE_BUDGET))),
            section_budget=int(os.getenv("SHOT_DESIGN_SECTION_BUDGET", str(DEFAULT_SECTION_BUDGET))),
            # 章节组合随场次变，预算池也随之重分：四章(H3)与三章共用同一个字符上限。
            section_budgets=shot_design_section_budgets(
                scene_kind, h3=normalize_video_provider(video_model).family == "minimax_h3",
            ),
        )
        prefix = (
            f"【通用分镜提示词技能（最高优先级，与下文冲突时以本节为准）】：\n{skill}\n\n"
            if skill else ""
        )
        return prefix + (
            f"【本项目单镜时长硬上限】：{cap} 秒"
            f"（所选视频模型 {video_model or '未指定'} 的单次生成上限），超过必须拆镜。\n\n"
        )

    def _extract_script_breakdown(self, config: Dict[str, Any], title: str, dir_style: str,
                                  shot_style: str, script: str, director_plan: str = "") -> Optional[Dict[str, Any]]:
        """
        阶段2后置步骤：把完整剧本结构化为「剧本大纲 + 分镜明细 + 事件时间轴 + 人物关系图谱」，
        供看板编剧页渲染。失败不阻断主流程，返回 None。

        长剧本按集分批分析：一次分析 30 集会在 JSON 中途被输出长度截断，解析失败后整个看板
        退化成正则兜底（角色变成「剧情角色」、关系变成「同场互动」）。
        """
        if not script or not script.strip():
            return None
        video_model = str(config.get("video_model") or "")
        episodes = self._split_script_by_episode(script)
        if len(episodes) <= self.BREAKDOWN_EPISODES_PER_BATCH:
            single = self._analyze_script_chunk(config, title, dir_style, shot_style, script, director_plan)
            scenes = [scene for scene in (single or {}).get("scenes") or [] if isinstance(scene, dict)]
            if episodes and scenes:
                # Shots numbered for an episode the screenplay does not have are the
                # model's invention, not the script's; the span is the authority.
                scenes = self._align_scenes_to_span(scenes, sorted(episodes))
            # 只重拆模型答过的集；按剧本正文回退补齐的集没有时长可言，也不该再去追问
            scenes = self._restructure_malformed_episodes(config, title, dir_style, shot_style, episodes, scenes)
            missing = [
                index for index in sorted(episodes)
                if index not in {episode_from_scene_id(str(scene.get("scene_id") or "")) for scene in scenes}
            ]
            if missing and episodes:
                # Stage 4 storyboards straight off these shots; an episode absent here
                # gets no storyboard at all, so fall back to the screenplay's own text.
                logger.warning(
                    "[Stage2] 单批结构化缺 %s 集 (%s)，按剧本正文回退补齐镜头",
                    len(missing), "、".join(str(index) for index in missing[:10]),
                )
                for index in missing:
                    scenes.extend(fallback_scenes_from_script(episodes[index]))
            if not scenes:
                return single
            result = dict(single) if isinstance(single, dict) else {}
            result["scenes"] = self._enforce_shot_durations(scenes, video_model)
            return result

        ordered = sorted(episodes)
        merged: Dict[str, Any] = {
            "scenes": [],
            "timeline": [],
            "roles": [],
            "relationships": [],
            "production_assets": {"scenes": [], "props": [], "costumes": [], "effects": []},
        }
        seen_roles: set = set()
        seen_edges: set = set()
        seen_assets: Dict[str, set] = {
            "scenes": set(), "props": set(), "costumes": set(), "effects": set(),
        }
        groups = [
            ordered[position:position + self.BREAKDOWN_EPISODES_PER_BATCH]
            for position in range(0, len(ordered), self.BREAKDOWN_EPISODES_PER_BATCH)
        ]
        # Retrying a failed batch one episode at a time costs one call per episode;
        # the budget bounds a run where every batch fails so it degrades to the
        # script-grounded fallback instead of hammering the provider forever.
        # 批次之间共享这本账，并发跑时必须上锁，否则 30 集会多付出几次重试调用。
        budget = {"calls": len(ordered) + 2 * len(groups), "lock": threading.Lock()}

        def analyze(group: List[int], want_overview: bool) -> List[Dict[str, Any]]:
            return self._analyze_episode_group(
                config, title, dir_style, shot_style, episodes, group,
                director_plan=director_plan, want_overview=want_overview, budget=budget,
            )

        # 每个批次只看自己那几集，彼此没有依赖；排队跑纯粹是在等墙钟。
        # 首批单独先跑，是为了保住「概览由第一个成功的批次写」这条既有语义：
        # 首批写出概览，后面就不必再要；首批垮了，后面每一批都带上概览请求，
        # 合并时按批次顺序取第一个有的，和串行时的结果一致。
        parts_by_group: List[List[Dict[str, Any]]] = [analyze(groups[0], True)]
        overview_found = any(
            isinstance(part, dict) and isinstance(part.get("overview"), dict) and part["overview"]
            for part in parts_by_group[0]
        )
        if len(groups) > 1:
            parts_by_group.extend(
                map_script_analysis(lambda group: analyze(group, not overview_found), groups[1:])
            )
        for parts in parts_by_group:
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if not isinstance(merged.get("overview"), dict) and isinstance(part.get("overview"), dict) and part["overview"]:
                    merged["overview"] = part["overview"]
                self._merge_breakdown_part(part, merged, seen_roles, seen_edges, seen_assets)
        # 只重拆模型答过的集；下面按剧本正文回退补齐的集没有时长可言，也不该再去追问
        merged["scenes"] = self._restructure_malformed_episodes(
            config, title, dir_style, shot_style, episodes, merged["scenes"],
        )
        # Episodes no batch ever structured would otherwise vanish from the shot
        # list while the dashboard still advertises them.  Fill them from the
        # screenplay text - never for an episode the screenplay does not contain.
        covered = {
            episode_from_scene_id(str(scene.get("scene_id") or ""))
            for scene in merged["scenes"] if isinstance(scene, dict)
        }
        absent = [index for index in ordered if index not in covered]
        if absent:
            logger.warning(
                "[Stage2] 结构化分析仍缺 %s 集 (%s)，按剧本正文回退补齐镜头",
                len(absent), "、".join(str(index) for index in absent[:10]),
            )
            for index in absent:
                merged["scenes"].extend(fallback_scenes_from_script(episodes[index]))
        if not merged["scenes"]:
            logger.warning("[Stage2] 分批结构化分析未产出任何镜头，跳过看板结构化渲染")
            return None
        merged["scenes"] = self._enforce_shot_durations(merged["scenes"], video_model)
        # The timeline is a whole-series arc; keep it readable rather than one entry per batch group.
        if len(merged["timeline"]) > 40:
            step = len(merged["timeline"]) / 40
            merged["timeline"] = [merged["timeline"][round(index * step)] for index in range(40)]
        return merged

    @staticmethod
    def _episode_shape_problems(scenes: List[Dict[str, Any]], shape=None) -> Dict[int, List[str]]:
        """Episodes that are not yet an episode: one shot only, or under the minimum running time."""
        shape = shape or configured_episode_shape()
        counts: Dict[int, int] = {}
        seconds: Dict[int, int] = {}
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            episode = episode_from_scene_id(str(scene.get("scene_id") or ""))
            counts[episode] = counts.get(episode, 0) + 1
            seconds[episode] = seconds.get(episode, 0) + parse_duration_seconds(scene.get("duration"))
        problems: Dict[int, List[str]] = {}
        for episode in counts:
            errors = [issue.message for issue in shape.issues(counts[episode], seconds[episode]) if issue.severity == "error"]
            if errors:
                problems[episode] = errors
        return problems

    def _restructure_malformed_episodes(self, config: Dict[str, Any], title: str, dir_style: str, shot_style: str,
                                        episodes: Dict[int, str], scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send each one-shot or under-length episode back once, on its own, saying what was wrong.

        The contract asks for a well-formed episode, but a batch of several episodes
        sometimes answers one of them with a single eight-second shot. That episode is
        re-analysed alone; the new answer replaces the old one only when it is better
        formed, so a second bad answer never loses what the first one had.
        """
        shape = creation_modes.episode_shape_for(config)
        problems = {episode: reasons for episode, reasons in self._episode_shape_problems(scenes, shape).items() if episode in episodes}
        if not problems:
            return scenes

        def restructure(episode: int) -> List[Dict[str, Any]]:
            part = self._analyze_script_chunk(
                config, title, dir_style, shot_style, episodes[episode],
                want_overview=False, episode_span=(episode, episode), correction="；".join(problems[episode]),
            )
            return self._align_scenes_to_span((part or {}).get("scenes"), [episode])

        ordered = sorted(problems)
        logger.warning(
            "[Stage2] %s 集的镜头拆分不成形 (%s)，逐集重新拆分",
            len(ordered), "、".join(str(episode) for episode in ordered[:10]),
        )
        replaced: Dict[int, List[Dict[str, Any]]] = {}
        for episode, answer in zip(ordered, map_script_analysis(restructure, ordered)):
            if answer and episode not in self._episode_shape_problems(answer, shape):
                replaced[episode] = answer
        if not replaced:
            return scenes
        kept = [
            scene for scene in scenes
            if not isinstance(scene, dict) or episode_from_scene_id(str(scene.get("scene_id") or "")) not in replaced
        ]
        return kept + [scene for episode in sorted(replaced) for scene in replaced[episode]]

    @staticmethod
    def _merge_breakdown_part(part: Dict[str, Any], merged: Dict[str, Any], seen_roles: set,
                              seen_edges: set, seen_assets: Dict[str, set]) -> None:
        """Fold one batch's structuring into the whole-series result, de-duplicated."""
        for scene in part.get("scenes") or []:
            if isinstance(scene, dict):
                merged["scenes"].append(scene)
        for event in part.get("timeline") or []:
            if isinstance(event, dict):
                merged["timeline"].append(event)
        for role in part.get("roles") or []:
            name = isinstance(role, dict) and str(role.get("name") or "").strip()
            if name and name not in seen_roles:
                seen_roles.add(name)
                merged["roles"].append(role)
        for edge in part.get("relationships") or []:
            if not isinstance(edge, dict):
                continue
            key = (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            if all(key) and key not in seen_edges:
                seen_edges.add(key)
                merged["relationships"].append(edge)
        part_assets = part.get("production_assets")
        if isinstance(part_assets, dict):
            for asset_kind in ("scenes", "props", "costumes", "effects"):
                for asset in part_assets.get(asset_kind) or []:
                    if not isinstance(asset, dict):
                        continue
                    asset_name = str(asset.get("name") or "").strip()
                    if not asset_name or asset_name in seen_assets[asset_kind]:
                        continue
                    seen_assets[asset_kind].add(asset_name)
                    merged["production_assets"][asset_kind].append(asset)

    @staticmethod
    def _align_scenes_to_span(raw_scenes: Any, group: List[int]) -> List[Dict[str, Any]]:
        """Force a batch's shots back onto the episodes that batch was given.

        A model handed episodes 5-8 sometimes numbers its answer E1S01..E4S03.
        Left alone those shots would pile onto episode 1 - doubling an episode
        that is already written while 5-8 read as never analysed.  The chunk text
        was episodes 5-8, so the content is theirs: relabel it rather than trust
        the model's numbering, and drop shots that would land on another batch's
        episodes.
        """
        scenes = [scene for scene in (raw_scenes or []) if isinstance(scene, dict)]
        if not scenes or not group:
            return []
        labels: List[int] = []
        for scene in scenes:
            episode = episode_from_scene_id(str(scene.get("scene_id") or ""))
            if episode not in labels:
                labels.append(episode)
        inside = [label for label in labels if label in set(group)]
        if inside:
            # Partly correct: keep what belongs here, drop what belongs to others.
            mapping = {label: label for label in inside}
        elif len(labels) <= len(group):
            # Wholesale renumbering: map in order onto the episodes actually sent.
            mapping = {label: group[position] for position, label in enumerate(sorted(labels))}
            logger.warning(
                "[Stage2] 批次 %s-%s 返回的集号 %s 与原文不符，已按原文集号重贴",
                group[0], group[-1], sorted(labels)[:8],
            )
        else:
            return []
        sequence: Dict[int, int] = {}
        aligned: List[Dict[str, Any]] = []
        for scene in scenes:
            target = mapping.get(episode_from_scene_id(str(scene.get("scene_id") or "")))
            if target is None:
                continue
            sequence[target] = sequence.get(target, 0) + 1
            aligned.append({**scene, "scene_id": f"E{target}S{sequence[target]:02d}"})
        return aligned

    def _analyze_episode_group(self, config: Dict[str, Any], title: str, dir_style: str, shot_style: str,
                               episodes: Dict[int, str], group: List[int], *, director_plan: str,
                               want_overview: bool, budget: Dict[str, int],
                               depth: int = 0) -> List[Dict[str, Any]]:
        """Structure one batch, halving it and retrying whatever it failed to cover.

        A batch that raises or answers with unparseable JSON used to drop its whole
        span on the floor - four episodes gone from a thirty episode shot list, with
        nothing in the result to say so.  Splitting the batch narrows the request
        until either an episode comes back or it is the only episode left.
        """
        # A provider that is simply down answers every retry the same way; stop
        # paying for the rest of the ladder and let the script-grounded fallback
        # cover what is left.  Only the retries are given up on - every batch still
        # gets its own first attempt, so an outage that ends mid-run does not
        # condemn the remaining episodes to the fallback.
        lock = budget.get("lock") or contextlib.nullcontext()
        with lock:
            if depth and budget.get("consecutive_failures", 0) >= self.BREAKDOWN_FAILURE_STREAK:
                return []
            if not group or budget["calls"] <= 0 or depth > 4:
                return []
            budget["calls"] -= 1
        part = self._analyze_script_chunk(
            config, title, dir_style, shot_style,
            "\n\n".join(episodes[index] for index in group),
            director_plan if want_overview else "",
            want_overview=want_overview,
            episode_span=(group[0], group[-1]),
        )
        results: List[Dict[str, Any]] = []
        covered: set = set()
        if isinstance(part, dict):
            aligned = self._align_scenes_to_span(part.get("scenes"), group)
            covered = {episode_from_scene_id(str(scene["scene_id"])) for scene in aligned}
            results.append({**part, "scenes": aligned})
        with lock:
            if covered:
                budget["consecutive_failures"] = 0
            else:
                budget["consecutive_failures"] = budget.get("consecutive_failures", 0) + 1
        missing = [index for index in group if index not in covered]
        if not missing or len(group) == 1:
            return results
        still_wants_overview = want_overview and not (
            isinstance(part, dict) and isinstance(part.get("overview"), dict) and part["overview"]
        )
        for sub in self._contiguous_batches(missing, max(1, len(group) // 2)):
            results.extend(self._analyze_episode_group(
                config, title, dir_style, shot_style, episodes, sub,
                director_plan=director_plan, want_overview=still_wants_overview,
                budget=budget, depth=depth + 1,
            ))
            if still_wants_overview and any(
                isinstance(item.get("overview"), dict) and item["overview"] for item in results
            ):
                still_wants_overview = False
        return results

    def _analyze_script_chunk(self, config: Dict[str, Any], title: str, dir_style: str, shot_style: str,
                              script: str, director_plan: str = "", want_overview: bool = True,
                              episode_span: Optional[tuple] = None, correction: str = "") -> Optional[Dict[str, Any]]:
        """Structure one screenplay chunk; a failure degrades the chunk, not the run."""
        video_model = str(config.get("video_model") or "")
        sys_prompt = self._breakdown_contract(max_shot_seconds(video_model), video_model)
        if not want_overview:
            sys_prompt += "\n本次只分析给定的这几集，overview 字段可以留空对象 {}。"
        else:
            sys_prompt += (
                "\noverview.title 必须是作品名本身，"
                "不要把「请帮我生成一个古装权谋短剧」这类创作指令当成片名。"
            )
        user_prompt = f"【短剧标题】：{title}\n\n【剧本原文】：\n{script}"
        if episode_span:
            first, last = episode_span
            user_prompt += (
                f"\n\n【本次分析范围】：以上是第 {first} 集到第 {last} 集的原文，"
                f"scene_id 的集数编号必须与原文的「第N集」一致。"
            )
        if director_plan:
            user_prompt += f"\n\n【导演策划大纲(辅助参考)】：\n{director_plan}"
        if correction:
            user_prompt += f"\n\n【上一次拆分不合格，必须改正】：{correction}"
        try:
            res = self.gateway.call_llm(
                config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style,
                max_tokens=self.SCRIPT_BATCH_MAX_TOKENS,
            )
            breakdown = extract_json_object(res)
            if not breakdown:
                logger.warning("[Stage2] 剧本结构化分析未解析出 JSON，跳过该批次")
            return breakdown
        except Exception as e:
            logger.warning(f"[Stage2] 剧本结构化分析失败(不阻断主流程): {type(e).__name__}")
            return None

    def _extract_character_dna_breakdown(self, config: Dict[str, Any], title: str, dir_style: str,
                                         shot_style: str, dna_text: str) -> Optional[Dict[str, Any]]:
        """
        阶段3后置步骤：把「角色 DNA 性格造型锁定包」markdown 结构化为 JSON，
        供看板角色资产图页面图文渲染。失败不阻断主流程，返回 None。
        """
        if not dna_text or not dna_text.strip():
            return None
        sys_prompt = (
            "你是短剧制片系统的角色资产结构化分析器。阅读给定的「角色 DNA 性格造型锁定包」文档，"
            "只输出一个合法 JSON 对象（不要输出 JSON 之外的任何解释文字），字段如下：\n"
            "{\n"
            '  "project": {"genre": "类型定位", "platform": "平台/受众", "delivery_spec": "交付基准(如 1080×1920, 9:16, 30fps)",'
            ' "constraints": "关键约束一句话"},\n'
            '  "assumptions": ["关键假设，每条一句话"],\n'
            '  "risks": [{"item": "风险项名称", "status": "BLOCKED|PENDING|PASS", "note": "一句话说明"}],\n'
            '  "characters": [{\n'
            '    "character_id": "如 char_001", "name": "角色名", "identity": "身份(可含多个状态,用/分隔)",\n'
            '    "voice_id": "声音ID(如 VC_xxx)，无则空字符串",\n'
            '    "colors": [{"name": "主色名(如 青灰)", "hex": "#8A9BA8"}],\n'
            '    "states": [{\n'
            '      "state_id": "如 modern / beggar_child", "title": "状态中文名(如 现代博士状态)",\n'
            '      "dna": "身份DNA一段话", "hair": "发型", "body": "体型", "clothing": "服装",\n'
            '      "accessories": "配饰", "style": "视觉风格",\n'
            '      "anchors": [{"view": "正面|正面四分之三|标准侧面|背面四分之三|背面", "detail": "该视图可见身份锚点"}]\n'
            "    }]\n"
            "  }]\n"
            "}\n"
            "要求：忠实提取原文信息不要虚构；hex 色值必须是文档中出现的；"
            "states 覆盖每个角色的全部状态卡；anchors 按身份视图顺序排列。"
        )
        user_prompt = f"【短剧标题】：{title}\n\n【角色 DNA 锁定包原文】：\n{dna_text}"
        try:
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style)
            breakdown = extract_json_object(res)
            if not breakdown:
                logger.warning("[Stage3] 角色 DNA 结构化分析未解析出 JSON，跳过角色资产图渲染")
            return breakdown
        except Exception as e:
            logger.warning(f"[Stage3] 角色 DNA 结构化分析失败(不阻断主流程): {type(e).__name__}")
            return None

    # ---------------- 阶段4：逐场分镜引擎 (剧本大纲 scenes 是分镜的唯一基准) ----------------

    @staticmethod
    def _breakdown_scenes(task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read the same source-reconciled outline used by the Writer dashboard."""
        assets = task.get("assets") or {}
        breakdown = assets.get("2_breakdown") or {}
        raw = breakdown.get("scenes") if isinstance(breakdown, dict) else []
        return reconcile_breakdown_scenes(raw, str(assets.get("2") or ""))

    @staticmethod
    def _init_scene_boards(task: Dict[str, Any], scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        把 4_scene_boards 按剧本大纲**全量**写齐(幂等，可续跑)：
        - done 且扁平列表里九格图齐的场景保留，续跑时直接跳过；
        - 崩溃残留的 generating、图不齐的 done 一律降级为 pending 重做；failed 保留标记等待重做；
        - 不再属于剧本大纲(或不完整)的散镜从 assets["4"] 清理，防止旧场景污染扁平列表。
        """
        assets = task["assets"]
        previous = assets.get("4_scene_boards") if isinstance(assets.get("4_scene_boards"), dict) else {}
        flat_shots = assets.get("4") if isinstance(assets.get("4"), list) else []
        shots_by_scene: Dict[str, List[Dict[str, Any]]] = {}
        for shot in flat_shots:
            if isinstance(shot, dict) and shot.get("scene_id"):
                shots_by_scene.setdefault(str(shot["scene_id"]), []).append(shot)

        boards: Dict[str, Dict[str, Any]] = {}
        for scene in scenes:
            scene_id = str(scene.get("scene_id") or "").strip()
            if not scene_id or scene_id in boards:
                continue
            episode = episode_from_scene_id(scene_id)
            prior = previous.get(scene_id) if isinstance(previous.get(scene_id), dict) else {}
            scene_shots = shots_by_scene.get(scene_id, [])
            grid_complete = len(scene_shots) == 9 and all(s.get("image_url") for s in scene_shots)
            if prior.get("status") == "done" and grid_complete:
                boards[scene_id] = {**prior, "status": "done", "shots_total": 9, "shots_done": 9, "episode": episode}
            else:
                entry: Dict[str, Any] = {
                    "status": "failed" if prior.get("status") == "failed" else "pending",
                    "shots_total": 9,
                    "shots_done": 0,
                    "episode": episode,
                }
                if prior.get("error"):
                    entry["error"] = prior["error"]
                boards[scene_id] = entry

        assets["4"] = [
            shot for shot in flat_shots
            if isinstance(shot, dict)
            and boards.get(str(shot.get("scene_id") or ""), {}).get("status") == "done"
        ]
        return boards

    @staticmethod
    def _storyboard_progress(boards: Dict[str, Any]) -> Dict[str, Any]:
        """由 4_scene_boards 汇总 4_progress：total 来自剧本大纲写全的场景数，不是已生成数。"""
        per_episode: Dict[int, Dict[str, Any]] = {}
        for entry in boards.values():
            if not isinstance(entry, dict):
                continue
            number = max(1, int(entry.get("episode") or 1))
            bucket = per_episode.setdefault(number, {"number": number, "total": 0, "done": 0})
            bucket["total"] += 1
            if entry.get("status") == "done":
                bucket["done"] += 1
        episodes: List[Dict[str, Any]] = []
        for number in sorted(per_episode):
            bucket = per_episode[number]
            bucket["complete"] = bucket["total"] > 0 and bucket["done"] >= bucket["total"]
            episodes.append(bucket)
        current = next(
            (bucket["number"] for bucket in episodes if not bucket["complete"]),
            episodes[-1]["number"] if episodes else 1,
        )
        return {"current_episode": current, "episodes": episodes}

    def _generate_scene_board(
        self,
        task: Dict[str, Any],
        config: Dict[str, Any],
        scene: Dict[str, Any],
        *,
        sys_prompt: str,
        storyboard_negative: str,
        title: str,
        genre: str,
        dir_style: str,
        shot_style: str,
        guidance: str,
        char_info: tuple,
    ) -> Dict[str, Any]:
        """
        单场景九宫格生成(可复用)：LLM 拆表 → audit 复核 → 逐格生图 → 合成 3×3 九宫格。
        输入一条剧本大纲场景(scene_id/content/characters/duration)，产出 9 个带 scene_id 的 shot。
        任一环节失败直接抛异常，由调用方把该场景标 failed，不中断本集其余场景。
        """
        scene_id = str(scene.get("scene_id") or "E1S01").strip() or "E1S01"
        # 分镜图沿用全片风格锁：漫剧项目的九格不再被写实实拍措辞压掉。
        board_style_pack = style_packs.resolve_pack(config)
        scene_duration = str(scene.get("duration") or "")
        context = compile_scene_context(task, scene, load_storyboard_elements(task, scene))
        scene_content = context["script"]
        scene_characters = context["characters"]
        if not scene_content.strip():
            raise ValueError(f"场景 {scene_id} 缺少剧情内容，无法生成对应分镜")
        task_id = str(task.get("task_id") or "")

        user_prompt = (
            "请基于以下剧本场景设计恰好9镜的精准九宫格分镜表，覆盖该场景完整剧情，不要断开：\n\n"
            f"【场景编号】：{scene_id}\n"
        )
        if scene_characters:
            user_prompt += f"【出场角色】：{'、'.join(scene_characters)}\n"
        if scene_duration:
            user_prompt += f"【场景时长预估】：{scene_duration}\n"
        user_prompt += context["prompt"]
        # 站位先于分镜表定稿：表格作者拿到的是同一份空间方案，画面描述的左右与远近不会和机位打架。
        blocking_preview = spatial_stage.try_plan_scene(task, scene, [], context)
        spatial_brief = spatial_table_brief(blocking_preview) if blocking_preview is not None else ""
        if spatial_brief:
            user_prompt += "\n" + spatial_brief
        # 题材决定这场戏怎么拍，感觉决定它拍成什么样：两者在场景内容之前先讲清楚。
        direction = genre_clusters.direction_from_task(config, genre=genre, text=scene_content)
        user_prompt += "\n" + direction.brief()
        # 镜头怎么接到下一镜，和镜头本身一样是分镜表作者的事：先把衔接规则讲清，再按同一套规则复核。
        user_prompt += "\n" + shot_transitions.TABLE_BRIEF
        user_prompt += (
            "\n只拆当前场景，不续写下一场。入镜角色列必须逐镜填写真实角色名；空镜填‘无’。"
            "不能用主角、反派、剧情推进分镜等占位词。人物外观及拍摄资产沿用以上资料。"
        )
        res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)

        parsed_shots = parse_storyboard_table(res, [])
        if len(parsed_shots) != 9:
            raise ValueError(f"场景 {scene_id} 分镜表需要9个真实镜头，实际解析出{len(parsed_shots)}个；请重新创作，不使用占位内容生图")
        # 技能把规则写进了提示词，但提示词是请求不是保证：模型仍会给出 110 秒的
        # "一个镜头"、抽象情绪词或连着五个同景别。这里做机器可判定的复核。
        shots = audit_and_log(
            parsed_shots,
            video_model=str(config.get("video_model") or ""),
            task_id=task_id,
            # 武戏的特写配额比文戏紧：特写是标点，不是正文。
            scene_kind=self._detect_scene_kind(scene_content, genre, scene.get("action_intensity")),
        )
        shots = list(shots or [])
        if len(shots) != 9:
            raise ValueError(f"场景 {scene_id} 校验后不足或超过9个真实镜头，请重新拆解")
        filler_shots = 0
        character_profiles = context["profiles"]
        # Validate every frame before making any paid image call.
        bindings = [panel_context(context, shot) for shot in shots]
        location = "；".join(item["name"] for item in context["scenes"])

        for index, shot in enumerate(shots, start=1):
            binding = bindings[index - 1]
            shot["shot_id"] = index
            shot["scene_id"] = scene_id
            shot["scene"] = (location or shot.get("scene") or scene_content)[:500]
            shot["characters"] = binding["characters"]
            shot["props"] = binding["props"]
            shot["effects"] = binding["effects"]
            shot["expression"] = shot.get("expression") or "与本镜触发事件对应的可观察微表情与呼吸变化"
            shot["continuity_in"] = "建立空间与人物关系" if index == 1 else "承接上一格最后动作、视线和屏幕方向"
            shot["continuity_out"] = "锁定人物朝向、道具归属、情绪强度、光向与色温"
            purpose_text = f"{shot.get('desc', '')} {shot.get('dialogue', '')}"
            if any(word in purpose_text for word in ("证据", "真相", "反转", "揭露")):
                shot["shot_purpose"] = "reversal"
            elif any(word in purpose_text for word in ("线索", "发现", "细节")):
                shot["shot_purpose"] = "clue"
            elif any(word in purpose_text for word in ("恐惧", "悬疑", "窥视", "隐藏")):
                shot["shot_purpose"] = "suspense"
            elif any(word in purpose_text for word in ("愤怒", "对峙", "争吵", "打斗", "冲突")):
                shot["shot_purpose"] = "tension"
            elif any(word in purpose_text for word in ("震惊", "爆炸", "切黑")):
                shot["shot_purpose"] = "shock"
            elif any(word in purpose_text for word in ("眼泪", "悲伤", "温柔", "微笑", "崩溃")):
                shot["shot_purpose"] = "emotion"
            else:
                shot["shot_purpose"] = "information"

        # 机位由空间方案按分镜表求解：构图 / 轴线 / 视线 / 调度四句话都是对同一份站位的测量，
        # 九格之间、同地点的不同场次之间左右关系与距离一致。
        spatial_plan = spatial_stage.try_plan_scene(task, scene, shots, context)
        spatial_fields = {
            shot["shot_id"]: spatial_stage.panel_fields(spatial_plan, shot["shot_id"]) if spatial_plan is not None else {}
            for shot in shots
        }
        if spatial_plan is not None:
            for shot in shots:
                shot["spatial"] = spatial_stage.shot_summary(spatial_plan, shot["shot_id"])

        # 切点规划：相邻两镜之间用什么接、带过去什么、两侧在切点各做什么；入剪 / 出剪 / 连续性四句话
        # 不再是固定措辞。规划失败只会退回固定措辞，不会让本场分镜失败。
        cut_fields: Dict[Any, Dict[str, str]] = {}
        cut_plan = None
        try:
            scene_order = [str(item.get("scene_id") or "") for item in self._breakdown_scenes(task)]
            flat_shots = task["assets"].get("4") if isinstance(task["assets"].get("4"), list) else []
            lead_in = shot_transitions.scene_lead_in(flat_shots, scene_order, scene_id)
            same_episode = lead_in is not None and episode_from_scene_id(str(lead_in.get("scene_id") or "")) == episode_from_scene_id(scene_id)
            cut_plan = shot_transitions.plan_transitions(
                shots, stage_plan=spatial_plan, previous_shot=lead_in if same_episode else None,
                first_of_episode=not same_episode,
            )
            for shot in shots:
                cut_fields[shot["shot_id"]] = shot_transitions.panel_fields(cut_plan, shot["shot_id"], total=len(shots))
                shot["cut_in"] = shot_transitions.shot_summary(cut_plan, shot["shot_id"])
                shot["continuity_in"] = cut_fields[shot["shot_id"]].get("continuity_in") or shot["continuity_in"]
                shot["continuity_out"] = cut_fields[shot["shot_id"]].get("continuity_out") or shot["continuity_out"]
        except Exception as cut_error:  # noqa: BLE001 - an enhancement, never the reason a board fails
            logger.warning("[Stage4] 场景 %s 切点规划失败，沿用固定衔接措辞: %s", scene_id, type(cut_error).__name__)
            cut_fields, cut_plan = {}, None

        board = NineGridStoryboard(
            title=title,
            scene_number=int(re.search(r"S(\d+)$", scene_id, re.I).group(1)) if re.search(r"S(\d+)$", scene_id, re.I) else 1,
            rhythm_profile=("romance" if genre in {"romance", "retro_romance"} else direction.cluster.rhythm_profile),
            assets=StoryAssetCatalog(
                characters=scene_characters or ["空镜（无人物）"],
                scenes=[location or shots[0]["scene"]],
                props=[item["name"] for item in context["props"]] or ["本场无额外道具"],
                effects=[item["name"] for item in context["effects"]] or ["本场无额外特效"],
            ),
            panels=[
                StoryboardPanel(
                    index=shot["shot_id"],
                    characters=shot["characters"],
                    shot_size=shot.get("size") or "中景",
                    camera_angle=spatial_fields[shot["shot_id"]].get("camera_angle") or shot.get("angle") or "遵守180度轴线的平视机位",
                    camera_movement=shot.get("motion") or "固定镜头",
                    camera_reason="服务当前镜头的叙事目的、信息揭示和情绪强度，不做无动机炫技",
                    lens_mm=spatial_fields[shot["shot_id"]].get("lens_mm") or 50,
                    aperture="T2.8",
                    composition=spatial_fields[shot["shot_id"]].get("composition") or "主体落在三分线，前中后景层次清楚，关键道具与负空间承担叙事功能",
                    action_axis=spatial_fields[shot["shot_id"]].get("action_axis") or "沿场景圣经指定轴线，人物不越180度轴线",
                    eyeline=spatial_fields[shot["shot_id"]].get("eyeline") or "说话人与聆听者视线方向、高度和出入画位置连续",
                    shot_purpose=shot["shot_purpose"],
                    story_beat=(shot.get("narrative_purpose") or shot["desc"])[:500],
                    duration_seconds=_bounded_shot_duration(shot.get("duration")),
                    subject_action=shot.get("desc") or f"第{shot['shot_id']}格剧情动作",
                    expression=shot["expression"],
                    scene=shot["scene"],
                    props=shot["props"],
                    effects=shot["effects"],
                    dialogue=shot.get("dialogue") or "",
                    sound=shot.get("sound") or "环境声与动作声连续",
                    lighting="继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次",
                    edit_in=cut_fields.get(shot["shot_id"], {}).get("edit_in") or "承接上一格动作、视线或声音桥，在叙事信息可读后切入",
                    edit_out=cut_fields.get(shot["shot_id"], {}).get("edit_out") or "在动作接触、视线落点、情绪转折或对白收音点切出",
                    generation_mode="auto",
                    blocking=spatial_fields[shot["shot_id"]].get("blocking") or "保持人物左右关系、视线匹配与关键道具位置，不越180度轴线",
                    start_state=cut_fields.get(shot["shot_id"], {}).get("start_state") or shot["continuity_in"],
                    end_state=cut_fields.get(shot["shot_id"], {}).get("end_state") or shot["continuity_out"],
                    continuity_in=shot["continuity_in"],
                    continuity_out=shot["continuity_out"],
                )
                for shot in shots
            ],
        )
        continuity_report = validate_storyboard_continuity(board.panels)
        if not continuity_report.passed:
            raise RuntimeError(f"场景 {scene_id} 九宫格分镜连续性质检未通过")

        # Compile and preflight every fixed panel input before any paid image I/O.
        image_requests = []
        for shot in shots:
            panel = board.panels[int(shot["shot_id"]) - 1]
            contract = ShotMotionContract.from_panel(panel)
            binding = bindings[int(shot["shot_id"]) - 1]
            ref_sheets = [item["image_url"] for item in binding["references"]]
            actor_refs = any(item["kind"] == "actor" for item in binding["references"])
            lock_pos = self.gateway.SHEET_LOCK_POSITIVE if actor_refs else ""
            lock_neg = self.gateway.SHEET_LOCK_NEGATIVE if actor_refs else ""
            compiled_image_prompt = compile_storyboard_image_prompt(
                contract,
                visual_style=style_packs.image_style_line(board_style_pack, lighting=dir_style),
            )
            img_prompt = (
                f"{lock_pos}。{compiled_image_prompt.prompt}。{binding['prompt']}。"
                f"strict consistent character features{self.gateway.DEID_POSITIVE}{self.gateway.SCENE_STABILITY_POSITIVE}。"
                f"{lock_neg}{style_packs.identity_negative(board_style_pack, self.gateway.DEID_NEGATIVE)}"
                f"{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
                f"{storyboard_negative}"
            )
            self.gateway.validate_image_request(
                config["image_model"], ref_sheets, require_reference_support=True,
            )
            image_requests.append((shot["shot_id"], contract, ref_sheets, img_prompt, binding))

        def _render_panel(request):
            shot_id, _contract, ref_sheets, img_prompt, _binding = request
            try:
                img_url, _ = self.gateway.generate_image(
                    config["image_model"], img_prompt, ref_images=ref_sheets,
                    enhance_prompt=False, require_reference_support=True,
                )
                return img_url
            except ValueError:
                # Configuration/reference errors are actionable and deterministic;
                # do not repeat them nine times or hide them behind a grid error.
                raise
            except Exception as e:
                logger.warning(f"场景 {scene_id} 分镜 {shot_id} 生图失败: {e}")
                return None

        # Only provider I/O runs concurrently; original panel order, contracts,
        # all-nine quality gates, composition and persistence remain sequential.
        image_urls = map_storyboard_images(_render_panel, image_requests)
        for shot, request, image_url in zip(shots, image_requests, image_urls):
            _shot_id, contract, ref_sheets, img_prompt, binding = request
            shot["image_url"] = image_url
            bound_contract = contract.model_copy(update={
                "storyboard_image": shot["image_url"],
                # Private inline bytes are transient provider inputs, not copied
                # nine times into task JSON. Keep public identity links for video.
                "reference_images": [url for url in ref_sheets if url.startswith(("http://", "https://"))],
            })
            shot["motion_contract"] = bound_contract.model_dump(mode="json")
            shot["contract_fingerprint"] = bound_contract.contract_fingerprint
            shot["storyboard_prompt"] = img_prompt
            shot["asset_bindings"] = [{"kind": item["kind"], "name": item["name"]} for item in binding["references"]]

        panel_images = [shot.get("image_url") for shot in shots]
        if len(panel_images) != 9 or not all(panel_images):
            raise RuntimeError(f"场景 {scene_id} 九宫格必须由9张有效分镜图组成，当前分镜图生成不完整")
        board_digest = hashlib.sha256(("|".join(panel_images) + f"|{scene_id}").encode("utf-8")).hexdigest()[:16]
        board_path = os.path.join(media_compositor.MEDIA_DIR, "storyboards", f"grid_{board_digest}.png")
        compose_nine_grid(panel_images, board_path)
        board_url = media_compositor.public_url(
            os.path.relpath(board_path, media_compositor.MEDIA_DIR).replace(os.sep, "/")
        )

        episode = episode_from_scene_id(scene_id)
        prompt_detail = compile_storyboard_prompt_detail(
            board,
            script_text=scene_content or "\n".join(shot.get("desc", "") for shot in shots),
            visual_style=f"{dir_style}，真人电视剧风格，精品短剧画风，大师级构图",
            episode=f"第{episode}集",
            scene_id=scene_id,
            character_profiles=character_profiles,
            production_context={
                **context,
                **({"spatial": spatial_stage.director_context(spatial_plan)} if spatial_plan is not None else {}),
                **({"transitions": {
                    "summary": cut_plan.summary,
                    "checks": [check.model_dump() for check in cut_plan.checks],
                }} if cut_plan is not None else {}),
                "direction": direction.as_dict(),
            },
        )
        return {
            "scene_id": scene_id,
            "shots": shots,
            "raw": res,
            "direction": direction.as_dict(),
            "filler_shots": filler_shots,
            "grid_url": board_url,
            "grid_prompt": context["prompt"] + "\n\n" + build_nine_grid_prompt(board),
            "storyboard": board.model_dump(mode="json"),
            "prompt_detail": prompt_detail.model_dump(mode="json"),
            "quality": continuity_report.model_dump(),
        }

    def _execute_stage_blocking(
        self,
        task_id: str,
        stage: int,
        *,
        _claimed_task: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行特定步骤，基于 LLM 的生成结果并应用 Hooks 校验 (同步阻塞实现)
        """
        task = _claimed_task or self._claim_stage_task(task_id, stage)

        task["status"] = "running"
        task["current_stage"] = stage
        self._progress_begin(task, stage)
        config = task["config"]
        title = config["title_suggestion"]

        dir_style = config.get("director_style") or "真人电影写实"
        shot_style = config.get("shot_style", "cinematic")
        guidance = config.get("guidance_instruction", "")
        
        genre = self.gateway.get_genre(title)
        tpl = self.gateway.GENRE_TEMPLATES.get(genre, self.gateway.GENRE_TEMPLATES["general"])

        # 从前面的资产提取出动态角色特征和台词，保持上下游完全一致性
        char1_name, char1_desc, char2_name, char2_desc = extract_character_info(task["assets"].get("1", ""))
        speech = extract_speech(task["assets"].get("2", ""))

        if stage == 1:
            # 阶段 1：总导演 (Executive Director)
            task["stage_name"] = "总导演策划"
            # 经 production-knowledge-master 装载器读取；本阶段现状是全文读入，budget=0 保持不截断。
            guide_elements = load_section("production-guidelines", budget=0)
            genre_summary = load_section("genre-summary", budget=0)
            narrative_structure = load_section("golden-narrative", budget=0)
            hook_ladder = load_section("episode-hook-ladder", budget=0)
            sys_prompt = (
                self._agent_role_prompt(task, AgentRole.EXECUTIVE_DIRECTOR)
                + "\n\n"
                "Role: AI 短剧总导演智能体 (Executive Director Agent)\n"
                "Methodology: 遵循山音超级导演大师视听定调理论，分析6个维度，确立爽剧主旋律，"
                "锁定首首2秒黄金Hook（如 Pattern Interrupt 模式打破或 Curiosity Gap 好奇心缺口），"
                "规划主要角色的 Want/Need 以及三幕结构大纲。台词和角色描述绝不能有心理描写或括号暗示。\n"
                "必须严格套用《黄金叙事结构》：前3秒强钩子、每30-60秒一个冲突或反转、每集结尾留钩子，"
                "并按‘受辱→忍耐→被逼绝境→身份/能力觉醒→打脸→更大敌人’这类爽文逆袭公式搭建三幕大纲。\n\n"
                f"【黄金叙事结构(单集与整部结构/情绪峰值/钩子公式)如下】：\n{narrative_structure}\n\n"
                f"【前三集钩子阶梯与付费墙卡点(E1 引爆/E2 升级/E3 反转，E8–E10 虚假胜利→崩塌→黑屏钩子)如下】：\n{hook_ladder}\n\n"
                f"【全局短剧制作注意事项与关键元素规范如下】：\n{guide_elements}\n\n"
                f"【短剧题材与爆款题材结构指导如下】：\n{genre_summary}\n"
            )
            # 追加自动进化的历史生产教训 (无 active 教训时为空串，不产生噪声)
            lessons_block = stage_lessons_block(1)
            if lessons_block:
                sys_prompt += f"\n\n{lessons_block}\n"

            script_content = config.get("script_content")
            if script_content:
                user_prompt = (
                    f"用户已手动提供短剧剧本《{config.get('script_name', '未命名')}》，请基于该剧本进行导演方案定调与三幕大纲规划。\n\n"
                    f"【手动剧本内容】：\n{script_content}"
                )
            else:
                user_prompt = f"请为短剧《{title}》做导演方案定调与三幕大纲规划。"

            self._progress_step(task, 25, "调用 LLM · 总导演定调与三幕大纲规划")
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
            self._progress_step(task, 85, "剧本一致性质检自检")
            task["assets"]["1"] = res
            
            task["logs"]["1"] = self.run_real_consistency_check(1, "总导演策划", task["assets"], config, title, task_id=task_id)

        elif stage == 2:
            # 阶段 2：编剧 (Writer Agent)
            task["stage_name"] = "编剧剧本创作"
            script_content = config.get("script_content")
            script_name = config.get("script_name", "未命名")
            library_text, _library_kind, library_episodes = screenwriting.library_sources(task)
            if library_text or library_episodes:
                # 文库里登记的整本源文与逐集原文就是手动剧本；旧路径按集号顺序合成一份正文
                parts = [library_text] if library_text else []
                parts.extend(f"第{index}集 {item['name'] or ''}\n{item['text']}".rstrip() for index, item in enumerate(library_episodes, start=1))
                script_content = "\n\n".join(parts)
                script_name = "剧本文库"
            # 结构化两段式编剧引擎（分集账本 → 分镜内容层 → 视觉层）是默认路径；
            # WRITER_ENGINE=legacy 或引擎失败且允许回退时走下方的自由文本旧路径。
            task["assets"].pop(screenwriting.STATE_KEY, None)
            structured_done = (
                screenwriting.selected_engine() == screenwriting.STRUCTURED_ENGINE
                and self._run_structured_writer(task, config, title, dir_style, shot_style, guidance, task_id)
            )
            if structured_done:
                pass
            elif script_content:
                # 若提供了手动剧本，则直接使用上传的剧本内容，跳过大模型创作
                task["assets"]["2"] = script_content
                self._progress_step(task, 40, "载入手动剧本并做结构化分析 (大纲/时间轴/人物关系)")
                task["assets"]["2_breakdown"] = self._extract_script_breakdown(
                    config, title, dir_style, shot_style, script_content, task["assets"].get("1", "")
                )
                task["logs"]["2"] = (
                    f"🪝 **[已跳过编剧生成]** 检测到手动上传的剧本《{script_name}》，已自动采用该剧本作为分镜依据。\n"
                    "#### ⚖️ 剧本一致性质检自检报告 (前置剧本校验)\n"
                    "| 检查维面 (Section) | 质检内容 | 状态 |\n"
                    "| :--- | :--- | :--- |\n"
                    "| 18.1 手动剧本导入 | 导入手动提供的对白与文本 | ✅ PASS (已载入剧本原文) |"
                )
            else:
                shanyin_prompt = self.get_shanyin_screenplay_skill()
                # 经 production-knowledge-master 装载器读取；本阶段现状是全文读入，budget=0 保持不截断。
                performance_guide = load_section("performance-details", budget=0)
                guide_elements = load_section("production-guidelines", budget=0)
                continuity_guide = load_section("continuity-design", budget=0)
                narrative_structure = load_section("golden-narrative", budget=0)
                dialogue_pacing_guide = load_section("dialogue-pacing", budget=0)
                craft_redlines = load_section("cinema-craft-redlines", budget=0)
                hook_ladder = load_section("episode-hook-ladder", budget=0)
                sys_prompt = (
                    self._agent_role_prompt(task, AgentRole.WRITER)
                    + "\n\n"
                    "Role: AI 专业短剧编剧智能体 (Writer Agent)\n"
                    "Methodology: 遵循山音超级编剧大师核心理念。只写摄影机能拍到的画面和能听到的声音，"
                    "杜绝任何心理描写和括号暗示（如'（她内心很紧张）'），对话高度口语化。\n"
                    "每一集都必须按《黄金叙事结构》单集模型落地：前3秒强钩子→交代冲突→压迫升级→反击/反转/情绪爆点→"
                    "结尾5秒悬念钩子；每集至少命中一个爽/燃/虐/怒/甜/惊情绪点，结尾留‘必须看下一集’的问题。\n\n"
                    f"【写作红线与 S 级三冲击(情绪/视觉/场景顶点、人物语言指纹、四张追踪表)如下】：\n{craft_redlines}\n\n"
                    f"【黄金叙事结构(单集黄金结构/每集三件事/短剧公式/一集模板)如下】：\n{narrative_structure}\n\n"
                    f"【前三集钩子阶梯(E1 引爆/E2 升级/E3 反转)、集尾悬念五型、付费墙前三步如下】：\n{hook_ladder}\n\n"
                    f"【短剧表演细节与具象物理动作指导如下】：\n{performance_guide}\n\n"
                    f"【跨镜头与场景动作连续性设计指导如下】：\n{continuity_guide}\n\n"
                    f"【短剧注意事项与合规/剪辑节奏规范如下】：\n{guide_elements}\n\n"
                    # 台词按 dialogue-pacing（台词语速情绪总结）第八节的万能公式落地：
                    # 一句台词 = 文本 + 语速 + 情绪 + 停顿 + 重音，缺一不可；只给文本会配出"念稿"。
                    "每句台词必须自带表演标注，格式：[角色][情绪类型-强度/克制度][语速][生理表现] 台词文本；"
                    "关键词用【】标注重音，停顿用……或[停顿N秒]显式标出，情绪转折处标[转折]。\n"
                    f"【台词语速情绪与停顿重音标注规范如下】：\n{dialogue_pacing_guide}\n\n"
                )
                ep_count = _bounded_episode_count(config.get("episode_count"))
                ep_labels = "、".join(f"「第{i}集 副标题」" for i in range(1, ep_count + 1))
                if shanyin_prompt:
                    sys_prompt += f"【山音超级编剧大师核心指导规范如下】：\n{shanyin_prompt}\n\n"
                    sys_prompt += (
                        "请特别注意：确保能基于该 skill 指南，生成**完整的分集全剧剧本**。\n"
                        f"剧本一共分为 {ep_count} 集进行详细展示。每一集应包含明确的【集数标注】、场景地点时间、画面视觉内容、台词对白以及【双轨节奏（情节/情感）与每集时长预估】。\n"
                        "请按照规范在输出前执行严格自检，绝对不允许出现任何心理描写和括号暗示（如角色心理活动需以物理动作暗示呈现）。"
                    )
                else:
                    sys_prompt += f"请生成完整的 {ep_count} 集全剧分集剧本，每一集包含场景、画面动作、台词，标注双轨节奏（情节/情感）及预估时长。"

                # 强制分集格式：每集必须以「第N集 标题」独立成行作为分隔，便于系统切分逐集制作
                sys_prompt += (
                    f"\n\n【强制分集格式要求】：全剧共 {ep_count} 集，每一集**必须**以独立成行的"
                    f"{ep_labels} 形式的标题作为该集起始分隔（务必使用中文'第N集'字样）。"
                    "每一集都要剧情完整、首尾呼应、单集结尾留强悬念钩子承接下一集；集与集之间人物、场景、服装、时间线保持连贯一致。"
                )
                # 一集一个大场景会让后续分镜只能切出一条记录，成片没有镜头语言可用。
                shot_cap = max_shot_seconds(str(config.get("video_model") or ""))
                sys_prompt += (
                    "\n\n【强制分镜格式要求】：每一集内部**必须**再切分为多个镜头，"
                    "每个镜头以独立成行的「场景N：地点 时间 内景/外景」开头（N 在本集内从 1 连续编号），"
                    "并在该行下一行用「镜头：景别 + 运镜」标注（如『镜头：中近景 缓推』）。"
                    f"单个镜头时长**不得超过 {shot_cap} 秒**"
                    f"（当前视频模型 {config.get('video_model') or '未指定'} 单次生成的上限），"
                    "切成几个镜头由你根据戏剧节奏自行判断；只写摄影机拍得到的画面动作与角色对白"
                    "（对白用'角色名：台词'格式），一个镜头内不要跨越多个地点或大段时间。"
                )
                # 追加自动进化的历史生产教训 (无 active 教训时为空串，不产生噪声)
                lessons_block = stage_lessons_block(2)
                if lessons_block:
                    sys_prompt += f"\n\n{lessons_block}\n"

                self._progress_step(task, 12, f"规划分集写作批次 (共 {ep_count} 集)")
                res = self._generate_full_script(
                    task, config, title, dir_style, shot_style, sys_prompt,
                    task["assets"].get("1", ""), ep_count, guidance,
                )
                task["assets"]["2"] = res
                # 用户在新建项目里选的集数是权威值，这里不改写它；只记录实际写出了多少集，
                # 以便看板在两者不一致时如实提示，而不是悄悄把目标降到已完成的数量。
                task["scripted_episode_count"] = self._audit_scripted_episodes(
                    res, ep_count, task.get("task_id"),
                )
                self._progress_step(task, 70, "剧本结构化分析 (大纲/时间轴/人物关系)")
                task["assets"]["2_breakdown"] = self._extract_script_breakdown(
                    config, title, dir_style, shot_style, res, task["assets"].get("1", "")
                )

                self._progress_step(task, 90, "剧本一致性质检自检")
                task["logs"]["2"] = self.run_real_consistency_check(2, "编剧剧本创作", task["assets"], config, title, task_id=task_id)

            self._progress_step(task, 96, "编译 Writer Dashboard 时间轴与人物关系契约")
            task["assets"]["2_writer_dashboard"] = compile_writer_dashboard(task).model_dump(
                mode="json", by_alias=True
            )

        elif stage == 3:
            # 阶段 3：角色设计师 (Character Designer)
            task["stage_name"] = "角色设计师造型"
            prior_dna = deepcopy(task["assets"].get("3_dna"))
            prior_character_records = [
                deepcopy(item)
                for item in (task["assets"].get("3_characters") or [])
                if isinstance(item, dict)
            ]
            # 经 production-knowledge-master 装载器读取；本阶段现状是全文读入，budget=0 保持不截断。
            sheet_template = load_section("actor-sheet-template", budget=0)
            # 角色设计师配药单：设定集是静态身份锚点，模块不含时序词(agent_council._ROLE_NEGATIVE_MODULES)。
            designer_negative = self._role_negative_suffix(task, AgentRole.CHARACTER_DESIGNER)
            task["assets"]["3_negative_prompt_modules"] = self._role_negative_modules(task, AgentRole.CHARACTER_DESIGNER)
            performance_guide = load_section("performance-details", budget=0)
            sys_prompt = (
                self._agent_role_prompt(task, AgentRole.CHARACTER_DESIGNER)
                + "\n\n"
                "Role: AI 角色设计师智能体 (Character Designer Agent)\n"
                "Methodology: 设计主角和反派的详细五维 DNA 角色卡（面部、发型、体型、服饰、情绪），"
                "锁定特征（服装与发型等）以保跨镜头多帧渲染的一致性，不能写任何心理词汇。\n"
                "角色身份由一张 21:9 数字演员设定集锁定：左栏「主肖像」正面近景，"
                "中栏「全身与元素」全身立绘 + 正面/90°侧面/背面三视图 + 2×4 元素拆解，"
                "右栏「细节矩阵」4×3 细节特写；其中正面全身、侧面全身、背面全身、正脸特写、"
                "3-4 侧脸五格是身份锚点。DNA 描述必须覆盖这五个锚点看得见的特征，"
                "并逐项写清鞋履、腰扣、护腕、领口刺绣、面料、发饰、手部、裙摆等可拆解元素。\n\n"
                f"【数字演员设定集一致性角色卡规则与示例】：\n{sheet_template}\n\n"
                f"【角色表情细节与身体微动作描述规范】：\n{performance_guide}\n"
            )
            # 追加自动进化的历史生产教训 (无 active 教训时为空串，不产生噪声)
            lessons_block = stage_lessons_block(3)
            if lessons_block:
                sys_prompt += f"\n\n{lessons_block}\n"
            stage2_breakdown = task["assets"].get("2_breakdown")
            screenplay_roles = (
                stage2_breakdown.get("roles")
                if isinstance(stage2_breakdown, dict) and isinstance(stage2_breakdown.get("roles"), list)
                else []
            )
            prior_scope_roles = (
                prior_dna.get("characters")
                if isinstance(prior_dna, dict) and isinstance(prior_dna.get("characters"), list)
                else []
            )
            scoped_roles = prior_scope_roles or screenplay_roles
            cast_lines = [
                f"- {str(item.get('name') or '').strip()}："
                f"{str(item.get('role') or item.get('position') or item.get('identity') or '剧情角色').strip()}"
                for item in scoped_roles
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            try:
                character_context_limit = max(
                    4000, min(60000, int(os.getenv("CHARACTER_SCRIPT_CONTEXT_LIMIT", "24000")))
                )
            except ValueError:
                character_context_limit = 24000
            character_script_context = str(
                task["assets"].get("2") or config.get("script_content") or ""
            )[:character_context_limit]
            user_prompt = (
                "请为短剧中的每一名具名角色进行独立的 DNA 性格造型锁定。"
                "不得遗漏角色、合并不同人物或生成外形服饰完全相同的分身。\n\n"
                "【剧本结构化角色表】：\n"
                + ("\n".join(cast_lines) if cast_lines else "未提供，以剧本与导演方案为准")
                + "\n\n【导演方案】：\n"
                + task["assets"].get("1", "")
                + "\n\n【剧本原文】：\n"
                + character_script_context
            )
            self._progress_step(task, 10, "调用 LLM · 角色 DNA 锁定包生成")
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
            
            # 直接将生成的全动态角色 DNA 设定文本存入 assets，消除预设角色构建框架
            task["assets"]["3"] = res
            task["assets"]["3_raw"] = res

            # 先结构化再生成资产：3_dna.characters 是角色名单的权威来源，
            # 只在结构化结果没有可用角色时才回退到严格锚定的 Markdown 角色卡标题。
            self._progress_step(task, 15, "角色 DNA 锁定包结构化提取")
            task["assets"]["3_dna"] = self._extract_character_dna_breakdown(
                config, title, dir_style, shot_style, res
            )

            # 为每名角色生成一张数字演员设定集，并物理拆成最多 25 个独立格子资产。
            # 后续镜头引用同一角色的五个身份锚点，锁定脸型/发型/服装/体型。
            sheets = {}
            characters = []
            try:
                def _clean_desc(t):
                    t = re.sub(r'^\*\*[^*]+\*\*[:：]?\s*', '', (t or "").strip())
                    t = re.sub(r'[#*>`]', '', t)
                    t = re.sub(r'\s+', ' ', t)
                    return t.strip()[:320]

                def _structured_role(item, cname):
                    role_text = str(item.get("role") or item.get("position") or item.get("identity") or "")
                    if any(label in role_text for label in ("反派", "对手", "大反派")) or cname == char2_name:
                        return "反派"
                    if any(label in role_text for label in ("主角", "男主", "女主", "核心")) or cname == char1_name:
                        return "主角"
                    return "配角"

                def _structured_desc(item):
                    details = [item.get("description"), item.get("desc"), item.get("identity")]
                    states = item.get("states")
                    if isinstance(states, list):
                        for state in states[:3]:
                            if not isinstance(state, dict):
                                continue
                            details.extend(
                                state.get(key)
                                for key in ("dna", "hair", "body", "clothing", "accessories", "style")
                            )
                    return _clean_desc("；".join(str(value) for value in details if value))

                ordered = []  # [(name, role, desc)]
                seen = set()

                def _known_character_alias(cname):
                    if cname in seen:
                        return True
                    title_tokens = (
                        "太后", "皇后", "皇帝", "陛下", "王爷", "王妃", "殿下",
                        "夫人", "嬷嬷", "公主", "将军", "大人", "掌柜", "师父",
                    )
                    return any(
                        (cname in known or known in cname)
                        and any(token in cname or token in known for token in title_tokens)
                        for known in seen
                    )

                dna = task["assets"].get("3_dna")
                dna_characters = dna.get("characters") if isinstance(dna, dict) else None
                if isinstance(dna_characters, list):
                    for item in dna_characters:
                        if not isinstance(item, dict):
                            continue
                        cname = _valid_character_name(item.get("name"))
                        if not cname or cname in seen:
                            continue
                        role = _structured_role(item, cname)
                        fallback_desc = char1_desc if role == "主角" else char2_desc if role == "反派" else ""
                        ordered.append((cname, role, _structured_desc(item) or fallback_desc))
                        seen.add(cname)

                if not ordered:
                    cards = _parse_character_cards(res)
                    for cname, card in cards.items():
                        if cname in seen:
                            continue
                        role = card["role"]
                        fallback_desc = char1_desc if role == "主角" else char2_desc if role == "反派" else ""
                        ordered.append((cname, role, _clean_desc(card["description"]) or fallback_desc))
                        seen.add(cname)

                # The screenplay breakdown is the completeness backstop.  A
                # character-DNA response may omit supporting roles; omission
                # must not silently turn into a missing five-view asset.
                for item in scoped_roles:
                    if not isinstance(item, dict):
                        continue
                    cname = _valid_character_name(item.get("name"))
                    if not cname or _known_character_alias(cname):
                        continue
                    role = _structured_role(item, cname)
                    fallback_desc = char1_desc if role == "主角" else char2_desc if role == "反派" else ""
                    role_desc = _clean_desc(item.get("description") or item.get("position") or "")
                    ordered.append((cname, role, role_desc or fallback_desc or "剧本具名角色，造型必须与其他角色明确区分"))
                    seen.add(cname)

                if not ordered:
                    task["assets"]["3_sheets"] = sheets
                    task["assets"]["3_characters"] = characters
                    task["assets"]["3_character_dashboard"] = compile_character_dashboard(task).model_dump(
                        mode="json", by_alias=True
                    )
                    self.repo.save_task(task_id, task)
                    raise RuntimeError("角色 DNA 中未提取出有效角色名")
                # By default every structured role gets a sheet. Operators may
                # still lower the cap explicitly, while the hard ceiling keeps
                # a malformed cast response from creating an unbounded job.
                max_sheets = max(1, min(60, int(os.getenv("MAX_CHARACTER_SHEETS", str(len(ordered))))))
                selected_characters = ordered[:max_sheets]
                sheet_total = len(selected_characters)

                def _persist_character_assets():
                    task["assets"]["3_sheets"] = sheets
                    task["assets"]["3_characters"] = characters
                    task["assets"]["3_character_dashboard"] = compile_character_dashboard(task).model_dump(
                        mode="json", by_alias=True
                    )
                    self.repo.save_task(task_id, task)

                # 初始快照使前端在首张图生较慢时也能展示 DNA 和等待状态。
                _persist_character_assets()
                max_attempts = max(1, min(3, int(os.getenv("CHARACTER_SHEET_MAX_ATTEMPTS", "2"))))
                failed_names = []
                prior_by_name = {
                    str(item.get("name") or "").strip(): item
                    for item in prior_character_records
                    if str(item.get("name") or "").strip()
                }

                def _is_reusable_character(record):
                    quality = record.get("five_view_quality")
                    views = record.get("views")
                    if not isinstance(quality, dict) or not quality.get("passed") or not isinstance(views, list):
                        return False
                    view_urls = {
                        str(view.get("view") or ""): str(view.get("image_url") or "").strip()
                        for view in views if isinstance(view, dict)
                    }
                    # 新契约的五个身份锚点，或旧五视图的五个角度——齐了就不重新付费出图。
                    return any(
                        all(view_urls.get(view_name) for view_name in wanted)
                        for wanted in (IDENTITY_VIEW_ORDER, LEGACY_IDENTITY_VIEW_ORDER)
                    )

                # 资产库里已有通过质检的同名角色身份视图时直接复用，不再付费出图；
                # 复用会把该资产挂到本项目，后续分镜阶段读到的是同一份资产。
                library_records = find_library_characters(task, [entry[0] for entry in selected_characters])
                for cname, role, cdesc in selected_characters:
                    record = library_records.get(cname)
                    if record and not _is_reusable_character(prior_by_name.get(cname) or {}):
                        prior_by_name[cname] = {**record, "role": role, "desc": cdesc}

                def _render_character_sheet(entry):
                    """一名角色的设定集付费调用(见 ``_render_actor_sheet``)；可以并发。"""
                    cname, role, cdesc = entry
                    # 已授权演员素材作为身份参考，但仍生成统一设定集，不允许用单张脸替代设定集。
                    auth_face = self.gateway.resolve_authorized_face(cname, role)
                    return self._render_actor_sheet(
                        name=cname, desc=cdesc, image_model=config["image_model"], dir_style=dir_style,
                        genre=genre, extra_negative=designer_negative, max_attempts=max_attempts,
                        ref_images=[auth_face] if auth_face else None,
                    )

                # 每名角色的设定集彼此独立，排队跑纯粹是在等墙钟；复用的角色不重新出图。
                pending = [
                    entry for entry in selected_characters
                    if not _is_reusable_character(prior_by_name.get(entry[0]) or {})
                ]
                if pending:
                    self._progress_step(
                        task, 18,
                        f"生成数字演员设定集 (共 {len(pending)}/{sheet_total} 名角色，最多 "
                        f"{character_sheet_concurrency()} 名同时进行)",
                    )
                rendered = dict(zip(
                    [entry[0] for entry in pending],
                    map_character_sheets(_render_character_sheet, pending),
                ))

                for sheet_no, (cname, role, cdesc) in enumerate(selected_characters, start=1):
                    reusable = prior_by_name.get(cname)
                    if reusable and _is_reusable_character(reusable):
                        characters.append(reusable)
                        existing_sheet = str(reusable.get("sheet") or "").strip()
                        if existing_sheet:
                            sheets[cname] = existing_sheet
                        _persist_character_assets()
                        continue
                    self._progress_step(
                        task,
                        18 + int(68 * sheet_no / sheet_total),
                        f"「{cname}」数字演员设定集完成 ({sheet_no}/{sheet_total})",
                    )
                    result = rendered.get(cname) or {}
                    sheet_url = result.get("sheet")
                    views = result.get("views") or []
                    cells = result.get("cells") or []
                    quality_payload = result.get("quality")
                    failure_phase = result.get("phase") or "generation_error"
                    last_error = result.get("error")
                    if sheet_url:
                        sheets[cname] = sheet_url

                    if last_error is None and quality_payload and quality_payload.get("passed"):
                        characters.append({
                            "name": cname,
                            "role": role,
                            "desc": cdesc,
                            "sheet": sheet_url,
                            "sheet_type": "actor_sheet_25_cell",
                            "views": views,
                            "sheet_cells": cells,
                            "five_view_quality": quality_payload,
                        })
                    else:
                        sheets.pop(cname, None)
                        safe_message = self._safe_error_text(last_error)
                        failed_quality = quality_payload or {
                            "passed": False,
                            "entropy": [],
                            "palette_similarity": 0,
                            "unique_view_hashes": 0,
                            "issues": [{
                                "code": failure_phase,
                                "message": safe_message or f"角色「{cname}」数字演员设定集生成失败",
                            }],
                        }
                        characters.append({
                            "name": cname,
                            "role": role,
                            "desc": cdesc,
                            "sheet": sheet_url,
                            "sheet_type": "actor_sheet_25_cell",
                            "views": views,
                            "sheet_cells": cells,
                            "five_view_quality": failed_quality,
                        })
                        failed_names.append(cname)
                    _persist_character_assets()

                if failed_names:
                    raise RuntimeError("以下角色数字演员设定集生成失败：" + "、".join(failed_names))
            except Exception as e:
                logger.error(f"[Stage3] 数字演员设定集生成异常: {type(e).__name__}")
                raise
            task["assets"]["3_sheets"] = sheets
            # 结构化角色清单(名字+身份+特征+设定集各格)，供前端阶段3罗列与下游逐镜复用
            task["assets"]["3_characters"] = characters

            # 场地、道具、服装、特效同样是分镜的锁定依据：归档到资产库、复用同名旧资产、
            # 补齐缺失参考图，并落下阶段4门禁读取的齐备快照。
            if self._catalog_kinds_to_fill(task):
                # The writer listed no costumes or effects (older script, or a run that skipped
                # them): read them off the screenplay now so their reference images are drawn too.
                self._progress_step(task, 91, "从剧本补全服装与特效清单")
                try:
                    self._fill_production_catalog(task)
                except Exception as exc:  # the rest of the library still gets filed and drawn
                    logger.warning("[Stage3] 服装/特效清单补全失败（不阻断）: %s", type(exc).__name__)
            self._progress_step(task, 92, "同步拍摄资产到资产库并补齐参考图")
            task["assets"][READINESS_KEY] = complete_project_assets(task, generate_missing=True)

            self._progress_step(task, 95, "角色造型一致性质检自检")
            task["logs"]["3"] = self.run_real_consistency_check(3, "角色设计师造型", task["assets"], config, title, task_id=task_id)

            self._progress_step(task, 97, "编译 Character Designer 数字演员设定集资产契约")
            task["assets"]["3_character_dashboard"] = compile_character_dashboard(task).model_dump(
                mode="json", by_alias=True
            )

        elif stage == 4:
            # 阶段 4：分镜师 (Storyboard Artist)
            task["stage_name"] = "分镜师分镜拆解"
            self._progress_step(task, 15, "调用 LLM · 15秒切片分镜拆解与九宫格规划")
            # 多指南叠加易撑爆上下文(Agnes-flash 等小模型会挂起/超时)，各取核心前段截断，
            # 既保留方法论又把总量控制在安全范围(直连 deepseek-v4-pro 时可调大或取消截断)。
            # 经 production-knowledge-master 装载器读取(登记预算 8000/5000，行边界截断)
            director_guide = load_section("director-shot-guide")
            # 分镜师配药单：九宫格是静图，模块含群像/机位/表演、不含时序词；与既有硬编码负面串合并挂尾。
            storyboard_negative = self._role_negative_suffix(task, AgentRole.STORYBOARD_ARTIST)
            task["assets"]["4_negative_prompt_modules"] = self._role_negative_modules(task, AgentRole.STORYBOARD_ARTIST)
            continuity_guide = load_section("continuity-design")
            shot_continuity = load_section("plot-shot-coherence")
            emotion_lib = load_section("emotion-expression")
            action_guide = load_section("martial-arts")
            scene_design = load_section("scene-design")
            # 技能前缀按本场戏的类型(打戏/文戏)另装章节，所以提示词按场次类型各编译一份：
            # 头尾两段与场次无关，中间夹的技能前缀才是变量。
            sys_prompt_head = self._agent_role_prompt(task, AgentRole.STORYBOARD_ARTIST) + "\n\n"
            sys_prompt_tail = (
                STORYBOARD_SCRIPT_PROMPT
                + "\n\n"
                "Role: AI 分镜师智能体 (Storyboard Artist Agent)\n"
                "Methodology: 将剧本转化为分镜清单 (Shot List)。结合《导演拍摄分镜指南》，"
                "运用36运镜、8种站位和16种空间构图，以及 88种运镜提示词进行拆解。输出一个标准的 Markdown 分镜表，"
                "必须包含列：镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的。画面内容仅写可见动作。\n"
                "【情绪具象化硬要求】：画面内容里的人物情绪一律写成可观察的面部肌肉/眼神/嘴部/下颌/呼吸/肢体细节"
                "（如‘眉心收紧、眼眶泛红、嘴唇抿成一条线、指节发白’），严禁只写‘悲伤/愤怒’等抽象词。\n"
                "【动作戏硬要求】：凡打斗/对抗镜头，按‘出招-受击’拆分为多镜，用物理力学受力反馈（重心沉降扬尘、"
                "拳拳到肉的面部形变、被击退滑地擦痕、气浪碎石），并严格锁定角色左右站位防止180度越轴。\n"
                "【镜头连贯性硬要求】：每个镜头都要承接上一镜最后一帧——锁住人物/空间/动作/情绪/道具/光影六个连贯锚点；"
                "每镜只推进一个小动作，严禁从‘发现’直接跳到‘离开’，按‘发现→反应→消化→决定→行动’逐镜拆分；"
                "情绪逐级递进不突变；道具始终在同一只手/同一位置；正反打遵守180度轴线、角色左右关系不翻转。\n"
                "【场景设计硬要求】：场景必须服务剧情(告白/对峙/揭露/崩溃/复仇等)，不是漂亮背景；"
                "为整场戏先定‘场景圣经’(空间布局/人物左右站位/关键道具位置/主光方向与色温/前中后景层次)，"
                "后续所有镜头都继承同一场景圣经，保持同一布局、同一光源、同一道具位置，背景简洁稳定不随机发挥。\n\n"
                f"【场景设计指南(场景圣经/功能化场景/空间布局/光影道具叙事)如下】：\n{scene_design}\n\n"
                f"【导演拍摄分镜完全指南与运镜标准如下】：\n{director_guide}\n\n"
                f"【情绪与面部表情提示词库(把抽象情绪转为可观察微表情/眼神/肢体)如下】：\n{emotion_lib}\n\n"
                f"【电影级武打镜头设计指南(力学受力反馈/五镜动作链/防越轴/慢动作卡点)如下】：\n{action_guide}\n\n"
                f"【情节与镜头连贯性提示词(六锚点/连续性圣经/承接上一镜/逐镜单动作)如下】：\n{shot_continuity}\n\n"
                f"【连续性与180度轴线防跳轴规范如下】：\n{continuity_guide}\n\n"
                "【本阶段输出覆盖规则】：上述补充提示词中的拆镜、时长、八要素、入镜角色与场景标识规则全部生效；"
                "为适配本阶段的严格九宫格产线，本次只选取因果连续、信息密度最高的恰好9镜。"
                "Markdown表格列必须严格保持：镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的 | 入镜角色 | 场景标识。\n"
                "请特别注意：输出恰好9个连续镜头，作为单张3×3九宫格分镜；每格必须提供新叙事信息。"
                "九镜覆盖完整情节，按地点建立→人物关系→关键情绪递进；普通镜头1.5-4秒，"
                "高风险动作镜头1.5-2.5秒，只有有明确情绪动机的长镜头才可延长且不超过8秒。"
            )
            # 追加自动进化的历史生产教训 (无 active 教训时为空串，不产生噪声)
            lessons_block = stage_lessons_block(4)
            if lessons_block:
                sys_prompt_tail += f"\n\n{lessons_block}\n"

            sys_prompt_by_kind: Dict[str, str] = {}

            def _sys_prompt_for(scene_kind: str) -> str:
                """打戏/文戏各编译一份系统提示词，同类场次复用，不重复读技能包。"""
                cached = sys_prompt_by_kind.get(scene_kind)
                if cached is None:
                    cached = (
                        sys_prompt_head
                        + self.storyboard_skill_prefix(config, scene_kind=scene_kind)
                        + sys_prompt_tail
                    )
                    sys_prompt_by_kind[scene_kind] = cached
                return cached

            # 剧本大纲(2_breakdown.scenes)是分镜的唯一基准：一集一集推进，每集为每个场景生成一张九宫格。
            # Old tasks without structured outlines are split by screenplay headings.
            scenes = self._breakdown_scenes(task)
            breakdown_missing = not scenes
            if breakdown_missing:
                scenes = fallback_scenes_from_script(str(task["assets"].get("2") or ""))
                if not scenes:
                    raise ValueError("剧本大纲缺少可用场景，请先完成剧本拆解")

            def _refresh_storyboard_progress(boards_state: Dict[str, Any]) -> Dict[str, Any]:
                progress_state = self._storyboard_progress(boards_state)
                if breakdown_missing:
                    progress_state["fallback"] = "no_breakdown_single_board" if len(scenes) == 1 else "screenplay_scene_headings"
                task["assets"]["4_progress"] = progress_state
                return progress_state

            # 一初始化就把 4_scene_boards 全量写齐(未开始的场景 status=pending)并立即落库，
            # 前端首轮轮询即可渲染全部集与「待创作」场景卡片。
            boards = self._init_scene_boards(task, scenes)
            task["assets"]["4_scene_boards"] = boards
            progress = _refresh_storyboard_progress(boards)
            self._progress_save(task)

            scene_map: Dict[str, Dict[str, Any]] = {}
            for scene in scenes:
                scene_map.setdefault(str(scene.get("scene_id") or "").strip(), scene)

            # 严格顺序：只处理第一个未 complete 的集，上一集未完成绝不生成下一集的任何场景。
            target_episode = next(
                (item["number"] for item in progress["episodes"] if not item["complete"]), None
            )
            if target_episode is None:
                self._progress_step(task, 90, "全部集的分镜九宫格均已完成，无需重跑")
            else:
                pending_ids = [
                    scene_id for scene_id, entry in boards.items()
                    if entry.get("episode") == target_episode and entry.get("status") != "done"
                ]
                succeeded = 0
                failed = 0
                char_info = (char1_name, char1_desc, char2_name, char2_desc)
                for offset, scene_id in enumerate(pending_ids):
                    entry = boards[scene_id]
                    entry["status"] = "generating"
                    entry["shots_done"] = 0
                    percent = 12 + int(78 * offset / max(1, len(pending_ids)))
                    self._progress_step(
                        task, percent,
                        f"第{target_episode}集 · 场景 {scene_id} 九宫格分镜生成 ({offset + 1}/{len(pending_ids)})",
                    )
                    scene = scene_map[scene_id]
                    # 打戏场次要换装打戏章节，判据来自剧本正文/题材/动作强度标注，
                    # 判成什么如实记进场景板，复核时能对着日志核对是不是判错了。
                    scene_kind = self._detect_scene_kind(
                        str(scene.get("content") or ""), genre, scene.get("action_intensity"),
                    )
                    entry["scene_kind"] = scene_kind
                    logger.info(
                        "[Stage4] 场景 %s 按 %s 场次装载分镜技能章节 (sections=%s)",
                        scene_id, scene_kind,
                        "/".join(self.storyboard_skill_sections(
                            str(config.get("video_model") or ""), scene_kind=scene_kind)),
                    )
                    try:
                        payload = self._generate_scene_board(
                            task, config, scene,
                            sys_prompt=_sys_prompt_for(scene_kind),
                            storyboard_negative=storyboard_negative,
                            title=title, genre=genre, dir_style=dir_style,
                            shot_style=shot_style, guidance=guidance,
                            char_info=char_info,
                        )
                    except Exception as scene_error:
                        # 单场景失败标 failed 不中断本集其余场景；集内有 failed 则该集不 complete
                        failed += 1
                        entry["status"] = "failed"
                        entry["shots_done"] = 0
                        entry["error"] = self._safe_error_text(scene_error)
                        logger.error(
                            "[Stage4] 场景 %s 九宫格生成失败: %s", scene_id, type(scene_error).__name__,
                        )
                    else:
                        succeeded += 1
                        entry["status"] = "done"
                        entry["shots_done"] = len(payload["shots"])
                        # 占位补格数量透传到场景板：shots_done=9 只保证九格图齐，
                        # filler_shots>0 说明其中有占位拆镜，复核界面据此提示重做。
                        entry["filler_shots"] = int(payload.get("filler_shots") or 0)
                        entry["grid_url"] = payload["grid_url"]
                        # 这场戏按哪个题材簇、什么感觉拍的，如实记进场景板，复核时能对着看。
                        entry["direction"] = payload.get("direction") or {}
                        entry["prompt_detail"] = payload["prompt_detail"]
                        entry["grid_prompt"] = payload["grid_prompt"]
                        # 按当前站位重画完成，之前「站位已改、画面过期」的标记随之解除。
                        entry.pop("spatial_stale", None)
                        # 连续性自检不再只是弹层里的清单：结论落到场景板，error 级失败会
                        # 在 _missing_stage_outputs 里挡住阶段五 (见 app/core/continuity_audit.py)。
                        entry["continuity"] = audit_prompt_detail(payload.get("prompt_detail"))
                        if not entry["continuity"]["passed"]:
                            logger.warning(
                                "[Stage4] 场景 %s 连续性自检未通过: %s",
                                scene_id, ",".join(entry["continuity"]["error_codes"]),
                            )
                        entry.pop("error", None)
                        flat_shots = task["assets"].get("4") if isinstance(task["assets"].get("4"), list) else []
                        task["assets"]["4"] = [
                            shot for shot in flat_shots if shot.get("scene_id") != scene_id
                        ] + payload["shots"]
                        # 旧键形状向后兼容：镜表原文/九宫格图/结构化分镜/质检以最近完成的场景为准，
                        # 阶段整体完成度由 4_progress 把关(见 _missing_stage_outputs)。
                        task["assets"]["4_raw"] = payload["raw"]
                        task["assets"]["4_grid"] = payload["grid_url"]
                        task["assets"]["4_grid_prompt"] = payload["grid_prompt"]
                        task["assets"]["4_storyboard"] = payload["storyboard"]
                        task["assets"]["4_prompt_detail"] = payload["prompt_detail"]
                        task["assets"]["4_quality"] = payload["quality"]
                    task["assets"]["4_continuity_audit"] = aggregate_scene_boards(boards)
                    # 每完成一个场景立即持久化，前端轮询能看到增量进度
                    progress = _refresh_storyboard_progress(boards)
                    self._progress_save(task)
                if pending_ids and succeeded == 0:
                    raise RuntimeError(
                        f"第{target_episode}集分镜九宫格全部生成失败(共{failed}个场景)，可重跑本阶段续跑"
                    )

            self._progress_step(task, 95, "分镜一致性质检自检")
            task["logs"]["4"] = self.run_real_consistency_check(4, "分镜师分镜拆解", task["assets"], config, title, task_id=task_id)

        elif stage == 5:
            # 阶段 5：视觉总监 (Visual Director)
            task["stage_name"] = "视觉总监多镜头多帧生成"
            self._progress_step(task, 8, "准备镜头运动契约与数字演员身份视图参考")

            # 视觉规范、Agent 契约与模块化负面词都来自同一委员会计划。
            # 经 production-knowledge-master 装载器读取(登记预算 0=全文)，下游按现状自行切片 [:1000] 进 img prompt。
            visual_style_doc = load_section("visual-style")
            visual_agent_brief = self._agent_role_prompt(task, AgentRole.VISUAL_DIRECTOR)
            # 本阶段无独立 sys_prompt(不走 call_llm)，教训块追加到视觉总监的 Agent 策略简报末尾，
            # 随 agent_policy 一并写入各镜头资产，供人工复核与单镜重做时参考。
            lessons_block = stage_lessons_block(5)
            if lessons_block:
                visual_agent_brief += f"\n\n{lessons_block}\n"
            self._ensure_agent_council(task)
            # 视觉总监配药单：唯一同时出图与出视频的角色。门禁要求图像侧与视频侧分别编译——
            # 只有视频侧携带时序连续性模块(temporal_continuity)，静帧发时序词是纯噪声。
            negative_prompt_modules = self._role_negative_modules(task, AgentRole.VISUAL_DIRECTOR)
            visual_negative_image = self._role_negative_suffix(
                task, AgentRole.VISUAL_DIRECTOR, exclude=("temporal_continuity",))
            visual_negative_video = self._role_negative_suffix(task, AgentRole.VISUAL_DIRECTOR)
            # 全片风格锁：同一套质感写进每一镜的提示词，2D/3D 漫剧不再被写实风格说明压掉。
            style_pack = style_packs.resolve_pack(config)
            # 这个模型在本项目上已经栽过两次的地方，这一轮先绕开：既写进提示词，也补进负面词。
            learned_notes = generation_feedback.preventive_notes(task, str(config.get("video_model") or ""))
            learned_negatives = generation_feedback.preventive_negatives(task, str(config.get("video_model") or ""))
            if learned_notes:
                logger.info("[Stage5] 按已知模型弱点预防性加固：%s", "；".join(learned_notes)[:200])
            # 音画同生的模型（MiniMax H3）自己出声：声音要写成对白 / 环境 / 配乐三层，
            # 每个说话的角色还要带上全片不变的音色锚定，否则跨镜换人声。
            audio_native = normalize_video_provider(str(config.get("video_model") or "")).family == "minimax_h3"
            voice_anchors = h3_sound_design.anchors_from_characters(
                task["assets"].get("3_characters") or [], gender_of=guess_gender,
            ) if audio_native else {}

            shots = task["assets"].get("4", [])
            if not isinstance(shots, list):
                shots = parse_storyboard_table(task["assets"].get("4_raw", ""), [])
                
            if not shots:
                # 没有分镜就没有可拍的内容：不替项目编三镜“挑衅—反扑”的套路戏去付费生成
                raise ValueError("第 5 阶段需要第 4 阶段的分镜表，请先完成分镜设计")
                
            # 数字演员身份视图锚点 (来自阶段3)
            char_sheets = task["assets"].get("3_sheets") or {}

            # 逐镜预览音轨用：角色性别 (台词配音男女声分配)
            char1_gender = "male" if guess_gender(char1_name) == "male" else "female"
            char2_gender = "male" if guess_gender(char2_name) == "male" else "female"

            # Clips an earlier run of this stage already produced: reused when the request is the same.
            earlier_clips = {
                str(clip.get("shot_id")): clip
                for clip in (task["assets"].get("5") or []) if isinstance(clip, dict) and clip.get("video_url")
            }
            scenes_by_id = {
                str(scene.get("scene_id") or ""): scene for scene in self._breakdown_scenes(task)
            }
            requested_reference_mode = normalize_video_reference_mode(
                config.get("video_reference_mode")
            )
            # Historical projects may still contain the removed first_frame value.
            # Persist the migration before generation so later runs remain deterministic.
            config["video_reference_mode"] = requested_reference_mode

            def _generate_motion_video(
                *,
                prompt_text: str,
                first_frame: str | None,
                last_frame: str | None,
                sequence_images: list[str],
                identity_images: list[str],
                motion_videos: list[str],
                timing_audios: list[str],
                seconds: int,
                intent: VideoGenerationIntent,
                seed: int | None = None,
            ) -> tuple[str | None, dict]:
                plan = plan_video_references(
                    requested_reference_mode,
                    model=config["video_model"],
                    first_frame=first_frame,
                    last_frame=last_frame,
                    sequence_images=sequence_images,
                    reference_images=identity_images,
                    reference_videos=motion_videos,
                    reference_audios=timing_audios,
                    intent=intent,
                )
                if plan.provider_status != "integrated":
                    if not self.gateway.video_family_ready(plan.provider_family, config["video_model"]):
                        raise RuntimeError(
                            f"视频模型族 {plan.provider_family} 的自动路由已完成，"
                            f"但未配置可用的运行时凭据（状态 {plan.provider_status}），禁止冒充其他供应商提交"
                        )
                    executable = self.gateway.video_family_modes(plan.provider_family)
                    if executable is not None and plan.mode not in executable:
                        raise RuntimeError(
                            f"视频模型族 {plan.provider_family} 的适配器尚不能执行 {plan.mode} 模式"
                            f"（已验证接口只支持 {'、'.join(sorted(executable))}），本镜不提交"
                        )
                # The prompt counted only the identity images; number them by what this request carries.
                prompt_text = renumber_reference_mentions(prompt_text, identity_images, plan)
                url = self.gateway.generate_video(
                    config["video_model"],
                    plan.first_frame,
                    prompt_text,
                    prefer_provider="seedance",
                    style_pack=style_pack.id,
                    last_frame=plan.last_frame,
                    ref_images=plan.reference_images,
                    ref_videos=plan.reference_videos,
                    ref_audios=plan.reference_audios,
                    duration=seconds,
                    seed=seed,
                )
                return url, {**plan.model_dump(mode="json"), "prompt_sent": prompt_text}

            # Every shot is prepared first (prompts, contracts, references: no provider call), then its
            # paid work goes through the generation queue as three items — frames → video → assemble —
            # so image, video and voice providers each run under their own ceiling and a restart or a
            # cancel shows exactly what was waiting.
            def _prepare_shot(shot_no: int, shot: dict) -> dict:
                shot_idx = shot_no - 1
                shot_id = shot.get("shot_id", shot_idx + 1)
                size = shot.get("size", "MS")
                motion = shot.get("motion", "Dolly In")
                desc = shot.get("desc", "")
                dialogue = shot.get("dialogue", "")

                # 跨镜连贯性约束 (plot-shot-coherence)：第0镜为建立镜不写"承接上一镜"，
                # 其余每镜都承接上一镜最后一帧；正/负向连贯六锚点约束拼进所有视频提示词。
                carry_lead = "" if shot_idx == 0 else f"{self.gateway.CONTINUITY_CARRY}. "

                # 动态计算时长：由剧情/台词/动作复杂度决定，上限跟随所选视频模型的单镜能力
                # （seedance2.5 可到 30s，H3/seedance2.0 为 15s），而不是写死 15/12。
                clip_ceiling = max_shot_seconds(str(config.get("video_model") or ""))
                if dialogue:
                    duration = min(clip_ceiling, int(len(dialogue) / 3.5) + 2)
                else:
                    duration = min(clip_ceiling, int(len(desc) / 8) + 2)
                duration = max(MIN_SHOT_SECONDS, duration)
                # 视觉工作区里人工定过的运镜 / 景别 / 时长优先于启发式；一镜一种运镜，
                # 用所选供应商文档里的写法插进提示词，不做二次翻译。
                visual = shot.get("visual") if isinstance(shot.get("visual"), dict) else {}
                if visual:
                    duration = max(MIN_SHOT_SECONDS, min(clip_ceiling, int(visual.get("duration_seconds") or duration)))
                    motion = render_camera_motion(
                        str(visual.get("camera_motion") or motion),
                        normalize_video_provider(str(config.get("video_model") or "")).family,
                    )
                    size = str(visual.get("shot_type") or size)
                    if str(visual.get("action") or "").strip():
                        desc = f"{desc}；动作演变：{str(visual['action']).strip()}"

                # 融合角色特征五维 DNA 并绑定身份视图
                char_prompt = ""
                ref_sheets = []
                if char1_name and char1_name in desc:
                    char_prompt += _character_clause(char1_name, char1_desc)
                    if char_sheets.get(char1_name):
                        ref_sheets.append(char_sheets[char1_name])
                if char2_name and char2_name in desc:
                    char_prompt += _character_clause(char2_name, char2_desc)
                    if char_sheets.get(char2_name):
                        ref_sheets.append(char_sheets[char2_name])
                if not ref_sheets and char_sheets:
                    ref_sheets = list(char_sheets.values())[:2]

                lock_pos = self.gateway.SHEET_LOCK_POSITIVE if ref_sheets else ""
                lock_neg = self.gateway.SHEET_LOCK_NEGATIVE if ref_sheets else ""
                raw_contract = shot.get("motion_contract")
                if raw_contract:
                    contract = ShotMotionContract.model_validate(raw_contract)
                else:
                    stored_board = NineGridStoryboard.model_validate(task["assets"]["4_storyboard"])
                    contract = ShotMotionContract.from_panel(stored_board.panels[int(shot_id) - 1])
                stored_fingerprint = shot.get("contract_fingerprint")
                if stored_fingerprint and stored_fingerprint != contract.contract_fingerprint:
                    raise RuntimeError(
                        f"镜头{shot_id}的契约指纹已失效，必须重新生成分镜图片和运镜计划"
                    )
                if (
                    (desc and desc != contract.subject_action)
                    or (motion and motion != contract.camera_movement)
                    or (size and size != contract.shot_size)
                ):
                    raise RuntimeError(
                        f"镜头{shot_id}的分镜明细与运镜契约发生漂移，必须重新编译该镜头"
                    )
                compiled_image = compile_storyboard_image_prompt(
                    contract,
                    visual_style=f"{visual_style_doc[:600]}；{style_packs.image_style_line(style_pack, lighting=dir_style)}",
                )
                compiled_motion = compile_motion_prompt(contract)
                assert_prompt_pair_consistent(compiled_image, compiled_motion)
                img_prompt = (
                    f"{lock_pos}。{compiled_image.prompt}{char_prompt}。"
                    f"strict consistent character features{self.gateway.DEID_POSITIVE}{self.gateway.SCENE_STABILITY_POSITIVE}。"
                    f"{lock_neg}{style_packs.identity_negative(style_pack, self.gateway.DEID_NEGATIVE)}"
                    f"{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
                    f"{visual_negative_image}"
                )

                # 已授权真人素材优先：本镜主导角色若配置了可信素材库授权素材，直接用它作首帧，
                # 让真实演员的脸进入画面且通过 Ark「疑似真人」审核 (素材已在授权白名单)。
                authorized_first = None
                for _cn, _role in ((char1_name, "主角"), (char2_name, "反派")):
                    if _cn and _cn in desc:
                        _a = self.gateway.resolve_authorized_face(_cn, _role)
                        if _a:
                            authorized_first = _a
                            break

                # 已批准的 Stage4 分镜是镜头契约的首帧；授权素材仅作为缺图时的回退。
                img_url = shot.get("image_url") or authorized_first

                end_state_markers = (
                    "完成", "到位", "落座", "关闭", "完全", "停在", "抓住", "递给",
                    "交付", "切黑", "最终", "结束于", "comes to rest", "fully closes",
                )
                exact_end_required = (
                    requested_reference_mode == "first_last_frame"
                    or any(marker in contract.end_state for marker in end_state_markers)
                )
                end_prompt = None
                if exact_end_required:
                    compiled_end = compile_storyboard_image_prompt(
                        contract,
                        visual_style=f"{visual_style_doc[:600]}；{style_packs.image_style_line(style_pack, lighting=dir_style)}",
                        frame_state="end",
                    )
                    end_prompt = (
                        f"{lock_pos}。{compiled_end.prompt}{char_prompt}。"
                        f"{lock_neg}{style_packs.identity_negative(style_pack, self.gateway.DEID_NEGATIVE)}"
                        f"{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
                        f"{visual_negative_image}"
                    )

                sequence_images = list(shot.get("sequence_images") or [])
                motion_refs = list(shot.get("reference_videos") or [])
                timing_refs = list(shot.get("reference_audios") or [])
                # 导演台白模视频拍的是某一版站位：站位改过之后它就过期了，和过期的九宫格一样不能悄悄拿来用；
                # 仍然有效时它是唯一的机位参考，实测的机位句不再与它并列出现（白模规则 3）。
                desk = director_desk.motion_inputs(task, shot, motion_refs, contract.blocking, compiled_motion.prompt)
                motion_refs = desk.reference_videos
                if desk.refused:
                    logger.warning(
                        "[Stage5] 镜头%s的导演台白模视频按旧站位拍摄，站位已修改，本镜不使用该参考（%s 条）；请在导演台重新截取",
                        shot_id, len(desk.refused),
                    )
                # 多参考生视频：五视图之外再绑定本镜命中的场地、道具、服装、特效参考图，
                # 与分镜出图用的是同一套项目资产；资产库不可读时整段停下，不悄悄退化。
                library_references: list = []
                scene_record = scenes_by_id.get(str(shot.get("scene_id") or ""))
                # How the writer asked each line of this shot to be played (shot plan ``delivery``).
                scene_lines = [
                    line for line in ((scene_record or {}).get("dialogue") or [])
                    if isinstance(line, dict) and str(line.get("text") or "").strip()
                ]
                shot_lines = [line for line in scene_lines if str(line.get("text")) in str(dialogue or "")] or scene_lines
                delivery_notes = [
                    f"{str(line.get('speaker') or '旁白')}：{str(line.get('delivery')).strip()}"
                    for line in shot_lines if str(line.get("delivery") or "").strip()
                ]
                emotion_reading = read_emotion("；".join(delivery_notes), contract.expression, desc)
                if scene_record is not None:
                    scene_elements = load_storyboard_elements(task, scene_record)
                    try:
                        library_references = panel_context(
                            compile_scene_context(task, scene_record, scene_elements), shot,
                        )["references"]
                    except ValueError as exc:
                        logger.warning("镜头%s资产绑定跳过: %s", shot_id, exc)
                sheet_pairs = [
                    (name, char_sheets[name]) for name in (char1_name, char2_name)
                    if name and char_sheets.get(name) in ref_sheets
                ] or [(name, url) for name, url in char_sheets.items() if url in ref_sheets]
                identity_images, reference_notes = merge_video_references(sheet_pairs, library_references)
                # 提示词里的 @[名字]：本镜每个参考图对应的资产，第 N 项就是参考图 N。
                reference_entries = video_reference_entries(sheet_pairs, library_references)
                reference_numbers = {name: number for number, (_, name, _) in enumerate(reference_entries, start=1) if name}
                mention_kinds = {name: kind for kind, name, _ in reference_entries if name}
                contract = contract.model_copy(update={
                    "storyboard_image": img_url,
                    # Private inline bytes are transient provider inputs, not task JSON.
                    "reference_images": [url for url in identity_images if url.startswith(("http://", "https://"))],
                    "reference_videos": motion_refs,
                    "reference_audios": timing_refs,
                })
                intent = VideoGenerationIntent(
                    exact_end_frame_required=exact_end_required,
                    narrative_image_sequence=bool(sequence_images),
                    identity_consistency_required=bool(identity_images),
                    motion_reference_required=bool(motion_refs),
                    audio_rhythm_required=bool(timing_refs),
                    multi_shot_output=bool(shot.get("multi_shot_output")),
                )
                dialogue_line = f"。原文台词保持不变：{dialogue}" if dialogue else ""
                shot_sound = (
                    (shot.get("sound") or contract.sound)
                    + (f"；环境音效：{str(visual.get('ambiance_audio')).strip()}" if visual and str(visual.get("ambiance_audio") or "").strip() else "")
                )
                sound_layers, voice_locks, sound_checks = "", [], []
                if audio_native:
                    speaking = [
                        voice_anchors[name]
                        for name in dict.fromkeys(speakers_in(dialogue, list(voice_anchors)))
                        if name in voice_anchors
                    ]
                    _, mood = h3_sound_design.delivery_for_emotion(
                        detect_emotion(f"{desc}{dialogue}", notes=f"{'；'.join(delivery_notes)} {contract.expression}")
                    )
                    compiled_sound = h3_sound_design.compile_sound_prompt(
                        speakers=speaking,
                        tone=mood,
                        narration=bool(dialogue) and not speaking,
                        ambience=[part for part in re.split(r"[；;·、]", shot_sound) if part.strip()][:3],
                        music="",
                        spacious=any(word in contract.scene for word in ("大厅", "广场", "礼堂", "走廊", "隧道", "山谷")),
                        silent=not dialogue.strip(),
                    )
                    sound_layers = compiled_sound.text
                    voice_locks = list(compiled_sound.voice_locks)
                    sound_checks = [
                        {"code": check.code, "passed": check.passed, "detail": check.detail}
                        for check in compiled_sound.checks
                    ]
                    failed = [check for check in compiled_sound.checks if not check.passed]
                    if failed:
                        logger.warning(
                            "[Stage5] 镜头%s 声音提示词未通过 %s：%s",
                            shot_id, "、".join(check.code for check in failed), failed[0].detail,
                        )
                # 提示词按风格锁分层编译：风格锁 → 素材职责 → 结构声明 → 六层锁 → 镜头块 →
                # 声音 → 铁律 → 负向词，并按目标模型的字数预算做压力裁剪（先砍声音/环境/色彩，
                # 锁定标签、主体、动作、机位、台词绝不裁）。
                compiled_video = compile_shot_prompt(
                    style_pack,
                    ShotPromptInput(
                        shot_index=shot_no,
                        duration_seconds=duration,
                        shot_size=size,
                        camera_movement=motion,
                        subject_action=f"{desc}{dialogue_line}",
                        scene=contract.scene,
                        blocking=desk.blocking,
                        start_state=contract.start_state,
                        end_state=contract.end_state,
                        eyeline=contract.eyeline,
                        props=contract.props,
                        characters=contract.characters,
                        lighting=contract.lighting,
                        sound=shot_sound,
                        sound_layers=sound_layers,
                        dialogue=dialogue,
                        # The named emotion stays; what a camera can see of it is added (face, body).
                        expression="；".join(part for part in (
                            contract.expression.strip(),
                            f"外化为{emotion_reading.visible}" if emotion_reading.visible and emotion_reading.visible not in contract.expression else "",
                        ) if part),
                        dialogue_notes="；".join(
                            [*delivery_notes, *(f"声音：{'、'.join(emotion_reading.voice_notes)}" for _ in [0] if emotion_reading.voice_notes)]
                        ),
                        composition=contract.composition,
                        cast_refs=[name for kind, name, _ in reference_entries if kind == "actor" and name],
                        scene_refs=[name for kind, name, _ in reference_entries if kind == "scene" and name],
                        prop_refs=[name for kind, name, _ in reference_entries if kind == "prop" and name],
                        motion_prompt=f"{carry_lead}{desk.motion_prompt}",
                        cut_in=shot.get("cut_in") if isinstance(shot.get("cut_in"), dict) else None,
                        reference_notes=[reference_notes] if reference_notes else [],
                        reference_kinds=["five_view"] if identity_images else [],
                        first_frame=True,
                        last_frame=exact_end_required,
                        tone=f"{dir_style}，{style_pack.tone_default}",
                        extra_negatives=[
                            *([visual_negative_video] if visual_negative_video.strip() else []),
                            *learned_negatives,
                        ],
                        continuity_constants=[
                            f"{self.gateway.CONTINUITY_POSITIVE}。{self.gateway.CONTINUITY_NEGATIVE}{self.gateway.CLONE_NEGATIVE}",
                            *(f"音色铁律：{line}" for line in voice_locks),
                            *(f"已知弱点规避：{note}" for note in learned_notes),
                        ],
                    ),
                    model=str(config.get("video_model") or ""),
                    max_duration_seconds=clip_ceiling,
                )
                # 人工改过的提示词优先；展示版保留 @[名字]，发给模型前换成「名字（参考图N）」。
                prompt_override = str(shot.get("video_prompt_override") or "").strip()
                display_prompt = prompt_override or compiled_video.text
                vid_prompt = resolve_mentions(display_prompt, reference_numbers)
                if compiled_video.pressure.tier == "red":
                    logger.warning(
                        "[Stage5] 镜头%s提示词超出 %s 预算 (%s/%s 字)，已裁掉 %s",
                        shot_id, compiled_video.pressure.model, compiled_video.pressure.length,
                        compiled_video.pressure.budget, "、".join(compiled_video.pressure.dropped) or "无可裁字段",
                    )
                # 固定种子 + 多版本择优：同一输入渲染 N 个候选，首个成功版本先入片，
                # 用户可在视觉工作区改选；任一候选失败即停止，不为一镜烧掉全部预算。
                base_seed = visual.get("seed") if visual and isinstance(visual.get("seed"), int) else None
                candidate_count = max(1, min(4, int(visual.get("candidates") or 1))) if visual else 1
                return {
                    "shot_no": shot_no, "shot_idx": shot_idx, "shot_id": shot_id, "shot": shot,
                    "size": size, "motion": motion, "desc": desc, "dialogue": dialogue, "duration": duration, "visual": visual,
                    "img_url": img_url, "img_prompt": img_prompt, "ref_sheets": ref_sheets, "end_prompt": end_prompt,
                    "contract": contract, "compiled_motion": compiled_motion, "compiled_video": compiled_video, "vid_prompt": vid_prompt,
                    "display_prompt": display_prompt, "prompt_edited": bool(prompt_override),
                    "reference_numbers": reference_numbers, "mention_kinds": mention_kinds,
                    "sequence_images": sequence_images, "identity_images": identity_images, "motion_refs": motion_refs,
                    "timing_refs": timing_refs, "intent": intent, "sound_layers": sound_layers, "voice_locks": voice_locks,
                    "sound_checks": sound_checks, "base_seed": base_seed, "candidate_count": candidate_count,
                    "target_frame": None, "candidate_urls": [], "route_decision": {},
                }

            def _frames_item(req: dict) -> dict:
                """The first frame when stage 4 left none, and the exact end frame when the shot needs one."""
                img_url = req["img_url"]
                if not img_url:
                    img_url, _ = self.gateway.generate_image(
                        config["image_model"], req["img_prompt"], ref_images=req["ref_sheets"],
                    )
                target_frame = None
                if req["end_prompt"]:
                    target_frame, _ = self.gateway.generate_image(
                        config["image_model"], req["end_prompt"], ref_images=[img_url, *req["ref_sheets"]],
                    )
                req["img_url"] = img_url
                req["target_frame"] = target_frame
                req["contract"] = req["contract"].model_copy(update={"storyboard_image": img_url})
                return req

            def _video_item(req: dict) -> dict:
                """Every candidate clip of one shot, in order; the first failure stops the rest."""
                shot_id, contract = req["shot_id"], req["contract"]
                duration, base_seed, candidate_count = req["duration"], req["base_seed"], req["candidate_count"]
                img_url, target_frame, vid_prompt, intent = req["img_url"], req["target_frame"], req["vid_prompt"], req["intent"]
                sequence_images, identity_images, motion_refs, timing_refs = req["sequence_images"], req["identity_images"], req["motion_refs"], req["timing_refs"]
                candidate_urls: list[str] = []
                route_decision: dict = {}
                # The same request answered before costs nothing: a usable clip from an earlier run of
                # this stage, or one a resumed provider job delivered after a restart.
                earlier = earlier_clips.get(str(shot_id))
                if (
                    earlier and not earlier.get("stale")
                    and str(earlier.get("contract_fingerprint") or "") == contract.contract_fingerprint
                    and earlier.get("video_reference_mode_requested") == requested_reference_mode
                ):
                    candidate_urls = [url for url in (earlier.get("candidates") or [earlier["video_url"]]) if url]
                    route_decision = earlier.get("video_route_decision") or {}
                    logger.info("[Stage5] 镜头 %s 复用上一轮已生成的片段，不再提交", shot_id)
                for candidate_index in range(candidate_count):
                    if candidate_index < len(candidate_urls):
                        continue
                    resumed_url = video_jobs.downloaded_clip(
                        task, int(shot_id), candidate=candidate_index, fingerprint=contract.contract_fingerprint,
                    )
                    if resumed_url:
                        candidate_urls.append(resumed_url)
                        logger.info("[Stage5] 镜头 %s 候选 %s 取自重启后续查到的片段", shot_id, candidate_index)
                        continue
                    with video_jobs.bind_shot(
                        task_id, int(shot_id), candidate=candidate_index,
                        checkpoint={"contract_fingerprint": contract.contract_fingerprint, "seconds": duration, "mode": requested_reference_mode},
                    ):
                        candidate_url, decision = _generate_motion_video(
                            prompt_text=vid_prompt,
                            first_frame=img_url,
                            last_frame=target_frame,
                            sequence_images=sequence_images,
                            identity_images=identity_images,
                            motion_videos=motion_refs,
                            timing_audios=timing_refs,
                            seconds=duration,
                            intent=intent,
                            seed=candidate_seed(base_seed, candidate_index),
                        )
                    route_decision = route_decision or decision
                    if not candidate_url:
                        break
                    candidate_urls.append(candidate_url)
                req["candidate_urls"] = candidate_urls
                req["route_decision"] = route_decision
                return req

            def _assemble_item(req: dict) -> dict:
                """The shot's preview track and its asset record, once its clips exist."""
                shot_id, shot, contract = req["shot_id"], req["shot"], req["contract"]
                size, motion, desc, dialogue, duration = req["size"], req["motion"], req["desc"], req["dialogue"], req["duration"]
                img_url, target_frame, candidate_urls, route_decision = req["img_url"], req["target_frame"], req["candidate_urls"], req["route_decision"]
                vid_prompt, compiled_video, compiled_motion = req["vid_prompt"], req["compiled_video"], req["compiled_motion"]
                sound_layers, sound_checks, base_seed = req["sound_layers"], req["sound_checks"], req["base_seed"]
                vid_url = candidate_urls[0] if candidate_urls else None
                used_reference_modes = [route_decision.get("mode")] if route_decision else []

                # 为逐镜预览片段仅挂载原文台词配音，不自动添加音乐；这与视频提示词的
                # “只生成音效，禁止生成音乐”约束保持一致。最终成片配乐仍由后续音频阶段处理。
                # voice_path 一并存入资产，供步骤6成片复用，避免重复配音。
                seg_lines = parse_shot_dialogue(
                    dialogue, char1_name, char2_name, char1_gender, char2_gender,
                    voice_narration=narration_delivery(config) == "use_tts",
                )
                voice_url, voice_path = None, None
                if seg_lines:
                    voice_url, voice_path = media_compositor.synthesize_preferred_dialogue_track(
                        seg_lines,
                        tts_model=config["tts_model"],
                        tag=f"voice_{task_id[:8]}_s{req['shot_idx']}",
                    )
                vid_url = media_compositor.attach_audio_to_clip(
                    vid_url, voice_path, bgm=False, tag=f"shotav_{task_id[:8]}_s{shot_id}")

                return {
                    "shot_id": shot_id,
                    "size": size,
                    "motion": motion,
                    "desc": desc,
                    "dialogue": dialogue,
                    "duration": duration,
                    "image_url": img_url,
                    "end_frame_url": target_frame,
                    "video_url": vid_url,
                    "candidates": candidate_urls,
                    "seed": base_seed,
                    "voice_url": voice_url,
                    "voice_path": voice_path,
                    "video_reference_mode_requested": requested_reference_mode,
                    "video_reference_modes_used": used_reference_modes,
                    "video_route_decision": route_decision,
                    "motion_prompt": req["display_prompt"],
                    "sent_prompt": vid_prompt,
                    "prompt_edited": req["prompt_edited"],
                    "reference_numbers": req["reference_numbers"],
                    "mention_kinds": req["mention_kinds"],
                    "prompt_pressure": compiled_video.pressure.as_dict(),
                    "style_pack": style_pack.id,
                    "sound_layers": sound_layers,
                    "sound_checks": sound_checks,
                    "contract_motion_prompt": compiled_motion.prompt,
                    "motion_contract": contract.model_dump(mode="json"),
                    "contract_fingerprint": contract.contract_fingerprint,
                    "artifact_fingerprint": contract.artifact_fingerprint,
                    "agent_role": AgentRole.VISUAL_DIRECTOR.value,
                    "agent_policy": visual_agent_brief,
                    "negative_prompt_modules": negative_prompt_modules,
                    # 第 4 阶段为这一镜规划的入镜切点；第 7 阶段合成时照此接片。
                    "cut_in": shot.get("cut_in") if isinstance(shot.get("cut_in"), dict) else None,
                    "continuity_state": ContinuityState(
                        characters=[name for name in (char1_name, char2_name) if name and name in desc] or [char1_name],
                        scene=shot.get("scene") or "本场戏场景圣经",
                        # 屏幕方向取自空间方案的机位测量；旧任务没有空间方案时才退回按描述词推断。
                        screen_direction=(
                            (shot.get("spatial") or {}).get("screen_direction")
                            if (shot.get("spatial") or {}).get("screen_direction") in {"left_to_right", "right_to_left", "neutral"}
                            else "left_to_right" if any(word in desc for word in ("向右", "从左向右"))
                            else "right_to_left" if any(word in desc for word in ("向左", "从右向左"))
                            else "neutral"
                        ),
                        action=desc,
                        emotion=shot.get("expression") or detect_emotion(desc),
                        props={prop: "按上一镜连续性锁定" for prop in (shot.get("props") or ["无关键道具"])},
                        lighting=f"{dir_style}统一主光方向与色温",
                        audio_bed=shot.get("sound") or "连续环境声",
                    ).model_dump(),
                }

            self._progress_step(task, 10, f"准备 {len(shots)} 镜的提示词与契约")
            requests = {shot_no: _prepare_shot(shot_no, shot) for shot_no, shot in enumerate(shots, start=1)}
            video_family = normalize_video_provider(str(config.get("video_model") or "")).family
            image_family = str(config.get("image_model") or "image").split("/")[0]
            tts_family = str(config.get("tts_model") or "tts").split("/")[0]
            queue = generation_queue.Queue()
            steps: dict[str, tuple[str, Callable[[dict], dict]]] = {}
            for shot_no, req in requests.items():
                label = f"镜头 {req['shot_id']}"
                meta = {"shot_id": req["shot_id"], "shot_no": shot_no}
                depends: list[str] = []
                if not req["img_url"] or req["end_prompt"]:
                    key = f"frames:{shot_no}"
                    queue.add(generation_queue.Item(key=key, label=f"{label} · 首尾帧", family=image_family, medium="image", meta=meta))
                    steps[key] = (str(shot_no), _frames_item)
                    depends = [key]
                key = f"video:{shot_no}"
                queue.add(generation_queue.Item(
                    key=key, label=f"{label} · 视频 ×{req['candidate_count']}", family=video_family, medium="video", depends_on=depends,
                    meta={**meta, "seconds": req["duration"], "candidates": req["candidate_count"], "job_key": video_jobs.job_key(int(req["shot_id"]), 0)},
                ))
                steps[key] = (str(shot_no), _video_item)
                key = f"assemble:{shot_no}"
                queue.add(generation_queue.Item(key=key, label=f"{label} · 配音与入片", family=tts_family, medium="audio", depends_on=[f"video:{shot_no}"], meta=meta))
                steps[key] = (str(shot_no), _assemble_item)

            completed: dict[int, dict] = {}

            def _work(item: generation_queue.Item) -> dict:
                shot_no, step = steps[item.key]
                return step(requests[int(shot_no)])

            def _persist(snapshot: dict) -> None:
                self.repo.mutate_task(task_id, lambda current: generation_queue.store_snapshot(current, snapshot))

            def _withdrawn() -> set[str]:
                current = self.repo.get_task(task_id)
                return generation_queue.withdrawn_in(current) if current else set()

            def _pause_requested() -> bool:
                current = self.repo.get_task(task_id)
                return bool(((current or {}).get("workflow_control") or {}).get("pause_requested"))

            def _on_done(item: generation_queue.Item, result: dict) -> None:
                if not item.key.startswith("assemble:"):
                    return
                completed[int(result["shot_id"]) if str(result.get("shot_id")).isdigit() else len(completed) + 1] = result
                # What is finished stays finished: the next progress save persists it, so an
                # interruption loses at most the shots in flight and a rerun reuses the rest.
                task["assets"]["5"] = [completed[key] for key in sorted(completed)]
                self._progress_step(
                    task, 10 + int(85 * len(completed) / max(len(shots), 1)),
                    f"图生视频 · 已完成 {len(completed)}/{len(shots)} 镜",
                )

            try:
                generation_queue.run(
                    queue, _work, persist=_persist, withdrawn=_withdrawn, pause_requested=_pause_requested, on_done=_on_done,
                    run_id=str((task.get("workflow_control") or {}).get("run_id") or ""),
                )
            except generation_queue.RunCancelled as cancelled:
                task["assets"]["5"] = [completed[key] for key in sorted(completed)]
                raise RuntimeError(str(cancelled)) from cancelled
            failed = [item for item in queue.by_status(generation_queue.FAILED)]
            if failed:
                task["assets"]["5"] = [completed[key] for key in sorted(completed)]
                raise RuntimeError("以下生成项失败：" + "；".join(f"{item.label}（{item.error}）" for item in failed[:5]))
            task["assets"]["5"] = [completed[key] for key in sorted(completed)]
            
            task["logs"]["5"] = self.run_real_consistency_check(5, "视觉总监多镜头生成", task["assets"], config, title, task_id=task_id)

        elif stage == 6:
            # 阶段 6：音频总监 (Audio Director) —— 按角色性别分配男女声逐句配音
            task["stage_name"] = "音频总监配音音效"
            self._progress_step(task, 12, "多角色台词解析与 TTS 配音合成")
            shots6 = task["assets"].get("5") or []
            char1_gender = "male" if guess_gender(char1_name) == "male" else "female"
            char2_gender = "male" if guess_gender(char2_name) == "male" else "female"

            # 逐镜配音：与 assets[5] 镜头顺序一一对齐 (无台词镜头为 None)，供合成时按时间轴精确对齐
            # 优先复用步骤5预览阶段已合成的逐镜配音 (voice_path)，避免重复 TTS
            shot_voices = []
            all_segments = []
            dialogue_directions = []
            voiced_count = 0
            if isinstance(shots6, list):
                for s in shots6:
                    cell = (s.get("dialogue") or "") if isinstance(s, dict) else ""
                    seg_lines = parse_shot_dialogue(
                        cell, char1_name, char2_name, char1_gender, char2_gender,
                        voice_narration=narration_delivery(config) == "use_tts",
                    )
                    if seg_lines:
                        dialogue_directions.extend([
                            {
                                "shot_id": s.get("shot_id") if isinstance(s, dict) else len(shot_voices) + 1,
                                "speaker": seg[3],
                                "voice_identity": f"{seg[3]}:locked_voice_id",
                                **dialogue_delivery_profile(seg[0], seg[2]),
                            }
                            for seg in seg_lines
                        ])
                        cached = s.get("voice_path") if isinstance(s, dict) else None
                        if cached and os.path.exists(cached):
                            vpath = cached
                        else:
                            _u, vpath = media_compositor.synthesize_preferred_dialogue_track(
                                seg_lines,
                                tts_model=config["tts_model"],
                                tag=f"voice_{task_id[:8]}_s{len(shot_voices)}",
                            )
                        shot_voices.append(vpath)
                        if vpath:
                            voiced_count += 1
                        all_segments.extend([(seg[0], seg[1]) for seg in seg_lines])
                    else:
                        shot_voices.append(None)

            # 全局兜底：若无任何逐镜台词，用主线台词合成一条，避免全片无人声
            audio_url, audio_path = None, None
            if not any(shot_voices) and speech:
                audio_url, audio_path = media_compositor.synthesize_preferred_dialogue_track(
                    [(speech, char1_gender, detect_emotion(speech))],
                    tts_model=config["tts_model"],
                    tag=f"voice_{task_id[:8]}_g",
                )
            if not audio_url and not any(shot_voices):
                audio_url = self.gateway.generate_tts(config["tts_model"], "young-man", speech)
                audio_path = None

            self._progress_step(task, 70, "合成 BGM 与环境音效")
            voiced = "、".join(f"{t}({'男声' if g=='male' else '女声'})" for t, g in all_segments[:4])
            estimated_duration = 0
            for shot in shots6 if isinstance(shots6, list) else []:
                duration_value = str(shot.get("duration", "8") if isinstance(shot, dict) else "8")
                match = re.search(r"\d+(?:\.\d+)?", duration_value)
                estimated_duration += float(match.group()) if match else 8
            estimated_duration = max(12, min(600, estimated_duration or len(shots6) * 8 or 60))
            bgm_url, bgm_path = None, None
            sfx_url, sfx_path = None, None
            if "eleven" in (config.get("tts_model") or "").lower():
                bgm_url, bgm_path = media_compositor.synthesize_elevenlabs_music(
                    f"{dir_style} {genre} short drama cinematic score, emotion arc with restrained opening, rising tension, clear climax and gentle resolution, instrumental only, leave space for dialogue",
                    estimated_duration,
                    tag=f"eleven_bgm_{task_id[:8]}",
                )
                sfx_url, sfx_path = media_compositor.synthesize_elevenlabs_sfx(
                    "cinematic short drama room tone and environmental ambience, subtle cloth movement, footsteps and natural space, no music, no speech",
                    duration_seconds=min(22, estimated_duration),
                    tag=f"eleven_sfx_{task_id[:8]}",
                )

            task["assets"]["6"] = {
                "audio_url": audio_url,
                "audio_path": audio_path,
                "shot_voices": shot_voices,
                "bgm_url": bgm_url,
                "bgm_path": bgm_path,
                "sfx_url": sfx_url,
                "sfx_path": sfx_path,
                "tts_text": voiced,
                "agent_role": AgentRole.AUDIO_DIRECTOR.value,
                "agent_policy": self._agent_role_prompt(task, AgentRole.AUDIO_DIRECTOR),
                "dialogue_directions": dialogue_directions,
                # 音频接口没有负面词通道；这两个模块是核验口径(口型时序/念白表演)，
                # 画面排除项已按门禁写进 BGM/SFX 的正向 prompt(instrumental only / no music, no speech)。
                "negative_prompt_modules": self._role_negative_modules(task, AgentRole.AUDIO_DIRECTOR),
                "elevenlabs_job_plan": {
                    "credentials": "server_environment_only",
                    "tts_endpoint": "/v1/text-to-speech/{voice_id}",
                    "dialogue_endpoint": "/v1/text-to-dialogue",
                    "sound_effect_endpoint": "/v1/sound-generation",
                    "music_endpoint": "/v1/music",
                    "voice_identity_locked": True,
                    "verbatim_dialogue_required": True,
                },
                "voice_profile": (f"逐镜情绪配音 ({voiced_count}/{len(shot_voices)} 镜有台词，按时间轴对齐)"
                                  if voiced_count else ("占位音频" if not audio_path else "全局兜底配音")),
                # 本阶段无 LLM 提示词，自动进化的历史生产教训随产物归档 (无 active 教训时为空串)
                "learned_lessons": stage_lessons_block(6),
            }
            
            task["logs"]["6"] = self.run_real_consistency_check(6, "音频总监配音音效", task["assets"], config, title, task_id=task_id)

        elif stage == 7:
            # 阶段 7：合成发布 (Composer & Publisher)
            task["stage_name"] = "合成发布渲染合流"
            self._progress_step(task, 15, "视听合流 · 转场衔接与压制渲染")
            # The cut is whatever the edit timeline says: built from stage 5 / 6 the first time,
            # refreshed when footage changed, otherwise the reviewer's trims and decisions stand.
            timeline, transition_reports = self._current_timeline(task, title)
            task["assets"][edit_timeline.TIMELINE_KEY] = timeline
            plan = edit_timeline.render_plan(timeline)
            shot_clips = plan["shot_video_urls"]
            film_title = plan["title"]
            composed_url = media_compositor.compose_film(
                shot_clips, plan["subtitles"], plan["audio_path"],
                tag=f"film_{task_id[:8]}", title=film_title, bgm=plan["bgm"],
                shot_voices=plan["shot_voices"] if any(plan["shot_voices"]) else None,
                bgm_path=plan["bgm_path"], sfx_path=plan["sfx_path"],
                transition_plans=plan["transition_plans"], trims=plan["trims"], bgm_volume=plan["bgm_volume"],
            )

            compose_mode = "ffmpeg 片头标题卡+多镜头拼接+字幕+多角色配音+BGM 真实合成"
            if composed_url:
                final_vid = composed_url
            else:
                # 合成失败时回退：取首个真实分镜视频；若一个真实分镜都没有则置空 (不再用硬编码占位视频)。
                real_clips = [u for u in shot_clips if u and LEGACY_PLACEHOLDER_MEDIA_HOST not in u]
                final_vid = real_clips[0] if real_clips else (shot_clips[0] if shot_clips else None)
                if final_vid:
                    compose_mode = "回退：采用单条分镜视频 (ffmpeg 合成未成功)"
                else:
                    compose_mode = "失败：无任何真实分镜视频可用，未产出成片"
                    logger.error("[Stage7] 无任何真实分镜视频，最终成片为空 (请检查 Seedance 图生视频是否可用)")

            task["video_url"] = final_vid
            task["assets"]["7"] = {
                "final_video_url": final_vid,
                "shot_clips": shot_clips,
                "transition_quality": transition_reports,
                "timeline_revision": timeline.get("revision"),
                "timeline_summary": edit_timeline.summary(timeline),
                "compose_mode": compose_mode,
                "agent_role": AgentRole.COMPOSER_PUBLISHER.value,
                "agent_policy": self._agent_role_prompt(task, AgentRole.COMPOSER_PUBLISHER),
                "delivery_profile": self._ensure_agent_council(task).get("delivery"),
                # 负面词台账：六个下游角色各自的配药单，随成片归档，支撑单镜重做时按原模块复现。
                "negative_prompt_ledger": self._ensure_agent_council(task).get("negative_prompt_by_role"),
                "aspect_ratio": self._ensure_agent_council(task).get("delivery", {}).get("aspect_ratio"),
                "subtitles": "已烧录中文字幕" if composed_url else "内置流光特效字幕",
                "release_state": "awaiting_evidence_backed_quality_and_human_review",
                # 本阶段无 LLM 提示词，自动进化的历史生产教训随产物归档 (无 active 教训时为空串)
                "learned_lessons": stage_lessons_block(7),
            }
            
            task["logs"]["7"] = self.run_real_consistency_check(7, "合成发布渲染合流", task["assets"], config, title, task_id=task_id)

        elif stage == 8:
            # 阶段 8：宣发 Agent (PR Agent)
            task["stage_name"] = "宣发Agent引流"
            self._progress_step(task, 25, "调用 LLM · 爆款标题与高完播率宣发文案")
            # 经 production-knowledge-master 装载器读取(登记预算 6000/5000，行边界截断)
            highlight_guide = load_section("highlight-detection")
            platform_guide = load_section("production-guidelines")
            sys_prompt = (
                self._agent_role_prompt(task, AgentRole.PR_AGENT)
                + "\n\n"
                "Role: AI 宣发智能体 (PR & Marketing Agent)\n"
                "Methodology: 遵循 seedance-social-hook 爆款引流理论。撰写适合 TikTok/抖音 的大字封面标题"
                "及满足“模式打破”与“好奇心缺口”的高完播率引流文案。"
                "所有宣传主张必须来自正片或已批准剧本的真实高光，不得制造不存在的剧情。\n\n"
                f"【高光识别、强度和观众行为标签规范】：\n{highlight_guide}\n\n"
                f"【平台、AI标识、版权、投放与指标规范】：\n{platform_guide}\n"
            )
            # 追加自动进化的历史生产教训 (无 active 教训时为空串，不产生噪声)
            lessons_block = stage_lessons_block(8)
            if lessons_block:
                sys_prompt += f"\n\n{lessons_block}\n"
            mode_line = creation_modes.promotion_guidance(config)
            if mode_line:
                sys_prompt += f"\n\n【创作类型】{mode_line}\n"
            user_prompt = "请为短剧制作爆款标题和宣发文案：\n\n【导演策划大纲】：\n" + task["assets"].get("1", "")
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
            
            pr_title, pr_body = parse_pr_info(res, title, f"《{title}》{tpl['genre_desc']}")
            task["short_link"] = settings.share_link_url(f"{tpl['short_link']}-{task_id[:8]}")
            task["pr_content"] = f"🔥 抖音爆款大字标题：{pr_title}\n📌 黄金引流文案：‘{pr_body}’"
            
            quality_gate = (task["assets"].get("7") or {}).get("quality_gate") or {}
            task["status"] = (
                "awaiting_council_review"
                if quality_gate.get("passed") is True
                else "awaiting_quality_review"
            )
            task["assets"]["8"] = {
                "short_link": task["short_link"],
                "pr_content": task["pr_content"],
                "raw_pr": res,
                "agent_role": AgentRole.PR_AGENT.value,
                "agent_policy": self._agent_role_prompt(task, AgentRole.PR_AGENT),
                "source_of_truth": "approved_script_and_final_highlights_only",
                "campaign_kpis": {
                    "three_second_retention_target": 0.70,
                    "completion_rate_target": 0.40,
                    "next_episode_click_target": 0.30,
                    "paid_conversion_target": 0.05,
                },
            }
            
            task["logs"]["8"] = self.run_real_consistency_check(8, "宣发Agent引流", task["assets"], config, title, task_id=task_id)

        # 每次成功执行一个阶段，就清除单次会话指令，保证下个阶段如果是自动生成的，不会继承上阶段的微调指令
        config["guidance_instruction"] = ""
        self._progress_done(task)
        self.repo.save_task(task_id, task)
        return task

    def submit_video_quality(
        self,
        task_id: str,
        measurements: VideoQualityMeasurements,
    ) -> Dict[str, Any]:
        """Persist an evidence-backed final decision; unreviewed films never become completed."""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        final_url = ((task.get("assets") or {}).get("7") or {}).get("final_video_url") or task.get("video_url")
        if not final_url:
            raise ValueError("尚无最终视频，不能提交质量验收")
        report = evaluate_video_quality(measurements)
        stage_assets = task.setdefault("assets", {}).setdefault("7", {})
        stage_assets["quality_gate"] = report.model_dump()
        if report.passed:
            task["status"] = "awaiting_council_review"
            task.pop("fail_reason", None)
        else:
            task["status"] = "quality_failed"
            task["fail_reason"] = "成片质量门禁未通过：" + "、".join(report.failed_dimensions)
        self.repo.save_task(task_id, task)
        return task

    def submit_council_release(
        self,
        task_id: str,
        evidence: CouncilReleaseEvidence,
    ) -> Dict[str, Any]:
        """Complete a task only after both media quality and all-eight-agent gates pass."""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        for stage in range(1, 9):
            if self._missing_stage_outputs(task, stage):
                raise ValueError(f"第{stage}阶段产物尚未完整完成，不能提交发布终审")
        video_gate = ((task.get("assets") or {}).get("7") or {}).get("quality_gate") or {}
        if video_gate.get("passed") is not True:
            raise ValueError("成片视频质量门禁尚未通过，不能执行八 Agent 发布终审")
        compiler = getattr(self, "agent_council", None) or AgentCouncilCompiler()
        report = compiler.evaluate_release(evidence)
        stage_assets = task.setdefault("assets", {}).setdefault("8", {})
        stage_assets["council_release_gate"] = report.model_dump(mode="json")
        if report.releasable:
            task["status"] = "completed"
            task.pop("fail_reason", None)
        else:
            task["status"] = "council_quality_failed"
            task["fail_reason"] = "八 Agent 发布门禁未通过：" + "、".join(report.blocking_codes)
        self.repo.save_task(task_id, task)
        return task

    async def execute_all_stages(self, task_id: str, *, _first_claimed: Optional[Dict[str, Any]] = None):
        """Continue from the first incomplete contract, including partial Stage 4."""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        stage = self.workflow_snapshot(task)["next_stage"]
        if _first_claimed is None and stage is None:
            return
        claimed = _first_claimed or self._claim_stage_task(task_id, stage, automatic=True)
        run_id = claimed["workflow_control"]["run_id"]
        revision = _task_script_revision(claimed)
        try:
            while claimed:
                stage = claimed["current_stage"]
                before = json.dumps((claimed.get("assets") or {}).get("4_progress"), sort_keys=True)
                await self.execute_stage(task_id, stage, _claimed_task=claimed, _automatic=True)
                current = self.repo.get_task(task_id)
                if not current or _task_script_revision(current) != revision:
                    return
                control = current.get("workflow_control") or {}
                if control.get("pause_requested") or current.get("status") in {"paused", "failed", "interrupted"}:
                    return
                next_stage = self.workflow_snapshot(current)["next_stage"]
                if next_stage is None:
                    return
                if next_stage == stage:
                    after = json.dumps((current.get("assets") or {}).get("4_progress"), sort_keys=True)
                    if stage != 4 or before == after:
                        raise StagePrerequisiteError(
                            f"第{stage}阶段执行后产物仍不完整，已停止自动推进，请检查本阶段结果后再继续。"
                        )
                claimed = self._claim_stage_task(task_id, next_stage, run_id=run_id, automatic=True)
        except StaleTaskWriteError:
            logger.info("[Task %s] 剧本版本已变更，停止旧自动流程", task_id)
        except Exception as exc:
            safe_error = self._safe_error_text(str(exc))
            def fail(current: Dict[str, Any]) -> None:
                if _task_script_revision(current) != revision:
                    return
                if (current.get("workflow_control") or {}).get("pause_requested"):
                    return
                current["status"] = "failed"
                current["fail_reason"] = f"阶段{stage}失败: {safe_error[:200]}"
                self._progress_fail(current, safe_error)
            self.repo.mutate_task(task_id, fail)
            logger.error("[Task %s] 自动流程停止: %s", task_id, safe_error[:200])
        finally:
            self._finish_workflow_run(task_id, run_id)

    # ==================================================================================
    # 多集连续剧引擎：完整剧本 -> 分集 -> 逐集制作 (尾帧链式衔接 + 五视图人物锁定 + 跨集连贯)
    # ==================================================================================
    def plan_episodes(self, task_id: str) -> Dict[str, Any]:
        """把已生成的完整剧本(阶段2)切分为多集，写入 task['episodes']。需先完成阶段1-3。"""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        script = task["assets"].get("2", "")
        if not script:
            raise ValueError("尚未生成剧本(请先完成阶段1-2)")
        eps = split_episodes(script)
        # 仅保留剧本与元信息，制作状态初始化为 idle
        task["episodes"] = [
            {"index": e["index"], "title": e["title"], "script": e["script"],
             "status": "idle", "shots": [], "video_url": None, "summary": ""}
            for e in eps
        ]
        task["total_episodes"] = len(eps)
        task["current_episode"] = 0
        task["assets"]["2_writer_dashboard"] = compile_writer_dashboard(task).model_dump(
            mode="json", by_alias=True
        )
        self.repo.save_task(task_id, task)
        return task

    async def produce_episode(self, task_id: str, ep_index: int) -> Dict[str, Any]:
        """制作指定集 (异步包装，阻塞式生成放线程池)。"""
        try:
            with usage_ledger.bind_task(task_id, f"episode_{ep_index}"):
                return await asyncio.to_thread(self._produce_episode_blocking, task_id, ep_index)
        except Exception as error:
            # 失败必须落到这一集的状态上：否则它永远停在 running，前端会一直轮询下去
            reason = self._safe_error_text(error)

            def _mark_failed(task: Dict[str, Any]) -> bool:
                episode = next((e for e in task.get("episodes") or [] if e.get("index") == ep_index), None)
                if not episode:
                    return False
                episode["status"] = "failed"
                episode["fail_reason"] = reason
                return True

            self.repo.mutate_task(task_id, _mark_failed)
            raise

    def _produce_episode_blocking(self, task_id: str, ep_index: int) -> Dict[str, Any]:
        """逐集制作核心：分镜 -> 尾帧链式逐镜生成(五视图锁人物) -> 情绪配音 -> 合成单集(2.5-3min)。"""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        episodes = task.get("episodes") or []
        ep = next((e for e in episodes if e.get("index") == ep_index), None)
        if not ep:
            raise ValueError(f"第{ep_index}集不存在，请先调用 plan_episodes")

        config = task["config"]
        title = config["title_suggestion"]
        dir_style = config.get("director_style", DEFAULT_DIRECTOR_STYLE)
        char1_name, char1_desc, char2_name, char2_desc = extract_character_info(task["assets"].get("1", ""))
        char_sheets = task["assets"].get("3_sheets") or {}
        # 多集连续生产线与主管线共用同一套委员会配药单，避免同一项目两套负面词标准。
        episode_negative_image = self._role_negative_suffix(
            task, AgentRole.VISUAL_DIRECTOR, exclude=("temporal_continuity",))
        char1_gender = guess_gender(char1_name)
        char2_gender = guess_gender(char2_name)

        ep["status"] = "running"
        ep.pop("fail_reason", None)
        task["current_episode"] = ep_index
        self.repo.save_task(task_id, task)

        # 单集镜头数、每隔几镜重新锚定身份视图、单镜时长；时长不超过所选视频模型的单镜上限
        SHOTS = settings.env_int("SHOTS_PER_EPISODE", self.EPISODE_SHOTS_DEFAULT, minimum=1, maximum=self.EPISODE_SHOTS_MAX)
        REANCHOR = settings.env_int("REANCHOR_EVERY", self.EPISODE_REANCHOR_DEFAULT, minimum=1)
        DURATION = settings.env_int(
            "SHOT_DURATION", self.EPISODE_SHOT_SECONDS_DEFAULT,
            minimum=MIN_SHOT_SECONDS, maximum=max_shot_seconds(str(config.get("video_model") or "")),
        )

        # 上一集摘要 (跨集剧情连贯)
        prev_summary = ""
        for e in episodes:
            if e.get("index") == ep_index - 1:
                prev_summary = e.get("summary", "")

        # 1. 分镜：把本集剧本拆成 SHOTS 个连续镜头
        sys_prompt = (
            "Role: AI 分镜师智能体。把单集剧本拆解为标准 Markdown 分镜表，"
            "必须包含列：镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的。"
            f"本集需输出恰好 {SHOTS} 个**连续衔接**的镜头(上一镜结尾即下一镜开头)，覆盖本集完整剧情，"
            "画面内容只写可见动作，台词对白列只在有人物说话时填写(否则留空)。"
        )
        user_prompt = (
            (f"【上一集剧情回顾(需承接)】：{prev_summary}\n\n" if prev_summary else "")
            + f"请把以下第{ep_index}集剧本拆成 {SHOTS} 个连续镜头分镜表：\n\n{ep['script']}"
        )
        guidance = config.get("guidance_instruction", "")
        sb_res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style,
                                       config.get("shot_style", "cinematic"), user_instruction=guidance)
        shots = parse_storyboard_table(sb_res, [])[:SHOTS]
        if not shots:
            # 与第 4 阶段一致：分镜表解析不出真实镜头就停下，不拿占位描述去逐镜付费生成
            raise ValueError(f"第{ep_index}集分镜表未解析出镜头，请重新制作本集；不使用占位内容生成画面")
        ep["storyboard_raw"] = sb_res

        # 2. 尾帧链式逐镜生成
        carry = task.get("_last_frame_carry")  # 上一集最后一帧 base64 (跨集衔接)
        shot_assets, clips, subtitles, shot_voices = [], [], [], []
        for idx, shot in enumerate(shots):
            desc = shot.get("desc", "")
            dialogue = shot.get("dialogue", "")
            # 首帧来源：需要重新锚定(每集首镜/每REANCHOR镜/无carry) -> 五视图底片；否则用上一镜尾帧链接
            need_anchor = (carry is None) or (idx % REANCHOR == 0)
            ref_sheets = []
            if char1_name and char1_name in desc and char_sheets.get(char1_name):
                ref_sheets.append(char_sheets[char1_name])
            if char2_name and char2_name in desc and char_sheets.get(char2_name):
                ref_sheets.append(char_sheets[char2_name])
            if not ref_sheets and char_sheets:
                ref_sheets = list(char_sheets.values())[:2]

            first_frame = carry
            display_img = None
            if need_anchor:
                lock_pos = self.gateway.SHEET_LOCK_POSITIVE if ref_sheets else ""
                lock_neg = self.gateway.SHEET_LOCK_NEGATIVE if ref_sheets else ""
                img_prompt = (f"{lock_pos}。短剧镜头底片，{desc}，{dir_style} 风格电影质感，9:16竖屏，"
                              f"画面无文字无水印{self.gateway.DEID_POSITIVE}。{lock_neg}{self.gateway.DEID_NEGATIVE}"
                              f"{episode_negative_image}")
                base_img, _prov = self.gateway.generate_image(config["image_model"], img_prompt, ref_images=ref_sheets)
                first_frame = base_img
                display_img = base_img

            vid_prompt = f"镜头画面：{desc}。人物外观、服装、场景与首帧保持一致，运动自然流畅。"
            vid_url = self.gateway.generate_video(config["video_model"], first_frame, vid_prompt,
                                                  prefer_provider="seedance", duration=DURATION)

            # 抽尾帧供下一镜首帧 (尾帧链式衔接)
            new_carry = media_compositor.extract_last_frame_b64(vid_url)
            if new_carry:
                carry = new_carry

            # 对话 -> 字幕(仅对话镜头) + 情绪配音
            sub_text = ""
            voice_path = None
            if dialogue:
                pairs = re.findall(r'([一-龥A-Za-z][一-龥A-Za-z·]{0,7})[：:]\s*([^：:]+?)(?=(?:[一-龥A-Za-z][一-龥A-Za-z·]{0,7}[：:])|$)', dialogue)
                seg_lines = []
                disp_lines = []
                if pairs:
                    for speaker, line in pairs:
                        line = line.strip().strip('“”"\'（）()')
                        if not line or len(re.findall(r'[一-龥]', line)) < 1:
                            continue
                        if any(k in speaker.lower() for k in SKIP_SPEAKERS):
                            continue
                        if char1_name and char1_name in speaker:
                            g = char1_gender
                        elif char2_name and char2_name in speaker:
                            g = char2_gender
                        else:
                            g = guess_gender(speaker)
                        seg_lines.append((line, g, detect_emotion(line)))
                        disp_lines.append(line)
                else:
                    clean = re.sub(r'[^：:]{1,8}[：:]', '', dialogue).strip().strip('“”"\'（）()')
                    if len(re.findall(r'[一-龥]', clean)) >= 1:
                        seg_lines.append((clean, char1_gender, detect_emotion(clean)))
                        disp_lines.append(clean)
                if seg_lines:
                    _u, voice_path = media_compositor.synthesize_preferred_dialogue_track(
                        seg_lines,
                        tts_model=config["tts_model"],
                        tag=f"ep{ep_index}s{idx}_{task_id[:6]}",
                    )
                    sub_text = "  ".join(disp_lines)[:40]

            shot_assets.append({
                "shot_id": shot.get("shot_id", idx + 1), "size": shot.get("size", "MS"),
                "motion": shot.get("motion", ""), "desc": desc, "dialogue": dialogue,
                "image_url": display_img, "video_url": vid_url, "anchored": need_anchor,
            })
            if vid_url:
                clips.append(vid_url)
                subtitles.append(sub_text)
                shot_voices.append(voice_path)
            # 实时保存进度
            ep["shots"] = shot_assets
            self.repo.save_task(task_id, task)

        # 3. 合成单集：片头(第N集) + 逐镜画面 + 对话字幕 + 同步情绪配音 + BGM
        ep_title = f"第{ep_index}集"
        if ep.get("title") and ep["title"] not in ("第%d集" % ep_index, ep_title):
            ep_title = f"第{ep_index}集 {re.sub(r'第.{1,3}集', '', ep['title']).strip(' ：:')[:16]}"
        composed = media_compositor.compose_film(clips, subtitles, None, tag=f"ep{ep_index}_{task_id[:8]}",
                                                 title=ep_title, bgm=True, shot_voices=shot_voices)
        if composed:
            ep["video_url"] = composed
        else:
            real = [u for u in clips if u and LEGACY_PLACEHOLDER_MEDIA_HOST not in u]
            ep["video_url"] = real[0] if real else (clips[0] if clips else None)

        # 4. 跨集衔接：保存本集最后一帧 + 生成本集摘要供下一集承接
        task["_last_frame_carry"] = carry
        try:
            sm = self.gateway.call_llm(config["llm_model"],
                                       "你是剧本统筹。用2句话概括本集结尾的人物状态与悬念，供下一集承接，不要换行。",
                                       f"第{ep_index}集剧本：\n{ep['script']}", title, dir_style,
                                       config.get("shot_style", "cinematic"))
            ep["summary"] = re.sub(r'\s+', ' ', sm)[:200] if sm else ""
        except Exception:
            ep["summary"] = ""

        ep["status"] = "completed"
        self.repo.save_task(task_id, task)
        logger.info(f"[Task {task_id}] 第{ep_index}集制作完成，镜头数={len(clips)}，成片={ep.get('video_url')}")
        return task

    # ---------------- 自然语言流程助手：意图识别 + 分步引导 + 后台执行 ----------------

    _CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}

    def workflow_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return build_workflow_snapshot(task, self.STAGE_LABELS, self._missing_stage_outputs)

    def _next_step_hint(self, task: Dict[str, Any]) -> str:
        return self.workflow_snapshot(task)["hint"]

    def _assistant_answer(self, task: Dict[str, Any], question: str) -> str:
        """针对用户提问的自然语言答疑（带任务上下文），失败时退化为状态说明。"""
        config = task["config"]
        title = config.get("title_suggestion", "")
        context = (
            f"短剧标题：{title}；当前进度：第 {task.get('current_stage', 0)}/8 阶段（{task.get('stage_name', '')}）；"
            f"任务状态：{task.get('status')}；已产出资产键：{', '.join(sorted((task.get('assets') or {}).keys())) or '无'}。"
            f"八大阶段依次为：" + "、".join(f"{k}.{v}" for k, v in self.STAGE_LABELS.items()) + "。"
        )
        sys_prompt = (
            "你是 AI 短剧制作平台的流程助手。基于给定的任务上下文，用简体中文简洁回答用户问题（不超过200字），"
            "并在结尾用一句话给出下一步操作建议（如：回复「继续」执行下一阶段 / 说出修改意见我会重塑当前阶段）。"
            "不要编造尚未生成的内容。"
        )
        try:
            return self.gateway.call_llm(
                config["llm_model"], sys_prompt, f"【任务上下文】{context}\n\n【用户问题】{question}",
                title, config.get("director_style", DEFAULT_DIRECTOR_STYLE), config.get("shot_style", "cinematic"),
            ).strip()
        except Exception:
            return f"目前{context}\n\n{self._next_step_hint(task)}"

    _AGENT_PREFIXES = ("/agent ", "/助手 ")

    def _agent_turn(self, task_id: str, task: Dict[str, Any], msg: str, *, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle /agent, /confirm and /cancel; None when the message is for the workflow assistant."""
        lowered = msg.lower()
        prefix = next((p for p in self._AGENT_PREFIXES if lowered.startswith(p)), None)
        if prefix is None and lowered not in {"/confirm", "/确认", "/cancel", "/取消"}:
            return None
        who = user or {"user_id": task.get("owner_user_id"), "role": "user"}
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        history = [h for h in (task.get(embedded_agent.HISTORY_KEY) or []) if isinstance(h, dict)]
        pending = task.get(embedded_agent.PENDING_KEY) if isinstance(task.get(embedded_agent.PENDING_KEY), dict) else None
        tool_calls: List[Dict[str, Any]] = []
        new_pending: Optional[Dict[str, Any]] = None
        if prefix is None:
            if lowered in {"/cancel", "/取消"}:
                reply = "已放弃待确认的操作。" if pending else "没有待确认的操作。"
            elif not pending:
                reply = "没有待确认的操作；先用 /agent 说明要做什么。"
            else:
                outcome = embedded_agent.confirm_pending(self, user=who, pending=pending)
                tool_calls.append({"tool": pending.get("tool"), "arguments": pending.get("arguments"), "result": outcome})
                reply = f"已执行「{pending.get('tool')}」：" + (json.dumps(outcome.get("result"), ensure_ascii=False)[:600] if outcome.get("ok") else f"失败：{outcome.get('error')}")
            turn = {"reply": reply, "tool_calls": tool_calls, "proposal": None}
        else:
            turn = embedded_agent.run_turn(self, user=who, task_id=task_id, message=msg[len(prefix):].strip(), history=history, config=config)
            new_pending = turn.get("proposal")

        def record(current: Dict[str, Any]) -> Dict[str, Any]:
            entries = [h for h in (current.get(embedded_agent.HISTORY_KEY) or []) if isinstance(h, dict)]
            entries.append({"role": "user", "content": msg})
            for call in turn.get("tool_calls") or []:
                entries.append({"role": "tool", "tool": call.get("tool"), "result": call.get("result")})
            entries.append({"role": "assistant", "content": turn["reply"]})
            current[embedded_agent.HISTORY_KEY] = entries[-embedded_agent.HISTORY_LIMIT * 2:]
            if new_pending:
                current[embedded_agent.PENDING_KEY] = new_pending
            else:
                current.pop(embedded_agent.PENDING_KEY, None)
            current.setdefault("chat_history", []).append({"id": uuid.uuid4().hex, "role": "assistant", "content": turn["reply"]})
            return current

        updated = self.repo.mutate_task(task_id, record) or task
        return {"reply": turn["reply"], "action": "agent", "stage": None, "task": self.hydrate_task_status(updated),
                "tool_calls": turn.get("tool_calls") or [], "proposal": new_pending}

    async def assistant_message(self, task_id: str, message: str, *, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Explicit intents execute; all other messages safely explain the live workflow."""
        msg = (message or "").strip()
        if not msg:
            raise ValueError("请输入消息")
        def append_user(task: Dict[str, Any]) -> Dict[str, Any]:
            task.setdefault("chat_history", []).append({"id": uuid.uuid4().hex, "role": "user", "content": msg})
            return task
        task = self.repo.mutate_task(task_id, append_user)
        if not task:
            raise ValueError("任务不存在")
        # The tool assistant lives behind /agent: it reads and changes the project with tools and
        # asks before anything paid; /confirm and /cancel settle its last proposal.
        agent_turn = self._agent_turn(task_id, task, msg, user=user)
        if agent_turn is not None:
            return agent_turn
        workflow = self.workflow_snapshot(task)
        intent, requested_stage = assistant_intent(msg)
        if intent == "resume":
            intent = "run_all" if (task.get("workflow_control") or {}).get("automatic") else "continue"
        action, stage_target = "none", None
        reply = workflow["hint"]
        # A durable stage event is already in the transcript; only free-form
        # answers still need to be appended as their own message.
        reply_recorded = False
        if intent in {"pause", "stop"}:
            task = self.pause_task(task_id, stop=intent == "stop") or task
            reply = self._next_step_hint(task)
            action = intent
        elif intent in {"continue", "run_all", "rerun", "edit", "compose"}:
            if workflow["mode"] == "running":
                reply = "当前制作已在执行，不会重复启动。\n\n" + workflow["hint"]
            else:
                target = requested_stage if intent in {"rerun", "compose"} else (
                    max(1, int(task.get("current_stage", 0) or 0)) if intent == "edit" else workflow["next_stage"]
                )
                if target is not None:
                    try:
                        claimed = self._claim_stage_task(
                            task_id, target, automatic=intent == "run_all",
                            guidance=msg if intent == "edit" else None,
                        )
                    except StagePrerequisiteError as exc:
                        reply = str(exc) + "\n\n" + self._next_step_hint(self.repo.get_task(task_id) or task)
                    else:
                        stage_target = target
                        action = "run_all" if intent == "run_all" else "run_stage"
                        async def run_background():
                            try:
                                if intent == "run_all":
                                    await self.execute_all_stages(task_id, _first_claimed=claimed)
                                else:
                                    await self.execute_stage(task_id, target, _claimed_task=claimed)
                            except Exception as exc:
                                logger.error("[Assistant] 后台阶段失败: %s", self._safe_error_text(str(exc))[:200])
                        asyncio.create_task(run_background())
                        # The reservation already recorded the one "started" message.
                        # Answer with that exact text and do not append a second copy.
                        started = find_chat_message(claimed, stage_event_id(claimed, "start"))
                        reply = started["content"] if started else (
                            f"已启动第 {target}/8 步：{self.STAGE_LABELS[target]}。\n"
                            + self.workflow_snapshot(claimed)["stages"][target - 1]["guidance"]
                        )
                        reply_recorded = started is not None
        elif intent == "help":
            reply = (
                "输入 / 可选择常用命令：\n"
                "/start 开启或继续当前项目\n/pause 暂停后续制作\n/resume 从未完成处恢复\n"
                "/stop 结束任务并保留已有产物\n/compose 合成视频（需先完成前 6 步）\n"
                "/auto 自动完成剩余制作，无需逐步确认\n/status 查看进度。\n"
                "暂停或结束会在当前阶段完成后生效，不会删除历史记录。"
            )
        elif intent == "question":
            # Workflow questions can be answered from verified state without a model call.
            sequence = " → ".join(f"{stage}.{label}" for stage, label in self.STAGE_LABELS.items())
            reply = "完整流程是：" + sequence + "。\n\n" + workflow["hint"]
        elif intent == "read":
            reply = "我在。您可以先了解当前步骤，或明确告诉我需要修改什么；这条消息没有启动生成。\n\n" + workflow["hint"]

        def append_reply(current: Dict[str, Any]) -> Dict[str, Any]:
            current.setdefault("chat_history", []).append({"id": uuid.uuid4().hex, "role": "assistant", "content": reply})
            return current
        if not reply_recorded:
            task = self.repo.mutate_task(task_id, append_reply) or task
        else:
            task = self.repo.get_task(task_id) or task
        return {"reply": reply, "action": action, "stage": stage_target, "task": self.hydrate_task_status(task)}

    async def chat_instruction(self, task_id: str, message: str) -> Dict[str, Any]:
        """Legacy chat endpoint shares the same safe intent and workflow contract."""
        return (await self.assistant_message(task_id, message))["task"]

    def update_task_config(self, task_id: str, req: DramaCreateRequest) -> Optional[Dict[str, Any]]:
        """
        更新指定任务的配置参数
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        
        task["config"]["director_style"] = req.director_style
        # 省略 style_pack 的更新请求沿用项目已有的风格锁，不会把 2D/3D 项目重置成写实默认值。
        if req.style_pack:
            # A lock read off a reference image is resolved together with its stored definition.
            task["config"]["style_pack"] = style_packs.resolve_pack({**task["config"], "style_pack": req.style_pack}).id
        task["config"]["shot_style"] = req.shot_style
        task["config"]["llm_model"] = req.llm_model
        task["config"]["image_model"] = req.image_model
        task["config"]["video_model"] = req.video_model
        task["config"]["tts_model"] = req.tts_model
        task["config"]["video_reference_mode"] = req.video_reference_mode
        task["config"]["narration_delivery"] = req.narration_delivery
        task["config"]["creation_mode"] = req.creation_mode
        task["config"]["content_language"] = req.content_language
        task["config"]["source_language"] = req.content_language
        if req.ad_brief is not None:
            task["config"]["ad_brief"] = req.ad_brief.model_dump()
        task["config"]["one_click"] = req.one_click
        task["config"]["episode_count"] = req.episode_count
        task["config"]["title_suggestion"] = req.title_suggestion
        
        self.repo.save_task(task_id, task)
        return task

    async def import_skill_logic(self, import_type: str, url: Optional[str], package_name: Optional[str], file: Optional[Any]) -> Dict[str, Any]:
        """
        处理导入外部 Skill 技能包的业务逻辑 (支持 GitHub/Clawhub/NPX/ZIP)
        """
        import os
        import shutil
        import zipfile
        import json
        from pathlib import Path
        from urllib.parse import urlparse
        
        # 确立 skills 保存目录
        skills_dir = str(BUNDLED_SKILLS_DIR)
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir)
            
        skill_name = "custom_imported_skill"
        skill_desc = "外部导入的短剧生成技能"
        
        # 1. 本地 ZIP 上传导入
        if import_type == "zip":
            if not file:
                raise ValueError("未上传任何 ZIP 技能文件包")
            display_filename = Path(file.filename or "skill.zip").name
            name_without_ext = os.path.splitext(display_filename)[0]
            skill_name = _safe_skill_name(name_without_ext)
            
            temp_zip_path = os.path.join(skills_dir, f".import-{uuid.uuid4().hex}.zip")
            maximum_archive_bytes = 50 * 1024 * 1024
            written = 0
            with open(temp_zip_path, "wb") as buffer:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > maximum_archive_bytes:
                        buffer.close()
                        os.remove(temp_zip_path)
                        raise ValueError("ZIP 技能包不能超过 50MB")
                    buffer.write(chunk)
                
            target_extract_dir = os.path.join(skills_dir, skill_name)
            if os.path.exists(target_extract_dir):
                shutil.rmtree(target_extract_dir)
            os.makedirs(target_extract_dir)
            
            try:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    members = zip_ref.infolist()
                    if len(members) > 2000:
                        raise ValueError("ZIP 文件数量超过 2000 个安全上限")
                    total_size = sum(member.file_size for member in members)
                    if total_size > 200 * 1024 * 1024:
                        raise ValueError("ZIP 解压后超过 200MB 安全上限")
                    target_root = Path(target_extract_dir).resolve()
                    for member in members:
                        member_path = (target_root / member.filename).resolve()
                        if member_path != target_root and target_root not in member_path.parents:
                            raise ValueError("ZIP 包含路径穿越条目")
                        unix_mode = (member.external_attr >> 16) & 0o170000
                        if unix_mode == 0o120000:
                            raise ValueError("ZIP 不允许包含符号链接")
                    zip_ref.extractall(target_root)
                logger.info(f"[SkillImporter] 成功解压 ZIP 技能包: {skill_name}")
            except Exception as e:
                shutil.rmtree(target_extract_dir, ignore_errors=True)
                logger.error(f"[SkillImporter] 解压 ZIP 失败: {str(e)}")
                raise ValueError(f"解压 ZIP 失败: {str(e)}")
            finally:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
            
            skill_desc = f"本地上传的技能包 ({display_filename})"

        # 2. 从 GitHub / Clawhub 链接导入
        elif import_type in ["github", "clawhub"]:
            if not url:
                raise ValueError("链接不能为空")
            parsed_url = urlparse(url)
            allowed_hosts = {
                host.strip().lower()
                for host in os.getenv("ALLOWED_SKILL_GIT_HOSTS", "github.com,gitee.com").split(",")
                if host.strip()
            }
            if parsed_url.scheme != "https" or (parsed_url.hostname or "").lower() not in allowed_hosts:
                raise ValueError("Skill 仓库只允许来自配置白名单中的 HTTPS Git 主机")
            if parsed_url.username or parsed_url.password:
                raise ValueError("Skill 仓库 URL 不允许内嵌凭证")
            repo_name = parsed_url.path.rstrip('/').split('/')[-1]
            if repo_name.endswith('.git'):
                repo_name = repo_name[:-4]
            skill_name = _safe_skill_name(repo_name)
            
            target_repo_dir = os.path.join(skills_dir, skill_name)
            if os.path.exists(target_repo_dir):
                shutil.rmtree(target_repo_dir)
            
            git_path = shutil.which("git")
            if git_path:
                try:
                    import subprocess
                    subprocess.run(
                        [git_path, "clone", "--depth", "1", url, target_repo_dir], 
                        check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    logger.info(f"[SkillImporter] 成功 Git 克隆技能仓库: {skill_name}")
                except Exception as e:
                    logger.warning(f"[SkillImporter] Git 克隆失败: {type(e).__name__}")
                    raise ValueError("Git Skill 克隆失败") from e
            else:
                os.makedirs(target_repo_dir)
                
            with open(os.path.join(target_repo_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump({"name": skill_name, "source": url, "type": import_type}, f, ensure_ascii=False, indent=4)
                
            skill_desc = f"Git 导入的技能包 ({url})"

        # 3. 从 NPX 一键安装导入
        elif import_type == "npx":
            if not package_name:
                raise ValueError("NPX 技能包名不能为空")
            if not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", package_name, flags=re.IGNORECASE):
                raise ValueError("NPX 技能包名格式无效")
            skill_name = _safe_skill_name(package_name.replace('/', '_').replace('@', ''))
            target_npx_dir = os.path.join(skills_dir, skill_name)
            if os.path.exists(target_npx_dir):
                shutil.rmtree(target_npx_dir)
            os.makedirs(target_npx_dir)
            
            # Register metadata only. Running arbitrary NPX package code inside
            # the API process would be remote code execution.
            with open(os.path.join(target_npx_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump({"name": skill_name, "package": package_name, "type": "npx"}, f, ensure_ascii=False, indent=4)
                
            skill_desc = f"NPX 一键安装技能包 ({package_name})"
            
        else:
            raise ValueError(f"不支持的导入类型: {import_type}")

        registry_path = os.path.join(skills_dir, IMPORTED_SKILL_REGISTRY)
        registry = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            except Exception:
                registry = {}
                
        registry[skill_name] = {
            "name": skill_name,
            "description": skill_desc,
            "type": import_type,
            "path": os.path.join(skills_dir, skill_name)
        }
        
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=4)
            
        return {
            "status": "success",
            "skillName": skill_name,
            "description": skill_desc,
            "skillsList": list(registry.values())
        }

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """
        返回本地可执行 Skills 与 16 个已审计能力源；sd25-pe 默认优先从 ~/.agents/skills/sd25-pe 读取。
        """
        import json
        from app.core.capability_manifest import UPSTREAM_CAPABILITIES
        from app.core.skill_registry import SkillRegistry

        discovered = SkillRegistry(skill_registry_roots()).list()
        result = [
            {
                "name": item.name,
                "description": item.description or f"本地 {item.kind} Skill",
                "type": item.kind,
                "path": str(item.path),
                "active": True,
            }
            for item in discovered
        ]

        registry_path = BUNDLED_SKILLS_DIR / IMPORTED_SKILL_REGISTRY
        if registry_path.is_file():
            try:
                imported = json.loads(registry_path.read_text(encoding="utf-8"))
                if isinstance(imported, dict):
                    result.extend(value for value in imported.values() if isinstance(value, dict))
            except (OSError, json.JSONDecodeError):
                pass

        known = {str(item.get("name") or item.get("id")) for item in result}
        for source in UPSTREAM_CAPABILITIES:
            if source["id"] in known:
                continue
            result.append({
                "name": source["id"],
                "description": "、".join(source["capabilities"]),
                "type": "audited-capability-source",
                "source": source["source"],
                "active": True,
            })
        return result

    def delete_skill_logic(self, skill_name: str) -> Dict[str, Any]:
        """
        物理删除指定的自定义已导入 Skill 技能包并更新注册表
        """
        import os
        import shutil
        import json

        skills_dir = str(BUNDLED_SKILLS_DIR)
        registry_path = os.path.join(skills_dir, IMPORTED_SKILL_REGISTRY)
        
        # 1. 物理删除技能包目录
        target_dir = os.path.join(skills_dir, skill_name)
        if not re.fullmatch(r"[\w.-]+", skill_name or "", flags=re.UNICODE):
            raise ValueError("Skill 名称无效")
        root_real = os.path.realpath(skills_dir)
        target_real = os.path.realpath(target_dir)
        if not target_real.startswith(root_real + os.sep):
            raise ValueError("Skill 路径越界")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            logger.info(f"[SkillImporter] 成功物理删除技能包目录: {target_dir}")
            
        # 2. 物理删除可能的 ZIP 压缩包
        temp_zip = os.path.join(skills_dir, f"{skill_name}.zip")
        if os.path.exists(temp_zip):
            os.remove(temp_zip)

        # 3. 更新 registry.json 注册表
        registry = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            except Exception:
                registry = {}

        if skill_name in registry:
            registry.pop(skill_name)

        try:
            with open(registry_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"[SkillImporter] 写入注册表失败: {str(e)}")

        return {
            "status": "success",
            "skillName": skill_name,
            "skillsList": list(registry.values())
        }

    def delete_task(self, task_id: str) -> bool:
        """
        根据任务唯一 ID 删除生成任务
        """
        return self.repo.delete_task(task_id)

    def parse_script_file(self, file_name: str, file_bytes: bytes) -> str:
        """
        手动解析上传的剧本文件并返回纯文本内容与安全摄取一致的规范化文本。
        """
        from app.ingest.parsers import SourceIngestor

        return SourceIngestor().ingest(file_name, file_bytes).text

    def get_shanyin_screenplay_skill(self) -> str:
        """
        读取本地山音超级编剧大师集成版技能包的最核心段落 (前600行) 作为Prompt系统注入
        """
        skill_path = os.path.join(
            str(BUNDLED_SKILLS_DIR / "shanyin-screenwriting-master"),
            "山音超级编剧大师集成版（Gemini及其他AI工具通用）.md",
        )
        if os.path.exists(skill_path):
            try:
                with open(skill_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    return "".join(lines[:600])
            except Exception as e:
                logger.error(f"[ShanyinSkill] 读取山音编剧技能文件失败: {str(e)}")
        return ""
