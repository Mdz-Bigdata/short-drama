"""拆解单：场怎么分、页长和日夜怎么算、元素怎么挂、导出长什么样。"""

import csv
import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.screenwriting.renderer import scene_breakdown_entry
from app.core.writer_dashboard import reconcile_breakdown_scenes
from app.core.script_breakdown import compile_breakdown, day_or_night, eighths_of, page_length, parse_heading, render_csv, render_markdown
from main import app


def _shot(scene_id, heading, text, *cast, seconds=30, **extra):
    return {"scene_id": scene_id, "content": f"{heading} {text}".strip(), "description": text, "duration": f"{seconds}s", "characters": list(cast), "label": "", **extra}


SCENES = [
    _shot("E1S01", "内景：宗祠正堂 - 夜", "沈砚推门进来，右手攥着玉牌。", "沈砚"),
    _shot("E1S02", "内景：宗祠正堂 - 夜", "林晚从供桌后抬头，额角刀伤未愈。", "沈砚", "林晚"),
    _shot("E1S03", "EXT. RIVER BANK - DAY", "黑色马车停在河岸，码头苦力让开。", "沈砚", "码头苦力", seconds=90),
    _shot("E2S01", "市井长街 黄昏 外景", "沈砚穿过长街。", "沈砚"),
]
TASK = {
    "config": {"title_suggestion": "雨夜来信"},
    "assets": {
        "2": "", "2_breakdown": {"scenes": [], "production_assets": {
            "scenes": [{"name": "宗祠正堂", "description": ""}],
            "props": [{"name": "玉牌", "description": ""}, {"name": "没出现的剑", "description": ""}],
            "vehicles": [{"name": "黑色马车", "description": ""}],
            "extras": [{"name": "码头苦力", "description": ""}],
            "makeup": [{"name": "林晚·额角刀伤", "description": ""}],
        }},
    },
}


class HeadingTests(unittest.TestCase):
    def test_every_way_a_heading_is_written(self):
        self.assertEqual(parse_heading("内景：宗祠正堂 - 夜"), ("INT", "宗祠正堂", "夜"))
        self.assertEqual(parse_heading("INT. MARY'S HOUSE - NIGHT"), ("INT", "MARY'S HOUSE", "NIGHT"))
        self.assertEqual(parse_heading("INT/EXT. CAR - DAY"), ("INT/EXT", "CAR", "DAY"))
        self.assertEqual(parse_heading("市井长街 黄昏 外景"), ("EXT", "市井长街", "黄昏"))
        self.assertEqual(parse_heading("外景 街道 日"), ("EXT", "街道", "日"))
        self.assertEqual(parse_heading("演武场 雨夜 外景"), ("EXT", "演武场", "雨夜"))
        self.assertEqual(parse_heading(""), ("", "", ""))

    def test_day_or_night_comes_from_the_words_and_is_not_guessed(self):
        for word in ("夜", "雨夜", "深夜", "凌晨", "NIGHT"):
            self.assertEqual(day_or_night(word), "NIGHT", word)
        for word in ("日", "黄昏", "清晨", "DAY", "DUSK"):
            self.assertEqual(day_or_night(word), "DAY", word)
        for word in ("", "CONTINUOUS", "未注明时段"):
            self.assertEqual(day_or_night(word), "", word)


class PageLengthTests(unittest.TestCase):
    def test_a_minute_is_a_page_and_eighths_are_not_reduced(self):
        self.assertEqual(eighths_of(60), 8)
        self.assertEqual(eighths_of(30), 4)
        self.assertEqual(eighths_of(1), 1)
        self.assertEqual(eighths_of(0), 0)
        self.assertEqual(page_length(4), "4/8")
        self.assertEqual(page_length(8), "1")
        self.assertEqual(page_length(19), "2 3/8")
        self.assertEqual(page_length(0), "")


class CompileTests(unittest.TestCase):
    def setUp(self):
        self.breakdown = compile_breakdown(TASK, SCENES)
        self.sheets = self.breakdown["scenes"]

    def test_shots_in_one_place_and_time_are_one_scene_numbered_per_episode(self):
        self.assertEqual([sheet["number"] for sheet in self.sheets], ["1-1", "1-2", "2-1"])
        self.assertEqual(self.sheets[0]["scene_ids"], ["E1S01", "E1S02"])
        self.assertEqual(self.sheets[0]["seconds"], 60)
        self.assertEqual(self.sheets[0]["page_length"], "1")
        self.assertEqual(self.breakdown["total_scenes"], 3)

    def test_a_marked_change_of_scene_starts_a_new_one_even_in_the_same_place(self):
        shots = [_shot("E1S01", "内景：书房 - 日", "甲。", "沈砚"), _shot("E1S02", "内景：书房 - 日", "乙。", "沈砚", segment_break=True)]
        self.assertEqual(len(compile_breakdown(TASK, shots)["scenes"]), 2)

    def test_a_shot_with_no_heading_carries_on_where_the_last_one_was(self):
        shots = [_shot("E1S01", "内景：书房 - 日", "甲。", "沈砚"), _shot("E1S02", "", "乙。", "沈砚")]
        sheets = compile_breakdown(TASK, shots)["scenes"]
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0]["location"], "书房")

    def test_side_time_and_strip_colour(self):
        self.assertEqual((self.sheets[0]["int_ext"], self.sheets[0]["day_night"], self.sheets[0]["strip"]), ("INT", "NIGHT", "blue"))
        self.assertEqual((self.sheets[1]["int_ext"], self.sheets[1]["day_night"], self.sheets[1]["strip"]), ("EXT", "DAY", "yellow"))
        self.assertEqual(self.sheets[2]["time"], "黄昏", "the original words are kept")
        self.assertEqual(self.sheets[2]["day_night"], "DAY")

    def test_cast_numbers_are_fixed_across_the_show_and_most_scenes_come_first(self):
        self.assertEqual([(item["number"], item["name"]) for item in self.breakdown["cast"]], [(1, "沈砚"), (2, "林晚")])
        self.assertEqual(self.breakdown["cast"][0]["scenes"], ["1-1", "1-2", "2-1"])
        self.assertEqual(self.sheets[0]["cast"], [{"number": 1, "name": "沈砚"}, {"number": 2, "name": "林晚"}])

    def test_only_named_elements_are_listed_and_unnamed_people_count_as_extras(self):
        self.assertEqual(self.sheets[0]["elements"]["prop"], ["玉牌"])
        self.assertEqual(self.sheets[0]["elements"]["look"], ["林晚：额角刀伤"])
        self.assertEqual(self.sheets[1]["elements"]["vehicle"], ["黑色马车"])
        self.assertEqual(self.sheets[1]["elements"]["extra"], ["码头苦力"])
        anonymous = compile_breakdown(TASK, [_shot("E1S01", "内景：书房 - 日", "甲。", "沈砚", "管事")])["scenes"][0]
        self.assertEqual(anonymous["elements"]["extra"], ["管事"])
        self.assertEqual([item["name"] for item in anonymous["cast"]], ["沈砚"])
        self.assertNotIn("码头苦力", [item["name"] for item in self.breakdown["cast"]])
        self.assertNotIn("没出现的剑", [item["name"] for item in self.breakdown["elements"]])

    def test_the_element_list_says_where_each_is_needed(self):
        props = [item for item in self.breakdown["elements"] if item["kind"] == "prop"]
        self.assertEqual(props, [{"kind": "prop", "label": "道具", "name": "玉牌", "scenes": ["1-1"]}])

    def test_an_empty_script_gives_an_empty_breakdown(self):
        empty = compile_breakdown(TASK, [])
        self.assertEqual((empty["total_scenes"], empty["scenes"], empty["cast"]), (0, [], []))


class RealOutlineTests(unittest.TestCase):
    def test_a_scene_written_by_the_engine_keeps_its_side_place_and_time(self):
        scene = {
            "scene_id": "E1S01", "setting": "市井长街 黄昏 外景", "duration_seconds": 15, "characters_in_scene": ["沈砚"],
            "scene_description": "沈砚穿过长街，手里攥着玉牌。",
            "utterances": [{"kind": "dialogue", "speaker": "沈砚", "text": "走吧。"}],
        }
        sheet = compile_breakdown(TASK, [scene_breakdown_entry(scene)])["scenes"][0]
        self.assertEqual((sheet["int_ext"], sheet["location"], sheet["time"], sheet["day_night"]), ("EXT", "市井长街", "黄昏", "DAY"))
        self.assertEqual(sheet["page_length"], "2/8")
        self.assertEqual(sheet["summary"], "沈砚穿过长街，手里攥着玉牌。")
        self.assertEqual(sheet["elements"]["prop"], ["玉牌"])

    def test_an_outline_built_from_a_plain_script_still_gives_sheets(self):
        script = "第1集\n\n内景：书房 - 夜\n\n沈砚抬头。\n\n沈砚：走吧。\n\n外景：河岸 - 日\n\n林晚转身。"
        sheets = compile_breakdown({"config": {}, "assets": {"2": script}}, reconcile_breakdown_scenes([], script))["scenes"]
        self.assertTrue(sheets)
        self.assertTrue(all(sheet["number"].startswith("1-") for sheet in sheets))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.breakdown = compile_breakdown(TASK, SCENES)

    def test_the_csv_opens_in_excel_with_one_row_per_scene(self):
        text = render_csv(self.breakdown)
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(rows[0][:5], ["场号", "内外", "日夜", "时段", "地点"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1][:3], ["1-1", "内", "夜"])
        self.assertIn("1.沈砚", rows[1][9])

    def test_a_cell_that_looks_like_a_formula_cannot_run(self):
        shots = [_shot("E1S01", "内景：=HYPERLINK(1) - 日", "甲。", "沈砚")]
        rows = list(csv.reader(io.StringIO(render_csv(compile_breakdown(TASK, shots)).lstrip("﻿"))))
        self.assertTrue(rows[1][4].startswith("'="))

    def test_the_markdown_has_the_strip_list_the_sheets_and_the_totals(self):
        text = render_markdown(self.breakdown)
        self.assertIn("# 雨夜来信 · 拆解单", text)
        self.assertIn("### 第 1-1 场：内 · 夜 · 宗祠正堂", text)
        self.assertIn("- 道具：玉牌", text)
        self.assertIn("| 1 | 沈砚 | 3 | 1-1、1-2、2-1 |", text)
        self.assertIn("估算", text, "the page length is labelled as an estimate")

    def test_a_pipe_in_the_script_does_not_break_the_table(self):
        shots = [_shot("E1S01", "内景：书房 - 日", "甲|乙。", "沈砚")]
        self.assertIn("甲\\|乙", render_markdown(compile_breakdown(TASK, shots)))


class RouteTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin", "id": "u1"}
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _get(self, query):
        breakdown = compile_breakdown(TASK, SCENES)
        with patch.object(drama_api.service, "script_breakdown", return_value=breakdown), \
                patch.object(drama_api.service.repo, "get_task", return_value={"task_id": "t", "owner_user_id": "u1"}):
            return self.client.get(f"/api/drama/t/script-breakdown{query}")

    def test_each_format_downloads(self):
        self.assertEqual(self._get("").json()["schema_version"], "script-breakdown.v1")
        csv_response = self._get("?format=csv")
        self.assertIn("text/csv", csv_response.headers["content-type"])
        self.assertIn("script-breakdown.csv", csv_response.headers["content-disposition"])
        self.assertIn("markdown", self._get("?format=md").headers["content-type"])

    def test_an_unknown_format_is_refused(self):
        self.assertEqual(self._get("?format=exe").status_code, 422)


if __name__ == "__main__":
    unittest.main()
