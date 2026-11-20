# -*- coding: utf-8 -*-
"""Publishing preparation: one package per platform, ready for a person to upload.

Stage 8 writes the campaign; this turns the finished films into what each platform's upload
form asks for — a title within its length, a description,
tags, the cover sizes, and a checklist of what still blocks going live (filing number, music
licence, a film missing). Nothing here posts anything: publishing is a person's click on the
platform's own upload page, which each package links to.

The limits below are each platform's published form limits at the time of writing; a platform
can change them, so every package says to confirm against the upload page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from app.core import prompt_data


_WORDING_FILE = "publish_targets"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/publish_targets.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


@dataclass(frozen=True)
class Platform:
    id: str
    name: str
    color: str
    region: str                 # "cn" or "global"
    language: str               # the language the copy is written in
    title_max: int
    description_max: int
    tags_max: int
    aspects: tuple[str, ...]    # aspect ratios the platform takes for this kind of video
    covers: tuple[str, ...]
    upload_url: str | None
    max_seconds: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# 模型偶尔会自己写一句 AI 声明：这个项目的简介里不要。
_AI_CLAIM = re.compile(_text_of("module.ai_claim"), re.I)
_CN_LIVE = _words_of("module.cn_live")

PLATFORMS: tuple[Platform, ...] = (
    Platform("iqiyi", _text_of("module.platforms"), "#3fae4a", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             _words_of("module.platforms.2"), "https://mp.iqiyi.com/", notes=_CN_LIVE),
    Platform("tencent", _text_of("module.platforms.3"), "#3d9de0", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             _words_of("module.platforms.4"), "https://om.qq.com/", notes=_CN_LIVE),
    Platform("youku", _text_of("module.platforms.5"), "#e06a64", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             _words_of("module.platforms.6"), "https://mp.youku.com/", notes=_CN_LIVE),
    Platform("douyin", _text_of("module.platforms.7"), "#1f2430", "cn", "zh", 30, 1000, 5, ("9:16",),
             _words_of("module.platforms.8"), "https://creator.douyin.com/",
             notes=(*_CN_LIVE, _text_of("module.notes"))),
    Platform("youtube", "YouTube", "#dd3838", "global", "en", 100, 5000, 15, ("9:16", "16:9"),
             _words_of("module.platforms.9"), "https://studio.youtube.com/", max_seconds=180,
             notes=_words_of("module.notes.2")),
    Platform("dramabox", "DramaBox", "#dd7a12", "global", "en", 60, 500, 5, ("9:16",),
             _words_of("module.platforms.10"), None,
             notes=_words_of("module.notes.3")),
)
PLATFORM_IDS = tuple(platform.id for platform in PLATFORMS)
_BY_ID = {platform.id: platform for platform in PLATFORMS}


def platform(platform_id: str) -> Platform:
    return _BY_ID[platform_id]


def catalog() -> list[dict[str, Any]]:
    """The platforms the share panel offers, in its order."""
    return [
        {"id": item.id, "name": item.name, "color": item.color, "region": item.region,
         "language": item.language, "uploadUrl": item.upload_url}
        for item in PLATFORMS
    ]


def _clip(text: str, limit: int) -> tuple[str, bool]:
    text = " ".join(str(text or "").split())
    return (text, False) if len(text) <= limit else (text[: max(1, limit - 1)].rstrip() + "…", True)


def _tags(raw: Any, limit: int) -> list[str]:
    values = raw if isinstance(raw, list) else re.split(r"[,，、#\s]+", str(raw or ""))
    tags: list[str] = []
    for value in values:
        tag = str(value).strip().lstrip("#").strip()
        if tag and tag not in tags and len(tag) <= 30:
            tags.append(tag)
    return tags[:limit]


@dataclass(frozen=True)
class Film:
    episode: int
    title: str
    url: str
    seconds: float | None


def build_package(
    target: Platform,
    copy: Mapping[str, Any] | None,
    *,
    films: Sequence[Film],
    aspect: str,
    fallback_title: str,
    fallback_description: str,
) -> dict[str, Any]:
    """One platform's package: copy fitted to its limits, plus the checks a person must clear."""
    copy = copy or {}
    checks: list[dict[str, str]] = []
    generated = bool(copy.get("title"))
    title, cut = _clip(copy.get("title") or fallback_title, target.title_max)
    if cut:
        checks.append({"level": "warning", "text": _text_of("build_package.text").format(target.title_max)})
    body = _AI_CLAIM.sub("", str(copy.get("description") or fallback_description or "")).strip()
    description, cut = _clip(body, target.description_max)
    if cut:
        checks.append({"level": "warning", "text": _text_of("build_package.text.2").format(target.description_max)})
    tags = _tags(copy.get("tags"), target.tags_max)
    if not generated:
        checks.append({"level": "warning", "text": _text_of("build_package.text.3")})
    if aspect and aspect not in target.aspects:
        checks.append({"level": "error", "text": _text_of("build_package.text.4").format(aspect, target.name, ' / '.join(target.aspects))})
    if not films:
        checks.append({"level": "error", "text": _text_of("build_package.text.5")})
    for film in films:
        if target.max_seconds and film.seconds and film.seconds > target.max_seconds:
            checks.append({"level": "info", "text": _text_of("build_package.text.6").format(film.episode, film.seconds, target.max_seconds)})
    checks.extend({"level": "todo", "text": note} for note in target.notes)
    return {
        "platform": target.id,
        "name": target.name,
        "language": target.language,
        "title": title,
        "description": description,
        "tags": tags,
        "covers": list(target.covers),
        "uploadUrl": target.upload_url,
        "episodes": [{"episode": film.episode, "title": film.title, "url": film.url, "seconds": film.seconds} for film in films],
        "checks": checks,
        "ready": not any(check["level"] == "error" for check in checks),
        "limits": {"title": target.title_max, "description": target.description_max, "tags": target.tags_max},
    }


def copy_prompt(platform_ids: Iterable[str], *, title: str, logline: str, episodes: Sequence[Film]) -> tuple[str, str]:
    """The one model call that writes every selected platform's copy at once."""
    rows = []
    for platform_id in platform_ids:
        item = _BY_ID[platform_id]
        language = _text_of("copy_prompt.language") if item.language == "zh" else "English"
        rows.append(
            _text_of("copy_prompt.text").format(item.id, item.name, language, item.title_max, item.description_max, item.tags_max)
        )
    system = (
        _text_of("copy_prompt.system")
    )
    episode_lines = "\n".join(_text_of("copy_prompt.episode_lines").format(film.episode, film.title) for film in episodes) or _text_of("copy_prompt.episode_lines.2")
    user = (
        _text_of("copy_prompt.user").format(title, logline[:2500], episode_lines) + "\n".join(rows)
    )
    return system, user


def parse_copy(text: str) -> dict[str, dict[str, Any]]:
    """The model's JSON, tolerating a fenced block; anything unreadable is an empty result."""
    match = re.search(r"\{.*\}", str(text or ""), re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    return {key: value for key, value in data.items() if key in _BY_ID and isinstance(value, dict)} if isinstance(data, dict) else {}


__all__ = [
    "Film", "PLATFORMS", "PLATFORM_IDS", "Platform",
    "build_package", "catalog", "copy_prompt", "parse_copy", "platform",
]
