import unittest

from app.core.frame_position import (
    FramePosition,
    facing_side,
    flipped_subjects,
    parse_frame_positions,
    render_frame_positions,
    uses_frame_grammar,
)


class FramePositionTests(unittest.TestCase):
    def test_parses_region_depth_facing_occlusion_and_forbidden_zone_per_subject(self):
        text = (
            "男人模糊的肩部从画面左侧进入极近前景，遮挡约四分之一，保留女人的眼睛。"
            "女人位于画面右侧中景，面部清晰对焦，视线朝向画面左侧，不要挡住女人的眼睛和嘴。"
        )
        positions = {item.subject: item for item in parse_frame_positions(text, ["女人", "男人"])}
        self.assertEqual((positions["男人"].region, positions["男人"].depth), ("画面左侧", "极近前景"))
        self.assertIn("遮挡约四分之一", positions["男人"].occlusion)
        self.assertEqual((positions["女人"].region, positions["女人"].depth, positions["女人"].facing), ("画面右侧", "中景", "视线朝向画面左侧"))
        self.assertIn("不要挡住女人的眼睛和嘴", positions["女人"].forbidden_zone)
        self.assertEqual(parse_frame_positions("女人站在男人左边，抬起左手", ["女人", "男人"]), [])

    def test_renders_the_five_part_position_sentence(self):
        sentence = render_frame_positions([
            FramePosition(subject="人物A", region="画面左侧三分之一", depth="中景", facing="面向画面右侧"),
            FramePosition(subject="人物B", region="画面右后方", depth="背景", facing="面向画面左侧",
                          forbidden_zone="中央区域不要出现第三个人物"),
        ])
        self.assertEqual(
            sentence,
            "人物A位于画面左侧三分之一的中景，面向画面右侧；人物B位于画面右后方的背景，面向画面左侧；中央区域不要出现第三个人物",
        )
        self.assertEqual(render_frame_positions([]), "")

    def test_frame_grammar_and_eyeline_flip_detection(self):
        self.assertTrue(uses_frame_grammar("女人占据画面左侧三分之一，男人位于背景"))
        self.assertFalse(uses_frame_grammar("女人站在男人左边"))
        self.assertEqual(facing_side("背对镜头"), "away")
        self.assertEqual(facing_side("看向画面右侧"), "right")
        before = [FramePosition(subject="女人", facing="朝向画面右侧"), FramePosition(subject="男人", facing="朝向画面左侧")]
        after = [FramePosition(subject="女人", facing="朝向画面左侧"), FramePosition(subject="男人", facing="面向镜头")]
        self.assertEqual(flipped_subjects(before, after), ["女人"])


if __name__ == "__main__":
    unittest.main()
