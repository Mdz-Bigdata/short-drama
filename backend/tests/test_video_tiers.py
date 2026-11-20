# -*- coding: utf-8 -*-
"""分辨率档位：型号没有的档位不发出去；成片清晰度只提供有官方价的档位；Flash 有自己的价。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import clip_fixes, video_tiers
from app.core.providers import pricing
from app.core.providers.pricing import PricingTable
from app.core.model_gateway import ModelGateway
from app.core.video_references import billed_resolution
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

_TABLE = PricingTable.from_mapping({
    "seedance-2-5-flash": {"kind": "per_second", "price": 0.99, "by_resolution": {"480p": 0.46, "720p": 0.99}},
    "seedance-2-5": {"kind": "per_second", "price": 1.51, "by_resolution": {"480p": 0.67, "720p": 1.51, "1080p": 3.74}},
})


class TierTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(pricing, "_table", _TABLE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flash_stops_at_720p_and_the_full_model_goes_to_4k(self):
        self.assertEqual(video_tiers.tiers("doubao-seedance-2-5-flash-261115"), ("480p", "720p"))
        self.assertEqual(video_tiers.tiers("Seedance 2.5 Flash"), ("480p", "720p"))
        self.assertEqual(video_tiers.tiers("seedance2.5"), ("480p", "720p", "1080p", "4k"))
        self.assertEqual(video_tiers.tiers("minimax-h3"), ())

    def test_a_tier_the_model_lacks_is_brought_down_and_an_unknown_model_is_left_alone(self):
        self.assertEqual(video_tiers.fit("seedance-2-5-flash", "1080p"), "720p")
        self.assertEqual(video_tiers.fit("seedance-2-5-flash", "4K"), "720p")
        self.assertEqual(video_tiers.fit("seedance-2-5", "4K"), "4k")
        self.assertEqual(video_tiers.fit("seedance-2-5", "480p"), "480p")
        self.assertEqual(video_tiers.fit("minimax-h3", "768p"), "768p")
        self.assertIsNone(video_tiers.fit("seedance-2-5", None))

    def test_what_is_billed_is_what_the_model_can_render(self):
        with patch.dict(os.environ, {"SEEDANCE_VIDEO_RESOLUTION": "1080p"}):
            self.assertEqual(billed_resolution("seedance-2-5-flash"), "720p")
            self.assertEqual(billed_resolution("seedance-2-5"), "1080p")
        self.assertEqual(billed_resolution("seedance-2-5-flash", "480p"), "480p")

    def test_flash_is_priced_by_its_own_entry_not_the_full_models(self):
        self.assertAlmostEqual(_TABLE.cost("doubao-seedance-2-5-flash-261115", units={"seconds": 10, "resolution": "720p"})[0], 9.9)
        self.assertAlmostEqual(_TABLE.cost("seedance2.5-flash", units={"seconds": 10, "resolution": "480p"})[0], 4.6)
        self.assertAlmostEqual(_TABLE.cost("doubao-seedance-2-5-pro", units={"seconds": 10, "resolution": "720p"})[0], 15.1)

    def test_only_priced_tiers_above_the_draft_are_offered(self):
        # 4k has no official price in the table, so it is not offered even though the model renders it.
        self.assertEqual(video_tiers.final_choices("seedance-2-5"), ["720p", "1080p"])
        self.assertEqual(video_tiers.final_choices("seedance-2-5-flash"), ["720p"])
        self.assertEqual(video_tiers.final_choices("minimax-h3"), [])

    def test_a_price_for_4k_makes_it_a_choice(self):
        table = PricingTable.from_mapping({"seedance-2-5": {"kind": "per_second", "price": 1.51, "by_resolution": {"720p": 1.51, "4K": 9.0}}})
        with patch.object(pricing, "_table", table):
            self.assertEqual(video_tiers.final_choices("seedance-2-5"), ["720p", "4k"])

    def test_the_projects_choice_holds_only_while_the_model_offers_it(self):
        self.assertEqual(video_tiers.final_resolution({"video_resolution": "1080P"}, "seedance-2-5"), "1080p")
        self.assertIsNone(video_tiers.final_resolution({"video_resolution": "1080p"}, "seedance-2-5-flash"))
        self.assertIsNone(video_tiers.final_resolution({}, "seedance-2-5"))

    def test_a_choice_that_is_not_offered_is_refused_with_the_ones_that_are(self):
        self.assertEqual(video_tiers.checked_choice("seedance-2-5", "1080p"), "1080p")
        self.assertIsNone(video_tiers.checked_choice("seedance-2-5", ""))
        with self.assertRaises(ValueError) as refused:
            video_tiers.checked_choice("seedance-2-5-flash", "1080p")
        self.assertIn("720p", str(refused.exception))
        with self.assertRaises(ValueError):
            video_tiers.checked_choice("minimax-h3", "1080p")

    def test_a_draft_stays_a_draft_and_the_rest_goes_out_at_the_final_resolution(self):
        config = {"video_draft": True, "video_resolution": "1080p", "video_model": "seedance-2-5"}
        self.assertEqual(clip_fixes.render_resolution(config, {}), "480p")
        self.assertEqual(clip_fixes.render_resolution(config, {"hd_retake": True}), "1080p")
        self.assertEqual(clip_fixes.render_resolution({"video_resolution": "1080p", "video_model": "seedance-2-5"}), "1080p")
        self.assertIsNone(clip_fixes.render_resolution({"video_model": "seedance-2-5"}))


class ProjectSettingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in (
            patch.object(pricing, "_table", _TABLE),
            patch.object(ModelGateway, "effective_video_model", staticmethod(lambda model: model)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t", {"task_id": "t", "owner_user_id": "u", "status": "completed", "current_stage": 5,
                                  "config": {"video_model": "seedance-2-5"}, "assets": {}})
        self.service = DramaService()
        self.service.repo = self.repo
        workspace = patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)

    def _config(self) -> dict:
        return self.repo.get_task("t")["config"]

    def test_a_tier_the_model_offers_is_saved_and_an_empty_one_clears_it(self):
        self.assertEqual(self.service.set_video_resolution("t", "1080P"), {"ok": True})
        self.assertEqual(self._config()["video_resolution"], "1080p")
        self.service.set_video_resolution("t", "")
        self.assertNotIn("video_resolution", self._config())

    def test_an_unpriced_or_missing_tier_is_refused_and_nothing_is_saved(self):
        with self.assertRaises(ValueError):
            self.service.set_video_resolution("t", "4k")
        self.assertNotIn("video_resolution", self._config())

    def test_a_missing_project_answers_none(self):
        self.assertIsNone(self.service.set_video_resolution("nope", "1080p"))


if __name__ == "__main__":
    unittest.main()
