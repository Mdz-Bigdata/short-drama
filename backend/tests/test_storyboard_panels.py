import unittest

from unittest.mock import patch

from app.core.screenwriting.durations import supported_shot_durations
from app.core.shot_table_rules import audit_shot_table
from app.core.video_references import split_shot_seconds
from app.core.storyboard_panels import MAX_PANELS, consolidate_panels, fit_panels, panel_limit, repeats, select_panels


def _shot(number: int, desc: str, size: str = "中景", angle: str = "平视", characters=("沈知微",), **extra) -> dict:
    return {"shot_id": number, "desc": desc, "size": size, "angle": angle, "characters": list(characters), **extra}


class StoryboardPanelTests(unittest.TestCase):
    def test_a_merge_never_pushes_in_and_then_pulls_back_inside_one_clip(self):
        shots = [
            _shot(1, "沈知微跪在堂中", size="中景", duration="4s", motion="缓慢推近"),
            _shot(2, "她抬眼", size="近景", duration="4s"),
            _shot(3, "她退后半步", size="中景", duration="4s"),
        ]

        panels = consolidate_panels(shots, video_model="seedance2.5")

        self.assertEqual(len(panels), 2)
        self.assertEqual(panels[0]["motion"], "缓慢推近，随后推近至近景")
        self.assertEqual(panels[1]["shot_id"], 3)

    def test_a_beat_too_short_to_stand_alone_joins_without_a_conflicting_move(self):
        shots = [
            _shot(1, "沈知微跪在堂中", size="近景", duration="2s", motion="缓慢推近"),
            _shot(2, "她退后半步", size="中景", duration="2s"),
        ]

        panels = consolidate_panels(shots, video_model="seedance2.5")

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["motion"], "缓慢推近")

    def test_a_short_table_is_drawn_as_it_is(self):
        shots = [
            _shot(1, "侯府正堂全景，众人分列两侧", size="远景", characters=("沈知微", "陆昀")),
            _shot(2, "沈知微跪在堂中，抬眼看向上首", size="中景"),
            _shot(3, "陆昀握紧扶手，指节发白", size="特写", angle="低机位", characters=("陆昀",)),
        ]

        panels = select_panels(shots)

        self.assertEqual([panel["shot_id"] for panel in panels], [1, 2, 3])

    def test_a_panel_with_the_same_setup_and_picture_is_dropped(self):
        first = _shot(1, "沈知微跪在堂中，双手交叠放在膝上，抬眼看向上首")
        same = _shot(2, "沈知微跪在堂中，双手交叠放在膝上，抬眼望向上首")
        moved = _shot(3, "沈知微跪在堂中，双手交叠放在膝上，抬眼看向上首", size="特写", angle="俯拍")

        self.assertTrue(repeats(first, same))
        self.assertEqual([panel["shot_id"] for panel in select_panels([first, same])], [1])
        # Word-for-word the same picture is a repeat even with a new size and angle.
        self.assertTrue(repeats(first, moved))

    def test_a_new_action_in_the_same_setup_is_kept(self):
        first = _shot(1, "沈知微跪在堂中，抬眼看向上首")
        acts = _shot(2, "沈知微猛地起身，袖中金针滑落在青砖上")

        self.assertFalse(repeats(first, acts))

    def test_a_long_beat_table_becomes_one_page_covering_the_whole_scene(self):
        sizes = ("远景", "全景", "中景", "近景", "特写")
        angles = ("平视", "俯拍", "仰拍", "侧拍")
        shots = [
            _shot(number, f"第{number}拍：动作{number}，人物移动到第{number}个位置", size=sizes[number % 5], angle=angles[number % 4])
            for number in range(1, 79)
        ]

        panels = select_panels(shots)

        self.assertEqual(len(panels), MAX_PANELS)
        ids = [panel["shot_id"] for panel in panels]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual((ids[0], ids[-1]), (1, 78), "the page opens on the scene's start and ends on its ending")
        for previous, panel in zip(panels, panels[1:]):
            self.assertFalse(repeats(previous, panel))

    def test_the_input_is_not_modified(self):
        shots = [_shot(1, "a"), _shot(2, "b")]
        panels = select_panels(shots)
        panels[0]["shot_id"] = 99
        self.assertEqual(shots[0]["shot_id"], 1)



class ConsolidatePanelTests(unittest.TestCase):
    def test_second_by_second_beats_of_one_character_become_one_clip(self):
        shots = [
            _shot(1, "沈知微跪在堂中", size="中景", duration="2s", dialogue=""),
            _shot(2, "她猛地抬眼", size="近景", duration="2s", dialogue="沈知微：这手，不是我的。"),
            _shot(3, "瞳孔骤缩", size="特写", duration="1s"),
        ]

        panels = consolidate_panels(shots, video_model="seedance2.5")

        self.assertEqual(len(panels), 1)
        panel = panels[0]
        self.assertEqual(panel["desc"], "沈知微跪在堂中；随后她猛地抬眼；随后瞳孔骤缩")
        self.assertEqual(panel["dialogue"], "沈知微：这手，不是我的。")
        self.assertEqual(panel["duration"], "5s")
        self.assertIn("推近至特写", panel["motion"])
        self.assertEqual(panel["merged_shots"], [2, 3])

    def test_a_new_character_a_new_place_or_a_reveal_starts_a_new_panel(self):
        base = _shot(1, "沈知微跪在堂中", duration="6s")
        enters = _shot(2, "陆昀推门而入", characters=("沈知微", "陆昀"), duration="5s")
        elsewhere = _shot(3, "药库里烛火摇动", scene="侯府药库", duration="5s")
        reveal = _shot(4, "契纸上的落款是她的名字", duration="5s", narrative_purpose="反转揭露")

        self.assertEqual(len(consolidate_panels([base, enters])), 2)
        self.assertEqual(len(consolidate_panels([{**base, "scene": "正堂"}, elsewhere])), 2)
        self.assertEqual(len(consolidate_panels([base, reveal])), 2)

    def test_a_panel_never_grows_past_one_steady_clip(self):
        shots = [_shot(number, f"动作{number}", size=("中景", "近景")[number % 2], duration="6s") for number in range(1, 7)]

        panels = consolidate_panels(shots, video_model="seedance2.5")

        self.assertTrue(all(int(panel["duration"].rstrip("s")) <= 15 for panel in panels))
        self.assertEqual(len(panels), 3)

    def test_a_reverse_shot_is_a_cut_not_a_camera_swing(self):
        two = _shot(1, "沈知微与陆昀隔案对视", characters=("沈知微", "陆昀"), duration="5s")
        push = _shot(2, "陆昀眉心收紧", size="近景", characters=("陆昀",), duration="4s")
        reverse = _shot(3, "沈知微抿住嘴唇", size="近景", characters=("沈知微",), duration="4s")
        shoulder = _shot(4, "越过陆昀肩头看沈知微", angle="过肩", characters=("陆昀", "沈知微"), duration="4s")

        panels = consolidate_panels([two, push, reverse, shoulder], video_model="seedance2.5")

        # Pushing in on 陆昀 from the two-shot is one move; cutting to 沈知微 and the over-the-shoulder are cuts.
        self.assertEqual([panel["shot_id"] for panel in panels], [1, 3, 4])

    def test_a_change_of_camera_height_is_a_new_setup(self):
        level = _shot(1, "沈知微与陆昀隔案对视", characters=("沈知微", "陆昀"), duration="4s")
        low = _shot(2, "陆昀沉下脸", size="近景", angle="仰拍", characters=("陆昀",), duration="4s")

        self.assertEqual(len(consolidate_panels([level, low])), 2)

    def test_blank_rows_are_never_drawn(self):
        shots = [
            _shot(1, "沈知微走进药库", duration="6s"),
            _shot(2, "留白：本场无新的、独立成拍的信息", size="留白", angle="待补"),
            _shot(3, "", size="中景"),
        ]

        self.assertEqual([panel["shot_id"] for panel in consolidate_panels(shots)], [1])
        self.assertEqual([panel["shot_id"] for panel in select_panels(shots)], [1])

    def test_a_slight_tilt_is_still_eye_level_and_a_split_second_beat_rides_along(self):
        first = _shot(1, "沈知微抬眼", size="近景", angle="平视略仰", duration="5s")
        tilt = _shot(2, "她的视线压向画右", size="近景", angle="平视略俯", duration="5s")
        flash = _shot(3, "瞳孔一缩", size="大特写", angle="低角度", duration="1s")

        panels = consolidate_panels([first, tilt, flash], video_model="seedance2.5")

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["merged_shots"], [2, 3])

    def test_a_far_jump_in_framing_is_not_pushed_in_one_move(self):
        wide = _shot(1, "侯府正堂全景", size="大远景", duration="6s")
        eye = _shot(2, "她的一只眼", size="大特写", duration="5s")

        self.assertEqual(len(consolidate_panels([wide, eye])), 2)

    def test_a_scene_holds_only_as_many_panels_as_its_seconds_allow(self):
        self.assertEqual(panel_limit("5s"), 1)
        self.assertEqual(panel_limit("9秒"), 1)
        self.assertEqual(panel_limit("10s"), 2)
        self.assertEqual(panel_limit("15s"), 3)
        self.assertEqual(panel_limit("45s"), MAX_PANELS)
        self.assertEqual(panel_limit("3分钟"), MAX_PANELS)
        self.assertEqual(panel_limit("2s"), 1)

    def test_a_scene_without_a_length_is_only_held_to_one_page(self):
        self.assertEqual(panel_limit(""), MAX_PANELS)
        self.assertEqual(panel_limit(None), MAX_PANELS)

    def test_the_seconds_per_panel_can_be_raised_for_fewer_images(self):
        with patch.dict("os.environ", {"STORYBOARD_SECONDS_PER_PANEL": "6"}):
            self.assertEqual(panel_limit("11s"), 1)
            self.assertEqual(panel_limit("12s"), 2)
        with patch.dict("os.environ", {"STORYBOARD_SECONDS_PER_PANEL": "1"}):
            self.assertEqual(panel_limit("8s"), 2)  # never below what one clip can be
        with patch.dict("os.environ", {"STORYBOARD_SECONDS_PER_PANEL": "4"}):
            self.assertEqual(panel_limit("8s"), 2)

    def test_fitting_merges_the_least_different_neighbours_and_keeps_every_word(self):
        panels = [
            _shot(1, "沈知微跪在堂中，抬眼看向上首", duration="4s", dialogue="沈知微：我不认。", sound="雨声"),
            _shot(2, "沈知微跪在堂中，抬眼看向门口", duration="4s", dialogue="无", sound="脚步声"),
            _shot(3, "陆昀推门而入，披风滴水", size="全景", angle="低机位", characters=("陆昀",), duration="4s", dialogue="陆昀：够了。"),
        ]

        fitted = fit_panels(panels, 2, video_model="seedance2.5")

        self.assertEqual(len(fitted), 2)
        self.assertEqual(fitted[0]["desc"], "沈知微跪在堂中，抬眼看向上首；随后沈知微跪在堂中，抬眼看向门口")
        self.assertEqual(fitted[0]["dialogue"], "沈知微：我不认。")
        self.assertEqual(fitted[0]["sound"], "雨声；脚步声")
        self.assertEqual(fitted[0]["duration"], "8s")
        self.assertEqual(fitted[0]["merged_shots"], [2])
        self.assertEqual(fitted[1]["shot_id"], 3)

    def test_a_merged_panel_takes_the_cast_of_both_and_their_finished_length(self):
        panels = [
            _shot(1, "靴底压住手背", duration="4秒（生成）｜1.8秒（成片）", dialogue="无"),
            _shot(2, "陆昀俯视", characters=("陆昀",), duration="生成4秒／成片1.6秒", dialogue="陆昀：贱籍碰剑。"),
            _shot(3, "沈知微不抬眼", duration="5秒（生成）｜1.6秒（成片）", dialogue="沈知微：布脏了。"),
        ]

        fitted = fit_panels(panels, 1, video_model="seedance2.5")

        self.assertEqual(len(fitted), 1)
        self.assertEqual(fitted[0]["duration"], "5s")
        self.assertEqual(fitted[0]["characters"], ["沈知微", "陆昀"])
        self.assertEqual(fitted[0]["dialogue"], "陆昀：贱籍碰剑。；沈知微：布脏了。")
        self.assertEqual(fitted[0]["merged_shots"], [2, 3])

    def test_nothing_is_merged_past_what_one_clip_can_hold(self):
        panels = [_shot(1, "沈知微跪下", duration="10s"), _shot(2, "陆昀转身离开", duration="10s")]
        self.assertEqual(len(fit_panels(panels, 1, video_model="MiniMax-H3")), 2)

    def test_a_beat_that_must_be_seen_alone_keeps_its_panel(self):
        panels = [
            _shot(1, "沈知微捧起信", duration="4s"),
            _shot(2, "信上落款竟是陆昀", duration="4s", narrative_purpose="反转揭露"),
        ]
        self.assertEqual(len(fit_panels(panels, 1, video_model="seedance2.5")), 2)

    def test_a_table_within_the_limit_is_left_as_it_is(self):
        panels = [_shot(1, "沈知微跪下", duration="4s"), _shot(2, "陆昀转身", duration="4s")]
        self.assertEqual(fit_panels(panels, 2, video_model="seedance2.5"), panels)

    def test_a_fifteen_second_scene_passes_through_every_step(self):
        for model in ("MiniMax-H3", "doubao-seedance-2-0-260128", "seedance2.5", "kling-v3", "some-new-model", ""):
            self.assertIn(15, supported_shot_durations(model), model)
            panels = [_shot(1, "沈知微跪下", duration="8s"), _shot(2, "陆昀转身离开", angle="俯拍", duration="7s")]
            self.assertEqual([panel["duration"] for panel in fit_panels(panels, 1, video_model=model)], ["15s"], model)
            audited = audit_shot_table([_shot(1, "沈知微跪下", duration="15s")], video_model=model)
            self.assertEqual(audited.shots[0]["duration"], "15s", model)
            self.assertEqual(split_shot_seconds(15, model), [15], model)

    def test_seedance_two_point_five_takes_a_thirty_second_scene(self):
        model = "doubao-seedance-2-5-pro"
        self.assertIn(30, supported_shot_durations(model))
        self.assertEqual(split_shot_seconds(30, model), [30])
        self.assertEqual(audit_shot_table([_shot(1, "沈知微跪下", duration="30s")], video_model=model).shots[0]["duration"], "30s")
        # One clip every ten seconds, the shortest this model is worth using.
        self.assertEqual([panel_limit(f"{seconds}s", video_model=model) for seconds in (10, 19, 20, 30)], [1, 1, 2, 3])
        panels = [_shot(1, "沈知微跪下", duration="15s"), _shot(2, "陆昀转身离开", angle="俯拍", duration="15s")]
        self.assertEqual([panel["duration"] for panel in fit_panels(panels, 1, video_model=model)], ["30s"])
        self.assertEqual(len(fit_panels(panels, 1, video_model="MiniMax-H3")), 2)

    def test_automatic_merging_still_stops_at_a_steady_length_within_the_limit(self):
        panels = [_shot(1, "沈知微跪下", duration="10s"), _shot(2, "她低头", duration="10s")]
        self.assertEqual(len(consolidate_panels(panels, video_model="seedance2.5")), 2)

    def test_a_chosen_seconds_per_panel_overrides_the_models_default(self):
        with patch.dict("os.environ", {"STORYBOARD_SECONDS_PER_PANEL": "5"}):
            self.assertEqual(panel_limit("30s", video_model="seedance2.5"), 6)
        with patch.dict("os.environ", {"STORYBOARD_SECONDS_PER_PANEL": "30"}):
            self.assertEqual(panel_limit("30s", video_model="seedance2.5"), 1)

    def test_empty_lines_do_not_pile_up_when_beats_join(self):
        shots = [_shot(1, "沈知微跪下", duration="4s", dialogue="无"), _shot(2, "她低头", duration="4s", dialogue="无")]
        self.assertEqual(consolidate_panels(shots, video_model="seedance2.5")[0]["dialogue"], "无")


if __name__ == "__main__":
    unittest.main()
