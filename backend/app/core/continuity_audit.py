# -*- coding: utf-8 -*-
"""连续性自检的项目级执行。

storyboard_director 为每个镜头算出的 continuity_checks 过去只被渲染成「查看提示词」
弹层里的一张勾选清单——看得见、管不住。本模块把同一份检查结果变成管线里真正起
作用的东西：

* 阶段四每完成一个场景，就把该场景的自检结论写进 4_scene_boards[scene]["continuity"]，
  并汇总成 assets["4_continuity_audit"]；
* 阶段闸门：只要有 error 级失败，阶段四就不算完成，进不了阶段五（旧任务没有这个
  键则不参与判定，与 4_progress 的约定一致）；
* 质检钩子：机器可判定的失败项先于大模型质检写进质检报告，进化引擎据此采收教训。

清单本身不再出现在提示词展示里——它是检查，不是提示词。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


# 阶段闸门与质检报告里最多列这么多条失败，避免一屏刷不完；总数另计。
_MAX_LISTED_FAILURES = 8


def summarize_checks(checks: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """把一组 ContinuityCheckItem（dict 形态）压成结论。

    passed 只看 error 级：warning 级失败（如「只有一个拍点」）是提示，不是缺陷。
    """
    error_codes: list[str] = []
    warning_codes: list[str] = []
    failures: list[dict[str, str]] = []
    total = 0
    for item in checks or ():
        if not isinstance(item, Mapping):
            continue
        total += 1
        if item.get("passed") is True:
            continue
        code = str(item.get("code") or "unknown")
        severity = "warning" if str(item.get("severity") or "error") == "warning" else "error"
        (warning_codes if severity == "warning" else error_codes).append(code)
        failures.append({
            "code": code,
            "severity": severity,
            "detail": str(item.get("detail") or ""),
        })
    return {
        "passed": not error_codes,
        "total": total,
        "error_codes": error_codes,
        "warning_codes": warning_codes,
        "failures": failures,
    }


def audit_prompt_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """对一个场景的 prompt_detail（StoryboardDirectorResult 的 dict）做自检结论。"""
    if not isinstance(detail, Mapping):
        return {"passed": False, "total": 0, "error_codes": ["missing_prompt_detail"],
                "warning_codes": [], "failures": [{
                    "code": "missing_prompt_detail", "severity": "error",
                    "detail": "场景缺少分镜提示词详情，无法执行连续性自检。",
                }]}
    summary = summarize_checks(detail.get("continuity_checks"))
    submission_ready = detail.get("submission_ready")
    # 编译器自己的 submission_ready 与本地结论应当一致；不一致按更严的算。
    if submission_ready is False:
        summary["passed"] = False
    return summary


def aggregate_scene_boards(boards: Mapping[str, Any] | None) -> dict[str, Any]:
    """汇总所有场景板的自检结论，供阶段闸门与前端进度使用。"""
    scenes_checked = 0
    scenes_failed: list[str] = []
    errors = 0
    warnings = 0
    failures: list[dict[str, str]] = []
    for scene_id, entry in sorted((boards or {}).items()):
        if not isinstance(entry, Mapping):
            continue
        continuity = entry.get("continuity")
        if not isinstance(continuity, Mapping):
            continue
        scenes_checked += 1
        error_codes = list(continuity.get("error_codes") or [])
        warning_codes = list(continuity.get("warning_codes") or [])
        errors += len(error_codes)
        warnings += len(warning_codes)
        if error_codes or continuity.get("passed") is False:
            scenes_failed.append(str(scene_id))
        for item in continuity.get("failures") or []:
            if isinstance(item, Mapping):
                failures.append({"scene_id": str(scene_id), **{k: str(v) for k, v in item.items()}})
    return {
        "scenes_checked": scenes_checked,
        "scenes_failed": scenes_failed,
        "errors": errors,
        "warnings": warnings,
        "passed": not scenes_failed,
        "failures": failures,
    }


def gate_reasons(audit: Mapping[str, Any] | None) -> list[str]:
    """阶段闸门用：有 error 级失败就返回一条可读的阻断理由，否则空列表。"""
    if not isinstance(audit, Mapping) or audit.get("passed") is not False:
        return []
    listed = [
        f"{item.get('scene_id')}:{item.get('code')}"
        for item in audit.get("failures") or []
        if isinstance(item, Mapping) and item.get("severity") != "warning"
    ]
    extra = max(0, len(listed) - _MAX_LISTED_FAILURES)
    shown = ",".join(listed[:_MAX_LISTED_FAILURES]) + (f",…+{extra}" if extra else "")
    return [f"4_continuity_audit.passed=true ({shown or '未通过'})"]


def audit_markdown(audit: Mapping[str, Any] | None) -> str:
    """质检报告里的机器自检表：没有检查记录时返回空串，不制造噪声。"""
    if not isinstance(audit, Mapping) or not audit.get("scenes_checked"):
        return ""
    lines = [
        "| 场景 | 检查项 | 级别 | 说明 |",
        "|---|---|---|---|",
    ]
    failures = [item for item in audit.get("failures") or [] if isinstance(item, Mapping)]
    for item in failures[:_MAX_LISTED_FAILURES]:
        lines.append(
            f"| {item.get('scene_id', '-')} | {item.get('code', '-')} | "
            f"{item.get('severity', 'error')} | {item.get('detail', '')} |"
        )
    if len(failures) > _MAX_LISTED_FAILURES:
        lines.append(f"| … | 另有 {len(failures) - _MAX_LISTED_FAILURES} 条 | | |")
    if not failures:
        lines.append("| 全部场景 | 连续性自检 | 通过 | 无失败项 |")
    header = (
        f"已对 {audit.get('scenes_checked')} 个场景执行机器连续性自检："
        f"error {audit.get('errors', 0)} 项、warning {audit.get('warnings', 0)} 项，"
        f"未通过场景 {len(audit.get('scenes_failed') or [])} 个。"
    )
    return header + "\n" + "\n".join(lines)
