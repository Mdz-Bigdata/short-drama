# -*- coding: utf-8 -*-
"""Turn a finished shot table into Seedance prompt packages a person can paste.

A storyboard shot is a unit of story; a generation shot is a unit of what the model
can actually hold — around four seconds of one continuous action. So a package is
built in two steps:

1. **Re-cut.** Every storyboard shot is split into generation shots at its own beats,
   never longer than :data:`MAX_GENERATED_SECONDS`, and never into equal slices — an
   entrance, the action and the landing are not the same length.
2. **Pack.** Generation shots are filled into packages of the requested length
   (10 / 15 / 20 / 30 seconds). Each package is self-contained: it repeats its own
   style lock, cast lock, light lock, carried physical state, spatial lock and
   negatives, and its clock restarts at ``00:00`` — the model never saw the package
   before it.

Four shapes come out of the same plan: the default package, a continuous-take
variant, a fight variant whose shots are short and deliberately uneven, and a
segmented short-drama script document.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core.h3_sound_design import PACE_BY_DELIVERY
from app.core.style_packs import StylePack, negatives_for
from app.core.writer_dashboard import parse_duration_seconds

Variant = Literal["standard", "continuous", "fight", "script_doc"]

# One generated shot holds about this much continuous action; past it the model drifts.
MAX_GENERATED_SECONDS = 4.0
MIN_GENERATED_SECONDS = 1.0
# How many generation shots a package of each length carries, as a sanity range.
PACKAGE_SHOT_RANGE: dict[int, tuple[int, int]] = {10: (2, 4), 15: (3, 5), 20: (4, 6), 30: (5, 8)}
SUPPORTED_PACKAGE_SECONDS = tuple(sorted(PACKAGE_SHOT_RANGE))
# A script document's segment, which is a different unit from a prompt package.
MAX_SEGMENT_SECONDS = 15
MAX_SEGMENT_SHOTS = 8
DIVIDER = "-" * 38
# What a package's locks emphasise, by where it falls in the scene.
_PHASES = ("建立与打量", "压力上升", "失衡与反击", "揭底与收束")


@dataclass
class GeneratedShot:
    """One unit of generation: a slice of a storyboard shot the model can hold."""

    source_shot_id: int
    beat: int                           # which beat of the storyboard shot this is
    seconds: float
    size: str
    motion: str
    action: str
    index: int = 0                      # position inside its package, set when the package closes
    dialogue: str = ""
    speaker: str = ""
    sound: str = ""
    characters: tuple[str, ...] = ()
    start_seconds: float = 0.0          # within its package

    @property
    def end_seconds(self) -> float:
        return round(self.start_seconds + self.seconds, 1)


@dataclass
class PromptPackage:
    index: int
    shots: list[GeneratedShot]
    episode_start: float
    phase: str

    @property
    def seconds(self) -> float:
        return round(sum(shot.seconds for shot in self.shots), 1)

    @property
    def episode_end(self) -> float:
        return round(self.episode_start + self.seconds, 1)

    @property
    def cast(self) -> list[str]:
        return list(dict.fromkeys(name for shot in self.shots for name in shot.characters))


@dataclass
class PackagePlan:
    packages: list[PromptPackage]
    variant: Variant
    package_seconds: int
    total_seconds: float
    delivery: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "variant": self.variant, "package_seconds": self.package_seconds,
            "total_seconds": self.total_seconds, "delivery": self.delivery,
            "packages": [
                {
                    "index": package.index, "seconds": package.seconds,
                    "episode_span": [package.episode_start, package.episode_end],
                    "phase": package.phase,
                    "shots": [
                        {
                            "source_shot_id": shot.source_shot_id, "beat": shot.beat, "index": shot.index,
                            "seconds": shot.seconds, "size": shot.size, "motion": shot.motion,
                            "action": shot.action, "dialogue": shot.dialogue,
                        }
                        for shot in package.shots
                    ],
                }
                for package in self.packages
            ],
            "warnings": list(self.warnings),
        }


def _clock(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _clauses(text: str) -> list[str]:
    """The beats of a shot description, in order."""
    parts = [part.strip() for part in re.split(r"[。；;！!？?]|，(?=[^，]{6,})", str(text or "")) if part.strip()]
    return parts or [str(text or "").strip() or "保持上一镜的动作继续"]


def recut(shot: Mapping[str, object], *, max_seconds: float = MAX_GENERATED_SECONDS) -> list[GeneratedShot]:
    """Split one storyboard shot into generation shots at its own beats.

    The slices follow the weight of each beat's description, so they come out uneven —
    a glance and a door slamming are not both two seconds.
    """
    seconds = float(parse_duration_seconds(shot.get("duration")) or max_seconds)
    beats = _clauses(str(shot.get("desc") or ""))
    wanted = max(1, min(len(beats), math.ceil(seconds / max_seconds)))
    if wanted < len(beats):
        # Merge neighbouring beats until there are as many as the length allows.
        merged: list[str] = list(beats)
        while len(merged) > wanted:
            shortest = min(range(len(merged) - 1), key=lambda index: len(merged[index]) + len(merged[index + 1]))
            merged[shortest : shortest + 2] = [merged[shortest] + "，" + merged[shortest + 1]]
        beats = merged

    weights = [max(len(beat), 6) for beat in beats]
    total_weight = sum(weights)
    shot_id = int(shot.get("shot_id") or 0)
    characters = tuple(
        str(name).strip() for name in (shot.get("characters") or []) if str(name).strip() not in {"", "无", "空镜"}
    )
    dialogue = str(shot.get("dialogue") or "").strip()
    pieces: list[GeneratedShot] = []
    for index, (beat, weight) in enumerate(zip(beats, weights), start=1):
        share = seconds * weight / total_weight
        length = round(max(MIN_GENERATED_SECONDS, min(max_seconds, share)), 1)
        pieces.append(GeneratedShot(
            source_shot_id=shot_id, beat=index, seconds=length,
            size=str(shot.get("size") or "中景"), motion=str(shot.get("motion") or "固定"),
            action=beat, sound=str(shot.get("sound") or ""), characters=characters,
            # A line is spoken inside one generation shot, never split across two.
            dialogue=dialogue if index == _dialogue_slot(beats) else "",
        ))
    return pieces


def _dialogue_slot(beats: Sequence[str]) -> int:
    """Which beat carries the line: the one that mentions speaking, else the longest."""
    for index, beat in enumerate(beats, start=1):
        if any(word in beat for word in ("说", "问", "喊", "道", "开口", "低声", "答")):
            return index
    return max(range(1, len(beats) + 1), key=lambda index: len(beats[index - 1]))


def plan_packages(
    shots: Sequence[Mapping[str, object]],
    *,
    package_seconds: int = 15,
    variant: Variant = "standard",
    delivery: str = "正常",
    max_generated_seconds: float | None = None,
) -> PackagePlan:
    """Re-cut ``shots`` and fill them into self-contained packages."""
    if package_seconds not in PACKAGE_SHOT_RANGE:
        raise ValueError(f"package length must be one of {SUPPORTED_PACKAGE_SECONDS} seconds")
    if delivery not in PACE_BY_DELIVERY:
        raise ValueError(f"delivery must be one of {tuple(PACE_BY_DELIVERY)}")
    ceiling = max_generated_seconds or (3.0 if variant == "fight" else MAX_GENERATED_SECONDS)

    generated: list[GeneratedShot] = []
    for raw in shots:
        if isinstance(raw, Mapping):
            generated.extend(recut(raw, max_seconds=ceiling))
    if not generated:
        return PackagePlan(packages=[], variant=variant, package_seconds=package_seconds, total_seconds=0.0, delivery=delivery)

    packages: list[PromptPackage] = []
    current: list[GeneratedShot] = []
    elapsed = 0.0
    low, high = PACKAGE_SHOT_RANGE[package_seconds]

    def close(shots_in: list[GeneratedShot], start: float) -> PromptPackage:
        clock = 0.0
        # Inside a package the shots are numbered 1..N: the model is reading this
        # package alone and has never seen the storyboard's own numbering.
        for position, shot in enumerate(shots_in, start=1):
            shot.index = position
            shot.start_seconds = round(clock, 1)
            clock += shot.seconds
        phase = _PHASES[min(len(packages), len(_PHASES) - 1)]
        return PromptPackage(index=len(packages) + 1, shots=list(shots_in), episode_start=round(start, 1), phase=phase)

    package_start = 0.0
    for shot in generated:
        filled = sum(item.seconds for item in current)
        if current and (filled + shot.seconds > package_seconds or len(current) >= high):
            packages.append(close(current, package_start))
            package_start = round(package_start + filled, 1)
            current = []
        current.append(shot)
        elapsed += shot.seconds
    if current:
        packages.append(close(current, package_start))

    warnings: list[str] = []
    for package in packages[:-1]:
        if len(package.shots) < low:
            warnings.append(
                f"第{package.index}条提示词只有{len(package.shots)}个生成镜头，{package_seconds}秒建议{low}-{high}个；"
                "补反应镜或把长镜再拆一层",
            )
    rate = PACE_BY_DELIVERY[delivery]
    for package in packages:
        for shot in package.shots:
            spoken = len(re.findall(r"[一-鿿]", shot.dialogue)) / rate if shot.dialogue else 0.0
            if spoken and spoken > shot.seconds:
                warnings.append(
                    f"第{package.index}条镜头{shot.index}（分镜{shot.source_shot_id}）的台词按「{delivery}」语速需 {spoken:.1f}s，"
                    f"超过本镜 {shot.seconds}s；拆句或加长本镜",
                )
    return PackagePlan(
        packages=packages, variant=variant, package_seconds=package_seconds,
        total_seconds=round(elapsed, 1), delivery=delivery, warnings=warnings,
    )


def package_count(total_seconds: float, package_seconds: int) -> int:
    """How many packages an episode of this length needs; the last one may be short."""
    if package_seconds <= 0:
        raise ValueError("package length must be positive")
    return max(1, math.ceil(max(0.0, total_seconds) / package_seconds))


# ---------------------------------------------------------------------------------------------
# Rendering


@dataclass
class PackageContext:
    """What every package restates: who, where, in what light, carrying what."""

    pack: StylePack
    scene: str = ""
    spatial_lock: str = ""
    lighting: str = ""
    cast_locks: Mapping[str, str] = field(default_factory=dict)
    carried_state: str = ""
    extra_negatives: Sequence[str] = ()


def render_package(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """One pasteable Seedance package in the default shape."""
    cast = "｜".join(f"{name}：{context.cast_locks.get(name, '按设定图渲染，不可改造')}" for name in package.cast) or "本段无人物"
    negatives = negatives_for(context.pack, ["multi_person"] if len(package.cast) >= 2 else [], context.extra_negatives)
    lines = [
        f"【提示词{package.index}】【{_clock(package.episode_start)} - {_clock(package.episode_end)}】",
        "<Asset_Setup>",
        f"全局风格锁：{context.pack.style_caption}；本段重心：{package.phase}。",
        f"出场资产锁：{cast}",
        f"光影基调锁：{context.lighting or '延续本场主光方向、色温与光比'}",
        f"物理状态遗留：{context.carried_state or '服装、伤痕与道具归属延续上一段，不自行恢复'}",
        "</Asset_Setup>",
        f"【空间坐标与专属背景锁】：{context.spatial_lock or context.scene or '沿用本场既定站位与地标，禁止越轴'}",
    ]
    for shot in package.shots:
        lines.append(
            f"【镜头 {shot.index}】【{_clock(shot.start_seconds)} - {_clock(shot.end_seconds)}】"
            f"{shot.size}·{shot.motion}｜{shot.action}"
            + (f"｜台词（逐字不变，口型同步）：{shot.dialogue}" if shot.dialogue else "｜无台词，人物闭口")
            + "｜光线延续，画面无字幕"
        )
    lines.append(f"【负面词约束】基础负面词：{' + '.join(negatives[:8])}")
    lines.append(f"　　　　　　动态负面词：{_dynamic_negatives(package)}")
    lines.append(DIVIDER)
    return "\n".join(lines)


def _dynamic_negatives(package: PromptPackage) -> str:
    """What this particular段 is most likely to drift on."""
    risks = ["禁止人物换装", "禁止道具凭空出现或消失"]
    if len(package.cast) >= 2:
        risks.append("禁止两人面部特征互换")
    if any(shot.dialogue for shot in package.shots):
        risks.append("禁止口型与台词不同步")
    if any("走" in shot.action or "跑" in shot.action for shot in package.shots):
        risks.append("禁止无因果瞬移")
    return " + ".join(risks)


def render_continuous(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """The continuous-take variant: one unbroken action chain, no cut language."""
    cast = "｜".join(f"{name}：{context.cast_locks.get(name, '按设定图渲染')}" for name in package.cast) or "本段无人物"
    lines = [
        f"【连续镜头 {package.index}】总时长 {package.seconds:g} 秒｜{package.phase}",
        "【全局锁定】",
        f"人物：{cast}",
        f"空间：{context.spatial_lock or context.scene or '沿用本场既定站位与地标'}",
        f"光线：{context.lighting or '同一镜内色温与光比不变'}",
        f"质感：{context.pack.style_caption}",
    ]
    for shot in package.shots:
        lines.append(
            f"【{_clock(shot.start_seconds)} - {_clock(shot.end_seconds)}】{shot.size}，"
            f"镜头沿路径{shot.motion}：{shot.action}"
            + (f"；此处说：{shot.dialogue}" if shot.dialogue else "")
        )
    lines.extend([
        "【连续性总约束】人物身份与服装不变；空间关系与轴线不变；机位沿一条路径移动，不得切镜；"
        "情绪按段落递进，不跳档；质感与色彩全程一致。",
        f"【负面词约束】{' + '.join(negatives_for(context.pack, ['extension'], context.extra_negatives)[:10])} + 禁止切镜 + 禁止焦点跳跃",
        DIVIDER,
    ])
    return "\n".join(lines)


def render_fight(package: PromptPackage, context: PackageContext, plan: PackagePlan) -> str:
    """The fight variant: the whole fight's rules once, then short uneven beats."""
    fighters = "；".join(f"{name}：{context.cast_locks.get(name, '按设定图渲染')}" for name in package.cast) or "对战双方"
    lines = [
        f"【整体战斗设定】{package.index}／{len(plan.packages)}｜{package.phase}",
        f"风格：{context.pack.style_caption}",
        f"人物识别锚：{fighters}",
        f"场地响应：{context.scene or '场地'}——每次命中都要在环境上留下痕迹，破坏逐级升级，不跳级",
        "整体运动规则：持续走位、切角绕后、侧闪反进；接触点清楚、先因后果；只有碰撞瞬间允许极短顿挫，随即回速。",
        "【分镜】",
    ]
    for shot in package.shots:
        lines.append(
            f"{_clock(shot.start_seconds)}-{_clock(shot.end_seconds)}（{shot.seconds:g}s）"
            f"｜{shot.size}·{shot.motion}｜{shot.action}"
        )
    lines.extend([
        "【负面提示词】" + " + ".join([
            "禁止站桩轮流出招", "禁止无因果瞬移", "禁止长时间蓄力", "禁止动作糊成光团",
            "禁止无故换轴", "禁止特效遮挡接触点", "禁止肢体穿模或多出肢体", "禁止面部与服装互换",
            "禁止定格、停格、子弹时间", "无字幕", "无水印",
        ]),
        DIVIDER,
    ])
    return "\n".join(lines)


def render_script_document(plan: PackagePlan, context: PackageContext, *, title: str = "") -> str:
    """The segmented short-drama script: assets, the whole dialogue, then Shot rows."""
    shots = [shot for package in plan.packages for shot in package.shots]
    cast = list(dict.fromkeys(name for shot in shots for name in shot.characters))
    lines = [f"# {title or '分镜脚本'}", "", "## 角色与场景资产清单"]
    lines.extend(f"@{name}：{context.cast_locks.get(name, '按设定图渲染，全片不变')}" for name in cast)
    lines.append(f"@场景：{context.scene or '本场景'}；{context.spatial_lock or '固定参照物与站位见空间锁'}")
    lines.append(f"@光效：{context.lighting or '本场主光方向、色温与光比全段不变'}")
    lines.append("")
    lines.append("## 完整台词本")
    spoken = [shot for shot in shots if shot.dialogue]
    for order, shot in enumerate(spoken, start=1):
        lines.append(f"台词{order:02d}（镜{shot.source_shot_id}）：{shot.dialogue}")
    lines.append(f"（共 {len(spoken)} 句，逐字保持原文，不改称谓与语序）")
    lines.append("")

    segments = _segments(shots)
    lines.append(f"## 分镜脚本（{plan.total_seconds:g} 秒）")
    for order, segment in enumerate(segments, start=1):
        seconds = round(sum(shot.seconds for shot in segment), 1)
        lines.extend([
            "",
            f"【分段{order} - 总时长预估 {seconds:g} 秒】",
            f"【全局光效控制标准 - {context.scene or '本场景'}】{context.lighting or '主光方向、色温与光比在本分段内不变'}",
        ])
        for position, shot in enumerate(segment, start=1):
            lines.extend([
                f"Shot {order}.{position}（时长：{shot.seconds:g} 秒）[{shot.size}]",
                f"  场景：{context.scene or '本场景'}",
                f"  出场人物：{('、'.join(f'@{name}' for name in shot.characters)) or '无'}",
                f"  主体：{('@' + shot.characters[0]) if shot.characters else '环境'}",
                f"  动作：{shot.action}",
                f"  台词：{shot.dialogue or '无台词'}",
                f"  镜头：{shot.motion}",
                f"  氛围光影：{context.lighting or '延续本分段光效标准'}",
                f"  音频指令：{shot.sound or '环境底噪延续；无台词处保留死寂底噪'}",
                f"  风格约束：{context.pack.style_caption}；9:16；画面干净无字幕",
                f"  → 动作桥接：结束于{_landing(shot)}，下一镜从此状态继续",
            ])
        lines.append(f"【分段时长核验】{len(segment)} 镜 / {seconds:g} 秒（上限 {MAX_SEGMENT_SHOTS} 镜 / {MAX_SEGMENT_SECONDS} 秒）")
    return "\n".join(lines)


def _segments(shots: Sequence[GeneratedShot]) -> list[list[GeneratedShot]]:
    segments: list[list[GeneratedShot]] = []
    current: list[GeneratedShot] = []
    for shot in shots:
        filled = sum(item.seconds for item in current)
        if current and (filled + shot.seconds > MAX_SEGMENT_SECONDS or len(current) >= MAX_SEGMENT_SHOTS):
            segments.append(current)
            current = []
        current.append(shot)
    if current:
        segments.append(current)
    return segments


def _landing(shot: GeneratedShot) -> str:
    tail = shot.action.split("，")[-1].strip()
    return tail or "本镜结束时的姿态与道具归属"


_RENDERERS = {"standard": render_package, "continuous": render_continuous, "fight": render_fight}


def render(plan: PackagePlan, context: PackageContext, *, title: str = "") -> str:
    """The whole deliverable: every package, or the script document for that variant."""
    if plan.variant == "script_doc":
        return render_script_document(plan, context, title=title)
    renderer = _RENDERERS[plan.variant]
    header = (
        f"# {title or 'Seedance 提示词'}｜{plan.variant}｜单条 {plan.package_seconds} 秒 × "
        f"{len(plan.packages)} 条｜共 {plan.total_seconds:g} 秒｜语速档「{plan.delivery}」"
    )
    body = "\n".join(renderer(package, context, plan) for package in plan.packages)
    return f"{header}\n\n{body}"


__all__ = [
    "DIVIDER", "MAX_GENERATED_SECONDS", "MAX_SEGMENT_SECONDS", "MAX_SEGMENT_SHOTS",
    "PACKAGE_SHOT_RANGE", "SUPPORTED_PACKAGE_SECONDS", "GeneratedShot", "PackageContext",
    "PackagePlan", "PromptPackage", "package_count", "plan_packages", "recut", "render",
    "render_continuous", "render_fight", "render_package", "render_script_document",
]
