# -*- coding: utf-8 -*-
"""Timeline rules for clip prompts (round 12, from the WeChat article on timelines for multi-shot clips).

A timeline manages the order of events, not only seconds: each moment's span in its block head, dialogue that fits
its moment, one main change per segment, a cut that keeps people where they are, a reaction after its trigger,
a back view written with what a back view shows, a calm camera on a listener's close-up, off-screen voices that
are heard but never seen, and a last pose held to the end. Every sentence comes from data.
"""

import unittest
from unittest.mock import patch

from app.core import clip_skeleton, h3_native, h3_sound_design, prompt_budget, prompt_data, slice_video, style_packs
from app.core.shot_motion_contract import ShotMotionContract
from app.core.video_prompt_engine import (
    ShotPromptInput, back_view, compile_shot_prompt, dialogue_speakers, dialogue_voices, format_dialogue, listener_shot,
    prop_holders, reaction_triggers, trigger_words,
)
from app.schema.production import StoryboardPanel
from tests.test_stage_five_queue import StageFiveQueueTests, _task

CLIP = prompt_data.load("clip_prompt")
WORDS = prompt_data.load("video_prompt_engine")
SKELETON = prompt_data.load("clip_skeleton")


def _shot(**overrides) -> ShotPromptInput:
    base = dict(
        shot_index=1, duration_seconds=5, shot_size="MS", camera_movement="固定机位", subject_action="林夏坐在书桌后",
        scene="书房", blocking="林夏坐在书桌后", start_state="林夏坐在书桌后", end_state="林夏坐定", characters=["林夏"],
    )
    base.update(overrides)
    return ShotPromptInput(**base)


def _compile(model: str = "seedance2.0", **overrides):
    return compile_shot_prompt(style_packs.FILM_35MM, _shot(**overrides), model=model)


def _beat(text: str, *, size: str = "MS", motion: str = "固定机位", seconds=None, end: str | None = None, start: str = "", camera: str = ""):
    sections = {
        "locks": "[空间锚]书房", "camera": camera or f"景别：{size}；运镜：{motion}", "subject": f"画面：{text}。",
        "dialogue": "无台词，人物闭口。", "end_state": f"落幅：{text}停住" if end is None else end,
    }
    return slice_video.Beat(sections=sections, size=size, motion=motion, seconds=seconds, start_state=start)


class SpanTests(unittest.TestCase):
    """Rule 2: each moment's span in its block head, 0 to the clip's end with no gap."""

    def test_spans_cover_the_clip_without_a_gap_and_end_at_its_length(self):
        piece = slice_video.Slice("E1S01", [0, 1, 2], 10, beat_seconds=[3.0, 4.0, 3.0])
        self.assertEqual(slice_video.spans(piece), [(0.0, 3.0), (3.0, 7.0), (7.0, 10.0)])
        uneven = slice_video.Slice("E1S01", [0, 1], 12, beat_seconds=[4.03, 7.07])
        bounds = slice_video.spans(uneven)
        self.assertEqual(bounds[0][0], 0.0)
        self.assertEqual(bounds[0][1], bounds[1][0])
        self.assertEqual(bounds[-1][1], 12)

    def test_the_spans_agree_with_the_h3_timecodes(self):
        piece = slice_video.Slice("E1S01", [0, 1, 2], 13, beat_seconds=[4.03, 3.37, 4.62])
        starts = h3_native.shot_starts(piece.beat_seconds, piece.seconds)
        self.assertEqual([h3_native.timecode(start) for start, _ in slice_video.spans(piece)[1:]], starts[1:])

    def test_the_block_head_carries_the_span_with_an_em_dash(self):
        beats = [_beat("按手印", seconds=(0.0, 3.0)), _beat("睁眼", size="CU", seconds=(3.0, 7.0)), _beat("松手", seconds=(7.0, 10.0))]
        text = slice_video.compile_prompt(beats, model="seedance2.0").text
        self.assertIn("【镜头1/3｜MS｜固定机位｜0—3秒】", text)
        self.assertIn("【镜头2/3｜CU｜固定机位｜3—7秒】", text)
        self.assertIn("【镜头3/3｜MS｜固定机位｜7—10秒】", text)
        self.assertEqual(slice_video.beat_count(text), 3)
        self.assertIn("{start}—{end}", CLIP["beat_span"])
        # Seedance 2.5's 30 s timeline detection matches "-" and "–", not the em dash.
        from app.core.seedance_video_director import _TIMESTAMP_PATTERN

        self.assertIsNone(_TIMESTAMP_PATTERN.search(text))

    def test_the_data_flag_turns_the_spans_off(self):
        with patch.object(slice_video, "BEAT_SPANS", False):
            self.assertEqual(slice_video.span_text((0.0, 3.0)), "")
        self.assertEqual(slice_video.span_text((3.333, 7.0)), "3.3—7秒")
        self.assertEqual(slice_video.span_text(None), "")


class DialogueFloorTests(unittest.TestCase):
    """Rule 3: a moment gets at least the seconds its dialogue takes at its emotion's pace."""

    def _shots(self):
        return [
            {"shot_id": 1, "scene_id": "E1S02", "duration": "3", "desc": "陈默转身面向林夏", "dialogue": "陈默：那份合同，是你签的。"},
            {"shot_id": 2, "scene_id": "E1S02", "duration": "4", "desc": "林夏听着", "dialogue": ""},
            {"shot_id": 3, "scene_id": "E1S02", "duration": "3", "desc": "林夏冷声回应", "dialogue": "林夏：查到了，又能怎样。",
             "motion_contract": {"expression": "冷笑"}},
        ]

    def test_each_moment_is_floored_by_its_dialogue_and_the_total_rises(self):
        shots = self._shots()
        floors = [slice_video.dialogue_floor(shot) for shot in shots]
        self.assertEqual(floors[1], 0.0)
        [piece] = slice_video.plan(shots, ceiling=15, planned={"E1S02": 8})
        for planned, floor in zip(piece.beat_seconds, floors):
            self.assertGreaterEqual(planned + 0.01, floor)
        self.assertGreaterEqual(piece.seconds, sum(floors))
        self.assertGreater(piece.seconds, 8, "the board's 8 s cannot hold both lines")

    def test_spare_time_still_goes_by_the_plan(self):
        shots = self._shots()
        [piece] = slice_video.plan(shots, ceiling=15, planned={"E1S02": 14})
        self.assertEqual(piece.seconds, 14)
        self.assertAlmostEqual(sum(piece.beat_seconds), 14, places=1)
        self.assertGreater(piece.beat_seconds[1], 0)

    def test_hand_set_lengths_are_not_floored(self):
        shot = {**self._shots()[2], "visual": {"duration_seconds": 2}}
        self.assertEqual(slice_video.dialogue_floor(shot), 0.0)

    def test_floors_over_the_ceiling_split_the_clip_in_order(self):
        line = "林夏：" + "这件事我早就知道了，" * 3 + "你还想瞒我多久。"
        shots = [{"shot_id": k, "scene_id": "E1S09", "duration": "3", "desc": "林夏说话", "dialogue": line} for k in (1, 2, 3)]
        pieces = slice_video.plan(shots, ceiling=15, planned={"E1S09": 9})
        self.assertGreater(len(pieces), 1)
        self.assertEqual([index for piece in pieces for index in piece.indexes], [0, 1, 2])
        self.assertTrue(all(piece.seconds <= 15 for piece in pieces))


class OneChangeTests(unittest.TestCase):
    """Rules 4 + 9 in the body, where the 2000-character cut does not reach."""

    def test_single_and_multi_moment_clips_say_one_change_per_segment(self):
        compiled = _compile()
        self.assertEqual(compiled.sections["one_change"], CLIP["one_change"] + "。")
        self.assertIn("one_change", prompt_budget.FIXED_SECTIONS, "a restated rule: not measured against the body budget")
        self.assertLess(compiled.text.index("【结构声明】"), compiled.text.index(CLIP["one_change"]))
        text = slice_video.compile_prompt([_beat("坐下"), _beat("抬眼")], model="seedance2.0").text
        self.assertIn(CLIP["one_change"], text.split("Pa2")[0])

    def test_a_fight_keeps_its_own_tempo(self):
        self.assertNotIn(CLIP["one_change"], _compile(situations=["fight"]).text)
        self.assertNotIn(CLIP["one_change"], slice_video.compile_prompt([_beat("出拳"), _beat("格挡")], model="seedance2.0", fight=True).text)

    def test_an_unlabelled_line_or_a_narrator_makes_no_listener(self):
        self.assertFalse(listener_shot(_shot(dialogue="你到底瞒了什么？")))
        self.assertFalse(listener_shot(_shot(dialogue="旁白：那年冬天很冷。")))
        self.assertTrue(listener_shot(_shot(dialogue="陈默：你到底瞒了什么？")))


class CutKeepsBlockingTests(unittest.TestCase):
    """Rule 5: a cut is not a move."""

    def test_a_new_size_or_move_says_people_keep_their_place_in_every_later_block(self):
        beats = [_beat("坐下"), _beat("抬眼", size="CU"), _beat("推开合同", size="MCU", motion="缓慢推近")]
        text = slice_video.compile_prompt(beats, model="seedance2.0").text
        self.assertEqual(text.count(CLIP["cut_keeps_blocking"]), 2, "deduping keeps it: it rides in the join clause")

    def test_the_same_framing_or_a_fight_adds_nothing(self):
        same = slice_video.compile_prompt([_beat("坐下"), _beat("抬眼")], model="seedance2.0").text
        self.assertNotIn(CLIP["cut_keeps_blocking"], same)
        fight = slice_video.compile_prompt([_beat("出拳"), _beat("格挡", size="CU")], model="seedance2.0", fight=True).text
        self.assertNotIn(CLIP["cut_keeps_blocking"], fight)

    def test_a_single_clip_with_a_cut_in_says_it_after_the_cut(self):
        structure = _compile(cut_in={"label": "硬切至林夏近景"}).sections["structure"]
        self.assertIn("切入本镜：硬切至林夏近景 + " + CLIP["cut_keeps_blocking"], structure)
        self.assertNotIn(CLIP["cut_keeps_blocking"], _compile().sections["structure"])


class ReactionAfterTriggerTests(unittest.TestCase):
    """Rule 6: a listener's reaction comes after the words that trigger it; the mouth stays shut."""

    def _listener(self, **overrides):
        return _compile(
            shot_size="CU", dialogue="陈默（画外）：你以为我查不到？", expression="震惊后强压",
            expression_reading="眼睛猛地睁大、嘴唇微张，呼吸一窒", **overrides,
        )

    def test_the_reaction_waits_for_the_last_words(self):
        expression = self._listener().sections["expression"]
        self.assertTrue(expression.startswith("表演：听到“我查不到”之后才震惊后强压"))
        self.assertTrue(expression.endswith("此前保持原状"))

    def test_a_listener_does_not_open_the_mouth(self):
        expression = self._listener().sections["expression"]
        self.assertNotIn("嘴唇微张", expression)
        self.assertIn("外化为眼睛猛地睁大，呼吸一窒", expression)

    def test_a_speaker_keeps_the_whole_reading_and_no_trigger(self):
        compiled = _compile(dialogue="林夏：你早就知道了。", expression="压着怒意", expression_reading="嘴唇微张、眼神发冷")
        self.assertEqual(compiled.sections["expression"], "表演：压着怒意；外化为嘴唇微张、眼神发冷")
        self.assertFalse(listener_shot(_shot(dialogue="林夏：你早就知道了。")))

    def test_the_trigger_is_the_last_two_to_four_words(self):
        self.assertEqual(trigger_words("陈默（画外）：你以为我查不到？"), "我查不到")
        self.assertEqual(trigger_words("林夏：我们离婚吧。"), "我们离婚吧")
        self.assertEqual(trigger_words("林夏：查到了，又能怎样。"), "又能怎样")
        self.assertEqual(trigger_words(""), "")

    def test_the_trigger_is_kept_through_condensing(self):
        sections = self._listener().sections
        self.assertEqual(reaction_triggers(sections), {"听到“我查不到”之后才"})
        beats = [slice_video.Beat(sections=sections, size="CU", motion="固定机位"), _beat("推开合同")]
        compiled = slice_video.compile_prompt(beats, model="seedance2.0")
        self.assertIn("听到“我查不到”之后才", slice_video.required_tokens(compiled.sections, 2))
        self.assertIn("【镜头2/2", slice_video.required_tokens(compiled.sections, 2))


class BackViewTests(unittest.TestCase):
    """Rule 7: do not write what the framing cannot show."""

    def _back(self, **overrides):
        return _compile(
            subject_action="林夏背对镜头站在落地窗前，肩膀微微下沉", composition="林夏背影居中", expression="疲惫、心酸",
            expression_reading="眉头微蹙、眼神黯淡", expression_notes="抿嘴", dialogue="林夏：算了。", **overrides,
        )

    def test_a_back_view_acts_with_the_body_and_never_turns(self):
        compiled = self._back()
        expression = compiled.sections["expression"]
        self.assertTrue(expression.startswith("表演：疲惫、心酸，"))
        self.assertIn("全程背对镜头，不转身", expression)
        for face in ("外化为", "眉头", "眼神黯淡", "抿嘴"):
            self.assertNotIn(face, expression)

    def test_no_face_lock_and_no_lip_sync_for_a_back_view(self):
        compiled = self._back()
        self.assertNotIn("面部全程在变", compiled.text)
        self.assertEqual(compiled.sections["performance_lock"], "\n".join(SKELETON["performance_lock"]["back"]))
        self.assertNotIn("口型同步铁律", compiled.sections["rules"])

    def test_back_view_words_and_their_false_friends(self):
        self.assertTrue(back_view(_shot(composition="林夏背影居中")))
        self.assertTrue(back_view(_shot(subject_action="镜头在林夏背后")))
        self.assertFalse(back_view(_shot(subject_action="陈默背对林夏站在窗前", characters=["陈默", "林夏"])))
        self.assertFalse(back_view(_shot(subject_action="陈默背对着林夏", characters=["陈默", "林夏"])))
        self.assertFalse(back_view(_shot(subject_action="林夏说：你背后有人", dialogue="林夏说：你背后有人")))

    def test_a_slice_of_back_views_keeps_the_back_lock_and_a_front_moment_brings_the_face_lock_back(self):
        back = self._back().sections
        front = _compile(expression="克制").sections
        only_back = clip_skeleton.merge([back, back], model="seedance2.0")
        self.assertEqual(only_back["performance_lock"], "\n".join(SKELETON["performance_lock"]["back"]))
        self.assertTrue(only_back["portrait_safety"], "the people are still people")
        mixed = clip_skeleton.merge([back, front], model="seedance2.0")
        self.assertIn("面部全程在变", mixed["performance_lock"])

    def test_h3_keeps_its_no_sigh_line_on_a_back_view(self):
        lock = compile_shot_prompt(
            style_packs.FILM_35MM, _shot(composition="林夏背影居中", expression="疲惫"), model="MiniMax-H3",
        ).sections["performance_lock"]
        self.assertTrue(lock.startswith(SKELETON["performance_lock"]["back"][0]))
        self.assertIn(SKELETON["performance_lock"]["no_sigh"], lock)
        self.assertNotIn("脸全程在变", lock)


class ListenerCameraTests(unittest.TestCase):
    """Rule 8: a subtle reaction is not fought by the camera."""

    def test_a_moving_listener_close_up_gets_the_calm_camera_sentence(self):
        camera = _compile(shot_size="CU", camera_movement="缓慢推近", dialogue="陈默（画外）：你以为我查不到？").sections["camera"]
        self.assertEqual(camera, "景别：CU；运镜：缓慢推近；" + SKELETON["listener_camera"])

    def test_fixed_wide_or_speaking_shots_get_nothing(self):
        line = "陈默（画外）：你以为我查不到？"
        self.assertNotIn(SKELETON["listener_camera"], _compile(shot_size="CU", dialogue=line).sections["camera"])
        self.assertNotIn(SKELETON["listener_camera"], _compile(shot_size="WS", camera_movement="环绕", dialogue=line).sections["camera"])
        self.assertNotIn(SKELETON["listener_camera"], _compile(shot_size="CU", camera_movement="环绕", dialogue="林夏：好。").sections["camera"])

    def test_a_slice_carries_it_into_the_moment_block(self):
        listener = _compile(shot_size="CU", camera_movement="环绕", dialogue="陈默（画外）：你以为我查不到？").sections
        beats = [
            slice_video.Beat(sections=listener, size="CU", motion="环绕"), _beat("推开合同"),
            slice_video.Beat(sections=listener, size="CU", motion="环绕"),
        ]
        text = slice_video.compile_prompt(beats, model="seedance2.0").text
        self.assertEqual(text.count(SKELETON["listener_camera"]), 2, "the first block and the third block's join both keep it")


class OffScreenTests(unittest.TestCase):
    """Rule 10: the off-screen speaker is heard, locked, and never shown."""

    def test_an_off_screen_label_is_read_even_for_someone_in_the_cast(self):
        self.assertEqual(dialogue_voices("陈默（画外）：你好\n林夏：嗯", ["陈默", "林夏"]), ([("陈默", True), ("林夏", False)], 2))
        self.assertEqual(dialogue_speakers("陈默（画外）：你好", ["陈默", "林夏"]), ([], ["陈默"], 1))
        self.assertEqual(dialogue_speakers("陈默（冷笑）：你好", ["陈默"]), (["陈默"], [], 1))

    def test_the_dialogue_says_the_off_screen_speaker_is_not_in_the_picture(self):
        text = format_dialogue("陈默（画外）：你以为我查不到？", ["林夏"], on_screen=["林夏"])
        self.assertTrue(text.endswith(WORDS["says"]["off_screen_absent"].format(names="陈默") + "）"))
        self.assertNotIn("在画外", format_dialogue("林夏：好。", ["林夏"], on_screen=["林夏"]))

    def test_an_off_screen_voice_is_a_voice_over_for_h3_not_silence(self):
        anchor = h3_sound_design.build_voice_anchor("陈默", description="32岁男性", gender="male")
        prompt = h3_sound_design.compile_sound_prompt(speakers=[anchor], narration=True)
        self.assertIn("voice-over, mouths closed", prompt.center)
        self.assertNotIn("no dialogue", prompt.center)


class EndHoldTests(unittest.TestCase):
    """Rule 11 and the moment's own end state."""

    def test_a_multi_moment_clip_holds_its_last_pose_once_after_the_last_block(self):
        compiled = slice_video.compile_prompt([_beat("坐下"), _beat("抬眼"), _beat("松手")], model="seedance2.0")
        text = compiled.text
        self.assertEqual(text.count(CLIP["end_hold"]), 1)
        self.assertLess(text.index("【镜头3/3"), text.index(CLIP["end_hold"]))
        self.assertIn("end_hold", prompt_budget.FIXED_SECTIONS)
        self.assertNotIn("end_hold", slice_video._BEAT_SECTIONS)

    def test_a_single_moment_has_no_hold_line(self):
        self.assertNotIn(CLIP["end_hold"], slice_video.compile_prompt([_beat("坐下")], model="seedance2.0").text)
        self.assertNotIn(CLIP["end_hold"], _compile().text)

    def test_a_moment_without_its_own_landing_ends_where_the_next_one_starts(self):
        beats = [_beat("坐下", end="落幅："), _beat("抬眼", start="林夏坐定，双手放在桌上"), _beat("松手")]
        text = slice_video.compile_prompt(beats, model="seedance2.0").text
        self.assertIn(CLIP["beat_lands"].format(state="林夏坐定，双手放在桌上"), text)
        self.assertEqual(text.count("本段落在："), 1, "moments with their own 落幅 and the last moment get none")
        self.assertNotIn("落幅：。", text)


class ShorthandTests(unittest.TestCase):
    """Bug: 「按在合同上」 contains 「同上」, and one shot's shorthand must never abort stage 5."""

    def test_a_word_that_merely_contains_a_shorthand_is_fine(self):
        compiled = _compile(blocking="林夏坐在书桌后，双手按在合同上")
        self.assertIn("双手按在合同上", compiled.sections["locks"])

    def test_a_standalone_shorthand_is_removed_and_logged_not_raised(self):
        with self.assertLogs("app.core.video_prompt_engine", level="WARNING"):
            compiled = _compile(start_state="同上，林夏坐在书桌后", scene="书房；场景不变")
        self.assertNotIn("同上", compiled.sections["locks"])
        self.assertNotIn("场景不变", compiled.sections["locks"])
        self.assertIn("林夏坐在书桌后", compiled.sections["locks"])


class FalseHoldTests(unittest.TestCase):
    """「原文台词保持不变」 is not someone holding the prop the line names."""

    def test_keep_words_are_not_holding(self):
        action = "陈默转身面向林夏。原文台词保持不变：陈默：那份合同，是你签的。"
        self.assertEqual(prop_holders(["合同"], ["陈默", "林夏"], action), ["合同"])
        self.assertEqual(prop_holders(["合同"], ["陈默"], "陈默握着合同"), ["合同：陈默持有"])
        self.assertEqual(_compile(subject_action=action, props=["合同"], characters=["陈默", "林夏"]).sections.get("contact", ""), "")


class VoiceLockTests(unittest.TestCase):
    """The voice lock pins timbre and pitch; pace follows each line."""

    def test_no_fixed_pace_in_the_lock(self):
        line = h3_sound_design.build_voice_anchor("林夏", description="28岁女记者", gender="female").lock_line()
        self.assertNotIn("语速", line)
        self.assertIn("中音区", line)
        self.assertNotIn("lock_pace", prompt_data.load("h3_sound_design")["says"])


class H3SystemPromptTests(unittest.TestCase):
    def test_the_system_prompt_is_data_and_says_how_cuts_listeners_and_the_end_behave(self):
        prompt = h3_native.system_prompt()
        self.assertEqual(h3_native.SYSTEM_PROMPT, "".join(prompt_data.value("h3_native", "system_prompt")))
        for words in ("镜头切换时人物站位与朝向不变", "保持这个姿态到片尾", "听者嘴唇闭合"):
            self.assertIn(words, prompt)
        self.assertIn(f"绝不超过 {h3_native.MAX_DRAFT_CHARS} 个字符", prompt)


def _panel(index, **kw):
    base = dict(
        index=index, characters=["林夏"], shot_size="MS", camera_angle="平视", camera_movement="固定机位", camera_reason="稳住",
        lens_mm=50, aperture="T2.8", composition="林夏居中", action_axis="摄影机在书桌南侧", eyeline="林夏望向画右",
        subject_action="", expression="克制", scene="书房", props=["合同"], effects=["无"], dialogue="", sound="室内安静底噪",
        lighting="台灯暖光", edit_in="承接上一镜", edit_out="停在落幅", generation_mode="auto", blocking="林夏坐在书桌后，双手按在合同上",
        start_state="林夏坐在书桌后", end_state="林夏坐定", continuity_out="林夏坐定",
    )
    base.update(kw)
    return StoryboardPanel(**base)


def _board_shot(shot_id, panel, seconds, **extra):
    contract = ShotMotionContract.from_panel(panel, storyboard_image=f"/media/E1S01_{shot_id}.png")
    return {
        "shot_id": shot_id, "scene_id": "E1S01", "size": panel.shot_size, "motion": panel.camera_movement, "desc": panel.subject_action,
        "dialogue": panel.dialogue, "sound": panel.sound, "duration": str(seconds), "image_url": f"/media/E1S01_{shot_id}.png",
        "characters": list(panel.characters), "props": list(panel.props),
        "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint, **extra,
    }


class StageFiveTests(unittest.TestCase):
    """The whole stage: a three-moment board with an off-screen line and a 「按在合同上」 blocking renders, no paid call."""

    def _run(self, model):
        harness = StageFiveQueueTests("test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted")
        harness.setUp()
        self.addCleanup(harness.temp.cleanup)
        task = _task(1)
        task["config"]["video_model"] = model
        task["config"].pop("video_granularity", None)
        task["assets"]["3_characters"] = [
            {"name": "林夏", "gender": "女", "desc": "28岁女性"}, {"name": "陈默", "gender": "男", "desc": "32岁男性"},
        ]
        task["assets"]["4"] = [
            _board_shot(1, _panel(1, subject_action="林夏低头看合同", dialogue="林夏：这是什么？"), 3),
            _board_shot(2, _panel(2, shot_size="CU", subject_action="林夏坐着听", dialogue="陈默（画外）：你以为我查不到？",
                                  expression="震惊后强压"), 4, cut_in={"label": "硬切至林夏近景"}),
            _board_shot(3, _panel(3, shot_size="MCU", camera_movement="缓慢推近", subject_action="林夏把合同推到桌边",
                                  dialogue="林夏：查到了，又能怎样。", expression="冷笑"), 3),
        ]
        sent = []
        with patch.object(harness.service.gateway, "call_llm", return_value=""), \
             patch.object(harness.service.gateway, "_http_chat", return_value=""), \
             patch.dict("os.environ", {"H3_NATIVE_PROMPTS": "0"}):
            stored = harness._run(task, on_video=sent.append)
        return stored, sent

    def test_seedance_gets_spans_cuts_reaction_off_screen_and_hold_in_the_body(self):
        stored, sent = self._run("seedance2.0")
        [clip] = stored["assets"]["5"]
        self.assertTrue(clip["video_url"], "one shot's 「按在合同上」 no longer aborts the stage")
        [prompt] = sent
        body = prompt.split("Pa2")[0]
        self.assertRegex(body, r"【镜头1/3｜MS｜固定机位｜0—[\d.]+秒】")
        self.assertRegex(body, r"【镜头3/3｜MCU｜缓慢推近｜[\d.]+—" + str(clip["duration"]) + "秒】")
        for words in (CLIP["one_change"], CLIP["cut_keeps_blocking"], "听到“我查不到”之后才", "陈默在画外，不出现在画面里", CLIP["end_hold"]):
            self.assertIn(words, body)
        self.assertNotIn("语速每秒", prompt)
        fitted, _removed = prompt_budget.fit_hard_limit(prompt, "seedance2.0")
        for words in (CLIP["cut_keeps_blocking"], "之后才", CLIP["end_hold"]):
            self.assertIn(words, fitted, "the new sentences survive the 2000-character cut")

    def test_h3_hears_the_off_screen_voice_instead_of_silence(self):
        _stored, sent = self._run("MiniMax-H3")
        [prompt] = sent
        self.assertIn("voice-over, mouths closed", prompt)
        self.assertNotIn("no dialogue, characters silent", prompt)
        self.assertIn("音色铁律：陈默", prompt, "the off-screen speaker gets a voice lock")


if __name__ == "__main__":
    unittest.main()
