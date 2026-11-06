# -*- coding: utf-8 -*-
"""逐集制作：一集做完「分镜 → 视觉 → 音频 → 合成」才开始下一集，全部集成片后才宣发。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import episode_cycle as cycle
from app.core.production_asset_readiness import evaluate_asset_readiness
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService, StagePrerequisiteError
from tests.test_storyboard_scene_contract import _stub_scene_board, _task


def _cycle_task(scenes):
    task = _task(scenes)
    task["config"].pop("episode_by_episode", None)
    return task


def _boards(*episodes_done):
    """两集各一场的分镜进度；episodes_done 里的集已完成。"""
    return {
        "4_progress": {"current_episode": 1, "episodes": [
            {"number": n, "total": 1, "done": int(n in episodes_done), "complete": n in episodes_done} for n in (1, 2)
        ]},
        "4": [{"scene_id": f"E{n}S01", "shot_id": k} for n in episodes_done for k in (1, 2)],
        "4_storyboard": {"panels": []}, "4_grid": "grid.png", "4_quality": {"passed": True},
    }


class HelperTests(unittest.TestCase):
    def test_shot_keys_are_unique_across_scenes_and_episodes(self):
        self.assertEqual(cycle.shot_uid({"scene_id": "E2S11", "shot_id": 3}), 201103)
        self.assertNotEqual(cycle.shot_uid({"scene_id": "E1S01", "shot_id": 1}), cycle.shot_uid({"scene_id": "E1S02", "shot_id": 1}))
        self.assertEqual(cycle.shot_uid({"shot_id": 4}), 4)   # 旧数据没有场号时退回镜号

    def test_the_current_episode_is_the_first_one_without_a_film(self):
        task = {"config": {}, "assets": {**_boards(1, 2)}}
        self.assertTrue(cycle.active(task))
        self.assertEqual(cycle.current_episode(task), 1)
        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        self.assertEqual(cycle.current_episode(task), 2)
        cycle.writable_record(task, 2)["film"] = {"final_video_url": "e2.mp4"}
        self.assertIsNone(cycle.current_episode(task))
        self.assertEqual([film["episode"] for film in cycle.films(task)], [1, 2])

    def test_only_multi_episode_projects_without_legacy_output_switch(self):
        single = {"config": {}, "assets": {"4_progress": {"episodes": [{"number": 1, "complete": True}]}}}
        self.assertFalse(cycle.active(single))
        legacy = {"config": {}, "assets": {**_boards(1, 2), "7": {"final_video_url": "whole.mp4"}}}
        self.assertFalse(cycle.active(legacy))
        off = {"config": {"episode_by_episode": False}, "assets": _boards(1, 2)}
        self.assertFalse(cycle.active(off))

    def test_a_rerun_only_clears_the_current_episode(self):
        task = {"config": {}, "assets": {**_boards(1, 2), "5": [
            {"scene_id": "E1S01", "shot_id": 1, "video_url": "a"}, {"scene_id": "E2S01", "shot_id": 1, "video_url": "b"}]}}
        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        cycle.writable_record(task, 2).update(audio={"audio_url": "v"})
        cycle.discard_for_rerun(task, 4)          # 当前集是第 2 集
        self.assertEqual([clip["scene_id"] for clip in task["assets"]["5"]], ["E1S01"])
        self.assertNotIn("audio", cycle.record(task, 2))
        self.assertEqual(cycle.film_of(task, 1), "e1.mp4")

    def test_an_episode_view_sees_only_that_episode(self):
        task = {"config": {}, "assets": {**_boards(1, 2), "5": [
            {"scene_id": "E1S01", "shot_id": 2, "video_url": "a2"}, {"scene_id": "E1S01", "shot_id": 1, "video_url": "a1"},
            {"scene_id": "E2S01", "shot_id": 1, "video_url": "b"}]}}
        view = cycle.episode_view(task, 1)
        self.assertEqual([clip["video_url"] for clip in view["assets"]["5"]], ["a1", "a2"])
        self.assertEqual({shot["scene_id"] for shot in view["assets"]["4"]}, {"E1S01"})
        self.assertFalse(cycle.active(view))     # 视图里不再二次分集


class _ServiceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo = self.repo
        # 这里验证的是逐集推进，不是五类资产库门槛（它有自己的测试）。
        readiness = patch("app.service.drama_service.evaluate_project_assets",
                          side_effect=lambda task: evaluate_asset_readiness(task, None))
        readiness.start()
        self.addCleanup(readiness.stop)


class WorkflowTests(_ServiceCase):

    def _snapshot(self, task):
        return self.service.workflow_snapshot(task)

    def test_episode_one_goes_to_video_before_episode_two_is_storyboarded(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "第一集"}, {"scene_id": "E2S01", "content": "第二集"}])
        task["assets"].update(_boards(1))
        snap = self._snapshot(task)
        self.assertEqual(snap["next_stage"], 5)
        self.assertIn("正在做第 1 集", snap["hint"])

        task["assets"][cycle.CYCLE_KEY] = {"version": 1, "episodes": {}}   # 第 5 阶段开工即登记逐集制作
        task["assets"]["5"] = [{"scene_id": "E1S01", "shot_id": k, "video_url": f"c{k}"} for k in (1, 2)]
        self.assertEqual(self._snapshot(task)["next_stage"], 6)
        cycle.writable_record(task, 1)["audio"] = {"audio_url": "v1"}
        self.assertEqual(self._snapshot(task)["next_stage"], 7)
        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        snap = self._snapshot(task)
        self.assertEqual(snap["next_stage"], 4)            # 第 1 集成片后才回到第 2 集分镜
        self.assertIn("正在做第 2 集", snap["hint"])
        self.assertIn("已完成成片 1 集", snap["hint"])

    def test_publicity_waits_for_every_episode(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}])
        task["assets"].update(_boards(1, 2))
        task["assets"]["5"] = [{"scene_id": f"E{n}S01", "shot_id": k, "video_url": "c"} for n in (1, 2) for k in (1, 2)]
        for n in (1, 2):
            cycle.writable_record(task, n).update(audio={"audio_url": "v"}, film={"final_video_url": f"e{n}.mp4"})
        self.assertEqual(self._snapshot(task)["next_stage"], 8)
        del task["assets"][cycle.CYCLE_KEY]["episodes"]["2"]["film"]
        self.assertEqual(self._snapshot(task)["next_stage"], 7)

    def test_starting_the_next_episode_never_wipes_the_finished_one(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}])
        task["assets"].update(_boards(1))
        task["assets"]["5"] = [{"scene_id": "E1S01", "shot_id": k, "video_url": f"c{k}"} for k in (1, 2)]
        cycle.writable_record(task, 1).update(audio={"audio_url": "v1"}, film={"final_video_url": "e1.mp4"})
        task["assets"]["6"] = {"audio_url": "v1"}
        task["assets"]["7"] = {"final_video_url": "e1.mp4"}
        task["video_url"] = "e1.mp4"
        self.repo.save_task(task["task_id"], task)

        claimed = self.service._claim_stage_task(task["task_id"], 4)

        self.assertEqual(len(claimed["assets"]["5"]), 2)
        self.assertEqual(cycle.film_of(claimed, 1), "e1.mp4")
        self.assertEqual(cycle.record(claimed, 1)["audio"], {"audio_url": "v1"})
        self.assertEqual(claimed["video_url"], "e1.mp4")

    def test_video_is_refused_until_the_current_episode_is_storyboarded(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}])
        task["assets"].update(_boards())
        self.repo.save_task(task["task_id"], task)
        with self.assertRaisesRegex(StagePrerequisiteError, "第1集分镜尚未完成"):
            self.service._claim_stage_task(task["task_id"], 5)


class StageFourGuardTests(_ServiceCase):

    def _run_stage4(self, task):
        self.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", _stub_scene_board), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_a_rerun_does_not_storyboard_ahead_of_the_episode_in_production(self):
        task = self._run_stage4(_cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}]))
        self.assertEqual(DramaService._missing_stage_outputs(task, 4), [])   # 第1集分镜够了就放行
        task = self._run_stage4(task)                                        # 再跑一次第 4 阶段
        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(boards["E2S01"]["status"], "pending")               # 第1集还没成片，第2集不提前做

        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        task = self._run_stage4(task)
        self.assertEqual(task["assets"]["4_scene_boards"]["E2S01"]["status"], "done")


class OneClickTests(_ServiceCase):

    def test_one_click_makes_each_episode_a_film_before_the_next(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "第一集"}, {"scene_id": "E2S01", "content": "第二集"}])
        self.repo.save_task(task["task_id"], task)
        calls, repo = [], self.repo

        async def fake_execute_stage(service_self, task_id, stage, **kwargs):
            current = repo.get_task(task_id)
            episode = cycle.current_episode(current) if cycle.active(current) else 1
            calls.append((stage, episode))
            assets = current["assets"]
            if stage == 4:
                progress = assets.setdefault("4_progress", {"current_episode": 1, "episodes": [
                    {"number": n, "total": 1, "done": 0, "complete": False} for n in (1, 2)]})
                target = next(item for item in progress["episodes"] if not item["complete"])
                target.update(done=1, complete=True)
                assets.setdefault("4", []).extend({"scene_id": f"E{target['number']}S01", "shot_id": k} for k in (1, 2))
                assets.update({"4_storyboard": {"panels": []}, "4_grid": "grid.png", "4_quality": {"passed": True}})
            elif stage == 5:
                assets.setdefault(cycle.CYCLE_KEY, {"version": 1, "episodes": {}})
                assets["5"] = cycle.merged_clips(cycle.other_clips(current, episode), [
                    {"scene_id": f"E{episode}S01", "shot_id": k, "video_url": f"e{episode}c{k}.mp4"} for k in (1, 2)])
            elif stage == 6:
                assets["6"] = {"audio_url": f"e{episode}.mp3"}
                cycle.writable_record(current, episode)["audio"] = dict(assets["6"])
            elif stage == 7:
                assets["7"] = {"final_video_url": f"e{episode}.mp4"}
                cycle.writable_record(current, episode)["film"] = {"final_video_url": f"e{episode}.mp4"}
            elif stage == 8:
                assets["8"] = {"pr_content": "文案", "short_link": "link"}
            current["stage_progress"]["status"] = "success"
            repo.save_task(task_id, current)
            return current

        async def instant(*_a, **_k):
            return None

        with patch.object(DramaService, "execute_stage", fake_execute_stage), \
             patch("app.service.drama_service.asyncio.sleep", new=instant):
            asyncio.run(self.service.execute_all_stages(task["task_id"]))

        self.assertEqual(calls, [(4, 1), (5, 1), (6, 1), (7, 1), (4, 2), (5, 2), (6, 2), (7, 2), (8, None)])
        final = repo.get_task(task["task_id"])
        self.assertEqual([film["final_video_url"] for film in cycle.films(final)], ["e1.mp4", "e2.mp4"])
        self.assertEqual(len(final["assets"]["5"]), 4)


if __name__ == "__main__":
    unittest.main()
