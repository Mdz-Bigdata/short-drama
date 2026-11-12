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
        self.service.repo.save_task("sb-1", self._named_task())
        env = patch.dict(os.environ, {"ASSISTANT_AGENT_ROUTING": "1"})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def _named_task() -> dict:
        """The project has a cast and a named scene, so plain sentences can point at them by name."""
        task = _task()
        task["assets"]["3_characters"] = [{"name": "林夏", "aliases": ["夏夏", "林总"], "desc": "女主"}, {"name": "陆", "aliases": []}, "bad"]
        task["assets"]["2_breakdown"]["scenes"][0]["label"] = "办公室 / 日"
        return task

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

    def test_a_rejected_turn_leaves_no_unanswered_question(self):
        """余额不足、冲突或出错时这一轮作废：刚写进对话的提问要撤掉，不能留一条没有回复的。"""
        with patch.object(self.service, "_answer_assistant", side_effect=RuntimeError("积分不足")):
            with self.assertRaises(RuntimeError):
                asyncio.run(self.service.assistant_message("sb-1", "打开 E1S01 的 3D 导演台", user={"user_id": "u1"}))
        history = self.service.repo.get_task("sb-1").get("chat_history") or []
        self.assertNotIn("打开 E1S01 的 3D 导演台", [entry.get("content") for entry in history])

    def test_an_answered_turn_keeps_the_question(self):
        self._say("打开 E1S01 的 3D 导演台", [
            json.dumps({"tool": "open_storyboard_view", "arguments": {"scene_id": "E1S01", "view": "desk"}}),
            json.dumps({"reply": "已打开。"}),
        ])
        history = self.service.repo.get_task("sb-1").get("chat_history") or []
        self.assertEqual([entry["role"] for entry in history[-2:]], ["user", "assistant"])

    def test_routing_is_off_without_a_text_model(self):
        task = _task()
        task["config"]["llm_model"] = ""
        self.service.repo.save_task("sb-1", task)
        with patch.object(self.service.gateway, "call_llm") as llm:
            result = asyncio.run(self.service.assistant_message("sb-1", "打开 E1S01 的提示词", user={"user_id": "u1"}))
        llm.assert_not_called()
        self.assertNotEqual(result["action"], "agent")

    def _say_edit(self, message, answers, context=None):
        """A plain edit sentence: the tool agent answers it and no stage is claimed or executed."""
        with patch.object(self.service.gateway, "call_llm", side_effect=list(answers)) as llm, \
                patch.object(self.service, "_claim_stage_task") as claim, patch.object(self.service, "execute_stage") as run:
            result = asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}, context=context))
        claim.assert_not_called()
        run.assert_not_called()
        return result, llm

    def test_a_face_edit_in_plain_words_reaches_the_tool_agent(self):
        result, llm = self._say_edit("把林夏的鼻子捏高一点", [json.dumps({"reply": "鼻梁已经调高了。"})])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual((result["action"], result["stage"], result["reply"]), ("agent", None, "鼻梁已经调高了。"))

    def test_a_stage_edit_in_plain_words_reaches_the_tool_agent_instead_of_rerunning_the_stage(self):
        result, llm = self._say_edit("把第3场的机位改到右侧过肩", [json.dumps({"reply": "第 3 场的机位已挪到右侧过肩。"})])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual((result["action"], result["stage"]), ("agent", None))
        # The agent made no tool call; its reply still stands, the stage is not re-run in its place.
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(result["reply"], "第 3 场的机位已挪到右侧过肩。")

    def test_an_edit_without_a_subject_word_or_a_project_name_keeps_the_stage_rerun_path(self):
        # Neither a subject word nor 林夏 / 夏夏 / E1S01 / 办公室: this is still "redo the current stage with guidance".
        with patch.object(self.service.gateway, "call_llm") as llm, patch.object(self.service, "_claim_stage_task", side_effect=RuntimeError("stop")) as claim:
            with self.assertRaises(RuntimeError):
                asyncio.run(self.service.assistant_message("sb-1", "修改一下整体节奏，再紧凑些", user={"user_id": "u1"}))
        llm.assert_not_called()
        claim.assert_called_once()

    def test_a_character_name_routes_an_edit_to_the_agent(self):
        result, llm = self._say_edit("把林夏改瘦一点", [json.dumps({"reply": "林夏已经改瘦了。"})])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual((result["action"], result["stage"], result["reply"]), ("agent", None, "林夏已经改瘦了。"))
        # The first alias counts too; the later ones and a one-character name do not.
        self.assertTrue(self.service._names_a_subject(self.service.repo.get_task("sb-1"), "把夏夏改瘦一点"))
        self.assertFalse(self.service._names_a_subject(self.service.repo.get_task("sb-1"), "把林总改瘦一点"))
        self.assertFalse(self.service._names_a_subject(self.service.repo.get_task("sb-1"), "把陆改瘦一点"))

    def test_a_scene_name_routes_an_edit_to_the_agent(self):
        result, llm = self._say_edit("把办公室那场改暗一点", [json.dumps({"reply": "办公室那场已经压暗了。"})])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual((result["action"], result["stage"]), ("agent", None))
        task = self.service.repo.get_task("sb-1")
        self.assertTrue(self.service._names_a_subject(task, "把办公室 / 日改暗一点"), "the full label counts")
        self.assertTrue(self.service._names_a_subject(task, "把E1S01改暗一点"), "the scene id counts")

    def test_a_malformed_task_still_routes_on_subject_words(self):
        broken = {"config": {"llm_model": "m"}, "assets": {"3_characters": 7, "2_breakdown": {"scenes": [None, {"scene_id": 3}]}, "4": "x"}}
        self.assertEqual(self.service._project_names(broken), [])
        self.assertTrue(self.service._routes_to_agent(broken, "把林夏的鼻子改高一点", "edit"))
        self.assertFalse(self.service._routes_to_agent(broken, "把林夏改瘦一点", "edit"))

    def _agent_turn_with_cards(self):
        """An agent turn whose tools opened a view (ui_action) and left a proposal waiting for /confirm."""
        from app.service import drama_service

        action = {"type": "storyboard_view", "scene_id": "E1S01", "view": "desk"}
        turn = {
            "reply": "已打开导演台；重跑第 4 阶段要花钱，确认吗？",
            "tool_calls": [
                {"tool": "open_storyboard_view", "arguments": {"scene_id": "E1S01", "view": "desk"}, "result": {"ok": True, "result": {"ui_action": action}}},
                {"tool": "get_scene_board", "arguments": {"scene_id": "E1S08"}, "result": {"ok": True, "result": {"status": "failed"}}},
                {"tool": "sculpt_face", "arguments": {"name": "林夏"}, "result": {"ok": False, "error": "没有这个角色", "result": {"ui_action": {"type": "ghost"}}}},
            ],
            "proposal": {"tool": "rerun_stage", "arguments": {"stage": 4}, "message": "重跑第 4 阶段"},
            "remember": [],
        }
        with patch.object(drama_service.embedded_agent, "run_turn", return_value=turn):
            result = asyncio.run(self.service.assistant_message("sb-1", "打开 E1S01 的导演台然后重跑", user={"user_id": "u1"}))
        return result, action

    def test_the_cards_of_an_agent_turn_are_kept_on_its_chat_entry(self):
        result, action = self._agent_turn_with_cards()
        self.assertEqual(result["action"], "agent")
        stored = self.service.repo.get_task("sb-1")["chat_history"]
        self.assertEqual(stored[-1]["role"], "assistant")
        self.assertEqual(stored[-1]["ui_actions"], [action], "only ok results with a ui_action dict")
        self.assertEqual(stored[-1]["proposal"], {"tool": "rerun_stage", "message": "重跑第 4 阶段"})
        self.assertNotIn("ui_actions", stored[-2], "the user's message carries no cards")
        self.assertNotIn("proposal", stored[-2])
        # A later turn without cards stores neither key.
        from app.service import drama_service

        with patch.object(drama_service.embedded_agent, "run_turn", return_value={"reply": "好。", "tool_calls": [], "proposal": None}):
            asyncio.run(self.service.assistant_message("sb-1", "/agent 谢谢", user={"user_id": "u1"}))
        last = self.service.repo.get_task("sb-1")["chat_history"][-1]
        self.assertEqual(last["content"], "好。")
        self.assertNotIn("ui_actions", last)
        self.assertNotIn("proposal", last)

    def test_the_status_payload_exposes_the_cards(self):
        from app.schema.drama import DramaTaskResponse

        result, action = self._agent_turn_with_cards()
        self.assertEqual(result["task"]["chat_history"][-1]["ui_actions"], [action])
        # The fixture never went through create_task, so it lacks the stage_name a real task carries.
        status = {**self.service.get_task_status("sb-1"), "stage_name": "分镜"}
        payload = DramaTaskResponse.model_validate(status).model_dump(mode="json", by_alias=True)
        entry = payload["chatHistory"][-1]
        self.assertEqual(entry["ui_actions"], [action])
        self.assertEqual(entry["proposal"], {"tool": "rerun_stage", "message": "重跑第 4 阶段"})
        self.assertEqual(set(payload["chatHistory"][-2]), {"id", "role", "content"}, "plain entries stay plain")

    def test_subject_words_come_from_the_intent_table(self):
        from app.core import prompt_data

        for group in prompt_data.words("assistant_intents", "agent_subjects"):
            self.assertTrue(self.service._AGENT_SUBJECTS.search(group.split("|")[-1].strip("()")), group)
        for word in ("捏脸", "下巴", "发型", "舞台", "走位", "轴线", "灯光", "撤销"):
            self.assertTrue(self.service._AGENT_SUBJECTS.search(word), word)

    def test_pause_and_workflow_questions_still_skip_the_model(self):
        with patch.object(self.service.gateway, "call_llm") as llm, patch.object(self.service, "_claim_stage_task", side_effect=RuntimeError("stop")):
            for message in ("暂停", "整体流程是什么？"):
                result = asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}))
                self.assertNotEqual(result["action"], "agent")
        llm.assert_not_called()

    def test_the_interface_context_line_is_handed_to_the_agent(self):
        context = {"scene_id": "E1S03", "shot_id": 2, "character": "林夏", "view": "desk", "stage": 4, "ignored": "x"}
        _, llm = self._say_edit("把林夏的鼻子改高一点", [json.dumps({"reply": "好。"})], context=context)
        prompt = llm.call_args.args[2]
        self.assertIn("[界面] 当前打开：场景 E1S03（第 2 镜）· 角色 林夏 · 视图 desk · 第 4 阶段", prompt)
        self.assertNotIn("ignored", prompt)
        self.assertLess(prompt.index("[界面] 当前打开"), prompt.index("把林夏的鼻子改高一点"))

    def test_the_interface_line_only_names_what_is_open(self):
        self.assertEqual(self.service._interface_line({"character": "林夏", "stage": 4}), "[界面] 当前打开：角色 林夏 · 第 4 阶段")
        self.assertEqual(self.service._interface_line({"shot_id": "5"}), "[界面] 当前打开：第 5 镜")
        self.assertEqual(self.service._interface_line({"scene_id": "", "view": None, "stage": True}), "")
        self.assertEqual(self.service._interface_line(None), "")
        _, llm = self._say_edit("把林夏的鼻子改高一点", [json.dumps({"reply": "好。"})])
        self.assertNotIn("[界面]", llm.call_args.args[2])

    def test_assistant_chat_passes_the_sidebar_context_to_the_service(self):
        from unittest.mock import AsyncMock

        from app.api import drama_api

        hydrated = {**self.service.hydrate_task_status(self.service.repo.get_task("sb-1")), "stage_name": "分镜", "logs": {}}
        answer = {"reply": "好。", "action": "agent", "stage": None, "task": hydrated, "tool_calls": [], "proposal": None}
        fake = type("Svc", (), {"assistant_message": AsyncMock(return_value=answer)})()
        payload = {"message": " 把林夏的鼻子改高一点 ", "context": {"scene_id": "E1S03", "shot_id": 2, "stage": 4, "view": ["desk"], "extra": "x"}}
        with patch.object(drama_api, "service", fake):
            body = asyncio.run(drama_api.assistant_chat("sb-1", payload, current_user={"user_id": "u1"}))
        fake.assistant_message.assert_awaited_once_with(
            "sb-1", "把林夏的鼻子改高一点", user={"user_id": "u1"}, context={"scene_id": "E1S03", "shot_id": 2, "stage": 4},
        )
        self.assertEqual((body["reply"], body["action"]), ("好。", "agent"))
        with patch.object(drama_api, "service", fake):
            asyncio.run(drama_api.assistant_chat("sb-1", {"message": "你好"}, current_user={"user_id": "u1"}))
        self.assertIsNone(fake.assistant_message.await_args.kwargs["context"])


class MentionChatTests(unittest.TestCase):
    """创作者在聊天里打 @[名字]：助手拿到一行 [引用]，消息交给工具助手。"""

    def setUp(self):
        from app.core import mention_catalog
        from tests.test_mention_catalog import FakeStore, _element

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = RoutingTests._named_task()
        self.service.repo.save_task("sb-1", task)
        library = [
            _element("a1", "actor", "林夏", task_ids=("sb-1",), description="冷面女总裁"),
            _element("m1", "prop", "青铜镜", task_ids=("sb-1",)),
            _element("m2", "scene", "青铜镜", task_ids=("sb-1",)),
        ]
        for patcher in (
            patch.dict(os.environ, {"ASSISTANT_AGENT_ROUTING": "1"}),
            patch.object(mention_catalog, "_fresh_store", side_effect=lambda: FakeStore(library)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _say(self, message, answers):
        with patch.object(self.service.gateway, "call_llm", side_effect=list(answers)) as llm, \
                patch.object(self.service, "_claim_stage_task") as claim:
            result = asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}))
        claim.assert_not_called()
        return result, llm

    def test_a_mention_routes_to_the_agent_with_a_reference_line(self):
        result, llm = self._say("@[林夏]在@[办公室 / 日]坐着", [json.dumps({"reply": "好。"})])
        self.assertEqual((result["action"], result["reply"]), ("agent", "好。"))
        prompt = llm.call_args.args[2]
        self.assertIn("[引用] 「林夏」= 演员：冷面女总裁；「办公室 / 日」= 场景：E1S01", prompt)
        self.assertLess(prompt.index("[引用]"), prompt.index("@[林夏]在@[办公室 / 日]坐着"))

    def test_aliases_ambiguous_and_unknown_names_are_spelled_out(self):
        _, llm = self._say("把@[夏夏]和@[青铜镜]、@[路人甲]都改一下", [json.dumps({"reply": "好。"})])
        prompt = llm.call_args.args[2]
        self.assertIn("「林夏」= 演员：冷面女总裁（消息里写作「夏夏」）", prompt)
        self.assertIn("「青铜镜」同时是场景和道具，先问清用户指的是哪一个", prompt)
        self.assertIn("「路人甲」在项目里找不到，当普通文字理解", prompt)

    def test_mentions_count_as_subjects_for_routing(self):
        task = self.service.repo.get_task("sb-1")
        self.assertTrue(self.service._names_a_subject(task, "把@[某人]改瘦一点"))
        self.assertTrue(self.service._routes_to_agent(task, "@[某人]的流程是什么？", "question"))
        self.assertTrue(self.service._routes_to_agent(task, "修改一下@[某人]", "edit"))
        no_model = {**task, "config": {"llm_model": ""}}
        self.assertFalse(self.service._routes_to_agent(no_model, "修改一下@[某人]", "edit"))

    def test_a_broken_catalog_never_breaks_the_chat(self):
        from app.core import mention_catalog

        with patch.object(mention_catalog, "mentionable", side_effect=RuntimeError("db down")):
            result, llm = self._say("@[林夏]是谁？", [json.dumps({"reply": "女主。"})])
        self.assertEqual(result["reply"], "女主。")
        self.assertNotIn("[引用]", llm.call_args.args[2])

    def test_workflow_commands_without_mentions_stay_deterministic(self):
        with patch.object(self.service.gateway, "call_llm") as llm, patch.object(self.service, "_claim_stage_task", side_effect=RuntimeError("stop")):
            for message in ("暂停", "整体流程是什么？"):
                result = asyncio.run(self.service.assistant_message("sb-1", message, user={"user_id": "u1"}))
                self.assertNotEqual(result["action"], "agent")
        llm.assert_not_called()
        self.assertEqual(self.service._mention_line(self.service.repo.get_task("sb-1"), "没有引用"), "")


if __name__ == "__main__":
    unittest.main()
