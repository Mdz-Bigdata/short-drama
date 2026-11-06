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
                self.assertIn(failure.variable, feedback.VARIABLE_NAMES)
                # The first round always has something to change in the failure's own class.
                self.assertTrue(any(fix.variable == failure.variable for fix in failure.fixes))
                self.assertTrue(all(fix.variable in feedback.VARIABLE_NAMES for fix in failure.fixes))

    def test_the_fight_symptoms_land_in_the_class_to_look_at_first(self):
        for report, category, variable in (
            ("第一下打完后面就越打越少了", "action_dwindle", "action"),
            ("接触点看不清，不知道打没打中", "contact_unclear", "camera"),
            ("两个人各打各的", "fight_disconnected", "action"),
            ("两人左右互换了", "spatial_break", "camera"),
            ("镜头乱切", "jump_cut", "camera"),
            ("两个人身体粘在一起", "body_merge", "reference"),
            ("刀多出一把", "weapon_failure", "reference"),
            ("打得软绵绵没有力量", "weightless_hit", "action"),
            ("后面伤口消失了", "damage_reset", "action"),
            ("首尾帧过渡扭曲", "endframe_warp", "reference"),
            ("光效凭空出现", "vfx_unsourced", "action"),
        ):
            with self.subTest(report):
                plan = feedback.plan_fix(report)
                self.assertEqual(plan.primary.id, category)
                self.assertEqual(plan.variable, variable)


class FixPlanTests(unittest.TestCase):
    def test_the_first_attempt_is_the_fix_itself(self):
        plan = feedback.plan_fix("脸崩了", attempt=1)

        self.assertEqual(plan.attempt, 1)
        self.assertEqual(plan.escalation, "")
        self.assertIn("把第三个人降为虚化、背影或剪影，画面里只留两个清晰人物", plan.steps)
        self.assertIn("面部畸形", plan.negatives)

    def test_a_round_changes_only_its_own_class(self):
        plan = feedback.plan_fix("脸崩了", attempt=1)

        self.assertEqual(plan.variable, "action")
        # The face fix in the reference class waits for a later round instead of riding along.
        self.assertNotIn("给这一镜挂上该角色的设定图作参考图，并重述外形锚点", plan.steps)
        self.assertIn("本轮只改动作，镜头、参考素材保持不变", plan.steps[-1])
        self.assertEqual(plan.as_dict()["variable_name"], "动作")

    def test_a_retry_gives_something_up_inside_the_same_class(self):
        second = feedback.plan_fix("脸崩了", attempt=2)

        self.assertEqual(second.variable, "action")
        self.assertEqual(second.escalation, feedback.ESCALATION["action"][0])
        self.assertIn("第2次重试", " ".join(second.steps))

    def test_two_rounds_without_improvement_turn_to_another_class(self):
        third = feedback.plan_fix("脸崩了", attempt=3)

        self.assertEqual(third.variable, "camera")
        self.assertEqual(third.reconsidered, ["action"])
        self.assertIn("可能分错了变量", third.steps[0])
        self.assertIn("拆成两镜：一镜两人，一镜单人反应", third.steps)
        self.assertEqual(third.escalation, feedback.ESCALATION["camera"][0])
        self.assertEqual(feedback.plan_fix("脸崩了", attempt=4).escalation, feedback.ESCALATION["camera"][1])

    def test_a_round_that_helped_keeps_working_in_its_class(self):
        plan = feedback.plan_fix("脸崩了", attempt=3, rounds=[("action", False), ("action", True)])

        self.assertEqual(plan.variable, "action")
        self.assertEqual(plan.escalation, feedback.ESCALATION["action"][1])

    def test_past_every_class_the_shot_is_out_of_the_models_reach(self):
        last = 1 + feedback.STALL_ROUNDS * (1 + len(feedback.RECONSIDER_ORDER["action"]))
        self.assertFalse(feedback.plan_fix("脸崩了", attempt=last - 1).give_up)
        plan = feedback.plan_fix("脸崩了", attempt=last)

        self.assertTrue(plan.give_up)
        self.assertEqual(plan.variable, "")
        self.assertIn("模型能力边界", " ".join(plan.steps))

    def test_a_second_problem_adds_its_negatives_without_taking_over(self):
        plan = feedback.plan_fix("脸崩了，手也畸形")

        self.assertEqual(plan.primary.id, "face_collapse")
        self.assertEqual([item.id for item in plan.secondary], ["hand_failure"])
        self.assertIn("多指", plan.negatives)


class SoundFailureTests(unittest.TestCase):
    def test_a_wrong_speaker_is_its_own_failure(self):
        plan = feedback.plan_fix("说话人错了，嘴在动的不是林夏")

        self.assertEqual(plan.primary.id, "wrong_speaker")
        steps = " ".join(plan.steps)
        self.assertIn("一镜只留一个说话人", steps)
        self.assertIn("台词前先写说话人名字", steps)
        self.assertIn("说话前先给说话人一个可见动作", steps)

    def test_an_early_or_late_effect_is_bound_to_a_visible_event(self):
        plan = feedback.plan_fix("音效提前了，杯子还没碰到桌子就响")

        self.assertEqual((plan.primary.id, plan.variable), ("sfx_timing", "sound"))
        self.assertIn("绑到一个可见事件", " ".join(plan.steps))
        # Two sound rounds without improvement: the next round cuts actions instead.
        later = feedback.plan_fix("音效提前了", rounds=[("sound", False), ("sound", False)])
        self.assertEqual(later.variable, "action")
        self.assertIn("减少动作", " ".join(later.steps))

    def test_sound_failures_end_by_dubbing_the_line_in_post(self):
        self.assertEqual(feedback.get_failure("lip_sync").variable, "sound")
        self.assertIn("对白移到后期配音", feedback.ESCALATION["sound"][-1])
        last = feedback.plan_fix("串台", rounds=[("sound", False)] * 2 + [("action", False)] * 2)

        self.assertTrue(last.give_up)
        self.assertIn("对白移到后期配音", " ".join(last.steps))
        # Picture failures still give up by changing the expression or the model.
        picture = feedback.plan_fix("脸崩了", rounds=[("action", False)] * 2 + [("camera", False)] * 2 + [("reference", False)] * 2)
        self.assertTrue(picture.give_up)
        self.assertIn("换一个视频模型", " ".join(picture.steps))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.task = {"assets": {}}

    def test_each_report_counts_as_the_next_attempt_on_that_shot(self):
        first = feedback.record(self.task, shot_id=3, result="failed", text="脸崩了", model="seedance2.5")
        second = feedback.record(self.task, shot_id=3, result="failed", text="脸崩了", model="seedance2.5")

        self.assertEqual((first["attempt"], second["attempt"]), (1, 2))
        self.assertEqual(second["plan"]["escalation"], feedback.ESCALATION["action"][0])
        self.assertEqual(self.task["assets"][feedback.LEDGER_KEY]["shots"]["3"][0]["variable"], "action")
        self.assertEqual(self.task["assets"][feedback.LEDGER_KEY]["stats"]["failed"], 2)

    def test_the_ledger_judges_each_round_by_the_report_that_followed_it(self):
        results = []
        for result in ("failed", "failed", "failed", "partial", "failed"):
            written = feedback.record(self.task, shot_id=5, result=result, text="接触点看不清", model="seedance2.5")
            results.append((written["plan"]["variable"], written["plan"]["reconsidered"]))

        # Two camera rounds failed → the third report turns to action; the partial after it means
        # action helped, so the fifth report stays in action and gives up its next rung.
        self.assertEqual(results[:3], [("camera", []), ("camera", []), ("action", ["camera"])])
        self.assertEqual(results[4], ("action", ["camera"]))
        self.assertEqual(written["plan"]["escalation"], feedback.ESCALATION["action"][2])

    def test_a_ledger_written_before_the_classes_still_counts_its_rounds(self):
        self.task["assets"][feedback.LEDGER_KEY] = {"shots": {"9": [
            {"result": "failed", "category": "contact_unclear", "attempt": 1},
            {"result": "failed", "category": "contact_unclear", "attempt": 2},
        ]}}

        written = feedback.record(self.task, shot_id=9, result="failed", text="接触点看不清", model="seedance2.5")

        self.assertEqual(written["plan"]["variable"], "action")

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
        self.assertEqual(second["plan"]["escalation"], feedback.ESCALATION["action"][0])
        self.assertEqual(second["plan"]["variable_name"], "动作")

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
