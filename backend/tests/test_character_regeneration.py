import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import media_compositor
from app.core.character_dashboard import REGENERATION_KEY
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.schema.production import IDENTITY_VIEW_ORDER
from app.service.drama_service import DramaService
from main import app


def _record(name: str, prefix: str) -> dict:
    return {
        "name": name, "role": "主角", "desc": "深蓝校服",
        "sheet": f"https://cdn.test/{prefix}/sheet.png", "sheet_type": "actor_sheet_25_cell",
        "views": [{"view": view, "image_url": f"/media/{prefix}/{view}.png"} for view in IDENTITY_VIEW_ORDER],
        "sheet_cells": [{"cell": "portrait", "image_url": f"/media/{prefix}/portrait.png"}],
        "five_view_quality": {"passed": True, "entropy": [6.0] * 5, "palette_similarity": 0.9, "unique_view_hashes": 5, "issues": []},
    }


class CharacterRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        (self.media / "old").mkdir(parents=True)
        Image.new("RGB", (64, 80), (200, 160, 140)).save(self.media / "old" / "portrait.png")
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        created = self.service.create_task(DramaCreateRequest(title_suggestion="渡口", llm_model="m", image_model="img-model"))
        self.task_id = created["task_id"]
        task = self.service.repo.get_task(self.task_id)
        task["assets"]["3_characters"] = [_record("沈知微", "old"), _record("陆行远", "lu")]
        task["assets"]["3_sheets"] = {"沈知微": "https://cdn.test/old/sheet.png", "陆行远": "https://cdn.test/lu/sheet.png"}
        self.service.repo.save_task(self.task_id, task)

    def _result(self, *, passed=True, error=None):
        return {
            "sheet": "https://cdn.test/new/sheet.png",
            "views": [{"view": view, "image_url": f"/media/new/{view}.png"} for view in IDENTITY_VIEW_ORDER],
            "cells": [{"cell": "portrait", "image_url": "/media/new/portrait.png"}],
            "quality": {"passed": passed, "entropy": [6.0] * 5, "palette_similarity": 0.9, "unique_view_hashes": 5, "issues": []},
            "phase": "quality_error", "error": error,
        }

    def test_a_passed_sheet_replaces_only_that_character_and_uses_the_portrait_as_reference(self):
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._result()) as render,
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            dashboard = self.service.regenerate_character(self.task_id, "沈知微", background=False)

        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["name"], "沈知微")
        self.assertEqual(kwargs["image_model"], "img-model")
        self.assertTrue(kwargs["ref_images"][0].startswith("data:image/jpeg;base64,"))
        task = self.service.repo.get_task(self.task_id)
        by_name = {item["name"]: item for item in task["assets"]["3_characters"]}
        self.assertEqual(by_name["沈知微"]["sheet"], "https://cdn.test/new/sheet.png")
        self.assertEqual(by_name["陆行远"]["sheet"], "https://cdn.test/lu/sheet.png")
        self.assertEqual(task["assets"]["3_sheets"]["沈知微"], "https://cdn.test/new/sheet.png")
        self.assertEqual(task["assets"][REGENERATION_KEY]["沈知微"]["status"], "done")
        character = next(item for item in dashboard.characters if item.name == "沈知微")
        self.assertFalse(character.regenerating)
        self.assertEqual(character.regeneration_error, "")

    def test_a_failed_sheet_keeps_the_old_images_and_says_why(self):
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._result(passed=False, error=RuntimeError("设定集质检失败：空白格"))),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            dashboard = self.service.regenerate_character(self.task_id, "沈知微", background=False)

        task = self.service.repo.get_task(self.task_id)
        record = next(item for item in task["assets"]["3_characters"] if item["name"] == "沈知微")
        self.assertEqual(record["sheet"], "https://cdn.test/old/sheet.png")
        character = next(item for item in dashboard.characters if item.name == "沈知微")
        self.assertIn("空白格", character.regeneration_error)

    def test_unknown_names_and_double_starts_are_refused(self):
        with self.assertRaises(ValueError):
            self.service.regenerate_character(self.task_id, "无名氏", background=False)
        task = self.service.repo.get_task(self.task_id)
        task["assets"][REGENERATION_KEY] = {"沈知微": {"status": "running", "started_epoch": time.time()}}
        self.service.repo.save_task(self.task_id, task)
        with self.assertRaises(ValueError) as caught:
            self.service.regenerate_character(self.task_id, "沈知微", background=False)
        self.assertIn("正在重新生成", str(caught.exception))
        dashboard = self.service.get_character_dashboard(self.task_id)
        self.assertTrue(next(item for item in dashboard.characters if item.name == "沈知微").regenerating)

    def test_a_stale_running_mark_does_not_block_a_new_attempt(self):
        task = self.service.repo.get_task(self.task_id)
        task["assets"][REGENERATION_KEY] = {"沈知微": {"status": "running", "started_epoch": time.time() - 3600}}
        self.service.repo.save_task(self.task_id, task)
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._result()),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            self.service.regenerate_character(self.task_id, "沈知微", background=False)
        self.assertEqual(self.service.repo.get_task(self.task_id)["assets"][REGENERATION_KEY]["沈知微"]["status"], "done")

    def test_hd_mode_replaces_only_the_six_identity_views(self):
        import io
        import random
        import sys

        sys.path.insert(0, str(Path(__file__).parent))
        from test_actor_hd_views import _triptych

        folder = self.media / "lu"
        folder.mkdir(parents=True, exist_ok=True)
        cells = ["portrait", "full_body", "front", "profile", "back", "face_front", "face_three_quarter", "element_shoe"]
        for index, cell in enumerate(cells):
            image = Image.new("RGB", (220, 260), (230, 230, 230))
            generator = random.Random(index)
            for y in range(0, 260, 5):
                for x in range(0, 220, 5):
                    value = generator.randint(30, 220)
                    image.paste((value, value, value), (x, y, x + 5, y + 5))
            image.save(folder / f"{index + 1:02d}_{cell}.png")
        task = self.service.repo.get_task(self.task_id)
        record = next(item for item in task["assets"]["3_characters"] if item["name"] == "陆行远")
        record["sheet_cells"] = [{"cell": cell, "image_url": f"/media/lu/{index + 1:02d}_{cell}.png"} for index, cell in enumerate(cells)]
        record["views"] = [{"view": view, "image_url": f"/media/lu/{cells.index(view) + 1:02d}_{view}.png"} for view in IDENTITY_VIEW_ORDER]
        self.service.repo.save_task(self.task_id, task)
        payloads = iter([_triptych(1536, 512), _triptych(1536, 1024, seeds=(4, 5, 6))])
        with (
            patch.object(self.service.gateway, "generate_image", return_value=("https://img.test/hd.png", "seedance")) as generate,
            patch("app.service.drama_service.storyboard_assets_open_image",
                  side_effect=lambda url: Image.open(io.BytesIO(next(payloads))).convert("RGB")),
        ):
            dashboard = self.service.regenerate_character(self.task_id, "陆行远", mode="hd", background=False)

        self.assertEqual(generate.call_count, 2)
        self.assertTrue(all(ref.startswith("data:image/") for ref in generate.call_args_list[0].kwargs["ref_images"]))
        stored = next(item for item in self.service.repo.get_task(self.task_id)["assets"]["3_characters"] if item["name"] == "陆行远")
        hd = {item["cell"] for item in stored["sheet_cells"] if item.get("hd")}
        self.assertEqual(hd, {"front", "profile", "back", "face_front", "face_three_quarter", "face_three_quarter_right"})
        self.assertEqual(stored["sheet"], "https://cdn.test/lu/sheet.png")   # 设定集本身不动
        shoe = next(item for item in stored["sheet_cells"] if item["cell"] == "element_shoe")
        self.assertEqual(shoe["image_url"], "/media/lu/08_element_shoe.png")
        character = next(item for item in dashboard.characters if item.name == "陆行远")
        self.assertEqual(character.regeneration_error, "")

    def test_the_api_starts_it_in_the_background(self):
        owner = self.service.repo.get_task(self.task_id).get("owner_user_id") or "u1"
        app.dependency_overrides[get_current_user] = lambda: {"user_id": owner, "role": "admin"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        client = TestClient(app)
        with (
            patch.object(drama_api, "service", self.service),
            patch.object(self.service, "_regenerate_character_worker") as worker,
        ):
            response = client.post(f"/api/drama/{self.task_id}/characters/regenerate", json={"name": "沈知微"})
            missing = client.post(f"/api/drama/{self.task_id}/characters/regenerate", json={"name": "无名氏"})
        self.assertEqual(response.status_code, 202, response.text)
        regenerating = {item["name"]: item["regenerating"] for item in response.json()["characters"]}
        self.assertTrue(regenerating["沈知微"])
        self.assertFalse(regenerating["陆行远"])
        self.assertEqual(missing.status_code, 422)
        for _ in range(50):
            if worker.called:
                break
            time.sleep(0.02)
        worker.assert_called_once_with(self.task_id, "沈知微", "sheet")


if __name__ == "__main__":
    unittest.main()
