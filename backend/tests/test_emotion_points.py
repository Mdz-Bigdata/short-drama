# -*- coding: utf-8 -*-
"""情绪点类型表：钩子、冲突、反转、爽点、暖点、泪点、笑点、揭秘、悬念、抒情、信息交代。

写的人（分集大纲、分镜内容、编剧方法论）和查的人（结构化校验、分镜师上下文）用同一张表。
"""

import json
import unittest
from pathlib import Path

from app.core import emotion_points as ep
from app.core.screenwriting.models import EpisodeOutlineDraft, SceneContent
from app.core.screenwriting.prompts import build_outline_plan_prompt, build_script_plan_prompt
from app.core.storyboard_scene_context import compile_scene_context
from app.service.screenwriting_service import WRITER_METHODOLOGY

EXPECTED = ("钩子", "冲突", "反转", "爽点", "暖点", "泪点", "笑点", "揭秘", "悬念", "抒情", "信息交代")


class TaxonomyTests(unittest.TestCase):
    def test_the_table_holds_the_eleven_kinds_in_order_each_with_a_definition(self):
        self.assertEqual(ep.KINDS, EXPECTED)
        self.assertTrue(all(ep.DEFINITIONS[kind] for kind in EXPECTED))
        self.assertEqual(ep.INFORMATIONAL, frozenset({"信息交代"}))
        self.assertEqual(ep.names(), "、".join(EXPECTED))
        self.assertIn("爽点（压抑之后的释放", ep.menu())

    def test_a_beat_tag_is_read_from_either_bracket_style_and_normalised(self):
        self.assertEqual(ep.beat_kind("【钩子】她推门进来"), "钩子")
        self.assertEqual(ep.beat_kind("[反转] 信是假的"), "反转")
        self.assertEqual(ep.beat_kind("她推门进来"), "")
        self.assertTrue(ep.is_kind(" 爽点 "))
        self.assertFalse(ep.is_kind("燃"))
        self.assertEqual(ep.hits(["信息交代", "钩子", "钩子", "燃", ""]), ["钩子"])


class ValidationTests(unittest.TestCase):
    def test_only_a_kind_outside_the_table_sends_a_beat_or_a_shot_back(self):
        self.assertEqual(ep.beat_problems(["【钩子】她推门", "他坐下"]), [], "an untagged beat is not worth another call")
        [problem] = ep.beat_problems(["【燃】他冲出去"], label="第 2 集")
        self.assertIn("第 2 集：这些节点的情绪点类型不在表里", problem)
        self.assertIn("【燃】他冲出去", problem)
        self.assertEqual(ep.untagged_beats(["【钩子】a", "b"]), ["b"])
        shots = [{"scene_id": "E1S01", "emotion_point": "燃"}, {"scene_id": "E1S02", "emotion_point": ""}]
        [problem] = ep.plan_problems(shots, label="第 1 集")
        self.assertIn("E1S01「燃」", problem)
        self.assertEqual(ep.plan_problems([{"scene_id": "E1S01", "emotion_point": "爽点"}]), [])

    def test_an_episode_that_only_explains_things_is_flagged_for_the_editor(self):
        flat = [{"scene_id": "E1S01", "emotion_point": "信息交代"}, {"scene_id": "E1S02", "emotion_point": ""}]
        self.assertIn("整集没有一格命中情绪点", ep.episode_without_point(flat))
        self.assertIsNone(ep.episode_without_point([*flat, {"scene_id": "E1S03", "emotion_point": "泪点"}]))
        self.assertIsNone(ep.episode_without_point([]))


class WiringTests(unittest.TestCase):
    def test_the_models_carry_the_field_and_the_prompts_name_every_kind(self):
        scene = SceneContent(scene_id="E1S01", emotion_point=None)
        self.assertEqual(scene.emotion_point, "")
        self.assertEqual(SceneContent(scene_id="E1S01", emotion_point="悬念").emotion_point, "悬念")
        self.assertIn("钩子/冲突/反转", EpisodeOutlineDraft.model_fields["story_beats"].description)
        outline = build_outline_plan_prompt(
            title="t", director_plan="plan", overview={}, first=1, last=1, total=1, context_entries=[], target_seconds=90, instructions=None,
        )
        self.assertIn("story_beats 每条以「【情绪点类型】」开头，类型只能是 " + ep.names(), outline)
        plan = build_script_plan_prompt(
            source_text="大纲", source_kind="outline", episode=1, overview={}, style="", characters={}, scenes={}, props={},
            supported_durations=[5, 10], default_duration=None, episode_target_seconds=None,
            episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None,
        )
        self.assertIn("- **emotion_point**：这一格要打到哪种情绪点上，只能填 " + ep.names(), plan)
        self.assertIn("情绪点类型固定为 " + ep.names(), WRITER_METHODOLOGY)

    def test_the_pacing_section_and_density_rule_agree_with_the_table(self):
        from app.core.screenwriting.pacing import render_pacing_section
        from app.core.screenwriting.prompts import spoken_density_rule

        pacing = render_pacing_section("drama")
        self.assertNotIn("爽 / 燃 / 虐", pacing)
        self.assertIn("钩子、冲突、反转", pacing)
        self.assertNotIn("（一问一答、", spoken_density_rule(0.7), "question-and-answer chains are what the dialogue rules warn against")

    def test_the_legacy_writer_prompt_lists_the_same_kinds(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "prompt" / "agent_prompts.json").read_text("utf-8"))
        self.assertIn("情绪点类型固定为 " + ep.names(), data["writer"])
        self.assertNotIn("爽/燃/虐/怒/甜/惊", data["writer"])

    def test_the_dashboard_scene_carries_the_point_through(self):
        from app.core.screenwriting.renderer import scene_breakdown_entry
        from app.schema.writer_dashboard import WriterDashboardScene

        record = scene_breakdown_entry({"scene_id": "E1S01", "duration_seconds": 5, "emotion_point": "揭秘", "scene_description": "x", "utterances": []})
        self.assertEqual(record["emotion_point"], "揭秘")
        self.assertEqual(WriterDashboardScene(scene_id="E1S01", episode_index=1, scene_index=1, emotion_point="揭秘").emotion_point, "揭秘")

    def test_the_storyboard_artist_is_told_which_point_the_scene_hits(self):
        task = {"task_id": "ep-1", "assets": {"3_characters": [{"name": "林夏", "desc": "女主角"}], "3_sheets": {"林夏": "https://cdn/l.png"}}}
        scene = {"scene_id": "E1S02", "content": "林夏推门而入，把信拍在桌上", "characters": ["林夏"], "emotion_point": "反转"}
        context = compile_scene_context(task, scene, [])
        self.assertIn("本场情绪点：反转——已知的事实或关系被推翻", context["script"])
        self.assertNotIn("本场情绪点", compile_scene_context(task, {**scene, "emotion_point": ""}, [])["script"])


if __name__ == "__main__":
    unittest.main()
