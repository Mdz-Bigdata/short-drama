# -*- coding: utf-8 -*-
"""Action and effect marks on a white-model blocking diagram: read from motion clips and the shot's sentence."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.core import prompt_data
from app.core.spatial_stage import action_marks, blocking_diagram
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.models import (
    MAX_EFFECTS, ActionClip, ActorOverride, ShotTimeline, StageActor, StageCamera, StageEffect, StageLandmark, StagePlan, StageShot,
)
from app.core.spatial_stage.operations import StageEditError, apply_operations


def _plan(action: str = "", clips: dict | None = None, **changes) -> StagePlan:
    base = dict(
        scene_id="E1S05", location="旧仓库 夜", aspect_ratio="16:9", revision=3,
        actors=[
            # 陆沉 faces +X, straight at 苏晚 two metres away; 老周 stands behind him.
            StageActor(id="a1", name="陆沉", position=[-1.0, 0.0], yaw_deg=90, role="principal", posture="fight"),
            StageActor(id="a2", name="苏晚", position=[1.0, 0.0], yaw_deg=-90, role="principal"),
            StageActor(id="a3", name="老周", position=[-3.0, 1.0], yaw_deg=90, role="supporting"),
        ],
        landmarks=[
            StageLandmark(id="l1", name="木箱", position=[3.0, 0.0], size=[0.8, 0.8, 0.6]),
            StageLandmark(id="l2", name="铁门", position=[0.0, -4.0], size=[2.4, 0.2, 2.6], kind="architecture"),
        ],
        cameras=[StageCamera(id="c1", label="c1", position=[0.0, 1.5, 5.0], target=[0.0, 1.2, 0.0], aspect="16:9", lens_mm=35)],
        shots=[StageShot(shot_id=1, camera_id="c1", subjects=["陆沉", "苏晚"], action=action)],
    )
    if clips:
        base["timelines"] = {"1": ShotTimeline(duration_s=6, clips=clips)}
    base.update(changes)
    return StagePlan(**base)


def _clip(clip: str, start: float, end: float, clip_id: str = "") -> ActionClip:
    return ActionClip(id=clip_id or clip.replace("-", "_"), clip=clip, start=start, end=end)


def _first(plan: StagePlan) -> dict:
    return blocking_diagram.build(plan)["diagrams"][0]


class ClipMarkTests(unittest.TestCase):
    def test_a_punch_clip_draws_a_strike_at_whoever_the_attacker_faces(self):
        diagram = _first(_plan(clips={"陆沉": [_clip("human-punch-cross-v1", 1.0, 1.8)]}))
        strike, = diagram["strikes"]
        self.assertEqual((strike["attacker"], strike["target"], strike["kind"], strike["source"]), ("陆沉", "苏晚", "fist", "clip"))
        self.assertEqual(strike["meters"], 2.0)
        # From his hand to her near side, along the line between them.
        self.assertEqual(strike["from"], [-0.7, 0.0])
        self.assertEqual(strike["to"], [0.75, 0.0])
        self.assertIsNone(strike["force_to"])
        self.assertEqual(diagram["modes"], ["staging", "action"])
        self.assertIn("动作预演", diagram["title"])

    def test_a_hit_reaction_on_the_struck_adds_the_force_arrow_along_the_blow(self):
        diagram = _first(_plan(clips={
            "陆沉": [_clip("human-sword-attack-v1", 0.5, 1.5)], "苏晚": [_clip("human-hit-knockback-v1", 1.2, 2.2)],
        }))
        strike, = diagram["strikes"]
        self.assertEqual(strike["kind"], "blade")
        self.assertEqual(strike["reaction"], "被击退")
        self.assertEqual(strike["force_to"], [1.95, 0.0])
        self.assertEqual(diagram["distances"], [])
        struck = next(figure for figure in diagram["figures"] if figure["name"] == "苏晚")
        self.assertEqual(struck["acts"], ["击退"])
        self.assertEqual([node["name"] for node in diagram["nodes"]], ["陆沉", "苏晚"])
        self.assertEqual(diagram["nodes"][0]["what"], prompt_data.load("stage_brief")["clip_names"]["human-sword-attack-v1"])

    def test_a_strike_at_nobody_points_the_way_the_attacker_faces(self):
        plan = _plan(clips={"老周": [_clip("human-punch-jab-v1", 0.0, 0.6)]})
        plan = plan.model_copy(update={"actors": [actor.model_copy(update={"yaw_deg": 180}) if actor.name == "老周" else actor for actor in plan.actors]})
        strike, = _first(plan)["strikes"]
        self.assertEqual((strike["attacker"], strike["target"]), ("老周", ""))
        self.assertLess(strike["to"][1], strike["from"][1])

    def test_rolls_blocks_and_jumps_become_short_labels_on_the_figure(self):
        diagram = _first(_plan(clips={
            "苏晚": [_clip("human-roll-v1", 0.0, 1.0), _clip("human-leap-air-v1", 1.5, 2.5)],
            "陆沉": [_clip("human-sword-block-v1", 0.0, 1.0)],
        }))
        acts = {figure["name"]: figure["acts"] for figure in diagram["figures"]}
        self.assertEqual(acts["苏晚"], ["闪避", "腾空"])
        self.assertEqual(acts["陆沉"], ["格挡"])
        self.assertEqual(diagram["strikes"], [])


class TextMarkTests(unittest.TestCase):
    def test_a_strike_is_read_from_the_sentence_only_when_the_clause_names_the_struck(self):
        diagram = _first(_plan("陆沉一拳打向苏晚，苏晚侧闪避开。"))
        strike, = diagram["strikes"]
        self.assertEqual((strike["attacker"], strike["target"], strike["kind"], strike["source"]), ("陆沉", "苏晚", "fist", "text"))
        self.assertEqual(next(f for f in diagram["figures"] if f["name"] == "苏晚")["acts"], ["闪避"])
        self.assertIn("可能读偏", " ".join(diagram["notes"]))

        nobody = _first(_plan("陆沉狠狠挥拳，汗水甩了出去。"))
        self.assertEqual(nobody["strikes"], [])

    def test_a_passive_sentence_still_knows_who_struck_whom(self):
        diagram = _first(_plan("苏晚被陆沉一脚踢飞。"))
        strike, = diagram["strikes"]
        self.assertEqual((strike["attacker"], strike["target"], strike["kind"], strike["reaction"]), ("陆沉", "苏晚", "kick", "被击退"))
        self.assertIsNotNone(strike["force_to"])

    def test_the_subject_carries_over_a_comma(self):
        strike, = _first(_plan("陆沉踏前半步，一掌拍向苏晚。"))["strikes"]
        self.assertEqual((strike["attacker"], strike["target"], strike["kind"]), ("陆沉", "苏晚", "palm"))

    def test_a_clip_and_the_sentence_about_the_same_blow_draw_one_line(self):
        diagram = _first(_plan("陆沉一拳打向苏晚。", clips={"陆沉": [_clip("human-punch-jab-v1", 0.5, 1.0)]}))
        self.assertEqual([strike["source"] for strike in diagram["strikes"]], ["clip"])
        self.assertEqual([node["source"] for node in diagram["nodes"]], ["clip"])
        self.assertNotIn("可能读偏", " ".join(diagram["notes"]))

    def test_a_blow_on_a_set_piece_marks_an_impact_point_there(self):
        diagram = _first(_plan("陆沉一拳砸向铁门。"))
        self.assertEqual(diagram["strikes"], [])
        effect, = diagram["effects"]
        self.assertEqual((effect["id"], effect["kind"], effect["center"], effect["source"]), ("VFX-01", "impact", [0.0, -4.0], "陆沉"))
        self.assertEqual(diagram["modes"], ["staging", "action", "vfx"])

    def test_an_effect_is_centred_on_whom_it_is_sent_at_and_says_who_stands_inside(self):
        diagram = _first(_plan("陆沉掌心的冲击波扑向苏晚，老周引下一道落雷。"))
        shock = next(effect for effect in diagram["effects"] if effect["kind"] == "shock")
        self.assertEqual(shock["center"], [1.0, 0.0])
        self.assertEqual(shock["from"], [-1.0, 0.0])
        self.assertEqual(shock["inside"], ["苏晚"])
        self.assertEqual([effect["id"] for effect in diagram["effects"]], ["VFX-01", "VFX-02"])
        self.assertEqual(diagram["modes"], ["staging", "action", "vfx"])
        low_x, low_z, high_x, high_z = diagram["bounds"]
        self.assertLessEqual(low_x, 1.0 - shock["radius_m"])
        self.assertGreaterEqual(high_x, 1.0 + shock["radius_m"])

    def test_an_effect_sent_at_a_set_piece_is_not_read_as_a_body_blow(self):
        diagram = _first(_plan("老周掌心的冲击波扑向木箱。"))
        self.assertEqual(diagram["strikes"], [])
        effect, = diagram["effects"]
        self.assertEqual((effect["kind"], effect["center"], effect["source"]), ("shock", [3.0, 0.0], "老周"))

    def test_an_effect_nobody_aims_sits_in_front_of_its_caster(self):
        effect, = _first(_plan("老周掌心腾起一团火球。"))["effects"]
        self.assertEqual((effect["kind"], effect["center"], effect["source"]), ("fire", [-2.0, 1.0], "老周"))

    def test_a_description_of_the_picture_draws_nothing(self):
        # Sentences of this kind fill the stored storyboards: light, set dressing, a posture, a negation.
        prose = ("苏晚左手提灯，灰尘在光柱里上下翻。火把火焰被压成两半向两侧舔开，烟尘未散。"
                 "陆沉肩背没有后撤，右脚后撤半步，钥匙环上闪过一线冷光；老周视线朝下躲开。"
                 "扳指内壁一道细裂纹，脚下碎石被鞋底推走，木屑向右侧炸开，远处一声爆炸。")
        plan = _plan(prose)
        plan = plan.model_copy(update={"actors": [actor.model_copy(update={"posture": "stand"}) for actor in plan.actors]})
        diagram = _first(plan)
        self.assertEqual((diagram["strikes"], diagram["effects"]), ([], []))
        self.assertEqual([figure["acts"] for figure in diagram["figures"]], [[], [], []])
        self.assertEqual(diagram["modes"], ["staging"])

    def test_a_dodge_in_the_text_counts_only_for_someone_a_strike_lands_on(self):
        self.assertEqual([figure["acts"] for figure in _first(_plan("苏晚侧闪避开，翻滚到木箱后。"))["figures"]], [[], [], []])


class DiagramTests(unittest.TestCase):
    def test_a_plain_scene_stays_a_plain_diagram_with_one_key_distance(self):
        plan = _plan("两人隔着木箱对视。")
        plan = plan.model_copy(update={"actors": [actor.model_copy(update={"posture": "stand"}) for actor in plan.actors]})
        diagram = _first(plan)
        self.assertEqual(diagram["modes"], ["staging"])
        self.assertEqual((diagram["strikes"], diagram["effects"], diagram["nodes"]), ([], [], []))
        self.assertNotIn("预演", diagram["title"])
        distance, = diagram["distances"]
        self.assertEqual((distance["a"], distance["b"], distance["meters"]), ("陆沉", "苏晚", 2.0))
        self.assertNotIn("■ 动作轨迹与受力", diagram["prompt"])
        self.assertIn("陆沉与苏晚之间拉一条细的标尺线，线上标「约 2 米」", diagram["prompt"])

    def test_someone_driven_back_along_a_walk_gets_the_route_named_instead_of_an_arrow(self):
        diagram = _first(_plan(
            "陆沉一脚踹向苏晚，苏晚踉跄。",
            shots=[StageShot(shot_id=1, camera_id="c1", action="陆沉一脚踹向苏晚，苏晚踉跄。",
                             overrides=[ActorOverride(name="苏晚", position=[0.2, 0.0], yaw_deg=-90)])],
        ))
        route, = diagram["routes"]
        self.assertEqual((route["name"], route["kind"], route["label"]), ("苏晚", "knockback", "击退方向"))
        self.assertIsNone(diagram["strikes"][0]["force_to"])
        self.assertIn("击退方向", diagram["prompt"])

    def test_the_prompt_and_the_legend_carry_every_mark(self):
        diagram = _first(_plan("陆沉一拳打向苏晚，陆沉拳上的冲击波扑向苏晚。", clips={"苏晚": [_clip("human-hit-chest-v1", 1.0, 1.6)]}))
        prompt = diagram["prompt"]
        for piece in ("■ 动作轨迹与受力", "拳轨迹：从陆沉出手的一侧指向苏晚", "受力方向", "■ 特效占位", "VFX-01 冲击波", "不画同一个人的多个分身", "白模假人"):
            self.assertIn(piece, prompt)
        self.assertLessEqual(len(prompt), prompt_data.load("blocking_diagram")["limits"]["prompt_chars"])
        marks = [row["mark"] for row in diagram["legend"]]
        for mark in ("陆沉", "苏晚", "CAM 1", "拳轨迹", "VFX-01"):
            self.assertIn(mark, marks)
        strike_row = next(row for row in diagram["legend"] if row["mark"] == "拳轨迹")
        self.assertIn("按分镜文字", strike_row["meaning"])
        self.assertTrue(all(set(row) == {"mark", "meaning", "color", "where"} for row in diagram["legend"]))

    def test_marks_are_capped(self):
        limits = prompt_data.load("action_marks")["limits"]
        clips = {"陆沉": [_clip("human-punch-jab-v1", index * 0.5, index * 0.5 + 0.4, f"k{index}") for index in range(10)]}
        diagram = _first(_plan(clips=clips))
        self.assertLessEqual(len(diagram["strikes"]), limits["max_strikes"])
        self.assertLessEqual(len(diagram["nodes"]), limits["max_nodes"])


def _two_shots(**changes) -> StagePlan:
    return _plan(shots=[
        StageShot(shot_id=1, camera_id="c1", subjects=["陆沉", "苏晚"]),
        StageShot(shot_id=2, camera_id="c1", subjects=["陆沉"], overrides=[ActorOverride(name="陆沉", position=[-2.5, 1.5], yaw_deg=90)]),
    ], **changes)


class EffectMarkerTests(unittest.TestCase):
    """Markers a person places on the desk: stored on the plan, edited by two operations, drawn first."""

    def test_placing_a_marker_takes_the_kinds_own_size_and_the_next_id(self):
        plan = apply_operations(_two_shots(), [
            {"op": "set_effect", "kind": "shock", "position": [1.0, 0.0], "source": "陆沉"},
            {"op": "set_effect", "kind": "crack", "position": [0.0, -4.0], "shot_ids": [2], "note": "门板开裂"},
        ], solve=False)
        first, second = plan.effects
        self.assertEqual((first.id, first.kind, first.radius_m, first.source, first.shot_ids), ("effect-01", "shock", 3.0, "陆沉", []))
        self.assertEqual((second.id, second.radius_m, second.shot_ids, second.note), ("effect-02", 1.0, [2], "门板开裂"))
        self.assertEqual(plan.source, "edited")

    def test_changing_a_marker_keeps_what_the_operation_leaves_out(self):
        plan = apply_operations(_two_shots(), [{"op": "set_effect", "id": "effect-07", "kind": "fire", "position": [1.0, 0.0], "radius_m": 4, "source": "苏晚"}], solve=False)
        moved = apply_operations(plan, [{"op": "set_effect", "id": "effect-07", "position": [2.0, 1.0]}], solve=False).effects[0]
        self.assertEqual((moved.id, moved.kind, moved.position, moved.radius_m, moved.source), ("effect-07", "fire", [2.0, 1.0], 4.0, "苏晚"))
        # A new kind brings its own size unless the operation gives one; an empty sender clears it.
        other = apply_operations(plan, [{"op": "set_effect", "id": "effect-07", "kind": "blast", "source": ""}], solve=False).effects[0]
        self.assertEqual((other.kind, other.radius_m, other.source), ("blast", 3.0, ""))

    def test_a_marker_the_stage_cannot_hold_is_refused_in_words(self):
        plan = _two_shots()
        for operation, piece in (
            ({"op": "set_effect", "kind": "tornado", "position": [0, 0]}, "特效种类只能是"),
            ({"op": "set_effect", "kind": "fire"}, "要给出位置"),
            ({"op": "set_effect", "kind": "fire", "position": [0, 0], "radius_m": 99}, "radius_m"),
            ({"op": "set_effect", "kind": "fire", "position": [0, 0], "source": "路人"}, "路人"),
            ({"op": "remove_effect", "id": "effect-09"}, "没有编号为「effect-09」的特效标记"),
        ):
            with self.assertRaises(StageEditError) as caught:
                apply_operations(plan, [operation], solve=False)
            self.assertIn(piece, str(caught.exception))
        full = plan.model_copy(update={"effects": [StageEffect(id=f"effect-{n:02d}", kind="fire", position=[0, 0]) for n in range(1, MAX_EFFECTS + 1)]})
        with self.assertRaises(StageEditError) as caught:
            apply_operations(full, [{"op": "set_effect", "kind": "fire", "position": [1, 1]}], solve=False)
        self.assertIn("已满", str(caught.exception))

    def test_removing_a_marker_and_a_plan_that_names_an_unknown_sender(self):
        plan = apply_operations(_two_shots(), [{"op": "set_effect", "kind": "bolt", "position": [0, 0]}], solve=False)
        self.assertEqual(apply_operations(plan, [{"op": "remove_effect", "id": "effect-01"}], solve=False).effects, [])
        with self.assertRaises(ValueError):
            _two_shots(effects=[StageEffect(id="e1", kind="fire", position=[0, 0], source="路人")])
        with self.assertRaises(ValueError):
            _two_shots(effects=[StageEffect(id="e1", kind="fire", position=[0, 0]), StageEffect(id="e1", kind="bolt", position=[1, 0])])

    def test_the_diagram_draws_a_marker_in_its_shots_first_and_says_it_was_placed_by_hand(self):
        plan = _two_shots(effects=[
            StageEffect(id="effect-01", kind="shock", position=[1.0, 0.0], radius_m=1.5, source="陆沉", shot_ids=[2], note="掌风"),
            StageEffect(id="effect-02", kind="collapse", position=[0.0, -4.0]),
        ])
        first, second = blocking_diagram.build(plan)["diagrams"]
        self.assertEqual([(effect["id"], effect["kind"]) for effect in first["effects"]], [("VFX-01", "collapse")])
        self.assertEqual(first["modes"][-1], "vfx")
        shock, collapse = second["effects"]
        self.assertEqual((shock["id"], shock["name"], shock["radius_m"], shock["rings"], shock["read_from"], shock["marker_id"]),
                         ("VFX-01", "掌风", 1.5, 1, "manual", "effect-01"))
        # The sender has walked in this shot: the arrow starts where the diagram draws him.
        self.assertEqual(shock["from"], [-1.0, 0.0])
        self.assertEqual(shock["inside"], ["苏晚"])
        self.assertEqual(collapse["source"], "")
        row = next(row for row in second["legend"] if row["mark"] == "VFX-01")
        self.assertIn("手动放置", row["meaning"])
        self.assertIn("VFX-01 掌风", second["prompt"])
        self.assertNotIn("可能读偏", " ".join(second["notes"]))

    def test_the_text_does_not_repeat_an_effect_a_marker_already_shows(self):
        plan = _plan("陆沉掌心的冲击波扑向苏晚。", effects=[StageEffect(id="effect-01", kind="shock", position=[1.2, 0.1])])
        effect, = _first(plan)["effects"]
        self.assertEqual(effect["read_from"], "manual")

    def test_a_marker_whose_only_shot_is_gone_goes_with_it_and_a_replan_keeps_the_rest(self):
        brief = SceneBrief(
            scene_id="E1S09", location="旧仓库 夜", characters=["陆沉", "苏晚"], aspect_ratio="16:9",
            shots=[ShotSpec(1, ["陆沉", "苏晚"], "", "全景", "平视", "固定", "陆沉与苏晚对峙"),
                   ShotSpec(2, ["陆沉", "苏晚"], "", "中景", "平视", "固定", "陆沉逼近苏晚")],
        )
        plan = apply_operations(build_plan(brief), [
            {"op": "set_effect", "kind": "shock", "position": [0.5, 0.0], "source": "陆沉"},
            {"op": "set_effect", "kind": "fire", "position": [1.0, 1.0], "shot_ids": [2]},
        ], solve=False)
        shorter = SceneBrief(scene_id=brief.scene_id, location=brief.location, characters=brief.characters,
                             aspect_ratio=brief.aspect_ratio, shots=brief.shots[:1])
        again = build_plan(shorter, blocking_from=plan)
        self.assertEqual([(effect.id, effect.kind, effect.source) for effect in again.effects], [("effect-01", "shock", "陆沉")])


class WordingTests(unittest.TestCase):
    def test_every_clip_in_the_tables_is_one_the_desk_knows(self):
        known = set(prompt_data.load("stage_brief")["clip_names"])
        tables = prompt_data.load("action_marks")["clips"]
        listed = [*tables["strike"], *tables["react"], *tables["evade"], *tables["guard"], *tables["air"]]
        self.assertEqual([clip for clip in listed if clip not in known], [])

    def test_every_word_list_compiles_and_every_kind_has_its_label(self):
        data = prompt_data.load("action_marks")
        for pattern, kind in data["text"]["strike"]:
            re.compile(pattern)
            self.assertIn(kind, data["strike_kinds"])
        for pattern, kind in data["text"]["react"]:
            re.compile(pattern)
            self.assertIn(kind, data["badges"])
            self.assertIn(kind, data["reaction_rank"])
        for pattern, kind in data["effects"]:
            re.compile(pattern)
            self.assertIn(kind, data["effect_kinds"])
        self.assertIn(data["impact_kind"], data["effect_kinds"])
        for kind, item in data["effect_kinds"].items():
            self.assertRegex(kind, r"^[a-z][a-z_]{1,29}$")
            self.assertTrue(data["effect_radius"]["low"] <= item["radius_m"] <= data["effect_radius"]["high"])
        self.assertEqual(action_marks.mode_label(["staging"]), data["modes"]["staging"])

    def test_the_module_keeps_its_wording_in_the_data_file(self):
        source = Path(action_marks.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search("[\u4e00-\u9fff]", source))


if __name__ == "__main__":
    unittest.main()
