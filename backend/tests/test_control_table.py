"""每镜控制表：各靠哪份素材，两份抢同一件事、或该有的没有，都标出来。"""

import unittest
from unittest.mock import patch

from app.service import control_table as table
from app.service.director_desk_service import ShotBlockout


def _rows(shot, assets=(), *, blockout=ShotBlockout(), still=""):
    with patch.object(table.desk, "shot_blockout", return_value=blockout), patch.object(table, "_desk_still", return_value=still):
        return {row["aspect"]: row for row in table.control_table({"assets": {}}, shot, list(assets))}


ACTOR = {"kind": "actor", "name": "谢九", "in_video": True}
SCENE = {"kind": "scene", "name": "磨刀铺内", "in_video": True}


class ControlTableTests(unittest.TestCase):
    def test_a_well_fed_shot_has_one_source_per_job(self):
        rows = _rows({"scene_id": "E1S01", "shot_id": 1, "image_url": "/p.png", "characters": ["谢九"]}, [ACTOR, SCENE])
        self.assertEqual(rows["look"]["sources"], ["角色参考图（谢九）"])
        self.assertEqual(rows["place"]["status"], "ok")
        self.assertEqual(rows["pose"]["sources"], ["分镜画面"])
        self.assertEqual(rows["rhythm"]["status"], "none")
        self.assertFalse([row for row in rows.values() if row["status"] in ("duplicate", "missing")])

    def test_two_motion_videos_or_a_blockout_plus_a_text_move_are_flagged(self):
        blockout = ShotBlockout(clip_url="/desk.mp4")
        two = _rows({"scene_id": "E1S01", "shot_id": 1, "reference_videos": ["/desk.mp4", "/mine.mp4"]}, [ACTOR, SCENE], blockout=blockout)
        self.assertEqual(two["motion"]["status"], "duplicate")
        self.assertIn("2 份视频参考", two["motion"]["note"])
        camera = _rows({"scene_id": "E1S01", "shot_id": 1, "reference_videos": ["/desk.mp4"], "visual": {"camera_motion": "Push In"}},
                       [ACTOR, SCENE], blockout=blockout)
        self.assertEqual(camera["motion"]["status"], "duplicate")
        self.assertIn("Push In", camera["motion"]["note"])
        steady = _rows({"scene_id": "E1S01", "shot_id": 1, "reference_videos": ["/desk.mp4"], "visual": {"camera_motion": "Static"}},
                       [ACTOR, SCENE], blockout=blockout)
        self.assertEqual(steady["motion"]["status"], "ok")

    def test_two_opening_frames_and_missing_references_are_flagged(self):
        rows = _rows({"scene_id": "E1S01", "shot_id": 1, "image_url": "/p.png", "characters": ["谢九"]}, still="/still.png")
        self.assertEqual(rows["pose"]["status"], "duplicate")
        self.assertEqual(rows["look"]["status"], "missing")
        self.assertEqual(rows["place"]["status"], "missing")
        depth = _rows({"scene_id": "E1S01", "shot_id": 1, "reference_videos": ["/depth.mp4"]}, blockout=ShotBlockout(clip_url="/depth.mp4", depth=True))
        self.assertEqual(depth["motion"]["sources"], ["导演台深度视频"])
        self.assertEqual(depth["space"]["status"], "missing", "a depth clip carries no colour or material")


if __name__ == "__main__":
    unittest.main()
