# -*- coding: utf-8 -*-
"""第 3 阶段提速：资产参考图同时出几张(有上限)，一张失败不拖累别的；每张的出法不变。"""

import asyncio
import os
import threading
import time
import unittest
from unittest.mock import patch

from app.core import project_asset_completion as pac


class _Store:
    def __init__(self, *_args, **_kwargs):
        pass

    async def get_element(self, element_id, _owner):
        return type("Item", (), {"id": element_id})()

    async def close(self):
        pass


class ConcurrentAssetImagesTests(unittest.TestCase):
    def test_missing_images_are_drawn_a_few_at_a_time_and_one_failure_does_not_stop_the_rest(self):
        summaries = [{"id": f"p{n}", "name": f"道具{n}", "kind": "prop", "has_image": False} for n in range(7)]
        running = {"now": 0, "peak": 0}
        lock = threading.Lock()

        async def draw(*, item, owner_id, store, extra_prompt):
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])
            await asyncio.sleep(0.05)
            with lock:
                running["now"] -= 1
            if item.id == "p3":
                raise RuntimeError("provider said no")

        async def nothing(**_kwargs):
            return None

        async def listed(*_args, **_kwargs):
            return summaries

        with patch.object(pac, "PlatformStore", _Store), \
             patch.object(pac, "project_element_summaries", side_effect=listed), \
             patch.object(pac, "extract_production_assets", return_value=[]), \
             patch.object(pac, "crowd_wardrobe", return_value=[]), \
             patch.object(pac, "evaluate_asset_readiness", return_value={}), \
             patch("app.api.drama_api._import_production_asset_candidates", side_effect=nothing), \
             patch("app.api.drama_api._file_character_looks", side_effect=nothing), \
             patch("app.api.drama_api._file_crowd_wardrobe", side_effect=nothing), \
             patch("app.api.element_api._generate_non_actor_reference", side_effect=draw), \
             patch.dict(os.environ, {"STAGE3_ASSET_IMAGE_CONCURRENCY": "3"}):
            started = time.monotonic()
            result = asyncio.run(pac._complete({}, "owner", "task", True))
            elapsed = time.monotonic() - started
        self.assertEqual(running["peak"], 3, "three at a time, never more")
        self.assertLess(elapsed, 7 * 0.05, "faster than one after another")
        self.assertEqual(result["generated"], 6)
        self.assertEqual(result["generation_failed"], ["道具3"])

    def test_with_no_setting_the_images_fill_the_process_wide_image_ceiling(self):
        # 名字互不包含：被另一条名字盖住的不单独出图(见 CoveredNameTests)。
        summaries = [{"id": f"p{n}", "name": f"{word}器", "kind": "prop", "has_image": False} for n, word in enumerate("金银铜铁锡玉石木竹陶瓷漆骨角")]
        running = {"now": 0, "peak": 0}
        lock = threading.Lock()

        async def draw(*, item, owner_id, store, extra_prompt):
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])
            await asyncio.sleep(0.05)
            with lock:
                running["now"] -= 1

        async def nothing(**_kwargs):
            return None

        async def listed(*_args, **_kwargs):
            return summaries

        environment = {key: value for key, value in os.environ.items() if key != "STAGE3_ASSET_IMAGE_CONCURRENCY"}
        with patch.object(pac, "PlatformStore", _Store), \
             patch.object(pac, "project_element_summaries", side_effect=listed), \
             patch.object(pac, "extract_production_assets", return_value=[]), \
             patch.object(pac, "crowd_wardrobe", return_value=[]), \
             patch.object(pac, "evaluate_asset_readiness", return_value={}), \
             patch("app.api.drama_api._import_production_asset_candidates", side_effect=nothing), \
             patch("app.api.drama_api._file_character_looks", side_effect=nothing), \
             patch("app.api.drama_api._file_crowd_wardrobe", side_effect=nothing), \
             patch("app.api.element_api._generate_non_actor_reference", side_effect=draw), \
             patch.object(pac.storyboard_concurrency, "image_ceiling", return_value=6), \
             patch.dict(os.environ, environment, clear=True):
            result = asyncio.run(pac._complete({}, "owner", "task", True))
        self.assertEqual(running["peak"], 6, "as many as the process lets the image provider see, never more")
        self.assertEqual(result["generated"], 14)


class CoveredNameTests(unittest.TestCase):
    def test_an_entry_another_one_fully_names_is_not_drawn_on_its_own(self):
        rows = [
            {"id": "1", "kind": "set_dressing", "name": "香头"}, {"id": "2", "kind": "set_dressing", "name": "偏殿香头"},
            {"id": "3", "kind": "set_dressing", "name": "偏殿木门"}, {"id": "4", "kind": "set_dressing", "name": "偏殿木门与门槛"},
            {"id": "5", "kind": "prop", "name": "长剑"}, {"id": "6", "kind": "prop", "name": "长剑剑鞘"},
            {"id": "7", "kind": "effect", "name": "剑刃冷白光"}, {"id": "8", "kind": "effect", "name": "剑刃 冷白光"},
            {"id": "9", "kind": "prop", "name": "香头"},
        ]
        from app.core import contained_assets

        self.assertEqual(contained_assets.skip_ids(rows), {"1", "3", "5", "8"})
        # 长剑和剑鞘是两样配套的东西：画在剑鞘那一张里，长剑不单独出图；别的类里的同名(道具「香头」)不受置景影响。


class HdViewTests(unittest.TestCase):
    def test_the_face_and_body_triptychs_are_drawn_at_the_same_time(self):
        from app.core import actor_hd_views

        running = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def generate(prompt, references, size):
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])
            time.sleep(0.1)
            with lock:
                running["now"] -= 1
            return None

        views = actor_hd_views.generate_hd_views(generate=generate, load=lambda url: b"", name="林夏", desc="", style="", references=[])
        self.assertEqual(views, {})
        self.assertEqual(running["peak"], len(actor_hd_views.HD_GROUPS))
        only_face = actor_hd_views.generate_hd_views(
            generate=generate, load=lambda url: b"", name="林夏", desc="", style="", references=[],
            only=tuple(actor_hd_views.HD_FACE_CELLS),
        )
        self.assertEqual(only_face, {})


class ResumeReuseTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.folder.name) / "tasks.json"))

    def _claim(self, status: str, progress_status: str):
        task_id = f"t-{status}"
        self.service.repo.save_task(task_id, {
            "task_id": task_id, "status": status, "current_stage": 3, "config": {}, "assets": {},
            "stage_progress": {"stage": 3, "status": progress_status}, "workflow_control": {"active": False},
        })
        with patch.object(self.service, "_assert_stage_prerequisites", return_value=None), \
             patch.object(self.service, "_discard_later_stage_outputs", return_value=None), \
             patch.object(self.service, "_adopt_selected_text_model", return_value=None):
            return self.service._claim_stage_task(task_id, 3)

    def test_a_failed_or_interrupted_stage_is_picked_up_as_a_resume_and_a_finished_one_is_not(self):
        self.assertEqual(self._claim("failed", "error")["stage_resume"], 3)
        self.assertEqual(self._claim("interrupted", "running")["stage_resume"], 3)
        self.assertIsNone(self._claim("completed", "success")["stage_resume"], "asked again after it finished: new DNA")

    def test_the_dna_structure_is_asked_once_for_the_same_text(self):
        task = {"task_id": "t1", "assets": {}}
        self.service.repo.save_task("t1", dict(task))
        config = {"llm_model": "deepseek-flash"}
        with patch.object(self.service.gateway, "call_llm", return_value='{"characters": [{"name": "林夏"}]}') as llm:
            first = self.service._extract_character_dna_breakdown(config, "刀不认人", "", "", "林夏：女，三十岁", task=task)
            second = self.service._extract_character_dna_breakdown(config, "刀不认人", "", "", "林夏：女，三十岁", task=task)
        self.assertEqual(first, second)
        self.assertEqual(llm.call_count, 1)
        stored = self.service.repo.get_task("t1")
        self.assertTrue(stored.get("llm_memo"), "kept on the project right away, so a later failure in the stage does not lose it")


if __name__ == "__main__":
    unittest.main()
