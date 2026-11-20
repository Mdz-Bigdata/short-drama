# -*- coding: utf-8 -*-
"""分集制作：产物按集归档，步骤按整部剧往下走——所有集的分镜、所有集的视频、所有集的音频、所有集的成片，然后宣发；不回到前面的步骤。"""

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

    def test_each_stage_works_on_the_first_open_episode_that_lacks_it(self):
        task = {"config": {}, "assets": {**_boards(1), "5": [{"scene_id": "E1S01", "shot_id": k, "video_url": "c"} for k in (1, 2)]}}
        self.assertEqual(cycle.episode_for(task, 4), 2)        # 第 1 集分镜有了，分镜这一步做第 2 集
        self.assertEqual(cycle.episode_for(task, 5), 2)        # 第 1 集视频有了；第 2 集还没镜头，也算缺
        self.assertEqual(cycle.episode_for(task, 6), 1)
        self.assertEqual(cycle.signature(task), ((1, (True, True, False, False)), (2, (False, False, False, False))))
        cycle.writable_record(task, 1)["audio"] = {"audio_url": "v1"}
        self.assertEqual(cycle.episode_for(task, 6), 2)
        self.assertEqual(cycle.episode_for(task, 7), 1)
        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        self.assertEqual(cycle.open_episodes(task), [2])       # 出了成片的集不再被任何一步打开
        self.assertEqual([cycle.episode_for(task, stage) for stage in (4, 5, 6, 7)], [2, 2, 2, 2])

    def test_a_stage_is_missing_until_every_open_episode_has_it(self):
        task = {"config": {}, "assets": {**_boards(1)}}
        self.assertEqual(cycle.missing(task, 4), ["第2集分镜尚未完成"])
        self.assertEqual(cycle.missing(task, 5), ["第1,2集视觉(运镜视频)尚未完成"])
        task["assets"].update(_boards(1, 2))
        self.assertEqual(cycle.missing(task, 4), [])
        self.assertEqual(cycle.missing(task, 6), ["第1,2集音频尚未完成"])
        self.assertEqual(cycle.missing(task, 8), ["第1集尚未做完成片(全部集完成后才宣发)"])
        self.assertIsNone(cycle.missing(task, 3))              # 前三步不分集

    def test_a_stage_asked_again_takes_the_first_open_episode(self):
        task = {"config": {}, "assets": {**_boards(1, 2)}}
        self.assertEqual(cycle.episode_for(task, 4), 1)        # 各集分镜都有了：重做就从第一个没出成片的集起
        cycle.writable_record(task, 1)["film"] = {"final_video_url": "e1.mp4"}
        self.assertEqual(cycle.episode_for(task, 4), 2)
        cycle.writable_record(task, 2)["film"] = {"final_video_url": "e2.mp4"}
        self.assertIsNone(cycle.episode_for(task, 4))

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

    def test_every_episode_finishes_a_step_before_the_next_step(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "第一集"}, {"scene_id": "E2S01", "content": "第二集"}])
        task["assets"].update(_boards(1))
        snap = self._snapshot(task)
        self.assertEqual(snap["next_stage"], 4)            # 第 2 集的分镜没做完，不进视频
        self.assertIn("共 2 集，已出成片 0 集", snap["hint"])
        self.assertIn("不会回到前面的步骤", snap["hint"])

        seen = []
        def step(change):
            change()
            seen.append(self._snapshot(task)["next_stage"])
        clip = lambda n: [{"scene_id": f"E{n}S01", "shot_id": k, "video_url": f"e{n}c{k}"} for k in (1, 2)]
        step(lambda: task["assets"].update(_boards(1, 2)))
        step(lambda: task["assets"].update({cycle.CYCLE_KEY: {"version": 1, "episodes": {}}, "5": clip(1)}))
        step(lambda: task["assets"].update({"5": clip(1) + clip(2)}))
        step(lambda: cycle.writable_record(task, 1).update(audio={"audio_url": "v1"}))
        step(lambda: cycle.writable_record(task, 2).update(audio={"audio_url": "v2"}))
        step(lambda: cycle.writable_record(task, 1).update(film={"final_video_url": "e1.mp4"}))
        step(lambda: cycle.writable_record(task, 2).update(film={"final_video_url": "e2.mp4"}))
        self.assertEqual(seen, [5, 5, 6, 6, 7, 7, 8])
        self.assertEqual(seen, sorted(seen))               # 一路只往后走

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

    def test_video_is_refused_until_every_episode_is_storyboarded(self):
        task = _cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}])
        task["assets"].update(_boards(1))                  # 第 1 集分镜做完也不行：不跳着走
        self.repo.save_task(task["task_id"], task)
        with self.assertRaisesRegex(StagePrerequisiteError, "第2集分镜尚未完成"):
            self.service._claim_stage_task(task["task_id"], 5)


class StageFourGuardTests(_ServiceCase):

    def _run_stage4(self, task):
        self.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", _stub_scene_board), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_storyboards_go_on_to_the_next_episode_without_waiting_for_a_film(self):
        task = self._run_stage4(_cycle_task([{"scene_id": "E1S01", "content": "一"}, {"scene_id": "E2S01", "content": "二"}]))
        self.assertEqual(task["assets"]["4_scene_boards"]["E2S01"]["status"], "pending")   # 一轮只做一集
        self.assertIn("第2集分镜尚未完成", DramaService._missing_stage_outputs(task, 4))     # 分镜这一步还没完
        task = self._run_stage4(task)                                        # 接着做第 2 集，不等第 1 集出成片
        self.assertEqual(task["assets"]["4_scene_boards"]["E2S01"]["status"], "done")
        self.assertEqual(DramaService._missing_stage_outputs(task, 4), [])


class OneClickTests(_ServiceCase):

    def _run(self, task, spoil=None):
        """假阶段各做成一集；``spoil(stage, assets)`` 可以在某一步弄坏点东西。记下每次调用的(阶段, 集)。"""
        self.repo.save_task(task["task_id"], task)
        calls, repo = [], self.repo

        async def fake_execute_stage(service_self, task_id, stage, **kwargs):
            current = repo.get_task(task_id)
            episode = cycle.episode_for(current, stage) if cycle.active(current) else 1
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
            if spoil:
                spoil(stage, assets, episode)
            current["stage_progress"]["status"] = "success"
            repo.save_task(task_id, current)
            return current

        async def instant(*_a, **_k):
            return None

        with patch.object(DramaService, "execute_stage", fake_execute_stage), \
             patch("app.service.drama_service.asyncio.sleep", new=instant):
            asyncio.run(self.service.execute_all_stages(task["task_id"]))
        return calls, repo.get_task(task["task_id"])

    def _two_episodes(self):
        return _cycle_task([{"scene_id": "E1S01", "content": "第一集"}, {"scene_id": "E2S01", "content": "第二集"}])

    def test_one_click_finishes_each_step_for_every_episode_then_moves_on(self):
        calls, final = self._run(self._two_episodes())
        self.assertEqual(calls, [(4, 1), (4, 2), (5, 1), (5, 2), (6, 1), (6, 2), (7, 1), (7, 2), (8, None)])
        stages = [stage for stage, _ in calls]
        self.assertEqual(stages, sorted(stages))           # 从分镜起只往后走，不回退、不跳步
        self.assertEqual([film["final_video_url"] for film in cycle.films(final)], ["e1.mp4", "e2.mp4"])
        self.assertEqual(len(final["assets"]["5"]), 4)

    def test_the_run_stops_instead_of_going_back_to_an_earlier_step(self):
        def spoil(stage, assets, episode):
            if stage == 6 and episode == 1:
                assets["4_quality"] = {"passed": False}   # 做到音频时，分镜质检被推翻了
        calls, final = self._run(self._two_episodes(), spoil)
        self.assertEqual(calls, [(4, 1), (4, 2), (5, 1), (5, 2), (6, 1)])   # 没有自动跳回第 4 步
        self.assertEqual(final["status"], "failed")
        self.assertIn("不会跳回前面的步骤", final["fail_reason"])
        self.assertIn("第 4/7 步", final["fail_reason"])

    def test_the_run_stops_when_a_step_makes_no_episode(self):
        def spoil(stage, assets, episode):
            if stage == 5 and episode == 2:
                assets["5"] = [clip for clip in assets["5"] if clip["scene_id"] != "E2S01"]   # 第 2 集一条也没拍出来
        calls, final = self._run(self._two_episodes(), spoil)
        self.assertEqual(calls, [(4, 1), (4, 2), (5, 1), (5, 2)])            # 不原地打转
        self.assertEqual(final["status"], "failed")
        self.assertIn("产物仍不完整", final["fail_reason"])


if __name__ == "__main__":
    unittest.main()
