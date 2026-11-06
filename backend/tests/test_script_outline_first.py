"""第 2 阶段大纲先行：大纲出来阶段就完成，详细剧本在后台写完后一次性落库。"""

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import script_detail
from app.core.writer_dashboard import script_episode_indexes
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService, StagePrerequisiteError

from tests.test_screenwriting_pipeline import _Gateway, _MINIATURE_ENVIRONMENT, _service, _task

TASK = "outline-first-1"


class _GatedGateway(_Gateway):
    """Holds every episode-writing call until ``release`` is set; ``fail_episode`` makes that episode's calls fail."""

    def __init__(self, *, fail_episode: int | None = None):
        super().__init__()
        self.release = threading.Event()
        self.fail_episode = fail_episode

    def call_llm(self, model, system_prompt, user_prompt, *args, **kwargs):
        if "当前正在生成第" in user_prompt:
            if not self.release.wait(10):
                raise TimeoutError("test gate never opened")
            if self.fail_episode is not None and f"当前正在生成第 {self.fail_episode} 集" in user_prompt:
                raise RuntimeError("provider down")
        return super().call_llm(model, system_prompt, user_prompt, *args, **kwargs)


def _wait_for(repo: TaskRepository, status: str) -> dict:
    for _ in range(500):
        task = repo.get_task(TASK) or {}
        record = script_detail.record_of(task)
        if record and record.get("status") == status:
            return task
        time.sleep(0.02)
    raise AssertionError(f"background record never reached {status}: {script_detail.record_of(task)}")


class OutlineFirstTests(unittest.TestCase):
    def setUp(self):
        _MINIATURE_ENVIRONMENT.start()
        self.environment = patch.dict("os.environ", {"SCRIPT_OUTLINE_FIRST": "1", "QC_IN_BACKGROUND": "0"})
        self.environment.start()
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task(TASK, _task(TASK))
        self.qc = patch.object(DramaService, "run_real_consistency_check", return_value="QC-OK")
        self.qc.start()

    def tearDown(self):
        self.qc.stop()
        self.environment.stop()
        _MINIATURE_ENVIRONMENT.stop()
        self.temp.cleanup()

    def _run_stage_two(self, gateway: _Gateway) -> tuple[DramaService, dict]:
        service = _service(gateway, self.repo)
        return service, asyncio.run(service.execute_stage(TASK, 2))

    def test_the_stage_ends_with_the_outline_and_the_screenplay_lands_whole_later(self):
        gateway = _GatedGateway()
        service, task = self._run_stage_two(gateway)

        state = task["assets"][screenwriting.STATE_KEY]
        self.assertEqual([entry["episode"] for entry in state["ledger"]], [1, 2])
        self.assertEqual(state["episodes"], {})
        self.assertEqual(task["assets"]["2"], "", "no episode is shown before all of them are written")
        self.assertEqual({role["name"] for role in task["assets"]["2_breakdown"]["roles"]}, {"林夏", "周教授"})
        stored = self.repo.get_task(TASK)
        self.assertTrue(script_detail.writing(stored))
        self.assertEqual(service._missing_stage_outputs(stored, 2), [], "the character stage may start on the outline")
        with self.assertRaisesRegex(StagePrerequisiteError, "仍在后台撰写"):
            service._assert_stage_prerequisites(stored, 4)

        # A stage that loaded the task before the screenplay landed saves its copy afterwards.
        stale = self.repo.get_task(TASK)
        gateway.release.set()
        done = _wait_for(self.repo, script_detail.DONE)
        self.repo.save_task(TASK, stale)

        final = self.repo.get_task(TASK)
        self.assertEqual(script_episode_indexes(final["assets"]["2"]), [1, 2])
        self.assertEqual(sorted(final["assets"][screenwriting.STATE_KEY]["episodes"]), ["1", "2"])
        self.assertEqual(final["scripted_episode_count"], 2)
        self.assertEqual(final["assets"]["2_writer_dashboard"]["stats"]["sceneCount"], 4)
        self.assertEqual(final["assets"]["2"], done["assets"]["2"], "the stale snapshot did not bring the outline back")
        self.assertIsNone(script_detail.blocking_reason(final))
        self.assertEqual(service.get_task_status(TASK)["logs"]["2"], "QC-OK")

    def test_a_failed_run_keeps_what_it_wrote_and_the_continue_button_finishes_it(self):
        gateway = _GatedGateway(fail_episode=2)
        service, _task_after = self._run_stage_two(gateway)
        gateway.release.set()
        failed = _wait_for(self.repo, script_detail.FAILED)

        # Episodes are written side by side, so a failure may come before any of them was stored.
        self.assertNotIn(2, script_episode_indexes(failed["assets"]["2"]))
        self.assertIn("失败", script_detail.blocking_reason(failed))
        self.assertEqual(service._missing_stage_outputs(failed, 2), [])

        gateway.fail_episode = None
        service.continue_script(TASK)
        final = _wait_for(self.repo, script_detail.DONE)
        self.assertEqual(script_episode_indexes(final["assets"]["2"]), [1, 2])

    def test_running_stage_two_again_cancels_the_old_writer(self):
        gateway = _GatedGateway()
        service, _task_after = self._run_stage_two(gateway)
        old_run = script_detail.record_of(self.repo.get_task(TASK))["run_id"]

        def rerun(current):
            DramaService._discard_later_stage_outputs(current, 2)
            return True

        self.repo.mutate_task(TASK, rerun)
        gateway.release.set()
        time.sleep(0.5)
        stored = self.repo.get_task(TASK)
        self.assertIsNone(script_detail.record_of(stored))
        self.assertEqual(stored["assets"]["2"], "", f"run {old_run} must not land after it was cancelled")

    def test_a_writer_lost_to_a_restart_reads_as_interrupted(self):
        record = script_detail.start_record("gone", 3, 0)
        record["updated_at"] -= script_detail.stall_seconds() + 1
        task = {"assets": {script_detail.KEY: record}}
        self.assertFalse(script_detail.writing(task))
        self.assertTrue(script_detail.pending(task))
        self.assertIn("中断", script_detail.blocking_reason(task))

    def test_an_automatic_run_waits_for_the_screenplay_and_stops_on_pause(self):
        service = _service(_Gateway(), self.repo)
        service.SCRIPT_DETAIL_POLL_SECONDS = 0.01

        def writing(current):
            current["assets"][script_detail.KEY] = script_detail.start_record("r1", 2, 0)
            return True

        self.repo.mutate_task(TASK, writing)

        def finish_soon():
            time.sleep(0.1)
            self.repo.mutate_task(TASK, lambda current: current["assets"][script_detail.KEY].update(status="done") or True)

        threading.Thread(target=finish_soon).start()
        self.assertIsNotNone(asyncio.run(service._await_script_detail(TASK)))

        self.repo.mutate_task(TASK, writing)
        self.repo.mutate_task(TASK, lambda current: current.update(workflow_control={"pause_requested": True}) or True)
        self.assertIsNone(asyncio.run(service._await_script_detail(TASK)))


if __name__ == "__main__":
    unittest.main()
