# -*- coding: utf-8 -*-
"""Mine shooting assets (locations, props, costumes, effects) out of a screenplay.

The extractor is deliberately deterministic: it reads the structured Writer
Agent breakdown plus the raw screenplay and reports only what the text states.
It never invents an asset, so an empty result means the screenplay did not
name one rather than that the model was unavailable.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# One asset kind -> the labelled sections that describe it in the shooting
# scripts this project produces (see backend/skills/**/storyboard-format.md).
_SECTION_LABELS: dict[str, tuple[str, ...]] = {
    "prop": ("关键道具", "道具"),
    "costume": ("服装", "服饰", "造型", "着装"),
    "effect": ("特效", "视效", "效果"),
}
# `SC01 建康城外乱葬岗` and `建康城外乱葬岗` are the same location written twice.
_SCENE_CODE_PREFIX = re.compile(r"^(?:SC|SCENE|E\d+S)\s*\d*\s*[-:：]?\s*", re.IGNORECASE)
_SCENE_HEADING = re.compile(
    r"【\s*(?:场景|SCENE)\s*[0-9零一二三四五六七八九十]*\s*[:：]?\s*([^】]{2,80})\s*】",
    re.IGNORECASE,
)
_SCENE_BIBLE_HEADING = re.compile(
    r"^#{0,6}\s*场景圣经\s*[:：]\s*(.+)$",
    re.MULTILINE,
)
_LIST_ITEM = re.compile(r"^\s*[-*•]\s*(.+)$")
_MAX_ASSETS_PER_KIND = 60
_MAX_NAME_LENGTH = 60
_MAX_DESCRIPTION_LENGTH = 2000


def _clean(value: Any) -> str:
    return " ".join(
        str(value or "")
        .replace("\x00", "")
        .replace("**", "")
        .replace("`", "")
        .split()
    ).strip()


def _split_entries(raw: str) -> list[str]:
    """Split one labelled section body into individual asset entries."""
    parts = re.split(r"[、,，;；]|\s{2,}", raw)
    return [part for part in (_clean(part) for part in parts) if part]


# A trailing clause such as `插在萧遥腰带。` describes the previous prop rather
# than naming a new one; asset names are noun phrases, not verb phrases.
_CLAUSE_START = re.compile(
    r"^(?:插在|挂在|放在|位于|系在|藏在|摆在|由|从|被|用于|用来|随|以|在|其|该|它|他|她)"
)
_ACTION_TAIL = re.compile(
    r"(?:割下|拿起|放下|折断|形成对比|对比|甩出|扔出|递给|举起|穿上|脱下|生锈|反光明显|飞溅)。?$"
)


def _is_asset_entry(entry: str, kind: str) -> bool:
    if len(entry) < 2 or len(entry) > 120:
        return False
    if _CLAUSE_START.match(entry):
        return False
    # A clause that narrates an action ("…上割下", "…形成对比") describes an
    # asset in use rather than naming one. Effects are the exception: a visual
    # effect ("泥浆飞溅") is itself named by its motion.
    if kind != "effect" and _ACTION_TAIL.search(entry):
        return False
    # Whole sentences are descriptions of an asset, not the asset itself.
    return entry.count("。") == 0 or (entry.endswith("。") and len(entry) <= 40)


def _asset_name(entry: str) -> str:
    """Take the leading noun phrase; the rest of the sentence is description."""
    head = re.split(r"[（(：:，,。.]", entry, maxsplit=1)[0]
    name = _clean(head)[:_MAX_NAME_LENGTH]
    return name or _clean(entry)[:_MAX_NAME_LENGTH]


def _iter_labelled_sections(text: str, labels: Iterable[str]) -> list[str]:
    """Yield the body text under each `**标签**：…` or `- 标签：…` marker."""
    bodies: list[str] = []
    for label in labels:
        pattern = re.compile(
            rf"(?:^|\n)\s*(?:[-*•]\s*)?(?:\*{{0,2}})\s*{re.escape(label)}\s*(?:\*{{0,2}})\s*[:：]\s*"
            rf"([^\n]*(?:\n(?!\s*(?:[-*•]\s*)?(?:\*{{0,2}})[^\n:：]{{1,12}}[:：])[^\n]*)*)",
        )
        for match in pattern.finditer(text):
            body = match.group(1)
            if body and body.strip():
                bodies.append(body)
    return bodies


def _extract_locations(scenes: list[dict[str, Any]], script: str) -> list[dict[str, str]]:
    """Scene headings such as 【场景1：建康城外乱葬岗 / 夜 / 暴雨】 name a location."""
    found: dict[str, str] = {}

    def record(raw_heading: str, description: str) -> None:
        heading = _clean(raw_heading)
        if not heading:
            return
        # `建康城外乱葬岗 / 夜 / 暴雨初歇` -> name is the place, rest is context.
        segments = [segment for segment in (_clean(part) for part in heading.split("/")) if segment]
        name = (segments[0] if segments else heading)[:_MAX_NAME_LENGTH]
        name = re.sub(r"^(?:场景|SCENE)\s*[0-9零一二三四五六七八九十]*\s*[:：]?\s*", "", name).strip()
        name = _SCENE_CODE_PREFIX.sub("", name).strip()
        if not name:
            return
        detail = "；".join(segments[1:]) if len(segments) > 1 else ""
        body = _clean(description)
        merged = _clean(" ".join(part for part in (detail, body) if part))[:_MAX_DESCRIPTION_LENGTH]
        # Keep the richest description when the same location appears repeatedly.
        if name in found and len(found[name]) >= len(merged):
            return
        found[name] = merged

    for match in _SCENE_BIBLE_HEADING.finditer(script or ""):
        record(match.group(1), "")
    for scene in scenes:
        content = str(scene.get("content") or "")
        heading = _SCENE_HEADING.search(content)
        if heading:
            record(heading.group(1), content)
    for match in _SCENE_HEADING.finditer(script or ""):
        record(match.group(1), "")

    return [
        {"name": name, "description": description}
        for name, description in list(found.items())[:_MAX_ASSETS_PER_KIND]
    ]


def _extract_labelled(kind: str, scenes: list[dict[str, Any]], script: str) -> list[dict[str, str]]:
    labels = _SECTION_LABELS[kind]
    found: dict[str, str] = {}
    sources = [script or "", *(str(scene.get("content") or "") for scene in scenes)]
    for source in sources:
        for body in _iter_labelled_sections(source, labels):
            for line in body.splitlines():
                item = _LIST_ITEM.match(line)
                entries = _split_entries(item.group(1) if item else line)
                for entry in entries:
                    if len(found) >= _MAX_ASSETS_PER_KIND or not _is_asset_entry(entry, kind):
                        continue
                    name = _asset_name(entry)
                    if not name or name in found:
                        continue
                    found[name] = entry[:_MAX_DESCRIPTION_LENGTH]
    return [{"name": name, "description": description} for name, description in found.items()]


def extract_production_assets(task: dict[str, Any], kind: str) -> list[dict[str, str]]:
    """Return the `{name, description}` assets of one kind named by the screenplay."""
    if kind not in {"scene", "prop", "costume", "effect"}:
        raise ValueError("仅支持提取 scene、prop、costume 或 effect 资产")
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
    scenes = [item for item in (breakdown.get("scenes") or []) if isinstance(item, dict)]
    script_parts = [
        str(assets.get("2") or config.get("script_content") or ""),
        str(assets.get("4_raw") or ""),
    ]
    script = "\n".join(part for part in script_parts if part)

    if kind == "scene":
        return _extract_locations(scenes, script)
    return _extract_labelled(kind, scenes, script)
