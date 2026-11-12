# -*- coding: utf-8 -*-
"""Seedance 2.0 的整条 2000 字上限：发出前只去重(名字只绑定一次参考图、重复的锚点与站位只留一遍、铁律合成一行)，
分镜、运镜、台词、声音与时间轴句一个字不删；不紧的模型、不超的提示词、人工改过的提示词都原样发。"""

import re
import unittest

from app.core import style_packs, tight_prompt
from app.core.asset_mentions import resolve_mentions
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt

NUMBERS = {"姜照": 2, "张建国": 4, "阳间墓园售后工位": 6}
FILLER = "；".join(f"第{n}道光斑在屏幕边缘缓慢移动" for n in range(1, 40))
RULES = "\n".join([
    "【关键约束】",
    "物理铁律：参考图与物理冲突时以物理为准：不反向、不瞬移、不突然加速。",
    "动作顺序铁律：画面里的动作按写明的先后一步一步完成。",
    "，严守跨镜连贯六锚点：同一人物同一张脸同一发型同一服装。",
    "音色铁律：姜照：28岁女声，清亮平稳；全片音色、音调与声线不变",
    "情绪叠加：姜照本镜情绪（平静）只改变语气、力度与停顿",
    "禁止空间重构 + 禁止比例畸变 + NOT cartoon + 无字幕 + 无水印",
    "禁止出现：水印、真实人物照片、真人肖像、名人脸。",
    "人物肖像安全约束：画面中的人物均为原创虚构角色，不对应任何真实人物、公众人物或名人。",
])


def _shot(**overrides):
    values = dict(
        shot_index=3, duration_seconds=8, shot_size="中景转近景", camera_movement="固定机位，缓慢推近",
        subject_action="姜照敲击键盘，张建国在电话那头沉默；" + FILLER, scene="阳间墓园售后工位",
        blocking="姜照居左下，张建国居右上", start_state="姜照盯着屏幕", end_state="手机滑落",
        characters=["姜照", "张建国"], dialogue="姜照（平静）：您说的是那套别墅吗？",
        cast_refs=["姜照", "张建国"], scene_refs=["阳间墓园售后工位"],
        composition="对角线构图：姜照居画面左下方，张建国居右上方",
    )
    values.update(overrides)
    return ShotPromptInput(**values)


def _prompt(**overrides) -> str:
    text = compile_shot_prompt(style_packs.FILM_35MM, _shot(**overrides), model="seedance2.0").text
    return "参考图1是开场画面，只决定开场构图、站位与光线；\n" + resolve_mentions(text, NUMBERS) + "\n" + RULES


def _clauses(text: str) -> list[str]:
    plain = re.sub(r"（参考图\d+）", "", text)
    return [part.strip() for part in re.split(r"[；。\n]", plain) if len(part.strip()) >= 4]


class CompactTests(unittest.TestCase):
    def test_only_tight_models_and_only_when_over(self):
        long = _prompt()
        for model in ("MiniMax-H3", "seedance2.5", "doubao-seedance-2-5-260128", "kling"):
            with self.subTest(model):
                text, fit = tight_prompt.compact(long, model)
                self.assertEqual(text, long)
                self.assertEqual(fit.steps, [])
        short = "画面：姜照（参考图2）推门。"
        self.assertEqual(tight_prompt.compact(short, "seedance2.0")[0], short, "不超就一字不改")
        self.assertEqual(tight_prompt.tight_limit("doubao-seedance-2-0-260128"), 2000)

    def test_the_shot_body_survives_word_for_word(self):
        before = _prompt()
        after, fit = tight_prompt.compact(before, "seedance2.0")
        self.assertLess(fit.after, fit.before)
        plain_after = re.sub(r"（参考图\d+）", "", after)
        body = [line for line in before.split("\n") if line.startswith(("画面：", "景别：", "构图：", "台词", "【结构声明】"))]
        self.assertTrue(body)
        for line in body:
            for clause in _clauses(line):
                core = re.sub(r"^[^：:，,。；]{1,6}[：:]", "", clause)
                self.assertIn(core, plain_after, f"正文丢了：{core}")
        self.assertIn("姜照（平静）{您说的是那套别墅吗？}", after, "台词逐字")

    def test_names_are_bound_once_and_the_opening_frame_line_stays(self):
        after, fit = tight_prompt.compact(_prompt(), "seedance2.0")
        lines = after.split("\n")
        self.assertTrue(lines[0].startswith("参考图1是开场画面"))
        self.assertTrue(lines[1].startswith("参考图绑定：姜照＝参考图2（"), lines[1])
        self.assertIn("张建国＝参考图4（", lines[1])
        self.assertIn("阳间墓园售后工位＝参考图6（", lines[1])
        self.assertEqual(re.findall(r"（参考图\d+）", "\n".join(lines[2:])), [], "名字只在绑定行带参考图号")
        self.assertIn("names", fit.steps)

    def test_the_rules_become_one_line_and_voice_and_safety_stay(self):
        after, _fit = tight_prompt.compact(_prompt(), "seedance2.0")
        constraints = tight_prompt._rules()["constraints"]
        self.assertEqual(after.count(constraints), 1)
        for gone in ("物理铁律：", "动作顺序铁律：", "严守跨镜连贯六锚点", "禁止空间重构", "禁止出现：水印"):
            self.assertNotIn(gone, after)
        for kept in ("音色铁律：姜照：28岁女声", "情绪叠加：姜照本镜情绪", "人物肖像安全约束："):
            self.assertIn(kept, after)
        self.assertLess(after.index("【关键约束】"), after.index(constraints))

    def test_scene_specific_negatives_stay_and_generic_ones_fold(self):
        from app.core import style_packs

        pack = style_packs.get_pack(style_packs.DEFAULT_PACK_ID)
        terms = style_packs.negatives_for(pack, ["fight"], extra=["no red umbrellas"])
        before = _prompt().replace("禁止空间重构 + 禁止比例畸变 + NOT cartoon + 无字幕 + 无水印", " + ".join(terms))
        after, _fit = tight_prompt.compact(before, "seedance2.0")
        for kept in ("no foot sliding", "no red umbrellas"):
            self.assertIn(kept, after)
        for gone in pack.negatives:
            self.assertNotIn(" + " + gone + " + ", " + " + after + " + ")

    def test_a_scene_image_demoted_by_the_staging_desk_gives_only_its_look(self):
        """导演台白模排第二张、演员第三张、场景第五张(默认路由)：降级标签按每张图自己那段职责句认，不贴到演员身上。"""
        from app.core import prompt_data

        marker = prompt_data.load("scene_views")["desk_demoted_marker"]
        opening = ("参考图1是开场画面，只决定开场构图、站位与光线；参考图2是导演台白模，只决定空间结构、人物站位与家具位置，"
                   "材质、颜色与光线不照它；")
        text = "\n".join([
            opening,
            "【人物锚点·锁脸】林夏（参考图3）。脸型、发型、服装与体型以参考图为准。",
            "林夏（参考图3）＝身份服装锚",
            "书房（参考图5）＝场景锚",
            f"【场景锚点·锁场景】书房（参考图5）。灯光色调、材质与环境动态保持一致，{marker}；",
            "【参考素材职责】",
            "参考图3仅锁定数字演员设定集「林夏」的脸型、发型、体型与服装，不采用图中背景；"
            f"参考图5仅锁定拍摄场地「书房」正面的材质、色调、光影与年代感，天色以本场为准，{marker}（不采用图中人物）。",
            "固定：书案、窗位置全程不变，人物不换位。",
            "画面：林夏（参考图3）在书房（参考图5）里翻书。" + FILLER * 3,
        ])
        after, _fit = tight_prompt.compact(text, "seedance2.0")
        lines = after.split("\n")
        self.assertEqual(lines[0], opening, "开场画面与导演台白模那句照留")
        binding = lines[1]
        self.assertTrue(binding.startswith("参考图绑定："), binding)
        demoted = tight_prompt._rules()["binding"]["gives_desk_demoted"]
        self.assertIn("书房＝参考图5（" + demoted + "）", binding)
        self.assertIn("林夏＝参考图3（脸型、发型、体型、服装）", binding, "演员不拿场景图的降级标签")
        self.assertNotIn("参考图5（环境结构", binding, "场景图不再和白模抢站位")
        self.assertIn("固定：书案、窗位置全程不变，人物不换位。", after)
        normal, _fit = tight_prompt.compact(text.replace(marker, "布局照旧"), "seedance2.0")
        self.assertIn("书房＝参考图5（环境结构、陈设、材质）", normal)

    def test_anchor_type_lines_follow_the_skeleton_table(self):
        """锚型定义行按 clip_skeleton 的锚型表认：带导演台白模时的「场景质感锚」也删，绑定行写它给的东西。"""
        text = "\n".join([
            "锚型定义 各图只给本型内容",
            "身份服装锚 脸型 发型 体型 服装",
            "场景质感锚 材质 色调 光影",
            "林夏（参考图3）＝身份服装锚",
            "书房（参考图5）＝场景质感锚",
            "画面：林夏（参考图3）在书房（参考图5）里翻书。" + FILLER * 3,
        ])
        after, _fit = tight_prompt.compact(text, "seedance2.0")
        self.assertNotIn("场景质感锚 材质", after)
        self.assertNotIn("身份服装锚 脸型", after)
        self.assertNotIn("＝场景质感锚", after)
        self.assertIn("书房＝参考图5（材质、色调、光影）", after, "新锚型的定义直接进绑定行")

    def test_appearance_text_goes_only_for_people_with_a_reference_image(self):
        text = "\n".join([
            "参考图绑定前的正文：姜照（参考图2）推门。" + FILLER * 3,
            "人物外貌：姜照（参考图2）：二十七八岁、短发。路人甲：五十岁、灰布长衫、跛左脚。",
        ])
        after, _fit = tight_prompt.compact(text, "seedance2.0")
        self.assertNotIn("二十七八岁", after)
        self.assertIn("路人甲：五十岁、灰布长衫、跛左脚。", after)

    def test_a_name_glued_to_earlier_words_is_still_the_name(self):
        text = "【人物锚点·锁脸】谢九（参考图4）。\n画面：看向画内的谢九（参考图4），随后谢九（参考图4）低头。" + FILLER * 3
        after, _fit = tight_prompt.compact(text, "seedance2.0")
        self.assertIn("谢九＝参考图4（", after)
        self.assertIn("看向画内的谢九，随后谢九低头", after)

    def test_repeats_go_but_dialogue_and_timeline_lines_stay(self):
        axis = "全场机位守在轴线同一侧，姜照恒在画左、张建国恒在画右"
        timeline = [
            "【镜头1/2｜中景｜0—4秒】机位切换，人物站位与朝向不变。",
            "一段只做一个主要变化，做完再接下一步；没写的动作不加，可以停顿。",
            "张建国听到“别墅”之后才抬头，此前保持原状。",
            "【镜头2/2｜近景｜4—8秒】机位切换，人物站位与朝向不变。",
            "姜照全程背对镜头，不转身。",
            "到达后保持到片尾，不再增加新动作。",
        ]
        text = "\n".join([
            "轴线：" + axis + "。",
            "画面：" + FILLER + "；" + axis + "。",
            "台词（逐字保持原文，口型同步）：姜照{" + axis + "。}",
            *timeline,
            "画面：" + FILLER * 2,
        ])
        after, fit = tight_prompt.compact(text, "seedance2.0")
        self.assertIn("repeats", fit.steps)
        self.assertEqual(after.count(axis), 2, "画面里那次删掉，台词里那次不动")
        self.assertIn("{" + axis + "。}", after)
        for line in timeline:
            self.assertIn(line, after)

    def test_still_over_is_sent_whole_with_a_note(self):
        after, fit = tight_prompt.compact(_prompt(subject_action="姜照敲击键盘；" + FILLER * 3), "seedance2.0")
        self.assertTrue(fit.over)
        self.assertIn("Seedance 2.5", fit.note)
        self.assertIn(str(fit.after), fit.note)
        self.assertEqual(fit.as_dict()["after"], len(after))


if __name__ == "__main__":
    unittest.main()
