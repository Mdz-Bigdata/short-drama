"""The episode ledger can be cut by hand, replanned as a candidate, and every number follows."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.core.screenwriting import ledger_ops
from app.api.auth_api import auth_service, get_current_user
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from main import app
from tests.test_screenwriting_engine import FakeModel, _engine
from tests.test_screenwriting_pipeline import _Gateway, _run_stage_two, _service, _task

NOVEL = (
    "林夏推开实验室的门，冷白灯光刺得她眯起眼。她在抽屉里找到了录音笔。"
    "周教授站在她身后，声音低沉：现在回头还来得及。林夏握紧录音笔，没有回头。"
)


def _state():
    """Two cut episodes written from the novel, as the engine leaves them."""
    return _engine(FakeModel()).write(title="暗室回声", director_plan="", episode_count=2, source_text=NOVEL)


def _spans(state):
    return [(e["episode"], e["source_range"]["start"], e["source_range"]["end"]) for e in state["ledger"] if e.get("source_range")]


class ManualCutTests(unittest.TestCase):
    def test_split_puts_the_second_half_right_after_and_renumbers_what_follows(self):
        state = _state()
        first_end = state["ledger"][0]["source_range"]["end"]
        cut = NOVEL.index("周教授")
        change = ledger_ops.split_episode(state, 2, cut, "回头")

        self.assertEqual(change.discarded, [2])
        self.assertEqual(change.created, [3])
        self.assertEqual(_spans(change.state), [(1, 0, first_end), (2, first_end, cut), (3, cut, len(NOVEL))])
        self.assertEqual(change.state["ledger"][2]["title"], "回头")
        self.assertEqual(change.state["episode_count"], 3)
        self.assertNotIn("2", change.state["episodes"])
        self.assertIn("1", change.state["episodes"])

    def test_split_outside_the_episode_or_on_an_own_source_episode_is_refused(self):
        state = _state()
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "本集原文之内"):
            ledger_ops.split_episode(state, 2, 1)
        own = ledger_ops.create_episode(state, title="番外", text="番外原文。").state
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "不能按位置拆分"):
            ledger_ops.split_episode(own, 3, 2)

    def test_moving_a_boundary_shifts_both_neighbours_and_drops_their_written_work(self):
        state = _state()
        new_end = NOVEL.index("周教授")
        change = ledger_ops.move_boundary(state, 1, new_end)

        self.assertEqual(sorted(change.discarded), [1, 2])
        self.assertEqual(_spans(change.state), [(1, 0, new_end), (2, new_end, len(NOVEL))])
        self.assertEqual(change.state["episodes"], {})

    def test_merging_with_the_next_episode_leaves_one_span_and_renumbers(self):
        state = ledger_ops.split_episode(_state(), 2, NOVEL.index("周教授")).state
        change = ledger_ops.merge_with_next(state, 2)

        self.assertEqual(len(change.state["ledger"]), 2)
        self.assertEqual(_spans(change.state)[1], (2, state["ledger"][1]["source_range"]["start"], len(NOVEL)))
        self.assertEqual(change.renumbered, {1: 1, 2: 2})
        self.assertIn("1", change.state["episodes"])

    def test_the_source_left_unsplit_is_reported_and_can_be_cut_into_an_episode(self):
        state = _state()
        gap_start = NOVEL.index("周教授")
        state["ledger"][1]["source_range"]["end"] = gap_start
        self.assertEqual(ledger_ops.unsplit_spans(state), [{"start": gap_start, "end": len(NOVEL)}])

        change = ledger_ops.cut_unsplit(state, gap_start, len(NOVEL), "尾声")
        self.assertEqual(change.created, [3])
        self.assertEqual(ledger_ops.unsplit_spans(change.state), [])
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "未切分"):
            ledger_ops.cut_unsplit(state, 0, 5)

    def test_clear_after_keeps_the_episodes_up_to_the_point_and_frees_the_rest_of_the_source(self):
        state = _state()
        change = ledger_ops.clear_after(state, 1)

        self.assertEqual([e["episode"] for e in change.state["ledger"]], [1])
        self.assertEqual(change.discarded, [2])
        self.assertEqual(ledger_ops.unsplit_spans(change.state), [{"start": state["ledger"][0]["source_range"]["end"], "end": len(NOVEL)}])


class CreateMoveDeleteTests(unittest.TestCase):
    def test_a_created_episode_takes_its_place_and_scene_ids_follow_the_renumbering(self):
        state = _state()
        change = ledger_ops.create_episode(state, title="序章", text="多年以前，实验室还亮着灯。", source_kind="novel", after=0)

        self.assertEqual([(e["episode"], e["source_origin"]) for e in change.state["ledger"]], [(1, "own"), (2, "cut"), (3, "cut")])
        self.assertEqual(change.created, [1])
        self.assertEqual(change.renumbered, {3: 1, 1: 2, 2: 3})
        self.assertEqual(set(change.state["episodes"]), {"2", "3"})
        self.assertTrue(all(s["scene_id"].startswith("E3S") for s in change.state["episodes"]["3"]["script"]["scenes"]))
        self.assertEqual(change.state["episodes"]["3"]["script"]["episode"], 3)
        self.assertEqual(change.discarded, [])

    def test_a_cut_episode_cannot_leave_source_order_but_an_own_episode_can_move_anywhere(self):
        state = ledger_ops.create_episode(_state(), title="番外", text="番外。").state
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "原文顺序"):
            ledger_ops.move_episode(state, 2, after=0)
        moved = ledger_ops.move_episode(state, 3, after=1)
        self.assertEqual([e["title"] for e in moved.state["ledger"]][1], "番外")
        self.assertEqual(moved.renumbered, {1: 1, 3: 2, 2: 3})

    def test_deleting_an_episode_reports_its_lost_work_and_frees_its_source(self):
        state = _state()
        self.assertEqual(ledger_ops.impact(state, [2])[0]["scenes"], 2)
        change = ledger_ops.delete_episode(state, 1)

        self.assertEqual(change.discarded, [1])
        self.assertEqual([e["episode"] for e in change.state["ledger"]], [1])
        self.assertEqual(ledger_ops.unsplit_spans(change.state)[0]["start"], 0)
        self.assertEqual(set(change.state["episodes"]), {"1"})

    def test_an_own_source_text_can_be_replaced_and_its_episode_must_be_rewritten(self):
        state = ledger_ops.create_episode(_state(), title="番外", text="番外。").state
        state["episodes"]["3"] = {"episode": 3, "script": {"episode": 3, "scenes": [{"scene_id": "E3S01"}]}}
        change = ledger_ops.update_own_source(state, 3, text="新的番外原文。")
        self.assertEqual(change.discarded, [3])
        self.assertEqual(change.state["ledger"][2]["source_text"], "新的番外原文。")
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "自带原文"):
            ledger_ops.update_own_source(state, 1, text="x")


class CandidateTests(unittest.TestCase):
    def test_a_candidate_is_compared_against_the_old_cut_and_adopted_in_place(self):
        state = _state()
        start = ledger_ops.replan_start(state, 2)
        mid = NOVEL.index("林夏握紧")
        entries = [
            {"title": "新二", "hook": "h", "source_range": {"start": start, "end": mid}},
            {"title": "新三", "hook": "h", "source_range": {"start": mid, "end": len(NOVEL)}},
        ]
        stored = ledger_ops.store_candidate(state, 2, entries)
        comparison = ledger_ops.compare_candidate(stored)

        self.assertTrue(comparison["adoptable"])
        self.assertEqual((comparison["old_count"], comparison["new_count"]), (1, 2))
        self.assertEqual([row["relation"] for row in comparison["entries"]], ["overlaps", "overlaps"])
        self.assertEqual(comparison["replaced_written"], [2])

        kept = ledger_ops.adopt_candidate(stored)
        self.assertEqual([(e["episode"], e["source_origin"], e["ledger_status"]) for e in kept.state["ledger"]],
                         [(1, "cut", kept.state["ledger"][0]["ledger_status"]), (2, "cut", "planned"), (3, "cut", "planned"), (4, "none", "stale")])
        self.assertEqual(kept.created, [2, 3])
        self.assertEqual(kept.discarded, [])
        self.assertIn("4", kept.state["episodes"])
        self.assertNotIn(ledger_ops.CANDIDATE_KEY, kept.state)

        deleted = ledger_ops.adopt_candidate(stored, delete_replaced=True)
        self.assertEqual(len(deleted.state["ledger"]), 3)
        self.assertEqual(deleted.discarded, [2])

    def test_a_candidate_dies_with_the_layout_it_was_planned_against(self):
        state = _state()
        stored = ledger_ops.store_candidate(state, 2, [{"title": "x", "source_range": state["ledger"][1]["source_range"]}])
        self.assertEqual(ledger_ops.compare_candidate(stored)["entries"][0]["relation"], "same")
        changed = ledger_ops.move_boundary(stored, 1, NOVEL.index("周教授")).state
        self.assertNotIn(ledger_ops.CANDIDATE_KEY, changed)
        stale = dict(stored, source_text=NOVEL + "尾声。")
        self.assertFalse(ledger_ops.compare_candidate(stale)["adoptable"])
        with self.assertRaisesRegex(ledger_ops.LedgerOperationError, "不能采纳"):
            ledger_ops.adopt_candidate(stale)
        self.assertNotIn(ledger_ops.CANDIDATE_KEY, ledger_ops.discard_candidate(stored))

    def test_describe_lists_entries_with_their_length_and_status(self):
        state = _state()
        view = ledger_ops.describe(state)
        self.assertEqual([e["episode"] for e in view["entries"]], [1, 2])
        self.assertTrue(all(e["written"] and e["origin"] == "cut" and e["units"] > 0 for e in view["entries"]))
        self.assertEqual(view["unsplit"], [])
        self.assertIsNone(view["candidate"])
        self.assertEqual(view["source_length"], len(NOVEL))


class LedgerServiceTests(unittest.TestCase):
    """The operations through the service: unwritten episodes are written, downstream is guarded, the API answers."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = _task("lg-1")
        task["assets"]["2_documents"] = [{"name": "story.txt", "role": "source", "content": NOVEL, "order": 0}]
        self.repo.save_task("lg-1", task)
        self.gateway = _Gateway()
        self.service = _service(self.gateway, self.repo)
        _run_stage_two(self.service, "lg-1")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "writer-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("writer-user")})
        self.addCleanup(self.client.close)
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)

    def _state(self):
        return screenwriting.state_of(self.repo.get_task("lg-1"))

    def test_the_fixture_was_cut_from_the_library_source(self):
        state = self._state()
        self.assertEqual(state["source_kind"], "novel")
        self.assertEqual([e["source_origin"] for e in state["ledger"]], ["cut", "cut"])

    def test_a_split_must_name_the_written_episode_it_discards_then_writes_both_halves(self):
        cut = NOVEL.index("周教授")
        with patch.object(drama_api, "service", self.service):
            refused = self.client.post("/api/drama/lg-1/screenwriting/ledger/ops", json={"operation": "split", "episode": 2, "offset": cut})
            accepted = self.client.post("/api/drama/lg-1/screenwriting/ledger/ops",
                                        json={"operation": "split", "episode": 2, "offset": cut, "confirm_discard": [2], "confirm_invalidate": True})
            ledger = self.client.get("/api/drama/lg-1/screenwriting/ledger")

        self.assertEqual(refused.status_code, 409)
        self.assertIn("第 2 集", refused.json()["detail"])
        self.assertEqual(accepted.status_code, 200, accepted.text)
        body = accepted.json()
        self.assertEqual(body["created"], [3])
        self.assertEqual([e["episode"] for e in body["entries"]], [1, 2, 3])
        self.assertTrue(all(e["written"] for e in body["entries"]))
        task = self.repo.get_task("lg-1")
        self.assertEqual(task["config"]["episode_count"], 3)
        self.assertIn("第3集", task["assets"]["2"])
        self.assertEqual([e["episode"] for e in ledger.json()["entries"]], [1, 2, 3])

    def test_an_impossible_operation_is_a_422_and_a_running_project_a_409(self):
        with patch.object(drama_api, "service", self.service):
            bad = self.client.post("/api/drama/lg-1/screenwriting/ledger/ops", json={"operation": "split", "episode": 2, "offset": 0})
            self.assertEqual(bad.status_code, 422)
            task = self.repo.get_task("lg-1")
            task["status"] = "running"
            task["stage_progress"] = {"stage": 3, "status": "running"}
            self.repo.save_task("lg-1", task)
            busy = self.client.post("/api/drama/lg-1/screenwriting/ledger/ops", json={"operation": "delete", "episode": 2, "confirm_discard": [2]})
        self.assertEqual(busy.status_code, 409)

    def test_a_replan_is_a_candidate_until_adopted_and_adoption_writes_the_new_episodes(self):
        with patch.object(drama_api, "service", self.service):
            planned = self.client.post("/api/drama/lg-1/screenwriting/replan", json={"from_episode": 2})
            self.assertEqual(planned.status_code, 200, planned.text)
            candidate = planned.json()["candidate"]
            self.assertEqual(candidate["from_episode"], 2)
            self.assertTrue(candidate["adoptable"])
            self.assertEqual(candidate["old_count"], 1)
            self.assertGreaterEqual(candidate["new_count"], 1)
            self.assertEqual([e["episode"] for e in self._state()["ledger"]], [1, 2], "the ledger waits for adoption")
            again = self.client.post("/api/drama/lg-1/screenwriting/replan", json={"from_episode": 2})
            self.assertEqual(again.status_code, 409)

            adopted = self.client.post("/api/drama/lg-1/screenwriting/replan/adopt",
                                       json={"delete_replaced": True, "confirm_discard": [2], "confirm_invalidate": True})
            self.assertEqual(adopted.status_code, 200, adopted.text)
        body = adopted.json()
        self.assertIsNone(body["candidate"])
        self.assertEqual(len(body["entries"]), 1 + candidate["new_count"])
        self.assertTrue(all(e["written"] for e in body["entries"]))
        self.assertEqual(self.repo.get_task("lg-1")["config"]["episode_count"], len(body["entries"]))

    def test_a_candidate_can_be_discarded(self):
        with patch.object(drama_api, "service", self.service):
            self.client.post("/api/drama/lg-1/screenwriting/replan", json={"from_episode": 1})
            dropped = self.client.post("/api/drama/lg-1/screenwriting/replan/discard")
        self.assertEqual(dropped.status_code, 200)
        self.assertIsNone(dropped.json()["candidate"])
        self.assertNotIn(ledger_ops.CANDIDATE_KEY, self._state())


if __name__ == "__main__":
    unittest.main()
