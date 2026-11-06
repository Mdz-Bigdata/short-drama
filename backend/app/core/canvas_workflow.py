# -*- coding: utf-8 -*-
"""From a creative brief to a run on the canvas: a plan a person can read before anything is spent.

A plan is a list of steps with named inputs. It is checked as a whole against what the canvas
would really accept (the same connection table a drag goes through), so a plan that validates
goes onto the canvas in one transaction and fails, if at all, because a provider failed rather
than because it was malformed. It stays a draft until someone applies it: planning writes
nothing to the canvas and starts nothing.

Nothing here calls a model or touches storage; see ``app.service.canvas_workflow_service``.

Behavioural reference: the description of DramaClaw's canvas workflows in its README
(Elastic License 2.0). The plan shape, prompts and checks are this project's own; see
THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core import canvas_tools, recipe_catalog, studio_canvas

MAX_STEPS = 40
_COLUMN_GAP = 80
_ROW_GAP = 60
_EXISTING = "node:"
# Kinds a plan may use. A previz node needs a scene someone has staged, which a plan cannot do for them.
StepKind = Literal["note", "media", "style_ref", "image_gen", "video_gen", "audio_gen", "video_compose", "tool"]
RUNNING_KINDS = frozenset({"image_gen", "video_gen", "audio_gen", "video_compose", "tool"})
STEP_STATES = frozenset({"pending", "queued", "running", "done", "failed", "skipped", "cancelled", "waiting_input", "removed"})

PLAN_SYSTEM_PROMPT = (
    "你是短剧和短视频的制作统筹。把创作需求拆成节点画布上的一条制作流程：每一步是一个节点，步骤之间连线传递结果。"
    "只规划真正需要的步骤，不要为了显得完整而加步骤；每多一个生成节点就多花一笔钱。只输出一个 JSON 对象，不要解释。"
)

_RULES = """规划规则：
- 每步有唯一的 ref（小写英文加数字）；inputs 写这一步要用哪些步骤的结果。
- kind 只能是：note（文本）、media（等用户上传的素材，medium 写 image / video / audio）、style_ref（风格描述，写在 text）、image_gen（生成图片）、video_gen（生成视频）、audio_gen（配音、配乐或音效，params.mode 为 speech / music / sfx）、video_compose（把视频片段拼成一条）、tool（工具，tool 字段写工具 id）。
- 平台不做纯文生视频：video_gen 至少要连一张图、一段视频。先出首帧，再连到 video_gen，role 写 first_frame。
- 一个连续镜头太长要切成几段时，后一段的 inputs 连前一段的 video_gen，role 写 continue_from：后一段的首帧就是前一段的尾帧，不挂上接缝处必跳。只有同一个连续镜头才这么连；两个镜头之间是剪切，各自出首帧，不要接。后一段的 prompt 先写上一段的结束状态，再写下一步。
- 动作复杂的镜头，prompt 按「起始姿态→主动作→身体联动→结束姿态」四步写，结束姿态写具体；拿不准可以先用 action_breakdown 工具拆。
- 两个不连续的镜头要接在一起，用 link_design 工具写接法；有首帧和尾帧要过渡，用 frame_bridge 工具写提示词，连到视频节点；首尾帧比例必须相同。
- 同一个角色或场景要在多个镜头里保持一致时，先生成一张参考图，再把它连到每个镜头。
- 提示词写在 prompt，要能直接生成：人物、动作、景别、机位、光线都写清楚。文本节点的内容写在 text。
- 只有确实需要用户提供的东西才用 media；需求里已经写清楚的，直接生成。
- 可以用 recipe 指定配方并在 recipe_inputs 里填它要的字段，这时不用写 prompt。
- 要用画布上已有的节点时，inputs 的 source 写 "node:节点id"。
- 总步数不超过 {max_steps}。"""


class StepInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=40)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
    kind: StepKind
    label: str = Field("", max_length=80)
    prompt: str = Field("", max_length=8000)
    text: str = Field("", max_length=8000)
    tool: str = Field("", max_length=40)
    medium: Literal["", "image", "video", "audio"] = ""
    recipe: str = Field("", max_length=80)
    recipe_inputs: dict[str, Any] = Field(default_factory=dict, max_length=24)
    params: dict[str, Any] = Field(default_factory=dict, max_length=24)
    inputs: list[StepInput] = Field(default_factory=list, max_length=20)


class WorkflowPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=80)
    summary: str = Field("", max_length=500)
    steps: list[PlanStep] = Field(min_length=1, max_length=MAX_STEPS)


def planning_prompt(brief: str, *, existing: Sequence[Mapping[str, Any]] = (), project_title: str = "") -> str:
    tools = "\n".join(
        f"- {tool.id}：{tool.label}，吃 {'/'.join(sorted(tool.inputs))}，产出 {tool.output}"
        + (f"，至少 {tool.images} 张图" if tool.images else "") + (f"，至少 {tool.videos} 段视频" if tool.videos else "")
        for tool in canvas_tools.TOOLS
    )
    looks = "、".join(f"{look.id}（{look.names['zh']}）" for look in canvas_tools.style_wall())
    recipes = "\n".join(
        f"- {recipe['id']}：{recipe['name']}，产出 {recipe['output_type']}，字段 " + "、".join(f"{item['name']}（{item['label']}）" for item in recipe["inputs"])
        for recipe in recipe_catalog.catalog().describe()["recipes"]
    )
    sections = [
        f"# 创作需求\n{brief.strip()}",
        f"# 项目\n{project_title}" if project_title else "",
        _RULES.format(max_steps=MAX_STEPS),
        f"# 可用工具（kind=tool 时用）\n{tools}\n风格转绘的 params.style 从这些里选：{looks}",
        f"# 可用配方\n{recipes}",
    ]
    if existing:
        rows = "\n".join(
            f"- node:{item['id']}：{studio_canvas.KIND_LABELS.get(str(item.get('kind')), item.get('kind'))} {studio_canvas._label(item)}"
            for item in existing[:40]
        )
        sections.append(f"# 画布上已有的节点\n{rows}")
    return "\n\n".join(part for part in sections if part)


def _pseudo(step: PlanStep) -> dict[str, Any]:
    """The step as the canvas's connection table sees a node."""
    params = dict(step.params)
    if step.kind == "tool":
        params["tool"] = step.tool
    payload: dict[str, Any] = {"params": params, "label": step.label}
    if step.medium:
        payload["medium"] = step.medium
    return {"id": step.ref, "kind": step.kind, "payload": payload}


def _problem(ref: str, code: str, message: str, *, blocking: bool = True) -> dict[str, Any]:
    return {"ref": ref, "code": code, "message": message, "blocking": blocking}


def _order_problem(plan: WorkflowPlan) -> list[dict[str, Any]]:
    """A plan that feeds itself can never start, whichever step goes first."""
    refs = {step.ref for step in plan.steps}
    waiting = {step.ref: {item.source for item in step.inputs if item.source in refs} for step in plan.steps}
    while waiting:
        free = [ref for ref, needs in waiting.items() if not needs]
        if not free:
            return [_problem(sorted(waiting)[0], "cycle", f"这些步骤互相依赖，没法开始：{'、'.join(sorted(waiting))}")]
        for ref in free:
            del waiting[ref]
        waiting = {ref: needs - set(free) for ref, needs in waiting.items()}
    return []


def validate_plan(plan: WorkflowPlan, *, existing: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Everything that would stop this plan going onto the canvas, or stop a step that is there from running."""
    problems: list[dict[str, Any]] = []
    by_ref: dict[str, PlanStep] = {}
    for step in plan.steps:
        if step.ref in by_ref:
            problems.append(_problem(step.ref, "duplicate_ref", f"步骤 {step.ref} 重复了"))
        by_ref[step.ref] = step
    nodes = {str(item.get("id")): item for item in existing}
    problems.extend(_order_problem(plan))
    for step in plan.steps:
        target = _pseudo(step)
        kinds: list[str] = []
        for item in step.inputs:
            if item.source == step.ref:
                problems.append(_problem(step.ref, "self", f"{step.ref} 不能用自己的结果"))
                continue
            source: Mapping[str, Any] | None
            if item.source.startswith(_EXISTING):
                source = nodes.get(item.source[len(_EXISTING):])
            else:
                source = _pseudo(by_ref[item.source]) if item.source in by_ref else None
            if source is None:
                problems.append(_problem(step.ref, "unknown_input", f"{step.ref} 要用的 {item.source} 不存在"))
                continue
            if step.kind == "tool" and canvas_tools.get_tool(step.tool) is None:
                continue  # said once below; every input would only repeat it
            try:
                studio_canvas.connection(source, target, role=item.role or None)
            except studio_canvas.CanvasOperationError as error:
                problems.append(_problem(step.ref, "bad_connection", f"{step.ref} ← {item.source}：{error}"))
                continue
            kinds.append(str(studio_canvas.output_type(source)))
        problems.extend(_step_problems(step, kinds))
    return problems


def _step_problems(step: PlanStep, kinds: Sequence[str]) -> list[dict[str, Any]]:
    words = bool(step.prompt.strip() or step.recipe or "text" in kinds)
    found: list[dict[str, Any]] = []
    if step.recipe:
        try:
            recipe_catalog.render(step.recipe, step.recipe_inputs)
        except (LookupError, recipe_catalog.RecipeInputError) as error:
            found.append(_problem(step.ref, "recipe", f"{step.ref} 的配方：{error}"))
    if step.kind == "media" and step.medium not in {"image", "video", "audio"}:
        found.append(_problem(step.ref, "medium", f"{step.ref} 要写明等用户上传 image、video 还是 audio"))
    if step.kind == "note" and not step.text.strip():
        found.append(_problem(step.ref, "empty_text", f"{step.ref} 是文本节点，text 不能是空的"))
    if step.kind == "image_gen" and not words:
        found.append(_problem(step.ref, "no_prompt", f"{step.ref} 没有提示词"))
    if step.kind == "video_gen":
        if not words:
            found.append(_problem(step.ref, "no_prompt", f"{step.ref} 没有提示词"))
        if not any(kind in {"image", "video", "capture"} for kind in kinds):
            found.append(_problem(step.ref, "no_reference", f"{step.ref} 是视频生成，平台不做纯文生视频：至少连一张图或一段视频"))
    if step.kind == "audio_gen":
        if not words:
            found.append(_problem(step.ref, "no_prompt", f"{step.ref} 没有要合成的文本"))
        if str(step.params.get("mode") or "speech") not in {"speech", "music", "sfx"}:
            found.append(_problem(step.ref, "mode", f"{step.ref} 的音频类型只能是 speech、music 或 sfx"))
    if step.kind == "video_compose" and not any(kind in {"video", "capture"} for kind in kinds):
        found.append(_problem(step.ref, "no_clips", f"{step.ref} 是视频合成，至少要连一段视频"))
    if step.kind == "tool":
        found.extend(_tool_problems(step, kinds, words))
    return found


def _tool_problems(step: PlanStep, kinds: Sequence[str], words: bool) -> list[dict[str, Any]]:
    tool = canvas_tools.get_tool(step.tool)
    if tool is None:
        return [_problem(step.ref, "tool", f"{step.ref} 用的工具 {step.tool or '（没写）'} 不存在")]
    found: list[dict[str, Any]] = []
    pictures = sum(kind in {"image", "capture"} for kind in kinds)
    if pictures < tool.images:
        found.append(_problem(step.ref, "no_image", f"{step.ref}（{tool.label}）要连 {tool.images} 张图，现在 {pictures} 张"))
    if kinds.count("video") < tool.videos:
        found.append(_problem(step.ref, "no_video", f"{step.ref}（{tool.label}）要连一段视频"))
    if tool.needs_prompt and not words:
        found.append(_problem(step.ref, "no_prompt", f"{step.ref}（{tool.label}）要写提示词或连文本"))
    if tool.engine == "image" and tool.id != "scene_360":
        # A connected text only arrives at run time, so anything will do here to test the rest of the settings.
        try:
            canvas_tools.image_prompt(tool, step.params, step.prompt or ("上游文本" if "text" in kinds else ""))
        except canvas_tools.CanvasToolError as error:
            found.append(_problem(step.ref, "params", f"{step.ref}（{tool.label}）：{error}"))
    return found


def blocking(problems: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(item.get("message")) for item in problems if item.get("blocking")]


def _depths(plan: WorkflowPlan) -> dict[str, int]:
    refs = {step.ref: step for step in plan.steps}
    depths: dict[str, int] = {}

    def depth(ref: str) -> int:
        if ref not in depths:
            depths[ref] = 0  # validated acyclic; this only guards against being called on a plan that was not
            sources = [item.source for item in refs[ref].inputs if item.source in refs]
            depths[ref] = 1 + max(map(depth, sources)) if sources else 0
        return depths[ref]

    for step in plan.steps:
        depth(step.ref)
    return depths


def compile_operations(plan: WorkflowPlan, *, origin: tuple[float, float] = (0.0, 0.0)) -> list[dict[str, Any]]:
    """The plan as canvas operations, laid out left to right in the order things happen."""
    depths = _depths(plan)
    widest = {column: 0.0 for column in depths.values()}
    for step in plan.steps:
        widest[depths[step.ref]] = max(widest[depths[step.ref]], studio_canvas.DEFAULT_SIZES[step.kind][0])
    lefts: dict[int, float] = {}
    left = origin[0]
    for column in sorted(widest):
        lefts[column] = left
        left += widest[column] + _COLUMN_GAP
    tops: dict[int, float] = {}
    operations: list[dict[str, Any]] = []
    for step in plan.steps:
        column = depths[step.ref]
        top = tops.get(column, origin[1])
        tops[column] = top + studio_canvas.DEFAULT_SIZES[step.kind][1] + _ROW_GAP
        operation: dict[str, Any] = {
            "op": "add_node", "ref": step.ref, "kind": step.kind, "label": step.label, "x": lefts[column], "y": top,
            "params": dict(step.params) | ({"tool": step.tool} if step.kind == "tool" else {}),
        }
        prompt = recipe_catalog.render(step.recipe, step.recipe_inputs)["prompt"] if step.recipe else step.prompt
        if step.kind == "note":
            operation["text"] = step.text
        elif step.kind == "style_ref":
            operation["styleText"] = step.text or step.prompt
        elif step.kind == "media":
            operation["medium"] = step.medium
        elif prompt:
            operation["prompt"] = prompt
        operations.append(operation)
    for step in plan.steps:
        for item in step.inputs:
            source = item.source[len(_EXISTING):] if item.source.startswith(_EXISTING) else item.source
            operations.append({"op": "connect", "source": source, "target": step.ref, **({"role": item.role} if item.role else {})})
    return operations


def step_state(step: Mapping[str, Any], node: Mapping[str, Any] | None, latest: Mapping[str, Any] | None, has_output: bool) -> str:
    """Where one applied step stands, read from the canvas and its runs rather than remembered."""
    if node is None:
        return "removed"
    kind = str(step.get("kind"))
    if kind == "media":
        return "done" if isinstance(studio_canvas.payload_of(node).get("output"), Mapping) else "waiting_input"
    if kind not in RUNNING_KINDS:
        return "done"
    status = str((latest or {}).get("status") or "")
    if status in {"queued", "running", "failed", "skipped", "cancelled"}:
        return status
    return "done" if status == "done" and has_output else "pending"


def overall_state(states: Iterable[str]) -> str:
    """One word for the whole run. What is running goes first: it is what a person is waiting on."""
    seen = set(states) - {"removed"}
    if seen & {"queued", "running"}:
        return "running"
    if seen & {"failed", "skipped", "cancelled"}:
        return "failed"
    if "waiting_input" in seen:
        return "needs_input"
    if "pending" in seen:
        return "ready"
    return "done"


__all__ = [
    "MAX_STEPS", "PLAN_SYSTEM_PROMPT", "PlanStep", "RUNNING_KINDS", "STEP_STATES", "StepInput", "WorkflowPlan", "blocking",
    "compile_operations", "overall_state", "planning_prompt", "step_state", "validate_plan",
]
