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

from app.core import breakdown_kinds
from app.core.action_grammar import concrete_ending, has_structure
from app.core.face_card import parse_face_card
from app.core.scene_turnaround import SCENE_VIEW_LABELS, SCENE_VIEW_PURPOSES
from app.core.shot_motion_contract import CompiledShotPrompt, ShotMotionContract
from app.core.storyboard_scene_context import EMPTY_ACTOR, costume_owner, is_uncast

MERGED_BEATS = "；随后"
_NOBODY = {EMPTY_ACTOR, "无", "无人", "无人物", "空镜", "—", "-"}
_NO_ASSET = ("本格无额外", "本场无额外")
_NO_LINE = {"", "无", "-", "—", "（无）", "(无)"}
_SPEAKER = re.compile(r"^([^：:\n]{1,40})[：:]")
_CONTACT = re.compile(r"握|持|攥|抓|拿|捧|端|扶|按|抱|搭|牵|拽|扣|夹|提着|背着|挎|举|递|接过|抵|放在|放下")
_PHASE_TURN = re.compile(r"→|->|转为|转成|变为|变成|随后|继而|再到")
_CLAUSE = re.compile(r"[^，,。；;！!？?\n]+")
_MAIN_LIGHT = re.compile(r"主光[：:][^；;。]+")
#: 切点规划和分镜表的固定措辞：只说了「要接上」，没说姿势，拿来当姿态写等于没写。
_SAYS_NOTHING = (
    "建立空间与人物关系", "承接上一格最后动作、视线和屏幕方向", "动作停在进行中，留给下一镜完成", "运镜落幅稳住，人物姿态与视线定格在可承接的状态",
    "人物姿态、视线与道具停在下一镜可以直接承接的状态", "形成下一格可承接的可见状态",
    "与本镜触发事件对应的可观察微表情与呼吸变化", "沿场景圣经指定轴线，人物不越180度轴线",
)
_PICTURE_NOUN = {
    "actor": "定妆照", "scene": "场景图", "prop": "道具图", "costume": "服装图", "effect": "特效图", "product": "商品图", **breakdown_kinds.PICTURE_NOUN,
}
_ONLY_GIVES = {
    "prop": "道具图只提供形制、材质与磨损，不提供人物和场景",
    "costume": "服装图只提供款式、面料与颜色，不提供人物和背景",
    "effect": "特效图只提供形态、色彩与强度，不提供人物和场景",
    "product": "商品图只提供外形、材质与颜色，不提供人物和背景",
    **breakdown_kinds.ONLY_GIVES,
}

_CLOSING = (
    "一格只演一个正在进行的可见动作，不演完整场戏。不要身份漂移，不要服装自愈，不要道具自愈，不要越轴，不要文字、字幕与水印，"
    "不要在一张图里同时呈现两拍表情，不要用形容词代替可见事实。禁止宫格、拼贴、分屏、边框与编号，不复制参考图的多视角版式。"
)
_NOT_A = "不是宫格拼版，不是海报，不是资产图，不是概念图。"


def _clip(text: Any, limit: int = 240) -> str:
    body = " ".join(str(text or "").split()).strip("。；;，, ")
    return body if len(body) <= limit else body[: limit - 1].rstrip("，、；;") + "…"


def _says_something(text: Any) -> str:
    body = _clip(text)
    return "" if not body or body in _SAYS_NOTHING or body.startswith("上一镜结束时的人物姿态") else body


def _one_phase(expression: Any, frame_state: str) -> str:
    """表情描述里写了变化(「眉心收紧，转为冷笑」)时只取这一帧的那个阶段：首帧取头，尾帧取尾。"""
    phases = [part.strip("，,；; ") for part in _PHASE_TURN.split(_says_something(expression)) if part.strip("，,；; ")]
    return (phases[-1] if frame_state == "end" else phases[0]) if phases else ""


def _people(contract: ShotMotionContract) -> list[str]:
    return [name for name in contract.characters if name.strip() and name not in _NOBODY]


def _named_assets(names: Iterable[str]) -> list[str]:
    return [name for name in names if name.strip() and not name.startswith(_NO_ASSET)]


def _step(text: str, part: str) -> str:
    match = re.search(rf"{part}[：:]\s*([^\n]+)", text) if has_structure(text) else None
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
            names.append(f"图{number} 本格首帧")
            continue
        extra = str(item.get("variant") or "") or (SCENE_VIEW_LABELS.get(view, "") if view != "scene_main" else "")
        names.append(f"图{number} 「{name}」{_PICTURE_NOUN.get(kind, '参考图')}" + (f"（{extra}）" if extra else ""))
    return f"参考图：{'、'.join(names)}。" if names else "参考图：无，按下面的文字设定生成。"


def _only_gives(references: Sequence[Mapping[str, Any]]) -> str:
    kinds = {str(item.get("kind") or "") for item in references}
    clauses = []
    if "first_frame" in kinds:
        clauses.append("首帧图只提供人物身份、服装、场景和光色，动作与姿态以本格结束状态为准")
    if "actor" in kinds:
        clauses.append("定妆照只提供脸型骨相、五官、发型发色、体型比例与服装，不提供背景、光线、版式和其他人物")
    scenes = [item for item in references if item.get("kind") == "scene"]
    main = next((item for item in scenes if not item.get("view")), None)
    if scenes:
        layout = _clip((main or scenes[0]).get("layout"))
        clauses.append("场景图只提供空间结构、陈设与材质" + (f"（{layout}）" if layout else "") + "，不提供光线、天色和人物，光线以本格为准")
    for number, item in enumerate(references, 1):
        view = str(item.get("view") or "")
        if view in SCENE_VIEW_PURPOSES and view != "scene_main":
            clauses.append(f"图{number} 用于{SCENE_VIEW_PURPOSES[view]}")
    clauses.extend(_ONLY_GIVES[kind] for kind in _ONLY_GIVES if kind in kinds)
    return "；".join(clauses)


def _costume_notes(people: Sequence[str], references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """每个人物穿什么、以哪张图为准。表演妆造上的造型名写明；旧项目的戏服图优先于定妆照；定妆照上的衣服名也写上，换装造型才不会被认错。"""
    described = {(str(item.get("kind")), str(item.get("name"))): str(item.get("description") or "") for item in assets}
    pictured = {str(item.get("name")): number for number, item in enumerate(references, 1) if item.get("kind") == "actor"}
    looks = {str(item.get("name")): str(item.get("variant")) for item in references if item.get("kind") == "actor" and item.get("variant")}
    added = {str(item.get("name")): _clip(item.get("makeup"), 80) for item in references if item.get("kind") == "actor" and item.get("makeup")}
    notes: dict[str, str] = {}
    for person in people:
        if person in added and person in pictured:
            worn = f"穿图{pictured[person]} 的「{looks[person]}」" if person in looks else f"服装以图{pictured[person]} 定妆照为准"
            notes[person] = f"「{person}」{worn}，图上没有的妆效按文字加上：{added[person]}"
            continue
        if person in looks and person in pictured:
            notes[person] = f"「{person}」穿图{pictured[person]} 的「{looks[person]}」"
            continue
        worn = next((
            (number, item) for number, item in enumerate(references, 1) if item.get("kind") == "costume"
            and costume_owner({"name": item.get("name"), "description": described.get(("costume", str(item.get("name"))), "")}, person)
        ), None)
        clothes = "、".join(fragment for fragment in parse_face_card(described.get(("actor", person), "")).other if "未提供" not in fragment)
        if worn:
            notes[person] = f"「{person}」穿图{worn[0]} 的「{worn[1].get('name')}」"
        elif person in pictured:
            notes[person] = f"「{person}」本格没有单独戏服，服装以图{pictured[person]} 定妆照为准" + (f"（{_clip(clothes, 60)}）" if clothes else "")
        elif clothes:
            notes[person] = f"「{person}」服装按设定：{_clip(clothes, 80)}"
    return notes


def _hair_line(people: Sequence[str], references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> str:
    described = {str(item.get("name")): str(item.get("description") or "") for item in assets if item.get("kind") == "actor"}
    pictured = {str(item.get("name")): number for number, item in enumerate(references, 1) if item.get("kind") == "actor"}
    parts = []
    for person in people:
        hair = "、".join(parse_face_card(described.get(person, "")).hair)
        if hair:
            parts.append(f"{person} {_clip(hair, 60)}")
        elif person in pictured:
            parts.append(f"{person} 以图{pictured[person]} 定妆照为准")
    return "；".join(parts)


def _written_assets(references: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]) -> str:
    """只能靠文字的设定：没有参考图的资产，和场地(批准的布局一张图表达不全)。"""
    shown = {(str(item.get("kind")), str(item.get("name"))) for item in references}
    rows = []
    for item in assets:
        key, text = (str(item.get("kind")), str(item.get("name"))), _clip(item.get("description"), 160)
        if not text:
            continue
        if key[0] == "scene":
            rows.append(f"「{key[1]}」设定：{text}")
        elif key not in shown:
            rows.append(f"「{key[1]}」没有参考图，按设定：{text}")
    return "；".join(rows)


def _mouth_line(contract: ShotMotionContract, people: Sequence[str], frame_state: str) -> str:
    rows = [row.strip() for row in str(contract.dialogue or "").splitlines() if row.strip() not in _NO_LINE]
    if not rows:
        return "口型：闭口，不说话"
    match = _SPEAKER.match(rows[-1] if frame_state == "end" else rows[0])
    speaker = match.group(1).strip() if match else (people[0] if len(people) == 1 else "")
    if speaker not in people:
        # 旁白、内心独白和画外音：画里的人不开口。
        return "口型：画内人物闭口，不说话"
    others = "，其他人物闭口" if len(people) > 1 else ""
    return f"口型：「{speaker}」正在说话，嘴唇微张{others}"


def _contact_line(contract: ShotMotionContract, beat: str, state: str) -> str:
    props = _named_assets(contract.props)
    clauses = [
        clause.strip() for clause in _CLAUSE.findall(f"{beat}，{state}")
        if any(prop in clause for prop in props) or _CONTACT.search(clause)
    ]
    if clauses:
        return "；".join(dict.fromkeys(clauses))
    if props:
        return f"{'、'.join(props)}的位置与归属沿用上一格，不换手"
    # 没认出接触动作不等于手里没东西(「把公文包放在桌角」)，所以不写「无持有物」。
    return "不额外添加手持物"


def _light_position(lighting: str) -> str:
    match = _MAIN_LIGHT.search(str(lighting or ""))
    return _clip(match.group(0)) if match else ""


def _three_lights(light_position: str, people: Sequence[str]) -> str:
    """主光用表里写的；补光和轮廓光只说和主光的关系，不编造具体的灯和数值。"""
    key = light_position.removeprefix("主光：") or "沿用本场建立镜"
    rim = "；轮廓光（rim）在主光对侧，勾出人物边缘，把人物和背景分开" if people else ""
    return f"三灯布光：主光（key）{key}；补光（fill）压低，暗部留细节不发灰{rim}。光质、光比、色温沿用本场建立镜，不临场改变。"


def _head_count(people: Sequence[str], later_beats: Sequence[str]) -> str:
    if not people:
        return "空镜，不生成面孔、肢体或人物服装"
    # 「人群」「众人」不止一个人，数不出来；后面几拍才入画的人这一拍可以还没出现。
    if any(is_uncast(name) for name in people):
        return ""
    return f"画面中最多{len(people)}个人物" if later_beats else f"画面中只保留{len(people)}个人物"


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
    event = _step(beat, "主动作") or _clip(beat, 400)
    pose = _step(beat, "结束姿态" if frame_state == "end" else "起始姿态") or _says_something(
        contract.end_state if frame_state == "end" else contract.start_state
    )
    costume = _costume_notes(people, references, assets)
    light_position = _light_position(contract.lighting)
    palette_lock = _clip(palette, 120) or "沿用本场建立镜"
    props = _named_assets(contract.props)

    if frame_state == "end":
        task = "生成这一格的结束画面，供视频模型作尾帧，动作已经停稳；单帧、独立、完整。"
    elif contract.shot_id == 1:
        task = "生成一格分镜示例图，供视频模型据此接拍，这是本场第一格，建立空间与人物关系；单帧、独立、完整。"
    else:
        task = "生成一格分镜示例图，供视频模型据此接拍，承接上一格的结束状态；单帧、独立、完整。"
    handoff = _clip(previous_end, 160) if frame_state == "start" and contract.shot_id != 1 else ""

    def lines(*rows: str) -> str:
        return "\n".join(row for row in rows if row)

    def row(label: str, text: str) -> str:
        return f"{label}：{text}。" if text else ""

    acting = "；".join(filter(None, (_step(beat, "身体联动"), _says_something(contract.eyeline))))
    expression = _one_phase(contract.expression, frame_state)
    drafting = lines(
        _reference_line(references),
        "；".join(costume.values()) + "。" if costume else "",
        _only_gives(references) + "。" if _only_gives(references) else "",
        _written_assets(references, assets) + "。" if _written_assets(references, assets) else "",
        f"{'、'.join(people)}是不同的角色，脸和服装都不互相借用。" if len(people) > 1 else "",
        "锚续：身份、服装、道具、朝向、光位、色板六项跨格不变。",
        task + _NOT_A,
        row("上一格结束状态", handoff),
        f"{event}。" + (f"{pose}。" if pose else ""),
        row("特效", "、".join(_named_assets(contract.effects))),
        row("调度", f"地点{_clip(contract.scene, 80)}；{_clip(contract.blocking, 400)}"),
        row("时段与光线", _clip(contract.lighting)),
        *(() if not people else (
            row("表演", acting),
            row("表情定格", expression or "只取这一拍正在发生的一个表情阶段，不叠加前后情绪"),
            row("发型", _hair_line(people, references, assets)),
            _mouth_line(contract, people, frame_state) + "。",
        )),
        row("持有物与接触点", _contact_line(contract, beat, pose)),
        row("同场戏跨镜头一致", "；".join(filter(None, (_says_something(contract.action_axis), _says_something(contract.continuity_in))))),
    )
    grading = lines(
        _three_lights(light_position, people),
        row("氛围", _clip(atmosphere, 80)),
        row("介质与渲染标准", _clip(medium, 700)),
    )
    exclusions = [item for item in (
        *(f"不出现{name}" for name in absent if name not in people),
        *(f"不提前呈现：{_step(later, '主动作') or _clip(later, 60)}" for later in later_beats),
        _head_count(people, later_beats),
    ) if item]
    framing = "，".join(filter(None, (
        _clip(contract.shot_size, 40), _clip(contract.camera_angle, 160), f"{contract.lens_mm}mm {contract.aperture}", _clip(contract.composition, 400),
    )))
    edge = lines(
        "物理优先：刚体保形，绳链受重下垂，不为对齐参考图违背重力。",
        f"画幅 9:16，二K 交付档，四边留安全区，主体不贴边不裁切。{framing}。",
        "本格结束状态六锁：" + "；".join((
            f"身份 {'、'.join(people) or '空镜，无人物'}",
            f"服装 {'；'.join(costume.values()) or '无'}",
            f"道具 {'、'.join(props) or '无'}",
            f"朝向 {_clip(contract.eyeline, 120) or '沿用上一格'}",
            f"光位 {light_position or '沿用本场建立镜'}",
            f"色板 {palette_lock}",
        )) + "。",
        f"本拍排除：{'；'.join(exclusions)}。",
        _CLOSING,
    )
    return CompiledShotPrompt(
        kind="storyboard_image",
        prompt=f"【落笔】\n{drafting}\n【调色】\n{grading}\n【收边】\n{edge}",
        contract_fingerprint=contract.contract_fingerprint,
    )


def medium_line(pack: Any, lighting: str = "", document: str = "") -> str:
    """介质与渲染标准：全片风格锁的原话，这里不另写一套。"""
    return "；".join(part for part in (str(document or "").strip(), pack.style_caption, str(lighting or "").strip()) if part)


def atmosphere_line(tone: str) -> str:
    """风格包调性的第一格(类型调性)。后面的节奏、结尾 beat 是说整段视频的，一张图用不上。"""
    return str(tone or "").split("+")[0].strip()


def palette_line(pack: Any) -> str:
    """全片贯穿色：绑在具体物件上，色板才不会漂。风格包没定义时为空。"""
    return "、".join(f"{colour.bound_to}{colour.name}{colour.hex}" for colour in pack.palette.through_colours[:4])


__all__ = ["MERGED_BEATS", "atmosphere_line", "compile_panel_still", "medium_line", "palette_line", "previous_ending"]
