# -*- coding: utf-8 -*-
"""全集景别节奏：编剧给每个分镜排的景别连成一条线，第 4 步每场照它起幅。

第 4 步各场的分镜表是并行写的，写表的人看不到前后场用了什么景别，单格长镜的场一多，整集就全落在中景。
编剧的视觉层一次写完一集，景别排得开(``writer_rule`` 讲给它听)；这里把它排的读成每场一句「开场景别」，
连用超了的那一场改成「换一档」，一集里缺远 / 全或缺近 / 特时给第一场 / 最后一场补上。
同一档最多连用几场、一集至少几档，和成片验收单(:mod:`app.core.delivery_check`)读同一份数。
写法在 app/data/prompt/size_rhythm.json。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "size_rhythm"
_CHECK = "delivery_check"


def _note(key: str, **values: Any) -> str:
    return str(prompt_data.value(_DATA, "note")[key]).format(**values)


def run_limit() -> int:
    return int(prompt_data.value(_CHECK, "max_same_size_run"))


def writer_rule() -> str:
    """编剧视觉层里 shot_type 一栏的排法：同一档最多连用几镜、一集至少几档。"""
    run = run_limit()
    return str(prompt_data.value(_DATA, "writer_rule")).format(run=run, next=run + 1, kinds=int(prompt_data.value(_CHECK, "min_sizes_in_cut")))


def band(shot_type: Any) -> str:
    """编剧的 shot_type(英文枚举) → 景别档(远 / 全 / 中 / 近 / 特)；过肩、主观这类不分档的是空串。"""
    return str(prompt_data.value(_DATA, "shot_type_bands").get(str(shot_type or "").strip(), ""))


def _episodes(task: Mapping[str, Any]) -> list[list[tuple[str, str]]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get("2_screenwriting") if isinstance(assets.get("2_screenwriting"), Mapping) else {}
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    ordered: list[list[tuple[str, str]]] = []
    for number in sorted(episodes, key=lambda key: int(key) if str(key).isdigit() else 0):
        script = (episodes[number] or {}).get("script") if isinstance(episodes[number], Mapping) else None
        scenes = script.get("scenes") if isinstance(script, Mapping) else None
        rows = []
        for scene in scenes or []:
            if isinstance(scene, Mapping) and str(scene.get("scene_id") or "").strip():
                composition = ((scene.get("image_prompt") or {}).get("composition") or {}) if isinstance(scene.get("image_prompt"), Mapping) else {}
                rows.append((str(scene["scene_id"]).strip(), band(composition.get("shot_type") if isinstance(composition, Mapping) else "")))
        if rows:
            ordered.append(rows)
    return ordered


def plan(task: Mapping[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """每场的开场景别安排：scene_id → [(planned | change | establish | land_close, 参数)]。没有编剧方案的场不在里面。"""
    labels = prompt_data.value(_DATA, "band_labels")
    wide, close = set(prompt_data.words(_DATA, "wide_bands")), set(prompt_data.words(_DATA, "close_bands"))
    limit = run_limit()
    notes: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for rows in _episodes(task):
        bands = [value for _sid, value in rows]
        establish = not any(value in wide for value in bands)
        if establish:
            bands[0] = str(prompt_data.value(_DATA, "establish_band"))
        run_band, run = "", 0
        for index, (scene_id, _written) in enumerate(rows):
            value = bands[index]
            entries: list[tuple[str, dict[str, Any]]] = []
            if index == 0 and establish:
                entries.append(("establish", {}))
                run_band, run = value, 1
            elif not value:
                run_band, run = "", 0
            elif value == run_band and run >= limit:
                # 编剧排的连用超了：这一场换一档，远近交给表格作者按戏选；换了以后连用从下一场重新数。
                entries.append(("change", {"count": run, "label": labels[value]}))
                run_band, run = "", 0
            else:
                run = run + 1 if value == run_band else 1
                run_band = value
                entries.append(("planned", {"label": labels[value]}))
            notes[scene_id] = entries
        if not any(value in close for value in bands):
            notes[rows[-1][0]].append(("land_close", {}))
    return notes


def scene_note(task: Mapping[str, Any], scene_id: str) -> str:
    """写进第 4 步分镜表提示词的一段：本场开场景别(编剧没排就不写)，加上景别不变只出一格。"""
    lines = [_note(kind, **values) for kind, values in plan(task).get(str(scene_id or "").strip(), [])]
    return _note("heading") + "".join([*lines, _note("one_picture")])


__all__ = ["band", "plan", "run_limit", "scene_note", "writer_rule"]
