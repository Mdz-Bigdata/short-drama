# -*- coding: utf-8 -*-
"""一个分镜片段，一段运镜视频。

第 4 阶段按「15 秒切片」拆分镜：一场戏一张看板，看板上的几格是同一段戏里连续的几个瞬间
(E1S01 = 2 个连续瞬间，计划 11.5 秒)。第 5 阶段据此为每个片段只生成一段视频：几个瞬间按顺序
写进同一条多镜头提示词，几格分镜画面按顺序作参考，一次出片，镜头之间在片内平滑过渡。

单次请求的时长有上限(Seedance 2.0 为 15 秒)。片段计划时长放得下就整段一次生成；放不下时
按瞬间顺序切成连续的几段，每段都放得下，绝不把一个片段压缩成更短的请求。

本模块只做规划与提示词拼装：不调供应商、不写任务。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.core import action_grammar, prompt_budget, prompt_data
from app.core.prompt_distiller import dedupe_blocks, repeated_clauses_out
from app.core.episode_cycle import covered_uids, shot_uid  # noqa: F401 - re-exported
from app.core.transition_catalog import smooth_text
from app.core.asset_mentions import mark_mentions
from app.core.spatial_stage import clip_brief
from app.core.video_prompt_engine import CompiledVideoPrompt, ShotPromptInput, _asset_anchor_sections, _render, bridge_line
from app.core.video_references import MIN_SHOT_SECONDS

BEAT_HEAD = prompt_data.text("clip_prompt", "beat_head")
_BEAT_HEAD = re.compile(re.escape(BEAT_HEAD) + r"(\d+)/(\d+)")
# 一个瞬间进入下一个瞬间：文戏片内没有硬切，按第 4 阶段规划的切点写成连贯的过渡。
DEFAULT_JOIN = prompt_data.text("clip_prompt", "default_join")
# 打戏相反：张力来自剪切密度，叠化和淡入淡出会立刻变软；每一刀落在接触帧上。
# 一整句不带「；」：去重按分句比，带了分号后半句会在第二个瞬间之后被当成重复删掉。
FIGHT_JOIN = prompt_data.text("clip_prompt", "fight_join")
# 每个瞬间的正文按这个顺序拼进片段；空的跳过。单镜的「运镜契约」整段(motion)不进片段：它把画面、
# 机位、轴线再写一遍，还带着「承接上一镜最后一帧」——同一段视频里的几个瞬间之间没有上一镜。
_BEAT_SECTIONS = ("camera", "composition", "subject", "expression", "contact", "handoff", "dialogue", "dialogue_notes", "end_state")


def enabled(config: Mapping[str, Any] | None) -> bool:
    """默认每个分镜片段一段视频；项目设 ``video_granularity: "shot"`` 时回到每个瞬间单独一段。"""
    return str((config or {}).get("video_granularity") or "slice").strip().lower() != "shot"


def _seconds(value: Any) -> float:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else 0.0


def beat_seconds(shot: Mapping[str, Any]) -> float:
    """一个瞬间的计划时长：视觉工作区里人工定的优先，其次是分镜表写的「5秒」。"""
    visual = shot.get("visual") if isinstance(shot.get("visual"), Mapping) else {}
    manual = _seconds(visual.get("duration_seconds")) if visual else 0.0
    return manual or _seconds(shot.get("duration"))


def planned_seconds(task: Mapping[str, Any], scene_id: str) -> float:
    """第 4 阶段为这个片段规划的总时长(看板提示词里的 duration_seconds)。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    boards = assets.get("4_scene_boards") if isinstance(assets.get("4_scene_boards"), Mapping) else {}
    board = boards.get(scene_id) if isinstance(boards.get(scene_id), Mapping) else {}
    detail = board.get("prompt_detail") if isinstance(board.get("prompt_detail"), Mapping) else {}
    return _seconds(detail.get("duration_seconds"))


@dataclass
class Slice:
    scene_id: str
    indexes: list[int]          # 在 shots 列表里的位置，按顺序
    seconds: int                # 这一段请求的时长
    part: int = 1               # 片段被切开时：第几段 / 共几段
    parts: int = 1
    beat_seconds: list[float] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.scene_id} 片段" + (f" {self.part}/{self.parts}" if self.parts > 1 else "")


def _fit(seconds: float, ceiling: int) -> int:
    return max(MIN_SHOT_SECONDS, min(ceiling, int(math.ceil(seconds - 1e-9))))


def plan(shots: Sequence[Mapping[str, Any]], *, ceiling: int, planned: Mapping[str, float] | None = None) -> list[Slice]:
    """把镜头按场(分镜片段)分组，每组一段视频；放不下单次上限的片段按瞬间顺序切开。

    时长以第 4 阶段的片段规划为准；有人工改过瞬间时长时，按人工时长相加。
    """
    planned = planned or {}
    groups: list[tuple[str, list[int]]] = []
    for index, shot in enumerate(shots):
        scene_id = str(shot.get("scene_id") or "")
        if groups and groups[-1][0] == scene_id and scene_id:
            groups[-1][1].append(index)
        else:
            groups.append((scene_id, [index]))
    slices: list[Slice] = []
    for scene_id, indexes in groups:
        beats = [beat_seconds(shots[i]) or float(MIN_SHOT_SECONDS) for i in indexes]
        manual = any(isinstance(shots[i].get("visual"), Mapping) and _seconds(shots[i]["visual"].get("duration_seconds")) for i in indexes)
        total = sum(beats)
        target = total if manual or not planned.get(scene_id) else float(planned[scene_id])
        scaled = [beat * target / total for beat in beats] if total else beats
        if target <= ceiling + 1e-9:
            slices.append(Slice(scene_id, list(indexes), _fit(target, ceiling), beat_seconds=[round(b, 2) for b in scaled]))
            continue
        chunks: list[tuple[list[int], list[float]]] = [([], [])]
        for index, beat in zip(indexes, scaled):
            if chunks[-1][0] and sum(chunks[-1][1]) + beat > ceiling + 1e-9:
                chunks.append(([], []))
            chunks[-1][0].append(index)
            chunks[-1][1].append(beat)
        for part, (chunk, seconds) in enumerate(chunks, start=1):
            slices.append(Slice(scene_id, chunk, _fit(sum(seconds), ceiling), part, len(chunks), [round(b, 2) for b in seconds]))
    return slices


def fingerprint(beat_fingerprints: Sequence[str], *, seconds: int, part: int, parts: int) -> str:
    """一段视频的请求指纹：任何一个瞬间的契约、时长或切分变了，旧片就不能当同一请求复用。"""
    raw = json.dumps({"beats": list(beat_fingerprints), "seconds": seconds, "part": part, "parts": parts}, sort_keys=True)
    return "slice:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def beat_count(prompt: str) -> int:
    """提示词里写了几个镜头块(网关据此告诉提示词优化器这是多镜头视频)。"""
    found = _BEAT_HEAD.search(prompt or "")
    return int(found.group(2)) if found else 1


@dataclass
class Beat:
    """一个瞬间拼进片段时用到的东西：它自己编译好的分节(已按单镜预算裁过)和切点。"""
    sections: Mapping[str, str]
    size: str = ""
    motion: str = ""
    cut_in: str = ""
    override: str = ""
    stage: Sequence[str] = ()


def _block(
    number: int, total: int, beat: Beat, *, include_motion: bool = False, drop_phrases: Sequence[str] = (), fight: bool = False,
) -> str:
    head = f"{BEAT_HEAD}{number}/{total}｜{beat.size or '景别承接'}｜{beat.motion or '运镜承接'}】"
    # 文戏片内不硬切：旧看板里规划的「硬切·顺接」按连贯衔接写；打戏每一刀都是硬切。
    if number == 1:
        join = ""
    elif fight:
        join = f"衔接：{FIGHT_JOIN}。"
    else:
        join = f"衔接：{smooth_text(beat.cut_in).strip() or DEFAULT_JOIN}。"
    if beat.override.strip():
        return f"{head}{join}{beat.override.strip()}"
    # include_motion：精炼前把(已去重的)运镜契约也带上——机位、焦段、调度距离只写在那里。
    # 景别和运镜块头已经写了，这里不再写一遍。
    keys = ("composition", "subject", "motion", *_BEAT_SECTIONS[3:]) if include_motion else _BEAT_SECTIONS[1:]
    values = []
    for key in keys:
        value = str(beat.sections.get(key) or "").strip()
        if key == "composition" and beat.size:
            value = value.replace(f"构图：{beat.size}，", "构图：", 1)
        for phrase in drop_phrases:
            value = value.replace(str(phrase), "").strip()
        if value:
            values.append(value if value.endswith(("。", "；", "）", ")", "】")) else f"{value}。")
    return f"{head}{join}{''.join(values)}"


def _lines(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        for line in str(value or "").splitlines():
            if line.strip() and line.strip() not in seen:
                seen.append(line.strip())
    return seen


def compile_prompt(
    beats: Sequence[Beat], *, model: str, aspect_ratio: str = "9:16", cast: Sequence[str] = (),
    scenes: Sequence[str] = (), props: Sequence[str] = (), costumes: Sequence[tuple[str, str]] = (), reference_notes: str = "",
    storyboard_frames: int = 0,
    part: int = 1, parts: int = 1, style_pack: str = "", include_motion: bool = False, drop_phrases: Sequence[str] = (),
    fight: bool = False, previous_end: str = "", last_frame: bool = False,
) -> CompiledVideoPrompt:
    """几个连续瞬间的一条多镜头提示词。``fight`` 的场次镜头之间硬切，打击点落在特写。

    风格锁、锚点、空间锁只写一次；每个瞬间一个镜头块，块里是它自己已按单镜预算裁好的正文，
    所以片段越长不会把后面的瞬间裁掉。只有一个瞬间时退化为普通单镜结构。
    """
    if not beats:
        raise ValueError("a slice needs at least one beat")
    first = beats[0].sections
    total = len(beats)
    structure = [
        f"同一场戏连续{total}个镜头，一次生成一段连贯视频，镜头按编号顺序推进" if total > 1 else "单镜连续画面，一镜到底不切镜",
        f"画幅{aspect_ratio}",
    ]
    if storyboard_frames > 1:
        structure.append(f"所给{storyboard_frames}张分镜画面按镜头顺序排列，依次是镜头1到镜头{storyboard_frames}的开场构图")
    elif storyboard_frames == 1:
        structure.append("以所给分镜画面为开场构图")
    if total > 1 and fight:
        structure.append("镜头之间全部硬切，不叠化、不淡入淡出、不黑场；每次击中落在特写或大特写，切点压在接触帧上")
    elif total > 1:
        structure.append("镜头之间按标注的衔接方式在片内平滑过渡，不硬切、不黑场、不跳帧")
    if parts > 1:
        structure.append(_part_line(part, parts, previous_end))
    if last_frame:
        # 尾帧是最后一个镜头的落幅：首尾帧之间的路由那一镜的运镜和动作走完(《首尾帧衔接》)。
        last = beats[-1]
        landing = str(last.sections.get("end_state") or "").replace("落幅：", "", 1)
        structure.append(f"以所给尾帧结束：它是镜头{total}的落幅，" + bridge_line(last.motion, landing).split("：", 1)[1])
    anchors_input = ShotPromptInput(
        shot_index=0, duration_seconds=MIN_SHOT_SECONDS, shot_size="", camera_movement="", subject_action="",
        scene="", blocking="", start_state="", end_state="", cast_refs=list(cast), scene_refs=list(scenes), prop_refs=list(props),
        costume_refs=list(costumes),
    )
    # 外貌简述按人去重：几个瞬间里同一个人只写一次。
    appearance = "".join(dict.fromkeys(
        f"{line}。" for beat in beats for line in str(beat.sections.get("appearance") or "").replace("人物外貌：", "", 1).split("。") if line.strip()
    ))
    sections: dict[str, str] = {
        "stage": mark_mentions(_stage_section(beats, str(first.get("locks") or "")), [*cast, *scenes, *props]),
        **_asset_anchor_sections(anchors_input),
        "anchors": ("【参考素材职责】\n" + reference_notes.strip().rstrip("。") + "。") if reference_notes.strip() else "",
        "structure": "【结构声明】" + " + ".join(structure) + "。",
        "locks": str(first.get("locks") or ""),
        "subject": "\n".join(dedupe_blocks([
            _block(number, total, beat, include_motion=include_motion, drop_phrases=drop_phrases, fight=fight)
            for number, beat in enumerate(beats, start=1)
        ])),
        "style_lock": str(first.get("style_lock") or ""),
        "appearance": f"人物外貌：{appearance}" if appearance else "",
        "quality": str(first.get("quality") or ""),
        "sound_layers": str(first.get("sound_layers") or ""),
        "sound": str(first.get("sound") or ""),
        "closing": str(first.get("closing") or ""),
        "rules": repeated_clauses_out("【关键约束】\n" + "\n".join(
            line for line in _lines([beat.sections.get("rules") or "" for beat in beats]) if line != "【关键约束】"
        )),
        "negatives": " + ".join(dict.fromkeys(
            part.strip() for beat in beats for part in str(beat.sections.get("negatives") or "").split(" + ") if part.strip()
        )),
    }
    return render({key: value for key, value in sections.items() if value}, model=model, beats=total, style_pack=style_pack)


def _stage_section(beats: Sequence[Beat], locks: str) -> str:
    """每个瞬间在导演台上的样子：片段的锁只有第一个瞬间的，后面的瞬间全靠这里。重复的一行只写一次，手改过的瞬间不加。"""
    seen: set[str] = set()
    written = [clip_brief.title()]
    for number, beat in enumerate(beats, start=1):
        if beat.override.strip():
            continue
        lines = clip_brief.new_clauses(clip_brief.not_restated(list(beat.stage), locks if number == 1 else ""), seen)
        if lines:
            written.append(f"镜头{number}：" + "\n".join(lines) if len(beats) > 1 else "\n".join(lines))
    return "\n".join(written) if len(written) > 1 else ""


def _part_line(part: int, parts: int, previous_end: str) -> str:
    line = f"本段是该场戏的第{part}/{parts}段"
    if part <= 1:
        return line
    # 接住上一段的结尾再往下演：把结束状态写出来，模型才有东西接，「接着往下演」四个字接不上。
    ending = action_grammar.concrete_ending(previous_end)
    return line + (f"，上一段结尾：{ending.rstrip('。')}；本段从这个状态接住再往下演，不重新起势" if ending else "，从上一段的落幅接着往下演，不重新起势")


def continue_single(compiled: CompiledVideoPrompt, *, model: str, part: int, parts: int, previous_end: str = "") -> CompiledVideoPrompt:
    """只有一个瞬间的后半段：单镜提示词已经写好、裁好，只在结构声明里补上它接的是哪一段。"""
    sections = dict(compiled.sections)
    head = str(sections.get("structure") or "【结构声明】").rstrip("。")
    joiner = "" if head.endswith("】") else " + "
    sections["structure"] = f"{head}{joiner}{_part_line(part, parts, previous_end)}。"
    rendered = render(sections, model=model, beats=1, style_pack=compiled.style_pack)
    rendered.pressure.distilled = compiled.pressure.distilled
    return replace(compiled, text=rendered.text, sections=rendered.sections, pressure=rendered.pressure)


def render(sections: Mapping[str, str], *, model: str, beats: int, style_pack: str = "", distilled: bool = False) -> CompiledVideoPrompt:
    """片段的分节拼成提示词并算压力：片段的预算是单镜预算 × 瞬间数。"""
    kept = {key: str(value) for key, value in sections.items() if str(value or "")}
    text = _render(kept)
    budget = prompt_budget.prompt_budget(model)
    body = sum(prompt_budget.prompt_length(value) for key, value in kept.items() if key not in prompt_budget.FIXED_SECTIONS)
    scaled = budget * beats if budget else None
    report = prompt_budget.PressureReport(
        model=model, budget=scaled, length=body, tier=prompt_budget.tier_for(body, scaled),
        total_length=prompt_budget.prompt_length(text), distilled=distilled,
    )
    return CompiledVideoPrompt(text=text, sections=kept, pressure=report, style_pack=style_pack)


__all__ = [
    "BEAT_HEAD", "Beat", "DEFAULT_JOIN", "FIGHT_JOIN", "Slice", "beat_count", "beat_seconds", "compile_prompt", "continue_single", "covered_uids", "render",
    "enabled", "fingerprint", "plan", "planned_seconds",
]
