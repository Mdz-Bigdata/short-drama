"""The video model chosen in the model centre is the one that renders, and references reach it intact."""

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import reference_fit
from app.core.model_gateway import ModelGateway
from app.core.providers.minimax_h3 import MiniMaxH3Client
from app.core.video_admission import assess_video_batch
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service.drama_service import DramaService
from main import app


def _data_uri(width: int, height: int, fmt: str = "PNG") -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 90)).save(buffer, format=fmt)
    mime = "png" if fmt == "PNG" else "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _size(uri: str) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size


def _minimax() -> RuntimeModelConfiguration:
    return RuntimeModelConfiguration(
        configuration_id="cfg-minimax", category="video", provider="minimax",
        base_url="https://api.minimaxi.com", api_key="saved-key", model_ids=("MiniMax-H3",),
    )


class RegistryIsolation(unittest.TestCase):
    def setUp(self):
        snapshot = runtime_model_registry.list("video") + runtime_model_registry.list("text") \
            + runtime_model_registry.list("image") + runtime_model_registry.list("audio")
        self.addCleanup(lambda: runtime_model_registry.replace(list(snapshot)))
        runtime_model_registry.replace([])


class ReferenceFitTests(unittest.TestCase):
    def test_an_identity_strip_narrower_than_two_to_five_is_padded_not_cropped(self):
        fitted = reference_fit.fit_image(_data_uri(804, 2048))

        width, height = _size(fitted)
        self.assertEqual(height, 2048)
        self.assertGreaterEqual(width / height, reference_fit.MIN_RATIO)
        self.assertTrue(fitted.startswith("data:image/png;base64,"))
        # The original picture sits in the middle, untouched; only the sides are new.
        picture = Image.open(io.BytesIO(base64.b64decode(fitted.split(",", 1)[1]))).convert("RGB")
        self.assertEqual(picture.getpixel((width // 2, height // 2)), (200, 120, 90))
        self.assertEqual(picture.getpixel((0, height // 2)), (0, 0, 0))

    def test_images_inside_the_limits_and_remote_urls_are_sent_as_they_are(self):
        storyboard = _data_uri(1440, 2560, "JPEG")
        self.assertIs(reference_fit.fit_image(storyboard), storyboard)
        self.assertEqual(reference_fit.fit_image("https://cdn/frame.jpeg"), "https://cdn/frame.jpeg")
        self.assertIsNone(reference_fit.fit_image(None))
        self.assertEqual(reference_fit.fit_image("data:image/png;base64,not-an-image"), "data:image/png;base64,not-an-image")

    def test_a_small_narrow_prop_is_enlarged_and_padded_without_slipping_out_of_the_range(self):
        # 229×740 was padded to 296×740, then enlarged to 300×751: ratio 0.3995, and the provider refused the whole request.
        width, height = _size(reference_fit.fit_image(_data_uri(229, 740)))
        self.assertGreaterEqual(width / height, reference_fit.PAD_MIN_RATIO)
        self.assertGreaterEqual(min(width, height), reference_fit.MIN_SIDE)
        self.assertTrue(reference_fit.within_limits(width, height))

    def test_every_size_that_needs_fitting_lands_inside_the_range_with_room_to_spare(self):
        sizes = [(w, h) for w in (1, 7, 60, 119, 229, 299, 300, 301, 333, 504, 569, 640, 799, 800, 804, 1023, 2048, 6001, 9000)
                 for h in (1, 9, 100, 299, 300, 301, 740, 751, 1139, 1600, 1744, 2000, 2048, 5999, 6000, 7001)]
        for width, height in sizes:
            if reference_fit.within_limits(width, height):
                continue
            (image_w, image_h), (canvas_w, canvas_h) = reference_fit._target_size(width, height)
            with self.subTest(size=(width, height), canvas=(canvas_w, canvas_h)):
                self.assertTrue(reference_fit.within_limits(canvas_w, canvas_h))
                self.assertLessEqual(image_w, canvas_w)
                self.assertLessEqual(image_h, canvas_h)
                # A picture that was outside the ratio range is padded past the edge, not onto it.
                if width / height < reference_fit.MIN_RATIO:
                    self.assertGreaterEqual(canvas_w / canvas_h, reference_fit.PAD_MIN_RATIO)
                if width / height > reference_fit.MAX_RATIO:
                    self.assertLessEqual(canvas_w / canvas_h, reference_fit.PAD_MAX_RATIO)
                # Padding only: one scale factor puts both sides of the picture within a pixel of where they are.
                low = max((image_w - 1) / width, (image_h - 1) / height)
                high = min((image_w + 1) / width, (image_h + 1) / height)
                self.assertLessEqual(low, high)

    def test_wide_and_tiny_images_are_brought_inside_the_limits(self):
        for width, height in ((2600, 800), (120, 200), (486, 1744)):
            with self.subTest(size=(width, height)):
                self.assertTrue(reference_fit.within_limits(*_size(reference_fit.fit_image(_data_uri(width, height)))))


class GatewayVideoRoutingTests(RegistryIsolation):
    def _gateway(self) -> ModelGateway:
        gateway = ModelGateway()
        gateway.optimize_video_prompt = lambda prompt, **_: prompt
        return gateway

    def test_a_failed_minimax_h3_shot_is_not_handed_to_seedance(self):
        runtime_model_registry.replace([_minimax()])
        gateway = self._gateway()
        gateway._ark_video = Mock(side_effect=AssertionError("H3 projects must not be rendered by Seedance"))

        with patch.object(MiniMaxH3Client, "create_video", side_effect=RuntimeError("MiniMax H3 request failed: HTTP 400, 2013 invalid params")), \
                self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            result = gateway.generate_video("MiniMax-H3", prompt="镜头推近", image_url="https://cdn/frame.jpeg", duration=6)

        self.assertIsNone(result)
        self.assertIn("2013 invalid params", "\n".join(logs.output))

    def test_minimax_h3_receives_fitted_references(self):
        runtime_model_registry.replace([_minimax()])
        gateway = self._gateway()
        sent = {}

        def create(client, request):
            sent["refs"] = list(request.reference_images)
            return Mock(video_url="https://cdn/h3.mp4", task_id=None)

        with patch.object(MiniMaxH3Client, "create_video", create):
            url = gateway.generate_video("MiniMax-H3", prompt="两人对峙", image_url="https://cdn/frame.jpeg", ref_images=[_data_uri(804, 2048)], duration=8)

        self.assertEqual(url, "https://cdn/h3.mp4")
        self.assertEqual(sent["refs"][0], "https://cdn/frame.jpeg")
        self.assertTrue(reference_fit.within_limits(*_size(sent["refs"][1])))

    def test_seedance_gets_fitted_references_and_a_rejection_fails_the_shot_instead_of_text_to_video(self):
        gateway = self._gateway()
        gateway._provider_creds = Mock(return_value=("ark-key-0123456789abcdef", "https://ark.example/api/v3", None))
        gateway._is_valid_key = lambda key: True
        calls = []

        def ark(key, base, prompt, first_frame=None, last_frame=None, ref_images=None, **kwargs):
            calls.append({"first": first_frame, "refs": list(ref_images or [])})
            from app.core import model_gateway

            model_gateway._ark_notes.last = "HTTP 400 InvalidParameter image ratio"
            return None

        gateway._ark_video = ark
        gateway._agnes_video = Mock(return_value=None)
        with self.assertLogs("app.core.model_gateway", level="ERROR") as logs:
            url = gateway.generate_video(
                gateway.seedance_model_name, prompt="雨夜对峙", image_url=None,
                ref_images=["https://cdn/frame.jpeg", _data_uri(804, 2048)], duration=10,
            )

        self.assertIsNone(url)
        # One image-to-video attempt with fitted references; no second, reference-free (text-to-video) request.
        self.assertEqual(len(calls), 1)
        self.assertTrue(reference_fit.within_limits(*_size(calls[0]["refs"][1])))
        for call in gateway._agnes_video.call_args_list:
            self.assertIsNotNone(call.args[2])
        self.assertTrue(any("InvalidParameter image ratio" in line and "禁止降级为文生视频" in line for line in logs.output))

    def test_a_request_without_any_frame_or_reference_is_never_sent(self):
        runtime_model_registry.replace([_minimax()])
        gateway = self._gateway()
        gateway._ark_video = Mock(side_effect=AssertionError("text-to-video must not reach Seedance"))
        with patch.object(MiniMaxH3Client, "create_video", side_effect=AssertionError("text-to-video must not reach H3")), \
                self.assertLogs("app.core.model_gateway", level="ERROR") as logs:
            for model in ("MiniMax-H3", gateway.seedance_model_name, "kling-v2"):
                self.assertIsNone(gateway.generate_video(model, prompt="只有一句提示词", image_url=None, duration=5))
        self.assertTrue(all("禁止文生视频" in line for line in logs.output))

    def test_an_ark_rejection_is_logged_with_its_code(self):
        gateway = self._gateway()
        response = Mock(status_code=400, text="{}")
        response.json.return_value = {"error": {"code": "InvalidParameter", "message": "image aspect ratio out of range"}}
        with patch("requests.post", return_value=response), \
                self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            url = gateway._ark_video("ark-key", "https://ark.example/api/v3", "p", ref_images=["https://cdn/a.jpeg"], duration=5)

        self.assertIsNone(url)
        self.assertIn("InvalidParameter image aspect ratio out of range", logs.output[0])

    def test_a_first_frame_request_leaves_the_ratio_to_the_image(self):
        gateway = self._gateway()
        response = Mock(status_code=400, text="{}")
        response.json.return_value = {"error": {"code": "InvalidParameter", "message": "stop here"}}
        sent = []
        for frames in ({"first_frame": "https://cdn/f.jpeg"},
                       {"first_frame": "https://cdn/f.jpeg", "last_frame": "https://cdn/l.jpeg"},
                       {"ref_images": ["https://cdn/a.jpeg"]}):
            with patch("requests.post", return_value=response) as post, \
                    self.assertLogs("app.core.model_gateway", level="WARNING"):
                gateway._ark_video("ark-key", "https://ark.example/api/v3", "p", duration=5, ratio="9:16", **frames)
            sent.append(post.call_args.kwargs["json"])

        self.assertNotIn("ratio", sent[0])
        self.assertNotIn("ratio", sent[1])
        self.assertEqual(sent[2]["ratio"], "9:16")


class VideoModelAvailabilityTests(RegistryIsolation):
    def test_a_model_centre_video_model_takes_priority_over_the_projects_stale_one(self):
        runtime_model_registry.replace([_minimax()])

        self.assertEqual(ModelGateway.effective_video_model("doubao-seedance-2-5-260628"), "MiniMax-H3")
        self.assertEqual(ModelGateway.effective_video_model("MiniMax-H3"), "MiniMax-H3")
        self.assertEqual(ModelGateway.video_model_problem("seedance", "doubao-seedance-2-5-260628"), "")
        self.assertEqual(ModelGateway.enabled_video_models(), ["MiniMax-H3"])

    def test_without_any_centre_video_model_the_configuration_file_model_is_used(self):
        self.assertEqual(ModelGateway.effective_video_model("doubao-seedance-2-0-260128"), "doubao-seedance-2-0-260128")
        self.assertEqual(ModelGateway.video_model_problem("seedance", "doubao-seedance-2-0-260128"), "")

    def test_the_gateway_renders_a_stale_project_model_with_the_centre_model(self):
        runtime_model_registry.replace([_minimax()])
        gateway = ModelGateway()
        gateway._ark_video = Mock(side_effect=AssertionError("the .env Seedance must not render while the centre has a video model"))
        sent = {}

        def create(client, request):
            sent["model"] = request.model
            return Mock(video_url="https://cdn/h3.mp4", task_id=None)

        with patch.object(MiniMaxH3Client, "create_video", create):
            url = gateway.generate_video("doubao-seedance-2-5-260628", prompt="雨夜对峙", image_url="https://cdn/frame.jpeg", duration=8)

        self.assertEqual((url, sent["model"]), ("https://cdn/h3.mp4", "MiniMax-H3"))


def _project(status: str = "completed") -> dict:
    return {
        "task_id": "vm", "owner_user_id": "u1", "status": status, "current_stage": 5,
        "stage_progress": {"stage": 5, "status": "running"} if status == "running" else {},
        "config": {"video_model": "doubao-seedance-2-5-260628", "llm_model": "deepseek-flash", "image_model": "img", "tts_model": "tts"},
        "assets": {"4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "沈砚推门", "duration": "5秒"}], "5_admission": {"decision": "blocked"}},
    }


class ProjectVideoModelTests(RegistryIsolation):
    def setUp(self):
        super().setUp()
        runtime_model_registry.replace([_minimax()])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("vm", _project())
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = TestClient(app)

    def test_the_workspace_and_admission_use_the_centre_model_and_say_so(self):
        with patch.object(drama_api, "service", self.service):
            before = self.client.get("/api/drama/vm/shots/visual").json()
            refused = self.client.put("/api/drama/vm/video-model", json={"video_model": "doubao-seedance-2-0-260128"})
            switched = self.client.put("/api/drama/vm/video-model", json={"video_model": "MiniMax-H3"})
        admission = self.service.assess_video_admission("vm")

        self.assertEqual((before["video_model"], before["video_model_issue"]), ("MiniMax-H3", ""))
        self.assertIn("doubao-seedance-2-5-260628", before["video_model_note"])
        self.assertEqual(before["duration_options"], list(range(4, 16)))
        self.assertEqual(admission["video_model"], "MiniMax-H3")
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual((switched.json()["video_model"], switched.json()["video_model_note"]), ("MiniMax-H3", ""))
        self.assertEqual(self.repo.get_task("vm")["config"]["video_model"], "MiniMax-H3")

    def test_stage_five_writes_the_centre_model_into_the_project_before_planning(self):
        task = _project()
        with patch.object(self.service, "_missing_stage_outputs", return_value=[]):
            self.service._assert_stage_prerequisites(task, 5)
        self.assertEqual(task["config"]["video_model"], "MiniMax-H3")
        self.assertEqual(task["config"]["video_model_replaced"], {"from": "doubao-seedance-2-5-260628", "to": "MiniMax-H3"})

    def test_the_model_is_not_switched_under_a_running_stage(self):
        self.repo.save_task("vm", _project("running"))
        with patch.object(drama_api, "service", self.service):
            response = self.client.put("/api/drama/vm/video-model", json={"video_model": "MiniMax-H3"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.repo.get_task("vm")["config"]["video_model"], "doubao-seedance-2-5-260628")

    def test_update_config_refuses_a_model_change_while_running_but_keeps_other_edits_working(self):
        self.repo.save_task("vm", _project("running"))
        base = {
            "titleSuggestion": "雨夜对峙", "llmModel": "deepseek-flash", "imageModel": "img", "ttsModel": "tts",
            "videoModel": "doubao-seedance-2-5-260628", "shotStyle": "cinematic",
        }
        kept = self.service.update_task_config("vm", DramaCreateRequest.model_validate(base))
        self.assertEqual(kept["config"]["shot_style"], "cinematic")
        with self.assertRaisesRegex(ValueError, "暂不能更换模型"):
            self.service.update_task_config("vm", DramaCreateRequest.model_validate({**base, "videoModel": "MiniMax-H3"}))
        self.assertEqual(self.repo.get_task("vm")["config"]["video_model"], "doubao-seedance-2-5-260628")


if __name__ == "__main__":
    unittest.main()
