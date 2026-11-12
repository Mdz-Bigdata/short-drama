# -*- coding: utf-8 -*-
"""Scenes and shots named the way a person says them: ids, ordinals, scene names, cast, and the ambiguities."""

import unittest

from app.core import stage_locator as locator


def _task():
    return {"assets": {
        "2_breakdown": {"scenes": [
            {"scene_id": "E1S01", "content": "医院走廊，林夏追上周明。", "characters": ["林夏", "周明"]},
            {"scene_id": "E1S02", "content": "办公室里苏雨推门。", "characters": ["林夏", "苏雨"]},
            {"scene_id": "E2S01", "content": "天台。", "characters": ["周明"]},
        ]},
        "4": [
            {"scene_id": "E1S01", "scene": "E1S01 - 医院走廊", "shot_id": 1, "characters": ["林夏", "周明"], "desc": "林夏追上周明" * 20},
            {"scene_id": "E1S02", "scene": "林夏的办公室", "shot_id": 1, "characters": ["林夏", "苏雨"], "desc": "两人对视"},
            {"scene_id": "E1S02", "scene": "林夏的办公室", "shot_id": 2, "characters": ["苏雨"], "desc": "苏雨推门"},
            {"scene_id": "E2S01", "scene": "E2S01：天台", "shot_id": 1, "characters": ["周明"], "desc": "周明望远"},
        ],
    }}


class NumberTest(unittest.TestCase):
    def test_chinese_numerals_and_digits(self):
        for token, value in (("3", 3), ("一", 1), ("十", 10), ("十二", 12), ("二十", 20), ("二十三", 23), ("两", 2), ("一百", 100)):
            self.assertEqual(locator.parse_number(token), value, token)
        self.assertIsNone(locator.parse_number("甲"))
        self.assertIsNone(locator.parse_number(""))


class ScenesTest(unittest.TestCase):
    def test_scenes_carry_episode_number_name_cast_and_shots(self):
        scenes = locator.scenes_of(_task())
        self.assertEqual([scene["scene_id"] for scene in scenes], ["E1S01", "E1S02", "E2S01"])
        first, second, third = scenes
        self.assertEqual((first["episode"], first["number"], first["name"]), (1, 1, "医院走廊"))
        self.assertEqual(second["name"], "林夏的办公室")
        self.assertEqual(third["name"], "天台")
        self.assertEqual(second["characters"], ["林夏", "苏雨"])
        self.assertEqual([shot["shot_id"] for shot in second["shots"]], [1, 2])
        self.assertEqual(second["shots"][1]["subjects"], ["苏雨"])
        self.assertLessEqual(len(first["shots"][0]["action"]), locator.ACTION_CHARS)

    def test_a_scene_known_only_from_shots_is_listed_too(self):
        task = _task()
        task["assets"]["4"].append({"scene_id": "E2S02", "scene": "E2S02 停车场", "shot_id": 1, "characters": ["林夏"], "desc": ""})
        scenes = locator.scenes_of(task)
        self.assertEqual(scenes[-1]["scene_id"], "E2S02")
        self.assertEqual(scenes[-1]["name"], "停车场")
        self.assertEqual(scenes[-1]["characters"], ["林夏"])

    def test_scene_label(self):
        self.assertEqual(locator.scene_label(_task(), "E1S02"), "E1S02 林夏的办公室")
        self.assertEqual(locator.scene_label(_task(), "E9S09"), "E9S09")

    def test_the_breakdowns_own_label_names_a_scene_before_any_shots_exist(self):
        # 分场表只写 label（renderer.scene_breakdown_entry 的键），还没到分镜阶段时也要能按场名找到。
        task = {"assets": {"2_breakdown": {"scenes": [
            {"scene_id": "E1S01", "label": "地下车库 / 夜", "content": "", "characters": ["赵总"]},
            {"scene_id": "E1S02", "label": "办公室 / 日", "content": "", "characters": ["林夏"]},
        ]}}}
        self.assertEqual([scene["name"] for scene in locator.scenes_of(task)], ["地下车库 / 夜", "办公室 / 日"])
        self.assertEqual(locator.resolve_scene_id(task, "地下车库那场"), "E1S01", "the place half of a 地点 / 时间 label matches on its own")
        self.assertEqual(locator.resolve_scene_id(task, "办公室"), "E1S02")
        self.assertEqual(locator.scene_label(task, "E1S02"), "E1S02 办公室 / 日")
        with self.assertRaisesRegex(LookupError, "地下车库"):
            locator.resolve_scene_id(task, "菜市场")


class ResolveSceneTest(unittest.TestCase):
    def test_ids_in_any_spelling(self):
        for text in ("E1S02", "e1s2", "E1 S02", "看看 E1S02 这一场"):
            self.assertEqual(locator.resolve_scene_id(_task(), text), "E1S02", text)
        self.assertEqual(locator.resolve_scene_id({"assets": {}}, "E3S4"), "E3S04", "a task without an outline still gets the canonical id")
        with self.assertRaisesRegex(LookupError, "E1S02 林夏的办公室"):
            locator.resolve_scene_id(_task(), "E1S07")

    def test_ordinals_need_an_episode_when_there_are_several(self):
        with self.assertRaisesRegex(LookupError, "哪一集"):
            locator.resolve_scene_id(_task(), "第2场")
        self.assertEqual(locator.resolve_scene_id(_task(), "第2场", default_episode=1), "E1S02")
        self.assertEqual(locator.resolve_scene_id(_task(), "第一集第二场"), "E1S02")
        self.assertEqual(locator.resolve_scene_id(_task(), "第二集 第一场"), "E2S01")
        self.assertEqual(locator.resolve_scene_id(_task(), "第1集第2场 优化一下", default_episode=2), "E1S02", "the text wins over the default")
        with self.assertRaisesRegex(LookupError, "第1集没有第5场"):
            locator.resolve_scene_id(_task(), "第五场", default_episode=1)

    def test_a_single_episode_needs_no_episode(self):
        task = _task()
        task["assets"]["2_breakdown"]["scenes"] = task["assets"]["2_breakdown"]["scenes"][:2]
        task["assets"]["4"] = task["assets"]["4"][:3]
        self.assertEqual(locator.resolve_scene_id(task, "第二场"), "E1S02")

    def test_scene_names_and_cast(self):
        self.assertEqual(locator.resolve_scene_id(_task(), "办公室"), "E1S02")
        self.assertEqual(locator.resolve_scene_id(_task(), "天台那场"), "E2S01")
        self.assertEqual(locator.resolve_scene_id(_task(), "苏雨"), "E1S02")
        self.assertEqual(locator.resolve_scene_id(_task(), "林夏"), "E1S02", "a unique scene-name substring wins before the cast")
        with self.assertRaisesRegex(LookupError, r"「周明」出现在 2 场里.*E1S01 医院走廊、E2S01 天台"):
            locator.resolve_scene_id(_task(), "周明")
        with self.assertRaisesRegex(LookupError, r"没找到「菜市场」.*（E1S01 医院走廊、E1S02 林夏的办公室、E2S01 天台）"):
            locator.resolve_scene_id(_task(), "菜市场")
        with self.assertRaises(LookupError):
            locator.resolve_scene_id(_task(), "")

    def test_the_candidate_list_is_capped(self):
        task = {"assets": {"2_breakdown": {"scenes": [{"scene_id": f"E1S{i:02d}", "content": "", "characters": []} for i in range(1, 12)]}}}
        with self.assertRaises(LookupError) as caught:
            locator.resolve_scene_id(task, "没有的")
        self.assertIn("E1S08", str(caught.exception))
        self.assertNotIn("E1S09", str(caught.exception))
        self.assertIn("…", str(caught.exception))


class ResolveShotTest(unittest.TestCase):
    def _storyboard(self):
        return [shot for shot in _task()["assets"]["4"] if shot["scene_id"] == "E1S02"]

    def _plan_shots(self):
        return [
            {"shot_id": 1, "subjects": ["沈砚", "黄琰"], "speaker": "黄琰", "action": "黄琰开口"},
            {"shot_id": 2, "subjects": ["沈砚", "黄琰"], "speaker": "沈砚", "action": "沈砚反驳"},
            {"shot_id": 3, "subjects": ["内侍"], "speaker": "", "action": "内侍退下"},
        ]

    def test_numbers_in_any_spelling(self):
        for text in ("第2镜", "第二镜", "2", "#2", " #2 ", "镜2"):
            self.assertEqual(locator.resolve_shot_id(self._storyboard(), text), 2, text)
        self.assertEqual(locator.resolve_shot_id([], "第7镜"), 7, "without shots the number is taken as given")
        with self.assertRaisesRegex(LookupError, "没有第9镜"):
            locator.resolve_shot_id(self._storyboard(), "第9镜")

    def test_a_name_that_is_in_exactly_one_shot(self):
        self.assertEqual(locator.resolve_shot_id(self._storyboard(), "林夏的那一镜"), 1)
        self.assertEqual(locator.resolve_shot_id(self._plan_shots(), "内侍的镜头"), 3)
        with self.assertRaisesRegex(LookupError, r"「苏雨」在 2 个镜头里.*第1镜 林夏、苏雨、第2镜 苏雨"):
            locator.resolve_shot_id(self._storyboard(), "苏雨的那一镜")

    def test_who_speaks_picks_the_shot_by_speaker(self):
        self.assertEqual(locator.resolve_shot_id(self._plan_shots(), "沈砚说话的那镜"), 2)
        self.assertEqual(locator.resolve_shot_id(self._plan_shots(), "黄琰说话的那一镜"), 1)
        with self.assertRaisesRegex(LookupError, "沈砚"):
            locator.resolve_shot_id(self._plan_shots(), "沈砚的那一镜")

    def test_unknown_names_list_the_shots(self):
        with self.assertRaisesRegex(LookupError, r"没找到「张三的那一镜」.*第1镜"):
            locator.resolve_shot_id(self._storyboard(), "张三的那一镜")
        with self.assertRaises(LookupError):
            locator.resolve_shot_id(self._storyboard(), "")


if __name__ == "__main__":
    unittest.main()
