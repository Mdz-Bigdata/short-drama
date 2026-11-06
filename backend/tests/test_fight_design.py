"""Fight episodes get fight-design rules in the writer's plan and visual layer; other episodes do not."""

import unittest

from app.core import fight_design
from app.core.screenwriting.prompts import build_script_plan_prompt, build_visual_prompt
from app.service.drama_service import DramaService

FIGHT = "雨夜屋顶，沈知微拔剑，与陆昀交手三合，刀剑相接，她被击退半步又反击。"
TALK = "沈知微与陆昀在正堂对峙，冲突一触即发，两人只是冷冷对视。"
XIANXIA = "殷无咎反手劈出一道紫电刀气横斩陆昭，雷柱砸落把刀气劈碎，冲击波把他震飞三丈。"


def _plan(source_text: str) -> str:
    return build_script_plan_prompt(
        source_text=source_text, source_kind="novel", episode=1, overview={}, style="写实",
        characters={"沈知微": {}, "陆昀": {}}, scenes={"屋顶": {}}, props={},
        supported_durations=[5, 10], default_duration=None, episode_target_seconds=None,
        episode_outline=None, next_episode_outline=None,
    )


def _visual(description: str) -> str:
    return build_visual_prompt(
        episode=1, overview={}, style="写实", style_description="电影感", characters={}, scenes={}, props={},
        content_scenes=[{"scene_id": "E1S01", "scene_description": description, "duration_seconds": 5}],
    )


class DetectionTests(unittest.TestCase):
    def test_a_fight_is_told_from_a_standoff(self):
        self.assertTrue(fight_design.looks_like_fight(FIGHT))
        self.assertFalse(fight_design.looks_like_fight(TALK), "conflict words alone are not a fight")
        self.assertFalse(fight_design.looks_like_fight("他拔剑。"), "one strong signal needs support")
        self.assertTrue(fight_design.looks_like_fight("他拔剑。", genre="wuxia"))

    def test_the_storyboard_stage_judges_a_fight_the_same_way(self):
        self.assertIs(DramaService.FIGHT_STRONG_SIGNALS, fight_design.STRONG_SIGNALS)
        self.assertIs(DramaService.FIGHT_WEAK_SIGNALS, fight_design.WEAK_SIGNALS)
        self.assertEqual(DramaService._detect_scene_kind(FIGHT), "fight")
        self.assertEqual(DramaService._detect_scene_kind(TALK), "general")
        self.assertEqual(DramaService._detect_scene_kind(TALK, action_intensity="high"), "fight")


class PromptTests(unittest.TestCase):
    def test_the_plan_carries_the_fight_rules_only_for_a_fight(self):
        plan = _plan(FIGHT)
        for phrase in ("先定因果再写招", "每人一套打法", "一打多不排队", "前置条件 → 发动 → 作用 → 结束", "台词嵌在攻防间隙"):
            self.assertIn(phrase, plan)
        self.assertNotIn("打戏设计", _plan(TALK))

    def test_the_visual_layer_writes_one_exchange_per_shot_for_a_fight(self):
        visual = _visual(FIGHT)
        self.assertIn("攻方动作 → 守方反应 → 接触结果 → 受力反馈 → 落点姿态", visual)
        self.assertIn("双方肢体与兵器轮廓分明", visual)
        self.assertNotIn("打斗分镜的视觉写法", _visual(TALK))

    def test_the_visual_layer_cuts_a_fight_by_its_length_and_never_into_one_second_pieces(self):
        visual = _visual(FIGHT)
        for phrase in ("4–6 秒分 1–2 段", "7–10 秒分 2–3 段", "11–15 秒分 3–5 段", "每段 2.5–4 秒"):
            self.assertIn(phrase, visual)
        # Impact frames, shake, blur and slow motion are rationed, not handed to every hit.
        for phrase in ("2–3 帧黑白或白闪冲击帧只给关键击与终结击", "镜头震动放在接触之后，只震一次", "接触点保持清晰", "慢动作只放在最后 1–2 秒"):
            self.assertIn(phrase, visual)

    def test_contact_is_written_as_a_point_on_a_path_with_its_simultaneous_details(self):
        visual = _visual(FIGHT)
        self.assertIn("起势 → 加速 → 接触 → 受力形变 → 继续推进 → 滑开 / 擦过 → 转入下一动作", visual)
        self.assertIn("句子不停在接触那一下", visual)
        self.assertIn("双方身体各自的反应", visual)

    def test_spacing_density_effects_camera_and_first_frame_reach_every_fight(self):
        visual = _visual(FIGHT)
        for phrase in (
            "至少半个身位", "接触点位于画面正中偏上",                      # spacing and screen position
            "第一次接触落在 1.5 秒前后", "流派节奏 × 交互力量档", "高手 ×1", "攻守易位",  # density
            "横斩扫出一道宽扇形", "上撩是向上扬起的月牙", "下劈是沉重的楔形", "轻击只溅火花", "每个角色固定一种特效颜色",
            "选跟随动作的运镜", "起势姿态",
            "不把要避开的那个名词再写一遍",
        ):
            self.assertIn(phrase, visual)
        self.assertNotIn("能量四态", visual, "the move-shape effects are not the xianxia block")

    def test_the_plan_sets_the_density_of_a_fight(self):
        plan = _plan(FIGHT)
        # 交锋多密不再是一个固定数，而是流派节奏 × 人物的交互力量档（exchange-unit-master）。
        self.assertIn("截拳道约 0.75 秒一个半单元", plan)
        self.assertIn("两个高手 9 秒至少过四招", plan)
        self.assertIn("第一次接触落在开场 1.5 秒前后", plan)


class XianxiaTests(unittest.TestCase):
    def test_an_energy_fight_is_a_fight_and_a_xianxia_one(self):
        self.assertTrue(fight_design.looks_like_fight(XIANXIA), "energy attacks alone still make a fight")
        self.assertTrue(fight_design.is_xianxia_fight(XIANXIA))
        self.assertFalse(fight_design.is_xianxia_fight(FIGHT), "a sword fight without energy is not xianxia")
        self.assertFalse(fight_design.is_xianxia_fight("仙门山巅，她御剑落在云海边，回头看了他一眼"), "xianxia without a fight")

    def test_the_plan_takes_the_rounds_and_the_ending_protocols_from_the_reference(self):
        plan = _plan(XIANXIA)
        self.assertIn("玄幻打戏补充", plan)
        self.assertIn("三轮攻守", plan)
        self.assertIn("遗物定场", plan)
        self.assertIn("原文或大纲已写定的胜负、出招顺序与结尾优先", plan)
        self.assertNotIn("能量四态", plan, "the energy look is the visual layer's job")
        self.assertNotIn("Seedance 2.5 写法", plan, "model syntax stays out of the writer's prompt")
        self.assertNotIn("玄幻打戏补充", _plan(FIGHT))

    def test_the_visual_layer_takes_the_energy_states_scale_and_close_exchanges(self):
        visual = _visual(XIANXIA)
        for phrase in ("能量四态", "尺度四件套", "近景对招", "色彩对冲"):
            self.assertIn(phrase, visual)
        self.assertNotIn("收束协议", visual)
        self.assertNotIn("能量四态", _visual(FIGHT))

    def test_the_director_layer_reads_the_same_xianxia_words(self):
        from app.core import seedance_video_director

        self.assertIs(seedance_video_director._XIANXIA_MARKERS, fight_design.XIANXIA_MARKERS)


if __name__ == "__main__":
    unittest.main()
