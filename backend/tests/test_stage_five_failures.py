"""A video provider's refusal is kept per storyboard board and shown on the shots of that board until it renders."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import video_failures
from app.core.shot_motion_contract import ShotMotionContract
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from tests.test_shot_visual_workspace import _panel

MINIMAX_1026 = "MiniMax H3 请求失败: RuntimeError: MiniMax H3 task ended with status=failed: 1026 input new_sensitive, input image sensitive"
FRAME = "http://localhost:8000/media/storyboards/frames/E1S09_p{}.png"
ARK_SENSITIVE = (
    "HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation "
    "The request failed because the input image may contain real person."
)


class ClassifyTests(unittest.TestCase):
    def test_minimax_1026_and_ark_sensitive_images_are_input_image_refusals(self):
        self.assertEqual(video_failures.classify(MINIMAX_1026), ("input_image_sensitive", "1026"))
        self.assertEqual(
            video_failures.classify(ARK_SENSITIVE),
            ("input_image_sensitive", "InputImageSensitiveContentDetected.PrivacyInformation"),
        )
        self.assertEqual(
            video_failures.classify("HTTP 400 InputImageSensitiveContentDetected "),
            ("input_image_sensitive", "InputImageSensitiveContentDetected"),
        )

    def test_other_refusals_are_provider_errors_with_their_code(self):
        self.assertEqual(
            video_failures.classify("MiniMax H3 请求失败: RuntimeError: HTTP 400, model MiniMax-H3 does not support resolution 1080P"),
            ("provider_error", ""),
        )
        self.assertEqual(video_failures.classify("MiniMax H3 未返回视频：1002 rate limit"), ("provider_error", "1002"))
        self.assertEqual(video_failures.classify("HTTP 400 InvalidParameter duration"), ("provider_error", "InvalidParameter"))
        # A number that is not a MiniMax status code stays out of the code field.
        self.assertEqual(video_failures.classify("镜头 1001 视频未生成：供应商未返回视频"), ("provider_error", ""))

    def test_inline_reference_bytes_are_counted_not_stored(self):
        decision = {"first_frame": "/media/a.png", "last_frame": None, "reference_images": ["data:image/png;base64,xx", "/media/a.png", "https://cdn/b.png"]}
        self.assertEqual(video_failures.sent_images(decision), ["/media/a.png", "https://cdn/b.png"])
        self.assertEqual(video_failures.inline_count(decision), 1)


def _shot(scene_id: str, index: int) -> dict:
    image = f"http://localhost:8000/media/storyboards/frames/{scene_id}_p{index}.png"
    contract = ShotMotionContract.from_panel(_panel(index), storyboard_image=image)
    return {
        "shot_id": index, "scene_id": scene_id, "size": "MS", "motion": "Dolly In", "desc": "沈砚推门而入",
        "dialogue": "", "sound": "铁链轻响", "duration": "3", "image_url": image,
        "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint,
    }


def _task(granularity: str) -> dict:
    # 各场镜号都从 1 起：E1S01 与 E1S09 都有第 1、2 镜。
    return {
        "task_id": "fail-1", "owner_user_id": "u1", "current_stage": 4, "status": "running",
        "stage_progress": {"stage": 5, "status": "running", "calls": []},
        "workflow_control": {"run_id": "run-1", "active": True, "pause_requested": False},
        "config": {
            "video_model": "MiniMax-H3", "image_model": "seedream", "tts_model": "elevenlabs", "llm_model": "deepseek",
            "title_suggestion": "朕的江山", "director_style": "realistic", "shot_style": "cinematic", "episode_count": 1,
            "video_granularity": granularity,
        },
        "assets": {
            "1": "方案", "2": "第1集 开场\n场景1：天牢\n沈砚：……", "3": "角色", "3_characters": [],
            "4": [_shot("E1S01", 1), _shot("E1S01", 2), _shot("E1S09", 1), _shot("E1S09", 2)],
        },
        "logs": {}, "chat_history": [],
    }


class StageFiveFailureRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        # 这里验证失败记录；H3 官方六段式改写(要调文本模型)见 tests/test_h3_native.py。
        native_off = patch.dict("os.environ", {"H3_NATIVE_PROMPTS": "0"})
        native_off.start()
        self.addCleanup(native_off.stop)

    def _run(self, task, *, refuse_scene: str | None, refuse_retry: bool = False):
        self.repo.save_task(task["task_id"], task)
        last = {"reason": ""}

        def generate_video(model, image_url, prompt, *args, **kwargs):
            sent = [image_url or "", *(kwargs.get("ref_images") or [])]
            frameless_retry = last["reason"] and not any("/frames/" in str(url) for url in sent)
            if refuse_scene and (any(refuse_scene in str(url) for url in sent) or (refuse_retry and frameless_retry)):
                last["reason"] = MINIMAX_1026
                return None
            last["reason"] = ""
            return f"https://cdn/{abs(hash(tuple(sent))) % 10000}.mp4"

        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "last_video_failure", side_effect=lambda: last["reason"]), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"), \
             patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "1"}):
            try:
                self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
            except RuntimeError as exc:
                if not refuse_scene:
                    raise
                self.assertIn("1026", str(exc), "the stage error still carries the provider's words")
        return self.repo.get_task(task["task_id"])

    def _rerun(self, stored: dict, *, refuse_scene: str | None, run_id: str) -> dict:
        stored["status"] = "running"
        stored["stage_progress"] = {"stage": 5, "status": "running", "calls": []}
        stored["workflow_control"] = {"run_id": run_id, "active": True, "pause_requested": False}
        return self._run(stored, refuse_scene=refuse_scene)

    def _failures_by_shot(self, task_id: str) -> dict:
        workspace = self.service.get_shot_visual_workspace(task_id)
        return {(shot["scene_id"], shot["shot_id"]): shot["failure"] for shot in workspace["shots"]}

    def test_a_refused_board_shows_on_its_own_shots_and_clears_once_it_renders(self):
        stored = self._run(_task("slice"), refuse_scene="E1S09")

        [(key, entry)] = stored["assets"][video_failures.FAILURES_KEY].items()
        self.assertEqual(key, "100901")
        self.assertEqual(entry["scene_id"], "E1S09")
        self.assertEqual(entry["shot_uids"], [100901, 100902])
        self.assertEqual((entry["kind"], entry["code"]), ("input_image_sensitive", "1026"))
        self.assertIn("input image sensitive", entry["message"])
        self.assertEqual(entry["frames"], [FRAME.format(1), FRAME.format(2)])
        self.assertTrue(set(entry["frames"]) <= set(entry["inputs"]), "the inputs list what was actually sent")

        failures = self._failures_by_shot("fail-1")
        self.assertIsNone(failures[("E1S01", 1)], "the same shot number in another scene is not marked")
        self.assertIsNone(failures[("E1S01", 2)])
        for number in (1, 2):
            failure = failures[("E1S09", number)]
            self.assertEqual(failure["kind"], "input_image_sensitive")
            self.assertEqual(failure["code"], "1026")
            self.assertIn("1026 input new_sensitive", failure["message"])
            self.assertEqual(failure["panels"], [FRAME.format(1), FRAME.format(2)])
            self.assertIn("按当前站位重画本场", failure["hint"])
            self.assertIn("E1S09", failure["hint"])

        again = self._rerun(stored, refuse_scene=None, run_id="run-2")
        self.assertEqual(again["assets"][video_failures.FAILURES_KEY], {})
        self.assertTrue(all(failure is None for failure in self._failures_by_shot("fail-1").values()))

    def _per_shot_task(self) -> dict:
        task = _task("shot")
        task["assets"]["3_sheets"] = {"沈砚": "https://cdn/sheet.png"}
        return task

    def test_per_shot_boards_are_keyed_by_the_unique_shot_number(self):
        stored = self._run(self._per_shot_task(), refuse_scene="E1S09", refuse_retry=True)
        records = stored["assets"][video_failures.FAILURES_KEY]
        self.assertEqual(sorted(records), ["100901", "100902"])
        self.assertEqual(records["100902"]["frames"], [FRAME.format(2)])
        self.assertEqual(records["100902"]["inputs"], [FRAME.format(2), "https://cdn/sheet.png"])
        self.assertTrue(records["100902"]["retried_without_frames"])
        failures = self._failures_by_shot("fail-1")
        self.assertEqual(failures[("E1S09", 2)]["panels"], [FRAME.format(2)])
        self.assertIn("参考图", failures[("E1S09", 2)]["hint"])
        self.assertIsNone(failures[("E1S01", 2)])

    def test_a_board_the_frameless_retry_rescues_leaves_no_failure(self):
        stored = self._run(self._per_shot_task(), refuse_scene="E1S09")
        self.assertEqual(stored["assets"].get(video_failures.FAILURES_KEY) or {}, {})
        self.assertTrue(all(clip["video_url"] for clip in stored["assets"]["5"]))

    def test_a_progress_save_of_the_stage_copy_does_not_drop_the_record(self):
        stored = self._run(self._per_shot_task(), refuse_scene="E1S09", refuse_retry=True)
        stale = dict(stored)
        stale["assets"] = {key: value for key, value in stored["assets"].items() if key != video_failures.FAILURES_KEY}
        self.repo.save_task("fail-1", stale)
        self.assertEqual(sorted(self.repo.get_task("fail-1")["assets"][video_failures.FAILURES_KEY]), ["100901", "100902"])

    def test_the_hint_points_at_the_references_when_the_frameless_retry_was_refused_too(self):
        entry = video_failures.build(
            scene_id="E1S09", shot_uids=[100901], message=MINIMAX_1026, frames=["/media/p1.png"], inputs=[],
            retried_without_frames=True,
        )
        self.assertIn("参考图", video_failures.hint(entry))
        self.assertNotIn("重画本场", video_failures.hint(entry))
        plain = video_failures.build(scene_id="E1S09", shot_uids=[100901], message="HTTP 500 InternalError", frames=[], inputs=[])
        self.assertEqual(plain["kind"], "provider_error")
        self.assertIn("重跑第 5 阶段", video_failures.hint(plain))


if __name__ == "__main__":
    unittest.main()
