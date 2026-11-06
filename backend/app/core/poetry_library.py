"""The classical poetry library: public-domain verse and prose the screenwriter may quote or re-create.

The texts live as data in ``app/data/poetry/<collection>.json``, one file per author (or per work,
for a single long piece). Each entry carries the full text, the lines people actually know, the
themes and emotions it serves, and what a short drama tends to do with it. The library is read
once per process, checked on load (a famous line that is not in its text is a typo, and fails),
and searched by plain keyword matching: no model is called, so looking things up is free.

Three readers:

- the screenwriting prompts, through :func:`writer_block`, which turns the project's chosen
  sources into a budgeted "素材" block the Writer may quote or rework;
- the assistant's tools (``search_poetry`` / ``get_poem`` in :mod:`app.core.agent_tools`);
- the HTTP API (``/api/poetry``), for people browsing the shelf.

Rights: everything shipped is public domain except where an entry says ``rights: protected``;
such entries carry a ``rights_note`` the prompt and the API repeat, so a re-creation decision is
made with the facts in view.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

POETRY_DIR = Path(__file__).resolve().parents[1] / "data" / "poetry"

Form = Literal["诗", "词", "曲", "文", "经"]
Rights = Literal["public_domain", "protected"]

# The project config key: author names, aliases, collection ids or work titles the Writer may draw on.
CONFIG_KEY = "poetry_sources"
# Any of these means "the whole shelf".
ALL_SOURCES = frozenset({"全部", "all", "*", "auto", "自动"})

_SPLIT = re.compile(r"[\s,，、;；/|]+")
_PUNCT = re.compile(r"[\s，。！？；：、“”‘’（）()《》〈〉…—\-·,.!?;:\"'\[\]]+")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class PoetryLibraryError(ValueError):
    """A data file on disk is wrong; names the file and the entry so it can be fixed."""


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SLUG.pattern)
    title: str = Field(min_length=1, max_length=80)
    form: Form
    tune: str = Field(default="", max_length=40)
    preface: str = Field(default="", max_length=2000)
    text: str = Field(min_length=4, max_length=12000)
    themes: list[str] = Field(min_length=1, max_length=12)
    emotions: list[str] = Field(default_factory=list, max_length=8)
    famous_lines: list[str] = Field(default_factory=list, max_length=12)
    drama_uses: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1000)
    rights: Rights = "public_domain"
    rights_note: str = Field(default="", max_length=400)
    # False for a work added in bulk from a complete edition, its themes tagged from its imagery rather than
    # read and written by a person; the Writer is shown the curated works first.
    curated: bool = True

    @model_validator(mode="after")
    def consistent(self) -> "Entry":
        flat = _PUNCT.sub("", self.text)
        for line in self.famous_lines:
            if _PUNCT.sub("", line) not in flat:
                raise ValueError(f"《{self.title}》的名句「{line}」不在正文里")
        if self.rights == "protected" and not self.rights_note.strip():
            raise ValueError(f"《{self.title}》标为受保护作品，必须写明 rights_note")
        return self


class Collection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(pattern=_SLUG.pattern)
    author: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    dynasty: str = Field(min_length=1, max_length=20)
    profile: str = Field(default="", max_length=600)
    # The edition the texts follow (only the original text is shipped: notes, translations and modern
    # punctuated editions may carry rights of their own).
    source: str = Field(default="", max_length=300)
    entries: list[Entry] = Field(min_length=1)


@dataclass(frozen=True)
class Poem:
    """One work, with its author attached: what every reader of the library gets back."""

    key: str  # "<collection>/<entry id>"
    collection: str
    author: str
    aliases: tuple[str, ...]
    dynasty: str
    profile: str
    entry: Entry

    @property
    def title(self) -> str:
        return self.entry.title

    @property
    def names(self) -> tuple[str, ...]:
        return (self.author, *self.aliases)


@dataclass(frozen=True)
class Library:
    poems: tuple[Poem, ...]
    collections: tuple[Collection, ...]

    def get(self, key: str) -> Poem:
        for poem in self.poems:
            if poem.key == key:
                return poem
        raise LookupError(f"诗词库里没有 {key!r}")

    def by_collection(self, collection: str) -> list[Poem]:
        return [poem for poem in self.poems if poem.collection == collection]


def _normal(text: str) -> str:
    return _PUNCT.sub("", str(text or "")).lower()


def load_library(folder: Path | None = None) -> Library:
    folder = folder or POETRY_DIR
    if not folder.is_dir():
        raise PoetryLibraryError(f"诗词库目录不存在：{folder}")
    collections: list[Collection] = []
    poems: list[Poem] = []
    seen_collections: set[str] = set()
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            collection = Collection.model_validate(payload)
        except (OSError, ValueError, ValidationError) as exc:
            raise PoetryLibraryError(f"{path.name}: {exc}") from exc
        if collection.collection in seen_collections:
            raise PoetryLibraryError(f"{path.name}: 集合 id {collection.collection!r} 重复")
        seen_collections.add(collection.collection)
        ids: set[str] = set()
        for entry in collection.entries:
            if entry.id in ids:
                raise PoetryLibraryError(f"{path.name}: 作品 id {entry.id!r} 重复")
            ids.add(entry.id)
            poems.append(Poem(
                key=f"{collection.collection}/{entry.id}", collection=collection.collection, author=collection.author,
                aliases=tuple(collection.aliases), dynasty=collection.dynasty, profile=collection.profile, entry=entry,
            ))
        collections.append(collection)
    if not poems:
        raise PoetryLibraryError(f"诗词库目录里没有作品：{folder}")
    return Library(poems=tuple(poems), collections=tuple(collections))


@lru_cache(maxsize=1)
def library() -> Library:
    return load_library()


def reset() -> None:
    library.cache_clear()


# ---------------------------------------------------------------------------- search


def _terms(query: str | Sequence[str] | None) -> list[str]:
    raw = _SPLIT.split(query) if isinstance(query, str) else list(query or [])
    seen: list[str] = []
    for term in raw:
        term = _normal(term)
        if term and term not in seen:
            seen.append(term)
    return seen


def _score(poem: Poem, terms: Sequence[str]) -> int:
    if not terms:
        return 0
    entry = poem.entry
    names = [_normal(name) for name in poem.names]
    title = _normal(entry.title + entry.tune)
    themes = [_normal(item) for item in entry.themes]
    emotions = [_normal(item) for item in entry.emotions]
    famous = _normal("".join(entry.famous_lines))
    body = _normal(entry.text + entry.preface + entry.note + "".join(entry.drama_uses))
    total = 0
    for term in terms:
        if any(term in name or name in term for name in names):
            total += 5
        if term in title:
            total += 5
        if any(term == item or term in item or item in term for item in themes):
            total += 4
        if any(term == item or term in item or item in term for item in emotions):
            total += 3
        if term in famous:
            total += 3
        if term in body:
            total += 1
    return total


def _matches_author(poem: Poem, author: str) -> bool:
    wanted = _normal(author)
    return not wanted or poem.collection == author or any(wanted in _normal(name) or _normal(name) in wanted for name in poem.names)


def search(
    query: str = "",
    *,
    author: str = "",
    form: str = "",
    theme: str = "",
    emotion: str = "",
    limit: int = 20,
    lib: Library | None = None,
) -> list[Poem]:
    """Poems matching every filter, ranked by how many query terms they carry and where."""
    lib = lib or library()
    terms = _terms(query)
    limit = max(1, min(int(limit or 20), 200))
    found: list[tuple[int, int, Poem]] = []
    for index, poem in enumerate(lib.poems):
        entry = poem.entry
        if not _matches_author(poem, author):
            continue
        if form and entry.form != form:
            continue
        if theme and not any(_normal(theme) in _normal(item) for item in entry.themes):
            continue
        if emotion and not any(_normal(emotion) in _normal(item) for item in entry.emotions):
            continue
        score = _score(poem, terms)
        if terms and score == 0:
            continue
        found.append((score, index, poem))
    found.sort(key=lambda item: (-item[0], item[1]))
    return [poem for _, _, poem in found[:limit]]


# ---------------------------------------------------------------------------- describing


def find_titled(title: str, *, author: str = "", lib: Library | None = None) -> list[Poem]:
    """Works with this title (or a title containing it), optionally by this author: exact titles first."""
    lib = lib or library()
    wanted = _normal(title)
    if not wanted:
        return []
    candidates = [poem for poem in lib.poems if _matches_author(poem, author)]
    exact = [poem for poem in candidates if _normal(poem.entry.title) == wanted]
    return exact or [poem for poem in candidates if wanted in _normal(poem.entry.title)]


def summary(poem: Poem) -> dict[str, Any]:
    entry = poem.entry
    item: dict[str, Any] = {
        "id": poem.key, "title": entry.title, "author": poem.author, "dynasty": poem.dynasty, "form": entry.form,
        "tune": entry.tune, "themes": list(entry.themes), "emotions": list(entry.emotions),
        "famous_lines": list(entry.famous_lines), "drama_uses": list(entry.drama_uses), "rights": entry.rights,
    }
    if entry.rights_note:
        item["rights_note"] = entry.rights_note
    return item


def detail(poem: Poem) -> dict[str, Any]:
    item = summary(poem)
    item.update({
        "preface": poem.entry.preface, "text": poem.entry.text, "note": poem.entry.note,
        "author_aliases": list(poem.aliases), "author_profile": poem.profile, "collection": poem.collection,
    })
    return item


def authors(lib: Library | None = None) -> list[dict[str, Any]]:
    lib = lib or library()
    return [
        {
            "collection": collection.collection, "author": collection.author, "aliases": list(collection.aliases),
            "dynasty": collection.dynasty, "profile": collection.profile, "source": collection.source, "count": len(collection.entries),
            "forms": sorted({entry.form for entry in collection.entries}),
        }
        for collection in lib.collections
    ]


def themes(lib: Library | None = None) -> list[dict[str, Any]]:
    """Every theme on the shelf with how many works carry it, most common first."""
    lib = lib or library()
    counts: dict[str, int] = {}
    for poem in lib.poems:
        for theme in poem.entry.themes:
            counts[theme] = counts.get(theme, 0) + 1
    return [{"theme": theme, "count": count} for theme, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


# ---------------------------------------------------------------------------- the writer's block


def requested_sources(config: Mapping[str, Any] | None) -> list[str]:
    """The sources a project asked for, as written: a list, or one comma-separated string."""
    raw = (config or {}).get(CONFIG_KEY)
    if isinstance(raw, str):
        items = _SPLIT.split(raw)
    elif isinstance(raw, Iterable) and not isinstance(raw, (bytes, Mapping)):
        items = [str(item) for item in raw]
    else:
        items = []
    return [item.strip() for item in items if item and item.strip()]


def enabled(config: Mapping[str, Any] | None) -> bool:
    return bool(requested_sources(config))


def resolve_sources(sources: Sequence[str], lib: Library | None = None) -> tuple[list[Poem], list[str]]:
    """The poems the requested sources name (by collection id, author, alias or work title), and the names nothing matched."""
    lib = lib or library()
    if any(source.strip().lower() in ALL_SOURCES for source in sources):
        return list(lib.poems), []
    chosen: list[Poem] = []
    unknown: list[str] = []
    for source in sources:
        wanted = _normal(source)
        hits = [
            poem for poem in lib.poems
            if poem.collection == source
            or any(_normal(name) == wanted for name in poem.names)
            or _normal(poem.entry.title) == wanted
            or (_normal(poem.entry.tune) == wanted and wanted)
        ]
        if not hits:
            # A looser pass: the name inside a longer title ("岳阳楼记" inside "岳阳楼记（节选）").
            hits = [poem for poem in lib.poems if wanted and (wanted in _normal(poem.entry.title) or any(wanted in _normal(n) for n in poem.names))]
        if not hits:
            unknown.append(source)
        for poem in hits:
            if poem not in chosen:
                chosen.append(poem)
    return chosen, unknown


def _interleave(poems: Sequence[Poem]) -> list[Poem]:
    """Round-robin across authors so a wide shelf shows every voice before any author's tenth poem."""
    buckets: dict[str, list[Poem]] = {}
    for poem in poems:
        buckets.setdefault(poem.collection, []).append(poem)
    out: list[Poem] = []
    while any(buckets.values()):
        for key in list(buckets):
            if buckets[key]:
                out.append(buckets[key].pop(0))
    return out


def pick(poems: Sequence[Poem], keywords: str | Sequence[str] = "", *, limit: int = 12) -> list[Poem]:
    """The ``limit`` poems from ``poems`` that fit the story best; keyword hits first, then a spread of authors.

    Curated works come before bulk-added ones at any score: their tags were written by a person and they carry
    the famous lines the Writer can quote, where a bulk entry's tags are a keyword reading that can out-score them.
    """
    terms = _terms(keywords)
    limit = max(1, int(limit))
    scored = sorted(
        ((_score(poem, terms), index, poem) for index, poem in enumerate(poems)),
        key=lambda item: (not item[2].entry.curated, -item[0], item[1]),
    )
    matched = [poem for score, _, poem in scored if score > 0]
    rest = [poem for score, _, poem in scored if score == 0]
    chosen = _interleave(matched)[:limit]
    if len(chosen) < limit:
        chosen += _interleave(rest)[: limit - len(chosen)]
    return chosen


def render_poem(poem: Poem, *, full: bool = False) -> str:
    """One work as the prompt shows it: title, author, the famous lines (or the whole text) and what it is for."""
    entry = poem.entry
    head = f"《{entry.title}》（{poem.dynasty}·{poem.author}，{entry.form}）"
    lines = [head]
    if full:
        if entry.preface:
            lines.append(f"序：{entry.preface}")
        lines.append(entry.text)
    elif entry.famous_lines:
        lines.append("名句：" + "／".join(entry.famous_lines))
    else:
        lines.append(entry.text.splitlines()[0])
    if entry.themes:
        lines.append("题旨：" + "、".join(entry.themes) + ("；情绪：" + "、".join(entry.emotions) if entry.emotions else ""))
    if entry.drama_uses:
        lines.append("可用于：" + "；".join(entry.drama_uses))
    if entry.rights_note:
        lines.append("版权提示：" + entry.rights_note)
    return "\n".join(lines)


MATERIALS_HEADER = "【诗词库·可取材素材】"
TRUNCATION_MARK = "（素材清单已按预算截断）"


def materials_block(
    poems: Sequence[Poem],
    *,
    budget: int = 3000,
    intro: str = "",
) -> str:
    """The chosen poems rendered under a character budget, whole entries only, never a cut line."""
    if not poems:
        return ""
    parts = [MATERIALS_HEADER]
    if intro:
        parts.append(intro)
    used = sum(len(part) + 1 for part in parts)
    shown = 0
    for poem in poems:
        block = render_poem(poem)
        if budget > 0 and used + len(block) + 2 + len(TRUNCATION_MARK) > budget and shown:
            parts.append(TRUNCATION_MARK)
            break
        parts.append(block)
        used += len(block) + 2
        shown += 1
    return "\n\n".join(parts)


def writer_block(
    config: Mapping[str, Any] | None,
    *,
    keywords: str | Sequence[str] = "",
    budget: int = 3000,
    limit: int = 12,
    lib: Library | None = None,
) -> str:
    """The block the Writer's prompt carries when the project named poetry sources; empty otherwise."""
    sources = requested_sources(config)
    if not sources:
        return ""
    lib = lib or library()
    poems, unknown = resolve_sources(sources, lib)
    if not poems:
        return ""
    chosen = pick(poems, keywords, limit=limit)
    names = "、".join(dict.fromkeys(poem.author for poem in chosen))
    intro = (
        f"本项目指定取材：{names}。下面每条给出名句与用法。引用只用这里给出的文字，不要凭记忆补写名句以外的句子"
        "（能调用工具时可用 get_poem 取全文）；化用须保留原句的意象与节奏；不要把作者或朝代张冠李戴。"
    )
    if unknown:
        intro += f"（诗词库里没有：{'、'.join(unknown)}）"
    return materials_block(chosen, budget=budget, intro=intro)


__all__ = [
    "ALL_SOURCES", "CONFIG_KEY", "Collection", "Entry", "Library", "MATERIALS_HEADER", "POETRY_DIR", "Poem", "find_titled",
    "PoetryLibraryError", "authors", "detail", "enabled", "library", "load_library", "materials_block", "pick",
    "render_poem", "requested_sources", "reset", "resolve_sources", "search", "summary", "themes", "writer_block",
]
