"""The dialogue pacing rule: the model judges each line's pace and gives the shot time to play it out."""

import json
import unittest
from pathlib import Path

from app.core import acting
from app.core.screenwriting.prompts import build_script_plan_prompt

COMMON = dict(
    episode=1, overview=None, style="", characters={}, scenes={}, props={}, supported_durations=[5, 10, 15], default_duration=None,
    episode_target_seconds=None, episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None,
)
RULE = "根据剧情、人物关系、情绪、动作和环境声，自主判断每句对白的快慢、停顿与留白"
NO_SPEED_UP = "不要为了塞进较短时长而刻意加速"


class PacingRuleTests(unittest.TestCase):
    def test_the_shot_plan_prompt_carries_the_rule_for_every_source(self):
        for kind in ("outline", "novel", "screenplay"):
            prompt = build_script_plan_prompt(source_text="原文", source_kind=kind, **COMMON)
            utterances = next(line for line in prompt.splitlines() if line.startswith("- **utterances**："))
            self.assertIn(RULE, utterances, kind)
            self.assertIn("选择足够的 duration_seconds 让表演自然完成", utterances, kind)
            self.assertIn(NO_SPEED_UP, utterances, kind)
            self.assertIn("内容确实需要多个视觉画面时，才拆成连续场景", utterances, kind)
            # The duration field still sets the floor: lines never squeezed into a tier too short to say them.
            self.assertIn("台词永不把时长压到念不完的短档", prompt, kind)

    def test_a_finished_screenplay_keeps_every_word(self):
        screenplay = build_script_plan_prompt(source_text="原文", source_kind="screenplay", **COMMON)
        self.assertIn("在逐字保留台词的前提下", screenplay)
        self.assertIn("不要仅为满足固定字数预算而改写原台词", screenplay)
        written = build_script_plan_prompt(source_text="大纲", source_kind="outline", **COMMON)
        self.assertNotIn("在逐字保留台词的前提下", written)
        self.assertEqual(acting.pacing_rule().count("**对白表演节奏**"), 1)

    def test_the_storyboard_prompts_carry_it_too(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "prompt" / "agent_prompts.json").read_text("utf-8"))
        for key in ("storyboard_script_prompt", "video_storyboard_prompt"):
            self.assertIn(RULE, data[key], key)
            self.assertIn(NO_SPEED_UP, data[key], key)
        timing = data["video_storyboard_prompt"].split("二、台词时长判断规则", 1)[1].split("三、", 1)[0]
        self.assertIn("让表演自然完成", timing)


if __name__ == "__main__":
    unittest.main()
