# -*- coding: utf-8 -*-
"""每镜控制表：这一镜要保留的几件事(动作与运镜、开场站位、空间层次、外观、节奏、场地)各靠哪份素材。

做 AI 视频的起点不是提示词，而是「保留什么、靠谁保留」：白模管动作，深度管空间，参考图管外观，
场地图管背景。两份素材抢同一件事时模型会在中间折中——每多一份控制就多一次信息损失，所以表里
把重复的和缺的标出来(最小控制集)，只提示、不拦生成。措辞在 data/prompt/control_table.json。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data
from app.core.camera_motion import normalize_camera_motion
from app.service import director_desk_service as desk

_DATA = "control_table"


def _word(group: str, key: str, *args: Any) -> str:
    return str(prompt_data.value(_DATA, group)[key]).format(*args)


def _desk_still(task: Mapping[str, Any], shot: Mapping[str, Any]) -> str:
    """导演台应用到这一镜的静帧地址；没应用时为空串。"""
    entry = (desk._peek(task).get("scenes") or {}).get(str(shot.get("scene_id") or ""))
    if not isinstance(entry, Mapping):
        return ""
    applied = (entry.get("applied") or {}).get(str(shot.get("shot_id")))
    still_id = applied.get("still") if isinstance(applied, Mapping) else None
    capture = next((item for item in entry.get("captures") or [] if isinstance(item, Mapping) and item.get("id") == still_id), None)
    return str(capture.get("url") or "") if capture and not capture.get("stale") else ""


def _has_stage_plan(task: Mapping[str, Any], scene_id: str) -> bool:
    plans = (task.get("assets") or {}).get("4_spatial") if isinstance(task.get("assets"), Mapping) else None
    scenes = plans.get("scenes") if isinstance(plans, Mapping) else None
    return isinstance(scenes, Mapping) and bool(scenes.get(scene_id))


def control_table(task: Mapping[str, Any], shot: Mapping[str, Any], assets: list[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """这一镜的控制表：[{aspect, label, sources, status(ok/duplicate/missing/none), note}]。

    ``assets`` 是这一镜用到的资产(asset_dependents.shot_assets 的结果)，用来数角色参考图和场地图。
    """
    rows: list[dict[str, Any]] = []

    def row(aspect: str, sources: list[str], status: str = "ok", note: str = "") -> None:
        if not sources and status == "ok":
            status = "none"
        rows.append({"aspect": aspect, "label": _word("aspects", aspect), "sources": sources, "status": status, "note": note})

    blockout = desk.shot_blockout(task, shot)
    videos = [str(url) for url in shot.get("reference_videos") or [] if url]
    other_videos = [url for url in videos if url != blockout.clip_url and url not in blockout.stale_urls]
    visual = shot.get("visual") if isinstance(shot.get("visual"), Mapping) else {}
    camera, _ = normalize_camera_motion(visual.get("camera_motion")) if visual.get("camera_motion") else ("", False)

    # 动作与运镜：白模 / 深度视频、附加的参考视频、文字运镜。
    motion = []
    if blockout.clip_url:
        motion.append(_word("sources", "depth" if blockout.depth else "blockout"))
    motion += [_word("sources", "motion_video")] * len(other_videos)
    if camera:
        motion.append(_word("sources", "camera_text", camera))
    video_count = (1 if blockout.clip_url else 0) + len(other_videos)
    if video_count > 1:
        row("motion", motion, "duplicate", _word("notes", "motion_duplicate", video_count, "、".join(motion[:video_count])))
    elif blockout.owns_camera and camera and camera != "Static":
        row("motion", motion, "duplicate", _word("notes", "camera_duplicate", camera))
    else:
        row("motion", motion or [_word("sources", "text_only")])

    # 开场构图与站位：分镜画面、导演台静帧、附加的参考图、导演台站位。
    still = _desk_still(task, shot)
    extra = [url for url in shot.get("sequence_images") or [] if url and url != still]
    pose = []
    if shot.get("image_url"):
        pose.append(_word("sources", "storyboard"))
    if still:
        pose.append(_word("sources", "desk_still"))
    if extra:
        pose.append(_word("sources", "extra_still", len(extra)))
    if _has_stage_plan(task, str(shot.get("scene_id") or "")):
        pose.append(_word("sources", "stage_plan"))
    if shot.get("image_url") and still:
        row("pose", pose, "duplicate", _word("notes", "pose_duplicate"))
    else:
        row("pose", pose or [_word("sources", "text_only")])

    used = [item for item in assets or [] if isinstance(item, Mapping)]
    actors = [str(item.get("name") or "") for item in used if item.get("kind") == "actor" and (item.get("in_video") or item.get("in_storyboard"))]
    scenes = [str(item.get("name") or "") for item in used if item.get("kind") == "scene" and (item.get("in_video") or item.get("in_storyboard"))]

    # 空间层次：深度视频、导演台站位、场地图。
    space = []
    if blockout.clip_url and blockout.depth:
        space.append(_word("sources", "depth"))
    if _has_stage_plan(task, str(shot.get("scene_id") or "")):
        space.append(_word("sources", "stage_plan"))
    if scenes:
        space.append(_word("sources", "scene_refs", "、".join(dict.fromkeys(scenes))))
    if blockout.depth and not shot.get("image_url") and not scenes:
        row("space", space, "missing", _word("notes", "depth_with_still"))
    else:
        row("space", space or [_word("sources", "text_only")])

    # 人物外观：角色参考图。有人物却没图，长相只靠文字。
    people = [str(name) for name in (shot.get("characters") or []) if str(name).strip() and str(name).strip() not in ("无", "空镜")]
    if actors:
        row("look", [_word("sources", "actor_refs", "、".join(dict.fromkeys(actors)))])
    elif people:
        row("look", [_word("sources", "text_only")], "missing", _word("notes", "look_missing"))
    else:
        row("look", [])

    # 节奏：参考音频。
    row("rhythm", [_word("sources", "audio")] * len([url for url in shot.get("reference_audios") or [] if url]))

    # 场地与背景：场地图。
    if scenes:
        row("place", [_word("sources", "scene_refs", "、".join(dict.fromkeys(scenes)))])
    else:
        row("place", [_word("sources", "text_only")], "missing", _word("notes", "place_missing"))
    return rows


__all__ = ["control_table"]
