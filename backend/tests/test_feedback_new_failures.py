# -*- coding: utf-8 -*-
"""The three failure kinds added for faces that flip, eyes that are empty and people who float."""

from __future__ import annotations

import unittest

from app.core import generation_feedback as feedback


class NewFailureTests(unittest.TestCase):
    def test_each_report_is_read_as_its_own_failure_first(self):
        for report, wanted in (
            ("一秒变脸，上一秒还在哭", "face_flip"),
            ("表情突变，没有过渡", "face_flip"),
            ("男主眼神呆滞，一直不眨眼", "dead_eyes"),
            ("人物飘在地面上，脚不沾地", "floating"),
            ("走路像滑步", "floating"),
        ):
            with self.subTest(report=report):
                self.assertEqual(feedback.classify(report)[0].failure.id, wanted)

    def test_a_report_that_names_two_things_keeps_both_in_the_order_they_are_said(self):
        found = [match.failure.id for match in feedback.classify("她的表情一秒变脸")]
        self.assertEqual(found[0], "expression_failure")
        self.assertIn("face_flip", found)

    def test_older_reports_still_land_where_they_did(self):
        self.assertEqual(feedback.classify("表情僵硬，面瘫")[0].failure.id, "expression_failure")
        self.assertEqual(feedback.classify("脸崩了，五官歪")[0].failure.id, "face_collapse")
        self.assertEqual(feedback.classify("这一拳软绵绵，轻飘飘")[0].failure.id, "weightless_hit")

    def test_each_new_failure_offers_an_action_fix_and_a_camera_fix(self):
        for failure_id in ("face_flip", "dead_eyes", "floating"):
            failure = feedback.get_failure(failure_id)
            self.assertIsNotNone(failure)
            self.assertEqual({fix.variable for fix in failure.fixes}, {"action", "camera"})
            self.assertTrue(failure.prevention)


if __name__ == "__main__":
    unittest.main()
