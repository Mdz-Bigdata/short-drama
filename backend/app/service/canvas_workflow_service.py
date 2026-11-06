"""Planning a canvas workflow, keeping the draft, putting it on the canvas, and saying how it is going.

A workflow never runs itself and never reruns what worked: ``runnable`` lists only the steps with
no result yet, and those go through the canvas's ordinary admission, so a retry after a failure
is priced and confirmed like anything else and finished steps cost nothing twice.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.core import canvas_workflow, studio_canvas, usage_ledger
from app.core.canvas_workflow import WorkflowPlan
from app.core.screenwriting.structured_llm import StructuredOutputError, call_structured

logger = logging.getLogger("app.service.canvas_workflow_service")

PLAN_MAX_TOKENS = 6000
PLAN_ATTEMPTS = 3
_ORIGIN_GAP = 120
MAX_BRIEF_CHARS = 4000


class WorkflowError(ValueError):
    """The workflow cannot do what was asked; the message says why."""


class CanvasWorkflowService:
    def __init__(self, studio: Any):
        self.studio = studio
        self.repository = studio.repository

    # ------------------------------------------------------------------ drafts
    def _document(self, project_id: str, owner_id: str, canvas_id: str) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        return canvas.model_dump(mode="json") if canvas else {"nodes": [], "edges": [], "version": 0}

    def plan(self, project_id: str, owner_id: str, *, canvas_id: str, brief: str, drama: Any, user: Mapping[str, Any] | None) -> dict[str, Any]:
        """Ask the text model for a plan and keep it as a draft. Nothing on the canvas changes."""
        text = " ".join(str(brief or "").split())
        if not text:
            raise WorkflowError("先写一下要做什么")
        if len(text) > MAX_BRIEF_CHARS:
            raise WorkflowError(f"需求太长了，请控制在 {MAX_BRIEF_CHARS} 字以内")
        task_id, task = self.studio._canvas_task(project_id, owner_id, drama, user)
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        title = str(config.get("title_suggestion") or "")
        existing = self._document(project_id, owner_id, canvas_id)["nodes"]

        def caller(system: str, prompt: str, max_tokens: int) -> str:
            return drama.gateway.call_llm(str(config.get("llm_model") or ""), system, prompt, title, max_tokens=max_tokens) or ""

        def plan_check(data: dict[str, Any]) -> list[str]:
            return canvas_workflow.blocking(canvas_workflow.validate_plan(WorkflowPlan.model_validate(data), existing=existing))

        try:
            with usage_ledger.bind_task(task_id, "canvas_workflow_plan"):
                result = call_structured(
                    caller, system_prompt=canvas_workflow.PLAN_SYSTEM_PROMPT,
                    user_prompt=canvas_workflow.planning_prompt(text, existing=existing, project_title=title),
                    schema=WorkflowPlan, max_tokens=PLAN_MAX_TOKENS, attempts=PLAN_ATTEMPTS, validators=[plan_check], label="canvas_workflow_plan",
                )
        except StructuredOutputError as error:
            logger.warning("[CanvasWorkflow] 规划失败 project=%s: %s", project_id, str(error)[:400])
            raise WorkflowError(f"模型连续 {PLAN_ATTEMPTS} 次没有给出能用的流程：" + "；".join(error.reasons)[:600]) from error
        except (RuntimeError, OSError) as error:
            logger.warning("[CanvasWorkflow] 模型调用失败 project=%s: %s", project_id, type(error).__name__)
            raise WorkflowError("调用文本模型失败，请稍后重试或在模型配置里换一个模型") from error
        return self._create(project_id, owner_id, canvas_id, text, WorkflowPlan.model_validate(result.data), existing)

    def create(self, project_id: str, owner_id: str, *, canvas_id: str, brief: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        """A draft from a plan someone wrote by hand. Costs nothing, and goes through the same checks."""
        existing = self._document(project_id, owner_id, canvas_id)["nodes"]
        return self._create(project_id, owner_id, canvas_id, brief, self._parse(plan), existing)

    @staticmethod
    def _parse(plan: Mapping[str, Any]) -> WorkflowPlan:
        try:
            return WorkflowPlan.model_validate(plan)
        except ValidationError as error:
            first = error.errors()[0]
            raise WorkflowError(f"流程格式不对：{'.'.join(str(part) for part in first['loc'])} {first['msg']}") from error

    def _create(self, project_id: str, owner_id: str, canvas_id: str, brief: str, plan: WorkflowPlan, existing: list[dict[str, Any]]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": f"wf_{uuid.uuid4().hex[:16]}", "project_id": project_id, "canvas_id": canvas_id, "owner_id": owner_id, "brief": brief[:MAX_BRIEF_CHARS],
            "applied": False, "plan": plan.model_dump(mode="json"), "problems": canvas_workflow.validate_plan(plan, existing=existing), "nodes": {},
            "created_at": now, "updated_at": now,
        }
        self.repository.save_canvas_workflow(record)
        return self.status(project_id, owner_id, record["id"])

    def update(self, project_id: str, owner_id: str, workflow_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        record = self._get(project_id, owner_id, workflow_id)
        if record["applied"]:
            raise WorkflowError("这个流程已经铺到画布上了；要改请直接改节点")
        parsed = self._parse(plan)
        existing = self._document(project_id, owner_id, record["canvas_id"])["nodes"]
        record.update(plan=parsed.model_dump(mode="json"), problems=canvas_workflow.validate_plan(parsed, existing=existing), updated_at=datetime.now(timezone.utc).isoformat())
        self.repository.save_canvas_workflow(record)
        return self.status(project_id, owner_id, workflow_id)

    def _get(self, project_id: str, owner_id: str, workflow_id: str) -> dict[str, Any]:
        record = self.repository.get_canvas_workflow(project_id, owner_id, workflow_id)
        if record is None:
            raise PermissionError("workflow not found")
        return record

    def list(self, project_id: str, owner_id: str, *, canvas_id: str) -> dict[str, Any]:
        rows = self.repository.list_canvas_workflows(project_id, owner_id, canvas_id=canvas_id)
        return {"workflows": [{
            "id": row["id"], "title": row["plan"].get("title", ""), "applied": row["applied"], "steps": len(row["plan"].get("steps", [])),
            "brief": row["brief"][:120], "updated_at": row["updated_at"],
        } for row in rows]}

    def delete(self, project_id: str, owner_id: str, workflow_id: str) -> dict[str, Any]:
        """Forget the plan. Whatever it already put on the canvas stays: those nodes are ordinary nodes now."""
        self._get(project_id, owner_id, workflow_id)
        self.repository.delete_canvas_workflow(project_id, owner_id, workflow_id)
        return {"id": workflow_id}

    # ------------------------------------------------------------------ onto the canvas
    def apply(self, project_id: str, owner_id: str, workflow_id: str, *, base_version: int | None = None) -> dict[str, Any]:
        """All the steps go on the canvas as one new version, or none do. Nothing starts running."""
        with self.repository.canvas_write_lock():
            record = self._get(project_id, owner_id, workflow_id)
            if record["applied"]:
                raise WorkflowError("这个流程已经铺到画布上了")
            plan = WorkflowPlan.model_validate(record["plan"])
            canvas_id = record["canvas_id"]
            document = self._document(project_id, owner_id, canvas_id)
            # The canvas may have changed since the draft was checked: a step can point at a node that has gone.
            problems = canvas_workflow.validate_plan(plan, existing=document["nodes"])
            refused = canvas_workflow.blocking(problems)
            if refused:
                record.update(problems=problems)
                self.repository.save_canvas_workflow(record)
                raise WorkflowError("流程还有问题，先改好：" + "；".join(refused)[:600])
            nodes = document["nodes"]
            origin = (max((float(node["x"]) + float(node["width"]) for node in nodes), default=-_ORIGIN_GAP) + _ORIGIN_GAP, min((float(node["y"]) for node in nodes), default=0.0))
            try:
                done = self.studio.edit_canvas(
                    project_id, owner_id, canvas_workflow.compile_operations(plan, origin=origin), canvas_id=canvas_id, base_version=base_version,
                )
            except studio_canvas.CanvasOperationError as error:
                raise WorkflowError(f"铺到画布时失败：{error}") from error
            record.update(applied=True, nodes=dict(done["created"]), problems=[], updated_at=datetime.now(timezone.utc).isoformat())
            self.repository.save_canvas_workflow(record)
        return {**self.status(project_id, owner_id, workflow_id), "version": done["version"]}

    # ------------------------------------------------------------------ how it is going
    def status(self, project_id: str, owner_id: str, workflow_id: str) -> dict[str, Any]:
        """Read off the canvas and its runs each time: a person may have edited, deleted or rerun anything since."""
        record = self._get(project_id, owner_id, workflow_id)
        steps = record["plan"].get("steps", [])
        view = {key: record[key] for key in ("id", "canvas_id", "brief", "applied", "plan", "problems", "created_at", "updated_at")}
        if not record["applied"]:
            return {**view, "state": "draft", "steps": [{"ref": step["ref"], "state": "draft", "node_id": "", "error": ""} for step in steps],
                    "runnable": [], "can_apply": not canvas_workflow.blocking(record["problems"])}
        nodes = {str(node.get("id")): node for node in self._document(project_id, owner_id, record["canvas_id"])["nodes"]}
        outputs = self.studio.canvas_outputs(project_id, owner_id, canvas_id=record["canvas_id"])
        rows = []
        for step in steps:
            node_id = str(record["nodes"].get(step["ref"]) or "")
            latest = outputs["latest"].get(node_id)
            state = canvas_workflow.step_state(step, nodes.get(node_id), latest, node_id in outputs["outputs"])
            rows.append({"ref": step["ref"], "state": state, "node_id": node_id, "error": str((latest or {}).get("error") or "") if state == "failed" else ""})
        runnable = [row["node_id"] for row, step in zip(rows, steps) if step["kind"] in canvas_workflow.RUNNING_KINDS and row["state"] in {"pending", "failed", "skipped", "cancelled"}]
        return {**view, "state": canvas_workflow.overall_state(row["state"] for row in rows), "steps": rows, "runnable": runnable, "can_apply": False}


__all__ = ["CanvasWorkflowService", "WorkflowError"]
