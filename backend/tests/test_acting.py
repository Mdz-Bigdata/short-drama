"""What an actor plays from: the shot's subtext as motive, held-back emotions, and how a line is said."""

import unittest

from app.core import acting, prompt_data, style_packs
from app.core.emotion_table import read_emotion
from app.core.screenwriting.renderer import scene_breakdown_entry
from app.core.sound_events import build_sound_events
from app.core.video_prompt_engine import compile_shot_prompt
from tests.test_native_audio_prompts import _shot

SUBTEXT = "林夏：已决定分手，仍爱他；沈砚：不知道父亲已经找过她"


class SubtextTests(unittest.TestCase):
    def test_the_shot_plan_carries_subtext_into_the_breakdown(self):
        entry = scene_breakdown_entry({"scene_id": "E1S01", "subtext": SUBTEXT, "utterances": []})
        self.assertEqual(entry["subtext"], SUBTEXT)

    def test_the_clip_prompt_gives_it_as_motive_only(self):
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(motive=acting.clip_line({"subtext": SUBTEXT})), model="seedance2.5")
        self.assertIn(SUBTEXT, compiled.sections["motive"])
        self.assertIn("原因不进画面", compiled.sections["motive"])

    def test_no_subtext_writes_no_motive(self):
        self.assertEqual(acting.clip_line({}), "")


class HeldBackEmotionTests(unittest.TestCase):
    def test_suppressed_anger_reads_as_restraint_not_anger(self):
        reading = read_emotion("他强忍怒火")
        self.assertEqual(reading.matched, "强忍")
        self.assertIn("不咬牙出声", reading.visible)

    def test_held_tears_say_where_the_eyes_go_and_what_not_to_play(self):
        visible = read_emotion("她含泪看着他").visible
        self.assertIn("脸颊干燥", visible)
        self.assertIn("从眼睛慢慢落到嘴角", visible)
        self.assertIn("不连续眨眼", visible)

    def test_a_body_struggling_is_not_hesitation(self):
        self.assertEqual(read_emotion("他在地上挣扎").matched, "")
        self.assertEqual(read_emotion("她内心挣扎").matched, "内心挣扎")

    def test_contempt_is_a_cold_sneer_not_a_smug_smile(self):
        self.assertEqual(read_emotion("他轻蔑地看了一眼").voice, "cold")
        self.assertNotIn("眼尾带着笑意", read_emotion("他轻蔑地看了一眼").visible)


class MixLevelTests(unittest.TestCase):
    def test_bed_and_contacts_carry_their_levels(self):
        plan = build_sound_events("环境音：空调低鸣；音效：纸杯放下", action="林夏把纸杯放在木柜台上", dialogue=True)
        self.assertIn("约 -12dB", plan.text)
        self.assertIn("约 -6dB", plan.text)


class WritingRulesTests(unittest.TestCase):
    def test_the_tension_and_lighting_rules_are_data(self):
        self.assertIn("信息差", prompt_data.text("tension", "outline_rule"))
        self.assertIn("5500K", prompt_data.text("clip_prompt", "light_kelvin_guide"))


if __name__ == "__main__":
    unittest.main()
