# -*- coding: utf-8 -*-
"""一场戏多长：拆解没写就取正文里的「时长：6秒」；场比模型宜用的下限短时，每格按场长出，2 分钟的剧本不被拉成 9 分钟。"""

import unittest

from app.core import scene_seconds
from app.core.video_references import MIN_SHOT_SECONDS, preferred_shot_seconds


class SceneSecondsTests(unittest.TestCase):
    def test_the_length_written_in_the_scene_text_is_used_when_the_field_is_empty(self):
        scene = {"duration": "", "content": "偏殿供桌 清晨 内景 镜头：中景 缓推 时长：6秒 画面：药白素衣的年轻女子……"}
        self.assertEqual(scene_seconds.scene_duration(scene), "6秒")
        self.assertEqual(scene_seconds.scene_duration({"duration": "12秒", "content": "时长：6秒"}), "12秒", "拆解写了以拆解为准")
        self.assertEqual(scene_seconds.scene_duration({"content": "没写时长"}), "")

    def test_a_short_scene_is_not_stretched_to_the_models_preferred_floor(self):
        floor, _cap = preferred_shot_seconds("doubao-seedance-2-5-260628")
        self.assertEqual(floor, 15)
        self.assertEqual(scene_seconds.clip_floor(floor, 6, MIN_SHOT_SECONDS), 6)
        self.assertEqual(scene_seconds.clip_floor(floor, 2, MIN_SHOT_SECONDS), MIN_SHOT_SECONDS, "不低于模型能出的最短")
        self.assertEqual(scene_seconds.clip_floor(floor, 25, MIN_SHOT_SECONDS), floor, "长场照旧")
        self.assertEqual(scene_seconds.clip_floor(floor, 0, MIN_SHOT_SECONDS), floor, "不知道多长就照旧")


if __name__ == "__main__":
    unittest.main()
