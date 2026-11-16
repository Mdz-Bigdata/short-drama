# -*- coding: utf-8 -*-
"""Enforce the shot-design skill's hard rules on a parsed shot table.

The skill (``backend/skills/shot-design-master``) states the rules in the stage
prompt, but a prompt is a request, not a guarantee: models routinely answer with
a 110s "shot", an abstract emotion word, or five identical medium shots in a row.
This module turns the rules that are mechanically checkable into an audit, and
repairs the one that is mechanically repairable - a clip longer than the selected
video model can render in a single generation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.core import exchange_units, fight_design, fight_exchange, light_setups, prompt_data, visual_wording
from app.core.frame_handoff import light_phrase
from app.core.camera_motion import normalize_camera_motion
from app.core.camera_recipes import repeated_move_signature
from app.core.frame_position import flipped_subjects, parse_frame_positions, uses_frame_grammar
from app.core.emotion_table import read_emotion
from app.core.screenwriting.speech_rate import line_seconds
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds, split_shot_seconds
from app.core.writer_dashboard import parse_duration_seconds


logger = logging.getLogger("app.core.shot_table_rules")

# The word tables, limits, patterns, issue names and sentences of the audit:
# app/data/prompt/shot_table_rules.json.
_WORDING = "shot_table_rules"


def _body(template: object) -> str:
    """A template written as one string or as an array of lines."""
    return "".join(str(line) for line in template) if isinstance(template, list) else str(template)


def _says(key: str, /, **values: object) -> str:
    """A sentence of the table's ``says``, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return _body(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _pattern(key: str) -> re.Pattern[str]:
    return re.compile(str(prompt_data.load(_WORDING)["patterns"][key]))


# 景别取词表，与 skills/shot-design-master/references/shot-grammar.md 的主表对应。
SHOT_SIZE_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "shot_size_terms")

# 情绪必须写成可观察的身体细节；这些词单独出现说明只写了结论没写画面。
ABSTRACT_EMOTION_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "abstract_emotion_terms")
# 只要同句出现具象身体线索，就认为情绪已经落地。
PHYSICAL_CUE_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "physical_cue_terms")
# 心理描写红线：摄影机拍不到的内容。
INNER_MONOLOGUE_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "inner_monologue_terms")

MIN_DESC_CHARS = prompt_data.number(_WORDING, "min_desc_chars")
MAX_SAME_SIZE_RUN = prompt_data.number(_WORDING, "max_same_size_run")
# 张力法则：镜头默认静止，运动只留给开头、呼吸和爆发；一场里带运动的镜头超过这个比例
# 就成了"监控回放"。
MAX_MOVING_SHOT_RATIO = float(prompt_data.value(_WORDING, "max_moving_shot_ratio"))
# 爆发前要有静置蓄力：前一镜至少停这么久、且镜头不动。
MIN_BUILDUP_SECONDS = prompt_data.number(_WORDING, "min_buildup_seconds")
BURST_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "burst_terms")
# 爆发镜越短越有冲击力：6 秒的爆发像放烟花，不像打人。
MAX_BURST_SECONDS = prompt_data.number(_WORDING, "max_burst_seconds")
# 分镜表里台词写成「角色名：台词」；说话人名很短，正文里的冒号句（他说：…）不会被当成第二个说话人。
_SPEAKER_LINE = _pattern("speaker_line")
# 特写是标点不是正文：一场戏里给得太多，冲击力就贬值了。
MAX_CLOSE_UPS_PER_SCENE = prompt_data.number(_WORDING, "max_close_ups_per_scene")
MAX_CLOSE_UPS_PER_FIGHT_SCENE = prompt_data.number(_WORDING, "max_close_ups_per_fight_scene")
CLOSE_UP_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "close_up_terms")
# 视频模型没有逐帧控制力：写「定格」只会让画面真的停住。冲击靠白闪、震镜、径向模糊做。
FROZEN_FRAME_TERMS: tuple[str, ...] = prompt_data.words(_WORDING, "frozen_frame_terms")
# 声音一层是底噪、一层是动作；层数堆多了混成一团。
MAX_AMBIENT_LAYERS = prompt_data.number(_WORDING, "max_ambient_layers")
MAX_ACTION_SOUNDS = prompt_data.number(_WORDING, "max_action_sounds")
_SOUND_SPLIT = _pattern("sound_split")
# 声音栏的分段、人物栏的拆分、比对点题金句时去掉的空白与标点。
_SOUND_CELLS = _pattern("sound_cells")
_CHARACTER_SPLIT = _pattern("character_split")
_LINE_NOISE = _pattern("line_noise")
# 人物栏里表示没人、声音栏里表示没声音的写法。
_NO_CHARACTER = frozenset(prompt_data.words(_WORDING, "no_character"))
_SILENT_SOUND = frozenset(prompt_data.words(_WORDING, "silent_sound"))


@dataclass
class ShotIssue:
    shot_id: Any
    rule: str
    detail: str
    severity: str = "warning"


def _issue(shot_id: Any, key: str, /, *, severity: str = "warning", **values: object) -> ShotIssue:
    """The table's ``issues[key]``: its rule name, and its detail filled in (``key`` is positional)."""
    spec = prompt_data.load(_WORDING)["issues"][key]
    return ShotIssue(shot_id, str(spec["rule"]), _body(spec["detail"]).format(**values), severity)


@dataclass
class ShotTableAudit:
    shots: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ShotIssue] = field(default_factory=list)
    repaired: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.ok:
            return _says("passed")
        by_rule: dict[str, int] = {}
        for issue in self.issues:
            by_rule[issue.rule] = by_rule.get(issue.rule, 0) + 1
        parts = prompt_data.text(_WORDING, "part_separator").join(
            _says("part", rule=rule, count=count) for rule, count in sorted(by_rule.items())
        )
        repaired = _says("repaired", repaired=self.repaired) if self.repaired else ""
        return _says("found", count=len(self.issues), parts=parts, repaired=repaired)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def speakers_in(dialogue: str, cast: Sequence[str] = ()) -> list[str]:
    """Who the dialogue cell gives lines to, in order.

    With a cast, only labels naming someone in it count, so a colon inside a line
    (「他说：走」) is not mistaken for a second speaker.
    """
    names = [name.strip() for name in _SPEAKER_LINE.findall(dialogue) if name.strip()]
    known = {str(name).strip() for name in cast if str(name).strip()}
    return [name for name in names if name in known] if known else names


def _spoken_text(dialogue: str) -> str:
    """The dialogue without the speaker labels, which are not spoken aloud."""
    return _SPEAKER_LINE.sub(" ", dialogue)


_PARENTHETICAL = _pattern("parenthetical")


def dialogue_seconds(dialogue: str, *notes: str, key_line: str = "") -> float:
    """这一镜的台词在画面里要占多久：逐句按情绪语速算(悲伤慢、暴怒快)，加句首句尾留白。

    台词栏按说话人拆成一句句(说话人、语气说明、舞台说明、花括号都不算字数)。每句的情绪先看它的
    语气说明(「（哽咽）」)，再看镜头写的表情；都没有按日常语速。本场的点题金句(``key_line``)一律降速。
    """
    from app.core.spoken_lines import labelled_lines, spoken_lines

    anchor = _LINE_NOISE.sub("", key_line or "")
    text = str(dialogue or "")
    utterances = [(note, line) for _name, note, line in labelled_lines(text)] or [
        (" ".join(_PARENTHETICAL.findall(text)), line) for line in spoken_lines([text])
    ]
    total = 0.0
    for note, spoken in utterances:
        if not spoken.strip():
            continue
        reading = read_emotion(note, *notes)
        is_key = len(anchor) >= 4 and anchor in _LINE_NOISE.sub("", spoken)
        total += line_seconds(spoken, reading.voice if reading.matched else None, key_line=is_key)
    return total


def _sound_layers(sound: str) -> tuple[int, int]:
    """``(ambience layers, action sounds)`` of one shot's sound cell."""
    ambience, action = "", ""
    separators = prompt_data.words(_WORDING, "sound_label_separators")
    ambience_labels = prompt_data.words(_WORDING, "ambience_labels")
    action_labels = prompt_data.words(_WORDING, "action_labels")
    effect_labels = prompt_data.words(_WORDING, "effect_labels")
    for part in _SOUND_CELLS.split(sound):
        # 「标签：内容」按分隔符的顺序找；都找不到时整段是标签、内容为空。
        for separator in separators:
            label, _, body = part.partition(separator)
            if body:
                break
        if _has_any(label, ambience_labels):
            ambience = body
        elif _has_any(label, action_labels) or _has_any(label, effect_labels) and not ambience:
            action = body
    if not ambience and not action:
        ambience = sound
    def _count(text: str) -> int:
        return len([item for item in _SOUND_SPLIT.split(text) if item.strip() and item.strip() not in _SILENT_SOUND])
    return _count(ambience), _count(action)


def audit_shot_table(
    shots: Sequence[dict[str, Any]],
    *,
    video_model: str = "",
    repair: bool = True,
    scene_kind: str = "",
    exchange: exchange_units.ScenePlan | None = None, whole_episode: bool = True,
    key_line: str = "",
) -> ShotTableAudit:
    """Check a parsed shot table against the skill's mechanically checkable rules.

    With ``repair`` the returned shots have over-long durations cut down to the
    model's single-clip ceiling; every other rule is reported, never silently
    rewritten, because only a human can decide how to re-stage a shot.

    ``scene_kind`` tightens the rules a fight scene is judged by (close-up quota).
    ``exchange`` is the scene's unit-chain plan (``exchange_units.scene_plan``) the table writer
    was briefed with; without one the table's own text is judged.
    """
    cap = max_shot_seconds(video_model)
    fight = "fight" in str(scene_kind or "").lower()
    if exchange is None:
        table_text = "\n".join(
            f"{_text(shot.get('desc'))}\n{_text(shot.get('dialogue'))}" for shot in shots if isinstance(shot, dict)
        )
        exchange = exchange_units.scene_plan(table_text, fight=fight, has_dialogue=True)
    close_ups = 0
    audit = ShotTableAudit()
    previous_size = ""
    same_size_run = 0
    previous_positions = []
    previous_static = True
    previous_seconds = 0
    previous_shot: dict[str, Any] | None = None
    moving_shots = 0
    motion_declared = 0
    fight_shots: list[tuple[Any, str]] = []

    for index, raw in enumerate(shots):
        if not isinstance(raw, dict):
            continue
        shot = dict(raw)
        shot_id = shot.get("shot_id", index + 1)
        desc = _text(shot.get("desc"))
        size = _text(shot.get("size"))

        seconds = parse_duration_seconds(shot.get("duration"))
        if seconds > cap:
            audit.issues.append(_issue(
                shot_id, "too_long", severity="error",
                seconds=seconds, model=video_model or prompt_data.text(_WORDING, "unnamed_model"), cap=cap,
            ))
            if repair:
                slices = split_shot_seconds(seconds, video_model)
                shot["duration"] = f"{slices[0]}s" if slices else f"{cap}s"
                audit.repaired += 1
        elif seconds and seconds < MIN_SHOT_SECONDS:
            audit.issues.append(_issue(shot_id, "too_short", seconds=seconds, floor=MIN_SHOT_SECONDS))

        if size and not _has_any(size.upper(), (term.upper() for term in SHOT_SIZE_TERMS)):
            audit.issues.append(_issue(shot_id, "unknown_size", size=size))

        if size and size == previous_size:
            same_size_run += 1
            if same_size_run >= MAX_SAME_SIZE_RUN:
                audit.issues.append(_issue(shot_id, "same_size_run", count=same_size_run + 1, size=size))
        else:
            same_size_run = 0
        previous_size = size

        if desc and len(desc) < MIN_DESC_CHARS:
            audit.issues.append(_issue(shot_id, "short_desc", chars=len(desc), minimum=MIN_DESC_CHARS))

        if _has_any(desc, INNER_MONOLOGUE_TERMS):
            hit = next(term for term in INNER_MONOLOGUE_TERMS if term in desc)
            audit.issues.append(_issue(shot_id, "inner_monologue", severity="error", hit=hit))

        if _has_any(desc, ABSTRACT_EMOTION_TERMS) and not _has_any(desc, PHYSICAL_CUE_TERMS):
            hit = next(term for term in ABSTRACT_EMOTION_TERMS if term in desc)
            audit.issues.append(_issue(shot_id, "abstract_emotion", hit=hit))

        # 画面写法(visual_wording.json)：不写主观评价词；非打斗的动作与运镜慢而稳。只是提示(warning)。
        # 打斗场的镜头、或画面本身读得出是打斗的镜头，按打戏规则走，不发快动作提示。
        moving = _text(shot.get("motion"))
        fight_like = fight or fight_design.looks_like_fight(f"{desc}\n{moving}")
        for finding in visual_wording.findings(desc, moving, fight=fight_like):
            audit.issues.append(ShotIssue(shot_id, finding.rule, finding.message))
        # 一镜的光影句子里叠了两套互相抵消的光(light_setups.json)：同样只是提示。只看写光的那几句，道具里的烛台不算。
        for hint in light_setups.clashes(light_phrase(desc)):
            audit.issues.append(ShotIssue(shot_id, light_setups.CLASH, hint))

        # 站位与视线写成观众看到的画面坐标，而不是人物自己的左右。
        characters = [
            name.strip() for name in (
                shot.get("characters") if isinstance(shot.get("characters"), list)
                else _CHARACTER_SPLIT.split(_text(shot.get("characters")))
            ) if str(name).strip() and str(name).strip() not in _NO_CHARACTER
        ]
        positions = parse_frame_positions(desc, characters) if characters and desc else []
        if characters and desc and not uses_frame_grammar(desc):
            audit.issues.append(_issue(shot_id, "no_frame_grammar"))
        flipped = flipped_subjects(previous_positions, positions)
        if flipped and not _has_any(desc, prompt_data.words(_WORDING, "turn_words")):
            audit.issues.append(_issue(
                shot_id, "eyeline_flip", names=prompt_data.text(_WORDING, "name_separator").join(flipped),
            ))
        if positions:
            previous_positions = positions

        # 一句台词必须在本镜说完：按项目统一语速换算，两端各留一点静默。
        dialogue = _text(shot.get("dialogue"))
        # 单元环扣：两人对话一格至少一个来回、格尾不空叹、一轮不超字数；打斗格按流派 × 力量档数 U。
        fight_shot = fight and (fight_design.fight_score(desc) > 0 or exchange_units.count_units(desc) > 0)
        for unit_issue in exchange_units.audit_shot(
            exchange, seconds=seconds, characters=characters, dialogue=dialogue, desc=desc, fight_shot=fight_shot,
        ):
            audit.issues.append(ShotIssue(shot_id, unit_issue.rule, unit_issue.detail))
        if fight_shot:
            # 招招写实：每个 U 写清谁、从哪发力、怎么走、打在谁身上哪里、结果与力；多人不站着、不排队。
            for exchange_issue in fight_exchange.audit_shot(desc, characters):
                audit.issues.append(ShotIssue(shot_id, exchange_issue.rule, exchange_issue.detail))
            fight_shots.append((shot_id, desc))
        # 按情绪语速算(悲伤约 1.8 字/秒、暴怒约 4 字/秒)，句首句尾留白已经算在里面。
        spoken = dialogue_seconds(dialogue, _text(shot.get("expression")), _text(shot.get("emotion")), key_line=key_line)
        if spoken and seconds and spoken > seconds:
            audit.issues.append(_issue(shot_id, "dialogue_overrun", spoken=spoken, seconds=seconds))

        sound_text = _text(shot.get("sound"))
        if sound_text:
            ambience, action = _sound_layers(sound_text)
            if ambience > MAX_AMBIENT_LAYERS or action > MAX_ACTION_SOUNDS:
                audit.issues.append(_issue(
                    shot_id, "sound_layers", ambience=ambience, action=action,
                    max_ambience=MAX_AMBIENT_LAYERS, max_action=MAX_ACTION_SOUNDS,
                ))

        if size and _has_any(size.upper(), (term.upper() for term in CLOSE_UP_TERMS)):
            close_ups += 1

        if _has_any(desc, FROZEN_FRAME_TERMS):
            hit = next(term for term in FROZEN_FRAME_TERMS if term in desc)
            audit.issues.append(_issue(shot_id, "frozen_frame", hit=hit))

        if _has_any(desc, BURST_TERMS) and seconds > MAX_BURST_SECONDS:
            audit.issues.append(_issue(shot_id, "long_burst", seconds=seconds, maximum=MAX_BURST_SECONDS))

        motion_text = _text(shot.get("motion"))
        if motion_text:
            motion_declared += 1
            canonical, _ = normalize_camera_motion(motion_text)
            is_static = canonical == "Static"
            if not is_static:
                moving_shots += 1
        else:
            is_static = True
        if _has_any(desc, BURST_TERMS) and index > 0 and (
            not previous_static or (previous_seconds and previous_seconds < MIN_BUILDUP_SECONDS)
        ):
            audit.issues.append(_issue(shot_id, "no_buildup", minimum=MIN_BUILDUP_SECONDS))
        previous_static = is_static
        previous_seconds = seconds

        # 防撞镜：画风质感锁死，相邻镜至少换掉运动 / 角度 / 节奏之一。
        current = {**shot, "_seconds": seconds}
        if previous_shot is not None and motion_text:
            shared = repeated_move_signature(previous_shot, current)
            if shared:
                audit.issues.append(_issue(shot_id, "repeated_move", signature=shared))
        previous_shot = current

        audit.shots.append(shot)

    if motion_declared >= 4 and moving_shots / motion_declared > MAX_MOVING_SHOT_RATIO:
        audit.issues.append(_issue(
            audit.shots[-1].get("shot_id", len(audit.shots)), "too_much_motion",
            moving=moving_shots, declared=motion_declared, percent=int(MAX_MOVING_SHOT_RATIO * 100),
        ))

    # 打戏分回合：每个打戏格标回合，回合只进不退，最后写清胜负。
    if fight:
        for round_shot, round_issue in fight_exchange.audit_rounds(fight_shots):
            audit.issues.append(ShotIssue(round_shot, round_issue.rule, round_issue.detail))

    close_up_cap = MAX_CLOSE_UPS_PER_FIGHT_SCENE if fight else MAX_CLOSE_UPS_PER_SCENE
    if close_ups > close_up_cap and audit.shots:
        audit.issues.append(_issue(
            audit.shots[-1].get("shot_id", len(audit.shots)), "close_up_quota",
            count=close_ups, kind=prompt_data.text(_WORDING, "fight_quota") if fight else "", cap=close_up_cap,
        ))

    if whole_episode and len(audit.shots) == 1:
        audit.issues.append(_issue(audit.shots[0].get("shot_id", 1), "single_shot", severity="error"))

    return audit


def audit_and_log(
    shots: Sequence[dict[str, Any]], *, video_model: str, task_id: str = "", scene_kind: str = "",
    exchange: exchange_units.ScenePlan | None = None, whole_episode: bool = True, key_line: str = "",
) -> list[dict[str, Any]]:
    """Audit, log the findings, and return the (possibly repaired) shot list."""
    audit = audit_shot_table(
        shots, video_model=video_model, scene_kind=scene_kind, exchange=exchange, whole_episode=whole_episode, key_line=key_line,
    )
    if audit.issues:
        logger.warning("[Stage4] %s (task=%s)", audit.summary(), task_id or "-")
        for issue in audit.issues[:20]:
            logger.info(prompt_data.text(_WORDING, "log_issue"), issue.shot_id, issue.rule, issue.detail)
    return audit.shots
