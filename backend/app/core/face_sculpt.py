# -*- coding: utf-8 -*-
"""捏脸与捏表情：把一个角色的长相和表情习惯，用一组固定控件捏出来，存进这个角色的统一资产。

为什么不另起一套资产：设定集、分镜、视频提示词读的都是第 3 阶段角色记录里的那一段描述
(``assets["3_characters"][i]["desc"]``)，再由 ``face_card`` 拆成「身份锚点 / 骨相 / 五官 / 皮肤 / 毛发 / 体态」
六层。捏脸只改这段描述里被捏到的那几层，所以宫殿、街道、书房，第一集到第三十集，每一镜拿到的都是同一张脸，
不需要任何一个提示词构建器认识「捏脸」。

改法(``merge_description``)：
1. 描述开头的称呼段(「女主角/佩剑者」)原样留在最前——``cast_aliases`` 靠它认人。
2. 捏出来的各层紧跟在称呼段后面，带层名写：设定集截断描述时先丢的是后面的服装与风格，不是锁脸的词。
3. 原描述里和某个已选控件说同一件事的片段(同一层、含该控件 ``replaces`` 里的词)删掉；其余一字不动。

每次保存都从第一次捏脸前的描述(``desc_before``)重新合成，捏多少次都不会层层加码；重置就是把它放回去。

捏表情给每个情绪一组「这个人怎么笑、怎么哭」的写法。情绪词与 ``emotion_table`` 同一套：第 5 阶段读出
某个人这一镜的情绪后，把他自己的那一条加进表情描述，不再只有通用的「眼角弯起、嘴角上扬」。

控件、选项、短语和措辞都在 ``app/data/prompt/face_sculpt.json``，这里只有结构和逻辑。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core import prompt_data
from app.core.emotion_table import read_emotion
from app.core.face_card import (
    FACE_LAYERS,
    NEGATIVE_LABEL,
    STATE_LAYER_FIELDS,
    audit_face_card,
    parse_face_card,
    render_face_card,
)
from app.core.screenwriting.structured_llm import extract_json_object

_DATA = "face_sculpt"
RECORD_KEY = "face_sculpt"
# 角色记录上记「现有设定集画的是哪段描述」的键：{"sheet": 地址, "desc_hash": 描述指纹}。它跟着设定集走、不跟着捏脸走，
# 所以重置捏脸(去掉 RECORD_KEY)之后仍知道那张画的是不是现在这张脸。
SHEET_KEY = "sheet_drawn_from"
SCALE_RANGE = (-2, 2)
# 撤销历史只留最近几步：每一步都是一整份捏脸，存多了角色记录会胖起来。步数在 face_sculpt.json 的 limits 里。
HISTORY_LIMIT = int(prompt_data.load(_DATA)["limits"]["history_limit"])
# 文本模型调用：(system, user, max_tokens) → 回答；离线模板的回答按没有算(None)。
LLM = Callable[[str, str, int], "str | None"]

_SEGMENT = re.compile(r"([；;。\n]+)")
_FRAGMENT = re.compile(r"([，,、]+)")
_NEGATION = re.compile(r"^(不要|避免|禁止|切勿|不能|不得)")
_LAYER_LABELS = {key: label for key, label in FACE_LAYERS}
_LABEL_LAYERS = {label: key for key, label in FACE_LAYERS}
# 状态卡字段 → 资产卡层(状态卡里体态叫 body)。
_STATE_FIELD_LAYER = {"bone": "bone", "features": "features", "skin": "skin", "hair": "hair", "body": "physique"}
# cast_aliases 只认 40 字以内的开头段；同一条规则决定哪段算称呼。
_HEAD_LIMIT = 40


class SculptError(ValueError):
    """捏脸数据不合法：说清是哪个控件、哪个值。"""


# ---------------------------------------------------------------------------- catalog


@dataclass(frozen=True)
class Control:
    key: str
    layer: str
    label: str
    kind: str                       # "choice" | "scale"
    options: tuple[tuple[str, str, str], ...]   # (value, label, phrase) for choice
    steps: tuple[str, ...]          # 5 phrases for scale, index = offset + 2
    replaces: tuple[str, ...]

    def phrase(self, value: Any) -> str:
        if self.kind == "scale":
            return self.steps[int(value) - SCALE_RANGE[0]]
        return next(phrase for option, _label, phrase in self.options if option == value)


@dataclass(frozen=True)
class Catalog:
    controls: tuple[Control, ...]
    presets: Mapping[str, Mapping[str, Any]]
    preset_labels: Mapping[str, str]
    expression_controls: Mapping[str, tuple[tuple[str, str, str], ...]]
    expression_control_labels: Mapping[str, str]
    expressions: tuple[tuple[str, str, tuple[str, ...]], ...]   # (key, label, words)
    limits: Mapping[str, int]
    wording: Mapping[str, Any]

    def control(self, key: str) -> Control:
        for control in self.controls:
            if control.key == key:
                return control
        raise SculptError(f"没有这个捏脸控件：{key}")

    def expression_label(self, key: str) -> str:
        return next((label for item, label, _words in self.expressions if item == key), key)


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    data = prompt_data.load(_DATA)
    layers = {item["key"] for item in data["layers"]}
    controls: list[Control] = []
    for raw in data["controls"]:
        if raw["layer"] not in layers:
            raise SculptError(f"控件 {raw['key']} 的层 {raw['layer']} 不存在")
        steps = tuple(raw.get("steps") or ())
        if raw["type"] == "scale" and len(steps) != SCALE_RANGE[1] - SCALE_RANGE[0] + 1:
            raise SculptError(f"刻度控件 {raw['key']} 必须有 5 档")
        controls.append(Control(
            key=raw["key"], layer=raw["layer"], label=raw["label"], kind=raw["type"],
            options=tuple((item["value"], item["label"], item["phrase"]) for item in raw.get("options") or ()),
            steps=steps, replaces=tuple(raw.get("replaces") or ()),
        ))
    expression_controls = {
        item["key"]: tuple((option["value"], option["label"], option["phrase"]) for option in item["options"])
        for item in data["expression_controls"]
    }
    return Catalog(
        controls=tuple(controls),
        presets={item["key"]: item["values"] for item in data["presets"]},
        preset_labels={item["key"]: item["label"] for item in data["presets"]},
        expression_controls=expression_controls,
        expression_control_labels={item["key"]: item["label"] for item in data["expression_controls"]},
        expressions=tuple((item["key"], item["label"], tuple(item["words"])) for item in data["expressions"]),
        limits=data["limits"],
        wording=data["wording"],
    )


def describe_catalog() -> dict[str, Any]:
    """前端要的控件表：分层的捏脸控件、预设、表情控件与情绪清单。"""
    cat = catalog()
    data = prompt_data.load(_DATA)
    return {
        "layers": [{"key": item["key"], "label": item["label"]} for item in data["layers"]],
        "controls": [
            {
                "key": control.key, "layer": control.layer, "label": control.label, "type": control.kind,
                **({"options": [{"value": value, "label": label} for value, label, _phrase in control.options]}
                   if control.kind == "choice" else {"steps": list(control.steps)}),
            }
            for control in cat.controls
        ],
        "presets": [{"key": key, "label": cat.preset_labels[key], "values": dict(values)} for key, values in cat.presets.items()],
        "expression_controls": [
            {"key": key, "label": cat.expression_control_labels[key],
             "options": [{"value": value, "label": label} for value, label, _phrase in options]}
            for key, options in cat.expression_controls.items()
        ],
        "expressions": [{"key": key, "label": label, "words": list(words)} for key, label, words in cat.expressions],
        "limits": dict(cat.limits),
    }


# ---------------------------------------------------------------------------- validation


@dataclass(frozen=True)
class Expression:
    choices: Mapping[str, str]      # expression control key → option value
    tell: str = ""                  # 这个人独有的面部特征(哭时鼻尖先红)
    habit: str = ""                 # 习惯小动作(笑前先低头)

    @property
    def empty(self) -> bool:
        return not self.choices and not self.tell and not self.habit


@dataclass(frozen=True)
class Sculpt:
    face: Mapping[str, Any]
    notes: Mapping[str, str]
    expressions: Mapping[str, Expression]
    preset: str = ""

    @property
    def empty(self) -> bool:
        return not self.face and not any(self.notes.values()) and not self.expressions

    def dump(self) -> dict[str, Any]:
        return {
            "face": dict(self.face),
            "notes": {key: value for key, value in self.notes.items() if value},
            "expressions": {
                key: {"choices": dict(item.choices), "tell": item.tell, "habit": item.habit}
                for key, item in self.expressions.items()
            },
            "preset": self.preset,
        }


def _normalise_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # 段分隔和层名冒号会被资产卡当成新的一层，捏的备注里一律换成逗号。
    return re.sub(r"[；;。\n:：]+", "，", text).strip("，, ")


def _clean_text(value: Any, limit: int, what: str) -> str:
    text = _normalise_text(value)
    if len(text) > limit:
        raise SculptError(f"{what}最多 {limit} 个字")
    return text


def _clip_text(value: Any, limit: int) -> str:
    """模型写长了就截到上限，不为此整句失败。"""
    return _normalise_text(value)[:limit].strip("，, ")


def validate(raw: Mapping[str, Any] | None) -> Sculpt:
    """把前端发来的捏脸数据核成一份干净的 Sculpt；不认识的控件或选项直接报错，不悄悄丢掉。"""
    raw = raw or {}
    cat = catalog()
    face: dict[str, Any] = {}
    for key, value in (raw.get("face") or {}).items():
        if value in (None, "", 0) and cat.control(key).kind == "scale":
            continue
        if value in (None, ""):
            continue
        control = cat.control(key)
        if control.kind == "scale":
            if isinstance(value, bool) or not isinstance(value, int) or not SCALE_RANGE[0] <= value <= SCALE_RANGE[1]:
                raise SculptError(f"「{control.label}」的刻度只能是 -2 到 2")
        elif value not in {option for option, _label, _phrase in control.options}:
            raise SculptError(f"「{control.label}」没有选项 {value}")
        face[key] = value
    layers = {key for key, _label in FACE_LAYERS}
    notes: dict[str, str] = {}
    for key, value in (raw.get("notes") or {}).items():
        if key not in layers:
            raise SculptError(f"没有这一层：{key}")
        text = _clean_text(value, cat.limits["note_chars"], f"「{_LAYER_LABELS[key]}」的补充")
        if text:
            notes[key] = text
    expressions: dict[str, Expression] = {}
    known = {key for key, _label, _words in cat.expressions}
    for key, item in (raw.get("expressions") or {}).items():
        if key not in known:
            raise SculptError(f"没有这个表情：{key}")
        item = item or {}
        choices: dict[str, str] = {}
        for control_key, value in (item.get("choices") or {}).items():
            options = cat.expression_controls.get(control_key)
            if options is None:
                raise SculptError(f"没有这个表情控件：{control_key}")
            if value in (None, ""):
                continue
            if value not in {option for option, _label, _phrase in options}:
                raise SculptError(f"表情「{cat.expression_label(key)}」的{cat.expression_control_labels[control_key]}没有选项 {value}")
            choices[control_key] = value
        label = cat.expression_label(key)
        expression = Expression(
            choices=choices,
            tell=_clean_text(item.get("tell"), cat.limits["tell_chars"], f"表情「{label}」的面部特征"),
            habit=_clean_text(item.get("habit"), cat.limits["habit_chars"], f"表情「{label}」的小动作"),
        )
        if not expression.empty:
            expressions[key] = expression
    preset = str(raw.get("preset") or "")
    if preset and preset not in cat.presets:
        raise SculptError(f"没有这个预设：{preset}")
    return Sculpt(face=face, notes=notes, expressions=expressions, preset=preset)


def preset_sculpt(key: str) -> Sculpt:
    cat = catalog()
    if key not in cat.presets:
        raise SculptError(f"没有这个预设：{key}")
    return validate({"face": cat.presets[key], "preset": key})


# ---------------------------------------------------------------------------- face layers


def layer_fragments(sculpt: Sculpt) -> dict[str, list[str]]:
    """每一层捏出来的片段，按控件表顺序；补充备注跟在该层最后。否定说法单独归到 negatives。"""
    cat = catalog()
    layers: dict[str, list[str]] = {}
    for control in cat.controls:
        if control.key in sculpt.face:
            phrase = control.phrase(sculpt.face[control.key])
            if phrase:
                layers.setdefault(control.layer, []).extend(part for part in _FRAGMENT.split(phrase)[::2] if part.strip())
    for key, note in sculpt.notes.items():
        for fragment in _FRAGMENT.split(note)[::2]:
            fragment = fragment.strip()
            if fragment:
                layers.setdefault("negatives" if _NEGATION.match(fragment) else key, []).append(fragment)
    return {key: list(dict.fromkeys(values)) for key, values in layers.items() if values}


def _replaced_words(sculpt: Sculpt) -> dict[str, tuple[str, ...]]:
    """每一层里，已选控件要替换掉的原描述词。"""
    words: dict[str, list[str]] = {}
    for control in catalog().controls:
        if control.key in sculpt.face and control.phrase(sculpt.face[control.key]):
            words.setdefault(control.layer, []).extend(control.replaces)
    return {key: tuple(values) for key, values in words.items()}


def _fragment_layer(fragment: str, forced: str | None) -> str:
    if forced:
        return forced
    card = parse_face_card(fragment)
    return next((key for key, _label in FACE_LAYERS if card.layer(key)), "other")


def _strip_replaced(text: str, replaced: Mapping[str, tuple[str, ...]]) -> str:
    """原描述里被这次捏脸替换掉的片段删掉，其余字符(含原来的标点)一个不动。"""
    if not replaced:
        return text
    out: list[str] = []
    pieces = _SEGMENT.split(text)
    for index in range(0, len(pieces), 2):
        segment = pieces[index]
        separator = pieces[index + 1] if index + 1 < len(pieces) else ""
        label, colon, rest = segment.partition("：")
        forced = _LABEL_LAYERS.get(label.strip()) if colon else None
        body = rest if forced else segment
        parts = _FRAGMENT.split(body)
        kept: list[str] = []
        for part_index in range(0, len(parts), 2):
            fragment = parts[part_index]
            layer = _fragment_layer(fragment.strip(), forced)
            # 资产卡认不出层的片段(「视觉年龄22–26」)也可能和捏出的某层说同一件事：用两字以上的替换词再对一遍。
            words = replaced.get(layer, ()) if layer != "other" else tuple(
                word for values in replaced.values() for word in values if len(word) >= 2
            )
            if fragment.strip() and any(word in fragment for word in words):
                continue
            if kept and part_index:
                kept.append(parts[part_index - 1])
            kept.append(fragment)
        body = "".join(kept).strip("，,、 ")
        if body:
            out.append(f"{label}：{body}" if forced else body)
            out.append(separator)
    return "".join(out).strip("；;。\n ")


def _split_head(desc: str) -> tuple[str, str]:
    """描述开头的称呼段(cast_aliases 认人用的那段)和其余部分。称呼段里没有长相词时才算。"""
    head, separator, rest = desc.partition(next((ch for ch in desc if ch in "；;。\n"), "\0"))
    if not separator or len(head.strip()) > _HEAD_LIMIT:
        return "", desc
    card = parse_face_card(head)
    if card.has_face_layers and not card.identity:
        return "", desc
    return head.strip(), rest


def _sculpt_segments(fragments: Mapping[str, list[str]]) -> list[str]:
    segments = [f"{label}：{'、'.join(fragments[key])}" for key, label in FACE_LAYERS if fragments.get(key)]
    if fragments.get("negatives"):
        segments.append(f"{NEGATIVE_LABEL}：{'、'.join(fragments['negatives'])}")
    return segments


def merge_description(base: str, sculpt: Sculpt) -> str:
    """捏脸写进一段角色描述：称呼段 → 捏出的各层 → 原描述里没被替换的部分。"""
    base = str(base or "").strip()
    fragments = layer_fragments(sculpt)
    if not fragments:
        return base
    head, rest = _split_head(base)
    kept = _strip_replaced(rest, _replaced_words(sculpt))
    return "；".join(part for part in (head, *_sculpt_segments(fragments), kept) if part)


def merge_state_fields(state: Mapping[str, Any], sculpt: Sculpt) -> dict[str, str]:
    """第 3 阶段某个造型状态的分层字段(骨相 / 五官 / 皮肤 / 毛发 / 体型)按同一规则合成；只返回被捏到的字段。"""
    fragments = layer_fragments(sculpt)
    replaced = _replaced_words(sculpt)
    merged: dict[str, str] = {}
    for field, _label in STATE_LAYER_FIELDS:
        layer = _STATE_FIELD_LAYER[field]
        if not fragments.get(layer):
            continue
        original = str(state.get(field) or "").strip()
        kept = [part.strip() for part in _FRAGMENT.split(original)[::2] if part.strip()]
        kept = [part for part in kept if not any(word in part for word in replaced.get(layer, ()))]
        merged[field] = "、".join(dict.fromkeys([*fragments[layer], *kept]))
    return merged


# ---------------------------------------------------------------------------- expressions


def expression_phrases(expression: Expression) -> list[str]:
    cat = catalog()
    phrases = [
        phrase
        for control_key, options in cat.expression_controls.items()
        if (value := expression.choices.get(control_key))
        for option, _label, phrase in options
        if option == value and phrase
    ]
    return [*phrases, *(text for text in (expression.tell, expression.habit) if text)]


def expression_line(name: str, key: str, expression: Expression) -> str:
    phrases = expression_phrases(expression)
    if not phrases:
        return ""
    cat = catalog()
    return cat.wording["expression_line"].format(name=name, label=cat.expression_label(key), phrases="，".join(phrases))


def expression_key_for(word: str) -> str | None:
    """emotion_table 读出的情绪词 → 表情键；读不出情绪时没有。"""
    if not word:
        return None
    return next((key for key, _label, words in catalog().expressions if word in words), None)


def stored_sculpt(record: Mapping[str, Any] | None) -> Sculpt | None:
    """角色记录里存着的捏脸；坏数据当作没有，不让一镜的提示词因此失败。"""
    stored = (record or {}).get(RECORD_KEY)
    if not isinstance(stored, Mapping):
        return None
    try:
        return validate(stored)
    except SculptError:
        return None


def shot_expression_lines(
    records: Iterable[Mapping[str, Any]],
    names: Sequence[str],
    deliveries: Sequence[tuple[str, str]],
    shot_word: str = "",
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    """这一镜里每个捏过表情的人，按他自己这一镜的情绪给出他的表情写法。

    一个人的情绪先看他自己的台词表演标注(``deliveries`` 里的 (说话人, 标注))；这一镜只有一个人时，
    整镜读出的情绪也算他的。两人同框又都没有自己的标注，就不猜。
    """
    aliases = aliases or {}
    by_name = {
        str(record.get("name") or "").strip(): record
        for record in records if isinstance(record, Mapping) and str(record.get("name") or "").strip()
    }
    own: dict[str, str] = {}
    for speaker, delivery in deliveries:
        speaker = aliases.get(str(speaker).strip(), str(speaker).strip())
        reading = read_emotion(delivery)
        if reading.matched and speaker not in own:
            own[speaker] = reading.matched
    present = list(dict.fromkeys(aliases.get(name, name) for name in names if name))
    lines: list[str] = []
    for name in present:
        sculpt = stored_sculpt(by_name.get(name))
        if sculpt is None or not sculpt.expressions:
            continue
        word = own.get(name) or (shot_word if len(present) == 1 else "")
        key = expression_key_for(word)
        expression = sculpt.expressions.get(key) if key else None
        line = expression_line(name, key, expression) if expression else ""
        if line:
            lines.append(line)
    return lines


def shot_expression_note(lines: Sequence[str]) -> str:
    return f"{catalog().wording['shot_expression_head']}{'；'.join(lines)}" if lines else ""


# ---------------------------------------------------------------------------- preview and task edits


def record_of(task: Mapping[str, Any], name: str) -> dict[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    for item in assets.get("3_characters") or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
            return item
    raise LookupError(f"项目里没有角色「{name}」")


def _dna_states(task: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    dna = (task.get("assets") or {}).get("3_dna")
    for item in (dna.get("characters") or []) if isinstance(dna, dict) else []:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
            return [state for state in item.get("states") or [] if isinstance(state, dict)]
    return []


def _base_description(record: Mapping[str, Any]) -> str:
    stored = record.get(RECORD_KEY)
    if isinstance(stored, Mapping) and "desc_before" in stored:
        return str(stored.get("desc_before") or "")
    return str(record.get("desc") or record.get("description") or "")


def _sheet_of(record: Mapping[str, Any], task: Mapping[str, Any] | None) -> str:
    """这个角色现在的设定集地址：角色记录自己带的，或第 3 阶段 ``assets["3_sheets"][name]`` 里的。"""
    if record.get("sheet"):
        return str(record["sheet"])
    assets = task.get("assets") if isinstance(task, Mapping) and isinstance(task.get("assets"), Mapping) else {}
    sheets = assets.get("3_sheets") if isinstance(assets.get("3_sheets"), Mapping) else {}
    item = sheets.get(str(record.get("name") or "").strip())
    if isinstance(item, Mapping):
        item = item.get("url") or item.get("image_url") or ""
    return str(item or "")


def _desc(record: Mapping[str, Any]) -> str:
    return str(record.get("desc") or record.get("description") or "")


def _desc_hash(desc: str) -> str:
    """描述的短指纹：只用来比「设定集画的是不是这段」，不在记录里再存一遍整段。"""
    return hashlib.sha1(re.sub(r"\s+", " ", str(desc or "")).strip().encode("utf-8")).hexdigest()[:16]


def note_sheet_drawn(record: dict[str, Any], sheet: str, desc: str) -> None:
    """记下这张设定集画的是哪段描述。出图的那一步(第 3 阶段 / 单人重出)拿到地址时调用最准；
    没调用的，捏脸这边下次改描述前按「地址变了就是按当时的描述重出的」补记(``_note_sheet``)。"""
    if sheet:
        record[SHEET_KEY] = {"sheet": str(sheet), "desc_hash": _desc_hash(desc)}


def _note_sheet(record: dict[str, Any], task: Mapping[str, Any] | None) -> None:
    """改描述之前先对账：现有设定集没记过、或地址和记下的不同(重出过)，就当它画的是现在这段描述。

    只在捏脸里记过「脸动时的设定集地址」(``sheet_at_save``)的旧记录：地址没变，说明那张画的还是捏脸前的描述。
    """
    sheet = _sheet_of(record, task)
    marker = record.get(SHEET_KEY) if isinstance(record.get(SHEET_KEY), Mapping) else {}
    if not sheet or marker.get("sheet") == sheet:
        return
    stored = record.get(RECORD_KEY)
    legacy = isinstance(stored, Mapping) and bool(stored.get("revision")) and sheet == stored.get("sheet_at_save")
    note_sheet_drawn(record, sheet, _base_description(record) if legacy else _desc(record))


def sheet_is_stale(record: Mapping[str, Any], task: Mapping[str, Any] | None = None) -> bool:
    """现有设定集画的是不是现在这张脸：记下的那张还在、而描述已不是画它时那段，就是旧脸——脸捏过去或放回来都一样。

    地址和记下的不同就是重出过(重出用的是当时的描述)，算新的；没记过的旧记录退回「脸动过而设定集地址没变」。
    """
    sheet = _sheet_of(record, task)
    if not sheet:
        return False
    marker = record.get(SHEET_KEY)
    if isinstance(marker, Mapping) and marker.get("sheet"):
        return str(marker["sheet"]) == sheet and str(marker.get("desc_hash") or "") != _desc_hash(_desc(record))
    stored = record.get(RECORD_KEY)
    return isinstance(stored, Mapping) and bool(stored.get("revision")) and sheet == stored.get("sheet_at_save")


def _split_names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[、，,/]", value)
    return [str(item).strip() for item in (value or []) if str(item or "").strip()] if isinstance(value, list) else []


def _character_names(task: Mapping[str, Any], record: Mapping[str, Any]) -> set[str]:
    """分镜表里可能用来叫这个人的名字：演员名、记录里的第一个别名，以及称呼表里只指向他的称呼。"""
    from app.core.storyboard_scene_context import cast_aliases

    name = str(record.get("name") or "").strip()
    names = {name, *_split_names(record.get("aliases"))[:1]}
    names.update(title for title, owner in cast_aliases(task).items() if owner == name)
    names.discard("")
    return names


def mark_character_clips_stale(task: Mapping[str, Any], name: str, reason: str) -> int:
    """这个人出镜的镜头所在的第 5 阶段片段全部标成待重做：脸改了，旧片段里还是旧脸。

    和 stage_director_ops.mark_scene_clips_stale 同一条对法：带场号或镜头编号表的片段按覆盖的镜头编号对 ``assets["4"]``
    里点到他的镜头，没有场号的旧片段按镜号对；同一镜有几段(分镜片段视频旁边还有单镜重拍)就标几段，不只标找到的第一段。
    不动第 4 阶段的图；返回标了几段。
    """
    from app.core import episode_cycle

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    clips = assets.get("5") if isinstance(assets.get("5"), list) else []
    shots = assets.get("4") if isinstance(assets.get("4"), list) else []
    if not clips or not shots:
        return 0
    try:
        names = _character_names(task, record_of(task, name))
    except LookupError:
        names = {str(name or "").strip()} - {""}
    named = [shot for shot in shots if isinstance(shot, Mapping) and not names.isdisjoint(_split_names(shot.get("characters")))]
    uids = {episode_cycle.shot_uid(shot) for shot in named}
    legacy_ids = {str(shot["shot_id"]) for shot in named if shot.get("shot_id") not in (None, "")}
    marked = 0
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        if clip.get("scene_id") or clip.get("shot_uids"):
            hit = not uids.isdisjoint(episode_cycle.covered_uids(clip))
        else:
            hit = str(clip.get("shot_id")) in legacy_ids
        if hit:
            clip["stale"] = True
            clip["stale_reason"] = reason
            marked += 1
    return marked


def _downstream(task: Mapping[str, Any], record: Mapping[str, Any], face_changed: bool) -> dict[str, Any]:
    """这次改动牵连到的下游：标了几段第 5 阶段片段，设定集是不是还是旧脸。只有脸变了才标片段。"""
    name = str(record.get("name") or "").strip()
    marked = 0
    if face_changed:
        marked = mark_character_clips_stale(task, name, _fill(catalog().wording["stale_clip_reason"], name=name))
    return {"clips_marked": marked, "sheet_stale": sheet_is_stale(record, task)}


def preview(record: Mapping[str, Any], sculpt: Sculpt, task: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """捏出来的效果：新描述、近景实际进提示词的脸、资产卡警告、每个表情的写法。不改任何数据。"""
    name = str(record.get("name") or "").strip()
    description = merge_description(_base_description(record), sculpt)
    card = parse_face_card(description)
    fragments = layer_fragments(sculpt)
    stale = sheet_is_stale(record, task)
    return {
        "description": description,
        "face_text": render_face_card(card, "close", include_other=False),
        "layers": {key: "、".join(values) for key, values in fragments.items()},
        "issues": [
            {"code": f"face_card_{issue.code}", "message": f"{issue.message}{issue.suggestion}"}
            for issue in audit_face_card(card)
        ],
        "expressions": {
            key: expression_line(name, key, expression) for key, expression in sculpt.expressions.items()
        },
        "sheet_stale": stale,
        "stale_note": catalog().wording["sheet_stale"] if stale else "",
    }


def _history(stored: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (stored.get("history") or []) if isinstance(item, Mapping) and item.get("id")]


def current(task: Mapping[str, Any], name: str) -> dict[str, Any]:
    record = record_of(task, name)
    sculpt = stored_sculpt(record) or Sculpt(face={}, notes={}, expressions={})
    stored = record.get(RECORD_KEY) if isinstance(record.get(RECORD_KEY), Mapping) else {}
    return {
        "name": name,
        "sculpt": sculpt.dump(),
        "revision": int(stored.get("revision") or 0),
        "updated_at": stored.get("updated_at"),
        "label": str(stored.get("label") or ""),
        # 最近的在前，不带整份捏脸：撤销时按 id 取。
        "history": [
            {"id": item["id"], "label": item.get("label", ""), "at": item.get("at"), "revision": item.get("revision", 0)}
            for item in reversed(_history(stored))
        ],
        "preview": preview(record, sculpt, task),
    }


def _pushed_history(stored: Mapping[str, Any], record: Mapping[str, Any], sculpt: Sculpt) -> list[dict[str, Any]]:
    """这次保存之前的那份捏脸进历史：第一次保存时进的是「捏脸前」的空白；原样重存不记。"""
    history = [dict(item) for item in _history(stored)]
    wording = catalog().wording
    if stored:
        previous = stored_sculpt(record) or Sculpt(face={}, notes={}, expressions={})
        if previous.dump() == sculpt.dump():
            return history
        snapshot = {"label": str(stored.get("label") or wording["history_manual"]), "revision": int(stored.get("revision") or 0),
                    "sculpt": previous.dump()}
    else:
        snapshot = {"label": wording["history_before"], "revision": 0, "sculpt": Sculpt(face={}, notes={}, expressions={}).dump()}
    history.append({"id": uuid.uuid4().hex[:8], "at": time.time(), **snapshot})
    return history[-HISTORY_LIMIT:]


def save(task: dict[str, Any], name: str, sculpt: Sculpt, *, label: str = "") -> dict[str, Any]:
    """捏脸写进这个角色的统一资产：角色描述、第 3 阶段各造型状态的分层字段，以及捏脸本身。

    第一次保存时记下原描述与各状态原字段，之后每次都从它们重新合成；捏脸清空等同于重置。
    ``label`` 说明这一步是怎么来的(手动调整 / 对话 / 撤销)，下次保存时随这份捏脸一起进撤销历史。
    """
    if sculpt.empty:
        return reset(task, name)
    record = record_of(task, name)
    stored = record.get(RECORD_KEY) if isinstance(record.get(RECORD_KEY), Mapping) else {}
    history = _pushed_history(stored, record, sculpt)
    desc_before = _base_description(record)
    states = _dna_states(task, name)
    states_before = dict(stored.get("states_before") or {}) if stored else {}
    for state in states:
        state_id = str(state.get("state_id") or state.get("title") or "")
        if state_id and state_id not in states_before:
            states_before[state_id] = {field: state[field] for field, _label in STATE_LAYER_FIELDS if field in state}
    face_changed = merge_description(desc_before, sculpt) != str(record.get("desc") or "")
    _note_sheet(record, task)   # 先记下现有设定集画的是改之前这段，再改描述
    record["desc"] = merge_description(desc_before, sculpt)
    for state in states:
        state_id = str(state.get("state_id") or state.get("title") or "")
        _restore_state(state, states_before.get(state_id, {}))
        state.update(merge_state_fields(state, sculpt))
    # revision 只数脸变了几次：只改表情不让设定集变成「待重出」。
    revision = int(stored.get("revision") or 0) + (1 if face_changed else 0)
    record[RECORD_KEY] = {
        **sculpt.dump(),
        "revision": revision,
        "updated_at": time.time() if face_changed else stored.get("updated_at"),
        "label": str(label or catalog().wording["history_manual"]),
        "history": history,
        "desc_before": desc_before,
        "states_before": states_before,
    }
    return {**current(task, name), "downstream": _downstream(task, record, face_changed)}


def revert(task: dict[str, Any], name: str, snapshot_id: str) -> dict[str, Any]:
    """退回撤销历史里的某一步：把那份捏脸再保存一次，描述与各状态照旧从原文重新合成，不会层层加码。"""
    record = record_of(task, name)
    stored = record.get(RECORD_KEY) if isinstance(record.get(RECORD_KEY), Mapping) else {}
    snapshot = next((item for item in _history(stored) if item["id"] == snapshot_id), None)
    if snapshot is None:
        raise LookupError(catalog().wording["history_missing"])
    try:
        sculpt = validate(snapshot.get("sculpt") or {})
    except SculptError as exc:
        raise LookupError(catalog().wording["history_missing"]) from exc
    label = catalog().wording["history_revert"].replace("{label}", str(snapshot.get("label") or ""))
    if not sculpt.empty:
        return save(task, name, sculpt, label=label)
    # 退回「捏脸前」：描述与各状态放回原样，但撤销历史留着，还能再退回来；只有重置才清历史。
    history = _pushed_history(stored, record, sculpt)
    downstream = reset(task, name)["downstream"]
    record[RECORD_KEY] = {"revision": 0, "label": label, "history": history}
    return {**current(task, name), "downstream": {**downstream, "sheet_stale": sheet_is_stale(record, task)}}


def reset(task: dict[str, Any], name: str) -> dict[str, Any]:
    """放回第一次捏脸前的描述与各状态字段，去掉捏脸(撤销历史一起清掉)。"""
    record = record_of(task, name)
    desc_before_reset = str(record.get("desc") or "")
    _note_sheet(record, task)   # 按捏过的脸重出过的设定集，脸放回去后就是旧脸；这一笔记在记录上，不随捏脸清掉
    stored = record.pop(RECORD_KEY, None)
    if isinstance(stored, Mapping):
        if "desc_before" in stored:
            record["desc"] = stored["desc_before"]
        before = stored.get("states_before") or {}
        for state in _dna_states(task, name):
            state_id = str(state.get("state_id") or state.get("title") or "")
            if state_id in before:
                _restore_state(state, before[state_id])
    face_changed = str(record.get("desc") or "") != desc_before_reset
    return {**current(task, name), "downstream": _downstream(task, record, face_changed)}


def _restore_state(state: dict[str, Any], before: Mapping[str, Any]) -> None:
    """分层字段放回原样：原来没有的字段删掉，不留空串。"""
    for field, _label in STATE_LAYER_FIELDS:
        if field in before:
            state[field] = before[field]
        else:
            state.pop(field, None)


# ---------------------------------------------------------------------------- natural-language edits


def _fill(template: str, **values: Any) -> str:
    """占位符逐个替换：措辞里带着 JSON 示例的大括号，不能用 str.format。"""
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def compact_catalog() -> str:
    """给模型看的控件表：键、名字、类型、选项的 value 与名字、刻度各档的意思；不带写进提示词的短语。"""
    cat = catalog()
    data = prompt_data.load(_DATA)
    table = {
        "layers": [{"key": item["key"], "label": item["label"]} for item in data["layers"]],
        "controls": [
            {
                "key": control.key, "layer": control.layer, "label": control.label, "kind": control.kind,
                **({"options": [{"value": value, "label": label} for value, label, _phrase in control.options]}
                   if control.kind == "choice" else
                   {"scale": {str(offset): step for offset, step in zip(range(SCALE_RANGE[0], SCALE_RANGE[1] + 1), control.steps) if step}}),
            }
            for control in cat.controls
        ],
        "presets": [{"key": key, "label": label} for key, label in cat.preset_labels.items()],
        "expression_controls": [
            {"key": key, "label": cat.expression_control_labels[key],
             "options": [{"value": value, "label": label} for value, label, _phrase in options]}
            for key, options in cat.expression_controls.items()
        ],
        "expressions": [{"key": key, "label": label} for key, label, _words in cat.expressions],
    }
    return json.dumps(table, ensure_ascii=False, separators=(",", ":"))


def _option_value(options: Iterable[tuple[str, str, str]], value: Any) -> str | None:
    """选项的 value；模型写成选项名字也认。"""
    text = str(value).strip()
    for option, label, _phrase in options:
        if text == option or text == label:
            return option
    return None


def _scale_value(value: Any) -> int | None:
    """刻度值：整数、整数值的小数、写成字符串的整数都认；超出 -2..2 不认。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            return None
    if not isinstance(value, int) or not SCALE_RANGE[0] <= value <= SCALE_RANGE[1]:
        return None
    return value


def _by_label(pairs: Iterable[tuple[str, str]], key: Any) -> str | None:
    text = str(key or "").strip()
    return next((item for item, label in pairs if text in (item, label)), None)


class _Filter:
    """把模型给的改动过一遍控件表：认得的进 patch，不认得的进 unknown 并说清原因。"""

    def __init__(self) -> None:
        self.cat = catalog()
        self.words: Mapping[str, str] = self.cat.wording["instruct"]
        self.patch: dict[str, Any] = {"face": {}, "notes": {}, "expressions": {}, "preset": ""}
        self.unknown: list[str] = []

    def _reject(self, reason: str, **values: Any) -> None:
        self.unknown.append(_fill(self.words[reason], **values))

    def face(self, raw: Any) -> None:
        if not isinstance(raw, Mapping):
            if raw is not None:
                self._reject("bad_shape", key="face")
            return
        for key, value in raw.items():
            control = next((item for item in self.cat.controls if item.key == key or item.label == key), None)
            if control is None:
                self._reject("unknown_control", key=key)
                continue
            if value in (None, ""):
                self.patch["face"][control.key] = None
            elif control.kind == "scale":
                number = _scale_value(value)
                if number is None:
                    self._reject("bad_scale", label=control.label, value=value)
                    continue
                self.patch["face"][control.key] = number if number else None
            else:
                option = _option_value(control.options, value)
                if option is None:
                    self._reject("unknown_option", label=control.label, value=value)
                    continue
                self.patch["face"][control.key] = option

    def notes(self, raw: Any) -> None:
        if not isinstance(raw, Mapping):
            if raw is not None:
                self._reject("bad_shape", key="notes")
            return
        for key, value in raw.items():
            layer = _by_label(FACE_LAYERS, key)
            if layer is None:
                self._reject("unknown_layer", key=key)
                continue
            text = _clip_text(value, self.cat.limits["note_chars"]) if value is not None else ""
            self.patch["notes"][layer] = text or None

    def expressions(self, raw: Any) -> None:
        if not isinstance(raw, Mapping):
            if raw is not None:
                self._reject("bad_shape", key="expressions")
            return
        pairs = [(key, label) for key, label, _words in self.cat.expressions]
        for key, item in raw.items():
            expression = _by_label(pairs, key)
            if expression is None:
                self._reject("unknown_expression", key=key)
                continue
            if item is None:
                self.patch["expressions"][expression] = None
                continue
            if not isinstance(item, Mapping):
                self._reject("bad_shape", key=f"expressions.{key}")
                continue
            label = self.cat.expression_label(expression)
            choices: dict[str, str | None] = {}
            raw_choices = item.get("choices")
            for control_key, value in (raw_choices.items() if isinstance(raw_choices, Mapping) else ()):
                control = _by_label(self.cat.expression_control_labels.items(), control_key)
                if control is None:
                    self._reject("unknown_expression_control", label=label, key=control_key)
                    continue
                if value in (None, ""):
                    choices[control] = None
                    continue
                option = _option_value(self.cat.expression_controls[control], value)
                if option is None:
                    self._reject("unknown_expression_option", label=label, control=self.cat.expression_control_labels[control], value=value)
                    continue
                choices[control] = option
            entry: dict[str, Any] = {"choices": choices}
            for field, limit in (("tell", self.cat.limits["tell_chars"]), ("habit", self.cat.limits["habit_chars"])):
                if field in item:
                    entry[field] = _clip_text(item[field], limit) if item[field] is not None else ""
            if not choices and not any(field in entry for field in ("tell", "habit")):
                # 控件全被驳回或整项是空的：原因已在 unknown 里，不能算成一条可用改动。
                continue
            self.patch["expressions"][expression] = entry

    def preset(self, raw: Any) -> None:
        if raw in (None, ""):
            return
        key = _by_label(self.cat.preset_labels.items(), raw)
        if key is None:
            self._reject("unknown_preset", key=raw)
            return
        self.patch["preset"] = key

    @property
    def empty(self) -> bool:
        """一条可用改动都没有：表情项要么去掉(None)，要么带选中的控件或 tell / habit 才算。"""
        expressions = self.patch["expressions"]
        usable = any(
            item is None or item.get("choices") or any(field in item for field in ("tell", "habit")) for item in expressions.values()
        )
        return not usable and not any(self.patch[key] for key in ("face", "notes", "preset"))


def _merge_patch(base: Sculpt, patch: Mapping[str, Any]) -> dict[str, Any]:
    """当前捏脸 ⊕ 改动：预设先铺底，再逐键覆盖；值为 None 的键去掉。"""
    merged = base.dump()
    if patch.get("preset"):
        merged["face"] = dict(catalog().presets[patch["preset"]])
        merged["preset"] = patch["preset"]
    for section in ("face", "notes"):
        for key, value in (patch.get(section) or {}).items():
            if value is None:
                merged[section].pop(key, None)
            else:
                merged[section][key] = value
    for key, item in (patch.get("expressions") or {}).items():
        if item is None:
            merged["expressions"].pop(key, None)
            continue
        entry = merged["expressions"].get(key) or {"choices": {}, "tell": "", "habit": ""}
        for control, value in (item.get("choices") or {}).items():
            if value is None:
                entry["choices"].pop(control, None)
            else:
                entry["choices"][control] = value
        for field in ("tell", "habit"):
            if field in item:
                entry[field] = item[field]
        merged["expressions"][key] = entry
    return merged


def _describe_patch(patch: Mapping[str, Any]) -> str:
    """模型没写说明时，按改动生成一句：「眼型→丹凤眼、鼻梁+1」。"""
    cat = catalog()
    parts: list[str] = []
    if patch.get("preset"):
        parts.append(cat.preset_labels[patch["preset"]])
    for key, value in (patch.get("face") or {}).items():
        control = cat.control(key)
        if value is None:
            parts.append(f"{control.label}×")
        elif control.kind == "scale":
            parts.append(f"{control.label}{value:+d}")
        else:
            parts.append(f"{control.label}→{next(label for option, label, _phrase in control.options if option == value)}")
    for key, value in (patch.get("notes") or {}).items():
        parts.append(f"{_LAYER_LABELS[key]}{'×' if value is None else '补充'}")
    for key, item in (patch.get("expressions") or {}).items():
        parts.append(f"{cat.expression_label(key)}{'×' if item is None else ''}")
    return "、".join(parts)


def apply_instruction(task: Mapping[str, Any], name: str, instruction: str, llm: LLM, *, model_name: str = "") -> dict[str, Any]:
    """一句话捏脸：模型把要求翻成控件取值，这里核一遍、合到当前捏脸上，返回合并后的捏脸与预览；不写任何数据。

    认不得的控件、选项、层、表情进 ``unknown``(带原因)而不是整句失败；备注、面部特征、小动作写长了截到上限。
    模型一个可用改动都没给时抛 ``SculptError``。调哪个模型由 ``llm`` 决定，``model_name`` 只是给调用方对账用的名字。
    """
    record = record_of(task, name)
    base = stored_sculpt(record) or Sculpt(face={}, notes={}, expressions={})
    cat = catalog()
    words: Mapping[str, str] = cat.wording["instruct"]
    system = _fill(words["system"], note_chars=cat.limits["note_chars"], tell_chars=cat.limits["tell_chars"])
    description = str(record.get("desc") or record.get("description") or "")[:600]
    user = _fill(
        words["user_template"],
        catalog=compact_catalog(), current=json.dumps(base.dump(), ensure_ascii=False, separators=(",", ":")),
        description=description, instruction=str(instruction or "").strip(),
    )
    answer = llm(system, user, int(cat.limits["instruct_max_tokens"]))
    data = extract_json_object(str(answer or ""))
    if not isinstance(data, Mapping):
        raise SculptError(words["nothing_usable"])
    accepted = _Filter()
    accepted.preset(data.get("preset"))
    accepted.face(data.get("face"))
    accepted.notes(data.get("notes"))
    accepted.expressions(data.get("expressions"))
    if accepted.empty:
        reasons = "；".join(accepted.unknown)
        raise SculptError(f"{words['nothing_usable']}：{reasons}" if reasons else words["nothing_usable"])
    sculpt = validate(_merge_patch(base, accepted.patch))
    reply = re.sub(r"\s+", " ", str(data.get("reply") or "")).strip() or _fill(
        words["reply_fallback"], changes=_describe_patch(accepted.patch),
    )
    return {
        "sculpt": sculpt,
        "patch": accepted.patch,
        "reply": reply,
        "unknown": accepted.unknown,
        "preview": preview(record, sculpt, task),
    }


__all__ = [
    "HISTORY_LIMIT", "LLM", "RECORD_KEY", "SHEET_KEY", "record_of", "Catalog", "Control", "Expression", "Sculpt", "SculptError",
    "apply_instruction", "catalog", "compact_catalog", "current", "describe_catalog", "expression_key_for",
    "expression_line", "expression_phrases", "layer_fragments", "mark_character_clips_stale", "merge_description",
    "merge_state_fields", "note_sheet_drawn", "preset_sculpt", "preview", "reset", "revert", "save", "sheet_is_stale",
    "shot_expression_lines", "shot_expression_note", "stored_sculpt", "validate",
]
