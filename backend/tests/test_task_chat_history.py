import copy
import tempfile
import unittest
from pathlib import Path

from app.repository.task_repo import StaleTaskWriteError, TaskRepository


def event(identifier, role, content):
    return {"id": identifier, "role": role, "content": content}


class TaskChatHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "chat-task"
        self.initial = {
            "task_id": self.task_id,
            "script_revision": 2,
            "status": "running",
            "assets": {"4": []},
            "chat_history": [event("user-1", "user", "继续")],
        }
        self.repo.save_task(self.task_id, self.initial)

    def append(self, *events):
        self.repo.mutate_task(
            self.task_id, lambda task: task.setdefault("chat_history", []).extend(events),
        )

    def test_stale_worker_save_preserves_new_user_and_assistant_events(self):
        worker = self.repo.get_task(self.task_id)
        new_events = [event("user-2", "user", "当前进度"), event("assistant-2", "assistant", "正在生成分镜")]
        self.append(*new_events)
        worker["assets"]["4"] = [{"scene_id": "E1S01", "status": "done"}]
        self.repo.save_task(self.task_id, worker)
        saved = self.repo.get_task(self.task_id)
        self.assertEqual(saved["chat_history"], self.initial["chat_history"] + new_events)
        self.assertEqual(saved["assets"], worker["assets"])
        self.assertEqual(worker["chat_history"], self.initial["chat_history"], "saving must not mutate a worker's snapshot")

    def test_existing_ids_keep_durable_content_and_new_ids_append_in_order_once(self):
        worker = self.repo.get_task(self.task_id)
        durable = event("assistant-1", "assistant", "阶段已开始")
        self.append(durable)
        worker["chat_history"] = [
            {**self.initial["chat_history"][0], "content": "旧快照内容"},
            {**durable, "content": "旧快照回答"},
            event("user-2", "user", "继续"),
            event("assistant-2", "assistant", "完成"),
            event("assistant-2", "assistant", "重复提交"),
        ]
        self.repo.save_task(self.task_id, worker)
        self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], [
            self.initial["chat_history"][0], durable,
            event("user-2", "user", "继续"), event("assistant-2", "assistant", "完成"),
        ])

    def test_legacy_history_preserves_repeated_messages_without_replaying_snapshot(self):
        legacy = [
            {"sender": "user", "text": "继续"},
            {"sender": "ai", "text": "开始生成"},
            {"sender": "user", "text": "继续"},
        ]
        self.repo.mutate_task(self.task_id, lambda task: task.update(chat_history=copy.deepcopy(legacy)))
        worker = self.repo.get_task(self.task_id)
        latest = event("assistant-2", "assistant", "进度已更新")
        self.append(latest)
        worker["chat_history"].append({"sender": "user", "text": "继续"})
        self.repo.save_task(self.task_id, worker)
        self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], [
            *legacy, latest, {"sender": "user", "text": "继续"},
        ])

    def test_legacy_snapshot_does_not_duplicate_migrated_canonical_events(self):
        worker = self.repo.get_task(self.task_id)
        worker["chat_history"] = [{"sender": "user", "text": "继续"}]
        self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], self.initial["chat_history"])

    def test_saving_hydrated_legacy_ids_does_not_duplicate_original_history(self):
        legacy = [{"sender": "user", "text": "继续"}, {"sender": "ai", "text": "制作中"},
                  {"sender": "user", "text": "继续"}]
        self.repo.mutate_task(self.task_id, lambda task: task.update(chat_history=legacy))
        snapshot = self.repo.get_task(self.task_id)
        snapshot["chat_history"] = [event(f"legacy-{index}", "user" if item["sender"] == "user" else "assistant", item["text"])
                                    for index, item in enumerate(legacy)]
        snapshot["chat_history"].append(event("new-user", "user", "继续"))
        self.repo.save_task(self.task_id, snapshot)
        self.repo.save_task(self.task_id, snapshot)
        self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], [*legacy, event("new-user", "user", "继续")])

    def test_missing_or_empty_snapshot_history_cannot_erase_durable_messages(self):
        for history in (None, []):
            worker = self.repo.get_task(self.task_id)
            if history is None:
                worker.pop("chat_history")
            else:
                worker["chat_history"] = history
            self.repo.save_task(self.task_id, worker)
            self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], self.initial["chat_history"])
        # A deliberate locked mutation remains authoritative, including clearing.
        self.repo.mutate_task(self.task_id, lambda task: task.update(chat_history=[]))
        self.assertEqual(self.repo.get_task(self.task_id)["chat_history"], [])

    def test_old_script_revision_still_rejects_entire_worker_write(self):
        worker = self.repo.get_task(self.task_id)
        self.repo.mutate_task(self.task_id, lambda task: task.update(script_revision=3, status="idle"))
        self.append(event("user-2", "user", "修改后的剧本"))
        expected = self.repo.get_task(self.task_id)
        worker["chat_history"].append(event("worker", "assistant", "旧版本完成"))
        with self.assertRaises(StaleTaskWriteError):
            self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id), expected)

    def test_worker_snapshots_preserve_atomically_updated_workflow_control(self):
        original = {"run_id": "run-one", "active": True, "pause_requested": False, "automatic": True}
        self.repo.mutate_task(self.task_id, lambda task: task.update(workflow_control=original))
        worker = self.repo.get_task(self.task_id)
        paused = {**original, "pause_requested": True}
        self.repo.mutate_task(self.task_id, lambda task: task.update(workflow_control=paused))
        worker["assets"] = {"4": [{"scene_id": "E1S01"}]}
        self.repo.save_task(self.task_id, worker)
        saved = self.repo.get_task(self.task_id)
        self.assertEqual(saved["workflow_control"], paused)
        self.assertEqual(saved["assets"], worker["assets"])
        self.assertEqual(worker["workflow_control"], original)

        finished = {"run_id": "run-one", "active": False, "pause_requested": False, "automatic": False}
        self.repo.mutate_task(self.task_id, lambda task: task.update(workflow_control=finished))
        worker.pop("workflow_control")
        self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id)["workflow_control"], finished)

        # Locked mutations can deliberately replace the reservation entirely.
        self.repo.mutate_task(self.task_id, lambda task: task.update(workflow_control={}))
        worker["workflow_control"] = original
        self.repo.save_task(self.task_id, worker)
        self.assertEqual(self.repo.get_task(self.task_id)["workflow_control"], {})


if __name__ == "__main__":
    unittest.main()
