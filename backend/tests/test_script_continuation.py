# -*- coding: utf-8 -*-
"""A screenplay that stopped short must be completable in place.

Projects generated before batched writing hold e.g. 15 episodes of a 30 episode
plan. Regenerating from scratch would discard finished episodes and invalidate
their downstream assets, so the missing episodes are appended instead.
"""
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


def _episode_text(index: int) -> str:
    return (
        f"第{index}集 副标题{index}\n"
        f"场景1：市井长街 黄昏 外景\n镜头：中近景 缓推\n陈九：第{index}集第一场。\n"
    )


class _ContinuationGateway:
    def __init__(self, *, breakdown: str = "", refuse: bool = False):
        self.calls: List[Dict[str, Any]] = []
        self.breakdown = breakdown
        self.refuse = refuse

    def call_llm(self, model, system_prompt, user_prompt, title,
                 director_style="", shot_style="", user_instruction="", max_tokens=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if "结构化分析器" in system_prompt:
            return self.breakdown or "{}"
        if self.refuse:
            return ""
        single = re.search(r"【本次只写 第 (\d+) 集】", user_prompt)
        if single:
            return _episode_text(int(single.group(1)))
        span = re.search(r"【本次只写 第 (\d+) 集到第 (\d+) 集】", user_prompt)
        if not span:
            return ""
        return "\n".join(
            _episode_text(index) for index in range(int(span.group(1)), int(span.group(2)) + 1)
        )


class ScriptContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("truncated-1", {
            "task_id": "truncated-1",
            "config": {
                "title_suggestion": "流氓天子",
                "episode_count": 30,
                "llm_model": "m",
                "video_model": "seedance2.0",
            },
            "assets": {
                "1": "导演策划",
                "2": "".join(_episode_text(index) for index in range(1, 16)),
            },
        })

    def tearDown(self):
        self.temp.cleanup()

    def _service(self, gateway):
        service = DramaService.__new__(DramaService)
        service.repo = self.repo
        service.gateway = gateway
        return service

    def test_the_missing_half_is_appended_and_persisted(self):
        service = self._service(_ContinuationGateway())

        dashboard = service.continue_script("truncated-1")

        stored = self.repo.get_task("truncated-1")["assets"]["2"]
        self.assertEqual(service._script_episode_indexes(stored), list(range(1, 31)))
        self.assertEqual(dashboard.stats.scripted_episodes, 30)
        self.assertEqual(dashboard.stats.total_episodes, 30)

    def test_existing_episodes_are_never_rewritten(self):
        service = self._service(_ContinuationGateway())
        before = self.repo.get_task("truncated-1")["assets"]["2"]

        service.continue_script("truncated-1")

        after = self.repo.get_task("truncated-1")["assets"]["2"]
        self.assertTrue(after.startswith(before.split("第16集")[0].strip()[:40]))
        for index in range(1, 16):
            self.assertEqual(after.count(f"第{index}集 副标题{index}"), 1)

    def test_only_the_missing_span_is_requested(self):
        gateway = _ContinuationGateway()
        service = self._service(gateway)

        service.continue_script("truncated-1")

        writes = [call for call in gateway.calls if "结构化分析器" not in call["system_prompt"]]
        self.assertTrue(writes)
        for call in writes:
            span = re.search(r"【本次只写 第 (\d+) 集(?:到第 (\d+) 集)?】", call["user_prompt"])
            self.assertIsNotNone(span)
            self.assertGreaterEqual(int(span.group(1)), 16)

    def test_the_continuation_prompt_carries_the_video_model_clip_cap(self):
        gateway = _ContinuationGateway()
        service = self._service(gateway)

        service.continue_script("truncated-1")

        writes = [call for call in gateway.calls if "结构化分析器" not in call["system_prompt"]]
        self.assertIn("不得超过 15 秒", writes[0]["system_prompt"])
        self.assertIn("续写", writes[0]["system_prompt"])

    def test_a_complete_script_is_refused_rather_than_re_run(self):
        self.repo.save_task("complete-1", {
            "task_id": "complete-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 3, "llm_model": "m"},
            "assets": {"2": "".join(_episode_text(index) for index in range(1, 4))},
        })
        gateway = _ContinuationGateway()

        with self.assertRaises(ValueError) as caught:
            self._service(gateway).continue_script("complete-1")

        self.assertIn("无需补写", str(caught.exception))
        self.assertEqual(gateway.calls, [])

    def test_a_project_without_a_script_is_refused(self):
        self.repo.save_task("empty-1", {
            "task_id": "empty-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 3, "llm_model": "m"},
            "assets": {},
        })

        with self.assertRaises(ValueError):
            self._service(_ContinuationGateway()).continue_script("empty-1")

    def test_a_model_that_returns_nothing_leaves_the_script_untouched(self):
        service = self._service(_ContinuationGateway(refuse=True))
        before = self.repo.get_task("truncated-1")["assets"]["2"]

        with self.assertRaises(ValueError):
            service.continue_script("truncated-1")

        self.assertEqual(self.repo.get_task("truncated-1")["assets"]["2"], before)

    def test_a_concurrent_script_edit_is_refused_not_clobbered(self):
        from app.service.drama_service import ScriptUpdateConflictError

        service = self._service(_ContinuationGateway())
        rival = "".join(_episode_text(index) for index in range(1, 16)) + "\n别的页面刚刚改过的剧本\n"

        original_extract = service._extract_script_breakdown

        def _extract_then_race(*args, **kwargs):
            # Another tab saves the screenplay while this continuation is still writing.
            task = self.repo.get_task("truncated-1")
            task["assets"]["2"] = rival
            self.repo.save_task("truncated-1", task)
            return original_extract(*args, **kwargs)

        service._extract_script_breakdown = _extract_then_race

        with self.assertRaises(ScriptUpdateConflictError):
            service.continue_script("truncated-1")

        self.assertEqual(self.repo.get_task("truncated-1")["assets"]["2"], rival)

    def test_a_running_project_is_refused(self):
        task = self.repo.get_task("truncated-1")
        task["status"] = "running"
        self.repo.save_task("truncated-1", task)
        gateway = _ContinuationGateway()

        with self.assertRaises(ValueError) as caught:
            self._service(gateway).continue_script("truncated-1")

        self.assertIn("仍有生成任务运行", str(caught.exception))
        self.assertEqual(gateway.calls, [])

    def test_a_running_episode_also_blocks_the_append(self):
        task = self.repo.get_task("truncated-1")
        task["episodes"] = [{"index": 3, "status": "running"}]
        self.repo.save_task("truncated-1", task)

        with self.assertRaises(ValueError):
            self._service(_ContinuationGateway()).continue_script("truncated-1")

    def test_scattered_gaps_are_requested_individually_not_as_one_span(self):
        self.repo.save_task("gappy-1", {
            "task_id": "gappy-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30, "llm_model": "m"},
            "assets": {
                "1": "导演策划",
                # Everything except 3, 17 and 25 already exists.
                "2": "".join(
                    _episode_text(index) for index in range(1, 31)
                    if index not in {3, 17, 25}
                ),
            },
        })
        gateway = _ContinuationGateway()

        self._service(gateway).continue_script("gappy-1")

        writes = [call for call in gateway.calls if "结构化分析器" not in call["system_prompt"]]
        spans = [
            re.search(r"【本次只写 第 (\d+) 集(?:到第 (\d+) 集)?】", call["user_prompt"]).groups()
            for call in writes
        ]
        # One request per gap - never "第3集到第25集", which would re-request 20 finished episodes.
        self.assertEqual([first for first, _ in spans], ["3", "17", "25"])
        self.assertTrue(all(last is None for _, last in spans))
        stored = self.repo.get_task("gappy-1")["assets"]["2"]
        self.assertEqual(DramaService._script_episode_indexes(stored), list(range(1, 31)))

    def test_contiguous_runs_are_still_batched_together(self):
        self.assertEqual(
            DramaService._contiguous_batches([16, 17, 18, 19, 20], 4),
            [[16, 17, 18, 19], [20]],
        )
        self.assertEqual(DramaService._contiguous_batches([3, 17, 25], 4), [[3], [17], [25]])
        self.assertEqual(DramaService._contiguous_batches([], 4), [])

    def test_a_bold_heading_script_is_understood_by_both_parsers(self):
        # The dashboard stat and the repair must agree, or a complete script shows
        # as truncated and 补写 fails with 409 forever.
        from app.core.writer_dashboard import compile_writer_dashboard

        bold = "".join(
            f"**第{index}集 副标题{index}**\n场景1：街市 日 外景\n陈九：台词。\n\n"
            for index in range(1, 31)
        )
        self.repo.save_task("bold-1", {
            "task_id": "bold-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30, "llm_model": "m"},
            "assets": {"2": bold},
        })

        stats = compile_writer_dashboard(self.repo.get_task("bold-1")).stats

        self.assertEqual(stats.scripted_episodes, 30)
        self.assertEqual(stats.total_episodes, 30)
        with self.assertRaises(ValueError):
            self._service(_ContinuationGateway()).continue_script("bold-1")

    def test_a_chinese_numeral_script_is_counted_correctly(self):
        from app.core.writer_dashboard import compile_writer_dashboard

        labels = ["一", "二", "三", "十三", "二十", "三十"]
        script = "".join(f"第{label}集 副标题\n正文\n\n" for label in labels)
        self.repo.save_task("cn-1", {
            "task_id": "cn-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30, "llm_model": "m"},
            "assets": {"2": script},
        })

        stats = compile_writer_dashboard(self.repo.get_task("cn-1")).stats

        # 第十三集 / 第二十集 / 第三十集 used to collapse onto episode 1.
        self.assertEqual(stats.scripted_episodes, 6)

    def test_a_missing_task_returns_none(self):
        self.assertIsNone(self._service(_ContinuationGateway()).continue_script("no-such-task"))

    def test_the_writer_dashboard_asset_is_recompiled(self):
        service = self._service(_ContinuationGateway())

        service.continue_script("truncated-1")

        stored = self.repo.get_task("truncated-1")["assets"]["2_writer_dashboard"]
        self.assertEqual(stored["stats"]["scriptedEpisodes"], 30)


if __name__ == "__main__":
    unittest.main()
