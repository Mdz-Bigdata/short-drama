# -*- coding: utf-8 -*-
"""Sound for a model that renders picture and sound together.

H3 has one sound entry and no faders, so the dialogue, the room and the score are
written as three named layers in one line, and a character's voice is described with
the same words in every clip or it drifts into somebody else's.
"""

import unittest

from app.core import h3_sound_design as sound
from app.core.style_packs import CINEMATIC_REALISM
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt


class VoiceAnchorTests(unittest.TestCase):
    def test_a_card_always_yields_the_same_voice(self):
        first = sound.build_voice_anchor("林夏", description="22岁记者，清亮嗓音", gender="female")
        again = sound.build_voice_anchor("林夏", description="22岁记者，清亮嗓音", gender="female")

        self.assertEqual(first, again)
        self.assertEqual(first.persona, "22岁清亮女声")
        # The card's own words decide the band; an age alone does not raise the pitch.
        self.assertEqual((first.pitch, first.pace_cps), ("中音区", 3.0))

    def test_the_lock_line_states_timbre_pitch_and_pace_and_says_it_never_changes(self):
        anchor = sound.build_voice_anchor("周教授", description="花白头发的中年教授", gender="male")

        line = anchor.lock_line()

        self.assertIn("周教授：", line)
        self.assertIn("沉稳男声", line)
        self.assertIn("中低音区", line)
        self.assertIn("语速每秒3字", line)
        self.assertIn("全片音色、音调与声线不变", line)
        self.assertNotIn("音色参考", line)          # no clean sample on file yet

    def test_a_clean_sample_is_referenced_when_the_project_has_one(self):
        anchor = sound.build_voice_anchor("林夏", gender="female", ref_audio="@音频1")

        self.assertIn("音色参考@音频1", anchor.lock_line())

    def test_the_card_decides_the_voice_band(self):
        bands = {
            "少年": sound.build_voice_anchor("阿灿", description="十六岁少年", gender="male"),
            "老人": sound.build_voice_anchor("老周", description="白发苍苍的老人", gender="male"),
            "冷": sound.build_voice_anchor("裴相", description="清冷疏离的权臣", gender="male"),
        }

        self.assertEqual(bands["少年"].pitch, "中高音区")
        self.assertEqual(bands["老人"].timbre, "苍哑")
        self.assertEqual(bands["冷"].timbre, "清冷")

    def test_a_cast_list_becomes_anchors_keyed_by_name(self):
        anchors = sound.anchors_from_characters(
            [{"name": "林夏", "desc": "22岁记者"}, {"name": "周教授", "description": "中年教授"}, {"name": ""}],
            gender_of=lambda name: "male" if name == "周教授" else "female",
        )

        self.assertEqual(set(anchors), {"林夏", "周教授"})
        self.assertEqual(anchors["周教授"].gender, "male")

    def test_the_emotion_of_a_shot_sets_the_pace_tier_and_the_mood_word(self):
        self.assertEqual(sound.delivery_for_emotion("angry"), ("急切", "angry"))
        self.assertEqual(sound.delivery_for_emotion("sad"), ("沉重", "sorrowful"))
        self.assertEqual(sound.delivery_for_emotion("unknown-feeling"), ("正常", ""))


class SoundPromptTests(unittest.TestCase):
    def setUp(self):
        self.lin = sound.build_voice_anchor("林夏", description="22岁记者", gender="female")
        self.zhou = sound.build_voice_anchor("周教授", description="中年教授", gender="male")

    def test_three_layers_in_one_line_with_the_dialogue_first(self):
        prompt = sound.compile_sound_prompt(
            speakers=[self.lin, self.zhou], ambience=["office air-con hum", "distant traffic"], tone="tense",
        )

        self.assertTrue(prompt.text.startswith("center: "))
        self.assertLess(prompt.text.index("center:"), prompt.text.index("ambient:"))
        self.assertLess(prompt.text.index("ambient:"), prompt.text.index("music:"))
        self.assertIn("female bright / male steady", prompt.center)
        self.assertIn("clear speech, center channel", prompt.center)
        self.assertIn("synced to mouth", prompt.center)
        self.assertIn("tense", prompt.center)
        self.assertIn("continuous, low volume, surround", prompt.ambient)
        self.assertEqual(prompt.music, "none")           # this project scores the film later
        self.assertEqual(prompt.voice_locks, [self.lin.lock_line(), self.zhou.lock_line()])
        self.assertTrue(prompt.passed, [c.detail for c in prompt.checks if not c.passed])

    def test_a_voice_over_keeps_the_mouths_closed_and_a_silent_shot_says_so(self):
        over = sound.compile_sound_prompt(speakers=[self.lin], narration=True)
        silent = sound.compile_sound_prompt(silent=True, ambience=["rain on window"])

        self.assertIn("voice-over, mouths closed", over.center)
        self.assertNotIn("synced to mouth", over.center)
        self.assertIn("no dialogue", silent.center)
        self.assertEqual(silent.voice_locks, [])
        self.assertTrue(silent.passed)

    def test_a_hall_gets_a_little_reverb_and_a_room_gets_none(self):
        hall = sound.compile_sound_prompt(speakers=[self.lin], ambience=["footsteps"], spacious=True)
        room = sound.compile_sound_prompt(speakers=[self.lin], ambience=["footsteps"])

        self.assertIn("low reverb", hall.ambient)
        self.assertNotIn("reverb", room.ambient)

    def test_a_score_is_pushed_under_the_voice_when_one_is_asked_for(self):
        prompt = sound.compile_sound_prompt(speakers=[self.lin], music="tense strings")

        self.assertIn("low frequency", prompt.music)
        self.assertIn("slight spread", prompt.music)
        self.assertTrue(prompt.passed)

    def test_the_voice_may_be_pushed_forward_in_a_noisy_room(self):
        prompt = sound.compile_sound_prompt(speakers=[self.lin], ambience=["market crowd"], foreground=True)

        self.assertIn("foreground", prompt.center)


class SoundCheckTests(unittest.TestCase):
    @staticmethod
    def _codes(text, **kwargs):
        return {check.code: check.passed for check in sound.check_sound_prompt(text, **kwargs)}

    def test_a_missing_layer_is_caught(self):
        codes = self._codes("center: female voice, clear speech; ambient: rain, low volume, surround")

        self.assertFalse(codes["h3_sound_three_layers"])

    def test_music_words_inside_the_dialogue_layer_are_caught(self):
        codes = self._codes(
            "center: gentle piano-like voice, clear speech, center channel; "
            "ambient: rain, continuous, low volume, surround; music: none",
        )

        self.assertFalse(codes["h3_sound_center_clean"])

    def test_a_loud_bed_and_a_flat_field_are_caught(self):
        codes = self._codes(
            "center: female voice, clear speech, center channel, synced to mouth; "
            "ambient: cafe murmur, continuous; music: jazz quartet upbeat",
        )

        self.assertFalse(codes["h3_sound_low_bed"])
        self.assertFalse(codes["h3_sound_space"])

    def test_an_over_long_sound_prompt_is_caught(self):
        long_text = (
            "center: female bright voice, clear speech, center channel, synced to mouth; "
            "ambient: " + ", ".join(["rain on window"] * 20) + ", continuous, low volume, surround; music: none"
        )

        self.assertFalse(self._codes(long_text)["h3_sound_word_budget"])

    def test_a_clean_prompt_passes_every_check(self):
        anchor = sound.build_voice_anchor("林夏", gender="female")
        prompt = sound.compile_sound_prompt(speakers=[anchor], ambience=["rain on window"])

        self.assertTrue(all(self._codes(prompt.text, speakers=[anchor]).values()))


class ShotPromptIntegrationTests(unittest.TestCase):
    def _shot(self, **overrides):
        values = dict(
            shot_index=1, duration_seconds=6, shot_size="近景", camera_movement="固定",
            subject_action="林夏开口质问" * 20, scene="办公室 夜 内景", blocking="林夏画左、周教授画右",
            start_state="两人隔桌对坐", end_state="林夏抬眼", dialogue="你到底瞒了什么？",
            sound="环境音：空调低鸣", environment="北侧档案柜" * 10,
        )
        values.update(overrides)
        return ShotPromptInput(**values)

    def test_the_sound_layers_survive_a_budget_that_drops_the_sound_note(self):
        anchor = sound.build_voice_anchor("林夏", gender="female")
        layers = sound.compile_sound_prompt(speakers=[anchor], ambience=["office hum"]).text

        compiled = compile_shot_prompt(
            CINEMATIC_REALISM, self._shot(sound_layers=layers), model="vidu", max_duration_seconds=15,
        )

        self.assertIn("【声音设计·三层】", compiled.text)
        self.assertIn("center:", compiled.text)
        self.assertNotIn("sound_layers", compiled.pressure.dropped)
        self.assertIn("environment", compiled.pressure.dropped)

    def test_without_layers_the_plain_sound_note_is_used(self):
        compiled = compile_shot_prompt(CINEMATIC_REALISM, self._shot(), model="seedance2.5", max_duration_seconds=30)

        self.assertIn("【声音设计】环境音：空调低鸣", compiled.text)
        self.assertNotIn("【声音设计·三层】", compiled.text)


class StageFiveWiringTests(unittest.TestCase):
    """Stage 5 is where the sound layers and the voice locks have to arrive."""

    @staticmethod
    def _source() -> str:
        from pathlib import Path as _Path

        import app.service.drama_service as service

        return _Path(service.__file__).read_text(encoding="utf-8")

    def test_an_audio_native_model_gets_layers_locks_and_a_record_of_the_checks(self):
        source = self._source()

        for marker in (
            'normalize_video_provider(str(config.get("video_model") or "")).family == "minimax_h3"',
            "h3_sound_design.anchors_from_characters",
            "h3_sound_design.compile_sound_prompt",
            "sound_layers=sound_layers",
            'f"音色铁律：{line}" for line in voice_locks',
            '"sound_checks": sound_checks',
        ):
            self.assertIn(marker, source, f"第5阶段声音接线点丢失：{marker}")

    def test_the_cast_and_the_speakers_come_from_the_same_readers(self):
        from app.core.shot_table_rules import speakers_in
        from app.service.drama_service import guess_gender

        anchors = sound.anchors_from_characters(
            [{"name": "林夏", "desc": "22岁女记者"}, {"name": "周教授", "desc": "中年男教授"}],
            gender_of=guess_gender,
        )
        speaking = [anchors[name] for name in speakers_in("林夏：你到底瞒了什么？", list(anchors)) if name in anchors]

        self.assertEqual([anchor.name for anchor in speaking], ["林夏"])
        self.assertTrue(sound.compile_sound_prompt(speakers=speaking).passed)


if __name__ == "__main__":
    unittest.main()
