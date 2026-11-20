"""Read-only, output-backed guidance shared by chat, polling and scheduling."""

from app.core import episode_cycle, prompt_data
import hashlib
import json
import re
from typing import Any, Callable


_WORDING_FILE = "workflow_guide"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/workflow_guide.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

STAGE_GUIDANCE = {
    1: _text_of("module.stage_guidance.1"),
    2: _text_of("module.stage_guidance.2"),
    3: _text_of("module.stage_guidance.3"),
    4: _text_of("module.stage_guidance.4"),
    5: _text_of("module.stage_guidance.5"),
    6: _text_of("module.stage_guidance.6"),
    7: _text_of("module.stage_guidance.7"),
    8: _text_of("module.stage_guidance.8"),
}


# 用户看到的是七个角色：第 6、7 阶段(声音、成片)同属剪辑合成师，都显示成第 6 步，宣发是第 7 步。
# 聊天里的「第 N 步」按这七步算；「第 N 阶段」、stage 字段和重跑命令仍是内部的八个阶段。
DISPLAY_STEPS = 7


def display_step(stage: int) -> int:
    """内部阶段 → 用户看到的第几步(1–5 不变，6、7 → 6，8 → 7)。"""
    return stage if stage <= 6 else stage - 1


def step_text(stage: int) -> str:
    return _text_of("step_text.text").format(display_step(stage), DISPLAY_STEPS)


def steps_done(completed: list[int]) -> int:
    """完成了几步：剪辑合成师那一步要声音和成片都做完才算。"""
    stages_of: dict[int, list[int]] = {}
    for stage in range(1, 9):
        stages_of.setdefault(display_step(stage), []).append(stage)
    return sum(all(stage in completed for stage in group) for group in stages_of.values())


def stage_event_id(task: dict[str, Any], phase: str) -> str | None:
    """Address one semantic event of the reserved stage, independently of when it fires."""
    progress = task.get("stage_progress") or {}
    stage = int(progress.get("stage") or 0)
    if not 1 <= stage <= 8:
        return None
    control = task.get("workflow_control") or {}
    event_key: list[Any] = [
        task.get("script_revision", 0),
        control.get("run_id"),
        stage,
        phase,
    ]
    if phase != "start":
        # One reservation reports one start, but a stage may be attempted more
        # than once inside it (partial Stage 4), and every attempt has a result.
        event_key.append(progress.get("started_at"))
    return "stage-event:" + hashlib.sha256(
        json.dumps(event_key).encode()
    ).hexdigest()[:24]


def find_chat_message(task: dict[str, Any], message_id: str | None) -> dict[str, Any] | None:
    if not message_id:
        return None
    history = task.get("chat_history")
    if not isinstance(history, list):
        return None
    return next(
        (
            item
            for item in history
            if isinstance(item, dict) and item.get("id") == message_id
        ),
        None,
    )


def append_stage_guidance(
    task: dict[str, Any],
    phase: str,
    labels: dict[int, str],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist one semantic event, never one message per progress percentage."""
    progress = task.get("stage_progress") or {}
    stage = int(progress.get("stage") or 0)
    if stage not in labels:
        return None
    control = task.get("workflow_control") or {}
    event_id = stage_event_id(task, phase)
    history = task.setdefault("chat_history", [])
    existing = find_chat_message(task, event_id)
    if existing is not None:
        return existing
    if phase == "start":
        # The reservation announces the stage once. The chat reply reuses this
        # very message so one click never renders two near-identical bubbles.
        content = _text_of("append_stage_guidance.content").format(step_text(stage), labels[stage], STAGE_GUIDANCE[stage])
        if control.get("automatic"):
            content += _text_of("append_stage_guidance.text")
        else:
            content += _text_of("append_stage_guidance.text.2")
    elif phase == "failed":
        content = _text_of("append_stage_guidance.content.2").format(step_text(stage), labels[stage])
    elif phase == "interrupted":
        # 服务重启会杀掉正在执行的阶段，却没有任何异常能写进聊天；不交代一句，
        # 用户只会看到「已完成 0/7 步」，以为流程卡死了。
        content = (
            _text_of("append_stage_guidance.content.3").format(step_text(stage), labels[stage])
        )
    elif phase == "done" and snapshot:
        complete = stage in snapshot["completed_stages"]
        content = (
            _text_of("append_stage_guidance.content.4").format(step_text(stage), labels[stage])
            if complete
            else _text_of("append_stage_guidance.content.5").format(step_text(stage), labels[stage])
        )
        next_stage = snapshot["next_stage"]
        if control.get("stop_requested"):
            content += _text_of("append_stage_guidance.text.3")
        elif control.get("pause_requested"):
            content += _text_of("append_stage_guidance.text.4")
        elif next_stage is None:
            content += "\n" + snapshot["hint"]
        elif control.get("automatic"):
            verb = _text_of("append_stage_guidance.verb") if next_stage <= stage else _text_of("append_stage_guidance.verb.2")
            content += _text_of("append_stage_guidance.text.5").format(verb, step_text(next_stage), labels[next_stage], STAGE_GUIDANCE[next_stage])
            content += _text_of("append_stage_guidance.text.6")
        elif complete and stage == 6 and next_stage == 7:
            # 剪辑合成师一个人干两步：声音做完不停，接着合成成片(见 DramaService._compose_after_sound)。
            content += _text_of("append_stage_guidance.text.7").format(labels[7], STAGE_GUIDANCE[7])
        else:
            if complete:
                # 手动模式：看板停在这一步，等用户审核产物后再说「继续」。
                content += _text_of("append_stage_guidance.text.8").format(display_step(stage))
            content += "\n" + snapshot["hint"]
    else:
        return None
    message = {"id": event_id, "role": "assistant", "content": content}
    history.append(message)
    return message


def build_workflow_snapshot(
    task: dict[str, Any],
    labels: dict[int, str],
    missing_outputs: Callable[[dict[str, Any], int], list[str]],
) -> dict[str, Any]:
    assets = task.get("assets") or {}
    status = task.get("status", "idle")
    current = int(task.get("current_stage", 0) or 0)
    progress = task.get("stage_progress") or {}
    control = task.get("workflow_control") or {}
    running = status not in {"interrupted", "failed"} and (
        bool(control.get("active"))
        or (status == "running" and progress.get("status") == "running")
    )
    missing = {stage: missing_outputs(task, stage) for stage in range(1, 9)}
    next_stage = next((stage for stage in range(1, 9) if missing[stage]), None)
    completed = list(range(1, next_stage or 9))
    production_complete = next_stage is None
    video_gate = (
        (assets.get("7") or {}).get("quality_gate", {})
        if isinstance(assets.get("7"), dict)
        else {}
    )
    council_gate = (
        (assets.get("8") or {}).get("council_release_gate", {})
        if isinstance(assets.get("8"), dict)
        else {}
    )
    # 完成 = 成片验收过 + 人说了「确认发布」；旧项目走过八 Agent 门禁的也算。
    human_release = (
        (assets.get("8") or {}).get("human_release", {})
        if isinstance(assets.get("8"), dict)
        else {}
    )
    release_ready = production_complete and (
        bool(human_release.get("confirmed_at"))
        or (video_gate.get("passed") is True and council_gate.get("releasable") is True)
    )
    actions: list[dict[str, Any]] = []
    if running:
        mode = "running"
        hint = _text_of("build_workflow_snapshot.hint").format(step_text(current), labels.get(current, '准备制作'), STAGE_GUIDANCE.get(current, ''))
        if control.get("stop_requested"):
            hint += _text_of("build_workflow_snapshot.text")
        elif control.get("pause_requested"):
            hint += _text_of("build_workflow_snapshot.text.2")
        else:
            hint += _text_of("build_workflow_snapshot.text.3")
            actions.append(
                {"kind": "pause", "label": _text_of("build_workflow_snapshot.label"), "message": _text_of("build_workflow_snapshot.message")}
            )
    elif release_ready and status == "completed":
        mode = "completed"
        hint = (
            _text_of("build_workflow_snapshot.hint.2")
        )
        actions.append(
            {"kind": "rerun", "label": _text_of("build_workflow_snapshot.label.2"), "message": _text_of("build_workflow_snapshot.message.2"), "stage": 7}
        )
    elif production_complete:
        # 八步产物齐了：先验收成片(看图模型自动打分)，人看过之后说「确认发布」项目完成。
        mode = "review"
        if not video_gate:
            hint = (
                _text_of("build_workflow_snapshot.hint.3")
            )
            actions.append({"kind": "review", "label": _text_of("build_workflow_snapshot.label.3"), "message": _text_of("build_workflow_snapshot.message.3")})
        elif video_gate.get("passed") is True:
            hint = (
                _text_of("build_workflow_snapshot.hint.4").format(round(float(video_gate.get('overall_score') or 0) * 100))
            )
            actions.append({"kind": "release", "label": _text_of("build_workflow_snapshot.label.4"), "message": _text_of("build_workflow_snapshot.message.4")})
        else:
            hint = (
                _text_of("build_workflow_snapshot.hint.5") + "、".join(video_gate.get("failed_dimensions") or []) + _text_of("build_workflow_snapshot.hint.6")
            )
            actions.append({"kind": "review", "label": _text_of("build_workflow_snapshot.label.5"), "message": _text_of("build_workflow_snapshot.message.5")})
            actions.append({"kind": "release", "label": _text_of("build_workflow_snapshot.label.6"), "message": _text_of("build_workflow_snapshot.message.6")})
        actions.append(
            {"kind": "rerun", "label": _text_of("build_workflow_snapshot.label.7"), "message": _text_of("build_workflow_snapshot.message.7"), "stage": 7}
        )
        if status in {"quality_failed", "council_quality_failed"}:
            hint += _text_of("build_workflow_snapshot.text.4")
    else:
        assert next_stage is not None
        mode = (
            "paused"
            if status in {"paused", "interrupted", "stopped"}
            else "blocked" if status == "failed" else "ready"
        )
        hint = _text_of("build_workflow_snapshot.hint.7").format(steps_done(completed), DISPLAY_STEPS, step_text(next_stage), labels[next_stage], STAGE_GUIDANCE[next_stage])
        if next_stage == 2:
            gaps = [item for item in missing[2] if item.startswith(_text_of("build_workflow_snapshot.gaps"))]
            if gaps:
                hint += "\n" + "；".join(gaps) + _text_of("build_workflow_snapshot.text.5")
        if next_stage == 3:
            # Soft review gate: production may start, but say which episodes nobody has confirmed.
            review_view = _review_summary(assets)
            if review_view and review_view.get("message"):
                hint += _text_of("build_workflow_snapshot.text.6").format(review_view['message'])
        cycle_line = episode_cycle.status_line(task)
        if cycle_line:
            hint += "\n" + cycle_line
        elif next_stage == 4:
            episodes = (assets.get("4_progress") or {}).get("episodes", [])
            done = sum(
                isinstance(item, dict) and bool(item.get("complete"))
                for item in episodes
            )
            if episodes:
                hint += _text_of("build_workflow_snapshot.text.7").format(done, len(episodes))
        if status == "stopped":
            hint = _text_of("build_workflow_snapshot.hint.8") + hint
        elif mode in {"paused", "blocked"}:
            hint += _text_of("build_workflow_snapshot.text.8")
        hint += (
            _text_of("build_workflow_snapshot.text.9")
        )
        actions.extend(
            [
                {
                    "kind": "continue",
                    "label": _text_of("build_workflow_snapshot.label.8").format(labels[next_stage]),
                    "message": _text_of("build_workflow_snapshot.message.8"),
                    "stage": next_stage,
                },
                {
                    # 「继续」已经自动做到成片；只想做这一步、做完停下看的人用这一个。
                    "kind": "step",
                    "label": _text_of("build_workflow_snapshot.label.9").format(labels[next_stage]),
                    "message": _text_of("build_workflow_snapshot.message.9"),
                    "stage": next_stage,
                },
            ]
        )
    actions.append({"kind": "status", "label": _text_of("build_workflow_snapshot.label.10"), "message": _text_of("build_workflow_snapshot.message.10")})
    stages = [
        {
            "stage": stage,
            "step": display_step(stage),
            "label": labels[stage],
            "guidance": STAGE_GUIDANCE[stage],
            "state": (
                "running"
                if running and stage == current
                else "complete" if stage in completed else "pending"
            ),
            "missing": missing[stage],
        }
        for stage in range(1, 9)
    ]
    # Deliberately excludes poll timestamps/percentages: one event per semantic change.
    event = [
        task.get("task_id"),
        task.get("script_revision", 0),
        mode,
        next_stage,
        completed,
        control.get("run_id"),
        progress.get("started_at"),
        progress.get("status"),
        hint,
    ]
    return {
        "stages": stages,
        "next_stage": next_stage,
        "active_stage": current if running else None,
        "completed_stages": completed,
        "steps_total": DISPLAY_STEPS,
        "steps_done": steps_done(completed),
        "production_complete": production_complete,
        "release_ready": release_ready,
        "mode": mode,
        "hint": hint,
        "actions": actions,
        "event_id": hashlib.sha256(
            json.dumps(event, ensure_ascii=False).encode()
        ).hexdigest()[:20],
    }


def _said(name: str) -> str:
    """One pattern string from assistant_intents.json."""
    return str(prompt_data.value("assistant_intents", name) or "")


def _says(name: str, text: str) -> bool:
    """这句话里有没有 assistant_intents.json 里 ``name`` 那组说法。"""
    return any(re.search(pattern, text) for pattern in prompt_data.words("assistant_intents", name))


def assistant_intent(message: str) -> tuple[str, int | None]:
    """Fail closed: ambiguity, negation and questions never schedule generation."""
    msg = message.strip().rstrip("。！! ")
    slash_commands = {
        "/pause": ("pause", None),
        _text_of("assistant_intent.slash_commands"): ("pause", None),
        "/resume": ("resume", None),
        _text_of("assistant_intent.slash_commands.2"): ("resume", None),
        "/stop": ("stop", None),
        _text_of("assistant_intent.slash_commands.3"): ("stop", None),
        "/start": ("continue", None),
        _text_of("assistant_intent.slash_commands.4"): ("continue", None),
        "/compose": ("compose", 7),
        _text_of("assistant_intent.slash_commands.5"): ("compose", 7),
        "/auto": ("run_all", None),
        _text_of("assistant_intent.slash_commands.6"): ("run_all", None),
        "/status": ("status", None),
        _text_of("assistant_intent.slash_commands.7"): ("status", None),
        "/help": ("help", None),
        _text_of("assistant_intent.slash_commands.8"): ("help", None),
        "/step": ("step", None),
        _text_of("assistant_intent.slash_commands.9"): ("step", None),
    }
    if msg.startswith("/"):
        return slash_commands.get(msg.lower(), ("help", None))
    if re.search(
        _text_of("assistant_intent.text"),
        msg,
    ):
        return "question", None
    # 「不用确认，直接做完」「别停」说的就是自动做完：它们带否定词，但否定的是逐步确认，不是生成。
    if _says("no_confirm", msg) and not re.search(_text_of("assistant_intent.text.2"), msg):
        return "run_all", None
    # 恢复与逐步会花钱：只认整句，「继续把林夏改瘦」不算。逐步先看：「每一步都停下来等我确认」不是暂停。
    bare = re.sub(_said("resume_suffix"), "", re.sub(_said("resume_prefix"), "", msg)).strip()
    if any(re.fullmatch(pattern, bare) for pattern in prompt_data.words("assistant_intents", "step")):
        return "step", None
    # 「先停一下」「先别往下做了」是要暂停：带否定词，但否定的是往下做，所以在否定判断之前看；「不要暂停」不算。
    resumes = any(re.fullmatch(pattern, bare) for pattern in prompt_data.words("assistant_intents", "resume"))
    # 「从停下的地方继续」里也有「停下」：整句是恢复就不当暂停。
    if not resumes and not _says("pause_negated", msg):
        if _says("stop", msg):
            return "stop", None
        if _says("pause", msg):
            return "pause", None
    if re.search(
        _text_of("assistant_intent.text.3"), msg
    ):
        return "read", None
    command = re.sub(_text_of("assistant_intent.command"), "", msg).strip()
    # 八步做完之后：「验收成片」自动验收，「确认发布」是人看过成片后的拍板。
    if _says("review", command):
        return "review", None
    if _says("release", command):
        return "release", None
    if command in {_text_of("assistant_intent.text.4"), _text_of("assistant_intent.text.5"), _text_of("assistant_intent.text.6"), _text_of("assistant_intent.text.7")}:
        return "pause", None
    if command in {_text_of("assistant_intent.text.8"), _text_of("assistant_intent.text.9"), _text_of("assistant_intent.text.10")}:
        return "stop", None
    if command in {_text_of("assistant_intent.text.11"), _text_of("assistant_intent.text.12")}:
        return "resume", None
    if command in {_text_of("assistant_intent.text.13"), _text_of("assistant_intent.text.14")}:
        return "compose", 7
    if command in {
        _text_of("assistant_intent.text.15"),
        _text_of("assistant_intent.text.16"),
        _text_of("assistant_intent.text.17"),
        _text_of("assistant_intent.text.18"),
        _text_of("assistant_intent.text.19"),
        _text_of("assistant_intent.text.20"),
        _text_of("assistant_intent.text.21"),
        _text_of("assistant_intent.text.22"),
        _text_of("assistant_intent.text.23"),
    }:
        return "continue", None
    if command in {
        _text_of("assistant_intent.text.24"),
        _text_of("assistant_intent.text.25"),
        _text_of("assistant_intent.text.26"),
        _text_of("assistant_intent.text.27"),
        _text_of("assistant_intent.text.28"),
        _text_of("assistant_intent.text.29"),
    }:
        return "run_all", None
    if resumes:
        return "resume", None
    rerun = re.fullmatch(
        _text_of("assistant_intent.rerun"),
        command,
    )
    if rerun:
        number = rerun.group(1)
        stage = int(number) if number.isdigit() else _text_of("assistant_intent.stage").index(number) + 1
        # 「第 7 步」是用户看到的宣发；「第 7 阶段」才是内部的成片合成。
        if rerun.group(2) == _text_of("assistant_intent.text.30") and stage == DISPLAY_STEPS:
            stage = 8
        return "rerun", stage
    if re.match(_text_of("assistant_intent.text.31"), command):
        return "edit", None
    # 「帮我从头到尾自动生成成片」「剩下的全部做完」：说法表在 app/data/prompt/assistant_intents.json。
    if _says("run_all", command):
        return "run_all", None
    if any(term in msg for term in _words_of("assistant_intent.text.32")):
        return "status", None
    return "read", None


def _review_summary(assets: dict) -> dict | None:
    state = assets.get("2_screenwriting") if isinstance(assets, dict) else None
    if not isinstance(state, dict) or not state.get("episodes"):
        return None
    from app.core.screenwriting import review

    return review.summary(state)
