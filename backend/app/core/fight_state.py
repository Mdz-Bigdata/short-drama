# -*- coding: utf-8 -*-
"""打戏里留下的东西跨镜头不丢：伤、断掉或脱手的兵器、破了的衣甲。

每一段视频都是单独生成的：上一镜被划开的左臂、断成两截的剑，下一镜的模型不知道，就会画回完好的样子。
这里从同一场前面几镜的分镜描述里按词抽出这些状态(整句留下，左右和部位都在句子里)，
写成一句「伤势与兵器承接」跟在本段提示词后面。捡起兵器之后，那人「脱手」的那条就不再带。

只认写明了谁的句子；没写名字时，这一镜只有一个人才算他的。词表与措辞在 ``app/data/prompt/fight_state.json``。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core import prompt_data

_WORDING = "fight_state"
_CLAUSE = re.compile(r"[^，,。；;！!？?\n]+")

WOUND, WEAPON, LOST, GARMENT, SCENE, POWER = "wound", "weapon", "lost", "garment", "scene", "power"
# 变化过、又恢复了常态：本场后面写明变化全部消失，不残留、不停在中间态。
RESTORED = "restored"


@dataclass(frozen=True)
class Mark:
    person: str
    kind: str
    text: str


def _words(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING, key)


def _kind(clause: str) -> str:
    if any(word in clause for word in _words("power_words")):
        return POWER
    if any(word in clause for word in _words("lost_words")):
        return LOST
    if any(word in clause for word in _words("weapon_words")):
        return WEAPON
    if any(part in clause for part in _words("garment_parts")) and any(word in clause for word in _words("garment_damage")):
        return GARMENT
    if any(word in clause for word in _words("wound_words")):
        return WOUND
    if any(word in clause for word in _words("scene_words")):
        return SCENE
    return ""


def _person(clause: str, names: Mapping[str, str], solo: str) -> str:
    """句子里最先出现的那个人(称呼也认)；没写名字时，这一镜只有一个人就算他的。"""
    found = [(clause.find(title), owner) for title, owner in names.items() if title and title in clause]
    return min(found)[1] if found else solo


def extract(text: str, names: Mapping[str, str], solo: str = "") -> tuple[list[Mark], set[str]]:
    """一镜留下的状态，和这一镜捡回兵器的人。``names`` 是 称呼 → 角色名(角色名自己也在里面)。"""
    limit = prompt_data.number(_WORDING, "clause_limit")
    marks: list[Mark] = []
    recovered: set[str] = set()
    clauses = [raw.strip() for raw in _CLAUSE.findall(str(text or "")) if raw.strip()]
    for index, clause in enumerate(clauses):
        person = _person(clause, names, solo)
        if _kind(clause) == SCENE:
            # 打坏的场景不属于哪个人：地面龟裂、焦痕、断柱……这一场后面都还在。
            marks.append(Mark(prompt_data.text(_WORDING, "scene_label"), SCENE, clause[:limit]))
            continue
        if not person:
            continue
        if any(word in clause for word in _words("recover_words")):
            recovered.add(person)
            continue
        if any(word in clause for word in _words("power_end_words")):
            # 魔气散去、收起法相：这个人「此后一直如此」的那条到此为止。
            recovered.add(f"power:{person}")
            continue
        kind = _kind(clause)
        if kind:
            # 句首就是这个人时去掉名字：承接句里已经按人分好了。
            text = re.sub(rf"^(?:{'|'.join(re.escape(title) for title, owner in names.items() if owner == person) or re.escape(person)})的?", "", clause) or clause
            if kind == POWER:
                # 突破之后紧跟的那句通常就是看得见的变化(周身泛起淡金光)：没点别人的名就一起带上。
                following = clauses[index + 1] if index + 1 < len(clauses) else ""
                if following and _person(following, names, "") in ("", person) and not _kind(following):
                    text = f"{text}，{following}"
                text = prompt_data.text(_WORDING, "power_label").format(text[: prompt_data.number(_WORDING, "power_limit")])
            else:
                text = text[:limit]
            marks.append(Mark(person, kind, text))
    return marks, recovered


def _shot_text(shot: Mapping[str, Any]) -> str:
    contract = shot.get("motion_contract") if isinstance(shot.get("motion_contract"), Mapping) else {}
    return "。".join(
        str(part or "") for part in (shot.get("desc"), contract.get("subject_action"), contract.get("end_state")) if str(part or "").strip()
    )


def _shot_people(shot: Mapping[str, Any]) -> list[str]:
    contract = shot.get("motion_contract") if isinstance(shot.get("motion_contract"), Mapping) else {}
    people = contract.get("characters") or shot.get("characters") or []
    return [str(name).strip() for name in people if str(name).strip() and str(name).strip() not in ("无", "空镜")]


def carry_line(marks: Sequence[Mark]) -> str:
    """一段视频前面已经留下的状态写成一句；没有时是空串。"""
    if not marks:
        return ""
    by_person: dict[str, list[str]] = {}
    for mark in marks:
        by_person.setdefault(mark.person, []).append(mark.text)
    template = prompt_data.text(_WORDING, "item")
    items = "；".join(template.format(person, "，".join(texts)) for person, texts in by_person.items())
    return prompt_data.text(_WORDING, "line").format(items)


def carry_key(scene_id: Any, shot_id: Any) -> str:
    return f"{scene_id or ''}:{shot_id}"


def scene_carry(shots: Iterable[Mapping[str, Any]], aliases: Mapping[str, str] | None = None) -> dict[str, str]:
    """每一镜开拍时本场已经留下的状态：``{"场次:镜号": 那一句}``，本场前面什么都没留下的镜不在里面。

    各场镜号都从 1 起，只用镜号会把别的场的伤势带过来，所以键带场次。``shots`` 按分镜顺序；换场就清零。
    """
    aliases = dict(aliases or {})
    keep = prompt_data.number(_WORDING, "max_marks")
    carried: dict[str, str] = {}
    scene = None
    marks: list[Mark] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            continue
        scene_id = str(shot.get("scene_id") or "")
        if scene_id != scene:
            # 换场：伤、兵器、场景损毁清零；突破、入魔这类变化跟着人走，到后面的场次还在。
            scene, marks = scene_id, [mark for mark in marks if mark.kind == POWER]
        line = carry_line(marks)
        if line:
            carried[carry_key(scene_id, shot.get("shot_id"))] = line
        people = _shot_people(shot)
        names = {**{name: name for name in people}, **{title: owner for title, owner in aliases.items() if owner in people}}
        found, recovered = extract(_shot_text(shot), names, people[0] if len(people) == 1 else "")
        # 捡回兵器的人，之前那条「脱手 / 被挑飞」不再带；断掉的兵器捡起来还是断的，照样带。
        restored = [
            Mark(mark.person, RESTORED, prompt_data.text(_WORDING, "restored_label"))
            for mark in marks if mark.kind == POWER and f"power:{mark.person}" in recovered
        ]
        marks = [
            mark for mark in marks
            if not (mark.kind == LOST and mark.person in recovered) and not (mark.kind == POWER and f"power:{mark.person}" in recovered)
            and not (mark.kind == RESTORED and any(new.person == mark.person and new.kind == POWER for new in found))
        ] + [mark for mark in dict.fromkeys(restored) if mark not in marks]
        for mark in found:
            if mark not in marks:
                marks.append(mark)
        scene_marks = [mark for mark in marks if mark.kind == SCENE][-prompt_data.number(_WORDING, "max_scene_marks"):]
        power_marks = [mark for mark in marks if mark.kind == POWER][-prompt_data.number(_WORDING, "max_power_marks"):]
        marks = [mark for mark in marks if mark.kind not in (SCENE, POWER)][-keep:] + scene_marks + power_marks
    return carried


__all__ = ["GARMENT", "LOST", "Mark", "POWER", "RESTORED", "SCENE", "WEAPON", "WOUND", "carry_key", "carry_line", "extract", "scene_carry"]
