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
_AI_CLAIM = re.compile(r"[^。！？!?.\n]*(?:AI ?(?:生成|制作|合成|创作)|AI-(?:generated|created)|generated (?:by|with) AI)[^。！？!?.\n]*[。！？!?.]?", re.I)
_CN_LIVE = (
    "上线前确认微短剧备案（或平台要求的备案/审核编号）",
    "确认配乐、音效与数字演员形象的商用授权",
)

PLATFORMS: tuple[Platform, ...] = (
    Platform("iqiyi", "爱奇艺", "#3fae4a", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             ("竖版 3:4 1080×1440", "横版 16:9 1920×1080"), "https://mp.iqiyi.com/", notes=_CN_LIVE),
    Platform("tencent", "腾讯", "#3d9de0", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             ("竖版 3:4 1080×1440", "横版 16:9 1920×1080"), "https://om.qq.com/", notes=_CN_LIVE),
    Platform("youku", "优酷", "#e06a64", "cn", "zh", 30, 300, 5, ("9:16", "16:9"),
             ("竖版 3:4 1080×1440", "横版 16:9 1920×1080"), "https://mp.youku.com/", notes=_CN_LIVE),
    Platform("douyin", "抖音", "#1f2430", "cn", "zh", 30, 1000, 5, ("9:16",),
             ("竖版 9:16 1080×1920",), "https://creator.douyin.com/",
             notes=(*_CN_LIVE, "付费短剧需先开通抖音短剧资质与分账")),
    Platform("youtube", "YouTube", "#dd3838", "global", "en", 100, 5000, 15, ("9:16", "16:9"),
             ("缩略图 16:9 1280×720",), "https://studio.youtube.com/", max_seconds=180,
             notes=("上传时在「Altered or synthetic content」处选择「是」",
                    "单集不超过 3 分钟按 Shorts 发布，否则按普通视频发布",
                    "确认配乐与数字演员形象的海外商用授权")),
    Platform("dramabox", "DramaBox", "#dd7a12", "global", "en", 60, 500, 5, ("9:16",),
             ("竖版 3:4 1080×1440",), None,
             notes=("DramaBox 没有公开上传入口：通过版权合作邮箱或商务对接提交",
                    "需提供英文字幕（或目标语种字幕）与整季分集表",
                    "确认海外发行权与数字演员形象授权")),
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
        checks.append({"level": "warning", "text": f"标题超过 {target.title_max} 字，已截断，建议改短"})
    body = _AI_CLAIM.sub("", str(copy.get("description") or fallback_description or "")).strip()
    description, cut = _clip(body, target.description_max)
    if cut:
        checks.append({"level": "warning", "text": f"简介超过 {target.description_max} 字，已截断"})
    tags = _tags(copy.get("tags"), target.tags_max)
    if not generated:
        checks.append({"level": "warning", "text": "文案由剧名与分集标题拼成（模型未返回），发布前请润色"})
    if aspect and aspect not in target.aspects:
        checks.append({"level": "error", "text": f"成片画幅 {aspect}，{target.name} 这一类视频要 {' / '.join(target.aspects)}"})
    if not films:
        checks.append({"level": "error", "text": "还没有成片：先完成第 7 阶段合成"})
    for film in films:
        if target.max_seconds and film.seconds and film.seconds > target.max_seconds:
            checks.append({"level": "info", "text": f"第 {film.episode} 集 {film.seconds:.0f} 秒，超过 {target.max_seconds} 秒，按普通视频发布"})
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
        language = "简体中文" if item.language == "zh" else "English"
        rows.append(
            f'- "{item.id}"（{item.name}）：语言 {language}；标题不超过 {item.title_max} 字符；'
            f"简介不超过 {item.description_max} 字符；标签至多 {item.tags_max} 个"
        )
    system = (
        "你是短剧发行编辑，为各平台写上架文案。只写正片里真实存在的人物与情节，不编造剧情、不承诺付费权益、"
        "不使用「最」「第一」等绝对化用语；不写 AI 生成、AI 制作这类声明；标题要有钩子，简介前两句交代冲突。"
        "只输出一个 JSON 对象，键是平台 id，值是 {\"title\": str, \"description\": str, \"tags\": [str]}，不要输出其它文字。"
    )
    episode_lines = "\n".join(f"第{film.episode}集：{film.title}" for film in episodes) or "（分集标题缺失）"
    user = (
        f"剧名：{title}\n剧情梗概：{logline[:2500]}\n分集：\n{episode_lines}\n\n各平台要求：\n" + "\n".join(rows)
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
