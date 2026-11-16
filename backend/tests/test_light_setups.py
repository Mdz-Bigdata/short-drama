# -*- coding: utf-8 -*-
"""Named lighting setups: the table is sound, the visual stage is told the ones its shots call for, clashes are hinted."""

import json
import unittest

from app.core import light_setups, prompt_data
from app.core.screenwriting import prompts
from tests.test_screenwriting_engine import FakeModel, _engine, _scene

_TABLE = prompt_data.load("light_setups")


class TableTests(unittest.TestCase):
    def test_every_setup_is_complete_and_only_names_setups_that_exist(self):
        names = light_setups.names()
        self.assertEqual(len(names), len(set(names)))
        for item in _TABLE["setups"]:
            with self.subTest(item["name"]):
                self.assertTrue(item["cues"] and item["marks"] and item["write"] and item["guard"])
                self.assertTrue(set(item["not_with"]) <= set(names) - {item["name"]})

    def test_the_content_of_the_shots_picks_the_setups_in_the_order_it_mentions_them(self):
        text = "祠堂 夜 内景 香案上两支烛火直晃。她走到窗边，月光落在算盘上。门缝里有人偷看。牢房里铁窗的影子。夕阳西下。"
        chosen = [item["name"] for item in light_setups.for_content(text)]
        self.assertEqual(chosen, ["烛火光", "单窗侧光", "月夜冷光", "缝隙光"], "the first four it mentions, no more")
        self.assertEqual(light_setups.for_content("两人在屋里说话。"), [])
        self.assertEqual(light_setups.guide("两人在屋里说话。"), "")

    def test_the_guide_says_how_to_write_it_what_not_to_stack_and_how_it_fails(self):
        guide = light_setups.guide("案上一支烛火。")
        self.assertIn("一个分镜只定一套主光", guide)
        self.assertIn("- 烛火光：暖橙色的火光轻轻跳动", guide)
        self.assertIn("别叠蓝调冷光、月夜冷光、条纹光、伦勃朗光", guide)
        self.assertIn("火苗写「不规则跳动」", guide)
        self.assertIn("- 胶片漏光：", light_setups.guide("她想起当年的旧事。"))
        self.assertNotIn("别叠；", light_setups.guide("她想起当年的旧事。"), "a setup with nothing to avoid says so by saying nothing")

    def test_two_setups_that_cancel_each_other_are_hinted_once(self):
        hints = light_setups.clashes("冷蓝月光从左上方照下，烛火暖光从右侧溢入")
        self.assertEqual(len(hints), 1)
        self.assertIn("「月夜冷光」和「烛火光」", hints[0])
        self.assertEqual(light_setups.clashes("左侧窗光约 4500K 斜照，暗部只有一点环境反光"), [])
        self.assertEqual(light_setups.clashes("夕阳暖金色侧光，发丝一圈极细的逆光金边"), [], "setups that go together are left alone")


class VisualStageTests(unittest.TestCase):
    def test_the_visual_prompt_carries_the_setups_its_shots_call_for(self):
        common = dict(episode=1, overview=None, style="写实", style_description="", characters={}, scenes={}, props={})
        lit = prompts.build_visual_prompt(content_scenes=[_scene(1, 1, scene_description="香案上两支烛火直晃。")], **common)
        plain = prompts.build_visual_prompt(content_scenes=[_scene(1, 1, scene_description="两人在屋里说话。")], **common)
        self.assertIn("- 烛火光：", lit)
        self.assertLess(lit.index("image_prompt.composition.lighting"), lit.index("- 烛火光："))
        self.assertLess(lit.index("- 烛火光："), lit.index("image_prompt.composition.ambiance"))
        self.assertNotIn("本批分镜用得上的光型", plain)

    def test_a_shot_lit_two_ways_gets_a_note_and_is_not_sent_back(self):
        class TwoLights(FakeModel):
            def __call__(self, system_prompt, user_prompt, max_tokens):
                answer = super().__call__(system_prompt, user_prompt, max_tokens)
                if "视觉生产层" in user_prompt:
                    data = json.loads(answer)
                    data["scenes"][0]["image_prompt"]["composition"]["lighting"] = "冷蓝月光从左上方照下，烛火暖光从右侧溢入"
                    return json.dumps(data, ensure_ascii=False)
                return answer

        model = TwoLights()
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)
        notes = [v for v in state["episodes"]["1"]["violations"] if v["code"] == "light_clash"]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["severity"], notes[0]["scene_id"]), ("warning", "E1S01"))
        self.assertEqual(len([c for c in model.calls if "视觉生产层" in c["prompt"]]), 1, "a note, not a second call")


class StoryboardStageTests(unittest.TestCase):
    """The storyboard writer never saw the skill's lighting chapter (it sits past the part that fits); it gets the short form."""

    def test_a_scene_is_told_the_few_setups_its_content_calls_for(self):
        brief = light_setups.scene_brief("祠堂 夜 香案上两支烛火直晃。她走到窗边，月光落在算盘上。门缝里有人偷看。牢房里铁窗的影子。")
        self.assertTrue(brief.startswith("【本场光型】"))
        self.assertIn("整场只定一套主光", brief)
        self.assertEqual([line.split("：")[0] for line in brief.splitlines()[1:]], ["- 烛火光", "- 单窗侧光", "- 月夜冷光"], "three at most for one scene")
        self.assertLess(len(brief), 700, "short enough to ride in a storyboard prompt")
        self.assertEqual(light_setups.scene_brief("两人在办公室里说话。"), "")

    def test_the_storyboard_prompt_carries_it_only_when_the_scene_calls_for_it(self):
        from app.service.drama_service import DramaService
        from tests.test_spatial_stage_pipeline import _generate, _task

        service = DramaService()
        quiet = _task("plain-1")
        quiet["assets"]["2_breakdown"]["scenes"][0]["content"] = "林夏和周教授在办公室里核对账目，桌上放着录音笔"
        plain: list = []
        _generate(service, quiet, "E1S01", plain)
        self.assertNotIn("【本场光型】", plain[0])

        task = _task("lit-1")
        task["assets"]["2_breakdown"]["scenes"][0]["content"] = "深夜，林夏在办公室与周教授对峙，桌上只点着一支蜡烛，烛火直晃"
        lit: list = []
        _generate(service, task, "E1S01", lit)
        self.assertIn("【本场光型】", lit[0])
        self.assertIn("- 烛火光：", lit[0])
        self.assertIn("- 分割光：", lit[0], "a confrontation calls for it too")

    def test_a_shot_whose_lighting_stacks_two_setups_is_hinted_in_the_table_audit(self):
        from app.core.shot_table_rules import audit_shot_table

        def shot(desc: str) -> dict:
            return {"shot_id": 1, "size": "中景", "motion": "固定镜头", "duration": "5秒", "characters": ["沈砚"], "desc": desc}

        stacked = audit_shot_table([shot("中景，沈砚立于画右。冷蓝月光从左上方照下，烛火暖光从右侧溢入，在他左颊打出明暗交界线。他抬手按住刀柄。")])
        clean = audit_shot_table([shot("中景，沈砚立于画右，案上一只未点的烛台。冷蓝月光从左上方照下，在他左颊打出明暗交界线。他抬手按住刀柄。")])
        self.assertIn("light_clash", [issue.rule for issue in stacked.issues])
        self.assertNotIn("light_clash", [issue.rule for issue in clean.issues], "a candlestick among the props is not a second light")
        self.assertNotIn("light_clash", [issue.rule for issue in stacked.issues if issue.severity == "error"])


if __name__ == "__main__":
    unittest.main()
