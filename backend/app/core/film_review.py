# -*- coding: utf-8 -*-
"""成片自动验收：从成片均匀截帧拼成一张联系表，交给能看图的模型打分，再按项目真实产物出一份发布报告。

成片质量门禁要的七项分数 (``video_quality.VideoQualityMeasurements``) 来自看图模型对联系表的打分：一次调用
看全片十几帧，既能比同一角色前后是不是一张脸，也能看相邻帧是否连贯。模型听不到声音，台词情绪与口型两项只按
画面判断(字幕出现时说话人的嘴和表情)；分镜里记过声音质检(``sound_checks``)的，台词时序取两者较低的那个。

八 Agent 发布门禁按项目里真实存在的产物出报告：每件交付物在 ``film_review.json`` 里对应到项目资产，
找不到就记缺失，不替它编造。这份报告只提示，不拦成片完成；完成要的是质量验收通过加上人说「确认发布」。
说法、帧数和交付物对照表在 app/data/prompt/film_review.json。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PIL import Image, ImageDraw

from app.core import media_compositor, prompt_data
from app.core.video_quality import VideoQualityMeasurements

_DATA = "film_review"
SCORE_KEYS = (
    "identity_consistency", "anatomy_integrity", "expression_fidelity", "photorealism",
    "temporal_continuity", "dialogue_emotion_timing", "lip_sync",
)


class FilmReviewError(RuntimeError):
    """成片没法验收：找不到成片文件、截不出帧、没有能看图的模型或模型没给出能读的分数。"""


def _number(key: str) -> int:
    return prompt_data.number(_DATA, key)


def timestamps(duration: float, count: int) -> list[float]:
    """均匀分布在片中的截帧时间：避开片头片尾各半格，每格取它那一段的中点。"""
    if duration <= 0 or count <= 0:
        return []
    step = duration / count
    return [round(step * (index + 0.5), 2) for index in range(count)]


def _duration(path: str) -> float:
    probe = media_compositor._ffprobe()
    if not probe:
        return 0.0
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        return float(out or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def _local_film(video: str, work: str) -> str:
    """成片在本机的路径：链接就下载到 ``work`` 里。"""
    path = media_compositor.local_media_path(video) or video
    if str(path).startswith("http"):
        local = os.path.join(work, "film.mp4")
        if not media_compositor._download(path, local):
            raise FilmReviewError("成片下载失败")
        path = local
    if not os.path.exists(path):
        raise FilmReviewError("找不到成片文件")
    return str(path)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


_BLACK = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*([\d.]+)")


def _filter_log(ffmpeg: str, path: str, chain: str) -> str:
    try:
        return subprocess.run(
            [ffmpeg, "-hide_banner", "-nostats", "-i", path, "-an", "-vf", chain, "-f", "null", "-"],
            capture_output=True, text=True, timeout=600,
        ).stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def scan_defects(path: str, duration: float | None = None) -> list[str]:
    """整片逐帧扫：黑场、上半或下半全黑、定格不动。看图模型只看十来帧，漏掉的短硬伤这里补上；不调模型。

    片头(标题卡)和片尾(淡出)几秒不算。每条写明起止时间，直接作为硬伤交给质量门禁。
    """
    ffmpeg = media_compositor._ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return []
    rules = prompt_data.value(_DATA, "scan")
    duration = duration if duration is not None else _duration(path)
    head, tail = float(rules["skip_head_seconds"]), float(rules["skip_tail_seconds"])
    scale = f"scale={int(rules['scale_width'])}:-2"
    found: list[tuple[float, float, str]] = []
    full = str(rules["regions"][0]["label"])
    for region in rules["regions"]:
        black = (
            f"blackdetect=d={region['min_seconds']}:pix_th={region['pixel_threshold']}:pic_th={rules['black_picture_ratio']}"
        )
        chain = ",".join(part for part in (scale, region["crop"], black) if part)
        for start, end in _BLACK.findall(_filter_log(ffmpeg, path, chain)):
            found.append((float(start), float(end), str(region["label"])))
    log = _filter_log(ffmpeg, path, f"{scale},freezedetect=n={rules['freeze_noise']}:d={rules['freeze_min_seconds']}")
    for start, end in zip(_FREEZE_START.findall(log), _FREEZE_END.findall(log) + [str(duration)] * 4):
        found.append((float(start), float(end), str(rules["freeze_label"])))
    top, bottom = (str(region["label"]) for region in rules["regions"][1:3])

    def overlaps(a: tuple[float, float, str], b: tuple[float, float, str]) -> bool:
        return a[0] < b[1] and a[1] > b[0]

    kept: list[tuple[float, float, str]] = []
    for item in sorted(found):
        start, end, label = item
        if end <= head or (duration and start >= duration - tail):
            continue
        # 全黑的时候上下边当然也黑：同一段只报最大的那一种。
        if label != full and any(other[2] == full and overlaps(item, other) for other in found):
            continue
        if label == bottom and any(other[2] == top and overlaps(item, other) for other in found):
            continue  # 已经并进上方那条
        if label == top:
            band = next((other for other in found if other[2] == bottom and overlaps(item, other)), None)
            if band is not None:
                item = (min(start, band[0]), max(end, band[1]), str(rules["both_bands_label"]))
        # 只有一边黑：可能是构图(拱门下、暗处前景)，要持续得够久才算黑边。
        if item[2] in (top, bottom) and item[1] - item[0] < float(rules["single_band_min_seconds"]):
            continue
        kept.append(item)
    template = str(rules["defect"])
    return [
        template.format(start=_clock(start), end=_clock(end), label=label, seconds=end - start)
        for start, end, label in kept[: int(rules["max_defects"])]
    ]


def sample_frames(video: str, count: int | None = None) -> list[tuple[float, Image.Image]]:
    """成片里均匀截 ``count`` 帧：(秒, 画面)。本地文件或链接都行。"""
    ffmpeg = media_compositor._ffmpeg()
    if not ffmpeg:
        raise FilmReviewError("没有 ffmpeg，截不了帧")
    count = count or _number("frames")
    with tempfile.TemporaryDirectory(prefix="film-review-") as work:
        path = _local_film(video, work)
        frames: list[tuple[float, Image.Image]] = []
        for index, second in enumerate(timestamps(_duration(path), count)):
            out = os.path.join(work, f"{index:02d}.jpg")
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-ss", f"{second:.2f}", "-i", path, "-frames:v", "1", "-q:v", "3", out],
                    timeout=60, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if os.path.exists(out):
                with Image.open(out) as image:
                    frames.append((second, image.convert("RGB")))
    if not frames:
        raise FilmReviewError("成片里截不出画面")
    return frames


def contact_sheet(frames: Sequence[tuple[float, Image.Image]]) -> str:
    """按时间顺序排成网格，每格左上角标时间；返回 JPEG data URI，一次交给看图模型。"""
    columns = _number("columns")
    width = _number("cell_width")
    first = frames[0][1]
    height = max(1, round(width * first.height / max(1, first.width)))
    rows = -(-len(frames) // columns)
    sheet = Image.new("RGB", (columns * width, rows * height), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    for index, (second, image) in enumerate(frames):
        x, y = (index % columns) * width, (index // columns) * height
        sheet.paste(image.resize((width, height), Image.LANCZOS), (x, y))
        label = f"{index + 1}  {int(second // 60):02d}:{second % 60:04.1f}"
        draw.rectangle((x, y, x + 150, y + 26), fill=(0, 0, 0))
        draw.text((x + 6, y + 6), label, fill=(255, 255, 255))
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def parse_scores(answer: str | None) -> dict[str, Any]:
    """看图模型的回答 → 七项分数、硬伤、总评；缺项或读不出来就报错，不拿默认分凑数。"""
    text = str(answer or "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise FilmReviewError("看图模型没有给出分数")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise FilmReviewError("看图模型的分数读不出来") from exc
    missing = [key for key in SCORE_KEYS if not isinstance(data.get(key), (int, float))]
    if missing:
        raise FilmReviewError("看图模型漏打了：" + "、".join(missing))
    scores = {key: max(0.0, min(1.0, float(data[key]))) for key in SCORE_KEYS}
    defects = [str(item).strip()[:200] for item in (data.get("hard_defects") or []) if str(item).strip()][:20]
    return {"scores": scores, "hard_defects": defects, "notes": str(data.get("notes") or "").strip()[:200]}


def sound_check_ratio(clips: Sequence[Mapping[str, Any]]) -> float | None:
    """分镜视频记过的声音质检通过了几成；一条都没记就是 None(不拿它说事)。"""
    checks = [check for clip in clips if isinstance(clip, Mapping) for check in (clip.get("sound_checks") or []) if isinstance(check, Mapping)]
    if not checks:
        return None
    return sum(1 for check in checks if check.get("passed")) / len(checks)


def review(
    video: str,
    describe: Callable[[str, str, str], str | None],
    *,
    clips: Sequence[Mapping[str, Any]] = (),
    frames: Sequence[tuple[float, Image.Image]] | None = None,
) -> tuple[VideoQualityMeasurements, dict[str, Any]]:
    """验收一部成片：截帧 → 联系表 → 看图打分。``describe(system, prompt, image)`` 调看图模型。

    返回交给质量门禁的分数，和一份给人看的记录(分数来源、硬伤、总评)。
    """
    frames = list(frames) if frames is not None else sample_frames(video)
    # 整片扫描不花钱，先做：模型只看到十来帧，黑场、定格这类短硬伤靠它。成片不在本机就跳过。
    local = media_compositor.local_media_path(video) or video
    scanned = scan_defects(local) if os.path.exists(str(local)) else []
    sheet = contact_sheet(frames)
    parsed = parse_scores(describe(prompt_data.text(_DATA, "system"), prompt_data.text(_DATA, "prompt"), sheet))
    parsed["hard_defects"] = [*scanned, *parsed["hard_defects"]]
    scores = dict(parsed["scores"])
    sources = {key: "联系表看图" for key in SCORE_KEYS}
    ratio = sound_check_ratio(clips)
    if ratio is not None and ratio < scores["dialogue_emotion_timing"]:
        scores["dialogue_emotion_timing"] = round(ratio, 4)
        sources["dialogue_emotion_timing"] = "分镜声音质检通过率"
    measurements = VideoQualityMeasurements(
        **scores, hard_defects=parsed["hard_defects"], assessor=prompt_data.text(_DATA, "assessor"), evidence_urls=[],
    )
    record = {
        "scores": scores, "sources": sources, "hard_defects": parsed["hard_defects"], "notes": parsed["notes"],
        "frames": [second for second, _image in frames], "sound_check_ratio": ratio,
        "scanned_defects": scanned,
    }
    return measurements, record


def _present(assets: Mapping[str, Any], path: str) -> bool:
    value: Any = assets
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return False
        value = value.get(part)
    return bool(value)


def release_evidence(
    task: Mapping[str, Any], *, stage_complete: Callable[[int], bool], human_final_review: bool = False,
) -> dict[str, Any]:
    """八 Agent 发布门禁的证据，全部取自项目里真实存在的东西；没有的交付物就不报。"""
    from app.core.agent_council import _ROLE_OUTPUTS

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    sources = prompt_data.value(_DATA, "artifact_sources")
    stages = prompt_data.value(_DATA, "role_stages")
    artifacts = []
    for role, outputs in _ROLE_OUTPUTS.items():
        present = [item for item in outputs if any(_present(assets, path) for path in sources.get(item, []))]
        if present:
            artifacts.append({"role": role.value, "artifact_ids": present, "approved": stage_complete(int(stages[role.value]))})
    review_record = (assets.get("7") or {}).get("auto_review") if isinstance(assets.get("7"), Mapping) else None
    scores = (review_record or {}).get("scores") or {}

    def five(value: float | None, fallback: float = 3.0) -> float:
        return round(1 + 4 * value, 2) if value is not None else fallback

    gate = lambda key: bool((assets.get(key) or {}).get("passed")) if isinstance(assets.get(key), Mapping) else False  # noqa: E731
    seven = assets.get("7") if isinstance(assets.get("7"), Mapping) else {}
    storyboard = assets.get("4_storyboard") if isinstance(assets.get("4_storyboard"), Mapping) else {}
    characters = [item for item in assets.get("3_characters") or [] if isinstance(item, Mapping)]
    views = [str(view.get("view")) for view in (characters[0].get("views") or []) if isinstance(view, Mapping)] if characters else []
    audio = [scores.get("dialogue_emotion_timing"), scores.get("lip_sync")]
    visual = [scores.get(key) for key in ("photorealism", "anatomy_integrity", "expression_fidelity")]
    final_present = bool(seven.get("final_video_url"))
    return {
        "artifacts": artifacts or [{"role": "executive_director", "artifact_ids": ["director_constitution"], "approved": False}],
        "issues": [],
        "dimension_scores": {
            "story": 5.0 if gate("2_review_gate") else 3.0,
            "character": five(scores.get("identity_consistency")),
            "continuity": five(scores.get("temporal_continuity")),
            "storyboard": 5.0 if gate("4_quality") else 3.0,
            "visual": five(sum(visual) / 3) if all(value is not None for value in visual) else 3.0,
            "audio": five(sum(audio) / 2) if all(value is not None for value in audio) else 3.0,
            "delivery": 5.0 if final_present and seven.get("subtitles") else 3.0,
            "compliance": 3.0,
        },
        "five_view_order": views,
        "storyboard_rows": int(storyboard.get("rows") or 0),
        "storyboard_columns": int(storyboard.get("columns") or 0),
        "storyboard_panel_count": len(storyboard.get("panels") or []),
        "storyboard_motion_fingerprints_match": all(
            isinstance(shot, Mapping) and shot.get("contract_fingerprint") for shot in assets.get("4") or []
        ) and bool(assets.get("4")),
        "video_route_accepted": all(isinstance(clip, Mapping) and clip.get("video_url") for clip in assets.get("5") or []) and bool(assets.get("5")),
        "dialogue_timing_approved": (scores.get("dialogue_emotion_timing") or 0) >= 0.8,
        "audio_mix_approved": _present(assets, "6.audio_url"),
        "final_media_present": final_present,
        "subtitles_approved": bool(seven.get("subtitles")),
        "rights_and_provenance_approved": False,
        "platform_compliance_approved": False,
        "human_final_review": human_final_review,
    }


__all__ = [
    "FilmReviewError", "SCORE_KEYS", "contact_sheet", "parse_scores", "release_evidence", "review", "sample_frames", "scan_defects",
    "sound_check_ratio", "timestamps",
]
