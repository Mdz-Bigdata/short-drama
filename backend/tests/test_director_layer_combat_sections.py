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

    def test_every_layer_keeps_the_camera_sentence_rules(self):
        self.assertIn("camera-move/写法总则", _sections("她低声说：“我知道是你。”眼神发冷"))


if __name__ == "__main__":
    unittest.main()
