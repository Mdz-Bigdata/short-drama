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

    def test_a_long_description_is_shortened_to_the_floor_but_not_past_it(self):
        sections = {"locks": "锚" * 50, "subject": "主体。" * 200, "camera": "机位"}
        kept, report = prompt_budget.compress(sections, "vidu")
        self.assertIn("subject", report.trimmed)
        self.assertGreaterEqual(prompt_budget.prompt_length(kept["subject"]), prompt_budget.MAIN_DESCRIPTION_FLOOR)
        self.assertTrue(kept["subject"].endswith("。"))


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
            self.gateway.generate_video("seedance2.5", None, "林夏走进办公室", style_pack="anime_2d_cel")
            anime_prompt, anime_caption = sent["prompt"], sent["style_caption"]
            self.gateway.generate_video("seedance2.5", None, "林夏走进办公室", style_pack="film_35mm")
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
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5")
        text = compiled.text
        self.assertTrue(text.startswith("[STYLE LOCK]"))
        for earlier, later in (
            ("[STYLE LOCK]", "【结构声明】"), ("【结构声明】", "[空间锚]"), ("[空间锚]", "机位：近景"),
            ("机位：近景", "台词（逐字保持原文"), ("台词（逐字保持原文", "【关键约束】"),
        ):
            self.assertLess(text.index(earlier), text.index(later), f"{earlier} 应在 {later} 之前")
        for tag in ("[空间锚]", "[状态锁]", "[道具锁]", "[光影锁]", "[声音锁]"):
            self.assertIn(tag, text)
        self.assertIn("整段6秒单镜连续画面", text)
        self.assertIn("不要BGM", text)
        self.assertIn("多人身份铁律", text)        # two characters in frame
        self.assertIn("口型同步铁律", text)        # the shot has a line
        self.assertEqual(compiled.style_pack, "film_35mm")

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


if __name__ == "__main__":
    unittest.main()
