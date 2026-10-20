import unittest
from unittest.mock import patch

from app.core import production_knowledge
from app.core.model_gateway import ModelGateway


class GlobalNegativeListTests(unittest.TestCase):
    """全局强制负面词只写在负面提示词指南里，代码读指南、不另存一份。"""

    def test_the_video_list_is_read_from_the_guide(self):
        terms = production_knowledge.global_negatives("video")
        self.assertEqual(len(terms), 21)
        self.assertEqual(terms[0], "禁止穿模")
        for term in ("禁止隔空打击", "禁止滑步悬空", "禁止站桩蓄力", "禁止玄幻悬浮打斗", "禁止低帧率卡顿"):
            self.assertIn(term, terms)

    def test_stills_get_only_the_single_frame_subset(self):
        video = set(production_knowledge.global_negatives("video"))
        image = production_knowledge.global_negatives("image")
        self.assertTrue(image)
        self.assertTrue(set(image) <= video)
        # 只在运动中才成立的问题不进静帧
        for motion_only in ("禁止低帧率卡顿", "禁止滑步悬空", "禁止狂奔大跳与剧烈翻滚等高爆发失控动作", "禁止画面抖动紊乱"):
            self.assertNotIn(motion_only, image)
        self.assertIn("禁止多余文字水印", image)

    def test_an_unknown_medium_is_rejected(self):
        with self.assertRaises(ValueError):
            production_knowledge.global_negatives("audio")

    def test_a_guide_without_the_section_yields_nothing(self):
        with patch.object(production_knowledge, "load_section", return_value="# 负面词\n\n无统一词表"):
            self.assertEqual(production_knowledge.global_negatives("video"), ())
            self.assertEqual(production_knowledge.global_negative_text("image"), "")


class GatewayGlobalNegativeTests(unittest.TestCase):
    def test_the_line_is_appended_once(self):
        prompt = ModelGateway._with_global_negatives("少女推门进店，回头看向街口。", "video")
        self.assertTrue(prompt.startswith("少女推门进店"))
        self.assertIn(ModelGateway.GLOBAL_NEGATIVE_LABEL + "禁止穿模、禁止肢体穿插", prompt)
        self.assertEqual(ModelGateway._with_global_negatives(prompt, "video"), prompt)
        self.assertEqual(prompt.count(ModelGateway.GLOBAL_NEGATIVE_LABEL), 1)

    def test_an_empty_prompt_or_an_empty_list_leaves_the_prompt_alone(self):
        self.assertEqual(ModelGateway._with_global_negatives("", "video"), "")
        with patch.object(production_knowledge, "global_negative_text", return_value=""):
            self.assertEqual(ModelGateway._with_global_negatives("镜头缓推", "image"), "镜头缓推")

    def test_agnes_truncation_never_cuts_the_list(self):
        long_prompt = "雨夜街道，" * 400
        prompt = ModelGateway._with_global_negatives(long_prompt, "video")
        agnes = ModelGateway._agnes_prompt(prompt, "video")
        line = ModelGateway.GLOBAL_NEGATIVE_LABEL + production_knowledge.global_negative_text("video")
        self.assertTrue(agnes.endswith(line))
        self.assertEqual(agnes.count(ModelGateway.GLOBAL_NEGATIVE_LABEL), 1)
        self.assertLessEqual(len(agnes), 600 + 1 + len(line))

    def test_video_and_image_calls_carry_the_list_to_the_provider(self):
        gateway = ModelGateway()
        seen = {}

        with patch.object(ModelGateway, "_enhancePromptWithRules", side_effect=lambda p: p), \
             patch("app.core.model_gateway.runtime_model_registry.resolve", return_value=None), \
             patch("app.core.model_gateway.runtime_model_registry.first_for_category", return_value=None), \
             patch.object(ModelGateway, "_provider_creds", return_value=("", "", "")):
            # 没有任何可用凭证：走到离线兜底前，提示词已经在入口处带上了词表。
            original = ModelGateway._with_global_negatives
            def spy(prompt, medium):
                result = original(prompt, medium)
                seen.setdefault(medium, result)
                return result
            with patch.object(ModelGateway, "_with_global_negatives", side_effect=spy):
                try:
                    gateway._generate_image_unmetered("", "古装少女站在桥头", enhance_prompt=False)
                except Exception:
                    pass
                try:
                    gateway._generate_video_unmetered("", None, "少女转身离开")
                except Exception:
                    pass
        self.assertIn(ModelGateway.GLOBAL_NEGATIVE_LABEL, seen["image"])
        self.assertNotIn("禁止低帧率卡顿", seen["image"])
        self.assertIn("禁止低帧率卡顿", seen["video"])


if __name__ == "__main__":
    unittest.main()
