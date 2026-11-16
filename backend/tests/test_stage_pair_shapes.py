# -*- coding: utf-8 -*-
"""How a pair and its company stand when the scene's words say more than "they talk".

No model, no network. Every shape keeps both principals on the one axis (first named screen left), so
only the distance and the two headings change: shoulder to shoulder, one a step behind the other
(following, being led, being guarded), back to back; and with company, a half circle or two rows.
The distances and trigger words are ``stage_planner.json``'s — the tests read them from there.
"""

import math
import unittest

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.planner import SceneBrief, build_plan

DATA = prompt_data.load("stage_planner")
RELATIONS = prompt_data.value("stage_brief", "pair_relations")
SHAPES = {shape["label"]: shape for shape in DATA["pair_shapes"]}
PAIR = ["沈砚", "柳烟"]


def _plan(text: str, cast=PAIR, **overrides):
    return build_plan(SceneBrief(scene_id="E1S01", location="长街 夜", text=text, characters=list(cast)), **overrides)


def _spot(actor) -> tuple[float, float]:
    return (actor.position[0], actor.position[1])


def _gap(first, second) -> float:
    return geo.distance(_spot(first), _spot(second))


def _offset(front, behind) -> tuple[float, float]:
    """How far ``behind`` stands back of ``front`` and to its side, measured along the heading of ``front``."""
    forward = geo.forward_of(front.yaw_deg)
    delta = geo.sub(_spot(behind), _spot(front))
    return -geo.dot(delta, forward), abs(geo.dot(delta, geo.right_of(forward)))


def _failed(plan) -> list[str]:
    return [check.code for check in plan.checks if not check.passed]


class TableTests(unittest.TestCase):
    def test_every_pair_shape_says_its_words_its_name_and_its_distances(self):
        for shape in DATA["pair_shapes"]:
            with self.subTest(label=shape.get("label")):
                self.assertTrue(shape["words"] and shape["label"])
                self.assertTrue(shape.get("relation") or shape["relation_key"] in RELATIONS)
                if "metres" in shape:
                    self.assertEqual(set(shape), {"words", "relation_key", "label", "metres"})
                else:
                    self.assertGreaterEqual(math.hypot(shape["back_m"], shape["side_m"]), 0.6, "two bodies fit")
                    self.assertIn(shape["subject"], {"front", "behind"})

    def test_nobody_is_asked_to_stand_inside_a_neighbour(self):
        # The planner pushes marks closer than 0.6 m apart; a table distance under that would not survive.
        self.assertGreaterEqual(DATA["side_by_side_metres"], 0.6)
        for shape in DATA["pair_shapes"]:
            self.assertGreaterEqual(shape.get("metres", 0.6), 0.6)
        for group in DATA["group_shapes"].values():
            self.assertGreaterEqual(group["spacing_m"], 0.6)
        self.assertEqual(set(DATA["group_shapes"]["ring"]["seated"]) - set(DATA["group_shapes"]["ring"]["words"]), set())


class PairShapeTests(unittest.TestCase):
    def test_shoulder_to_shoulder_is_its_own_distance_whatever_the_mood(self):
        for text in ("沈砚与柳烟并肩走在长街上。", "沈砚与柳烟并肩而立，与来人对峙。"):
            plan = _plan(text)
            left, right = plan.actor("沈砚"), plan.actor("柳烟")
            with self.subTest(text=text):
                self.assertAlmostEqual(_gap(left, right), DATA["side_by_side_metres"])
                self.assertEqual((left.yaw_deg, right.yaw_deg), (0.0, 0.0))
                self.assertTrue(plan.formation.startswith(RELATIONS["side_by_side"]))
                self.assertEqual(_failed(plan), [])

    def test_a_follower_stands_a_step_behind_and_to_the_side_going_the_same_way(self):
        shape = SHAPES["跟随"]
        for text, front in (
            ("沈砚走在前面，柳烟跟在沈砚身后。", "沈砚"),
            ("沈砚跟在柳烟身后，一言不发。", "柳烟"),
            ("她跟在沈砚身后。", "沈砚"),          # named after the word: the other one follows
        ):
            plan = _plan(text)
            behind = next(name for name in PAIR if name != front)
            leader, follower = plan.actor(front), plan.actor(behind)
            with self.subTest(text=text):
                self.assertAlmostEqual(leader.yaw_deg, follower.yaw_deg)
                back, side = _offset(leader, follower)
                self.assertAlmostEqual(back, shape["back_m"], places=2)
                self.assertAlmostEqual(side, shape["side_m"], places=2)
                self.assertGreater(geo.forward_of(leader.yaw_deg)[1], 0, "turned toward the camera side, not away")
                # Whoever leads, the first named keeps screen left and the axis stays between the two.
                self.assertEqual((plan.actor("沈砚").screen_side, plan.actor("柳烟").screen_side), ("left", "right"))
                self.assertEqual((plan.axis.from_name, plan.axis.to_name), ("沈砚", "柳烟"))
                self.assertEqual(plan.formation, f"{shape['relation']}·{shape['label']}·{front}在前，{behind}落后1.2米、偏侧0.5米")
                self.assertEqual(_failed(plan), [])

    def test_whoever_shows_the_way_is_in_front(self):
        plan = _plan("沈砚提灯引路，柳烟低头走着。")
        back, _side = _offset(plan.actor("沈砚"), plan.actor("柳烟"))
        self.assertAlmostEqual(back, SHAPES["引导"]["back_m"], places=2)
        self.assertIn(SHAPES["引导"]["label"], plan.formation)

    def test_a_guard_stands_half_a_step_ahead_at_the_shoulder(self):
        shape = SHAPES["护送"]
        for text in ("宴会厅里，沈砚护着柳烟穿过宾客。", "柳烟被沈砚护在身后。"):
            plan = _plan(text, ["沈砚", "柳烟", "宾客"])
            guard, guarded = plan.actor("沈砚"), plan.actor("柳烟")
            with self.subTest(text=text):
                back, side = _offset(guard, guarded)
                self.assertAlmostEqual(back, shape["back_m"], places=2)
                self.assertAlmostEqual(side, shape["side_m"], places=2)
                self.assertAlmostEqual(_gap(guard, guarded), 1.0, places=1)
                self.assertTrue(plan.formation.startswith(shape["relation"]))
                self.assertEqual(_failed(plan), [])

    def test_back_to_back_is_close_and_turned_outward(self):
        shape = SHAPES["警戒"]
        plan = _plan("追兵围上来，沈砚与柳烟背靠背，各自握紧兵器。", ["沈砚", "柳烟", "追兵"])
        left, right = plan.actor("沈砚"), plan.actor("柳烟")
        self.assertAlmostEqual(_gap(left, right), shape["metres"])
        self.assertEqual((left.yaw_deg, right.yaw_deg), (-90.0, 90.0))
        self.assertTrue(plan.formation.startswith(RELATIONS["back_to_back"]))
        self.assertIn(f"相距0.6米{RELATIONS['back_to_back']}", plan.shot(1).text.blocking)
        self.assertEqual(_failed(plan), [], "a pair turned outward is not held to facing each other")

    def test_a_clause_about_somebody_else_does_not_place_the_pair(self):
        for text in ("沈砚和柳烟跟在管家身后进了门。", "侍卫护着马车，沈砚与柳烟站在路边说话。", "他紧随其后。"):
            plan = _plan(text, ["沈砚", "柳烟", "管家"])
            with self.subTest(text=text):
                self.assertTrue(plan.formation.startswith(RELATIONS["facing"]))
                self.assertAlmostEqual(_gap(plan.actor("沈砚"), plan.actor("柳烟")), DATA["default_separation"]["metres"])

    def test_an_earlier_promise_of_sides_still_holds(self):
        plan = _plan("沈砚走在前面，柳烟跟在沈砚身后。", side_memory={"沈砚": "right"})
        self.assertEqual((plan.actor("沈砚").screen_side, plan.actor("柳烟").screen_side), ("right", "left"))
        back, side = _offset(plan.actor("沈砚"), plan.actor("柳烟"))
        self.assertAlmostEqual(back, SHAPES["跟随"]["back_m"], places=2)
        self.assertGreater(geo.forward_of(plan.actor("沈砚").yaw_deg)[1], 0)


class GroupShapeTests(unittest.TestCase):
    def test_a_group_sitting_round_closes_a_half_circle_open_to_the_camera(self):
        ring = DATA["group_shapes"]["ring"]
        for cast in (["沈砚", "柳烟", "老周"], ["沈砚", "柳烟", "老周", "阿福", "小满"]):
            plan = _plan("众人围坐在火炉旁商量对策。" if len(cast) > 3 else "三人围坐饮茶。", cast)
            people = [plan.actor(name) for name in cast]
            # Along the arc: left end, the company upstage from left to right, right end.
            arc = [people[0], *people[2:], people[1]]
            with self.subTest(count=len(cast)):
                for near, far in zip(arc, arc[1:]):
                    self.assertAlmostEqual(_gap(near, far), ring["spacing_m"], places=2)
                radius = _gap(people[0], people[1]) / 2
                for person in people:
                    self.assertAlmostEqual(geo.distance(_spot(person), (0.0, 0.0)), radius, places=2)
                    self.assertLessEqual(person.position[1], 0.0, "nobody sits between the pair and the camera")
                    self.assertEqual(person.posture, "sit")
                    self.assertAlmostEqual(person.yaw_deg, geo.yaw_toward(_spot(person), (0.0, 0.0)), places=1)
                self.assertTrue(plan.formation.startswith(RELATIONS["facing"]))
                self.assertIn("围成半圆，相邻0.8米", plan.formation)
                self.assertEqual(_failed(plan), [])

    def test_gathered_round_without_a_sitting_word_stays_standing(self):
        plan = _plan("三人围着沙盘争论。", ["沈砚", "柳烟", "老周"])
        self.assertEqual({actor.posture for actor in plan.actors}, {"stand"})
        self.assertIn("围成半圆", plan.formation)

    def test_two_rows_seat_the_front_and_stand_the_back(self):
        rows = DATA["group_shapes"]["rows"]
        cast = ["沈砚", "柳烟", "老周", "阿福", "小满", "阿贵"]
        plan = _plan("一家人拍合影。", cast)
        front = [plan.actor(name) for name in ("沈砚", "柳烟", "老周")]
        back = [plan.actor(name) for name in ("阿福", "小满", "阿贵")]
        self.assertEqual({actor.yaw_deg for actor in plan.actors}, {0.0})
        self.assertEqual(({actor.posture for actor in front}, {actor.posture for actor in back}), ({"sit"}, {"stand"}))
        self.assertEqual(({actor.position[1] for actor in front}, {actor.position[1] for actor in back}), ({0.0}, {-rows["depth_m"]}))
        for row in (front, back):
            xs = sorted(actor.position[0] for actor in row)
            for near, far in zip(xs, xs[1:]):
                self.assertAlmostEqual(far - near, rows["spacing_m"])
        # The pair is the middle of the front row, still left and right of each other.
        self.assertAlmostEqual(plan.actor("沈砚").position[0], -rows["spacing_m"] / 2)
        self.assertAlmostEqual(plan.actor("柳烟").position[0], rows["spacing_m"] / 2)
        self.assertTrue(plan.formation.startswith(RELATIONS["side_by_side"]))
        self.assertIn("前排沈砚、柳烟、老周，后排阿福、小满、阿贵", plan.formation)
        self.assertEqual(_failed(plan), [])

    def test_an_odd_group_puts_the_extra_person_in_front(self):
        plan = _plan("五人站成两排。", ["沈砚", "柳烟", "老周", "阿福", "小满"])
        self.assertEqual(sorted(actor.name for actor in plan.actors if actor.position[1] == 0.0), sorted(["沈砚", "柳烟", "老周"]))

    def test_a_pair_alone_has_no_ring_to_close(self):
        plan = _plan("沈砚与柳烟围炉对坐。")
        self.assertAlmostEqual(_gap(plan.actor("沈砚"), plan.actor("柳烟")), DATA["default_separation"]["metres"])
        self.assertNotIn("半圆", plan.formation)

    def test_without_the_words_company_still_closes_the_triangle_upstage(self):
        plan = _plan("沈砚与柳烟说话，老周站在后面。", ["沈砚", "柳烟", "老周"])
        self.assertIn(DATA["formations"]["supporting_shapes"]["one"], plan.formation)
        self.assertLess(plan.actor("老周").position[1], -1.0)


if __name__ == "__main__":
    unittest.main()
