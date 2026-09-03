# -*- coding: utf-8 -*-
"""Enforce the shot-design skill's hard rules on a parsed shot table.

The skill (``backend/skills/shot-design-master``) states the rules in the stage
prompt, but a prompt is a request, not a guarantee: models routinely answer with
a 110s "shot", an abstract emotion word, or five identical medium shots in a row.
This module turns the rules that are mechanically checkable into an audit, and
repairs the one that is mechanically repairable - a clip longer than the selected
video model can render in a single generation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds, split_shot_seconds
from app.core.writer_dashboard import parse_duration_seconds


logger = logging.getLogger("app.core.shot_table_rules")

# 景别取词表，与 skills/shot-design-master/references/shot-grammar.md 的主表对应。
SHOT_SIZE_TERMS: tuple[str, ...] = (
    "大远景", "远景", "全景", "中远景", "中全景", "中景", "中近景", "近景",
    "特写", "大特写", "极特写", "侧脸特写", "眼部特写", "嘴部特写", "手部特写",
    "局部特写", "道具特写", "背影", "过肩", "双人", "主观", "空镜",
    "EWS", "WS", "LS", "FS", "MLS", "MS", "MCU", "CU", "BCU", "ECU", "OTS", "POV",
)

# 情绪必须写成可观察的身体细节；这些词单独出现说明只写了结论没写画面。
ABSTRACT_EMOTION_TERMS: tuple[str, ...] = (
    "悲伤", "愤怒", "害怕", "感动", "开心", "难过", "生气", "恐惧",
    "紧张", "兴奋", "失望", "绝望", "震惊", "尴尬", "焦虑", "痛苦",
)
# 只要同句出现具象身体线索，就认为情绪已经落地。
PHYSICAL_CUE_TERMS: tuple[str, ...] = (
    "眉", "眼", "唇", "嘴", "下颌", "牙关", "鼻翼", "呼吸", "肩", "手", "指",
    "背", "喉", "脸颊", "泪", "颤", "攥", "握", "咬", "抿", "垂", "瞳",
)
# 心理描写红线：摄影机拍不到的内容。
INNER_MONOLOGUE_TERMS: tuple[str, ...] = (
    "心想", "内心", "心里", "暗想", "回忆起", "想起", "觉得", "认为", "希望",
)

MIN_DESC_CHARS = 50
MAX_SAME_SIZE_RUN = 2


@dataclass
class ShotIssue:
    shot_id: Any
    rule: str
    detail: str
    severity: str = "warning"


@dataclass
class ShotTableAudit:
    shots: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ShotIssue] = field(default_factory=list)
    repaired: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.ok:
            return "分镜表通过全部硬性规则检查"
        by_rule: dict[str, int] = {}
        for issue in self.issues:
            by_rule[issue.rule] = by_rule.get(issue.rule, 0) + 1
        parts = "；".join(f"{rule} × {count}" for rule, count in sorted(by_rule.items()))
        repaired = f"，已自动修复 {self.repaired} 处超长镜头" if self.repaired else ""
        return f"分镜表检查发现 {len(self.issues)} 项问题：{parts}{repaired}"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def audit_shot_table(
    shots: Sequence[dict[str, Any]],
    *,
    video_model: str = "",
    repair: bool = True,
) -> ShotTableAudit:
    """Check a parsed shot table against the skill's mechanically checkable rules.

    With ``repair`` the returned shots have over-long durations cut down to the
    model's single-clip ceiling; every other rule is reported, never silently
    rewritten, because only a human can decide how to re-stage a shot.
    """
    cap = max_shot_seconds(video_model)
    audit = ShotTableAudit()
    previous_size = ""
    same_size_run = 0

    for index, raw in enumerate(shots):
        if not isinstance(raw, dict):
            continue
        shot = dict(raw)
        shot_id = shot.get("shot_id", index + 1)
        desc = _text(shot.get("desc"))
        size = _text(shot.get("size"))

        seconds = parse_duration_seconds(shot.get("duration"))
        if seconds > cap:
            audit.issues.append(ShotIssue(
                shot_id, "时长超模型上限",
                f"{seconds}s 超过 {video_model or '未指定模型'} 的单镜上限 {cap}s",
                "error",
            ))
            if repair:
                slices = split_shot_seconds(seconds, video_model)
                shot["duration"] = f"{slices[0]}s" if slices else f"{cap}s"
                audit.repaired += 1
        elif seconds and seconds < MIN_SHOT_SECONDS:
            audit.issues.append(ShotIssue(
                shot_id, "时长低于下限",
                f"{seconds}s 低于可提交下限 {MIN_SHOT_SECONDS}s",
            ))

        if size and not _has_any(size.upper(), (term.upper() for term in SHOT_SIZE_TERMS)):
            audit.issues.append(ShotIssue(shot_id, "景别不在词典内", f"「{size}」不是标准景别术语"))

        if size and size == previous_size:
            same_size_run += 1
            if same_size_run >= MAX_SAME_SIZE_RUN:
                audit.issues.append(ShotIssue(
                    shot_id, "同景别连续堆叠",
                    f"连续 {same_size_run + 1} 镜都是「{size}」，需远近交替",
                ))
        else:
            same_size_run = 0
        previous_size = size

        if desc and len(desc) < MIN_DESC_CHARS:
            audit.issues.append(ShotIssue(
                shot_id, "画面内容过短", f"{len(desc)} 字，规范要求不少于 {MIN_DESC_CHARS} 字",
            ))

        if _has_any(desc, INNER_MONOLOGUE_TERMS):
            hit = next(term for term in INNER_MONOLOGUE_TERMS if term in desc)
            audit.issues.append(ShotIssue(
                shot_id, "出现心理描写", f"「{hit}」是摄影机拍不到的内容", "error",
            ))

        if _has_any(desc, ABSTRACT_EMOTION_TERMS) and not _has_any(desc, PHYSICAL_CUE_TERMS):
            hit = next(term for term in ABSTRACT_EMOTION_TERMS if term in desc)
            audit.issues.append(ShotIssue(
                shot_id, "情绪未具象化", f"只写了「{hit}」，没有可观察的面部或肢体细节",
            ))

        audit.shots.append(shot)

    if len(audit.shots) == 1:
        audit.issues.append(ShotIssue(
            audit.shots[0].get("shot_id", 1), "整集仅一个镜头", "一集必须拆成多个镜头", "error",
        ))

    return audit


def audit_and_log(shots: Sequence[dict[str, Any]], *, video_model: str, task_id: str = "") -> list[dict[str, Any]]:
    """Audit, log the findings, and return the (possibly repaired) shot list."""
    audit = audit_shot_table(shots, video_model=video_model)
    if audit.issues:
        logger.warning("[Stage4] %s (task=%s)", audit.summary(), task_id or "-")
        for issue in audit.issues[:20]:
            logger.info("[Stage4] 镜%s %s：%s", issue.shot_id, issue.rule, issue.detail)
    return audit.shots
