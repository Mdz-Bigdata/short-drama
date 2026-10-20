"""A video prompt names each reference image by the position it actually has in the request."""

import unittest

from app.core.asset_mentions import resolve_mentions
from app.core.storyboard_scene_context import merge_video_references, video_reference_entries
from app.core.video_references import VideoGenerationIntent, VideoReferencePlan, plan_video_references, renumber_reference_mentions

SHEETS = [("林夏", "https://cdn/linxia.png"), ("周教授", "https://cdn/zhou.png")]
LIBRARY = [{"kind": "scene", "name": "地下实验室", "image_url": "https://cdn/lab.png"}]


def _prompt():
    entries = video_reference_entries(SHEETS, LIBRARY)
    numbers = {name: number for number, (_, name, _) in enumerate(entries, start=1)}
    images, notes = merge_video_references(SHEETS, LIBRARY)
    text = resolve_mentions(f"{notes}。@[林夏]在@[地下实验室]里看向@[周教授]。", numbers)
    return text, images


class RenumberTests(unittest.TestCase):
    def test_before_routing_the_prompt_counts_only_the_identity_images(self):
        text, images = _prompt()
        self.assertIn("林夏（参考图1）", text)
        self.assertIn("周教授（参考图2）", text)
        self.assertIn("地下实验室（参考图3）", text)
        self.assertEqual(images, ["https://cdn/linxia.png", "https://cdn/zhou.png", "https://cdn/lab.png"])

    def test_multi_reference_puts_the_first_frame_ahead_and_every_number_moves_with_it(self):
        text, images = _prompt()
        plan = plan_video_references(
            "multi_reference", model="seedance-2.0", first_frame="https://cdn/frame.png", reference_images=images,
            intent=VideoGenerationIntent(identity_consistency_required=True),
        )
        self.assertEqual(plan.reference_images[0], "https://cdn/frame.png")
        sent = renumber_reference_mentions(text, images, plan)
        self.assertTrue(sent.startswith("参考图1是本镜首帧画面"))
        self.assertIn("林夏（参考图2）", sent)
        self.assertIn("周教授（参考图3）", sent)
        self.assertIn("地下实验室（参考图4）", sent)
        self.assertIn("参考图2仅锁定数字演员设定集「林夏」", sent)
        self.assertIn("参考图4仅锁定拍摄场地「地下实验室」", sent)
        for number, url in enumerate(plan.reference_images, start=1):
            if url == "https://cdn/zhou.png":
                self.assertIn(f"周教授（参考图{number}）", sent)

    def test_an_image_the_request_does_not_carry_is_no_longer_cited(self):
        text, images = _prompt()
        plan = VideoReferencePlan(mode="multi_reference", reference_images=["https://cdn/frame.png", "https://cdn/linxia.png"])
        sent = renumber_reference_mentions(text, images, plan)
        self.assertIn("林夏（参考图2）", sent)
        self.assertNotIn("周教授（参考图", sent)
        self.assertIn("看向周教授", sent)
        self.assertNotIn("「周教授」", sent, "the lock note for an image that is not sent is dropped")
        self.assertNotIn("参考图3", sent)

    def test_first_frame_modes_send_no_identity_images_so_none_is_cited(self):
        text, images = _prompt()
        plan = VideoReferencePlan(mode="first_last_frame", first_frame="https://cdn/a.png", last_frame="https://cdn/b.png")
        sent = renumber_reference_mentions(text, images, plan)
        self.assertNotIn("参考图", sent)
        self.assertIn("林夏在地下实验室里看向周教授", sent)

    def test_numbers_are_mapped_in_one_pass_without_chaining(self):
        text = "甲（参考图1）、乙（参考图2）"
        plan = VideoReferencePlan(mode="multi_reference", reference_images=["https://cdn/b.png", "https://cdn/a.png"])
        sent = renumber_reference_mentions(text, ["https://cdn/a.png", "https://cdn/b.png"], plan)
        self.assertEqual(sent, "甲（参考图2）、乙（参考图1）")


if __name__ == "__main__":
    unittest.main()
