"""一个资产被哪些镜头用着；改了它，用到它的镜头、场景板和片段跟着过期。"""

import unittest
from copy import deepcopy

from app.core import asset_dependents


def _task() -> dict:
    return {
        "task_id": "t1", "owner_user_id": "u1", "config": {"title_suggestion": "暗室回声"},
        "assets": {
            "4": [
                {
                    "shot_id": 1, "scene_id": "E1S01", "characters": ["林夏", "周教授"], "props": ["录音笔"],
                    "effects": ["本格无额外特效"], "scene": "地下实验室",
                    "asset_bindings": [
                        {"kind": "actor", "name": "林夏", "element_id": "el-lin", "element_version": 3},
                        {"kind": "scene", "name": "地下实验室", "element_id": "el-lab", "element_version": 1},
                    ],
                },
                {"shot_id": 2, "scene_id": "E1S01", "characters": ["周教授"], "props": [], "scene": "地下实验室"},
                # 第二场的镜号又从 1 起：只看镜号会把它和第一场第 1 镜混成一镜。
                {"shot_id": 1, "scene_id": "E1S02", "characters": ["老周"], "props": [], "scene": "走廊"},
            ],
            "5": [
                {
                    "shot_id": 1, "scene_id": "E1S01", "shot_uid": 100101, "video_url": "/media/a.mp4",
                    "reference_numbers": {"林夏": 1, "地下实验室": 2, "录音笔": 3}, "mention_kinds": {"林夏": "actor", "地下实验室": "scene", "录音笔": "prop"},
                    "asset_versions": {"el-lin": 3, "el-lab": 1},
                },
                {"shot_id": 2, "scene_id": "E1S01", "shot_uid": 100102, "video_url": "/media/b.mp4"},
                {"shot_id": 1, "scene_id": "E1S02", "shot_uid": 100201, "video_url": "/media/c.mp4"},
            ],
            "4_scene_boards": {
                "E1S01": {"status": "done", "grid_url": "/media/g1.png"},
                "E1S02": {"status": "done", "grid_url": "/media/g2.png"},
            },
        },
    }


class ShotAssetsTests(unittest.TestCase):
    def test_bindings_shot_fields_and_the_clip_merge_into_one_row_per_asset(self):
        task = _task()
        rows = asset_dependents.shot_assets(task, task["assets"]["4"][0])
        by_key = {(row["kind"], row["name"]): row for row in rows}

        self.assertEqual(set(by_key), {("actor", "林夏"), ("actor", "周教授"), ("prop", "录音笔"), ("scene", "地下实验室")})
        lin = by_key[("actor", "林夏")]
        self.assertEqual((lin["element_id"], lin["element_version"], lin["image_number"]), ("el-lin", 3, 1))
        self.assertTrue(lin["in_storyboard"] and lin["in_video"])
        # 分镜表点了名、但视频请求里没有他的参考图。
        zhou = by_key[("actor", "周教授")]
        self.assertEqual((zhou["element_id"], zhou["image_number"], zhou["in_video"]), ("", None, False))
        self.assertTrue(zhou["in_storyboard"])
        self.assertEqual(by_key[("prop", "录音笔")]["image_number"], 3)
        self.assertFalse(any(row["stale"] for row in rows))

    def test_a_stale_clip_or_a_stale_board_makes_the_rows_stale(self):
        task = _task()
        task["assets"]["5"][0]["stale"] = True
        self.assertTrue(all(row["stale"] for row in asset_dependents.shot_assets(task, task["assets"]["4"][0])))
        task = _task()
        task["assets"]["4_scene_boards"]["E1S01"].update(asset_stale=True, asset_stale_grid_url="/media/g1.png")
        self.assertTrue(all(row["stale"] for row in asset_dependents.shot_assets(task, task["assets"]["4"][1])))
        # 标记之后已经重画过(九宫格换了)：不再算过期。
        task["assets"]["4_scene_boards"]["E1S01"]["grid_url"] = "/media/g1-new.png"
        self.assertFalse(any(row["stale"] for row in asset_dependents.shot_assets(task, task["assets"]["4"][1])))

    def test_placeholders_and_a_scene_column_that_is_prose_are_not_assets(self):
        task = _task()
        shot = {"shot_id": 5, "scene_id": "E1S01", "characters": ["空镜（无人物）"], "props": ["本格无额外道具"], "scene": "雨" * 80}
        self.assertEqual(asset_dependents.shot_assets(task, shot), [])


class ShotsUsingTests(unittest.TestCase):
    def test_a_bound_element_id_finds_its_shot(self):
        task = _task()
        shots = asset_dependents.shots_using(task, element_id="el-lin", kind="actor", names=[])
        self.assertEqual([(shot["scene_id"], shot["shot_id"]) for shot in shots], [("E1S01", 1)])

    def test_names_and_aliases_find_shots_without_bindings(self):
        task = _task()
        shots = asset_dependents.shots_using(task, element_id="el-zhou", kind="actor", names=["周教授", "老周"])
        self.assertEqual([(shot["scene_id"], shot["shot_id"]) for shot in shots], [("E1S01", 1), ("E1S01", 2), ("E1S02", 1)])
        # 名字对上但类型不对的不算；规范化后的名字(多了空格)照样对上。
        self.assertEqual(asset_dependents.shots_using(task, kind="prop", names=["周教授"]), [])
        self.assertEqual(len(asset_dependents.shots_using(task, kind="prop", names=[" 录音 笔 "])), 1)

    def test_a_same_name_binding_to_another_element_is_not_this_asset(self):
        task = _task()
        shots = asset_dependents.shots_using(task, element_id="el-lin-other", kind="actor", names=["林夏"])
        self.assertEqual(shots, [])

    def test_a_look_is_found_through_its_variant_binding(self):
        task = _task()
        task["assets"]["4"][1]["asset_bindings"] = [
            {"kind": "actor", "name": "周教授", "element_id": "el-zhou", "element_version": 2, "variant_element_id": "el-zhou-wet", "variant_element_version": 1},
        ]
        shots = asset_dependents.shots_using(task, element_id="el-zhou-wet", kind="actor", names=["周教授·落水"])
        self.assertEqual([shot["shot_id"] for shot in shots], [2])


class MarkDependentsTests(unittest.TestCase):
    def test_only_clips_covering_the_shots_are_marked_across_scenes(self):
        task = _task()
        counts = asset_dependents.mark_dependents_stale(
            task, element_id="el-lin", kind="actor", names=["林夏"], reason=asset_dependents.STALE_REASON.format(name="林夏"),
        )
        self.assertEqual(counts, {"shots_marked": 1, "clips_marked": 1, "boards_marked": 1})
        clips = task["assets"]["5"]
        self.assertTrue(clips[0]["stale"])
        self.assertIn("林夏", clips[0]["stale_reason"])
        # 第二场的第 1 镜和第一场的第 1 镜同号，但不是同一镜：它的片段不动。
        self.assertNotIn("stale", clips[1])
        self.assertNotIn("stale", clips[2])
        boards = task["assets"]["4_scene_boards"]
        self.assertTrue(boards["E1S01"]["asset_stale"])
        self.assertIn("重画本场分镜", boards["E1S01"]["asset_stale_reason"])
        self.assertNotIn("asset_stale", boards["E1S02"])
        self.assertTrue(task["assets"]["4"][0]["asset_stale"])
        self.assertNotIn("asset_stale", task["assets"]["4"][2])

    def test_a_legacy_clip_without_a_scene_is_matched_by_its_shot_number(self):
        task = _task()
        task["assets"]["5"] = [{"shot_id": 2, "video_url": "/media/old.mp4"}]
        counts = asset_dependents.mark_dependents_stale(task, kind="actor", names=["周教授"], reason="改了")
        self.assertEqual(counts["clips_marked"], 1)
        self.assertTrue(task["assets"]["5"][0]["stale"])

    def test_marking_twice_counts_nothing_the_second_time(self):
        task = _task()
        reason = asset_dependents.STALE_REASON.format(name="周教授")
        first = asset_dependents.mark_dependents_stale(task, kind="actor", names=["周教授", "老周"], reason=reason)
        snapshot = deepcopy(task)
        second = asset_dependents.mark_dependents_stale(task, kind="actor", names=["周教授", "老周"], reason=reason)
        self.assertEqual(first, {"shots_marked": 3, "clips_marked": 3, "boards_marked": 2})
        self.assertEqual(second, {"shots_marked": 0, "clips_marked": 0, "boards_marked": 0})
        self.assertEqual(task, snapshot)

    def test_nothing_uses_an_unknown_asset(self):
        task = _task()
        snapshot = deepcopy(task)
        counts = asset_dependents.mark_dependents_stale(task, element_id="el-x", kind="prop", names=["铁链"], reason="改了")
        self.assertEqual(counts, {"shots_marked": 0, "clips_marked": 0, "boards_marked": 0})
        self.assertEqual(task, snapshot)


class VersionTests(unittest.TestCase):
    def test_bindings_keep_one_row_per_asset_with_its_identity(self):
        references = [
            {"kind": "actor", "name": "林夏", "image_url": "data:body", "id": "el-lin", "version": 3},
            {"kind": "actor", "name": "林夏", "image_url": "data:face", "view": "face", "id": "el-lin", "version": 3},
            {"kind": "scene", "name": "地下实验室", "image_url": "https://cdn/lab.png"},
        ]
        self.assertEqual(asset_dependents.binding_entries(references), [
            {"kind": "actor", "name": "林夏", "element_id": "el-lin", "element_version": 3},
            {"kind": "scene", "name": "地下实验室", "element_id": "", "element_version": 0},
        ])

    def test_request_versions_and_matching(self):
        req = {"library_references": [
            {"kind": "actor", "name": "林夏", "id": "el-lin", "version": 3, "variant_element_id": "el-look", "variant_version": 2},
            {"kind": "scene", "name": "走廊"},
        ]}
        current = asset_dependents.request_asset_versions(req)
        self.assertEqual(current, {"el-lin": 3, "el-look": 2})
        self.assertEqual(asset_dependents.request_asset_versions({"asset_versions": {"el-a": 1}, "library_references": req["library_references"]}), {"el-a": 1})
        self.assertTrue(asset_dependents.versions_match({"asset_versions": {"el-lin": 3, "el-look": 2}}, current))
        self.assertFalse(asset_dependents.versions_match({"asset_versions": {"el-lin": 2, "el-look": 2}}, current))
        # 没记版本的旧片(功能上线前做的)算一样，免得下次第 5 阶段把旧片整批重做、白花钱；
        # 之后资产改了，资产改动会把它标成过期，照样重做。
        self.assertTrue(asset_dependents.versions_match({}, current))
        self.assertTrue(asset_dependents.versions_match({}, {}))


if __name__ == "__main__":
    unittest.main()
