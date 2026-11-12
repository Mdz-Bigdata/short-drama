# -*- coding: utf-8 -*-
"""每格分镜图的提示词：给图片模型，每格一份，固定【落笔】【调色】【收边】三段。

一格分镜是视频模型接拍的依据，只演一个正在进行的可见动作。几件事要注意：

* 一格可能由几拍合并而来(``storyboard_panels`` 用「；随后」连接)，整段视频都要演，但这张图只画开头
  那一拍(尾帧画最后一拍)，后面的拍进「本拍排除」，不提前出现。
* 各格是并发出图的，看不到上一格的成图，所以上一格的结束状态要写成文字。
* 图号和发给模型的参考图顺序一一对应，``references`` 必须和 ``ref_images`` 同序。
* 没有内容可填的栏整行不写，不留空话；不编造表里没有的光比、色温。

本模块只做文本，不调模型。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from app.core import breakdown_kinds, prompt_data, real_person, wuxia_vfx
from app.core.action_grammar import concrete_ending, has_structure
from app.core.face_card import parse_face_card
from app.core.scene_turnaround import SCENE_VIEW_LABELS, SCENE_VIEW_PURPOSES
from app.core.shot_motion_contract import CompiledShotPrompt, ShotMotionContract
from app.core.storyboard_scene_context import EMPTY_ACTOR, costume_owner, is_uncast, look_makeup_note

# 每格提示词的全部固定句、栏名、词表和正则都在 app/data/prompt/panel_still.json：这里只拼接。
_DATA = "panel_still"


def _fixed(key: str) -> Mapping[str, Any]:
    return prompt_data.value(_DATA, key)


def _says(key: str, /, **values: object) -> str:
    """A sentence of the table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(_fixed("says")[key]).format(**values)


def _word(key: str) -> str:
    return str(_fixed("words")[key])


def _label(key: str) -> str:
    return str(_fixed("labels")[key])


def _mark(key: str) -> str:
    return str(_fixed("marks")[key])


def _pattern(key: str) -> re.Pattern[str]:
    return re.compile(str(_fixed("patterns")[key]))


MERGED_BEATS = prompt_data.text(_DATA, "merged_beats")
_NOBODY = {EMPTY_ACTOR, *prompt_data.words(_DATA, "nobody")}
_NO_ASSET = prompt_data.words(_DATA, "no_asset")
_NO_LINE = set(prompt_data.words(_DATA, "no_line"))
_SPEAKER = _pattern("speaker")
_CONTACT = _pattern("contact")
_PHASE_TURN = _pattern("phase_turn")
_CLAUSE = _pattern("clause")
_MAIN_LIGHT = _pattern("main_light")
_OUTFIT_BREAKS = _pattern("outfit_breaks")
_STEP = str(_fixed("patterns")["step"])
#: 切点规划和分镜表的固定措辞：只说了「要接上」，没说姿势，拿来当姿态写等于没写。
_SAYS_NOTHING = prompt_data.words(_DATA, "says_nothing")
_PICTURE_NOUN = {**prompt_data.value(_DATA, "picture_noun"), **breakdown_kinds.PICTURE_NOUN}
_ONLY_GIVES = {**prompt_data.value(_DATA, "only_gives"), **breakdown_kinds.ONLY_GIVES}
_CLOSING = _says("closing")
_NOT_A = _says("not_a")
_LIST = _mark("list")
_CLAUSES = _mark("clause")
_COMMA = _mark("comma")
_PERIOD = _mark("period")
_CLIP_EDGES = _mark("clip_edges")
_CLIP_TAIL = _mark("clip_tail")
_PHASE_EDGES = _mark("phase_edges")


def _clip(text: Any, limit: int = 240) -> str:
    body = " ".join(str(text or "").split()).strip(_CLIP_EDGES)
    return body if len(body) <= limit else body[: limit - 1].rstrip(_CLIP_TAIL) + "…"


def _says_something(text: Any) -> str:
    body = _clip(text)
    return "" if not body or body in _SAYS_NOTHING or body.startswith(_word("says_nothing_prefix")) else body


def _one_phase(expression: Any, frame_state: str) -> str:
    """表情描述里写了变化(「眉心收紧，转为冷笑」)时只取这一帧的那个阶段：首帧取头，尾帧取尾。"""
    phases = [part.strip(_PHASE_EDGES) for part in _PHASE_TURN.split(_says_something(expression)) if part.strip(_PHASE_EDGES)]
    return (phases[-1] if frame_state == "end" else phases[0]) if phases else ""


def _people(contract: ShotMotionContract) -> list[str]:
    return [name for name in contract.characters if name.strip() and name not in _NOBODY]


def _named_assets(names: Iterable[str]) -> list[str]:
    return [name for name in names if name.strip() and not name.startswith(_NO_ASSET)]


def _step(text: str, part: str) -> str:
    match = re.search(_STEP.format(part=part), text) if has_structure(text) else None
    return _clip(match.group(1)) if match else ""


def _beat(action: str, frame_state: str) -> tuple[str, list[str]]:
    """这张图画的那一拍，和它后面还没发生、不能提前出现的拍。"""
    beats = [part.strip() for part in str(action or "").split(MERGED_BEATS) if part.strip()] or [""]
    return (beats[-1], []) if frame_state == "end" else (beats[0], beats[1:])


def previous_ending(end_state: str, action: str) -> str:
    """上一格停在了什么样子：结束状态写了姿势就用它，只是固定措辞时用它动作的最后一句。"""
    return concrete_ending(_says_something(end_state)) or concrete_ending(_beat(action, "end")[0])


def _reference_line(references: Sequence[Mapping[str, Any]]) -> str:
    names = []
    for number, item in enumerate(references, 1):
        kind, name, view = str(item.get("kind") or ""), str(item.get("name") or ""), str(item.get("view") or "")
        if kind == "first_frame":
            names.append(_says("ref_first_frame", number=number))
            continue
        if kind == "actor" and view == "face":
            names.append(
                _says("ref_face_real", number=number, name=name) if item.get("real_person") else _says("ref_face", number=number, name=name)
            )
            continue
        # 还没画的造型：这张图还是设定集，不在图名上写造型。
        variant = "" if item.get("look_undrawn") else str(item.get("variant") or "")
        extra = variant or (SCENE_VIEW_LABELS.get(view, "") if view != "scene_main" else "")
        noun = _PICTURE_NOUN.get(kind, _word("picture_default"))
        names.append(_says("ref_picture", number=number, name=name, noun=noun) + (_says("paren", text=extra) if extra else ""))
    return _says("references", names=_LIST.join(names)) if names else _says("no_references")


def _only_gives(references: Sequence[Mapping[str, Any]]) -> str:
    kinds = {str(item.get("kind") or "") for item in references}
    clauses = []
    if "first_frame" in kinds:
        clauses.append(_says("first_frame_gives"))
    if "actor" in kinds:
        clauses.append(_says("actor_gives"))
    real = list(dict.fromkeys(str(item.get("name") or "") for item in references if item.get("real_person")))
    if real:
        clauses.append(real_person.say("panel_line", _LIST.join(_says("quoted", name=name) for name in real)))
    scenes = [item for item in references if item.get("kind") == "scene"]
    main = next((item for item in scenes if not item.get("view")), None)
    if scenes:
        layout = _clip((main or scenes[0]).get("layout"))
        clauses.append(_says("scene_gives", layout=_says("paren", text=layout) if layout else ""))
    for number, item in enumerate(references, 1):
        view = str(item.get("view") or "")
        if view in SCENE_VIEW_PURPOSES and view != "scene_main":
            clauses.append(_says("view_use", number=number, purpose=SCENE_VIEW_PURPOSES[view]))
    clauses.extend(_ONLY_GIVES[kind] for kind in _ONLY_GIVES if kind in kinds)
    return _CLAUSES.join(clauses)


def _costume_notes(people: Sequence[str], references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """每个人物穿什么、以哪张图为准。表演妆造上的造型名写明；旧项目的戏服图优先于定妆照；定妆照上的衣服名也写上，换装造型才不会被认错。"""
    described = {(str(item.get("kind")), str(item.get("name"))): str(item.get("description") or "") for item in assets}
    pictured = {str(item.get("name")): number for number, item in enumerate(references, 1) if item.get("kind") == "actor" and item.get("view") != "face"}
    looks = {str(item.get("name")): str(item.get("variant")) for item in references if item.get("kind") == "actor" and item.get("variant")}
    # 这一场按剧情穿的那身的文字；还没画成定妆图的，衣服只能照文字画。
    limit = prompt_data.number("character_looks", "outfit_limit")
    outfits = {
        str(item.get("name")): _clip(_OUTFIT_BREAKS.sub(_COMMA, str(item.get("outfit"))).strip(_COMMA), limit)
        for item in references if item.get("kind") == "actor" and item.get("variant") and item.get("outfit")
    }
    undrawn = {str(item.get("name")) for item in references if item.get("kind") == "actor" and item.get("variant") and item.get("look_undrawn")}
    added = {str(item.get("name")): _clip(item.get("makeup"), 80) for item in references if item.get("kind") == "actor" and item.get("makeup")}
    # 定妆图上已经画了的妆效：照样写出来，图上画反了左右也按文字。
    drawn = {
        str(item.get("name")): look_makeup_note(_clip(item.get("look_makeup"), 120), panel=True)
        for item in references if item.get("kind") == "actor" and item.get("look_makeup")
    }
    notes: dict[str, str] = {}

    def dressed(person: str) -> str:
        """穿着这一场那身定妆图的人：图号、造型名和衣服的文字。"""
        if person in undrawn:
            return prompt_data.text("character_looks", "panel_look_undrawn").format(person, pictured[person], looks[person], outfits.get(person) or looks[person])
        if person in outfits:
            return prompt_data.text("character_looks", "panel_look_drawn").format(person, pictured[person], looks[person], outfits[person])
        return _says("wears", person=person, number=pictured[person], name=looks[person])

    for person in people:
        # 还没画的造型：旧项目有这身的戏服图就照它，没有就照文字。
        old_costume = person in undrawn and any(
            item.get("kind") == "costume"
            and costume_owner({"name": item.get("name"), "description": described.get(("costume", str(item.get("name"))), "")}, person)
            for item in references
        )
        if person in looks and person in pictured and not old_costume:
            notes[person] = dressed(person) + drawn.get(person, "") + (_says("added_makeup", makeup=added[person]) if person in added else "")
            continue
        if person in added and person in pictured and not old_costume:
            notes[person] = (
                _says("dressed_by_photo", person=person, number=pictured[person]) + drawn.get(person, "") + _says("added_makeup", makeup=added[person])
            )
            continue
        worn = next((
            (number, item) for number, item in enumerate(references, 1) if item.get("kind") == "costume"
            and costume_owner({"name": item.get("name"), "description": described.get(("costume", str(item.get("name"))), "")}, person)
        ), None)
        clothes = _LIST.join(fragment for fragment in parse_face_card(described.get(("actor", person), "")).other if _word("not_given") not in fragment)
        if worn:
            notes[person] = _says("wears", person=person, number=worn[0], name=worn[1].get("name")) + (
                _says("added_makeup", makeup=added[person]) if person in added else ""
            )
        elif person in pictured:
            notes[person] = _says("no_costume", person=person, number=pictured[person]) + (_says("paren", text=_clip(clothes, 60)) if clothes else "")
        elif clothes:
            notes[person] = _says("costume_as_written", person=person, clothes=_clip(clothes, 80))
    return notes


def _hair_line(people: Sequence[str], references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> str:
    described = {str(item.get("name")): str(item.get("description") or "") for item in assets if item.get("kind") == "actor"}
    pictured = {str(item.get("name")): number for number, item in enumerate(references, 1) if item.get("kind") == "actor" and item.get("view") != "face"}
    parts = []
    for person in people:
        hair = _LIST.join(parse_face_card(described.get(person, "")).hair)
        if hair:
            parts.append(f"{person} {_clip(hair, 60)}")
        elif person in pictured:
            parts.append(_says("hair_by_photo", person=person, number=pictured[person]))
    return _CLAUSES.join(parts)


def _written_assets(references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> str:
    """只能靠文字的设定：没有参考图的资产，和场地(批准的布局一张图表达不全)。"""
    shown = {(str(item.get("kind")), str(item.get("name"))) for item in references}
    rows: list[str] = []
    unpictured: list[str] = []
    for item in assets:
        key, text = (str(item.get("kind")), str(item.get("name"))), _clip(item.get("description"), 160)
        if not text:
            continue
        if key[0] == "scene":
            rows.append(_says("scene_setting", name=key[1], text=text))
        elif key[0] == "effect" and key in shown:
            # 特效图只是一个瞬间：形状、颜色和走向照样写出来。
            rows.append(wuxia_vfx.panel_effect_note(key[1], str(item.get("description") or "")))
        elif key not in shown:
            unpictured.append(key[1])
            rows.append(_says("unpictured", name=key[1], text=text))
    if unpictured:
        # 先点名再逐条写：没有图的资产最容易被整件漏画。
        rows.insert(len(rows) - len(unpictured), str(_fixed("unreferenced")["lead"]).format(names=_LIST.join(unpictured)) + _PERIOD)
    return _CLAUSES.join(rows).replace(_PERIOD + _CLAUSES, _PERIOD)


def _mouth_line(contract: ShotMotionContract, people: Sequence[str], frame_state: str) -> str:
    mouth = _fixed("mouth")
    rows = [row.strip() for row in str(contract.dialogue or "").splitlines() if row.strip() not in _NO_LINE]
    if not rows:
        return _says("labelled", label=mouth["label"], text=mouth["silent"])
    match = _SPEAKER.match(rows[-1] if frame_state == "end" else rows[0])
    speaker = match.group(1).strip() if match else (people[0] if len(people) == 1 else "")
    if speaker not in people:
        # 旁白、内心独白和画外音：画里的人不开口。
        return _says("labelled", label=mouth["label"], text=mouth["off_screen"])
    # 一张图画不出一句话：取这句刚说完、嘴合上的那一刻，张嘴吐字留给视频。
    parts = (
        str(mouth["speaker"]).format(speaker=speaker), str(mouth["spoken"]),
        str(mouth["listeners"]) if len(people) > 1 else "", str(mouth["never"]),
    )
    return _says("labelled", label=mouth["label"], text=_CLAUSES.join(part for part in parts if part))


def _same_instance(people: Sequence[str], references: Sequence[Mapping[str, Any]]) -> str:
    """同一性声明：每个人的几张图是他本人，不同的人互不借用。"""
    same = _fixed("same_instance")
    pictured = any(item.get("kind") == "actor" and str(item.get("name")) in people for item in references)
    costumed = any(item.get("kind") == "costume" for item in references)
    parts = (
        str(same["with_costume" if costumed else "looks_only"]) if pictured else "",
        str(same["distinct"]).format(people=_LIST.join(people)) if len(people) > 1 else "",
    )
    return _CLAUSES.join(part for part in parts if part)


def _prop_masters(props: Sequence[str], references: Sequence[Mapping[str, Any]]) -> str:
    """有自己设定图的道具：形制照那张图，这一格只改它的位置。"""
    master = _fixed("prop_master")
    rows = []
    for name in props:
        pictures = [
            str(master["picture"]).format(number=number)
            for number, item in enumerate(references, 1) if item.get("kind") == "prop" and str(item.get("name")) == name
        ]
        if pictures:
            rows.append(str(master["row"]).format(name=name, pictures=_LIST.join(pictures)))
    return _CLAUSES.join(rows)


def _technique(contract: ShotMotionContract, light_position: str) -> str:
    """技法基准：焦段、光圈、光位照表里的写；光比和色温只在表里写了才有，不编造。"""
    technique = _fixed("technique")
    lighting = str(contract.lighting or "")
    found = [re.search(str(technique[key]), lighting) for key in ("ratio", "temperature")]
    parts = (
        str(technique["lens"]).format(lens=contract.lens_mm), str(technique["aperture"]).format(aperture=contract.aperture),
        *(match.group(0).strip() for match in found if match),
        str(technique["light"]).format(light=light_position.removeprefix(_word("main_light_prefix"))) if light_position else "",
    )
    return _CLAUSES.join(part for part in parts if part)


def _contact_line(contract: ShotMotionContract, beat: str, state: str) -> str:
    props = _named_assets(contract.props)
    clauses = [
        clause.strip() for clause in _CLAUSE.findall(beat + _COMMA + state)
        if any(prop in clause for prop in props) or _CONTACT.search(clause)
    ]
    if clauses:
        return _CLAUSES.join(dict.fromkeys(clauses))
    if props:
        return _says("props_carried", props=_LIST.join(props))
    # 没认出接触动作不等于手里没东西(「把公文包放在桌角」)，所以不写「无持有物」。
    return _says("no_extra_holding")


def _light_position(lighting: str) -> str:
    match = _MAIN_LIGHT.search(str(lighting or ""))
    return _clip(match.group(0)) if match else ""


def _three_lights(light_position: str, people: Sequence[str]) -> str:
    """主光用表里写的；补光和轮廓光只说和主光的关系，不编造具体的灯和数值。"""
    key = light_position.removeprefix(_word("main_light_prefix")) or _word("key_default")
    return _says("three_lights", key=key, rim=_says("rim") if people else "")


def _head_count(people: Sequence[str], later_beats: Sequence[str]) -> str:
    if not people:
        return _says("empty_heads")
    # 「人群」「众人」不止一个人，数不出来；后面几拍才入画的人这一拍可以还没出现。
    if any(is_uncast(name) for name in people):
        return ""
    return _says("at_most", count=len(people)) if later_beats else _says("only", count=len(people))


def compile_panel_still(
    contract: ShotMotionContract,
    *,
    references: Sequence[Mapping[str, Any]] = (),
    assets: Sequence[Mapping[str, Any]] = (),
    previous_end: str = "",
    medium: str = "",
    atmosphere: str = "",
    palette: str = "",
    absent: Sequence[str] = (),
    frame_state: Literal["start", "end"] = "start",
) -> CompiledShotPrompt:
    """渲染一格的提示词。``references`` 与发给模型的参考图同序，``assets`` 是本格资产的文字设定。"""
    people = _people(contract)
    beat, later_beats = _beat(contract.subject_action, frame_state)
    event = _step(beat, _word("step_event")) or _clip(beat, 400)
    pose = _step(beat, _word("step_end") if frame_state == "end" else _word("step_start")) or _says_something(
        contract.end_state if frame_state == "end" else contract.start_state
    )
    costume = _costume_notes(people, references, assets)
    light_position = _light_position(contract.lighting)
    palette_lock = _clip(palette, 120)
    props = _named_assets(contract.props)

    if frame_state == "end":
        task = _says("task_end")
    elif contract.shot_id == 1:
        task = _says("task_first")
    else:
        task = _says("task_next")
    handoff = _clip(previous_end, 160) if frame_state == "start" and contract.shot_id != 1 else ""

    def lines(*rows: str) -> str:
        return "\n".join(row for row in rows if row)

    def row(label: str, text: str) -> str:
        return _says("row", label=label, text=text) if text else ""

    acting = _CLAUSES.join(filter(None, (_step(beat, _word("step_body")), _says_something(contract.eyeline))))
    expression = _one_phase(contract.expression, frame_state)
    drafting = lines(
        _reference_line(references),
        _CLAUSES.join(costume.values()) + _PERIOD if costume else "",
        _only_gives(references) + _PERIOD if _only_gives(references) else "",
        _written_assets(references, assets) + _PERIOD if _written_assets(references, assets) else "",
        _same_instance(people, references) + _PERIOD if _same_instance(people, references) else "",
        _says("anchor"),
        task + _NOT_A,
        row(_label("handoff"), handoff),
        event + _PERIOD + (pose + _PERIOD if pose else ""),
        row(_label("effects"), _LIST.join(_named_assets(contract.effects))),
        # 一格只是一个瞬间：首帧画蓄力，尾帧画余波，放出的那一下留给视频。
        row(_label("effect_moment"), wuxia_vfx.panel_effect_beat(_named_assets(contract.effects), frame_state)),
        row(_label("blocking"), _says("blocking", scene=_clip(contract.scene, 80), blocking=_clip(contract.blocking, 400))),
        row(_label("time_light"), _clip(contract.lighting)),
        row(str(_fixed("prop_master")["label"]), _prop_masters(props, references)),
        *(() if not people else (
            row(_label("acting"), acting),
            row(_label("expression"), expression or _says("expression_default")),
            row(_label("hair"), _hair_line(people, references, assets)),
            _mouth_line(contract, people, frame_state) + _PERIOD,
        )),
        row(_label("contact"), _contact_line(contract, beat, pose)),
        row(_label("continuity"), _CLAUSES.join(filter(None, (_says_something(contract.action_axis), _says_something(contract.continuity_in))))),
    )
    grading = lines(
        _three_lights(light_position, people),
        wuxia_vfx.panel_effect_light(_named_assets(contract.effects)) + _PERIOD if _named_assets(contract.effects) else "",
        row(str(_fixed("technique")["label"]), _technique(contract, light_position)),
        row(_label("atmosphere"), _clip(atmosphere, 80)),
        row(_label("medium"), _clip(medium, 700)),
    )
    exclusions = [item for item in (
        *(_says("absent", name=name) for name in absent if name not in people),
        *(_says("not_yet", beat=_step(later, _word("step_event")) or _clip(later, 60)) for later in later_beats),
        # 只有一拍、又是会留下结果的动作(放下、递出、打开)：首帧只画开始那一瞬，结果只在尾帧。
        _says("result_not_yet", beat=_clip(event, 60))
        if frame_state == "start" and not later_beats and _pattern("result_verb").search(event) else "",
        _head_count(people, later_beats),
    ) if item]
    framing = _COMMA.join(filter(None, (
        _clip(contract.shot_size, 40), _clip(contract.camera_angle, 160), f"{contract.lens_mm}mm {contract.aperture}", _clip(contract.composition, 400),
    )))
    locks = _fixed("six_locks")
    carried = "first" if contract.shot_id == 1 else "default"
    edge = lines(
        _says("physics"),
        _says("frame", framing=framing),
        _says("locks", locks=_CLAUSES.join((
            f"{_label('lock_identity')} " + (str(locks["identity"]).format(people=_LIST.join(people)) if people else _word("lock_nobody")),
            f"{_label('lock_wardrobe')} " + (
                str(locks["wardrobe"]).format(wardrobe=_CLAUSES.join(costume.values()) or locks["wardrobe_default"]) if people else _word("lock_none")
            ),
            f"{_label('lock_prop')} " + (str(locks["prop"]).format(props=_LIST.join(props)) if props else _word("lock_none")),
            f"{_label('lock_facing')} {_clip(contract.eyeline, 120) or locks[f'facing_{carried}']}",
            f"{_label('lock_light')} {light_position or locks[f'light_{carried}']}",
            f"{_label('lock_palette')} {palette_lock or locks[f'palette_{carried}']}",
        ))),
        _says("exclusions", exclusions=_CLAUSES.join(exclusions)),
        _CLOSING,
    )
    return CompiledShotPrompt(
        kind="storyboard_image",
        prompt=_says("prompt", drafting=drafting, grading=grading, edge=edge),
        contract_fingerprint=contract.contract_fingerprint,
    )


def medium_line(pack: Any, lighting: str = "", document: str = "") -> str:
    """介质与渲染标准：全片风格锁的原话，这里不另写一套。"""
    return _CLAUSES.join(part for part in (str(document or "").strip(), pack.style_caption, str(lighting or "").strip()) if part)


def atmosphere_line(tone: str) -> str:
    """风格包调性的第一格(类型调性)。后面的节奏、结尾 beat 是说整段视频的，一张图用不上。"""
    return str(tone or "").split("+")[0].strip()


def palette_line(pack: Any) -> str:
    """全片贯穿色：绑在具体物件上，色板才不会漂。风格包没定义时为空。"""
    return _LIST.join(f"{colour.bound_to}{colour.name}{colour.hex}" for colour in pack.palette.through_colours[:4])


__all__ = ["MERGED_BEATS", "atmosphere_line", "compile_panel_still", "medium_line", "palette_line", "previous_ending"]
