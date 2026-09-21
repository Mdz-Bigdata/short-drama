# -*- coding: utf-8 -*-
"""连续性自检从「弹层清单」变成「项目级检查」的验收。

三件事必须同时成立：场景板上有结论、阶段闸门认这个结论、质检模型先看到机器结果。
"""

import unittest
from typing import Any, Dict
from unittest import mock

from app.core import knowledge_evolution
from app.core.continuity_audit import (
    aggregate_scene_boards,
    audit_markdown,
    audit_prompt_detail,
    gate_reasons,
    summarize_checks,
)
from app.service.drama_service import DramaService


def _check(code: str, passed: bool, severity: str = "error") -> Dict[str, Any]:
    return {"code": code, "passed": passed, "severity": severity, "detail": f"{code} 的说明"}


class SummaryTests(unittest.TestCase):
    def test_only_error_failures_fail_the_summary(self):
        summary = summarize_checks([
            _check("timeline_full_coverage", True),
            _check("single_beat_no_connector", False, "warning"),
        ])

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["warning_codes"], ["single_beat_no_connector"])
        self.assertEqual(summary["total"], 2)

    def test_an_error_failure_is_recorded_with_its_detail(self):
        summary = summarize_checks([_check("timeline_no_gap_overlap", False)])

        self.assertFalse(summary["passed"])
        self.assertEqual(summary["error_codes"], ["timeline_no_gap_overlap"])
        self.assertEqual(summary["failures"][0]["detail"], "timeline_no_gap_overlap 的说明")

    def test_a_missing_detail_is_itself_a_failure(self):
        summary = audit_prompt_detail(None)

        self.assertFalse(summary["passed"])
        self.assertEqual(summary["error_codes"], ["missing_prompt_detail"])

    def test_the_compiler_verdict_can_only_make_things_stricter(self):
        detail = {"continuity_checks": [_check("ok", True)], "submission_ready": False}

        self.assertFalse(audit_prompt_detail(detail)["passed"])


class AggregateTests(unittest.TestCase):
    def test_boards_without_a_verdict_are_not_counted(self):
        audit = aggregate_scene_boards({
            "E1S01": {"status": "done", "continuity": summarize_checks([_check("a", True)])},
            "E1S02": {"status": "pending"},
        })

        self.assertEqual(audit["scenes_checked"], 1)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["scenes_failed"], [])

    def test_one_failing_scene_fails_the_aggregate_and_names_the_scene(self):
        audit = aggregate_scene_boards({
            "E1S01": {"continuity": summarize_checks([_check("a", True)])},
            "E1S02": {"continuity": summarize_checks([_check("state_chain_continuous", False)])},
        })

        self.assertFalse(audit["passed"])
        self.assertEqual(audit["scenes_failed"], ["E1S02"])
        self.assertEqual(audit["failures"][0]["scene_id"], "E1S02")
        self.assertEqual(gate_reasons(audit), ["4_continuity_audit.passed=true (E1S02:state_chain_continuous)"])

    def test_passing_or_absent_audits_produce_no_gate_reason(self):
        self.assertEqual(gate_reasons(None), [])
        self.assertEqual(gate_reasons({"passed": True, "failures": []}), [])

    def test_markdown_lists_failures_and_is_silent_without_checks(self):
        self.assertEqual(audit_markdown({"scenes_checked": 0}), "")
        table = audit_markdown(aggregate_scene_boards({
            "E1S03": {"continuity": summarize_checks([_check("verbatim_dialogue_preserved", False)])},
        }))
        self.assertIn("| E1S03 | verbatim_dialogue_preserved | error |", table)


def _stage_four_assets(audit: Dict[str, Any] | None) -> Dict[str, Any]:
    assets: Dict[str, Any] = {
        "4": [{"shot_id": 1}], "4_storyboard": {"x": 1}, "4_grid": "u", "4_quality": {"passed": True},
    }
    if audit is not None:
        assets["4_continuity_audit"] = audit
    return assets


class StageGateTests(unittest.TestCase):
    def test_a_failed_audit_blocks_stage_five(self):
        failing = aggregate_scene_boards({
            "E1S02": {"continuity": summarize_checks([_check("grid_pages_exact_layout", False)])},
        })

        missing = DramaService._missing_stage_outputs({"assets": _stage_four_assets(failing)}, 4)

        self.assertIn("4_continuity_audit.passed=true (E1S02:grid_pages_exact_layout)", missing)

    def test_a_passing_audit_or_an_old_task_is_not_blocked(self):
        passing = aggregate_scene_boards({"E1S01": {"continuity": summarize_checks([_check("a", True)])}})

        self.assertEqual(DramaService._missing_stage_outputs({"assets": _stage_four_assets(passing)}, 4), [])
        self.assertEqual(DramaService._missing_stage_outputs({"assets": _stage_four_assets(None)}, 4), [])


class _CapturingGateway:
    def __init__(self):
        self.calls = []

    def call_llm(self, model, system_prompt, user_prompt, *args, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        return "| 检查维面 | 质检内容 | 状态得分 | 状态说明 |\n|---|---|---|---|\n| 连续性 | 时间轴 | 5 | 通过 |"


class QualityHookTests(unittest.TestCase):
    def test_stage_four_qc_sees_the_machine_audit_before_the_checklist(self):
        gateway = _CapturingGateway()
        service = DramaService.__new__(DramaService)
        service.gateway = gateway
        assets = _stage_four_assets(aggregate_scene_boards({
            "E1S04": {"continuity": summarize_checks([_check("timeline_no_gap_overlap", False)])},
        }))

        with mock.patch.object(knowledge_evolution, "harvest_from_qc"), \
             mock.patch.object(knowledge_evolution, "promote_and_prune"):
            report = service.run_real_consistency_check(4, "分镜", assets, {"llm_model": "x"}, "测试剧")

        self.assertIn("HOOK 拦截器触发", report)
        _, user_prompt = gateway.calls[-1]
        self.assertIn("机器连续性自检", user_prompt)
        self.assertIn("| E1S04 | timeline_no_gap_overlap | error |", user_prompt)
        self.assertLess(user_prompt.find("机器连续性自检"), user_prompt.find("请参考以下一致性检查清单"))

    def test_other_stages_are_not_given_a_stage_four_audit(self):
        gateway = _CapturingGateway()
        service = DramaService.__new__(DramaService)
        service.gateway = gateway

        with mock.patch.object(knowledge_evolution, "harvest_from_qc"), \
             mock.patch.object(knowledge_evolution, "promote_and_prune"):
            service.run_real_consistency_check(2, "剧本", {"2": "剧本正文"}, {"llm_model": "x"}, "测试剧")

        self.assertNotIn("机器连续性自检", gateway.calls[-1][1])


if __name__ == "__main__":
    unittest.main()
