"""Characters, scenes and props, one chapter at a time, into a list a person confirms.

A chapter is a document of the project's script library (its own sources first, then its own episodes), or
else a part of the written script between episode headings, or else the whole script. One text call reads one
chapter and must answer with three lists: characters, scenes, props. A list may be empty (a chapter with no one
in it gives only scenes or props), but a missing list, or an answer that is not a JSON object, means the chapter
was not extracted; it is reported, never recorded as success.

What a chapter yields goes to the project's pending list (``task["assets"]["chapter_assets"]``), merged by kind
and name with what earlier chapters gave. Nothing reaches the asset library until a person confirms an entry;
the confirming is done by the service, which creates the library asset and links it to the project. An entry
whose name the project already uses is marked ``known``.

The prompt (method first, the output contract last), lists, limits and messages are in
``app/data/prompt/chapter_assets.json``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

from app.core import prompt_data
from app.core.screenwriting.structured_llm import extract_json_object

_DATA = "chapter_assets"
KEY = "chapter_assets"
LISTS = ("characters", "scenes", "props")
ACTIONS = ("confirm", "dismiss", "restore")


class ChapterAssetError(ValueError):
    """The chapter or entry does not exist, or the model's answer cannot count as an extraction."""


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    text: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:16]


def _rules() -> dict[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> int:
    return int(_rules()["limits"][key])


def _error(key: str, **values: object) -> ChapterAssetError:
    return ChapterAssetError(str(_rules()["errors"][key]).format(**values))


def label(list_name: str) -> str:
    return str(_rules()["lists"][list_name]["label"])


def element_kind(list_name: str) -> str:
    return str(_rules()["lists"][list_name]["element_kind"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------
# Chapters


def _library_chapters(task: Mapping[str, Any]) -> list[Chapter]:
    from app.service.screenwriting_service import ordered_documents

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    documents = assets.get("2_documents") if isinstance(assets.get("2_documents"), list) else []
    found: list[Chapter] = []
    for role in ("source", "episode"):
        for document in ordered_documents(documents, role):
            text = str(document.get("content") or "").strip()
            if text and document.get("id"):
                found.append(Chapter(f"doc:{document['id']}", str(document.get("name") or document["id"]), text))
    return found


def _script_chapters(task: Mapping[str, Any]) -> list[Chapter]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    script = str(assets.get("2") or config.get("script_content") or "").strip()
    if not script:
        return []
    heading = re.compile(str(_rules()["episode_heading"]), re.MULTILINE)
    marks = list(heading.finditer(script))
    if not marks:
        return [Chapter("script", str(_rules()["whole_title"]), script)]
    parts: list[Chapter] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(script)
        text = script[mark.start():end].strip()
        line = text.splitlines()[0].strip(" #*\t")[:60] if text else ""
        if text:
            parts.append(Chapter(f"part:{index + 1}", line or str(_rules()["episode_title"]).format(number=index + 1), text))
    return parts


def chapters(task: Mapping[str, Any]) -> list[Chapter]:
    """The project's chapters in reading order: library documents, else parts of the script, else none."""
    return _library_chapters(task) or _script_chapters(task)


def chapter(task: Mapping[str, Any], chapter_id: str) -> Chapter:
    found = next((item for item in chapters(task) if item.id == chapter_id), None)
    if found is None:
        if not chapters(task):
            raise _error("no_chapters")
        raise _error("unknown_chapter", chapter=chapter_id)
    return found


# ---------------------------------------------------------------------------------------------
# The call


def _known_names(task: Mapping[str, Any]) -> dict[str, list[str]]:
    """Names the project already uses, per list: confirmed and pending entries, the catalog, the character table."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    names: dict[str, list[str]] = {name: [] for name in LISTS}
    for character in assets.get("3_characters") or []:
        if isinstance(character, Mapping) and character.get("name"):
            names["characters"].append(str(character["name"]))
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    catalog = breakdown.get("production_assets") if isinstance(breakdown.get("production_assets"), Mapping) else {}
    for list_name in ("scenes", "props"):
        for item in catalog.get(list_name) or []:
            if isinstance(item, Mapping) and item.get("name"):
                names[list_name].append(str(item["name"]))
    for item in (assets.get(KEY) or {}).get("items") or [] if isinstance(assets.get(KEY), Mapping) else []:
        if isinstance(item, Mapping) and item.get("list") in names and item.get("status") != "dismissed":
            names[str(item["list"])].append(str(item.get("name") or ""))
    return {key: list(dict.fromkeys(name for name in value if name))[: _limit("known_names")] for key, value in names.items()}


def prompt(task: Mapping[str, Any], target: Chapter) -> tuple[str, str]:
    """The system prompt (method, then the output contract) and the user prompt for one chapter."""
    rules = _rules()
    known = _known_names(task)
    known_block = ""
    if any(known.values()):
        joiner = str(rules["list_joiner"])
        known_block = str(rules["known_heading"]) + "".join(
            str(rules["known_line"]).format(label=label(name), names=joiner.join(values))
            for name, values in known.items() if values
        )
    text = target.text
    if len(text) > _limit("chapter_chars"):
        text = text[: _limit("chapter_chars")].rstrip() + str(rules["cut_note"])
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    user = str(rules["user"]).format(
        title=str(config.get("title_suggestion") or ""), chapter=target.title, known=known_block, text=text,
    )
    return f"{rules['system']}\n\n{rules['contract']}", user


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse(answer: str) -> dict[str, list[dict[str, Any]]]:
    """The three lists of an answer, or :class:`ChapterAssetError` when it cannot count as an extraction."""
    if not str(answer or "").strip():
        raise _error("no_answer")
    found = extract_json_object(answer)
    if not isinstance(found, dict):
        raise _error("not_object")
    missing = [name for name in LISTS if name not in found]
    if missing:
        raise _error("missing_lists", lists=str(_rules()["list_joiner"]).join(label(name) for name in missing))
    lists: dict[str, list[dict[str, Any]]] = {}
    for name in LISTS:
        raw = found[name]
        if not isinstance(raw, list):
            raise _error("not_list", label=label(name))
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            title = _clean(entry.get("name"), _limit("name_chars"))
            if not title or title in seen:
                continue
            seen.add(title)
            aliases = [
                alias for alias in dict.fromkeys(_clean(item, _limit("name_chars")) for item in entry.get("aliases") or [] if isinstance(item, str))
                if alias and alias != title
            ][: _limit("aliases")]
            items.append({"name": title, "aliases": aliases, "description": _clean(entry.get("description"), _limit("description_chars"))})
            if len(items) >= _limit("items_per_list"):
                break
        lists[name] = items
    return lists


# ---------------------------------------------------------------------------------------------
# The pending list


def _state(task: MutableMapping[str, Any]) -> dict[str, Any]:
    assets = task.setdefault("assets", {})
    state = assets.get(KEY)
    if not isinstance(state, dict):
        state = {"chapters": {}, "items": []}
        assets[KEY] = state
    state.setdefault("chapters", {})
    state.setdefault("items", [])
    return state


def _same(item: Mapping[str, Any], list_name: str, entry: Mapping[str, Any]) -> bool:
    if item.get("list") != list_name:
        return False
    names = {str(item.get("name") or ""), *map(str, item.get("aliases") or [])}
    return entry["name"] in names or any(alias in names for alias in entry.get("aliases") or [])


def record(task: MutableMapping[str, Any], target: Chapter, lists: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, int]:
    """Merge one chapter's lists into the pending list; returns how many entries were new per list."""
    state = _state(task)
    items: list[dict[str, Any]] = state["items"]
    added = {name: 0 for name in LISTS}
    for list_name in LISTS:
        for entry in lists.get(list_name) or []:
            same = next((item for item in items if _same(item, list_name, entry)), None)
            if same is None:
                items.append({
                    "id": uuid.uuid4().hex[:12], "list": list_name, "name": entry["name"],
                    "aliases": list(entry.get("aliases") or []), "description": entry.get("description") or "",
                    "chapters": [target.id], "status": "pending", "created_at": _now(),
                })
                added[list_name] += 1
                continue
            if target.id not in same["chapters"]:
                same["chapters"].append(target.id)
            same["aliases"] = list(dict.fromkeys([*same.get("aliases", []), *(entry.get("aliases") or [])]))[: _limit("aliases")]
            if not same.get("description") and entry.get("description"):
                same["description"] = entry["description"]
    state["chapters"][target.id] = {
        "fingerprint": target.fingerprint, "extracted_at": _now(),
        "counts": {name: len(lists.get(name) or []) for name in LISTS},
    }
    return added


def item(task: Mapping[str, Any], item_id: str) -> dict[str, Any]:
    state = (task.get("assets") or {}).get(KEY) if isinstance(task.get("assets"), Mapping) else None
    found = next((entry for entry in (state or {}).get("items") or [] if entry.get("id") == item_id), None)
    if found is None:
        raise _error("unknown_item")
    return found


def check_action(entry: Mapping[str, Any], action: str) -> None:
    """Whether ``action`` may be taken on ``entry``: confirm and dismiss a pending entry, restore a dismissed one."""
    if action not in ACTIONS:
        raise _error("unknown_action", action=action)
    status = str(entry.get("status") or "pending")
    allowed = status == "dismissed" if action == "restore" else status == "pending"
    if not allowed:
        raise _error("not_pending", state=str(_rules()["states"].get(status, status)))


def settle(task: MutableMapping[str, Any], item_id: str, action: str, *, element_id: str = "") -> dict[str, Any]:
    entry = item(task, item_id)
    check_action(entry, action)
    entry["status"] = {"confirm": "confirmed", "dismiss": "dismissed", "restore": "pending"}[action]
    entry["settled_at"] = _now()
    if element_id:
        entry["element_id"] = element_id
    return entry


def view(task: Mapping[str, Any]) -> dict[str, Any]:
    """Chapters with what each last gave and whether its text changed since, and every entry, with ``known`` set."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get(KEY) if isinstance(assets.get(KEY), Mapping) else {}
    done = state.get("chapters") or {}
    known = _known_names({**task, "assets": {**assets, KEY: {}}})
    shown_chapters = []
    for target in chapters(task):
        last = done.get(target.id) if isinstance(done.get(target.id), Mapping) else None
        shown_chapters.append({
            "id": target.id, "title": target.title, "chars": len(target.text),
            "extracted_at": last.get("extracted_at") if last else None,
            "counts": last.get("counts") if last else None,
            "changed": bool(last) and last.get("fingerprint") != target.fingerprint,
        })
    entries = []
    for entry in state.get("items") or []:
        if isinstance(entry, Mapping):
            names = {str(entry.get("name") or ""), *map(str, entry.get("aliases") or [])}
            entries.append({**entry, "label": label(str(entry.get("list"))), "known": bool(names & set(known.get(str(entry.get("list")), [])))})
    return {"chapters": shown_chapters, "items": entries, "lists": [{"id": name, "label": label(name)} for name in LISTS]}
