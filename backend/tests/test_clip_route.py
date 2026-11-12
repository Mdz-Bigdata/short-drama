# -*- coding: utf-8 -*-
"""第 5 阶段每段视频的接法：六条规则按优先级定，做不到的报错不降级。"""

import unittest

from app.core import clip_route as cr
from app.core.clip_route import ClipFacts as C

ALL = ("text", "first_frame", "first_last_frame", "multi_reference", "multimodal")
NO_FIRST_LAST = ("text", "first_frame", "multi_reference")
FRAMES_ONLY = ("text", "first_frame", "first_last_frame")


def route(clips, modes=ALL, **kwargs):
    return cr.route_clips(clips, modes, **kwargs)


class LongTakeTests(unittest.TestCase):
    def test_parts_of_a_long_take_are_first_last_and_chain(self):
        routes = route([C(1, "S1", part=1, parts=2, storyboards=3), C(2, "S1", part=2, parts=2, storyboards=2)])
        self.assertEqual(routes[1].kind, cr.FIRST_LAST)
        self.assertIsNone(routes[1].chain_from)
        self.assertEqual((routes[2].kind, routes[2].chain_from), (cr.FIRST_LAST, 1))
        self.assertEqual(routes[2].provider_mode(), "first_last_frame")

    def test_no_downgrade(self):
        no_model = route([C(1, "S1", part=2, parts=2, storyboards=2)], NO_FIRST_LAST)[1]
        self.assertIsNone(no_model.kind)
        self.assertIn("不支持首尾帧", no_model.error)
        one_board = route([C(1, "S1", part=1, parts=2, storyboards=1)])[1]
        self.assertIn("只有一张分镜", one_board.error)
        self.assertTrue(one_board.decided)

    def test_attached_media_cannot_ride_a_long_take(self):
        self.assertIn("送不进去", route([C(1, "S1", parts=2, storyboards=2, attached_media=True)])[1].error)

    def test_a_long_take_continuing_a_scene_opens_on_the_previous_tail(self):
        routes = route([C(1, "S1", storyboards=1), C(2, "S1", part=1, parts=2, storyboards=2)])
        self.assertEqual((routes[2].kind, routes[2].chain_from), (cr.FIRST_LAST, 1))


class SceneChainTests(unittest.TestCase):
    def test_second_clip_on_takes_the_tail_frame(self):
        routes = route([C(1, "S1", characters=("林婉",), storyboards=2), C(2, "S1", characters=("林婉",), storyboards=1, subject_refs=True)])
        second = routes[2]
        self.assertEqual((second.kind, second.chain_from, second.provider_mode()), (cr.TAILFRAME, 1, "first_frame"))
        self.assertEqual(second.fallbacks, (cr.TAILREF, cr.INDEPENDENT))

    def test_extension_steps_only_when_the_model_can_extend(self):
        second = route([C(1, "S1"), C(2, "S1")], can_extend=True)[2]
        self.assertEqual(second.fallbacks, (cr.TAILREF, cr.EXTEND, cr.EXTEND, cr.INDEPENDENT))

    def test_a_new_face_or_a_hero_prop_makes_it_tailref(self):
        routes = route([
            C(1, "S1", characters=("林婉",)), C(2, "S1", characters=("林婉", "沈砚")), C(3, "S1", characters=("林婉", "沈砚"), hero_prop=True),
        ])
        self.assertEqual(routes[2].kind, cr.TAILREF)
        self.assertIn("沈砚", routes[2].reason)
        self.assertEqual(routes[2].provider_mode(), "multi_reference")
        self.assertEqual(routes[2].fallbacks, (cr.INDEPENDENT,))
        self.assertEqual(routes[3].kind, cr.TAILREF)

    def test_without_reference_modes_a_new_face_still_chains_on_the_frame(self):
        routes = route([C(1, "S1", characters=("林婉",)), C(2, "S1", characters=("沈砚",))], FRAMES_ONLY)
        self.assertEqual(routes[2].kind, cr.TAILFRAME)
        self.assertEqual(routes[2].fallbacks, (cr.INDEPENDENT,))

    def test_a_new_scene_starts_fresh(self):
        routes = route([C(1, "S1", storyboards=1), C(2, "S2", storyboards=1), C(3, "S1", storyboards=1)])
        self.assertIsNone(routes[2].chain_from)
        self.assertIsNone(routes[3].chain_from, "隔了一场再回来不算连续出片")

    def test_chaining_can_be_turned_off(self):
        routes = route([C(1, "S1", storyboards=1), C(2, "S1", storyboards=1)], scene_chain=False)
        self.assertEqual(routes[2].kind, cr.FIRST_FRAME)


class ReferenceRuleTests(unittest.TestCase):
    def test_a_solo_scene_with_references_is_decided_without_the_judge(self):
        solo = route([C(1, "S1", storyboards=3, subject_refs=True)])
        self.assertEqual(solo[1].kind, cr.REFERENCE)
        self.assertEqual(cr.undecided_keys(solo), set())

    def test_attached_media_is_multimodal_or_an_error(self):
        self.assertEqual(route([C(1, "S1", attached_media=True)])[1].provider_mode(), "multimodal")
        self.assertIn("收不下", route([C(1, "S1", attached_media=True)], NO_FIRST_LAST)[1].error)
        chained = route([C(1, "S1"), C(2, "S1", attached_media=True)])[2]
        self.assertEqual((chained.kind, chained.provider_mode()), (cr.TAILREF, "multimodal"))

    def test_hero_prop_shot_opens_a_scene_with_references(self):
        routes = route([C(1, "S1", storyboards=2, hero_prop=True), C(2, "S1")])
        self.assertEqual((routes[1].kind, routes[1].rule), (cr.REFERENCE, "hero_prop"))

    def test_single_storyboard(self):
        with_refs = route([C(1, "S1", storyboards=1, subject_refs=True), C(2, "S1")])[1]
        self.assertEqual((with_refs.kind, with_refs.rule), (cr.REFERENCE, "single_storyboard"))
        bare = route([C(1, "S1", storyboards=1), C(2, "S1")])[1]
        self.assertEqual((bare.kind, bare.provider_mode()), (cr.FIRST_FRAME, "first_frame"))

    def test_everything_else_is_left_to_the_judge(self):
        routes = route([C(1, "S1", storyboards=3, subject_refs=True), C(2, "S1")], scene_chain=False)
        self.assertIsNone(routes[1].kind)
        self.assertEqual(cr.undecided_keys(routes), {1, 2})



class RealPersonTests(unittest.TestCase):
    def test_a_real_face_never_carries_frames_and_is_not_chained_from(self):
        routes = route([
            C(1, "S1", storyboards=1), C(2, "S1", storyboards=1, frameless=True, subject_refs=True), C(3, "S1", storyboards=1),
        ])
        self.assertEqual((routes[2].kind, routes[2].rule, routes[2].chain_from), (cr.REFERENCE, "real_person", None))
        self.assertIsNone(routes[3].chain_from, "上一段画着真人脸，尾帧送不出去")
        self.assertEqual(routes[3].kind, cr.FIRST_FRAME)

    def test_a_real_face_inside_a_long_take_is_an_error(self):
        self.assertIn("真人演员", route([C(1, "S1", part=1, parts=2, storyboards=2, frameless=True)])[1].error)


if __name__ == "__main__":
    unittest.main()
