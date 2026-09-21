import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.camera_motion import (
    duration_options,
    normalize_camera_motion,
    normalize_shot_type,
    render_camera_motion,
    vocabulary,
)
from app.core.shot_motion_contract import ShotMotionContract
from app.repository.task_repo import TaskRepository
from app.schema.production import StoryboardPanel
from app.schema.shot_visual import ShotVisualSettings
from app.service.drama_service import DramaService
from main import app


class CameraMotionVocabularyTests(unittest.TestCase):
    def test_storyboard_spellings_collapse_onto_the_provider_vocabulary(self):
        for raw, expected in (
            ("Dolly In", "Push In"), ("Slow Dolly In", "Push In"), ("dolly_zoom", "Push In"),
            ("Lateral Tracking", "Truck Right"), ("跟拍", "Tracking Shot"), ("镜头缓慢推近主体", "Zoom In"),
            ("固定镜头", "Static"), ("Establishing Shot", "Static"), ("PAN_LEFT", "Pan Left"),
            ("环绕", "Orbit"), ("手持", "Shake"), ("升镜", "Pedestal Up"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_camera_motion(raw), (expected, True))
        self.assertEqual(normalize_camera_motion("镜头先推再拉再摇"), ("Static", False))
        self.assertEqual(normalize_camera_motion(""), ("Static", False))

    def test_shot_sizes_collapse_onto_the_nine_shot_types(self):
        for raw, expected in (
            ("MS", "Medium Shot"), ("MCU", "Medium Close-up"), ("FS", "Long Shot"), ("特写", "Close-up"),
            ("大特写", "Extreme Close-up"), ("过肩", "Over-the-shoulder"), ("POV", "Point-of-view"),
            ("中远景", "Medium Long Shot"), ("大全景", "Extreme Long Shot"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_shot_type(raw), (expected, True))
        self.assertEqual(normalize_shot_type("莫名其妙"), ("Medium Shot", False))

    def test_rendering_uses_each_providers_documented_phrasing(self):
        self.assertEqual(render_camera_motion("Push In", "minimax_h3"), "[Push in] 镜头缓慢推进")
        self.assertEqual(render_camera_motion("Orbit", "minimax_h3"), "镜头围绕主体环绕（Orbit）")
        self.assertEqual(render_camera_motion("dolly in", "seedance"), "镜头缓慢推进（Push In）")
        self.assertEqual(render_camera_motion("nonsense", "kling"), "固定机位，镜头保持不动（Static）")

    def test_duration_options_follow_the_selected_video_model(self):
        self.assertEqual(duration_options("seedance2.5"), list(range(4, 31)))
        self.assertEqual(duration_options("MiniMax-H3"), list(range(4, 16)))
        self.assertEqual(duration_options(""), list(range(4, 11)))
        vocab = vocabulary()
        self.assertEqual(len(vocab["camera_motions"]), 16)
        self.assertEqual(len(vocab["shot_types"]), 9)
        self.assertEqual(vocab["camera_motions"][0], {"value": "Static", "label": "固定"})

    def test_settings_reject_moves_outside_the_vocabulary(self):
        settings = ShotVisualSettings(camera_motion="dolly in", shot_type="ms", duration_seconds=6)
        self.assertEqual((settings.camera_motion, settings.shot_type), ("Push In", "Medium Shot"))
        with self.assertRaises(ValueError):
            ShotVisualSettings(camera_motion="推拉摇移一起上", shot_type="ms", duration_seconds=6)


def _panel(index: int = 1) -> StoryboardPanel:
    return StoryboardPanel(
        index=index, characters=["沈砚"], shot_size="MS", camera_angle="平视", camera_movement="Dolly In",
        camera_reason="推进强调情绪", lens_mm=50, aperture="T2.8", composition="人物居中，前景门框",
        action_axis="摄影机在南侧", eyeline="沈砚望向门口", subject_action="沈砚推门而入", expression="警惕",
        scene="天牢", props=["铁链"], effects=["月光尘埃"], dialogue="", sound="铁链轻响",
        lighting="冷白月光", edit_in="承接上一镜", edit_out="停在门内", generation_mode="auto",
        continuity_out="停在门内，铁链垂落",
    )


def _task_with_shots() -> dict:
    contract = ShotMotionContract.from_panel(_panel(), storyboard_image="/media/p1.png")
    return {
        "task_id": "visual-task",
        "owner_user_id": "u1",
        "current_stage": 5,
        "status": "completed",
        "config": {"video_model": "seedance2.5", "title_suggestion": "朕的江山"},
        "assets": {
            "4": [{
                "shot_id": 1, "scene_id": "E1S01", "size": "MS", "motion": "Dolly In", "desc": "沈砚推门而入",
                "dialogue": "", "sound": "铁链轻响", "duration": "3", "image_url": "/media/p1.png",
                "storyboard_prompt": "沈砚推门而入的分镜画面", "motion_contract": contract.model_dump(mode="json"),
                "contract_fingerprint": contract.contract_fingerprint,
            }],
            "5": [{
                "shot_id": 1, "size": "MS", "motion": "Dolly In", "duration": 6, "video_url": "/media/c1.mp4",
                "image_url": "/media/p1.png", "motion_prompt": "【批次 1】…",
                "video_route_decision": {"mode": "first_last_frame", "provider_family": "seedance"},
            }],
        },
    }


class ShotVisualWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("visual-task", _task_with_shots())
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = TestClient(app)

    def test_workspace_derives_settings_from_the_storyboard_and_the_model_capability(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/visual-task/shots/visual")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider_family"], "seedance")
        self.assertEqual(body["duration_options"], list(range(4, 31)))
        self.assertEqual(len(body["camera_motions"]), 16)
        shot = body["shots"][0]
        self.assertEqual(shot["settings_source"], "derived")
        self.assertEqual(shot["settings"]["camera_motion"], "Push In")
        self.assertEqual(shot["settings"]["shot_type"], "Medium Shot")
        self.assertEqual(shot["settings"]["duration_seconds"], 6)
        self.assertEqual(shot["video_url"], "/media/c1.mp4")
        self.assertEqual(shot["video_prompt"], "【批次 1】…")
        self.assertFalse(shot["stale"])
        self.assertEqual(body["current_stage"], 5)

    def test_editing_updates_the_contract_marks_the_clip_stale_and_keeps_the_stage(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.put("/api/drama/visual-task/shots/1/visual", json={
                "camera_motion": "环绕", "shot_type": "特写", "duration_seconds": 8,
                "action": "沈砚停步回望", "ambiance_audio": "远处滴水", "lighting": "", "ambiance": "",
            })
            self.assertEqual(response.status_code, 200, response.text)
            rejected = self.client.put("/api/drama/visual-task/shots/1/visual", json={
                "camera_motion": "Orbit", "shot_type": "Close-up", "duration_seconds": 45,
            })
            missing = self.client.put("/api/drama/visual-task/shots/9/visual", json={
                "camera_motion": "Orbit", "shot_type": "Close-up", "duration_seconds": 8,
            })

        shot = response.json()["shots"][0]
        self.assertEqual(shot["settings_source"], "edited")
        self.assertEqual(shot["settings"]["camera_motion"], "Orbit")
        self.assertTrue(shot["stale"])
        self.assertIn("重跑第 5 阶段", shot["stale_reason"])
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("不在模型支持范围", rejected.json()["detail"])
        self.assertEqual(missing.status_code, 422)

        stored = self.repo.get_task("visual-task")
        record = stored["assets"]["4"][0]
        contract = ShotMotionContract.model_validate(record["motion_contract"])
        self.assertEqual((contract.camera_movement, contract.shot_size), ("Orbit", "Close-up"))
        self.assertEqual(record["contract_fingerprint"], contract.contract_fingerprint)
        self.assertEqual((record["motion"], record["size"], record["duration"]), ("Orbit", "Close-up", "8"))
        self.assertEqual(record["visual"]["action"], "沈砚停步回望")
        # Editing camera settings never advances or rewinds the eight-agent flow.
        self.assertEqual(stored["current_stage"], 5)
        self.assertEqual(stored["status"], "completed")

    def test_edits_are_refused_while_a_stage_is_running(self):
        task = self.repo.get_task("visual-task")
        task["status"] = "running"
        task["stage_progress"] = {"status": "running", "stage": 5}
        self.repo.save_task("visual-task", task)
        with patch.object(drama_api, "service", self.service):
            response = self.client.put("/api/drama/visual-task/shots/1/visual", json={
                "camera_motion": "Static", "shot_type": "Medium Shot", "duration_seconds": 6,
            })
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
