"""真人演员：本人照片就是身份，按照片出分镜和视频；Seedance 只用火山方舟真人人像库素材；分镜像不像本人要核对。"""

import asyncio
import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api.auth_api import auth_service
from app.core import likeness_check, real_person
from app.core.element_library_reuse import find_library_characters
from app.core.model_gateway import ModelGateway
from app.core.panel_still_prompt import _costume_notes, _reference_line
from app.core.storyboard_scene_context import reference_note
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.service.drama_service import DramaService
from main import app

TASK_ID = "real-person-task"


def _photo(color=(180, 140, 120)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 80), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_uri(content: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


class RecordTests(unittest.TestCase):
    def test_no_consent_no_real_person(self):
        with self.assertRaisesRegex(real_person.RealPersonError, "肖像使用授权"):
            real_person.clean_record(person="林夏", scope="", expires="", ark_assets=[], confirmed=False, confirmed_by="u1")

    def test_asset_ids_and_dates_are_checked(self):
        with self.assertRaisesRegex(real_person.RealPersonError, "asset://"):
            real_person.clean_record(person="林夏", scope="", expires="", ark_assets=["https://x/y.png"], confirmed=True, confirmed_by="u1")
        with self.assertRaisesRegex(real_person.RealPersonError, "日期"):
            real_person.clean_record(person="林夏", scope="", expires="明年", ark_assets=[], confirmed=True, confirmed_by="u1")
        record = real_person.clean_record(
            person="林夏", scope="短剧", expires="2099-01-01", ark_assets=["asset://asset-1", "asset://asset-1"], confirmed=True, confirmed_by="u1",
        )
        self.assertEqual(record["ark_assets"], ["asset://asset-1"])
        self.assertTrue(real_person.usable({"real_person": record}))
        self.assertFalse(real_person.usable({"real_person": {**record, "expires": "2001-01-01"}}), "an expired authorization is not used")

    def test_missing_views_are_filled_from_the_photos_not_drawn(self):
        self.assertEqual(
            real_person.view_slots({"face_front", "front"}),
            {"front": "front", "profile": "front", "back": "front", "face_front": "face_front", "face_three_quarter": "face_front"},
        )
        self.assertEqual(set(real_person.view_slots({"face_front"}).values()), {"face_front"})


class PromptTests(unittest.TestCase):
    def test_panels_with_a_real_actor_lose_the_do_not_look_real_negatives(self):
        kept = real_person.keep_likeness(ModelGateway.PANEL_IDENTITY_NEGATIVE)
        for word in ("证件照", "真实可识别的个人身份", "headshot", "真实名人"):
            self.assertNotIn(word, kept)
        self.assertIn("严禁任何非写实风格", kept, "the style negatives stay")
        self.assertIn("2d/3d cartoon", kept)

    def test_the_face_photo_is_its_own_reference_and_the_look_still_numbers_right(self):
        references = [
            {"kind": "actor", "name": "林夏", "image_url": "body", "real_person": True, "variant": "校服"},
            {"kind": "actor", "name": "林夏", "image_url": "face", "real_person": True, "view": "face"},
        ]
        self.assertIn("「林夏」本人的正脸照片，相貌严格按照片", reference_note(2, references[1]))
        self.assertIn("相貌以本人正脸照为准", reference_note(1, references[0]))
        self.assertIn("图2 「林夏」本人正脸照", _reference_line(references))
        self.assertIn("穿图1 的「校服」", _costume_notes(["林夏"], references, [])["林夏"], "the costume points at the body picture, not the face")


class SeedanceTests(unittest.TestCase):
    def test_photos_and_looks_give_way_to_ark_assets(self):
        references = [
            {"kind": "actor", "name": "林夏", "image_url": "look-board", "real_person": True, "variant": "校服", "outfit": "藏青校服",
             "ark_assets": ["asset://asset-a", "asset://asset-b"]},
            {"kind": "actor", "name": "林夏", "image_url": "face-photo", "real_person": True, "view": "face", "ark_assets": ["asset://asset-a", "asset://asset-b"]},
            {"kind": "actor", "name": "周教授", "image_url": "prof", "real_person": True},
            {"kind": "scene", "name": "教室", "image_url": "room"},
        ]
        out, missing = real_person.for_seedance(references)
        self.assertEqual([item["image_url"] for item in out], ["asset://asset-a", "asset://asset-b", "room"])
        self.assertEqual(missing, ["周教授"])
        note = reference_note(1, out[0])
        self.assertIn("这一镜穿「校服」：藏青校服", note)
        self.assertNotIn("；", note)


class LikenessTests(unittest.TestCase):
    def test_answers_are_read_and_judged(self):
        self.assertIsNone(likeness_check.parse("看起来挺像"))
        good = likeness_check.parse('{"same_person": true, "score": 8, "differences": []}')
        bad = likeness_check.parse('{"same_person": false, "score": 5, "differences": ["脸型更圆。"]}')
        self.assertTrue(likeness_check.passed(good))
        self.assertFalse(likeness_check.passed(bad))
        self.assertIn("「林夏」：脸型更圆", likeness_check.fix_prompt([{**bad, "name": "林夏"}]))

    def test_the_photo_and_the_panel_are_shown_side_by_side(self):
        service = DramaService()
        seen = []

        def describe(model, system, prompt, image, **kwargs):
            seen.append(image)
            return '{"same_person": true, "score": 9, "differences": []}', "vision-model"

        with patch.object(service.gateway, "describe_image", side_effect=describe):
            checks = service._check_likeness(_data_uri(_photo((10, 10, 10))), [("林夏", _photo())])
        self.assertEqual(checks[0]["score"], 9.0)
        board = Image.open(io.BytesIO(base64.b64decode(seen[0].split(",", 1)[1])))
        self.assertGreater(board.width, board.height, "photo and panel sit next to each other")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'real.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            await self.store.seed_capabilities()
            await self.store.seed_billing_plans()
            user, _ = await self.store.create_user(email="real@example.com", phone=None, password="real-password-strong")
            return user

        self.user = asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(lambda: asyncio.run(self.store.close()))
        self.client = TestClient(app)
        self.cookie = {"auth_token": auth_service.generate_token(self.user.id)}
        for target in ("app.api.element_api.ELEMENT_MEDIA_ROOT",):
            patcher = patch(target, Path(self.temp.name) / "elements")
            patcher.start()
            self.addCleanup(patcher.stop)

    def _actor(self) -> dict:
        created = self.client.post(
            "/api/elements", json={"kind": "actor", "name": "林夏", "description": "短发", "metadata": {"task_id": TASK_ID}}, cookies=self.cookie,
        )
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()

    def _upload(self, element_id: str, slot: str, content: bytes) -> dict:
        response = self.client.post(
            f"/api/elements/{element_id}/files", data={"slot": slot}, files={"file": (f"{slot}.png", content, "image/png")}, cookies=self.cookie,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _set(self, element_id: str, **overrides) -> object:
        body = {"person": "林夏本人", "scope": "短剧", "expires": "2099-12-31", "ark_assets": ["asset://asset-20260401-xyz"], "confirmed": True, **overrides}
        return self.client.put(f"/api/elements/{element_id}/real-person", json=body, cookies=self.cookie)

    def test_a_face_photo_and_consent_make_a_usable_actor_that_is_never_redrawn(self):
        actor = self._actor()
        self._upload(actor["id"], "face_front", _photo())
        self.assertEqual(self._set(actor["id"], confirmed=False).status_code, 422)
        saved = self._set(actor["id"])
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "ready", "a real actor needs only the face photo")
        self.assertEqual(saved.json()["metadata"]["real_person"]["ark_assets"], ["asset://asset-20260401-xyz"])
        with patch("app.api.element_api._regenerate_library_actor") as regenerate:
            refused = self.client.post(f"/api/elements/{actor['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(refused.status_code, 409)
        regenerate.assert_not_called()
        cleared = self.client.delete(f"/api/elements/{actor['id']}/real-person", cookies=self.cookie)
        self.assertEqual(cleared.json()["status"], "draft", "an ordinary actor still needs five views")

    def test_stage_three_reuses_the_photos_as_the_five_views(self):
        actor = self._actor()
        self._upload(actor["id"], "face_front", _photo((200, 150, 130)))
        self._upload(actor["id"], "front", _photo((90, 90, 120)))
        self._set(actor["id"])
        media = Path(self.temp.name) / "media"
        media.mkdir()
        with patch("app.core.element_library_reuse.PlatformStore", return_value=self.store), \
                patch.object(self.store, "close", return_value=asyncio.sleep(0)), \
                patch("app.core.element_library_reuse.MEDIA_DIR", str(media)):
            records = find_library_characters({"task_id": "another-task", "owner_user_id": self.user.id}, ["林夏"])
        record = records["林夏"]
        self.assertTrue(record["real_person"])
        self.assertEqual(record["sheet"], "")
        views = {view["view"]: view["image_url"] for view in record["views"]}
        self.assertEqual(set(views), {"front", "profile", "back", "face_front", "face_three_quarter"})
        self.assertEqual(views["face_three_quarter"], views["face_front"])
        self.assertEqual(views["back"], views["front"])
        copied = media / views["face_front"].split("/media/", 1)[1]
        self.assertTrue(copied.is_file())


if __name__ == "__main__":
    unittest.main()
