import unittest

from app.core.continuity import ContinuityState, plan_transition
from app.core.media_compositor import subtitle_cues, wrap_subtitle
from app.service.drama_service import final_cut_transitions


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

    def test_a_new_script_scene_in_the_same_place_is_not_an_axis_cross(self):
        # 每场戏的导演台各摆一套机位：E1S06 的「左到右」和 E1S07 的「右到左」不是同一条轴线。
        def shot(scene_id, direction):
            state = {
                "characters": ["断水"], "scene": "磨刀铺内", "screen_direction": direction, "action": "磨刀",
                "emotion": "冷", "props": {}, "lighting": "暖色", "audio_bed": "雨声",
            }
            return {"shot_id": 1, "scene_id": scene_id, "video_url": "x", "continuity_state": state, "continuity_out": state}

        specs, reports = final_cut_transitions([shot("E1S06", "left_to_right"), shot("E1S07", "right_to_left")])
        self.assertTrue(reports[0]["accepted"])
        self.assertEqual(len(specs), 1)
        # 同一场戏里越轴照旧拦下，报错写清是哪场哪镜。
        with self.assertRaisesRegex(RuntimeError, "E1S06 第1镜→E1S06 第1镜"):
            final_cut_transitions([shot("E1S06", "left_to_right"), shot("E1S06", "right_to_left")])

    def test_subtitles_break_after_punctuation_and_never_start_a_line_with_it(self):
        fits = lambda line: len(line) <= 16
        self.assertEqual(wrap_subtitle("你叫断水。 刀不认人，我认。 断水不认人？", fits), ["你叫断水。 刀不认人，我认。", "断水不认人？"])
        lines = wrap_subtitle("这刀……是我的。人是我杀的。这话你拖了七年。刀不认人，我认。", fits)
        self.assertEqual(lines, ["这刀……是我的。人是我杀的。", "这话你拖了七年。刀不认人，我认。"])
        self.assertFalse(any(line[0] in "，。？！…" for line in wrap_subtitle("一二三四五六七八九十一二三四五六。七", fits)))
        self.assertEqual(wrap_subtitle("甲：走。\n乙：不走。", fits), ["甲：走。", "乙：不走。"])

    def test_a_shots_lines_come_up_one_by_one_and_each_stays_two_seconds(self):
        cues = subtitle_cues("这刀……是我的。 人是我杀的。 这话你拖了七年。 刀不认人，我认。", 9.4)
        self.assertEqual([text for text, _start, _end in cues], ["这刀……是我的。", "人是我杀的。", "这话你拖了七年。", "刀不认人，我认。"])
        self.assertEqual((cues[0][1], cues[-1][2]), (0.0, 9.4))
        self.assertTrue(all(end - start >= 2.0 - 1e-6 for _text, start, end in cues))
        self.assertTrue(all(cues[k][2] == cues[k + 1][1] for k in range(len(cues) - 1)), "no gap, no overlap")
        # 镜头放不下每句 2 秒：相邻的句子并成一条。
        self.assertEqual([text for text, _a, _b in subtitle_cues("一。二。三。四。五。", 5)], ["一。二。三。", "四。五。"])
        self.assertEqual(subtitle_cues("好。", 1.5), [("好。", 0.0, 1.5)])
        self.assertEqual(subtitle_cues("", 5), [])


if __name__ == "__main__":
    unittest.main()
