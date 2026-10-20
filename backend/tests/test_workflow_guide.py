import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.core.workflow_guide import assistant_intent
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaTaskResponse
from app.service.drama_service import DramaService, StagePrerequisiteError


def outputs(stage):
    return {
        1: {"1": "已确认方案"},
        2: {
            "2": "第1集 夜雨\n场景1：林夏：去找线索。\n第2集 黎明\n场景1：林夏：找到了。"
        },
        3: {
            "3": "角色资产",
            "3_sheets": {"林夏": "actor.png"},
            "3_character_dashboard": {"state": "READY"},
        },
        4: {
            "4": [{"scene_id": "E1S01", "image_url": "shot.png"}],
            "4_storyboard": {"panels": []},
            "4_grid": "grid.png",
            "4_quality": {"passed": True},
        },
        5: {"5": [{"video_url": "clip.mp4"}]},
        6: {"6": {"audio_url": "audio.mp3"}},
        7: {"7": {"final_video_url": "film.mp4"}},
        8: {"8": {"pr_content": "宣发文案", "short_link": "share-link"}},
    }[stage]


def task_at(completed):
    assets = {}
    for stage in range(1, completed + 1):
        assets.update(outputs(stage))
    return {
        "task_id": "workflow",
        "current_stage": completed,
        "stage_name": "阶段",
        "status": "idle",
        "config": {"title_suggestion": "测试", "episode_count": 2, "video_model": "seedance2.0"},
        "assets": assets,
        "logs": {},
    }


class WorkflowGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService.__new__(DramaService)
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.gateway = Mock()

    def save(self, task):
        self.service.repo.save_task(task["task_id"], task)

    def test_slash_commands_are_explicit_and_unknown_commands_are_help_only(self):
        expected = {
            "/pause": ("pause", None),
            "/resume": ("resume", None),
            "/stop": ("stop", None),
            "/start": ("continue", None),
            "/compose": ("compose", 7),
            "/auto": ("run_all", None),
            "/status": ("status", None),
            "/help": ("help", None),
        }
        for command, intent in expected.items():
            self.assertEqual(assistant_intent(command), intent)
        for command in ("/", "/unknown", "/auto 不要生成"):
            self.assertEqual(assistant_intent(command), ("help", None))

    def test_slash_compose_explains_missing_prerequisites_without_skipping(self):
        self.save(task_at(3))
        with patch.object(self.service, "execute_stage") as execute:
            response = asyncio.run(
                self.service.assistant_message("workflow", "/compose")
            )
        self.assertEqual(response["action"], "none")
        self.assertIn("尚未完整完成", response["reply"])
        execute.assert_not_called()

    def test_slash_stop_preserves_assets_and_history(self):
        task = task_at(3)
        self.save(task)
        response = asyncio.run(self.service.assistant_message("workflow", "/stop"))
        self.assertEqual(response["action"], "stop")
        stored = self.service.repo.get_task("workflow")
        self.assertEqual(stored["status"], "stopped")
        self.assertEqual(stored["assets"], task["assets"])
        self.assertEqual(len(stored["chat_history"]), 2)
        self.assertIn("保留", response["reply"])

    def test_stop_or_pause_does_not_turn_failed_old_assets_into_completed_outputs(self):
        for command in ("/stop", "/pause"):
            for has_progress in (False, True):
                task = task_at(5)
                task["status"] = "failed"
                if has_progress:
                    task["stage_progress"] = {"stage": 5, "status": "error"}
                if self.service.repo.get_task("workflow"):
                    self.service.repo.mutate_task(
                        "workflow",
                        lambda current: (current.clear(), current.update(task)),
                    )
                else:
                    self.save(task)
                response = asyncio.run(
                    self.service.assistant_message("workflow", command)
                )
                self.assertEqual(response["task"]["workflow"]["next_stage"], 5)
                with patch.object(self.service, "execute_stage"):
                    response = asyncio.run(
                        self.service.assistant_message("workflow", "/resume")
                    )
                self.assertEqual(response["stage"], 5)

    def test_slash_resume_remembers_automatic_mode(self):
        for automatic in (False, True):
            task = task_at(3)
            task.update(
                status="paused",
                workflow_control={"automatic": automatic, "active": False},
            )
            (
                self.service.repo.mutate_task(
                    "workflow", lambda current: current.update(task)
                )
                if self.service.repo.get_task("workflow")
                else self.save(task)
            )
            with patch.object(self.service, "execute_stage"), patch.object(
                self.service, "execute_all_stages"
            ):
                response = asyncio.run(
                    self.service.assistant_message("workflow", "/resume")
                )
            self.assertEqual(
                response["action"], "run_all" if automatic else "run_stage"
            )
            self.assertEqual(response["stage"], 4)

    def test_all_eight_steps_are_driven_by_actual_outputs(self):
        for completed in range(9):
            with self.subTest(completed=completed):
                snapshot = self.service.workflow_snapshot(task_at(completed))
                self.assertEqual(len(snapshot["stages"]), 8)
                self.assertEqual(
                    snapshot["next_stage"], completed + 1 if completed < 8 else None
                )
                self.assertEqual(
                    snapshot["completed_stages"], list(range(1, completed + 1))
                )
        self.assertEqual(self.service.workflow_snapshot(task_at(8))["mode"], "review")

    def test_failed_stage_with_old_outputs_is_retried_not_skipped(self):
        task = task_at(5)
        task["status"] = "failed"
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 5)
        with self.assertRaises(StagePrerequisiteError):
            self.service._assert_stage_prerequisites(task, 6)

    def test_failed_render_without_media_cannot_advance_to_promotion(self):
        task = task_at(7)
        task["assets"]["7"] = {"final_video_url": None, "compose_mode": "failed"}
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 7)
        with self.assertRaises(StagePrerequisiteError):
            self.service._assert_stage_prerequisites(task, 8)

    def test_empty_video_and_audio_metadata_do_not_count_as_outputs(self):
        task = task_at(6)
        task["assets"]["5"] = [{"video_url": None, "image_url": "image.png"}]
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 5)
        task["assets"].update(outputs(5))
        task["assets"]["6"] = {"audio_url": None, "shot_voices": [None]}
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 6)

    def test_missing_upstream_cannot_be_hidden_by_downstream_outputs(self):
        task = task_at(7)
        del task["assets"]["2"]
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 2)
        with self.assertRaises(StagePrerequisiteError):
            self.service._assert_stage_prerequisites(task, 8)

    def test_partial_storyboards_and_missing_episode_progress_stay_on_four(self):
        task = task_at(4)
        task["assets"]["4_progress"] = {"episodes": [{"number": 1, "complete": True}]}
        self.assertEqual(self.service.workflow_snapshot(task)["next_stage"], 4)
        task["assets"]["4_progress"]["episodes"].append(
            {"number": 2, "complete": False}
        )
        snapshot = self.service.workflow_snapshot(task)
        self.assertIn("1/2 集", snapshot["hint"])
        self.assertEqual(snapshot["next_stage"], 4)

    def test_completion_requires_both_real_review_gates(self):
        task = task_at(8)
        for status in (
            "completed",
            "awaiting_quality_review",
            "quality_failed",
            "awaiting_council_review",
            "council_quality_failed",
        ):
            task["status"] = status
            self.assertFalse(self.service.workflow_snapshot(task)["release_ready"])
            self.assertEqual(self.service.workflow_snapshot(task)["mode"], "review")
        task["status"] = "completed"
        task["assets"]["7"]["quality_gate"] = {"passed": True}
        task["assets"]["8"]["council_release_gate"] = {"releasable": True}
        self.assertEqual(self.service.workflow_snapshot(task)["mode"], "completed")

    def test_running_progress_percent_does_not_create_new_guidance_events(self):
        task = task_at(3)
        task.update(
            current_stage=4,
            status="running",
            stage_progress={"status": "running", "percent": 10},
        )
        first = self.service.workflow_snapshot(task)
        task["stage_progress"]["percent"] = 90
        task["stage_progress"]["updated_at"] = "later"
        self.assertEqual(
            first["event_id"], self.service.workflow_snapshot(task)["event_id"]
        )

    def test_council_gate_alone_cannot_substitute_for_promotion_agent_outputs(self):
        task = task_at(7)
        task["assets"]["7"]["quality_gate"] = {"passed": True}
        task["assets"]["8"] = {"council_release_gate": {"releasable": True}}
        task["status"] = "completed"
        snapshot = self.service.workflow_snapshot(task)
        self.assertEqual(snapshot["next_stage"], 8)
        self.assertFalse(snapshot["release_ready"])
        self.save(task)
        with self.assertRaisesRegex(ValueError, "第8阶段"):
            self.service.submit_council_release("workflow", None)

    def test_malformed_outline_rows_do_not_hide_episodes_or_break_polling(self):
        task = task_at(4)
        task["assets"]["2_breakdown"] = {"scenes": [{"content": "无编号旧记录"}]}
        task["assets"]["4_progress"] = {"episodes": []}
        self.save(task)
        status = self.service.get_task_status("workflow")
        self.assertEqual(status["workflow"]["next_stage"], 4)
        self.assertEqual(
            [scene["scene_id"] for scene in status["assets"]["2_breakdown"]["scenes"]],
            ["E1S01", "E2S01"],
        )

    def test_questions_greetings_negated_and_unknown_messages_never_execute(self):
        for message in (
            "你好",
            "谢谢",
            "怎么继续？",
            "请不要暂停",
            "不要一键成片",
            "先不重跑第4阶段",
            "能不能重新生成",
            "进度",
            "随机意见",
        ):
            task = task_at(4)
            self.save(task)
            with patch.object(self.service, "execute_stage") as execute:
                response = asyncio.run(
                    self.service.assistant_message("workflow", message)
                )
            self.assertEqual(response["action"], "none", message)
            execute.assert_not_called()
            self.assertEqual(
                self.service.repo.get_task("workflow")["assets"], task["assets"]
            )
        self.service.gateway.assert_not_called()

    def test_polite_explicit_commands_have_the_same_intent(self):
        for prefix in ("请", "请帮我", "帮我", "麻烦你"):
            self.assertEqual(assistant_intent(prefix + "继续"), ("continue", None))
            self.assertEqual(assistant_intent(prefix + "重跑第 4 阶段"), ("rerun", 4))
            self.assertEqual(assistant_intent(prefix + "一键成片"), ("run_all", None))

    def test_chat_history_is_persisted_and_exposed_by_schema(self):
        self.save(task_at(1))
        asyncio.run(self.service.assistant_message("workflow", "你好"))
        persisted = self.service.repo.get_task("workflow")["chat_history"]
        self.assertEqual(
            [message["role"] for message in persisted], ["user", "assistant"]
        )
        response = self.service.get_task_status("workflow")
        wire = DramaTaskResponse.model_validate(response).model_dump(by_alias=True)
        self.assertEqual(wire["chatHistory"], persisted)
        self.assertEqual(wire["workflow"]["next_stage"], 2)

    def test_atomic_reservation_rejects_duplicate_generation(self):
        self.save(task_at(3))
        first = self.service._claim_stage_task("workflow", 4)
        with self.assertRaises(StagePrerequisiteError):
            self.service._claim_stage_task("workflow", 4)
        self.assertEqual(
            self.service.repo.get_task("workflow")["workflow_control"],
            first["workflow_control"],
        )

    def test_partial_four_continue_claims_four_not_five(self):
        task = task_at(4)
        task["assets"]["4_progress"] = {"episodes": [{"number": 1, "complete": False}]}
        self.save(task)

        async def scenario():
            with patch.object(
                self.service, "execute_stage", return_value=None
            ) as execute:
                response = await self.service.assistant_message("workflow", "继续")
                await asyncio.sleep(0)
                self.assertEqual(response["stage"], 4)
                self.assertEqual(execute.call_args.args[1], 4)

        asyncio.run(scenario())

    def test_pause_survives_worker_snapshot_and_stops_at_safe_boundary(self):
        self.save(task_at(3))
        worker = self.service._claim_stage_task("workflow", 4)
        self.service.pause_task("workflow")
        worker["stage_progress"]["status"] = "success"
        self.save(worker)
        snapshot = self.service.get_task_status("workflow")["workflow"]
        self.assertIn("暂停请求", snapshot["hint"])
        self.assertEqual(snapshot["mode"], "running")
        self.service._finish_workflow_run(
            "workflow", worker["workflow_control"]["run_id"]
        )
        self.assertEqual(self.service.repo.get_task("workflow")["status"], "paused")

    def test_one_click_completes_eight_in_order_and_never_restarts_on_review(self):
        self.save(task_at(0))
        calls = []

        def fake_worker(task_id, stage, *, _claimed_task):
            calls.append(stage)
            task = deepcopy(_claimed_task)
            task["assets"].update(outputs(stage))
            task["stage_progress"]["status"] = "success"
            self.save(task)
            return task

        with patch.object(
            self.service, "_execute_stage_blocking", side_effect=fake_worker
        ):
            asyncio.run(self.service.execute_all_stages("workflow"))
            asyncio.run(self.service.execute_all_stages("workflow"))
        self.assertEqual(calls, list(range(1, 9)))
        self.assertEqual(
            self.service.get_task_status("workflow")["workflow"]["mode"], "review"
        )

    def test_no_progress_auto_run_stops_instead_of_looping_paid_calls(self):
        self.save(task_at(3))

        def no_outputs(task_id, stage, *, _claimed_task):
            _claimed_task["stage_progress"]["status"] = "success"
            self.save(_claimed_task)
            return _claimed_task

        with patch.object(
            self.service, "_execute_stage_blocking", side_effect=no_outputs
        ) as run:
            asyncio.run(self.service.execute_all_stages("workflow"))
        self.assertEqual(run.call_count, 1)
        task = self.service.repo.get_task("workflow")
        self.assertEqual(task["status"], "failed")
        self.assertFalse(task["workflow_control"]["active"])

    def test_repair_is_idempotent_and_shared_by_status_dashboard_and_production(self):
        task = task_at(2)
        existing = {
            "scene_id": "E2S07",
            "content": "保留编辑",
            "duration": "11s",
            "image_url": "keep.png",
        }
        task["assets"]["2_breakdown"] = {
            "scenes": [existing],
            "roles": [{"name": "林夏"}],
        }
        self.save(task)
        self.service.repair_outline("workflow")
        first = self.service.repo.get_task("workflow")
        self.service.repair_outline("workflow")
        self.assertEqual(self.service.repo.get_task("workflow"), first)
        self.assertIn(existing, first["assets"]["2_breakdown"]["scenes"])
        ids = [scene["scene_id"] for scene in self.service._breakdown_scenes(first)]
        self.assertEqual(
            ids,
            [
                scene.scene_id
                for scene in self.service.get_writer_dashboard("workflow").scenes
            ],
        )
        self.assertEqual(
            ids,
            [
                scene["scene_id"]
                for scene in self.service.get_task_status("workflow")["assets"][
                    "2_breakdown"
                ]["scenes"]
            ],
        )



class StageDoneReviewMessageTests(unittest.TestCase):
    LABELS = DramaService.STAGE_LABELS

    def _task(self, automatic: bool) -> dict:
        return {
            "task_id": "review-message",
            "workflow_control": {"run_id": "r", "automatic": automatic},
            "stage_progress": {"stage": 1, "started_at": "t0"},
            "chat_history": [],
        }

    def _snapshot(self) -> dict:
        return {"completed_stages": [1], "next_stage": 2, "hint": "已完成 1/8 步。接下来是第 2/8 步：编剧剧本创作。"}

    def test_manual_mode_holds_the_finished_stage_for_review(self):
        from app.core.workflow_guide import append_stage_guidance

        message = append_stage_guidance(self._task(False), "done", self.LABELS, self._snapshot())
        self.assertIn("已停在第 1 步看板，请先审核本步产物", message["content"])
        self.assertIn("回复「继续」进入下一步", message["content"])

    def test_automatic_mode_does_not_ask_for_review(self):
        from app.core.workflow_guide import append_stage_guidance

        message = append_stage_guidance(self._task(True), "done", self.LABELS, self._snapshot())
        self.assertNotIn("请先审核", message["content"])


class SelectedTextModelTests(unittest.TestCase):
    """Every stage runs on the globally selected text model when the project's own is not enabled."""

    def tearDown(self):
        from app.platform.runtime_models import runtime_model_registry

        runtime_model_registry.replace([])

    def _registry(self, *model_ids):
        from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry

        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="deepseek", category="text", provider="deepseek", base_url="https://api.deepseek.com",
            api_key="k", model_ids=tuple(model_ids),
        )] if model_ids else [])

    def test_a_disabled_project_model_is_replaced_and_saved_at_stage_start(self):
        self._registry("deepseek-flash")
        task = {"task_id": "t", "config": {"llm_model": "deepseek-v4-pro"}}
        DramaService._adopt_selected_text_model(task)
        self.assertEqual(task["config"]["llm_model"], "deepseek-flash")

    def test_an_enabled_choice_or_an_empty_registry_is_left_alone(self):
        self._registry("deepseek-flash", "deepseek-v4-pro")
        task = {"task_id": "t", "config": {"llm_model": "deepseek-v4-pro"}}
        DramaService._adopt_selected_text_model(task)
        self.assertEqual(task["config"]["llm_model"], "deepseek-v4-pro")
        self._registry()
        stale = {"task_id": "t", "config": {"llm_model": "gone"}}
        DramaService._adopt_selected_text_model(stale)
        self.assertEqual(stale["config"]["llm_model"], "gone")

    def test_the_claim_writes_the_selected_model_into_the_task(self):
        self._registry("deepseek-flash")
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            service = DramaService()
            service.repo = repo
            task = task_at(0)
            task["config"]["llm_model"] = "deepseek-v4-pro"
            repo.save_task(task["task_id"], task)
            service._claim_stage_task(task["task_id"], 1)
            self.assertEqual(repo.get_task(task["task_id"])["config"]["llm_model"], "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
