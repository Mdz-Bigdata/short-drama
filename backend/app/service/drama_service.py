# -*- coding: utf-8 -*-
import logging
import uuid
import asyncio
import json
import re
import os
import hashlib
import time
from pathlib import Path
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from app.repository.task_repo import StaleTaskWriteError, TaskRepository
from app.core.model_gateway import ModelGateway
from app.core import media_compositor
from app.core.storyboard_assets import compose_nine_grid, split_five_view_sheet
from app.core.storyboard_quality import build_nine_grid_prompt, validate_storyboard_continuity
from app.core.shot_motion_contract import (
    ShotMotionContract,
    assert_prompt_pair_consistent,
    compile_motion_prompt,
    compile_storyboard_image_prompt,
)
from app.core.continuity import ContinuityState, plan_transition
from app.core.image_quality import validate_five_view_images
from app.core.video_quality import VideoQualityMeasurements, evaluate_video_quality
from app.core.video_references import (
    VideoGenerationIntent,
    normalize_video_reference_mode,
    plan_video_references,
)
from app.core.agent_council import AgentCouncilCompiler
from app.core.workflow_prompts import STORYBOARD_SCRIPT_PROMPT, build_video_batch_prompt
from app.core.storyboard_prompt_detail import compile_storyboard_prompt_detail
from app.core.writer_dashboard import compile_writer_dashboard
from app.core.character_dashboard import compile_character_dashboard
from app.schema.drama import DramaCreateRequest
from app.schema.production import NineGridStoryboard, StoryAssetCatalog, StoryboardPanel
from app.schema.agent_council import AgentRole, CouncilCompileRequest, CouncilReleaseEvidence
from app.schema.writer_dashboard import WriterDashboardResponse
from app.schema.character_dashboard import CharacterDashboardResponse


class ScriptUpdateConflictError(RuntimeError):
    """The screenplay changed or has active derivatives that require confirmation."""


class ScriptUpdateTaskNotFoundError(LookupError):
    """The task is missing or does not belong to the editor."""


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
    char1_name = "主角"
    char1_desc = "身穿连帽卫衣，戴银色项链"
    char2_name = "反派"
    char2_desc = "穿高定西服，眼神傲慢"
    
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

def extract_speech(script: str) -> str:
    """
    辅助方法：从编剧对白脚本中动态提取主要台词
    """
    if not script:
        return "既然如此，我今日便要了断于此！"
    lines = re.findall(r'[\u4e00-\u9fa5\w]+\s*：\s*([^\n]+)', script)
    if lines:
        for line in lines:
            cleaned = line.strip()
            if len(cleaned) > 5 and "环境" not in cleaned and "调度" not in cleaned:
                return cleaned
        return lines[0].strip()
    return "既然如此，我今日便要了断于此！"

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


def detect_emotion(text: str) -> str:
    """根据台词内容粗略判定情绪，用于配音的情绪与节奏 (对应 media_compositor.EMOTION_PRESETS)。"""
    t = text or ""
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


# 非角色发声体，配音时跳过 (不为音效/旁白标记等生成人声)
SKIP_SPEAKERS = ("音效", "环境音", "背景音", "特效音", "音乐", "声音", "bgm", "ost")


def parse_shot_dialogue(cell: str, char1_name: str, char2_name: str,
                        char1_gender: str, char2_gender: str) -> list:
    """
    把一个镜头的台词单元格解析为 [(台词, 性别, 情绪)]，供逐句情绪配音。
    步骤5(预览音轨)与步骤6(成片配音)共用，避免解析逻辑重复发散。
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
            if char1_name and char1_name in speaker:
                g = char1_gender
            elif char2_name and char2_name in speaker:
                g = char2_gender
            elif "旁白" in speaker:
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

class DramaService:
    """
    AI 短剧 8-Agent 协同与断点状态控制业务服务类 (Service)
    """
    def __init__(self):
        self.repo = TaskRepository()
        self.gateway = ModelGateway()
        self.agent_council = AgentCouncilCompiler()
        self.script_archive_max_total_bytes = _SCRIPT_ARCHIVE_MAX_TOTAL_BYTES
        self.script_archive_max_entries = _SCRIPT_ARCHIVE_MAX_ENTRIES

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
            episode_count=max(1, min(120, int(config.get("episode_count") or 3))),
            episode_duration_seconds=90,
            output_language="zh-CN",
            visual_style=str(config.get("director_style") or "写实电影感"),
            action_intensity=(
                "high" if self.gateway.get_genre(title) in {"military", "sports", "wuxia", "xianxia"}
                else "medium"
            ),
        )
        compiled = self.agent_council.compile(request).model_dump(mode="json")
        assets["agent_council"] = compiled
        return compiled

    def _agent_role_prompt(self, task: Dict[str, Any], role: AgentRole) -> str:
        plan = self._ensure_agent_council(task)
        for agent in plan.get("agents", []):
            if agent.get("role") == role.value:
                return str(agent.get("system_prompt") or "")
        raise RuntimeError(f"八 Agent 计划缺少角色：{role.value}")

    def read_md_file(self, filename: str) -> str:
        """Load one prompt document from the repository root.

        The prompt .md files live beside the backend/ directory, so the root is
        three levels above this module. DRAMA_PROMPT_ROOT overrides it for
        deployments that ship the prompts elsewhere.
        """
        root = os.getenv("DRAMA_PROMPT_ROOT") or str(Path(__file__).resolve().parents[3])
        path = os.path.join(root, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"读取md文件 {filename} 失败: {str(e)}")
        else:
            logger.warning("提示词文件不存在: %s", path)
        return ""

    def split_shot_action(self, desc: str, creative_title: str) -> tuple:
        """
        将一个镜头的动作描述拆解为前后两个阶段的画面描述，分别用于生成多组图片
        """
        sys_prompt = "You are a storyboard artist. Split the given visual description into two consecutive keyframe visual prompts for image generation. Output format: Part 1: [prompt for keyframe 1] | Part 2: [prompt for keyframe 2]. Do not output anything else."
        user_prompt = f"Please split this action description: {desc}"
        try:
            res = self.gateway.call_llm("deepseek-chat", sys_prompt, user_prompt, creative_title)
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
                    cmd = [ff, "-y", "-i", local_path, "-vf", scale_pad, "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", norm_path]
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

    def run_real_consistency_check(self, stage: int, stage_name: str, assets: dict, config: dict, creative_title: str) -> str:
        """
        读取 "AI 生成短剧一致性检查清单.md" 内容，使用大模型对当前阶段的 assets 进行真实的自检和核验，并输出打分表格。
        """
        checklist = self.read_md_file("AI 生成短剧一致性检查清单.md")
        checklist_cut = checklist[:3500] if checklist else "一致性检查指南"
        
        sys_prompt = (
            "Role: AI 短剧终极质检专家 (Quality Control Hook Agent)\n"
            "Methodology: 遵循 `AI 生成短剧一致性检查清单.md` 质检准则，对当前阶段生成的真实资产进行客观审查打分。\n"
            "输出格式：标准的 Markdown 质检自检报告表格。表格必须包含列：检查维面 | 质检内容 | 状态得分 | 状态说明。\n"
            "最后对本阶段给出一个总体结论和一致性评分。"
        )
        
        # 提取当前阶段的资产特征
        asset_info = str(assets.get(str(stage)) or assets.get(stage) or "")[:2000]
        
        user_prompt = (
            f"当前短剧：《{creative_title}》\n"
            f"当前阶段：第 {stage} 阶段 — {stage_name}\n"
            f"当前已生成资产：\n{asset_info}\n\n"
            f"请参考以下一致性检查清单，对上述资产进行核验打分，输出自检表格和结论：\n\n{checklist_cut}"
        )
        
        try:
            res = self.gateway.call_llm(config.get("llm_model", "deepseek-chat"), sys_prompt, user_prompt, creative_title)
            if res and "|" in res:
                return f"🪝 **[HOOK 拦截器触发] `PostAgentCallHook ({stage_name}质检)`**\n\n{res}"
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
                "shot_style": req.shot_style,
                "llm_model": req.llm_model,
                "image_model": req.image_model,
                "video_model": req.video_model,
                "tts_model": req.tts_model,
                "video_reference_mode": req.video_reference_mode,
                "one_click": req.one_click,
                "episode_count": max(1, min(12, int(getattr(req, "episode_count", 3) or 3))),
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
        assets = task.get("assets") or {}
        board_payload = assets.get("4_storyboard")
        if isinstance(board_payload, dict) and not assets.get("4_prompt_detail"):
            try:
                board = NineGridStoryboard.model_validate(board_payload)
                profiles = {
                    str(item.get("name")): str(item.get("desc") or "")
                    for item in (assets.get("3_characters") or [])
                    if isinstance(item, dict) and item.get("name")
                }
                detail = compile_storyboard_prompt_detail(
                    board,
                    script_text=str(assets.get("2") or "\n".join(
                        str(item.get("desc") or "") for item in (assets.get("4") or [])
                        if isinstance(item, dict)
                    )),
                    visual_style=f"{(task.get('config') or {}).get('director_style') or '真人电影写实'}，精品短剧画风，大师级构图",
                    episode="第1集",
                    character_profiles=profiles,
                )
                assets["4_prompt_detail"] = detail.model_dump(mode="json")
            except Exception as exc:
                logger.warning("分镜提示词详情兼容编译失败: %s", type(exc).__name__)
        return task

    def get_writer_dashboard(self, task_id: str) -> Optional[WriterDashboardResponse]:
        """Compile the current Writer Agent assets into the stable dashboard contract."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return compile_writer_dashboard(task)

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
        return {
            "id": str(document.get("id") or ""),
            "name": str(document.get("name") or ""),
            "size_bytes": len(str(document.get("content") or "").encode("utf-8")),
            "updated_at": str(document.get("updated_at") or ""),
        }

    def list_script_documents(self, task_id: str) -> Optional[List[Dict[str, Any]]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        documents = self._script_documents(task)
        return [self._script_document_summary(item) for item in documents if isinstance(item, dict)]

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
    ) -> Optional[Dict[str, Any]]:
        safe_name = self._script_document_name(name)
        safe_content = str(content or "").replace("\x00", "")
        if len(safe_content.encode("utf-8")) > self._MAX_SCRIPT_DOCUMENT_BYTES:
            raise ValueError("剧本文件不能超过 2 MB")
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
            }
            documents.append(document)
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
    ) -> Optional[Dict[str, Any]]:
        safe_name = self._script_document_name(name) if name is not None else None
        safe_content = str(content).replace("\x00", "") if content is not None else None
        if safe_content is not None and len(safe_content.encode("utf-8")) > self._MAX_SCRIPT_DOCUMENT_BYTES:
            raise ValueError("剧本文件不能超过 2 MB")
        timestamp = datetime.now(timezone.utc).isoformat()

        def mutation(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            for document in self._script_documents(task):
                if not isinstance(document, dict) or str(document.get("id")) != document_id:
                    continue
                if safe_name is not None:
                    document["name"] = safe_name
                if safe_content is not None:
                    document["content"] = safe_content
                document["updated_at"] = timestamp
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
            task["assets"]["2_documents"] = remaining
            return removed

        return self.repo.mutate_task(task_id, mutation)

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
    ) -> Optional[WriterDashboardResponse]:
        """Atomically apply a user-authored screenplay revision without calling an LLM.

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
            if not content_changed and not file_name_changed:
                return current_dashboard

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
                        if key in {"2", "2_breakdown"} or key in downstream_asset_keys
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
                for key in list(logs):
                    if stage_key(key, minimum=2):
                        logs.pop(key, None)

                parsed_episodes = split_episodes(content, max_episodes=12)
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

    def pause_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        暂停当前正在运行 of 短剧任务
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        task["status"] = "idle"
        self.repo.save_task(task_id, task)
        return task

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

    async def execute_stage(self, task_id: str, stage: int) -> Dict[str, Any]:
        """
        执行特定步骤 (异步包装)。真实大模型调用是阻塞式 I/O (文本/图片/视频轮询可达数分钟)，
        故放入线程池执行，避免阻塞 FastAPI 事件循环导致前端状态轮询无响应。
        执行异常时把异常信息写入 stage_progress 并标记任务 failed，供前端对话面板抛错展示。
        """
        try:
            return await asyncio.to_thread(self._execute_claimed_stage_blocking, task_id, stage)
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

    def _claim_stage_task(self, task_id: str, stage: int) -> Dict[str, Any]:
        """Atomically mark and return the exact script revision a worker will execute."""

        def claim(task: Dict[str, Any]) -> Dict[str, Any]:
            task["status"] = "running"
            task["current_stage"] = stage
            return task

        claimed_task = self.repo.mutate_task(task_id, claim)
        if claimed_task is None:
            raise ValueError("任务不存在")
        return claimed_task

    def _execute_claimed_stage_blocking(self, task_id: str, stage: int) -> Dict[str, Any]:
        """Claim a revision in the worker thread and attach it to any provider failure."""
        claimed_task = self._claim_stage_task(task_id, stage)
        claimed_revision = _task_script_revision(claimed_task)
        try:
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
        self._emit_task_progress(task, "task_stage_failed", error=error[:260])

    def _extract_script_breakdown(self, config: Dict[str, Any], title: str, dir_style: str,
                                  shot_style: str, script: str, director_plan: str = "") -> Optional[Dict[str, Any]]:
        """
        阶段2后置步骤：把完整剧本结构化为「剧本大纲 + 场景明细 + 事件时间轴 + 人物关系图谱」，
        供看板编剧页渲染。失败不阻断主流程，返回 None。
        """
        if not script or not script.strip():
            return None
        sys_prompt = (
            "你是短剧制片系统的剧本结构化分析器。阅读给定剧本，只输出一个合法 JSON 对象（UTF-8，"
            "不要输出 markdown 代码块之外的任何解释文字），字段如下：\n"
            "{\n"
            '  "overview": {"synopsis": "150-250字剧情概述", "genre": "题材类型(如 现代都市励志)",'
            ' "theme": "一句话主题", "world_setting": "世界观与时代背景设定，100-200字"},\n'
            '  "scenes": [{"scene_id": "E{集数}S{场景序号，两位数}，如 E1S01", "duration": "预估时长如 8s",'
            ' "content": "该场景可见画面与动作概述，2-4句", "characters": ["出场角色名"]}],\n'
            '  "timeline": [{"phase": "故事开始|进展纠葛|危机|高潮|结局 之一", "title": "事件短标题",'
            ' "desc": "2-3句事件描述", "points": ["该事件的叙事作用要点，2-3条"]}],\n'
            '  "relationships": [{"from": "角色A", "to": "角色B", "relation": "2-4字关系动词，如 欺骗/驱赶/背叛/扶持"}],\n'
            '  "roles": [{"name": "角色名", "position": "女主角|男主角|反派|男配角|女配角|其它角色"}]\n'
            "}\n"
            "要求：scenes 覆盖剧本全部场景并按剧情顺序排列；timeline 提炼 5-8 个关键节点按时间顺序；"
            "relationships 只保留剧情中真实发生的关系；角色名必须与剧本中的称呼完全一致。"
        )
        user_prompt = f"【短剧标题】：{title}\n\n【剧本原文】：\n{script}"
        if director_plan:
            user_prompt += f"\n\n【导演策划大纲(辅助参考)】：\n{director_plan}"
        try:
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style)
            breakdown = extract_json_object(res)
            if not breakdown:
                logger.warning("[Stage2] 剧本结构化分析未解析出 JSON，跳过看板结构化渲染")
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
            "states 覆盖每个角色的全部状态卡；anchors 按五视图顺序排列。"
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

        dir_style = config.get("director_style", "cyberpunk")
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
            guide_elements = self.read_md_file("AI短剧注意事项与关键元素.md")
            genre_summary = self.read_md_file("短剧题材类型总结.md")
            narrative_structure = self.read_md_file("AI漫剧短剧剧本黄金叙事结构.md")
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
                f"【全局短剧制作注意事项与关键元素规范如下】：\n{guide_elements}\n\n"
                f"【短剧题材与爆款题材结构指导如下】：\n{genre_summary}\n"
            )
            
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
            
            task["logs"]["1"] = self.run_real_consistency_check(1, "总导演策划", task["assets"], config, title)

        elif stage == 2:
            # 阶段 2：编剧 (Writer Agent)
            task["stage_name"] = "编剧剧本创作"
            script_content = config.get("script_content")
            script_name = config.get("script_name", "未命名")
            if script_content:
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
                performance_guide = self.read_md_file("AI短剧表演细节与提示词指南.md")
                guide_elements = self.read_md_file("AI短剧注意事项与关键元素.md")
                continuity_guide = self.read_md_file("AI短剧连续性设计指南.md")
                narrative_structure = self.read_md_file("AI漫剧短剧剧本黄金叙事结构.md")
                sys_prompt = (
                    self._agent_role_prompt(task, AgentRole.WRITER)
                    + "\n\n"
                    "Role: AI 专业短剧编剧智能体 (Writer Agent)\n"
                    "Methodology: 遵循山音超级编剧大师核心理念。只写摄影机能拍到的画面和能听到的声音，"
                    "杜绝任何心理描写和括号暗示（如'（她内心很紧张）'），对话高度口语化。\n"
                    "每一集都必须按《黄金叙事结构》单集模型落地：前3秒强钩子→交代冲突→压迫升级→反击/反转/情绪爆点→"
                    "结尾5秒悬念钩子；每集至少命中一个爽/燃/虐/怒/甜/惊情绪点，结尾留‘必须看下一集’的问题。\n\n"
                    f"【黄金叙事结构(单集黄金结构/每集三件事/短剧公式/一集模板)如下】：\n{narrative_structure}\n\n"
                    f"【短剧表演细节与具象物理动作指导如下】：\n{performance_guide}\n\n"
                    f"【跨镜头与场景动作连续性设计指导如下】：\n{continuity_guide}\n\n"
                    f"【短剧注意事项与合规/剪辑节奏规范如下】：\n{guide_elements}\n\n"
                )
                ep_count = max(1, min(12, int(config.get("episode_count", 3) or 3)))
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
                    f"\n\n【强制分集格式要求】：全剧必须切分为 {ep_count} 集，每一集**必须**以独立成行的"
                    f"{ep_labels} 作为该集起始分隔标题（务必使用中文'第N集'字样）。"
                    "每一集都要剧情完整、首尾呼应、单集结尾留强悬念钩子承接下一集；集与集之间人物、场景、服装、时间线保持连贯一致。"
                    "每集内部按【场景】组织，包含可见画面动作与角色对白(用'角色名：台词'格式)。"
                )

                user_prompt = f"请基于导演策划大纲为短剧《{title}》编写完整的分集剧本：\n\n【导演策划】：\n" + task["assets"].get("1", "")
                self._progress_step(task, 15, "调用 LLM · 分集剧本创作")
                res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
                task["assets"]["2"] = res
                self._progress_step(task, 70, "剧本结构化分析 (大纲/时间轴/人物关系)")
                task["assets"]["2_breakdown"] = self._extract_script_breakdown(
                    config, title, dir_style, shot_style, res, task["assets"].get("1", "")
                )

                self._progress_step(task, 90, "剧本一致性质检自检")
                task["logs"]["2"] = self.run_real_consistency_check(2, "编剧剧本创作", task["assets"], config, title)

            self._progress_step(task, 96, "编译 Writer Dashboard 时间轴与人物关系契约")
            task["assets"]["2_writer_dashboard"] = compile_writer_dashboard(task).model_dump(
                mode="json", by_alias=True
            )

        elif stage == 3:
            # 阶段 3：角色设计师 (Character Designer)
            task["stage_name"] = "角色设计师造型"
            sheet_template = self.read_md_file("AI短剧五视图解决人物一致性提示词模板.md")
            performance_guide = self.read_md_file("AI短剧表演细节与提示词指南.md")
            sys_prompt = (
                self._agent_role_prompt(task, AgentRole.CHARACTER_DESIGNER)
                + "\n\n"
                "Role: AI 角色设计师智能体 (Character Designer Agent)\n"
                "Methodology: 设计主角和反派的详细五维 DNA 角色卡（面部、发型、体型、服饰、情绪），"
                "锁定特征（服装与发型等）以保跨镜头多帧渲染的一致性，不能写任何心理词汇。\n\n"
                f"【五视图一致性角色卡设定规则与示例】：\n{sheet_template}\n\n"
                f"【角色表情细节与身体微动作描述规范】：\n{performance_guide}\n"
            )
            user_prompt = "请为短剧角色进行 DNA 性格造型锁定：\n\n【导演方案】：\n" + task["assets"].get("1", "")
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

            # 为每名角色生成严格有序的五视图设定图，并物理拆成五个独立视图资产。
            # 后续镜头引用同一角色五视图，锁定脸型/发型/服装/体型。
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

                if not ordered:
                    task["assets"]["3_sheets"] = sheets
                    task["assets"]["3_characters"] = characters
                    task["assets"]["3_character_dashboard"] = compile_character_dashboard(task).model_dump(
                        mode="json", by_alias=True
                    )
                    self.repo.save_task(task_id, task)
                    raise RuntimeError("角色 DNA 中未提取出有效角色名")
                # 限制最多 6 个角色出五视图，避免单阶段图生调用过多过慢 (可用 MAX_CHARACTER_SHEETS 调整)
                max_sheets = max(1, min(20, int(os.getenv("MAX_CHARACTER_SHEETS", "6"))))
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
                for sheet_no, (cname, role, cdesc) in enumerate(selected_characters, start=1):
                    self._progress_step(
                        task,
                        18 + int(68 * (sheet_no - 1) / sheet_total),
                        f"生成「{cname}」五视图设定图 ({sheet_no}/{sheet_total})",
                    )
                    sheet_url = None
                    views = []
                    five_view_quality = None
                    record_persisted = False
                    failure_phase = "generation_error"
                    try:
                        # 已授权演员素材作为身份参考，但仍生成统一五视图，不允许用单张脸替代五视图。
                        auth_face = self.gateway.resolve_authorized_face(cname, role)
                        sheet_url = self.gateway.generate_character_sheet(
                            config["image_model"], cname, cdesc, dir_style, genre=genre,
                            ref_images=[auth_face] if auth_face else None,
                        )
                        if not sheet_url:
                            raise RuntimeError(f"角色「{cname}」五视图生成失败")
                        sheets[cname] = sheet_url

                        failure_phase = "split_error"
                        view_digest = hashlib.sha256(f"{cname}|{sheet_url}".encode("utf-8")).hexdigest()[:16]
                        view_dir = os.path.join(media_compositor.MEDIA_DIR, "character_views", view_digest)
                        view_paths = split_five_view_sheet(sheet_url, view_dir)
                        view_names = ["front", "front_three_quarter", "profile", "rear_three_quarter", "back"]
                        views = [
                            {
                                "view": view_name,
                                "image_url": media_compositor.public_url(
                                    os.path.relpath(str(path), media_compositor.MEDIA_DIR).replace(os.sep, "/")
                                ),
                            }
                            for view_name, path in zip(view_names, view_paths)
                        ]

                        failure_phase = "quality_error"
                        five_view_quality = validate_five_view_images(view_paths)
                        record = {
                            "name": cname,
                            "role": role,
                            "desc": cdesc,
                            "sheet": sheet_url,
                            "sheet_type": "ordered_five_view_turnaround",
                            "views": views,
                            "five_view_quality": five_view_quality.model_dump(),
                        }
                        characters.append(record)
                        _persist_character_assets()
                        record_persisted = True
                        if not five_view_quality.passed:
                            raise RuntimeError(
                                f"角色「{cname}」五视图质检失败："
                                + "；".join(issue.message for issue in five_view_quality.issues)
                            )
                    except Exception as char_error:
                        if not record_persisted:
                            safe_message = self._safe_error_text(char_error)
                            failed_quality = {
                                "passed": False,
                                "entropy": [],
                                "palette_similarity": 0,
                                "unique_view_hashes": 0,
                                "issues": [{
                                    "code": failure_phase,
                                    "message": safe_message or f"角色「{cname}」五视图生成失败",
                                }],
                            }
                            characters.append({
                                "name": cname,
                                "role": role,
                                "desc": cdesc,
                                "sheet": sheet_url,
                                "sheet_type": "ordered_five_view_turnaround",
                                "views": views,
                                "five_view_quality": failed_quality,
                            })
                            _persist_character_assets()
                        raise
            except Exception as e:
                logger.error(f"[Stage3] 角色五视图生成异常: {type(e).__name__}")
                raise
            task["assets"]["3_sheets"] = sheets
            # 结构化角色清单(名字+身份+特征+五视图)，供前端阶段3罗列与下游逐镜复用
            task["assets"]["3_characters"] = characters

            self._progress_step(task, 95, "角色造型一致性质检自检")
            task["logs"]["3"] = self.run_real_consistency_check(3, "角色设计师造型", task["assets"], config, title)

            self._progress_step(task, 97, "编译 Character Designer 五视图资产契约")
            task["assets"]["3_character_dashboard"] = compile_character_dashboard(task).model_dump(
                mode="json", by_alias=True
            )

        elif stage == 4:
            # 阶段 4：分镜师 (Storyboard Artist)
            task["stage_name"] = "分镜师分镜拆解"
            self._progress_step(task, 15, "调用 LLM · 15秒切片分镜拆解与九宫格规划")
            # 多指南叠加易撑爆上下文(Agnes-flash 等小模型会挂起/超时)，各取核心前段截断，
            # 既保留方法论又把总量控制在安全范围(直连 deepseek-v4-pro 时可调大或取消截断)。
            director_guide = self.read_md_file("AI短剧与漫剧导演级拍摄分镜完全指南.md")[:8000]
            continuity_guide = self.read_md_file("AI短剧连续性设计指南.md")[:5000]
            shot_continuity = self.read_md_file("短剧情节与镜头连贯性提示词.md")[:5000]
            emotion_lib = self.read_md_file("短剧情绪与面部表情提示词库.md")[:5000]
            action_guide = self.read_md_file("AI短剧电影级武打镜头设计指南.md")[:5000]
            scene_design = self.read_md_file("场景设计提示词.md")[:5000]
            sys_prompt = (
                self._agent_role_prompt(task, AgentRole.STORYBOARD_ARTIST)
                + "\n\n"
                + STORYBOARD_SCRIPT_PROMPT
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
            user_prompt = "请基于以下编剧剧本设计恰好9镜的精准九宫格分镜表，覆盖完整剧情，不要断开：\n\n【剧本】：\n" + task["assets"].get("2", "")
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
            
            shot_1_mov = "Extreme Close-up Dolly" if shot_style == "cinematic" else "Slow Dolly In"
            shot_3_mov = "Dolly Zoom" if shot_style == "cinematic" else "Lateral Tracking"
            fallback_shots = []
            for i in range(1, 10):
                fallback_shots.append({
                    "shot_id": i,
                    "size": "MS",
                    "motion": "Slow Dolly In" if i % 2 == 0 else "Establishing Shot",
                    "desc": f"{char1_name}与{char2_name}在{dir_style}下的剧情推进分镜 {i}。",
                    "dialogue": "",
                    "duration": "2.5s"
                })
            
            shots = parse_storyboard_table(res, fallback_shots)
            shots = list(shots or [])[:9]
            while len(shots) < 9:
                shots.append(fallback_shots[len(shots)])
            for index, shot in enumerate(shots, start=1):
                shot["shot_id"] = index
                shot["scene"] = shot.get("scene") or "继承本场戏场景圣经"
                shot["props"] = shot.get("props") or ["按剧本锁定的关键道具"]
                if isinstance(shot["props"], str):
                    shot["props"] = [shot["props"]]
                shot["effects"] = shot.get("effects") or ["自然环境动态，无额外特效"]
                if isinstance(shot["effects"], str):
                    shot["effects"] = [shot["effects"]]
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

            board = NineGridStoryboard(
                title=title,
                rhythm_profile=(
                    "romance" if genre in {"romance", "retro_romance"}
                    else "suspense" if genre == "mystery"
                    else "horror" if genre == "horror"
                    else "comedy" if genre == "comedy"
                    else "action" if genre in {"military", "sports", "wuxia", "xianxia"}
                    else "confrontation"
                ),
                assets=StoryAssetCatalog(
                    characters=[c.get("name") for c in task["assets"].get("3_characters", []) if c.get("name")] or [char1_name, char2_name],
                    scenes=["本场戏场景圣经"],
                    props=["按剧本锁定的关键道具"],
                    effects=["自然环境动态与剧情特效"],
                ),
                panels=[
                    StoryboardPanel(
                        index=shot["shot_id"],
                        characters=[
                            name for name in (char1_name, char2_name)
                            if name and (name in (shot.get("desc") or "") or len((char1_name, char2_name)) == 1)
                        ] or [char1_name or char2_name or "当前镜头角色"],
                        shot_size=shot.get("size") or "中景",
                        camera_angle=shot.get("angle") or "遵守180度轴线的平视机位",
                        camera_movement=shot.get("motion") or "固定镜头",
                        camera_reason="服务当前镜头的叙事目的、信息揭示和情绪强度，不做无动机炫技",
                        lens_mm=50,
                        aperture="T2.8",
                        composition="主体落在三分线，前中后景层次清楚，关键道具与负空间承担叙事功能",
                        action_axis="沿场景圣经指定轴线，人物不越180度轴线",
                        eyeline="说话人与聆听者视线方向、高度和出入画位置连续",
                        shot_purpose=shot["shot_purpose"],
                        story_beat=f"第{shot['shot_id']}个因果/情绪信息单元",
                        duration_seconds=_bounded_shot_duration(shot.get("duration")),
                        subject_action=shot.get("desc") or f"第{shot['shot_id']}格剧情动作",
                        expression=shot["expression"],
                        scene=shot["scene"],
                        props=shot["props"],
                        effects=shot["effects"],
                        dialogue=shot.get("dialogue") or "",
                        sound=shot.get("sound") or "环境声与动作声连续",
                        lighting="继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次",
                        edit_in="承接上一格动作、视线或声音桥，在叙事信息可读后切入",
                        edit_out="在动作接触、视线落点、情绪转折或对白收音点切出",
                        generation_mode="auto",
                        blocking="保持人物左右关系、视线匹配与关键道具位置，不越180度轴线",
                        start_state=shot["continuity_in"],
                        end_state=shot["continuity_out"],
                        continuity_in=shot["continuity_in"],
                        continuity_out=shot["continuity_out"],
                    )
                    for shot in shots
                ],
            )
            continuity_report = validate_storyboard_continuity(board.panels)
            if not continuity_report.passed:
                raise RuntimeError("九宫格分镜连续性质检未通过")
            
            # 为每个 Shot 生成初版一致性分镜预览图
            char_sheets = task["assets"].get("3_sheets") or {}
            for shot in shots:
                desc = shot.get("desc", "")
                panel = board.panels[int(shot["shot_id"]) - 1]
                contract = ShotMotionContract.from_panel(panel)
                
                # 提取参与人物并绑定五视图
                ref_sheets = []
                char_prompt = ""
                if char1_name and char1_name in desc:
                    char_prompt += f", featuring character {char1_name} who is: {char1_desc}"
                    if char_sheets.get(char1_name):
                        ref_sheets.append(char_sheets[char1_name])
                if char2_name and char2_name in desc:
                    char_prompt += f", featuring character {char2_name} who is: {char2_desc}"
                    if char_sheets.get(char2_name):
                        ref_sheets.append(char_sheets[char2_name])
                if not ref_sheets and char_sheets:
                    ref_sheets = list(char_sheets.values())[:2]
                
                lock_pos = self.gateway.SHEET_LOCK_POSITIVE if ref_sheets else ""
                lock_neg = self.gateway.SHEET_LOCK_NEGATIVE if ref_sheets else ""
                compiled_image_prompt = compile_storyboard_image_prompt(
                    contract,
                    visual_style=(
                        "Photorealistic live-action cinematic film still, real human actors, "
                        f"35mm film, 9:16 vertical aspect ratio, {dir_style} lighting style"
                    ),
                )
                img_prompt = (
                    f"{lock_pos}。{compiled_image_prompt.prompt}{char_prompt}。"
                    f"strict consistent character features{self.gateway.DEID_POSITIVE}{self.gateway.SCENE_STABILITY_POSITIVE}。"
                    f"{lock_neg}{self.gateway.DEID_NEGATIVE}{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
                )
                try:
                    img_url, _ = self.gateway.generate_image(config["image_model"], img_prompt, ref_images=ref_sheets)
                    shot["image_url"] = img_url
                except Exception as e:
                    logger.warning(f"分镜 {shot.get('shot_id')} 生图失败: {e}")
                    shot["image_url"] = None
                bound_contract = contract.model_copy(update={
                    "storyboard_image": shot["image_url"],
                    "reference_images": ref_sheets,
                })
                shot["motion_contract"] = bound_contract.model_dump(mode="json")
                shot["contract_fingerprint"] = bound_contract.contract_fingerprint
                shot["storyboard_prompt"] = compiled_image_prompt.prompt

            panel_images = [shot.get("image_url") for shot in shots]
            if len(panel_images) != 9 or not all(panel_images):
                raise RuntimeError("九宫格必须由9张有效分镜图组成，当前分镜图生成不完整")
            board_digest = hashlib.sha256("|".join(panel_images).encode("utf-8")).hexdigest()[:16]
            board_path = os.path.join(media_compositor.MEDIA_DIR, "storyboards", f"grid_{board_digest}.png")
            compose_nine_grid(panel_images, board_path)
            board_url = media_compositor.public_url(
                os.path.relpath(board_path, media_compositor.MEDIA_DIR).replace(os.sep, "/")
            )
            
            task["assets"]["4"] = shots
            task["assets"]["4_raw"] = res
            task["assets"]["4_grid"] = board_url
            task["assets"]["4_grid_prompt"] = build_nine_grid_prompt(board)
            task["assets"]["4_storyboard"] = board.model_dump(mode="json")
            character_profiles = {
                str(item.get("name")): str(item.get("desc") or "")
                for item in (task["assets"].get("3_characters") or [])
                if isinstance(item, dict) and item.get("name")
            }
            task["assets"]["4_prompt_detail"] = compile_storyboard_prompt_detail(
                board,
                script_text=str(task["assets"].get("2") or "\n".join(shot.get("desc", "") for shot in shots)),
                visual_style=f"{dir_style}，真人电视剧风格，精品短剧画风，大师级构图",
                episode="第1集",
                character_profiles=character_profiles,
            ).model_dump(mode="json")
            task["assets"]["4_quality"] = continuity_report.model_dump()
            
            task["logs"]["4"] = self.run_real_consistency_check(4, "分镜师分镜拆解", task["assets"], config, title)

        elif stage == 5:
            # 阶段 5：视觉总监 (Visual Director)
            task["stage_name"] = "视觉总监多镜头多帧生成"
            self._progress_step(task, 8, "准备镜头运动契约与角色五视图参考")

            # 视觉规范、Agent 契约与模块化负面词都来自同一委员会计划。
            visual_style_doc = self.read_md_file("画质风格类型总结.md")
            visual_agent_brief = self._agent_role_prompt(task, AgentRole.VISUAL_DIRECTOR)
            council_plan = self._ensure_agent_council(task)
            negative_prompt_modules = list(council_plan.get("negative_prompt_modules") or [])
            
            shots = task["assets"].get("4", [])
            if not isinstance(shots, list):
                shots = parse_storyboard_table(task["assets"].get("4_raw", ""), [])
                
            if not shots:
                shot_1_mov = "Extreme Close-up Dolly" if shot_style == "cinematic" else "Slow Dolly In"
                shot_3_mov = "Dolly Zoom" if shot_style == "cinematic" else "Lateral Tracking"
                shots = [
                    {"shot_id": 1, "size": "MS", "motion": "Establishing Shot", "desc": f"{char1_name}出场，环境渲染 ({dir_style} 风格)。"},
                    {"shot_id": 2, "size": "MCU", "motion": shot_1_mov, "desc": f"{char2_name}正面意图挑衅，视线沿180度轴线对峙。"},
                    {"shot_id": 3, "size": "FS", "motion": shot_3_mov, "desc": f"{char1_name}出示底牌进行正义反扑，{char2_name}震惊后退。"}
                ]
                
            # 角色五视图锚点 (来自阶段3)
            char_sheets = task["assets"].get("3_sheets") or {}

            # 逐镜预览音轨用：角色性别 (台词配音男女声分配)
            char1_gender = "male" if guess_gender(char1_name) == "male" else "female"
            char2_gender = "male" if guess_gender(char2_name) == "male" else "female"

            shot_assets = []
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
                    raise RuntimeError(
                        f"视频模型族 {plan.provider_family} 的自动路由已完成，"
                        f"但当前状态为 {plan.provider_status}，禁止冒充其他供应商提交"
                    )
                url = self.gateway.generate_video(
                    config["video_model"],
                    plan.first_frame,
                    prompt_text,
                    prefer_provider="seedance",
                    last_frame=plan.last_frame,
                    ref_images=plan.reference_images,
                    ref_videos=plan.reference_videos,
                    ref_audios=plan.reference_audios,
                    duration=seconds,
                )
                return url, plan.model_dump(mode="json")

            # 处理全部分镜镜头，确保合片时长达到 1min ~ 3min
            for shot_no, shot in enumerate(shots, start=1):
                self._progress_step(
                    task,
                    10 + int(85 * (shot_no - 1) / max(len(shots), 1)),
                    f"图生视频 · 镜头 {shot_no}/{len(shots)}",
                )
                shot_id = shot.get("shot_id", len(shot_assets) + 1)
                size = shot.get("size", "MS")
                motion = shot.get("motion", "Dolly In")
                desc = shot.get("desc", "")
                dialogue = shot.get("dialogue", "")

                # 跨镜连贯性约束 (短剧情节与镜头连贯性提示词.md)：第0镜为建立镜不写"承接上一镜"，
                # 其余每镜都承接上一镜最后一帧；正/负向连贯六锚点约束拼进所有视频提示词。
                shot_idx = len(shot_assets)
                continuity_suffix = f" {self.gateway.CONTINUITY_POSITIVE}. {self.gateway.CONTINUITY_NEGATIVE}"
                carry_lead = "" if shot_idx == 0 else f"{self.gateway.CONTINUITY_CARRY}. "

                # 动态计算时长：由剧情/台词/动作复杂度决定时长，可突破 5s
                if dialogue:
                    duration = max(5, min(15, int(len(dialogue) / 3.5) + 2))
                else:
                    duration = max(5, min(12, int(len(desc) / 8) + 2))

                # 融合角色特征五维 DNA 并绑定五视图
                char_prompt = ""
                ref_sheets = []
                if char1_name and char1_name in desc:
                    char_prompt += f", featuring character {char1_name} who is: {char1_desc}"
                    if char_sheets.get(char1_name):
                        ref_sheets.append(char_sheets[char1_name])
                if char2_name and char2_name in desc:
                    char_prompt += f", featuring character {char2_name} who is: {char2_desc}"
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
                    visual_style=(
                        f"{visual_style_doc[:1000]}；{dir_style} lighting style；"
                        "photorealistic live-action movie quality；9:16 vertical aspect ratio"
                    ),
                )
                compiled_motion = compile_motion_prompt(contract)
                assert_prompt_pair_consistent(compiled_image, compiled_motion)
                img_prompt = (
                    f"{lock_pos}。{compiled_image.prompt}{char_prompt}。"
                    f"strict consistent character features{self.gateway.DEID_POSITIVE}{self.gateway.SCENE_STABILITY_POSITIVE}。"
                    f"{lock_neg}{self.gateway.DEID_NEGATIVE}{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
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
                if not img_url:
                    img_url, _ = self.gateway.generate_image(
                        config["image_model"], img_prompt, ref_images=ref_sheets,
                    )
                contract = contract.model_copy(update={
                    "storyboard_image": img_url,
                    "reference_images": ref_sheets,
                })

                end_state_markers = (
                    "完成", "到位", "落座", "关闭", "完全", "停在", "抓住", "递给",
                    "交付", "切黑", "最终", "结束于", "comes to rest", "fully closes",
                )
                exact_end_required = (
                    requested_reference_mode == "first_last_frame"
                    or any(marker in contract.end_state for marker in end_state_markers)
                )
                target_frame = None
                if exact_end_required:
                    compiled_end = compile_storyboard_image_prompt(
                        contract,
                        visual_style=(
                            f"{visual_style_doc[:1000]}；{dir_style} lighting style；"
                            "photorealistic live-action movie quality；9:16 vertical aspect ratio"
                        ),
                        frame_state="end",
                    )
                    end_prompt = (
                        f"{lock_pos}。{compiled_end.prompt}{char_prompt}。"
                        f"{lock_neg}{self.gateway.DEID_NEGATIVE}"
                        f"{self.gateway.SCENE_STABILITY_NEGATIVE}{self.gateway.EMOTION_FACE_NEGATIVE}"
                    )
                    target_frame, _ = self.gateway.generate_image(
                        config["image_model"], end_prompt, ref_images=[img_url, *ref_sheets],
                    )

                sequence_images = list(shot.get("sequence_images") or [])
                motion_refs = list(shot.get("reference_videos") or [])
                timing_refs = list(shot.get("reference_audios") or [])
                contract = contract.model_copy(update={
                    "storyboard_image": img_url,
                    "reference_images": ref_sheets,
                    "reference_videos": motion_refs,
                    "reference_audios": timing_refs,
                })
                intent = VideoGenerationIntent(
                    exact_end_frame_required=exact_end_required,
                    narrative_image_sequence=bool(sequence_images),
                    identity_consistency_required=bool(ref_sheets),
                    motion_reference_required=bool(motion_refs),
                    audio_rhythm_required=bool(timing_refs),
                    multi_shot_output=bool(shot.get("multi_shot_output")),
                )
                spatial_relationship = (
                    f"{contract.scene}。固定空间参照与调度：{contract.blocking}。"
                    f"本批次开始状态：{contract.start_state}。人物朝向与视线关系：{contract.eyeline}。"
                    f"关键道具位置：{'、'.join(contract.props) if contract.props else '无关键道具'}。"
                )
                dialogue_line = f"。原文台词保持不变：{dialogue}" if dialogue else ""
                timeline = (
                    f"0-{duration}秒，{size}，{motion}，{carry_lead}{compiled_motion.prompt}。"
                    f"画面动作与表演：{desc}{dialogue_line}。{continuity_suffix}"
                )
                vid_prompt = build_video_batch_prompt(
                    batch_index=shot_no,
                    visual_style=f"{dir_style}，真人实拍电影感",
                    duration_seconds=duration,
                    spatial_relationship=spatial_relationship,
                    timeline=timeline,
                    sound=shot.get("sound") or contract.sound,
                )
                vid_url, route_decision = _generate_motion_video(
                    prompt_text=vid_prompt,
                    first_frame=img_url,
                    last_frame=target_frame,
                    sequence_images=sequence_images,
                    identity_images=ref_sheets,
                    motion_videos=motion_refs,
                    timing_audios=timing_refs,
                    seconds=duration,
                    intent=intent,
                )
                used_reference_modes = [route_decision["mode"]]

                # 为逐镜预览片段仅挂载原文台词配音，不自动添加音乐；这与视频提示词的
                # “只生成音效，禁止生成音乐”约束保持一致。最终成片配乐仍由后续音频阶段处理。
                # voice_path 一并存入资产，供步骤6成片复用，避免重复配音。
                seg_lines = parse_shot_dialogue(dialogue, char1_name, char2_name, char1_gender, char2_gender)
                voice_url, voice_path = None, None
                if seg_lines:
                    voice_url, voice_path = media_compositor.synthesize_preferred_dialogue_track(
                        seg_lines,
                        tts_model=config["tts_model"],
                        tag=f"voice_{task_id[:8]}_s{len(shot_assets)}",
                    )
                vid_url = media_compositor.attach_audio_to_clip(
                    vid_url, voice_path, bgm=False, tag=f"shotav_{task_id[:8]}_s{shot_id}")

                shot_assets.append({
                    "shot_id": shot_id,
                    "size": size,
                    "motion": motion,
                    "desc": desc,
                    "dialogue": dialogue,
                    "duration": duration,
                    "image_url": img_url,
                    "end_frame_url": target_frame,
                    "video_url": vid_url,
                    "voice_url": voice_url,
                    "voice_path": voice_path,
                    "video_reference_mode_requested": requested_reference_mode,
                    "video_reference_modes_used": used_reference_modes,
                    "video_route_decision": route_decision,
                    "motion_prompt": vid_prompt,
                    "contract_motion_prompt": compiled_motion.prompt,
                    "motion_contract": contract.model_dump(mode="json"),
                    "contract_fingerprint": contract.contract_fingerprint,
                    "artifact_fingerprint": contract.artifact_fingerprint,
                    "agent_role": AgentRole.VISUAL_DIRECTOR.value,
                    "agent_policy": visual_agent_brief,
                    "negative_prompt_modules": negative_prompt_modules,
                    "continuity_state": ContinuityState(
                        characters=[name for name in (char1_name, char2_name) if name and name in desc] or [char1_name],
                        scene=shot.get("scene") or "本场戏场景圣经",
                        screen_direction=(
                            "left_to_right" if any(word in desc for word in ("向右", "从左向右"))
                            else "right_to_left" if any(word in desc for word in ("向左", "从右向左"))
                            else "neutral"
                        ),
                        action=desc,
                        emotion=shot.get("expression") or detect_emotion(desc),
                        props={prop: "按上一镜连续性锁定" for prop in (shot.get("props") or ["无关键道具"])},
                        lighting=f"{dir_style}统一主光方向与色温",
                        audio_bed=shot.get("sound") or "连续环境声",
                    ).model_dump(),
                })
                
            task["assets"]["5"] = shot_assets
            
            task["logs"]["5"] = self.run_real_consistency_check(5, "视觉总监多镜头生成", task["assets"], config, title)

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
                    seg_lines = parse_shot_dialogue(cell, char1_name, char2_name, char1_gender, char2_gender)
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
                                  if voiced_count else ("占位音频" if not audio_path else "全局兜底配音"))
            }
            
            task["logs"]["6"] = self.run_real_consistency_check(6, "音频总监配音音效", task["assets"], config, title)

        elif stage == 7:
            # 阶段 7：合成发布 (Composer & Publisher)
            task["stage_name"] = "合成发布渲染合流"
            self._progress_step(task, 15, "视听合流 · 转场衔接与压制渲染")
            shots5 = task["assets"].get("5") or []
            shot_voices_all = (task["assets"].get("6") or {}).get("shot_voices") or []
            # 镜头视频/字幕/逐镜配音三者按同一顺序锁步对齐 (仅纳入有视频的镜头)，确保画/字/声同步
            shot_clips, subtitles, shot_voices, included_shots = [], [], [], []
            for idx, s in enumerate(shots5):
                if not isinstance(s, dict) or not s.get("video_url"):
                    continue
                included_shots.append(s)
                shot_clips.append(s.get("video_url"))
                # 字幕：优先各镜头台词，回退到画面描述简述
                txt = (s.get("dialogue") or "").strip()
                txt = re.sub(r'[^：:]{1,8}[：:]', '', txt).strip() if txt else ""
                if not txt:
                    txt = (s.get("desc") or "").strip()[:24]
                subtitles.append(txt)
                shot_voices.append(shot_voices_all[idx] if idx < len(shot_voices_all) else None)
            audio_path = (task["assets"].get("6") or {}).get("audio_path")
            bgm_path = (task["assets"].get("6") or {}).get("bgm_path")
            sfx_path = (task["assets"].get("6") or {}).get("sfx_path")
            transition_reports = []
            transition_specs = []
            for previous_shot, current_shot in zip(included_shots, included_shots[1:]):
                previous_state = previous_shot.get("continuity_state") if isinstance(previous_shot, dict) else None
                current_state = current_shot.get("continuity_state") if isinstance(current_shot, dict) else None
                if not previous_state or not current_state:
                    transition_specs.append({"type": "crossfade", "duration": 0.22})
                    transition_reports.append({"accepted": True, "score": 0.75, "reasons": ["缺少旧任务结构化状态，使用保守短叠化。"]})
                    continue
                plan = plan_transition(
                    ContinuityState.model_validate(previous_state),
                    ContinuityState.model_validate(current_state),
                )
                transition_reports.append(plan.model_dump())
                if not plan.accepted:
                    raise RuntimeError(
                        f"镜头 {previous_shot.get('shot_id')}→{current_shot.get('shot_id')} 连续性质检失败："
                        + "；".join(plan.reasons)
                    )
                transition_specs.append({
                    "type": plan.video_transition,
                    "duration": plan.duration_seconds,
                })

            # 片头标题：取选题名 (去除"请帮我生成"等口令冗余)
            film_title = re.sub(r'^(请帮我?|帮我?)?(生成|制作|来)?(一个|一部)?', '', title).strip() or title

            # 用 ffmpeg 将多镜头真实视频拼接 + 片头标题卡 + 烧录中文字幕 + 逐镜配音(按时间轴对齐) + BGM，导出单条成片
            composed_url = media_compositor.compose_film(
                shot_clips, subtitles, audio_path,
                tag=f"film_{task_id[:8]}", title=film_title, bgm=True,
                shot_voices=shot_voices if any(shot_voices) else None,
                bgm_path=bgm_path,
                sfx_path=sfx_path,
                transition_plans=transition_specs,
            )

            compose_mode = "ffmpeg 片头标题卡+多镜头拼接+字幕+多角色配音+BGM 真实合成"
            if composed_url:
                final_vid = composed_url
            else:
                # 合成失败时回退：取首个真实分镜视频；若一个真实分镜都没有则置空 (不再用硬编码占位视频)。
                real_clips = [u for u in shot_clips if u and "volccdn.com" not in u]
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
                "compose_mode": compose_mode,
                "agent_role": AgentRole.COMPOSER_PUBLISHER.value,
                "agent_policy": self._agent_role_prompt(task, AgentRole.COMPOSER_PUBLISHER),
                "delivery_profile": self._ensure_agent_council(task).get("delivery"),
                "aspect_ratio": self._ensure_agent_council(task).get("delivery", {}).get("aspect_ratio"),
                "subtitles": "已烧录中文字幕" if composed_url else "内置流光特效字幕",
                "release_state": "awaiting_evidence_backed_quality_and_human_review",
            }
            
            task["logs"]["7"] = self.run_real_consistency_check(7, "合成发布渲染合流", task["assets"], config, title)

        elif stage == 8:
            # 阶段 8：宣发 Agent (PR Agent)
            task["stage_name"] = "宣发Agent引流"
            self._progress_step(task, 25, "调用 LLM · 爆款标题与高完播率宣发文案")
            highlight_guide = self.read_md_file("影视剧高光时刻识别方案.md")[:6000]
            platform_guide = self.read_md_file("AI短剧注意事项与关键元素.md")[:5000]
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
            user_prompt = "请为短剧制作爆款标题和宣发文案：\n\n【导演策划大纲】：\n" + task["assets"].get("1", "")
            res = self.gateway.call_llm(config["llm_model"], sys_prompt, user_prompt, title, dir_style, shot_style, user_instruction=guidance)
            
            pr_title, pr_body = parse_pr_info(res, title, "被无赖逼至绝境，他休假归来，一铁拳打碎黑暗！爽点爆裂！")
            task["short_link"] = f"https://short-drama.volces.com/s/{tpl.get('short_link', 'general_revenge_king')}"
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
            
            task["logs"]["8"] = self.run_real_consistency_check(8, "宣发Agent引流", task["assets"], config, title)

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

    async def execute_all_stages(self, task_id: str):
        """
        一键成片模式下，全自动、不中断地连续运行 1 到 8 步骤
        """
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")

        task["status"] = "running"
        self.repo.save_task(task_id, task)

        # 循环跑完 1 到 8 步
        current_stage = task["current_stage"]
        start_stage = current_stage + 1 if current_stage < 8 else 1
        if task["status"] == "completed":
            start_stage = 1
            
        for stage in range(start_stage, 9):
            current_task = self.repo.get_task(task_id)
            if not current_task or current_task.get("status") != "running":
                logger.info(f"[Task {task_id}] 任务已被暂停或取消，退出自动生成流程")
                return
            logger.info(f"[Task {task_id}] 正在执行一键成片 - 进度 {stage}/8 (阶段: {current_task.get('stage_name', '')})")
            try:
                await self.execute_stage(task_id, stage)
            except StaleTaskWriteError:
                logger.info(
                    "[Task %s] 一键成片的旧剧本版本已被替换，停止旧流程",
                    task_id,
                )
                return
            except Exception as e:
                # 任一阶段异常立即落库为 failed，避免任务永久卡在 running 变成孤儿；可经 /resume 断点续跑
                logger.error(f"[Task {task_id}] 阶段 {stage} 执行异常，标记为 failed: {str(e)[:200]}")
                ft = self.repo.get_task(task_id)
                if ft:
                    ft["status"] = "failed"
                    ft["fail_reason"] = f"阶段{stage}失败: {str(e)[:200]}"
                    self.repo.save_task(task_id, ft)
                return
            await asyncio.sleep(1.0)

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
        return await asyncio.to_thread(self._produce_episode_blocking, task_id, ep_index)

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
        dir_style = config.get("director_style", "cyberpunk")
        char1_name, char1_desc, char2_name, char2_desc = extract_character_info(task["assets"].get("1", ""))
        char_sheets = task["assets"].get("3_sheets") or {}
        char1_gender = guess_gender(char1_name)
        char2_gender = guess_gender(char2_name)

        ep["status"] = "running"
        task["current_episode"] = ep_index
        self.repo.save_task(task_id, task)

        SHOTS = int(os.getenv("SHOTS_PER_EPISODE", "16"))
        REANCHOR = int(os.getenv("REANCHOR_EVERY", "4"))
        DURATION = int(os.getenv("SHOT_DURATION", "10"))

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
        fallback = [{"shot_id": i + 1, "size": "MS", "motion": "Slow Dolly In",
                     "desc": f"{char1_name}的剧情推进镜头{i+1}", "dialogue": ""} for i in range(SHOTS)]
        shots = parse_storyboard_table(sb_res, fallback)[:SHOTS]
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
                              f"画面无文字无水印{self.gateway.DEID_POSITIVE}。{lock_neg}{self.gateway.DEID_NEGATIVE}")
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
                        if any(k in speaker.lower() for k in ("音效", "环境音", "背景音", "特效音", "音乐", "声音", "bgm")):
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
            real = [u for u in clips if u and "volccdn.com" not in u]
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

    def _next_step_hint(self, task: Dict[str, Any]) -> str:
        """基于当前进度生成引导式下一步提示。"""
        cur = int(task.get("current_stage", 0) or 0)
        status = task.get("status", "idle")
        sp = task.get("stage_progress") or {}
        if status == "running" and sp.get("status") == "running":
            return (f"当前正在执行第 {sp.get('stage', cur)} 阶段《{sp.get('stage_label', task.get('stage_name', ''))}》"
                    f"（{sp.get('percent', 0)}% · {sp.get('label', '')}），完成后我会提示您。您也可以说「暂停」。")
        if status == "failed":
            reason = task.get("fail_reason") or (task.get("stage_progress") or {}).get("error") or "未知原因"
            return f"⚠️ 上次执行在第 {cur} 阶段失败：{reason}。回复「重跑第 {cur} 阶段」可重新执行，或先说出修改意见再重跑。"
        if cur >= 8:
            return "全部 8 个阶段已完成 🎉 您可以点击右上角「导出」下载成片，或说「重跑第 N 阶段」重塑某一环节。"
        nxt = cur + 1
        return (f"当前已完成第 {cur}/8 阶段。下一步：第 {nxt} 阶段《{self.STAGE_LABELS.get(nxt, '')}》"
                f"— 回复「继续」即可执行；也可以直接说出调整意见（如“把反派改得更狠”），我会重塑当前阶段。")

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
                title, config.get("director_style", "cyberpunk"), config.get("shot_style", "cinematic"),
            ).strip()
        except Exception:
            return f"目前{context}\n\n{self._next_step_hint(task)}"

    async def assistant_message(self, task_id: str, message: str) -> Dict[str, Any]:
        """
        自然语言对话入口：识别意图（执行/重跑/暂停/查询/微调/答疑），
        执行类动作后台异步启动并立即返回，前端通过 /status 轮询 stage_progress 展示进度条与调用过程。
        返回 {"reply", "action", "stage", "task"}。
        """
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        msg = (message or "").strip()
        task.setdefault("chat_history", []).append({"sender": "user", "text": msg})

        cur = int(task.get("current_stage", 0) or 0)
        status = task.get("status", "idle")
        # 单阶段执行完成后任务 status 可能停留在 running（历史行为），以 stage_progress 为准判定“真正在跑”
        sp = task.get("stage_progress") or {}
        actively_running = status == "running" and sp.get("status") == "running"
        action, stage_target = "none", None

        async def _run_stage_background(stage: int):
            try:
                await self.execute_stage(task_id, stage)
            except Exception as e:
                # execute_stage 已把异常写入 stage_progress 并标记 failed，这里只兜底日志
                logger.error(f"[Assistant] 后台执行阶段{stage}失败: {str(e)[:200]}")

        def _launch(stage: int):
            task["status"] = "running"
            self._progress_begin(task, stage)
            self.repo.save_task(task_id, task)
            asyncio.create_task(_run_stage_background(stage))

        # 解析「重跑/重新生成第N阶段」
        rerun_match = (re.search(r'重(?:新)?(?:跑|生成|执行|做|来)[^0-9一二三四五六七八]*(?:第)?\s*([1-8一二三四五六七八])\s*(?:阶段|步|环节)?', msg)
                       or re.search(r'(?:第)?\s*([1-8一二三四五六七八])\s*(?:阶段|步|环节)[^，。]*重(?:新)?(?:跑|生成|执行|做)', msg))

        if "暂停" in msg:
            self.pause_task(task_id)
            task = self.repo.get_task(task_id)
            reply = "⏸️ 已暂停任务，断点已保存。回复「继续」可从断点恢复执行。"
        elif actively_running:
            reply = "⏳ 当前有阶段正在执行中，请先等待完成（下方进度条实时展示调用过程），或说「暂停」中断。\n\n" + self._next_step_hint(task)
        elif rerun_match:
            raw = rerun_match.group(1)
            stage_target = self._CN_DIGITS.get(raw, None) or int(raw)
            if stage_target > max(cur, 1):
                reply = f"第 {stage_target} 阶段还未执行到（当前第 {cur}/8 阶段），请先回复「继续」按顺序推进。"
                stage_target = None
            else:
                _launch(stage_target)
                action = "run_stage"
                reply = (f"🔄 已开始重跑第 {stage_target} 阶段《{self.STAGE_LABELS.get(stage_target, '')}》。"
                         f"下方进度条将实时展示每一步调用过程，完成或异常我都会告知您。")
        elif any(k in msg for k in ("一键成片", "一键生成", "全部生成", "自动跑完", "开始生成")):
            task["status"] = "running"
            self.repo.save_task(task_id, task)
            asyncio.create_task(self.execute_all_stages(task_id))
            action = "run_all"
            reply = "🚀 一键成片已启动！8 大智能体将连续执行剩余阶段，每个阶段的调用过程与进度百分比都会在下方实时滚动展示。"
        elif any(k in msg for k in ("下一步", "继续", "开始吧", "执行", "推进")) and len(msg) <= 12:
            if cur >= 8:
                reply = "全部 8 个阶段均已完成 🎉 可以点击右上角「导出」，或说「重跑第 N 阶段」重塑某一环节。"
            else:
                stage_target = cur + 1
                _launch(stage_target)
                action = "run_stage"
                reply = (f"▶️ 已启动第 {stage_target} 阶段《{self.STAGE_LABELS.get(stage_target, '')}》执行。"
                         f"我会实时展示调用过程与进度百分比，完成后引导您进入下一步。")
        elif any(k in msg for k in ("进度", "状态", "到哪", "怎么样了", "查询")) and len(msg) <= 16:
            reply = "📊 " + self._next_step_hint(task)
        elif msg.endswith(("？", "?")) or re.match(r'^(什么|为什么|怎么|如何|能不能|可以|是否|哪|介绍|解释)', msg):
            reply = self._assistant_answer(task, msg)
        else:
            # 默认视为创作微调指令：记录 guidance 并重塑当前阶段
            task["config"]["guidance_instruction"] = msg
            stage_target = cur if cur > 0 else 1
            _launch(stage_target)
            action = "run_stage"
            reply = (f"✍️ 已记录您的调整意见：「{msg[:60]}」，正在按该指引重塑第 {stage_target} 阶段"
                     f"《{self.STAGE_LABELS.get(stage_target, '')}》。下方进度条实时展示调用过程。")

        task = self.repo.get_task(task_id) or task
        task.setdefault("chat_history", []).append({"sender": "ai", "text": reply})
        self.repo.save_task(task_id, task)
        return {"reply": reply, "action": action, "stage": stage_target, "task": task}

    async def chat_instruction(self, task_id: str, message: str) -> Dict[str, Any]:
        """
        核心方法：处理用户的对话引导指令，应用到当前的短剧生成环节中
        """
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
            
        # 记录对话流历史
        if "chat_history" not in task:
            task["chat_history"] = []
        task["chat_history"].append({"sender": "user", "text": message})
        
        # 提取低层参数配置和指令
        config = task["config"]
        msg_lower = message.lower()
        
        # 判定命令控制语境
        if "一键成片" in msg_lower or "一键" in msg_lower or "开始生成" in msg_lower:
            # 切换状态并启动后台任务
            task["status"] = "running"
            self.repo.save_task(task_id, task)
            asyncio.create_task(self.execute_all_stages(task_id))
            await asyncio.sleep(0.5)
            return self.repo.get_task(task_id)
            
        elif "下一步" in msg_lower or "继续" in msg_lower:
            current_stage = task["current_stage"]
            next_stage = current_stage + 1 if current_stage < 8 else 8
            return await self.execute_stage(task_id, next_stage)
            
        else:
            # 保存用户当前对话微调指引到 task 中，使下一次 execute_stage 会读取并传给 LLM
            config["guidance_instruction"] = message
            self.repo.save_task(task_id, task)
            
            # 定位目标阶段：如果 current_stage 是 0 或是已完成，微调第 1 阶段；否则微调/重构当前阶段
            target_stage = task["current_stage"]
            if target_stage == 0:
                target_stage = 1
                
            return await self.execute_stage(task_id, target_stage)

    def update_task_config(self, task_id: str, req: DramaCreateRequest) -> Optional[Dict[str, Any]]:
        """
        更新指定任务的配置参数
        """
        task = self.repo.get_task(task_id)
        if not task:
            return None
        
        task["config"]["director_style"] = req.director_style
        task["config"]["shot_style"] = req.shot_style
        task["config"]["llm_model"] = req.llm_model
        task["config"]["image_model"] = req.image_model
        task["config"]["video_model"] = req.video_model
        task["config"]["tts_model"] = req.tts_model
        task["config"]["video_reference_mode"] = req.video_reference_mode
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
        skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "skills")
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

        registry_path = os.path.join(skills_dir, "registry.json")
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
        返回本地可执行 Skills 与 13 个已审计能力源；sd25-pe 默认优先从 ~/.agents/skills/sd25-pe 读取。
        """
        import json
        from pathlib import Path
        from app.core.capability_manifest import UPSTREAM_CAPABILITIES
        from app.core.skill_registry import SkillRegistry

        backend_root = Path(__file__).resolve().parents[2]
        skills_dir = backend_root / "skills"
        configured_sd25 = (os.getenv("SD25_PE_SKILL_PATH") or "").strip()
        sd25_roots = (
            [Path(configured_sd25).expanduser()]
            if configured_sd25
            else [Path.home() / ".agents" / "skills" / "sd25-pe", Path.home() / "Desktop" / "sd25-pe"]
        )
        discovered = SkillRegistry([skills_dir, *sd25_roots]).list()
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

        registry_path = skills_dir / "registry.json"
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

        skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "skills")
        registry_path = os.path.join(skills_dir, "registry.json")
        
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
            str(Path(__file__).resolve().parents[2] / "skills" / "shanyin-screenwriting-master"),
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
