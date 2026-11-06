# -*- coding: utf-8 -*-
"""分集大纲不得推翻已定事实：模型校对一遍，有矛盾退回重规划一次，仍有就记警告。"""

import json
import re
import unittest
from unittest.mock import patch

from app.core.screenwriting import fact_check

OVERVIEW = {"title": "拭剑奴", "synopsis": "刀将落下的瞬间，他刚擦过的那把剑自己出鞘三寸，手没有断。", "thesis": "最难的不是拔剑，是承认自己也是刀。"}
LEDGER = [{"episode": 1, "title": "剑自鸣", "hook": "剑为什么出鞘？", "story_beats": ["【钩子】刀横在腕上", "【反转】刀落，断手滚落；同一瞬剑自鸣"]}]
FOUND = {"contradictions": [{"episode": 1, "beat": "刀落，断手滚落；同一瞬剑自鸣", "fact": "刀将落下的瞬间剑自己出鞘，手没有断", "fix": "刀未落，剑先出鞘，手保住"}]}


class PromptAndParseTests(unittest.TestCase):
    def test_the_facts_are_the_filled_overview_fields_and_the_plan_head(self):
        facts = fact_check.facts_text(OVERVIEW, "方案正文" * 100, 10)
        self.assertIn("故事梗概：刀将落下的瞬间", facts)
        self.assertIn("立意：最难的不是拔剑", facts)
        self.assertNotIn("母题", facts, "an empty field is not a fact")
        self.assertTrue(facts.endswith("方案正文方案正文方案"), "the plan is cut to the limit")
        prompt = fact_check.build_prompt(facts, LEDGER)
        self.assertIn("<facts>", prompt)
        self.assertIn("第 1 集《剑自鸣》", prompt)
        self.assertIn("- 【反转】刀落，断手滚落", prompt)

    def test_an_answer_is_read_and_a_bad_one_means_no_contradiction(self):
        answers = iter([json.dumps(FOUND, ensure_ascii=False), "我觉得没问题"])
        found = fact_check.check(lambda *a, **k: next(answers), facts="f", entries=LEDGER)
        self.assertEqual([item.fix for item in found], ["刀未落，剑先出鞘，手保住"])
        self.assertEqual(fact_check.check(lambda *a, **k: next(answers), facts="f", entries=LEDGER), [])
        self.assertIn("- 第 1 集「刀落，断手滚落；同一瞬剑自鸣」推翻了「刀将落下的瞬间剑自己出鞘，手没有断」：刀未落，剑先出鞘，手保住", fact_check.retry_block(found))
        self.assertIn("第 1-1 集分集大纲重规划后仍与已定事实相悖", fact_check.warning_text(1, 1, found))


def _engine_with(verdicts):
    """The engine tests' fake model, plus answers for the fact check: one verdict per check, in order."""
    from tests.test_screenwriting_engine import FakeModel, _engine

    class Model(FakeModel):
        def __init__(self):
            super().__init__()
            self.outline_prompts: list[str] = []
            self.verdicts = list(verdicts)

        def __call__(self, system_prompt, user_prompt, max_tokens):
            if "连续性校对" in system_prompt:
                self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
                return json.dumps(self.verdicts.pop(0), ensure_ascii=False)
            if "分集大纲" in user_prompt and "episodes 数组长度必须等于" in user_prompt:
                self.outline_prompts.append(user_prompt)
            return super().__call__(system_prompt, user_prompt, max_tokens)

    model = Model()
    return model, _engine(model)


class EngineTests(unittest.TestCase):
    def _write(self, engine):
        return engine.write(title="暗室回声", director_plan="总导演方案：林夏的手没有断。", episode_count=1, source_kind="outline")

    def test_a_contradicted_ledger_is_planned_again_with_the_reasons(self):
        model, engine = _engine_with([FOUND, {"contradictions": []}])
        with patch.dict("os.environ", {"SCREENWRITING_FACT_CHECK": "1"}):
            state = self._write(engine)
        self.assertEqual(len(model.outline_prompts), 2)
        self.assertIn("上一版大纲推翻了这些已定事实", model.outline_prompts[1])
        self.assertIn("刀未落，剑先出鞘，手保住", model.outline_prompts[1])
        self.assertEqual(state["warnings"], [])
        checks = [call for call in model.calls if "连续性校对" in call["system"]]
        self.assertEqual(len(checks), 2)
        self.assertIn("故事梗概：林夏追查实验室真相。", checks[0]["prompt"])
        self.assertIn("总导演方案：林夏的手没有断。", checks[0]["prompt"])

    def test_a_ledger_still_contradicting_after_one_retry_is_kept_with_a_warning(self):
        model, engine = _engine_with([FOUND, FOUND])
        with patch.dict("os.environ", {"SCREENWRITING_FACT_CHECK": "1"}):
            state = self._write(engine)
        self.assertEqual(len(model.outline_prompts), 2, "one retry, not a loop")
        [warning] = state["warnings"]
        self.assertTrue(re.match(r"第 1-1 集分集大纲重规划后仍与已定事实相悖", warning))
        self.assertIn("断手滚落", warning)

    def test_the_check_is_off_by_default_in_tests_and_costs_nothing(self):
        model, engine = _engine_with([])
        self._write(engine)
        self.assertEqual(len(model.outline_prompts), 1)
        self.assertFalse([call for call in model.calls if "连续性校对" in call["system"]])


if __name__ == "__main__":
    unittest.main()
