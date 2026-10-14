"""Read-only, output-backed guidance shared by chat, polling and scheduling."""

import hashlib
import json
import re
from typing import Any, Callable

STAGE_GUIDANCE = {
    1: "先确定题材、受众、人物冲突和整季方向。请检查总导演方案是否符合您的创作目标。",
    2: "将方案写成分集剧本和场景大纲。请检查集数连续、剧情与对白完整。",
    3: "建立数字演员、场地、道具、服装和特效资产。请检查角色造型与剧本设定一致。",
    4: "按每集、每场剧情制作分镜，并关联本场演员与拍摄资产。请检查画面内容和镜头衔接。",
    5: "把确认的分镜制作成视频镜头。请检查人物一致性、动作与画面连续性。",
    6: "制作角色配音、音效和配乐。请检查台词、情绪、音量与画面对齐。",
    7: "合成视频、字幕和音轨。请预览成片，再提交质量验收。",
    8: "生成宣发文案与发布素材。最后完成成片质量验收和八 Agent 发布终审。",
}


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
        content = f"开始第 {stage}/8 步：{labels[stage]}。\n{STAGE_GUIDANCE[stage]}"
        if control.get("automatic"):
            content += "\n当前是自动制作模式，无需逐步确认；我会继续说明每一步的结果，您也可以随时请求暂停。"
        else:
            content += "\n完成后我会说明本阶段结果，再引导您确认或继续。"
    elif phase == "failed":
        content = f"第 {stage}/8 步：{labels[stage]}本轮未完成，已停止推进。\n已有内容会保留。请查看错误提示，处理后说「继续」从未完成处恢复。"
    elif phase == "interrupted":
        # 服务重启会杀掉正在执行的阶段，却没有任何异常能写进聊天；不交代一句，
        # 用户只会看到「已完成 0/8 步」，以为流程卡死了。
        content = (
            f"第 {stage}/8 步：{labels[stage]}执行到一半时服务重启，本轮被打断，未能完成。\n"
            "已有内容会保留。回复「继续」重新执行这一步，完成后会自动进入下一步的看板。"
        )
    elif phase == "done" and snapshot:
        complete = stage in snapshot["completed_stages"]
        content = (
            f"第 {stage}/8 步：{labels[stage]}的产物已生成。"
            if complete
            else f"第 {stage}/8 步：{labels[stage]}本轮处理已结束，但本阶段仍有待完成内容。"
        )
        next_stage = snapshot["next_stage"]
        if control.get("stop_requested"):
            content += "\n已收到结束请求，当前阶段结束后停止后续制作，已有内容保留。"
        elif control.get("pause_requested"):
            content += "\n已收到暂停请求，当前阶段结束后暂停后续制作，已有内容保留。"
        elif next_stage is None:
            content += "\n" + snapshot["hint"]
        elif control.get("automatic"):
            verb = "仍需补齐" if next_stage <= stage else "下一步是"
            content += f"\n接下来{verb}第 {next_stage}/8 步：{labels[next_stage]}。{STAGE_GUIDANCE[next_stage]}"
            content += "\n我会先检查暂停或结束请求；没有收到时才继续制作，无需手动确认。"
        else:
            if complete:
                # 手动模式：看板停在这一步，等用户审核产物后再说「继续」。
                content += f"\n已停在第 {stage} 步看板，请先审核本步产物；确认无误后回复「继续」进入下一步，需要调整请说「修改……」。"
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
    release_ready = (
        production_complete
        and video_gate.get("passed") is True
        and council_gate.get("releasable") is True
    )
    actions: list[dict[str, Any]] = []
    if running:
        mode = "running"
        hint = f"正在进行第 {current}/8 步：{labels.get(current, '准备制作')}。{STAGE_GUIDANCE.get(current, '')}"
        if control.get("stop_requested"):
            hint += "\n已请求结束任务。当前阶段结束后停止后续制作，已有产物和聊天记录会保留。"
        elif control.get("pause_requested"):
            hint += "\n已收到暂停请求；当前阶段执行结束后会停下，不再启动后续阶段。本阶段内的模型调用可能仍会继续。"
        else:
            hint += "\n完成这一轮后，我会根据实际产物提示下一步；您可以随时查询进度或请求暂停。"
            actions.append(
                {"kind": "pause", "label": "暂停后续制作", "message": "暂停"}
            )
    elif release_ready and status == "completed":
        mode = "completed"
        hint = (
            "8 个 Agent 的制作流程和发布终审均已通过，整个项目完成。\n"
            "成片在第 7 步「合成发布渲染合流」看板，宣发文案与短链在第 8 步「宣发Agent引流」看板；"
            "想换个版本可以说「重跑第 7 阶段」重新合成。"
        )
        actions.append(
            {"kind": "rerun", "label": "重新合成成片", "message": "重跑第 7 阶段", "stage": 7}
        )
    elif production_complete:
        # 八步产物齐了不等于走完流程：还剩成片验收和八 Agent 发布终审两道门，
        # 这里要把「去哪一页、点什么」说清楚，用户不该在最后一公里没了指引。
        mode = "review"
        if video_gate.get("passed") is not True:
            hint = (
                "8 个 Agent 的制作产物已生成，只差最后两步。\n"
                "第一步：打开第 7 步「合成发布渲染合流」看板，预览成片并检查视频、字幕、音轨，"
                "然后提交成片质量验收。\n"
                "第二步：验收通过后，在第 8 步「宣发Agent引流」看板提交八 Agent 发布终审，"
                "终审通过整个项目才算完成。"
            )
            actions.append(
                {"kind": "rerun", "label": "重新合成成片", "message": "重跑第 7 阶段", "stage": 7}
            )
        else:
            hint = (
                "成片质量验收已通过，只剩最后一步。\n"
                "请在第 8 步「宣发Agent引流」看板提交八 Agent 发布终审；终审通过后才会标记整个项目完成。"
            )
            actions.append(
                {"kind": "rerun", "label": "重跑宣发文案", "message": "重跑第 8 阶段", "stage": 8}
            )
        if status in {"quality_failed", "council_quality_failed"}:
            hint += "\n上次验收未通过，请先查看未通过项并修正，再提交验收。"
    else:
        assert next_stage is not None
        mode = (
            "paused"
            if status in {"paused", "interrupted", "stopped"}
            else "blocked" if status == "failed" else "ready"
        )
        hint = f"已完成 {len(completed)}/8 步。接下来是第 {next_stage}/8 步：{labels[next_stage]}。\n{STAGE_GUIDANCE[next_stage]}"
        if next_stage == 2:
            gaps = [item for item in missing[2] if item.startswith("剧本缺少第")]
            if gaps:
                hint += "\n" + "；".join(gaps) + "。请先在剧本大纲点击「补写缺失的集数」，保留已有剧本和镜头。回复「继续」则会重新执行编剧阶段。"
        if next_stage == 4:
            episodes = (assets.get("4_progress") or {}).get("episodes", [])
            done = sum(
                isinstance(item, dict) and bool(item.get("complete"))
                for item in episodes
            )
            if episodes:
                hint += f"\n分镜目前完成 {done}/{len(episodes)} 集，需要继续补齐本阶段，暂不进入视频制作。"
        if status == "stopped":
            hint = "任务已结束，已有产物和聊天记录已保留。\n" + hint
        elif mode in {"paused", "blocked"}:
            hint += "\n上次执行已暂停、中断或失败；继续时会从尚未完成的步骤恢复。"
        hint += "\n回复「继续」执行这一步；也可以先告诉我您想了解的内容。要调整已有结果，请明确说「修改……」。"
        actions.extend(
            [
                {
                    "kind": "continue",
                    "label": f"继续：{labels[next_stage]}",
                    "message": "继续",
                    "stage": next_stage,
                },
                {
                    "kind": "run_all",
                    "label": "自动完成剩余制作",
                    "message": "一键成片",
                    "stage": next_stage,
                },
            ]
        )
    actions.append({"kind": "status", "label": "查看流程进度", "message": "进度"})
    stages = [
        {
            "stage": stage,
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
        "production_complete": production_complete,
        "release_ready": release_ready,
        "mode": mode,
        "hint": hint,
        "actions": actions,
        "event_id": hashlib.sha256(
            json.dumps(event, ensure_ascii=False).encode()
        ).hexdigest()[:20],
    }


def assistant_intent(message: str) -> tuple[str, int | None]:
    """Fail closed: ambiguity, negation and questions never schedule generation."""
    msg = message.strip().rstrip("。！! ")
    slash_commands = {
        "/pause": ("pause", None),
        "/暂停": ("pause", None),
        "/resume": ("resume", None),
        "/恢复": ("resume", None),
        "/stop": ("stop", None),
        "/结束任务": ("stop", None),
        "/start": ("continue", None),
        "/开启": ("continue", None),
        "/compose": ("compose", 7),
        "/合成视频": ("compose", 7),
        "/auto": ("run_all", None),
        "/一键成片": ("run_all", None),
        "/status": ("status", None),
        "/进度": ("status", None),
        "/help": ("help", None),
        "/帮助": ("help", None),
    }
    if msg.startswith("/"):
        return slash_commands.get(msg.lower(), ("help", None))
    if re.search(
        r"[?？]|(?:怎么|如何|为什么|是否|能否|能不能|可不可以|可以吗|吗$|介绍|解释)",
        msg,
    ):
        return "question", None
    if re.search(
        r"(?:不要|别|不用|不需要|不想|先不|暂不|无需|不再|不能|不可以|别再)", msg
    ):
        return "read", None
    command = re.sub(r"^(?:请帮我|请|帮我|麻烦你|麻烦)", "", msg).strip()
    if command in {"暂停", "暂停任务", "停止", "停止生成"}:
        return "pause", None
    if command in {"结束", "结束任务", "终止任务"}:
        return "stop", None
    if command in {"恢复", "恢复任务"}:
        return "resume", None
    if command in {"合成视频", "合成成片"}:
        return "compose", 7
    if command in {
        "继续",
        "下一步",
        "继续下一步",
        "开始吧",
        "开始",
        "执行",
        "推进",
        "恢复",
        "继续制作",
    }:
        return "continue", None
    if command in {
        "一键成片",
        "一键生成",
        "全部生成",
        "自动跑完",
        "开始生成",
        "自动完成剩余制作",
    }:
        return "run_all", None
    rerun = re.fullmatch(
        r"(?:重跑|重新生成|重新执行|重做)\s*第?\s*([1-8一二三四五六七八])\s*(?:阶段|步|环节)?",
        command,
    )
    if rerun:
        number = rerun.group(1)
        return "rerun", (
            int(number) if number.isdigit() else "一二三四五六七八".index(number) + 1
        )
    if re.match(r"^(?:修改|调整|改成|把.+改|将.+改|帮我修改|请修改)", command):
        return "edit", None
    if any(term in msg for term in ("进度", "状态", "到哪", "流程")):
        return "status", None
    return "read", None
