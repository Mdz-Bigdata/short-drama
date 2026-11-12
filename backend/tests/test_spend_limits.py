# -*- coding: utf-8 -*-
"""预算上限与每镜尝试上限：每提交一次视频前过闸，到了就停并说清楚停在哪。"""

import unittest
from unittest.mock import patch

from app.core import spend_limits


def _quote(model, media, units):
    return {"priced": True, "currency": "CNY", "cost": 0.5 * units["seconds"]}


class GuardTests(unittest.TestCase):
    def test_the_run_stops_before_the_submission_that_would_go_over_budget(self):
        guard = spend_limits.RunGuard({"video_budget_cap": 10, "video_model": "MiniMax-H3"})
        with patch("app.core.usage_ledger.estimate", side_effect=_quote):
            guard.admit(1, earlier_attempts=0, seconds=11, resolution="768p", label="E1S06")
            with self.assertRaises(spend_limits.LimitReached) as stopped:
                guard.admit(2, earlier_attempts=0, seconds=11, resolution="768p", label="E1S07")
        self.assertIn("E1S07", str(stopped.exception))
        self.assertIn("5.50", str(stopped.exception), "says how far the budget already went")
        self.assertEqual(guard.spent, 5.5, "the refused submission is not charged")

    def test_a_shot_at_its_attempt_cap_is_not_submitted_again_across_runs(self):
        guard = spend_limits.RunGuard({"video_max_attempts": 3})
        with patch("app.core.usage_ledger.estimate", side_effect=_quote):
            guard.admit(5, earlier_attempts=2, seconds=5, resolution=None, label="E1S02")
            with self.assertRaises(spend_limits.LimitReached) as stopped:
                guard.admit(5, earlier_attempts=2, seconds=5, resolution=None, label="E1S02")
        self.assertIn("回首帧", str(stopped.exception), "points at the upstream fix, not at clicking again")
        self.assertEqual(guard.tried(5, 2), 3)

    def test_no_limits_means_no_stop_and_usd_prices_are_converted(self):
        guard = spend_limits.RunGuard({})
        with patch("app.core.usage_ledger.estimate", side_effect=_quote):
            for _ in range(30):
                guard.admit(1, earlier_attempts=0, seconds=10, resolution=None, label="x")
        with patch("app.core.usage_ledger.estimate", return_value={"priced": True, "currency": "USD", "cost": 1.0}):
            self.assertAlmostEqual(spend_limits.estimate_cny("m", 5), 7.2)

    def test_settings_validate_and_blank_means_unlimited(self):
        self.assertEqual(spend_limits.validate(0, 0), (None, None))
        self.assertEqual(spend_limits.validate(20.0, 3), (20.0, 3))
        with self.assertRaises(ValueError):
            spend_limits.validate(10, 99)


from tests.test_clip_route_stage5 import ClipRouteStageFiveTests, _task  # noqa: E402


class StageFiveLimitTests(ClipRouteStageFiveTests):
    def test_attempts_are_counted_on_the_clip_and_a_shot_at_its_cap_is_not_resubmitted(self):
        task = _task(2)
        task["config"]["video_max_attempts"] = 1
        stored = self._run_routes(task)
        self.assertEqual([clip.get("attempts") for clip in stored["assets"]["5"]], [1, 1])
        stored["assets"]["5"][1]["stale"] = True
        with self.assertRaises(Exception) as stopped:
            self._run_routes(stored)
        self.assertEqual(self.calls, [], "the shot at its cap is not sent again")
        self.assertIn("每镜最多尝试", str(stopped.exception))

    def test_the_second_shot_is_not_submitted_once_the_run_budget_would_be_exceeded(self):
        task = _task(2)
        task["config"]["video_budget_cap"] = 3
        with patch("app.core.usage_ledger.estimate", side_effect=lambda model, media, units: {"priced": True, "currency": "CNY", "cost": 2.0}):
            with self.assertRaises(Exception) as stopped:
                self._run_routes(task)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("本轮视频预算 3 元", str(stopped.exception))

    def test_without_limits_nothing_changes(self):
        stored = self._run_routes(_task(2))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([clip.get("attempts") for clip in stored["assets"]["5"]], [1, 1])


for _inherited in [name for name in vars(ClipRouteStageFiveTests) if name.startswith("test_")]:
    setattr(StageFiveLimitTests, _inherited, None)


if __name__ == "__main__":
    unittest.main()
