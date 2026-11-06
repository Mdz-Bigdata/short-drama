# -*- coding: utf-8 -*-
"""分镜故事板工具栏的每个功能都能用自然语言操作，以及让第 4 阶段整集失败的分镜表解析问题。

- 解析：模型在一份回答里附带道具表、运镜契约表、连续性账本、质检表时，只认带镜号与画面列的那张分镜表，按表头认列。
- 角色：「未露面按压者」这类无名人物不算编出来的新角色。
- 工具：读九宫格、读提示词、提示词分包、资产设定图、送回重画、在界面上打开视图。
- 对话：不带 /agent 的自然语言请求交给工具助手；继续 / 暂停 / 重跑第 N 阶段仍走原来的流程。
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.agent_tools import catalog
from app.core.embedded_agent import _envelope
from app.core.storyboard_scene_context import panel_context
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService, parse_storyboard_table

GRID_HEADER = "| 格位 | 镜号 | 画面内容 | 入镜角色 | 场景 | 道具 | 特效 | 景别/角度/焦段 | 构图 | 运镜路径/速度/起止 | 时长 | 台词/声音 | 镜头运动契约指纹 | 负面模块 |"


def _grid_row(n: int, speech: str = "心跳增强") -> str:
    return (f"| 上左 | {n} | 第{n}镜：粗手攥住沈知微手腕往印泥按 | 沈知微；未露面按压者（手部） | 靖安侯府正堂 | 红泥印盒 | 无 "
            f"| 中景；平视偏左；50毫米 | 沈知微在左三分 | 固定后轻推；慢；起于收紧止于触泥 | 1.{n}秒 | {speech} "
            f"| SMC-E1S01-0{n}-中景-缓推 | 通用画质 |")


def _answer() -> str:
    rows = [_grid_row(n, '沈知微：“这手，不是我的。” 心跳重起' if n == 8 else "心跳增强") for n in range(1, 10)]
    return "\n".join([
        "# 场景圣经", "| 道具 | 剧情功能 | 状态 |", "|---|---|---|", "| 红泥印盒 | 按印 | 掀盖 |", "| 契纸 | 认契 | 摊开 |", "",
        "# 九宫格分镜", GRID_HEADER, "|" + "---|" * 14, *rows, "",
        "# 镜头运镜契约", "| 镜号 | 契约指纹 | 景别 | 角度 |", "|---|---|---|---|",
        *[f"| {n} | SMC-{n} | 中景 | 平视 |" for n in range(1, 10)], "",
        "# 连续性账本", "| 镜号 | 末帧状态 | 下一镜首帧承接 |", "|---|---|---|",
        *[f"| {n} | 状态{n} | 承接{n} |" for n in range(1, 10)], "",
        "# 质检", "| 质检项 | 结论 | 问题等级 |", "|---|---|---|", "| 左右 | 通过 | 无 |",
    ])


class ParserTests(unittest.TestCase):
    def test_only_the_shot_grid_counts_even_when_the_answer_carries_four_other_tables(self):
        shots = parse_storyboard_table(_answer(), [])
        self.assertEqual([shot["shot_id"] for shot in shots], list(range(1, 10)))

    def test_columns_are_read_by_header_not_position(self):
        shot = parse_storyboard_table(_answer(), [])[0]
        self.assertEqual((shot["size"], shot["angle"], shot["lens"]), ("中景", "平视偏左", "50毫米"))
        self.assertIn("粗手攥住沈知微手腕", shot["desc"])
        self.assertTrue(shot["motion"].startswith("固定后轻推"))      # 不是「镜头运动契约指纹」那一列
        self.assertEqual(shot["duration"], "1.1秒")
        self.assertEqual(shot["characters"], ["沈知微", "未露面按压者"])
        self.assertEqual(shot["scene"], "靖安侯府正堂")
        self.assertTrue(shot["characters_explicit"])

    def test_dialogue_is_split_from_the_sound_cue(self):
        eighth = parse_storyboard_table(_answer(), [])[7]
        self.assertEqual(eighth["dialogue"], "沈知微：这手，不是我的。")
        self.assertEqual(eighth["sound"], "心跳重起")

    def test_the_legacy_headerless_eleven_column_table_still_parses(self):
        legacy = "\n".join(f"| {n} | 近景 | 平视 | 固定 | 林夏盯着对面{n} | | 环境声 | 3s | 线索 | 林夏 | E1S01 办公室 |" for n in range(1, 10))
        shots = parse_storyboard_table(legacy, [])
        self.assertEqual(len(shots), 9)
        self.assertEqual((shots[0]["size"], shots[0]["scene_id"], shots[0]["characters"]), ("近景", "E1S01", ["林夏"]))


class CastCellTests(unittest.TestCase):
    def test_a_note_in_brackets_is_not_split_into_names(self):
        table = (
            "| 镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的 | 入镜角色 | 场景标识 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | 局部特写 | 俯拍 | 固定 | 粗手摁住沈知微的拇指 | | 环境声 | 4s | 铺垫 | 沈知微（画外粗手为未具名之人、仅手部入画） | E1S01 正堂 |"
        )
        shots = parse_storyboard_table(table, [])
        self.assertEqual(shots[0]["characters"], ["沈知微"])


class AnonymousCastTests(unittest.TestCase):
    def _context(self):
        return {"characters": ["沈知微"], "all_character_names": ["沈知微", "陆昀"], "actors": [], "scenes": [], "props": [],
                "costumes": [], "effects": [], "products": [], "references": [], "script": "", "prompt": ""}

    def test_an_unnamed_figure_is_not_an_invented_character(self):
        shot = {"desc": "一双粗手攥住沈知微的手腕", "characters": ["沈知微", "未露面按压者"], "characters_explicit": True}
        bound = panel_context(self._context(), shot)
        self.assertNotIn("未露面按压者", json.dumps(bound, ensure_ascii=False).split("一双粗手")[0])

    def test_servants_named_by_their_job_are_background_extras(self):
        shot = {"desc": "管事与两名仆妇按住沈知微的肩", "characters": ["沈知微", "管事", "仆妇甲", "仆妇乙", "仆役"], "characters_explicit": True}
        bound = panel_context(self._context(), shot)
        self.assertEqual(bound["characters"], ["沈知微"])

    def test_a_surnamed_steward_is_a_real_character_and_still_checked(self):
        shot = {"desc": "李管事按住沈知微的肩", "characters": ["沈知微", "李管事"], "characters_explicit": True}
        with self.assertRaisesRegex(ValueError, "未出场角色：李管事"):
            panel_context(self._context(), shot)

    def test_a_real_invented_name_is_still_rejected(self):
        shot = {"desc": "王二攥住沈知微的手腕", "characters": ["沈知微", "王二"], "characters_explicit": True}
        with self.assertRaisesRegex(ValueError, "未出场角色：王二"):
            panel_context(self._context(), shot)


class EnvelopeTests(unittest.TestCase):
    def test_a_reply_with_real_newlines_is_read_not_shown_raw(self):
        self.assertEqual(_envelope('{"reply": "第一行\n第二行"}'), {"reply": "第一行\n第二行"})

    def test_a_fenced_tool_call_is_read(self):
        self.assertEqual(_envelope('好的。\n```json\n{"tool": "get_scene_board", "arguments": {"scene_id": "E1S01"}}\n```'),
                         {"tool": "get_scene_board", "arguments": {"scene_id": "E1S01"}})

    def test_plain_text_is_not_an_envelope(self):
        self.assertIsNone(_envelope("我在。"))


def _task() -> dict:
    return {
        "task_id": "sb-1", "owner_user_id": "u1", "status": "idle", "current_stage": 4, "logs": {},
        "config": {"llm_model": "m", "image_model": "img", "video_model": "v", "title_suggestion": "换命录"},
        "chat_history": [],
        "assets": {
            "2_breakdown": {"scenes": [{"scene_id": "E1S01", "content": "按印", "characters": ["沈知微"]}]},
            "4_scene_boards": {
                "E1S01": {"status": "done", "episode": 1, "shots_done": 9, "shots_total": 9, "grid_prompt": "九宫格提示词",
                          "prompt_detail": {"summary": "明细"}},
                "E1S08": {"status": "failed", "episode": 1, "shots_done": 0, "shots_total": 9, "error": "分镜表需要9个真实镜头"},
            },
            "4": [{"scene_id": "E1S01", "shot_id": n, "size": "中景", "desc": f"第{n}镜", "image_url": f"/m/{n}.png"} for n in range(1, 10)],
        },
    }


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("sb-1", _task())
        self.user = {"user_id": "u1"}

    def call(self, name, **arguments):
        return catalog.call(name, {"task_id": "sb-1", **arguments}, service=self.service, user=self.user)

    def test_every_toolbar_button_has_a_tool(self):
        names = {tool.name for tool in catalog.list()}
        for name in ("get_scene_board", "get_scene_prompt", "describe_stage", "edit_stage", "render_blender_previz",
                     "get_prompt_packages", "get_asset_sheets", "redraw_scene", "run_stage", "open_storyboard_view"):
            self.assertIn(name, names)

    def test_reading_a_board_reports_its_shots_and_download(self):
        result = self.call("get_scene_board", scene_id="E1S01")["result"]
        self.assertEqual((result["status"], len(result["shots"])), ("done", 9))
        self.assertIn("target=scene&scene=E1S01", result["download_url"])
        failed = self.call("get_scene_board", scene_id="E1S08")["result"]
        self.assertEqual((failed["status"], failed["error"]), ("failed", "分镜表需要9个真实镜头"))

    def test_an_unknown_scene_names_the_known_ones(self):
        result = self.call("get_scene_board", scene_id="E9S99")
        self.assertFalse(result["ok"])
        self.assertIn("E1S01", result["error"])

    def test_the_prompt_is_read_and_a_missing_one_is_explained(self):
        self.assertEqual(self.call("get_scene_prompt", scene_id="E1S01")["result"]["grid_prompt"], "九宫格提示词")
        self.assertIn("尚未生成", self.call("get_scene_prompt", scene_id="E1S08")["error"])

    def test_opening_a_view_returns_an_action_for_the_interface(self):
        result = self.call("open_storyboard_view", scene_id="E1S01", view="desk")["result"]
        self.assertEqual(result["ui_action"], {"type": "storyboard_view", "scene_id": "E1S01", "view": "desk"})
        self.assertFalse(self.call("open_storyboard_view", scene_id="E1S01", view="nope")["ok"])

    def test_asset_sheets_and_redraw_run(self):
        self.assertTrue(self.call("get_asset_sheets")["ok"])
        with patch.object(self.service, "redraw_spatial_scene", return_value={"plan": {}}) as redraw:
            result = self.call("redraw_scene", scene_id="E1S01")
        redraw.assert_called_once_with("sb-1", "E1S01")
        self.assertEqual(result["result"]["status"], "pending")

    def test_rerunning_the_stage_waits_for_confirmation(self):
        result = self.call("run_stage", stage=4)
        self.assertTrue(result.get("needs_confirmation"))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("sb-1", _task())
        env = patch.dict(os.environ, {"ASSISTANT_AGENT_ROUTING": "1"})
        env.start()
        self.addCleanup(env.stop)

    def _say(self, message, answers):
        with patch.object(self.service.gateway, "call_llm", side_effect=list(answers)) as llm:
            result = asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}))
        return result, llm

    def test_a_plain_request_is_handled_by_the_tool_agent(self):
        result, llm = self._say("打开 E1S01 的 3D 导演台", [
            json.dumps({"tool": "open_storyboard_view", "arguments": {"scene_id": "E1S01", "view": "desk"}}),
            json.dumps({"reply": "已打开 E1S01 的 3D 导演台。"}),
        ])
        self.assertEqual(result["action"], "agent")
        self.assertEqual(result["reply"], "已打开 E1S01 的 3D 导演台。")
        action = result["tool_calls"][0]["result"]["result"]["ui_action"]
        self.assertEqual(action, {"type": "storyboard_view", "scene_id": "E1S01", "view": "desk"})

    def test_a_question_about_a_scene_reaches_the_agent(self):
        result, _ = self._say("E1S08 为什么失败？", [
            json.dumps({"tool": "get_scene_board", "arguments": {"scene_id": "E1S08"}}),
            json.dumps({"reply": "分镜表解析出的镜头数不对。"}),
        ])
        self.assertEqual(result["tool_calls"][0]["tool"], "get_scene_board")

    def test_workflow_commands_keep_their_deterministic_path(self):
        with patch.object(self.service.gateway, "call_llm") as llm, patch.object(self.service, "_claim_stage_task", side_effect=RuntimeError("stop")):
            for message in ("暂停", "整体流程是什么？"):
                asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}))
        llm.assert_not_called()

    def test_routing_is_off_without_a_text_model(self):
        task = _task()
        task["config"]["llm_model"] = ""
        self.service.repo.save_task("sb-1", task)
        with patch.object(self.service.gateway, "call_llm") as llm:
            result = asyncio.run(self.service.assistant_message("sb-1", "打开 E1S01 的提示词", user={"user_id": "u1"}))
        llm.assert_not_called()
        self.assertNotEqual(result["action"], "agent")


if __name__ == "__main__":
    unittest.main()
