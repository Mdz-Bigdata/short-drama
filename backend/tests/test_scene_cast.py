# -*- coding: utf-8 -*-
"""剧本只描述外貌、没写名字的出场角色，按他的定妆图(表演妆造)认出来，定妆照和妆造才进得了提示词。"""

import unittest

from app.core import scene_cast
from app.core.character_variants import LOOK_SOURCE


def _look(of: str, label: str) -> dict:
    return {"kind": "actor", "name": f"{of}·{label}", "metadata": {"variant": {"of": of, "label": label, "source": LOOK_SOURCE}}}


VARIANTS = {
    "阿箬": [_look("阿箬", "药白药堂长衣·右腕药渍")],
    "陈三": [_look("陈三", "铁灰铁匠短褐·左颧旧烫斑·左臂截断残端")],
    "沈九": [_look("沈九", "洗白旧麻青短褐·眉骨旧疤·左肩旧疤")],
}
E1S11 = "偏殿供桌 清晨 内景 画面：药白素衣的年轻女子被人从人群里推出半步，腕上一片深色药渍。她低头，手指绞住袖口。"


class DescribedCastTests(unittest.TestCase):
    def test_an_unnamed_woman_in_her_look_is_recognised(self):
        self.assertEqual(scene_cast.described(E1S11, VARIANTS, []), ["阿箬"])

    def test_one_shared_or_common_word_is_not_enough(self):
        self.assertEqual(scene_cast.described("墙上挂着一件短褐，地上一片深色水渍。", VARIANTS, []), [], "「短褐」两人都穿")
        self.assertEqual(scene_cast.described("药碗里还剩一点药渍。", VARIANTS, []), [], "只命中一个词")

    def test_people_already_in_the_scene_are_not_added_again(self):
        self.assertEqual(scene_cast.described(E1S11, VARIANTS, ["阿箬"]), [])

    def test_only_looks_count(self):
        plain = {"阿箬": [{"kind": "actor", "name": "阿箬·少年", "metadata": {"variant": {"of": "阿箬", "label": "药白药渍", "source": "manual"}}}]}
        self.assertEqual(scene_cast.described(E1S11, plain, []), [])


if __name__ == "__main__":
    unittest.main()
