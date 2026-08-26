import json
import tempfile
import unittest
from pathlib import Path

from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


class TaskRuntimeLoggingTests(unittest.TestCase):
    def test_progress_events_are_structured_correlated_and_timed(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = object.__new__(DramaService)
            service.repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            task = {"task_id": "task-log-001", "assets": {}, "logs": {}}

            with self.assertLogs("app.service.drama_service", level="INFO") as captured:
                service._progress_begin(task, 4)
                service._progress_step(task, 15, "调用 LLM · 九宫格规划")
                service._progress_done(task)

            payloads = [json.loads(line.split(":", 2)[-1]) for line in captured.output]
            self.assertEqual(
                [payload["event"] for payload in payloads],
                ["task_stage_started", "task_stage_progress", "task_stage_completed"],
            )
            self.assertTrue(all(payload["task_id"] == "task-log-001" for payload in payloads))
            self.assertTrue(all(payload["stage"] == 4 for payload in payloads))
            self.assertEqual(task["stage_progress"]["status"], "success")
            self.assertIn("started_at", task["stage_progress"])
            self.assertIn("updated_at", task["stage_progress"])
            self.assertIn("elapsed_ms", task["stage_progress"])
            self.assertIn("duration_ms", task["stage_progress"]["calls"][0])

    def test_start_script_streams_prefixed_logs_to_terminal_and_files(self):
        script = (Path(__file__).resolve().parents[2] / "start.sh").read_text(encoding="utf-8")

        self.assertIn("stream_log", script)
        self.assertIn('python -u main.py', script)
        self.assertIn('tee -a "$log_file"', script)
        self.assertIn('stream_log "[BACKEND]" "$WORKSPACE_DIR/backend.log"', script)
        self.assertIn('stream_log "[FRONTEND]" "$WORKSPACE_DIR/frontend.log"', script)

    def test_progress_failure_redacts_credentials_before_logging_or_persisting(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = object.__new__(DramaService)
            service.repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            task = {"task_id": "task-secret-001", "assets": {}, "logs": {}}

            service._progress_begin(task, 4)
            with self.assertLogs("app.service.drama_service", level="INFO") as captured:
                service._progress_fail(
                    task,
                    "provider failed api_key=super-secret-credential authorization: Bearer sk_test_abcdefghijklmnop",
                )

            output = "\n".join(captured.output)
            self.assertNotIn("super-secret-credential", output)
            self.assertNotIn("sk_test_abcdefghijklmnop", output)
            self.assertNotIn("super-secret-credential", task["stage_progress"]["error"])
            self.assertIn("[REDACTED]", task["stage_progress"]["error"])


if __name__ == "__main__":
    unittest.main()
