# -*- coding: utf-8 -*-
"""Style packs, per-model prompt budgets and the layered video prompt they build.

The look a production commits to has to reach every prompt unchanged, the budget has to
cut the right things in the right order, and an animated production must not be told to
look photoreal. No model and no network.
"""

import unittest
import unittest.mock

from app.core import prompt_budget, style_packs
from app.core.style_packs import PaletteColour
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt, extension_prompt


def _shot(**overrides) -> ShotPromptInput:
    values = dict(
        shot_index=2, duration_seconds=6, shot_size="近景", camera_movement="缓推",
        subject_action="林夏盯着对面，手指攥紧录音笔", scene="办公室 夜 内景",
        blocking="林夏画左、周教授画右，相距2.6米面对面", start_state="林夏坐在桌前，录音笔在右手",
        end_state="林夏抬眼看向周教授", eyeline="林夏看向画右", props=["录音笔"],
        characters=["林夏", "周教授"], lighting="冷白顶光（5000K，光比3:1）",
        sound="环境音：空调低鸣·远；动作音：按键咔哒", dialogue="你到底瞒了什么？",
    )
    values.update(overrides)
    return ShotPromptInput(**values)


class PackSelectionTests(unittest.TestCase):
    def test_a_production_without_a_setting_keeps_the_projects_own_look(self):
        pack = style_packs.resolve_pack({})
        self.assertEqual(pack.id, style_packs.DEFAULT_PACK_ID)
        self.assertEqual(pack.medium, "live_action")
        # The default caption is the one the gateway has always sent to Ark.
        self.assertIn("photorealistic live-action cinematic film still", pack.style_caption)

    def test_the_setting_wins_over_the_words_and_the_longest_word_wins(self):
        self.assertEqual(style_packs.resolve_pack({"style_pack": "atom_punk", "director_style": "写实"}).id, "atom_punk")
        self.assertEqual(style_packs.resolve_pack({"style_pack": "ATOM-PUNK"}).id, "atom_punk")
        self.assertEqual(style_packs.resolve_pack({"director_style": "3D国漫仙侠"}).id, "anime_3d_cg")
        self.assertEqual(style_packs.resolve_pack({"director_style": "日漫赛璐珞"}).id, "anime_2d_cel")
        self.assertEqual(style_packs.resolve_pack({"visual_style": "35mm 胶片"}).id, "film_35mm")
        # An unknown setting is the default, never an error.
        self.assertEqual(style_packs.resolve_pack({"style_pack": "no_such_pack"}).id, style_packs.DEFAULT_PACK_ID)

    def test_every_pack_states_its_look_its_negatives_and_how_an_extension_restates_it(self):
        for pack in style_packs.list_packs():
            with self.subTest(pack.id):
                self.assertTrue(pack.lock_text.startswith("[STYLE LOCK]"), pack.id)
                self.assertGreaterEqual(len(pack.negatives), 5)
                self.assertIn("无字幕", pack.negatives)
                self.assertTrue(pack.extension_restatement.strip())
                self.assertTrue(pack.sound.closing_sentence.strip())
                anime = pack.medium in {"anime_2d", "anime_3d"}
                bans_photoreal = any(
                    "photorealistic" in term.lower() or "live action" in term.lower() or "live-action" in term.lower()
                    for term in pack.negatives
                )
                self.assertEqual(anime, bans_photoreal, f"{pack.id} 的负向词应当与它的介质一致")


class StyleLayerTests(unittest.TestCase):
    def test_the_lock_is_verbatim_and_only_the_tone_line_changes(self):
        pack = style_packs.FILM_35MM
        first = style_packs.style_lock_block(pack, {"动作/情绪参考片": "是枝裕和式日常静默", "光线时段": "夜晚practical light"})
        second = style_packs.style_lock_block(pack, {"动作/情绪参考片": "港产追逐"})
        self.assertIn(pack.lock_text, first)
        self.assertIn(pack.lock_text, second)
        self.assertIn("是枝裕和式日常静默", first)
        self.assertIn("夜晚practical light", first)
        # A slot left empty keeps the pack's default for that slot.
        self.assertIn("克制张力", second)
        self.assertEqual(style_packs.style_lock_block(pack).splitlines()[-1], pack.tone_default + "。")

    def test_a_colour_card_carries_the_through_colours_and_refuses_an_abstract_binding(self):
        pack = style_packs.ATOM_PUNK
        card = style_packs.build_palette_card(
            pack, project="丧尸清道夫", episode=1, segment=2, subject="加油站",
            new_colours=[PaletteColour(name="警示红", hex="#FF4444", bound_to="警示灯")],
        )
        self.assertEqual(card.title, "丧尸清道夫 EP1 SEG2 - 加油站 COLOR REFERENCE")
        self.assertEqual([colour.hex for colour in card.colours][:3], ["#FFBF00", "#4A7C59", "#2C3539"])
        self.assertEqual(card.carried, 3)
        lines = style_packs.palette_lines(card, "@图片3")
        self.assertIn("@图片3作为整段色卡锚定", lines[0])
        self.assertIn("所有色彩严格按色卡4色执行", lines[0])
        self.assertIn("警示灯警示红#FF4444", lines[1])

        with self.assertRaisesRegex(ValueError, "必须绑定具体物件"):
            style_packs.build_palette_card(
                pack, project="p", episode=1, segment=1, subject="s",
                new_colours=[PaletteColour(name="灰", hex="#888888", bound_to="阴影")],
            )
        with self.assertRaisesRegex(ValueError, "色卡最多"):
            style_packs.build_palette_card(
                pack, project="p", episode=1, segment=1, subject="s",
                new_colours=[PaletteColour(name=f"色{index}", hex=f"#{index:02d}00AA", bound_to=f"物件{index}") for index in range(1, 14)],
            )

    def test_named_rules_cover_the_cast_the_reference_media_and_the_pack(self):
        rules = style_packs.iron_rules(
            style_packs.FILM_35MM, subjects=["林夏", "周教授"],
            reference_kinds=["five_view", "palette_card", "blockout"], rule_ids=["camera", "extension"],
        )
        joined = "\n".join(rules)
        self.assertIn("机位铁律", joined)
        self.assertIn("延长重申铁律：全片保持35mm胶片质感", joined)
        self.assertIn("多人身份铁律", joined)          # two subjects add it without being asked
        self.assertIn("设定图反偷懒铁律", joined)
        self.assertIn("色卡反偷懒铁律", joined)
        self.assertIn("白模反偷懒铁律", joined)
        self.assertNotIn("故事板反偷懒铁律", joined)   # no storyboard reference in this shot
        with self.assertRaises(KeyError):
            style_packs.iron_rules(style_packs.FILM_35MM, rule_ids=["no_such_rule"])

    def test_negatives_add_the_situations_and_never_repeat_a_term(self):
        terms = style_packs.negatives_for(style_packs.ATOM_PUNK, ["multi_person", "night"], ["NOT modern vehicles", "无字幕"])
        self.assertEqual(len(terms), len(set(terms)))
        self.assertIn("no character face-swap", terms)
        self.assertIn("NOT clear blue sky", terms)
        self.assertIn("NOT modern vehicles", terms)

    def test_an_animated_pack_is_not_told_to_look_photoreal(self):
        base = "(避免：清晰可识别的正面真人脸；并严禁任何非写实风格：动画、卡通、3d render, illustration)"
        live = style_packs.identity_negative(style_packs.FILM_35MM, base)
        anime = style_packs.identity_negative(style_packs.ANIME_2D_CEL, base)
        self.assertEqual(live, base)
        self.assertIn("清晰可识别的正面真人脸", anime)
        self.assertNotIn("并严禁任何非写实风格", anime)
        self.assertTrue(anime.endswith(")"))
        self.assertIn("cel-shaded anime", style_packs.image_style_line(style_packs.ANIME_2D_CEL))
        self.assertIn("画幅 9:16", style_packs.image_style_line(style_packs.ANIME_2D_CEL))


class BudgetTests(unittest.TestCase):
    def test_each_model_has_its_own_budget_and_sora_has_none(self):
        self.assertEqual(prompt_budget.prompt_budget("seedance2.5"), 900)
        self.assertEqual(prompt_budget.prompt_budget("doubao-seedance-2-5-260128"), 900)
        self.assertEqual(prompt_budget.prompt_budget("seedance2.0"), 600)
        self.assertEqual(prompt_budget.prompt_budget("kling-2.6"), 500)
        self.assertIsNone(prompt_budget.prompt_budget("sora"))
        self.assertEqual(prompt_budget.prompt_budget("brand-new-model"), prompt_budget.DEFAULT_BUDGET[1])

    def test_pressure_grades_against_the_budget(self):
        self.assertEqual(prompt_budget.pressure("字" * 400, "seedance2.5").tier, "green")
        self.assertEqual(prompt_budget.pressure("字" * 850, "seedance2.5").tier, "yellow")
        report = prompt_budget.pressure("字" * 1200, "seedance2.5")
        self.assertEqual((report.tier, report.ratio), ("red", 1.33))
        self.assertEqual(prompt_budget.pressure("字" * 9000, "sora").tier, "unlimited")
        self.assertEqual(prompt_budget.prompt_length(" 一 二\n三 "), 3)

    def test_sections_are_cut_in_order_and_the_load_bearing_ones_never_are(self):
        sections = {
            "style_lock": "锁" * 200, "locks": "锚" * 120, "subject": "主体" * 100, "camera": "机位近景缓推",
            "dialogue": "台词：你到底瞒了什么？", "sound": "音效" * 40, "environment": "环境" * 40,
            "light": "光线：冷白顶光（5000K，光比3:1）侧逆光", "colour": "色" * 40, "effects": "特效" * 30,
            "dialogue_notes": "情绪" * 20, "rules": "铁律" * 60,
        }
        kept, report = prompt_budget.compress(sections, "jimeng")
        self.assertEqual(report.dropped[:2], ["sound", "environment"])
        self.assertIn("light", report.trimmed)
        self.assertNotIn("5000K", kept["light"])
        for key in ("style_lock", "locks", "subject", "camera", "dialogue", "rules"):
            self.assertIn(key, kept, key)
        self.assertLessEqual(report.length, report.budget)
        # The fixed layers are restated every time and are not measured against the budget.
        self.assertGreater(report.total_length, report.length)

    def test_a_long_description_is_never_cut_even_over_budget(self):
        sections = {"locks": "锚" * 50, "subject": "主体。" * 200, "camera": "机位"}
        kept, report = prompt_budget.compress(sections, "vidu")
        self.assertEqual(kept["subject"], sections["subject"])
        self.assertNotIn("subject", report.trimmed)
        self.assertEqual(report.tier, "red")


class GatewayLookTests(unittest.TestCase):
    def setUp(self):
        from app.core.model_gateway import ModelGateway

        self.gateway = ModelGateway()

    def test_a_clip_is_clamped_to_the_chosen_models_own_ceiling(self):
        self.assertEqual(self.gateway.ark_clip_seconds("doubao-seedance-2-5-260128", 30), 30)
        self.assertEqual(self.gateway.ark_clip_seconds("seedance2.5", 40), 30)
        self.assertEqual(self.gateway.ark_clip_seconds("seedance2.0", 30), 15)
        self.assertEqual(self.gateway.ark_clip_seconds("seedance2.5", 2), 4)

    def test_the_pack_decides_the_anchor_caption_and_whether_photoreal_words_are_added(self):
        sent = {}

        def fake_ark(api_key, base_url, prompt, **kwargs):
            sent["prompt"] = prompt
            sent["style_caption"] = kwargs.get("style_caption")
            return "http://video.test/clip.mp4"

        with unittest.mock.patch.object(self.gateway, "_ark_video", side_effect=fake_ark), \
             unittest.mock.patch.object(self.gateway, "_is_valid_key", return_value=True), \
             unittest.mock.patch.object(self.gateway, "optimize_video_prompt", side_effect=lambda text, **_: text):
            self.gateway.generate_video("seedance2.5", "https://cdn.test/frame.jpeg", "林夏走进办公室", style_pack="anime_2d_cel")
            anime_prompt, anime_caption = sent["prompt"], sent["style_caption"]
            self.gateway.generate_video("seedance2.5", "https://cdn.test/frame.jpeg", "林夏走进办公室", style_pack="film_35mm")
            film_prompt, film_caption = sent["prompt"], sent["style_caption"]

        self.assertEqual(anime_caption, style_packs.ANIME_2D_CEL.style_caption)
        self.assertEqual(film_caption, style_packs.FILM_35MM.style_caption)
        # The photoreal enhancer (grain, depth of field, film look) is for live action only.
        self.assertNotIn("film grain", anime_prompt)
        self.assertIn("film grain", film_prompt)


class StylePackApiTests(unittest.TestCase):
    def test_the_catalog_lists_every_pack_with_what_a_picker_needs(self):
        from fastapi.testclient import TestClient

        from app.api.auth_api import get_current_user
        from main import app

        app.dependency_overrides[get_current_user] = lambda: {"user_id": "style-user", "role": "user"}
        try:
            response = TestClient(app).get("/api/production/style-packs")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default"], style_packs.DEFAULT_PACK_ID)
        by_id = {pack["id"]: pack for pack in payload["packs"]}
        self.assertEqual(set(by_id), {pack.id for pack in style_packs.list_packs()})
        atom = by_id["atom_punk"]
        self.assertEqual(atom["medium"], "live_action")
        self.assertTrue(atom["name"] and atom["summary"])
        self.assertIn("#FFBF00", [colour["hex"] for colour in atom["through_colours"]])
        self.assertTrue(atom["lock"])


class TaskConfigTests(unittest.TestCase):
    """Creating a project locks a look; updating other settings must not unlock it."""

    def setUp(self):
        import tempfile
        from pathlib import Path as _Path

        from app.repository.task_repo import TaskRepository
        from app.schema.drama import DramaCreateRequest
        from app.service.drama_service import DramaService

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(_Path(self.temp.name) / "tasks.json"))
        self.request = DramaCreateRequest

    def test_the_chosen_pack_is_stored_and_survives_a_config_update(self):
        created = self.service.create_task(self.request(title_suggestion="废土求生", style_pack="atom_punk"))
        task_id = created["task_id"]
        self.assertEqual(created["config"]["style_pack"], "atom_punk")

        updated = self.service.update_task_config(task_id, self.request(title_suggestion="废土求生", video_model="seedance2.5"))
        self.assertEqual(updated["config"]["style_pack"], "atom_punk")

        switched = self.service.update_task_config(
            task_id, self.request(title_suggestion="废土求生", style_pack="anime_2d_cel"),
        )
        self.assertEqual(switched["config"]["style_pack"], "anime_2d_cel")

    def test_a_project_created_without_a_pack_takes_one_from_its_style_words(self):
        created = self.service.create_task(self.request(title_suggestion="仙侠", director_style="anime"))
        self.assertEqual(created["config"]["style_pack"], "anime_2d_cel")
        default = self.service.create_task(self.request(title_suggestion="都市"))
        self.assertEqual(default["config"]["style_pack"], style_packs.DEFAULT_PACK_ID)


class VideoPromptTests(unittest.TestCase):
    def test_the_prompt_is_layered_in_one_fixed_order(self):
        """《运镜提示词》三段：Pa1 锚点、结构、锁、镜头块；Pa2 风格、外貌、画质、声音；Pa3 铁律。"""
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(cast_refs=["林夏", "周教授"]), model="seedance2.5")
        text = compiled.text
        self.assertTrue(text.startswith("【人物锚点·锁脸】"))
        for earlier, later in (
            ("【人物锚点·锁脸】", "【结构声明】"), ("【结构声明】", "[空间锚]"), ("[空间锚]", "景别：近景"),
            ("景别：近景", "台词（逐字保持原文"), ("台词（逐字保持原文", "落幅："), ("落幅：", "[STYLE LOCK]"),
            ("[STYLE LOCK]", "画质："), ("画质：", "【声音设计】"), ("【声音设计】", "不要BGM"), ("不要BGM", "【关键约束】"),
        ):
            self.assertLess(text.index(earlier), text.index(later), f"{earlier} 应在 {later} 之前")
        for tag in ("[空间锚]", "[状态锁]", "[道具锁]", "[光影锁]", "[声音锁]"):
            self.assertIn(tag, text)
        self.assertIn("单镜连续画面，一镜到底不切镜", text)
        self.assertNotRegex(text, r"(?<!\d)\d{1,2}\s*[-–~至]\s*\d{1,2}\s*(?:s|秒)", "no absolute second ranges")
        self.assertIn("不要BGM", text)
        self.assertIn("多人身份铁律", text)        # two characters in frame
        self.assertIn("口型同步铁律", text)        # the shot has a line
        self.assertEqual(compiled.style_pack, "film_35mm")

    def test_the_cast_line_declares_the_people_distinct_and_binds_each_costume(self):
        compiled = compile_shot_prompt(
            style_packs.FILM_35MM,
            _shot(cast_refs=["林夏", "周教授"], costume_refs=[("林夏", "林夏·深蓝西装"), ("周教授", "周教授·灰呢外套")]),
            model="seedance2.5",
        )
        text = compiled.text
        self.assertIn("@[林夏]、@[周教授]是2个不同的人，互不相像，各自在画面里只出现一次；同一人物的多张参考图属于同一个人", text)
        self.assertIn("【服装绑定】@[林夏]全程穿@[林夏·深蓝西装]；@[周教授]全程穿@[周教授·灰呢外套]，款式、颜色与配饰以参考图为准，不换装", text)
        self.assertLess(text.index("【服装绑定】"), text.index("【结构声明】"))
        alone = compile_shot_prompt(style_packs.FILM_35MM, _shot(cast_refs=["林夏"], characters=["林夏"]), model="seedance2.5").text
        self.assertIn("画面里只有这一个人，只出现一次", alone)
        self.assertNotIn("【服装绑定】", alone)

    def test_a_picture_that_already_ends_with_a_full_stop_does_not_get_a_second_one(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(subject_action="林夏盯着对面。"), model="seedance2.5").text
        self.assertIn("画面：林夏盯着对面。\n", text)
        self.assertNotIn("。。", text)

    def test_the_props_lock_says_who_holds_what(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text
        self.assertIn("[道具锁]录音笔：林夏持有", text, "「林夏坐在桌前，录音笔在右手」：拿着的人在前一个分句里")
        unowned = compile_shot_prompt(
            style_packs.FILM_35MM, _shot(start_state="桌上放着录音笔", subject_action="林夏盯着对面"), model="seedance2.5",
        ).text
        self.assertIn("[道具锁]录音笔\n", unowned, "no holder in the text: no holder is invented")

    def test_each_person_gets_a_short_appearance_line_cut_to_the_shot_size(self):
        looks = {
            "林夏": "骨相：瓜子脸、浅眼窝；五官：内双、鼻尖圆钝；皮肤：冷白；毛发：黑色低马尾；体态：清瘦，四肢修长",
            "周教授": "身份锚点：反派/周教授（系主任）、男性、五十多岁；毛发：花白短发；其他固定特征：金丝眼镜",
        }
        close = compile_shot_prompt(style_packs.FILM_35MM, _shot(cast_looks=looks), model="seedance2.5").text
        self.assertIn("人物外貌：@[林夏]：瓜子脸、浅眼窝；内双、鼻尖圆钝；冷白；黑色低马尾。@[周教授]：男性、五十多岁；花白短发；金丝眼镜。", close)
        self.assertNotIn("反派", close, "the role and the name are not a look")
        self.assertNotIn("骨相：", close, "layer labels are for the audit, not the model")
        self.assertNotIn("四肢修长", close, "a close shot does not describe the limbs")
        wide = compile_shot_prompt(style_packs.FILM_35MM, _shot(cast_looks=looks, shot_size="全景"), model="seedance2.5").text
        self.assertIn("清瘦、四肢修长", wide)
        long_look = {"林夏": "；".join(f"特征{n}" for n in range(40))}
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(cast_looks=long_look), model="seedance2.5").text
        line = text.split("人物外貌：", 1)[1].split("\n", 1)[0]
        self.assertLessEqual(len(line), 100, line)
        self.assertNotIn("人物外貌", compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text)

    def test_every_pack_states_what_good_picture_quality_means_for_its_medium(self):
        for pack in style_packs.list_packs():
            text = compile_shot_prompt(pack, _shot(), model="seedance2.5").text
            self.assertIn("画质：", text, pack.id)
            self.assertIn("锐利不糊", text, pack.id)
            if pack.medium == "live_action":
                self.assertIn("皮肤毛孔与布料纤维清晰", text, pack.id)
            else:
                self.assertNotIn("皮肤毛孔", text, pack.id)
        self.assertIn("线条粗细稳定", compile_shot_prompt(style_packs.ANIME_2D_CEL, _shot(), model="seedance2.5").text)

    def test_the_physics_and_form_rules_put_physics_over_the_reference(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text
        rules = text.split("【关键约束】", 1)[1]
        self.assertIn("物理铁律：参考图与物理冲突时以物理为准：不反向、不瞬移、不突然加速", rules)
        self.assertIn("动作轴线连续不反转", rules)
        self.assertIn("收尾站位、朝向与道具归属即下一镜起点", rules)
        self.assertIn("形态铁律：形态在时间上连续继承", rules)
        self.assertIn("不得纹理闪烁、鬼影、拖尾、频闪", rules)
        self.assertLess(rules.index("物理铁律"), rules.index("形态铁律"))

    def test_a_fight_shot_gets_the_fight_rule_and_a_quiet_one_does_not(self):
        fight = compile_shot_prompt(style_packs.FILM_35MM, _shot(situations=["fight"]), model="seedance2.5").text
        rules = fight.split("【关键约束】", 1)[1]
        self.assertIn("打斗铁律：拳拳到肉", rules)
        self.assertIn("动作飘逸流畅：招与招之间用身法衔接", rules)
        self.assertIn("全程连贯不断档", rules)
        self.assertIn("NOT slow motion for the whole clip", fight)
        self.assertNotIn("打斗铁律", compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text)

    def test_a_quiet_shot_does_its_actions_in_order_and_a_fight_keeps_its_own_rule(self):
        quiet = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text.split("【关键约束】", 1)[1]
        self.assertIn("动作顺序铁律：画面里的动作按写明的先后一步一步完成", quiet)
        self.assertIn("大小与远近以画面里的参照物为准", quiet)
        fight = compile_shot_prompt(style_packs.FILM_35MM, _shot(situations=["fight"]), model="seedance2.5").text
        self.assertNotIn("动作顺序铁律", fight)

    def test_a_fight_shot_picks_up_the_previous_landing_at_the_head_of_its_picture(self):
        text = compile_shot_prompt(
            style_packs.FILM_35MM,
            _shot(situations=["fight"], carry_in="从上一镜收势接住：林夏左膝跪地、右手撑在桌沿，从这个姿态直接起势、不重新摆架；"),
            model="seedance2.5",
        ).text
        self.assertIn("画面：从上一镜收势接住：林夏左膝跪地、右手撑在桌沿，从这个姿态直接起势、不重新摆架；林夏盯着对面", text)

    def test_a_silent_shot_says_so_and_drops_the_lip_sync_rule(self):
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(dialogue="", characters=["林夏"]), model="seedance2.5")
        self.assertIn("无台词，人物闭口", compiled.text)
        self.assertNotIn("口型同步铁律", compiled.text)
        self.assertNotIn("多人身份铁律", compiled.text)

    def test_the_animated_pack_puts_its_own_look_and_bans_in_the_prompt(self):
        compiled = compile_shot_prompt(style_packs.ANIME_2D_CEL, _shot(), model="seedance2.5")
        self.assertIn("cel-shaded anime illustration", compiled.text)
        self.assertIn("NOT photorealistic", compiled.text)
        self.assertNotIn("35mm", compiled.text)
        self.assertNotIn("film grain visible", compiled.text)

    def test_a_tight_budget_cuts_the_optional_layers_and_keeps_the_shot(self):
        shot = _shot(subject_action="林夏盯着对面" * 30, environment="北侧档案柜" * 20, effects=["烟雾"], dialogue_notes="压低声音")
        compiled = compile_shot_prompt(style_packs.FILM_35MM, shot, model="jimeng")
        self.assertNotEqual(compiled.pressure.tier, "red")
        self.assertLessEqual(compiled.pressure.length, compiled.pressure.budget)
        self.assertIn("sound", compiled.pressure.dropped)
        self.assertIn("[空间锚]", compiled.text)
        self.assertIn("台词（逐字保持原文", compiled.text)
        self.assertIn("【关键约束】", compiled.text)
        # Seedance 2.5 has room for the same shot with its sound design intact.
        roomy = compile_shot_prompt(style_packs.FILM_35MM, shot, model="seedance2.5")
        self.assertNotIn("sound", roomy.pressure.dropped)

    def test_an_extension_restates_the_look_and_may_ride_a_mask(self):
        text = extension_prompt(
            style_packs.ATOM_PUNK, source_ref="@视频1", seconds=15,
            continuation="镜头继续向加油站深处推进", mask="翻起的泛黄书页",
        )
        self.assertIn("延长视频15s向后延长", text)
        self.assertIn("禁止生硬切镜", text)
        self.assertIn("遮罩转场", text)
        self.assertIn(style_packs.ATOM_PUNK.extension_restatement, text)
        self.assertNotIn("光线：主光", text)

    def test_an_extension_names_the_light_and_restates_the_set_every_fourth_link(self):
        def extend(index: int) -> str:
            return extension_prompt(
                style_packs.FILM_35MM, source_ref="@视频1", seconds=5, continuation="林夏走到窗前",
                key_light="画面右侧窗外冷光，4200K", space_snapshot="同一书房：门在画面左侧、窗在画面右侧", chain_index=index,
            )

        for index in range(1, 9):
            self.assertIn("光线：主光画面右侧窗外冷光，4200K，延长片段内主光方向与色温不变。", extend(index))
        restated = [index for index in range(1, 9) if "【空间快照】同一书房：门在画面左侧" in extend(index)]
        self.assertEqual(restated, [1, 4, 8])


class FightNegativeTests(unittest.TestCase):
    def test_a_fight_bans_wall_to_wall_slow_motion_but_not_the_one_hit_worth_seeing_twice(self):
        for pack in style_packs.list_packs():
            terms = style_packs.negatives_for(pack, ["fight"])
            self.assertNotIn("NOT slow motion", terms, pack.id)
            self.assertNotIn("NOT speed ramping", terms, pack.id)
        live = style_packs.negatives_for(style_packs.get_pack(style_packs.DEFAULT_PACK_ID), ["fight"])
        self.assertIn("NOT slow motion for the whole clip", live)
        self.assertIn("no foot sliding", live)

    def test_a_fight_scene_sends_its_negatives_and_a_dialogue_scene_does_not(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        from tests.test_stage_five_queue import _task

        prompts: list[str] = []

        def generate_video(model, image_url, prompt, *args, **kwargs):
            prompts.append(prompt)
            return f"https://cdn/{len(prompts)}.mp4"

        for kind in ("fight", "general"):
            task = _task(1)
            task["task_id"] = f"fight-{kind}"
            task["assets"]["4_scene_boards"] = {"E1S01": {"status": "done", "episode": 1, "scene_kind": kind}}
            prompts.clear()
            with tempfile.TemporaryDirectory() as temp:
                service = DramaService()
                service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
                service.repo.save_task(task["task_id"], task)
                with patch.object(service.gateway, "generate_video", side_effect=generate_video), \
                        patch.object(service.gateway, "generate_image", return_value=("https://cdn/f.png", "m")), \
                        patch.object(service.gateway, "call_llm", return_value=""), \
                        patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"), \
                        patch.object(DramaService, "_missing_stage_outputs", staticmethod(lambda *a, **k: [])):
                    service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
            self.assertEqual(len(prompts), 1, kind)
            self.assertEqual("no foot sliding" in prompts[0], kind == "fight", kind)


if __name__ == "__main__":
    unittest.main()
