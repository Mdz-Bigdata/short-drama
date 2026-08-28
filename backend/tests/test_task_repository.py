import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repository.task_repo import (
    StaleTaskWriteError,
    TaskRepository,
    TaskStoreUnavailableError,
)


class TaskRepositoryTests(unittest.TestCase):
    def test_task_writes_round_trip_through_the_sql_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            repo = TaskRepository(str(path))
            repo.save_task("task-1", {"task_id": "task-1", "status": "running"})
            self.assertEqual(repo.get_task("task-1")["status"], "running")
            self.assertTrue(path.with_suffix(".sqlite3").exists())
            self.assertTrue(repo.delete_task("task-1"))
            self.assertIsNone(repo.get_task("task-1"))
            self.assertFalse(repo.delete_task("task-1"))

    def test_listing_preserves_creation_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            for name in ("b-task", "a-task", "c-task"):
                repo.save_task(name, {"task_id": name})
            self.assertEqual(
                [task["task_id"] for task in repo.list_all_tasks()],
                ["b-task", "a-task", "c-task"],
            )

    def test_stale_script_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            repo.save_task("task-1", {"task_id": "task-1", "script_revision": 3})
            with self.assertRaises(StaleTaskWriteError):
                repo.save_task("task-1", {"task_id": "task-1", "script_revision": 2})
            # An equal or newer revision still lands.
            repo.save_task("task-1", {"task_id": "task-1", "script_revision": 3, "status": "x"})
            self.assertEqual(repo.get_task("task-1")["status"], "x")

    def test_mutate_task_persists_the_mutation_and_returns_its_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            repo.save_task("task-1", {"task_id": "task-1", "count": 0})

            def bump(task):
                task["count"] += 1
                return task["count"]

            self.assertEqual(repo.mutate_task("task-1", bump), 1)
            self.assertEqual(repo.get_task("task-1")["count"], 1)
            self.assertIsNone(repo.mutate_task("missing", bump))

    def test_a_failed_mutation_rolls_back_instead_of_half_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            repo.save_task("task-1", {"task_id": "task-1", "status": "idle"})

            def explode(task):
                task["status"] = "broken"
                raise RuntimeError("mutation failed")

            with self.assertRaises(RuntimeError):
                repo.mutate_task("task-1", explode)
            self.assertEqual(repo.get_task("task-1")["status"], "idle")

    def test_concurrent_mutations_do_not_lose_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            repo.save_task("task-1", {"task_id": "task-1", "count": 0})

            def bump(task):
                task["count"] += 1
                return task["count"]

            workers = [
                threading.Thread(target=lambda: [repo.mutate_task("task-1", bump) for _ in range(20)])
                for _ in range(5)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            self.assertEqual(repo.get_task("task-1")["count"], 100)


class LegacyJsonMigrationTests(unittest.TestCase):
    """The old tasks_db.json is imported once and kept untouched as a backup."""

    def test_legacy_tasks_are_imported_once_and_the_json_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "tasks.json"
            original = {
                "task-a": {"task_id": "task-a", "status": "idle"},
                "task-b": {"task_id": "task-b", "status": "completed"},
            }
            legacy.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            repo = TaskRepository(str(legacy))
            self.assertEqual(
                [task["task_id"] for task in repo.list_all_tasks()],
                ["task-a", "task-b"],
            )
            # The JSON file is a backup now, byte-for-byte untouched.
            self.assertEqual(json.loads(legacy.read_text(encoding="utf-8")), original)

            # Post-migration changes must survive a rebuilt repository and must
            # not be overwritten by a second import of the legacy file.
            repo.delete_task("task-a")
            repo.save_task("task-c", {"task_id": "task-c"})
            again = TaskRepository(str(legacy))
            self.assertEqual(
                [task["task_id"] for task in again.list_all_tasks()],
                ["task-b", "task-c"],
            )

    def test_a_corrupt_legacy_file_blocks_startup_instead_of_being_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "tasks.json"
            legacy.write_text('{"task-a": {"task_id"', encoding="utf-8")

            repo = TaskRepository(str(legacy))
            with self.assertRaises(TaskStoreUnavailableError):
                repo.list_all_tasks()
            with self.assertRaises(TaskStoreUnavailableError):
                repo.save_task("task-x", {"task_id": "task-x"})
            # The unreadable legacy data is left exactly as found.
            self.assertEqual(legacy.read_text(encoding="utf-8"), '{"task-a": {"task_id"')

    def test_a_non_object_legacy_file_is_rejected_rather_than_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "tasks.json"
            legacy.write_text("[]", encoding="utf-8")
            repo = TaskRepository(str(legacy))
            with self.assertRaises(TaskStoreUnavailableError):
                repo.list_all_tasks()

    def test_a_missing_legacy_file_is_a_legitimately_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            self.assertEqual(repo.list_all_tasks(), [])
            repo.save_task("task-9", {"task_id": "task-9"})
            self.assertEqual(repo.get_task("task-9"), {"task_id": "task-9"})


class TaskStoreFailureTests(unittest.TestCase):
    """A store that cannot be reached must fail loudly, not appear empty."""

    def test_an_unreachable_database_raises_instead_of_returning_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            corrupted = Path(tmp) / "broken.sqlite3"
            corrupted.write_bytes(b"this is not a sqlite database")
            repo = TaskRepository(
                str(Path(tmp) / "tasks.json"),
                database_url=f"sqlite:///{corrupted}",
            )
            with self.assertRaises(TaskStoreUnavailableError):
                repo.list_all_tasks()
            with self.assertRaises(TaskStoreUnavailableError):
                repo.save_task("task-1", {"task_id": "task-1"})
            with self.assertRaises(TaskStoreUnavailableError):
                repo.get_task("task-1")

    def test_a_row_write_failure_does_not_disturb_other_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            for index in range(3):
                repo.save_task(f"task-{index}", {"task_id": f"task-{index}"})

            with patch.object(repo.engine, "begin", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    repo.save_task("task-9", {"task_id": "task-9"})

            self.assertEqual(len(repo.list_all_tasks()), 3)


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


if __name__ == "__main__":
    unittest.main()
