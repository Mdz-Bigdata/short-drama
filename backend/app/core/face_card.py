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

# 锁定的五层(皮肤与毛发拆成两层，镜头裁切时它们的去留不同)，顺序即渲染顺序。
FACE_LAYERS: tuple[tuple[str, str], ...] = (
    ("identity", "身份锚点"),
    ("bone", "骨相"),
    ("features", "五官"),
    ("skin", "皮肤"),
    ("hair", "毛发"),
    ("physique", "体态"),
)
OTHER_LABEL = "其他固定特征"
NEGATIVE_LABEL = "画面避免"
# 解析时认得的段首层名：解析自己渲染出的文本，片段回到原层。
_SEGMENT_LABELS = {label: key for key, label in FACE_LAYERS} | {OTHER_LABEL: "other", NEGATIVE_LABEL: "negatives"}

# 半身像只留 2—3 个皮肤词；再多 AI 会过度纹理化，脸变脏。
MAX_SKIN_TERMS = 3

Framing = Literal["close", "full", "all"]
BoneSystem = Literal["east_asian", "european"]

# ---------------- 骨相系统词库 ----------------
# 只收两套系统里「有区分度」的锚点；脸型、眼睛这类两边都用的通用词不收。
# 「高鼻梁」「五官深邃」在中文语境里也常用来写东亚角色，收进来会误报，故不收。
_BONE_SYSTEM_TERMS: dict[BoneSystem, tuple[str, ...]] = {
    "east_asian": (
        "浅眼窝", "眼窝浅", "平缓眉弓", "眉弓平缓", "低鼻根", "鼻根低", "内眦褶", "内双",
        "单眼皮", "面中平缓", "面部中前区平缓", "扁平脸", "短鼻梁", "圆钝鼻尖", "鼻尖圆钝",
        "宽鼻翼", "下巴后缩", "颧弓外扩",
        "shallow eye socket", "low nasal root", "epicanthal fold", "inner double eyelid",
        "monolid", "flat midface", "short nasal bridge", "rounded nasal tip",
    ),
    "european": (
        "深眼窝", "眼窝深", "高眉弓", "强眉弓", "眉弓突出", "高鼻根", "鼻根高", "欧式大双",
        "平行双", "无内眦褶", "尖锐鼻尖", "鼻尖尖锐", "窄鼻翼", "面中突出", "面部中前区突出",
        "下巴前翘",
        "deep-set eye", "deeper-set eye", "high nasal root", "higher nasal root",
        "strong brow ridge", "parallel double eyelid", "sharper nasal tip", "sharp nasal tip",
        "narrow nasal wing", "no epicanthal fold",
    ),
}
# 单一系统的卡自动把对面系统最容易「拉混血」的锚点写进负面提示(文章模板里的 --no)。
# 键是卡自己的系统，值是这张卡要避开的对面锚点。
_MIXING_NEGATIVES: dict[BoneSystem, tuple[str, ...]] = {
    "east_asian": ("深眼窝", "高鼻根", "强眉弓"),
    "european": ("面中平缓", "内眦褶"),
}
_POPULATION_LABELS: dict[BoneSystem, tuple[str, ...]] = {
    "east_asian": ("东亚", "中国", "华人", "汉族", "日本", "韩国", "east asian", "chinese", "japanese", "korean"),
    "european": (
        "北欧", "南欧", "东欧", "西欧", "高加索", "白人", "european", "caucasian", "nordic", "scandinavian",
    ),
}
_SYSTEM_NAMES: dict[BoneSystem, str] = {"east_asian": "东亚", "european": "欧洲"}
# 「亚洲」「欧洲」本身太宽：前面没有东/南/西/北限定时视为大而空的标签。
_VAGUE_LABELS = (
    re.compile(r"(?<![东南西北])亚洲"),
    re.compile(r"(?<![东南西北])欧洲"),
    re.compile(r"(?<!east )(?<!south )(?<!southeast )\basian\b", re.I),
    re.compile(r"(?<!northern )(?<!southern )(?<!eastern )(?<!western )\beuropean\b", re.I),
)

# ---------------- 分层关键词 ----------------
# 按优先级归层：服装配饰先拦下(否则「眼镜」会被认成五官)，皮肤质感先于五官(「眼下细纹」是皮肤)，
# 骨相专词先于五官(「眉弓」不是「眉」)，泛化的「脸」垫后，体态最后(「瘦削的脸」是骨相不是体态)。
_LAYER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("other", (
        "穿", "衣", "服", "裙", "裤", "鞋", "靴", "帽", "袍", "衫", "装", "围巾", "披风", "盔甲",
        "眼镜", "项链", "耳环", "耳坠", "戒指", "手表", "手镯", "腰带", "配饰", "道具",
        "wear", "dress", "shirt", "coat", "jacket", "glasses", "costume",
    )),
    ("identity", ("气质",)),  # 「散发着清冷气质」不是发型
    ("skin", (
        "肤", "毛孔", "绒毛", "细纹", "瑕疵", "雀斑", "泛红", "哑光", "磨皮", "油光", "颗粒",
        "痘", "skin", "pore", "freckle", "redness", "matte", "fine lines", "blemish",
    )),
    ("bone", (
        "颧", "下颌", "下颚", "颌", "眉弓", "眼窝", "面中", "骨相", "骨骼", "脸型", "折叠", "轮廓",
        "额头", "扁平脸", "jaw", "cheekbone", "brow ridge", "eye socket", "midface", "bone structure",
        "face shape", "lower face",
    )),
    ("features", (
        "眼", "眸", "睫", "眦", "内双", "双眼皮", "单眼皮", "鼻", "唇", "嘴", "下巴", "痣", "疤",
        "酒窝", "梨涡", "牙", "耳", "眉", "eyelid", "eyes", "nasal", "nose", "lips", "chin", "mole",
        "scar", "dimple", "epicanthal", "monolid", "brow",
    )),
    ("hair", (
        "发", "马尾", "辫", "刘海", "鬓", "胡", "须", "寸头", "光头", "丸子头", "体毛",
        "hair", "beard", "ponytail", "bangs",
    )),
    ("bone", ("脸", "face")),
    ("physique", (
        "身高", "肩", "躯干", "四肢", "腿", "臂", "重心", "体型", "体态", "身材", "高挑", "矮小",
        "魁梧", "健壮", "苗条", "微胖", "精瘦", "清瘦", "瘦", "头身", "骨架", "腰身", "细腰", "骨盆",
        "shoulder", "torso", "limb", "build", "tall", "slender", "petite",
    )),
    ("identity", (
        "岁", "少年", "青年", "中年", "老年", "少女", "男", "女", "气质", "身份", "混血", "人",
        "woman", "man", "girl", "boy", "years old",
    )),
)
# 远景/全身里看不见的皮肤质感词；肤色词(暖黄调、冷白皮)仍然保留。
_SKIN_TEXTURE_TERMS = (
    "毛孔", "绒毛", "细纹", "瑕疵", "颗粒", "纹理", "质感", "哑光", "雀斑", "泛红", "肤色不均",
    "痘", "光泽", "油光", "细腻", "粗糙", "磨皮",
    "pore", "peach fuzz", "fine lines", "blemish", "grain", "texture", "matte", "freckle", "redness",
)
# 肤色词：远景里仍看得见。「暖黄调半哑光皮肤」这种片段带着肤色，远景也保留。
_SKIN_TONE_TERMS = (
    "调", "白皙", "冷白", "暖黄", "黝黑", "小麦", "古铜", "苍白", "tone", "fair", "tan", "pale",
)
# 「别致」「勿忘我」不是否定，所以单字「别」「勿」不算。
_NEGATION = re.compile(r"^(不要|避免|禁止|切勿|不能|不得|no\s|avoid\s|without\s)", re.I)
_SEGMENT_SPLIT = re.compile(r"[；;。\n]+")
_FRAGMENT_SPLIT = re.compile(r"[，,、]+")


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
        label, sep, rest = segment.partition("：")
        forced = _SEGMENT_LABELS.get(label.strip()) if sep else None
        if forced:
            # 上游有时自己已经带了层名(「骨相：骨相：瓜子脸」)，多出来的那层一并剥掉。
            segment = rest.removeprefix(f"{label.strip()}：")
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
    return _match_terms("、".join(card.bone + card.features), _BONE_SYSTEM_TERMS)


def population_systems(card: FaceCard) -> set[BoneSystem]:
    return set(_match_terms("、".join(card.identity), _POPULATION_LABELS))


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
        detail = "；".join(f"{_SYSTEM_NAMES[key]}：{'、'.join(terms)}" for key, terms in systems.items())
        issues.append(FaceCardIssue(
            code="mixed_bone_system",
            message=f"骨相与五官里混用了两套骨相锚点（{detail}），模型容易拉出一张混血脸。",
            suggestion="人群标签只配同一套骨相锚点；确实要混血角色，就在身份锚点里写明混血再选一套为主。",
        ))
    labels = population_systems(card)
    if len(systems) == 1 and labels and not labels & set(systems):
        (system,) = systems
        issues.append(FaceCardIssue(
            code="label_anchor_conflict",
            message=(
                f"身份锚点写的是{'、'.join(_SYSTEM_NAMES[key] for key in labels)}，"
                f"骨相锚点却全来自{_SYSTEM_NAMES[system]}一套。"
            ),
            suggestion="人群标签和骨相锚点放在同一套系统里，哪层不对改哪层，不要继续加词。",
        ))
    if _skin_texture_count(card) > MAX_SKIN_TERMS:
        issues.append(FaceCardIssue(
            code="skin_overload",
            message=f"皮肤质感词超过{MAX_SKIN_TERMS}个，近景里脸会被过度纹理化、显脏。",
            suggestion="想自然写「轻微肤色不均、眼下细纹」，想干净写「半哑光、细腻肤质」，二三个即可。",
        ))
    identity_text = "、".join(card.identity)
    if identity_text and not labels and any(pattern.search(identity_text) for pattern in _VAGUE_LABELS):
        issues.append(FaceCardIssue(
            code="vague_population_label",
            message="只写了「亚洲」「欧洲」这类大而空的人群标签，模型只会给出最平均的模板脸。",
            suggestion="限定到东亚、北欧这类具体标签，并补上脸型、眼窝、鼻根、下颌等骨相锚点。",
        ))
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
            parts.append(f"{label}：{'、'.join(values)}")
    if include_other and card.other:
        parts.append(f"{OTHER_LABEL}：{'、'.join(card.other)}")
    return "；".join(parts)


# 景别 → 裁切。「中近景」「中景」先于「近景」判断，否则会被当成特写。
_FRAMING_PATTERNS: tuple[tuple[Framing, tuple[str, ...]], ...] = (
    ("full", ("全景", "远景", "全身", "七分身", "大全景", "wide", "full shot", "long shot", "establishing")),
    ("close", ("中近景", "中景", "半身", "近景", "特写", "medium", "close", "bust", "mcu", "ecu")),
)


def framing_for_shot_size(shot_size: str) -> Framing:
    """把一镜的景别描述映射到裁切层级；说不清景别时保留全部层。"""
    lowered = (shot_size or "").lower()
    for framing, patterns in _FRAMING_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return framing
    return "all"


# 阶段 3 角色状态卡里的分层字段 → 层名(「body」在状态卡里叫体型，在资产卡里是体态层)。
STATE_LAYER_FIELDS: tuple[tuple[str, str], ...] = (
    ("bone", "骨相"), ("features", "五官"), ("skin", "皮肤"), ("hair", "毛发"), ("body", "体态"),
)


def state_face_fragments(state: Mapping[str, Any]) -> list[str]:
    """阶段 3 角色状态的长相文本：分层字段带上层名在前，整段 DNA 在后。

    设定集描述(drama_service)和看板质检(character_dashboard)都从这里取，两边归层一致。
    """
    fragments = [
        f"{label}：{str(state[key]).strip()}"
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
