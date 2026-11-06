# -*- coding: utf-8 -*-
"""A text model as the director of a stage: it plans first, the rules check what it planned.

Three things run on the same contract, a JSON reply carrying the stage's own semantic operations:

- ``plan_candidates`` asks for several complete stagings of a scene (set, marks, poses, lenses, moves),
  repairs and scores each and recommends one. The rule planner's stage is kept as the comparison and the fallback.
- ``run_turn`` is one message of a conversation: the model edits a working copy, reads back what its edit did to
  the checks and the frame, and goes again until it is satisfied or out of rounds. Nothing is saved here.
- ``read_model_reply`` reads one object written part by part, for the model library.

Nothing here calls a provider: ``llm(system, user, max_tokens)`` is handed in, so every path can be driven by a
stub, and an operation a model got wrong costs that operation with its error sent back rather than the whole turn.

The shape of the conversation, a transaction per turn with its result read back, an optional scope of selected
objects, is what mangfufu/director-desk's built-in assistant does (``desktop/ai-conversation.cjs``, MIT); its prompts
are not used. The text / image / pose / object generation split is described in GuiYi-Xi/monoform-previs-studio's
README; that repository has no licence, so none of its code or prompts were read. Set-dressing and lens rules are
taken from the MIT-licensed arjun988/blender-skills vendored under ``backend/skills/blender-skills``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.screenwriting.structured_llm import extract_json_object
from app.core import project_memory
from app.core.spatial_stage import model_kit, repair, scoring
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.operations import MAX_OPERATIONS, StageEditError, apply_operations

logger = logging.getLogger(__name__)

LLM = Callable[[str, str, int], "str | None"]

PLAN_MAX_TOKENS = 8000
TURN_MAX_TOKENS = 6000
MODEL_MAX_TOKENS = 4000
MAX_TURN_ROUNDS = 3
MAX_CANDIDATES = 3
MAX_MESSAGE = 2000
_DIGEST_LANDMARKS = 60
_DIGEST_SHOTS = 40
_FAILED_OP_COST = 3.0
_FAILED_OP_LIMIT = 15.0

# The ids the desk draws; ``lib/poses.ts`` holds their angles.
POSE_PRESETS: tuple[tuple[str, str], ...] = (
    ("stand", "站立"), ("t-pose", "T型"), ("walk", "行走"), ("run", "跑步"), ("sit", "坐姿"), ("crouch", "蹲下"),
    ("kneel-one", "单膝跪"), ("kneel-two", "双膝跪"), ("hands-on-hips", "叉腰"), ("lean", "倚靠"), ("bow", "鞠躬"),
    ("think", "思考"), ("fight", "格斗"), ("kick", "踢腿"), ("throw", "投掷"), ("push", "推"), ("wave", "招手"),
    ("reach", "伸手"), ("cross-arms", "抱臂"), ("phone", "看手机"), ("lie", "卧倒"), ("hands-behind", "背手站立"),
    ("look-back", "侧身回头"), ("point-ahead", "抬手指向"), ("punch", "出拳"),
)

STRATEGIES: tuple[tuple[str, str], ...] = (
    ("稳住关系", "把人物关系拍清楚：轴线明确，一个定场镜头交代全部人物，对话用过肩与正反打，机位都在轴线同侧。"),
    ("纵深调度", "利用场景纵深：前景、中景、后景分层站位，用布景做前景遮挡和框中框，人物不站成一排，镜头有高低和焦段的对比。"),
    ("动势走位", "让人动起来：关键情绪点安排走位和转身（set_path / auto_route），镜头跟着人物的动势运动（apply_camera_move），动作结束后人物的关系发生变化。"),
)

OP_GUIDE = """坐标与约定：单位米；地面点 [x, z]，y 为高度；yaw_deg 0 面向 +Z，90 面向 +X；物体的 size 是 [宽(X), 深(Z), 高(Y)]。「画面左右」取决于机位朝向，先看机位 position 与 target 再换算。

人物：move_actor {name, position:[x,z], yaw_deg?, posture?(stand/walk/run/fight/sit/crouch/kneel/lie/bow/lean)}；orient_toward {name, target:"人名"} 或 {name, position:[x,z]}；face_pair {first, second, distance?}；place_relative {name, anchor, relation:(front/behind/left/right/foreground/background), distance?, reference?:(actor/camera/world), camera_id?}；arrange_group {names:[...], layout:(line/arc/circle/grid), spacing?, center?:[x,z], facing?}；set_axis {from_name, to_name}；flip_camera_side {}；add_crowd {rows, columns, center:[x,z], spacing?, label?}；add_extra {name?, position:[x,z]}。
只改某一镜：set_shot_override {shot_id, name, position?, yaw_deg?, posture?, offstage?, hold?}。
姿势：set_pose {name, preset, shot_id?}（shot_id 省略则整场生效）；只有 figure 为 mannequin 才看得见四肢，摆姿势前先 set_figure {name, figure:"mannequin"}。preset 可选：""" + "、".join(f"{key}({label})" for key, label in POSE_PRESETS) + """。
布景与模型：add_landmark {name, kit:"模型库 id", position:[x,z], yaw_deg?, size?}；模型库没有的东西写 add_landmark {name, kind:(prop/furniture/architecture/light), position:[x,z], yaw_deg?, parts:[{shape:(box/cylinder/sphere/cone/wedge), center:[x,y,z], size:[宽,深,高], rotation?:[x,y,z 度], tone?:(dark/light)}]}（parts 的坐标以物体地面中心为原点，米）；单一体块写 add_landmark {name, shape, position, size}。move_landmark {name, position}；transform_landmark {name, position?, size?, yaw_deg?, kit?, parts?}；remove_landmark {name}；array_landmark {name, count, spacing?, layout?:(line/grid/ring)}；align_landmarks {names:[...], axis:(x/z)}。
机位：solve_camera {shot_id, size?, angle?, subjects?, over_shoulder?, motion?}（让求解器按要求架机，优先用它）；best_camera {shot_id?, alternates?:0-3}（在当前机位附近搜索更好的视角）；frame_shot {shot_id, size:大特写/特写/近景/中近景/中景/中全景/全景/远景/大远景}；move_camera {camera_id, position:[x,y,z], target:[x,y,z], lens_mm?}；add_camera {shot_id, label?, position, target, lens_mm?}（候选机位）；use_camera {shot_id, camera_id}。
运动：apply_camera_move {shot_id, preset:(push/pull/truck/rise/descend/arc/arc-push/crane-reveal/ground-rise/whip-pan/push-pause/dolly-zoom/roll-recover/reframe), amplitude?, side?}；auto_route {shot_id, name, to:[x,z], speed_mps?, clip?}（自动绕开布景和其他人走到终点，优先用它）；set_path {shot_id, target:"人名或 camera", points:[[x,z],...], speed_mps?, clip?}；set_timeline {shot_id, clips?:{人物名:[{id, clip, start, end}]}, follow?:[{id, actor, start, end}]}。
修正：repair_checks {}（自动修正未通过的空间检查）。"""

_RULES = """调度原则：
- 主次：主角站在画面和空间的重心，次要人物不抢位；三人以上不站成一排，用三角形和前后层次。
- 距离讲关系：亲密 0.5 米内，对话 0.9 到 1.5 米，对峙 1.5 到 3 米。人物之间留出走位空间，通道至少 0.8 米。
- 视线和轴线：同一组对手戏的机位留在轴线同一侧，除非有明确的越轴理由。
- 人物不能站进实体布景里，布景也不能挡在机位和主角之间（有意的前景除外，前景要矮或在画边）。舞台上的人物都站在地面，站不到平台或楼梯上，这类布景只用来做背景。
- 姿势服务于戏：情绪和动作决定姿势，站着说话不需要造型；需要肢体表达的才换 mannequin 并摆姿势。
- 不改写剧情：人物、场景和动作都来自剧本，不添加剧本没有的人物。"""


class DirectorAIError(ValueError):
    """The model gave nothing usable; the stage is untouched."""


@dataclass
class Applied:
    plan: StagePlan
    applied: list[Mapping[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Scope:
    """What a person selected: the turn may only touch these. Empty means the whole stage."""

    names: tuple[str, ...] = ()
    shot_id: int | None = None

    @property
    def limited(self) -> bool:
        return bool(self.names) or self.shot_id is not None

    def describe(self) -> str:
        if not self.limited:
            return ""
        words = []
        if self.names:
            words.append("对象：" + "、".join(self.names))
        if self.shot_id is not None:
            words.append(f"镜头：第 {self.shot_id} 镜")
        return "用户这次只选中了 " + "；".join(words) + "。只改这些，其他保持原样。"


_SKILL_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("set-dressing", ("Density Rules", "Cluster Method")),
    ("prop-artist", ("Design Principles",)),
    ("camera-cinematography", ("Lens Guide", "Composition Checklist")),
)
# Asked for by what the scene is, each under the same budget.
_SKILL_ROUTES: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = (
    (("车", "船", "马车", "摩托", "飞机"), "vehicle-artist", ("Design Principles", "Blockout Checklist")),
    (("街", "城", "村", "广场", "庭院", "府", "宫", "山", "林", "废墟"), "environment-artist", ("Core Principles", "Composition Guidelines")),
    (("恐怖", "惊悚", "诡", "鬼", "凶"), "horror-style", ("Design Philosophy", "Sparse Detail Rule")),
    (("悬疑", "侦探", "黑帮"), "noir-style", ("Tenets",)),
)
_SKILL_BUDGET = 2400


def _skills_dir() -> Path:
    from app import settings

    return Path(settings.skills_root()) / "blender-skills"


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def craft_notes(scene_text: str = "") -> str:
    """Craft rules for this kind of scene from the vendored skills; empty when they are not installed."""
    wanted = list(_SKILL_SECTIONS) + [
        (skill, headings) for words, skill, headings in _SKILL_ROUTES if any(word in scene_text for word in words)
    ]
    chunks: list[str] = []
    used = 0
    for skill, headings in wanted:
        try:
            text = (_skills_dir() / skill / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        for heading in headings:
            body = _section(text, heading)
            if body and used + len(body) <= _SKILL_BUDGET:
                chunks.append(f"[{skill} · {heading}]\n{body}")
                used += len(body)
    return "\n\n".join(chunks)


def digest(plan: StagePlan) -> str:
    """The stage as a model should read it: positions, lenses and what each lens actually sees."""
    actors = [
        {
            "name": actor.name, "position": actor.position, "yaw": actor.yaw_deg, "posture": actor.posture, "role": actor.role,
            "height": actor.height_m, "figure": actor.figure, **({"pose": actor.pose.preset} if actor.pose and actor.pose.preset else {}),
        }
        for actor in plan.actors if not actor.crowd_id
    ]
    pieces = [
        {
            "name": piece.name, "kind": piece.kind, "position": piece.position, "size": piece.size, "yaw": piece.yaw_deg,
            **({"kit": piece.kit} if piece.kit else {}), **({"elevation": piece.elevation_m} if piece.elevation_m else {}),
        }
        for piece in plan.landmarks[:_DIGEST_LANDMARKS]
    ]
    cameras = {camera.id: camera for camera in plan.cameras}
    shots = []
    for shot in plan.shots[:_DIGEST_SHOTS]:
        camera = cameras.get(shot.camera_id)
        seen = [
            {"name": state.name, "x": round(state.x, 2), "h": round(state.height_fraction, 2), **({"hidden_by": state.occluded_by} if state.occluded_by else {})}
            if state.visible else {"name": state.name, "out_of_frame": True}
            for state in shot.screen if camera and state.name in camera.subjects
        ]
        shots.append({
            "shot_id": shot.shot_id, "action": shot.action[:100], "speaker": shot.speaker, "subjects": shot.subjects,
            **({"camera": {
                "id": camera.id, "position": camera.position, "target": camera.target, "lens_mm": camera.lens_mm,
                "size": camera.shot_size, "angle": camera.angle, "function": camera.function, "move": camera.move.kind,
            }} if camera else {}),
            "sees": seen,
            **({"overrides": [item.name for item in shot.overrides]} if shot.overrides else {}),
        })
    state = {
        "location": plan.location, "aspect": plan.aspect_ratio, "actors": actors,
        **({"crowds": [{"id": crowd.id, "label": crowd.label, "rows": crowd.rows, "columns": crowd.columns, "center": crowd.center} for crowd in plan.crowds]} if plan.crowds else {}),
        "set": pieces,
        **({"set_more": len(plan.landmarks) - _DIGEST_LANDMARKS} if len(plan.landmarks) > _DIGEST_LANDMARKS else {}),
        "axis": {"kind": plan.axis.kind, "from": plan.axis.from_name, "to": plan.axis.to_name, "side": plan.axis.camera_side},
        "shots": shots,
    }
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def _report(plan: StagePlan) -> str:
    """What the checks and the score say about a stage right now."""
    measured = scoring.score_plan(plan)
    failing = [f"{check.code}（{check.severity}）：{check.detail[:200]}" for check in plan.checks if not check.passed]
    lines = [f"当前评分 {measured['score']}/100。"]
    lines += [f"未通过：{item}" for item in failing]
    lines += [f"问题：{item}" for item in measured["notes"]]
    return "\n".join(lines)


def _salvage_operations(text: str) -> dict[str, Any] | None:
    """A reply cut off inside its list keeps every operation it finished."""
    opening = text.find('"operations"')
    bracket = text.find("[", opening) if opening >= 0 else -1
    if bracket < 0:
        return None
    decoder = json.JSONDecoder()
    index, operations = bracket + 1, []
    while True:
        while index < len(text) and text[index] in " \r\n\t,":
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        operations.append(value)
    return {"operations": operations, "done": False} if operations else None


def read_reply(text: Any) -> dict[str, Any] | None:
    """The JSON object of a reply, or what can be saved of one; a sentence with no JSON comes back as a reply."""
    body = str(text or "").strip()
    if not body:
        return None
    parsed = extract_json_object(body) or _salvage_operations(body)
    if parsed is None:
        return {"reply": body[:2000], "operations": [], "done": True, "remember": [], "title": "", "rationale": ""}
    operations = parsed.get("operations")
    return {
        "reply": str(parsed.get("reply") or parsed.get("rationale") or "")[:2000],
        "title": str(parsed.get("title") or "")[:60],
        "rationale": str(parsed.get("rationale") or parsed.get("reply") or "")[:600],
        "operations": [item for item in operations if isinstance(item, Mapping)][:MAX_OPERATIONS] if isinstance(operations, list) else [],
        "done": parsed.get("done") is not False,
        "remember": parsed.get("remember") if isinstance(parsed.get("remember"), list) else [],
    }


_OP_NAME_KEYS = ("name", "first", "second", "anchor", "target")
_ALWAYS_ALLOWED = frozenset({"repair_checks"})


def out_of_scope(op: Mapping[str, Any], scope: Scope, plan: StagePlan) -> str:
    """Why this operation reaches past what a person selected; empty when it does not."""
    if not scope.limited or str(op.get("op")) in _ALWAYS_ALLOWED:
        return ""
    if scope.shot_id is not None:
        if op.get("shot_id") is not None and int(op["shot_id"]) != scope.shot_id:
            return f"只能改第 {scope.shot_id} 镜"
        camera_id = op.get("camera_id")
        shot = next((item for item in plan.shots if item.shot_id == scope.shot_id), None)
        if camera_id and shot is not None and camera_id != shot.camera_id and camera_id not in shot.alt_camera_ids:
            return f"只能改第 {scope.shot_id} 镜用的机位"
    if scope.names:
        kind = str(op.get("op"))
        if kind in ("orient_toward", "set_path", "auto_route"):
            touched = [op.get("name") or op.get("target")]
        elif kind in ("face_pair",):
            touched = [op.get("first"), op.get("second")]
        elif kind == "arrange_group":
            touched = list(op.get("names") or [])
        else:
            touched = [op.get("name")] if op.get("name") else []
        strays = [str(name) for name in touched if name and name not in scope.names and name != "camera"]
        if strays:
            return f"{'、'.join(strays)} 不在选中范围内"
    return ""


def apply_each(plan: StagePlan, operations: Sequence[Mapping[str, Any]], scope: Scope = Scope()) -> Applied:
    """Apply one by one, so a wrong operation costs itself and its error can go back to the model."""
    outcome = Applied(plan=plan)
    for index, op in enumerate(operations, start=1):
        reason = out_of_scope(op, scope, plan)
        if reason:
            outcome.errors.append(f"第 {index} 个操作 {op.get('op')}：{reason}")
            continue
        try:
            outcome.plan = apply_operations(outcome.plan, [op])
        except StageEditError as error:
            outcome.errors.append(f"第 {index} 个操作 {op.get('op')}：{str(error)[:240]}")
            continue
        except Exception as error:  # noqa: BLE001 - a model's op must not be able to fail the turn
            logger.warning("[DirectorAI] 操作 %s 意外失败: %s", op.get("op"), error)
            outcome.errors.append(f"第 {index} 个操作 {op.get('op')}：参数不合法")
            continue
        outcome.applied.append(op)
    return outcome


def _mannequins_for_poses(plan: StagePlan) -> StagePlan:
    """A pose on a stand-in draws nothing; whoever a model posed gets a figure that shows it."""
    shot_poses = {item.name for shot in plan.shots for item in shot.overrides if item.pose}
    posed = [
        {"op": "set_figure", "name": actor.name, "figure": "mannequin"}
        for actor in plan.actors
        if actor.figure == "standin" and not actor.crowd_id and (actor.pose or actor.name in shot_poses)
    ]
    return apply_operations(plan, posed) if posed else plan


def polish(plan: StagePlan) -> StagePlan:
    """What needs no model: fix what the rules can fix, then look for better lenses. Never returns something worse."""
    current = plan
    for step in ({"op": "repair_checks"}, {"op": "best_camera"}):
        try:
            trial = apply_operations(current, [step])
        except (StageEditError, ValueError):
            continue
        if scoring.score_plan(trial)["score"] >= scoring.score_plan(current)["score"]:
            current = trial
    return current


def _system(extra: str = "", scene_text: str = "") -> str:
    craft = craft_notes(scene_text)
    return (
        "你是短剧的导演兼摄影指导和美术指导，负责一场戏的 3D 预演：搭景、站位、姿势、机位和运动。"
        "你通过语义操作修改舞台，操作由程序执行并校验。只输出一个 JSON 对象，不要解释或代码块标记。\n\n"
        f"{OP_GUIDE}\n\n模型库（id（名称 宽×深×高，米））：\n{model_kit.catalog_text()}\n\n{_RULES}"
        + (f"\n\n美术与摄影规范：\n{craft}" if craft else "")
        + (f"\n\n{extra}" if extra else "")
    )


_PLAN_FORMAT = """输出这个 JSON：
{"title": "方案名（6 字内）", "rationale": "两三句话，说清为什么这样摆：谁是重心、空间怎么用、镜头怎么讲戏", "operations": [ ... ]}
要求：
1. 先搭景：用 add_landmark 把这场戏必需的环境和关键道具摆出来，优先用模型库；已有的布景能用就用，不合适就 remove_landmark 或移动。
2. 再站位：用 move_actor / face_pair / arrange_group 定每个人的位置和朝向，定好后 set_axis。
3. 需要肢体表达的人物摆姿势（先 set_figure，再 set_pose）。
4. 最后给每一镜定机位：solve_camera {shot_id, size, angle, ...}；有运动的镜头加 apply_camera_move 或 auto_route。
操作按这个顺序写。总数控制在 60 个以内。"""


@dataclass
class Candidate:
    id: str
    title: str
    rationale: str
    source: str  # "model" or "rules"
    plan: StagePlan
    measured: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    rounds: int = 1

    def as_dict(self, *, with_plan: bool = True) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "rationale": self.rationale, "source": self.source,
            "score": self.measured["score"], "measured": self.measured, "errors": self.errors[:12], "rounds": self.rounds,
            **({"plan": self.plan.model_dump(mode="json")} if with_plan else {}),
        }


def _strategies(count: int) -> Sequence[tuple[str, str]]:
    return STRATEGIES[:max(1, min(count, len(STRATEGIES)))]


def plan_prompt(baseline: StagePlan, scene_text: str, strategy: tuple[str, str], goal: str = "", memory: str = "") -> str:
    return (
        f"这一场的剧本：\n{scene_text[:6000]}\n\n"
        + (f"{memory}\n\n" if memory else "") +
        f"程序先按规则排了一版舞台，你可以推翻其中任何部分：\n{digest(baseline)}\n\n"
        f"这版的方案方向是「{strategy[0]}」：{strategy[1]}\n"
        + (f"导演的额外要求：{goal.strip()[:MAX_MESSAGE]}\n" if goal.strip() else "")
        + f"\n{_PLAN_FORMAT}"
    )


def build_candidate(
    baseline: StagePlan, scene_text: str, strategy: tuple[str, str], llm: LLM, index: int, goal: str = "", memory: str = "",
) -> Candidate | None:
    """One complete staging from the model, or None when it gave nothing that could be used."""
    system = _system(scene_text=scene_text)
    prompt = plan_prompt(baseline, scene_text, strategy, goal, memory)
    reply = read_reply(llm(system, prompt, PLAN_MAX_TOKENS))
    if not reply or not reply["operations"]:
        return None
    done = apply_each(baseline, reply["operations"])
    if not done.applied:
        logger.warning("[DirectorAI] 方案 %s 的 %d 个操作全部失败: %s", strategy[0], len(reply["operations"]), done.errors[:3])
        return None
    plan, errors, rounds = done.plan, done.errors, 1
    # One round to answer for what failed: the errors are specific, and a fix is much cheaper than a new plan.
    failing = repair.failing(plan.checks) or scoring.score_plan(plan)["notes"]
    if errors or failing:
        follow_up = (
            f"你刚才的操作执行后，舞台变成：\n{digest(plan)}\n\n{_report(plan)}\n"
            + ("执行失败的操作：\n" + "\n".join(errors) + "\n" if errors else "")
            + '\n只输出修正这些问题所需的增量操作：{"operations": [ ... ]}。没有要改的就输出 {"operations": []}。'
        )
        again = read_reply(llm(system, follow_up, TURN_MAX_TOKENS))
        rounds = 2
        if again and again["operations"]:
            fixed = apply_each(plan, again["operations"])
            if scoring.score_plan(fixed.plan)["score"] >= scoring.score_plan(plan)["score"]:
                plan, errors = fixed.plan, fixed.errors
    plan = polish(_mannequins_for_poses(plan))
    return Candidate(
        id=f"model-{index + 1}", title=reply["title"] or strategy[0], rationale=reply["rationale"],
        source="model", plan=plan.model_copy(update={"planner": "model", "planner_note": reply["rationale"][:600]}),
        measured=scoring.score_plan(plan), errors=errors, rounds=rounds,
    )


def rank(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Model plans first unless they still break a check the rule plan does not: a passing plan always beats a failing one.

    Among those, what the model meant counts: a plan most of whose operations failed is mostly the baseline it started from.
    """
    return sorted(candidates, key=lambda item: (
        item.measured["errors"] > 0 or item.measured["standing"] > 0, item.source != "model",
        -(item.measured["score"] - min(_FAILED_OP_LIMIT, _FAILED_OP_COST * len(item.errors))),
    ))


def rules_candidate(baseline: StagePlan) -> Candidate:
    plan = polish(baseline)
    return Candidate(
        id="rules", title="规则基线", rationale="规则规划器的方案：不调用模型，按人物关系和剧本动作套用调度模板再求解机位。",
        source="rules", plan=plan, measured=scoring.score_plan(plan), rounds=0,
    )


def run_turn(
    plan: StagePlan, message: str, llm: LLM, *, history: Sequence[Mapping[str, Any]] = (), scope: Scope = Scope(),
    scene_text: str = "", max_rounds: int = MAX_TURN_ROUNDS, memory: str = "",
) -> dict[str, Any]:
    """One message: edit a working copy until the model is done or the rounds run out; nothing is saved."""
    system = _system(
        '每次输出：{"reply": "对用户说的话，简短说明你做了什么、为什么；没改东西就直接回答", "operations": [ ... ], "done": true}。'
        "用户只是提问时 operations 留空。改动后程序会把结果读给你，还有问题就把 done 写成 false 并继续；满意了 done 写 true。"
        "用户明确要求的改动，即使让某项检查不通过也照做，但要在 reply 里说明后果。"
        + project_memory.REMEMBER_INSTRUCTION,
        scene_text,
    )
    past = "\n".join(f"{'用户' if item.get('role') == 'user' else '你'}：{str(item.get('text') or '')[:400]}" for item in history[-8:])
    working, errors, reply_text, applied = plan, [], "", []
    remembered: list[Any] = []
    rounds = 0
    feedback = ""
    for rounds in range(1, max(1, max_rounds) + 1):
        # The script and the past conversation do not change between rounds of one turn: once is enough.
        prompt = (
            (f"剧本：\n{scene_text[:3000]}\n\n" if scene_text and rounds == 1 else "")
            + (f"{memory}\n\n" if memory and rounds == 1 else "")
            + (f"之前的对话：\n{past}\n\n" if past and rounds == 1 else "")
            + f"当前舞台：\n{digest(working)}\n\n{_report(working)}\n\n"
            + (f"{scope.describe()}\n" if scope.limited else "")
            + f"用户说：{message.strip()[:MAX_MESSAGE]}"
            + (f"\n\n{feedback}" if feedback else "")
        )
        reply = read_reply(llm(system, prompt, TURN_MAX_TOKENS))
        if reply is None:
            if rounds == 1:
                raise DirectorAIError("模型没有返回结果，舞台没有改动；请检查模型配置或稍后重试")
            break
        reply_text = reply["reply"] or reply_text
        remembered.extend(reply["remember"])
        if not reply["operations"]:
            break
        before = set(repair.failing(working.checks))
        done = apply_each(working, reply["operations"], scope)
        working, errors = done.plan, done.errors
        applied.extend(done.applied)
        introduced = set(repair.failing(working.checks)) - before
        if reply["done"] and not errors and not introduced:
            break
        feedback = (
            "你上一轮的操作已经执行，上面的「当前舞台」就是执行后的状态。\n"
            + (("失败的操作：\n" + "\n".join(errors) + "\n") if errors else "")
            + (f"新出现的检查问题：{'、'.join(sorted(introduced))}\n" if introduced else "")
            + "只输出还需要的增量操作；不需要再改就让 operations 为空，并在 reply 里告诉用户最终做了什么。"
        )
    return {
        "reply": reply_text or ("已按要求调整舞台。" if applied else "这次没有改动舞台。"),
        "plan": working, "applied": applied, "errors": errors, "rounds": rounds, "remember": remembered,
    }


OPTIMIZE_MESSAGE = (
    "请检查这版舞台，优化它：先解决未通过的检查和上面列出的问题，再看站位有没有层次、镜头有没有变化、"
    "人物是否在画面合适的位置。只改确实有帮助的地方，没问题的不要动。"
)


def optimize(plan: StagePlan, llm: LLM | None, *, goal: str = "", scene_text: str = "", scope: Scope = Scope(), memory: str = "") -> dict[str, Any]:
    """Make the stage better: rules first, then the model; a result that scores lower is thrown away."""
    start = scoring.score_plan(plan)
    best = polish(plan) if not scope.limited else plan
    reply = "用规则修正了能自动修的问题，并在现有机位附近找了更好的视角。"
    applied: list[Mapping[str, Any]] = []
    errors: list[str] = []
    rounds = 0
    used_model = False
    if llm is not None:
        try:
            outcome = run_turn(best, goal.strip() or OPTIMIZE_MESSAGE, llm, scope=scope, scene_text=scene_text, memory=memory)
        except DirectorAIError:
            reply += "（模型没有返回结果，这次只用了规则。）"
        else:
            used_model, errors, rounds = True, outcome["errors"], outcome["rounds"]
            trial = _mannequins_for_poses(outcome["plan"]) if outcome["applied"] else outcome["plan"]
            if scoring.score_plan(trial)["score"] >= scoring.score_plan(best)["score"]:
                best, applied, reply = trial, outcome["applied"], outcome["reply"]
            else:
                reply = "模型给的改动没有让评分变高，已放弃，只保留了规则修正。"
    finish = scoring.score_plan(best)
    if finish["score"] < start["score"]:
        best, finish = plan, start
    return {
        "plan": best, "reply": reply, "applied": applied, "errors": errors, "rounds": rounds, "used_model": used_model,
        "before": start, "after": finish,
    }


_MODEL_SYSTEM = (
    "你是电影美术的白模师，把一件东西搭成可以放进 3D 预演的简单体块组合：比例对、轮廓一眼认得出，不追求细节。"
    "只输出一个 JSON 对象，不要解释或代码块标记。"
)
_MODEL_FORMAT = """输出：
{"name": "物体名", "kind": "prop|furniture|architecture|light", "summary": "一句话", "kit": "模型库里正好有这东西时写 id，否则留空", "parts": [
  {"shape": "box|cylinder|sphere|cone|wedge", "center": [x, y, z], "size": [宽, 深, 高], "rotation": [0, 0, 0], "tone": "|dark|light"}
]}
约定：单位米，真实尺寸；原点在物体地面中心，y 向上，+z 是物体正面；center 是体块中心；size 是体块未旋转时的 [X, Z, Y] 尺寸；rotation 是绕 x、y、z 的度数（车轮是竖着的圆柱：rotation [0, 0, 90]）。wedge 的高边在 -Z。tone 用来区分主要部件。
拆分：先大形（主体），再次形（腿、轮、屋顶），最后最能认出它的一两个细节。总数 6 到 40 块；部件要相互接触，不要悬空。
如果模型库里有，kit 写 id、parts 留空即可。

模型库（id（名称 宽×深×高，米））：
"""


def model_prompt(description: str, size: Sequence[float] | None = None) -> tuple[str, str]:
    craft = craft_notes(description)
    user = f"{_MODEL_FORMAT}{model_kit.catalog_text()}\n\n要搭的东西：{description.strip()[:MAX_MESSAGE]}"
    if size:
        user += f"\n总尺寸约 宽 {size[0]:g} 米、深 {size[1]:g} 米、高 {size[2]:g} 米。"
    return _MODEL_SYSTEM + (f"\n\n{craft}" if craft else ""), user


def read_model_reply(text: Any, description: str, size: Sequence[float] | None = None) -> dict[str, Any]:
    """A proposal for one object: its name, overall size and parts, ready for ``add_landmark``."""
    data = extract_json_object(str(text or ""))
    if data is None:
        raise DirectorAIError("模型没有返回可解析的模型结构，请重试或把描述写具体一些")
    name = str(data.get("name") or description).strip()[:40] or "模型"
    kind = data.get("kind") if data.get("kind") in ("prop", "furniture", "architecture", "light") else "prop"
    kit_id = str(data.get("kit") or "").strip()
    try:
        if data.get("parts"):
            parts, overall, dropped = model_kit.read_parts(data["parts"], size)
            kit = ""
        elif kit_id:
            found, parts, overall = model_kit.build_kit(kit_id, size)
            kit, kind, dropped = found.id, found.kind, 0
        else:
            raise DirectorAIError("模型没有给出任何体块，请重试或把描述写具体一些")
    except model_kit.ModelKitError as error:
        raise DirectorAIError(str(error)) from error
    return {
        "name": name, "kind": kind, "kit": kit, "size": overall, "summary": str(data.get("summary") or "")[:200],
        "parts": [part.model_dump(mode="json") for part in parts], "dropped": dropped,
    }


__all__ = [
    "Applied", "Candidate", "DirectorAIError", "LLM", "MAX_CANDIDATES", "MAX_MESSAGE", "MODEL_MAX_TOKENS", "OP_GUIDE", "POSE_PRESETS",
    "PLAN_MAX_TOKENS", "STRATEGIES", "Scope", "TURN_MAX_TOKENS", "apply_each", "build_candidate", "craft_notes", "digest", "model_prompt",
    "optimize", "out_of_scope", "plan_prompt", "polish", "rank", "read_model_reply", "read_reply", "rules_candidate", "run_turn",
]
