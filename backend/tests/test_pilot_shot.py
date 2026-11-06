"""首镜试拍：只拍一段，整批时复用它，试拍过的项目不能直接往下做。"""

import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import generation_queue as gq, pilot_shot
from app.core.shot_motion_contract import ShotMotionContract
from app.service.drama_service import DramaService, StagePrerequisiteError
from main import app
from tests.test_shot_visual_workspace import _panel
from tests import test_stage_five_queue as queue_fixture
from tests.test_stage_five_queue import _task


def _request(number, cast=("沈砚",), desc="沈砚推门", chain_from=None, beats=None):
    contract = ShotMotionContract.from_panel(_panel(1)).model_copy(update={"characters": list(cast)})
    req = {"shot_id": number, "shot_uid": 100100 + number, "contract": contract, "desc": desc}
    if chain_from:
        req["chain_from"] = chain_from
    if beats:
        req["slice"] = {"scene_id": "E1S01", "label": f"片段{number}", "beats": beats}
    return req


class PickTests(unittest.TestCase):
    def test_the_fewest_people_and_actions_win_and_the_reason_says_so(self):
        requests = {
            1: _request(1, cast=("沈砚", "林晚")),
            2: _request(2, desc="沈砚推门；随后沈砚落座"),
            3: _request(3),
        }
        number, reason = pilot_shot.pick(requests)
        self.assertEqual(number, 3)
        self.assertIn("1 个人、1 个动作", reason)

    def test_an_empty_shot_is_the_last_choice_because_it_proves_nothing(self):
        requests = {1: _request(1, cast=("空镜（无人物）",)), 2: _request(2, cast=("沈砚", "林晚", "周叔"))}
        self.assertEqual(pilot_shot.pick(requests)[0], 2)
        self.assertIn("没有人物", pilot_shot.pick({1: _request(1, cast=("空镜（无人物）",))})[1])

    def test_a_board_clip_counts_all_its_moments(self):
        crowded = [
            {"shot_uid": 1, "characters": ["沈砚"], "desc": "推门"},
            {"shot_uid": 2, "characters": ["林晚"], "desc": "抬头"},
        ]
        requests = {1: _request(1, beats=crowded), 2: _request(2)}
        self.assertEqual(pilot_shot.pick(requests)[0], 2)

    def test_a_continuation_needs_its_first_part(self):
        requests = {1: _request(1, cast=("甲", "乙")), 2: _request(2, chain_from=1), 3: _request(3, cast=("甲", "乙"))}
        self.assertEqual(pilot_shot.pick(requests)[0], 1, "第 2 段要接第 1 段的末帧，不能单独试拍")
        self.assertEqual(pilot_shot.pick(requests, wanted_uid=100102)[0], 1)

    def test_a_chosen_shot_wins_and_an_unknown_one_falls_back(self):
        requests = {1: _request(1, cast=("甲", "乙")), 2: _request(2)}
        self.assertEqual(pilot_shot.pick(requests, wanted_uid=100101), (1, "你选的这一镜"))
        self.assertEqual(pilot_shot.pick(requests, wanted_uid=999)[0], 2)


class PilotRunTests(queue_fixture.StageFiveQueueTests):
    def _pilot(self, task):
        task.setdefault("assets", {})[pilot_shot.ASSET_KEY] = pilot_shot.requested()
        return self._run(task)

    def test_only_one_clip_is_made_and_the_stage_is_not_complete(self):
        stored = self._pilot(_task(3))
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(len(stored["assets"]["5"]), 1)
        self.assertEqual(stored["assets"][pilot_shot.ASSET_KEY]["state"], pilot_shot.READY)
        self.assertEqual(len(stored["assets"][gq.QUEUE_KEY]["items"]), 2, "视频和入片各一项")
        self.assertIn("5.首镜试拍后其余片段尚未生成", self.service._missing_stage_outputs(stored, 5))
        with self.assertRaises(StagePrerequisiteError):
            self.service._assert_stage_prerequisites(stored, 6)

    def test_the_batch_reuses_the_pilot_and_pays_only_for_the_rest(self):
        stored = self._pilot(_task(3))
        pilot_url = stored["assets"]["5"][0]["video_url"]
        pilot_uid = stored["assets"][pilot_shot.ASSET_KEY]["shot_uid"]
        self.submitted.clear()
        stored["status"] = "running"
        with patch("app.service.drama_service.media_compositor.media_available", return_value=True):
            stored = self._run(stored)
        self.assertEqual(len(self.submitted), 2, "试拍那段不再花钱")
        self.assertEqual(len(stored["assets"]["5"]), 3)
        self.assertNotIn(pilot_shot.ASSET_KEY, stored["assets"])
        again = next(clip for clip in stored["assets"]["5"] if pilot_uid in (clip.get("shot_uids") or [clip.get("shot_uid")]))
        self.assertEqual(again["video_url"], pilot_url)
        self.assertNotIn("5.首镜试拍后其余片段尚未生成", self.service._missing_stage_outputs(stored, 5))

    def test_board_clips_make_one_clip_per_scene_and_the_batch_reuses_it(self):
        """默认的出片方式：一场戏一段视频，试拍的是一整段。"""
        task = _task(4)
        task["config"].pop("video_granularity")
        for shot in task["assets"]["4"][2:]:
            shot["scene_id"] = "E1S02"
        stored = self._pilot(task)
        self.assertEqual(len(self.submitted), 1)
        record = stored["assets"][pilot_shot.ASSET_KEY]
        self.assertEqual(len(record["shot_uids"]), 2, "这段覆盖这场的两个瞬间")
        self.assertEqual(record["scene_id"], "E1S01")
        self.submitted.clear()
        stored["status"] = "running"
        with patch("app.service.drama_service.media_compositor.media_available", return_value=True):
            stored = self._run(stored)
        self.assertEqual(len(self.submitted), 1, "只补另一场那一段")
        self.assertEqual(len(stored["assets"]["5"]), 2)

    def test_a_reshoot_keeps_the_reason_it_was_picked_for(self):
        task = _task(2)
        task["assets"][pilot_shot.ASSET_KEY] = pilot_shot.requested(100102, "人最少")
        stored = self._run(task)
        self.assertEqual(stored["assets"][pilot_shot.ASSET_KEY]["reason"], "人最少")
        self.assertEqual(stored["assets"][pilot_shot.ASSET_KEY]["shot_uid"], 100102)

    def test_a_second_pilot_keeps_the_clips_that_already_exist(self):
        stored = self._run(_task(3))
        self.assertEqual(len(stored["assets"]["5"]), 3)
        stored["status"] = "running"
        self.submitted.clear()
        target = stored["assets"]["5"][1]
        target["stale"] = True
        stored["assets"][pilot_shot.ASSET_KEY] = pilot_shot.requested(target["shot_uid"])
        with patch("app.service.drama_service.media_compositor.media_available", return_value=True):
            stored = self._run(stored)
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(len(stored["assets"]["5"]), 3, "其余片段没有丢")

    def test_a_failed_pilot_says_why_and_the_next_batch_run_is_a_real_batch(self):
        task = _task(2)
        task["assets"][pilot_shot.ASSET_KEY] = pilot_shot.requested()
        self.repo.save_task(task["task_id"], task)
        with patch.object(self.service.gateway, "generate_video", return_value=None), \
             patch.object(self.service.gateway, "last_video_failure", return_value="HTTP 400 疑似真人"), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            with self.assertRaises(RuntimeError):
                self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        stored = self.repo.get_task(task["task_id"])
        record = stored["assets"][pilot_shot.ASSET_KEY]
        self.assertEqual(record["state"], pilot_shot.FAILED)
        self.assertIn("疑似真人", record["error"])
        self.assertFalse(pilot_shot.is_requested(stored["assets"]))
        stored["status"] = "running"
        self.submitted.clear()
        stored = self._run(stored)
        self.assertEqual(len(self.submitted), 2)
        self.assertNotIn(pilot_shot.ASSET_KEY, stored["assets"])

    def test_the_workspace_shows_the_clip_and_how_many_are_left(self):
        stored = self._pilot(_task(3))
        stored["status"] = "success"
        stored["workflow_control"] = {}
        stored["stage_progress"] = {"stage": 5, "status": "success"}
        self.repo.save_task(stored["task_id"], stored)
        view = self.service.get_shot_visual_workspace(stored["task_id"])
        pilot = view["pilot"] if isinstance(view, dict) else view.pilot
        self.assertEqual(pilot["state"], pilot_shot.READY)
        self.assertTrue(pilot["video_url"])
        self.assertEqual(pilot["others_left"], 2)
        self.assertEqual(pilot["checks"], ["脸", "服装", "人数", "动作", "口型"])


class ViewTests(unittest.TestCase):
    def test_a_run_that_stopped_halfway_does_not_look_like_it_is_still_running(self):
        assets = {pilot_shot.ASSET_KEY: {"state": pilot_shot.RUNNING, "shot_uids": [1]}}
        self.assertEqual(pilot_shot.view(assets, running_now=True)["state"], pilot_shot.RUNNING)
        stopped = pilot_shot.view(assets, running_now=False)
        self.assertEqual(stopped["state"], pilot_shot.FAILED)
        self.assertIn("没有跑完", stopped["error"])

    def test_no_record_no_view(self):
        self.assertIsNone(pilot_shot.view({}, running_now=False))


class StartTests(queue_fixture.StageFiveQueueTests):
    def _start(self, task, **kwargs):
        self.repo.save_task(task["task_id"], task)

        async def run():
            with patch.object(DramaService, "execute_stage", side_effect=lambda *a, **k: asyncio.sleep(0)) as started:
                result = await self.service.start_pilot_shot(task["task_id"], **kwargs)
                await asyncio.sleep(0)
                return result, started

        return asyncio.run(run())

    def _idle(self, shots=2):
        task = _task(shots)
        task.update(status="success", workflow_control={}, stage_progress={"stage": 4, "status": "success"})
        return task

    def test_a_running_project_is_refused_and_keeps_its_record(self):
        with self.assertRaises(StagePrerequisiteError):
            self._start(_task(2))
        self.assertNotIn(pilot_shot.ASSET_KEY, self.repo.get_task("q5-1")["assets"])

    def test_a_refused_claim_restores_the_previous_record(self):
        task = self._idle()
        task["assets"][pilot_shot.ASSET_KEY] = {"state": pilot_shot.READY, "shot_uids": [1]}
        with patch.object(DramaService, "_claim_stage_task", side_effect=StagePrerequisiteError("准入没过")):
            with self.assertRaises(StagePrerequisiteError):
                self._start(task)
        self.assertEqual(self.repo.get_task("q5-1")["assets"][pilot_shot.ASSET_KEY]["state"], pilot_shot.READY)

    def test_the_problems_of_a_failed_pilot_go_into_the_feedback_ledger(self):
        task = self._idle()
        task["assets"][pilot_shot.ASSET_KEY] = {"state": pilot_shot.READY, "shot_id": 1, "shot_uid": 100101, "shot_uids": [100101]}
        with patch.object(DramaService, "_claim_stage_task", side_effect=lambda task_id, stage, **k: self.repo.get_task(task_id)):
            self._start(task, redo=True, problems=["脸", "口型", "别的"])
        ledger = str(self.repo.get_task("q5-1")["assets"]["5_feedback"])
        self.assertIn("变脸", ledger)
        self.assertIn("口型", ledger)
        self.assertNotIn("别的", ledger)

    def test_redo_marks_the_clip_stale_and_asks_for_the_same_shot(self):
        task = self._idle()
        contract = task["assets"]["4"][0]["motion_contract"]
        uid = 100101
        task["assets"]["5"] = [{"shot_id": 1, "scene_id": "E1S01", "shot_uid": uid, "video_url": "/media/a.mp4", "motion_contract": contract}]
        task["assets"][pilot_shot.ASSET_KEY] = {"state": pilot_shot.READY, "shot_id": 1, "shot_uid": uid, "shot_uids": [uid], "reason": "人最少"}
        with patch.object(DramaService, "_claim_stage_task", side_effect=lambda task_id, stage, **k: self.repo.get_task(task_id)):
            _, started = self._start(task, redo=True)
        stored = self.repo.get_task("q5-1")
        self.assertTrue(stored["assets"]["5"][0]["stale"])
        self.assertEqual(stored["assets"][pilot_shot.ASSET_KEY], pilot_shot.requested(uid, "人最少"))
        started.assert_called_once()


class RouteTests(unittest.TestCase):
    def test_the_route_reports_a_refusal_as_409(self):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin", "id": "u1"}
        self.addCleanup(app.dependency_overrides.clear)

        async def refuse(*_a, **_k):
            raise StagePrerequisiteError("当前制作正在执行")

        with patch.object(drama_api.service, "start_pilot_shot", side_effect=refuse), \
                patch.object(drama_api.service.repo, "get_task", return_value={"task_id": "t", "owner_user_id": "u1"}):
            response = TestClient(app).post("/api/drama/t/shots/pilot", json={})
        self.assertEqual(response.status_code, 409, response.text)


for name in [item for item in dir(queue_fixture.StageFiveQueueTests) if item.startswith("test_")]:
    # 只继承夹具，不重复跑父类的用例。
    for case in (PilotRunTests, StartTests):
        setattr(case, name, None)

if __name__ == "__main__":
    unittest.main()
