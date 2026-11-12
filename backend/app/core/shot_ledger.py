# -*- coding: utf-8 -*-
"""镜间衔接账本：同一场戏里，下一镜从上一镜结束时的样子开拍。

每一镜都是单独生成的，模型不记得上一镜里谁站哪、手里拿着什么。这里按镜头顺序把
每个关键道具「在谁手里(哪只手)或放在哪、哪面朝镜头、什么状态」和每个人物「姿态」
记成账：

* 下一镜的提示词开头写明它接的是什么样子(:func:`handoff_line`)；
* 道具在相邻两镜之间换了手、挪了位置或变了状态，而这一镜里没有递、放、拿、打开这类
  动作，记一条「道具穿帮」；人物姿态变了而没写起身、坐下，记一条「姿态跳变」。

有空间方案的场次先读方案：物理接触(谁哪只手握着什么、什么搁在什么上)和每镜收尾时的
姿态(:func:`staged_facts`)；再从镜头文字(起始状态、画面动作、结束状态)里读，读不出的
不记、不替它编。措辞和词表在 data/prompt/shot_ledger.json。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.core import prompt_data

_DATA = "shot_ledger"


def _says(key: str, **values: Any) -> str:
    return str(prompt_data.value(_DATA, "says")[key]).format(**values)


def _table(key: str) -> list[tuple[re.Pattern[str], str]]:
    return [(re.compile(words), label) for words, label in prompt_data.value(_DATA, key)]


@dataclass(frozen=True)
class PropState:
    """一件道具此刻的样子；都空表示还不知道。"""

    holder: str = ""
    hand: str = ""
    place: str = ""
    down: bool = False
    condition: str = ""
    facing: str = ""

    def known(self) -> bool:
        return bool(self.holder or self.place or self.down or self.condition or self.facing)

    def where(self) -> str:
        if self.holder:
            return f"{self.holder}{self.hand}"
        return self.place or ("" if not self.down else "放下")


@dataclass
class Entry:
    """一镜的账：开拍时(承接上一镜)和收尾时每件道具、每个人的样子，以及这一镜的穿帮。"""

    scene_id: str
    shot_id: Any
    start_props: dict[str, PropState] = field(default_factory=dict)
    end_props: dict[str, PropState] = field(default_factory=dict)
    start_postures: dict[str, str] = field(default_factory=dict)
    end_postures: dict[str, str] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)
    first_in_scene: bool = True


def key(scene_id: Any, shot_id: Any) -> str:
    return f"{scene_id or ''}:{shot_id}"


def _texts(shot: Mapping[str, Any]) -> list[str]:
    """一镜按时间顺序的三段文字：起始状态、画面动作、结束状态。"""
    contract = shot.get("motion_contract") if isinstance(shot.get("motion_contract"), Mapping) else {}
    action = str(shot.get("desc") or contract.get("subject_action") or shot.get("action") or "")
    return [str(contract.get("start_state") or ""), action, str(contract.get("end_state") or "")]


def _names(shot: Mapping[str, Any], cast: Sequence[str]) -> list[str]:
    listed = [str(name).strip() for name in (shot.get("characters") or []) if str(name).strip()]
    return sorted(dict.fromkeys([*listed, *(str(name).strip() for name in cast if str(name).strip())]), key=len, reverse=True)


def _is_prop(name: str, names: Sequence[str]) -> bool:
    name = str(name or "").strip()
    return bool(name) and not any(name.startswith(word) for word in prompt_data.words(_DATA, "no_prop")) and (
        name not in prompt_data.words(_DATA, "not_props") and not any(person in name or name in person for person in names)
    )


def _props(shot: Mapping[str, Any], carried: Mapping[str, PropState], names: Sequence[str] = ()) -> list[str]:
    """这一镜要记账的道具：道具栏登记的、上一镜带过来的，和动作句里被拿、被放、被翻的东西。"""
    listed = [str(item).strip() for item in (shot.get("props") or [])]
    contract = shot.get("motion_contract") if isinstance(shot.get("motion_contract"), Mapping) else {}
    listed += [str(item).strip() for item in (contract.get("props") or [])]
    for text in _texts(shot):
        for pattern in prompt_data.words(_DATA, "object_patterns"):
            listed += [match.group(1).strip() for match in re.finditer(pattern, text)]
    return sorted(dict.fromkeys(item for item in [*listed, *carried] if _is_prop(item, names)), key=len, reverse=True)


def _clauses(text: str) -> list[tuple[str, str]]:
    """(分句, 这个分句之前同一句里最近提到的人用来找主语的整句前文)。"""
    sentence_split = re.compile(prompt_data.text(_DATA, "sentence"))
    clause_split = re.compile(prompt_data.text(_DATA, "clause"))
    out = []
    for sentence in sentence_split.split(str(text or "")):
        before = ""
        for clause in clause_split.split(sentence):
            if clause.strip():
                out.append((clause, before))
            before += clause + "，"
    return out


def _subject(clause: str, before: str, names: Sequence[str], at: int) -> str:
    """这个分句里在 ``at`` 之前最近的人名；分句里没有就用同一句前文里最后提到的人。"""
    found = [(clause.rfind(name, 0, at), name) for name in names if 0 <= clause.rfind(name, 0, at)]
    if found:
        return max(found)[1]
    earlier = [(before.rfind(name), name) for name in names if before.rfind(name) >= 0]
    return max(earlier)[1] if earlier else ""


def _hand(clause: str) -> str:
    return next((label for word, label in prompt_data.value(_DATA, "hands").items() if word in clause), "")


def _place(match_end: int, clause: str) -> str:
    tail = re.match(prompt_data.text(_DATA, "place_tail"), clause[match_end:])
    return tail.group(0) if tail else ""


def _last_prop(before: str, props: Sequence[str]) -> str:
    found = [(before.rfind(prop), prop) for prop in props if before.rfind(prop) >= 0]
    return max(found)[1] if found else ""


def _read_prop(clause: str, before: str, prop: str, names: Sequence[str], props: Sequence[str] = ()) -> tuple[dict[str, Any], set[str]]:
    """这个分句对 ``prop`` 说了什么：(要改的字段, 动作种类)。种类 ``move`` 是递、拿、放(换手或挪位)，
    ``state`` 是打开、点燃这类改状态的；只是描述(拿着、放在桌上)时种类为空。没说就是 ({}, 空)。

    分句里没提任何道具、只写了「翻开」「合上」这类改状态的动作，算在同一句前文最近提到的那件道具上。
    """
    # 「保持」「坚持」里的「持」不是拿着：先去掉再认。
    for word in prompt_data.words(_DATA, "hold_false"):
        clause = clause.replace(word, "")
    at = clause.find(prop)
    if at < 0:
        if any(other in clause for other in props) or _last_prop(before, props or (prop,)) != prop:
            return {}, set()
        # 只认改状态的动作(翻开、合上、点燃)：没写东西名的「压在石面上」多半说的是手，不是道具。
        change, kinds = _read_prop(prop + clause, before, prop, names, props)
        if kinds != {"state"}:
            return {}, set()
        return {key: value for key, value in change.items() if key in ("condition", "facing")}, kinds
    change: dict[str, Any] = {}
    kinds: set[str] = set()
    given = re.search(prompt_data.text(_DATA, "give") + "(" + "|".join(map(re.escape, names)) + ")", clause) if names else None
    if given:
        change.update(holder=given.group(1), hand="", place="", down=False)
        kinds.add("move")
    else:
        take = next((verb for verb in prompt_data.words(_DATA, "take") if verb in clause), "")
        put = re.search(prompt_data.text(_DATA, "put"), clause)
        if take and (not put or clause.find(take) > put.start()):
            holder = _subject(clause, before, names, clause.find(take))
            if holder:
                change.update(holder=holder, hand=_hand(clause), place="", down=False)
                kinds.add("move")
        elif put and at < put.start():
            # 道具在动词前面才是被放下的东西；「双手放在合同两侧」里合同是位置参照。
            place = _place(put.end(), clause)
            change.update(holder="", hand="", place=place, down=not place)
            kinds.add("move")
    if re.search(prompt_data.text(_DATA, "condition_events"), clause):
        kinds.add("state")
    for pattern, label in _table("conditions"):
        if pattern.search(clause):
            change["condition"] = label
            break
    for pattern, label in _table("facings"):
        if pattern.search(clause):
            change["facing"] = label
            break
    in_hand = re.search("把" + re.escape(prop) + "(?:" + prompt_data.text(_DATA, "in_hand_after_ba") + ")", clause)
    if "move" not in kinds and "holder" not in change and in_hand:
        holder = _subject(clause, before, names, in_hand.start())
        if holder:
            change.update(holder=holder, hand=_hand(clause), place="", down=False)
    if "move" not in kinds and "holder" not in change:
        hold = next((verb for verb in prompt_data.words(_DATA, "hold_verbs") if verb in clause), "")
        rest = re.search(prompt_data.text(_DATA, "rest"), clause)
        if hold:
            holder = _subject(clause, before, names, clause.find(hold) if clause.find(hold) < at else at)
            if holder:
                change.update(holder=holder, hand=_hand(clause), place="", down=False)
        elif rest and rest.start() > at:
            place = _place(rest.end(), clause)
            if place:
                change.update(holder="", hand="", place=place, down=False)
    return change, kinds


def _read_posture(clause: str, before: str, names: Sequence[str]) -> list[tuple[str, str, bool]]:
    """这个分句里谁是什么姿态：[(人, 姿态, 是不是过渡动作)]。"""
    moves = re.compile(prompt_data.text(_DATA, "posture_moves"))
    found = []
    for pattern, label in _table("postures"):
        for match in pattern.finditer(clause):
            who = _subject(clause, before, names, match.start())
            if who:
                found.append((match.start(), who, label, bool(moves.match(clause, match.start()))))
    return [(who, label, moved) for _at, who, label, moved in sorted(found)]


def _differs(before: PropState, after: Mapping[str, Any], acted: set[str] = frozenset()) -> bool:
    """``after`` 和上一镜结束时对不上；这一镜里有对应动作(``acted``)的那一项不算。"""
    if "holder" in after and "move" not in acted:
        if before.holder and after["holder"] and before.holder != after["holder"]:
            return True
        if (before.place or before.down) and after["holder"]:
            return True
        if before.holder and after.get("place"):
            return True
        if before.place and after.get("place") and before.place != after["place"]:
            return True
    return "state" not in acted and bool(before.condition and after.get("condition") and before.condition != after["condition"])


def describe(prop: str, state: PropState) -> str:
    """「文件夹在林夏右手（合上）」「茶杯在书案上」。"""
    if state.holder:
        head = _says("prop_held", prop=prop, holder=state.holder, hand=state.hand or _says("hand_default"))
    elif state.place:
        head = _says("prop_placed", prop=prop, place=state.place)
    elif state.down:
        head = _says("prop_down", prop=prop)
    else:
        head = prop
    details = [item for item in (state.condition, state.facing) if item]
    return head + (_says("prop_extra", details=_says("detail_join").join(details)) if details else "")


@dataclass(frozen=True)
class Staged:
    """空间方案里一镜的物理事实：拿着的、搁着的道具和收尾时的姿态。"""

    props: dict[str, dict[str, Any]] = field(default_factory=dict)
    postures: dict[str, str] = field(default_factory=dict)


def staged_facts(plan: Any, shot_id: Any) -> Staged:
    """读方案(只读)：这一镜的握持、搁置接触和每个人收尾时的姿态。方案里没有这一镜时是空的。"""
    if plan is None:
        return Staged()
    try:
        stage_shot = plan.shot(int(shot_id))
    except (TypeError, ValueError):
        return Staged()
    if stage_shot is None:
        return Staged()
    from app.core.spatial_stage import contacts

    hands = prompt_data.value(_DATA, "contact_hands")
    props: dict[str, dict[str, Any]] = {}
    for contact in contacts.in_shot(getattr(plan, "contacts", None) or [], stage_shot.shot_id):
        if contact.kind == "hold":
            props[contact.target] = {"holder": contact.actor, "hand": hands.get(contact.hand, hands[""]), "place": "", "down": False}
        elif contact.kind == "rest":
            props[contact.target] = {"holder": "", "hand": "", "place": contact.support, "down": False}
    names = prompt_data.value(_DATA, "plan_postures")
    # 只记这一镜画面里看得见的人：画外的人在方案里也站着个默认姿态，不能当成他这一镜的样子。
    visible = {state.name for state in getattr(stage_shot, "screen", []) or [] if getattr(state, "visible", False)}
    postures = {
        actor.name: names.get(actor.posture, "") for actor in plan.actors_in(stage_shot, at_end=True)
        if actor.name in visible and names.get(actor.posture)
    }
    return Staged(props=props, postures=postures)


def walk(
    shots: Sequence[Mapping[str, Any]], cast: Sequence[str] = (), *, plans: Callable[[str], Any] | None = None,
) -> dict[str, Entry]:
    """按顺序给每一镜记账；``key(scene_id, shot_id)`` → :class:`Entry`。换场次就从头记。

    ``plans(scene_id)`` 给这场的空间方案(没有时 None)：方案里的接触先记，当作这一镜写明的事实。
    """
    plan_cache: dict[str, Any] = {}
    ledger: dict[str, Entry] = {}
    props: dict[str, PropState] = {}
    postures: dict[str, str] = {}
    scene = None
    for shot in shots:
        if not isinstance(shot, Mapping):
            continue
        scene_id = str(shot.get("scene_id") or "")
        first = scene_id != scene
        if first:
            props, postures, scene = {}, {}, scene_id
        names = _names(shot, cast)
        entry = Entry(scene_id=scene_id, shot_id=shot.get("shot_id"), first_in_scene=first,
                      start_props=dict(props), start_postures=dict(postures))
        if plans is not None and scene_id not in plan_cache:
            try:
                plan_cache[scene_id] = plans(scene_id)
            except Exception:  # 方案读不出来就只看文字
                plan_cache[scene_id] = None
        staged = staged_facts(plan_cache.get(scene_id), shot.get("shot_id"))
        texts = _texts(shot)
        wanted = sorted(dict.fromkeys([*_props(shot, props, names), *staged.props]), key=len, reverse=True)
        clauses = [item for text in texts for item in _clauses(text)]
        acted: dict[str, set[str]] = {}
        for clause, before in clauses:
            for prop in wanted:
                acted.setdefault(prop, set()).update(_read_prop(clause, before, prop, names, wanted)[1])
        moved = {who for clause, before in clauses for who, _label, is_move in _read_posture(clause, before, names) if is_move}
        flagged: set[str] = set()
        seen_posture: set[str] = set()
        # 方案里的接触整镜都成立：先当这一镜写明的事实记上(对不上上一镜、又没有对应动作就是穿帮)。
        for prop, change in staged.props.items():
            if not first and _differs(entry.start_props.get(prop, PropState()), change, acted.get(prop, set())):
                entry.issues.append({"rule": "prop_jump", "detail": _says(
                    "prop_jump", prop=prop, before=describe(prop, entry.start_props[prop]).removeprefix(prop),
                    after=describe(prop, replace(props.get(prop, PropState()), **change)).removeprefix(prop),
                )})
                flagged.add(prop)
            props[prop] = replace(props.get(prop, PropState()), **change)
        for clause, before in clauses:
            for prop in wanted:
                change, _kinds = _read_prop(clause, before, prop, names, wanted)
                if not change:
                    continue
                current = props.get(prop, PropState())
                if not first and prop not in flagged and _differs(entry.start_props.get(prop, PropState()), change, acted.get(prop, set())):
                    after = describe(prop, replace(current, **change))
                    entry.issues.append({"rule": "prop_jump", "detail": _says(
                        "prop_jump", prop=prop, before=describe(prop, entry.start_props[prop]).removeprefix(prop), after=after.removeprefix(prop),
                    )})
                    flagged.add(prop)
                props[prop] = replace(current, **change)
            for who, label, _is_move in _read_posture(clause, before, names):
                if who not in seen_posture:
                    seen_posture.add(who)
                    earlier = entry.start_postures.get(who)
                    if not first and earlier and earlier != label and who not in moved:
                        entry.issues.append({"rule": "posture_jump", "detail": _says("posture_jump", name=who, before=earlier, after=label)})
                postures[who] = label
        # 方案摆出来的收尾姿态为准(导演台上摆的就是这一镜结束时的样子)。
        postures.update(staged.postures)
        entry.end_props, entry.end_postures = dict(props), dict(postures)
        ledger[key(scene_id, shot.get("shot_id"))] = entry
    return ledger


def handoff_line(entry: Entry | None, people: Sequence[str] = (), props: Sequence[str] = ()) -> str:
    """这一镜开拍时接的样子，写进视频提示词；一场戏的第一镜、或什么都没记下时是空串。

    ``people`` / ``props`` 是这一镜里出现的人和道具：只写它们，不把画外的东西请进画面。
    """
    items = handoff_items(entry, people, props)
    return _says("handoff", items=items) if items else ""


def handoff_items(entry: Entry | None, people: Sequence[str] = (), props: Sequence[str] = ()) -> str:
    """只有那几样东西(「林夏站着，右手持文件夹；茶杯在书案上」)，给字数有限的首帧交接栏。"""
    if entry is None or entry.first_in_scene:
        return ""
    in_shot = {str(name) for name in people if str(name).strip()}
    wanted = {str(prop) for prop in props if str(prop).strip()}
    items: list[str] = []
    held: dict[str, list[str]] = {}
    for prop, state in entry.start_props.items():
        if state.holder and (not in_shot or state.holder in in_shot):
            details = [item for item in (state.condition, state.facing) if item]
            held.setdefault(state.holder, []).append(
                _says("holds", hand=state.hand or _says("holds_default_hand"), prop=prop)
                + (_says("prop_extra", details=_says("detail_join").join(details)) if details else "")
            )
    for name, posture in entry.start_postures.items():
        if in_shot and name not in in_shot:
            continue
        hands = held.pop(name, [])
        items.append(_says("person", name=name, posture=posture) + (_says("person_holds", hands=_says("detail_join").join(hands)) if hands else ""))
    for name, hands in held.items():
        items.append(name + _says("detail_join").join(hands))  # 记下拿着东西、却没记下姿态的人
    for prop, state in entry.start_props.items():
        if not state.holder and state.known() and (not wanted or prop in wanted):
            items.append(describe(prop, state))
    return _says("join").join(items[: int(prompt_data.value(_DATA, "max_items"))])


def end_props(entry: Entry | None) -> dict[str, str]:
    """一镜收尾时每件道具的样子(给合成前的连续性质检比交接)；没记下的不写。"""
    if entry is None:
        return {}
    return {prop: describe(prop, state) for prop, state in entry.end_props.items() if state.known()}


__all__ = ["Entry", "PropState", "Staged", "describe", "end_props", "handoff_items", "handoff_line", "key", "staged_facts", "walk"]
