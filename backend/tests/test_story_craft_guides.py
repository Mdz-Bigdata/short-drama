"""剧本与分镜的手艺章节：主角拷问与人物关系进编剧提示词，高张力镜头只给高张力场次。"""

import unittest

from app.core import prompt_data
from app.core.scene_tension import looks_tense, tension_hits
from app.service import screenwriting_service as screenwriting


class WriterCraftTests(unittest.TestCase):
    def test_the_writer_is_asked_to_interrogate_the_lead_and_build_relationships(self):
        prompt = screenwriting.writer_system_prompt("你是编剧。", stage="write")
        self.assertIn("主角拷问与人物关系架法", prompt)
        self.assertIn("致命的软肋", prompt)
        self.assertIn("一部戏只有一条主线", prompt)

    def test_the_extraction_calls_do_not_pay_for_it(self):
        self.assertNotIn("致命的软肋", screenwriting.writer_system_prompt("你是编剧。", stage="extract"))


class SceneTensionTests(unittest.TestCase):
    def test_a_standoff_reads_as_tense(self):
        scene = "陆行远步步紧逼，把她逼到墙角，冷笑着质问账本的下落；两人对视，屋里一片死寂。"
        self.assertTrue(looks_tense(scene))
        self.assertGreaterEqual(len(tension_hits(scene)), 2)

    def test_tension_written_into_hands_and_blades_reads_as_tense(self):
        # 剧本不写心理：她的张力在手上和刀上。
        self.assertTrue(looks_tense("裘三娘没有向前一步，只把左手移到腰间刀柄上，五指一根根收紧，指节顶出白痕。"))

    def test_an_everyday_scene_does_not(self):
        self.assertFalse(looks_tense("清晨的早点铺，她给弟弟盛了一碗豆浆，两人说说笑笑地出门上学。"))
        self.assertFalse(looks_tense("他沉默地吃完了面。"), "one word alone is not enough")


class StoryboardRuleTests(unittest.TestCase):
    def test_scale_is_written_with_a_reference_and_actions_as_a_chain(self):
        rules = prompt_data.text("storyboard_hard_rules", "text")
        self.assertIn("写画面里的参照物", rules)
        self.assertIn("抬手→停住半拍→转身", rules)


if __name__ == "__main__":
    unittest.main()
