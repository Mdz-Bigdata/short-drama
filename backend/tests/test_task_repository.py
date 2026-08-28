import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repository.task_repo import TaskRepository, TaskStoreUnavailableError


class TaskRepositoryTests(unittest.TestCase):
    def test_local_task_writes_are_round_trip_and_leave_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            repo = TaskRepository(str(path))
            repo.save_task("task-1", {"task_id": "task-1", "status": "running"})
            self.assertEqual(repo.get_task("task-1")["status"], "running")
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            self.assertTrue(repo.delete_task("task-1"))
            self.assertIsNone(repo.get_task("task-1"))


if __name__ == "__main__":
    unittest.main()


class TaskStoreFailureTests(unittest.TestCase):
    """A store that cannot be read must never be mistaken for an empty one."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.json"
        self.repo = TaskRepository(str(self.path))
        for index in range(3):
            self.repo.save_task(f"task-{index}", {"task_id": f"task-{index}", "status": "idle"})

    def tearDown(self):
        self.temp.cleanup()

    def test_a_corrupt_database_refuses_reads_and_writes_instead_of_wiping_it(self):
        self.path.write_text('{"task-0": {"task_id"', encoding="utf-8")

        with self.assertRaises(TaskStoreUnavailableError):
            self.repo.get_task("task-0")
        with self.assertRaises(TaskStoreUnavailableError):
            self.repo.list_all_tasks()
        with self.assertRaises(TaskStoreUnavailableError):
            self.repo.save_task("task-9", {"task_id": "task-9"})

        # The damaged file is left exactly as found; no task was destroyed.
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"task-0": {"task_id"')

    def test_a_non_object_database_is_rejected_rather_than_treated_as_empty(self):
        self.path.write_text("[]", encoding="utf-8")

        with self.assertRaises(TaskStoreUnavailableError):
            self.repo.list_all_tasks()

    def test_a_missing_database_is_still_a_legitimately_empty_store(self):
        self.path.unlink()

        self.assertEqual(self.repo.list_all_tasks(), [])
        self.repo.save_task("task-9", {"task_id": "task-9"})
        self.assertEqual(self.repo.get_task("task-9"), {"task_id": "task-9"})

    def test_a_failed_write_does_not_leave_a_temporary_file_behind(self):
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")

        with patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.repo.save_task("task-9", {"task_id": "task-9"})

        self.assertFalse(temporary.exists())
        # The original database survived the failed write.
        self.assertIn("task-0", self.repo.list_all_tasks()[0]["task_id"])


class PromptFileResolutionTests(unittest.TestCase):
    """Prompt documents must resolve from the repo, not a developer's home."""

    def test_prompts_resolve_without_any_hardcoded_absolute_path(self):
        from app.service import drama_service as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/Users/mindezhi", source)

        service = module.DramaService()
        content = service.read_md_file("AI短剧注意事项与关键元素.md")
        self.assertTrue(content.strip(), "a shipped prompt document should be readable")

    def test_prompt_root_can_be_overridden_and_missing_files_are_safe(self):
        from app.service.drama_service import DramaService

        service = DramaService()
        with tempfile.TemporaryDirectory() as elsewhere:
            (Path(elsewhere) / "custom.md").write_text("覆盖后的提示词", encoding="utf-8")
            with patch.dict("os.environ", {"DRAMA_PROMPT_ROOT": elsewhere}):
                self.assertEqual(service.read_md_file("custom.md"), "覆盖后的提示词")
                self.assertEqual(service.read_md_file("absent.md"), "")

    def test_the_duplicate_prompt_reader_is_gone_from_the_model_gateway(self):
        from app.core import model_gateway

        self.assertFalse(hasattr(model_gateway.ModelGateway, "read_md_file"))
