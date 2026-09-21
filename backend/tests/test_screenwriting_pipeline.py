# -*- coding: utf-8 -*-
"""Stage 2 with the structured screenwriting engine, end to end through the task pipeline.

Covers what the engine's own unit tests cannot: that the Writer stage stores the
structured state, projects it into the screenplay text and breakdown the rest of
the pipeline reads, degrades to the legacy text engine when the engine fails,
continues a truncated script from the ledger, and exposes plan editing over HTTP.
"""

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core.model_gateway import ModelGateway
from app.core.screenwriting.engine import ENGINE_NAME
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from app.core.writer_dashboard import compile_writer_dashboard, script_episode_indexes
from main import app

from tests.test_screenwriting_engine import PROSE_OPENING, FakeModel


class _Gateway:
    """Model gateway stub: routes structured prompts to the fake model, legacy ones to text."""

    GENRE_TEMPLATES = ModelGateway.GENRE_TEMPLATES

    def __init__(self, *, structured: bool = True, breakdown: str = "{}"):
        self.model = FakeModel()
        self.structured = structured
        self.breakdown = breakdown
        self.legacy_calls: List[Dict[str, Any]] = []

    def get_genre(self, title: str) -> str:
        return "mystery"

    def call_llm(self, model, system_prompt, user_prompt, title, director_style="", shot_style="",
                 user_instruction="", max_tokens=None):
        if "结构化分析器" in system_prompt:
            return self.breakdown
        if ("输出格式" in user_prompt and "JSON Schema" in user_prompt) or "小说体剧本正文" in user_prompt:
            if not self.structured:
                return "抱歉，我无法完成该请求。"
            return self.model(system_prompt, user_prompt, max_tokens or 8000)
        self.legacy_calls.append({"system": system_prompt, "prompt": user_prompt})
        span = re.search(r"【本次只写 第 (\d+) 集(?:到第 (\d+) 集)?】", user_prompt)
        if not span:
            return ""
        first = int(span.group(1))
        last = int(span.group(2) or first)
        return "\n".join(
            f"第{index}集 传统副标题{index}\n场景1：旧引擎场景 夜 内景\n镜头：中景 固定\n林夏：这是旧引擎第{index}集。\n"
            for index in range(first, last + 1)
        )


def _service(gateway: _Gateway, repo: TaskRepository) -> DramaService:
    service = DramaService()
    service.gateway = gateway
    service.repo = repo
    return service


def _task(task_id: str = "sw-task-1", *, episode_count: int = 2, **config_extra) -> Dict[str, Any]:
    config = {
        "title_suggestion": "暗室回声",
        "director_style": "realistic",
        "shot_style": "cinematic",
        "llm_model": "deepseek",
        "video_model": "seedance2.0",
        "episode_count": episode_count,
    }
    config.update(config_extra)
    return {
        "task_id": task_id,
        "owner_user_id": "writer-user",
        "current_stage": 1,
        "stage_name": "总导演策划",
        "status": "idle",
        "config": config,
        "assets": {"1": "三幕大纲：林夏追查实验室真相。"},
        "logs": {},
        "episodes": [],
        "chat_history": [],
    }


def _run_stage_two(service: DramaService, task_id: str) -> Dict[str, Any]:
    """Run stage 2 exactly as the API does, so the task ends in its real post-stage state."""
    with patch.object(service, "run_real_consistency_check", return_value="QC-OK"):
        return asyncio.run(service.execute_stage(task_id, 2))


class StructuredStageTwoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("sw-task-1", _task())
        self.gateway = _Gateway()
        self.service = _service(self.gateway, self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def test_stage_two_stores_state_and_projects_screenplay_and_breakdown(self):
        task = _run_stage_two(self.service, "sw-task-1")

        state = task["assets"][screenwriting.STATE_KEY]
        self.assertEqual(state["engine"], ENGINE_NAME)
        self.assertEqual(state["source_kind"], "outline")
        self.assertEqual([entry["episode"] for entry in state["ledger"]], [1, 2])

        self.assertEqual(script_episode_indexes(task["assets"]["2"]), [1, 2])
        self.assertEqual(task["scripted_episode_count"], 2)
        breakdown = task["assets"]["2_breakdown"]
        self.assertEqual([scene["scene_id"] for scene in breakdown["scenes"]], ["E1S01", "E1S02", "E2S01", "E2S02"])
        self.assertEqual(breakdown["overview"]["genre"], "悬疑")
        self.assertEqual({role["name"] for role in breakdown["roles"]}, {"林夏", "周教授"})
        self.assertEqual(len(breakdown["timeline"]), 2)
        self.assertEqual(task["logs"]["2"], "QC-OK")

        dashboard = task["assets"]["2_writer_dashboard"]
        self.assertEqual(dashboard["state"], "READY")
        self.assertEqual(dashboard["stats"]["sceneCount"], 4)

    def test_stage_two_screenplay_reads_as_prose_not_as_a_shot_list(self):
        task = _run_stage_two(self.service, "sw-task-1")

        text = task["assets"]["2"]
        self.assertTrue(text.startswith("第1集 第1集标题\n\n" + PROSE_OPENING))
        self.assertIn("“你到底瞒了什么？”林夏没有移开视线。", text)
        for line in text.splitlines():
            self.assertNotRegex(line, r"^(?:场景\d*|镜头|画面|动作|环境音|时长|台词提示|集尾钩子|林夏|周教授)[：:]")
        # The shots the prose was told from still reach the dashboard through the breakdown.
        self.assertEqual({role["name"] for role in task["assets"]["2_writer_dashboard"]["roles"]}, {"林夏", "周教授"})
        self.assertEqual(task["assets"][screenwriting.STATE_KEY]["episodes"]["2"]["prose_origin"], "model")

    def test_stage_two_prompts_carry_the_writer_persona_and_knowledge(self):
        _run_stage_two(self.service, "sw-task-1")

        systems = {call["system"] for call in self.gateway.model.calls}
        self.assertEqual(len(systems), 1)
        system = systems.pop()
        self.assertIn("AI 专业短剧编剧智能体", system)
        self.assertIn("黄金叙事结构", system)
        self.assertIn("单句不超过 15 个字", system)

    def test_stage_two_falls_back_to_the_legacy_engine_when_the_model_cannot_do_json(self):
        self.gateway.structured = False
        task = _run_stage_two(self.service, "sw-task-1")

        self.assertNotIn(screenwriting.STATE_KEY, task["assets"])
        self.assertIn("旧引擎第1集", task["assets"]["2"])
        self.assertEqual(script_episode_indexes(task["assets"]["2"]), [1, 2])
        self.assertTrue(self.gateway.legacy_calls)

    def test_legacy_engine_can_be_selected_explicitly(self):
        with patch.dict("os.environ", {"WRITER_ENGINE": "legacy"}):
            task = _run_stage_two(self.service, "sw-task-1")

        self.assertNotIn(screenwriting.STATE_KEY, task["assets"])
        self.assertIn("旧引擎第1集", task["assets"]["2"])
        self.assertEqual(self.gateway.model.calls, [])

    def test_uploaded_screenplay_is_extracted_instead_of_skipping_the_writer(self):
        uploaded = (
            "第1集 对峙\n场景1：实验室\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。\n"
            "场景2：走廊\n林夏：录音就是证据。\n"
        )
        task = _task("sw-task-2", episode_count=1, script_content=uploaded, script_name="upload.txt")
        self.repo.save_task("sw-task-2", task)

        result = _run_stage_two(self.service, "sw-task-2")

        state = result["assets"][screenwriting.STATE_KEY]
        self.assertEqual(state["source_kind"], "screenplay")
        plan_prompt = next(call["prompt"] for call in self.gateway.model.calls if "当前正在生成第 1 集" in call["prompt"] and "scene_description" in call["prompt"])
        self.assertIn("**提取**", plan_prompt)
        self.assertIn("你到底瞒了什么？", plan_prompt)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.gateway = _Gateway()
        self.service = _service(self.gateway, self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_episodes_are_written_from_the_structured_ledger(self):
        self.repo.save_task("sw-task-3", _task("sw-task-3", episode_count=2))
        _run_stage_two(self.service, "sw-task-3")
        task = self.repo.get_task("sw-task-3")
        task["config"]["episode_count"] = 4
        self.repo.save_task("sw-task-3", task)
        before = len(self.gateway.model.calls)

        dashboard = self.service.continue_script("sw-task-3")

        self.assertEqual(dashboard.stats.scripted_episodes, 4)
        self.assertEqual(dashboard.stats.missing_episodes, [])
        stored = self.repo.get_task("sw-task-3")
        state = stored["assets"][screenwriting.STATE_KEY]
        self.assertEqual([entry["episode"] for entry in state["ledger"]], [1, 2, 3, 4])
        self.assertEqual(sorted(state["episodes"]), ["1", "2", "3", "4"])
        # The continuation never re-derives the overview or rewrites finished episodes.
        later = [call["prompt"] for call in self.gateway.model.calls[before:]]
        self.assertFalse(any("提炼项目概述" in prompt for prompt in later))
        self.assertFalse(any("当前正在生成第 1 集" in prompt for prompt in later))
        self.assertEqual(self.gateway.legacy_calls, [])
        self.assertEqual(script_episode_indexes(stored["assets"]["2"]), [1, 2, 3, 4])

    def test_a_manual_script_edit_marks_the_structured_state_stale(self):
        self.repo.save_task("sw-task-4", _task("sw-task-4"))
        _run_stage_two(self.service, "sw-task-4")
        task = self.repo.get_task("sw-task-4")
        source_hash = compile_writer_dashboard(task).source_hash

        self.service.update_script(
            "sw-task-4",
            content="第1集 手改\n场景1：新场景 夜 内景\n林夏：我改过了。\n",
            expected_source_hash=source_hash,
            confirm_invalidate=True,
            owner_user_id="writer-user",
        )

        stored = self.repo.get_task("sw-task-4")
        state = stored["assets"][screenwriting.STATE_KEY]
        self.assertTrue(state["stale"])
        self.assertIn("手动修改", state["stale_reason"])
        # A stale state must not be used to continue the script.
        self.assertFalse(screenwriting.is_usable(state))


class ScreenwritingApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("sw-api-1", _task("sw-api-1"))
        self.gateway = _Gateway()
        self.service = _service(self.gateway, self.repo)
        _run_stage_two(self.service, "sw-api-1")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "writer-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("writer-user")})

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_state_endpoint_returns_ledger_inventory_and_duration_constraints(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/sw-api-1/screenwriting")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["sourceKind"], "outline")
        self.assertEqual([entry["episode"] for entry in body["ledger"]], [1, 2])
        self.assertEqual(body["ledger"][0]["storyBeats"], ["节点1A", "节点1B"])
        self.assertIn("林夏", body["inventory"]["characters"])
        self.assertEqual(body["durations"]["supported"][0], 4)
        self.assertEqual(body["durations"]["supported"][-1], 15)
        self.assertEqual([item["episode"] for item in body["episodes"]], [1, 2])
        self.assertEqual(body["episodes"][0]["sceneCount"], 2)

    def test_episode_endpoint_returns_plan_script_and_text(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1")
            missing = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/9")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([scene["scene_id"] for scene in body["plan"]["scenes"]], ["E1S01", "E1S02"])
        self.assertIn("image_prompt", body["script"]["scenes"][0])
        state = self.repo.get_task("sw-api-1")["assets"][screenwriting.STATE_KEY]
        self.assertEqual(body["screenplayText"], "第1集 第1集标题\n\n" + state["episodes"]["1"]["prose"])
        self.assertTrue(body["planRevision"].startswith("sha256-v1:"))
        self.assertEqual(missing.status_code, 404)

    def test_prompt_preview_returns_the_prompt_without_calling_the_model(self):
        calls_before = len(self.gateway.model.calls)
        with patch.object(drama_api, "service", self.service):
            plan = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1/prompt?stage=plan")
            visual = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1/prompt?stage=visual")
            prose = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1/prompt?stage=prose")
            bad = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1/prompt?stage=nonsense")

        self.assertEqual(plan.status_code, 200)
        self.assertIn("当前正在生成第 1 集", plan.json()["prompt"])
        self.assertEqual(prose.status_code, 200)
        self.assertEqual(prose.json()["stage"], "prose")
        self.assertIn("小说体剧本正文", prose.json()["prompt"])
        self.assertEqual(visual.status_code, 200)
        self.assertIn("### E1S01", visual.json()["prompt"])
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(len(self.gateway.model.calls), calls_before)

    def test_plan_patch_rewrites_only_the_edited_shot_and_updates_every_artifact(self):
        with patch.object(drama_api, "service", self.service):
            revision = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1").json()["planRevision"]
            before = len(self.gateway.model.calls)
            response = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={
                    "baseRevision": revision,
                    "operations": [{"op": "update", "id": "E1S02", "fields": {"scene_description": "周教授摘下眼镜，镜片映出红光。"}}],
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["rewrittenSceneIds"], ["E1S02"])
        visual_prompts = [call["prompt"] for call in self.gateway.model.calls[before:] if "视觉生产层" in call["prompt"]]
        self.assertEqual(len(visual_prompts), 1)
        self.assertNotIn("### E1S01", visual_prompts[0])

        stored = self.repo.get_task("sw-api-1")
        self.assertIn("周教授摘下眼镜", stored["assets"]["2"])
        self.assertFalse(stored["assets"][screenwriting.STATE_KEY]["stale"])
        self.assertEqual(
            [scene["scene_id"] for scene in stored["assets"]["2_breakdown"]["scenes"]],
            ["E1S01", "E1S02", "E2S01", "E2S02"],
        )
        self.assertIn("周教授摘下眼镜", json.dumps(stored["assets"]["2_breakdown"], ensure_ascii=False))

    def test_editing_only_the_cast_still_invalidates_downstream_assets(self):
        # Cast is not rendered into the screenplay text, yet stage 3+ consumed it via the
        # breakdown, so the same archive gate as a text edit must apply.
        task = self.repo.get_task("sw-api-1")
        task["current_stage"] = 4
        task["assets"]["3_characters"] = [{"name": "林夏"}]
        task["assets"]["4_storyboard"] = {"panels": ["旧分镜"]}
        self.repo.save_task("sw-api-1", task)
        operations = [{"op": "update", "id": "E1S02", "fields": {"characters_in_scene": ["周教授", "林夏"]}}]

        with patch.object(drama_api, "service", self.service):
            revision = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1").json()["planRevision"]
            refused = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={"baseRevision": revision, "operations": operations},
            )
            accepted = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={"baseRevision": revision, "operations": operations, "confirmInvalidate": True},
            )

        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn("归档", refused.json()["detail"])
        self.assertEqual(accepted.status_code, 200, accepted.text)
        stored = self.repo.get_task("sw-api-1")
        self.assertNotIn("4_storyboard", stored["assets"])
        self.assertEqual(stored["current_stage"], 2)
        breakdown_scene = next(scene for scene in stored["assets"]["2_breakdown"]["scenes"] if scene["scene_id"] == "E1S02")
        self.assertEqual(breakdown_scene["characters"], ["周教授", "林夏"])
        self.assertTrue(stored["script_archives"])

    def test_plan_patch_rejects_a_stale_revision_and_an_illegal_operation(self):
        with patch.object(drama_api, "service", self.service):
            stale = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={"baseRevision": "sha256-v1:" + "0" * 64, "operations": [{"op": "remove", "id": "E1S02"}]},
            )
            revision = self.client.get("/api/drama/sw-api-1/screenwriting/episodes/1").json()["planRevision"]
            unknown = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={"baseRevision": revision, "operations": [{"op": "update", "id": "E1S77", "fields": {"setting": "x"}}]},
            )
            forbidden = self.client.patch(
                "/api/drama/sw-api-1/screenwriting/episodes/1/plan",
                json={"baseRevision": revision, "operations": [{"op": "update", "id": "E1S01", "fields": {"image_prompt": {}}}]},
            )

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(unknown.status_code, 422)
        self.assertIn("E1S77", json.dumps(unknown.json(), ensure_ascii=False))
        self.assertEqual(forbidden.status_code, 422)
        # Nothing was written by any rejected request.
        stored = self.repo.get_task("sw-api-1")
        self.assertEqual(len(stored["assets"][screenwriting.STATE_KEY]["episodes"]["1"]["plan"]["scenes"]), 2)

    def test_state_endpoint_reports_unavailable_for_a_legacy_task(self):
        legacy = _task("sw-api-legacy")
        legacy["assets"]["2"] = "第1集 旧剧本\n场景1：旧场景\n林夏：旧台词。\n"
        self.repo.save_task("sw-api-legacy", legacy)

        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/sw-api-legacy/screenwriting")
            episode = self.client.get("/api/drama/sw-api-legacy/screenwriting/episodes/1")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertEqual(episode.status_code, 404)


if __name__ == "__main__":
    unittest.main()
