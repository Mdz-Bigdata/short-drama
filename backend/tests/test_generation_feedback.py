# -*- coding: utf-8 -*-
"""The loop that closes after a shot comes back wrong.

A person says "脸崩了"; the project has to turn that into a category, a fix that gives
something up when the last attempt already failed, and a memory that keeps the same
mistake from being made on the next shot.
"""

import unittest

from app.core import generation_feedback as feedback


class ClassificationTests(unittest.TestCase):
    def test_a_plain_sentence_becomes_a_category(self):
        matches = feedback.classify("镜3脸崩了")

        self.assertEqual(matches[0].failure.id, "face_collapse")
        self.assertEqual(matches[0].matched, "脸崩")

    def test_several_problems_are_ordered_as_they_are_said(self):
        matches = feedback.classify("手指是六根，而且脸崩了")

        self.assertEqual([match.failure.id for match in matches][:2], ["hand_failure", "face_collapse"])

    def test_a_report_that_names_nothing_known_gets_no_plan(self):
        self.assertEqual(feedback.classify("总觉得差点意思"), [])
        self.assertIsNone(feedback.plan_fix("总觉得差点意思"))

    def test_an_explicit_category_wins_over_the_words(self):
        plan = feedback.plan_fix("随便写的", category="colour_drift")

        self.assertEqual(plan.primary.id, "colour_drift")

    def test_every_failure_is_a_complete_entry(self):
        for failure in feedback.FAILURES:
            with self.subTest(failure.id):
                self.assertTrue(failure.triggers and failure.diagnosis)
                self.assertGreaterEqual(len(failure.fixes), 2)
                self.assertTrue(failure.prevention)


class FixPlanTests(unittest.TestCase):
    def test_the_first_attempt_is_the_fix_itself(self):
        plan = feedback.plan_fix("脸崩了", attempt=1)

        self.assertEqual(plan.attempt, 1)
        self.assertEqual(plan.escalation, "")
        self.assertIn("把第三个人降为虚化、背影或剪影，画面里只留两个清晰人物", plan.steps)
        self.assertIn("面部畸形", plan.negatives)

    def test_every_retry_gives_something_up_in_the_same_order(self):
        second = feedback.plan_fix("脸崩了", attempt=2)
        third = feedback.plan_fix("脸崩了", attempt=3)

        self.assertEqual(second.escalation, feedback.ESCALATION[0])
        self.assertEqual(third.escalation, feedback.ESCALATION[1])
        self.assertIn("第3次重试", " ".join(third.steps))

    def test_past_the_last_cut_the_shot_is_out_of_the_models_reach(self):
        plan = feedback.plan_fix("脸崩了", attempt=len(feedback.ESCALATION) + 1)

        self.assertTrue(plan.give_up)
        self.assertIn("模型能力边界", " ".join(plan.steps))

    def test_a_second_problem_adds_its_negatives_without_taking_over(self):
        plan = feedback.plan_fix("脸崩了，手也畸形")

        self.assertEqual(plan.primary.id, "face_collapse")
        self.assertEqual([item.id for item in plan.secondary], ["hand_failure"])
        self.assertIn("多指", plan.negatives)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.task = {"assets": {}}

    def test_each_report_counts_as_the_next_attempt_on_that_shot(self):
        first = feedback.record(self.task, shot_id=3, result="failed", text="脸崩了", model="seedance2.5")
        second = feedback.record(self.task, shot_id=3, result="failed", text="脸崩了", model="seedance2.5")

        self.assertEqual((first["attempt"], second["attempt"]), (1, 2))
        self.assertEqual(second["plan"]["escalation"], feedback.ESCALATION[0])
        self.assertEqual(self.task["assets"][feedback.LEDGER_KEY]["stats"]["failed"], 2)

    def test_the_same_failure_twice_becomes_that_models_weakness(self):
        for _ in range(feedback.PROMOTE_AFTER):
            feedback.record(self.task, shot_id=1, result="failed", text="手指畸形", model="seedance2.5")

        weak = feedback.weaknesses(self.task, "seedance2.5")
        self.assertEqual([failure.id for failure in weak], ["hand_failure"])
        self.assertTrue(any("手部" in note for note in feedback.preventive_notes(self.task, "seedance2.5")))
        self.assertIn("多指", feedback.preventive_negatives(self.task, "seedance2.5"))
        # Another model on the same project is not tarred with it.
        self.assertEqual(feedback.weaknesses(self.task, "kling-2.6"), [])

    def test_one_failure_is_not_yet_a_weakness(self):
        feedback.record(self.task, shot_id=1, result="failed", text="手指畸形", model="seedance2.5")

        self.assertEqual(feedback.weaknesses(self.task, "seedance2.5"), [])

    def test_a_fix_that_worked_twice_becomes_a_project_pattern(self):
        for shot in (1, 2):
            feedback.record(
                self.task, shot_id=shot, result="success", model="seedance2.5", applied_fix="第三人降为虚化",
            )

        notes = feedback.preventive_notes(self.task, "seedance2.5")
        self.assertTrue(any("已验证有效：第三人降为虚化" in note for note in notes))
        self.assertEqual(feedback.summary(self.task)["patterns"][0]["hits"], 2)

    def test_a_success_needs_no_fix_plan(self):
        written = feedback.record(self.task, shot_id=4, result="success", model="seedance2.5")

        self.assertIsNone(written["plan"])

    def test_the_summary_says_what_breaks_most(self):
        feedback.record(self.task, shot_id=1, result="failed", text="脸崩了", model="seedance2.5")
        feedback.record(self.task, shot_id=2, result="failed", text="脸崩了", model="seedance2.5")
        feedback.record(self.task, shot_id=3, result="failed", text="穿模了", model="seedance2.5")

        report = feedback.summary(self.task)

        self.assertEqual(report["top_failures"][0], {"category": "face_collapse", "name": "脸崩 / 换脸", "count": 2})
        self.assertEqual(report["stats"]["reports"], 3)
        self.assertEqual(report["shots"]["1"]["attempts"], 1)
        self.assertIn("face_collapse", [item["category"] for item in report["model_profiles"]["seedance2.5"]["weaknesses"]])

    def test_a_shot_history_does_not_grow_without_bound(self):
        for _ in range(feedback.MAX_HISTORY_PER_SHOT + 5):
            feedback.record(self.task, shot_id=7, result="failed", text="脸崩了", model="seedance2.5")

        self.assertEqual(len(self.task["assets"][feedback.LEDGER_KEY]["shots"]["7"]), feedback.MAX_HISTORY_PER_SHOT)


class StageFiveWiringTests(unittest.TestCase):
    def test_stage_five_designs_around_what_the_model_already_failed_at(self):
        from pathlib import Path

        import app.service.drama_service as service

        source = Path(service.__file__).read_text(encoding="utf-8")

        for marker in (
            "generation_feedback.preventive_notes(task",
            "generation_feedback.preventive_negatives(task",
            "*learned_negatives,",
            'f"已知弱点规避：{note}" for note in learned_notes',
        ):
            self.assertIn(marker, source, f"第5阶段预防性加固接线点丢失：{marker}")


if __name__ == "__main__":
    unittest.main()


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from app.api import drama_api
        from app.api.auth_api import get_current_user
        from app.repository.task_repo import TaskRepository
        from main import app

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        drama_api.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "qc-user", "role": "user"}
        self.addCleanup(app.dependency_overrides.clear)

        from fastapi.testclient import TestClient

        self.client = TestClient(app)
        self.service = drama_api.service
        self.task_id = "qc-task"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "qc-user", "current_stage": 5, "status": "idle",
            "config": {"title_suggestion": "暗室回声", "video_model": "seedance2.5"},
            "assets": {}, "logs": {}, "episodes": [],
        })

    def _report(self, **body):
        return self.client.post(f"/api/drama/{self.task_id}/shots/3/feedback", json=body)

    def test_a_report_comes_back_with_the_fix_for_the_next_attempt(self):
        response = self._report(result="failed", text="脸崩了，五官歪")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan"]["category"], "face_collapse")
        self.assertEqual(payload["attempt"], 1)
        self.assertTrue(payload["plan"]["steps"])
        self.assertEqual(payload["summary"]["stats"]["failed"], 1)

    def test_the_second_report_on_the_same_shot_gives_something_up(self):
        self._report(result="failed", text="脸崩了")
        second = self._report(result="failed", text="脸崩了").json()

        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["plan"]["escalation"], feedback.ESCALATION[0])

    def test_the_ledger_endpoint_carries_the_weakness_and_its_prevention(self):
        self._report(result="failed", text="手指畸形")
        self._report(result="failed", text="手指畸形")

        payload = self.client.get(f"/api/drama/{self.task_id}/feedback").json()

        weaknesses = payload["summary"]["model_profiles"]["seedance2.5"]["weaknesses"]
        self.assertEqual([item["category"] for item in weaknesses], ["hand_failure"])
        self.assertTrue(any("手部" in note for note in payload["preventive_notes"]))
        self.assertTrue(any(item["id"] == "hand_failure" for item in payload["catalog"]))

    def test_a_bad_result_value_is_refused_and_a_missing_task_is_a_404(self):
        self.assertEqual(self._report(result="maybe", text="脸崩了").status_code, 422)
        self.assertEqual(
            self.client.post("/api/drama/no-such-task/shots/1/feedback", json={"result": "failed", "text": "脸崩了"}).status_code,
            404,
        )
