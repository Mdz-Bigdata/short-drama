# -*- coding: utf-8 -*-
"""自己出声的视频模型(MiniMax H3、Seedance 2.x)：「声音」一段不裁、不压缩，多镜头片段每一镜的都写上，H3 超长时也不截掉。"""

import unittest

from app.core import h3_native, prompt_budget, prompt_distiller, slice_video


class DistillTests(unittest.TestCase):
    def test_native_audio_models_keep_sound_out_of_the_condensed_body(self):
        for model in ("MiniMax-H3", "doubao-seedance-2-0-pro-250528", "seedance-2.5"):
            self.assertNotIn("sound", prompt_distiller.distillable_for(model), model)
            self.assertNotIn("sound_layers", prompt_distiller.distillable_for(model), model)
            self.assertIn("sound", prompt_distiller.fixed_for(model), model)
        self.assertIn("sound", prompt_distiller.distillable_for("doubao-seedance-1-0-pro"), "a silent model still condenses its sound note")
        self.assertNotIn("sound", prompt_distiller.fixed_for("doubao-seedance-1-0-pro"))

    def test_sound_stays_verbatim_when_the_rest_is_condensed(self):
        sound = "声音设计：门轴吱呀一声，雨打瓦檐由远及近，刀背磕在案沿闷响一下。"
        sections = {"subject": "沈砚推门而入，" * 40, "sound": sound}
        plan = prompt_distiller.plan(
            sections, 200, distillable=prompt_distiller.distillable_for("MiniMax-H3"), fixed=prompt_distiller.fixed_for("MiniMax-H3"),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.kept["sound"], sound)
        self.assertNotIn("门轴", plan.body)


class CutTests(unittest.TestCase):
    def test_a_tight_budget_cuts_other_sections_but_not_sound(self):
        # Seedance 的正文预算现在是 2000：主体写长一些才压得到预算。
        sections = {"subject": "沈砚推门而入。" * 300, "sound": "声音设计：门轴吱呀。" * 20, "environment": "雨夜青石巷。" * 20}
        kept, report = prompt_budget.compress(sections, "doubao-seedance-2-0-pro-250528")
        self.assertIn("sound", kept)
        self.assertNotIn("sound", report.dropped)
        silent, silent_report = prompt_budget.compress(sections, "doubao-seedance-1-0-pro")
        self.assertIn("sound", silent_report.dropped)


class HardLimitTests(unittest.TestCase):
    def test_seedance_2_keeps_its_sound_section_when_cut_to_the_hard_limit(self):
        sound = "【声音事件】\n门轴吱呀一声。\n雨打瓦檐由远及近。"
        prompt = "\n".join(["【画面】" + "沈砚推门而入，灯焰被风压低。" * 200, sound, "【关键约束】同一张脸。", "禁止出现：字幕。"])
        model = "doubao-seedance-2-0-pro-250528"
        fitted, removed = prompt_budget.fit_hard_limit(prompt, model)
        # 分镜与运镜内容不删：超上限也整段原样发，声音段自然也在。
        self.assertEqual(fitted, prompt)
        self.assertEqual(removed, ["over_limit_kept"])
        self.assertIn(sound, fitted)


class SliceTests(unittest.TestCase):
    def test_every_beat_brings_its_own_sound(self):
        beats = [
            slice_video.Beat(sections={"subject": "沈砚推门。", "sound": "声音设计：门轴吱呀。"}, size="中景", motion="固定"),
            slice_video.Beat(sections={"subject": "林晚回头。", "sound": "声音设计：雨打瓦檐。"}, size="近景", motion="固定"),
            slice_video.Beat(sections={"subject": "两人对视。", "sound": "声音设计：雨打瓦檐。"}, size="近景", motion="固定"),
        ]
        compiled = slice_video.compile_prompt(beats, model="MiniMax-H3")
        sound = compiled.sections.get("sound", "")
        self.assertIn("门轴吱呀", sound)
        self.assertIn("雨打瓦檐", sound)
        self.assertEqual(sound.count("雨打瓦檐"), 1, "a line repeated by two beats is written once")


class SliceLabelTests(unittest.TestCase):
    def test_a_sound_only_one_beat_has_names_its_shot(self):
        beats = [
            slice_video.Beat(sections={"subject": "沈砚推门。", "sound_layers": "【声音设计·三层】ambient: 门轴吱呀\n【声音事件】刀背磕案沿", "sound": ""}),
            slice_video.Beat(sections={"subject": "林晚回头。", "sound_layers": "【声音设计·三层】ambient: 雨打瓦檐\n【声音事件】刀背磕案沿", "sound": ""}),
        ]
        layers = slice_video.compile_prompt(beats, model="MiniMax-H3").sections["sound_layers"].split("\n")
        self.assertIn("【声音设计·三层】（镜头1/2）ambient: 门轴吱呀", layers)
        self.assertIn("【声音设计·三层】（镜头2/2）ambient: 雨打瓦檐", layers)
        self.assertIn("【声音事件】刀背磕案沿", layers, "a sound every beat has carries no shot number")

    def test_the_three_layer_heading_is_protected_from_the_hard_cut_too(self):
        sound = "【声音设计·三层】ambient: 门轴吱呀, 雨打瓦檐"
        prompt = "\n".join(["【画面】" + "沈砚推门而入，灯焰被风压低。" * 200, sound, "禁止出现：字幕。"])
        fitted, _removed = prompt_budget.fit_hard_limit(prompt, "doubao-seedance-2-0-pro-250528")
        self.assertIn(sound, fitted)


class H3FitTests(unittest.TestCase):
    def _prompt(self, detail_sentences: int) -> str:
        detail = "[Shot 1] <Subject 1> pushes the door open. " + " ".join(
            f"Detail {n}: the lamp flame leans as the draught from the door crosses the room." for n in range(detail_sentences)
        ) + " [Shot 2] At 00:05.000, the shot transitions to <Subject 2> turning."
        return "\n\n".join([
            "subject_definitions: <Subject 1> is 沈砚 (<Picture 1>). <Audio 1> is the voice-timbre reference for 沈砚.",
            "summary: [reference generation] A door opens on a rainy night.",
            "retention_analysis: <Subject 1>: fully_preserved. <Audio 1>: reference for 沈砚's voice.",
            f"detailed_description: {detail}",
            "overall_soundscape: Rain on the roof tiles rises from far to near. The door hinge creaks once. A knife back knocks the bench.",
            "non_diegetic_music: Low guqin and erhu under the rain.",
        ])

    def test_over_the_limit_the_picture_details_go_and_the_sound_stays(self):
        prompt = self._prompt(120)
        self.assertGreater(len(prompt), h3_native.MAX_CHARS)
        fitted = h3_native.fit(prompt)
        self.assertLessEqual(len(fitted), h3_native.MAX_CHARS)
        self.assertIn("overall_soundscape: Rain on the roof tiles rises from far to near. The door hinge creaks once. A knife back knocks the bench.", fitted)
        self.assertIn("non_diegetic_music: Low guqin and erhu under the rain.", fitted)
        self.assertIn("<Audio 1> is the voice-timbre reference for 沈砚.", fitted)
        self.assertIn("<Audio 1>: reference for 沈砚's voice.", fitted)
        self.assertIn("[Shot 2] At 00:05.000", fitted)

    def test_a_rewrite_a_little_over_the_draft_limit_is_kept_and_fit_trims_the_picture(self):
        from tests.test_h3_native import GOOD, _job

        longer = GOOD.replace("detailed_description:", "detailed_description: " + "The lamp flame leans in the draught. " * 180, 1)
        self.assertGreater(len(longer), h3_native.MAX_DRAFT_CHARS)
        self.assertLess(len(longer), h3_native.MAX_ACCEPT_CHARS)
        self.assertEqual(h3_native.check(_job(), longer), "", "full sound made it longer: still the English rewrite, not the Chinese fallback")
        self.assertLessEqual(len(h3_native.fit(longer)), h3_native.MAX_CHARS)

    def test_a_prompt_within_the_limit_is_untouched(self):
        prompt = self._prompt(3)
        self.assertEqual(h3_native.fit(prompt), prompt)


if __name__ == "__main__":
    unittest.main()
