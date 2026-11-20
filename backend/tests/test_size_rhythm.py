# -*- coding: utf-8 -*-
"""全集景别节奏：编剧排的景别连成一条线，第 4 步各场照它起幅；连用超了换一档，一集里远、中、近都要有。"""

import unittest

from app.core import prompt_data, size_rhythm


def _task(*episodes):
    return {"assets": {"2_screenwriting": {"episodes": {
        str(number): {"script": {"scenes": [
            {"scene_id": f"E{number}S{index:02d}", "image_prompt": {"composition": {"shot_type": shot_type}}}
            for index, shot_type in enumerate(types, 1)
        ]}}
        for number, types in enumerate(episodes, 1)
    }}}}


def _kinds(plan, scene_id):
    return [kind for kind, _values in plan.get(scene_id, [])]


class SizeRhythmTests(unittest.TestCase):
    def test_the_writer_and_the_delivery_check_count_with_the_same_numbers(self):
        run = int(prompt_data.value("delivery_check", "max_same_size_run"))
        kinds = int(prompt_data.value("delivery_check", "min_sizes_in_cut"))
        rule = size_rhythm.writer_rule()
        self.assertIn(f"最多连用 {run} 个分镜，第 {run + 1} 个换一档", rule)
        self.assertIn(f"至少用到 {kinds} 档", rule)
        self.assertEqual(size_rhythm.band("Medium Long Shot"), "全")
        self.assertEqual(size_rhythm.band("Over-the-shoulder"), "")

    def test_a_varied_plan_is_followed_as_written(self):
        plan = size_rhythm.plan(_task(["Long Shot", "Medium Shot", "Medium Close-up", "Medium Shot", "Close-up"]))
        self.assertEqual([_kinds(plan, f"E1S0{index}") for index in range(1, 6)], [["planned"]] * 5)
        self.assertIn("「远景」", size_rhythm.scene_note(_task(["Long Shot", "Medium Shot", "Close-up"]), "E1S01"))

    def test_the_fourth_scene_in_one_size_is_told_to_change_and_the_count_starts_again(self):
        # Episode 2 of a real project: seven Medium Shots between a Medium Close-up and a Medium Long Shot.
        types = ["Medium Close-up"] + ["Medium Shot"] * 7 + ["Medium Long Shot", "Medium Close-up", "Close-up"]
        plan = size_rhythm.plan(_task(types))
        kinds = [_kinds(plan, f"E1S{index:02d}") for index in range(1, 12)]
        self.assertEqual(kinds[4], ["change"], "E1S05 follows three 中景 scenes")
        self.assertEqual([kind for kind in kinds if kind == ["change"]], [["change"]], "three more 中景 after it are allowed")
        note = size_rhythm.scene_note(_task(types), "E1S05")
        self.assertIn("连着 3 场从「中景」起幅", note)
        self.assertIn("按这场的戏选", note, "the table author picks wider or closer")
        # A shot with no size band (over the shoulder) breaks the run.
        plan = size_rhythm.plan(_task(["Long Shot", "Medium Shot", "Medium Shot", "Over-the-shoulder", "Medium Shot", "Medium Shot", "Close-up"]))
        self.assertNotIn("change", sum((_kinds(plan, f"E1S0{index}") for index in range(1, 8)), []))

    def test_an_episode_missing_wide_or_close_gets_them_at_its_ends(self):
        plan = size_rhythm.plan(_task(["Medium Shot"] * 4))
        self.assertEqual(_kinds(plan, "E1S01"), ["establish"], "no wide size planned: the first scene opens wide")
        self.assertEqual(_kinds(plan, "E1S04"), ["planned", "land_close"], "no close size planned: the last scene lands close")
        self.assertIn("全景或远景", size_rhythm.scene_note(_task(["Medium Shot"] * 4), "E1S01"))

    def test_every_table_is_told_one_size_one_picture_even_without_a_plan(self):
        note = size_rhythm.scene_note({"assets": {}}, "E1S01")
        self.assertIn("只出一张分镜图", note)
        self.assertNotIn("起幅", note.split("】", 1)[1].split("格内", 1)[0])


class PromptTests(unittest.TestCase):
    def test_the_writers_visual_layer_is_told_to_vary_sizes(self):
        from app.core.screenwriting import prompts

        prompt = prompts.build_visual_prompt(
            episode=1, overview=None, style="写实", style_description="", characters={}, scenes={}, props={},
            content_scenes=[{"scene_id": "E1S01", "duration_seconds": 15, "scene_description": "两人在屋里说话。", "utterances": []}],
        )
        line = next(row for row in prompt.splitlines() if row.startswith("- **image_prompt.composition.shot_type**"))
        self.assertIn(size_rhythm.writer_rule(), line)


if __name__ == "__main__":
    unittest.main()
