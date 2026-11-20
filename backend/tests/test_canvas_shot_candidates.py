"""A clip offered to a shot joins its version list: the clip in use first, links that can no longer play left out."""

import time
import unittest
from unittest.mock import patch

from app.core import canvas_shot_candidates, media_compositor

EXPIRED = f"https://ark.example/clip.mp4?X-Tos-Date=20261112T093210Z&X-Tos-Expires=86400"


class OfferTest(unittest.TestCase):
    def test_the_clip_in_use_leads_and_dead_links_go(self):
        shot = {"scene_id": "E1S02", "shot_id": 1, "shot_uid": 100201}
        assets = {"5": [{"scene_id": "E1S02", "shot_id": 1, "shot_uid": 100201, "video_url": "/media/kept.mp4", "candidates": [EXPIRED, "/media/other.mp4"]}]}
        alive = {"/media/other.mp4"}
        with patch.object(media_compositor, "media_available", side_effect=lambda url: url in alive):
            self.assertTrue(canvas_shot_candidates.offer(assets, shot, "/media/new.mp4"))
        self.assertEqual(assets["5"][0]["candidates"], ["/media/kept.mp4", "/media/other.mp4", "/media/new.mp4"])
        self.assertEqual(assets["5"][0]["video_url"], "/media/kept.mp4", "offered, not switched")

    def test_a_segment_clip_and_a_shot_without_a_clip_are_left_alone(self):
        shot = {"scene_id": "E1S02", "shot_id": 1, "shot_uid": 100201}
        segment = {"5": [{"scene_id": "E1S02", "shot_id": 1, "shot_uids": [100201, 100202], "video_url": "/media/seg.mp4", "candidates": ["/media/seg.mp4"]}]}
        self.assertFalse(canvas_shot_candidates.offer(segment, shot, "/media/new.mp4"))
        self.assertEqual(segment["5"][0]["candidates"], ["/media/seg.mp4"])
        self.assertFalse(canvas_shot_candidates.offer({"5": []}, shot, "/media/new.mp4"))


if __name__ == "__main__":
    unittest.main()
