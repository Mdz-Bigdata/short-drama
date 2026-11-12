# -*- coding: utf-8 -*-
"""因果链：分集大纲的节点之间连「所以」，总导演和编剧都读同一份写法。"""

import unittest

from app.core import agent_council, prompt_data
from app.core.production_knowledge import load_section
from app.core.screenwriting.prompts import build_outline_plan_prompt
from app.service import screenwriting_service


class CausalChainTests(unittest.TestCase):
    def test_the_outline_plan_asks_beats_to_follow_from_each_other(self):
        prompt = build_outline_plan_prompt(
            title="t", director_plan="plan", overview={"synopsis": "s"}, first=1, last=2, total=2,
            context_entries=[], target_seconds=90, instructions=None,
        )
        rule = prompt_data.text("causal_chain", "outline_rule")
        self.assertIn(rule, prompt)
        self.assertIn("「所以」不是「然后」", prompt)
        # 规则跟在规划规则里，不在原文或策划方案里
        self.assertLess(prompt.index("# 规划规则"), prompt.index(rule), prompt.index("# 总导演策划方案"))

    def test_the_guide_is_registered_and_readable_whole(self):
        guide = load_section("causal-chain-craft", budget=0)
        for heading in ("节点之间先连「所以」", "改变了什么", "选择参与进来", "写完一场过三问", "删中间那场"):
            self.assertIn(heading, guide)

    def test_the_writer_reads_it_while_writing_but_not_while_drawing_or_extracting(self):
        label = "因果链（节点之间连「所以」"
        self.assertIn(label, screenwriting_service.writer_system_prompt("role", stage="write"))
        self.assertNotIn(label, screenwriting_service.writer_system_prompt("role", stage="visual"))
        self.assertNotIn(label, screenwriting_service.writer_system_prompt("role", stage="extract"))

    def test_the_council_owns_it_under_story_causality(self):
        capability = next(item for item in agent_council.CAPABILITIES if item.id == "story_causality")
        self.assertTrue(any("causal-chain-craft" in source for source in capability.source_files), capability.source_files)


if __name__ == "__main__":
    unittest.main()
