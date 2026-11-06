# -*- coding: utf-8 -*-
"""The classics behind xianxia and wuxia writing (诸子、史记、佛经、理学心学): on the shelf, findable, and public domain."""

import unittest

from app.core import poetry_library

# Added for 仙侠/武侠 writing, by collection id.
COLLECTIONS = ("xunzi", "mozi", "hanfeizi", "liezi", "shiji", "fojing", "zhangzai", "wangyangming")

# Lines a writer reaches for, and the collection each must come from.
LINES = (
    ("xunzi", "锲而不舍，金石可镂"),
    ("xunzi", "制天命而用之"),
    ("mozi", "义不杀少而杀众"),
    ("hanfeizi", "儒以文乱法，侠以武犯禁"),
    ("liezi", "子子孙孙无穷匮也"),
    ("shiji", "士为知己者死"),
    ("shiji", "风萧萧兮易水寒"),
    ("fojing", "色即是空，空即是色"),
    ("fojing", "本来无一物，何处惹尘埃"),
    ("zhangzai", "为万世开太平"),
    ("zhangzai", "民吾同胞，物吾与也"),
    ("wangyangming", "知是行的主意，行是知的功夫"),
    ("lunyu", "克己复礼为仁"),
    ("lunyu", "以直报怨，以德报德"),
    ("mengzi", "虽千万人吾往矣"),
    ("zhuangzi", "有天子剑，有诸侯剑，有庶人剑"),
    ("zhuangzi", "天地与我并生，而万物与我为一"),
    ("du-fu", "一舞剑器动四方"),
)


class ClassicsTests(unittest.TestCase):
    def setUp(self):
        poetry_library.reset()
        self.lib = poetry_library.library()

    def test_the_collections_are_on_the_shelf_and_public_domain(self):
        for name in COLLECTIONS:
            with self.subTest(name):
                poems = self.lib.by_collection(name)
                self.assertTrue(poems, name)
                self.assertTrue(all(poem.entry.rights == "public_domain" for poem in poems))

    def test_the_lines_people_quote_are_in_the_right_place(self):
        for collection, line in LINES:
            with self.subTest(line):
                texts = [poem.entry.text for poem in self.lib.by_collection(collection)]
                flat = [poetry_library._normal(text) for text in texts]
                self.assertTrue(any(poetry_library._normal(line) in text for text in flat), line)

    def test_a_writer_can_name_them(self):
        for name in ("荀子", "墨子", "韩非子", "列子", "史记", "心经", "坛经", "张载", "王阳明"):
            with self.subTest(name):
                poems, unknown = poetry_library.resolve_sources([name], self.lib)
                self.assertEqual(unknown, [])
                self.assertTrue(poems)

    def test_searching_the_genre_finds_them(self):
        self.assertIn("游侠列传·序（节选）", [poem.title for poem in poetry_library.search("游侠", limit=20)])
        self.assertIn("说剑", [poem.title for poem in poetry_library.search("天子剑", limit=20)])
        # The genre note lives on the collection profile, not on every entry, so it does not pull unrelated works into a search.
        self.assertNotIn("颜渊·克己复礼", [poem.title for poem in poetry_library.search("剑客", limit=20)])

    def test_the_corrected_readings_stay_corrected(self):
        xian_wen = poetry_library.find_titled("宪问·以直报怨", lib=self.lib)[0].entry
        self.assertNotIn("以德报怨，以德报德", xian_wen.text)
        xi_ming = poetry_library.find_titled("西铭", lib=self.lib)[0].entry.text
        self.assertTrue(xi_ming.startswith("乾称父"))
        self.assertNotIn("伪", xi_ming)
        shuo_jian = poetry_library.find_titled("说剑", lib=self.lib)[0].entry.text
        self.assertNotIn("（", shuo_jian)


if __name__ == "__main__":
    unittest.main()
