# -*- coding: utf-8 -*-
"""The market: browse and install endpoint definitions from market sources, with no central service.

A *market source* is a GitHub repository (or any ``https://`` directory) that
serves an index file and, beside it, one definition file per *market entry*.
Browsing reads the cached index; installing fetches that one definition, checks
it against the index, and lands it as an ordinary declarative video endpoint
plus an *install record* that says which source and entry it came from. The
record is its own entity: deleting the source does not touch it, the installed
endpoint stays editable, and the two axes of its state are kept apart —
market (latest / update available / no longer in the market) and local
(modified since install). Uninstalling is deleting the endpoint.

Nothing here talks to a GitHub API: every fetch is a raw file address, so a
single optional proxy prefix covers all GitHub traffic. Fetches go out on the
person's behalf, so they are bounded like any server-side request: HTTPS only,
public addresses only, a few redirects, a size cap, a timeout. Versions are
compared for equality only; the market is a user feature and the embedded
agent neither browses nor installs it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import settings
from app.core.providers.declarative_video import VideoEndpointSpec

logger = logging.getLogger("app.core.market")

INDEX_SCHEMA_FAMILY = "short-drama-market"
INDEX_SCHEMA_MAJOR = 1
INDEX_SCHEMA = f"{INDEX_SCHEMA_FAMILY}/{INDEX_SCHEMA_MAJOR}"
INDEX_FILENAME = "market-index.json"
ENTRY_KINDS = ("video_endpoint",)
SOURCES_KEY = "market_sources"
INSTALLS_KEY = "market_installs"
ENDPOINTS_KEY = "video_endpoints"
OFFICIAL_SOURCE_ENV = "MARKET_OFFICIAL_SOURCE_URL"
RAW_PROXY_ENV = "MARKET_RAW_PROXY_PREFIX"
RAW_GITHUB_HOST = "raw.githubusercontent.com"

MAX_INDEX_BYTES = 1_000_000
MAX_DEFINITION_BYTES = 262_144
MAX_REDIRECTS = 3
FETCH_TIMEOUT_SECONDS = 15.0

EntryKind = Literal["video_endpoint"]
MarketStatus = Literal["latest", "update_available", "unavailable"]

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_GITHUB_REPO = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/tree/([^/]+))?/?$")


class MarketError(ValueError):
    """A market operation the person asked for cannot be done; the message says why."""

    def __init__(self, message: str, *, code: str = "market_error", status: int = 400, **details: Any):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details


# ---------------------------------------------------------------- schemas


class MarketEntry(BaseModel):
    """One installable item as the index lists it; the payload lives at ``path``."""

    model_config = ConfigDict(extra="ignore")

    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    kind: EntryKind = "video_endpoint"
    path: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=600)
    author: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=12)
    min_app_version: str = Field(default="", max_length=40)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError("slug 只能是小写字母、数字和连字符，且以字母或数字开头")
        return value

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        clean = value.strip()
        parts = clean.split("/")
        if clean.startswith("/") or "\\" in clean or "://" in clean or any(part in ("", ".", "..") for part in parts):
            raise ValueError("path 必须是源内的相对路径，不能含 .. 或绝对地址")
        return clean


class MarketIndex(BaseModel):
    """The index a market source publishes. Unknown optional fields are ignored so older
    clients keep reading newer indexes; only a higher major version is refused outright."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_id: str = Field(alias="schema", min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    entries: list[MarketEntry] = Field(default_factory=list, max_length=500)

    @field_validator("schema_id")
    @classmethod
    def supported_schema(cls, value: str) -> str:
        family, _, major = value.partition("/")
        if family != INDEX_SCHEMA_FAMILY or not major.isdigit():
            raise ValueError(f"索引 schema 必须是 {INDEX_SCHEMA_FAMILY}/<主版本>")
        if int(major) > INDEX_SCHEMA_MAJOR:
            raise ValueError(f"索引 schema 主版本 {major} 高于本客户端支持的 {INDEX_SCHEMA_MAJOR}，请升级应用")
        return value

    @field_validator("entries")
    @classmethod
    def unique_slugs(cls, entries: list[MarketEntry]) -> list[MarketEntry]:
        seen: set[str] = set()
        for entry in entries:
            if entry.slug in seen:
                raise ValueError(f"索引里 slug 重复：{entry.slug}")
            seen.add(entry.slug)
        return entries


class DefinitionMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    kind: EntryKind = "video_endpoint"
    author: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=600)


class EntryDefinition(BaseModel):
    """The payload of an entry: who it is (``meta``) and the endpoint spec itself."""

    model_config = ConfigDict(extra="ignore")

    meta: DefinitionMeta
    spec: dict[str, Any]


def parse_index(raw: bytes | str | Mapping[str, Any]) -> MarketIndex:
    try:
        data = raw if isinstance(raw, Mapping) else json.loads(raw)
        return MarketIndex.model_validate(data)
    except (ValueError, TypeError) as exc:  # json and pydantic errors both read as ValueError
        raise MarketError(f"市场索引不可用：{_short(exc)}", code="bad_index") from exc


def parse_definition(raw: bytes | str | Mapping[str, Any]) -> EntryDefinition:
    try:
        data = raw if isinstance(raw, Mapping) else json.loads(raw)
        definition = EntryDefinition.model_validate(data)
    except (ValueError, TypeError) as exc:
        raise MarketError(f"条目定义不可用：{_short(exc)}", code="bad_definition") from exc
    return definition


def _short(exc: BaseException) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", ()))
        return f"{loc or '(root)'}: {first.get('msg', '')}"
    return str(exc)[:300]


def spec_digest(spec: Mapping[str, Any]) -> str:
    """A stable fingerprint of a spec, so a local edit after install can be told apart."""
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- sources


@dataclass(frozen=True)
class ResolvedSource:
    key: str          # canonical: github:owner/repo@branch or url:<index url>
    kind: str         # github | direct
    base_url: str     # where entry paths are resolved from (ends with /)
    index_url: str
    label: str


def source_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def resolve_source(url: str) -> ResolvedSource:
    """A GitHub repository page or a direct index link → where its raw files live."""
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise MarketError("市场源地址必须是 https:// 开头的 GitHub 仓库或索引直链", code="bad_source_url")
    host = parsed.hostname.lower()
    if host in ("github.com", "www.github.com"):
        match = _GITHUB_REPO.match(parsed.path)
        if not match:
            raise MarketError("GitHub 市场源请给仓库地址，如 https://github.com/owner/repo 或 …/tree/branch", code="bad_source_url")
        owner, repo, branch = match.group(1), match.group(2), match.group(3) or "main"
        base = f"https://{RAW_GITHUB_HOST}/{owner}/{repo}/{branch}/"
        return ResolvedSource(key=f"github:{owner}/{repo}@{branch}", kind="github", base_url=base, index_url=base + INDEX_FILENAME, label=f"{owner}/{repo}")
    path = parsed.path or "/"
    if not path.endswith(".json"):
        path = path.rstrip("/") + "/" + INDEX_FILENAME
    index_url = urlunsplit(("https", parsed.netloc.lower(), path, "", ""))
    base = index_url.rsplit("/", 1)[0] + "/"
    return ResolvedSource(key=f"url:{index_url}", kind="direct", base_url=base, index_url=index_url, label=host)


def raw_proxied(url: str) -> str:
    """The address to actually fetch: GitHub raw files may go through one configured proxy prefix."""
    prefix = (os.getenv(RAW_PROXY_ENV) or "").strip()
    parsed = urlsplit(url)
    if prefix and (parsed.hostname or "").lower() == RAW_GITHUB_HOST:
        return prefix.rstrip("/") + "/" + url if not prefix.endswith("=") else prefix + url
    return url


def entry_url(source: ResolvedSource, entry: MarketEntry) -> str:
    return source.base_url + entry.path


# ---------------------------------------------------------------- fetching (bounded)

Fetch = Callable[[str, int], bytes]


def _assert_public_host(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise MarketError("只抓取 https:// 地址", code="fetch_refused")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise MarketError(f"市场源域名无法解析：{parsed.hostname}", code="fetch_refused") from exc
    for address in {item[4][0] for item in addresses}:
        if not settings.is_public_address(address):
            raise MarketError(f"市场源域名解析到了非公网地址 {address}，拒绝抓取", code="fetch_refused")


def http_fetch(url: str, max_bytes: int, *, transport: httpx.BaseTransport | None = None, timeout: float = FETCH_TIMEOUT_SECONDS) -> bytes:
    """GET ``url`` with the server-side boundaries: HTTPS, public hosts at every hop, few redirects, a size cap."""
    current = raw_proxied(url)
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, headers={"User-Agent": "short-drama-market/1"}) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            _assert_public_host(current)
            with client.stream("GET", current) as response:
                if response.is_redirect:
                    target = response.headers.get("location") or ""
                    current = str(response.url.join(target))
                    continue
                if response.status_code != 200:
                    raise MarketError(f"抓取失败（HTTP {response.status_code}）：{url}", code="fetch_failed", status=502)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise MarketError(f"文件超过 {max_bytes} 字节上限：{url}", code="fetch_too_large", status=502)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise MarketError(f"文件超过 {max_bytes} 字节上限：{url}", code="fetch_too_large", status=502)
                return bytes(body)
    raise MarketError(f"重定向超过 {MAX_REDIRECTS} 次：{url}", code="fetch_refused", status=502)


# ---------------------------------------------------------------- stored state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def official_source_url() -> str:
    return (os.getenv(OFFICIAL_SOURCE_ENV) or "").strip()


def _source_row(resolved: ResolvedSource, *, label: str = "", official: bool = False) -> dict[str, Any]:
    return {
        "id": source_id(resolved.key), "key": resolved.key, "kind": resolved.kind, "url": resolved.index_url,
        "base_url": resolved.base_url, "label": (label or resolved.label)[:120], "official": official, "enabled": True,
        "added_at": _now(), "fetched_at": None, "error": "", "index": None,
    }


def stored_sources(setting: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Sources as saved, with the official one (from the environment) present whether or not it was saved."""
    rows = [dict(row) for row in (setting.get("items") or []) if isinstance(row, Mapping) and row.get("key")]
    official = official_source_url()
    if official:
        try:
            resolved = resolve_source(official)
        except MarketError as exc:
            logger.warning("[Market] 官方市场源地址无效，忽略：%s", exc)
        else:
            for row in rows:
                if row["key"] == resolved.key:
                    row["official"] = True
                    break
            else:
                rows.insert(0, _source_row(resolved, label="官方市场源", official=True))
    else:
        for row in rows:
            row["official"] = False
    return rows


def source_view(row: Mapping[str, Any]) -> dict[str, Any]:
    index = row.get("index") if isinstance(row.get("index"), Mapping) else None
    return {
        "id": row.get("id") or source_id(str(row["key"])), "key": row["key"], "kind": row.get("kind"), "url": row.get("url"),
        "label": row.get("label") or "", "official": bool(row.get("official")), "enabled": bool(row.get("enabled", True)),
        "fetched_at": row.get("fetched_at"), "error": row.get("error") or "",
        "entry_count": len(index.get("entries") or []) if index else 0, "index_name": (index or {}).get("name") or "",
    }


def install_view(record: Mapping[str, Any], *, sources: Mapping[str, Mapping[str, Any]], endpoint: Mapping[str, Any] | None) -> dict[str, Any]:
    """An install record with both axes of its state resolved against the sources and the endpoint."""
    source = sources.get(str(record.get("source_key")))
    index = (source or {}).get("index") if source else None
    listed = None
    if source and source.get("enabled", True) and isinstance(index, Mapping):
        listed = next((e for e in (index.get("entries") or []) if isinstance(e, Mapping) and e.get("slug") == record.get("slug")), None)
    if listed is None:
        market: MarketStatus = "unavailable"
    elif str(listed.get("version")) == str(record.get("version")):
        market = "latest"
    else:
        market = "update_available"
    spec = (endpoint or {}).get("spec") if endpoint else None
    modified = bool(spec) and spec_digest(spec) != record.get("digest")
    return {
        "family": record.get("family"), "source_key": record.get("source_key"), "source_id": source_id(str(record.get("source_key"))),
        "source_label": (source or {}).get("label") or "", "slug": record.get("slug"), "name": record.get("name"),
        "version": record.get("version"), "available_version": (listed or {}).get("version") if listed else None,
        "installed_at": record.get("installed_at"), "updated_at": record.get("updated_at"),
        "market_status": market, "modified": modified, "endpoint_present": endpoint is not None,
    }


# ---------------------------------------------------------------- operations


class Market:
    """Market operations over the platform store; ``fetch`` is injectable so tests never hit the network."""

    def __init__(self, store, *, fetch: Fetch = http_fetch):
        self.store = store
        self.fetch = fetch

    # ---- reading

    async def _sources(self) -> list[dict[str, Any]]:
        return stored_sources(await self.store.get_setting(SOURCES_KEY))

    async def _installs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in (await self.store.get_setting(INSTALLS_KEY)).get("items") or [] if isinstance(r, Mapping)]

    async def _endpoints(self) -> list[dict[str, Any]]:
        return [dict(r) for r in (await self.store.get_setting(ENDPOINTS_KEY)).get("items") or [] if isinstance(r, Mapping)]

    async def sources(self) -> list[dict[str, Any]]:
        return [source_view(row) for row in await self._sources()]

    async def installed(self) -> list[dict[str, Any]]:
        sources = {row["key"]: row for row in await self._sources()}
        endpoints = {str((e.get("spec") or {}).get("family")): e for e in await self._endpoints()}
        return [install_view(record, sources=sources, endpoint=endpoints.get(str(record.get("family")))) for record in await self._installs()]

    async def entries(self) -> list[dict[str, Any]]:
        """Every entry of every enabled source, with its install state for this instance."""
        installs = {(r.get("source_key"), r.get("slug")): r for r in await self._installs()}
        endpoints = {str((e.get("spec") or {}).get("family")): e for e in await self._endpoints()}
        rows: list[dict[str, Any]] = []
        for source in await self._sources():
            index = source.get("index") if isinstance(source.get("index"), Mapping) else None
            if not source.get("enabled", True) or not index:
                continue
            for entry in index.get("entries") or []:
                if not isinstance(entry, Mapping):
                    continue
                record = installs.get((source["key"], entry.get("slug")))
                state = None
                if record:
                    state = install_view(record, sources={source["key"]: source}, endpoint=endpoints.get(str(record.get("family"))))
                rows.append({
                    **{k: entry.get(k) for k in ("slug", "name", "version", "kind", "summary", "author", "tags", "min_app_version")},
                    "source_id": source["id"], "source_key": source["key"], "source_label": source.get("label") or "",
                    "installed": state is not None, "installed_family": (record or {}).get("family"),
                    "installed_version": (record or {}).get("version"), "market_status": (state or {}).get("market_status"),
                    "modified": bool((state or {}).get("modified")),
                })
        return rows

    # ---- sources

    async def add_source(self, url: str, *, label: str = "", actor_id: str) -> dict[str, Any]:
        resolved = resolve_source(url)
        rows = await self._sources()
        if any(row["key"] == resolved.key for row in rows):
            raise MarketError("这个市场源已经登记过了", code="duplicate_source", status=409)
        row = _source_row(resolved, label=label)
        self._refresh_row(row)
        rows.append(row)
        await self.store.put_setting(SOURCES_KEY, {"items": rows}, actor_id=actor_id)
        return source_view(row)

    async def set_source_enabled(self, id_: str, enabled: bool, *, actor_id: str) -> dict[str, Any]:
        rows = await self._sources()
        row = self._find(rows, id_)
        row["enabled"] = bool(enabled)
        await self.store.put_setting(SOURCES_KEY, {"items": rows}, actor_id=actor_id)
        return source_view(row)

    async def remove_source(self, id_: str, *, actor_id: str) -> dict[str, Any]:
        """Forget a third-party source. Its install records stay: they name the source by key, not by row."""
        rows = await self._sources()
        row = self._find(rows, id_)
        if row.get("official"):
            raise MarketError("官方市场源随版预置，只能停用，不能删除", code="official_source", status=409)
        rows = [r for r in rows if r is not row]
        await self.store.put_setting(SOURCES_KEY, {"items": rows}, actor_id=actor_id)
        return {"id": id_, "deleted": True}

    async def refresh_source(self, id_: str, *, actor_id: str) -> dict[str, Any]:
        rows = await self._sources()
        row = self._find(rows, id_)
        self._refresh_row(row)
        await self.store.put_setting(SOURCES_KEY, {"items": rows}, actor_id=actor_id)
        if row.get("error"):
            raise MarketError(str(row["error"]), code="refresh_failed", status=502)
        return source_view(row)

    async def refresh_all(self, *, actor_id: str) -> list[dict[str, Any]]:
        rows = await self._sources()
        for row in rows:
            if row.get("enabled", True):
                self._refresh_row(row)
        await self.store.put_setting(SOURCES_KEY, {"items": rows}, actor_id=actor_id)
        return [source_view(row) for row in rows]

    def _refresh_row(self, row: dict[str, Any]) -> None:
        """Fetch and validate the source's index; a failure is recorded on the row, the old index kept."""
        try:
            index = parse_index(self.fetch(str(row["url"]), MAX_INDEX_BYTES))
        except MarketError as exc:
            row["error"] = str(exc)
        except (httpx.HTTPError, OSError) as exc:
            row["error"] = f"抓取索引失败：{str(exc)[:200]}"
        else:
            row["index"] = index.model_dump(mode="json", by_alias=True)
            row["fetched_at"] = _now()
            row["error"] = ""

    @staticmethod
    def _find(rows: list[dict[str, Any]], id_: str) -> dict[str, Any]:
        for row in rows:
            if (row.get("id") or source_id(str(row["key"]))) == id_:
                return row
        raise MarketError("没有这个市场源", code="unknown_source", status=404)

    # ---- install / update

    async def install(
        self, source_id_: str, slug: str, *, actor_id: str, cipher, api_key: str = "", family: str = "",
        overwrite: bool = False, discard_local: bool = False,
    ) -> dict[str, Any]:
        """Land an entry as a local endpoint plus its install record, in one transaction.

        A first install needs an API key; an update keeps the key it has. A family that
        already belongs to another market entry is refused; one with no install record
        is only replaced when ``overwrite`` says so. An update over a locally modified
        endpoint is refused until ``discard_local`` says the edits may go.
        """
        rows = await self._sources()
        source_row = self._find(rows, source_id_)
        if not source_row.get("enabled", True):
            raise MarketError("这个市场源已停用", code="source_disabled", status=409)
        index = source_row.get("index") if isinstance(source_row.get("index"), Mapping) else None
        listed = next((e for e in ((index or {}).get("entries") or []) if isinstance(e, Mapping) and e.get("slug") == slug), None)
        if listed is None:
            raise MarketError("索引里没有这个条目，请先刷新市场源", code="unknown_entry", status=404)
        entry = MarketEntry.model_validate(listed)
        resolved = ResolvedSource(key=source_row["key"], kind=source_row.get("kind") or "direct", base_url=source_row["base_url"], index_url=source_row["url"], label=source_row.get("label") or "")
        try:
            definition = parse_definition(self.fetch(entry_url(resolved, entry), MAX_DEFINITION_BYTES))
        except (httpx.HTTPError, OSError) as exc:
            raise MarketError(f"抓取条目定义失败：{str(exc)[:200]}", code="fetch_failed", status=502) from exc
        meta = definition.meta
        if (meta.slug, meta.name, meta.version, meta.kind) != (entry.slug, entry.name, entry.version, entry.kind):
            raise MarketError("索引与条目定义不一致（slug / 名称 / 版本 / 类型），拒绝安装；请联系市场源维护者", code="index_mismatch", status=409)
        target = (family or str(definition.spec.get("family") or "") or entry.slug.replace("-", "_")).strip().lower()
        try:
            spec = VideoEndpointSpec.model_validate({**definition.spec, "family": target})
            spec.check()
        except ValueError as exc:
            raise MarketError(f"条目的端点声明无效：{exc}", code="bad_definition", status=422) from exc

        endpoints = await self._endpoints()
        installs = await self._installs()
        existing = next((e for e in endpoints if (e.get("spec") or {}).get("family") == target), None)
        record = next((r for r in installs if r.get("family") == target), None)
        if record and (record.get("source_key"), record.get("slug")) != (source_row["key"], slug):
            raise MarketError(f"端点 {target} 来自另一个市场条目（{record.get('source_label') or record.get('source_key')} / {record.get('slug')}），不做跨条目转移；请换一个族标识", code="family_bound", status=409)
        if existing and record is None and not overwrite:
            raise MarketError(f"本地已有端点 {target}（非市场安装）；确认覆盖后才会替换", code="overwrite_needed", status=409, family=target)
        if record and existing and not discard_local and spec_digest(existing.get("spec") or {}) != record.get("digest"):
            raise MarketError(f"端点 {target} 安装后被本地修改过；更新会覆盖这些修改，请先导出或确认丢弃", code="modified_locally", status=409, family=target)
        key = (api_key or "").strip()
        if not key and not (existing or {}).get("api_key_ciphertext"):
            raise MarketError("首次安装需要提供这个供应商的 API Key", code="api_key_required", status=422)
        spec_json = spec.model_dump(mode="json")
        endpoint = {
            "spec": spec_json,
            "enabled": (existing or {}).get("enabled", True),
            "api_key_ciphertext": cipher.encrypt(key) if key else existing["api_key_ciphertext"],
            "api_key_hint": key[-4:] if key else (existing or {}).get("api_key_hint", ""),
        }
        endpoints = [e for e in endpoints if (e.get("spec") or {}).get("family") != target] + [endpoint]
        now = _now()
        new_record = {
            "family": target, "source_key": source_row["key"], "source_label": source_row.get("label") or "", "slug": entry.slug,
            "name": entry.name, "version": entry.version, "kind": entry.kind, "digest": spec_digest(spec_json),
            "installed_at": (record or {}).get("installed_at") or now, "updated_at": now,
        }
        installs = [r for r in installs if r.get("family") != target] + [new_record]
        await self.store.put_settings({ENDPOINTS_KEY: {"items": endpoints}, INSTALLS_KEY: {"items": installs}}, actor_id=actor_id)
        return {"endpoint": endpoint, "record": install_view(new_record, sources={source_row["key"]: source_row}, endpoint=endpoint), "updated": record is not None}

    async def forget_install(self, family: str, *, actor_id: str) -> bool:
        """Drop the install record of ``family`` (used when its endpoint is deleted: uninstall is deletion)."""
        installs = await self._installs()
        kept = [r for r in installs if r.get("family") != family]
        if len(kept) == len(installs):
            return False
        await self.store.put_setting(INSTALLS_KEY, {"items": kept}, actor_id=actor_id)
        return True

    # ---- contributing

    async def export_bundle(self, family: str, *, author: str = "", summary: str = "") -> dict[str, Any]:
        """The files a person adds to a market source to publish ``family``: a definition plus the index entry.

        The manual path (a pull request to the source's repository) is the only
        contribution path here; nothing is uploaded anywhere.
        """
        endpoint = next((e for e in await self._endpoints() if (e.get("spec") or {}).get("family") == family), None)
        if endpoint is None:
            raise MarketError("没有这个声明式端点", code="unknown_endpoint", status=404)
        record = next((r for r in await self._installs() if r.get("family") == family), None)
        spec = dict(endpoint.get("spec") or {})
        slug = (record or {}).get("slug") or family.replace("_", "-")
        version = (record or {}).get("version") or "1.0.0"
        meta = {
            "slug": slug, "name": str(spec.get("label") or family), "version": version, "kind": "video_endpoint",
            "author": author or (record or {}).get("author") or "", "summary": summary or "",
        }
        definition = {"meta": meta, "spec": spec}
        entry = {**{k: meta[k] for k in ("slug", "name", "version", "kind", "summary", "author")}, "path": f"entries/{slug}/definition.json", "tags": []}
        return {
            "slug": slug,
            "files": {f"entries/{slug}/definition.json": json.dumps(definition, ensure_ascii=False, indent=2) + "\n"},
            "index_entry": entry,
            "note": f"把 files 里的文件加进市场源仓库，并把 index_entry 追加到 {INDEX_FILENAME} 的 entries 里（API Key 不在其中）。",
        }


__all__ = [
    "ENDPOINTS_KEY",
    "ENTRY_KINDS",
    "INDEX_FILENAME",
    "INDEX_SCHEMA",
    "INSTALLS_KEY",
    "MAX_DEFINITION_BYTES",
    "MAX_INDEX_BYTES",
    "MAX_REDIRECTS",
    "SOURCES_KEY",
    "EntryDefinition",
    "Market",
    "MarketEntry",
    "MarketError",
    "MarketIndex",
    "ResolvedSource",
    "entry_url",
    "http_fetch",
    "install_view",
    "parse_definition",
    "parse_index",
    "raw_proxied",
    "resolve_source",
    "source_id",
    "source_view",
    "spec_digest",
    "stored_sources",
]
