"""360° panoramas: a 2:1 picture from an image model, kept as a desk backdrop, and never a real model call in here."""

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw, ImageStat

from app.api import drama_api, panorama_api
from app.api.auth_api import get_current_user
from app.core import media_compositor, panorama
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.operations import apply_operations
from app.repository.task_repo import TaskRepository
from app.service import director_desk_service as desk
from app.service.drama_service import DramaService


def _picture(size=(800, 800), left=(200, 40, 40), right=(40, 40, 200)):
    image = Image.new("RGB", size, left)
    ImageDraw.Draw(image).rectangle([size[0] // 2, 0, size[0], size[1]], fill=right)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FitPanoramaTests(unittest.TestCase):
    def _image(self, result):
        return Image.open(io.BytesIO(result.content)).convert("RGB")

    def test_any_shape_comes_out_exactly_two_to_one(self):
        for size in ((800, 800), (1000, 300), (1024, 512), (3000, 1000)):
            result = panorama.fit_panorama(_picture(size))
            self.assertEqual(result.width, 2 * result.height, size)
            self.assertEqual(self._image(result).size, (result.width, result.height))

    def test_the_edges_are_blended_and_the_gap_is_reported(self):
        result = panorama.fit_panorama(_picture((1000, 500)))
        self.assertGreater(result.seam_delta, panorama.SEAM_WARNING)
        image = self._image(result)
        left, right = image.crop((0, 0, 1, 500)), image.crop((999, 0, 1000, 500))
        self.assertLess(sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3, 15)
        # Well inside, the picture is untouched.
        self.assertGreater(image.getpixel((200, 250))[0], 170)
        self.assertLess(image.getpixel((200, 250))[2], 80)

    def test_a_seamless_input_reports_no_gap(self):
        self.assertLess(panorama.fit_panorama(_picture((1000, 500), right=(200, 40, 40))).seam_delta, 1)

    def test_oversized_is_capped_and_unusable_is_refused(self):
        self.assertEqual(panorama.fit_panorama(_picture((5000, 2500))).width, panorama.MAX_WIDTH)
        with self.assertRaisesRegex(ValueError, "太小"):
            panorama.fit_panorama(_picture((100, 50)))
        with self.assertRaisesRegex(ValueError, "不是可用"):
            panorama.fit_panorama(b"not an image")

    def test_prompt_asks_for_the_format_and_needs_a_subject(self):
        prompt = panorama.panorama_prompt("雨夜客厅")
        for phrase in ("equirectangular", "2:1", "地平线", "无缝", "没有人", "雨夜客厅"):
            self.assertIn(phrase, prompt)
        self.assertIn("书房", panorama.panorama_prompt("", scene={"location": "书房"}))
        self.assertIn("扩展", panorama.panorama_prompt("", has_reference=True))
        with self.assertRaisesRegex(ValueError, "地点"):
            panorama.panorama_prompt("  ")


class PanoramaRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        for target, name, value in (
            (media_compositor, "MEDIA_DIR", str(self.media)),
            (media_compositor, "PUBLIC_BASE_URL", "http://testserver/media"),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-pano"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "u-1", "config": {"image_model": "seedream"},
            "assets": {"2_breakdown": {"scenes": [{"scene_id": "E1S01", "location": "雨夜客厅"}]}},
        })
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(panorama_api.router)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u-1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.client = TestClient(app)
        self.url = f"/api/drama/{self.task_id}/panoramas/scenes/E1S01"
        self.generated = "data:image/png;base64," + base64.b64encode(_picture((1024, 512))).decode()

    def _generate(self, **kwargs):
        with patch.object(self.service.gateway, "generate_image", return_value=(self.generated, "seedance")) as call:
            response = self.client.post(self.url, **kwargs)
        return response, call

    def test_text_generates_a_stored_backdrop_picture(self):
        response, call = self._generate(data={"description": "雨夜客厅，暖灯"})
        self.assertEqual(response.status_code, 201, response.text)
        [item] = response.json()["panoramas"]
        self.assertEqual((item["width"], item["height"], item["source"]), (1024, 512, "text"))
        self.assertTrue(item["url"].startswith("http://testserver/media/desk_"))
        self.assertTrue((self.media / item["url"].rsplit("/", 1)[-1]).is_file())
        self.assertIn("暖灯", call.call_args.args[1])
        self.assertEqual(call.call_args.kwargs["size"], panorama.PANORAMA_SIZE)
        self.assertFalse(call.call_args.kwargs["enhance_prompt"])
        self.assertIsNone(call.call_args.kwargs["ref_images"])
        # It is a desk backdrop like an uploaded one: the desk lists it.
        task = self.service.repo.get_task(self.task_id)
        [capture] = desk.scene_view(task, "E1S01")["captures"]
        self.assertEqual((capture["kind"], capture["url"]), ("backdrop", item["url"]))
        self.assertEqual(self.client.get(self.url).json()["panoramas"][0]["id"], item["id"])

    def test_empty_description_falls_back_to_the_scene(self):
        response, call = self._generate(data={})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn("雨夜客厅", call.call_args.args[1])

    def test_a_reference_is_sent_inline_and_must_be_honoured(self):
        response, call = self._generate(data={"description": ""}, files={"reference": ("a.png", _picture((64, 64)), "image/png")})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["panoramas"][0]["source"], "image")
        self.assertTrue(call.call_args.kwargs["ref_images"][0].startswith("data:image/png;base64,"))
        self.assertTrue(call.call_args.kwargs["require_reference_support"])

    def test_refusals_cost_nothing(self):
        bad, call = self._generate(data={}, files={"reference": ("a.png", b"not an image", "image/png")})
        self.assertEqual(bad.status_code, 422)
        call.assert_not_called()
        with patch.object(self.service.gateway, "generate_image") as paid:
            self.assertEqual(self.client.post(f"/api/drama/{self.task_id}/panoramas/scenes/E9S99", data={"description": "x"}).status_code, 404)
            paid.assert_not_called()

    def test_a_full_scene_refuses_before_paying(self):
        def fill(task):
            for _ in range(desk.MAX_BACKDROPS_PER_SCENE):
                desk.add_capture(task, "E1S01", desk.CaptureUpload(content=b"", kind="backdrop", shot_id=0), "http://x/a.png")
        self.service.repo.mutate_task(self.task_id, fill)
        response, call = self._generate(data={"description": "x"})
        self.assertEqual(response.status_code, 422)
        call.assert_not_called()

    def test_provider_failure_is_a_plain_502(self):
        for side_effect, value in ((None, (None, None)), (RuntimeError("key=secret"), None)):
            with patch.object(self.service.gateway, "generate_image", return_value=value, side_effect=side_effect):
                response = self.client.post(self.url, data={"description": "x"})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("secret", response.text)
        self.assertEqual(self.client.get(self.url).json()["panoramas"], [])

    def test_a_remote_result_goes_through_the_validated_download(self):
        with patch.object(self.service.gateway, "generate_image", return_value=("https://cdn.example/p.png", "seedance")), \
             patch("app.service.panorama_service.fetch_remote_image_bytes", return_value=_picture((1024, 512))) as fetch:
            response = self.client.post(self.url, data={"description": "x"})
        self.assertEqual(response.status_code, 201, response.text)
        fetch.assert_called_once_with("https://cdn.example/p.png")

    def test_deleting_the_picture_on_the_desk_takes_it_off_the_list(self):
        response, _ = self._generate(data={"description": "x"})
        capture_id = response.json()["panoramas"][0]["capture_id"]
        self.service.repo.mutate_task(self.task_id, lambda task: desk.delete_capture(task, "E1S01", capture_id))
        self.assertEqual(self.client.get(self.url).json()["panoramas"], [])

    def test_the_stored_url_is_one_the_real_backdrop_operation_accepts(self):
        response, _ = self._generate(data={"description": "x"})
        url = response.json()["panoramas"][0]["url"]
        plan = build_plan(SceneBrief(scene_id="E1S01", location="客厅", characters=["林晚"], shots=[
            ShotSpec(shot_id=1, subjects=["林晚"], speaker="林晚", size="中景", angle="平视", motion="固定", desc="坐下"),
        ]))
        after = apply_operations(plan, [{"op": "set_backdrop", "kind": "panorama", "url": url, "yaw_deg": 0}])
        self.assertEqual((after.backdrop.kind, after.backdrop.url), ("panorama", url))


if __name__ == "__main__":
    unittest.main()
