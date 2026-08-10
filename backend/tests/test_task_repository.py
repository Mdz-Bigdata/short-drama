import tempfile
import unittest
from pathlib import Path

from app.repository.task_repo import TaskRepository


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
