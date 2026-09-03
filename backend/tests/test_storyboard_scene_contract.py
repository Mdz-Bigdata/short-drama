"""逐场分镜引擎的资产契约测试 (与前端 StoryboardWorkspace 的冻结契约逐字段对齐)。

契约键：
- assets["4"]           扁平 shots，每个 shot 带 "scene_id"
- assets["4_scene_boards"] {scene_id: {status, shots_total, shots_done, episode}} 全量覆盖剧本明细
- assets["4_progress"]  {current_episode, episodes: [{number, total, done, complete}]} (episodes 是数组)

生图与 LLM 均以 _generate_scene_board 桩替代 (沿用 test_writer_dashboard 的 TaskRepository 桩先例)。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService, StagePrerequisiteError


def _stub_scene_board(self, task, config, scene, **kwargs):
    scene_id = str(scene.get("scene_id") or "E1S01")
    if scene_id == "FAIL_ME":
        raise RuntimeError("stubbed board failure")
    shots = [
        {"shot_id": index, "scene_id": scene_id, "image_url": f"http://img.test/{scene_id}/{index}.png",
         "size": "MS", "motion": "Fixed", "desc": f"分镜 {index}"}
        for index in range(1, 10)
    ]
    return {
        "scene_id": scene_id,
        "shots": shots,
        "raw": "raw markdown",
        "grid_url": f"http://grid.test/{scene_id}.png",
        "grid_prompt": "grid prompt",
        "storyboard": {"panels": []},
        "prompt_detail": {"episode": scene_id},
        "quality": {"passed": True},
    }


def _task(scenes):
    assets = {
        "1": "角色1：林夏，调查记者。角色2：周教授，反派。",
        "2": "第1集 匿名录音\n场景1：雨夜办公室\n林夏：你隐瞒了什么？",
        "3": "角色设计完成",
        "3_sheets": {},
        "3_characters": [],
        "3_character_dashboard": {"state": "READY"},
    }
    if scenes is not None:
        assets["2_breakdown"] = {"scenes": scenes}
    return {
        "task_id": "storyboard-contract-1",
        "owner_user_id": "u1",
        "status": "idle",
        "current_stage": 3,
        "config": {
            "title_suggestion": "十二小时",
            "episode_count": 2,
            "llm_model": "m",
            "image_model": "img",
            "video_model": "v",
        },
        "assets": assets,
        "logs": {},
        "episodes": [],
        "total_episodes": 2,
    }


class StoryboardSceneContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo

    def tearDown(self):
        self.temp.cleanup()

    def _run_stage4(self, task):
        self.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", _stub_scene_board), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_first_run_generates_only_episode_one_and_writes_the_full_scene_board_map(self):
        task = self._run_stage4(_task([
            {"scene_id": "E1S01", "content": "收到匿名录音", "characters": ["林夏"], "duration": "60s"},
            {"scene_id": "E1S02", "content": "追查线索", "characters": ["林夏"], "duration": "45s"},
            {"scene_id": "E2S01", "content": "实验室对峙", "characters": ["林夏", "周教授"]},
        ]))

        boards = task["assets"]["4_scene_boards"]
        # 全量覆盖剧本明细：未开始的下一集场景也在场景板里 (status=pending)。
        self.assertEqual(set(boards), {"E1S01", "E1S02", "E2S01"})
        for scene_id in ("E1S01", "E1S02"):
            self.assertEqual(boards[scene_id]["status"], "done")
            self.assertEqual(boards[scene_id]["shots_total"], 9)
            self.assertEqual(boards[scene_id]["shots_done"], 9)
            self.assertEqual(boards[scene_id]["episode"], 1)
        self.assertEqual(boards["E2S01"], {
            "status": "pending", "shots_total": 9, "shots_done": 0, "episode": 2,
        })

        # 4_progress：episodes 是数组；complete 键名与集序数字均为契约字段。
        progress = task["assets"]["4_progress"]
        self.assertEqual(progress["current_episode"], 2)
        self.assertEqual(progress["episodes"], [
            {"number": 1, "total": 2, "done": 2, "complete": True},
            {"number": 2, "total": 1, "done": 0, "complete": False},
        ])

        # 扁平 shots：只含已完成场景，且每个 shot 打了 scene_id。
        shots = task["assets"]["4"]
        self.assertEqual(len(shots), 18)
        self.assertEqual({shot["scene_id"] for shot in shots}, {"E1S01", "E1S02"})

        # 上一集未完成时阶段4不算整体完成，阶段5被卡住。
        missing = DramaService._missing_stage_outputs(task, 4)
        self.assertIn("4_progress.episodes[2].complete=true", missing)

    def test_rerun_resumes_the_next_episode_and_keeps_finished_boards(self):
        task = self._run_stage4(_task([
            {"scene_id": "E1S01", "content": "收到匿名录音"},
            {"scene_id": "E2S01", "content": "实验室对峙"},
        ]))
        task = self._run_stage4(task)

        boards = task["assets"]["4_scene_boards"]
        self.assertEqual({scene_id: entry["status"] for scene_id, entry in boards.items()},
                         {"E1S01": "done", "E2S01": "done"})
        progress = task["assets"]["4_progress"]
        self.assertTrue(all(item["complete"] for item in progress["episodes"]))
        self.assertEqual(len(task["assets"]["4"]), 18)
        self.assertEqual(DramaService._missing_stage_outputs(task, 4), [])

    def test_failed_scene_keeps_the_episode_incomplete_and_is_redone_on_rerun(self):
        scenes = [
            {"scene_id": "E1S01", "content": "顺利场景"},
            {"scene_id": "FAIL_ME", "content": "必挂场景"},
        ]
        task = self._run_stage4(_task(scenes))

        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(boards["E1S01"]["status"], "done")
        self.assertEqual(boards["FAIL_ME"]["status"], "failed")
        self.assertIn("error", boards["FAIL_ME"])
        progress = task["assets"]["4_progress"]
        self.assertEqual(progress["episodes"][0], {"number": 1, "total": 2, "done": 1, "complete": False})

        # 续跑：把必挂场景改为可成功，done 场景不重做，failed 场景重做。
        task["assets"]["2_breakdown"]["scenes"][1]["scene_id"] = "E1S02"
        task = self._run_stage4(task)
        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(set(boards), {"E1S01", "E1S02"})
        self.assertTrue(all(entry["status"] == "done" for entry in boards.values()))
        self.assertTrue(task["assets"]["4_progress"]["episodes"][0]["complete"])

    def test_missing_breakdown_falls_back_to_a_single_board_and_labels_the_progress(self):
        task = self._run_stage4(_task(None))

        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(set(boards), {"E1S01"})
        self.assertEqual(boards["E1S01"]["status"], "done")
        progress = task["assets"]["4_progress"]
        self.assertEqual(progress["fallback"], "no_breakdown_single_board")
        self.assertEqual(progress["episodes"], [{"number": 1, "total": 1, "done": 1, "complete": True}])
        self.assertEqual(DramaService._missing_stage_outputs(task, 4), [])

    def test_stage5_claim_is_rejected_server_side_until_every_episode_completes(self):
        """R3(b)：绕过 UI 直接推进阶段5时，后端 _claim_stage_task 必须拦截。

        /api/drama/{id}/next 与 assistant 的 _launch 都经由 _claim_stage_task /
        _assert_stage_prerequisites，这里直接对该闸门断言。
        """
        task = self._run_stage4(_task([
            {"scene_id": "E1S01", "content": "收到匿名录音"},
            {"scene_id": "E2S01", "content": "实验室对峙"},
        ]))
        # 第2集未完成：推进阶段5被 409 语义的 StagePrerequisiteError 拦下。
        with self.assertRaisesRegex(StagePrerequisiteError, r"4_progress\.episodes\[2\]\.complete=true"):
            self.service._claim_stage_task(task["task_id"], 5)
        # 拦截必须不落库：任务不能被标成 running/stage5。
        untouched = self.repo.get_task(task["task_id"])
        self.assertNotEqual(untouched.get("current_stage"), 5)

        # 续跑补完第2集后放行。
        task = self._run_stage4(task)
        claimed = self.service._claim_stage_task(task["task_id"], 5)
        self.assertEqual(claimed["current_stage"], 5)

    def test_next_episode_scene_never_enters_generation_while_earlier_scene_unfinished(self):
        """R2：第N集存在非 done 场景时，第N+1集任何场景都不进入生成调用；done 跳过、failed 重做。"""
        calls = []

        def recording_stub(service_self, task, config, scene, **kwargs):
            calls.append(str(scene.get("scene_id")))
            return _stub_scene_board(service_self, task, config, scene, **kwargs)

        task = _task([
            {"scene_id": "E1S01", "content": "顺利场景"},
            {"scene_id": "FAIL_ME", "content": "必挂场景"},
            {"scene_id": "E2S01", "content": "下一集场景"},
        ])
        self.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", recording_stub), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
            rerun = self.repo.get_task(task["task_id"])
            with self.assertRaisesRegex(RuntimeError, "全部生成失败"):
                self.service._execute_stage_blocking(rerun["task_id"], 4, _claimed_task=rerun)

        # 两轮生成调用序列：E2S01 从未被调用；E1S01 done 后续跑不重做；FAIL_ME 续跑重做。
        self.assertEqual(calls, ["E1S01", "FAIL_ME", "FAIL_ME"])
        boards = self.repo.get_task(task["task_id"])["assets"]["4_scene_boards"]
        self.assertEqual(boards["E2S01"]["status"], "pending")
        self.assertEqual(boards["FAIL_ME"]["status"], "failed")
        self.assertEqual(boards["FAIL_ME"]["shots_done"], 0)

    def test_done_board_with_incomplete_grid_is_downgraded_and_redone(self):
        """R2 证伪：状态谎报 done 但九格图不齐时，续跑必须降级重做，不得沿用虚报计数。"""
        task = self._run_stage4(_task([{"scene_id": "E1S01", "content": "顺利场景"}]))
        # 手工污染：抠掉一张图，状态仍留 done / shots_done=9。
        task["assets"]["4"][3]["image_url"] = None
        self.repo.save_task(task["task_id"], task)

        calls = []

        def recording_stub(service_self, t, config, scene, **kwargs):
            calls.append(str(scene.get("scene_id")))
            return _stub_scene_board(service_self, t, config, scene, **kwargs)

        rerun = self.repo.get_task(task["task_id"])
        with patch.object(DramaService, "_generate_scene_board", recording_stub), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(rerun["task_id"], 4, _claimed_task=rerun)

        self.assertEqual(calls, ["E1S01"])  # 图不齐的 done 被降级为 pending 并重新生成
        boards = self.repo.get_task(task["task_id"])["assets"]["4_scene_boards"]
        self.assertEqual(boards["E1S01"]["status"], "done")
        self.assertEqual(boards["E1S01"]["shots_done"], 9)

    def test_scene_board_entry_carries_filler_shot_count(self):
        """R2 证伪配套：audit 后不足9镜被 fallback 补齐时，占位数量必须透出，不许无痕冒充。"""

        def filler_stub(service_self, t, config, scene, **kwargs):
            payload = _stub_scene_board(service_self, t, config, scene, **kwargs)
            payload["filler_shots"] = 2
            return payload

        task = _task([{"scene_id": "E1S01", "content": "顺利场景"}])
        self.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", filler_stub), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)

        boards = self.repo.get_task(task["task_id"])["assets"]["4_scene_boards"]
        self.assertEqual(boards["E1S01"]["status"], "done")
        self.assertEqual(boards["E1S01"]["filler_shots"], 2)

    def test_malformed_scene_ids_do_not_crash_and_default_to_episode_one(self):
        # 跳号/同集重复/E后无数字/无E前缀：重复 id 保留第一条，无法解析的编号一律归入第1集。
        # 前端 sceneEpisodeNumber 使用同一 /E(\d{1,3})/i 推导，两端行为一致。
        task = self._run_stage4(_task([
            {"scene_id": "E1S01", "content": "a"},
            {"scene_id": "E1S03", "content": "跳号"},
            {"scene_id": "E1S01", "content": "重复"},
            {"scene_id": "ESpecial", "content": "E后无数字"},
            {"scene_id": "S07", "content": "无E前缀"},
        ]))

        boards = task["assets"]["4_scene_boards"]
        self.assertEqual(set(boards), {"E1S01", "E1S03", "ESpecial", "S07"})
        self.assertTrue(all(entry["episode"] == 1 for entry in boards.values()))
        progress = task["assets"]["4_progress"]
        self.assertEqual(progress["episodes"], [{"number": 1, "total": 4, "done": 4, "complete": True}])


class ExecuteAllStagesEpisodeLoopTests(unittest.TestCase):
    """一键成片：阶段4逐集推进时必须连续补跑到所有集 complete，再进入阶段5。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo

    def tearDown(self):
        self.temp.cleanup()

    def test_one_click_reruns_stage4_until_every_episode_completes(self):
        import asyncio

        task = _task([
            {"scene_id": "E1S01", "content": "第一集"},
            {"scene_id": "E2S01", "content": "第二集"},
        ])
        self.repo.save_task(task["task_id"], task)
        calls = []
        repo = self.repo

        async def fake_execute_stage(service_self, task_id, stage):
            calls.append(stage)
            current = repo.get_task(task_id)
            if stage == 4:
                # 模拟逐集引擎：每次执行只推进一个未完成的集。
                progress = current["assets"].get("4_progress")
                if not progress:
                    current["assets"]["4_progress"] = {"current_episode": 2, "episodes": [
                        {"number": 1, "total": 1, "done": 1, "complete": True},
                        {"number": 2, "total": 1, "done": 0, "complete": False},
                    ]}
                else:
                    progress["episodes"][1].update(done=1, complete=True)
                repo.save_task(task_id, current)
            return current

        with patch.object(DramaService, "execute_stage", fake_execute_stage), \
             patch("app.service.drama_service.asyncio.sleep", new=lambda *_a, **_k: _instant()):
            asyncio.run(self.service.execute_all_stages(task["task_id"]))

        # 阶段4被自动补跑到第2集完成，然后才推进 5-8；绝不带着未完成的集闯关。
        self.assertEqual(calls, [4, 4, 5, 6, 7, 8])


async def _instant():
    return None


class GenerateSceneBoardInvariantTests(unittest.TestCase):
    """直接打真实 _generate_scene_board(只桩 gateway 的 LLM/生图)，证伪 shots_done 虚报路径。"""

    def setUp(self):
        self.service = DramaService()
        self.task = {
            "task_id": "board-invariant-1",
            "assets": {"3_sheets": {}, "3_characters": []},
            "config": {"llm_model": "m", "image_model": "img", "video_model": "v"},
        }
        self.scene = {"scene_id": "E1S02", "content": "林夏追查线索", "characters": ["林夏"], "duration": "45s"}

    def _call(self, llm_response, generate_image):
        with patch.object(self.service.gateway, "call_llm", return_value=llm_response), \
             patch.object(self.service.gateway, "generate_image", side_effect=generate_image), \
             patch("app.service.drama_service.compose_nine_grid", lambda images, path: path):
            return self.service._generate_scene_board(
                self.task, self.task["config"], self.scene,
                sys_prompt="s", storyboard_negative="", title="十二小时", genre="mystery",
                dir_style="noir", shot_style="cinematic", guidance="",
                char_info=("林夏", "记者", "周教授", "反派"),
            )

    def test_partial_image_failure_raises_instead_of_returning_a_done_payload(self):
        """生图部分失败时必须抛错(调用方标 failed/shots_done=0)，绝不返回可被记成 done 的 payload。"""
        calls = {"n": 0}

        def flaky_generate_image(model, prompt, ref_images=None):
            calls["n"] += 1
            if calls["n"] >= 7:
                raise RuntimeError("provider 503")
            return f"http://img.test/{calls['n']}.png", "meta"

        with self.assertRaisesRegex(RuntimeError, "分镜图生成不完整"):
            self._call("模型没有输出表格", flaky_generate_image)
        self.assertEqual(calls["n"], 9)  # 9 格全部尝试过而非提前虚报

    def test_audit_shortfall_padding_is_counted_as_filler_shots(self):
        """LLM 只给出4镜时补足到9格可以，但 filler_shots 必须如实等于 5；整表未解析时等于 9。"""
        table = "| 镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的 |\n"
        table += "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        for i in range(1, 5):
            table += (
                f"| {i} | MS | 平视 | Dolly In | 林夏推门而入，目光扫过散落的档案，指节抵住桌沿慢慢收紧，"
                f"呼吸放缓第{i}拍 | | 环境声 | 2.5s | 铺垫 |\n"
            )

        def steady_generate_image(model, prompt, ref_images=None):
            return "http://img.test/ok.png", "meta"

        payload = self._call(table, steady_generate_image)
        self.assertEqual(len(payload["shots"]), 9)
        self.assertTrue(all(shot["image_url"] for shot in payload["shots"]))
        self.assertEqual(payload["filler_shots"], 5)

        payload = self._call("模型没有输出表格", steady_generate_image)
        self.assertEqual(payload["filler_shots"], 9)


if __name__ == "__main__":
    unittest.main()
