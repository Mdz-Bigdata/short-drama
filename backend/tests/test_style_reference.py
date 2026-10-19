"""A reference image becomes a project-only style lock that every prompt then compiles from."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import style_analysis, style_packs
from app.core.credential_pool import Credential
from app.core.model_gateway import ModelGateway
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service.drama_service import DramaService
from main import app

ANSWER = {
    "name": "雨夜霓虹", "medium": "live_action", "summary": "湿润街道上的霓虹反光，冷暖对撞的夜景电影质感",
    "lighting": "低位霓虹侧光，硬光，夜间", "palette": [
        {"name": "霓虹品红", "hex": "#D81B60", "role": "招牌与反光"}, {"name": "深青", "hex": "0B3C49", "role": "阴影与夜空"},
    ],
    "contrast": "高", "temperature": "冷暖对撞", "saturation": "偏高", "camera_body": "数字电影机", "lens": "35mm 大光圈浅景深",
    "grain": "细颗粒", "texture": "湿润反光路面", "composition": "低机位前景虚化", "era": "", "mood": "孤独悬疑",
    "lock": ["neon-lit rainy night + 霓虹雨夜", "wet reflective street + 湿润反光路面", "teal and magenta contrast + 青品对撞"],
    "positives": ["雨丝在光里可见"], "negatives": ["白天高调光"],
    "style_caption": "霓虹雨夜电影质感，neon-lit rainy night cinematic still, wet reflective streets, teal and magenta contrast, shallow depth of field",
}


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (200, 30, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class ProfileAndPackTests(unittest.TestCase):
    def test_an_answer_becomes_a_profile_and_a_lock_that_inherits_from_its_medium(self):
        profile = style_analysis.parse_profile("```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```")
        self.assertEqual(profile.palette[1].hex, "#0B3C49")
        pack = style_analysis.to_pack(profile, task_id="t-1")
        base = style_packs.get_pack("cinematic_realism")
        self.assertTrue(pack.id.startswith("custom_"))
        self.assertEqual(pack.id, style_analysis.custom_pack_id("t-1"))
        self.assertEqual((pack.name, pack.medium), ("参考图·雨夜霓虹", "live_action"))
        self.assertEqual(pack.lock, ANSWER["lock"])
        self.assertEqual([c.hex for c in pack.palette.through_colours], ["#D81B60", "#0B3C49"])
        self.assertEqual(pack.palette.knobs["contrast"], "高")
        self.assertEqual(pack.camera.lens, "35mm 大光圈浅景深")
        self.assertEqual(pack.anti_leak, base.anti_leak, "rules the image cannot speak to come from the base lock")
        self.assertIn("白天高调光", pack.negatives)
        self.assertIn(ANSWER["style_caption"], style_packs.image_style_line(pack))

        anime = style_analysis.to_pack(style_analysis.parse_profile(json.dumps({**ANSWER, "medium": "anime_2d"})), task_id="t-2")
        self.assertEqual(anime.anti_leak, style_packs.get_pack("anime_2d_cel").anti_leak)

    def test_an_unreadable_or_incomplete_answer_is_explained(self):
        with self.assertRaisesRegex(style_analysis.StyleAnalysisError, "不是 JSON"):
            style_analysis.parse_profile("这是一张很好看的图。")
        with self.assertRaisesRegex(style_analysis.StyleAnalysisError, "lock"):
            style_analysis.parse_profile(json.dumps({k: v for k, v in ANSWER.items() if k != "lock"}))

    def test_the_prompt_asks_for_style_only(self):
        system, user = style_analysis.analysis_prompt("想要更冷一点")
        self.assertIn("不要描述图中的具体人物", system)
        self.assertIn("style_caption", user)
        self.assertIn("想要更冷一点", user)


class ResolutionTests(unittest.TestCase):
    def test_a_project_with_a_stored_lock_resolves_to_it_and_the_id_alone_finds_it_afterwards(self):
        pack = style_analysis.to_pack(style_analysis.parse_profile(json.dumps(ANSWER)), task_id="t-3")
        config = {"style_pack": pack.id, "custom_style_pack": pack.model_dump(mode="json")}
        self.assertEqual(style_packs.resolve_pack(config).id, pack.id)
        self.assertEqual(style_packs.get_pack(pack.id).style_caption, ANSWER["style_caption"])
        self.assertEqual(style_packs.resolve_pack({"style_pack": pack.id}).id, "cinematic_realism", "an id without its definition falls back")
        mismatched = {"style_pack": "anime_2d_cel", "custom_style_pack": pack.model_dump(mode="json")}
        self.assertEqual(style_packs.resolve_pack(mismatched).id, "anime_2d_cel")


class GatewayVisionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(runtime_model_registry.replace, [])

    def _register(self, multimodal):
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="cfg", category="text", provider="openai", base_url="https://api.openai.com/v1", api_key="k",
            model_ids=("writer", "seer"), credentials=(Credential(id="primary", api_key="k"),), multimodal_ids=multimodal,
        )])

    def test_the_image_goes_as_a_content_part_to_a_model_that_can_see(self):
        self._register(("seer",))
        gateway = ModelGateway()
        sent = {}

        def chat(key, base_url, model, system, content, timeout=180, max_tokens=None):
            sent.update(model=model, content=content)
            return '{"ok": true}'

        with patch.object(gateway, "_http_chat", side_effect=chat):
            answer, used = gateway.describe_image("writer", "SYS", "看图", "data:image/jpeg;base64,AAAA")
        self.assertEqual((answer, used, sent["model"]), ('{"ok": true}', "seer", "seer"), "a text-only preferred model is passed over")
        self.assertEqual(sent["content"][1], {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}})

    def test_without_a_multimodal_model_nothing_is_sent(self):
        self._register(())
        gateway = ModelGateway()
        with patch.object(gateway, "_http_chat", side_effect=AssertionError("must not call")):
            self.assertEqual(gateway.describe_image("writer", "S", "P", "data:x"), (None, ""))


class ServiceAndApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("sr-1", {"task_id": "sr-1", "owner_user_id": "u1", "status": "idle", "current_stage": 3,
                                     "config": {"style_pack": "film_35mm", "llm_model": "writer", "title_suggestion": "暗室回声"},
                                     "assets": {"3_sheets": {"林夏": "x"}}, "logs": {}, "chat_history": []})
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def _upload(self, content=None, name="ref.png", kind="image/png"):
        return self.client.post("/api/drama/sr-1/style/reference", files={"file": (name, content or _png(), kind)}, data={"hint": "更冷一点"})

    def test_upload_analyse_apply_and_revert(self):
        seen = {}

        def describe(model, system, prompt, image, **kwargs):
            seen.update(model=model, image=image, prompt=prompt)
            return json.dumps(ANSWER, ensure_ascii=False), "seer"

        with patch.object(drama_api, "service", self.service), patch.object(self.service.gateway, "describe_image", side_effect=describe):
            analysed = self._upload()
            self.assertEqual(analysed.status_code, 200, analysed.text)
            body = analysed.json()
            self.assertEqual(body["reference"]["profile"]["name"], "雨夜霓虹")
            self.assertEqual(body["reference"]["model"], "seer")
            self.assertFalse(body["reference"]["applied"])
            self.assertEqual(body["current_pack"]["id"], "film_35mm", "analysis alone changes nothing")
            self.assertTrue(seen["image"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(seen["model"], "writer")
            self.assertIn("更冷一点", seen["prompt"])

            applied = self.client.post("/api/drama/sr-1/style/reference/apply")
            self.assertEqual(applied.status_code, 200, applied.text)
            self.assertTrue(applied.json()["current_pack"]["custom"])
            self.assertEqual(applied.json()["stages_with_old_look"], [3])
            config = self.repo.get_task("sr-1")["config"]
            self.assertEqual(style_packs.resolve_pack(config).style_caption, ANSWER["style_caption"])
            self.assertEqual(config["style_pack_before_reference"], "film_35mm")

            # Saving the project settings with the custom id keeps the custom lock.
            self.service.update_task_config("sr-1", DramaCreateRequest(titleSuggestion="暗室回声", stylePack=config["style_pack"]))
            self.assertTrue(self.repo.get_task("sr-1")["config"]["style_pack"].startswith("custom_"))

            reverted = self.client.post("/api/drama/sr-1/style/reference/revert")
            self.assertEqual(reverted.json()["current_pack"]["id"], "film_35mm")
            self.assertEqual(self.client.post("/api/drama/sr-1/style/reference/revert").status_code, 409)

    def test_bad_images_and_a_missing_vision_model_are_explained(self):
        with patch.object(drama_api, "service", self.service), patch.object(self.service.gateway, "describe_image", return_value=(None, "")):
            self.assertEqual(self._upload(b"not an image", "ref.png").status_code, 422)
            missing = self._upload()
            not_analysed = self.client.post("/api/drama/sr-1/style/reference/apply")
        self.assertEqual(missing.status_code, 422)
        self.assertIn("多模态", missing.json()["detail"])
        self.assertEqual(not_analysed.status_code, 409)


if __name__ == "__main__":
    unittest.main()
