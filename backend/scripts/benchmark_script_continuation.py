"""Offline matched-input benchmark: whole-show vs incremental analysis.

Run from backend: ./.venv/bin/python scripts/benchmark_script_continuation.py
All model calls are local stubs; only temporary SQLite stores are written.
"""

import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from tests.test_script_continuation import _ContinuationGateway, _episode_text


class DelayedGateway(_ContinuationGateway):
    def call_llm(self, *args, **kwargs):
        if "结构化分析器" not in args[1]:
            return super().call_llm(*args, **kwargs)
        time.sleep(0.02)
        self.calls.append({"system_prompt": args[1], "user_prompt": args[2]})
        script = (
            args[2]
            .split("【剧本原文】：", 1)[1]
            .split("【本次分析范围】")[0]
            .split("【导演策划大纲")[0]
        )
        return json.dumps(
            {
                "scenes": [
                    {"scene_id": f"E{index}S01", "content": "新分析", "duration": "10s"}
                    for index in DramaService._script_episode_indexes(script)
                ],
                "overview": {"title": "测试"},
            }
        )


def measure(whole_show: bool) -> dict:
    timings, calls = [], []
    for _ in range(5):
        with tempfile.TemporaryDirectory() as directory:
            service = DramaService.__new__(DramaService)
            service.repo = TaskRepository(str(Path(directory) / "tasks.json"))
            service.gateway = DelayedGateway()
            existing = [index for index in range(1, 31) if index not in {16, 17, 18}]
            scenes = [
                {
                    "scene_id": f"E{index}S01",
                    "content": "已确认",
                    "image_url": "keep.png",
                }
                for index in existing
            ]
            service.repo.save_task(
                "bench",
                {
                    "task_id": "bench",
                    "config": {"episode_count": 30, "llm_model": "fake"},
                    "assets": {
                        "2": "".join(_episode_text(index) for index in existing),
                        "2_breakdown": {"scenes": scenes},
                    },
                },
            )
            if whole_show:
                extract = service._extract_script_breakdown

                def full_analysis(config, title, director, shot, script, plan):
                    full = "".join(_episode_text(index) for index in range(1, 31))
                    return extract(config, title, director, shot, full, plan)

                service._extract_script_breakdown = full_analysis
            start = time.perf_counter()
            dashboard = service.continue_script("bench")
            timings.append(round((time.perf_counter() - start) * 1000, 3))
            calls.append(
                sum(
                    "结构化分析器" in call["system_prompt"]
                    for call in service.gateway.calls
                )
            )
            assert dashboard.stats.scripted_episodes == 30
            assert dashboard.stats.missing_episodes == []
            saved = service.repo.get_task("bench")["assets"]["2_breakdown"]["scenes"]
            assert all(scene in saved for scene in scenes)
    return {
        "ms": timings,
        "median_ms": statistics.median(timings),
        "analysis_calls": calls,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {"whole_show_baseline": measure(True), "incremental": measure(False)},
            indent=2,
        )
    )
