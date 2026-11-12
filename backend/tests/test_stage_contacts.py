# -*- coding: utf-8 -*-
"""Contact constraints on the stage: a prop in a hand, someone on a seat, a thing lying on a table.

No model, no network: the resolver is checked with numbers, the operations with their refusals, the planner with
the shot table's words, and the check, its repair and the prompt clauses with plans built here.
"""

import itertools
import unittest
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan, clip_brief, contacts, repair
from app.core.spatial_stage import operations as stage_operations
from app.core.spatial_stage.models import StageActor, StageContact, StageLandmark, StagePlan, StagePose
from app.core.spatial_stage.operations import StageEditError, apply_operations
from app.core.spatial_stage.planner import refresh
from tests.test_spatial_stage import _brief
from tests.test_stage_set_clearance import _bedroom

_SAYS = prompt_data.load("stage_operations")["says"]
_IDS = itertools.count(10)
CODE = "spatial_contact_kept"


def _actor(position=(1.0, 2.0), yaw=0.0, posture="stand", height=1.7, **extra) -> StageActor:
    return StageActor(id="actor-01", name="林夏", position=list(position), yaw_deg=yaw, posture=posture, height_m=height, **extra)


def _piece(name="录音笔", position=(0.0, 0.0), size=(0.14, 0.03, 0.03), **extra) -> StageLandmark:
    return StageLandmark(id=f"mark-{next(_IDS)}", name=name, position=list(position), size=list(size), **extra)


def _study(*shots: ShotSpec) -> SceneBrief:
    return SceneBrief(
        scene_id="E3S01", location="书房 / 夜 / 内景", text="林夏与周教授在书房对峙。", characters=["林夏", "周教授"],
        props=["录音笔", "书案", "扶手椅", "玉佩"],
        shots=list(shots) or [
            ShotSpec(1, ["林夏", "周教授"], "", "全景", "平视", "固定", "两人在书房"),
            ShotSpec(2, ["林夏"], "林夏", "近景", "平视", "固定", "林夏右手握着录音笔"),
            ShotSpec(3, ["周教授"], "周教授", "近景", "平视", "固定", "周教授坐在扶手椅上"),
            ShotSpec(4, [], "", "特写", "俯拍", "固定", "林夏左手攥着玉佩"),
            ShotSpec(5, ["林夏", "周教授"], "", "中景", "平视", "固定", "林夏双手捧着录音笔，周教授看着桌上的玉佩"),
        ],
    )


def _contact(plan: StagePlan, kind: str, target: str) -> StageContact:
    return next(item for item in plan.contacts if item.kind == kind and item.target == target)


def _check(plan: StagePlan):
    return next((item for item in plan.checks if item.code == CODE), None)


def _refusal(test: unittest.TestCase, plan: StagePlan, *ops: dict) -> str:
    with test.assertRaises(StageEditError) as raised:
        apply_operations(plan, list(ops))
    return str(raised.exception)


class ResolverMathsTests(unittest.TestCase):
    def test_the_right_hand_is_to_the_right_and_ahead_at_047_of_the_height(self):
        x, height, z = contacts.hand_point(_actor(), "right")
        # Yaw 0 faces +z; the actor's right is -x.
        self.assertAlmostEqual(x, 1.0 - 0.22)
        self.assertAlmostEqual(z, 2.0 + 0.18)
        self.assertAlmostEqual(height, 1.7 * 0.47)
        self.assertEqual(contacts.hand_point(_actor(), ""), contacts.hand_point(_actor(), "right"))

    def test_the_left_hand_mirrors_and_both_hands_are_on_the_centre_line(self):
        x, _, z = contacts.hand_point(_actor(), "left")
        self.assertAlmostEqual(x, 1.22)
        self.assertAlmostEqual(z, 2.18)
        x, _, z = contacts.hand_point(_actor(), "both")
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(z, 2.25)

    def test_the_hand_turns_with_the_actor(self):
        # Facing +x the actor's right is +z.
        x, _, z = contacts.hand_point(_actor(yaw=90.0), "right")
        self.assertAlmostEqual(x, 1.18)
        self.assertAlmostEqual(z, 2.22)

    def test_hand_height_follows_the_posture_and_the_pose_preset(self):
        for posture, factor in (("stand", 0.47), ("walk", 0.47), ("fight", 0.47), ("bow", 0.47), ("sit", 0.55),
                                ("crouch", 0.5), ("kneel", 0.5), ("lie", 0.12)):
            with self.subTest(posture=posture):
                self.assertAlmostEqual(contacts.hand_height(_actor(posture=posture, height=1.6)), 1.6 * factor)
        posed = _actor(posture="stand", pose=StagePose(preset="sit-chair"))
        self.assertAlmostEqual(contacts.hand_height(posed), 1.7 * 0.55)

    def test_a_held_prop_sits_half_its_height_below_the_hand_and_turns_with_the_actor(self):
        prop = contacts.held(_piece(size=(0.14, 0.03, 0.2)), _actor(yaw=30.0), "right")
        hand = contacts.hand_point(_actor(yaw=30.0), "right")
        self.assertEqual(prop.position, [round(hand[0], 3), round(hand[2], 3)])
        self.assertAlmostEqual(prop.elevation_m, round(1.7 * 0.47 - 0.1, 3))
        self.assertEqual(prop.yaw_deg, 30.0)
        # Lying down the hand is lower than half a big prop: the prop rests on the floor, never under it.
        self.assertEqual(contacts.held(_piece(size=(0.5, 0.5, 0.5)), _actor(posture="lie"), "both").elevation_m, 0.0)

    def test_a_seated_actor_is_on_the_seat_centre_facing_as_before(self):
        seat = _piece("扶手椅", position=(-2.0, -0.6), size=(0.5, 0.5, 0.5))
        sitter = contacts.seated(_actor(yaw=45.0), seat)
        self.assertEqual(sitter.position, [-2.0, -0.6])
        self.assertEqual(sitter.posture, "sit")
        self.assertEqual(sitter.yaw_deg, 45.0)

    def test_a_seat_is_a_piece_whose_top_is_between_03_and_07_metres(self):
        self.assertTrue(contacts.is_seat(_piece("凳", size=(0.4, 0.4, 0.3))))
        self.assertTrue(contacts.is_seat(_piece("榻", size=(2.0, 1.4, 0.55))))
        self.assertFalse(contacts.is_seat(_piece("书案", size=(1.4, 0.7, 0.75))))
        self.assertFalse(contacts.is_seat(_piece("垫", size=(0.4, 0.4, 0.2))))
        self.assertTrue(contacts.is_seat(_piece("垫", size=(0.4, 0.4, 0.2), elevation_m=0.3)))

    def test_a_rested_thing_is_on_the_top_and_clamped_into_the_footprint(self):
        desk = _piece("书案", position=(0.0, 0.0), size=(1.4, 0.7, 0.75))
        cup = contacts.rested(_piece("茶杯", position=(2.0, 0.1), size=(0.1, 0.1, 0.1)), desk)
        self.assertEqual(cup.position, [0.68, 0.1])
        self.assertEqual(cup.elevation_m, 0.75)
        # Inside the footprint it stays where it is.
        self.assertEqual(contacts.rested(_piece("茶杯", position=(0.2, -0.1)), desk).position, [0.2, -0.1])

    def test_the_footprint_turns_with_the_support(self):
        desk = _piece("书案", position=(0.0, 0.0), size=(1.4, 0.7, 0.75), yaw_deg=90.0, elevation_m=0.1)
        cup = contacts.rested(_piece("茶杯", position=(2.0, 0.1)), desk)
        # Turned a quarter, the desk's 0.7 m depth lies along x: the cup can come no further than 0.35 - 0.02.
        self.assertEqual(cup.position, [0.33, 0.1])
        self.assertEqual(cup.elevation_m, 0.85)

    def test_a_thing_on_a_thing_on_a_table_settles_whatever_the_order(self):
        table = _piece("书案", position=(0.0, 0.0), size=(1.4, 0.7, 0.75))
        tray = _piece("托盘", position=(3.0, 0.0), size=(0.4, 0.3, 0.02))
        cup = _piece("茶杯", position=(5.0, 0.0), size=(0.08, 0.08, 0.1))
        rests = [
            StageContact(id="c1", kind="rest", target="茶杯", support="托盘"),
            StageContact(id="c2", kind="rest", target="托盘", support="书案"),
        ]
        placed = {item.name: item for item in contacts.place_landmarks([table, tray, cup], [], rests, 1)}
        self.assertEqual(placed["托盘"].position, [0.68, 0.0])
        self.assertEqual(placed["托盘"].elevation_m, 0.75)
        self.assertEqual(placed["茶杯"].elevation_m, 0.77)
        self.assertEqual(placed["茶杯"].position, [0.86, 0.0])

    def test_a_contact_only_applies_in_its_shots_and_a_missing_holder_leaves_the_prop(self):
        prop = _piece(position=(5.0, 5.0))
        hold = StageContact(id="c1", kind="hold", actor="林夏", target="录音笔", shot_ids=[2])
        self.assertEqual(contacts.place_landmarks([prop], [_actor()], [hold], 1)[0].position, [5.0, 5.0])
        self.assertEqual(contacts.place_landmarks([prop], [_actor()], [hold], 2)[0].position, [0.78, 2.18])
        # Offstage in the shot (not in the staged cast): the prop stays where it is stored.
        self.assertEqual(contacts.place_landmarks([prop], [], [hold], 2)[0].position, [5.0, 5.0])
        # Nothing else changes, and the stored pieces are not touched.
        self.assertEqual(prop.position, [5.0, 5.0])

    def test_a_seated_holder_holds_at_sitting_height_whatever_the_pose_preset_says(self):
        # The desk draws a sitter seated even when the pose preset names standing; the hand follows the seat.
        seat = _piece("扶手椅", position=(-2.0, -0.6), size=(0.5, 0.5, 0.5))
        prop = _piece(position=(5.0, 5.0), size=(0.14, 0.03, 0.04))
        standing_pose = _actor(pose=StagePose(preset="stand"))
        self.assertAlmostEqual(contacts.hand_height(standing_pose), 1.7 * 0.47)
        self.assertAlmostEqual(contacts.hand_height(standing_pose, seated=True), 1.7 * 0.55)
        found = [
            StageContact(id="c1", kind="sit", actor="林夏", target="扶手椅", shot_ids=[3]),
            StageContact(id="c2", kind="hold", actor="林夏", target="录音笔", shot_ids=[2, 3]),
        ]
        for shot_id, factor in ((2, 0.47), (3, 0.55)):
            with self.subTest(shot=shot_id):
                cast = contacts.seat_actors([standing_pose], [seat, prop], found, shot_id)
                placed = contacts.place_landmarks([seat, prop], cast, found, shot_id)[1]
                self.assertAlmostEqual(placed.elevation_m, round(1.7 * factor - 0.02, 3))
        # A pose shaped joint by joint keeps its own say elsewhere; only the preset's posture gives way to the seat.
        self.assertEqual(contacts.seated(standing_pose, seat).pose, standing_pose.pose)

    def test_a_seat_moves_the_sitter_only_in_its_shots(self):
        seat = _piece("扶手椅", position=(-2.0, -0.6), size=(0.5, 0.5, 0.5))
        sit = StageContact(id="c1", kind="sit", actor="林夏", target="扶手椅", shot_ids=[3])
        self.assertEqual(contacts.seat_actors([_actor()], [seat], [sit], 2)[0].position, [1.0, 2.0])
        self.assertEqual(contacts.seat_actors([_actor()], [seat], [sit], 3)[0].position, [-2.0, -0.6])

    def test_taking_a_target_out_of_shots_keeps_the_rest_of_its_scene(self):
        whole = StageContact(id="c1", kind="rest", target="录音笔", support="书案")
        listed = StageContact(id="c2", kind="hold", actor="林夏", target="玉佩", shot_ids=[1, 2])
        left = contacts.without_shots([whole, listed], "录音笔", [2], [1, 2, 3])
        self.assertEqual(left[0].shot_ids, [1, 3])
        self.assertEqual(left[1], listed)
        self.assertEqual(contacts.without_shots([whole], "录音笔", [], [1, 2, 3]), [])
        self.assertEqual(contacts.without_shots([listed], "玉佩", [1, 2], [1, 2, 3]), [])
        self.assertEqual(contacts.without_shots([whole], "录音笔", [9], [1, 2, 3]), [whole])
        self.assertEqual(contacts.next_id([whole, listed]), "contact-01")
        self.assertEqual(contacts.next_id([whole.model_copy(update={"id": "contact-07"})]), "contact-08")


class OldPlanTests(unittest.TestCase):
    def _fixtures(self) -> dict[str, StagePlan]:
        from tests import test_director_desk, test_director_desk_repairs, test_stage_props, test_stage_resolve_cut

        return {
            "spatial_stage": build_plan(_brief()),
            "bedroom": build_plan(_bedroom()),
            "director_desk": build_plan(test_director_desk._brief()),
            "desk_repairs": build_plan(test_director_desk_repairs._brief()),
            "props": build_plan(test_stage_props._scene(["录音笔", "书案"])),
            "resolve_cut": test_stage_resolve_cut._plan(),
            "study": build_plan(_study()),
        }

    def test_a_plan_saved_without_contacts_loads_unchanged(self):
        for name, plan in self._fixtures().items():
            with self.subTest(fixture=name):
                saved = plan.model_dump(mode="json")
                saved.pop("contacts")
                loaded = StagePlan.model_validate(saved)
                self.assertEqual(loaded.contacts, [])
                self.assertEqual(loaded.model_dump(mode="json"), {**saved, "contacts": []})

    def test_a_plan_without_contacts_is_projected_exactly_as_before(self):
        plan = build_plan(_brief())
        self.assertEqual(plan.contacts, [])
        self.assertIsNone(_check(plan))
        for shot in plan.shots:
            self.assertIs(plan.landmarks_in(shot), plan.landmarks)


class ModelValidationTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_study())

    def _with(self, *items: StageContact) -> dict:
        return {**self.plan.model_dump(mode="json"), "contacts": [item.model_dump(mode="json") for item in items]}

    def test_each_kind_names_what_it_needs(self):
        for bad in (
            {"kind": "hold", "target": "录音笔"},
            {"kind": "sit", "target": "扶手椅", "actor": "林夏", "support": "书案"},
            {"kind": "rest", "target": "录音笔"},
            {"kind": "rest", "target": "录音笔", "support": "录音笔"},
            {"kind": "rest", "target": "录音笔", "support": "书案", "actor": "林夏"},
            {"kind": "sit", "target": "扶手椅", "actor": "林夏", "hand": "left"},
            {"kind": "hold", "target": "录音笔", "actor": "林夏", "shot_ids": [2, 2]},
        ):
            with self.subTest(contact=bad), self.assertRaises(ValueError):
                StageContact(id="c1", **bad)

    def test_names_resolve_to_the_stage(self):
        for bad in (
            StageContact(id="c1", kind="hold", actor="无名", target="录音笔"),
            StageContact(id="c1", kind="hold", actor="林夏", target="不存在"),
            StageContact(id="c1", kind="rest", target="录音笔", support="不存在"),
        ):
            with self.subTest(contact=bad), self.assertRaises(ValueError):
                StagePlan.model_validate(self._with(bad))

    def test_no_two_contacts_on_one_target_in_one_shot(self):
        hold = StageContact(id="c1", kind="hold", actor="林夏", target="录音笔", shot_ids=[2])
        with self.assertRaises(ValueError):
            StagePlan.model_validate(self._with(hold, StageContact(id="c2", kind="rest", target="录音笔", support="书案")))
        with self.assertRaises(ValueError):
            StagePlan.model_validate(self._with(hold, StageContact(id="c2", kind="hold", actor="周教授", target="录音笔", shot_ids=[2, 3])))
        with self.assertRaises(ValueError):
            StagePlan.model_validate(self._with(hold, hold))
        apart = StageContact(id="c2", kind="rest", target="录音笔", support="书案", shot_ids=[1, 3])
        self.assertEqual(len(StagePlan.model_validate(self._with(hold, apart)).contacts), 2)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_study())

    def test_hold_with_each_hand(self):
        left = _contact(self.plan, "hold", "玉佩")
        self.assertEqual((left.actor, left.hand, left.shot_ids, left.source), ("林夏", "left", [4], "auto"))
        holds = [item for item in self.plan.contacts if item.kind == "hold" and item.target == "录音笔"]
        self.assertEqual([(item.hand, item.shot_ids) for item in holds], [("right", [2]), ("both", [5])])

    def test_a_hold_with_no_hand_named_is_the_right_hand(self):
        plan = build_plan(_study(ShotSpec(1, ["林夏"], "林夏", "近景", "平视", "固定", "林夏拿着录音笔走来走去")))
        hold = _contact(plan, "hold", "录音笔")
        self.assertEqual((hold.hand, hold.shot_ids), ("", [1]))

    def test_sit_lasts_until_the_sitter_stands(self):
        plan = build_plan(_study(
            ShotSpec(1, ["周教授"], "", "中景", "平视", "固定", "周教授坐在扶手椅上"),
            ShotSpec(2, ["周教授"], "", "近景", "平视", "固定", "周教授沉默"),
            ShotSpec(3, ["周教授"], "", "近景", "平视", "固定", "周教授起身"),
        ))
        sit = _contact(plan, "sit", "扶手椅")
        self.assertEqual((sit.actor, sit.shot_ids), ("周教授", [1, 2]))
        chair = plan.landmark("扶手椅")
        seated = {actor.name: actor for actor in plan.actors_in(plan.shot(2))}["周教授"]
        self.assertEqual((seated.position, seated.posture), (chair.position, "sit"))
        standing = {actor.name: actor for actor in plan.actors_in(plan.shot(3))}["周教授"]
        self.assertNotEqual(standing.posture, "sit")

    def _pair(self, desc: str, **extra) -> StagePlan:
        return build_plan(SceneBrief(
            scene_id="E3S02", location="书房 / 夜 / 内景", text="林夏与周教授在书房对峙。", characters=["林夏", "周教授"],
            props=["扶手椅", "书案", "录音笔"], **extra, shots=[
                ShotSpec(1, ["林夏", "周教授"], "", "全景", "平视", "固定", "两人在书房"),
                ShotSpec(2, ["周教授"], "周教授", "近景", "平视", "固定", desc),
                ShotSpec(3, ["林夏", "周教授"], "", "中景", "平视", "固定", "两人对视"),
                ShotSpec(4, ["林夏"], "林夏", "近景", "过肩", "固定", "林夏盯着对面"),
            ],
        ))

    def test_a_seat_dressed_for_a_sitter_is_set_under_them(self):
        quiet, seated = self._pair("周教授沉默不语"), self._pair("周教授坐在扶手椅上")
        professor = seated.actor("周教授")
        chair = seated.landmark("扶手椅")
        self.assertEqual(chair.position, professor.position)
        self.assertEqual(chair.yaw_deg, professor.yaw_deg)
        self.assertEqual(_contact(seated, "sit", "扶手椅").shot_ids, [2, 3, 4])
        # The pair keeps its marks, facings and screen sides; sitting down costs no new warning.
        self.assertEqual(
            [(actor.name, actor.position, actor.yaw_deg, actor.screen_side) for actor in seated.actors],
            [(actor.name, actor.position, actor.yaw_deg, actor.screen_side) for actor in quiet.actors],
        )
        for shot_id in (1, 3):
            sides = lambda plan: [(state.name, state.region) for state in plan.shot(shot_id).screen if state.visible]  # noqa: E731
            self.assertEqual(sides(seated), sides(quiet))
        self.assertIn("面对面", seated.shot(3).text.blocking)
        failing = lambda plan: sorted(check.code for check in plan.checks if not check.passed)  # noqa: E731
        self.assertEqual(failing(seated), failing(quiet))
        self.assertTrue(_check(seated).passed)
        # Every other piece keeps the rules it had: the desk and the recorder stand where they stood.
        for name in ("书案", "录音笔"):
            self.assertEqual(seated.landmark(name).position, quiet.landmark(name).position)

    def test_a_seat_already_on_the_set_stays_and_is_only_sat_on_within_reach(self):
        far = StageLandmark(id="mark-90", name="扶手椅", kind="prop", position=[4.0, -3.0], size=[0.5, 0.5, 0.5])
        plan = build_plan(SceneBrief(
            scene_id="E3S03", location="书房 / 夜 / 内景", text="林夏与周教授在书房对峙。", characters=["林夏", "周教授"],
            props=["扶手椅"], shots=[ShotSpec(1, ["周教授"], "周教授", "近景", "平视", "固定", "周教授坐在扶手椅上")],
        ), location_landmarks=[far])
        self.assertEqual(plan.landmark("扶手椅").position, [4.0, -3.0])
        self.assertFalse([item for item in plan.contacts if item.kind == "sit"])
        mark = build_plan(SceneBrief(scene_id="x", location="书房", characters=["林夏", "周教授"])).actor("周教授").position
        near = far.model_copy(update={"position": [mark[0] + 0.8, mark[1] - 0.6]})
        plan = build_plan(SceneBrief(
            scene_id="E3S03", location="书房 / 夜 / 内景", text="林夏与周教授在书房对峙。", characters=["林夏", "周教授"],
            props=["扶手椅"], shots=[ShotSpec(1, ["周教授"], "周教授", "近景", "平视", "固定", "周教授坐在扶手椅上")],
        ), location_landmarks=[near])
        self.assertEqual(plan.landmark("扶手椅").position, near.position)
        self.assertEqual(_contact(plan, "sit", "扶手椅").actor, "周教授")
        self.assertEqual({a.name: a for a in plan.actors_in(plan.shot(1))}["周教授"].position, near.position)

    def test_a_hand_prop_on_the_table_rests_on_it_except_while_held(self):
        rest = _contact(self.plan, "rest", "录音笔")
        self.assertEqual((rest.support, rest.shot_ids), ("书案", [1, 3, 4]))
        bedroom = build_plan(_bedroom())
        self.assertEqual(
            [(item.kind, item.target, item.support, item.shot_ids) for item in bedroom.contacts],
            [("rest", "录音笔", "书案", []), ("rest", "玉佩", "书案", [])],
        )

    def test_a_prop_merely_named_is_in_no_contact(self):
        plan = build_plan(_study(
            ShotSpec(1, ["林夏"], "林夏", "近景", "平视", "固定", "林夏看着桌上的录音笔"),
            ShotSpec(2, ["周教授"], "", "近景", "平视", "固定", "录音笔在周教授手边，林夏握手"),
        ))
        self.assertEqual([item.kind for item in plan.contacts], ["rest", "rest"])

    def test_someone_else_named_before_the_verb_owns_the_clause(self):
        plan = build_plan(_study(ShotSpec(1, ["林夏", "周教授"], "", "中景", "平视", "固定", "林夏看着周教授拿起录音笔")))
        self.assertEqual(_contact(plan, "hold", "录音笔").actor, "周教授")

    def test_a_held_prop_is_framed_where_the_hand_is(self):
        # Shot 4 shows nobody and names the pendant: an insert of it, solved in 林夏's left hand.
        camera = self.plan.camera(self.plan.shot(4).camera_id)
        hand = contacts.hand_point(self.plan.actor("林夏"), "left")
        self.assertAlmostEqual(camera.target[0], hand[0], places=2)
        self.assertAlmostEqual(camera.target[2], hand[2], places=2)
        held = {item.name: item for item in self.plan.landmarks_in(self.plan.shot(4))}["玉佩"]
        self.assertAlmostEqual(camera.target[1], held.elevation_m + held.size[2] * 0.8, places=2)

    def test_there_is_no_cap_on_contacts_in_a_shot(self):
        props = [f"玉牌{index}" for index in range(12)]
        text = "，".join(f"林夏握着{name}" for name in props)
        brief = _study(ShotSpec(1, ["林夏"], "林夏", "近景", "平视", "固定", text))
        brief.props = props
        plan = build_plan(brief)
        self.assertEqual(sorted(item.target for item in plan.contacts if item.kind == "hold"), sorted(props))

    def test_a_replan_keeps_a_persons_contacts_and_derives_the_rest_again(self):
        edited = apply_operations(self.plan, [
            {"op": "set_contact", "kind": "hold", "actor": "周教授", "target": "玉佩", "hand": "right", "shot_ids": [5]},
        ])
        again = build_plan(_study(), blocking_from=edited)
        manual = [item for item in again.contacts if item.source == "manual"]
        self.assertEqual([(item.actor, item.target, item.shot_ids) for item in manual], [("周教授", "玉佩", [5])])
        # The derived rest gives the manual hold its shot; the derived holds come back as they were.
        self.assertEqual(_contact(again, "rest", "玉佩").shot_ids, [1, 2, 3])
        self.assertEqual(
            sorted((item.target, item.hand, tuple(item.shot_ids)) for item in again.contacts if item.kind == "hold" and item.source == "auto"),
            sorted([("玉佩", "left", (4,)), ("录音笔", "both", (5,)), ("录音笔", "right", (2,))]),
        )


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_study())

    def test_set_contact_adds_a_manual_contact_and_bumps_the_revision(self):
        edited = apply_operations(self.plan, [{"op": "set_contact", "kind": "hold", "actor": "周教授", "target": "玉佩", "shot_ids": [3]}])
        added = edited.contacts[-1]
        self.assertEqual((added.kind, added.actor, added.hand, added.shot_ids, added.source), ("hold", "周教授", "", [3], "manual"))
        self.assertEqual(added.id, "contact-07")
        self.assertEqual(edited.revision, self.plan.revision + 1)
        # The resting contact gives up shot 3 to it.
        self.assertEqual(_contact(edited, "rest", "玉佩").shot_ids, [1, 2, 5])

    def test_a_whole_scene_contact_replaces_every_contact_on_the_target(self):
        edited = apply_operations(self.plan, [{"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "hand": "left"}])
        on_it = [item for item in edited.contacts if item.target == "录音笔"]
        self.assertEqual([(item.kind, item.hand, item.shot_ids) for item in on_it], [("hold", "left", [])])

    def test_a_whole_scene_hold_is_kept_in_the_stored_marks_and_follows_the_actor(self):
        edited = apply_operations(self.plan, [{"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔"}])
        hand = contacts.hand_point(edited.actor("林夏"), "")
        self.assertEqual(edited.landmark("录音笔").position, [round(hand[0], 3), round(hand[2], 3)])
        moved = apply_operations(edited, [{"op": "move_actor", "name": "林夏", "position": [-2.5, 1.0]}])
        hand = contacts.hand_point(moved.actor("林夏"), "")
        self.assertEqual(moved.landmark("录音笔").position, [round(hand[0], 3), round(hand[2], 3)])
        self.assertTrue(_check(moved).passed)

    def test_set_contact_sit_and_rest(self):
        edited = apply_operations(self.plan, [
            {"op": "set_contact", "kind": "sit", "actor": "林夏", "target": "扶手椅", "shot_ids": [1]},
            {"op": "set_contact", "kind": "rest", "target": "录音笔", "support": "扶手椅", "shot_ids": [3]},
        ])
        sit, rest = edited.contacts[-2], edited.contacts[-1]
        self.assertEqual((sit.kind, sit.actor, sit.shot_ids), ("sit", "林夏", [1]))
        self.assertEqual((rest.kind, rest.support, rest.shot_ids), ("rest", "扶手椅", [3]))
        on_chair = {item.name: item for item in edited.landmarks_in(edited.shot(3))}["录音笔"]
        self.assertEqual(on_chair.elevation_m, 0.5)

    def test_remove_contact_everywhere_or_in_one_shot(self):
        gone = apply_operations(self.plan, [{"op": "remove_contact", "target": "录音笔"}])
        self.assertFalse([item for item in gone.contacts if item.target == "录音笔"])
        one = apply_operations(self.plan, [{"op": "remove_contact", "target": "录音笔", "shot_id": 3}])
        self.assertEqual(_contact(one, "rest", "录音笔").shot_ids, [1, 4])
        whole = apply_operations(self.plan, [{"op": "set_contact", "kind": "rest", "target": "录音笔", "support": "书案"}])
        cut = apply_operations(whole, [{"op": "remove_contact", "target": "录音笔", "shot_id": 2}])
        self.assertEqual(_contact(cut, "rest", "录音笔").shot_ids, [1, 3, 4, 5])
        self.assertEqual(cut.revision, whole.revision + 1)

    def test_every_refusal_says_what_the_table_says(self):
        cases = [
            ({"op": "set_contact", "kind": "lean", "target": "录音笔"}, _SAYS["contact_kind"].format(options="hold / sit / rest")),
            ({"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "无"}, _SAYS["contact_no_target"].format(name="无")),
            ({"op": "set_contact", "kind": "hold", "actor": "无名", "target": "录音笔"}, _SAYS["no_actor"].format(name="无名")),
            ({"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "hand": "foot"},
             _SAYS["contact_hand"].format(options="right / left / both")),
            ({"op": "set_contact", "kind": "sit", "actor": "林夏", "target": "书案"},
             _SAYS["contact_not_a_seat"].format(name="书案", top=0.75, low=0.3, high=0.7)),
            ({"op": "set_contact", "kind": "rest", "target": "录音笔", "support": "无"}, _SAYS["contact_no_support"].format(name="无")),
            ({"op": "set_contact", "kind": "rest", "target": "书案", "support": "书案"}, _SAYS["contact_on_itself"].format(name="书案")),
            ({"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "shot_ids": 2}, _SAYS["contact_shot_ids"]),
            ({"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "shot_ids": [99]}, _SAYS["no_shot"].format(shot=99)),
            ({"op": "remove_contact", "target": "扶手椅", "shot_id": 1}, _SAYS["contact_none_in_shot"].format(name="扶手椅", shot=1)),
            ({"op": "remove_contact", "target": "书案"}, _SAYS["contact_none"].format(name="书案")),
        ]
        for op, reason in cases:
            with self.subTest(op=op):
                self.assertEqual(_refusal(self, self.plan, op), f"operations[0] {op['op']}：{reason}")

    def test_a_full_contact_list_is_refused(self):
        with patch.object(stage_operations, "MAX_CONTACTS", len(self.plan.contacts)):
            message = _refusal(self, self.plan, {"op": "set_contact", "kind": "hold", "actor": "周教授", "target": "书案", "shot_ids": [1]})
        self.assertTrue(message.endswith(_SAYS["contacts_full"].format(limit=len(self.plan.contacts))))

    def test_all_or_nothing(self):
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [
                {"op": "set_contact", "kind": "hold", "actor": "周教授", "target": "书案"},
                {"op": "remove_contact", "target": "不存在"},
            ])
        self.assertEqual(len(self.plan.contacts), 6)

    def test_a_prop_held_all_scene_cannot_be_moved_alone(self):
        held = apply_operations(self.plan, [{"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔"}])
        message = _refusal(self, held, {"op": "move_landmark", "name": "录音笔", "position": [3.0, 3.0]})
        self.assertEqual(message, "operations[0] move_landmark：「录音笔」在林夏右手里：先解除接触再单独移动")
        both = apply_operations(self.plan, [{"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "hand": "both"}])
        self.assertIn("在林夏双手里", _refusal(self, both, {"op": "move_landmark", "name": "录音笔", "position": [3.0, 3.0]}))
        # Held in a few shots only, its stored place is where it lies in the others: that can move.
        moved = apply_operations(self.plan, [{"op": "remove_contact", "target": "录音笔"}, {"op": "move_landmark", "name": "录音笔", "position": [3.0, 3.0]}])
        self.assertEqual(moved.landmark("录音笔").position, [3.0, 3.0])

    def test_removing_a_piece_or_a_person_ends_its_contacts(self):
        edited = apply_operations(self.plan, [{"op": "remove_landmark", "name": "扶手椅"}])
        self.assertFalse([item for item in edited.contacts if item.target == "扶手椅"])
        extra = apply_operations(self.plan, [{"op": "add_extra", "name": "路人"}])
        extra = apply_operations(extra, [{"op": "set_contact", "kind": "hold", "actor": "路人", "target": "书案", "shot_ids": [1]}])
        gone = apply_operations(extra, [{"op": "remove_extra", "name": "路人"}])
        self.assertFalse([item for item in gone.contacts if item.actor == "路人"])


class CheckAndRepairTests(unittest.TestCase):
    def setUp(self):
        plan = build_plan(_study())
        self.held = apply_operations(plan, [{"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "玉佩", "hand": "left"}])
        # A plan stored whole (the desk's save, a model's plan) with the pendant left on the floor.
        pieces = [item.model_copy(update={"position": [3.0, 3.0], "elevation_m": 0.0}) if item.name == "玉佩" else item for item in self.held.landmarks]
        self.broken = refresh(self.held.model_copy(update={"landmarks": pieces}))

    def test_the_check_passes_when_every_contact_is_kept(self):
        check = _check(self.held)
        self.assertTrue(check.passed)
        self.assertEqual(check.severity, "warning")

    def test_the_check_fails_for_a_prop_away_from_the_hand(self):
        check = _check(self.broken)
        self.assertFalse(check.passed)
        self.assertIn("「玉佩」离林夏的左手", check.detail)

    def test_the_check_fails_for_a_thing_off_its_support_and_a_sitter_off_the_seat(self):
        plan = apply_operations(self.held, [
            {"op": "set_contact", "kind": "rest", "target": "录音笔", "support": "书案"},
            {"op": "set_contact", "kind": "sit", "actor": "周教授", "target": "扶手椅"},
        ])
        moved = [item.model_copy(update={"elevation_m": 0.0}) if item.name == "录音笔" else item for item in plan.landmarks]
        people = [actor.model_copy(update={"position": [2.0, 2.0]}) if actor.name == "周教授" else actor for actor in plan.actors]
        check = _check(refresh(plan.model_copy(update={"landmarks": moved, "actors": people})))
        self.assertFalse(check.passed)
        self.assertIn("「录音笔」没有放在「书案」上", check.detail)
        self.assertIn("周教授没有坐在「扶手椅」上", check.detail)

    def test_a_seated_holder_with_a_standing_preset_is_checked_at_sitting_height(self):
        plan = apply_operations(self.held, [
            {"op": "set_pose", "name": "林夏", "preset": "stand"},
            {"op": "set_contact", "kind": "sit", "actor": "林夏", "target": "扶手椅"},
        ])
        pendant = plan.landmark("玉佩")
        self.assertAlmostEqual(pendant.elevation_m, round(1.7 * 0.55 - pendant.size[2] / 2, 3))
        self.assertTrue(_check(plan).passed)

    def test_a_seat_too_high_and_a_holder_offstage_need_a_person(self):
        plan = apply_operations(self.held, [
            {"op": "set_contact", "kind": "sit", "actor": "周教授", "target": "扶手椅", "shot_ids": [3]},
            {"op": "transform_landmark", "name": "扶手椅", "size": [0.5, 0.5, 0.9]},
            {"op": "set_shot_override", "shot_id": 2, "name": "林夏", "offstage": True},
        ])
        check = _check(plan)
        self.assertFalse(check.passed)
        self.assertIn("「扶手椅」座面高0.90米", check.detail)
        self.assertIn("第2镜林夏不在场", check.detail)
        self.assertEqual(check.shot_ids, [2])
        proposal = next(item for item in repair.propose(plan) if item.code == CODE)
        self.assertFalse(proposal.automatic)
        self.assertIn("座面高0.90米", proposal.manual)

    def test_the_repair_puts_the_prop_back_in_the_hand(self):
        proposal = next(item for item in repair.propose(self.broken) if item.code == CODE)
        self.assertEqual(proposal.label, "贴合接触")
        self.assertEqual([op["op"] for op in proposal.operations], ["transform_landmark"])
        self.assertEqual(proposal.detail, "把玉佩贴回接触的位置。")
        fixed = apply_operations(self.broken, proposal.operations)
        self.assertTrue(_check(fixed).passed)
        again = apply_operations(self.broken, [{"op": "repair_checks", "codes": [CODE]}])
        self.assertTrue(_check(again).passed)
        hand = contacts.hand_point(again.actor("林夏"), "left")
        self.assertEqual(again.landmark("玉佩").position, [round(hand[0], 3), round(hand[2], 3)])

    def test_the_repair_seats_the_sitter(self):
        plan = apply_operations(self.held, [{"op": "set_contact", "kind": "sit", "actor": "周教授", "target": "扶手椅"}])
        people = [actor.model_copy(update={"position": [2.0, 2.0], "posture": "stand"}) if actor.name == "周教授" else actor for actor in plan.actors]
        broken = refresh(plan.model_copy(update={"actors": people}))
        proposal = next(item for item in repair.propose(broken) if item.code == CODE)
        self.assertEqual(proposal.operations, [
            {"op": "move_actor", "name": "周教授", "position": plan.landmark("扶手椅").position, "posture": "sit"},
        ])
        self.assertTrue(_check(apply_operations(broken, proposal.operations)).passed)


class PromptClauseTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_study())

    def test_the_panel_text_says_each_visible_contact_once(self):
        blocking = {shot.shot_id: shot.text.blocking for shot in self.plan.shots}
        self.assertIn("林夏右手握着录音笔", blocking[2])
        self.assertIn("周教授坐在扶手椅上", blocking[3])
        self.assertIn("录音笔放在书案上", blocking[1])
        self.assertIn("林夏双手握着录音笔", blocking[5])
        self.assertEqual(blocking[2].count("录音笔放在"), 0)
        # 林夏 is out of shot 3's frame: what she holds is not said there.
        self.assertNotIn("林夏右手", blocking[3])

    def test_the_clip_brief_gives_contacts_their_own_line(self):
        lines = clip_brief.shot_lines(self.plan, 5)
        touching = [line for line in lines if line.startswith("接触：")]
        self.assertEqual(touching, ["接触：林夏双手握着录音笔；周教授坐在扶手椅上；玉佩放在书案上"])
        space = next(line for line in lines if line.startswith("空间："))
        self.assertNotIn("双手握着", space)
        # The person line reads the seated posture the contact gives.
        person = next(line for line in lines if line.startswith("人物：周教授"))
        self.assertIn("坐着", person)

    def test_a_plan_without_contacts_writes_no_contact_line(self):
        plan = build_plan(_brief())
        for shot in plan.shots:
            self.assertFalse([line for line in clip_brief.shot_lines(plan, shot.shot_id) if line.startswith("接触：")])

    def test_the_wording_is_data(self):
        panel = prompt_data.load("stage_panel")
        reworded = {**panel, "contacts": {**panel["contacts"], "hold": "{actor}用{hand}拿{target}"}}
        load = prompt_data.load
        with patch.object(prompt_data, "load", side_effect=lambda name: reworded if name == "stage_panel" else load(name)):
            plan = refresh(self.plan)
        self.assertIn("林夏用右手拿录音笔", plan.shot(2).text.blocking)


if __name__ == "__main__":
    unittest.main()
