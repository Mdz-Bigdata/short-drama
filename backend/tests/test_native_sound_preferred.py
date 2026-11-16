# -*- coding: utf-8 -*-
"""A video model's own sound comes first, wherever a clip is picked, repaired, composed or produced.

No network and no model. What is pinned: picking another take that has its own sound drops the
earlier dub; a region repair that comes back with sound keeps it; the canvas compose node no
longer strips the clips' own sound; a provider declared in data can say it makes sound; and the
single-episode producer has the model speak the lines and dubs only a clip that came back silent.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core import media_compositor, studio_canvas
from app.core.providers.declarative_video import declared_video_endpoints
from app.core.video_references import uses_native_soundtrack, video_native_audio
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from app.service.studio_canvas_runs import CanvasRunner
from tests.test_provider_pools import _spec

RAW, OTHER = "https://cdn/1.mp4", "https://cdn/1-b.mp4"


def _task(model: str = "seedance2.0", **clip) -> dict:
    return {
        "task_id": "t", "owner_user_id": "u", "status": "completed", "current_stage": 5, "config": {"video_model": model},
        "assets": {
            "4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "沈砚推门而入"}],
            "5": [{"shot_id": 1, "scene_id": "E1S01", "shot_uid": 100101, "video_url": RAW, "candidates": [RAW, OTHER], "duration": 6, **clip}],
        },
    }


class _ServiceCase(unittest.TestCase):
    def _service(self, task: dict) -> DramaService:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        self.repo.save_task("t", task)
        service = DramaService()
        service.repo = self.repo
        workspace = patch.object(service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)
        return service

    def _clip(self) -> dict:
        return self.repo.get_task("t")["assets"]["5"][0]


class PickingAnotherTakeTests(_ServiceCase):
    def _pick(self, task: dict, heard):
        service = self._service(task)
        with patch("app.service.drama_service.media_compositor.keep_clip", return_value="https://kept/1-b.mp4") as keep, \
                patch("app.service.drama_service.media_compositor.clip_has_sound", return_value=heard), \
                patch("app.service.drama_service.media_compositor.attach_audio_to_clip", return_value="https://dubbed/1-b.mp4") as attach:
            service.select_shot_candidate("t", 1, OTHER, scene_id="E1S01")
        return self._clip(), keep, attach

    def test_a_take_with_its_own_sound_drops_the_earlier_dub(self):
        clip, _keep, attach = self._pick(_task(voice_path="/media/dub.mp3", native_audio=False), True)
        attach.assert_not_called()
        self.assertEqual(clip["video_url"], "https://kept/1-b.mp4")
        self.assertTrue(clip["native_audio"])
        self.assertNotIn("voice_path", clip)
        self.assertEqual(clip["selected_candidate"], OTHER)

    def test_a_silent_take_or_one_that_cannot_be_heard_keeps_the_dub(self):
        for heard in (False, None):
            with self.subTest(heard=heard):
                clip, _keep, attach = self._pick(_task(voice_path="/media/dub.mp3", native_audio=False), heard)
                attach.assert_called_once()
                self.assertEqual(clip["video_url"], "https://dubbed/1-b.mp4")
                self.assertEqual(clip["voice_path"], "/media/dub.mp3")
                self.assertFalse(clip["native_audio"])

    def test_a_shot_once_marked_silent_is_heard_again_when_the_new_take_has_sound(self):
        clip, _keep, attach = self._pick(_task(native_audio=False), True)
        attach.assert_not_called()
        self.assertTrue(clip["native_audio"])

    def test_a_model_that_makes_no_sound_is_dubbed_as_before(self):
        clip, keep, attach = self._pick(_task("kling3", voice_path="/media/dub.mp3"), True)
        keep.assert_not_called()
        attach.assert_called_once()
        self.assertEqual(clip["voice_path"], "/media/dub.mp3")


class RegionRepairTests(_ServiceCase):
    def _repair(self, task: dict, heard):
        service = self._service(task)
        service.gateway = MagicMock()
        service.gateway.generate_video.return_value = "https://cdn/fixed.mp4"
        with patch("app.core.clip_fixes.provider_can_fetch", return_value=True), \
                patch("app.core.clip_fixes.clip_seconds", return_value=6.0), \
                patch.object(DramaService, "_repair_supported", return_value=True), \
                patch("app.service.drama_service.media_compositor.keep_clip", return_value="https://kept/fixed.mp4"), \
                patch("app.service.drama_service.media_compositor.clip_has_sound", return_value=heard), \
                patch("app.service.drama_service.threading.Thread") as thread:
            service.repair_shot("t", 1, box={"x": 0, "y": 0, "w": 0.5, "h": 0.5}, note="去掉多出来的人", scene_id="E1S01")
            thread.call_args.kwargs["target"]()
        return self._clip()

    def test_a_repair_that_comes_back_with_sound_keeps_it(self):
        clip = self._repair(_task(voice_path="/media/dub.mp3", native_audio=False), True)
        self.assertEqual((clip["repair"]["status"], clip["video_url"]), ("done", "https://kept/fixed.mp4"))
        self.assertTrue(clip["native_audio"])
        self.assertFalse(clip.get("voice_path"))

    def test_a_silent_repair_leaves_the_dub_where_it_was(self):
        clip = self._repair(_task(voice_path="/media/dub.mp3", native_audio=False), False)
        self.assertEqual(clip["voice_path"], "/media/dub.mp3")
        self.assertFalse(clip["native_audio"])


class CanvasComposeTests(unittest.TestCase):
    def test_clips_that_carry_sound_keep_it_in_the_composed_film(self):
        inputs = studio_canvas.Inputs(clips=["https://cdn/a.mp4", "https://cdn/b.mp4", "https://cdn/c.mp4"])
        with patch.object(media_compositor, "clip_has_sound", side_effect=[True, False, None]), \
                patch.object(media_compositor, "compose_film", return_value="/media/out.mp4") as compose:
            url = CanvasRunner._compose(inputs, "x")
        self.assertEqual(url, "/media/out.mp4")
        self.assertEqual(compose.call_args.kwargs["native_audio"], [True, False, False], "only a clip heard to have sound is trusted")
        self.assertFalse(compose.call_args.kwargs["bgm"])


class DeclaredProviderTests(unittest.TestCase):
    def tearDown(self):
        declared_video_endpoints.replace([])

    def test_a_declared_provider_can_say_it_makes_sound(self):
        declared_video_endpoints.replace([(_spec(), "acme-key")])
        self.assertFalse(video_native_audio("acme-v1"), "silent unless it says otherwise")
        declared_video_endpoints.replace([(_spec(native_audio=True), "acme-key")])
        self.assertTrue(video_native_audio("acme-v1"))
        self.assertTrue(uses_native_soundtrack({"video_model": "acme-v1"}))
        self.assertFalse(uses_native_soundtrack({"video_model": "acme-v1", "native_audio": False}))


class KlingSoundSwitchTests(unittest.TestCase):
    """Kling renders sound only when asked (``sound: "on"``); the ask is a host switch that starts off."""

    def _body(self, model: str) -> dict:
        import json

        import httpx

        from app.core.providers.video_adapters import KlingVideoAdapter, VideoJobRequest

        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_1", "task_status": "submitted"}})

        adapter = KlingVideoAdapter(api_key="ak_test:sk_test", base_url="https://api-singapore.klingai.com", transport=httpx.MockTransport(handler))
        try:
            adapter.create_video(VideoJobRequest(model=model, prompt="雨夜追逐", first_frame="https://cdn.example/first.png", duration_seconds=6))
        finally:
            adapter.close()
        return bodies[0]

    def test_without_the_switch_kling_is_asked_for_nothing_and_dubbed_as_before(self):
        with patch.dict("os.environ", {"KLING_NATIVE_SOUND": ""}):
            self.assertNotIn("sound", self._body("kling-v3"))
            self.assertFalse(video_native_audio("kling3"))
            self.assertFalse(uses_native_soundtrack({"video_model": "kling-v3"}))

    def test_with_the_switch_the_versions_that_can_are_asked_and_keep_their_sound(self):
        with patch.dict("os.environ", {"KLING_NATIVE_SOUND": "1"}):
            self.assertEqual(self._body("kling-v3")["sound"], "on")
            for model in ("kling3", "kling-v3", "kling-v3-turbo", "kling-4.0"):
                self.assertTrue(uses_native_soundtrack({"video_model": model}), model)
            # Not on the capability map for sound: asked for nothing, dubbed.
            self.assertNotIn("sound", self._body("kling-v2-1"))
            for model in ("kling-o1", "kling-v2-6", "kling-v2-1", "kling"):
                self.assertFalse(video_native_audio(model), model)


if __name__ == "__main__":
    unittest.main()
