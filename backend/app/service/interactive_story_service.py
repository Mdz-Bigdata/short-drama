# -*- coding: utf-8 -*-
"""An interactive story kept on its task: ``assets["interactive_story"]``.

    {version, revision, graph, stats, uploads: [Upload], updated_at}

``revision`` moves only when the graph does. A playtest writes counters next to it and leaves it
alone, otherwise testing a story in one tab would turn the editor's next save into a conflict.

Media is the one place a story reaches outside itself, so a saved graph may only name what this
project already holds (its shots, clips, finals, this story's uploads). The export reads files from
exactly that list, which is what keeps it from being a way to fetch an arbitrary address.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO

from app.core import episode_cycle, interactive_story as story, media_compositor, usage_ledger
from app.core.interactive_story import StoryInputError
from app.core.screenwriting.prompts import language_scope
from app.core.screenwriting.structured_llm import StructuredOutputError, call_structured
from app.service.director_desk_service import sniff_media

logger = logging.getLogger("app.service.interactive_story")

ASSET_KEY = "interactive_story"
STORE_VERSION = 1
MAX_UPLOADS = 200
_MEBIBYTE = 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 10 * _MEBIBYTE
MAX_VIDEO_UPLOAD_BYTES = 200 * _MEBIBYTE
# What one .html may carry inline; past this a segment plays as its text card and the ZIP is the way to get the video.
MAX_INLINE_BYTES = 64 * _MEBIBYTE
MAX_ZIP_MEDIA_BYTES = 4 * 1024 * _MEBIBYTE
PLAN_MAX_TOKENS = 12_000
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm"}
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_MEDIA_URL = re.compile(r"^(https?://|/)[^\s\x00-\x1f<>\"'`\\]*$")
_UPLOAD_PREFIX = "istory_"


class StoryConflict(ValueError):
    """Someone else saved since this editor loaded; its copy is out of date."""


class StoryPlanError(ValueError):
    """The model never produced a usable story; the message says what was wrong with its last answer."""


PLAN_SYSTEM_PROMPT = """你是互动短剧的故事架构师。根据创作要求，设计一张观众可以做选择的分支剧情图。

要求：
- 先写 outline（5 到 12 条大纲节拍），再把它展开成 segments。
- 每个片段写 title 和 narration（旁白或场景描述），需要台词时写 dialogue。片段是 30 到 90 秒可拍摄的一场戏，不要写成长篇小说。
- 抉择点放在 choices 里，每个选项的 text 写观众要做的事，target 填目标片段的 id；选项要让故事真正走向不同，不要给假选择。
- 不同的选择可以通过 effects 累积到 variables（例如好感度用 number、是否拿到关键道具用 flag）：add 只用于 number，set 用于两种类型。
- 用 condition 让后面的选项或路线依赖这些变量；被挡住的选项用 when_locked 决定隐藏（hide）还是显示为锁定（lock），锁定时写 locked_hint。条件只能写成 {var, op, value}，或放进 all / any；op 取 eq、ne、gt、gte、lt、lte。
- routes 是不需要观众操作的自动路线，按顺序取第一条成立的，适合用变量决定走向哪个结局；condition 为空表示一定走。
- 需要紧张感的抉择点可以设 timer（seconds 为 5 到 30，default_choice 填该片段里一个不带条件的选项 id）。
- 结局片段的 kind 写 ending，并写 ending_label；结局不能再有 choices 或 routes。其他片段必须有出口，所有路线最终都要能走到结局。允许回环，但回环必须有出口。
- start 填开场片段的 id。variables 里声明用到的每个变量。
- media、position 不要写。segment 的 id 用简短的 s1、s2 这种形式。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- the store


def store_of(task: dict[str, Any]) -> dict[str, Any]:
    assets = task.setdefault("assets", {})
    store = assets.get(ASSET_KEY)
    if not isinstance(store, dict) or store.get("version") != STORE_VERSION:
        store = {"version": STORE_VERSION, "revision": 0, "graph": None, "stats": story.empty_stats(), "uploads": [], "updated_at": ""}
        assets[ASSET_KEY] = store
    if not isinstance(store.get("uploads"), list):
        store["uploads"] = []
    return store


def _peek(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(ASSET_KEY)
    return store if isinstance(store, Mapping) and store.get("version") == STORE_VERSION else {}


# --------------------------------------------------------------------------- what the project already has


def _usable(url: Any) -> str:
    # Stored tasks also hold `inline:` markers and the odd data URI; neither is something a story can point at.
    text = str(url or "").strip()
    return text if len(text) <= 2048 and _MEDIA_URL.match(text) else ""


def _clip_duration(clip: Mapping[str, Any]) -> float:
    for key in ("duration_s", "duration", "requested_seconds", "actual_seconds"):
        value = clip.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return 0.0


def project_media(task: Mapping[str, Any]) -> dict[str, Any]:
    """Shots, their generated clips and the finished films, as the picker lists them."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    clips = [clip for clip in assets.get("5") or [] if isinstance(clip, dict)]
    shots = []
    for number, shot in enumerate(assets.get("4") or [], start=1):
        if not isinstance(shot, dict):
            continue
        keyed = {**shot, "shot_id": int(shot.get("shot_id") or number)}
        clip = episode_cycle.clip_for(keyed, clips) or {}
        video = _usable(clip.get("video_url"))
        candidates = [_usable(item) for item in clip.get("candidates") or clip.get("candidate_urls") or []]
        shots.append({
            "shot_id": keyed["shot_id"], "shot_uid": episode_cycle.shot_uid(keyed), "scene_id": str(shot.get("scene_id") or ""),
            "desc": str(shot.get("desc") or shot.get("description") or "")[:160],
            "image_url": _usable(shot.get("image_url")) or None, "video_url": video or None,
            "candidate_urls": [item for item in dict.fromkeys(candidates) if item and item != video][:6],
            "duration_s": _clip_duration(clip), "stale": bool(clip.get("stale")),
        })
    films = []
    for episode in task.get("episodes") or []:
        if isinstance(episode, dict) and _usable(episode.get("video_url")):
            films.append({"label": str(episode.get("title") or episode.get("index") or ""), "video_url": _usable(episode["video_url"])})
    final = assets.get("7") if isinstance(assets.get("7"), Mapping) else {}
    known_films = {item["video_url"] for item in films}
    for url in (final.get("final_video_url"), task.get("video_url")):
        if _usable(url) and _usable(url) not in known_films:
            films.append({"label": "", "video_url": _usable(url)})
            known_films.add(_usable(url))
    return {"shots": shots, "films": films, "uploads": [dict(item) for item in _peek(task).get("uploads") or [] if isinstance(item, Mapping)]}


def _allowed_urls(task: Mapping[str, Any]) -> set[str]:
    library = project_media(task)
    urls = {item["url"] for item in library["uploads"] if item.get("url")}
    urls |= {item["video_url"] for item in library["films"]}
    for shot in library["shots"]:
        urls |= {url for url in (shot["image_url"], shot["video_url"], *shot["candidate_urls"]) if url}
    # A clip regenerated since its segment was saved has gone from the project, not from the story.
    stored = _peek(task).get("graph")
    return urls | (story.media_urls(stored) if isinstance(stored, Mapping) else set())


def _check_media(graph: Mapping[str, Any], allowed: set[str]) -> None:
    foreign = sorted(story.media_urls(graph) - allowed)
    if foreign:
        raise StoryInputError(f"片段的媒体必须来自本项目的镜头、成片或上传文件；不认识：{foreign[0][:120]}")


# --------------------------------------------------------------------------- fetching media for an export


@dataclass(frozen=True)
class MediaItem:
    url: str
    kind: str
    status: str  # local | remote | expired | missing
    path: str | None = None
    size: int = 0


def _locate(url: str, kind: str) -> MediaItem:
    path = media_compositor.local_media_path(url)
    if path:
        return MediaItem(url, kind, "local", path, os.path.getsize(path))
    if url.startswith(("http://", "https://")):
        return MediaItem(url, kind, "remote" if media_compositor.media_available(url) else "expired")
    return MediaItem(url, kind, "missing")


def _graph_media(graph: Mapping[str, Any]) -> list[MediaItem]:
    seen: dict[str, MediaItem] = {}
    for segment in graph.get("segments") or []:
        media = segment.get("media")
        if isinstance(media, Mapping) and media.get("url") and media["url"] not in seen:
            seen[media["url"]] = _locate(str(media["url"]), str(media.get("kind") or "video"))
    return list(seen.values())


def _fetch(item: MediaItem, workdir: str) -> str | None:
    """A readable local path for an item. Downloads go through the compositor's guard against private hosts."""
    if item.status == "local":
        return item.path
    if item.status != "remote":
        return None
    destination = os.path.join(workdir, uuid.uuid4().hex)
    return destination if media_compositor._download(item.url, destination, timeout=60, retries=1) else None


def _proven_type(path: str, kind: str) -> str | None:
    """What the file's own bytes say it is, provided that is what the segment says it should be."""
    with open(path, "rb") as handle:
        proven = sniff_media(handle.read(4096))
    return proven if proven in _EXTENSIONS and proven.startswith(f"{kind}/") else None


def _download_name(title: str, extension: str) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", title or "").strip(" ._")[:60]
    return f"{clean or 'interactive-story'}.{extension}"


@dataclass
class ExportFile:
    filename: str
    media_type: str
    content: bytes | None = None
    path: str | None = None


class InteractiveStoryService:
    """Everything that needs the task store or a model; the rules themselves live in ``core.interactive_story``."""

    def __init__(self, repo: Any, gateway: Any = None) -> None:
        self.repo = repo
        self.gateway = gateway

    def _task(self, task_id: str) -> dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise LookupError("任务不存在")
        return task

    # ----------------------------------------------------------------------- reading and saving

    @staticmethod
    def _analysis(graph: Mapping[str, Any]) -> dict[str, Any]:
        return story.analyze_story(graph)

    @staticmethod
    def _public_analysis(analysis: Mapping[str, Any]) -> dict[str, Any]:
        # Route keys only exist to be matched against playtests; the page has no use for 2000 of them.
        return {**analysis, "paths": {key: value for key, value in analysis["paths"].items() if key != "route_keys"}}

    def _view(self, store: Mapping[str, Any]) -> dict[str, Any]:
        graph = store.get("graph") if isinstance(store.get("graph"), Mapping) else None
        analysis = self._analysis(graph) if graph else None
        return {
            "revision": int(store.get("revision") or 0), "graph": graph, "updated_at": store.get("updated_at") or "",
            "analysis": self._public_analysis(analysis) if analysis else None,
            "stats": story.stats_view(store.get("stats"), graph, analysis["paths"]) if graph and analysis else None,
        }

    def canvas_handoff(self, task_id: str, segment_id: str, *, owner_id: str, studio: Any) -> dict[str, Any]:
        """Two nodes on the project's main canvas for one segment: a first frame to draw, and the video it feeds.

        The canvas is where a single clip can be made and paid for on its own; stage 5 only runs whole batches.
        When the segment already shows one of the project's shots, the video node is bound to that shot, so
        committing the result writes it back where the media picker will find it.
        """
        task = self.repo.get_task(task_id)
        if not task:
            raise LookupError("项目不存在")
        graph = self.view(task_id)["graph"]
        segment = next((item for item in graph.get("segments", []) if item.get("id") == segment_id), None)
        if segment is None:
            raise LookupError("没有这个片段")
        lines = [f"{line.get('speaker') or ''}：{line.get('text') or ''}".strip("：") for line in segment.get("dialogue") or [] if line.get("text")]
        prompt = "\n".join(part for part in (str(segment.get("narration") or "").strip(), *lines) if part)[:4000]
        if not prompt:
            raise StoryInputError("这个片段还没有旁白或台词，先写一点再去画布生成")
        media = segment.get("media") or {}
        binding: dict[str, Any] = {}
        if media.get("source") == "shot" and media.get("shot_uid"):
            shot = next((item for item in project_media(task)["shots"] if item["shot_uid"] == media["shot_uid"]), None)
            if shot:
                binding = {"binding": {"sceneId": shot["scene_id"], "shotId": shot["shot_id"]}}
        title = str(segment.get("title") or segment_id)[:60]
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        project_id = studio.repository.project_for_task(task_id, owner_id, str(config.get("title_suggestion") or "画布")).id
        done = studio.edit_canvas(project_id, owner_id, [
            {"op": "add_node", "ref": "frame", "kind": "image_gen", "label": f"{title} · 首帧", "prompt": prompt},
            {"op": "add_node", "ref": "clip", "kind": "video_gen", "label": f"{title} · 视频", "prompt": prompt, "params": binding},
            {"op": "connect", "source": "frame", "target": "clip", "role": "first_frame"},
        ])
        return {"project_id": project_id, "canvas_id": "main", "nodes": done["created"], "bound": bool(binding), "version": done["version"]}

    def view(self, task_id: str) -> dict[str, Any]:
        return self._view(_peek(self._task(task_id)))

    def save(self, task_id: str, base_revision: int, raw_graph: Any) -> dict[str, Any]:
        graph = story.parse_graph(raw_graph)

        def mutate(task: dict[str, Any]) -> dict[str, Any]:
            store = store_of(task)
            # Checked inside the row lock: two tabs saving at once cannot both pass.
            if int(store.get("revision") or 0) != int(base_revision):
                raise StoryConflict("互动剧已在其他页面更新，请刷新后重试")
            _check_media(graph, _allowed_urls(task))
            store["graph"] = graph
            store["revision"] = int(store.get("revision") or 0) + 1
            store["updated_at"] = _now()
            return dict(store)

        saved = self.repo.mutate_task(task_id, mutate)
        if saved is None:
            raise LookupError("任务不存在")
        return self._view(saved)

    def analyze(self, raw_graph: Any) -> dict[str, Any]:
        """A draft's problems without saving it; nothing here costs anything or touches the task."""
        return self._public_analysis(self._analysis(story.parse_graph(raw_graph)))

    # ----------------------------------------------------------------------- planning

    def plan(
        self, task_id: str, brief: str, *, endings: int = 3, minutes: int = 10, language: str = "zh", use_project: bool = True,
    ) -> dict[str, Any]:
        """Draft a story from a brief. It is only returned: replacing the graph is the author's decision."""
        task = self._task(task_id)
        if self.gateway is None:
            raise StoryPlanError("没有可用的文本模型")
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        title = str(config.get("title_suggestion") or "")
        model = str(config.get("llm_model") or "")

        def caller(system: str, user: str, max_tokens: int) -> str:
            return self.gateway.call_llm(
                model, system, user, title, str(config.get("director_style") or ""), str(config.get("shot_style") or ""),
                user_instruction="", max_tokens=max_tokens,
            ) or ""

        endings = max(2, min(int(endings), 12))
        sections = [f"# 创作要求\n{brief.strip()}", f"# 规模\n结局不少于 {endings} 个；每条完整路线的观看时长约 {max(1, int(minutes))} 分钟。"]
        if use_project:
            sections.append(self._project_context(task))
        try:
            with usage_ledger.bind_task(task_id, "interactive_story_plan"), language_scope(language):
                result = call_structured(
                    caller, system_prompt=PLAN_SYSTEM_PROMPT, user_prompt="\n\n".join(part for part in sections if part),
                    schema=story.StoryPlanDraft, max_tokens=PLAN_MAX_TOKENS, attempts=3,
                    validators=[lambda data: story.plan_problems(data, min_endings=endings)], label="interactive_story_plan",
                )
        except StructuredOutputError as error:
            logger.warning("[InteractiveStory] 规划失败 task=%s: %s", task_id, str(error)[:400])
            raise StoryPlanError("模型连续 3 次没有给出可用的分支剧情：" + "；".join(error.reasons)[:600]) from error
        except (RuntimeError, ValueError, OSError) as error:
            logger.warning("[InteractiveStory] 模型调用失败 task=%s: %s", task_id, type(error).__name__)
            raise StoryPlanError("调用文本模型失败，请稍后重试或在模型配置里换一个模型") from error
        graph = story.parse_graph(result.data)
        return {"draft": graph, "analysis": self._public_analysis(self._analysis(graph)), "attempts": result.attempts}

    @staticmethod
    def _project_context(task: Mapping[str, Any]) -> str:
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
        names = [str(item.get("name")) for item in assets.get("3_characters") or [] if isinstance(item, Mapping) and item.get("name")][:16]
        lines = []
        if config.get("title_suggestion"):
            lines.append(f"剧名：{config['title_suggestion']}")
        if names:
            lines.append("已有角色：" + "、".join(names))
        return "# 本项目已有的设定（尽量沿用）\n" + "\n".join(lines) if lines else ""

    # ----------------------------------------------------------------------- media

    def media_library(self, task_id: str) -> dict[str, Any]:
        return project_media(self._task(task_id))

    def add_upload(self, task_id: str, source: BinaryIO, *, filename: str, duration_s: float = 0.0) -> dict[str, Any]:
        """Store one image or video. Its own bytes decide what it is, never the declared type."""
        self._task(task_id)
        head = source.read(4096)
        proven = sniff_media(head)
        if proven not in _EXTENSIONS:
            raise StoryInputError("只支持 PNG、JPEG、WebP 图片或 MP4、WebM 视频；文件内容不是其中任何一种")
        kind = proven.split("/", 1)[0]
        limit = MAX_IMAGE_UPLOAD_BYTES if kind == "image" else MAX_VIDEO_UPLOAD_BYTES
        os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
        name = "{}{}_{}.{}".format(_UPLOAD_PREFIX, _SAFE.sub("", task_id)[:40] or "task", uuid.uuid4().hex, _EXTENSIONS[proven])
        path = os.path.join(media_compositor.MEDIA_DIR, name)
        size = len(head)
        try:
            with open(path, "wb") as handle:
                chunk = head
                while chunk:
                    if size > limit:
                        raise StoryInputError(f"{'图片' if kind == 'image' else '视频'}不能超过 {limit // _MEBIBYTE} MB")
                    handle.write(chunk)
                    chunk = source.read(_MEBIBYTE)
                    size += len(chunk)
            record = {
                "id": uuid.uuid4().hex, "kind": kind, "url": media_compositor.public_url(name),
                "label": re.sub(r"[\x00-\x1f]", "", os.path.basename(filename or ""))[:120], "size": size,
                "duration_s": duration_s if kind == "video" and 0 < duration_s <= 7200 else 0.0, "created_at": _now(),
            }

            def mutate(task: dict[str, Any]) -> dict[str, Any]:
                uploads = store_of(task)["uploads"]
                if len(uploads) >= MAX_UPLOADS:
                    raise StoryInputError(f"一部互动剧最多上传 {MAX_UPLOADS} 个文件，先删掉用不上的")
                uploads.append(record)
                return record

            if self.repo.mutate_task(task_id, mutate) is None:
                raise LookupError("任务不存在")
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            raise
        return record

    def remove_upload(self, task_id: str, upload_id: str) -> dict[str, Any]:
        def mutate(task: dict[str, Any]) -> str:
            store = store_of(task)
            found = next((item for item in store["uploads"] if isinstance(item, dict) and item.get("id") == upload_id), None)
            if found is None:
                raise LookupError("这个上传文件不存在")
            graph = store.get("graph")
            if isinstance(graph, Mapping) and found.get("url") in story.media_urls(graph):
                raise StoryConflict("还有片段在用这个文件，先把它从片段上换掉")
            store["uploads"] = [item for item in store["uploads"] if item is not found]
            return str(found.get("url") or "")

        url = self.repo.mutate_task(task_id, mutate)
        if url is None:
            raise LookupError("任务不存在")
        # Only files this feature wrote; a stored URL never gets to choose what is deleted.
        name = os.path.basename(url)
        if name.startswith(_UPLOAD_PREFIX) and media_compositor.local_media_path(url):
            os.remove(os.path.join(media_compositor.MEDIA_DIR, name))
        return self.media_library(task_id)

    # ----------------------------------------------------------------------- playtest statistics

    def record_playtest(self, task_id: str, run: Mapping[str, Any]) -> dict[str, Any]:
        def mutate(task: dict[str, Any]) -> dict[str, Any]:
            store = store_of(task)
            graph = store.get("graph")
            if not isinstance(graph, Mapping):
                raise LookupError("这个项目还没有互动剧")
            store["stats"] = story.record_playtest(store.get("stats"), graph, run)
            return dict(store)

        saved = self.repo.mutate_task(task_id, mutate)
        if saved is None:
            raise LookupError("任务不存在")
        return story.stats_view(saved.get("stats"), saved["graph"], story.analyze_paths(saved["graph"]))

    def reset_playtest(self, task_id: str) -> dict[str, Any]:
        def mutate(task: dict[str, Any]) -> dict[str, Any]:
            store = store_of(task)
            store["stats"] = story.empty_stats()
            return dict(store)

        saved = self.repo.mutate_task(task_id, mutate)
        if saved is None:
            raise LookupError("任务不存在")
        graph = saved.get("graph")
        return story.stats_view(saved["stats"], graph) if isinstance(graph, Mapping) else story.stats_view(saved["stats"], {})

    # ----------------------------------------------------------------------- export

    def _exportable(self, task_id: str) -> dict[str, Any]:
        graph = _peek(self._task(task_id)).get("graph")
        if not isinstance(graph, Mapping):
            raise StoryInputError("这个项目还没有互动剧")
        problems = [item["message"] for item in story.validate_graph(graph) if item["severity"] == "error"]
        if problems:
            raise StoryInputError("故事还有问题，导出的播放器会走不通：" + "；".join(problems[:5]))
        return dict(graph)

    def export_preview(self, task_id: str) -> dict[str, Any]:
        """What each format will carry, without downloading anything."""
        graph = _peek(self._task(task_id)).get("graph")
        if not isinstance(graph, Mapping):
            return {"ready": False, "errors": [], "media": [], "inline_limit_bytes": MAX_INLINE_BYTES}
        located = {item.url: item for item in _graph_media(graph)}
        rows = []
        for segment in graph.get("segments") or []:
            media = segment.get("media")
            if isinstance(media, Mapping) and media.get("url"):
                item = located[media["url"]]
                rows.append({
                    "segment_id": segment["id"], "title": segment.get("title") or segment["id"], "kind": item.kind,
                    "status": item.status, "size": item.size,
                })
        issues = story.validate_graph(graph)
        errors = [item for item in issues if item["severity"] == "error"]
        return {"ready": not errors, "errors": errors, "media": rows, "inline_limit_bytes": MAX_INLINE_BYTES}

    def export_html(self, task_id: str, *, lang: str = "zh-CN") -> ExportFile:
        graph = self._exportable(task_id)
        inlined: dict[str, str] = {}
        budget = MAX_INLINE_BYTES
        with tempfile.TemporaryDirectory(prefix="istory_") as workdir:
            for item in _graph_media(graph):
                if item.status == "local" and item.size > budget:
                    continue
                path = _fetch(item, workdir)
                if not path or os.path.getsize(path) > budget:
                    continue
                proven = _proven_type(path, item.kind)
                if not proven:
                    continue
                budget -= os.path.getsize(path)
                with open(path, "rb") as handle:
                    inlined[item.url] = f"data:{proven};base64,{base64.b64encode(handle.read()).decode('ascii')}"
        page = story.render_player_html(story.player_story(graph, inlined), lang=lang)
        return ExportFile(_download_name(str(graph.get("title") or ""), "html"), "text/html; charset=utf-8", content=page.encode("utf-8"))

    def export_zip(self, task_id: str, *, lang: str = "zh-CN") -> ExportFile:
        """``index.html`` beside ``media/``. The archive is a temporary file; the caller removes it after sending."""
        graph = self._exportable(task_id)
        handle, archive = tempfile.mkstemp(prefix="istory_", suffix=".zip")
        os.close(handle)
        try:
            bundled: dict[str, str] = {}
            left_out: list[str] = []
            budget = MAX_ZIP_MEDIA_BYTES
            with zipfile.ZipFile(archive, "w", allowZip64=True) as bundle, tempfile.TemporaryDirectory(prefix="istory_") as workdir:
                for number, item in enumerate(_graph_media(graph), start=1):
                    path = _fetch(item, workdir)
                    proven = _proven_type(path, item.kind) if path else None
                    if not path or not proven or os.path.getsize(path) > budget:
                        left_out.append(item.url)
                        continue
                    budget -= os.path.getsize(path)
                    # Numbered names: nothing from a URL or a filename ever becomes a path inside the archive.
                    member = f"media/{number:04d}.{_EXTENSIONS[proven]}"
                    bundle.write(path, member, compress_type=zipfile.ZIP_STORED)
                    bundled[item.url] = member
                    if item.status == "remote":
                        os.remove(path)
                page = story.render_player_html(story.player_story(graph, bundled), lang=lang, bundled=True)
                bundle.writestr("index.html", page, compress_type=zipfile.ZIP_DEFLATED)
                notes = [
                    "Open index.html in a browser to play. Keep the media folder beside it.",
                    "打开 index.html 即可播放；media 文件夹要放在它旁边。",
                ]
                if left_out:
                    notes += ["", f"{len(left_out)} media file(s) could not be included and play as text cards:", *[f"- {_visible_address(url)}" for url in left_out]]
                bundle.writestr("README.txt", "\n".join(notes) + "\n", compress_type=zipfile.ZIP_DEFLATED)
        except Exception:
            if os.path.exists(archive):
                os.remove(archive)
            raise
        return ExportFile(_download_name(str(graph.get("title") or ""), "zip"), "application/zip", path=archive)


def _visible_address(url: str) -> str:
    # A provider's signed link is a credential until it expires; the query string stays out of a shared file.
    return os.path.basename(url.split("?", 1)[0]) or "media"


__all__ = ["ASSET_KEY", "ExportFile", "InteractiveStoryService", "StoryConflict", "StoryInputError", "StoryPlanError", "project_media", "store_of"]
