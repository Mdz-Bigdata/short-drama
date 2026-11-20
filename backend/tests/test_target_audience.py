"""A serial is written for a chosen audience: 男频 / 女频 and an age band, told to the director and the episode planner."""

import tempfile
import unittest
from pathlib import Path

from app.core import prompt_data, target_audience
from app.core.screenwriting.prompts import build_anchored_plan_prompt, build_outline_plan_prompt
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service import screenwriting_service
from app.service.drama_service import DramaService

MALE = prompt_data.value("target_audience", "leans")["male"]
FEMALE = prompt_data.value("target_audience", "leans")["female"]


def _outline(audience_rules, *, first=1, total=30):
    return build_outline_plan_prompt(
        title="t", director_plan="plan", overview={"synopsis": "s"}, first=first, last=first + 1, total=total,
        context_entries=[], target_seconds=90, instructions=None, audience_rules=audience_rules,
    )


class RulesTest(unittest.TestCase):
    def test_unknown_values_read_as_not_chosen(self):
        self.assertEqual(target_audience.normalize({"lean": "both", "age": "kids"}), {"lean": "", "age": ""})
        self.assertEqual(target_audience.normalize(None), {"lean": "", "age": ""})
        self.assertEqual(target_audience.normalize({"lean": "female", "age": "senior"}), {"lean": "female", "age": "senior"})

    def test_the_director_writes_for_the_chosen_audience_or_decides_one(self):
        chosen = target_audience.director_rule({"creation_mode": "drama", "target_audience": {"lean": "male", "age": "youth"}})
        self.assertIn("男频的青年观众", chosen)
        self.assertIn(MALE["opening"], chosen)
        self.assertNotIn(FEMALE["opening"], chosen)
        open_choice = target_audience.director_rule({"creation_mode": "narration"})
        self.assertIn("目标用户：……", open_choice)
        self.assertIn(MALE["opening"], open_choice)
        self.assertIn(FEMALE["opening"], open_choice)

    def test_a_short_film_or_an_advert_gets_nothing(self):
        for mode in ("film", "ad"):
            config = {"creation_mode": mode, "target_audience": {"lean": "male"}}
            self.assertEqual(target_audience.director_rule(config), "")
            self.assertEqual(target_audience.outline_rules(config, first=1, total=1), [])
            self.assertEqual(target_audience.adaptation_rules(config, opens_series=True), [])

    def test_opening_rules_only_where_the_first_three_episodes_are_planned(self):
        creation = {"creation_mode": "drama", "target_audience": {"lean": "female", "age": "adult"}}
        early = "\n".join(target_audience.outline_rules(creation, first=1, total=60))
        later = "\n".join(target_audience.outline_rules(creation, first=11, total=60))
        self.assertIn(FEMALE["opening"], early)
        self.assertIn("全剧 60 集", early)
        self.assertIn("世界观", early)
        self.assertNotIn(FEMALE["opening"], later)
        self.assertIn(FEMALE["keep"], later)
        self.assertIn("青中年", later)
        self.assertNotIn("主线", later)

    def test_a_novel_gets_only_a_chosen_lean_and_never_the_main_line_rules(self):
        creation = {"creation_mode": "drama", "target_audience": {"lean": "male"}}
        first = "\n".join(target_audience.adaptation_rules(creation, opens_series=True))
        self.assertIn(MALE["opening"], first)
        self.assertNotIn("主线：", first)
        self.assertNotIn(MALE["opening"], "\n".join(target_audience.adaptation_rules(creation, opens_series=False)))
        self.assertEqual(target_audience.adaptation_rules({"creation_mode": "drama"}, opens_series=True), [])


class PromptTest(unittest.TestCase):
    def test_the_outline_prompt_carries_the_rules_among_its_planning_rules(self):
        rules = target_audience.outline_rules({"creation_mode": "drama", "target_audience": {"lean": "male"}}, first=1, total=30)
        prompt = _outline(rules)
        self.assertIn(MALE["opening"], prompt)
        self.assertLess(prompt.index("# 规划规则"), prompt.index(MALE["opening"]), prompt.index("# 总导演策划方案"))

    def test_without_rules_the_prompts_are_unchanged(self):
        self.assertEqual(_outline(()), build_outline_plan_prompt(
            title="t", director_plan="plan", overview={"synopsis": "s"}, first=1, last=2, total=30,
            context_entries=[], target_seconds=90, instructions=None,
        ))
        common = dict(window="原文", window_is_final=True, overview={}, source_kind="novel", context_entries=[],
                      target_volume=None, max_episodes=3, remaining_episodes=None, instructions=None, opens_series=True)
        self.assertEqual(build_anchored_plan_prompt(**common), build_anchored_plan_prompt(**common, audience_rules=()))
        rules = target_audience.adaptation_rules({"creation_mode": "drama", "target_audience": {"lean": "female"}}, opens_series=True)
        self.assertIn(FEMALE["opening"], build_anchored_plan_prompt(**common, audience_rules=rules))

    def test_the_engine_plans_with_the_projects_audience(self):
        prompts = []

        def model(*args, **kwargs):
            prompts.append("\n".join(str(part) for part in (*args, *kwargs.values())))
            return ""

        config = {"creation_mode": "drama", "llm_model": "m", "video_model": "seedance2.0", "target_audience": {"lean": "female", "age": "senior"}}
        engine = screenwriting_service.build_engine(model, config=config, title="t", system_prompt="S")
        self.assertEqual(engine.creation["target_audience"], {"lean": "female", "age": "senior"})
        try:
            engine._plan_outline_batch({"director_plan": "plan", "overview": {"synopsis": "s"}}, 1, 2, total=20, earlier=[])
        except Exception:  # noqa: BLE001 - an empty answer ends the batch; the prompt is what is checked
            pass
        plan = next(p for p in prompts if "# 总导演策划方案" in p)
        self.assertIn(FEMALE["opening"], plan)
        self.assertIn("中老年", plan)


class ProjectTest(unittest.TestCase):
    def test_a_project_stores_its_audience(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            chosen = service.create_task(DramaCreateRequest(titleSuggestion="一部剧", targetAudience={"lean": "male", "age": "youth"}), owner_user_id="u1")
            unset = service.create_task(DramaCreateRequest(titleSuggestion="另一部剧"), owner_user_id="u1")
            self.assertEqual(service.repo.get_task(chosen["task_id"])["config"]["target_audience"], {"lean": "male", "age": "youth"})
            self.assertEqual(service.repo.get_task(unset["task_id"])["config"]["target_audience"], {"lean": "", "age": ""})
            # The eight-agent brief names the chosen audience instead of the generic default.
            self.assertEqual(service.repo.get_task(chosen["task_id"])["assets"]["agent_council"]["request"]["audience"], "男频的青年观众")
        with self.assertRaises(ValueError):
            DramaCreateRequest(titleSuggestion="一部剧", targetAudience={"lean": "kids"})


if __name__ == "__main__":
    unittest.main()
