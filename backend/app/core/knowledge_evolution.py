# -*- coding: utf-8 -*-
"""知识进化引擎：从质检报告蒸馏可复用的生产教训，落盘到技能包 learned/ 并按命中晋升。

数据流：run_real_consistency_check 产出质检报告 → harvest_from_qc 经可注入的 LLM
蒸馏成候选教训（去重/强化）→ promote_and_prune 按命中数晋升、按分数退休 →
production_knowledge.stage_lessons_block 把 active 教训注回各阶段提示词。

存储是技能包 backend/skills/production-knowledge-master/learned/ 下的两份 JSONL：
lessons.jsonl 是教训库（原子写：临时文件 + os.replace），evolution_log.jsonl 是
追加式变更审计日志。退休的教训只改状态不删除——审计需要完整轨迹。

设计红线：
- 全程 fail-soft：文件不存在视为空库，损坏行跳过并记日志，LLM 失败返回空列表，
  任何路径都绝不抛异常阻塞流水线。
- 路径固定在技能包内，不接受外部路径参数（越界防护）；测试通过 monkeypatch
  模块级 LESSONS_PATH / LOG_PATH 重定向。
- 本模块绝不 import production_knowledge（import 方向单向：装载器 → 进化引擎）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field


logger = logging.getLogger("app.core.knowledge_evolution")

SKILL_NAME = "production-knowledge-master"
SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME

# 教训库与审计日志固定在技能包 learned/ 内；不提供外部路径入参。
LESSONS_PATH = SKILL_ROOT / "learned" / "lessons.jsonl"
LOG_PATH = SKILL_ROOT / "learned" / "evolution_log.jsonl"
# 滚动归档文件：过期候选与超量退休记录移入此处，热文件受控、审计轨迹不丢。
ARCHIVE_PATH = SKILL_ROOT / "learned" / "lessons_archive.jsonl"

# 晋升与退休规则：候选命中 ≥2 次转正；每阶段 active 上限 12，超限退休分数最低者。
PROMOTE_HITS = 2
MAX_ACTIVE_PER_STAGE = 12
# 去重阈值：规范化精确匹配之外，字符 3-gram Jaccard ≥0.6 视为同一条教训。
DEDUP_JACCARD = 0.6
# 强化幅度：重复命中的教训每次上调的分数。
REINFORCE_SCORE_STEP = 0.2
# 幂等窗口：每条教训记住最近计过数的 task_id 数量——同一任务重跑质检不重复刷 hits。
MAX_SEEN_TASK_IDS = 20
# evidence 来自不可信的 LLM 蒸馏输出，硬截断防止单条撑爆教训库。
MAX_EVIDENCE_CHARS = 500
# 单次 harvest 最多入库/强化的候选数，防止一次异常响应灌库。
MAX_CANDIDATES_PER_HARVEST = 8
# 候选过期：updated_at 距今超过 30 天且命中不足晋升线的僵尸候选，归档出热文件。
CANDIDATE_TTL_DAYS = 30
# 每阶段 retired 记录的热文件上限，超限按 updated_at 最旧者滚动归档。
MAX_RETIRED_PER_STAGE = 50

_HARVEST_SYS_PROMPT = (
    "你是短剧生产流水线的教训蒸馏器。从质检报告提取可复用的生产教训："
    "每条 ≤200 字祈使句，只提有证据的失败模式（低分项、明确指出的缺陷），"
    "禁止空泛套话，禁止复述得分正常的项。"
    '输出 JSON 数组 [{"rule": "祈使句教训", "evidence": "报告中的原始证据"}]，'
    "没有可提取的教训时输出 []。除 JSON 外不要输出任何内容。"
)


class LessonRecord(BaseModel):
    """一条生产教训：从质检报告蒸馏出的、可注回提示词的祈使句规则。"""

    id: str
    stage: int
    rule: str  # ≤200 字符祈使句
    trigger: Literal["qc_finding", "repeat_failure", "manual"]
    evidence: str
    score: float
    hits: int
    status: Literal["candidate", "active", "retired"]
    created_at: str
    updated_at: str
    # 已计过数的任务 id（截尾保留最近 MAX_SEEN_TASK_IDS 个）：同任务重跑质检时
    # 幂等去重，不重复 hits+1/score 强化——防止单任务重跑把候选虚假刷成 active。
    seen_task_ids: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_lessons() -> list[LessonRecord]:
    """读取教训库；文件不存在视为空库，损坏行跳过并记日志，绝不抛异常。"""
    path = LESSONS_PATH
    if not path.is_file():
        return []
    records: list[LessonRecord] = []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        logger.warning("[KnowledgeEvolution] 教训库读取失败: %s", type(error).__name__)
        return []
    for lineno, line in enumerate(raw_lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(LessonRecord.model_validate(json.loads(line)))
        except Exception:  # noqa: BLE001 - 损坏行跳过，保住其余教训
            logger.warning("[KnowledgeEvolution] 跳过损坏的教训行 %s:%d", path.name, lineno)
    return records


def _atomic_write_lessons(records: list[LessonRecord]) -> None:
    """原子写教训库：同目录临时文件 + os.replace，掉电也不会留半个库。"""
    path = LESSONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent), suffix=".tmp", delete=False
        ) as tmp:
            tmp_name = tmp.name
            for record in records:
                tmp.write(record.model_dump_json() + "\n")
        os.replace(tmp_name, path)
    except OSError as error:
        logger.warning("[KnowledgeEvolution] 教训库写入失败: %s", type(error).__name__)
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def _append_log(event: str, **fields: object) -> None:
    """追加一条审计日志；日志失败只警告，绝不影响主流程。"""
    entry = {"ts": _now(), "event": event, **fields}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:
        logger.warning("[KnowledgeEvolution] 审计日志写入失败: %s", type(error).__name__)


def _normalize_rule(rule: str) -> str:
    """去重用的规范化：去空白与标点、转小写，只留字面内容。"""
    return re.sub(r"[\s，。！？；：、,.!?;:\"'“”‘’（）()\[\]【】-]+", "", rule).lower()


def _char_3grams(text: str) -> set[str]:
    if len(text) < 3:
        return {text} if text else set()
    return {text[i : i + 3] for i in range(len(text) - 2)}


def _jaccard(a: str, b: str) -> float:
    ga, gb = _char_3grams(a), _char_3grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _find_duplicate(rule: str, stage: int, existing: list[LessonRecord]) -> LessonRecord | None:
    """在同阶段已有教训里找重复：规范化精确匹配或 3-gram Jaccard ≥ 阈值。"""
    normalized = _normalize_rule(rule)
    for record in existing:
        if record.stage != stage:
            continue
        other = _normalize_rule(record.rule)
        if normalized == other or _jaccard(normalized, other) >= DEDUP_JACCARD:
            return record
    return None


def _parse_llm_lessons(raw: str) -> list[dict]:
    """容错解析 LLM 输出：截取首个 '[' 到末个 ']' 的 JSON 数组，失败返回空列表。"""
    if not raw:
        return []
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        logger.warning("[KnowledgeEvolution] LLM 教训输出不是合法 JSON，本轮放弃")
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict) and str(item.get("rule", "")).strip()]


def harvest_from_qc(
    stage: int,
    qc_report: str,
    task_id: str,
    llm: Callable[[str, str], str] | None = None,
) -> list[LessonRecord]:
    """从一份质检报告蒸馏候选教训并写入教训库。

    llm 是可注入的 callable(sys, user) -> str（生产传 gateway.call_llm 的偏函数，
    测试传桩）。无 llm 或调用/解析失败一律返回 []——进化是旁路，绝不阻塞流水线。
    重复教训不新增：命中已有条目则 hits+1、score 上调（强化）。
    返回本轮新增与被强化的记录。
    """
    try:
        if llm is None or not (qc_report or "").strip():
            return []
        user_prompt = (
            f"阶段：第 {stage} 阶段（任务 {task_id}）\n"
            f"以下是本阶段的质检报告，请提取生产教训：\n\n{qc_report}"
        )
        try:
            raw = llm(_HARVEST_SYS_PROMPT, user_prompt)
        except Exception as error:  # noqa: BLE001 - LLM 故障不外溢
            logger.warning("[KnowledgeEvolution] 教训蒸馏 LLM 调用失败: %s", type(error).__name__)
            return []
        candidates = _parse_llm_lessons(raw or "")
        if not candidates:
            return []
        # 不可信输出限流：单次响应最多处理 MAX_CANDIDATES_PER_HARVEST 条，防灌库。
        if len(candidates) > MAX_CANDIDATES_PER_HARVEST:
            logger.warning("[KnowledgeEvolution] LLM 单次输出 %d 条候选，截取前 %d 条",
                           len(candidates), MAX_CANDIDATES_PER_HARVEST)
            candidates = candidates[:MAX_CANDIDATES_PER_HARVEST]

        records = _load_lessons()
        touched: list[LessonRecord] = []
        dirty = False
        now = _now()
        for item in candidates:
            rule = str(item["rule"]).strip()[:200]
            # evidence 同为不可信 LLM 输出：硬截断，防止单条撑爆热文件拖慢全线加载
            evidence = str(item.get("evidence", "")).strip()[:MAX_EVIDENCE_CHARS]
            duplicate = _find_duplicate(rule, stage, records)
            if duplicate is not None:
                if task_id in duplicate.seen_task_ids:
                    # 同任务重跑质检：幂等跳过强化，仅刷新 updated_at——
                    # 否则单任务反复重跑即可把候选虚假刷过 PROMOTE_HITS 晋升线。
                    duplicate.updated_at = now
                    dirty = True
                    _append_log("dedup_task_skip", lesson_id=duplicate.id, stage=stage,
                                task_id=task_id, hits=duplicate.hits)
                    continue
                # 同一失败模式在新任务再次出现：强化而不是新增
                duplicate.hits += 1
                duplicate.score = round(duplicate.score + REINFORCE_SCORE_STEP, 4)
                duplicate.updated_at = now
                duplicate.seen_task_ids = (
                    duplicate.seen_task_ids + [task_id])[-MAX_SEEN_TASK_IDS:]
                if duplicate.status == "retired":
                    # 已退休的模式复发：回置 candidate（保留 hits/score）重新竞争晋升，
                    # 否则 retired 记录吸走后续命中、复发的失败模式被永久静音。
                    duplicate.status = "candidate"
                    _append_log("revive", lesson_id=duplicate.id, stage=stage,
                                task_id=task_id, hits=duplicate.hits)
                touched.append(duplicate)
                dirty = True
                _append_log("reinforce", lesson_id=duplicate.id, stage=stage,
                            task_id=task_id, hits=duplicate.hits, score=duplicate.score)
                continue
            record = LessonRecord(
                id=f"L{uuid.uuid4().hex[:10]}",
                stage=stage,
                rule=rule,
                trigger="qc_finding",
                evidence=evidence,
                score=1.0,
                hits=1,
                status="candidate",
                created_at=now,
                updated_at=now,
                seen_task_ids=[task_id],
            )
            records.append(record)
            touched.append(record)
            dirty = True
            _append_log("harvest", lesson_id=record.id, stage=stage,
                        task_id=task_id, rule=rule)
        if dirty:
            _atomic_write_lessons(records)
        return touched
    except Exception as error:  # noqa: BLE001 - 兜底 fail-soft
        logger.warning("[KnowledgeEvolution] harvest_from_qc 失败: %s", type(error).__name__)
        return []


def active_lessons(stage: int, limit: int = 6) -> list[LessonRecord]:
    """取某阶段 active 状态的教训，按 score*hits 降序取前 limit 条。"""
    try:
        pool = [r for r in _load_lessons() if r.status == "active" and r.stage == stage]
        pool.sort(key=lambda r: (r.score * r.hits, r.score), reverse=True)
        return pool[: max(limit, 0)]
    except Exception as error:  # noqa: BLE001
        logger.warning("[KnowledgeEvolution] active_lessons 失败: %s", type(error).__name__)
        return []


def _archive_records(stale: list[LessonRecord]) -> None:
    """把记录追加进滚动归档文件；归档失败只警告（记录仍会从热文件移除，
    但审计日志里已有对应事件，轨迹可追）。"""
    if not stale:
        return
    try:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
            for record in stale:
                f.write(record.model_dump_json() + "\n")
    except OSError as error:
        logger.warning("[KnowledgeEvolution] 归档写入失败: %s", type(error).__name__)


def _age_days(timestamp: str) -> float:
    """updated_at 距今的天数；解析失败返回 0（视为新鲜，绝不误删）。"""
    try:
        then = datetime.fromisoformat(timestamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0


def promote_and_prune() -> dict:
    """晋升与退休：candidate 命中 ≥2 转正；每阶段 active 超过上限则按分数退休最低者。

    退休只改 status（审计需要完整轨迹），每次变更都追加 evolution_log.jsonl。
    热文件体积约束（教训库绝不只进不出）：
    - 过期候选（updated_at 超过 CANDIDATE_TTL_DAYS 天仍未攒够晋升命中）滚动归档；
    - 每阶段 retired 超过 MAX_RETIRED_PER_STAGE 时，最旧者滚动归档。
    归档 = 移出 lessons.jsonl、追加进 lessons_archive.jsonl 并记审计日志，轨迹不丢。
    """
    try:
        records = _load_lessons()
        promoted: list[str] = []
        retired: list[str] = []
        archived: list[str] = []
        now = _now()

        for record in records:
            if record.status == "candidate" and record.hits >= PROMOTE_HITS:
                record.status = "active"
                record.updated_at = now
                promoted.append(record.id)
                _append_log("promote", lesson_id=record.id, stage=record.stage,
                            hits=record.hits, score=record.score)

        by_stage: dict[int, list[LessonRecord]] = {}
        for record in records:
            if record.status == "active":
                by_stage.setdefault(record.stage, []).append(record)
        for stage, actives in by_stage.items():
            overflow = len(actives) - MAX_ACTIVE_PER_STAGE
            if overflow <= 0:
                continue
            actives.sort(key=lambda r: (r.score, r.hits))  # 分数最低者先退休
            for record in actives[:overflow]:
                record.status = "retired"
                record.updated_at = now
                retired.append(record.id)
                _append_log("retire", lesson_id=record.id, stage=stage, score=record.score)

        # 热文件收容：过期僵尸候选归档（超过 TTL 仍攒不够晋升命中的不再占加载开销）
        stale: list[LessonRecord] = []
        for record in records:
            if (record.status == "candidate" and record.hits < PROMOTE_HITS
                    and _age_days(record.updated_at) > CANDIDATE_TTL_DAYS):
                stale.append(record)
                archived.append(record.id)
                _append_log("archive_expired_candidate", lesson_id=record.id,
                            stage=record.stage, hits=record.hits)
        # 热文件收容：retired 超出每阶段上限时按 updated_at 最旧者滚动归档
        retired_by_stage: dict[int, list[LessonRecord]] = {}
        for record in records:
            if record.status == "retired" and record not in stale:
                retired_by_stage.setdefault(record.stage, []).append(record)
        for stage, pool in retired_by_stage.items():
            overflow = len(pool) - MAX_RETIRED_PER_STAGE
            if overflow <= 0:
                continue
            pool.sort(key=lambda r: r.updated_at)  # 最旧者先归档
            for record in pool[:overflow]:
                stale.append(record)
                archived.append(record.id)
                _append_log("archive_retired", lesson_id=record.id, stage=stage)
        if stale:
            _archive_records(stale)
            stale_ids = {r.id for r in stale}
            records = [r for r in records if r.id not in stale_ids]

        if promoted or retired or stale:
            _atomic_write_lessons(records)
        return {"promoted": promoted, "retired": retired, "archived": archived,
                "total": len(records),
                "active": sum(1 for r in records if r.status == "active")}
    except Exception as error:  # noqa: BLE001
        logger.warning("[KnowledgeEvolution] promote_and_prune 失败: %s", type(error).__name__)
        return {"promoted": [], "retired": [], "archived": [], "total": 0, "active": 0}


def evolution_report() -> dict:
    """各阶段 candidate/active/retired 计数与 top 规则，供第 7 阶段归档。"""
    try:
        records = _load_lessons()
        stages: dict[int, dict] = {}
        for record in records:
            bucket = stages.setdefault(
                record.stage,
                {"candidate": 0, "active": 0, "retired": 0, "top_rules": []},
            )
            bucket[record.status] += 1
        for stage, bucket in stages.items():
            top = [r for r in records if r.stage == stage and r.status == "active"]
            top.sort(key=lambda r: (r.score * r.hits, r.score), reverse=True)
            bucket["top_rules"] = [r.rule for r in top[:3]]
        return {"stages": stages, "total": len(records)}
    except Exception as error:  # noqa: BLE001
        logger.warning("[KnowledgeEvolution] evolution_report 失败: %s", type(error).__name__)
        return {"stages": {}, "total": 0}
