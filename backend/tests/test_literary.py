# -*- coding: utf-8 -*-
"""立意与题眼台词：总导演写立意卡，概述接下来，大纲考验它，分镜每集一句题眼，校验器按同一张表查。"""

import json
import unittest
from pathlib import Path

from app.core import literary
from app.core.screenwriting.models import Overview, SceneContent
from app.core.screenwriting.prompts import (
    build_asset_inventory_prompt,
    build_outline_plan_prompt,
    build_overview_prompt,
    build_prose_prompt,
    build_script_plan_prompt,
)
from app.core.storyboard_scene_context import compile_scene_context
from app.service.screenwriting_service import WRITER_METHODOLOGY

OVERVIEW = {"synopsis": "s", "genre": "古装", "theme": "t", "thesis": "人最难赦免的是自己", "motif": "一把钝刀", "world_setting": "w"}


def _shot(scene_id, point, key_line="", lines=("你要的是赢。", "我要的是不用再拔它。")):
    return {
        "scene_id": scene_id, "emotion_point": point, "key_line": key_line,
        "utterances": [{"kind": "dialogue", "speaker": "沈无咎", "text": text} for text in lines],
    }


class TableTests(unittest.TestCase):
    def test_the_table_names_the_overview_fields_points_and_abstract_words(self):
        self.assertEqual([key for key, _ in literary.OVERVIEW_FIELDS], ["thesis", "motif", "ending_image"])
        self.assertEqual(literary.OVERVIEW_LABELS["thesis"], "立意")
        self.assertIn("反转", literary.KEY_LINE_POINTS)
        self.assertIn("冲突", literary.KEY_LINE_POINTS, "a break-up line sits on the conflict shot")
        self.assertNotIn("信息交代", literary.KEY_LINE_POINTS)
        self.assertEqual(literary.abstract_hits("这就是命运，人生如此"), ["命运", "人生"])
        self.assertEqual(literary.abstract_hits("刀钝了，就不该再拔"), [])

    def test_overview_lines_only_write_what_is_filled(self):
        self.assertEqual(literary.overview_lines(OVERVIEW), ["立意：人最难赦免的是自己", "母题：一把钝刀"])
        self.assertEqual(literary.overview_lines({}), [])
        self.assertEqual(literary.overview_lines(None), [])


class ValidationTests(unittest.TestCase):
    def test_a_key_line_must_be_one_of_the_shot_s_own_lines_on_a_listed_point(self):
        good = [_shot("E1S01", "冲突"), _shot("E1S02", "反转", key_line="我要的是不用再拔它。")]
        self.assertEqual(literary.plan_problems(good, label="第 1 集"), [])
        [problem] = literary.plan_problems([_shot("E1S01", "反转", key_line="别的话")], label="第 1 集")
        self.assertIn("第 1 集：E1S01 的 key_line 不是这一格 utterances 里的任何一句", problem)
        [problem] = literary.plan_problems([_shot("E1S01", "信息交代", key_line="你要的是赢。")])
        self.assertIn("压在「信息交代」上", problem)
        self.assertIn("反转 / 揭秘 / 抒情", problem)

    def test_one_key_line_per_episode(self):
        two = [_shot("E1S01", "反转", key_line="你要的是赢。"), _shot("E1S02", "揭秘", key_line="我要的是不用再拔它。")]
        [problem] = literary.plan_problems(two)
        self.assertIn("一集只能有一句题眼台词", problem)
        self.assertIn("E1S01、E1S02", problem)

    def test_only_written_lines_are_checked_for_length_and_abstract_words(self):
        soup = "命运从来不会放过任何一个真正想要逃离它的人"
        shot = _shot("E1S01", "抒情", key_line=soup, lines=(soup,))
        problems = literary.plan_problems([shot], authored=True)
        self.assertEqual(len(problems), 2)
        self.assertIn("超过 20 个字", problems[0])
        self.assertIn("抽象名词（命运）", problems[1])
        self.assertEqual(literary.plan_problems([shot], authored=False), [], "an adapted or extracted line is the source's")

    def test_question_and_answer_chains_and_long_speeches_are_warned_about(self):
        qa = {
            "scene_id": "E1S03", "utterances": [
                {"kind": "dialogue", "speaker": "甲", "text": "你去哪了？"}, {"kind": "dialogue", "speaker": "乙", "text": "码头。"},
                {"kind": "dialogue", "speaker": "甲", "text": "见谁？"}, {"kind": "dialogue", "speaker": "乙", "text": "老周。"},
            ],
        }
        [(code, message, scene_id)] = literary.dialogue_warnings([qa])
        self.assertEqual((code, scene_id), ("qa_dialogue", "E1S03"))
        self.assertIn("E1S03 是问答式对白（连着 2 问 2 答）", message)
        sparring = {
            "scene_id": "E1S04", "utterances": [
                {"kind": "dialogue", "speaker": "甲", "text": "你去哪了？"}, {"kind": "dialogue", "speaker": "乙", "text": "你管得着？"},
                {"kind": "dialogue", "speaker": "甲", "text": "见谁？"}, {"kind": "dialogue", "speaker": "乙", "text": "老周。"},
            ],
        }
        self.assertEqual(literary.dialogue_warnings([sparring]), [], "a question answered with a question is sparring, not Q&A")
        speech = {"scene_id": "E1S05", "utterances": [{"kind": "dialogue", "speaker": "甲", "text": "我" * 46}, {"kind": "voiceover", "text": "旁" * 80}]}
        [(code, message, _)] = literary.dialogue_warnings([speech])
        self.assertEqual(code, "long_line")
        self.assertIn("有一句 46 字的长话", message)
        self.assertEqual(literary.dialogue_warnings([_shot("E1S01", "冲突")]), [])
        stiff = {"scene_id": "E1S06", "utterances": [
            {"kind": "dialogue", "speaker": "甲", "text": "我明白你的意思，然而方向不同。"}, {"kind": "dialogue", "speaker": "乙", "text": "嗯。"},
        ]}
        [(code, message, _)] = literary.dialogue_warnings([stiff])
        self.assertEqual(code, "stiff_line")
        self.assertIn("E1S06 的台词在念稿（我明白你的意思、然而）", message)
        self.assertEqual(literary.stiff_hits("别跟我解释这个。"), [])

    def test_an_episode_without_a_key_line_is_a_reminder_unless_nobody_speaks(self):
        self.assertIn("整集没有一句题眼台词", literary.episode_without_key_line([_shot("E1S01", "冲突")]))
        self.assertIsNone(literary.episode_without_key_line([_shot("E1S01", "反转", key_line="你要的是赢。")]))
        self.assertIsNone(literary.episode_without_key_line([{"scene_id": "E1S01", "utterances": []}]))
        self.assertIsNone(literary.episode_without_key_line([]))


class WiringTests(unittest.TestCase):
    def test_the_models_carry_the_thesis_card_and_the_key_line(self):
        overview = Overview(thesis="人最难赦免的是自己", motif="钝刀", ending_image="刀入鞘")
        self.assertEqual(overview.model_dump()["ending_image"], "刀入鞘")
        self.assertIn("可以被反驳的判断", Overview.model_fields["thesis"].description)
        self.assertEqual(SceneContent(scene_id="E1S01", key_line=None).key_line, "")
        self.assertIn("逐字等于", SceneContent.model_fields["key_line"].description)

    def test_the_director_and_overview_prompts_ask_for_the_card(self):
        self.assertIn("立意卡", literary.thesis_card())
        self.assertIn("母题物件", literary.thesis_card())
        self.assertIn("立意不等于主角想要的东西", literary.thesis_card())
        self.assertIn("标签句", literary.voice_print_rule())
        prompt = build_overview_prompt("plan", source_kind="outline")
        self.assertIn("立意是一个可以被反驳的判断句", prompt)

    def test_the_outline_plan_tests_the_thesis_and_places_the_motif(self):
        prompt = build_outline_plan_prompt(
            title="t", director_plan="plan", overview=OVERVIEW, first=1, last=1, total=1, context_entries=[], target_seconds=90, instructions=None,
        )
        self.assertIn("- 立意：人最难赦免的是自己", prompt)
        self.assertIn("- 母题：一把钝刀", prompt)
        self.assertIn("立意要被考验", prompt)
        self.assertIn("三次变义", prompt)
        self.assertIn("钩子是把话留一半：结果、原因、答案、人四个信息位只空一个", prompt)
        self.assertIn("下一集开头三个节点内开始兑现", prompt)

    def test_the_script_plan_explains_the_key_line_and_only_teaches_writing_it_when_creating(self):
        common = dict(
            episode=1, overview=OVERVIEW, style="", characters={}, scenes={}, props={}, supported_durations=[5, 10], default_duration=None,
            episode_target_seconds=None, episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None,
        )
        created = build_script_plan_prompt(source_text="大纲", source_kind="outline", **common)
        self.assertIn("- **key_line**：本集的题眼台词：一集最多一句", created)
        self.assertIn("反转 / 揭秘 / 抒情", created)
        self.assertIn("从说话人自己的行当里说理", created)
        self.assertIn("不超过 20 个字", created)
        self.assertIn("命运、人生", created)
        self.assertIn("立意：人最难赦免的是自己", created)
        self.assertIn("尾重句", created)
        self.assertIn("台词写法：每句台词先想潜台词再落笔", created)
        self.assertIn("身份焊在嘴上", created)
        self.assertIn("别用问答传信息", created)
        self.assertIn("绑定信念的标签句", created)
        self.assertIn("真人不说完整句", created)
        self.assertIn("不写念稿词：「我认为」「我明白了」", created)
        self.assertIn("遮住角色名读一遍", created)
        self.assertIn("禁止项（这个人绝对不会说的话）", build_asset_inventory_prompt("原文", source_kind="novel", overview=OVERVIEW))
        adapted = build_script_plan_prompt(source_text="原文", source_kind="novel", **common)
        self.assertIn("- **key_line**：本集的题眼台词", adapted)
        self.assertNotIn("从说话人自己的行当里说理", adapted)
        self.assertNotIn("台词写法：", adapted)

    def test_the_inventory_methodology_and_prose_carry_the_rules(self):
        inventory = build_asset_inventory_prompt("原文", source_kind="novel", overview=OVERVIEW)
        self.assertIn("用什么说理", inventory)
        self.assertIn("题眼台词压在情绪点上", WRITER_METHODOLOGY)
        prose = build_prose_prompt(
            episode=1, overview=OVERVIEW, style="", characters={}, content_scenes=[_shot("E1S01", "反转")], episode_outline=None,
        )
        self.assertIn("5. **母题与留白**", prose)
        self.assertIn("6. **结尾落在物上**", prose)
        self.assertIn("7. **不要出现**", prose)
        self.assertIn("9. **语言**", prose)
        self.assertIn("立意：人最难赦免的是自己", prose)

    def test_the_legacy_writer_prompt_says_the_same(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "prompt" / "agent_prompts.json").read_text("utf-8"))
        self.assertIn(literary.methodology(), data["writer"])

    def test_the_video_model_is_told_to_hold_after_the_key_line(self):
        self.assertEqual(literary.clip_note("我要的是不用再拔它。"), "「我要的是不用再拔它。」是本集题眼：说完停一拍，不接话、不解释，镜头多停在说话人脸上半秒")
        self.assertEqual(literary.clip_note(""), "")

    def test_the_storyboard_artist_is_told_to_hold_on_the_key_line(self):
        task = {"task_id": "ep-1", "assets": {"3_characters": [{"name": "林夏", "desc": "女主角"}], "3_sheets": {"林夏": "https://cdn/l.png"}}}
        scene = {"scene_id": "E1S02", "content": "林夏把刀放回鞘里", "characters": ["林夏"], "emotion_point": "反转", "key_line": "我要的是不用再拔它。"}
        context = compile_scene_context(task, scene, [])
        self.assertIn("本场题眼台词：「我要的是不用再拔它。」——画面给这句留停留", context["script"])
        self.assertNotIn("题眼台词", compile_scene_context(task, {**scene, "key_line": ""}, [])["script"])


class StageFiveKeyLineTests(unittest.TestCase):
    def setUp(self):
        # Borrow the queue tests' offline stage-5 harness without inheriting (and re-running) its cases;
        # imported here so unittest does not collect that class from this module as well.
        from tests.test_stage_five_queue import StageFiveQueueTests

        self.stage = StageFiveQueueTests()
        self.stage.setUp()
        self.addCleanup(self.stage.doCleanups)

    def test_the_clip_prompt_tells_the_video_model_which_line_is_the_key_line(self):
        from tests.test_stage_five_queue import _task

        task = _task(2)
        line = "朕的江山，不换。"
        task["assets"]["2_breakdown"] = {"scenes": [{
            "scene_id": "E1S01", "content": "沈砚推门而入", "characters": ["沈砚"], "emotion_point": "反转", "key_line": line,
            "dialogue": [{"kind": "dialogue", "speaker": "沈砚", "text": "你来了。"}, {"kind": "dialogue", "speaker": "沈砚", "text": line}],
        }]}
        task["assets"]["4"][0]["dialogue"] = f"沈砚：{line}"
        task["assets"]["4"][1]["dialogue"] = "沈砚：你来了。"
        prompts: list[str] = []
        self.stage._run(task, on_video=prompts.append)
        self.assertEqual(len(prompts), 2)
        with_key = [text for text in prompts if literary.clip_note(line) in text]
        self.assertEqual(len(with_key), 1, "only the shot that speaks the key line is told to hold after it")
        self.assertIn("台词表达：", with_key[0])


if __name__ == "__main__":
    unittest.main()
