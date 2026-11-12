# -*- coding: utf-8 -*-
"""What the camera sees is written as visible things; ordinary motion is written slow and steady.

No model, no network. The word table (``visual_wording.json``) feeds the writing rules in the
screenwriting and storyboard prompts and the soft checks on a drafted plan and a stage-4 shot table.
The checks are hints: warnings only, never errors, and a fight shot never gets the fast-motion hint.
"""

import json
import unittest
from pathlib import Path

from app.core import prompt_data, visual_wording
from app.core.screenwriting.prompts import build_script_plan_prompt, build_visual_prompt
from app.core.screenwriting.violations import PlanCheckContext, check_script_plan
from app.core.shot_table_rules import audit_shot_table

DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "prompt"
FIGHT = "雨夜屋顶，沈知微拔剑，与陆昀交手三合，刀剑相接，她被击退半步又反击，剧烈喘息，急速旋身。"
PLAN_COMMON = dict(
    episode=1, overview=None, style="", characters={}, scenes={}, props={}, supported_durations=[5, 10, 15], default_duration=None,
    episode_target_seconds=None, episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None,
)
CODES = {visual_wording.SUBJECTIVE_CODE, visual_wording.FAST_MOTION_CODE}


class HitsTests(unittest.TestCase):
    def test_subjective_words_are_found_in_table_order(self):
        self.assertEqual(visual_wording.subjective_hits("她很漂亮，画面震撼又唯美，一身高级感。"), ["漂亮", "震撼", "唯美", "高级感"])
        self.assertEqual(visual_wording.subjective_hits("她嘴角微扬，泪水滑落脸颊，下颌线分明、颧骨高。"), [])
        self.assertEqual(visual_wording.subjective_hits("漂 亮"), ["漂亮"], "whitespace does not hide a word")

    def test_no_false_hit_inside_a_longer_word(self):
        for text in ("他只好看着她离开。", "她正好看见门开了。", "刚好看到信封。", "这里没人好看守。", "人群里有个敏感人物。"):
            self.assertEqual(visual_wording.subjective_hits(text), [], text)
        for text in ("车停在高速公路边。", "车驶上高速路。", "高速摄影拍下水滴落下。"):
            self.assertEqual(visual_wording.fast_motion_hits(text, fight=False), [], text)
        # The same word outside the longer one still counts.
        self.assertEqual(visual_wording.subjective_hits("他只好看着她，她很好看。"), ["好看"])
        self.assertEqual(visual_wording.fast_motion_hits("高速公路上，他高速冲过去。", fight=False), ["高速"])

    def test_fast_motion_words_and_the_fight_exemption(self):
        text = "她急速转身，剧烈颤抖，夸张地挥手。"
        self.assertEqual(visual_wording.fast_motion_hits(text, fight=False), ["剧烈", "夸张", "急速"])
        self.assertEqual(visual_wording.fast_motion_hits(text, fight=True), [])
        self.assertEqual(visual_wording.fast_motion_hits("她缓慢转身，逐渐抬头。", fight=False), [])

    def test_texts_do_not_bridge_into_one_word(self):
        self.assertEqual(visual_wording.subjective_hits("漂", "亮"), [])

    def test_findings_carry_the_words_and_their_hints(self):
        found = visual_wording.findings("他很帅气，疯狂奔跑。", fight=False)
        self.assertEqual([item.code for item in found], [visual_wording.SUBJECTIVE_CODE, visual_wording.FAST_MOTION_CODE])
        self.assertEqual(found[0].words, ("帅气",))
        self.assertIn("「帅气」", found[0].message)
        self.assertIn("下颌线分明", found[0].message)
        self.assertIn("「疯狂」", found[1].message)
        self.assertEqual([item.code for item in visual_wording.findings("他很帅气，疯狂奔跑。", fight=True)], [visual_wording.SUBJECTIVE_CODE])
        self.assertEqual(visual_wording.findings("他推门进来。", fight=False), [])

    def test_every_entry_has_a_word_and_a_hint_and_not_in_contains_its_word(self):
        data = prompt_data.load("visual_wording")
        for key in ("subjective_words", "fast_motion_words"):
            for entry in data[key]:
                with self.subTest(word=entry.get("word")):
                    self.assertTrue(entry["word"] and entry["hint"])
                    for longer in entry.get("not_in") or []:
                        self.assertIn(entry["word"], longer)
                        self.assertGreater(len(longer), len(entry["word"]))


class RulesInPromptsTests(unittest.TestCase):
    def test_the_shot_plan_scene_description_rule_for_every_source(self):
        for kind in ("outline", "novel", "screenplay"):
            prompt = build_script_plan_prompt(source_text="原文", source_kind=kind, **PLAN_COMMON)
            rule = next(line for line in prompt.splitlines() if line.startswith("- **scene_description**："))
            with self.subTest(kind=kind):
                self.assertIn("只写看得见的、慢而稳的", rule)
                self.assertIn(visual_wording.subjective_examples(), rule)
                self.assertIn(visual_wording.fast_motion_examples(), rule)
                self.assertIn("「嘴角微扬」", rule)
                self.assertIn("缓慢走近、轻柔转身、逐渐抬头", rule)
                self.assertIn("打斗镜头照打戏规则写", rule)

    def test_the_visual_prompt_asks_for_visible_detail_and_steady_motion(self):
        prompt = build_visual_prompt(
            episode=1, overview={}, style="写实", style_description="电影感", characters={}, scenes={}, props={},
            content_scenes=[{"scene_id": "E1S01", "scene_description": "林清推门进屋。", "duration_seconds": 5}],
        )
        scene = prompt.split("- **image_prompt.scene**：", 1)[1].split("- **image_prompt.composition.shot_type**", 1)[0]
        self.assertIn(f"不写{visual_wording.subjective_examples()}这类主观评价词", scene)
        action = prompt.split("- **video_prompt.action**：", 1)[1].split("- **video_prompt.camera_motion**", 1)[0]
        self.assertIn(f"不写{visual_wording.fast_motion_examples()}", action)
        self.assertIn("打斗分镜照打斗规则写", action)
        camera = next(line for line in prompt.splitlines() if line.startswith("- **video_prompt.camera_motion**："))
        self.assertIn("非打斗分镜优先固定、缓推、缓拉、平稳横移", camera)

    def test_the_two_storyboard_prompts_carry_one_bullet_each(self):
        data = json.loads((DATA / "agent_prompts.json").read_text("utf-8"))
        for key in ("storyboard_script_prompt", "video_storyboard_prompt"):
            with self.subTest(key=key):
                self.assertEqual(data[key].count("只写看得见的、慢而稳的"), 1)
                self.assertIn("不写漂亮、帅气、震撼、唯美、高级感这类评价词", data[key])
                self.assertIn("不写高速、剧烈、夸张、疯狂、急速，打斗镜头按打戏规则", data[key])
        rhythm = data["video_storyboard_prompt"].split("四、镜头节奏规则", 1)[1].split("五、", 1)[0]
        self.assertIn("6. 只写看得见的、慢而稳的", rhythm)

    def test_the_character_block_names_no_praise_words(self):
        rule = json.loads((DATA / "character_block.json").read_text("utf-8"))["rules"][0]
        self.assertIn("不写漂亮、帅气、美丽这类评价词", rule)


def _ctx(kind: str = "outline") -> PlanCheckContext:
    return PlanCheckContext(episode=1, supported_durations=[5, 10], character_names=["林清"], source_kind=kind)


def _plan_shot(description: str, **extra) -> dict:
    return {"scene_id": "E1S01", "duration_seconds": 5, "characters_in_scene": ["林清"], "scene_description": description, **extra}


class PlanCheckTests(unittest.TestCase):
    def _wording(self, result):
        return [item for item in result.all if item.code in CODES]

    def test_hints_are_warnings_only_in_every_mode(self):
        for kind in ("outline", "novel", "screenplay"):
            result = check_script_plan([_plan_shot("林清很漂亮，她急速转身，画面震撼。")], _ctx(kind))
            with self.subTest(kind=kind):
                self.assertFalse([item for item in result.errors if item.code in CODES])
                found = {item.code: item for item in result.warnings if item.code in CODES}
                self.assertEqual(set(found), CODES)
                self.assertTrue(all(item.severity == "warning" and item.scene_id == "E1S01" for item in found.values()))
                self.assertIn("「漂亮」「震撼」", found[visual_wording.SUBJECTIVE_CODE].message)
                self.assertIn("分镜 E1S01·主观评价词", str(found[visual_wording.SUBJECTIVE_CODE]))

    def test_a_clean_shot_gets_no_hint(self):
        result = check_script_plan([_plan_shot("林清缓缓抬起头，嘴角微扬，泪水滑落脸颊。")], _ctx())
        self.assertEqual(self._wording(result), [])

    def test_the_visual_fields_are_checked_when_present(self):
        shot = _plan_shot("林清推门进屋。", image_prompt={"scene": "她一身高级感。"}, video_prompt={"action": "她疯狂地奔跑。"})
        codes = {item.code for item in self._wording(check_script_plan([shot], _ctx()))}
        self.assertEqual(codes, CODES)

    def test_a_fight_shot_never_gets_the_fast_motion_hint(self):
        self.assertEqual(visual_wording.fast_motion_hits(FIGHT, fight=False), ["剧烈", "急速"], "the fight text does carry fast words")
        result = check_script_plan([_plan_shot(FIGHT)], _ctx())
        self.assertNotIn(visual_wording.FAST_MOTION_CODE, {item.code for item in result.all})
        # Judged by the shot's source excerpt too.
        shot = _plan_shot("她急速旋身。", source_text=FIGHT)
        self.assertNotIn(visual_wording.FAST_MOTION_CODE, {item.code for item in check_script_plan([shot], _ctx("novel")).all})


def _table_shot(**overrides):
    shot = {
        "shot_id": 1, "size": "中景", "duration": "8s",
        "desc": "陈九站在祭坛边，火把照亮他的侧脸，指节扣紧火把木柄，肩背绷直，袍角垂落没有一丝晃动，眼神冷得没有波澜。",
    }
    shot.update(overrides)
    return shot


class ShotTableTests(unittest.TestCase):
    RULES = {prompt_data.text("visual_wording", "subjective_rule"), prompt_data.text("visual_wording", "fast_motion_rule")}

    def _wording(self, audit):
        return [issue for issue in audit.issues if issue.rule in self.RULES]

    def test_hints_are_warnings(self):
        shots = [
            _table_shot(desc="陈九站在祭坛边，画面唯美震撼，火把照亮他的侧脸，他急速转身望向殿门，袍角翻起，肩背绷直。"),
            _table_shot(shot_id=2, size="全景", motion="急速推近"),
        ]
        found = self._wording(audit_shot_table(shots, video_model="seedance2.0"))
        self.assertEqual([(issue.shot_id, issue.rule) for issue in found], [
            (1, prompt_data.text("visual_wording", "subjective_rule")),
            (1, prompt_data.text("visual_wording", "fast_motion_rule")),
            (2, prompt_data.text("visual_wording", "fast_motion_rule")),
        ])
        self.assertTrue(all(issue.severity == "warning" for issue in found))

    def test_a_clean_table_gets_no_hint(self):
        shots = [_table_shot(), _table_shot(shot_id=2, size="全景", motion="缓慢推近")]
        self.assertEqual(self._wording(audit_shot_table(shots, video_model="seedance2.0")), [])

    def test_a_fight_never_gets_the_fast_motion_hint(self):
        fast = prompt_data.text("visual_wording", "fast_motion_rule")
        in_fight_scene = [_table_shot(desc="陈九急速旋身，剧烈喘息，火把在他身后摇晃，袍角翻起，他把重心压到左脚。")]
        audit = audit_shot_table(in_fight_scene, video_model="seedance2.0", scene_kind="fight", whole_episode=False)
        self.assertNotIn(fast, {issue.rule for issue in audit.issues})
        looks_like_one = [_table_shot(desc=FIGHT)]
        audit = audit_shot_table(looks_like_one, video_model="seedance2.0", whole_episode=False)
        self.assertNotIn(fast, {issue.rule for issue in audit.issues})


if __name__ == "__main__":
    unittest.main()
