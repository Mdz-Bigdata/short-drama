# -*- coding: utf-8 -*-
"""What "燃一点" or "压抑" actually changes in a shot list.

A director's brief arrives as a feeling, not as parameters. This turns the feeling
into the seven things a storyboard can act on — how the camera tends to move, how
dense the effects are, how fast the cutting is, which shot sizes dominate, how the
frame is composed, how it is lit, and what the sound does — so the same word means
the same thing every time it is used.

A brief has one **primary** feeling and up to two **secondary** ones. The primary
sets the tone and wins every contest; the secondaries only bend the numbers
(roughly 70 / 15 / 15, or 70 / 30 with a single secondary). Feelings that pull
against each other (hot-blooded against oppressive, healing against tragic) are not
merged: the primary stays, the conflicting secondary is dropped and reported.

Nothing here calls a model: the same brief always decodes to the same numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

# Shot-size families the distribution is expressed in.
SIZE_BANDS = ("wide", "medium", "close")


@dataclass(frozen=True)
class Intent:
    """One feeling, and the seven offsets it applies."""

    id: str
    name: str
    triggers: tuple[str, ...]
    camera: str                  # how the camera tends to move
    vfx_density: float           # share of shots carrying a visible effect, 0-1
    rhythm: float                # multiplier on shot length: <1 cuts faster
    sizes: tuple[float, float, float]   # wide / medium / close share, sums to 1
    composition: str
    lighting: str
    sound: str
    # Feelings this one cannot be blended with.
    conflicts: tuple[str, ...] = ()


INTENTS: tuple[Intent, ...] = (
    Intent(
        "vfx_maxed", "特效拉满", ("特效拉满", "特效满", "视觉轰炸", "特效炸裂", "满屏特效"),
        camera="打斗专项与特殊视角：极速推拉、离心甩出、超快环绕",
        vfx_density=0.8, rhythm=0.7, sizes=(0.3, 0.3, 0.4),
        composition="低机位、超广角透视、前景粒子层层叠加",
        lighting="高对比配局部过曝，硬逆光剪影",
        sound="爆炸、能量、低频轰鸣；音效层可加到五层",
    ),
    Intent(
        "tight_fight", "打斗紧凑", ("打斗紧凑", "拳拳到肉", "近身缠斗", "快切打斗", "硬桥硬马"),
        camera="贴身平移、攻击轨迹跟拍、低角度扫掠拉出",
        vfx_density=0.5, rhythm=0.6, sizes=(0.2, 0.5, 0.3),
        composition="锁定身体焦点、持续动态模糊、前景快速掠过",
        lighting="强对比快速切换，命中帧提亮",
        sound="打击声优先，每次命中给低频闷响，环境声压到最低",
    ),
    Intent(
        "tension", "压迫紧绷", ("紧张", "绷住", "压迫", "剑拔弩张", "对峙感", "窒息"),
        camera="缓慢推进、被遮挡的窥视式推镜、静止到骤动",
        vfx_density=0.1, rhythm=1.5, sizes=(0.2, 0.4, 0.4),
        composition="偏离中心、大量留白、前景遮挡、荷兰角",
        lighting="高对比、硬阴影、明确的明暗交界线、单一方向光源",
        sound="持续低频铺底（心跳、耳鸣），静默拉长，重音留给关键点",
    ),
    Intent(
        "impact", "视觉冲击", ("冲击", "爆点", "炸裂", "震撼", "血脉偾张"),
        camera="急刹推镜、离心甩出、俯冲、斜向推拉、弹射升起",
        vfx_density=0.6, rhythm=0.7, sizes=(0.4, 0.3, 0.3),
        composition="超广角在先、极端近远透视、元素冲出画框",
        lighting="穿插一两帧全白闪、硬逆光爆发、明暗极端切换",
        sound="每次爆点给低频 BOOM，瞬态前置",
    ),
    Intent(
        "burning", "高燃", ("燃", "热血", "燃炸", "带感", "上头"),
        camera="弹射升起、超快环绕接推近、静止到骤动、上升拉开",
        vfx_density=0.5, rhythm=0.75, sizes=(0.3, 0.3, 0.4),
        composition="低机位为主、主体向上冲出画框、背景留给天空或光源",
        lighting="暖色主导（金橙红）、强逆光、镜头光晕、由暗到亮抬升",
        sound="音乐优先、画面跟着节拍走，音效推而不抢",
    ),
    Intent(
        "epic", "史诗宏大", ("史诗", "宏大", "壮阔", "大场面", "磅礴"),
        camera="上升拉开、反向拉轨、升降广角、宏观环绕",
        vfx_density=0.15, rhythm=1.3, sizes=(0.6, 0.25, 0.15),
        composition="对称、三分法、深焦、前中后景分明，人物不超过画面三分之一",
        lighting="黄金时刻或蓝调时刻、上帝光、大面积柔光，不做硬切",
        sound="管弦与人声优先，环境层丰富，单个音效留 5-10 秒",
    ),
    Intent(
        "oppressive", "压抑暗黑", ("压抑", "暗黑", "阴郁", "沉重", "绝望"),
        camera="窥视式推镜、缓慢推进、俯冲下压",
        vfx_density=0.1, rhythm=1.5, sizes=(0.15, 0.35, 0.5),
        composition="压缩头顶空间、画框向内挤压、人物被环境吞掉、前景遮挡",
        lighting="低调、单光源、大片阴影吃掉人物、冷色主导，拒绝暖调",
        sound="持续低频铺底、不协和音与噪声、可听见的心跳；不超过两层",
        conflicts=("burning", "healing"),
    ),
    Intent(
        "healing", "唯美治愈", ("唯美", "治愈", "温暖", "清新", "柔和", "甜"),
        camera="并行横移、宏观环绕、贴水面滑行、上升拉开",
        vfx_density=0.15, rhythm=1.5, sizes=(0.35, 0.4, 0.25),
        composition="居中对称、大量留白、柔焦前景",
        lighting="柔光为主、低对比、暖色（粉金奶油）、逆光柔焦、丰富焦外",
        sound="钢琴竖琴风铃与自然声，一到两层，拒绝厚重音效",
        conflicts=("oppressive", "tragic"),
    ),
    Intent(
        "comedic", "轻松搞笑", ("搞笑", "喜剧", "轻松", "沙雕", "无厘头", "解压"),
        camera="快速甩镜切反应、急推到表情峰值、跳切闪回",
        vfx_density=0.1, rhythm=0.85, sizes=(0.25, 0.35, 0.4),
        composition="人物直面镜头、对称的「呆视」构图、表情最大化",
        lighting="高调、明亮均匀、高饱和、暖色主导",
        sound="卡通音效优先（叮、啵、啪、咻），每层不超过 0.3 秒",
        conflicts=("tragic", "oppressive"),
    ),
    Intent(
        "eerie", "悬疑惊悚", ("悬疑", "惊悚", "诡异", "恐怖", "反转强"),
        camera="从缝隙窥视、反向拉轨、甩镜、跳切闪回、穿物推进",
        vfx_density=0.25, rhythm=1.2, sizes=(0.4, 0.3, 0.3),
        composition="透过缝隙取景、人物背对镜头、信息藏在画面边缘、人物小而空间吞噬",
        lighting="低调、大片黑区、单点光源（手电烛光月光）、闪烁光、阴影里有东西",
        sound="环境音优先（风、滴水、门轴、远处脚步）、不协和音、极低频",
        conflicts=("comedic",),
    ),
    Intent(
        "tragic", "虐心催泪", ("虐", "催泪", "悲情", "心碎", "遗憾", "破防"),
        camera="反向拉轨（抽离感）、俯冲下压、上升拉开",
        vfx_density=0.1, rhythm=1.8, sizes=(0.3, 0.2, 0.5),
        composition="人物在画面里很小、大量留白、雨雪作前景、背影取景",
        lighting="冷色主导（蓝灰青）、低饱和、高光压下去、阴天平光",
        sound="独奏钢琴或大提琴、雨风钟声、心跳渐弱；关键台词后留 3-5 秒纯画面",
        conflicts=("comedic", "healing"),
    ),
    Intent(
        "beat_synced", "卡点", ("卡点", "踩点", "节拍", "BGM同步"),
        camera="急刹推镜、每拍一次甩镜、重拍定帧、弹射升起",
        vfx_density=0.5, rhythm=0.7, sizes=(0.3, 0.2, 0.5),
        composition="每一拍构图重心换位（左→中→右→上→下），元素走对角与放射线",
        lighting="每个重拍给一到两帧全白或全色闪",
        sound="以 BGM 节拍为准，所有音效对齐节拍（±50 毫秒），不超过三层",
    ),
    Intent(
        "one_take", "一镜到底", ("一镜到底", "长镜头", "不切镜", "连续镜头"),
        camera="复合联动运镜：平滑跟随、环绕跟拍、移焦、旋转跟随",
        vfx_density=0.2, rhythm=1.2, sizes=(0.3, 0.45, 0.25),
        composition="重心沿运镜路径平滑转移、三分或居中、始终保留一个视觉锚点",
        lighting="光比平滑过渡、不用闪帧、同一镜内色温不变",
        sound="每段独立声音节拍（3-5 个变化点），底噪贯穿，动作声落在段落起止",
    ),
)
_BY_ID = {intent.id: intent for intent in INTENTS}
PRIMARY_WEIGHT = 0.7
SECONDARY_WEIGHT_ONE = 0.3
SECONDARY_WEIGHT_TWO = 0.15
MAX_SECONDARY = 2


@dataclass
class IntentPlan:
    """The decoded brief: what the shot list should come out like."""

    primary: Intent
    secondary: list[Intent] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)   # (intent id, why)
    vfx_density: float = 0.0
    rhythm: float = 1.0
    sizes: tuple[float, float, float] = (0.33, 0.34, 0.33)

    @property
    def names(self) -> list[str]:
        return [self.primary.name, *(intent.name for intent in self.secondary)]

    def shot_seconds(self, base: float) -> float:
        """A base shot length under this brief, never outside what a clip can be."""
        return round(max(1.0, base * self.rhythm), 1)

    def brief(self) -> str:
        """The paragraph the storyboard writer is given."""
        mix = "、".join(
            f"{label}{round(share * 100)}%" for label, share in zip(("远中景", "中景", "近特写"), self.sizes)
        )
        lines = [
            f"【感觉】主感觉：{self.primary.name}"
            + (f"；次感觉：{'、'.join(intent.name for intent in self.secondary)}（只做偏移，不反客为主）" if self.secondary else ""),
            f"运镜倾向：{self.primary.camera}",
            f"景别分布：{mix}；镜头长度按{self.rhythm:.2f}倍基准（小于1更碎、大于1更长）",
            f"特效密度：约{round(self.vfx_density * 100)}%的镜头带明显特效",
            f"构图：{self.primary.composition}",
            f"光影：{self.primary.lighting}",
            f"音效策略：{self.primary.sound}",
        ]
        for intent in self.secondary:
            lines.append(f"次感觉「{intent.name}」只在对应段落与峰值镜加权：{intent.camera}；{intent.lighting}")
        if self.dropped:
            lines.append("已丢弃冲突次感觉：" + "、".join(f"{name}（{why}）" for name, why in self.dropped))
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "primary": self.primary.id, "secondary": [intent.id for intent in self.secondary],
            "dropped": [{"intent": name, "reason": why} for name, why in self.dropped],
            "vfx_density": round(self.vfx_density, 3), "rhythm": round(self.rhythm, 3),
            "sizes": {band: round(share, 3) for band, share in zip(SIZE_BANDS, self.sizes)},
            "names": self.names,
        }


def get_intent(intent_id: str) -> Intent | None:
    return _BY_ID.get(str(intent_id or "").strip().lower())


def detect_intents(text: str) -> list[Intent]:
    """Every feeling named in a brief, strongest signal first.

    Ordered by where the word appears, so the first thing a director says is taken
    as the main feeling.
    """
    haystack = str(text or "")
    if not haystack.strip():
        return []
    hits: list[tuple[int, Intent]] = []
    for intent in INTENTS:
        positions = [haystack.find(word) for word in intent.triggers if word in haystack]
        if positions:
            hits.append((min(positions), intent))
    return [intent for _, intent in sorted(hits, key=lambda item: item[0])]


def decode(
    text: str = "", *, primary: str = "", secondary: Sequence[str] = (), default: str = "tension",
) -> IntentPlan:
    """Decode a brief into one primary feeling, up to two secondaries, and the numbers.

    Explicit ids win over the words in ``text``; an unreadable brief falls back to
    ``default`` so a shot list is never left without direction.
    """
    chosen = [intent for intent in (get_intent(primary),) if intent]
    chosen.extend(intent for intent in (get_intent(item) for item in secondary) if intent)
    if not chosen:
        chosen = detect_intents(text)
    if not chosen:
        fallback = get_intent(default) or INTENTS[0]
        chosen = [fallback]

    lead, rest = chosen[0], []
    dropped: list[tuple[str, str]] = []
    for intent in chosen[1:]:
        if intent.id == lead.id:
            continue
        if intent.id in lead.conflicts or lead.id in intent.conflicts:
            dropped.append((intent.name, f"与主感觉「{lead.name}」相冲"))
            continue
        if len(rest) >= MAX_SECONDARY:
            dropped.append((intent.name, "一份分镜最多两个次感觉"))
            continue
        rest.append(intent)

    weights = _weights(len(rest))
    parts = [lead, *rest]
    vfx = sum(intent.vfx_density * weight for intent, weight in zip(parts, weights))
    rhythm = sum(intent.rhythm * weight for intent, weight in zip(parts, weights))
    sizes = tuple(
        sum(intent.sizes[index] * weight for intent, weight in zip(parts, weights)) for index in range(3)
    )
    total = sum(sizes) or 1.0
    return IntentPlan(
        primary=lead, secondary=rest, dropped=dropped,
        vfx_density=round(vfx, 3), rhythm=round(rhythm, 3),
        sizes=tuple(round(share / total, 3) for share in sizes),
    )


def _weights(secondary_count: int) -> list[float]:
    if secondary_count == 0:
        return [1.0]
    if secondary_count == 1:
        return [PRIMARY_WEIGHT, SECONDARY_WEIGHT_ONE]
    return [PRIMARY_WEIGHT, SECONDARY_WEIGHT_TWO, SECONDARY_WEIGHT_TWO]


def describe() -> list[dict]:
    """The catalogue a picker shows."""
    return [
        {
            "id": intent.id, "name": intent.name, "triggers": list(intent.triggers),
            "camera": intent.camera, "vfx_density": intent.vfx_density, "rhythm": intent.rhythm,
            "sizes": {band: share for band, share in zip(SIZE_BANDS, intent.sizes)},
            "composition": intent.composition, "lighting": intent.lighting, "sound": intent.sound,
            "conflicts": list(intent.conflicts),
        }
        for intent in INTENTS
    ]


__all__ = [
    "INTENTS", "MAX_SECONDARY", "PRIMARY_WEIGHT", "SIZE_BANDS", "Intent", "IntentPlan",
    "decode", "describe", "detect_intents", "get_intent",
]
