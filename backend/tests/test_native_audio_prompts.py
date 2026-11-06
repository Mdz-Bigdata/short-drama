# -*- coding: utf-8 -*-
"""Sound in the clip prompt: only for models that make sound, and bound to what the picture shows.

A silent model gets no sound wording at all; a model that renders sound gets one ambience
bed, at most two contacts tied to a visible event, a clear line above the bed, and a
dialogue line that says who speaks, after what, and that nobody else does.
"""

import unittest

from app.core import style_packs
from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.core.sound_events import build_sound_events, split_cues
from app.core.spoken_lines import spoken_lines
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt, format_dialogue, handoff_line
from app.core.video_references import VIDEO_PROVIDER_PROFILES, video_native_audio


def _shot(**overrides) -> ShotPromptInput:
    values = dict(
        shot_index=4, duration_seconds=8, shot_size="近景", camera_movement="固定",
        subject_action="林夏把纸杯放在木柜台上，抬眼看向周教授", scene="咖啡店 夜 内景",
        blocking="林夏画左、周教授画右", start_state="林夏端着纸杯", end_state="林夏直视周教授",
        props=["纸杯"], characters=["林夏", "周教授"],
        sound="环境音：空调低鸣；动作音：纸杯碰柜台、按键咔哒", dialogue="林夏：你到底瞒了什么？",
    )
    values.update(overrides)
    return ShotPromptInput(**values)


class NativeAudioCapabilityTests(unittest.TestCase):
    def test_every_video_profile_says_whether_it_makes_sound(self):
        limits = {name: caps.limits for name, caps in ProviderCapabilityRegistry().list().items()}
        for profile in VIDEO_PROVIDER_PROFILES:
            with self.subTest(profile.family):
                self.assertIn("native_audio", limits[profile.family])
        self.assertTrue(limits["minimax_h3"]["native_audio"])
        self.assertTrue(limits["seedance"]["native_audio"])
        self.assertFalse(limits["kling"]["native_audio"], "the adapter never asks Kling for sound")

    def test_versions_and_unknown_models(self):
        self.assertTrue(video_native_audio("seedance2.5"))
        self.assertTrue(video_native_audio("doubao-seedance-2-0-260128"))
        self.assertFalse(video_native_audio("doubao-seedance-1-0-pro-250528"), "Seedance 1.0 is silent")
        self.assertTrue(video_native_audio("MiniMax-H3"))
        self.assertFalse(video_native_audio("kling-v2-1"))
        self.assertFalse(video_native_audio("vidu"))
        self.assertFalse(video_native_audio(""))


class SilentModelPromptTests(unittest.TestCase):
    def test_a_silent_model_gets_no_sound_wording(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(native_audio=False), model="kling-v2-1").text

        for absent in ("[声音锁]", "【声音设计】", "【声音事件】", "音效", "BGM", "口型同步）"):
            self.assertNotIn(absent, text)
        self.assertIn("台词口型（逐字对应原文，只做口型）", text)
        self.assertIn("严禁新增叠加的字幕、歌词、说明文字、图形符号与水印。", text)
        self.assertIn("场景中原有的匾额、招牌、对联、标语保持原样", text)
        self.assertNotIn("无字幕；无水印", text)

    def test_a_silent_model_ignores_layers_handed_to_it(self):
        text = compile_shot_prompt(
            style_packs.FILM_35MM, _shot(native_audio=False, sound_layers="center: x; ambient: y; music: none"),
            model="kling-v2-1",
        ).text

        self.assertNotIn("【声音设计·三层】", text)

    def test_a_sound_model_keeps_its_sound_sections(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text

        self.assertIn("[声音锁]空调低鸣", text)
        self.assertIn("【声音设计】环境铺底：空调低鸣", text)
        self.assertIn("仅生成动作音效", text)


class SoundEventTests(unittest.TestCase):
    def test_cues_split_into_bed_and_contacts(self):
        beds, contacts = split_cues("环境音：空调低鸣、远处车流；动作音：纸杯碰柜台")

        self.assertEqual(beds, ["空调低鸣", "远处车流"])
        self.assertEqual(contacts, ["纸杯碰柜台"])

    def test_a_contact_is_bound_to_the_visible_event_and_described_physically(self):
        plan = build_sound_events(
            "环境音：空调低鸣；动作音：纸杯碰柜台", action="林夏把纸杯放在木柜台上，抬眼", props=["纸杯"],
            shot_size="近景", dialogue=True,
        )

        self.assertEqual(len(plan.contacts), 1)
        line = plan.contacts[0].line()
        self.assertTrue(line.startswith("林夏把纸杯放在木柜台上的瞬间："))
        for part in ("近处", "轻短", "偏闷", "接触声", "安静"):
            self.assertIn(part, line)
        self.assertIn("随后的动作不再重复这一声", plan.text)
        self.assertIn("对白清晰，始终在环境铺底之上", plan.text)
        self.assertIn("环境铺底：空调低鸣，全程连续", plan.text)

    def test_a_fight_cue_binds_to_the_strike_not_the_footstep(self):
        plan = build_sound_events(
            "雨打青石，拳肉闷响", shot_size="中景",
            action="沈砚右脚踏实青石，腰胯一拧，右直拳沿画面中线击中裴崇左颧骨，拳峰压出褶皱；裴崇头偏向画右",
        )
        self.assertEqual(plan.bed, "雨打青石")
        self.assertEqual([contact.event for contact in plan.contacts], ["右直拳沿画面中线击中裴崇左颧骨"])
        self.assertIn("重而闷的拳脚击打的闷响", plan.contacts[0].sound)
        # No cue at all: the strike itself is still a contact, though nothing in the clause is a prop or a material.
        silent = build_sound_events("", shot_size="近景", action="裴崇右腿斜踢，脚背击中沈砚左侧肋部；沈砚闷哼一声")
        self.assertEqual([contact.event for contact in silent.contacts], ["脚背击中沈砚左侧肋部"])
        blades = build_sound_events("", shot_size="近景", action="两人兵刃相交，火星溅在湿石上")
        self.assertIn("金属交击声", blades.contacts[0].sound)
        # The cue names a hit, this moment has none: the moment's own contacts are used instead of nothing.
        pin = build_sound_events("雨打青石，拳肉闷响", shot_size="全景", action="裴崇右膝砸在青石上，溅起一圈积水；沈砚的脚踩住刀鞘", props=["刀"])
        self.assertEqual([contact.event for contact in pin.contacts], ["裴崇右膝砸在青石上", "沈砚的脚踩住刀鞘"])
        self.assertEqual(pin.unbound, ["拳肉闷响"])

    def test_a_contact_nobody_sees_is_left_out(self):
        plan = build_sound_events("动作音：按键咔哒", action="林夏盯着对面，手指攥紧录音笔", props=["录音笔"])

        self.assertEqual(plan.contacts, [])
        self.assertEqual(plan.unbound, ["按键咔哒"])
        self.assertNotIn("按键", plan.text)

    def test_at_most_two_contacts(self):
        plan = build_sound_events(
            "动作音：杯子碰桌、门关上、钥匙落地",
            action="她把杯子放在桌上，走去把门关上，钥匙落地", props=["杯子", "钥匙"],
        )

        self.assertEqual(len(plan.contacts), 2)

    def test_an_action_contact_is_used_when_the_note_names_none(self):
        plan = build_sound_events("环境音：雨声", action="他把玻璃杯放在桌上", props=["玻璃杯"], shot_size="中景")

        self.assertEqual(len(plan.contacts), 1)
        self.assertIn("清脆", plan.contacts[0].sound)
        self.assertIn("嘈杂", plan.contacts[0].sound, "rain is a noisy bed")

    def test_exclusions_leave_out_what_the_shot_plans(self):
        quiet = build_sound_events("", action="她坐着", dialogue=True)
        planned = build_sound_events("", action="她坐着", dialogue=True, narration=True, music=True)

        self.assertEqual(quiet.exclusions, ["无旁白", "无音乐", "无额外对白"])
        self.assertEqual(planned.exclusions, ["无额外对白"])
        self.assertEqual(quiet.bed, "轻微的空间底噪")


class DialogueLineTests(unittest.TestCase):
    def test_the_speaker_is_named_after_their_action_and_the_others_stay_silent(self):
        text = format_dialogue(
            "林夏：你到底瞒了什么？", ["林夏", "周教授"],
            action="林夏把纸杯放在木柜台上，抬眼看向周教授", on_screen=["林夏", "周教授"],
        )

        self.assertEqual(
            text,
            "@[林夏]先把纸杯放在木柜台上，随后@[林夏]{你到底瞒了什么？}（只有@[林夏]说话；@[周教授]闭口不出声）",
        )

    def test_two_speakers_take_turns(self):
        text = format_dialogue("林夏：你来了。\n周教授：嗯。", ["林夏", "周教授"], on_screen=["林夏", "周教授"])

        self.assertIn("只有@[林夏]、@[周教授]说话，按台词顺序轮流开口，同一时刻只有一人出声", text)

    def test_a_voice_over_keeps_the_mouths_closed(self):
        text = format_dialogue("旁白：那年冬天很冷。", ["林夏"], on_screen=["林夏"])

        self.assertIn("画外声，画面人物闭口不出声", text)

    def test_the_dialogue_text_glued_to_the_action_is_not_an_action(self):
        text = format_dialogue(
            "林夏：我知道，你走吧", ["林夏"], action="林夏转身。原文台词保持不变：林夏：我知道，你走吧",
        )

        self.assertTrue(text.startswith("@[林夏]先转身，随后@[林夏]{"))


class HandoffTests(unittest.TestCase):
    def test_a_handoff_gets_a_feasible_path(self):
        line = handoff_line(
            "林夏端起纸杯，周教授把钥匙递给林夏", ["林夏", "周教授"], props=["纸杯", "钥匙"],
            setting="咖啡店 柜台 林夏站柜台外",
        )

        self.assertIn("林夏与周教授同在一个空间里，中间只隔一张开放的柜台", line)
        self.assertIn("钥匙在两人伸手可及处", line)
        self.assertIn("开阔处", line)
        self.assertLess(len(line), 120)

    def test_a_glass_door_stays_behind_the_handoff(self):
        line = handoff_line(
            "店员把热饮递给顾客", ["店员", "顾客"], props=["热饮"], setting="雨夜便利店 柜台 玻璃门在入口",
        )

        self.assertIn("中间只隔一张开放的柜台", line)
        self.assertIn("玻璃、门只在背景，不在两人之间，也不在手与热饮之间", line)

    def test_no_handoff_no_line(self):
        self.assertEqual(handoff_line("林夏看向周教授", ["林夏", "周教授"]), "")
        self.assertEqual(handoff_line("林夏把钥匙递过去", ["林夏"]), "", "a handoff needs two people")

    def test_the_handoff_line_reaches_the_clip_prompt(self):
        text = compile_shot_prompt(
            style_packs.FILM_35MM, _shot(subject_action="周教授把纸杯递给林夏"), model="seedance2.5",
        ).text

        self.assertIn("递接路径：林夏与周教授之间没有遮挡", text)


class DialogueIsNotASoundEventTests(unittest.TestCase):
    def test_braced_dialogue_never_becomes_a_contact_event(self):
        plan = build_sound_events(
            "动作音：拍击声", action="裴仲玄右手扣鞘口，将剑推回到底。原文台词保持不变：裴仲玄：{谁？}停顿一拍{谁动的剑？}",
            props=["剑"],
        )
        text = " ".join(plan.contact_lines())
        self.assertNotIn("}", text)
        self.assertNotIn("谁动的剑", text)


class LeadActionTests(unittest.TestCase):
    """「某人先做什么，随后开口」只写明确是这个人做的动作；构图、光和身体状态不算。"""

    def _lead(self, action):
        text = format_dialogue("沈无咎：走。", ["沈无咎", "苏问剑"], action=action)
        return text.split("，随后")[0] if "，随后" in text else None

    def test_clauses_that_do_not_name_the_speaker_are_never_a_lead(self):
        for clause in (
            "他的面部与胸前团纹保留清晰", "画面中央过道清空", "无多余手指", "前景虚化的剑身斜切画面左下", "第一句时他身体不动",
            "门缝冷青光从画面右侧打在他半张脸上", "衣摆被雨水打得沉坠贴腿", "左颊贴地压出一道石缝的红痕", "睫毛上挂着水珠",
        ):
            self.assertIsNone(self._lead(clause), clause)

    def test_a_named_clause_about_the_frame_is_not_an_action_either(self):
        for clause in ("沈无咎恒在画面左侧", "沈无咎的面部完整保留", "沈无咎静止", "沈无咎仍在画面左侧"):
            self.assertIsNone(self._lead(clause), clause)

    def test_a_named_action_stays(self):
        self.assertEqual(self._lead("沈无咎把布按在剑脊上，雨水顺着石缝流走"), "@[沈无咎]先把布按在剑脊上")
        self.assertEqual(self._lead("沈无咎转身"), "@[沈无咎]先转身")

    def test_a_long_description_is_not_squeezed_in_front_of_the_line(self):
        self.assertIsNone(self._lead("沈无咎一只手慢慢按住剑柄又松开再按住剑柄再松开然后停住不动了"))

    def test_an_action_involving_someone_else_is_left_to_the_picture(self):
        self.assertIsNone(self._lead("沈无咎看向苏问剑抬手"))


class DialogueBracesTests(unittest.TestCase):
    """第 4 阶段的台词栏写法很多，发给模型的永远是 @[说话人]（语气）{台词}，不多套括号。"""

    def _format(self, dialogue, cast=("裴仲玄", "苏问剑", "沈无咎")):
        return format_dialogue(dialogue, list(cast))

    def test_a_line_already_in_braces_is_not_wrapped_again(self):
        text = self._format("裴仲玄：{落。}（低沉厚实的男声，尾音不拖）")
        self.assertEqual(text, "@[裴仲玄]（低沉厚实的男声，尾音不拖）{落。}")

    def test_quoted_lines_keep_only_the_words_inside_the_braces(self):
        for dialogue in ("沈无咎：「布脏了，我换一块。」（气息短；不抬音量）", "沈无咎：（气息短；不抬音量）「布脏了，我换一块。」", "沈无咎：“布脏了，我换一块。”（气息短；不抬音量）"):
            self.assertEqual(self._format(dialogue), "@[沈无咎]（气息短；不抬音量）{布脏了，我换一块。}", dialogue)

    def test_a_long_note_beside_the_speaker_is_still_a_note(self):
        text = self._format("沈无咎（中低声区、偏冷带颗粒感的青年男声，语速慢、尾音压平）：{剑自己动的。}")
        self.assertEqual(text, "@[沈无咎]（中低声区、偏冷带颗粒感的青年男声，语速慢、尾音压平）{剑自己动的。}")

    def test_each_speaker_on_one_line_gets_their_own_words(self):
        text = self._format("陈九：{布角……翻过来了。}（气声）／沈无咎：{老人家，看错了。}（声线平直）", cast=("陈九", "沈无咎"))
        self.assertEqual(text, "@[陈九]（气声）{布角……翻过来了。} @[沈无咎]（声线平直）{老人家，看错了。}")
        joined = self._format("沈无咎：「我擦的是你的剑。」裴仲玄（画外）：「怨谁。」")
        self.assertEqual(joined, "@[沈无咎]{我擦的是你的剑。} @[裴仲玄]（画外）{怨谁。}")

    def test_a_no_line_in_front_of_a_real_line_does_not_silence_the_speaker(self):
        text = format_dialogue("无；苏问剑：{都退开三步。}（字字压住）", ["苏问剑"], on_screen=["苏问剑"])
        self.assertEqual(text, "@[苏问剑]（字字压住）{都退开三步。}（只有@[苏问剑]说话）")

    def test_a_pause_between_two_lines_stays_outside_the_braces(self):
        text = self._format("无；裴仲玄（冷硬压嗓）：{谁？} 停顿一拍 {谁动的剑？}")
        self.assertEqual(text, "@[裴仲玄]（冷硬压嗓）{谁？}停顿一拍{谁动的剑？}")

    def test_brackets_and_slashes_inside_a_line_belong_to_the_line(self):
        self.assertEqual(self._format("裴仲玄：{走/留（你选）。}"), "@[裴仲玄]{走/留（你选）。}")

    def test_a_speaker_outside_the_shot_is_formatted_the_same_way(self):
        self.assertEqual(self._format("陈九：{别看。}（气声）"), "陈九（气声）{别看。}")
        self.assertEqual(self._format("{远处有人喊。}（画外）"), "（画外）{远处有人喊。}")

    def test_someone_speaking_from_outside_the_shot_keeps_their_name_out_of_the_line(self):
        text = format_dialogue("苏问剑：雨里没有这声音。 沈无咎：那我不知道。", ["苏问剑"], on_screen=["苏问剑"])
        self.assertEqual(
            text, "@[苏问剑]{雨里没有这声音。} 沈无咎{那我不知道。}（只有@[苏问剑]、沈无咎说话，按台词顺序轮流开口，同一时刻只有一人出声）",
        )

    def test_a_narrator_is_named_but_keeps_the_mouths_closed(self):
        self.assertEqual(
            format_dialogue("旁白：那年冬天很冷。", ["林夏"], on_screen=["林夏"]), "旁白{那年冬天很冷。}（画外声，画面人物闭口不出声）",
        )

    def test_a_silent_note_with_a_semicolon_is_still_no_line(self):
        self.assertEqual(self._format("无（本格静默，只留环境声与灯焰；两人均未开口）"), "")

    def test_a_note_beside_the_second_speaker_does_not_hide_their_line(self):
        dialogue = "苏问剑（低声）：第七层，空了。 沈无咎（气声压低）：什么时候的事？"
        self.assertEqual(spoken_lines([dialogue]), ["第七层，空了。", "什么时候的事？"])
        self.assertEqual(self._format(dialogue), "@[苏问剑]（低声）{第七层，空了。} @[沈无咎]（气声压低）{什么时候的事？}")

    def test_every_line_can_still_be_read_back_for_the_h3_check(self):
        text = self._format("陈九：{布角……翻过来了。}（气声；发虚）／沈无咎：「老人家，看错了。」", cast=("陈九", "沈无咎"))
        self.assertEqual(spoken_lines([text]), ["布角……翻过来了。", "老人家，看错了。"])
        self.assertEqual(text.count("{"), 2)
        self.assertEqual(text.count("}"), 2)


class FirstLastFrameBridgeTests(unittest.TestCase):
    """首尾帧生视频：提示词要写清首帧怎么走到尾帧，两帧之间不跨机位、光源、人物与道具。"""

    def _compile(self, **changes):
        fields = dict(
            shot_index=1, duration_seconds=8, shot_size="中景", camera_movement="缓慢推近", subject_action="沈知微把信推过桌面",
            scene="正堂", blocking="沈知微居中", start_state="信在她手边", end_state="信停在陆昀面前，她的手收回", characters=["沈知微"],
            native_audio=True, first_frame=True, last_frame=True,
        )
        fields.update(changes)
        return compile_shot_prompt(style_packs.get_pack(style_packs.DEFAULT_PACK_ID), ShotPromptInput(**fields), model="seedance2.0").text

    def test_the_path_between_the_frames_is_written(self):
        text = self._compile()
        self.assertIn("以所给尾帧结束：首帧到尾帧不换机位高度、不换光源、不换人物与道具", text)
        self.assertIn("运镜（缓慢推近）", text)
        self.assertIn("走到“信停在陆昀面前，她的手收回”", text)
        self.assertIn("不提前出现、不中途跳变", text)

    def test_without_a_last_frame_nothing_is_promised(self):
        self.assertNotIn("尾帧", self._compile(last_frame=False))

    def test_a_slice_names_which_shot_the_last_frame_belongs_to(self):
        from app.core import slice_video

        def beat(text):
            return slice_video.Beat(
                sections={"camera": "景别：MS；运镜：推", "subject": f"画面：{text}。", "end_state": f"落幅：{text}停住"}, size="MS", motion="推",
            )

        text = slice_video.compile_prompt([beat("推门"), beat("落座")], model="seedance2.0", last_frame=True).text
        self.assertIn("以所给尾帧结束：它是镜头2的落幅", text)
        self.assertIn("走到“落座停住”", text)
        self.assertNotIn("尾帧", slice_video.compile_prompt([beat("推门"), beat("落座")], model="seedance2.0").text)


if __name__ == "__main__":
    unittest.main()
