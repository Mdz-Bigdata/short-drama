"""一句台词在画面里要占多久：字数 ÷ 情绪语速 + 句首句尾留白，至少 2 秒。"""

import unittest

from app.core.screenwriting.speech_rate import estimate_spoken_seconds, line_seconds
from app.core.shot_table_rules import dialogue_seconds


class SpeechPaceTests(unittest.TestCase):
    def test_the_articles_worked_examples(self):
        # 16 字悲伤台词约 11 秒；8 字暴怒约 3 秒；13 字日常约 5 秒；金句降速留白。
        self.assertAlmostEqual(line_seconds("为什么……你明明答应过不会离开我的。", "sad"), 11.2, delta=0.6)
        self.assertAlmostEqual(line_seconds("你根本什么都不懂！", "shout"), 2.8, delta=0.4)
        self.assertAlmostEqual(line_seconds("我今天就是来跟你说清楚这件事。"), 5.0, delta=0.8)
        self.assertGreater(line_seconds("所有的一切，都是他布下的局。", key_line=True), line_seconds("所有的一切，都是他布下的局。") + 3)

    def test_a_short_line_still_gets_two_seconds_and_blank_is_nothing(self):
        self.assertEqual(line_seconds("走。", "angry"), 2.0)
        self.assertEqual(line_seconds("", "sad"), 0.0)
        self.assertEqual(line_seconds("……"), 0.0)

    def test_an_unknown_emotion_reads_as_everyday_speech_and_the_episode_rate_is_untouched(self):
        self.assertEqual(line_seconds("我今天就是来跟你说清楚这件事。", "whatever"), line_seconds("我今天就是来跟你说清楚这件事。"))
        self.assertAlmostEqual(estimate_spoken_seconds("一二三四五六七八九十"), 2.0)

    def test_each_line_of_a_shot_takes_its_own_emotion(self):
        both = dialogue_seconds("林夏：（哽咽）别走。\n顾言：（怒吼）滚！")
        self.assertAlmostEqual(both, line_seconds("别走。", "sad") + line_seconds("滚！", "shout"), places=3)
        self.assertGreater(dialogue_seconds("林夏：我等了你三年。", "悲伤"), dialogue_seconds("林夏：我等了你三年。"))

    def test_the_scenes_key_line_slows_down_wherever_it_is_spoken(self):
        plain = dialogue_seconds("沈砚：刀不认人，我认。")
        keyed = dialogue_seconds("沈砚：刀不认人，我认。", key_line="刀不认人 我认")
        self.assertEqual(keyed, line_seconds("刀不认人，我认。", key_line=True))
        self.assertGreater(keyed, plain + 2)
        self.assertEqual(dialogue_seconds("沈砚：走吧。", key_line="刀不认人，我认"), dialogue_seconds("沈砚：走吧。"))


if __name__ == "__main__":
    unittest.main()


class DialogueCraftTests(unittest.TestCase):
    """台词更像真人开口：接球、不把情绪讲满、按戏路调口气、生硬与自然对照；客服腔和演讲腔算念稿。"""

    def test_the_writing_rule_carries_the_new_craft(self):
        from app.core import literary
        rule = literary.dialogue_rule()
        for phrase in ("接球", "情绪不讲满", "嘴硬", "按戏路调口气", "久别重逢", "家人对峙", "你以后别替我做主"):
            self.assertIn(phrase, rule)
        self.assertIn("情绪外露多少", literary.voice_print_rule())

    def test_customer_service_and_speech_phrases_read_as_stiff_but_everyday_ones_do_not(self):
        from app.core import literary
        self.assertEqual(literary.stiff_hits("事实上，我无法接受。"), ["事实上", "我无法接受"])
        self.assertEqual(literary.stiff_hits("我理解你的感受，请你冷静一下"), ["我理解你的感受", "请你冷静一下"])
        self.assertEqual(literary.stiff_hits("你知道吗，我等了你三年"), [])
