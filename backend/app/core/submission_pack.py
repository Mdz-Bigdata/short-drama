# -*- coding: utf-8 -*-
"""Submission pack: a project laid out as the platform's AI-drama script attachment (剧本附件).

The attachment has thirteen items in a fixed order. Most come straight from the project:

* the script body is the storyboard-ready plan rewritten in the template's layout — 「第一集」, 「1-1 乱葬岗 夜 外」
  (the scene numbers of the script breakdown), 出场人物, △ action lines, 「人物（语气）：台词」, OS / VO lines,
  a caption the first time a person or a place appears, and 「（本集完）」. Shooting notes (shot sizes, camera
  positions, light setups) are taken out of the action lines, as the template asks. No model is called for it.
* the title, whether it is adapted, the episode count are read from the project.

The judgement items — audience, world, category, the paywall episode, the synopsis, the outline in blocks of
episodes and the main characters — are written by the project's text model from a digest of the project, checked
(options, ranges, lengths, names) and kept in ``assets["2_submission"]`` with a fingerprint of that digest, so a
changed script shows the pack as stale instead of silently disagreeing with it.

Every sentence, label, word list and limit is ``app/data/prompt/submission_pack.json``.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.core import prompt_data, script_breakdown, target_audience
from app.core.screenwriting.structured_llm import call_structured
from app.core.writer_dashboard import episode_from_scene_id, resolve_drama_title

_WORDING = "submission_pack"
ASSET_KEY = "2_submission"
STORE_VERSION = 1

LLMCaller = Callable[[str, str, int], str]


def _entry(key: str) -> Any:
    """The entry at the dotted ``key`` of the wording table."""
    node: Any = prompt_data.load(_WORDING)
    for part in key.split("."):
        node = node[part]
    return node


def _says(key: str, /, **values: object) -> str:
    """A template of the wording table, filled in; a list is a template of several lines."""
    entry = _entry(key)
    return ("\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)).format(**values)


def _word(key: str) -> str:
    """A word or label of the wording table, used as it stands."""
    return str(_entry(key))


def _table(key: str) -> Any:
    """A table or number of the wording table, used as it stands."""
    return _entry(key)


def _pattern(key: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(_word(key), flags)


def _text(value: object, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _length(text: str) -> int:
    """Characters as a reviewer counts them: everything but whitespace."""
    return len(re.sub(r"\s+", "", text or ""))


# --------------------------------------------------------------------------- numbers


def chinese_number(number: int) -> str:
    """1 → 一, 12 → 十二, 20 → 二十, 105 → 一百零五, 110 → 一百一十 (episode headings stop at 999)."""
    digits = _table("numerals.digits")
    ten, hundred = _word("numerals.ten"), _word("numerals.hundred")
    number = max(0, min(int(number), 999))
    if number < 10:
        return digits[number]
    if number < 20:
        return ten + (digits[number % 10] if number % 10 else "")
    if number < 100:
        return digits[number // 10] + ten + (digits[number % 10] if number % 10 else "")
    rest = number % 100
    head = digits[number // 100] + hundred
    if not rest:
        return head
    if rest < 10:
        return head + digits[0] + digits[rest]
    return head + digits[rest // 10] + ten + (digits[rest % 10] if rest % 10 else "")


# --------------------------------------------------------------------------- the project


def _state(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get("2_screenwriting")
    return state if isinstance(state, Mapping) else {}


def _overview(task: Mapping[str, Any]) -> Mapping[str, Any]:
    overview = _state(task).get("overview")
    return overview if isinstance(overview, Mapping) else {}


def _ledger(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [row for row in _state(task).get("ledger") or [] if isinstance(row, Mapping)]
    return sorted(rows, key=lambda row: int(row.get("episode") or 0))


def roster(task: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """The named characters, lead first as the writer listed them: name → {description, position}."""
    inventory = _state(task).get("inventory") if isinstance(_state(task).get("inventory"), Mapping) else {}
    people = inventory.get("characters") if isinstance(inventory.get("characters"), Mapping) else {}
    if people:
        return {str(name): (value if isinstance(value, Mapping) else {}) for name, value in people.items() if str(name).strip()}
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    return {
        str(item.get("name")): {"description": item.get("desc") or item.get("description") or ""}
        for item in assets.get("3_characters") or [] if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    }


def title_of(task: Mapping[str, Any]) -> str:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return resolve_drama_title(_overview(task).get("title"), str(assets.get("2") or "")[:20000], config.get("title_suggestion"))


def episode_count(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]] = ()) -> int:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    counted = [
        len(_ledger(task)),
        int(_state(task).get("episode_count") or 0),
        int(config.get("episode_count") or 0),
        max((episode_from_scene_id(str(scene.get("scene_id") or "")) for scene in scenes), default=0),
    ]
    return max(counted)


def chosen_channel(task: Mapping[str, Any]) -> str:
    """男频 / 女频 when the creator chose the audience at creation (config.target_audience); empty when not."""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return str(_table("options.lean_channels").get(target_audience.of(config).get("lean") or "", ""))


def adaptation(task: Mapping[str, Any]) -> str:
    """The novel's name when the project was cut from a novel; empty for an original or the author's own script."""
    if str(_state(task).get("source_kind") or "") != "novel":
        return ""
    for row in _ledger(task):
        name = _text(row.get("source_name"), 80)
        if name:
            return name.rsplit(".", 1)[0]
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return _text(config.get("script_name"), 80).rsplit(".", 1)[0]


# --------------------------------------------------------------------------- the script body


def action_sentences(description: str) -> list[str]:
    """The action as one sentence a line, with the shooting notes (「竖屏特写」「雨幕侧逆光」) taken out."""
    camera = [str(word) for word in _table("body.camera_words")]
    short = int(_table("body.camera_clause_max"))
    joiner = _word("body.clause_joiner")
    sentences: list[str] = []
    for match in _pattern("body.sentence_pattern").finditer(description or ""):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        end = sentence[-1] if _pattern("body.sentence_end").fullmatch(sentence[-1]) else ""
        body = sentence[:-1] if end else sentence
        clauses = [part.strip() for part in _pattern("body.clause_split").split(body) if part.strip()]
        for index, clause in enumerate(clauses):
            # 「特写：虎口上方三寸…」: a shot label in front of the action goes, the action stays.
            head, *tail = _pattern("body.label_split").split(clause, maxsplit=1)
            if tail and tail[0].strip() and len(head) <= short and any(word in head for word in camera):
                clauses[index] = tail[0].strip()
        kept = [clause for clause in clauses if not (len(clause) <= short and any(word in clause for word in camera))]
        if kept:
            sentences.append(joiner.join(kept) + end)
    return sentences


def dialogue_line(item: Mapping[str, Any]) -> str:
    """One spoken line in the template's form; the delivery note is its first part, at most ``note_max`` characters."""
    text = _text(item.get("text"), 500)
    if not text:
        return ""
    speaker = _text(item.get("speaker"), 40)
    if item.get("kind") != "dialogue" or not speaker:
        return _says("body.narration", text=text)
    parts = [part for part in _pattern("body.delivery_split").split(_text(item.get("delivery"), 200)) if part]
    inner = bool(parts) and parts[0].upper() in {str(word).upper() for word in _table("body.inner_labels")}
    off = bool(parts) and parts[0].upper() in {str(word).upper() for word in _table("body.off_screen_labels")}
    if inner or off:
        parts = parts[1:]
    note = parts[0][: int(_table("body.note_max"))] if parts else ""
    if inner:
        return _says("body.inner_voice", speaker=speaker, note=note, text=text)
    if off:
        return _says("body.off_screen_noted", speaker=speaker, note=note, text=text) if note else _says("body.off_screen", speaker=speaker, text=text)
    return _says("body.dialogue_noted", speaker=speaker, note=note, text=text) if note else _says("body.dialogue", speaker=speaker, text=text)


def _introduce(sentence: str, waiting: dict[str, str]) -> str:
    """Put a person's caption right after the first time the action names them; ``waiting`` loses whoever got one."""
    for name in sorted(waiting, key=len, reverse=True):
        at = sentence.find(name)
        if at < 0:
            continue
        caption = _says("body.caption", text=waiting.pop(name))
        sentence = sentence[: at + len(name)] + caption + sentence[at + len(name):]
    return sentence


def script_body(
    task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], identities: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Episodes of scenes of lines, in the template's layout; scene numbers and places are the breakdown's."""
    breakdown = script_breakdown.compile_breakdown(task, scenes)
    shots = {str(scene.get("scene_id") or ""): scene for scene in scenes if isinstance(scene, Mapping)}
    identity_max = int(_table("body.identity_max"))
    waiting = {
        name: (_says("body.person_caption", name=name, identity=_text((identities or {}).get(name), identity_max))
               if _text((identities or {}).get(name)) else name)
        for name in roster(task)
    }
    seen_places: set[str] = set()
    episodes: dict[int, list[dict[str, Any]]] = {}
    sides = _table("body.sides")
    for sheet in breakdown.get("scenes") or []:
        cast = [str(person.get("name")) for person in sheet.get("cast") or [] if person.get("name")]
        lines: list[str] = []
        place = _text(sheet.get("location"), 60)
        # A place gets its caption once: 「演武场 廊下」 after 「演武场」 is the same place.
        main_place = place.split(" ")[0] if place else ""
        if main_place and main_place not in seen_places:
            seen_places.add(main_place)
            lines.append(_says("body.caption", text=main_place))
        for scene_id in sheet.get("scene_ids") or []:
            shot = shots.get(str(scene_id)) or {}
            for sentence in action_sentences(str(shot.get("description") or shot.get("content") or "")):
                lines.append(_says("body.action", text=_introduce(sentence, waiting)))
            for item in shot.get("dialogue") or []:
                if isinstance(item, Mapping):
                    speaker = _text(item.get("speaker"), 40)
                    if item.get("kind") == "dialogue" and speaker and speaker not in cast:
                        cast.append(speaker)
                    line = dialogue_line(item)
                    if line:
                        lines.append(line)
        heading = _says(
            "body.scene_heading", number=sheet.get("number") or "",
            place=" ".join(part for part in (place, _text(sheet.get("time"), 20)) if part), side=sides.get(str(sheet.get("int_ext") or ""), ""),
        ).strip()
        episodes.setdefault(int(sheet.get("episode") or 1), []).append({"heading": heading, "cast": cast, "lines": lines})
    return [{"episode": number, "scenes": episodes[number]} for number in sorted(episodes)]


def body_lines(body: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    separator = _word("body.name_separator")
    for episode in body:
        lines.append(_says("body.episode_heading", number=chinese_number(int(episode["episode"]))))
        for scene in episode.get("scenes") or []:
            lines.append(scene["heading"])
            if scene.get("cast"):
                lines.append(_says("body.cast", names=separator.join(scene["cast"])))
            lines.extend(scene.get("lines") or [])
            lines.append("")
        lines.extend([_word("body.episode_end"), ""])
    return lines


# --------------------------------------------------------------------------- what the model writes


class _Person(BaseModel):
    name: str = Field(description=_word("model.schema.name"))
    gender: str = Field(description=_word("model.schema.gender"))
    age: str = Field(description=_word("model.schema.age"))
    identity: str = Field(description=_word("model.schema.identity"))
    personality: str = Field(description=_word("model.schema.personality"))
    intro: str = Field(description=_word("model.schema.intro"))


class _Details(BaseModel):
    channel: str = Field(description=_word("model.schema.channel"))
    world: str = Field(description=_word("model.schema.world"))
    category: str = Field(description=_word("model.schema.category"))
    paywall_episode: int = Field(description=_word("model.schema.paywall_episode"))
    paywall_reason: str = Field(description=_word("model.schema.paywall_reason"))
    premiere_hook: str = Field(default="", description=_word("model.schema.premiere_hook"))
    synopsis: str = Field(description=_word("model.schema.synopsis"))
    characters: list[_Person] = Field(description=_word("model.schema.characters"))


class _Outline(BaseModel):
    outline: str = Field(description=_word("model.schema.outline"))


def digest(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]] = (), *, episodes: range | None = None, beats: int | None = None) -> str:
    """The project as the model reads it; ``episodes`` narrows the per-episode part, ``beats`` caps the beats per episode."""
    overview = _overview(task)
    beat_chars = int(_table("limits.beat_chars"))
    beats = int(_table("limits.beats_per_episode")) if beats is None else beats
    novel = adaptation(task)
    kind = str(_state(task).get("source_kind") or "outline")
    sources = _table("digest.sources")
    if kind == "novel":
        source = _says("digest.sources.novel", name=novel) if novel else _word("digest.sources.novel_unnamed")
    else:
        source = str(sources.get(kind) or sources["outline"])
    lines = [
        _says("digest.title", title=title_of(task)),
        _says("digest.episodes", count=episode_count(task, scenes)),
        _says("digest.source", source=source),
    ]
    for key, field in (("genre", "genre"), ("theme", "theme"), ("world", "world_setting"), ("synopsis", "synopsis")):
        text = _text(overview.get(field), 1500)
        if text:
            lines.append(_fill_overview(key, text))
    people = roster(task)
    if people:
        lines.append(_word("digest.people"))
        for name, person in people.items():
            lines.append(_says(
                "digest.person", name=name, position=_text(person.get("position"), 20) or "-",
                description=_text(person.get("description"), 300),
            ))
    inventory = _state(task).get("inventory") if isinstance(_state(task).get("inventory"), Mapping) else {}
    relations = [
        _says("digest.relation", first=_text(edge.get("from_") or edge.get("from"), 20), second=_text(edge.get("to"), 20), relation=_text(edge.get("relation"), 20))
        for edge in inventory.get("relationships") or [] if isinstance(edge, Mapping) and edge.get("to")
    ]
    if relations:
        lines.append(_says("digest.relations", text=_word("digest.beat_separator").join(relations[:30])))
    rows = [row for row in _ledger(task) if episodes is None or int(row.get("episode") or 0) in episodes]
    if rows:
        lines.append(_word("digest.episodes_heading"))
        for row in rows:
            picked = [_text(beat, beat_chars) for beat in (row.get("story_beats") or [])[:beats] if _text(beat)]
            lines.append(_says(
                "digest.episode", episode=int(row.get("episode") or 0), title=_text(row.get("title"), 60),
                beats=_word("digest.beat_separator").join(picked), hook=_text(row.get("hook"), beat_chars * 2),
            ))
    elif scenes:
        lines.append(_word("digest.episodes_heading"))
        by_episode: dict[int, list[str]] = {}
        for scene in scenes:
            number = episode_from_scene_id(str(scene.get("scene_id") or ""))
            if episodes is None or number in episodes:
                by_episode.setdefault(number, []).append(_text(scene.get("description") or scene.get("content"), beat_chars))
        for number in sorted(by_episode):
            lines.append(_says(
                "digest.episode", episode=number, title="", beats=_word("digest.beat_separator").join(by_episode[number][: max(beats, 1) * 2]), hook="",
            ))
    return "\n".join(lines)


def _fill_overview(key: str, text: str) -> str:
    if key == "genre":
        return _says("digest.genre", text=text)
    if key == "theme":
        return _says("digest.theme", text=text)
    if key == "world":
        return _says("digest.world", text=text)
    return _says("digest.synopsis", text=text)


def fingerprint(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]] = ()) -> str:
    return hashlib.sha256(digest(task, scenes).encode("utf-8")).hexdigest()[:32]


def _is_serial(count: int) -> bool:
    return count >= int(_table("limits.serial_min_episodes"))


def _details_validator(count: int, names: Sequence[str], fixed_channel: str = "") -> Callable[[dict[str, Any]], list[str]]:
    channels = [str(option) for option in _table("options.channels")]
    low, high = (int(value) for value in _table("limits.synopsis"))
    intro_low, intro_high = (int(value) for value in _table("limits.intro"))
    limit = int(_table("limits.max_characters"))
    serial = _is_serial(count)

    def check(data: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        data["channel"] = fixed_channel or _text(data.get("channel"), 10)
        if data["channel"] not in channels:
            reasons.append(_says("model.reasons.channel", options="/".join(channels)))
        if not 1 <= int(data.get("paywall_episode") or 0) <= count:
            reasons.append(_says("model.reasons.paywall", episodes=count))
        size = _length(data.get("synopsis") or "")
        if not low <= size <= high:
            reasons.append(_says("model.reasons.length", field="synopsis", count=size, low=low, high=high))
        people = data.get("characters") or []
        if not people:
            reasons.append(_word("model.reasons.no_people"))
        if len(people) > limit:
            reasons.append(_says("model.reasons.too_many", limit=limit))
        for person in people:
            name = _text(person.get("name"), 40)
            if name not in names:
                reasons.append(_says("model.reasons.unknown_person", name=name))
            size = _length(person.get("intro") or "")
            if not intro_low <= size <= intro_high:
                reasons.append(_says("model.reasons.length", field=f"characters[{name}].intro", count=size, low=intro_low, high=intro_high))
        hook = _text(data.get("premiere_hook"), 2000)
        if serial and not hook:
            reasons.append(_word("model.reasons.premiere"))
        if not serial:
            data["premiere_hook"] = ""
        return reasons

    return check


def _outline_validator(field_name: str) -> Callable[[dict[str, Any]], list[str]]:
    low, high = (int(value) for value in _table("limits.outline"))

    def check(data: dict[str, Any]) -> list[str]:
        size = _length(data.get("outline") or "")
        return [] if low <= size <= high else [_says("model.reasons.length", field=field_name, count=size, low=low, high=high)]

    return check


def outline_blocks(count: int) -> list[tuple[int, int]]:
    size = max(1, int(_table("limits.outline_block")))
    return [(first, min(first + size - 1, count)) for first in range(1, count + 1, size)]


def write(caller: LLMCaller, task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], *, max_tokens: int) -> dict[str, Any]:
    """The judgement items, checked: one call for the details, one per block of episodes for the outline."""
    count = max(1, episode_count(task, scenes))
    title = title_of(task)
    names = list(roster(task))
    synopsis_low, synopsis_high = (int(value) for value in _table("limits.synopsis"))
    intro_low, intro_high = (int(value) for value in _table("limits.intro"))
    fixed = chosen_channel(task)
    channels = "/".join(str(option) for option in _table("options.channels"))
    details = call_structured(
        caller,
        system_prompt=_word("model.system"),
        user_prompt=_says(
            "model.details_task", title=title, episodes=count, digest=digest(task, scenes, beats=int(_table("limits.detail_beats"))),
            channel_rule=_says("model.channel_fixed", channel=fixed) if fixed else _says("model.channel_free", channels=channels),
            worlds="/".join(str(option) for option in _table("options.worlds")),
            categories="/".join(str(option) for option in _table("options.categories")),
            serial_rule=_word("model.serial_rule") if _is_serial(count) else _word("model.not_serial"),
            synopsis_min=synopsis_low, synopsis_max=synopsis_high, max_characters=int(_table("limits.max_characters")),
            intro_min=intro_low, intro_max=intro_high,
        ),
        schema=_Details, max_tokens=max_tokens, validators=[_details_validator(count, names, fixed)], label="submission_details",
    ).data
    outline_low, outline_high = (int(value) for value in _table("limits.outline"))
    outline = []
    for first, last in outline_blocks(count):
        result = call_structured(
            caller,
            system_prompt=_word("model.system"),
            user_prompt=_says(
                "model.outline_task", title=title, episodes=count, first=first, last=last, min=outline_low, max=outline_high,
                digest=digest(task, scenes, episodes=range(first, last + 1)),
            ),
            schema=_Outline, max_tokens=max_tokens, validators=[_outline_validator(f"{first}-{last}")], label="submission_outline",
        ).data
        outline.append({"first": first, "last": last, "text": _text(result.get("outline"), 2000)})
    return {
        "version": STORE_VERSION,
        "fingerprint": fingerprint(task, scenes),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "details": details,
        "outline": outline,
    }


# --------------------------------------------------------------------------- the pack


def offline_text() -> str:
    return _word("model.offline")


def not_found_text() -> str:
    return _word("document.not_found")


def stored(task: Mapping[str, Any]) -> Mapping[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    value = assets.get(ASSET_KEY)
    return value if isinstance(value, Mapping) and value.get("version") == STORE_VERSION else None


def compile_pack(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Everything the attachment says; ``details`` is empty until the model items were written."""
    kept = stored(task)
    details = dict(kept.get("details") or {}) if kept else {}
    identities = {str(person.get("name")): str(person.get("identity") or "") for person in details.get("characters") or [] if isinstance(person, Mapping)}
    count = max(1, episode_count(task, scenes))
    return {
        "title": title_of(task),
        "adapted_from": adaptation(task),
        "episodes": count,
        "serial": _is_serial(count),
        # The creator's own choice wins over what the model wrote, also when it was changed afterwards.
        "channel": chosen_channel(task) or _text(details.get("channel"), 10),
        "details": details,
        "outline": list(kept.get("outline") or []) if kept else [],
        "body": script_body(task, scenes, identities),
        "ready": bool(details),
        "stale": bool(kept) and kept.get("fingerprint") != fingerprint(task, scenes),
        "built_at": str(kept.get("built_at") or "") if kept else "",
    }


def _items(pack: Mapping[str, Any]) -> list[tuple[str, str | list[str]]]:
    """The attachment's twelve items before the body, as (label, value or lines)."""
    details = pack.get("details") or {}
    missing = _word("document.missing")
    labels = _table("document.labels")
    adapted = str(pack.get("adapted_from") or "")
    paywall = (
        _says("document.paywall", episode=details.get("paywall_episode"), reason=_text(details.get("paywall_reason"), 600))
        if details.get("paywall_episode") else missing
    )
    if not pack.get("serial"):
        premiere = _word("document.not_serial")
    else:
        premiere = _text(details.get("premiere_hook"), 2000) or missing
    outline: list[str] = []
    for block in pack.get("outline") or []:
        outline.extend([_says("document.outline_block", first=block.get("first"), last=block.get("last")), _text(block.get("text"), 2000)])
    people: list[str] = []
    fields = _table("document.person_fields")
    for number, person in enumerate(details.get("characters") or [], start=1):
        people.append(_says("document.person_heading", number=chinese_number(number), name=_text(person.get("name"), 40)))
        for field in ("gender", "age", "identity", "personality", "intro"):
            people.append(_says("document.person_field", label=fields[field], value=_text(person.get(field), 400)))
    return [
        (labels["title"], str(pack.get("title") or "")),
        (labels["ip"], _word("document.yes") if adapted else _word("document.no")),
        (labels["ip_source"], _says("document.ip_name", name=adapted) if adapted else _word("document.none")),
        (labels["channel"], str(pack.get("channel") or "") or missing),
        (labels["world"], _text(details.get("world"), 20) or missing),
        (labels["category"], _text(details.get("category"), 20) or missing),
        (labels["episodes"], _says("document.episodes", count=pack.get("episodes"))),
        (labels["paywall"], paywall),
        (labels["premiere"], premiere),
        (labels["synopsis"], _text(details.get("synopsis"), 2000) or missing),
        (labels["outline"], outline or missing),
        (labels["characters"], people or missing),
    ]


def _notes(pack: Mapping[str, Any]) -> list[str]:
    notes = []
    if not pack.get("ready"):
        notes.append(_word("document.missing_note"))
    elif pack.get("stale"):
        notes.append(_word("document.stale_note"))
    return notes


def render_markdown(pack: Mapping[str, Any]) -> str:
    lines = [f"# {_says('document.title', title=pack.get('title') or '')}", ""]
    for note in _notes(pack):
        lines.extend([f"> {note}", ""])
    lines.extend([f"## {_word('document.attachment_heading')}", ""])
    for number, (label, value) in enumerate(_items(pack), start=1):
        if isinstance(value, list):
            lines.append(_says("document.item", number=number, label=label, value=""))
            lines.extend(["", *value, ""])
        else:
            lines.append(_says("document.item", number=number, label=label, value=value))
    lines.extend(["", _says("document.item", number=13, label=_table("document.labels")["body"], value=""), ""])
    lines.extend(body_lines(pack.get("body") or []))
    return "\n".join(lines).rstrip() + "\n"


def render_docx(pack: Mapping[str, Any]) -> bytes:
    """The same attachment as a Word document (the platform takes .docx; a Lark doc imports it)."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.size = Pt(11)
    style.font.name = _word("document.docx_font")
    style.element.rPr.rFonts.set(qn("w:eastAsia"), _word("document.docx_font"))
    document.add_heading(_says("document.title", title=pack.get("title") or ""), level=1)
    for note in _notes(pack):
        document.add_paragraph().add_run(note).italic = True
    document.add_heading(_word("document.attachment_heading"), level=2)
    for number, (label, value) in enumerate(_items(pack), start=1):
        if isinstance(value, list):
            document.add_paragraph().add_run(_says("document.item", number=number, label=label, value="")).bold = True
            for line in value:
                document.add_paragraph(line)
        else:
            paragraph = document.add_paragraph()
            paragraph.add_run(_says("document.item", number=number, label=label, value="")).bold = True
            paragraph.add_run(value)
    document.add_heading(_says("document.item", number=13, label=_table("document.labels")["body"], value=""), level=2)
    headings = {_says("body.episode_heading", number=chinese_number(int(episode["episode"]))) for episode in pack.get("body") or []}
    scene_headings = {scene["heading"] for episode in pack.get("body") or [] for scene in episode.get("scenes") or []}
    for line in body_lines(pack.get("body") or []):
        if not line:
            continue
        paragraph = document.add_paragraph()
        paragraph.add_run(line).bold = line in headings or line in scene_headings
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = [
    "ASSET_KEY", "action_sentences", "not_found_text", "offline_text", "body_lines", "chinese_number", "compile_pack", "dialogue_line", "digest", "fingerprint",
    "outline_blocks", "render_docx", "render_markdown", "roster", "script_body", "stored", "write",
]
