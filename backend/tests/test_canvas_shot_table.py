# -*- coding: utf-8 -*-
"""What the real three-shot canvas trial (2026-11-16) showed, fixed and pinned.

1. 拆镜头表 is asked for the number of shots the node or its text names (「镜头数：3」「三个镜头」), and says when the
   model gave another number; its lines name who speaks.
2. It lists who is in each shot and how each character looks, and every first frame's words carry those looks.
3. Music and sound effects are quoted by the second with their own models, not the voice's per-character price.
"""

import json
import unittest
from unittest import mock

from app.core import canvas_tools, prompt_data, usage_ledger
from app.core.providers import pricing
from tests.test_canvas_workspace import CanvasCase, _node

TABLE = {
    "cast": [{"name": "女孩", "look": "二十出头，黑色长发，深色风衣"}, {"name": "店主", "look": "七十岁，白发，灰色开衫"}],
    "shots": [
        {"size": "中景", "motion": "固定", "seconds": 4, "desc": "女孩推门进店", "characters": ["女孩"], "dialogue": "女孩：还营业吗？"},
        {"size": "近景", "motion": "", "seconds": 4, "desc": "店主抬头", "characters": ["店主", "店主"], "dialogue": "店主：一直在等你。"},
        {"size": "特写", "motion": "推", "seconds": 3, "desc": "女孩愣住", "characters": ["女孩"], "dialogue": "女孩：等我？"},
    ],
}


class ShotTableRulesTests(unittest.TestCase):
    def test_the_asked_number_comes_from_the_node_then_the_text(self):
        self.assertEqual(canvas_tools.asked_shots({"shots": 2}, "写成三个镜头"), 2)
        self.assertEqual(canvas_tools.asked_shots({}, "写成三个镜头，每镜五秒"), 3)
        self.assertEqual(canvas_tools.asked_shots({}, "镜头数：4\n旧书店门口，夜"), 4)
        self.assertEqual(canvas_tools.asked_shots({}, "十二个镜头"), 12)
        self.assertEqual(canvas_tools.asked_shots({"shots": "x"}, "她走到镜头前"), 0)
        self.assertEqual(canvas_tools.asked_shots({"shots": 500}, ""), prompt_data.number("canvas_tools", "shot_table.count_max"))

    def test_the_question_says_exactly_how_many_or_leaves_it_to_the_story(self):
        exact = canvas_tools.shot_table_question("剧本正文", 3)
        self.assertIn(prompt_data.text("canvas_tools", "shot_table.count_exact").format(count=3), exact)
        self.assertIn("剧本正文", exact)
        self.assertIn(prompt_data.text("canvas_tools", "shot_table.count_free"), canvas_tools.shot_table_question("剧本正文", 0))
        # Who speaks and who is in the shot are asked for by name.
        self.assertIn("人物名：对白", exact)
        self.assertIn("characters", exact)
        self.assertIn("cast", exact)
        # A look names the face's ethnicity or region first, defaulting to where the story happens.
        self.assertIn("人种或地域", exact)
        self.assertIn("按故事发生的地方定", exact)

    def test_the_script_writer_passes_a_shot_count_on(self):
        self.assertIn("镜头数：N", canvas_tools.SCRIPT_PROMPT)

    def test_rows_keep_who_is_in_them_and_the_cast_keeps_each_look(self):
        answer = json.dumps(TABLE, ensure_ascii=False)
        shots = canvas_tools.parse_shots(answer)
        self.assertEqual([shot["characters"] for shot in shots], [["女孩"], ["店主"], ["女孩"]])
        self.assertEqual(shots[0]["dialogue"], "女孩：还营业吗？")
        self.assertEqual(canvas_tools.parse_cast(answer), TABLE["cast"])
        self.assertEqual(canvas_tools.parse_cast(json.dumps({"shots": TABLE["shots"]})), [])
        old = canvas_tools.parse_shots(json.dumps({"shots": [{"desc": "旧表", "seconds": 4}]}))
        self.assertEqual(old[0]["characters"], [])

    def test_each_first_frame_carries_the_looks_of_who_is_in_it(self):
        shots = canvas_tools.parse_shots(json.dumps(TABLE, ensure_ascii=False))
        beats = canvas_tools.shots_as_beats(shots, canvas_tools.parse_cast(json.dumps(TABLE, ensure_ascii=False)))
        self.assertEqual(beats[0]["prompt"], "女孩推门进店，中景，固定。人物：女孩（二十出头，黑色长发，深色风衣）")
        self.assertEqual(beats[1]["prompt"], "店主抬头，近景。人物：店主（七十岁，白发，灰色开衫）")
        self.assertEqual(canvas_tools.shots_as_beats(shots)[0]["prompt"], "女孩推门进店，中景，固定")

    def test_a_character_in_more_than_one_shot_gets_the_words_for_a_look_sheet_of_them_alone(self):
        answer = json.dumps(TABLE, ensure_ascii=False)
        shots = canvas_tools.parse_shots(answer)
        cast = canvas_tools.with_sheets(canvas_tools.parse_cast(answer), shots)
        girl, owner = cast
        self.assertEqual(girl["sheet_prompt"], prompt_data.text("canvas_tools", "cast.sheet_prompt").format(name="女孩", look="二十出头，黑色长发，深色风衣"))
        self.assertNotIn("sheet_prompt", owner, "in one shot only: the words in that frame are enough")
        self.assertEqual(canvas_tools.recurring(shots), {"女孩"})

    def test_a_frame_with_a_sheeted_character_says_the_reference_is_for_face_and_clothes_only(self):
        answer = json.dumps(TABLE, ensure_ascii=False)
        shots = canvas_tools.parse_shots(answer)
        beats = canvas_tools.shots_as_beats(shots, canvas_tools.with_sheets(canvas_tools.parse_cast(answer), shots))
        note = prompt_data.text("canvas_tools", "shots_as_beats.reference_note")
        self.assertTrue(beats[0]["prompt"].endswith(note))
        self.assertNotIn(note, beats[1]["prompt"], "the shop owner has no sheet")
        self.assertTrue(beats[2]["prompt"].endswith(note))


class LineOrderAndTimeTests(unittest.TestCase):
    SCRIPT = "（旧书店门口，夜）\n女孩推门。\n女孩：还开着吗？\n\n（旧书店内，夜）\n老店主抬头。\n老店主：一直在等你。\n女孩：等我？"

    def test_the_question_asks_for_lines_in_script_order_and_each_shot_s_time(self):
        question = canvas_tools.shot_table_question(self.SCRIPT, 3)
        self.assertIn("按剧本里的先后顺序", question)
        self.assertIn("\"time\"", question)

    def test_a_line_said_after_one_that_comes_later_in_the_script_is_flagged(self):
        moved = [
            {"dialogue": ""},
            {"dialogue": "老店主：一直在等你。"},
            {"dialogue": "女孩：「还开着吗？」\n女孩：等我？"},
        ]
        self.assertEqual(canvas_tools.lines_out_of_order(self.SCRIPT, moved), ["还开着吗？"])

    def test_lines_in_order_or_reworded_are_not_flagged(self):
        kept = [{"dialogue": "女孩：还开着吗？"}, {"dialogue": "老店主：一直在等你。\n女孩：等我？"}]
        self.assertEqual(canvas_tools.lines_out_of_order(self.SCRIPT, kept), [])
        self.assertEqual(canvas_tools.lines_out_of_order(self.SCRIPT, [{"dialogue": "老店主：我等了你很久。"}, {"dialogue": "女孩：还开着吗？"}]), [])

    def test_the_time_goes_into_the_frame_words_unless_they_already_say_it(self):
        shots = canvas_tools.parse_shots(json.dumps({"shots": [
            {"desc": "女孩收伞", "seconds": 4, "time": "夜"},
            {"desc": "夜里的街口", "seconds": 4, "time": "夜"},
            {"desc": "店里", "seconds": 4},
        ]}, ensure_ascii=False))
        self.assertEqual([shot["time"] for shot in shots], ["夜", "夜", ""])
        beats = canvas_tools.shots_as_beats(shots)
        self.assertEqual(beats[0]["prompt"], "女孩收伞。" + prompt_data.text("canvas_tools", "shots_as_beats.time").format(time="夜"))
        self.assertEqual(beats[1]["prompt"], "夜里的街口")
        self.assertEqual(beats[2]["prompt"], "店里")


class ShotTableRunTests(CanvasCase):
    def test_a_table_node_asks_for_its_count_and_keeps_cast_and_count(self):
        asked = []

        def answer(model, system, question, *args, **kwargs):
            asked.append(question)
            return json.dumps(TABLE, ensure_ascii=False)

        self.gateway.call_llm = answer
        table = _node("table", "tool", params={"tool": "shot_table", "model": "deepseek-flash", "shots": 2}, prompt="雨夜，女孩走进旧书店")
        saved = self.put([table])
        self.assertEqual(self.run_nodes(["table"], saved["version"])["status"], "started")
        self.assertIn(prompt_data.text("canvas_tools", "shot_table.count_exact").format(count=2), asked[0])
        output = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["table"]
        self.assertEqual([(item["name"], item["look"]) for item in output["cast"]], [(item["name"], item["look"]) for item in TABLE["cast"]])
        self.assertEqual([bool(item.get("sheet_prompt")) for item in output["cast"]], [True, False])
        self.assertEqual(output["asked"], 2, "the table asked for 2 and the node can say it got 3")
        self.assertEqual(len(output["shots"]), 3)
        self.assertIn("人物：女孩", output["beats"][0]["prompt"])
        self.assertNotIn("line_order", output, "the stand-in lines are not in the node's text, so nothing is compared")


class SoundQuoteTests(CanvasCase):
    def setUp(self):
        super().setUp()
        # The prices these tests read back: their own table, not whatever price file this machine has (or lacks).
        pricing.set_pricing_table(pricing.PricingTable.from_mapping({
            "music_v2": {"kind": "per_second", "currency": "USD", "price": 0.0025},
            "eleven_sound_effects": {"kind": "per_second", "currency": "USD", "price": 0.002},
        }))
        self.addCleanup(pricing.set_pricing_table, None)

    def quote(self, mode, **params):
        saved = self.put([_node("sound", "audio_gen", prompt="安静的钢琴", params={"mode": mode, **params})])
        with mock.patch("app.core.media_compositor._elevenlabs_available", return_value=True):
            return self.client.post(f"{self.base}/canvas/runs/assess", json={"node_ids": ["sound"]}).json()["nodes"][0]

    def test_music_is_quoted_by_the_second_with_the_music_model(self):
        row = self.quote("music", durationSeconds=12)
        self.assertEqual((row["model"], row["requested_seconds"]), ("music_v2", 12))
        self.assertEqual(row["estimate"], usage_ledger.estimate("music_v2", "audio", {"seconds": 12}))
        self.assertAlmostEqual(row["estimate"]["cost"], 12 * 0.0025, places=6)

    def test_music_without_a_length_is_quoted_for_the_length_it_will_be_made(self):
        row = self.quote("music")
        default = prompt_data.value("studio_canvas_runs", "audio_pricing")["music"]["default_seconds"]
        self.assertEqual(row["requested_seconds"], default)

    def test_sound_effects_have_their_own_price(self):
        row = self.quote("sfx", durationSeconds=6)
        self.assertEqual(row["model"], "eleven_sound_effects")
        self.assertAlmostEqual(row["estimate"]["cost"], 6 * 0.002, places=6)


if __name__ == "__main__":
    unittest.main()
