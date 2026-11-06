import unittest

from app.core import knowledge_registry
from app.core import seedance_video_director as director

SEEDANCE_25 = "doubao-seedance-2-5-260128"


def _sections(prompt: str) -> list[str]:
    director.reset_seedance_director_cache()
    return list(director.build_director_layer(video_model=SEEDANCE_25, duration=8, prompt=prompt).sections)


class CombatSectionsTests(unittest.TestCase):
    """打戏才带打斗运镜手册；玄幻打戏再加能量形态、尺度与收束协议；文戏两者都不带。"""

    def setUp(self):
        if not director.skill_installed():
            self.skipTest("seedance-2-5-video-director 未安装")

    def test_the_new_references_are_registered(self):
        for key in ("combat-camera-handbook", "xianxia-combat-vfx", "camera-move-library", "episode-hook-ladder"):
            item = knowledge_registry.section(key)
            self.assertIsNotNone(item, key)
            self.assertTrue(item.path.is_file(), key)

    def test_a_xianxia_fight_gets_both_fight_references(self):
        sections = _sections("剑修御剑劈出剑气，对手以法阵格挡，两人拳脚对撞后大招爆发")
        for name in ("combat/核心原则", "xianxia/能量四态", "xianxia/收束协议", "xianxia/尺度四件套"):
            self.assertIn(name, sections)

    def test_energy_words_alone_mark_a_xianxia_fight(self):
        """冒牌天帝试拍那条：没写"仙/剑气"，只有刀气、雷柱、紫电——也是玄幻打戏。"""
        sections = _sections("殷无咎反手劈出一道紫电刀气横斩陆昭，雷柱砸落把刀气劈碎，冲击波把他震退三步")
        self.assertIn("xianxia/能量四态", sections)

    def test_a_street_fight_gets_camera_rules_but_no_xianxia(self):
        sections = _sections("两人在巷子里拳脚互打，一人被踢倒撞上墙")
        self.assertIn("combat/核心原则", sections)
        self.assertFalse(any(name.startswith("xianxia/") for name in sections))

    def test_a_xianxia_scene_without_a_fight_stays_quiet(self):
        sections = _sections("仙门山巅，她御剑落在云海边，回头看了他一眼")
        self.assertFalse(any(name.startswith(("combat/", "xianxia/")) for name in sections))

    def test_a_duel_gets_the_single_fight_camera_dictionary(self):
        director.reset_seedance_director_cache()
        layer = director.build_director_layer(video_model=SEEDANCE_25, duration=8, prompt="两人在巷子里拳脚互打，一人被踢倒撞上墙")

        self.assertIn("combat/单挑机位公式", layer.sections)
        self.assertNotIn("combat/割草专章", layer.sections)
        for entry in ("旋身攻击", "破门而入", "跃起下压", "翻滚闪避", "格挡震手", "压迫长镜", "胜负环绕"):
            self.assertIn(entry, layer.text, entry)

    def test_a_mass_battle_gets_the_mow_down_table_and_its_extras_rules(self):
        director.reset_seedance_director_cache()
        layer = director.build_director_layer(
            video_model=SEEDANCE_25, duration=8, prompt="他一人杀入敌群，长刀横斩，杂兵成片击飞",
        )

        self.assertIn("combat/割草专章", layer.sections)
        self.assertNotIn("combat/单挑机位公式", layer.sections)
        for rule in ("没有清晰五官的模糊剪影", "只减不增", "不从画外补人", "不起身再战", "群像甩焦"):
            self.assertIn(rule, layer.text, rule)

    def test_the_handbook_no_longer_asks_for_a_freeze_on_every_hit(self):
        """shot_table_rules 把「凝滞」判成模型做不到的定格；手册里的命中处理改成接触后震一次。"""
        text = knowledge_registry.section("combat-camera-handbook").path.read_text(encoding="utf-8")

        self.assertNotIn("凝滞", text)
        self.assertIn("4–6 秒 1–2 个，7–10 秒 2–3 个，11–15 秒 3–5 个", text)

    def test_the_precedence_note_asks_for_few_positively_worded_exclusions(self):
        director.reset_seedance_director_cache()
        layer = director.build_director_layer(video_model=SEEDANCE_25, duration=8, prompt="她低头看信")

        self.assertIn("排除项少而精、尽量正着说", layer.text)
        self.assertIn("被排除的那个名词不在正文里重复出现", layer.text)

    def test_every_layer_keeps_the_camera_sentence_rules(self):
        self.assertIn("camera-move/写法总则", _sections("她低声说：“我知道是你。”眼神发冷"))


if __name__ == "__main__":
    unittest.main()
