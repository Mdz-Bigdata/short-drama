# -*- coding: utf-8 -*-
"""Set pieces against people and lenses: nobody is marked inside furniture, a piece that hides
the subject is reported and repaired by finding a lens, and props take their real size.

No model, no network. The reference scene is the two-hander of ``test_spatial_stage``.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan, model_kit, repair, validation
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import CameraKey, ShotTimeline, StageLandmark, StagePlan
from app.core.spatial_stage.operations import apply_operations
from app.core.spatial_stage.planner import _prop_size, refresh
from app.core.spatial_stage.projection import CameraView
from tests.test_spatial_stage import _brief

CODE = "spatial_set_clearance"


def _box(position, size, *, yaw=0.0, elevation=0.0, parts=()):
    return SimpleNamespace(position=list(position), size=list(size), yaw_deg=yaw, elevation_m=elevation, parts=list(parts))


def _with(plan: StagePlan, *pieces: StageLandmark) -> StagePlan:
    return refresh(plan.model_copy(update={"landmarks": [*plan.landmarks, *pieces]}))


def _wall() -> StageLandmark:
    # A partition between the pair, across both over-the-shoulder sight lines.
    return StageLandmark(id="wall-01", name="隔墙", kind="architecture", position=[0.3, 0.2], size=[0.2, 1.2, 2.6])


def _check(plan: StagePlan):
    return next(check for check in plan.checks if check.code == CODE)


def _in_frame(plan: StagePlan, shot_id: int, piece: StageLandmark) -> tuple[float, float]:
    """Where the middle of ``piece`` lands in the shot's frame: ±1 is the edge of the picture."""
    x, y, depth = CameraView.of(plan.camera(plan.shot(shot_id).camera_id)).project(
        (piece.position[0], piece.elevation_m + piece.size[2] / 2, piece.position[1]),
    )
    assert depth > 0, f"{piece.name} is behind the lens"
    return x, y


def _inside(plan: StagePlan) -> list[tuple[str, str]]:
    return [
        (actor.name, piece.name)
        for actor in plan.actors
        for piece in plan.landmarks
        if piece.elevation_m < geo.LOW_PIECE_M and geo.inside_piece(actor.position, piece)
    ]


class FootprintTests(unittest.TestCase):
    def test_inside_is_the_footprint_not_the_distance_to_the_centre(self):
        bed = _box([0.0, 0.0], [2.0, 1.6, 0.5])
        self.assertTrue(geo.inside_piece([0.9, 0.7], bed))
        self.assertFalse(geo.inside_piece([1.1, 0.0], bed))
        self.assertTrue(geo.inside_piece([1.1, 0.0], bed, 0.3))
        self.assertFalse(geo.inside_piece([1.4, 0.0], bed, 0.3))

    def test_the_footprint_turns_with_the_piece(self):
        screen = _box([0.0, 0.0], [3.0, 0.2, 1.8], yaw=90.0)
        self.assertTrue(geo.inside_piece([0.0, 1.2], screen))
        self.assertFalse(geo.inside_piece([1.2, 0.0], screen))

    def test_a_tall_piece_hides_what_is_behind_it_and_a_low_one_does_not(self):
        eye, face = (0.0, 1.6, -3.0), (0.0, 1.5, 3.0)
        self.assertTrue(geo.piece_blocks_sight(eye, face, _box([0.0, 0.0], [2.0, 0.2, 2.4])))
        self.assertFalse(geo.piece_blocks_sight(eye, face, _box([0.0, 0.0], [2.0, 0.2, 1.0])))
        self.assertFalse(geo.piece_blocks_sight(eye, face, _box([4.0, 0.0], [2.0, 0.2, 2.4])))

    def test_a_cup_on_a_table_hides_nobody(self):
        eye, chest = (0.0, 0.8, -2.0), (0.0, 0.8, 2.0)
        self.assertFalse(geo.piece_blocks_sight(eye, chest, _box([0.0, 0.0], [0.1, 0.1, 0.1], elevation=0.75)))
        # A cabinet standing on a platform is still in the way.
        self.assertTrue(geo.piece_blocks_sight(eye, chest, _box([0.0, 0.0], [1.2, 0.6, 0.2], elevation=0.75)))

    def test_a_lens_inside_a_box_is_held_by_it(self):
        cabinet = _box([0.0, 0.0], [1.0, 0.6, 1.8])
        self.assertTrue(geo.piece_holds_point((0.2, 1.5, 0.1), cabinet))
        self.assertFalse(geo.piece_holds_point((0.2, 2.0, 0.1), cabinet))
        self.assertFalse(geo.piece_holds_point((0.8, 1.5, 0.1), cabinet))


class SetClearanceCheckTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_a_plan_from_the_planner_is_clear(self):
        check = _check(self.plan)
        self.assertTrue(check.passed)
        self.assertEqual(check.severity, "warning")

    def test_a_wall_across_the_sight_line_is_named_with_its_shots(self):
        blocked = _with(self.plan, _wall())
        check = _check(blocked)
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [2, 3])
        self.assertEqual(check.detail, "第2镜沈砚被布景「隔墙」挡住；第3镜黄琰被布景「隔墙」挡住，请换机位或挪开布景。")
        # A warning: the plan still passes, so scenes saved before the check stay usable.
        self.assertTrue(validation.passed(blocked.checks))

    def test_a_lens_inside_a_piece_is_reported(self):
        x, _, z = self.plan.camera(self.plan.shot(2).camera_id).position
        cabinet = StageLandmark(id="cab-01", name="立柜", kind="furniture", position=[x, z], size=[1.0, 1.0, 2.2])
        check = _check(_with(self.plan, cabinet))
        self.assertFalse(check.passed)
        self.assertIn("第2镜机位在「立柜」里面", check.detail)

    def test_a_doorway_is_open_where_the_door_is(self):
        kit, parts, overall = model_kit.build_kit("wall-door")
        door = dict(id="door-01", name="门墙", kind="architecture", position=[0.0, 2.5], size=list(overall), kit=kit.id)
        camera = self.plan.camera(self.plan.shot(1).camera_id)

        def hidden(piece: StageLandmark) -> set[str]:
            plan = self.plan.model_copy(update={"landmarks": [*self.plan.landmarks, piece]})
            return {name for name, _ in validation.set_obstructions(plan, plan.shot(1), camera)}

        self.assertEqual(hidden(StageLandmark(**door, parts=parts)), {"沈砚", "黄琰"})
        # The same wall with no opening hides the man standing in the middle too.
        self.assertEqual(hidden(StageLandmark(**door)), {"沈砚", "黄琰", "内侍"})


class SetClearanceRepairTests(unittest.TestCase):
    def setUp(self):
        self.blocked = _with(build_plan(_brief()), _wall())

    def test_the_repair_finds_each_shot_a_lens_that_sees_past_the_piece(self):
        proposal = next(item for item in repair.propose(self.blocked) if item.code == CODE)
        self.assertEqual(proposal.label, "绕开布景")
        self.assertTrue(proposal.automatic)
        self.assertEqual(proposal.operations, [{"op": "best_camera", "shot_id": 2}, {"op": "best_camera", "shot_id": 3}])
        fixed = apply_operations(self.blocked, proposal.operations, solve=False)
        self.assertEqual(repair.failing(fixed.checks), [])
        # Nobody was moved to make room: only the lenses.
        self.assertEqual([actor.position for actor in fixed.actors], [actor.position for actor in self.blocked.actors])
        self.assertEqual(fixed.landmarks, self.blocked.landmarks)

    def test_a_keyed_camera_is_left_to_a_person(self):
        camera = self.blocked.camera(self.blocked.shot(2).camera_id)
        keys = [CameraKey(time=time, position=camera.position, target=camera.target) for time in (0, 4)]
        timelines = {**self.blocked.timelines, "2": ShotTimeline(duration_s=5, camera=keys)}
        keyed = refresh(self.blocked.model_copy(update={"timelines": timelines}))
        proposal = next(item for item in repair.propose(keyed) if item.code == CODE)
        self.assertEqual(proposal.operations, [{"op": "best_camera", "shot_id": 3}])
        self.assertIn("第2镜", proposal.manual)
        self.assertIn("请手动移动机位，或挪开挡住的布景", proposal.manual)

    def test_the_check_and_its_repair_say_what_the_wording_table_says(self):
        load = prompt_data.load
        reworded = {
            **load("stage_brief"),
            "shot_named": "镜{shot}",
            "set_hides_subject": "「{piece}」遮住{name}",
            "set_clearance_failed": "{findings}。",
            "set_clearance_repair": "给{shots}另找机位。",
        }
        with patch.object(prompt_data, "load", side_effect=lambda name: reworded if name == "stage_brief" else load(name)):
            check = _check(refresh(self.blocked))
            proposal = next(item for item in repair.propose(self.blocked) if item.code == CODE)
        self.assertEqual(check.detail, "镜2「隔墙」遮住沈砚；镜3「隔墙」遮住黄琰。")
        self.assertEqual(proposal.detail, "给镜2、镜3另找机位。")


def _bedroom() -> SceneBrief:
    cast = ["沈砚", "黄琰", "林晚", "顾城", "老周", "阿福", "小翠"]
    return SceneBrief(
        scene_id="E2S01",
        location="卧房 / 夜 / 内景",
        text="沈砚与黄琰在床榻边对峙，众人围在两侧。",
        characters=cast,
        props=["录音笔", "玉佩", "书案"],
        shots=[
            ShotSpec(1, cast, "", "全景", "平视", "固定", "众人围在床榻边"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
            ShotSpec(3, ["黄琰"], "黄琰", "近景", "过肩", "缓推", "黄琰抬头"),
        ],
    )


class PlannerSetTests(unittest.TestCase):
    def test_nobody_is_marked_inside_a_set_piece(self):
        plan = build_plan(_bedroom())
        self.assertEqual(repair.failing(plan.checks), [])
        self.assertEqual(_inside(plan), [])
        # The bed is still in the room, stepped clear of the marks rather than dropped.
        self.assertIn("床榻", [piece.name for piece in plan.landmarks])

    def test_a_hand_prop_is_its_real_size_and_rests_on_the_table(self):
        plan = build_plan(_bedroom())
        pieces = {piece.name: piece for piece in plan.landmarks}
        desk, recorder, pendant = pieces["书案"], pieces["录音笔"], pieces["玉佩"]
        self.assertEqual(recorder.size, [0.14, 0.03, 0.03])
        self.assertEqual(pendant.size, [0.06, 0.05, 0.03])
        top = desk.elevation_m + desk.size[2]
        for prop in (recorder, pendant):
            self.assertAlmostEqual(prop.elevation_m, top)
            self.assertTrue(geo.inside_piece(prop.position, desk))
        self.assertNotEqual(recorder.position, pendant.position)

    def test_a_hand_prop_with_no_table_stays_on_a_floor_mark_at_its_real_size(self):
        plan = build_plan(_brief(text="沈砚与黄琰在院中对峙。", location="院子 / 日 / 外景", props=["录音笔"]))
        recorder = next(piece for piece in plan.landmarks if piece.name == "录音笔")
        self.assertEqual(recorder.size, [0.14, 0.03, 0.03])
        self.assertEqual(recorder.elevation_m, 0.0)

    def test_an_insert_of_a_prop_on_a_table_is_shot_at_the_table_top(self):
        for angle in ("", "平视", "仰拍", "贴地", "顶拍"):
            with self.subTest(angle=angle):
                plan = build_plan(_brief(props=["书案", "茶杯"], shots=[
                    ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "两人对坐"),
                    ShotSpec(2, [], "", "特写", angle, "固定", "茶杯特写"),
                ]))
                pieces = {piece.name: piece for piece in plan.landmarks}
                desk, cup = pieces["书案"], pieces["茶杯"]
                top = desk.elevation_m + desk.size[2]
                self.assertAlmostEqual(cup.elevation_m, top)
                x, y = _in_frame(plan, 2, cup)
                self.assertLess(abs(x), 0.3)
                self.assertLess(abs(y), 0.3)
                camera = plan.camera("cam-02")
                # The lens is over the table top, never under it looking up through the wood.
                self.assertGreater(camera.position[1], top)
                self.assertIn("茶杯位于画面中央", plan.shot(2).text.composition)
                self.assertTrue(_check(plan).passed, _check(plan).detail)

    def test_an_insert_of_a_piece_on_the_floor_is_shot_where_it_was(self):
        plan = build_plan(_brief())
        camera = plan.camera("cam-05")
        brazier = next(piece for piece in plan.landmarks if piece.name == "炭盆")
        self.assertEqual(camera.target, [brazier.position[0], round(brazier.size[2] * 0.8, 3), brazier.position[1]])

    def test_what_lies_on_a_table_crosses_the_stage_with_it(self):
        # A lone character plays screen left of the first piece, so the table is moved to their right.
        plan = build_plan(SceneBrief(
            scene_id="E4S01", location="客厅 / 夜 / 内景", text="林夏走进客厅。", characters=["林夏"],
            props=["茶几", "手机", "钥匙"], shots=[ShotSpec(1, ["林夏"], "", "全景", "平视", "固定", "林夏走进客厅")],
        ))
        pieces = {piece.name: piece for piece in plan.landmarks}
        table = pieces["茶几"]
        self.assertGreater(table.position[0], plan.actor("林夏").position[0])
        for name in ("手机", "钥匙"):
            self.assertTrue(geo.inside_piece(pieces[name].position, table), name)
            self.assertAlmostEqual(pieces[name].elevation_m, table.elevation_m + table.size[2])

    def test_an_insert_follows_a_piece_that_made_way_for_another_lens(self):
        cast = ["王妃", "林晚", "沈砚", "黄琰"]
        brief = SceneBrief(
            scene_id="E5S01", location="大殿", text="沈砚伏案写信，黄琰站在屏风后。", characters=cast, props=["信"],
            shots=[
                ShotSpec(1, [], "", "特写", "俯拍", "", "信特写"),
                ShotSpec(2, ["王妃", "沈砚", "林晚"], "王妃", "特写", "仰拍", "横移", "王妃坐下"),
                ShotSpec(3, ["林晚", "黄琰", "沈砚"], "林晚", "近景", "", "横移", "林晚后退两步"),
            ],
            aspect_ratio="16:9",
        )
        plan = build_plan(brief)
        pieces = {piece.name: piece for piece in plan.landmarks}
        desk, letter = pieces["书案"], pieces["信"]
        # The desk stepped upstage out of a lens's way, and took the letter with it.
        self.assertLess(desk.position[1], -1.0)
        self.assertTrue(geo.inside_piece(letter.position, desk))
        camera = plan.camera("cam-01")
        self.assertEqual([camera.target[0], camera.target[2]], letter.position)
        x, y = _in_frame(plan, 1, letter)
        self.assertLess(abs(x), 0.3)
        self.assertLess(abs(y), 0.3)
        self.assertTrue(_check(plan).passed, _check(plan).detail)

    def test_sizes_come_from_the_scale_table_then_the_kind_of_thing_then_the_stand_in(self):
        self.assertEqual(_prop_size("智能手机"), (0.155, 0.075, 0.03))
        self.assertEqual(_prop_size("马"), (2.5, 0.6, 1.6))
        self.assertEqual(_prop_size("玉佩（裂了一道）"), (0.06, 0.05, 0.03))
        self.assertEqual(_prop_size("黄绫"), (0.5, 0.5, 0.5))
        # Nothing that would not fit on a stage is built at full size.
        self.assertEqual(_prop_size("航空母舰"), (0.5, 0.5, 0.5))

    def test_a_character_that_ends_other_things_names_is_only_that_thing_on_its_own(self):
        stand_in = (0.5, 0.5, 0.5)
        # 坛 is a wine jar, 牌 a token, 信 a letter; the things below only end in the same character.
        for name in ("祭坛", "花坛", "招牌", "广告牌", "集装箱", "保险箱", "氧气瓶", "煤气罐", "降落伞", "面包", "秘书", "脚印", "短信", "火药", "摇篮", "警笛"):
            with self.subTest(name=name):
                self.assertEqual(_prop_size(name), stand_in)
        for name, size in {
            "坛": (0.14, 0.14, 0.24), "牌": (0.06, 0.05, 0.03), "信": (0.26, 0.18, 0.03), "一封信": (0.26, 0.18, 0.03),
            "箱": (0.45, 0.25, 0.3), "刀": (1.0, 0.05, 0.03), "长刀": (1.0, 0.05, 0.03), "玉簪": (0.06, 0.05, 0.03),
            # 酒坛、令牌、木箱、茶杯收进了尺寸补充表(everyday_items.json)：按表里的真实尺寸，白模和提示词同一个数。
            "酒坛": (0.35, 0.35, 0.45), "令牌": (0.1, 0.06, 0.03), "木箱": (0.8, 0.5, 0.5), "茶杯": (0.08, 0.08, 0.06),
            # A kitchen knife is not a sabre, and a suitcase stands on the floor.
            "菜刀": (0.3, 0.1, 0.03), "手术刀": (0.15, 0.03, 0.03), "行李箱": (0.5, 0.3, 0.7),
        }.items():
            with self.subTest(name=name):
                self.assertEqual(_prop_size(name), size)

    def test_two_numbers_in_the_scale_table_are_length_and_girth_unless_the_thing_is_flat(self):
        self.assertEqual(_prop_size("水杯"), (0.15, 0.08, 0.08))
        self.assertEqual(_prop_size("葫芦"), (0.3, 0.15, 0.15))
        self.assertEqual(_prop_size("盾牌"), (0.8, 0.5, 0.03))
        self.assertEqual(_prop_size("A4纸"), (0.297, 0.21, 0.03))

    def test_a_big_prop_is_parked_upstage_not_between_the_pair(self):
        plan = build_plan(_brief(props=["马"]))
        horse = next(piece for piece in plan.landmarks if piece.name == "马")
        self.assertEqual(horse.size, [2.5, 0.6, 1.6])
        self.assertLess(horse.position[1], -1.0)
        self.assertEqual(repair.failing(plan.checks), [])

    def test_pieces_placed_this_run_make_way_for_the_lenses(self):
        shots = [
            ShotSpec(1, ["士兵们"], "士兵们", "特写", "平视", "固定", "某人转身"),
            ShotSpec(2, [], "", "近景", "平视", "缓推", "某人抬头"),
            ShotSpec(3, ["士兵们"], "士兵们", "特写", "平视", "升", "某人坐下"),
            ShotSpec(4, [], "", "中近景", "仰拍", "升", "某人转身"),
            ShotSpec(5, ["士兵们"], "士兵们", "中近景", "仰拍", "缓推", "某人走近"),
            ShotSpec(6, ["士兵们"], "士兵们", "全景", "仰拍", "缓推", "某人抬头"),
            ShotSpec(7, [], "", "中景", "过肩", "缓推", "某人坐下"),
        ]
        plan = build_plan(SceneBrief(
            scene_id="E3S01", location="营地 / 日 / 外景", text="沈砚坐在桌前，黄琰拥抱他。",
            characters=["士兵们"], props=["马", "中型轿车"], shots=shots, aspect_ratio="16:9",
        ))
        self.assertTrue(_check(plan).passed, _check(plan).detail)
        self.assertEqual(_inside(plan), [])


class SavedPlanTests(unittest.TestCase):
    def test_a_saved_plan_loads_as_it_was(self):
        plan = build_plan(_bedroom())
        self.assertEqual(StagePlan.model_validate(plan.model_dump()), plan)

    def test_replanning_over_a_saved_scene_keeps_its_stand_in_boxes(self):
        saved = build_plan(_bedroom())
        old = [
            piece.model_copy(update={"size": [0.5, 0.5, 0.5], "position": [0.0, 0.0], "elevation_m": 0.0})
            if piece.name == "录音笔" else piece
            for piece in saved.landmarks
        ]
        saved = refresh(saved.model_copy(update={"landmarks": old}))
        again = build_plan(_bedroom(), blocking_from=saved)
        self.assertEqual(
            [(piece.name, piece.position, piece.size, piece.elevation_m) for piece in again.landmarks],
            [(piece.name, piece.position, piece.size, piece.elevation_m) for piece in saved.landmarks],
        )


if __name__ == "__main__":
    unittest.main()
