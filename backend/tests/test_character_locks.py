"""角色禁用项：写了的照写，没写的从卡里推；接在外貌后面，不被截掉。"""

import unittest

from app.core import character_locks
from app.core.video_prompt_engine import appearance_lines


class CharacterLockTests(unittest.TestCase):
    def test_written_locks_come_first_and_facts_fill_in(self):
        card = "年轻东亚男子，束发，浅色战袍，右手持长剑；禁用项：剑雨不变成火"
        self.assertEqual(character_locks.locks_of(card), ["剑雨不变成火", "头发始终束起", "长剑始终在右手", "战袍始终是浅色"])
        rest, written = character_locks.split_locks("身份锚点：x；禁用项：剑始终在右手、战袍不变色；毛发：束发")
        self.assertEqual((rest, written), ("身份锚点：x；毛发：束发", ["剑始终在右手", "战袍不变色"]))
        self.assertEqual(character_locks.locks_of("短发，灰色T恤"), [])

    def test_the_lock_line_survives_a_long_appearance(self):
        long_card = "身份锚点：" + "、".join(f"特征{i}" for i in range(60)) + "；禁用项：长剑始终在右手"
        line = appearance_lines({"林夏": long_card}, ["林夏"], "中景")
        self.assertTrue(line.endswith("不许变：长剑始终在右手。"))
        self.assertNotIn("禁用项", line)


if __name__ == "__main__":
    unittest.main()
