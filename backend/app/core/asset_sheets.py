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
- **prop**: every object the breakdown lists, as the 2×3 design sheet (five views and a scale cell);
  the ones the story leans on are marked as key props.
- **palette**: the colour card, with every colour bound to something visible.

What a sheet may say is bounded by the script. Where the script is silent the sheet
infers conservatively from period, role and setting, and says nothing it cannot see.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core import prompt_data
from app.core.actor_sheet_layout import FULL_BODY_PROPORTION_RULE
from app.core.style_packs import PaletteCard, PaletteColour, StylePack, build_palette_card

AssetKind = Literal["character", "scene", "prop", "palette"]

# Every sentence, layout, word table and length limit of the sheets: app/data/prompt/asset_sheets.json.
_WORDING = "asset_sheets"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the sheets' wording table, filled in (a long one is stored as lines joined with nothing)."""
    body = prompt_data.load(_WORDING)["says"][key]
    return ("".join(body) if isinstance(body, list) else str(body)).format(**values)


def _word(key: str) -> str:
    """A word of the table used as it stands (a separator, the empty-scene phrases)."""
    return prompt_data.text(_WORDING, key)


def _limit(key: str) -> int:
    return int(prompt_data.value(_WORDING, "limits")[key])


# A scene name has to be recognisable on its own: two traits plus the place.
MIN_SCENE_NAME_CHARS = _limit("min_scene_name")
# Every scene prompt opens with this, or the model puts a person in the room.
EMPTY_SCENE_PREFIX = _word("empty_scene_prefix")
EMPTY_SCENE_SUFFIX = _word("empty_scene_suffix")

CHARACTER_LAYOUT = _says("character_layout", proportion_rule=FULL_BODY_PROPORTION_RULE)
SCENE_LAYOUT = _says("scene_layout")
# 和道具设定图(core/prop_turnaround)出的那张一致：说法在 app/data/prompt/prop_sheet.json。
PROP_LAYOUT = prompt_data.text("prop_sheet", "asset_layout")

# Words that say what a character looks like, and words that only say how they feel.
_APPEARANCE_HINTS = prompt_data.words(_WORDING, "appearance_hints")
_FEELING_WORDS = prompt_data.words(_WORDING, "feeling_words")
# A prop the story leans on is a key prop; every prop still gets its sheet.
_PROP_SIGNALS = prompt_data.words(_WORDING, "prop_signals")
# light, material, time: each group gives the first of its words the name or description holds.
_SCENE_TRAIT_WORDS = tuple(tuple(str(word) for word in group) for group in prompt_data.value(_WORDING, "scene_trait_words"))
_PIECE_SPLIT = prompt_data.pattern(_WORDING, "piece_split")
_SENTENCE_SPLIT = prompt_data.pattern(_WORDING, "sentence_split")
_PIECE = _word("piece_separator")


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


def _clean(text: object, limit: int = _limit("description")) -> str:
    return " ".join(str(text or "").split())[:limit]


def _visual_only(description: str) -> tuple[str, list[str]]:
    """Keep what a camera can see; report what was dropped as feeling rather than look."""
    kept, dropped = [], []
    for part in _PIECE_SPLIT.split(description):
        piece = part.strip()
        if not piece:
            continue
        if any(word in piece for word in _FEELING_WORDS) and not any(hint in piece for hint in _APPEARANCE_HINTS):
            dropped.append(piece)
            continue
        kept.append(piece)
    return _PIECE.join(kept), dropped


def character_sheet(name: str, description: str = "", *, role: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A character's turnaround sheet: looks only, never temperament."""
    visual, dropped = _visual_only(_clean(description))
    anchors = [piece for piece in visual.split(_PIECE) if piece][: _limit("character_anchors")]
    style = _says("style", caption=pack.style_caption) if pack else ""
    prompt = _says(
        "character_prompt", style=style, name=name, visual=visual or _says("character_visual_fallback"), layout=CHARACTER_LAYOUT,
    )
    notes = [_says("character_dropped_note", dropped=_word("dropped_separator").join(dropped))] if dropped else []
    if not anchors:
        notes.append(_says("character_no_looks_note"))
    return AssetSheet(
        kind="character", name=name, function=role or _says("character_function"),
        anchors=anchors, prompt=prompt, layout=CHARACTER_LAYOUT, notes=notes,
    )


def scene_name(raw: str, description: str = "") -> str:
    """A scene name that identifies the place: two traits plus the place itself."""
    base = _clean(raw, _limit("name")) or _says("scene_name_fallback")
    if len(base) >= MIN_SCENE_NAME_CHARS:
        return base
    haystack = f"{raw} {description}"
    traits = [
        next((word for word in group if word in haystack), "")
        for group in _SCENE_TRAIT_WORDS
    ]
    prefix = "".join(trait for trait in traits if trait)[: _limit("scene_traits")]
    return f"{prefix}{base}" if prefix else _says("scene_name_traitless", base=base)


def scene_sheet(name: str, description: str = "", *, function: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A scene's four-view sheet. The frame holds the room and nothing else."""
    full_name = scene_name(name, description)
    body = _clean(description) or _says("scene_body_fallback")
    style = _says("style", caption=pack.style_caption) if pack else ""
    prompt = _says(
        "scene_prompt", prefix=EMPTY_SCENE_PREFIX, style=style, name=full_name, body=body, layout=SCENE_LAYOUT, suffix=EMPTY_SCENE_SUFFIX,
    )
    notes: list[str] = []
    if len(full_name) < MIN_SCENE_NAME_CHARS:
        notes.append(_says("scene_short_name_note"))
    return AssetSheet(
        kind="scene", name=full_name, function=function or _says("scene_function"),
        anchors=[piece for piece in body.split(_PIECE) if piece][: _limit("scene_anchors")],
        prompt=prompt, layout=SCENE_LAYOUT, notes=notes,
    )


def prop_sheet(name: str, description: str = "", *, function: str = "", pack: StylePack | None = None) -> AssetSheet:
    """A prop sheet: the 2×3 design sheet every prop gets."""
    body = _clean(description) or _says("prop_body_fallback")
    style = _says("style", caption=pack.style_caption) if pack else ""
    return AssetSheet(
        kind="prop", name=_clean(name, _limit("name")), function=function or prompt_data.text("prop_sheet", "function_key"),
        anchors=[piece for piece in body.split(_PIECE) if piece][: _limit("prop_anchors")],
        prompt=_says("prop_prompt", style=style, name=_clean(name, _limit("name")), body=body, layout=PROP_LAYOUT),
        layout=PROP_LAYOUT,
    )


def palette_sheet(card: PaletteCard, *, pack: StylePack, segment: str = "") -> AssetSheet:
    """The colour card as a sheet: a flat swatch board, never a scene."""
    colours = _word("palette_colour_separator").join(f"{colour.bound_to}{colour.name}{colour.hex}" for colour in card.colours)
    structure = _says(
        "palette_structure", main=card.colours[0].hex,
        second=card.colours[1].hex if len(card.colours) > 1 else _word("palette_no_second"),
        carried=card.carried, added=len(card.colours) - card.carried, pack=pack.name,
    )
    prompt = _says("palette_prompt", title=card.title, count=len(card.colours), colours=colours)
    return AssetSheet(
        kind="palette", name=card.title, function=segment or _says("palette_function"),
        anchors=[f"{colour.name}{colour.hex}" for colour in card.colours],
        prompt=prompt, layout=_says("palette_layout"), notes=[structure],
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
    for sentence in _SENTENCE_SPLIT.split(script):
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
    from the breakdown's production assets. Every prop gets a sheet; the ones the script
    leans on are marked as key props.
    """
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    script = _script_text(task)
    result = SheetSet()

    seen: set[str] = set()
    for item in assets.get("3_characters") or []:
        if not isinstance(item, Mapping):
            continue
        name = _clean(item.get("name"), _limit("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        result.characters.append(character_sheet(
            name, str(item.get("desc") or item.get("description") or ""),
            role=str(item.get("role") or ""), pack=pack,
        ))

    for item in _named_assets(task, "scenes"):
        name = _clean(item.get("name"), _limit("name"))
        if name:
            result.scenes.append(scene_sheet(name, str(item.get("description") or ""), pack=pack))

    for item in _named_assets(task, "props"):
        name = _clean(item.get("name"), _limit("name"))
        if not name:
            continue
        # 每件道具都出设定图：只出现一次的也要在镜头里前后一致。剧情倚重的标为关键道具。
        leaned_on = script.count(name) > 1 or _handled_near(script, name)
        function = prompt_data.text("prop_sheet", "function_key" if leaned_on else "function_passing")
        result.props.append(prop_sheet(name, str(item.get("description") or ""), function=function, pack=pack))

    if palette_colours:
        card = build_palette_card(
            pack, project=project or str((task.get("config") or {}).get("title_suggestion") or _says("project_fallback")),
            episode=episode, segment=segment, subject=result.scenes[0].name if result.scenes else _says("subject_fallback"),
            new_colours=list(palette_colours),
        )
        result.palette = palette_sheet(card, pack=pack)

    if not result.characters:
        result.warnings.append(_says("no_characters"))
    return result


def render_markdown(sheets: SheetSet, *, title: str = "") -> str:
    """The sheet set as a document a person can work from."""
    lines = [_says("markdown_title", title=title or _says("markdown_title_fallback"))]
    joined = _word("markdown_list_separator").join
    for attribute, heading in prompt_data.value(_WORDING, "markdown_sections"):
        items = getattr(sheets, attribute)
        if not items:
            continue
        lines.extend(["", _says("markdown_section", heading=heading)])
        for order, sheet in enumerate(items, start=1):
            lines.extend([
                "",
                _says("markdown_sheet", order=order, name=sheet.name),
                _says("markdown_function", function=sheet.function),
                _says("markdown_anchors", anchors=joined(sheet.anchors) or _says("markdown_no_anchors")),
                _says("markdown_prompt", prompt=sheet.prompt),
                _says("markdown_layout", layout=sheet.layout),
            ])
            lines.extend(_says("markdown_note", note=note) for note in sheet.notes)
    if sheets.palette:
        lines.extend([
            "", _says("markdown_palette_section"), "",
            _says("markdown_palette_name", name=sheets.palette.name),
            _says("markdown_function", function=sheets.palette.function),
            _says("markdown_palette_colours", colours=joined(sheets.palette.anchors)),
            _says("markdown_prompt", prompt=sheets.palette.prompt),
            *(_says("markdown_palette_note", note=note) for note in sheets.palette.notes),
        ])
    if sheets.warnings:
        lines.extend(["", _says("markdown_warning_section"), *(_says("markdown_warning", warning=warning) for warning in sheets.warnings)])
    return "\n".join(lines)


__all__ = [
    "CHARACTER_LAYOUT", "EMPTY_SCENE_PREFIX", "EMPTY_SCENE_SUFFIX", "MIN_SCENE_NAME_CHARS",
    "PROP_LAYOUT", "SCENE_LAYOUT", "AssetSheet", "SheetSet",
    "character_sheet", "extract_sheets", "palette_sheet", "prop_sheet", "render_markdown",
    "scene_name", "scene_sheet",
]
