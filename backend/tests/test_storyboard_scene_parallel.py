# -*- coding: utf-8 -*-
"""Stage 4 draws the scenes of an episode side by side and ends up where a serial stage would.

Only the provider edge is stubbed: tables and images go through the real ``_generate_scene_board``
and the real stage loop, against a throwaway task store.
"""

import hashlib
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from app.core.model_gateway import ModelGateway
from app.core import usage_ledger
from app.core.storyboard_concurrency import SceneBoardsStopped, SceneTurns, draw_scene_boards
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from app.service.spatial_stage_service import ASSET_KEY
from tests.test_spatial_stage_pipeline import ROWS

SCENE_IDS = ["E1S01", "E1S02", "E1S03", "E1S04", "E1S05", "E1S06", "E1S07", "E1S08"]


def _table(scene_id: str) -> str:
    """A table whose every row names its scene, so the fake image model can tell the scenes apart."""
    return "\n".join(
        f"| {index} | {size} | {angle} | {motion} | {desc}（卷宗{scene_id}） | | 环境声 | 5s | 线索 | {cast} | {scene_id} 办公室 |"
        for index, (size, angle, motion, desc, cast) in enumerate(ROWS, start=1)
    )


def _task(task_id: str) -> Dict[str, Any]:
    scenes = [
        {
            "scene_id": scene_id,
            "content": f"林夏在办公室与周教授对峙，桌上放着录音笔（{scene_id}）",
            "characters": ["林夏", "周教授"],
            "duration": "15s",
        }
        for scene_id in SCENE_IDS
    ]
    scenes.append({"scene_id": "E2S01", "content": "下一集：地下实验室", "characters": ["林夏"], "duration": "15s"})
    return {
        "task_id": task_id,
        "owner_user_id": "director-user",
        "current_stage": 3,
        "status": "idle",
        "config": {
            "stage_planner": "rules",
            "title_suggestion": "暗室回声", "llm_model": "m", "image_model": "img", "video_model": "v",
            "episode_count": 2, "episode_by_episode": False,
        },
        "assets": {
            "1": "角色1：林夏，调查记者。角色2：周教授，反派。",
            "2": "第1集 匿名录音\n场景1：办公室\n林夏：你隐瞒了什么？\n第2集 实验室\n场景1：地下实验室",
            "3": "角色设计完成",
            "3_sheets": {"林夏": "http://img.test/lin.png", "周教授": "http://img.test/zhou.png"},
            "3_characters": [{"name": "林夏", "desc": "青灰大衣"}, {"name": "周教授", "desc": "花白头发"}],
            "3_character_dashboard": {"state": "READY"},
            "2_breakdown": {"scenes": scenes},
        },
        "logs": {},
        "episodes": [],
        "total_episodes": 2,
    }


class _Providers:
    """Fake table writer and image model; the first scene is the slowest, so scenes finish out of order."""

    def __init__(self, delay: float = 0.02, *, fail_images=(), fail_tables=()):
        self.delay = delay
        self.fail_images = set(fail_images)
        self.fail_tables = set(fail_tables)
        self.lock = threading.Lock()
        self.table_calls: List[str] = []
        self.image_calls: List[str] = []
        self.tables_active = self.tables_peak = 0
        self.images_active = self.images_peak = 0

    def _pause(self, scene_id: str) -> None:
        rank = SCENE_IDS.index(scene_id) if scene_id in SCENE_IDS else 0
        time.sleep(self.delay * (len(SCENE_IDS) - rank))

    def llm(self, model, system, user, *args, **kwargs):
        scene_id = re.search(r"【场景编号】：(\S+)", user)[1]
        with self.lock:
            self.table_calls.append(scene_id)
            self.tables_active += 1
            self.tables_peak = max(self.tables_peak, self.tables_active)
        try:
            self._pause(scene_id)
            if scene_id in self.fail_tables:
                raise RuntimeError("synthetic table failure")
            return _table(scene_id)
        finally:
            with self.lock:
                self.tables_active -= 1

    def image(self, model, prompt, ref_images=None, **kwargs):
        scene_id = re.search(r"卷宗(E\dS\d\d)", prompt)[1]
        with self.lock:
            self.image_calls.append(scene_id)
            self.images_active += 1
            self.images_peak = max(self.images_peak, self.images_active)
        try:
            self._pause(scene_id)
            if scene_id in self.fail_images:
                raise RuntimeError("synthetic image failure")
            return f"http://img.test/{hashlib.sha256(prompt.encode()).hexdigest()[:12]}.png", "meta"
        finally:
            with self.lock:
                self.images_active -= 1


class ParallelStageFourTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, providers: _Providers, *, width: int, task_id: str = "parallel-1", expect=None) -> Dict[str, Any]:
        task = _task(task_id)
        self.repo.save_task(task_id, task)
        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": str(width)}), \
                patch.object(self.service.gateway, "call_llm", side_effect=providers.llm), \
                patch.object(self.service.gateway, "generate_image", side_effect=providers.image), \
                patch.object(self.service.gateway, "validate_image_request", create=True), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path), \
                patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            if expect is None:
                self.service._execute_stage_blocking(task_id, 4, _claimed_task=task)
            else:
                with self.assertRaisesRegex(*expect):
                    self.service._execute_stage_blocking(task_id, 4, _claimed_task=task)
        return self.repo.get_task(task_id)

    def test_scenes_overlap_and_only_the_current_episode_is_drawn(self):
        providers = _Providers()
        task = self._run(providers, width=6)

        self.assertGreater(providers.tables_peak, 1)
        self.assertLessEqual(providers.tables_peak, 6)
        self.assertGreater(providers.images_peak, 3)
        self.assertLessEqual(providers.images_peak, 6)
        self.assertNotIn("E2S01", providers.table_calls)
        boards = task["assets"]["4_scene_boards"]
        self.assertTrue(all(boards[scene_id]["status"] == "done" for scene_id in SCENE_IDS))
        self.assertEqual(boards["E2S01"]["status"], "pending")

    def test_drawing_side_by_side_ends_exactly_where_one_at_a_time_does(self):
        serial = self._run(_Providers(delay=0.005), width=1, task_id="parallel-serial")
        parallel = self._run(_Providers(delay=0.005), width=6, task_id="parallel-side")

        def shots(task):
            return [
                {key: shot.get(key) for key in (
                    "scene_id", "shot_id", "desc", "cut_in", "continuity_in", "continuity_out",
                    "spatial", "storyboard_prompt", "image_url", "contract_fingerprint",
                )}
                for shot in task["assets"]["4"]
            ]

        self.assertEqual(shots(parallel), shots(serial))
        self.assertEqual([shot["scene_id"] for shot in shots(parallel)], sorted(shot["scene_id"] for shot in shots(parallel)))
        # The second scene's first shot cut from the first scene's table, however late its images came.
        self.assertTrue(any(shot["scene_id"] == "E1S02" and shot["shot_id"] == 1 and shot["cut_in"] for shot in shots(parallel)))
        store_serial, store_parallel = serial["assets"][ASSET_KEY], parallel["assets"][ASSET_KEY]
        self.assertEqual(store_parallel["side_memory"], store_serial["side_memory"])
        self.assertEqual(store_parallel["locations"], store_serial["locations"])
        # The legacy single-board keys show the last scene in story order, not the last to finish.
        self.assertEqual(parallel["assets"]["4_raw"], serial["assets"]["4_raw"])
        self.assertIn("E1S08", parallel["assets"]["4_raw"])
        self.assertEqual(parallel["assets"]["4_grid"], serial["assets"]["4_grid"])

    def test_a_failed_scene_leaves_the_others_and_is_reported_on_its_board(self):
        task = self._run(_Providers(fail_images={"E1S03"}, fail_tables={"E1S01"}), width=6)

        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(boards["E1S01"]["status"], "failed")
        self.assertEqual(boards["E1S03"]["status"], "failed")
        self.assertEqual(boards["E1S03"]["shots_done"], 0)
        for scene_id in set(SCENE_IDS) - {"E1S01", "E1S03"}:
            self.assertEqual(boards[scene_id]["status"], "done", scene_id)
        self.assertFalse({shot["scene_id"] for shot in task["assets"]["4"]} & {"E1S01", "E1S03"})

    def test_every_scene_failing_still_fails_the_stage(self):
        self._run(
            _Providers(delay=0.001, fail_tables=set(SCENE_IDS)), width=6,
            expect=(RuntimeError, "全部生成失败"),
        )

    def test_progress_is_saved_as_each_scene_finishes_and_never_goes_backwards(self):
        saved: List[int] = []
        original = self.repo.save_task

        def recording_save(task_id, task):
            progress = (task.get("assets") or {}).get("4_scene_boards") or {}
            saved.append(sum(1 for entry in progress.values() if entry.get("status") == "done"))
            return original(task_id, task)

        with patch.object(self.repo, "save_task", side_effect=recording_save):
            self._run(_Providers(delay=0.005), width=6)
        self.assertEqual(saved, sorted(saved))
        self.assertTrue(set(range(1, len(SCENE_IDS) + 1)) <= set(saved))


class PanelBudgetTests(ParallelStageFourTests):
    def _board(self, duration: str, rows: int = len(ROWS), video_model: str = "v"):
        providers = _Providers(delay=0)
        prompts: List[str] = []

        def llm(model, system, user, *args, **kwargs):
            prompts.append(user)
            return "\n".join(_table("E1S01").splitlines()[:rows])

        task = _task("budget-1")
        task["config"]["video_model"] = video_model
        scene = {**task["assets"]["2_breakdown"]["scenes"][0], "duration": duration}
        with patch.object(self.service.gateway, "call_llm", side_effect=llm), \
                patch.object(self.service.gateway, "generate_image", side_effect=providers.image), \
                patch.object(self.service.gateway, "validate_image_request", create=True), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path):
            payload = self.service._generate_scene_board(
                task, task["config"], scene, sys_prompt="s", storyboard_negative="", title="暗室回声",
                genre="mystery", dir_style="noir", shot_style="cinematic", guidance="", char_info=("林夏", "", "周教授", ""),
            )
        return payload, providers, prompts

    def test_a_ten_second_scene_draws_at_most_two_panels_and_is_told_so(self):
        payload, providers, prompts = self._board("10s", rows=3)
        self.assertIn("最多2格", prompts[0])
        self.assertLessEqual(len(payload["shots"]), 2)
        self.assertEqual(len(providers.image_calls), len(payload["shots"]))
        # Nothing the table wrote is lost: every row's action is still in the panels.
        told = "\n".join(shot["desc"] for shot in payload["shots"])
        for _, _, _, action, _ in ROWS[:3]:
            self.assertIn(action, told)
        self.assertEqual(sorted(shot["shot_id"] for shot in payload["shots"]), list(range(1, len(payload["shots"]) + 1)))

    def test_a_thirty_second_seedance_scene_can_be_one_long_panel_on_the_board(self):
        payload, _, prompts = self._board("30s", rows=2, video_model="seedance2.5")
        self.assertIn("最多3格", prompts[0])
        self.assertIn("每格是一段10–30秒的连续视频", prompts[0])
        self.assertNotIn("每格是一段5", prompts[0])
        for panel in payload["storyboard"]["panels"]:
            self.assertLessEqual(panel["duration_seconds"], 30)

    def test_a_panel_written_at_thirty_seconds_stays_thirty_seconds(self):
        def long_table(model, system, user, *args, **kwargs):
            return "| 1 | 中景 | 平视 | 固定 | 林夏与周教授对峙（卷宗E1S01） | | 环境声 | 30s | 线索 | 林夏、周教授 | E1S01 办公室 |"

        providers = _Providers(delay=0)
        task = _task("budget-30")
        task["config"]["video_model"] = "seedance2.5"
        scene = {**task["assets"]["2_breakdown"]["scenes"][0], "duration": "30s"}
        with patch.object(self.service.gateway, "call_llm", side_effect=long_table), \
                patch.object(self.service.gateway, "generate_image", side_effect=providers.image), \
                patch.object(self.service.gateway, "validate_image_request", create=True), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path):
            payload = self.service._generate_scene_board(
                task, task["config"], scene, sys_prompt="s", storyboard_negative="", title="暗室回声",
                genre="mystery", dir_style="noir", shot_style="cinematic", guidance="", char_info=("林夏", "", "周教授", ""),
            )
        self.assertEqual(payload["shots"][0]["duration"], "30s")
        self.assertEqual(payload["storyboard"]["panels"][0]["duration_seconds"], 30)

    def test_a_long_scene_keeps_the_panels_its_table_needs(self):
        payload, _, prompts = self._board("60s")
        self.assertIn("最多9格", prompts[0])
        self.assertGreater(len(payload["shots"]), 2)


class SceneTurnTests(unittest.TestCase):
    def test_sections_run_in_story_order_whatever_order_the_scenes_arrive(self):
        turns = SceneTurns(["a", "b", "c"])
        entered: List[str] = []

        def scene(key):
            with turns.turn("stage", key):
                entered.append(key)

        threads = [threading.Thread(target=scene, args=(key,)) for key in ("c", "b", "a")]
        for thread in threads:
            thread.start()
            time.sleep(0.01)
        for thread in threads:
            thread.join(2)
        self.assertEqual(entered, ["a", "b", "c"])

    def test_a_scene_that_fails_before_its_turn_does_not_hold_up_the_rest(self):
        turns = SceneTurns(["a", "b"])
        entered: List[str] = []

        def later():
            with turns.turn("stage", "b"):
                entered.append("b")

        thread = threading.Thread(target=later)
        thread.start()
        time.sleep(0.01)
        self.assertEqual(entered, [])
        turns.finish("a")
        thread.join(2)
        self.assertEqual(entered, ["b"])

    def test_a_section_that_raises_still_passes_the_turn_on(self):
        turns = SceneTurns(["a", "b"])
        with self.assertRaises(ValueError):
            with turns.turn("stage", "a"):
                raise ValueError("planning failed")
        with turns.turn("stage", "b"):
            pass

    def test_a_later_scene_cuts_from_this_runs_table_not_the_stored_one(self):
        turns = SceneTurns(["a", "b"])
        turns.note_draft("a", [{"scene_id": "a", "shot_id": 1, "desc": "new"}])
        shots = turns.shots_with_drafts([
            {"scene_id": "a", "shot_id": 1, "desc": "old"}, {"scene_id": "z", "shot_id": 1, "desc": "kept"},
        ])
        self.assertEqual(sorted(shot["desc"] for shot in shots), ["kept", "new"])


class SchedulerTests(unittest.TestCase):
    def test_width_bounds_the_boards_in_flight_and_reports_each_one_once(self):
        lock = threading.Lock()
        active = {"now": 0, "peak": 0}
        finished: List[str] = []
        started: List[str] = []

        def draw(key, turns):
            with lock:
                active["now"] += 1
                active["peak"] = max(active["peak"], active["now"])
            time.sleep(0.01)
            with lock:
                active["now"] -= 1
            return key

        keys = [f"s{index}" for index in range(10)]
        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": "3"}):
            draw_scene_boards(
                draw, keys, on_started=started.extend,
                on_finished=lambda key, payload, error: finished.append(payload),
            )
        self.assertEqual(active["peak"], 3)
        self.assertEqual(started, keys)
        self.assertCountEqual(finished, keys)

    def test_one_at_a_time_is_available_as_a_rollback(self):
        order: List[str] = []
        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": "1"}):
            draw_scene_boards(
                lambda key, turns: order.append(key), ["a", "b", "c"],
                on_started=lambda keys: None, on_finished=lambda key, payload, error: None,
            )
        self.assertEqual(order, ["a", "b", "c"])

    def test_a_scene_error_is_handed_to_the_caller_without_stopping_the_rest(self):
        outcome: Dict[str, Any] = {}

        def draw(key, turns):
            if key == "a":
                raise ValueError("no table")
            return key

        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": "2"}):
            draw_scene_boards(
                draw, ["a", "b", "c"], on_started=lambda keys: None,
                on_finished=lambda key, payload, error: outcome.__setitem__(key, error or payload),
            )
        self.assertIsInstance(outcome["a"], ValueError)
        self.assertEqual((outcome["b"], outcome["c"]), ("b", "c"))

    def test_a_failed_save_stops_new_scenes_and_a_waiting_scene_pays_for_nothing(self):
        release_slow = threading.Event()
        started: List[str] = []
        paid: List[str] = []
        gave_up: List[str] = []

        def draw(key, turns):
            if key == "slow":
                release_slow.wait(5)
            try:
                with turns.turn("stage", key):
                    pass
            except SceneBoardsStopped:
                gave_up.append(key)
                raise
            paid.append(key)
            return key

        def on_finished(key, payload, error):
            threading.Timer(0.05, release_slow.set).start()
            raise OSError("task store is gone")

        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": "3"}):
            with self.assertRaisesRegex(OSError, "task store is gone"):
                draw_scene_boards(
                    draw, ["quick", "slow", "waiting", "never"],
                    on_started=started.extend, on_finished=on_finished,
                )
        self.assertNotIn("never", started)
        self.assertIn("waiting", gave_up)
        self.assertNotIn("waiting", paid)


class ImageRateLimitTests(unittest.TestCase):
    def _gateway(self):
        gateway = ModelGateway.__new__(ModelGateway)
        gateway.tls_verify = True
        return gateway

    def _reply(self, status, body=None, headers=None):
        class Reply:
            status_code = status
            text = "rate limited" if status == 429 else ""

            def json(self):
                return body or {}

        reply = Reply()
        reply.headers = headers or {}
        return reply

    def test_a_rate_limited_image_is_asked_again_after_the_wait(self):
        gateway = self._gateway()
        replies = [
            self._reply(429, headers={"Retry-After": "7"}),
            self._reply(200, {"data": [{"url": "http://img.test/a.png"}]}),
        ]
        with patch("requests.post", side_effect=replies) as post, patch("time.sleep") as sleep, \
                patch.object(gateway, "_is_host_broken", return_value=False), \
                patch.object(gateway, "_note_host_ok"), patch.object(gateway, "_proxies_for", return_value=None):
            url = gateway._http_image("k", "http://img.test/v1", "seedream", "a prompt")
        self.assertEqual(url, "http://img.test/a.png")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(7.0)

    def test_it_gives_up_once_the_retries_are_spent(self):
        gateway = self._gateway()
        with patch("requests.post", return_value=self._reply(429)) as post, patch("time.sleep"), \
                patch.object(gateway, "_is_host_broken", return_value=False), \
                patch.object(gateway, "_proxies_for", return_value=None):
            self.assertIsNone(gateway._http_image("k", "http://img.test/v1", "seedream", "a prompt"))
        self.assertEqual(post.call_count, 4)


if __name__ == "__main__":
    unittest.main()


class RerunReuseTests(ParallelStageFourTests):
    """生图失败的场次重跑时，已经写过、审过的分镜表直接复用；新场和「重画」仍然重写。"""

    def _stage4(self, task, providers):
        with patch.dict("os.environ", {"STORYBOARD_SCENE_CONCURRENCY": "2"}), \
                patch.object(self.service.gateway, "call_llm", side_effect=providers.llm), \
                patch.object(self.service.gateway, "generate_image", side_effect=providers.image), \
                patch.object(self.service.gateway, "validate_image_request", create=True), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path), \
                patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_a_scene_whose_images_failed_is_redrawn_without_rewriting_its_table(self):
        task = _task("rerun-1")
        self.repo.save_task("rerun-1", task)
        first = _Providers(delay=0, fail_images={"E1S03"})
        stored = self._stage4(task, first)
        self.assertEqual(stored["assets"]["4_scene_boards"]["E1S03"]["status"], "failed")
        self.assertIn("E1S03", first.table_calls)

        second = _Providers(delay=0)
        stored = self._stage4(stored, second)
        self.assertEqual(stored["assets"]["4_scene_boards"]["E1S03"]["status"], "done")
        self.assertNotIn("E1S03", second.table_calls, "the accepted table is reused")
        self.assertIn("E1S03", second.image_calls, "the images are made again")
        self.assertTrue(stored["assets"]["4_scene_boards"]["E1S03"]["timings"].get("table_reused"))
        # The stage runner binds the project for the usage ledger; here the stage is called directly, so the
        # record of the question not asked lands in the ledger's unattributed queue.
        self.assertTrue(any(
            (record.get("units") or {}).get("reused") and (record.get("units") or {}).get("label") == "storyboard_table"
            for record in usage_ledger.unattributed
        ), "the reuse is recorded as a call that cost nothing")

    def test_a_redraw_asks_for_a_new_table(self):
        task = _task("rerun-2")
        self.repo.save_task("rerun-2", task)
        stored = self._stage4(task, _Providers(delay=0))
        stored["assets"]["4_scene_boards"]["E1S03"]["status"] = "pending"
        self.repo.save_task("rerun-2", stored)
        again = _Providers(delay=0)
        stored = self._stage4(stored, again)
        self.assertEqual(set(again.table_calls), {"E1S03"}, "only the redrawn scene is written, and it is written afresh")
        self.assertEqual(stored["assets"]["4_scene_boards"]["E1S03"]["status"], "done")
        self.assertFalse(stored["assets"]["4_scene_boards"]["E1S03"]["timings"].get("table_reused"))
