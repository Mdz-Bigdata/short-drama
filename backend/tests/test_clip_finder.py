# -*- coding: utf-8 -*-
"""``clip_finder`` answers exactly what ``clip_for`` answers, for every shot, against any list of clips.

The shot workspace, the video admission, the clip hand-off notes and the interactive-story media list look up
the clip of every shot of a show; ``clip_finder`` indexes the clips once instead of scanning them per shot.
"""

import random
import unittest

from app.core import asset_dependents, episode_cycle
from app.core.episode_cycle import clip_finder, clip_for


def _shots(episodes: int = 3, scenes: int = 4, per_scene: int = 5) -> list[dict]:
    return [
        {"scene_id": f"E{e}S{s:02d}", "shot_id": k}
        for e in range(1, episodes + 1) for s in range(1, scenes + 1) for k in range(1, per_scene + 1)
    ]


class SameAnswerTests(unittest.TestCase):
    def assert_same(self, shots, clips):
        find = clip_finder(clips)
        for shot in shots:
            self.assertIs(find(shot), clip_for(shot, clips), f"shot {shot} against {len(clips)} clips")

    def test_one_clip_per_shot(self):
        shots = _shots()
        clips = [{"scene_id": shot["scene_id"], "shot_id": shot["shot_id"], "video_url": f"v{i}"} for i, shot in enumerate(shots)]
        self.assert_same(shots, clips)

    def test_a_storyboard_clip_covers_each_of_its_moments(self):
        shots = _shots(1, 2, 6)
        uids = [episode_cycle.shot_uid(shot) for shot in shots]
        clips = [
            {"scene_id": "E1S01", "shot_id": 1, "shot_uids": uids[:3]},
            {"scene_id": "E1S01", "shot_id": 4, "shot_uids": [str(uid) for uid in uids[3:6]]},  # 编号存成了字符串
            {"shot_uids": uids[6:9]},  # 只有覆盖的编号，没有场号
        ]
        self.assert_same(shots, clips)
        self.assertIs(clip_finder(clips)(shots[4]), clips[1])
        self.assertIsNone(clip_finder(clips)(shots[-1]))

    def test_the_first_clip_listed_wins(self):
        shot = {"scene_id": "E1S01", "shot_id": 2}
        uid = episode_cycle.shot_uid(shot)
        clips = [
            {"scene_id": "E1S01", "shot_id": 9, "shot_uids": [uid]},
            {"scene_id": "E1S01", "shot_id": 2},
            {"shot_id": 2},
            {"shot_id": "2"},
        ]
        self.assert_same([shot], clips)
        self.assertIs(clip_finder(clips)(shot), clips[0])
        # 有场号的片段一段都对不上时，才轮到没有场号的旧片段，同样取最先出现的那一段。
        self.assertIs(clip_finder(clips[2:])(shot), clips[2])
        self.assert_same([shot], clips[2:])

    def test_legacy_clips_are_matched_by_shot_number_as_text(self):
        shots = [{"shot_id": 3}, {"shot_id": "3"}, {"scene_id": "E2S01", "shot_id": 3}, {"shot_id": None}, {}]
        clips = [{"shot_id": "3", "video_url": "a"}, {"shot_id": 3, "video_url": "b"}, {"shot_id": None}, {"video_url": "c"}]
        self.assert_same(shots, clips)

    def test_explicit_uids_and_things_that_are_not_clips(self):
        shots = [{"shot_uid": 101, "shot_id": 1}, {"shot_uid": 0, "scene_id": "E1S01", "shot_id": 1}, {"shot_uid": True, "shot_id": 7}]
        clips = [None, "clip", 5, {"scene_id": "", "shot_uids": []}, {"scene_id": "E1S01", "shot_id": 1},
                 {"scene_id": "x", "shot_uid": 101}, {"shot_uids": [1]}, {"scene_id": "散场", "shot_id": "abc"}]
        self.assert_same(shots, clips)

    def test_no_clips_at_all(self):
        self.assert_same(_shots(1, 1, 3), [])
        self.assertIsNone(clip_finder([])({"shot_id": 1}))

    def test_random_mixes(self):
        rng = random.Random(20261120)
        for _ in range(300):
            shots = _shots(rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 5))
            for shot in shots:
                if rng.random() < 0.2:
                    shot["shot_uid"] = rng.choice([episode_cycle.shot_uid(shot), rng.randint(1, 400000), 0, -3])
                if rng.random() < 0.1:
                    shot.pop("scene_id")
            clips = []
            for _ in range(rng.randint(0, 14)):
                kind = rng.random()
                source = rng.choice(shots)
                if kind < 0.35:
                    clips.append({"scene_id": source.get("scene_id", ""), "shot_id": source["shot_id"]})
                elif kind < 0.65:
                    covered = [episode_cycle.shot_uid(rng.choice(shots)) for _ in range(rng.randint(0, 4))]
                    clips.append({"scene_id": rng.choice(["", source.get("scene_id", "")]),
                                  "shot_uids": [str(uid) if rng.random() < 0.3 else uid for uid in covered]})
                elif kind < 0.9:
                    clips.append({"shot_id": rng.choice([source["shot_id"], str(source["shot_id"]), None])})
                else:
                    clips.append(rng.choice([None, "not a clip", {"shot_uid": rng.randint(1, 400000), "scene_id": "E1S01"}]))
            self.assert_same(shots, clips)

    def test_a_clip_whose_numbers_cannot_be_read_fails_where_it_always_did(self):
        # 「²」算数字却转不成整数：逐镜扫到它才报错，排在它前面的片段照样找得到。
        clips = [{"scene_id": "E1S01", "shot_id": 1}, {"scene_id": "E1S01", "shot_uids": ["²"]}]
        found, missing = {"scene_id": "E1S01", "shot_id": 1}, {"scene_id": "E1S01", "shot_id": 2}
        find = clip_finder(clips)
        self.assertIs(find(found), clips[0])
        self.assertIs(clip_for(found, clips), clips[0])
        with self.assertRaises(ValueError):
            clip_for(missing, clips)
        with self.assertRaises(ValueError):
            find(missing)


class HandedOverClipTests(unittest.TestCase):
    """The shot workspace hands ``shot_assets`` the clip it already found; the list must not change."""

    def test_the_asset_list_is_the_same_with_the_clip_handed_over(self):
        task = {"assets": {
            "4": [
                {"scene_id": "E1S01", "shot_id": 1, "characters": ["林夏", "周教授"], "props": ["录音笔"], "asset_stale": False},
                {"scene_id": "E1S01", "shot_id": 2, "characters": ["林夏"]},
                {"scene_id": "E1S02", "shot_id": 1, "characters": ["周教授"]},
            ],
            "5": [
                {"scene_id": "E1S01", "shot_id": 1, "shot_uids": [100101, 100102], "stale": True,
                 "mention_kinds": {"林夏": "actor"}, "reference_numbers": {"林夏": 1}},
            ],
        }}
        find = clip_finder(task["assets"]["5"])
        for shot in task["assets"]["4"]:
            self.assertEqual(
                asset_dependents.shot_assets(task, shot, clip=find(shot) or {}),
                asset_dependents.shot_assets(task, shot),
            )


if __name__ == "__main__":
    unittest.main()
