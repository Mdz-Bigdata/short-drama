# -*- coding: utf-8 -*-
"""人物资产卡：用分层结构词锁定角色长相，而不是靠「亚洲人」「欧洲人」一个标签。

只写人群标签，模型给的是训练集里最平均的那张脸；要让同一个角色跨镜头像同一个人，
得把长相拆成可控的结构词，并按层固定下来：

    身份锚点 → 骨相 → 五官 → 皮肤 → 毛发 → 体态        (锁定，跨镜头不变)
    镜头与光影                                         (不入卡，随每一镜变)

三条规则贯穿本模块：

1. **骨相词不跨系统拼接。** 模型对「东亚平均脸 / 欧洲平均脸」各有一套默认关联：浅眼窝、
   低鼻根、内眦褶是一套，深眼窝、高鼻根、强眉弓是另一套。同一张脸里两套混写，最常见的
   结果是一张混血脸。``audit_face_card`` 把这种混写报出来。这是模型标签的平均倾向，
   不是现实人群的判据——个体差异远大于群体均值。
2. **否定词放负面提示。** 「不要磨皮」写在正向提示里，模型常理解成「要磨皮」。
   卡里以「不要/避免/禁止…」开头的片段一律移进 ``negatives``。
3. **构图裁到哪，词写到哪。** 半身镜头写「四肢修长」是浪费 token 还干扰画面；全身远景写
   毛孔细纹同理。``fit_face_text_to_framing`` 按景别只留看得见的层，皮肤词最多留三个。

卡可以从自由文本里解析出来(剧本外貌句、阶段 3 的 DNA 段落)，也能解析它自己渲染出的
「骨相：…；五官：…」文本——解析与渲染互为幂等，同一段 DNA 经过几道工序不会层层加码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from app.core import prompt_data

# The layer names, the word tables, the split rules and what the audit says:
# app/data/prompt/face_card.json (its _about says why each table is ordered the way it is).
_WORDING = "face_card"

Framing = Literal["close", "full", "all"]
BoneSystem = Literal["east_asian", "european"]


def _word_table(key: str) -> dict[BoneSystem, tuple[str, ...]]:
    """A ``{system: words}`` table of the card's data, in file order."""
    return {name: tuple(str(word) for word in words) for name, words in prompt_data.value(_WORDING, key).items()}


def _rules(key: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """A first-match ``[[name, [words…]], …]`` table of the card's data, in file order."""
    return tuple((str(name), tuple(str(word) for word in words)) for name, words in prompt_data.value(_WORDING, key))


def _says(key: str, /, **values: object) -> str:
    """A sentence of the audit's wording, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["issues"][key]).format(**values)


# 锁定的六层(皮肤与毛发拆成两层)，顺序即渲染顺序。
FACE_LAYERS: tuple[tuple[str, str], ...] = prompt_data.pairs(_WORDING, "layers")
OTHER_LABEL = prompt_data.text(_WORDING, "other_label")
NEGATIVE_LABEL = prompt_data.text(_WORDING, "negative_label")
_LABEL_SEP = prompt_data.text(_WORDING, "label_separator")
_LIST_SEP = prompt_data.text(_WORDING, "list_separator")
_SEGMENT_SEP = prompt_data.text(_WORDING, "segment_separator")
# 解析时认得的段首层名：解析自己渲染出的文本，片段回到原层。
_SEGMENT_LABELS = {label: key for key, label in FACE_LAYERS} | {OTHER_LABEL: "other", NEGATIVE_LABEL: "negatives"}

# 半身像只留这么多皮肤词；再多 AI 会过度纹理化，脸变脏。
MAX_SKIN_TERMS = prompt_data.number(_WORDING, "max_skin_terms")

# ---------------- 骨相系统词库 ----------------
_BONE_SYSTEM_TERMS: dict[BoneSystem, tuple[str, ...]] = _word_table("bone_system_terms")
# 单一系统的卡自动把对面系统最容易「拉混血」的锚点写进负面提示。键是卡自己的系统。
_MIXING_NEGATIVES: dict[BoneSystem, tuple[str, ...]] = _word_table("mixing_negatives")
_POPULATION_LABELS: dict[BoneSystem, tuple[str, ...]] = _word_table("population_labels")
_SYSTEM_NAMES: dict[BoneSystem, str] = {
    name: str(label) for name, label in prompt_data.value(_WORDING, "system_names").items()
}
# 「亚洲」「欧洲」本身太宽：前面没有东/南/西/北限定时视为大而空的标签。
_VAGUE_LABELS = tuple(
    re.compile(str(item["pattern"]), re.I if item["ignore_case"] else 0)
    for item in prompt_data.value(_WORDING, "vague_labels")
)

# ---------------- 分层关键词 ----------------
# 按优先级归层，先命中的层胜出(顺序的理由见 face_card.json 的 _about)。
_LAYER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = _rules("layer_rules")
# 远景/全身里看不见的皮肤质感词；肤色词仍然保留。
_SKIN_TEXTURE_TERMS = prompt_data.words(_WORDING, "skin_texture_terms")
_SKIN_TONE_TERMS = prompt_data.words(_WORDING, "skin_tone_terms")
_NEGATION = prompt_data.pattern(_WORDING, "negation", re.I)
_SEGMENT_SPLIT = prompt_data.pattern(_WORDING, "segment_split")
_FRAGMENT_SPLIT = prompt_data.pattern(_WORDING, "fragment_split")


@dataclass
class FaceCard:
    """一张人物资产卡。各层是去重后的片段列表，``other`` 收不属于长相的固定特征(服装、配饰)。"""

    identity: list[str] = field(default_factory=list)
    bone: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    skin: list[str] = field(default_factory=list)
    hair: list[str] = field(default_factory=list)
    physique: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)

    def layer(self, key: str) -> list[str]:
        return getattr(self, key)

    @property
    def has_face_layers(self) -> bool:
        """卡里是否真的写了长相——全落在 ``other`` 的文本(如「剧本未提供外貌」)不算。"""
        return any(self.layer(key) for key, _label in FACE_LAYERS)


@dataclass(frozen=True)
class FaceCardIssue:
    code: Literal["mixed_bone_system", "label_anchor_conflict", "skin_overload", "vague_population_label"]
    message: str
    suggestion: str


def _issue(code: str, /, **values: object) -> FaceCardIssue:
    """One audit finding: its message and suggestion read from the card's data, filled in."""
    wording = prompt_data.load(_WORDING)["issues"][code]
    return FaceCardIssue(
        code=code,  # type: ignore[arg-type]
        message=str(wording["message"]).format(**values),
        suggestion=str(wording["suggestion"]).format(**values),
    )


def _classify(fragment: str) -> str:
    lowered = fragment.lower()
    for layer, terms in _LAYER_RULES:
        if any(term in lowered for term in terms):
            return layer
    return "other"


def _append(bucket: list[str], value: str) -> None:
    if value and value not in bucket:
        bucket.append(value)


def parse_face_card(text: str) -> FaceCard:
    """把一段身份 DNA 拆成分层的人物资产卡。

    以「骨相：」这类层名开头的段整段归该层(解析自己渲染出的文本时保持原层)；
    其余片段按关键词归层；以否定词开头的片段进 ``negatives``。
    """
    card = FaceCard()
    for segment in _SEGMENT_SPLIT.split(text or ""):
        segment = segment.strip()
        if not segment:
            continue
        label, sep, rest = segment.partition(_LABEL_SEP)
        forced = _SEGMENT_LABELS.get(label.strip()) if sep else None
        if forced:
            # 上游有时自己已经带了层名(「骨相：骨相：瓜子脸」)，多出来的那层一并剥掉。
            segment = rest.removeprefix(f"{label.strip()}{_LABEL_SEP}")
        for fragment in _FRAGMENT_SPLIT.split(segment):
            fragment = fragment.strip()
            if not fragment:
                continue
            if forced == "negatives" or (forced is None and _NEGATION.match(fragment)):
                _append(card.negatives, _NEGATION.sub("", fragment).strip() or fragment)
                continue
            _append(card.layer(forced or _classify(fragment)), fragment)
    return card


def _match_terms(text: str, terms_by_key: dict[BoneSystem, tuple[str, ...]]) -> dict[BoneSystem, list[str]]:
    """最长优先匹配，命中的片段从文本里挖掉——「无内眦褶」不会再被当成「内眦褶」。"""
    remaining = text.lower()
    ordered = sorted(
        ((term, key) for key, terms in terms_by_key.items() for term in terms),
        key=lambda item: -len(item[0]),
    )
    hits: dict[BoneSystem, list[str]] = {}
    for term, key in ordered:
        if term.lower() in remaining:
            hits.setdefault(key, []).append(term)
            remaining = remaining.replace(term.lower(), "\0")
    return hits


def bone_systems(card: FaceCard) -> dict[BoneSystem, list[str]]:
    """卡里骨相层与五官层命中的系统锚点。"""
    return _match_terms(_LIST_SEP.join(card.bone + card.features), _BONE_SYSTEM_TERMS)


def population_systems(card: FaceCard) -> set[BoneSystem]:
    return set(_match_terms(_LIST_SEP.join(card.identity), _POPULATION_LABELS))


def card_negatives(card: FaceCard) -> list[str]:
    """卡的负面词：卡里写明的否定片段 + 单一骨相系统时对面系统的混血锚点。"""
    negatives = list(card.negatives)
    systems = bone_systems(card)
    if len(systems) == 1:
        (system,) = systems
        for term in _MIXING_NEGATIVES[system]:
            _append(negatives, term)
    return negatives


def _is_skin_texture(fragment: str) -> bool:
    return any(term in fragment.lower() for term in _SKIN_TEXTURE_TERMS)


def _is_skin_tone(fragment: str) -> bool:
    return any(term in fragment.lower() for term in _SKIN_TONE_TERMS)


def _skin_texture_count(card: FaceCard) -> int:
    return sum(1 for fragment in card.skin if _is_skin_texture(fragment))


def audit_face_card(card: FaceCard) -> list[FaceCardIssue]:
    """人物资产卡最常翻车的几个坑。只报警告，不改卡：怎么改是创作者的决定。"""
    issues: list[FaceCardIssue] = []
    systems = bone_systems(card)
    if len(systems) > 1:
        detail = _SEGMENT_SEP.join(
            _says("system_terms", system=_SYSTEM_NAMES[key], terms=_LIST_SEP.join(terms)) for key, terms in systems.items()
        )
        issues.append(_issue("mixed_bone_system", detail=detail))
    labels = population_systems(card)
    if len(systems) == 1 and labels and not labels & set(systems):
        (system,) = systems
        issues.append(_issue(
            "label_anchor_conflict",
            labels=_LIST_SEP.join(_SYSTEM_NAMES[key] for key in labels),
            system=_SYSTEM_NAMES[system],
        ))
    if _skin_texture_count(card) > MAX_SKIN_TERMS:
        issues.append(_issue("skin_overload", limit=MAX_SKIN_TERMS))
    identity_text = _LIST_SEP.join(card.identity)
    if identity_text and not labels and any(pattern.search(identity_text) for pattern in _VAGUE_LABELS):
        issues.append(_issue("vague_population_label"))
    return issues


def _visible_layers(framing: Framing) -> tuple[str, ...]:
    if framing == "close":  # 特写到半身：看不见体态比例
        return ("identity", "bone", "features", "skin", "hair")
    if framing == "full":   # 全身远景：看不见毛孔细纹，看得见体态
        return ("identity", "bone", "features", "skin", "hair", "physique")
    return tuple(key for key, _label in FACE_LAYERS)


def render_face_card(card: FaceCard, framing: Framing = "all", *, include_other: bool = True) -> str:
    """把卡渲染成「身份锚点：…；骨相：…」的正向文本。负面词不进正向文本，由调用方放进负面提示。"""
    parts: list[str] = []
    visible = _visible_layers(framing)
    for key, label in FACE_LAYERS:
        if key not in visible:
            continue
        values = card.layer(key)
        if key == "skin" and framing == "full":
            values = [value for value in values if _is_skin_tone(value) or not _is_skin_texture(value)]
        elif key == "skin" and framing == "close":
            values = values[:MAX_SKIN_TERMS]
        if values:
            parts.append(f"{label}{_LABEL_SEP}{_LIST_SEP.join(values)}")
    if include_other and card.other:
        parts.append(f"{OTHER_LABEL}{_LABEL_SEP}{_LIST_SEP.join(card.other)}")
    return _SEGMENT_SEP.join(parts)


# 景别 → 裁切，按顺序判断：「中近景」「中景」先于「近景」，否则会被当成特写。
_FRAMING_PATTERNS: tuple[tuple[Framing, tuple[str, ...]], ...] = _rules("framing_patterns")


def framing_for_shot_size(shot_size: str) -> Framing:
    """把一镜的景别描述映射到裁切层级；说不清景别时保留全部层。"""
    lowered = (shot_size or "").lower()
    for framing, patterns in _FRAMING_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return framing
    return "all"


# 阶段 3 角色状态卡里的分层字段 → 层名(「body」在状态卡里叫体型，在资产卡里是体态层)。
STATE_LAYER_FIELDS: tuple[tuple[str, str], ...] = prompt_data.pairs(_WORDING, "state_layer_fields")


def state_face_fragments(state: Mapping[str, Any]) -> list[str]:
    """阶段 3 角色状态的长相文本：分层字段带上层名在前，整段 DNA 在后。

    设定集描述(drama_service)和看板质检(character_dashboard)都从这里取，两边归层一致。
    """
    fragments = [
        f"{label}{_LABEL_SEP}{str(state[key]).strip()}"
        for key, label in STATE_LAYER_FIELDS
        if str(state.get(key) or "").strip()
    ]
    dna = str(state.get("dna") or "").strip()
    return fragments + ([dna] if dna else [])


def fit_face_text_to_framing(text: str, shot_size: str) -> tuple[str, list[str]]:
    """按本镜景别裁剪一段身份 DNA，返回 (正向文本, 负面词)。

    文本里没解析出任何长相层时原样返回——它要么不是外貌描述，要么是「待补充」占位，
    重排只会把它弄乱。
    """
    card = parse_face_card(text)
    if not card.has_face_layers:
        return text, []
    return render_face_card(card, framing_for_shot_size(shot_size)), card_negatives(card)
