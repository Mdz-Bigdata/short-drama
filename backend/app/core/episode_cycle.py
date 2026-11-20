# -*- coding: utf-8 -*-
"""分集制作：多集项目的产物按集归档，但步骤按整部剧往下走——第 4 步把所有集的分镜做完，第 5 步把所有集的
视频做完，然后是所有集的音频、所有集的成片，最后宣发。任何一步都不会因为「该做下一集了」回到前面的步骤。

早先是「逐集」：一集走完 分镜 → 视觉 → 音频 → 合成 才开始下一集，于是做到第 6 步又回到第 4 步，进度从
6/7 掉回「已完成 3/7」。2026-11-19 按使用者的要求改成步骤优先(从分镜开始严格往下推进，不回退、不跳着走)。

「这一步现在做哪一集」不单独存游标，而是推出来的(``episode_for``)：还没出成片的集里，第一个缺这一步产物的。
产物一落库，它自然变成下一集；一步里所有集都做完，工作流的「下一步」才往后走。

产物按集归档在 ``assets["episode_cycle"]["episodes"][N]``(audio / timeline / film)，键名不以数字开头，
重跑前面阶段时的清理只动当前集，已完成的集永远不会被冲掉。第 5 阶段的片段仍在 ``assets["5"]``，
每条带 scene_id / episode / shot_uid，按集合并，不再按「镜号」覆盖(各场镜号都从 1 开始)。

只对 2 集及以上、且还没有按旧方式产出整部视频的项目生效；``config.episode_by_episode = False`` 可关闭。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence
from app.core import prompt_data


_WORDING_FILE = "episode_cycle"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/episode_cycle.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

CYCLE_KEY = "episode_cycle"
TIMELINE_KEY = "7_timeline"
VIEW_MARKER = "_episode_view"
_SCENE = re.compile(r"E(\d{1,3})S(\d{1,3})", re.IGNORECASE)


def episode_of_scene(scene_id: Any) -> int:
    match = re.search(r"E(\d{1,3})", str(scene_id or ""), flags=re.IGNORECASE)
    return max(1, min(200, int(match.group(1)))) if match else 1


def episode_of(item: Mapping[str, Any]) -> int:
    """一条镜头 / 片段属于第几集：显式的 episode 优先，否则看 scene_id。"""
    raw = item.get("episode") if isinstance(item, Mapping) else None
    if isinstance(raw, int) and raw > 0:
        return raw
    return episode_of_scene(item.get("scene_id") if isinstance(item, Mapping) else "")


def shot_uid(item: Mapping[str, Any]) -> int:
    """全剧唯一、稳定的镜头编号：第 E 集第 S 场第 N 镜 → E·100000 + S·100 + N(如 E2S11 第 3 镜 = 201103)。

    各场的镜号都从 1 开始，只用镜号做键会让不同场的片段互相覆盖；没有场号的旧数据退回镜号本身。
    """
    if isinstance(item.get("shot_uid"), int) and item["shot_uid"] > 0:
        return item["shot_uid"]
    try:
        number = int(item.get("shot_id") or 0)
    except (TypeError, ValueError):
        number = 0
    match = _SCENE.search(str(item.get("scene_id") or ""))
    if not match:
        return number
    return int(match.group(1)) * 100000 + int(match.group(2)) * 100 + number


def covered_uids(clip: Mapping[str, Any]) -> list[int]:
    """一段视频覆盖的镜头编号：分镜片段视频覆盖它的每个瞬间，单镜视频只覆盖自己。"""
    uids = clip.get("shot_uids")
    if isinstance(uids, list) and uids:
        return [int(uid) for uid in uids if isinstance(uid, int) or str(uid).isdigit()]
    return [shot_uid(clip)]


def clip_for(shot: Mapping[str, Any], clips: Sequence[Any]) -> dict[str, Any] | None:
    """这个镜头所在的那段视频；没有场号的旧片段按镜号对。"""
    uid = shot_uid(shot)
    for clip in clips:
        if isinstance(clip, dict) and (clip.get("scene_id") or clip.get("shot_uids")) and uid in covered_uids(clip):
            return clip
    for clip in clips:
        if isinstance(clip, dict) and not (clip.get("scene_id") or clip.get("shot_uids")) and str(clip.get("shot_id")) == str(shot.get("shot_id")):
            return clip
    return None


def episode_numbers(task: Mapping[str, Any]) -> list[int]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    progress = assets.get("4_progress") if isinstance(assets.get("4_progress"), Mapping) else {}
    numbers = sorted({
        int(item["number"]) for item in progress.get("episodes") or []
        if isinstance(item, Mapping) and isinstance(item.get("number"), int)
    })
    if numbers:
        return numbers
    boards = assets.get("4_scene_boards") if isinstance(assets.get("4_scene_boards"), Mapping) else {}
    return sorted({episode_of_scene(scene_id) for scene_id in boards})


def active(task: Mapping[str, Any]) -> bool:
    """逐集制作是否生效：2 集以上；已经按旧方式整部出过视频 / 音频 / 成片的项目不切换。"""
    if task.get(VIEW_MARKER):
        return False
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    if config.get("episode_by_episode") is False:
        return False
    if len(episode_numbers(task)) < 2:
        return False
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    if CYCLE_KEY in assets:
        return True
    return not any(assets.get(key) for key in ("5", "6", "7"))


def _cycle(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    cycle = assets.get(CYCLE_KEY)
    return cycle if isinstance(cycle, Mapping) else {}


def record(task: Mapping[str, Any], number: int) -> Mapping[str, Any]:
    episodes = _cycle(task).get("episodes")
    entry = episodes.get(str(number)) if isinstance(episodes, Mapping) else None
    return entry if isinstance(entry, Mapping) else {}


def writable_record(task: dict[str, Any], number: int) -> dict[str, Any]:
    cycle = task.setdefault("assets", {}).setdefault(CYCLE_KEY, {"version": 1, "episodes": {}})
    return cycle.setdefault("episodes", {}).setdefault(str(number), {})


def film_of(task: Mapping[str, Any], number: int) -> str:
    film = record(task, number).get("film")
    return str(film.get("final_video_url") or "") if isinstance(film, Mapping) else ""


def finished(task: Mapping[str, Any]) -> list[int]:
    return [number for number in episode_numbers(task) if film_of(task, number)]


def current_episode(task: Mapping[str, Any]) -> int | None:
    """第一个还没有成片的集；全部做完时为 None。"""
    return next((number for number in episode_numbers(task) if not film_of(task, number)), None)


def stage_done(task: Mapping[str, Any], number: int, stage: int) -> bool:
    """第 ``number`` 集有没有第 ``stage`` 步(4 分镜 / 5 视频 / 6 音频 / 7 成片)的产物。"""
    if stage == 4:
        return storyboard_complete(task, number)
    if stage == 5:
        shots = episode_shots(task, number)
        done = {uid for clip in episode_clips(task, number) if clip.get("video_url") for uid in covered_uids(clip)}
        return bool(shots) and all(shot_uid(shot) in done for shot in shots)
    if stage == 6:
        audio = record(task, number).get("audio")
        return isinstance(audio, Mapping) and bool(audio)
    if stage == 7:
        return bool(film_of(task, number))
    return True


def open_episodes(task: Mapping[str, Any]) -> list[int]:
    """还没出成片的集，按集号。出了成片的集不再被任何一步重新打开。"""
    return [number for number in episode_numbers(task) if not film_of(task, number)]


def episode_for(task: Mapping[str, Any], stage: int) -> int | None:
    """第 ``stage`` 步现在做哪一集：还没出成片的集里第一个缺这一步产物的。

    这一步的产物各集都有了(人要求重做这一步时)，就是第一个还没出成片的集；全部集都出了成片时为 None。
    """
    pending = open_episodes(task)
    return next((number for number in pending if not stage_done(task, number, stage)), pending[0] if pending else None)


def signature(task: Mapping[str, Any]) -> tuple:
    """每一集做到了哪一步：同一步连着做下一集时，自动推进靠它确认上一轮真的做成了一集。"""
    return tuple((number, tuple(stage_done(task, number, stage) for stage in (4, 5, 6, 7))) for number in episode_numbers(task))


def storyboard_complete(task: Mapping[str, Any], number: int) -> bool:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    progress = assets.get("4_progress") if isinstance(assets.get("4_progress"), Mapping) else {}
    return any(
        isinstance(item, Mapping) and item.get("number") == number and item.get("complete")
        for item in progress.get("episodes") or []
    )


def episode_shots(task: Mapping[str, Any], number: int) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    return [shot for shot in assets.get("4") or [] if isinstance(shot, dict) and episode_of(shot) == number]


def episode_clips(task: Mapping[str, Any], number: int) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    clips = [clip for clip in assets.get("5") or [] if isinstance(clip, dict) and clip.get("scene_id") and episode_of(clip) == number]
    return sorted(clips, key=shot_uid)


def other_clips(task: Mapping[str, Any], number: int) -> list[dict[str, Any]]:
    """别的集已经出好的片段：本集重做时原样保留。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    return [clip for clip in assets.get("5") or [] if isinstance(clip, dict) and clip.get("scene_id") and episode_of(clip) != number]


def merged_clips(others: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted([dict(clip) for clip in (*others, *current)], key=shot_uid)


def missing(task: Mapping[str, Any], stage: int) -> list[str] | None:
    """分集口径下第 4–8 阶段还缺什么；不分集(或不是这几个阶段)时返回 None，由原口径判断。

    一步要所有还没出成片的集都做完才算完成，所以「下一步」只会停在同一步或往后走。
    """
    if stage < 4 or not active(task):
        return None
    pending = open_episodes(task)
    if stage == 8:
        return [_text_of("missing.text.2").format(pending[0])] if pending else []
    gaps = [number for number in pending if not stage_done(task, number, stage)]
    if not gaps:
        return []
    key = {4: "missing.text", 5: "missing.text.3", 6: "missing.text.4", 7: "missing.text.5"}.get(stage)
    return [_text_of(key).format(",".join(map(str, gaps)))] if key else None


def episode_view(task: Mapping[str, Any], number: int) -> dict[str, Any]:
    """只看第 N 集的任务视图：第 4 阶段的镜头、第 5 阶段的片段、本集的音频与剪辑时间线。

    视图是浅拷贝；阶段代码在视图上读写，结果由调用方归档回本集。
    """
    assets = dict(task.get("assets") or {})
    entry = record(task, number)
    assets["4"] = episode_shots(task, number)
    assets["5"] = episode_clips(task, number)
    audio = entry.get("audio")
    if isinstance(audio, Mapping) and audio:
        assets["6"] = dict(audio)
    else:
        assets.pop("6", None)
    timeline = entry.get("timeline")
    if isinstance(timeline, Mapping) and timeline:
        assets[TIMELINE_KEY] = dict(timeline)
    else:
        assets.pop(TIMELINE_KEY, None)
    return {**task, "assets": assets, VIEW_MARKER: number}


def timeline_episode(task: Mapping[str, Any]) -> int | None:
    """剪辑时间线默认看哪一集：下一部要合成的集已有片段就看它，否则看最近做完的一集。"""
    current = current_episode(task)
    if current is not None and episode_clips(task, current):
        return current
    done = finished(task)
    return done[-1] if done else current


def discard_for_rerun(task: dict[str, Any], stage: int) -> None:
    """开始做第 ``stage`` 步：只清掉这一步要做的那一集在它之后的产物，别的集一概不动。"""
    current = episode_for(task, stage)
    if current is None:
        return
    assets = task.setdefault("assets", {})
    if stage < 5:
        assets["5"] = other_clips(task, current)
    entry = writable_record(task, current)
    if stage < 6:
        entry.pop("audio", None)
    if stage < 7:
        entry.pop("timeline", None)
        entry.pop("film", None)


def films(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for number in episode_numbers(task):
        film = record(task, number).get("film")
        if isinstance(film, Mapping) and film.get("final_video_url"):
            out.append({"episode": number, "final_video_url": film["final_video_url"], "completed_at": film.get("completed_at", "")})
    return out


def status_line(task: Mapping[str, Any]) -> str:
    if not active(task):
        return ""
    numbers = episode_numbers(task)
    current = current_episode(task)
    done = finished(task)
    if current is None:
        return _text_of("status_line.text").format(len(numbers))
    return _text_of("status_line.text.2").format(len(numbers), len(done))
