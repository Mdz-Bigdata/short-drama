# -*- coding: utf-8 -*-
"""Design sheets: the reference images a production has to lock before it shoots.

A character drawn afresh in every shot is a different person by episode three, and a
room re-invented per scene is a different room. So before any frame is generated, the
story is read once and turned into a sheet per asset — each with a stable name, the
anchors that identify it, and a prompt that can be pasted into an image model as is.

Four kinds, each with its own fixed layout, because the layout is what makes the sheet
usable later:

- **character**: an oversized frontal face close-up beside front / profile / back full
  figures, with the costume broken out below, on white, with no text in the frame.
- **scene**: one image as a 2×2 grid of four angles, and a prompt that opens by saying
  the frame holds no people at all — a scene sheet with an actor in it locks the actor,
  not the room.
- **prop**: only the objects the story actually turns on, shot clean for reuse.
- **palette**: the colour card, with every colour bound to something visible.

What a sheet may say is bounded by the script. Where the script is silent the sheet
infers conservatively from period, role and setting, and says nothing it cannot see.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core.style_packs import PaletteCard, PaletteColour, StylePack, build_palette_card

AssetKind = Literal["character", "scene", "prop", "palette"]

# A scene name has to be recognisable on its own: two traits plus the place.
MIN_SCENE_NAME_CHARS = 4
# Every scene prompt opens with this, or the model puts a person in the room.
EMPTY_SCENE_PREFIX = "不能出现其他人, 无人, 纯场景,"
EMPTY_SCENE_SUFFIX = "no humans, empty, landscape only"

CHARACTER_LAYOUT = (
    "版式：画面左侧三分之一为超大高清正面面部特写；右侧三分之二并排三张全身三视图，依次为正面(FRONT)、"
    "侧面(PROFILE)、背面(BACK)；人物下方另排服装细节与配饰展示图。纯白背景，构图工整。"
    "所有视角的身高、五官位置、服装褶皱严格一致。画面内不得出现任何文字。"
)
SCENE_LAYOUT = (
    "版式：同一张图四宫格输出四个视角——高角度航拍俯瞰、低角度仰视、侧面视角、反面视角；"
    "每格画面内标注该视角名称。"
)
PROP_LAYOUT = "版式：纯色背景产品级特写，单体居中，正面与四分之三侧各一，展示材质、磨损与使用痕迹。画面内不得出现人物与文字。"

# Words that say what a character looks like, and words that only say how they feel.
_APPEARANCE_HINTS = (
    "岁", "身高", "体型", "发", "眼", "眉", "脸", "肤", "痣", "疤", "胡", "妆", "穿", "衣", "袍", "裙",
    "裤", "鞋", "帽", "镜", "链", "戒", "表", "包", "制服", "西装", "大衣", "围巾",
)
_FEELING_WORDS = ("性格", "内心", "情绪", "善良", "冷漠", "温柔", "狠", "爱", "恨", "悲", "喜", "野心", "自卑")
# A prop earns a sheet only if the story leans on it.
_PROP_SIGNALS = ("特写", "递", "接", "抢", "藏", "打开", "关上", "掏出", "握", "摔", "碎", "签", "证据", "信", "钥匙", "照片")
_SCENE_TRAIT_WORDS = (
    ("暖光", "冷光", "顶灯", "烛光", "霓虹", "阳光", "月光", "灯火"),          # light
    ("木", "玻璃", "水泥", "砖", "铁皮", "石", "地毯", "瓷砖", "纸"),          # material
    ("清晨", "正午", "黄昏", "深夜", "雨夜", "雪天", "阴天"),                  # time
)


@dataclass
class AssetSheet:
    """One asset, ready to be generated and then reused as a reference."""

    kind: AssetKind
    name: str
    function: str                     # what it does in the story
    anchors: list[str] = field(default_factory=list)
    prompt: str = ""
    layout: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "name": self.name, "function": self.function,
            "anchors": list(self.anchors), "prompt": self.prompt, "layout": self.layout,
            "notes": list(self.notes),
        }


@dataclass
class SheetSet:
    characters: list[AssetSheet] = field(default_factory=list)
    scenes: list[AssetSheet] = field(default_factory=list)
    props: list[AssetSheet] = field(default_factory=list)
    palette: AssetSheet | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[AssetSheet]:
        return [*self.characters, *self.scenes, *self.props, *([self.palette] if self.palette else [])]

    def as_dict(self) -> dict:
        return {
            "characters": [sheet.as_dict() for sheet in self.characters],
            "scenes": [sheet.as_dict() for sheet in self.scenes],
            "props": [sheet.as_dict() for sheet in self.props],
            "palette": self.palette.as_dict() if self.palette else None,
            "warnings": list(self.warnings),
        }


def _clean(text: object, limit: int = 400) -> str:
    return " ".join(str(text or "").split())[:limit]


def _visual_only(description: str) -> tuple[str, list[str]]:
    """Keep what a camera can see; report what was dropped as feeling rather than look."""
    kept, dropped = [], []
    for part in re.split(r"[，,；;。]", description):
        piece = part.strip()
        if not piece:
            continue
        if any(word in piece for word in _FEELING_WORDS) and not any(hint in piece for hint in _APPEARANCE_HINTS):
            dropped.append(piece)
            continue
        kept.append(piece)
    return "，".join(kept), dropped


def character_sheet(name: str, description: str = "", *, role: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A character's turnaround sheet: looks only, never temperament."""
    visual, dropped = _visual_only(_clean(description))
    anchors = [piece for piece in visual.split("，") if piece][:8]
    style = f"{pack.style_caption}；" if pack else ""
    prompt = (
        f"{style}角色设定板：{name}。{visual or '按题材、身份与场合保守补全常驻造型'}。"
        "同一人物、同一服装、同一发型、同一体型；五官位置、痣与疤痕位置固定。"
        f"{CHARACTER_LAYOUT}"
    )
    notes = [f"未写进提示词的性格描述（只用于反推造型）：{'、'.join(dropped)}"] if dropped else []
    if not anchors:
        notes.append("剧本没有给出外形信息：请补一句外形描述，否则每集都会换脸")
    return AssetSheet(
        kind="character", name=name, function=role or "剧本具名角色",
        anchors=anchors, prompt=prompt, layout=CHARACTER_LAYOUT, notes=notes,
    )


def scene_name(raw: str, description: str = "") -> str:
    """A scene name that identifies the place: two traits plus the place itself."""
    base = _clean(raw, 40) or "场景"
    if len(base) >= MIN_SCENE_NAME_CHARS:
        return base
    haystack = f"{raw} {description}"
    traits = [
        next((word for word in group if word in haystack), "")
        for group in _SCENE_TRAIT_WORDS
    ]
    prefix = "".join(trait for trait in traits if trait)[:4]
    return f"{prefix}{base}" if prefix else f"无人{base}"


def scene_sheet(name: str, description: str = "", *, function: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A scene's four-view sheet. The frame holds the room and nothing else."""
    full_name = scene_name(name, description)
    body = _clean(description) or "按题材与时代补全空间类型、时间、光线结构与主要材质"
    style = f"{pack.style_caption}；" if pack else ""
    prompt = (
        f"{EMPTY_SCENE_PREFIX} {style}{full_name}：{body}。"
        f"写清空间类型、确切时间、光线结构（方向、色温、光比）、前中后景的标志性材质与物件。"
        f"{SCENE_LAYOUT} {EMPTY_SCENE_SUFFIX}"
    )
    notes: list[str] = []
    if len(full_name) < MIN_SCENE_NAME_CHARS:
        notes.append("场景名过短，建议用「光线 / 材质 / 时间 + 地点」组合命名")
    return AssetSheet(
        kind="scene", name=full_name, function=function or "剧情实际发生的空间",
        anchors=[piece for piece in body.split("，") if piece][:8],
        prompt=prompt, layout=SCENE_LAYOUT, notes=notes,
    )


def prop_sheet(name: str, description: str = "", *, function: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A prop sheet, for the objects the story actually turns on."""
    body = _clean(description) or "按题材与用途保守补全材质、颜色、新旧与使用方式"
    style = f"{pack.style_caption}；" if pack else ""
    return AssetSheet(
        kind="prop", name=_clean(name, 40), function=function or "推动剧情或承担连续性的关键道具",
        anchors=[piece for piece in body.split("，") if piece][:6],
        prompt=f"{style}道具设定图：{_clean(name, 40)}。{body}。{PROP_LAYOUT}",
        layout=PROP_LAYOUT,
    )


def palette_sheet(card: PaletteCard, *, pack: StylePack, segment: str = "") -> AssetSheet:
    """The colour card as a sheet: a flat swatch board, never a scene."""
    colours = "；".join(f"{colour.bound_to}{colour.name}{colour.hex}" for colour in card.colours)
    structure = (
        f"色板结构：主色 {card.colours[0].hex}；辅色 {card.colours[1].hex if len(card.colours) > 1 else '—'}；"
        f"高光与阴影按本片光比；承前 {card.carried} 色，新增 {len(card.colours) - card.carried} 色；"
        f"对比与色温按{pack.name}的影调设定。"
    )
    prompt = (
        f"色卡参考图：{card.title}。白底平色块，横向排列 {len(card.colours)} 个色块，"
        f"每块下方留出物件名位置（生成时不要写文字）。色值：{colours}。"
        "不是场景图、不是渲染图，只做色值参考。"
    )
    return AssetSheet(
        kind="palette", name=card.title, function=segment or "整段色彩母板",
        anchors=[f"{colour.name}{colour.hex}" for colour in card.colours],
        prompt=prompt, layout="版式：白底 16:9 平色块色卡，色块等宽排列。", notes=[structure],
    )


# ---------------------------------------------------------------------------------------------
# Reading a task


def _script_text(task: Mapping[str, object]) -> str:
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    parts = [str(assets.get("2") or ""), str(config.get("script_content") or "")]
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
    for scene in breakdown.get("scenes") or []:
        if isinstance(scene, Mapping):
            parts.append(str(scene.get("content") or ""))
    return "\n".join(part for part in parts if part)


def _handled_near(script: str, name: str) -> bool:
    """Whether the script does something with this object in the sentence that names it.

    One mention is not a reason for a sheet; one mention that is handed over, hidden,
    opened or smashed is. The unit is the sentence, so a hand-over in the line before
    does not vouch for a teacup sitting on the table in this one.
    """
    for sentence in re.split(r"[。！？!?\n]", script):
        if name in sentence and any(signal in sentence for signal in _PROP_SIGNALS):
            return True
    return False


def _named_assets(task: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
    production = breakdown.get("production_assets") if isinstance(breakdown.get("production_assets"), dict) else {}
    return [item for item in (production.get(key) or []) if isinstance(item, Mapping)]


def extract_sheets(
    task: Mapping[str, object], *, pack: StylePack, palette_colours: Sequence[PaletteColour] = (),
    project: str = "", episode: int = 1, segment: int = 1,
) -> SheetSet:
    """Read a task once and produce the sheets it needs before anything is generated.

    Characters come from the cast the project already extracted; scenes and props come
    from the breakdown's production assets, with props filtered down to the ones the
    script actually leans on.
    """
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    script = _script_text(task)
    result = SheetSet()

    seen: set[str] = set()
    for item in assets.get("3_characters") or []:
        if not isinstance(item, Mapping):
            continue
        name = _clean(item.get("name"), 40)
        if not name or name in seen:
            continue
        seen.add(name)
        result.characters.append(character_sheet(
            name, str(item.get("desc") or item.get("description") or ""),
            role=str(item.get("role") or ""), pack=pack,
        ))

    for item in _named_assets(task, "scenes"):
        name = _clean(item.get("name"), 40)
        if name:
            result.scenes.append(scene_sheet(name, str(item.get("description") or ""), pack=pack))

    for item in _named_assets(task, "props"):
        name = _clean(item.get("name"), 40)
        if not name:
            continue
        mentions = script.count(name)
        leaned_on = mentions > 1 or _handled_near(script, name)
        if not leaned_on:
            result.warnings.append(f"道具「{name}」在剧本里只出现一次且没有被强调，未出设定图")
            continue
        result.props.append(prop_sheet(name, str(item.get("description") or ""), pack=pack))

    if palette_colours:
        card = build_palette_card(
            pack, project=project or str((task.get("config") or {}).get("title_suggestion") or "本片"),
            episode=episode, segment=segment, subject=result.scenes[0].name if result.scenes else "全片",
            new_colours=list(palette_colours),
        )
        result.palette = palette_sheet(card, pack=pack)

    if not result.characters:
        result.warnings.append("还没有角色卡：先跑完第3阶段，再出设定图")
    return result


def render_markdown(sheets: SheetSet, *, title: str = "") -> str:
    """The sheet set as a document a person can work from."""
    lines = [f"# {title or '资产设定图'}"]
    for heading, items in (("人物资产", sheets.characters), ("场景资产", sheets.scenes), ("道具资产", sheets.props)):
        if not items:
            continue
        lines.extend(["", f"## 【{heading}】"])
        for order, sheet in enumerate(items, start=1):
            lines.extend([
                "",
                f"### {order}. {sheet.name}",
                f"- 功能定位：{sheet.function}",
                f"- 稳定识别锚点：{'；'.join(sheet.anchors) or '（剧本未给出，需补充）'}",
                f"- 描述提示词：{sheet.prompt}",
                f"- 固定格式输出：{sheet.layout}",
            ])
            lines.extend(f"- 备注：{note}" for note in sheet.notes)
    if sheets.palette:
        lines.extend([
            "", "## 【色板资产】", "",
            f"### {sheets.palette.name}",
            f"- 功能定位：{sheets.palette.function}",
            f"- 色值：{'；'.join(sheets.palette.anchors)}",
            f"- 描述提示词：{sheets.palette.prompt}",
            *(f"- 色板结构说明：{note}" for note in sheets.palette.notes),
        ])
    if sheets.warnings:
        lines.extend(["", "## 【提示】", *(f"- {warning}" for warning in sheets.warnings)])
    return "\n".join(lines)


__all__ = [
    "CHARACTER_LAYOUT", "EMPTY_SCENE_PREFIX", "EMPTY_SCENE_SUFFIX", "MIN_SCENE_NAME_CHARS",
    "PROP_LAYOUT", "SCENE_LAYOUT", "AssetSheet", "SheetSet",
    "character_sheet", "extract_sheets", "palette_sheet", "prop_sheet", "render_markdown",
    "scene_name", "scene_sheet",
]
