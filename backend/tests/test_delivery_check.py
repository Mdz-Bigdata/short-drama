"""成片交付前验收：太短、台词放不下、景别不变、同场光向换边、景别太少。"""

import unittest

from app.core import delivery_check


def _task(clips, boards):
    return {"assets": {"5": clips, "4": boards}}


def _clip(scene, uid, size="中景", dialogue="", seconds=6):
    return {"scene_id": scene, "shot_id": uid, "shot_uid": uid, "video_url": f"https://cdn/{uid}.mp4", "size": size,
            "dialogue": dialogue, "duration": seconds}


def _timeline(clips, trims=None):
    rows = []
    for index, clip in enumerate(clips):
        start, end = (trims or {}).get(index, (0.0, None))
        rows.append({"shot_uid": clip["shot_uid"], "shot_id": clip["shot_id"], "scene_id": clip["scene_id"], "video_url": clip["video_url"],
                     "duration": clip["duration"], "in": start, "out": end, "subtitle": clip["dialogue"].split("：")[-1],
                     "review": {"decision": "pending"}})
    return {"clips": rows}


class DeliveryCheckTests(unittest.TestCase):
    def test_reading_sizes_and_light(self):
        self.assertEqual(delivery_check.opening_size("中景起幅→近景落幅"), "中景")
        self.assertEqual(delivery_check.opening_size("中近景转近景"), "中近景")
        self.assertEqual(delivery_check.light_side("主光：暖橙硬光自画面左侧偏后低角度斜切"), "左")
        self.assertEqual(delivery_check.light_side("暖橙光只打亮案面、三娘左颊"), "", "a lit cheek is not where the light comes from")

    def test_each_problem_names_its_shot_and_a_clean_cut_passes(self):
        clips = [
            _clip("E1S01", 1, "全景", seconds=6),
            _clip("E1S01", 2, "中景", dialogue="林夏：（哽咽）我等了你整整三年，你一句话都没有给过我。", seconds=8),
            _clip("E1S01", 3, "中景", seconds=1),
            _clip("E1S02", 4, "中景"), _clip("E1S02", 5, "中景"), _clip("E1S02", 6, "中景"),
        ]
        # 同一场两镜光向相反：第 1 镜左、第 2 镜右。
        boards = [
            {"scene_id": "E1S01", "shot_id": 1, "storyboard_prompt": "主光自画面左侧打来"},
            {"scene_id": "E1S01", "shot_id": 2, "storyboard_prompt": "主光自画面右侧打来"},
        ]
        issues = delivery_check.check(_task(clips, boards), _timeline(clips))
        found = {(issue["shot_uid"], issue["rule"]) for issue in issues}
        self.assertIn((2, "dialogue"), found)
        self.assertIn((3, "too_short"), found)
        self.assertIn((5, "same_size"), found, "the fourth 中景 in a row")
        self.assertNotIn((6, "same_size"), found, "a run is reported once")
        self.assertIn((2, "light_flip"), found)
        self.assertTrue(all(issue["detail"] for issue in issues))
        clean = [_clip("E1S01", 1, "全景"), _clip("E1S01", 2, "中景"), _clip("E1S01", 3, "特写")]
        self.assertEqual(delivery_check.check(_task(clean, []), _timeline(clean)), [])

    def test_the_check_follows_the_trims_on_the_timeline(self):
        clips = [_clip("E1S01", 1, "全景", dialogue="林夏：我今天就是来跟你说清楚这件事。", seconds=8), _clip("E1S01", 2, "近景"), _clip("E1S01", 3, "特写")]
        self.assertEqual(delivery_check.check(_task(clips, []), _timeline(clips)), [])
        trimmed = delivery_check.check(_task(clips, []), _timeline(clips, {0: (0.0, 3.0)}))
        self.assertEqual([issue["rule"] for issue in trimmed], ["dialogue"])

    def test_a_cut_with_fewer_than_three_kinds_of_shot_is_noted_once(self):
        clips = [_clip("E1S01", 1, "中景"), _clip("E1S01", 2, "近景"), _clip("E1S01", 3, "中景")]
        issues = delivery_check.check(_task(clips, []), _timeline(clips))
        self.assertEqual([issue["rule"] for issue in issues], ["few_sizes"])


if __name__ == "__main__":
    unittest.main()
