"""Stage transitions must survive polling gaps, reloads and worker snapshots."""

import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from tests.test_workflow_guide import outputs, task_at


class WorkflowTranscriptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = DramaService.__new__(DramaService)
        self.service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        self.service.repo.save_task("workflow", task_at(0))

    def test_all_eight_stages_are_durable_without_any_frontend_poll(self):
        def worker(task_id, stage, *, _claimed_task):
            task = deepcopy(_claimed_task)
            self.service._progress_begin(task, stage)
            task["assets"].update(outputs(stage))
            self.service._progress_done(task)
            self.service.repo.save_task(task_id, task)
            return task

        with patch.object(self.service, "_execute_stage_blocking", side_effect=worker):
            asyncio.run(self.service.execute_all_stages("workflow"))
        history = self.service.get_task_status("workflow")["chat_history"]
        for stage in range(1, 9):
            self.assertTrue(
                any(f"开始第 {stage}/8 步" in item["content"] for item in history)
            )
            self.assertTrue(
                any(
                    f"第 {stage}/8 步" in item["content"]
                    and "产物已生成" in item["content"]
                    for item in history
                )
            )
        self.assertTrue(any("验收" in item["content"] for item in history))
        self.assertFalse(any("回复「继续」" in item["content"] for item in history))
        self.assertEqual(len(history), len({item["id"] for item in history}))

    def test_gap_guidance_names_missing_episodes_and_offers_preserving_repair(self):
        task = task_at(2)
        task["config"]["episode_count"] = 1
        task["assets"]["2"] = "第1集\n场景1：开场\n第3集\n场景1：结局"
        snapshot = self.service.workflow_snapshot(task)
        self.assertEqual(snapshot["next_stage"], 2)
        self.assertIn("剧本缺少第2集", snapshot["hint"])
        self.assertIn("补写", snapshot["hint"])

    def test_progress_updates_do_not_spam_chat_and_completion_is_idempotent(self):
        task = self.service._claim_stage_task("workflow", 1)
        self.service._progress_begin(task, 1)
        self.service._progress_step(task, 40, "模型调用")
        self.service._progress_step(task, 70, "质量检查")
        self.assertEqual(len(task.get("chat_history", [])), 1)
        task["assets"].update(outputs(1))
        self.service._progress_done(task)
        self.service._progress_done(task)
        self.assertEqual(len(task["chat_history"]), 2)
        self.assertIn("回复「继续」", task["chat_history"][-1]["content"])

    def test_pause_during_automatic_work_never_records_an_unconditional_next_start(self):
        for stop in (False, True):
            task_id = f"pause-{stop}"
            task = {**task_at(0), "task_id": task_id}
            self.service.repo.save_task(task_id, task)
            worker = self.service._claim_stage_task(task_id, 1, automatic=True)
            self.service._progress_begin(worker, 1)
            self.service.pause_task(task_id, stop=stop)
            worker["assets"].update(outputs(1))
            self.service._progress_done(worker)
            self.service.repo.save_task(task_id, worker)
            self.service._finish_workflow_run(task_id, worker["workflow_control"]["run_id"])
            saved = self.service.repo.get_task(task_id)
            self.assertEqual(saved["status"], "stopped" if stop else "paused")
            contents = [item["content"] for item in saved["chat_history"]]
            self.assertFalse(any("自动进入" in text for text in contents))
            self.assertFalse(any("开始第 2/8 步" in text for text in contents))
            self.assertIn("结束" if stop else "暂停", contents[-1])

    def test_partial_storyboard_never_claims_the_entire_stage_is_complete(self):
        task = task_at(4)
        task["workflow_control"] = {"automatic": True, "run_id": "partial"}
        task["assets"]["4_progress"] = {
            "episodes": [
                {"number": 1, "complete": True},
                {"number": 2, "complete": False},
            ]
        }
        self.service._progress_begin(task, 4)
        self.service._progress_done(task)
        content = task["chat_history"][-1]["content"]
        self.assertIn("本轮", content)
        self.assertIn("4/8", content)
        self.assertNotIn("自动进入第 5", content)
        self.assertIn("分镜", content)

    def test_one_continue_records_a_single_start_message(self):
        started = []

        def worker(task_id, stage, *, _claimed_task):
            started.append(stage)
            return _claimed_task

        with patch.object(self.service, "_execute_stage_blocking", side_effect=worker):
            result = asyncio.run(self.service.assistant_message("workflow", "继续"))
        history = self.service.repo.get_task("workflow")["chat_history"]
        assistant = [item["content"] for item in history if item["role"] == "assistant"]
        self.assertEqual(len(assistant), 1)
        self.assertIn("开始第 1/8 步", assistant[0])
        self.assertEqual(result["reply"], assistant[0])
        self.assertEqual(len(history), len({item["id"] for item in history}))

    def test_a_finished_stage_is_never_replayed_after_the_run_fails(self):
        worker = self.service._claim_stage_task("workflow", 1, automatic=True)
        self.service._progress_begin(worker, 1)
        worker["assets"].update(outputs(1))
        self.service._progress_done(worker)
        self.service.repo.save_task("workflow", worker)

        def die(task):
            task["status"] = "failed"
            task["fail_reason"] = "阶段1失败: 上游中断"
            self.service._progress_fail(task, "上游中断")

        self.service.repo.mutate_task("workflow", die)
        snapshot = self.service.workflow_snapshot(self.service.repo.get_task("workflow"))
        self.assertEqual(snapshot["completed_stages"], [1])
        self.assertEqual(snapshot["next_stage"], 2)
        self.assertIn("第 2/8 步：编剧剧本创作", snapshot["hint"])

    def test_replaying_a_stage_still_reports_it_as_unfinished_while_it_runs(self):
        worker = self.service._claim_stage_task("workflow", 1)
        self.service._progress_begin(worker, 1)
        worker["assets"].update(outputs(1))
        self.service._progress_done(worker)
        self.service.repo.save_task("workflow", worker)
        self.service._finish_workflow_run("workflow", worker["workflow_control"]["run_id"])
        replay = self.service._claim_stage_task("workflow", 1)
        self.assertEqual(self.service.workflow_snapshot(replay)["next_stage"], 1)

    def test_failure_is_recorded_without_claiming_success_or_exposing_secrets(self):
        task = self.service._claim_stage_task("workflow", 1)
        self.service._progress_begin(task, 1)
        self.service._progress_fail(task, "api_key=sk-secret12345678901234567890")
        content = task["chat_history"][-1]["content"]
        self.assertIn("未完成", content)
        self.assertNotIn("sk-secret", content)
        self.assertNotIn("产物已生成", content)
