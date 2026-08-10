import unittest

from app.core.continuity import ContinuityState, plan_transition


class ContinuityTests(unittest.TestCase):
    def test_matching_action_prefers_short_match_transition(self):
        previous = ContinuityState(
            characters=["林夏"], scene="客厅", screen_direction="left_to_right",
            action="右手将信封递出", emotion="克制", props={"信封": "林夏右手"},
            lighting="暖色左侧主光", audio_bed="雨声",
        )
        current = ContinuityState(
            characters=["林夏", "顾言"], scene="客厅", screen_direction="left_to_right",
            action="顾言左手接住信封", emotion="震惊", props={"信封": "顾言左手"},
            lighting="暖色左侧主光", audio_bed="雨声",
        )
        plan = plan_transition(previous, current)
        self.assertEqual(plan.video_transition, "match_cut")
        self.assertEqual(plan.audio_transition, "l_cut")
        self.assertLessEqual(plan.duration_seconds, 0.5)
        self.assertTrue(plan.accepted)

    def test_axis_flip_is_rejected_without_neutral_bridge(self):
        previous = ContinuityState(
            characters=["林夏"], scene="客厅", screen_direction="left_to_right",
            action="向右走", emotion="紧张", props={}, lighting="暖色", audio_bed="雨声",
        )
        current = ContinuityState(
            characters=["林夏"], scene="客厅", screen_direction="right_to_left",
            action="继续向前走", emotion="紧张", props={}, lighting="暖色", audio_bed="雨声",
        )
        plan = plan_transition(previous, current)
        self.assertFalse(plan.accepted)
        self.assertIn("180", " ".join(plan.reasons))


if __name__ == "__main__":
    unittest.main()
