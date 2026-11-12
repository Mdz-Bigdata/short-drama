# -*- coding: utf-8 -*-
"""Every blow written out, and the fight played in rounds.

A fight shot is written as exchange units (``U1（a–b秒）…``, see :mod:`app.core.exchange_units`). A unit's strike says
five things or the video model invents them: who strikes, where the force starts (the foot that pushes off, the turn
of the waist, which hand or which part of the weapon), the path (a downward diagonal cut, a straight thrust from the
hip, a sweep along the floor), who it lands on and where, and what it does (the head snapping aside, three stumbling
steps back, sparks where blades meet, a table overturned). With three or more fighters nobody stands and watches and
the attackers do not queue. The scene is fought in rounds that only escalate — probing, clash, escalation, reversal,
decision — with a pause between them and a clear finish.

:func:`brief` goes to the stage-4 shot-table writer, :func:`audit_shot` and :func:`audit_rounds` check what came back,
:func:`writer_rule` goes to the scriptwriter. Wording and word lists live in ``app/data/prompt/fight_exchange.json``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core import prompt_data

_DATA = "fight_exchange"
_U_START = re.compile(r"U\s*(\d+)(?:\s*[–\-~～至]\s*U?\s*\d+)?\s*[（(]")
_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass(frozen=True)
class FightIssue:
    rule: str
    detail: str


def _issue(key: str, **values: object) -> FightIssue:
    spec = prompt_data.value(_DATA, "issues")[key]
    detail = str(spec["detail"])
    for name, value in values.items():
        detail = detail.replace("{" + name + "}", str(value))
    return FightIssue(str(spec["rule"]), detail)


def _stages() -> list[str]:
    return [str(stage) for stage in prompt_data.value(_DATA, "round_stages")]


def writer_rule() -> str:
    return prompt_data.text(_DATA, "writer_rule")


def brief(fighters: int) -> str:
    """The shot-table writer's 「招招写实」 block; the multi-fighter line only with enough people in the scene."""
    multi = ""
    if fighters >= prompt_data.number(_DATA, "multi_min"):
        multi = prompt_data.text(_DATA, "multi_line").replace("{count}", str(fighters))
    lines = [line.replace("{multi}", multi).replace("{stages}", " → ".join(_stages())) for line in prompt_data.value(_DATA, "brief")]
    return "\n".join(line for line in lines if line)


def units(desc: str) -> list[tuple[int, str]]:
    """The U segments of a shot description, each with its number: the text from one U label to the next."""
    text = str(desc or "")
    starts = list(_U_START.finditer(text))
    return [(int(match.group(1)), text[match.start(): starts[i + 1].start() if i + 1 < len(starts) else len(text)])
            for i, match in enumerate(starts)]


def _has(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in words)


def _unit_names(found: Sequence[int]) -> str:
    return "、".join(f"U{number}" for number in found)


def audit_shot(desc: str, characters: Sequence[str]) -> list[FightIssue]:
    """One fight shot: does every unit say who, from where, how, onto whom and with what result; does everyone fight."""
    segments = units(desc)
    if not segments:
        return []
    elements: Mapping[str, Mapping[str, object]] = prompt_data.value(_DATA, "elements")
    cast = [str(name).strip() for name in characters if str(name).strip()]
    issues: list[FightIssue] = []

    missing_by_unit: dict[int, list[str]] = {}
    no_person: list[int] = []
    for number, segment in segments:
        gaps = [str(spec["label"]) for key, spec in elements.items() if not _has(segment, spec["words"])]  # type: ignore[arg-type]
        if gaps:
            missing_by_unit[number] = gaps
        # 落点要有人：出手的和挨打的都写进这个 U(两个以上的人才谈得上打向谁)。
        if len(cast) >= 2 and sum(name in segment for name in cast) < 2:
            no_person.append(number)
    # 句子顺序就是力的顺序：出手的那半句里，蹬地拧腰写在劈砍刺砸之后，就是先出手后发力(摆拍)。
    order = prompt_data.value(_DATA, "order_check")
    backwards = []
    for number, segment in segments:
        attack = re.split(r"[；;。]", segment, maxsplit=1)[0]
        body = [attack.find(word) for word in order["body"] if word in attack]
        strike = [attack.find(word) for word in order["strike"] if word in attack]
        if body and strike and min(strike) < max(body):
            backwards.append(number)
    if backwards:
        issues.append(_issue("force_order", units=_unit_names(backwards)))

    if missing_by_unit:
        # 同样缺什么的 U 合在一句里说。
        grouped: dict[str, list[int]] = {}
        for number, gaps in missing_by_unit.items():
            grouped.setdefault("、".join(gaps), []).append(number)
        for gaps, numbers in grouped.items():
            issues.append(_issue("missing", units=_unit_names(numbers), missing=gaps))
    if no_person:
        issues.append(_issue("no_target_person", units=_unit_names(no_person)))

    if len(cast) >= prompt_data.number(_DATA, "multi_min"):
        idle = [name for name in cast if not any(name in segment for _, segment in segments)]
        if idle:
            issues.append(_issue("idle", names="、".join(idle)))
        together = prompt_data.words(_DATA, "together_words")
        if not any(_has(segment, together) or sum(name in segment for name in cast) >= 3 for _, segment in segments):
            issues.append(_issue("queued", count=len(cast)))
    return issues


def round_of(desc: str) -> tuple[int, str] | None:
    """The 「【第N回合·阶段】」 label at the head of a fight shot, as (number, stage)."""
    match = re.search(prompt_data.text(_DATA, "round_label"), str(desc or ""))
    if not match:
        return None
    return _number(match.group("number")), match.group("stage").strip()


def _number(raw: str) -> int:
    """「3」「三」「十」「十二」「二十一」 as a number."""
    if raw.isdigit():
        return int(raw)
    if "十" not in raw:
        return _NUMERALS.get(raw, 0)
    tens, _, ones = raw.partition("十")
    return (_NUMERALS.get(tens, 0) if tens else 1) * 10 + (_NUMERALS.get(ones, 0) if ones else 0)


def audit_rounds(fight_shots: Sequence[tuple[object, str]]) -> list[tuple[object, FightIssue]]:
    """A scene's fight shots in order (shot id, description): labelled by round, rounds only escalate, a finish at the end."""
    if not fight_shots:
        return []
    stages = _stages()
    order = {stage: rank for rank, stage in enumerate(stages)}
    found: list[tuple[object, FightIssue]] = []
    labelled: list[tuple[object, int, str]] = []
    for shot_id, desc in fight_shots:
        label = round_of(desc)
        if label is None:
            found.append((shot_id, _issue("no_round", stages=" → ".join(stages))))
        else:
            labelled.append((shot_id, *label))
    previous_rank, previous_stage = -1, ""
    for shot_id, number, stage in labelled:
        rank = next((order[name] for name in stages if name in stage), None)
        if rank is not None:
            if rank < previous_rank:
                found.append((shot_id, _issue("round_back", number=number, stage=stage, previous=previous_stage, stages=" → ".join(stages))))
            previous_rank, previous_stage = max(previous_rank, rank), stage
    if len(fight_shots) >= 2 and len({number for _, number, _ in labelled}) == 1 and len(labelled) == len(fight_shots):
        found.append((fight_shots[-1][0], _issue("one_round", shots=len(fight_shots))))
    if labelled and len(fight_shots) >= 2 and stages[-1] not in labelled[-1][2]:
        found.append((labelled[-1][0], _issue("no_finish", final=stages[-1])))
    return found


def _cast_of(shot: Mapping[str, object]) -> list[str]:
    raw = shot.get("characters")
    names = raw if isinstance(raw, list) else re.split(r"[、，,/\s]+", str(raw or ""))
    return [str(name).strip() for name in names if str(name).strip() and str(name).strip() not in {"无", "空镜"}]


def table_issues(shots: Sequence[Mapping[str, object]]) -> list[str]:
    """A fight scene's drafted shot table, checked the way the revision round reads it: one line per problem."""
    from app.core import fight_design

    template = prompt_data.text(_DATA, "table_issue")
    lines: list[str] = []
    fight_shots: list[tuple[object, str]] = []
    for index, shot in enumerate(shots, start=1):
        desc = str(shot.get("desc") or "")
        if not (units(desc) or fight_design.fight_score(desc) > 0):
            continue
        shot_id = shot.get("shot_id", index)
        fight_shots.append((shot_id, desc))
        for issue in audit_shot(desc, _cast_of(shot)):
            lines.append(template.format(shot=shot_id, rule=issue.rule, detail=issue.detail))
    for shot_id, issue in audit_rounds(fight_shots):
        lines.append(template.format(shot=shot_id, rule=issue.rule, detail=issue.detail))
    return lines


__all__ = ["FightIssue", "audit_rounds", "audit_shot", "brief", "round_of", "table_issues", "units", "writer_rule"]
