# -*- coding: utf-8 -*-
"""拳种谱：点了名的拳种落成看得见的打法；以及同一批外部技能里补进来的物理因果几条和银黑 CG 画风。"""

import unittest

from app.core import canvas_tools, prompt_data, seedance_video_director, style_moves, weapon_moves


class StyleMovesTests(unittest.TestCase):
    def test_a_scene_that_names_an_art_gets_its_moves_as_things_a_camera_can_see(self):
        brief = style_moves.style_brief("沈砚以咏春黐手贴住来拳，对面一记贴山靠撞进怀里")
        self.assertTrue(brief.startswith("【拳种谱】"))
        self.assertIn("- 咏春：", brief)
        self.assertIn("- 八极拳：", brief)
        self.assertNotIn("- 太极拳：", brief)
        # Not bare move names: the entry says how the body goes.
        self.assertIn("沿身体中线", brief)
        self.assertIn("跺地震脚", brief)

    def test_a_fight_the_script_already_choreographed_is_filmed_as_written(self):
        named = "沈无咎用咏春贴身抢攻，陈九以八极拳硬接，两人交手数招，沈无咎被一记重击撞退到旗杆下"
        scripted = "沈无咎以咏春黐手粘住陈九的来拳，一掌拍偏他的前臂，另一拳沿中线打在他胸口；陈九一记八极拳的贴山靠撞向他怀里"
        self.assertFalse(style_moves.choreographed(named))
        self.assertTrue(style_moves.choreographed(scripted))
        self.assertIn("- 咏春：", style_moves.style_brief(named))
        # The art is named here too, but the moves are the script's: nothing is laid over them.
        self.assertEqual(style_moves.styles_in(scripted), ["八极拳", "咏春"])
        self.assertEqual(style_moves.style_brief(scripted), "")
        self.assertEqual(style_moves.style_brief(scripted, "- 沈无咎：咏春", ["沈无咎"]), "")
        self.assertIn("照剧本写", prompt_data.text("style_moves", "lead"))

    def test_an_art_is_only_read_off_its_name_never_guessed_from_a_punch_or_a_kick(self):
        self.assertEqual(style_moves.style_brief("他一拳打在对方胸口，又补了一脚，两人摔成一团"), "")
        self.assertEqual(style_moves.styles_in("剑冢前，他挥剑劈下"), [])
        self.assertEqual(style_moves.style_brief(""), "")

    def test_the_fighters_card_in_the_plan_names_the_art_for_the_people_in_this_scene_only(self):
        plan = "【打法卡】\n- 韩九：八极拳出身，右膝旧伤\n- 柳七：练太极拳的账房\n"
        self.assertEqual(style_moves.styles_in("两人在渡口交手", plan, ["韩九", "沈青禾"]), ["八极拳"])
        self.assertEqual(style_moves.styles_in("两人在渡口交手", plan, [{"name": "柳七"}]), ["太极拳"])
        self.assertEqual(style_moves.styles_in("两人在渡口交手", plan, []), [])
        self.assertEqual(style_moves.cast_lines(plan, ["韩九"]), "- 韩九：八极拳出身，右膝旧伤")

    def test_what_does_not_fit_is_left_out_whole_and_the_table_is_sound(self):
        data = prompt_data.load("style_moves")
        everything = "，".join(item["name"] for item in data["styles"])
        brief = style_moves.style_brief(everything)
        self.assertLessEqual(len(brief), data["budget"])
        self.assertTrue(all(line.endswith(tuple(item["moves"][-6:] for item in data["styles"])) for line in brief.splitlines()[1:]), "no line is cut mid-sentence")
        names = [item["name"] for item in data["styles"]]
        self.assertEqual(len(names), len(set(names)))
        seen: dict[str, str] = {}
        for item in data["styles"]:
            self.assertGreaterEqual(len(item["moves"]), 80, item["name"])
            for alias in item["aliases"]:
                self.assertGreaterEqual(len(alias), 2, f"{item['name']}: a one-character alias matches everything")
                self.assertNotIn(alias, seen, f"{alias} names both {seen.get(alias)} and {item['name']}")
                seen[alias] = item["name"]
        # 兵器在兵器谱，不在这里重复。
        self.assertFalse(set(names) & {str(item["name"]) for item in prompt_data.load("weapon_moves")["weapons"]})
        self.assertEqual(weapon_moves.weapons_in("咏春黐手"), [])

    def test_lightness_skill_keeps_a_foothold_under_every_lift(self):
        entry = next(item for item in prompt_data.load("style_moves")["styles"] if item["name"] == "轻功身法")
        self.assertIn("落脚点", entry["moves"])
        self.assertIn("不瞬间换位", entry["moves"])


class PhysicsAndLookTests(unittest.TestCase):
    def test_a_physical_beat_on_seedance_25_is_told_one_system_one_event_and_no_labels(self):
        layer = str(seedance_video_director.build_director_layer(
            video_model="doubao-seedance-2-5", duration=10, mode="first_frame", prompt="茶水泼到亚麻衬衫上，她后退撞翻了椅子",
        ))
        for words in ("One physical system for the whole frame", "One main physical event per beat", "Write what the viewer sees, not a label", "A material behaves like itself"):
            self.assertIn(words, layer)

    def test_the_style_wall_has_the_silver_black_game_cg_look(self):
        look = canvas_tools.style_look("cg_silver_black")
        self.assertIsNotNone(look)
        self.assertEqual(look.group, "动画")
        for words in ("银黑色调", "一处不到十分之一的点缀色", "强光源"):
            self.assertIn(words, look.prompt)
        self.assertLessEqual(len(look.prompt), 400)


if __name__ == "__main__":
    unittest.main()
