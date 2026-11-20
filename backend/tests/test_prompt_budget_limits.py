# -*- coding: utf-8 -*-
"""Official prompt limits: MiniMax H3 7000, Seedance 2.0 2000 for the whole prompt negatives included, Seedance 2.5 up to
15000 (2000–4000 for a 30-second clip). What goes first when a prompt is over: generic boilerplate, never the shot."""

import unittest
from unittest.mock import patch

from app.core import prompt_budget
from app.core.model_gateway import ModelGateway

SHOT = "画面：沈砚推门而入。台词（逐字保持原文，口型同步）：沈砚{朕的江山，不换。}"
BOILERPLATE = "\n".join([
    "Pa2", "[STYLE LOCK]", "Shot on 35mm Kodak Vision3 500T film stock", "+ practical light only + naturalistic handheld breathing",
    "realistic，日常静默调性 + 克制张力。", "画质：" + "真人实拍电影画质，皮肤毛孔清晰；" * 6,
    "Pa3", "风格铁律：NOT 3D rendered + NOT CGI", "设定图反偷懒铁律：设定图仅作造型参考",
    "，严守跨镜连贯六锚点：同一人物同一张脸。(规避跨镜断裂：" + "jump cut, time skip, " * 40 + ")",
    "禁止空间重构 + NOT cartoon + (避免：" + "worst quality, blurry, " * 40 + ")",
    "人物肖像安全约束：画面中的人物均为原创虚构角色。", "禁止出现：水印、真实人物照片。",
])


class BudgetTest(unittest.TestCase):
    def test_h3_takes_its_official_limit_and_the_others_stay(self):
        for model in ("MiniMax-H3", "minimax-h3", "H3"):
            self.assertEqual(prompt_budget.prompt_budget(model), 7000, model)
        self.assertEqual(prompt_budget.prompt_budget("hailuo-02"), 400, "MiniMax's older Hailuo models keep theirs")
        self.assertEqual(prompt_budget.prompt_budget("seedance2.0"), 2000)
        self.assertEqual(prompt_budget.prompt_budget("doubao-seedance-2-5-260128"), 4000, "2000–4000 for a 30-second clip")
        self.assertIsNone(prompt_budget.prompt_budget("sora-2"))

    def test_a_multi_shot_clip_stays_inside_h3s_whole_prompt_limit(self):
        self.assertEqual(prompt_budget.clip_budget("MiniMax-H3", 3), 7000)
        self.assertEqual(prompt_budget.clip_budget("seedance2.0", 3), 2000, "Seedance's limits are whole-prompt limits too")
        self.assertEqual(prompt_budget.clip_budget("kling-2.6", 3), 1500, "per-shot budgets still add up per moment")
        self.assertIsNone(prompt_budget.clip_budget("sora", 3))

    def test_a_long_h3_prompt_is_not_flagged_or_cut(self):
        sections = {"subject": "人" * 1500, "action": "动" * 600, "sound": "雨声铺底，台词对口型" * 20, "environment": "雪夜庭院" * 20}
        kept, report = prompt_budget.compress(sections, "MiniMax-H3")
        self.assertEqual(report.dropped, [])
        self.assertNotEqual(report.tier, "red")
        self.assertEqual(kept["sound"], sections["sound"])



class HardLimitTest(unittest.TestCase):
    def _prompt(self, shot=SHOT):
        return ModelGateway._with_global_negatives(f"{shot}\n\n{BOILERPLATE}", "video")

    def test_the_providers_hard_limits(self):
        self.assertEqual(prompt_budget.hard_limit("doubao-seedance-2-0-260128"), 2000)
        self.assertEqual(prompt_budget.hard_limit("seedance2.5"), 15000)
        self.assertIsNone(prompt_budget.hard_limit("kling-2.6"))

    def test_a_prompt_inside_the_limit_is_sent_as_it_is(self):
        self.assertEqual(prompt_budget.fit_hard_limit("短", "seedance2.0"), ("短", []))
        long_for_20 = self._prompt()
        self.assertEqual(prompt_budget.fit_hard_limit(long_for_20, "seedance2.5")[0], long_for_20, "15000 is far away")

    def test_boilerplate_goes_first_and_the_shot_stays(self):
        prompt = self._prompt()
        self.assertGreater(len(prompt), 2000)
        fitted, removed = prompt_budget.fit_hard_limit(prompt, "seedance2.0")
        self.assertLessEqual(len(fitted), 2000)
        self.assertNotIn("truncated", removed)
        self.assertIn(SHOT, fitted)
        self.assertNotIn("worst quality", fitted)
        self.assertEqual(removed, ["drop1"], "only as much as it takes: the English negative lists were enough")
        self.assertIn("Kodak", fitted)
        tighter, more = prompt_budget.fit_hard_limit(prompt.replace("同一人物同一张脸。", "同一人物同一张脸。" + "画面连贯；" * 300), "seedance2.0")
        self.assertIn("drop2", more)
        self.assertNotIn("Kodak", tighter)
        self.assertIn("realistic，日常静默调性", tighter, "the style line in Chinese is not part of the English lock")
        for line in ("人物肖像安全约束", "禁止出现：", ModelGateway.GLOBAL_NEGATIVE_LABEL):
            self.assertIn(line, fitted)

    def test_the_enhancement_words_go_before_anything_written_for_the_shot(self):
        plain = "镜头" * 900
        fitted, removed = prompt_budget.fit_hard_limit(plain + "，film grain" * 50, "seedance2.0", plain=plain)
        self.assertEqual((fitted, removed), (plain, ["enhancement"]))

    def test_storyboard_and_camera_content_is_never_cut(self):
        shot = "画面：沈砚推门而入，铁链垂落。运镜：缓推。" * 160
        prompt = self._prompt(shot=shot)
        fitted, removed = prompt_budget.fit_hard_limit(prompt, "seedance2.0")
        self.assertIn(shot, fitted, "every word of the shot and its camera moves stays")
        self.assertEqual(removed[-1], "over_limit_kept")
        self.assertNotIn("truncated", removed)
        self.assertIn(ModelGateway.GLOBAL_NEGATIVE_LABEL, fitted)
        self.assertIn("人物肖像安全约束", fitted)

    def test_the_gateway_sends_seedance_inside_its_limit(self):
        gateway = ModelGateway()
        sent = {}

        def fake_ark(api_key, base_url, prompt, **kwargs):
            sent["prompt"] = prompt
            return "http://video.test/clip.mp4"

        with patch.object(gateway, "_ark_video", side_effect=fake_ark), patch.object(gateway, "_is_valid_key", return_value=True), \
             patch.object(gateway, "optimize_video_prompt", side_effect=lambda text, **_: text):
            gateway.generate_video("seedance2.0", "https://cdn.test/frame.jpeg", f"{SHOT}\n\n{BOILERPLATE}", style_pack="film_35mm")
        self.assertLessEqual(len(sent["prompt"]), 2000)
        self.assertIn(SHOT, sent["prompt"])

    def _sent_after_rewrite(self, rewrite):
        gateway = ModelGateway()
        sent, calls = {}, []

        def fake_ark(api_key, base_url, prompt, **kwargs):
            sent["prompt"] = prompt
            return "http://video.test/clip.mp4"

        def optimizer(text, **_):
            calls.append(text)
            return rewrite(text)

        with patch.object(gateway, "_ark_video", side_effect=fake_ark), patch.object(gateway, "_is_valid_key", return_value=True), \
             patch.object(gateway, "optimize_video_prompt", side_effect=optimizer):
            gateway.generate_video("seedance2.0", "https://cdn.test/frame.jpeg", f"{SHOT}\n\n{BOILERPLATE}", style_pack="film_35mm")
        self.assertEqual(len(calls), 1, "改写确实走到了")
        return sent["prompt"], calls[0]

    def test_a_rewrite_over_the_limit_falls_back_to_the_fitted_prompt(self):
        prompt, fitted = self._sent_after_rewrite(lambda text: text + "，镜头稳定" * 600)
        self.assertLessEqual(len(prompt), 2000)
        self.assertEqual(prompt, fitted, "退回改写前已经按上限收过的那条，不截断改写结果")

    def test_a_rewrite_inside_the_limit_is_used(self):
        prompt, _fitted = self._sent_after_rewrite(lambda text: "改写：" + SHOT)
        self.assertTrue(prompt.startswith("改写：" + SHOT))
        self.assertLessEqual(len(prompt), 2000)


if __name__ == "__main__":
    unittest.main()
