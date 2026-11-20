# -*- coding: utf-8 -*-
"""刀法谱、点了名的刀术流派和短刃：出品人 2026-11-20 给的十篇套路图解补进来的那一部分。

No model is called: the tables are read and the briefs rendered.
"""

import unittest
from pathlib import Path

from app.core import prompt_data, sabre_techniques, style_moves, weapon_moves

ROOT = Path(__file__).resolve().parents[2]
ADDED = ("点刀", "格刀", "按刀", "挑刀", "穿刀", "反刺", "背花", "换手")
SCHOOLS = ("追风刀", "火龙刀", "单剑刀", "查拳刀", "通背刀")


class SabreTableTests(unittest.TestCase):
    def test_the_table_is_sound(self):
        table = prompt_data.load("sabre_techniques")["techniques"]
        names = [item["name"] for item in table]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[-1], "收刀", "putting the sabre away closes the list")
        for name in ADDED:
            self.assertIn(name, names)
        seen: dict[str, str] = {}
        for item in table:
            self.assertGreaterEqual(len(item["how"]), 20, item["name"])
            self.assertTrue(item["use"], item["name"])
            for alias in item["aliases"]:
                self.assertGreaterEqual(len(alias), 2, f"{item['name']}: a one-character alias matches everything")
                self.assertNotIn(alias, seen, f"{alias} names both {seen.get(alias)} and {item['name']}")
                seen[alias] = item["name"]

    def test_only_the_techniques_the_scene_names_are_sent_and_only_when_a_sabre_is_there(self):
        scene = "裴仲玄挥刀逼近，提膝刀尖一点，沈无咎立刀一格，往下一压，反手刺他面门"
        self.assertEqual(sabre_techniques.techniques_in(scene), ["点刀", "格刀", "按刀", "反刺"])
        brief = sabre_techniques.technique_brief(scene)
        self.assertTrue(brief.startswith("【刀法】"))
        for words in ("- 点刀：手腕一抖", "- 格刀：刀竖起来", "另一只手的掌心按在刀背前段", "- 反刺：", "对刀的通则："):
            self.assertIn(words, brief)
        self.assertNotIn("- 挑刀：", brief)
        self.assertEqual(sabre_techniques.techniques_in("两人持棍，一人左格右格，立棍一格"), [], "the same words with another weapon are not sabre techniques")
        self.assertEqual(sabre_techniques.technique_brief("两人挥刀相斗，难分高下"), "", "a sabre fight that names no technique gets the sequence instead")

    def test_the_routines_own_names_for_the_old_techniques_are_read(self):
        # 套路图解管扎叫「直刺」、管斜着落的一刀叫「斜劈」、管腕花叫「剪腕」。
        self.assertEqual(sabre_techniques.techniques_in("他持刀弓步直刺，左右斜劈，收回时一个剪腕"), ["砍刀", "扎刀", "腕花"])
        self.assertEqual(sabre_techniques.techniques_in("单刀正撩接左截，提膝上架"), ["截刀", "撩刀", "架刀"])
        self.assertEqual(sabre_techniques.techniques_in("他挥刀抢上，刀交左手，一个背花，跃起下劈"), ["劈刀", "背花", "换手"])

    def test_everything_named_at_once_stays_inside_the_budget_and_no_line_is_cut(self):
        data = prompt_data.load("sabre_techniques")
        scene = "单刀 " + " ".join(item["aliases"][0] for item in data["techniques"])
        self.assertEqual(len(sabre_techniques.techniques_in(scene)), len(data["techniques"]))
        brief = sabre_techniques.technique_brief(scene)
        self.assertLessEqual(len(brief), data["budget"])
        self.assertTrue(brief.endswith(data["usage"]))
        ends = tuple(item["use"][-6:] for item in data["techniques"])
        self.assertTrue(all(line.endswith(ends) for line in brief.splitlines()[1:-1]))

    def test_the_storyboard_request_reads_the_sabre_table_for_fight_scenes(self):
        service = (ROOT / "backend" / "app" / "service" / "drama_service.py").read_text(encoding="utf-8")
        self.assertIn('sabre_techniques.technique_brief(scene_content) if scene_kind == "fight" else ""', service)


class SabreSchoolTests(unittest.TestCase):
    def test_a_named_sabre_school_is_told_as_what_the_camera_sees(self):
        brief = style_moves.style_brief("沈无咎使的是追风刀法，裴仲玄一手通背刀，两人在渡口交手")
        self.assertTrue(brief.startswith("【拳种谱】"))
        self.assertIn("- 追风刀：快、连、跳转多", brief)
        self.assertIn("- 通背刀：不跳不停，一步跟一步往前逼", brief)
        self.assertNotIn("- 火龙刀：", brief)
        # 只写了流派名的场次也认作有刀：流派说人怎么动，兵器谱说刀怎么走、怎么挡。
        for school in SCHOOLS:
            self.assertEqual(weapon_moves.weapons_in(f"他使的是{school}"), ["刀"], school)
        self.assertIn("- 刀：", weapon_moves.weapon_brief("沈无咎使的是追风刀法"))

    def test_a_school_whose_name_holds_a_technique_s_word_does_not_name_that_technique(self):
        # 「通背刀」里有「背刀」(藏刀的一种叫法)：点流派名不是点藏刀；真写了背刀照认。
        self.assertEqual(sabre_techniques.techniques_in("裴仲玄一手通背刀法，挥刀逼近"), [])
        self.assertEqual(sabre_techniques.technique_brief("沈无咎使追风刀法，裴仲玄一手通背刀，两人对峙"), "")
        self.assertEqual(sabre_techniques.techniques_in("裴仲玄一手通背刀法，背刀而立"), ["藏刀"])

    def test_the_fighters_card_names_the_school_for_the_people_in_this_scene(self):
        plan = "【打法卡】\n- 韩九：火龙刀出身，藏刀不露\n- 柳七：查拳刀法，跳步快\n"
        self.assertEqual(style_moves.styles_in("两人在渡口交手", plan, ["韩九"]), ["火龙刀"])
        self.assertEqual(style_moves.styles_in("两人在渡口交手", plan, ["柳七"]), ["查拳刀"])

    def test_a_fight_the_script_already_choreographed_is_filmed_as_written(self):
        scripted = "沈无咎以追风刀缠头转身，一刀劈在裴仲玄肩头，裴仲玄横刀架住，一脚踢中他小腹"
        self.assertTrue(style_moves.choreographed(scripted))
        self.assertEqual(style_moves.style_brief(scripted), "")

    def test_a_school_is_read_off_its_name_and_not_off_everyday_words(self):
        self.assertEqual(style_moves.styles_in("他低头检查刀刃，又查刀鞘上的缺口"), [])
        self.assertEqual(style_moves.styles_in("两人挥刀相斗，顺水推舟卖了个人情"), [])
        table = {item["name"]: item for item in prompt_data.load("style_moves")["styles"]}
        for name in SCHOOLS:
            self.assertGreaterEqual(len(table[name]["moves"]), 120, name)
            self.assertIn("对手", table[name]["moves"], f"{name}: how the one on the receiving end reacts")


class ShortBladeTests(unittest.TestCase):
    def test_a_short_blade_goes_in_and_out_and_takes_the_hand_of_a_longer_weapon_first(self):
        line = {str(item["name"]): str(item["moves"]) for item in prompt_data.load("weapon_moves")["weapons"]}["短刃"]
        for words in ("出刀就抽回", "先斜划他伸出来的手臂，沉身平划大腿，再直刺中路", "对长兵器不拼距离，先打他握兵器的手", "被划中先是一道细线"):
            self.assertIn(words, line)
        self.assertIn("出刀就抽回", weapon_moves.weapon_brief("她握着匕首贴了上去"))


if __name__ == "__main__":
    unittest.main()
