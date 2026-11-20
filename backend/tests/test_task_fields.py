# -*- coding: utf-8 -*-
"""A few fields of a stored task, without parsing the whole project on every read.

``get_task_fields`` and ``list_task_fields`` answer what ``get_task`` and ``list_all_tasks`` would,
reduced to the fields asked for; a row is parsed once per stored version. No model, no network.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app.repository import task_repo
from app.repository.task_repo import TaskRepository

OWNER = ("owner_user_id",)
LINE = ("task_id", "owner_user_id", "status", "config")


def _task(task_id: str, owner: str = "u1", **extra) -> dict:
    return {
        "task_id": task_id, "owner_user_id": owner, "status": "idle", "config": {"title_suggestion": task_id},
        "assets": {"2": "第1集 " + "很长的剧本。" * 200}, **extra,
    }


class _Store(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def tearDown(self):
        self.temp.cleanup()

    def _parses(self):
        """Count the payloads the repository parses while the block runs."""
        counted = []
        original = TaskRepository._load_payload

        def counting(raw):
            counted.append(1)
            return original(raw)

        return counted, patch.object(TaskRepository, "_load_payload", staticmethod(counting))

    def _write_raw(self, task_id: str, payload: str) -> None:
        self.repo.save_task(task_id, _task(task_id))
        with self.repo.engine.begin() as connection:
            connection.execute(
                task_repo._TASKS.update().where(task_repo._TASKS.c.task_id == task_id)
                .values(payload=payload, updated_ns=task_repo.time.time_ns())
            )


class OneTaskTests(_Store):
    def test_it_answers_what_get_task_would(self):
        self.repo.save_task("t1", _task("t1", owner="u7"))
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u7"})
        self.assertEqual(self.repo.get_task_fields("t1", LINE), {key: self.repo.get_task("t1")[key] for key in LINE})
        # A field the task does not have is simply absent, as a .get() on the task would find.
        self.assertEqual(self.repo.get_task_fields("t1", ("video_url",)), {})

    def test_nothing_to_act_on_is_none(self):
        self.assertIsNone(self.repo.get_task_fields("missing", OWNER))
        self._write_raw("broken", "{not json")
        self.assertIsNone(self.repo.get_task("broken"))
        self.assertIsNone(self.repo.get_task_fields("broken", OWNER))
        self._write_raw("empty", "{}")
        self.assertEqual(self.repo.get_task("empty"), {})
        self.assertIsNone(self.repo.get_task_fields("empty", OWNER), "an empty task is refused like a missing one")

    def test_a_task_without_the_field_is_still_a_task(self):
        self._write_raw("ownerless", '{"task_id": "ownerless", "status": "idle"}')
        self.assertEqual(self.repo.get_task_fields("ownerless", OWNER), {})

    def test_an_unchanged_row_is_parsed_once(self):
        self.repo.save_task("t1", _task("t1"))
        counted, counting = self._parses()
        with counting:
            for _ in range(5):
                self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u1"})
        self.assertEqual(len(counted), 1)

    def test_every_kind_of_write_is_seen_at_once(self):
        self.repo.save_task("t1", _task("t1", owner="u1"))
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u1"})

        changed = self.repo.get_task("t1")
        changed["owner_user_id"] = "u2"
        self.repo.save_task("t1", changed)
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u2"})

        self.repo.mutate_task("t1", lambda task: task.update(owner_user_id="u3"))
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u3"})

        self.assertTrue(self.repo.delete_task("t1"))
        self.assertIsNone(self.repo.get_task_fields("t1", OWNER))

        self.repo.save_task("t1", _task("t1", owner="u4"))
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u4"})

    def test_another_repository_on_the_same_database_sees_the_write(self):
        # Two processes are two repositories; here they share one process, which is the harder case for a kept answer.
        other = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t1", _task("t1", owner="u1"))
        self.assertEqual(other.get_task_fields("t1", OWNER), {"owner_user_id": "u1"})
        self.repo.mutate_task("t1", lambda task: task.update(owner_user_id="u9"))
        self.assertEqual(other.get_task_fields("t1", OWNER), {"owner_user_id": "u9"})

    def test_a_write_that_bypasses_this_process_is_seen_by_its_version(self):
        self.repo.save_task("t1", _task("t1", owner="u1"))
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u1"})
        self._write_raw("t1", '{"task_id": "t1", "owner_user_id": "elsewhere"}')
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "elsewhere"})

    def test_the_caller_gets_its_own_copy(self):
        self.repo.save_task("t1", _task("t1"))
        first = self.repo.get_task_fields("t1", LINE)
        first["config"]["title_suggestion"] = "scribbled"
        first["status"] = "scribbled"
        self.assertEqual(self.repo.get_task_fields("t1", LINE), {key: self.repo.get_task("t1")[key] for key in LINE})

    def test_a_stubbed_get_task_still_decides_for_a_task_that_is_not_stored(self):
        with patch.object(self.repo, "get_task", return_value={"task_id": "t9", "owner_user_id": "u5"}):
            self.assertEqual(self.repo.get_task_fields("t9", OWNER), {"owner_user_id": "u5"})
        self.assertIsNone(self.repo.get_task_fields("t9", OWNER), "nothing was kept from the stub")


class ListingTests(_Store):
    def _expected(self, fields=LINE):
        return [{key: task[key] for key in fields if key in task} for task in self.repo.list_all_tasks()]

    def test_it_lists_what_list_all_tasks_would_in_the_same_order(self):
        for index in range(7):
            self.repo.save_task(f"t{index}", _task(f"t{index}", owner=f"u{index % 2}"))
        self.assertEqual(self.repo.list_task_fields(LINE), self._expected())
        self.assertEqual([task["task_id"] for task in self.repo.list_task_fields(LINE)], [f"t{index}" for index in range(7)])

    def test_unreadable_rows_are_left_out_and_empty_ones_kept_as_list_all_tasks_does(self):
        self.repo.save_task("t1", _task("t1"))
        self._write_raw("broken", "[1, 2]")
        self._write_raw("empty", "{}")
        self.assertEqual(self.repo.list_all_tasks()[1:], [{}])
        self.assertEqual(self.repo.list_task_fields(LINE), self._expected())

    def test_a_poll_parses_only_the_rows_that_changed(self):
        for index in range(5):
            self.repo.save_task(f"t{index}", _task(f"t{index}"))
        self.repo.list_task_fields(LINE)
        counted, counting = self._parses()
        with counting:
            self.assertEqual(self.repo.list_task_fields(LINE), self._expected())
            before = len(counted)
        # list_all_tasks (inside _expected) parsed all five; the field listing parsed none.
        self.assertEqual(before, 5)

        self.repo.mutate_task("t3", lambda task: task.update(status="running"))
        counted, counting = self._parses()
        with counting:
            listed = self.repo.list_task_fields(LINE)
        self.assertEqual(len(counted), 1, "only the changed project is read again")
        self.assertEqual([task["status"] for task in listed], ["idle", "idle", "idle", "running", "idle"])

    def test_created_and_deleted_tasks_show_at_once(self):
        self.repo.save_task("t1", _task("t1"))
        self.repo.save_task("t2", _task("t2"))
        self.assertEqual(len(self.repo.list_task_fields(LINE)), 2)
        self.repo.save_task("t3", _task("t3"))
        self.repo.delete_task("t1")
        self.assertEqual([task["task_id"] for task in self.repo.list_task_fields(LINE)], ["t2", "t3"])
        self.assertEqual(self.repo.list_task_fields(LINE), self._expected())

    def test_a_task_deleted_behind_this_process_is_let_go_of(self):
        self.repo.save_task("t1", _task("t1"))
        self.repo.save_task("t2", _task("t2"))
        self.repo.list_task_fields(LINE)
        with self.repo.engine.begin() as connection:
            connection.execute(sa.delete(task_repo._TASKS).where(task_repo._TASKS.c.task_id == "t1"))
        self.assertEqual([task["task_id"] for task in self.repo.list_task_fields(LINE)], ["t2"])
        self.assertIsNone(self.repo._kept_fields().get(LINE, "t1"))

    def test_each_listing_is_the_callers_own(self):
        self.repo.save_task("t1", _task("t1"))
        first = self.repo.list_task_fields(LINE)
        first[0]["config"]["title_suggestion"] = "scribbled"
        first.clear()
        self.assertEqual(self.repo.list_task_fields(LINE), self._expected())

    def test_listings_of_different_fields_do_not_mix(self):
        self.repo.save_task("t1", _task("t1", owner="u1"))
        self.assertEqual(self.repo.list_task_fields(OWNER), [{"owner_user_id": "u1"}])
        self.assertEqual(self.repo.list_task_fields(LINE), self._expected())
        self.assertEqual(self.repo.get_task_fields("t1", OWNER), {"owner_user_id": "u1"})

    def test_many_changed_rows_are_read_in_batches(self):
        with patch.object(task_repo, "_FIELDS_READ_BATCH", 3):
            for index in range(8):
                self.repo.save_task(f"t{index}", _task(f"t{index}"))
            self.assertEqual(self.repo.list_task_fields(LINE), self._expected())


class KeptWithinLimitsTests(_Store):
    """A project's config may carry a whole uploaded script: what is held on to is bounded."""

    def _big(self, task_id: str, size: int) -> dict:
        task = _task(task_id)
        task["config"]["script_content"] = "剧" * size
        return task

    def test_an_answer_too_large_to_keep_is_still_right_and_is_read_each_time(self):
        self.repo.save_task("small", _task("small"))
        self.repo.save_task("large", self._big("large", 500))
        with patch.object(task_repo, "_FIELDS_ENTRY_LIMIT", 300):
            for _ in range(2):
                self.assertEqual(self.repo.list_task_fields(LINE), [
                    {key: task[key] for key in LINE} for task in self.repo.list_all_tasks()
                ])
            self.assertEqual(self.repo.get_task_fields("large", LINE), {key: self.repo.get_task("large")[key] for key in LINE})
            kept = self.repo._kept_fields()
            self.assertIsNotNone(kept.get(LINE, "small"))
            self.assertIsNone(kept.get(LINE, "large"))
            counted, counting = self._parses()
            with counting:
                self.repo.list_task_fields(LINE)
            self.assertEqual(len(counted), 1, "only the project that is not kept is read again")

    def test_nothing_more_is_kept_once_the_total_is_reached(self):
        for index in range(6):
            self.repo.save_task(f"t{index}", self._big(f"t{index}", 100))
        one = len(self.repo._fields_entry(LINE, 1, task_repo.json.dumps(self._big("t0", 100)))[1])
        with patch.object(task_repo, "_FIELDS_TOTAL_LIMIT", one * 3 + 10):
            listed = self.repo.list_task_fields(LINE)
            kept = self.repo._kept_fields()
            self.assertEqual(sum(kept.get(LINE, f"t{index}") is not None for index in range(6)), 3)
            self.assertLessEqual(kept._held, one * 3 + 10)
            self.assertEqual(self.repo.list_task_fields(LINE), listed)
            self.assertEqual(listed, [{key: task[key] for key in LINE} for task in self.repo.list_all_tasks()])

    def test_what_is_held_is_counted_down_when_a_task_changes_or_goes(self):
        self.repo.save_task("t1", self._big("t1", 400))
        self.repo.save_task("t2", _task("t2"))
        self.repo.list_task_fields(LINE)
        kept = self.repo._kept_fields()
        with_both = kept._held
        self.repo.save_task("t1", _task("t1"))
        self.repo.list_task_fields(LINE)
        self.assertLess(kept._held, with_both)
        self.repo.delete_task("t1")
        self.repo.delete_task("t2")
        self.assertEqual(self.repo.list_task_fields(LINE), [])
        self.assertEqual(kept._held, 0)


if __name__ == "__main__":
    unittest.main()
