"""One emotion word drives face, body, voice and impact; a held prop is written as contact; clip prompts carry the writer's delivery notes."""

import unittest

from app.core import style_packs
from app.core.emotion_table import RULES, VOICE_LABELS, check_order, read_emotion
from app.core.screenwriting.prompts import build_outline_plan_prompt, build_script_plan_prompt
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt, contact_line
from app.service.drama_service import detect_emotion


class EmotionTableTests(unittest.TestCase):
    def test_the_table_is_ordered_specific_before_generic_and_uses_known_voices(self):
        self.assertEqual(check_order(), [])
        self.assertTrue(all(rule.voice in VOICE_LABELS for rule in RULES))
        self.assertTrue(all(1 <= len(rule.face) <= 2 for rule in RULES))

    def test_a_sneer_is_never_read_as_a_smile(self):
        sneer = read_emotion("林深冷笑一声")
        self.assertEqual((sneer.matched, sneer.voice), ("冷笑", "cold"))
        self.assertIn("眼神发冷", sneer.visible)
        smile = read_emotion("她笑了")
        self.assertEqual(smile.voice, "happy")
        roar = read_emotion("他怒吼")
        self.assertEqual((roar.matched, roar.voice, roar.impact), ("怒吼", "shout", True))
        self.assertGreater(roar.rate, 1.0)
        self.assertLess(read_emotion("委屈").rate, 1.0)

    def test_voice_only_words_change_the_voice_and_never_the_face(self):
        reading = read_emotion("低声、沙哑")
        self.assertEqual(reading.matched, "")
        self.assertEqual(reading.visible, "")
        self.assertEqual(reading.voice_notes, ("压低音量", "嗓音沙哑"))
        both = read_emotion("低声冷笑")
        self.assertEqual(both.matched, "冷笑")
        self.assertIn("压低音量", both.voice_notes)

    def test_at_most_two_face_phrases_and_an_explicit_note_beats_the_description(self):
        reading = read_emotion("绝望", "他笑着")
        self.assertEqual(reading.matched, "绝望")
        self.assertLessEqual(len(reading.face), 2)

    def test_the_voice_detector_reads_notes_and_parentheticals_before_guessing(self):
        self.assertEqual(detect_emotion("你终于来了", notes="冷笑 / 慢"), "cold")
        self.assertEqual(detect_emotion("林深（冷笑）：你终于来了"), "cold")
        self.assertEqual(detect_emotion("求求你别走"), "sad", "no note: the old keyword guess still works")
        self.assertEqual(detect_emotion("你别生气了"), "neutral", "an emotion word inside the spoken line does not decide")


class ContactTests(unittest.TestCase):
    def test_holding_supporting_and_resting_are_written_as_contact(self):
        self.assertIn("四指环绕法杖的握持处", contact_line("她右手握住法杖", ["法杖"]))
        self.assertIn("掌心朝上呈碗状承住水晶球的下半部", contact_line("她双手托着水晶球", ["水晶球"]))
        self.assertIn("掌根与放松的手指平贴在石栏的受力面上", contact_line("她扶着石栏回望", ["石栏"]))
        self.assertEqual(contact_line("她看向法杖", ["法杖"]), "", "looking at a prop is not handling it")
        self.assertEqual(contact_line("她握紧拳头", ["法杖"]), "", "only a prop of the shot counts")


def _shot(**overrides):
    params = dict(
        shot_index=3, duration_seconds=8, shot_size="近景", camera_movement="缓慢推进",
        subject_action="林夏右手握住录音笔，抬眼看向周教授", scene="地下实验室", blocking="林夏站在实验台左侧",
        start_state="林夏低头看着录音笔", end_state="林夏抬眼直视周教授", props=["录音笔"], characters=["林夏", "周教授"],
        dialogue="林夏：你到底瞒了什么？", dialogue_notes="林夏：压抑-克制 / 慢 / 尾音下沉",
        expression="压抑；外化为嘴唇抿成一线，肩背绷住不动，指节攥得发白",
    )
    params.update(overrides)
    return ShotPromptInput(**params)


class ClipPromptTests(unittest.TestCase):
    def test_the_clip_prompt_carries_delivery_visible_emotion_and_contact_without_seconds(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text
        self.assertIn("台词表达：林夏：压抑-克制 / 慢 / 尾音下沉", text)
        self.assertIn("外化为嘴唇抿成一线", text)
        self.assertIn("持物接触：四指环绕", text)
        self.assertIn("落幅：", text)
        self.assertNotRegex(text, r"(?<!\d)\d{1,2}\s*[-–~至]\s*\d{1,2}\s*(?:s|秒)")
        self.assertNotIn("整段8秒", text)


class ScreenwritingPromptTests(unittest.TestCase):
    def test_hooks_pick_the_emotion_first_and_lines_keep_their_delivery_in_every_mode(self):
        outline = build_outline_plan_prompt(
            title="暗室回声", director_plan="大纲", overview={}, first=1, last=1, total=1,
            context_entries=[], target_seconds=None, instructions=None,
        )
        self.assertIn("钩子先定情绪、再选写法", outline)
        self.assertIn("能猜、又猜不准", outline)
        common = dict(
            episode=1, overview={}, style="写实", characters={"林夏": {}}, scenes={"实验室": {}}, props={},
            supported_durations=[4, 8], default_duration=None, episode_target_seconds=None,
            episode_outline=None, next_episode_outline=None,
        )
        novel = build_script_plan_prompt(source_text="林夏冷笑道：你来了。", source_kind="novel", **common)
        self.assertIn("写进这句的 delivery", novel)
        self.assertIn("不在画面里写情绪名词", novel)
        screenplay = build_script_plan_prompt(source_text="林夏（冷笑）：你来了。", source_kind="screenplay", **common)
        self.assertIn("照录进这句的 delivery", screenplay)


if __name__ == "__main__":
    unittest.main()
