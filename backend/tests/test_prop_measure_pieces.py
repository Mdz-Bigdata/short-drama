"""A prop whose name ends in a measure word (「旧铜钥匙串」) is bound when the text writes it the usual way (「一串旧铜钥匙」).

Before, its pieces were only the endings of the full name (匙串, 钥匙串, 铜钥匙串), so 「那串旧铜钥匙」 bound nothing and the
clip went out without the prop's reference picture.
"""

import unittest

from app.core.storyboard_scene_context import name_pieces, named_by_noun

KEYS = {"name": "旧铜钥匙串", "kind": "prop"}
SWORD = {"name": "断水剑", "kind": "prop"}


class MeasureWordPiecesTest(unittest.TestCase):
    def test_the_name_without_its_measure_word_is_a_piece(self):
        pieces = name_pieces(KEYS)
        self.assertTrue({"旧铜钥匙", "铜钥匙", "钥匙", "钥匙串"} <= pieces)
        self.assertNotIn("旧铜钥匙串", pieces)

    def test_the_usual_wording_binds_it(self):
        for text in ("腰侧那串旧铜钥匙落在画面中央偏右", "前景右下旧铜钥匙虚化一角", "他把钥匙串塞回腰间"):
            with self.subTest(text=text):
                self.assertTrue(named_by_noun(KEYS, text, [KEYS, SWORD]))
        self.assertFalse(named_by_noun(KEYS, "雨落在旗杆上", [KEYS, SWORD]))

    def test_a_piece_two_props_share_still_binds_neither(self):
        other = {"name": "铜钥匙", "kind": "prop"}
        self.assertFalse(named_by_noun(KEYS, "桌上放着钥匙", [KEYS, other]))

    def test_names_without_a_trailing_measure_word_keep_their_pieces(self):
        self.assertEqual(name_pieces({"name": "墙角接雨木盆", "kind": "prop"}), name_pieces({"name": "墙角接雨木盆", "kind": "prop"}))
        self.assertNotIn("墙角接雨木", name_pieces({"name": "墙角接雨木盆", "kind": "prop"}))
        self.assertNotIn("钥", name_pieces({"name": "钥匙串", "kind": "prop"}))
        self.assertEqual(name_pieces({"name": "旧铜钥匙串", "kind": "actor"}), frozenset())


if __name__ == "__main__":
    unittest.main()
