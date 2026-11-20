"""The script structure chosen at creation (三幕式, 英雄旅程 …) reaches the stage-1 director and the episode planner.

No model is called: the rules are rendered and the planner's request is built and read.
"""

import unittest

from app.core import script_structure
from app.core.screenwriting.prompts import build_outline_plan_prompt


def creation(key, **extra):
    return {"creation_mode": "drama", "script_structure": key, **extra}


class DirectorTest(unittest.TestCase):
    def test_a_chosen_structure_is_how_the_whole_outline_is_built(self):
        rule = script_structure.director_rule(creation("five_act"))
        self.assertIn("五幕式", rule)
        self.assertIn("三幕大纲", rule, "the default three-act wording is redirected to the chosen structure")

    def test_nothing_chosen_an_advert_or_an_uploaded_script_adds_nothing(self):
        self.assertEqual(script_structure.director_rule(creation("")), "")
        self.assertEqual(script_structure.director_rule(creation("unknown")), "")
        self.assertEqual(script_structure.director_rule(creation("three_act", creation_mode="ad")), "")
        self.assertEqual(script_structure.director_rule(creation("three_act", script_content="1-1 …")), "")
        self.assertTrue(script_structure.director_rule(creation("circular", creation_mode="film")))


class PlannerTest(unittest.TestCase):
    def test_acts_become_episode_ranges_and_a_batch_hears_only_its_own(self):
        early = "".join(script_structure.outline_rules(creation("three_act"), first=1, last=10, total=70))
        middle = "".join(script_structure.outline_rules(creation("three_act"), first=31, last=40, total=70))
        self.assertIn("第一幕·建置(第 1–18 集)", early)
        self.assertNotIn("第二幕", early)
        self.assertIn("第二幕·对抗(第 19–52 集)", middle)
        self.assertNotIn("第一幕", middle)

    def test_every_part_gets_an_episode_and_the_last_ends_on_the_last_episode(self):
        for key in ("three_act", "five_act", "hero_journey", "seven_point", "fichtean"):
            for total in (10, 12, 30, 70, 100):
                parts = script_structure._table()[key]["parts"]
                spans = script_structure._spans(parts, total)
                self.assertEqual(spans[0][1], 1)
                self.assertEqual(spans[-1][2], total)
                for (_, start, end), (_, next_start, _) in zip(spans, spans[1:]):
                    self.assertLessEqual(start, end)
                    self.assertEqual(next_start, end + 1)

    def test_the_seven_point_and_crisis_structures_tell_the_director_and_each_batch_their_nodes(self):
        self.assertIn("七个节点", script_structure.director_rule(creation("seven_point")))
        self.assertIn("第一场戏主角已经身处危机", script_structure.director_rule(creation("fichtean")))
        opening = "".join(script_structure.outline_rules(creation("seven_point"), first=1, last=10, total=70))
        self.assertIn("开场钩子(第 1–4 集)", opening)
        self.assertNotIn("真相揭露", opening)
        late = "".join(script_structure.outline_rules(creation("fichtean"), first=31, last=45, total=60))
        self.assertIn("危机攀升(第 7–39 集)", late)
        self.assertIn("高潮(第 40–51 集)", late)
        self.assertNotIn("开场危机", late)
        self.assertEqual(script_structure.label("fichtean"), "费希特曲线")

    def test_fewer_episodes_than_parts_speaks_in_shares_of_the_film(self):
        text = "".join(script_structure.outline_rules(creation("hero_journey", creation_mode="film"), first=1, last=1, total=1))
        self.assertIn("约占全片", text)
        self.assertNotIn("第 1–", text)

    def test_structures_without_parts_give_their_rule_to_every_batch(self):
        lines = script_structure.outline_rules(creation("nonlinear"), first=21, last=30, total=60)
        self.assertEqual(len(lines), 1)
        self.assertIn("时间", lines[0])

    def test_the_rules_reach_the_episode_planners_request(self):
        rules = script_structure.outline_rules(creation("episodic"), first=1, last=5, total=20)
        prompt = build_outline_plan_prompt(
            title="t", director_plan="方案", overview=None, first=1, last=5, total=20, context_entries=[],
            target_seconds=90, instructions="", cast=None, creation_mode="drama", audience_rules=rules,
        )
        self.assertIn("本剧用单元结构", prompt)


if __name__ == "__main__":
    unittest.main()
