import unittest

from app.core.transition_catalog import (
    classify_transition_category,
    compose_transition,
    describe_transition,
    normalize_transition_type,
    transition_catalog,
    transition_label,
    uses_transition_grammar,
)


class TransitionCatalogTests(unittest.TestCase):
    def test_free_text_types_collapse_onto_the_editing_vocabulary(self):
        for raw, expected in (
            ("硬切", "cut"), ("声音先行硬切", "sound_bridge"), ("视线匹配硬切", "cut"), ("淡入淡出", "fade"),
            ("交叉叠化 2 秒", "dissolve"), ("闪白", "flash"), ("划像", "wipe"), ("匹配剪辑", "match_cut"),
            ("快切蒙太奇", "montage"), ("J-cut", "sound_bridge"), ("推拉转场", "push_pull"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_transition_type(raw), (expected, True))
        self.assertEqual(normalize_transition_type("随便写的"), ("cut", False))
        self.assertEqual(normalize_transition_type(""), ("cut", False))
        self.assertEqual(transition_label("dissolve"), "叠化")

    def test_media_categories_are_recognised_from_prose(self):
        self.assertEqual(classify_transition_category("衣袖拂过镜头后切换新场景"), "occlusion")
        self.assertEqual(classify_transition_category("镜头俯冲穿破云层"), "camera_move")
        self.assertEqual(classify_transition_category("女子转身，服饰时代全部改变"), "action")
        self.assertEqual(classify_transition_category("夜空劈下闪电"), "light")
        self.assertEqual(classify_transition_category("同一院落四季轮转"), "time")
        self.assertEqual(classify_transition_category("人物推开石门，门后是异境"), "space")
        self.assertEqual(classify_transition_category("普通对话"), "")

    def test_universal_formula_composes_a_transition_prompt(self):
        spec = compose_transition(
            "叠化", outgoing_action="沈砚抬手推开木窗", medium="窗帘被风拂过遮挡镜头",
            camera_move="镜头轻微推进", incoming_scene="十年后的同一间书房", light="暖黄烛光转为冷白晨光",
        )
        self.assertEqual((spec.kind, spec.kind_label, spec.category_label), ("dissolve", "叠化", "遮挡蒙太奇"))
        self.assertEqual(
            spec.prompt,
            "叠化（时间流逝、回忆过渡、季节变化）；前镜收尾：沈砚抬手推开木窗；转场媒介：窗帘被风拂过遮挡镜头；"
            "镜头运动：镜头轻微推进；切入：十年后的同一间书房；光影氛围：暖黄烛光转为冷白晨光",
        )
        self.assertIn("念旧", spec.emotions)
        bare = compose_transition("硬切")
        self.assertEqual(bare.prompt, "硬切（同场景动作衔接、正反打、节奏推进）")

    def test_describe_and_grammar_helpers(self):
        self.assertEqual(describe_transition("声音先行硬切"), "声音先行：悬疑、回忆、梦境；声音先于画面进入（暗流、期待）；媒介类别：电影高级叙事")
        self.assertIn("未在转场词典内，按硬切处理", describe_transition("随便写的"))
        self.assertTrue(uses_transition_grammar("转场媒介：衣袖"))
        self.assertFalse(uses_transition_grammar("人物走向窗边"))
        catalog = transition_catalog()
        self.assertEqual(len(catalog["types"]), 9)
        self.assertEqual(len(catalog["categories"]), 9)


if __name__ == "__main__":
    unittest.main()
