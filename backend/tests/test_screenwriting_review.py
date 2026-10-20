"""Episodes are confirmed by fingerprint, violating drafts stay quarantined until repaired, and the gate is soft."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core.screenwriting import ledger_ops, review
from app.core.screenwriting.engine import RepairNotImproved
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from main import app
from tests.test_screenwriting_engine import FakeModel, _engine, _scene
from tests.test_screenwriting_pipeline import _MINIATURE_ENVIRONMENT, _Gateway, _run_stage_two, _service, _task
from tests.test_workflow_guide import task_at

LONG_LINE = "字" * 120  # ~24 s of speech, more than the 15 s longest clip


def setUpModule():
    # The fake model writes miniature episodes; the service reads its episode frame from the environment.
    _MINIATURE_ENVIRONMENT.start()


def tearDownModule():
    _MINIATURE_ENVIRONMENT.stop()


def _draft_plan(attempt: int, _prompt: str) -> str:
    return json.dumps({"title": "对峙", "scenes": [_scene(1, 1, text=LONG_LINE), _scene(1, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)


def _clean_plan(attempt: int, _prompt: str) -> str:
    return json.dumps({"title": "对峙", "scenes": [_scene(1, 1), _scene(1, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)


class ReviewStateTests(unittest.TestCase):
    def _written(self):
        return _engine(FakeModel()).write(title="暗室回声", director_plan="大纲", episode_count=2)

    def test_an_episode_is_pending_until_confirmed_and_changed_once_its_plan_moves(self):
        state = self._written()
        self.assertEqual(review.status_of(state, 1)["status"], "pending")

        confirmed = review.confirm(state, 1, by="writer-user")
        status = review.status_of(confirmed, 1)
        self.assertEqual((status["status"], status["confirmed_by"]), ("confirmed", "writer-user"))
        self.assertEqual(status["confirmed_revision"], confirmed["episodes"]["1"]["plan_revision"])

        confirmed["episodes"]["1"]["plan_revision"] = "sha256-v1:elsewhere"
        self.assertEqual(review.status_of(confirmed, 1)["status"], "changed")
        self.assertEqual(review.status_of(review.reopen(confirmed, 1), 1)["status"], "pending")
        with self.assertRaisesRegex(review.ReviewError, "没有确认记录"):
            review.reopen(state, 1)
        with self.assertRaisesRegex(review.ReviewError, "尚未写出"):
            review.confirm(state, 9)

    def test_a_quarantined_draft_cannot_be_confirmed_and_the_summary_names_it(self):
        state = self._written()
        state["episodes"]["2"][review.DRAFT_KEY] = review.quarantine(["第 2 集：口播约 24 秒超过最长档 15 秒"], origin="model", attempts=3)
        self.assertEqual(review.status_of(state, 2)["status"], "draft")
        with self.assertRaisesRegex(review.ReviewError, "带违约的草稿"):
            review.confirm(state, 2)

        view = review.summary(review.confirm(state, 1))
        self.assertEqual((view["confirmed"], view["pending"], view["drafts"], view["all_confirmed"]), ([1], [], [2], False))
        self.assertEqual(view["message"], "第 2 集仍是带违约的草稿")
        self.assertEqual(review.summary(review.confirm(review.confirm(state, 1), 1))["message"], "第 2 集仍是带违约的草稿")

    def test_confirmations_follow_a_ledger_renumbering_and_drop_with_a_deleted_episode(self):
        state = review.confirm(review.confirm(self._written(), 1), 2)
        state["source_kind"] = "outline"
        moved = ledger_ops.create_episode(state, title="序章", after=0).state
        self.assertEqual(set(moved[review.REVIEWS_KEY]), {"2", "3"})
        self.assertEqual(review.status_of(moved, 3)["status"], "confirmed")
        gone = ledger_ops.delete_episode(state, 1).state
        self.assertEqual(set(gone[review.REVIEWS_KEY]), {"1"})
        self.assertEqual(review.status_of(gone, 1)["status"], "confirmed")


class EngineQuarantineTests(unittest.TestCase):
    def test_a_plan_that_never_passes_is_kept_as_a_quarantined_draft(self):
        model = FakeModel()
        model.plan_overrides[1] = _draft_plan
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)

        draft = review.draft_of(state["episodes"]["1"])
        self.assertEqual((draft["origin"], draft["attempts"]), ("model", 3))
        self.assertTrue(any("超过" in reason for reason in draft["reasons"]))
        self.assertEqual(review.status_of(state, 1)["status"], "draft")

    def test_a_repair_that_passes_lifts_the_quarantine_and_asks_with_the_reasons(self):
        model = FakeModel()
        model.plan_overrides[1] = _draft_plan
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        model.plan_overrides[1] = _clean_plan

        repaired, outcome = engine.repair_episode(state, 1)

        self.assertTrue(outcome["repaired"])
        self.assertEqual(outcome["remaining"], [])
        self.assertIsNone(review.draft_of(repaired["episodes"]["1"]))
        self.assertEqual(review.status_of(repaired, 1)["status"], "pending")
        prompt = model.calls[-3]["prompt"] if "修复上一版草稿" in model.calls[-3]["prompt"] else next(c["prompt"] for c in model.calls if "修复上一版草稿" in c["prompt"])
        self.assertIn("超过", prompt)
        self.assertIn(LONG_LINE[:20], prompt)
        self.assertEqual(review.draft_of(state["episodes"]["1"])["origin"], "model", "the input state is untouched")

    def test_a_repair_that_is_no_better_is_refused_and_the_draft_kept(self):
        model = FakeModel()
        model.plan_overrides[1] = _draft_plan
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        with self.assertRaises(RepairNotImproved):
            engine.repair_episode(state, 1)
        with self.assertRaisesRegex(Exception, "不是带违约的草稿"):
            engine.repair_episode(_engine(FakeModel()).write(title="t", director_plan="大纲", episode_count=1), 1)

    def test_a_human_edit_that_breaks_a_soft_rule_is_a_draft_and_a_clean_edit_lifts_it(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = [dict(scene) for scene in state["episodes"]["1"]["plan"]["scenes"]]
        scenes[0]["utterances"] = [{"kind": "dialogue", "speaker": "林夏", "text": LONG_LINE}]
        edited, _ = engine.replace_plan(state, 1, scenes)
        self.assertEqual(review.draft_of(edited["episodes"]["1"])["origin"], "edit")

        scenes[0]["utterances"] = [{"kind": "dialogue", "speaker": "林夏", "text": "你到底瞒了什么？"}]
        clean, _ = engine.replace_plan(edited, 1, scenes)
        self.assertIsNone(review.draft_of(clean["episodes"]["1"]))


class ReviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("rv-1", _task("rv-1"))
        self.gateway = _Gateway()
        self.gateway.model.plan_overrides[2] = lambda attempt, prompt: json.dumps(
            {"title": "反击", "scenes": [_scene(2, 1, text=LONG_LINE), _scene(2, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)
        self.service = _service(self.gateway, self.repo)
        _run_stage_two(self.service, "rv-1")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "writer-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("writer-user")})
        self.addCleanup(self.client.close)
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)

    def test_state_reports_review_status_and_confirmation_binds_to_the_plan(self):
        with patch.object(drama_api, "service", self.service):
            before = self.client.get("/api/drama/rv-1/screenwriting").json()
            self.assertEqual([e["review"]["status"] for e in before["episodes"]], ["pending", "draft"])
            self.assertEqual(before["reviewSummary"]["drafts"], [2])
            self.assertIn("第 2 集仍是带违约的草稿", before["reviewSummary"]["message"])

            confirmed = self.client.post("/api/drama/rv-1/screenwriting/episodes/1/review", json={"action": "confirm"})
            refused = self.client.post("/api/drama/rv-1/screenwriting/episodes/2/review", json={"action": "confirm"})
            after = self.client.get("/api/drama/rv-1/screenwriting/review").json()

        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["review"]["status"], "confirmed")
        self.assertEqual(confirmed.json()["review"]["confirmedBy"], "writer-user")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual((after["confirmed"], after["drafts"]), ([1], [2]))

    def test_editing_a_confirmed_episode_puts_it_back_to_changed(self):
        with patch.object(drama_api, "service", self.service):
            self.client.post("/api/drama/rv-1/screenwriting/episodes/1/review", json={"action": "confirm"})
            episode = self.client.get("/api/drama/rv-1/screenwriting/episodes/1").json()
            patched = self.client.patch(
                "/api/drama/rv-1/screenwriting/episodes/1/plan",
                json={"baseRevision": episode["planRevision"], "operations": [{"op": "update", "id": "E1S01", "fields": {"scene_description": "林夏把门反锁。"}}]},
            )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["review"]["status"], "changed")

    def test_repair_rewrites_the_draft_when_the_model_does_better_and_keeps_it_otherwise(self):
        with patch.object(drama_api, "service", self.service):
            unchanged = self.client.post("/api/drama/rv-1/screenwriting/episodes/2/repair", json={})
            self.assertEqual(unchanged.status_code, 200, unchanged.text)
            self.assertEqual(unchanged.json()["repair"]["improved"], False)
            self.assertEqual(unchanged.json()["review"]["status"], "draft")

            self.gateway.model.plan_overrides[2] = lambda attempt, prompt: json.dumps(
                {"title": "反击", "scenes": [_scene(2, 1), _scene(2, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)
            repaired = self.client.post("/api/drama/rv-1/screenwriting/episodes/2/repair", json={})
            not_a_draft = self.client.post("/api/drama/rv-1/screenwriting/episodes/1/repair", json={})

        self.assertEqual(repaired.status_code, 200, repaired.text)
        self.assertEqual(repaired.json()["repair"]["repaired"], True)
        self.assertEqual(repaired.json()["review"]["status"], "pending")
        self.assertIsNone(review.draft_of(screenwriting.state_of(self.repo.get_task("rv-1"))["episodes"]["2"]))
        self.assertEqual(not_a_draft.status_code, 422)

    def test_stage_three_starts_anyway_but_records_what_the_gate_saw(self):
        task = self.repo.get_task("rv-1")
        self.service._assert_stage_prerequisites(task, 3)
        record = task["assets"][review.GATE_KEY]
        self.assertTrue(record["soft"])
        self.assertFalse(record["passed"])
        self.assertEqual((record["pending"], record["drafts"]), ([1], [2]))
        self.assertIn("第 1 集尚未审核确认", record["message"])


class WorkflowHintTests(unittest.TestCase):
    def test_the_next_step_hint_names_unconfirmed_episodes_without_blocking(self):
        task = task_at(2)
        state = _engine(FakeModel()).write(title="暗室回声", director_plan="大纲", episode_count=2)
        task["assets"]["2_screenwriting"] = review.confirm(state, 1)
        service = DramaService.__new__(DramaService)
        snapshot = service.workflow_snapshot(task)
        self.assertIn("第 2 集尚未审核确认", snapshot["hint"])
        self.assertIn("不拦截", snapshot["hint"])
        self.assertEqual(snapshot["next_stage"], 3)

        task["assets"]["2_screenwriting"] = review.confirm(task["assets"]["2_screenwriting"], 2)
        self.assertNotIn("审核", service.workflow_snapshot(task)["hint"])


if __name__ == "__main__":
    unittest.main()
