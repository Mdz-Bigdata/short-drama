"""分镜表定稿前的一次修订。

分镜表作者(文本模型)交来的表有两种过不了：被校验退回(占位内容、入镜角色列和画面对不上、
点到了没出场的人)，或衔接自检没过(相邻两镜光色相反、景别跳级、运镜对冲，单镜推了又拉或叠了三种运镜)。以前两种都要等
整集跑完再手动重跑那一场；现在把原因原样交回作者，改一版再定稿。修订只多花一次文本调用，
发生在任何生图之前，不花生图的钱。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from app.core import camera_motion, prompt_data, shot_transitions


_WORDING_FILE = "storyboard_revision"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/storyboard_revision.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

# 版数、退回代码、持物词表、打戏词表都是数据(app/data/prompt/storyboard_revision.json)。
_DATA = "storyboard_revision"
# 最多交两版：初稿 + 一版修订。再多也不会更好，只会更贵。
MAX_DRAFTS = prompt_data.number(_DATA, "max_drafts")
PREVIOUS_TABLE_LIMIT = prompt_data.number(_DATA, "previous_table_limit")
# 让作者改的衔接问题：都是《首尾帧衔接》《镜头组禁忌》里明文禁止、又能在表上直接改掉的。
REVISE_CODES = prompt_data.words(_DATA, "revise_codes")


_CLAUSE = re.compile(r"[^，,。；;！!？?\n]+")
_HOLDING = prompt_data.pattern(_DATA, "holding")
_TAKES = prompt_data.pattern(_DATA, "takes")
_HAND = prompt_data.pattern(_DATA, "hand")
_HAND_CHANGE = prompt_data.pattern(_DATA, "hand_change")

# 打戏里含混的技法词(《视频创作工艺手册》3.3)：模型分不清左右肢，也没有接触点，画出来就是糊的一团。
# 每个词配一句改法，退回去时一起给作者。「一拳」「一脚」单独出现常是量词(离地约一拳)，只查整句的写法。
VAGUE_FIGHT_MOVES: tuple[tuple[str, str], ...] = prompt_data.pairs(_DATA, "vague_fight_moves")


def vague_fight_issues(shots: Sequence[Mapping[str, Any]]) -> list[str]:
    """打戏分镜表里的含混技法词，每镜一句，附改法。"""
    issues = []
    for index, shot in enumerate(shots, start=1):
        desc = str(shot.get("desc") or "")
        hits = [(word, fix) for word, fix in VAGUE_FIGHT_MOVES if word in desc]
        if hits:
            issues.append(
                _text_of("vague_fight_issues.text").format(index, '」「'.join(word for word, _ in hits), hits[0][1])
            )
    return issues


# 拳拳到肉：出了手就要写打在哪、受击方怎么反应。只认明确的出手词，起势、对峙、拔刀不算出手。
_STRIKES = prompt_data.words(_DATA, "strikes")
_CONTACTS = prompt_data.words(_DATA, "contacts")
_REACTIONS = prompt_data.words(_DATA, "reactions")


def contact_issues(shots: Sequence[Mapping[str, Any]], *, exclude: Sequence[int] = ()) -> list[str]:
    """打戏分镜出了手却没写打在哪、或受击方没有反应：每镜一句。``exclude`` 里的镜已因含混技法退回，不再重复说。"""
    issues = []
    for index, shot in enumerate(shots, start=1):
        if index in exclude:
            continue
        desc = str(shot.get("desc") or "")
        strikes = [word for word in _STRIKES if word in desc]
        if not strikes:
            continue
        if not any(word in desc for word in _CONTACTS):
            issues.append(
                _text_of("contact_issues.text").format(index, strikes[0])
            )
        elif not any(word in desc for word in _REACTIONS):
            issues.append(
                _text_of("contact_issues.text.2").format(index)
            )
    return issues


def handoff_issues(
    shots: Sequence[Mapping[str, Any]], *, scene_id: str, fight: bool = False, props: Sequence[str] = (),
) -> list[str]:
    """定稿前对表：只看表本身就能判定的衔接与运镜问题，每条一句，没有就是空。``fight`` 的场次再查含混技法词。
    """
    staged = [{**shot, "scene_id": scene_id, "shot_id": index} for index, shot in enumerate(shots, start=1)]
    try:
        plan = shot_transitions.plan_transitions(staged)
    except Exception:  # noqa: BLE001 - 对表是加分项，算不出来不能成为这场分镜失败的原因
        transitions = []
    else:
        transitions = [check.detail for check in plan.checks if not check.passed and check.code in REVISE_CODES]
    fight_notes: list[str] = []
    if fight:
        vague = vague_fight_issues(shots)
        flagged = [int(re.match(_text_of("handoff_issues.flagged"), note).group(1)) for note in vague]
        fight_notes = vague + contact_issues(shots, exclude=flagged)
    return transitions + motion_issues(shots) + prop_issues(shots, props) + fight_notes


def prop_issues(shots: Sequence[Mapping[str, Any]], props: Sequence[str]) -> list[str]:
    """手持连续性：道具没拿起来就已经在手上，或者没换手就换了一只手。在生成之前拦下来，比拍完重拍便宜。"""
    issues = []
    for prop in dict.fromkeys(str(name).strip() for name in props if str(name).strip()):
        seen = False
        last_hold: tuple[str, str] | None = None        # (谁, 哪只手)
        for index, shot in enumerate(shots, start=1):
            desc = str(shot.get("desc") or "")
            clauses = [clause for clause in _CLAUSE.findall(desc) if prop in clause]
            if not clauses:
                continue
            taken = any(_TAKES.search(clause) for clause in clauses)
            if not seen and index > 1 and not taken and any(_HOLDING.search(clause) for clause in clauses):
                issues.append(_text_of("prop_issues.text").format(index, prop))
            seen = True
            cast = [str(name) for name in shot.get("characters") or []]
            for clause in clauses:
                hand = _HAND.search(clause)
                holder = next((name for name in cast if name in clause), cast[0] if len(cast) == 1 else "")
                if not hand or not holder:
                    continue
                if last_hold and last_hold[0] == holder and last_hold[1] != hand.group(0) and not taken and not _HAND_CHANGE.search(desc):
                    issues.append(_text_of("prop_issues.text.2").format(index, holder, prop, last_hold[1], hand.group(0)))
                last_hold = (holder, hand.group(0))
    return issues


def motion_issues(shots: Sequence[Mapping[str, Any]]) -> list[str]:
    """单镜运镜违反一镜一主运镜的地方(推了又拉、三种以上叠在一起)，每镜一句。"""
    issues = []
    for index, shot in enumerate(shots, start=1):
        problem = camera_motion.motion_problem(shot.get("motion"))
        if problem:
            issues.append(_text_of("motion_issues.text").format(index, str(shot.get('motion') or '')[:40], problem))
    return issues


def previous_table(reply: str) -> str:
    """上一版回答里的表格行：修订要在它上面改，不从头再想一遍。太长就不带，免得截成半张表。"""
    table = "\n".join(line for line in str(reply or "").splitlines() if line.lstrip().startswith("|"))
    if not table or len(table) > PREVIOUS_TABLE_LIMIT:
        return ""
    return _text_of("previous_table.text").format(table)


def rejection_note(reason: str, reply: str = "") -> str:
    return (
        previous_table(reply)
        + _text_of("rejection_note.text") + reason.strip()
        + _text_of("rejection_note.text.2")
    )


def revision_note(issues: Sequence[str], reply: str = "") -> str:
    return (
        previous_table(reply)
        + _text_of("revision_note.text")
        + "\n".join(f"- {issue}" for issue in issues)
        + _text_of("revision_note.text.2")
    )
