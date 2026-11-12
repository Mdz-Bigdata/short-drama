# -*- coding: utf-8 -*-
"""The fixed sentences every clip prompt repeats, and the three headed parts they sit in.

Pa1 says which picture gives what and who is who; Pa2 holds the look, the space and the
sound; Pa3 holds the locks and the bans, followed by the portrait, on-screen text and
"never show" paragraphs. Which sentence a clip gets depends on the model (Seedance marks
sounds with angle brackets, H3 has its own shorter performance lock), on what the shot is
(a fight, a conversation, a silent shot) and on which pictures actually travel.
"""

import unittest

from app.core import clip_skeleton, h3_native, slice_video, style_packs
from app.core.asset_mentions import resolve_mentions
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt

_NUMBERS = {"姜照": 1, "张建国": 2, "旧茶馆": 3, "纸杯": 4, "红嫁衣": 5}


def _shot(**overrides) -> ShotPromptInput:
    values = dict(
        shot_index=1, duration_seconds=10, shot_size="近景", camera_movement="缓慢推近",
        subject_action="姜照把纸杯放在木柜台上，抬眼看向张建国", scene="旧茶馆大堂", blocking="姜照在柜台内，张建国在柜台外",
        start_state="姜照低头擦杯，张建国站定", end_state="姜照抬眼，张建国垂手", eyeline="姜照看向张建国",
        props=["纸杯"], characters=["姜照", "张建国"], lighting="窗侧主光", sound="环境音：雨声、远处车流；音效：纸杯放下",
        dialogue="姜照：你来晚了。\n张建国（低声）：路上堵。", cast_refs=["姜照", "张建国"], scene_refs=["旧茶馆"], prop_refs=["纸杯"],
        action_axis="沿柜台方向的轴线；机位在柜台外侧",
    )
    values.update(overrides)
    return ShotPromptInput(**values)


def _text(model: str = "seedance2.5", **overrides) -> str:
    return compile_shot_prompt(style_packs.FILM_35MM, _shot(**overrides), model=model).text


_FIGHT = dict(situations=["fight"], subject_action="姜照一记直拳击中张建国胸口，张建国后退半步", dialogue="")


class ThreePartTests(unittest.TestCase):
    def test_the_parts_come_in_order_with_their_content(self):
        text = _text()
        for earlier, later in (
            ("Pa1\n锚型定义", "【人物锚点·锁脸】"), ("【人物锚点·锁脸】", "对白语言："), ("对白语言：", "2 Conti Movs："),
            ("2 Conti Movs：", "\nPa2\n"), ("\nPa2\n", "空间坐标全程固定："), ("空间坐标全程固定：", "\nPa3\n"),
            ("\nPa3\n", "【关键约束】"), ("【关键约束】", "面部全程在变："), ("面部全程在变：", "话轮依次接上"),
            ("话轮依次接上", "禁止出现非台词和旁白的话外音。"), ("禁止随机文字。", "人物肖像安全约束："),
            ("人物肖像安全约束：", "视频文字与字幕约束："), ("视频文字与字幕约束：", "禁止出现：水印"),
        ):
            self.assertLess(text.index(earlier), text.index(later), f"{earlier} 应在 {later} 之前")

    def test_nothing_after_the_rules_carries_a_reference_mark(self):
        self.assertNotIn("@[", _text()[_text().index("【关键约束】"):])

    def test_the_fixed_sentences_are_not_counted_against_the_budget(self):
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.0")
        self.assertFalse(compiled.pressure.dropped, "一条普通对话镜头不该因为固定句被压缩")


class AnchorTypeTests(unittest.TestCase):
    def test_each_picture_is_given_one_type(self):
        text = _text()
        self.assertIn("锚型定义 各图只给本型内容 不给型外信息 不得由本图推断型外", text)
        for row in ("@[姜照]＝身份服装锚", "@[张建国]＝身份服装锚", "@[纸杯]＝道具锚", "@[旧茶馆]＝场景锚"):
            self.assertIn(row, text)
        self.assertIn("身份服装锚 脸型 发型 体型 服装", text)
        self.assertNotIn("戏服锚 服装版型 材质 层次", text, "没有戏服图就不解释戏服锚")

    def test_a_costume_picture_splits_identity_from_clothes(self):
        text = _text(costume_refs=[("姜照", "红嫁衣")], costume_images=["红嫁衣"])
        self.assertIn("@[姜照]＝身份锚", text)
        self.assertIn("@[红嫁衣]＝戏服锚", text)
        self.assertIn("@[张建国]＝身份服装锚", text)
        self.assertIn("@[姜照]、@[红嫁衣] 为同一人　@[姜照]、@[张建国] 各是不同的角色 禁止分身 不复制水印与无关路人", text)

    def test_a_costume_that_lives_on_the_look_picture_has_no_row_of_its_own(self):
        text = _text(costume_refs=[("姜照", "红嫁衣")])
        self.assertIn("@[姜照]＝身份服装锚", text)
        self.assertNotIn("戏服锚", text)
        self.assertNotIn("为同一人", text)
        self.assertIn("@[姜照]、@[张建国] 各是不同的角色 禁止分身 不复制水印与无关路人", text)

    def test_one_person_is_still_told_not_to_double(self):
        solo = dict(characters=["姜照"], cast_refs=["姜照"], dialogue="", eyeline="", subject_action="姜照把纸杯放在木柜台上")
        self.assertIn("\n禁止分身 不复制水印与无关路人\n", _text(**solo))
        costumed = _text(costume_refs=[("姜照", "红嫁衣")], costume_images=["红嫁衣"], **solo)
        self.assertIn("@[姜照]、@[红嫁衣] 为同一人 禁止分身 不复制水印与无关路人", costumed)
        numbers = {name: number for name, number in _NUMBERS.items() if name != "红嫁衣"}
        settled = clip_skeleton.settle(resolve_mentions(costumed, numbers))
        self.assertIn("\n禁止分身 不复制水印与无关路人\n", settled, "戏服图没发出去，这个人仍然不许分身")

    def test_a_shot_of_a_place_only_keeps_the_watermark_half(self):
        text = _text(characters=[], cast_refs=(), dialogue="", eyeline="", subject_action="雨打在旧茶馆的窗上", start_state="", end_state="")
        self.assertIn("\n不复制水印与无关路人\n", text)
        self.assertNotIn("禁止分身 不复制水印与无关路人", text)

    def test_a_shot_without_pictures_has_no_anchor_block(self):
        text = _text(cast_refs=(), scene_refs=(), prop_refs=())
        self.assertNotIn("锚型定义", text)
        self.assertNotIn("不复制水印与无关路人", text)
        self.assertTrue(text.startswith("Pa1\n"))


class SettleTests(unittest.TestCase):
    def _costumed(self) -> str:
        return _text(costume_refs=[("姜照", "红嫁衣")], costume_images=["红嫁衣"])

    def test_rows_follow_the_pictures_that_are_sent(self):
        settled = clip_skeleton.settle(resolve_mentions(self._costumed(), _NUMBERS))
        self.assertIn("姜照（参考图1）＝身份锚", settled)
        self.assertIn("红嫁衣（参考图5）＝戏服锚", settled)
        self.assertIn("姜照（参考图1）、红嫁衣（参考图5） 为同一人", settled)

    def test_a_costume_picture_that_is_not_sent_leaves_no_trace(self):
        numbers = {name: number for name, number in _NUMBERS.items() if name != "红嫁衣"}
        settled = clip_skeleton.settle(resolve_mentions(self._costumed(), numbers))
        self.assertNotIn("戏服锚", settled)
        self.assertNotIn("为同一人", settled)
        self.assertNotIn("＝身份锚", settled)
        self.assertIn("姜照（参考图1）＝身份服装锚", settled, "衣服没有单独的图，这个人的图就连服装一起管")
        self.assertIn("姜照（参考图1）、张建国（参考图2） 各是不同的角色 禁止分身 不复制水印与无关路人", settled)

    def test_unused_definitions_and_an_empty_header_go(self):
        settled = clip_skeleton.settle(resolve_mentions(_text(), {"姜照": 1, "张建国": 2}))
        self.assertIn("身份服装锚 脸型 发型 体型 服装", settled)
        for gone in ("道具锚 形制 材质 磨损", "＝道具锚", "场景锚 环境结构 陈设 材质", "＝场景锚"):
            self.assertNotIn(gone, settled)
        nothing = clip_skeleton.settle(resolve_mentions(_text(), {}))
        self.assertNotIn("锚型定义", nothing)
        self.assertNotIn("＝", nothing.split("【结构声明】")[0])

    def test_a_request_with_only_frames_names_no_pictures(self):
        settled = clip_skeleton.settle(resolve_mentions(self._costumed(), _NUMBERS), frames_only=True)
        self.assertNotIn("锚型定义", settled)
        self.assertNotIn("戏服锚", settled)
        self.assertNotIn("不复制水印与无关路人", settled)
        self.assertIn("Pa1\n", settled)

    def test_text_without_the_block_is_left_alone(self):
        self.assertEqual(clip_skeleton.settle("画面：姜照敲击键盘。"), "画面：姜照敲击键盘。")


class DialogueTests(unittest.TestCase):
    def test_the_language_line_names_who_speaks(self):
        self.assertIn("对白语言：@[姜照]、@[张建国] 说中文普通话，口型按该语言同步，不说别的语言。", _text())
        self.assertIn("说中文普通话（Mandarin Chinese），口型按该语言同步，不说别的语言。", _text("MiniMax-H3"))

    def test_an_off_screen_voice_has_no_lips_to_sync(self):
        text = _text(dialogue="旁白：那一夜没有人睡。")
        self.assertIn("对白语言：说话的人 说中文普通话，不说别的语言。", text)
        self.assertNotIn("口型按该语言同步", text)

    def test_a_shot_without_lines_has_no_language_line(self):
        text = _text(dialogue="")
        self.assertNotIn("对白语言：", text)
        self.assertNotIn("话轮依次接上", text)
        self.assertIn("视频文字与字幕约束：本镜头没有人物对话，禁止出现字幕。", text)

    def test_a_single_line_needs_no_turn_lock(self):
        self.assertNotIn("话轮依次接上", _text(dialogue="姜照：你来晚了。"))

    def test_a_silent_model_is_not_told_about_voices(self):
        text = _text("kling-v2", native_audio=False)
        self.assertNotIn("对白语言：", text)
        self.assertNotIn("禁止出现非台词和旁白的话外音。", text)
        self.assertIn("禁止随机文字。", text)


class PerformanceLockTests(unittest.TestCase):
    def test_each_model_family_has_its_own_wording(self):
        seedance = _text()
        self.assertIn("面部全程在变：眉眼先动，再口鼻，再身体，说完表情停在落点不回中性。", seedance)
        self.assertIn("接收者先动眼再动身，眉眼口鼻幅度做到四到六成，不自行收小。", seedance)
        h3 = _text("MiniMax-H3")
        self.assertIn("脸全程在变：眉眼先动，再口鼻，再身体，说完保持新表情。", h3)
        self.assertIn("听者先动眼再动身，眉眼口鼻幅度做到四到六成。", h3)
        self.assertIn("人物不叹气、不喘粗气、不长呼气、不发出叹气声。", h3)
        self.assertNotIn("不叹气", seedance)

    def test_a_scripted_sigh_is_allowed(self):
        self.assertNotIn("不叹气", _text("MiniMax-H3", subject_action="张建国叹了口气，把伞靠在柜台边"))
        self.assertIn("不叹气", _text("MiniMax-H3", subject_action="张建国赞叹地看着姜照"))

    def test_a_short_clip_gets_the_first_sentence_only(self):
        text = _text(duration_seconds=5)
        self.assertIn("面部全程在变：", text)
        self.assertNotIn("接收者先动眼再动身", text)

    def test_a_shot_without_people_has_no_performance_lock(self):
        text = _text(characters=[], cast_refs=(), dialogue="", subject_action="雨打在窗上", props=[], prop_refs=())
        self.assertNotIn("面部全程在变", text)
        self.assertNotIn("人物肖像安全约束", text)
        self.assertIn("禁止出现：水印、真实人物照片、真人肖像、名人脸。", text, "空镜里也不该冒出真人的脸")


class FightTests(unittest.TestCase):
    def test_a_fight_gets_its_lens_sound_and_chain_locks(self):
        text = _text(**_FIGHT)
        self.assertIn("镜头：运镜跟着动作走：出手快推急跟", text)
        self.assertIn("<拳脚打到肉的沉闷肉响>，<打到骨头的脆响>，<兵器或前臂相撞的短促硬响>，<被打者的闷哼>，都和接触在同一帧。", text)
        for sentence in (
            "回合依次接上，不重播上一招、不跳招。", "拳脚真的打到身上，不隔空、不穿身；挨过打的地方后面还疼，不回满血。",
            "全程都在本场景里，背景不变，不出现白底或棚拍背景。", "镜头从第一帧到最后一帧都在运动，不固定机位，不停在一个姿势上。",
        ):
            self.assertIn(sentence, text)
        self.assertIn("机位全程在两人连线的同一侧，不越轴，景别与切点按各镜头", text)

    def test_a_locked_off_fight_is_not_told_to_keep_moving(self):
        text = _text(**_FIGHT, camera_movement="固定机位")
        self.assertNotIn("镜头从第一帧到最后一帧都在运动", text)
        self.assertNotIn("镜头：运镜跟着动作走", text)
        self.assertIn("回合依次接上", text)

    def test_only_seedance_marks_sounds_with_brackets(self):
        h3 = _text("MiniMax-H3", **_FIGHT)
        self.assertIn("击打声与接触同帧：打到肉是沉闷的肉响", h3)
        self.assertNotIn("<拳脚", h3)
        self.assertIn("环境铺底：<雨声、远处车流>", _text())
        self.assertIn("的瞬间：<一声近处、轻短、偏闷、发软的接触声>，在嘈杂的环境里仍能分辨", _text(), "只括声音本身，不括它听起来怎样")
        self.assertIn("环境铺底：雨声、远处车流", _text("MiniMax-H3"))

    def test_a_conversation_has_no_fight_sentences(self):
        text = _text()
        for sentence in ("回合依次接上", "击打声", "<拳脚", "镜头：运镜跟着动作走"):
            self.assertNotIn(sentence, text)


class TailTests(unittest.TestCase):
    def test_invented_people_are_declared_fictional(self):
        text = _text()
        self.assertIn("人物肖像安全约束：画面中的人物均为原创虚构角色，不对应任何真实人物、公众人物或名人。", text)
        self.assertIn("禁止出现：水印、真实人物照片、真人肖像、名人脸。", text)
        self.assertIn("本镜头虽有人物对话，但台词字幕由后期统一合成叠加", text)

    def test_faces_are_not_hidden_unless_the_task_asks(self):
        text = _text()
        for hidden in ("正脸特写", "背影", "逆光轮廓", "侧后方"):
            self.assertNotIn(hidden, text.split("人物肖像安全约束：")[1])
        safe = _text(portrait_safe=True)
        self.assertIn("如出现人物，优先使用中远景、侧后方、低头、背影、逆光轮廓", safe)
        self.assertIn("禁止出现：水印、真实人物照片、真人肖像、名人脸、正脸特写。", safe)

    def test_a_real_actor_is_not_called_fictional(self):
        text = _text(real_person=True)
        self.assertNotIn("原创虚构角色", text)
        self.assertNotIn("真人肖像", text)
        self.assertIn("禁止出现：水印。", text)
        self.assertIn("面部全程在变：", text)


class SliceTests(unittest.TestCase):
    def _slice(self, model: str = "MiniMax-H3", **second) -> str:
        costume = dict(costume_refs=[("姜照", "红嫁衣")], costume_images=["红嫁衣"])
        first = compile_shot_prompt(style_packs.FILM_35MM, _shot(dialogue="姜照：你来晚了。", duration_seconds=5, **costume), model=model)
        values = dict(shot_index=2, duration_seconds=5, shot_size="中景", dialogue="张建国（低声）：路上堵。", **costume)
        values.update(second)
        then = compile_shot_prompt(style_packs.FILM_35MM, _shot(**values), model=model)
        beats = [slice_video.Beat(first.sections, size="近景", motion="缓慢推近"), slice_video.Beat(then.sections, size="中景", motion="固定机位")]
        return slice_video.compile_prompt(
            beats, model=model, cast=["姜照", "张建国"], scenes=["旧茶馆"], props=["纸杯"], costumes=[("姜照", "红嫁衣")],
        ).text

    def test_a_slice_states_each_fixed_sentence_once(self):
        text = self._slice()
        for once in ("Pa1", "Pa2", "Pa3", "锚型定义", "2 Conti Movs：", "对白语言：", "空间坐标全程固定：", "禁止随机文字。", "禁止出现："):
            self.assertEqual(text.count(once), 1, once)
        self.assertIn("@[姜照]＝身份锚", text)
        self.assertIn("@[红嫁衣]＝戏服锚", text)
        self.assertIn("@[姜照]、@[红嫁衣] 为同一人", text)

    def test_the_speakers_of_every_beat_share_one_language_line(self):
        self.assertIn("对白语言：@[姜照]、@[张建国] 说中文普通话（Mandarin Chinese），口型按该语言同步，不说别的语言。", self._slice())

    def test_two_beats_with_lines_are_two_turns(self):
        text = self._slice("seedance2.5")
        self.assertIn("话轮依次接上，说过的话不重说。", text)
        self.assertIn("接收者先动眼再动身", text, "两拍合起来够长，表演锁写全")
        self.assertIn("本镜头虽有人物对话", text)
        self.assertLess(text.index("2 Conti Movs："), text.index("【镜头1/2"))

    def test_a_sigh_in_any_beat_lifts_the_ban(self):
        self.assertIn("不叹气", self._slice())
        self.assertNotIn("不叹气", self._slice(subject_action="张建国叹了口气，把伞靠在柜台边"))

    def test_beats_from_before_the_skeleton_stay_as_they_were(self):
        beats = [slice_video.Beat({"subject": "画面：姜照擦杯。"}), slice_video.Beat({"subject": "画面：张建国进门。"})]
        text = slice_video.compile_prompt(beats, model="seedance2.5", cast=["姜照"]).text
        for added in ("Pa1", "Pa3", "锚型定义", "禁止出现："):
            self.assertNotIn(added, text)


class RewriteTests(unittest.TestCase):
    def test_headers_and_the_tail_are_not_handed_to_the_h3_rewriter(self):
        sections = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="MiniMax-H3").sections
        board = h3_native.board_text(sections)
        for kept_out in ("Pa1", "Pa2", "Pa3", "2 Conti Movs：", "人物肖像安全约束", "视频文字与字幕约束", "禁止出现："):
            self.assertNotIn(kept_out, board)
        for kept in ("锚型定义", "对白语言：", "空间坐标全程固定：", "脸全程在变："):
            self.assertIn(kept, board)


if __name__ == "__main__":
    unittest.main()
