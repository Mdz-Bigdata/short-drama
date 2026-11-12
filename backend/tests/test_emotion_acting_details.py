# -*- coding: utf-8 -*-
"""Emotions written as things a camera sees: the groups added for 破防, 强忍泪水, 黑化, 倔强, 迷茫, 坚定, 动容, 心动, 焦灼, 隐痛."""

import unittest

from app.core.emotion_table import VOICE_LABELS, check_order, read_emotion


class ActingDetailTest(unittest.TestCase):
    def test_the_table_stays_ordered_and_every_voice_is_one_the_dubbing_knows(self):
        self.assertEqual(check_order(), [])
        for text in ("破防", "强忍泪水", "黑化", "倔强", "迷茫", "坚定", "动容", "心动", "焦灼", "隐痛"):
            self.assertIn(read_emotion(text).voice, VOICE_LABELS, text)

    def test_each_new_emotion_is_drawn_as_a_body_detail_not_its_name(self):
        cases = {
            "她笑着笑着就破防了": ("破防", "眼眶"),
            "强忍泪水看着他走远": ("强忍泪水", "泪珠"),
            "他眼神变冷，像换了个人": ("眼神变冷", "冷光"),
            "她倔强地抬起头": ("倔强", "下巴"),
            "站在路口一脸茫然": ("茫然", "失焦"),
            "那一刻他下定决心": ("下定决心", "凝住"),
            "多年后重逢": ("重逢", "湿润"),
            "两人暧昧地对视了一眼": ("暧昧", "耳根"),
            "门外脚步声越来越近，他焦灼地等着": ("焦灼", "细汗"),
            "看到旧玉佩，隐痛浮上心头": ("隐痛", "暗下去"),
        }
        for text, (word, detail) in cases.items():
            reading = read_emotion(text)
            self.assertEqual(reading.matched, word, text)
            self.assertIn(detail, reading.visible, text)
            for name in ("破防", "黑化", "倔强", "迷茫", "心动", "暧昧", "焦灼"):
                self.assertNotIn(name, reading.visible, f"{text}: the face says what is seen, not the emotion's name")

    def test_held_back_moments_say_what_not_to_play(self):
        self.assertIn("不让眼泪掉下来", read_emotion("强忍泪水").hold_back)
        self.assertIn("不咧嘴大笑", read_emotion("心动").hold_back)
        self.assertTrue(read_emotion("破防").impact, "a breakdown lands hard")

    def test_the_older_readings_do_not_move(self):
        self.assertEqual(read_emotion("他冷笑一声").matched, "冷笑")
        self.assertEqual(read_emotion("她强忍着不出声").matched, "强忍")
        self.assertEqual(read_emotion("开心地笑了").matched, "开心")


if __name__ == "__main__":
    unittest.main()
