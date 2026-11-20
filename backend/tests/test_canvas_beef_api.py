import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import canvas_beef_api, drama_api
from app.api.auth_api import get_current_user
from app.core import canvas_beef_prompt_optimizer as optimizer
from app.core import prompt_data
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry
from app.repository.task_repo import TaskRepository


def reply(**over):
    body = {"prompt": "雨夜码头，林夏提灯站在船头，冷蓝主光，中景", "avoid": ["文字水印", "文字水印"], "changes": ["补了光线"],
            "assumptions": ["按夜景理解"], "alternatives": ["另一版提示词", "雨夜码头，林夏提灯站在船头，冷蓝主光，中景"]}
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


class OptimizerTest(unittest.TestCase):
    def request(self, **over):
        fields = {"prompt": "林夏 码头 夜", "medium": "image", "mode": "expand"}
        fields.update(over)
        return optimizer.Request(**fields)

    def test_the_mode_rule_comes_before_the_contract_which_is_last(self):
        system, user = optimizer.prompts(optimizer.checked(self.request(mode="fit_model", target_model="seedream-5")))
        self.assertTrue(system.endswith(prompt_data.text("canvas_beef_prompt_optimizer", "contract")))
        self.assertIn("seedream-5", system)
        self.assertIn("林夏 码头 夜", user)

    def test_a_clip_gets_the_one_camera_move_rule_before_the_contract_and_a_picture_does_not(self):
        rule = prompt_data.text("canvas_beef_prompt_optimizer", "video_rules")
        for mode in optimizer.MODES:
            if mode in optimizer.LAYOUT_MODES:
                # A fixed layout applies the one-move rule per timed segment instead (test_prompt_structure).
                continue
            extra = {"references": ["林夏：短发"]} if mode == "references" else {}
            clip, _ = optimizer.prompts(optimizer.checked(self.request(medium="video", mode=mode, **extra)))
            self.assertIn(rule, clip)
            self.assertLess(clip.index(rule), clip.index(prompt_data.text("canvas_beef_prompt_optimizer", "contract")))
            picture, _ = optimizer.prompts(optimizer.checked(self.request(medium="image", mode=mode, **extra)))
            self.assertNotIn(rule, picture)

    def test_references_are_listed_and_pictures_only_counted(self):
        checked = optimizer.checked(self.request(mode="references", references=["  林夏：短发，青色斗篷  ", ""], image_references=2))
        _, user = optimizer.prompts(checked)
        self.assertIn("林夏：短发，青色斗篷", user)
        self.assertIn("2 张已连接的参考图", user)
        with self.assertRaises(optimizer.OptimizerError) as refused:
            optimizer.checked(self.request(mode="references"))
        self.assertIn("连上文字或图片参考", str(refused.exception))

    def test_requests_that_cannot_be_optimized_are_refused(self):
        limit = prompt_data.value("canvas_beef_prompt_optimizer", "limits")["prompt_chars"]
        for over, said in (
            ({"mode": "louder"}, "没有这种优化方式"), ({"medium": "audio"}, "图片或视频"),
            ({"prompt": " \x07 "}, "先写一点"), ({"prompt": "字" * (limit + 1)}, str(limit)),
        ):
            with self.assertRaises(optimizer.OptimizerError) as refused:
                optimizer.checked(self.request(**over))
            self.assertIn(said, str(refused.exception))

    def test_a_usable_answer_is_cleaned_and_anything_else_leaves_the_prompt_alone(self):
        result = optimizer.parse(f"好的：\n```json\n{reply()}\n```")
        self.assertEqual(result.avoid, ["文字水印"])
        self.assertEqual(result.alternatives, ["另一版提示词"])
        for answer, said in (("", "没有给出回答"), ("改好了：雨夜码头", "不是要求的格式"), (reply(prompt="  "), "没有给出整理好的")):
            with self.assertRaises(optimizer.OptimizerError) as refused:
                optimizer.parse(answer)
            self.assertIn(said, str(refused.exception))
            self.assertIn("原提示词没有改动", str(refused.exception))


class CanvasBeefApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        repo.save_task("cv-1", {"task_id": "cv-1", "owner_user_id": "u1", "config": {"title_suggestion": "雨巷", "llm_model": "deepseek-flash"},
                                "assets": {}, "logs": {}, "chat_history": []})
        patch = mock.patch.object(drama_api.service, "repo", repo)
        patch.start()
        self.addCleanup(patch.stop)
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="c", category="text", provider="qwen", base_url="https://x", api_key="k", model_ids=("qwen-max",),
        )])
        self.addCleanup(runtime_model_registry.replace, [])
        self.app = FastAPI()
        self.app.include_router(canvas_beef_api.drama_router)
        self.app.include_router(canvas_beef_api.studio_router)
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "username": "u1", "role": "user", "permissions": []}
        self.client = TestClient(self.app)

    def test_options_list_the_projects_text_model_first(self):
        shown = self.client.get("/api/drama/cv-1/canvas-beef/prompt-optimize").json()
        self.assertEqual(shown["text_models"], ["deepseek-flash", "qwen-max"])
        self.assertEqual([mode["id"] for mode in shown["modes"]], list(optimizer.MODES))
        limits = self.client.get("/api/drama/cv-1/canvas-beef/reference-limits").json()
        self.assertEqual(limits, {"images": 9, "videos": 3, "audios": 3})

    def test_an_optimization_uses_the_chosen_model_and_is_billed_to_the_project(self):
        seen = []

        def llm(model, system, user, *args, **kwargs):
            from app.core import usage_ledger
            seen.append((model, usage_ledger.current_task_id()))
            return reply()

        with mock.patch.object(drama_api.service.gateway, "call_llm", side_effect=llm):
            done = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                "prompt": "林夏 码头 夜", "medium": "image", "mode": "refine", "text_model": "qwen-max",
            })
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["prompt"], "雨夜码头，林夏提灯站在船头，冷蓝主光，中景")
        self.assertEqual(seen, [("qwen-max", "cv-1")])

    def test_an_unknown_model_or_a_bad_answer_is_refused(self):
        unknown = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
            "prompt": "x", "medium": "image", "mode": "refine", "text_model": "gpt-who",
        })
        self.assertEqual(unknown.status_code, 422)
        with mock.patch.object(drama_api.service.gateway, "call_llm", return_value="好的我改完了"):
            bad = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={"prompt": "x", "medium": "video", "mode": "style"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("原提示词没有改动", bad.json()["detail"])

    def test_an_older_version_is_read_without_changing_anything(self):
        studio = mock.Mock()
        record = mock.Mock()
        record.model_dump.return_value = {"version": 3, "nodes": [{"id": "n1"}], "edges": []}
        studio.repository.get_canvas_version.return_value = record
        self.app.dependency_overrides[canvas_beef_api.get_studio_service] = lambda: studio
        shown = self.client.get("/api/studio/projects/p1/canvas/versions/3?canvas_id=main")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown.json()["nodes"], [{"id": "n1"}])
        studio.repository.get_canvas_version.assert_called_once_with("p1", "u1", 3, canvas_id="main")
        studio.repository.put_canvas.assert_not_called()
        studio.repository.get_canvas_version.return_value = None
        self.assertEqual(self.client.get("/api/studio/projects/p1/canvas/versions/9").status_code, 404)
        studio.repository.get_canvas_version.side_effect = PermissionError("not yours")
        self.assertEqual(self.client.get("/api/studio/projects/p1/canvas/versions/3").status_code, 404)


if __name__ == "__main__":
    unittest.main()
