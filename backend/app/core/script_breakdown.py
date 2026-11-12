# -*- coding: utf-8 -*-
"""剧本拆解单：把分集剧本整理成制片能照着准备的表，每场一张。

字段按 docs/screenplay-standard/剧本规范与拆解元素.md 第 6 节：场号、内外、日夜、地点、页长、概要、
演员编号和各类元素。这里的「场」是连续发生在同一地点、同一时段的一组分镜，不是一个分镜。

几处是估的，不是剧本写的：

* 页长按「一页约一分钟」从分镜时长折算成 1/8 页；
* 日夜从时段词归一，判不出来就留空，不猜；
* 元素按名字在这一场文字里是否出现来挂，没点名的不算；
* 表演妆造一栏不看点名，和分镜用同一套规则算这一场每个人是哪身，写明戏服和妆效。

没有剧情日：项目里还没有这个数据。本模块只做文本，不调模型。
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import breakdown_kinds, character_variants, prompt_data
from app.core.character_looks import crowd_wardrobe, plan_looks, untimed_makeup
from app.core.production_asset_extractor import extract_production_assets
from app.core.storyboard_scene_context import EMPTY_ACTOR, is_uncast, mentioned
from app.core.writer_dashboard import episode_from_scene_id, parse_duration_seconds

# The words a heading is read with, the labels of the sheet and its export templates: app/data/prompt/script_breakdown.json.
_WORDING = "script_breakdown"


def _entry(key: str) -> Any:
    """The entry at the dotted ``key`` ("section.name") of the wording table."""
    node: Any = prompt_data.load(_WORDING)
    for part in key.split("."):
        node = node[part]
    return node


def _says(key: str, /, **values: object) -> str:
    """A template of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(_entry(key)).format(**values)


def _word(key: str) -> str:
    """A word or label of the wording table, used as it stands."""
    return str(_entry(key))


def _table(key: str) -> Any:
    """A word table of the wording table, used as it stands."""
    return _entry(key)


def _pattern(key: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(_word(key), flags)


#: 拆解单上的元素类别，按第 6.2 节的顺序；名字在 script_breakdown.json 的 element_labels。
_ELEMENT_ORDER = ("extra", "stunt", "vehicle", "prop", "effect", "look", "set_dressing", "product")
ELEMENT_KINDS: tuple[tuple[str, str], ...] = tuple((kind, str(_table("element_labels")[kind])) for kind in _ELEMENT_ORDER)
_SIDE_CODES = ("INT", "EXT", "INT/EXT")
_EN_HEADING = re.compile(r"^(INT\./EXT|INT/EXT|I/E|INT|EXT)\.?\s+(.+?)(?:\s+-\s+(.+?))?$", re.I)
_CN_HEADING = _pattern("patterns.cn_heading")
_SPLIT = _pattern("patterns.split")
_LEADING_HEADING = _pattern("patterns.leading_heading")
# 内景 / 外景 / 内外景 first, then the one-character 内 / 外.
_SIDES = {
    **{str(_table("side_words")[code]): code for code in _SIDE_CODES},
    **{str(_table("side_short_words")[code]): code for code in ("INT", "EXT")},
}
_SIDE_LABELS = {code: str(_table("side_labels")[code]) for code in _SIDE_CODES}
_NIGHT_WORDS = tuple(str(word) for word in _table("night_words"))
_DAY_WORDS = tuple(str(word) for word in _table("day_words"))
_TIME_TOKEN = _pattern("patterns.time_token")
_SENTENCE_END = _pattern("patterns.sentence_end")
_DAY_NIGHT_LABELS = {code: str(_table("day_night_labels")[code]) for code in ("DAY", "NIGHT")}
#: 堪布条的通行配色：内日白、外日黄、内夜蓝、外夜绿。
_STRIP_COLOURS = {("INT", "DAY"): "white", ("EXT", "DAY"): "yellow", ("INT", "NIGHT"): "blue", ("EXT", "NIGHT"): "green"}
_STRIP_LABELS = {colour: str(_table("strip_labels")[colour]) for colour in _STRIP_COLOURS.values()}
_LIST = _word("separators.list")
_SECONDS_PER_PAGE = 60
_SUMMARY_CHARS = 60
_CSV_FORMULA = ("=", "+", "-", "@")


def parse_heading(text: str) -> tuple[str, str, str]:
    """(内外, 地点, 时段原词) from a heading line; what is not written stays empty."""
    line = " ".join(str(text or "").split())
    if not line:
        return "", "", ""
    english = _EN_HEADING.match(line)
    if english:
        side = english.group(1).upper()
        return ("INT/EXT" if "/" in side else side), english.group(2).strip(), (english.group(3) or "").strip()
    chinese = _CN_HEADING.match(line)
    if chinese:
        location, time = chinese.group(2).strip(), (chinese.group(3) or "").strip()
        if not time:
            tokens = location.split()
            if len(tokens) > 1 and _TIME_TOKEN.match(tokens[-1]):
                location, time = " ".join(tokens[:-1]), tokens[-1]
        return _SIDES[chinese.group(1)], location, time
    # 「市井长街 黄昏 外景」: the order the screenwriting engine writes.
    tokens = [token for token in _SPLIT.split(line) if token]
    side = next((token for token in tokens if token in _SIDES), "")
    time = next((token for token in tokens if _TIME_TOKEN.match(token)), "")
    location = " ".join(token for token in tokens if token not in {side, time})
    return _SIDES.get(side, ""), location, time


def day_or_night(time: str) -> str:
    """DAY / NIGHT from the words of a heading; empty when they do not say."""
    words = str(time or "").upper()
    if any(word in words for word in _NIGHT_WORDS):
        return "NIGHT"
    return "DAY" if any(word in words for word in _DAY_WORDS) else ""


def eighths_of(seconds: int) -> int:
    """Page length in eighths of a page, at a minute a page; a scene is never shorter than 1/8."""
    return max(1, math.ceil(seconds / _SECONDS_PER_PAGE * 8)) if seconds > 0 else 0


def page_length(eighths: int) -> str:
    """``2 3/8``. Eighths are never reduced: a scheduler adds them up as they stand."""
    pages, rest = divmod(max(0, int(eighths)), 8)
    if not rest:
        return str(pages) if pages else ""
    return f"{pages} {rest}/8" if pages else f"{rest}/8"


def _scene_lines(raw: Mapping[str, Any]) -> tuple[str, str]:
    """(the heading of a shot, what happens in it). The outline writes ``content`` as heading + description + lines."""
    content = " ".join(str(raw.get("content") or "").split())
    description = " ".join(str(raw.get("description") or "").split())
    heading = ""
    if description and description in content:
        heading = content[: content.index(description)].strip()
    elif not description:
        match = _LEADING_HEADING.match(content)
        heading = match.group(1) if match else ""
    # The label is only a fallback: it has the place and the time but drops 内景 / 外景.
    return heading or str(raw.get("label") or ""), description or content


def _group_scenes(raw_scenes: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    previous: tuple[int, str, str, str] | None = None
    for raw in raw_scenes:
        heading, text = _scene_lines(raw)
        side, location, time = parse_heading(heading)
        episode = episode_from_scene_id(str(raw.get("scene_id") or ""))
        # A shot with no heading of its own carries on where the last one was.
        if previous and previous[0] == episode and not location:
            side, location, time = previous[1], previous[2], previous[3]
        place = (episode, side, location, time)
        shot = {**raw, "_side": side, "_location": location, "_time": time, "_episode": episode, "_text": text}
        if groups and place == previous and not raw.get("segment_break"):
            groups[-1].append(shot)
        else:
            groups.append([shot])
        previous = place
    return groups


def _catalog(task: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    catalog: dict[str, list[dict[str, Any]]] = {}
    for kind, _label in ELEMENT_KINDS:
        if kind == "look":
            continue
        catalog[kind] = [item for item in extract_production_assets(dict(task), kind) if str(item.get("name") or "").strip()]
    return catalog


def _cast_numbers(groups: Sequence[Sequence[Mapping[str, Any]]], extras: set[str]) -> dict[str, int]:
    """Cast numbers stay the same across the show: most scenes first, ties in order of appearance."""
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for group in groups:
        for name in dict.fromkeys(name for shot in group for name in shot.get("characters") or [] if _is_cast(name, extras)):
            counts[name] = counts.get(name, 0) + 1
            first_seen.setdefault(name, len(first_seen))
    ordered = sorted(counts, key=lambda name: (-counts[name], first_seen[name]))
    return {name: number for number, name in enumerate(ordered, start=1)}


def _is_cast(name: Any, extras: set[str]) -> bool:
    """有名有姓的人才编号：跑龙套和目录里登记成群演的不算。"""
    text = str(name or "").strip()
    return bool(text) and text != EMPTY_ACTOR and text not in extras and not is_uncast(text)


def compile_breakdown(task: Mapping[str, Any], raw_scenes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The whole show's breakdown: one sheet per scene, plus who and what is needed across scenes."""
    groups = _group_scenes(raw_scenes)
    catalog = _catalog(task)
    listed_extras = {str(item["name"]) for item in catalog["extra"]}
    numbers = _cast_numbers(groups, listed_extras)
    # 写剧本阶段还没有第 3 步的角色：这张表按它自己数出来的演员算。
    cast = list(numbers)
    known = {str(item["name"]) for item in catalog["extra"]}
    for item in crowd_wardrobe(task, cast=cast):
        if item["name"] not in known:
            catalog["extra"].append(item)
    listed_extras = {str(item["name"]) for item in catalog["extra"]}
    looks_by_person: dict[str, list[dict[str, Any]]] = {}
    for look in plan_looks(task, cast=cast):
        looks_by_person.setdefault(look["of"], []).append({"name": look["name"], character_variants.VARIANT_KEY: look["facts"], "label": look["label"]})
    loose_makeup = untimed_makeup(task, cast=cast)
    per_episode: dict[int, int] = {}
    sheets: list[dict[str, Any]] = []
    needed: dict[tuple[str, str], list[str]] = {}
    cast_scenes: dict[str, list[str]] = {name: [] for name in numbers}
    for group in groups:
        first = group[0]
        episode = int(first["_episode"] or 0)
        per_episode[episode] = per_episode.get(episode, 0) + 1
        number = f"{episode}-{per_episode[episode]}"
        seconds = sum(parse_duration_seconds(shot.get("duration")) for shot in group)
        eighths = eighths_of(seconds)
        text = " ".join(str(shot.get("_text") or "") for shot in group)
        cast_names = list(dict.fromkeys(name for shot in group for name in shot.get("characters") or [] if _is_cast(name, listed_extras)))
        for name in cast_names:
            cast_scenes[name].append(number)
        crowd = list(dict.fromkeys(
            str(name) for shot in group for name in shot.get("characters") or []
            if str(name).strip() and name != EMPTY_ACTOR and not _is_cast(name, listed_extras)
        ))
        elements: dict[str, list[str]] = {}
        for kind, _label in ELEMENT_KINDS:
            if kind == "look":
                names = _looks_in_scene(cast_names, looks_by_person, loose_makeup, text, group)
            else:
                names = [str(item["name"]) for item in catalog[kind] if mentioned(item, text)]
            if kind == "extra":
                names = list(dict.fromkeys([*names, *crowd]))
            if names:
                elements[kind] = names
                for name in names:
                    needed.setdefault((kind, name), []).append(number)
        side, day_night = str(first["_side"]), day_or_night(str(first["_time"]))
        sheets.append({
            "number": number, "episode": episode, "scene_ids": [str(shot.get("scene_id") or "") for shot in group],
            "int_ext": side, "day_night": day_night, "time": str(first["_time"]), "location": str(first["_location"]),
            "seconds": seconds, "eighths": eighths, "page_length": page_length(eighths),
            "strip": _STRIP_COLOURS.get((side, day_night), ""),
            "summary": _summary(str(first.get("_text") or "")),
            "cast": [{"number": numbers[name], "name": name} for name in cast_names],
            "elements": elements,
        })
    # 哪一场都没提到、也定不下时间的妆效，汇总里也要看得到，免得漏准备。
    for item in loose_makeup:
        if not any(key_kind == "look" and _says("says.look_owner", name=item["of"]) in name and item["label"] in name for key_kind, name in needed):
            needed[("look", _says("says.untimed_look", name=item["of"], label=item["label"]))] = []
    total = sum(sheet["eighths"] for sheet in sheets)
    return {
        "schema_version": "script-breakdown.v1",
        "title": str((task.get("config") or {}).get("title_suggestion") or (task.get("config") or {}).get("titleSuggestion") or ""),
        "total_scenes": len(sheets), "total_eighths": total, "total_pages": page_length(total),
        "scenes": sheets,
        "cast": [{"number": number, "name": name, "scenes": cast_scenes[name]} for name, number in numbers.items()],
        "elements": [
            {"kind": kind, "label": label, "name": name, "scenes": needed[(kind, name)]}
            for kind, label in ELEMENT_KINDS for key_kind, name in needed if key_kind == kind
        ],
    }


def _looks_in_scene(
    cast_names: Sequence[str], looks: Mapping[str, list[dict[str, Any]]], loose_makeup: Sequence[Mapping[str, str]], text: str, group: Sequence[Mapping[str, Any]],
) -> list[str]:
    """这一场每个人是哪身：和分镜同一套规则。「沈无咎：染血残衣·左颊剑伤」；这场中途受伤就前后都列；设定集那身不列。"""
    rows: list[str] = []
    for name in cast_names:
        worn: dict[str, None] = {}
        for shot in group:
            scene_id = str(shot.get("scene_id") or "")
            chosen = character_variants.pick(
                looks.get(name) or [], text=str(shot.get("_text") or ""),
                episode=character_variants.episode_of(scene_id), scene=character_variants.scene_of(scene_id),
            )
            if chosen:
                worn[str(chosen["label"])] = None
        added = [item["label"] for item in loose_makeup if item["of"] == name and mentioned({"name": item["name"]}, text)]
        joiner = _word("separators.look")
        parts = [joiner.join([label, *added]) for label in worn] or ([joiner.join(added)] if added else [])
        if parts:
            rows.append(_says("says.look_row", name=name, looks=_LIST.join(parts)))
    return rows


def _summary(text: str) -> str:
    sentence = _SENTENCE_END.split(" ".join(text.split()), maxsplit=1)[0]
    return sentence if len(sentence) <= _SUMMARY_CHARS else sentence[: _SUMMARY_CHARS - 1].rstrip(_word("summary_trim")) + _word("ellipsis")


def _safe_cell(value: Any) -> str:
    """Script text ends up in a spreadsheet; a cell that starts like a formula must not run as one."""
    text = str(value if value is not None else "")
    return f"'{text}" if text.startswith(_CSV_FORMULA) else text


def _cast_line(sheet: Mapping[str, Any]) -> str:
    return _LIST.join(f"{item['number']}.{item['name']}" for item in sheet.get("cast") or [])


def render_csv(breakdown: Mapping[str, Any]) -> str:
    """One row per scene. A BOM up front so Excel reads the Chinese as UTF-8."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([*(str(column) for column in _table("csv_header")), *(label for _kind, label in ELEMENT_KINDS)])
    for sheet in breakdown.get("scenes") or []:
        writer.writerow([_safe_cell(cell) for cell in (
            sheet["number"], _SIDE_LABELS.get(sheet["int_ext"], ""), _DAY_NIGHT_LABELS.get(sheet["day_night"], ""), sheet["time"], sheet["location"],
            sheet["page_length"], sheet["seconds"], _STRIP_LABELS.get(sheet["strip"], ""), sheet["summary"], _cast_line(sheet),
            *(_LIST.join(sheet["elements"].get(kind) or []) for kind, _label in ELEMENT_KINDS),
        )])
    return "\ufeff" + buffer.getvalue()


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(breakdown: Mapping[str, Any]) -> str:
    """The sheets to read: the strip list first, then one block per scene, then who and what across scenes."""
    title = str(breakdown.get("title") or _word("markdown.untitled"))
    lines = [
        _says("markdown.title", title=_md(title)), "",
        _says("markdown.totals", scenes=breakdown.get("total_scenes", 0), pages=breakdown.get("total_pages") or 0), "",
        _word("markdown.strips_heading"), "",
        *(str(line) for line in _table("markdown.strips_table")),
    ]
    for sheet in breakdown.get("scenes") or []:
        lines.append(_says(
            "markdown.strip_row", number=sheet["number"], side=_SIDE_LABELS.get(sheet["int_ext"], ""),
            day_night=_DAY_NIGHT_LABELS.get(sheet["day_night"], ""), location=_md(sheet["location"]), page_length=sheet["page_length"],
            strip=_STRIP_LABELS.get(sheet["strip"], ""), cast=_md(_cast_line(sheet)), summary=_md(sheet["summary"]),
        ))
    lines.extend(["", _word("markdown.sheets_heading"), ""])
    for sheet in breakdown.get("scenes") or []:
        place = _word("separators.place").join(part for part in (_SIDE_LABELS.get(sheet["int_ext"], ""), _DAY_NIGHT_LABELS.get(sheet["day_night"], ""), sheet["location"]) if part)
        lines.extend([_says("markdown.sheet_heading", number=sheet["number"], place=_says("markdown.sheet_place", place=_md(place)) if place else ""), ""])
        if sheet["time"]:
            lines.append(_says("markdown.time", time=_md(sheet["time"])))
        if sheet["page_length"]:
            lines.append(_says("markdown.page_length", page_length=sheet["page_length"], seconds=sheet["seconds"]))
        lines.append(_says("markdown.shots", shots=_LIST.join(sheet["scene_ids"])))
        if sheet["summary"]:
            lines.append(_says("markdown.summary", summary=_md(sheet["summary"])))
        if sheet["cast"]:
            lines.append(_says("markdown.cast", cast=_md(_cast_line(sheet))))
        for kind, label in ELEMENT_KINDS:
            if sheet["elements"].get(kind):
                lines.append(_says("markdown.element", label=label, names=_md(_LIST.join(sheet["elements"][kind]))))
        lines.append("")
    if breakdown.get("cast"):
        lines.extend([_word("markdown.cast_heading"), "", *(str(line) for line in _table("markdown.cast_table"))])
        lines.extend(
            _says("markdown.cast_row", number=item["number"], name=_md(item["name"]), count=len(item["scenes"]), scenes=_LIST.join(item["scenes"]))
            for item in breakdown["cast"]
        )
        lines.append("")
    if breakdown.get("elements"):
        lines.extend([_word("markdown.elements_heading"), "", *(str(line) for line in _table("markdown.elements_table"))])
        lines.extend(
            _says("markdown.element_row", label=item["label"], name=_md(item["name"]), count=len(item["scenes"]), scenes=_LIST.join(item["scenes"]))
            for item in breakdown["elements"]
        )
        lines.append("")
    return "\n".join(lines)


__all__ = ["ELEMENT_KINDS", "compile_breakdown", "day_or_night", "eighths_of", "page_length", "parse_heading", "render_csv", "render_markdown"]
