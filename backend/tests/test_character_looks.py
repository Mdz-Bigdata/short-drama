"""Costumes are not assets of their own: each is a look on the character who wears it, drawn from their face."""

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service
from app.api.drama_api import _file_character_looks, _file_crowd_wardrobe
from app.core import character_looks, character_variants, project_asset_completion, script_breakdown
from app.core.character_looks import LOOK_BOARD_SIZE, episode_spans, look_prompt, parse_look_check, plan_looks, wardrobe_text
from app.core.panel_still_prompt import _costume_notes
from app.core.production_asset_readiness import evaluate_asset_readiness, readiness_reasons
from app.core.production_asset_extractor import extract_production_assets
from app.core.storyboard_scene_context import compile_scene_context, costume_wearers, mentioned, panel_context, reference_note
from app.service.drama_service import DramaService
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository
from main import app
from tests.test_platform_api import VALID_PNG

SHEN = "沈无咎"
FACE = "身份锚点：沉默少年；骨相：窄长脸；五官：单眼皮；发型：黑发；服装：灰布短褐"
TASK_ID = "task-looks"


def _task(costumes=None) -> dict:
    return {
        "task_id": TASK_ID,
        "owner_user_id": "owner",
        "config": {"title_suggestion": "拭剑奴"},
        "assets": {
            "2": "第1集\n沈无咎拭剑。",
            "3_characters": [
                {"name": SHEN, "desc": FACE, "views": [], "five_view_quality": {"passed": True}},
                {"name": "苏问剑", "desc": "冷峻女子", "views": [], "five_view_quality": {"passed": True}},
            ],
            "2_breakdown": {"production_assets": {
                "scenes": [], "props": [], "effects": [],
                "costumes": costumes if costumes is not None else [
                    {"name": "沈无咎·麻灰拭剑奴衣", "description": "沈无咎穿着；交领短褐，腰束布带。第1集受辱、第2-8集拭剑、第11-45集日常均穿此套"},
                    {"name": "沈无咎·染血残衣", "description": "沈无咎穿着；同款麻灰短褐，大片暗红浸染。第9集被指为凶手、第10集黑屏前穿此套"},
                    {"name": "月白守冢袍", "character": "苏问剑", "description": "月白窄袖长袍，银灰腰带"},
                    {"name": "禁军甲胄", "description": "黑铁札甲，红缨"},
                ],
            }},
        },
    }


def _looks_as_elements(task=None, *, images=True) -> list[dict]:
    return [
        {
            "id": f"look-{index}", "kind": "actor", "name": look["name"], "description": look["description"],
            "metadata": {"variant": look["facts"], "task_id": TASK_ID},
            "image_url": f"data:look-{index}" if images else "",
        }
        for index, look in enumerate(plan_looks(task or _task()))
    ]


class PlanTests(unittest.TestCase):
    def test_episode_ranges_are_read_and_merged(self):
        self.assertEqual(episode_spans("第1集受辱、第2-8集拭剑、第11-45集日常"), [[1, 8], [11, 45]])
        self.assertEqual(episode_spans("第九集、第十集黑屏前"), [[9, 10]])
        self.assertEqual(episode_spans("第二十三集起穿"), [[23, 500]])
        self.assertEqual(episode_spans("第3集至第5集"), [[3, 5]])
        self.assertEqual(episode_spans("交领短褐"), [])

    def test_the_picture_gets_the_clothes_and_not_the_story(self):
        text = wardrobe_text("沈无咎穿着；交领短褐，腰束布带，第1集受辱时穿。第2-8集拭剑", SHEN)
        self.assertEqual(text, "交领短褐，腰束布带")

    def test_every_costume_with_a_known_wearer_becomes_their_look(self):
        looks = {look["name"]: look for look in plan_looks(_task())}
        self.assertEqual(list(looks), ["沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣", "月白守冢袍"])
        worn = looks["沈无咎·麻灰拭剑奴衣"]
        self.assertEqual((worn["of"], worn["label"]), (SHEN, "麻灰拭剑奴衣"))
        self.assertEqual(worn["facts"]["spans"], [[1, 8], [11, 45]])
        self.assertEqual(worn["facts"]["episodes"], [1, 45])
        self.assertEqual(worn["facts"]["source"], character_variants.LOOK_SOURCE)
        self.assertNotIn("第", worn["description"])
        self.assertNotIn("穿着", worn["description"])
        self.assertEqual(looks["月白守冢袍"]["of"], "苏问剑")

    def test_a_wearer_called_by_a_title_is_still_found(self):
        task = _task([{"name": "侯府嫡女·石榴红襦裙", "description": "石榴红襦裙"}])
        task["assets"]["3_characters"] = [{"name": "陆婉", "desc": "侯府嫡女／女配角；圆鹅蛋脸"}]
        looks = plan_looks(task)
        self.assertEqual([(look["of"], look["label"]) for look in looks], [("陆婉", "石榴红襦裙")])

    def test_no_cast_means_no_looks_yet(self):
        task = _task()
        task["assets"]["3_characters"] = []
        self.assertEqual(plan_looks(task), [])

    def test_the_prompt_dresses_the_person_and_forbids_a_mannequin(self):
        prompt = look_prompt("沈无咎·染血残衣", "同款麻灰短褐", "写实古装")
        self.assertIn("严格参考所给参考图里的同一个人", prompt)
        self.assertIn("同款麻灰短褐", prompt)
        self.assertIn("写实古装", prompt)
        self.assertIn("不用人台或假人", prompt)
        self.assertEqual(LOOK_BOARD_SIZE, "2848x1600")
        self.assertNotIn("写几道伤就只画几道", prompt)

    def test_a_wound_is_drawn_to_the_letter(self):
        prompt = look_prompt("沈清漪·夜行黑衣·左颊刀伤", "黑色夜行衣；妆效：左颊一道两寸刀口，血迹半干发暗")
        self.assertIn("写几道伤就只画几道", prompt)
        self.assertIn("暗红到褐色", prompt)
        self.assertIn("各格里形状、长度、血量和颜色完全一样", prompt)
        self.assertIn("不挡住领口的形制", prompt)


class LookCheckTests(unittest.TestCase):
    def test_the_verdict_is_read_from_the_answer(self):
        self.assertEqual(parse_look_check('{"passed": true, "problems": []}'), {"passed": True, "problems": []})
        fenced = '核对如下：\n```json\n{"passed": false, "problems": ["正脸特写右颊多了一道伤"]}\n```'
        self.assertEqual(parse_look_check(fenced), {"passed": False, "problems": ["正脸特写右颊多了一道伤"]})

    def test_a_pass_that_names_problems_is_a_fail(self):
        self.assertEqual(parse_look_check('{"passed": true, "problems": ["侧面没画伤"]}'), {"passed": False, "problems": ["侧面没画伤"]})
        self.assertEqual(parse_look_check('{"passed": false}'), {"passed": False, "problems": ["妆效和文字对不上"]})

    def test_an_unclear_answer_counts_as_unchecked(self):
        for answer in (None, "", "看起来不错", '{"problems": []}', '{"passed": "yes"}', "{passed: true"):
            self.assertIsNone(parse_look_check(answer), answer)


class WearingTests(unittest.TestCase):
    def _context(self, scene_id="E9S01", content="沈无咎跪在殿前。", elements=None):
        elements = elements if elements is not None else _looks_as_elements()
        scene = {"scene_id": scene_id, "content": content, "characters": [SHEN]}
        return compile_scene_context(_task(), scene, elements)

    def test_the_episode_decides_the_look(self):
        for scene_id, expected in (("E9S01", "染血残衣"), ("E3S01", "麻灰拭剑奴衣"), ("E12S01", "麻灰拭剑奴衣")):
            self.assertEqual(self._context(scene_id)["actors"][0]["variant"], expected, scene_id)

    def test_an_episode_outside_every_range_keeps_the_sheet(self):
        self.assertNotIn("variant", self._context("E60S01")["actors"][0])

    def test_naming_the_costume_beats_the_episode(self):
        context = self._context("E3S01", "沈无咎穿着染血残衣跪在殿前。")
        self.assertEqual(context["actors"][0]["variant"], "染血残衣")

    def test_the_narrowest_range_wins_when_two_overlap(self):
        wide = {"name": "奴衣", character_variants.VARIANT_KEY: {"of": SHEN, "episodes": [1, 45]}}
        narrow = {"name": "残衣", character_variants.VARIANT_KEY: {"of": SHEN, "episodes": [9, 10]}}
        self.assertEqual(character_variants.pick([wide, narrow], episode=9)["name"], "残衣")

    def test_a_sole_costume_with_no_episodes_is_worn_everywhere_and_two_are_not(self):
        only = {"name": "奴衣", character_variants.VARIANT_KEY: {"of": SHEN, "source": "costume", "episodes": None}}
        other = {"name": "残衣", character_variants.VARIANT_KEY: {"of": SHEN, "source": "costume", "episodes": None}}
        hand_made = {"name": "少年", character_variants.VARIANT_KEY: {"of": SHEN, "episodes": None}}
        self.assertEqual(character_variants.pick([only], episode=3)["name"], "奴衣")
        self.assertIsNone(character_variants.pick([only, other], episode=3))
        self.assertIsNone(character_variants.pick([hand_made], episode=3))

    def test_the_text_keeps_the_face_and_swaps_the_clothes(self):
        actor = self._context()["actors"][0]
        self.assertIn("窄长脸", actor["description"])
        self.assertIn("大片暗红浸染", actor["description"])
        self.assertNotIn("灰布短褐", actor["description"])
        self.assertEqual(actor["image_url"], "data:look-1")

    def test_a_shot_binds_the_look_and_no_second_outfit(self):
        older = {"id": "old", "kind": "costume", "name": "沈无咎·染血残衣", "description": "旧人台图", "image_url": "data:mannequin"}
        context = self._context(elements=[*_looks_as_elements(), older])
        self.assertNotIn("沈无咎·染血残衣", [item["name"] for item in context["costumes"]])
        panel = panel_context(context, {"characters": [SHEN], "desc": "沈无咎跪在殿前，血衣贴背"})
        urls = [item["image_url"] for item in panel["references"]]
        self.assertIn("data:look-1", urls)
        self.assertNotIn("data:mannequin", urls)

    def test_an_older_costume_image_still_binds_until_the_look_is_drawn(self):
        older = {"id": "old", "kind": "costume", "name": "沈无咎·染血残衣", "description": "沈无咎，旧人台图", "image_url": "data:mannequin"}
        context = self._context(content="沈无咎穿着染血残衣跪在殿前。", elements=[*_looks_as_elements(images=False), older])
        self.assertEqual([item["image_url"] for item in context["costumes"] if item["name"] == older["name"]], ["data:mannequin"])

    def test_prompts_name_the_outfit_on_the_person(self):
        reference = {"kind": "actor", "name": SHEN, "image_url": "data:look", "variant": "染血残衣"}
        self.assertEqual(costume_wearers([reference], [SHEN]), [(SHEN, "染血残衣")])
        self.assertIn("「沈无咎」（造型：染血残衣）", reference_note(1, reference))
        plain = reference_note(1, {"kind": "actor", "name": SHEN})
        self.assertNotIn("造型", plain)
        self.assertNotIn("；", reference_note(1, reference))


class MakeupTests(unittest.TestCase):
    """妆效画在定妆图上：写了集数的和当时穿的那身合成一张，受伤之前的戏不带伤。"""

    WOUND = {"name": "沈无咎·左颊剑伤", "description": "左颊一道三寸血口。第9集起"}

    def _looks(self, *makeup, costumes=None) -> dict:
        task = _task(costumes)
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = list(makeup)
        self.task = task
        return {look["name"]: look for look in plan_looks(task)}

    def _worn(self, scene_id, content="沈无咎跪在殿前。"):
        elements = _looks_as_elements(self.task)
        scene = {"scene_id": scene_id, "content": content, "characters": [SHEN]}
        return compile_scene_context(self.task, scene, elements)["actors"][0]

    def test_a_timed_wound_joins_whatever_is_worn_from_then_on(self):
        looks = self._looks(self.WOUND)
        self.assertEqual(looks["沈无咎·麻灰拭剑奴衣"]["facts"]["spans"], [[1, 8]])
        self.assertEqual(looks["沈无咎·染血残衣·左颊剑伤"]["facts"]["spans"], [[9, 10]])
        self.assertEqual(looks["沈无咎·麻灰拭剑奴衣·左颊剑伤"]["facts"]["spans"], [[11, 45]])
        # 这身每一集都带着伤，不单独画；「第9集起」算到戏服写到的第 45 集，后面不多出一张只有伤的图。
        self.assertNotIn("沈无咎·染血残衣", looks)
        self.assertNotIn("沈无咎·左颊剑伤", looks)
        combined = looks["沈无咎·染血残衣·左颊剑伤"]
        self.assertEqual(combined["label"], "染血残衣·左颊剑伤")
        self.assertIn("大片暗红浸染；妆效：左颊一道三寸血口", combined["description"])
        self.assertNotIn("第9集", combined["description"])
        self.assertEqual(combined["facts"]["outfit"], "沈无咎·染血残衣")
        self.assertEqual(combined["facts"]["makeups"], ["沈无咎·左颊剑伤"])

    def test_the_episode_decides_whether_the_wound_is_there(self):
        self._looks(self.WOUND)
        for scene_id, expected in (("E3S01", "麻灰拭剑奴衣"), ("E9S01", "染血残衣·左颊剑伤"), ("E20S01", "麻灰拭剑奴衣·左颊剑伤")):
            self.assertEqual(self._worn(scene_id)["variant"], expected, scene_id)

    def test_naming_an_outfit_on_two_looks_lets_the_episode_choose(self):
        self._looks(self.WOUND)
        self.assertEqual(self._worn("E3S01", "沈无咎穿麻灰拭剑奴衣。")["variant"], "麻灰拭剑奴衣")
        self.assertEqual(self._worn("E20S01", "沈无咎穿麻灰拭剑奴衣。")["variant"], "麻灰拭剑奴衣·左颊剑伤")

    def test_a_shot_naming_the_outfit_does_not_undo_the_episode(self):
        self._looks(self.WOUND)
        scene = {"scene_id": "E3S01", "content": "沈无咎跪在殿前。", "characters": [SHEN]}
        context = compile_scene_context(self.task, scene, _looks_as_elements(self.task))
        panel = panel_context(context, {"characters": [SHEN], "desc": "沈无咎跪着，麻灰拭剑奴衣沾灰"})
        actor = next(item for item in panel["references"] if item["kind"] == "actor")
        self.assertEqual(actor["variant"], "麻灰拭剑奴衣")

    def test_a_wound_on_the_only_outfit_keeps_that_outfit_as_the_default(self):
        looks = self._looks(
            {"name": "沈无咎·左颊剑伤", "description": "左颊血口。第9-12集"},
            costumes=[{"name": "沈无咎·麻灰奴衣", "description": "麻灰短褐"}],
        )
        self.assertIsNone(looks["沈无咎·麻灰奴衣"]["facts"]["episodes"])
        self.assertEqual(looks["沈无咎·麻灰奴衣·左颊剑伤"]["facts"]["spans"], [[9, 12]])
        self.assertEqual(self._worn("E3S01")["variant"], "麻灰奴衣")
        self.assertEqual(self._worn("E10S01")["variant"], "麻灰奴衣·左颊剑伤")

    def test_an_open_wound_after_every_outfit_or_with_none_still_runs_on(self):
        looks = self._looks(
            {"name": "沈无咎·左颊剑伤", "description": "左颊血口。第50集起"},
            costumes=[{"name": "沈无咎·奴衣", "description": "短褐。第1-45集"}],
        )
        self.assertEqual(looks["沈无咎·左颊剑伤"]["facts"]["spans"], [[50, 500]])
        looks = self._looks({"name": "沈无咎·左颊剑伤", "description": "左颊血口。第9集起"}, costumes=[])
        self.assertEqual(looks["沈无咎·左颊剑伤"]["facts"]["spans"], [[9, 500]])

    def test_two_wounds_at_once_are_drawn_together(self):
        looks = self._looks(
            {"name": "沈无咎·左颊剑伤", "description": "左颊血口。第1-5集"},
            {"name": "沈无咎·断指", "description": "左手小指缠布。第3-8集"},
            costumes=[],
        )
        self.assertEqual(looks["沈无咎·左颊剑伤"]["facts"]["spans"], [[1, 2]])
        self.assertEqual(looks["沈无咎·左颊剑伤·断指"]["facts"]["spans"], [[3, 5]])
        self.assertEqual(looks["沈无咎·断指"]["facts"]["spans"], [[6, 8]])

    def test_a_wound_nothing_can_date_gets_no_picture_and_is_written_onto_the_current_outfit(self):
        looks = self._looks({"name": "沈无咎·老年妆", "description": "两鬓斑白，额头皱纹"})
        self.assertEqual(list(looks), ["沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣", "月白守冢袍"])
        self.assertEqual(self._worn("E3S01", "老年妆的沈无咎跪在殿前。")["variant"], "麻灰拭剑奴衣")
        scene = {"scene_id": "E3S01", "content": "老年妆的沈无咎跪在殿前。", "characters": [SHEN]}
        context = compile_scene_context(self.task, scene, _looks_as_elements(self.task))
        panel = panel_context(context, {"characters": [SHEN], "desc": "老年妆的沈无咎跪着"})
        actor = next(item for item in panel["references"] if item["kind"] == "actor")
        self.assertEqual((actor["variant"], actor["makeup"]), ("麻灰拭剑奴衣", "两鬓斑白，额头皱纹"))
        self.assertIn("图上没有的妆效按文字加上：两鬓斑白", reference_note(1, actor))
        self.assertEqual(_costume_notes([SHEN], [actor], [])[SHEN], "「沈无咎」穿图1 的「麻灰拭剑奴衣」，图上没有的妆效按文字加上：两鬓斑白，额头皱纹")
        # 这一镜没提，就不加。
        quiet = panel_context(context, {"characters": [SHEN], "desc": "沈无咎跪着"})
        self.assertNotIn("makeup", next(item for item in quiet["references"] if item["kind"] == "actor"))

    def test_it_is_never_the_default_look(self):
        self._looks({"name": "沈无咎·老年妆", "description": "两鬓斑白"}, costumes=[])
        self.assertNotIn("variant", self._worn("E3S01"))

    def test_a_drawn_look_replaces_the_older_wound_picture(self):
        self._looks(self.WOUND)
        older = {"id": "old", "kind": "makeup", "name": "沈无咎·左颊剑伤", "description": "沈无咎，旧妆效图", "image_url": "data:wound"}
        scene = {"scene_id": "E9S01", "content": "沈无咎·左颊剑伤渗血。", "characters": [SHEN]}
        context = compile_scene_context(self.task, scene, [*_looks_as_elements(self.task), older])
        self.assertEqual(context["makeup"], [])

    def test_a_wound_with_no_wearer_stays_on_the_sheet_only(self):
        looks = self._looks({"name": "溃兵血污", "description": "脸上血污。第9集起"})
        self.assertEqual(list(looks), ["沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣", "月白守冢袍"])

    def test_the_face_stays_in_the_text_under_makeup_alone(self):
        self._looks({"name": "沈无咎·左颊剑伤", "description": "左颊血口。第1-5集"}, costumes=[])
        worn = self._worn("E3S01")
        self.assertIn("窄长脸", worn["description"])
        self.assertIn("；妆效：左颊血口", worn["description"])
        self.assertNotIn("服装：妆效", worn["description"])


def _scene(scene_id, text, *people) -> dict:
    return {"scene_id": scene_id, "content": text, "characters": list(people)}


class TimingTests(unittest.TestCase):
    """妆效和戏服什么时候在身上：描述写的集 > 描述写的场 > 模型定的 > 剧本提到它的那几场。"""

    def _plan(self, *makeup, scenes=(), costumes=None):
        task = _task(costumes if costumes is not None else [{"name": "沈无咎·奴衣", "description": "短褐"}])
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = list(makeup)
        task["assets"]["2_breakdown"]["scenes"] = list(scenes)
        self.task = task
        return {look["name"]: look for look in plan_looks(task)}

    def _worn(self, scene_id):
        scene = {"scene_id": scene_id, "content": "沈无咎走来。", "characters": [SHEN]}
        return compile_scene_context(self.task, scene, _looks_as_elements(self.task))["actors"][0].get("variant")

    def test_a_scene_reference_sets_the_episode_and_the_scene(self):
        looks = self._plan({"name": "沈无咎·剑伤", "description": "左颊血口。从第2集第3场起"}, scenes=[_scene("E1S01", "沈无咎", SHEN), _scene("E2S01", "沈无咎", SHEN), _scene("E3S01", "沈无咎", SHEN)])
        facts = looks["沈无咎·奴衣·剑伤"]["facts"]
        self.assertEqual(facts["starts"], [2, 3])
        self.assertEqual(facts["spans"], [[2, 500]])
        self.assertNotIn("第2集", looks["沈无咎·奴衣·剑伤"]["description"].replace("妆效", ""))

    def test_within_the_episode_the_wound_starts_at_its_scene(self):
        self._plan({"name": "沈无咎·剑伤", "description": "左颊血口。E2S03"}, scenes=[_scene(f"E2S0{n}", "沈无咎", SHEN) for n in (1, 2, 3, 4)])
        self.assertEqual(self._worn("E2S02"), "奴衣")
        self.assertEqual(self._worn("E2S03"), "奴衣·剑伤")
        self.assertEqual(self._worn("E3S01"), "奴衣")

    def test_a_timed_outfit_keeps_the_episode_the_wound_begins_in(self):
        looks = self._plan(
            {"name": "沈无咎·剑伤", "description": "左颊血口。从第2集第3场起"},
            costumes=[{"name": "沈无咎·奴衣", "description": "短褐。第1-3集"}],
            scenes=[_scene("E1S01", "沈无咎", SHEN), _scene("E2S01", "沈无咎", SHEN)],
        )
        self.assertEqual(looks["沈无咎·奴衣"]["facts"]["spans"], [[1, 2]])
        self.assertEqual(looks["沈无咎·奴衣·剑伤"]["facts"]["spans"], [[2, 3]])
        self.assertEqual(self._worn("E2S01"), "奴衣")
        self.assertEqual(self._worn("E2S03"), "奴衣·剑伤")

    def test_a_scene_number_without_an_episode_takes_the_earliest_such_scene(self):
        looks = self._plan({"name": "沈无咎·剑伤", "description": "左颊血口，从第3场开始"}, scenes=[_scene("E2S03", "沈无咎", SHEN), _scene("E4S03", "沈无咎", SHEN)])
        self.assertEqual(looks["沈无咎·奴衣·剑伤"]["facts"]["starts"], [2, 3])

    def test_with_nothing_written_the_script_says_when(self):
        looks = self._plan(
            {"name": "沈无咎·左颊剑伤", "description": "左颊血口"},
            scenes=[
                _scene("E1S01", "沈无咎拭剑。", SHEN), _scene("E2S02", "沈无咎左颊剑伤渗血。", SHEN),
                _scene("E3S01", "苏问剑看见左颊剑伤的告示。", "苏问剑"), _scene("E4S01", "沈无咎的左颊剑伤结痂。", SHEN),
            ],
        )
        facts = looks["沈无咎·奴衣·左颊剑伤"]["facts"]
        self.assertEqual((facts["spans"], facts["starts"]), ([[2, 4]], [2, 2]))

    def test_the_models_answer_counts_only_when_nothing_is_written(self):
        looks = self._plan({"name": "沈无咎·老年妆", "description": "两鬓斑白", "timing": "第20集起"}, scenes=[_scene("E20S01", "沈无咎", SHEN)])
        self.assertEqual(looks["沈无咎·奴衣·老年妆"]["facts"]["spans"], [[20, 500]])
        looks = self._plan({"name": "沈无咎·老年妆", "description": "两鬓斑白。第5集", "timing": "第20集起"}, scenes=[_scene("E5S01", "沈无咎", SHEN)])
        self.assertEqual(looks["沈无咎·奴衣·老年妆"]["facts"]["spans"], [[5, 5]])

    def test_only_what_still_has_no_date_goes_to_the_model(self):
        task = _task([{"name": "沈无咎·奴衣", "description": "短褐"}, {"name": "苏问剑·甲", "description": "甲"}, {"name": "苏问剑·乙", "description": "乙"}])
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [
            {"name": "沈无咎·老年妆", "description": "两鬓斑白"}, {"name": "沈无咎·剑伤", "description": "第3集起"},
        ]
        # 一个人只有一身就是默认，不用问；一个人好几身都没日子才问。
        self.assertEqual(sorted(character_looks.undated(task)), ["沈无咎·老年妆", "苏问剑·乙", "苏问剑·甲"])

    def test_episodes_the_wearer_is_never_in_cost_nothing(self):
        looks = self._plan(
            {"name": "沈无咎·剑伤", "description": "左颊血口。第9集起"},
            costumes=[{"name": "沈无咎·奴衣", "description": "短褐。第1-8集"}, {"name": "沈无咎·残衣", "description": "残衣。第9-10集"}, {"name": "沈无咎·官服", "description": "官服。第11-20集"}],
            scenes=[_scene("E1S01", "沈无咎拭剑。", SHEN), _scene("E9S01", "沈无咎跪着。", SHEN), _scene("E15S01", "苏问剑独自走。", "苏问剑")],
        )
        # 官服那段他没出场：不出官服带伤这张。
        self.assertEqual(sorted(looks), ["沈无咎·奴衣", "沈无咎·残衣·剑伤"])
        self.assertNotIn("苏问剑·月白", " ".join(looks))

    def test_a_character_with_no_scenes_at_all_draws_nothing(self):
        looks = self._plan(costumes=[{"name": "苏问剑·月白袍", "description": "袍"}], scenes=[_scene("E1S01", "沈无咎拭剑。", SHEN)])
        self.assertEqual(looks, {})

    def test_without_an_outline_every_look_is_kept(self):
        looks = self._plan(costumes=[{"name": "苏问剑·月白袍", "description": "袍"}])
        self.assertEqual(list(looks), ["苏问剑·月白袍"])


class DatingPassTests(unittest.TestCase):
    def _service(self, task):
        service = DramaService()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        service.repo.save_task(TASK_ID, task)
        return service

    def _task(self):
        task = _task([{"name": "沈无咎·奴衣", "description": "短褐"}])
        task["config"]["llm_model"] = "test-model"
        task["assets"]["2_breakdown"]["production_assets"].update({
            "scenes": [{"name": "剑冢", "description": "夜"}], "props": [], "effects": [{"name": "雷光", "description": "光"}],
            "makeup": [{"name": "沈无咎·老年妆", "description": "两鬓斑白"}, {"name": "沈无咎·旧疾", "description": "脸色发青"}],
        })
        return task

    def test_the_model_is_asked_once_and_its_answer_is_kept(self):
        service = self._service(self._task())
        answer = '{"items": [{"name": "沈无咎·老年妆", "episodes": "第20集起"}, {"name": "沈无咎·旧疾", "episodes": ""}]}'
        with patch.object(service.gateway, "call_llm", return_value=answer) as call:
            service.ensure_production_asset_catalog(TASK_ID)
            service.ensure_production_asset_catalog(TASK_ID)
        self.assertEqual(call.call_count, 1)
        asked = call.call_args.args[2]
        self.assertIn("沈无咎·老年妆", asked)
        self.assertNotIn("沈无咎·奴衣\n", asked)
        looks = {look["name"]: look for look in plan_looks(service.repo.get_task(TASK_ID))}
        self.assertEqual(looks["沈无咎·奴衣·老年妆"]["facts"]["spans"], [[20, 500]])
        self.assertEqual([item["name"] for item in character_looks.untimed_makeup(service.repo.get_task(TASK_ID))], ["沈无咎·旧疾"])

    def test_a_failed_pass_changes_nothing_and_blocks_nothing(self):
        service = self._service(self._task())
        with patch.object(service.gateway, "call_llm", side_effect=RuntimeError("down")):
            self.assertIsNotNone(service.ensure_production_asset_catalog(TASK_ID))
        self.assertEqual(len(character_looks.undated(service.repo.get_task(TASK_ID))), 2)

    def test_a_new_version_of_the_script_is_asked_again(self):
        service = self._service(self._task())
        with patch.object(service.gateway, "call_llm", return_value='{"items": []}') as call:
            service.ensure_production_asset_catalog(TASK_ID)
            task = service.repo.get_task(TASK_ID)
            task["assets"]["2"] += "\n第2集\n沈无咎老了。"
            service.repo.save_task(TASK_ID, task)
            service.ensure_production_asset_catalog(TASK_ID)
        self.assertEqual(call.call_count, 2)


class CrowdTests(unittest.TestCase):
    def _task(self, **catalog):
        task = _task(catalog.pop("costumes", []))
        task["assets"]["2"] = "禁军列阵。溃兵逃入城门。"
        task["assets"]["2_breakdown"]["production_assets"].update(catalog)
        return task

    def test_a_crowds_costume_and_makeup_become_one_extra(self):
        task = self._task(
            costumes=[{"name": "禁军甲胄", "description": "黑铁札甲，红缨"}],
            makeup=[{"name": "溃兵血污", "description": "脸上血污。第9集起"}, {"name": "溃兵断臂", "description": "假断臂"}],
        )
        rows = {item["name"]: item["description"] for item in extract_production_assets(task, "extra")}
        self.assertEqual(rows["禁军"], "服装：黑铁札甲，红缨")
        self.assertEqual(rows["溃兵"], "妆效：脸上血污；妆效：假断臂")

    def test_it_joins_an_extra_already_listed(self):
        task = self._task(
            costumes=[{"name": "禁军甲胄", "description": "黑铁札甲"}], extras=[{"name": "禁军", "description": "二十人列阵"}],
        )
        rows = extract_production_assets(task, "extra")
        self.assertEqual([(item["name"], item["description"]) for item in rows], [("禁军", "二十人列阵；服装：黑铁札甲")])

    def test_someone_not_in_the_cast_is_their_own_crowd_entry(self):
        task = self._task(costumes=[{"name": "王二·囚衣", "description": "灰布囚衣"}])
        self.assertEqual(extract_production_assets(task, "extra")[0]["name"], "王二")

    def test_a_shot_naming_the_crowd_binds_the_picture(self):
        task = self._task(costumes=[{"name": "禁军甲胄", "description": "黑铁札甲"}])
        self.assertTrue(mentioned(extract_production_assets(task, "extra")[0], "禁军列阵"))

    def test_before_the_cast_exists_nothing_is_guessed_to_be_a_crowd(self):
        task = self._task(costumes=[{"name": "沈无咎·奴衣", "description": "短褐"}])
        task["assets"]["3_characters"] = []
        self.assertEqual(extract_production_assets(task, "extra"), [])

    def test_a_named_wearer_stays_on_the_character(self):
        task = self._task(costumes=[{"name": "沈无咎·奴衣", "description": "短褐"}])
        self.assertEqual(extract_production_assets(task, "extra"), [])


class BreakdownSheetTests(unittest.TestCase):
    def test_one_column_says_what_each_person_wears_in_each_scene(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [
            MakeupTests.WOUND, {"name": "沈无咎·老年妆", "description": "两鬓斑白"},
        ]
        def shot(scene_id, text):
            return {"scene_id": scene_id, "label": "内景：殿 - 夜", "content": text, "description": text, "characters": [SHEN], "duration": "10秒"}
        breakdown = script_breakdown.compile_breakdown(task, [
            shot("E3S01", "沈无咎拭剑。"), shot("E9S01", "沈无咎跪在殿前。"), shot("E20S01", "老年妆的沈无咎独行。"),
        ])
        worn = [sheet["elements"]["look"] for sheet in breakdown["scenes"]]
        self.assertEqual(worn, [["沈无咎：麻灰拭剑奴衣"], ["沈无咎：染血残衣·左颊剑伤"], ["沈无咎：麻灰拭剑奴衣·左颊剑伤·老年妆"]])
        self.assertEqual({item["label"] for item in breakdown["elements"] if item["kind"] == "look"}, {"表演妆造"})
        self.assertFalse([kind for sheet in breakdown["scenes"] for kind in sheet["elements"] if kind in ("costume", "makeup")])
        self.assertIn("表演妆造", script_breakdown.render_csv(breakdown))
        self.assertNotIn("化妆", script_breakdown.render_csv(breakdown))

    def test_a_wound_taken_mid_scene_lists_before_and_after(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [{"name": "沈无咎·左颊剑伤", "description": "左颊血口。从第9集第2场起"}]
        def shot(scene_id, text):
            return {"scene_id": scene_id, "label": "内景：殿 - 夜", "content": text, "description": text, "characters": [SHEN], "duration": "10秒"}
        breakdown = script_breakdown.compile_breakdown(task, [shot("E9S01", "沈无咎跪着。"), shot("E9S02", "沈无咎中剑。")])
        self.assertEqual(breakdown["scenes"][0]["elements"]["look"], ["沈无咎：染血残衣、染血残衣·左颊剑伤"])

    def test_a_wound_nobody_can_date_still_shows_in_the_summary(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [{"name": "沈无咎·老年妆", "description": "两鬓斑白"}]
        breakdown = script_breakdown.compile_breakdown(task, [
            {"scene_id": "E3S01", "label": "内景：殿 - 夜", "content": "沈无咎拭剑。", "description": "沈无咎拭剑。", "characters": [SHEN], "duration": "10秒"},
        ])
        rows = [item for item in breakdown["elements"] if item["kind"] == "look" and "老年妆" in item["name"]]
        self.assertEqual([(item["name"], item["scenes"]) for item in rows], [("沈无咎：老年妆（未定时间）", [])])

    def test_a_crowds_wardrobe_shows_under_extras(self):
        task = _task([{"name": "禁军甲胄", "description": "黑铁札甲"}])
        task["assets"]["2"] = "禁军列阵。"
        breakdown = script_breakdown.compile_breakdown(task, [
            {"scene_id": "E1S01", "label": "外景：城门 - 日", "content": "沈无咎穿过列阵的禁军。", "description": "沈无咎穿过列阵的禁军。", "characters": [SHEN], "duration": "10秒"},
        ])
        self.assertIn("禁军", breakdown["scenes"][0]["elements"]["extra"])


class ReadinessTests(unittest.TestCase):
    def _summaries(self, **has_image) -> list[dict]:
        names = ["沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣", "月白守冢袍"]
        return [
            {"id": name, "kind": "actor", "name": name, "has_image": name in has_image.get("drawn", ()), "metadata": {"task_id": TASK_ID}}
            for name in names
        ]

    def test_a_missing_look_holds_the_storyboard(self):
        readiness = evaluate_asset_readiness(_task(), self._summaries(drawn=("月白守冢袍",)))
        look = readiness["kinds"]["look"]
        self.assertEqual((look["label"], look["total"], look["ready"]), ("表演妆造", 3, 1))
        self.assertTrue(look["enforced"])
        self.assertTrue(any(reason.startswith("3.表演妆造缺少参考图（2项）") for reason in readiness_reasons(readiness)))

    def test_a_costume_without_a_wearer_never_blocks(self):
        readiness = evaluate_asset_readiness(_task(), self._summaries())
        self.assertNotIn("禁军甲胄", readiness["kinds"]["look"]["missing"])

    def test_an_older_projects_costume_image_is_not_charged_for_again_at_the_gate(self):
        older = [
            {"id": name, "kind": "costume", "name": name, "has_image": True, "metadata": {"task_id": TASK_ID}}
            for name in ("沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣", "月白守冢袍")
        ]
        self.assertEqual(evaluate_asset_readiness(_task(), older)["kinds"]["look"]["missing"], [])


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'looks.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            await self.store.seed_capabilities()
            await self.store.seed_billing_plans()
            self.user, _ = await self.store.create_user(email="looks@example.com", phone=None, password="looks-password-strong")

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)
        self.cookie = {"auth_token": auth_service.generate_token(self.user.id)}
        storage = patch("app.api.element_api.ELEMENT_MEDIA_ROOT", Path(self.temp.name) / "looks")
        storage.start()
        self.addCleanup(storage.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _file_looks(self) -> dict:
        return asyncio.run(_file_character_looks(task=_task(), task_id=TASK_ID, owner_id=self.user.id, store=self.store))

    def _actors(self) -> dict:
        items = self.client.get(f"/api/elements?kind=actor&page_size=50&task_id={TASK_ID}", cookies=self.cookie).json()["items"]
        return {item["name"]: item for item in items}

    def _base_actor(self, image=True) -> str:
        created = self.client.post(
            "/api/elements", json={"kind": "actor", "name": SHEN, "description": FACE, "metadata": {"task_id": TASK_ID}}, cookies=self.cookie,
        ).json()
        if image:
            uploaded = self.client.post(
                f"/api/elements/{created['id']}/files", data={"slot": "front"},
                files={"file": ("face.png", VALID_PNG, "image/png")}, cookies=self.cookie,
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
        return created["id"]

    def _drawing(self, calls: list):
        def generate(model, prompt, ref_images=None, size=None, **kwargs):
            calls.append({"prompt": prompt, "ref_images": ref_images, "size": size, **kwargs})
            return "https://assets.example.test/look.png", "seedream"
        return patch("app.api.element_api.element_image_gateway.generate_image", side_effect=generate)

    def test_filing_is_idempotent_and_draws_nothing(self):
        with patch("app.api.element_api.element_image_gateway.generate_image") as generate:
            first = self._file_looks()
            second = self._file_looks()
        generate.assert_not_called()
        self.assertEqual(first["created"], 3)
        self.assertEqual(second["created"], 0)
        actors = self._actors()
        self.assertEqual(actors["月白守冢袍"]["metadata"]["variant"]["of"], "苏问剑")
        self.assertEqual(actors["沈无咎·染血残衣"]["metadata"]["variant"]["spans"], [[9, 10]])
        self.assertNotIn("第9集", actors["沈无咎·染血残衣"]["description"])

    def test_a_look_someone_edited_is_left_alone(self):
        self._file_looks()
        look = self._actors()["沈无咎·染血残衣"]
        edited = self.client.put(
            f"/api/elements/{look['id']}/variant",
            json={"of": SHEN, "label": "血衣", "triggers": "血衣", "episode_from": 9, "episode_to": 12}, cookies=self.cookie,
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self._file_looks()
        facts = self._actors()["沈无咎·染血残衣"]["metadata"]["variant"]
        self.assertEqual((facts["label"], facts["episodes"], facts["source"]), ("血衣", [9, 12], "costume"))
        self.assertNotIn("spans", facts)

    def test_editing_only_the_triggers_keeps_scattered_ranges(self):
        self._file_looks()
        look = self._actors()["沈无咎·麻灰拭剑奴衣"]
        self.client.put(
            f"/api/elements/{look['id']}/variant",
            json={"of": SHEN, "label": "奴衣", "triggers": "奴衣", "episode_from": 1, "episode_to": 45}, cookies=self.cookie,
        )
        self.assertEqual(self._actors()["沈无咎·麻灰拭剑奴衣"]["metadata"]["variant"]["spans"], [[1, 8], [11, 45]])

    def _file_with_wound(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [MakeupTests.WOUND]
        return asyncio.run(_file_character_looks(task=task, task_id=TASK_ID, owner_id=self.user.id, store=self.store))

    def test_adding_a_wound_rebuilds_the_ranges_and_retires_what_nobody_wears(self):
        self._file_looks()
        self.assertEqual(self._actors()["沈无咎·麻灰拭剑奴衣"]["metadata"]["variant"]["spans"], [[1, 8], [11, 45]])
        self._file_with_wound()
        actors = self._actors()
        self.assertEqual(actors["沈无咎·麻灰拭剑奴衣"]["metadata"]["variant"]["spans"], [[1, 8]])
        self.assertIn("沈无咎·染血残衣·左颊剑伤", actors)
        self.assertTrue(actors["沈无咎·染血残衣"]["metadata"]["variant"]["retired"])
        self.assertFalse(character_variants.is_current_look(actors["沈无咎·染血残衣"]))
        # 退役的不进换装候选，也不再补画。
        self.assertEqual(character_variants.split([actors["沈无咎·染血残衣"]]), ([], {}))
        job = self.client.post(
            "/api/elements/generation-jobs", json={"kind": "actor", "looks": True, "task_id": TASK_ID}, cookies=self.cookie,
        ).json()
        self.assertEqual(job["total"], len([item for item in actors.values() if character_variants.is_current_look(item)]))
        # 剧本改回去，它又能穿了。
        self._file_looks()
        self.assertNotIn("retired", self._actors()["沈无咎·染血残衣"]["metadata"]["variant"])

    def test_an_edited_look_is_neither_rebuilt_nor_retired(self):
        self._file_looks()
        look = self._actors()["沈无咎·染血残衣"]
        self.client.put(
            f"/api/elements/{look['id']}/variant",
            json={"of": SHEN, "label": "血衣", "triggers": "血衣", "episode_from": 9, "episode_to": 12}, cookies=self.cookie,
        )
        self._file_with_wound()
        facts = self._actors()["沈无咎·染血残衣"]["metadata"]["variant"]
        self.assertEqual((facts["episodes"], facts.get("retired")), ([9, 12], None))

    def _file_for(self, task_id, task=None) -> dict:
        return asyncio.run(_file_character_looks(task=task or _task(), task_id=task_id, owner_id=self.user.id, store=self.store))

    def _actors_in(self, task_id) -> dict:
        items = self.client.get(f"/api/elements?kind=actor&page_size=50&task_id={task_id}", cookies=self.cookie).json()["items"]
        return {item["name"]: item for item in items}

    def _drawn(self, look_id):
        uploaded = self.client.post(
            f"/api/elements/{look_id}/files", data={"slot": "front"},
            files={"file": ("look.png", VALID_PNG, "image/png")}, cookies=self.cookie,
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)

    def test_a_look_is_shared_only_while_the_two_projects_agree(self):
        self._file_for("project-a")
        look = self._actors_in("project-a")["沈无咎·染血残衣"]
        self._drawn(look["id"])
        result = self._file_for("project-b")
        same = self._actors_in("project-b")["沈无咎·染血残衣"]
        self.assertEqual(same["id"], look["id"])
        self.assertEqual(result["reused"], 1)

    def test_different_episodes_get_their_own_entry_and_a_copy_of_the_picture(self):
        self._file_for("project-a")
        look = self._actors_in("project-a")["沈无咎·染血残衣"]
        self._drawn(look["id"])
        other = _task()
        catalog = other["assets"]["2_breakdown"]["production_assets"]["costumes"]
        catalog[1] = {**catalog[1], "description": catalog[1]["description"].replace("第9集被指为凶手、第10集黑屏前", "第30集被指为凶手")}
        with patch("app.api.element_api.element_image_gateway.generate_image") as generate:
            self._file_for("project-b", other)
        generate.assert_not_called()
        mine, theirs = self._actors_in("project-b")["沈无咎·染血残衣"], self._actors_in("project-a")["沈无咎·染血残衣"]
        self.assertNotEqual(mine["id"], theirs["id"])
        self.assertEqual(mine["metadata"]["variant"]["spans"], [[30, 30]])
        self.assertEqual(theirs["metadata"]["variant"]["spans"], [[9, 10]])
        self.assertEqual(len(mine["files"]), 1)
        # 回到 A 同步，A 还是 A 的，B 也不被改回去。
        self._file_for("project-a")
        self.assertEqual(self._actors_in("project-b")["沈无咎·染血残衣"]["metadata"]["variant"]["spans"], [[30, 30]])
        self.assertEqual(self._actors_in("project-a")["沈无咎·染血残衣"]["metadata"]["variant"]["spans"], [[9, 10]])

    def test_a_shared_look_that_changes_splits_off_and_leaves_the_other_project_alone(self):
        self._file_for("project-a")
        look = self._actors_in("project-a")["沈无咎·染血残衣"]
        self._drawn(look["id"])
        self._file_for("project-b")
        changed = _task()
        catalog = changed["assets"]["2_breakdown"]["production_assets"]["costumes"]
        catalog[1] = {**catalog[1], "description": catalog[1]["description"].replace("第9集被指为凶手、第10集黑屏前", "第30集被指为凶手")}
        self._file_for("project-b", changed)
        self.assertEqual(self._actors_in("project-a")["沈无咎·染血残衣"]["metadata"]["variant"]["spans"], [[9, 10]])
        mine = self._actors_in("project-b")["沈无咎·染血残衣"]
        self.assertNotEqual(mine["id"], look["id"])
        self.assertEqual(mine["metadata"]["variant"]["spans"], [[30, 30]])
        self.assertEqual(len(mine["files"]), 1)

    def test_a_look_this_project_drops_stays_with_the_other_project(self):
        self._file_for("project-a")
        look = self._actors_in("project-a")["沈无咎·染血残衣"]
        self._drawn(look["id"])
        self._file_for("project-b")
        dropped = _task()
        del dropped["assets"]["2_breakdown"]["production_assets"]["costumes"][1]
        self._file_for("project-b", dropped)
        self.assertNotIn("沈无咎·染血残衣", self._actors_in("project-b"))
        kept = self._actors_in("project-a")["沈无咎·染血残衣"]
        self.assertNotIn("retired", kept["metadata"]["variant"])
        self.assertEqual(kept["metadata"]["task_id"], "project-a")

    def test_a_rewritten_costume_updates_the_words_and_flags_the_picture(self):
        self._file_looks()
        look = self._actors()["沈无咎·染血残衣"]
        self._drawn(look["id"])
        changed = _task()
        catalog = changed["assets"]["2_breakdown"]["production_assets"]["costumes"]
        catalog[1] = {**catalog[1], "description": catalog[1]["description"].replace("大片暗红浸染", "满身泥浆")}
        with patch("app.api.element_api.element_image_gateway.generate_image") as generate:
            asyncio.run(_file_character_looks(task=changed, task_id=TASK_ID, owner_id=self.user.id, store=self.store))
        generate.assert_not_called()
        flagged = self._actors()["沈无咎·染血残衣"]
        self.assertIn("满身泥浆", flagged["description"])
        self.assertTrue(flagged["metadata"]["needs_redraw"])
        self._base_actor()
        calls: list = []
        with self._drawing(calls), patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG):
            redrawn = self.client.post(f"/api/elements/{flagged['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(redrawn.status_code, 200, redrawn.text)
        self.assertFalse(redrawn.json()["metadata"]["needs_redraw"])

    def test_an_undrawn_look_is_rewritten_with_no_flag(self):
        self._file_looks()
        changed = _task()
        catalog = changed["assets"]["2_breakdown"]["production_assets"]["costumes"]
        catalog[1] = {**catalog[1], "description": catalog[1]["description"].replace("大片暗红浸染", "满身泥浆")}
        asyncio.run(_file_character_looks(task=changed, task_id=TASK_ID, owner_id=self.user.id, store=self.store))
        self.assertFalse(self._actors()["沈无咎·染血残衣"]["metadata"].get("needs_redraw"))

    def _extras(self) -> dict:
        items = self.client.get(f"/api/elements?kind=extra&page_size=50&task_id={TASK_ID}", cookies=self.cookie).json()["items"]
        return {item["name"]: item for item in items}

    def test_a_drawn_crowd_learns_its_new_wardrobe_and_is_flagged(self):
        created = self.client.post(
            "/api/elements", json={"kind": "extra", "name": "禁军", "description": "二十人列阵", "metadata": {"task_id": TASK_ID, "task_ids": [TASK_ID]}}, cookies=self.cookie,
        ).json()
        self.client.post(f"/api/elements/{created['id']}/files", data={"slot": "reference"}, files={"file": ("a.png", VALID_PNG, "image/png")}, cookies=self.cookie)
        task = _task()
        task["assets"]["2"] = "禁军列阵。"
        asyncio.run(_file_crowd_wardrobe(task=task, task_id=TASK_ID, owner_id=self.user.id, store=self.store))
        crowd = self._extras()["禁军"]
        self.assertEqual(crowd["description"], "二十人列阵；服装：黑铁札甲，红缨")
        self.assertTrue(crowd["metadata"]["needs_redraw"])
        # 再同步一次不会重复写。
        asyncio.run(_file_crowd_wardrobe(task=task, task_id=TASK_ID, owner_id=self.user.id, store=self.store))
        self.assertEqual(self._extras()["禁军"]["description"], "二十人列阵；服装：黑铁札甲，红缨")

    def _untimed_task(self, repository) -> None:
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [{"name": "沈无咎·老年妆", "description": "两鬓斑白"}]
        repository.save_task(TASK_ID, task)

    def test_someone_can_date_a_wound_and_it_joins_the_outfit(self):
        repository = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self._untimed_task(repository)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: None
        with patch.object(drama_api.service, "repo", repository):
            listed = self.client.get(f"/api/drama/{TASK_ID}/character-looks/untimed", cookies=self.cookie).json()["items"]
            self.assertEqual([(item["of"], item["label"], item["text"]) for item in listed], [(SHEN, "老年妆", "两鬓斑白")])
            refused = self.client.put(f"/api/drama/{TASK_ID}/character-looks/timing", json={"name": "沈无咎·老年妆", "episodes": "后来"}, cookies=self.cookie)
            missing = self.client.put(f"/api/drama/{TASK_ID}/character-looks/timing", json={"name": "不存在", "episodes": "第9集起"}, cookies=self.cookie)
            saved = self.client.put(f"/api/drama/{TASK_ID}/character-looks/timing", json={"name": "沈无咎·老年妆", "episodes": "第12集起"}, cookies=self.cookie)
            after = self.client.get(f"/api/drama/{TASK_ID}/character-looks/untimed", cookies=self.cookie).json()["items"]
        self.assertEqual((refused.status_code, missing.status_code, saved.status_code), (422, 404, 200), saved.text)
        self.assertIn("第2集第3场起", refused.json()["detail"])
        self.assertEqual(after, [])
        self.assertIn("沈无咎·麻灰拭剑奴衣·老年妆", self._actors())
        self.assertIn("沈无咎·麻灰拭剑奴衣·老年妆", saved.json()["readiness"]["kinds"]["look"]["missing"])

    def test_makeup_is_no_longer_filed_or_drawn_on_its_own(self):
        older = self.client.post(
            "/api/elements", json={"kind": "makeup", "name": "沈无咎·旧伤", "description": "沈无咎，旧伤"}, cookies=self.cookie,
        ).json()
        with patch("app.api.element_api.element_image_gateway.generate_image") as generate:
            refused = self.client.post(f"/api/elements/{older['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
            bulk = self.client.post("/api/elements/generation-jobs", json={"kind": "makeup"}, cookies=self.cookie)
        self.assertEqual((refused.status_code, bulk.status_code), (422, 422))
        generate.assert_not_called()
        self.assertEqual(self.client.get(f"/api/elements/{older['id']}", cookies=self.cookie).status_code, 200)

    def test_an_earlier_costume_and_wound_picture_feed_the_new_look(self):
        self._base_actor()
        older = []
        for kind, name in (("costume", "沈无咎·染血残衣"), ("makeup", "沈无咎·左颊剑伤"), ("costume", "别人·别的衣服")):
            created = self.client.post("/api/elements", json={"kind": kind, "name": name, "description": "旧图"}, cookies=self.cookie).json()
            self.client.post(f"/api/elements/{created['id']}/files", data={"slot": "reference"}, files={"file": ("old.png", VALID_PNG, "image/png")}, cookies=self.cookie)
            older.append(created["id"])
        self._file_with_wound()
        look = self._actors()["沈无咎·染血残衣·左颊剑伤"]
        calls: list = []
        with self._drawing(calls), patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG):
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls[0]["ref_images"]), 3)
        self.assertIn("第1张参考图是这个人", calls[0]["prompt"])
        self.assertIn("不取其中的人台和人脸", calls[0]["prompt"])
        for element_id in older:
            self.assertEqual(self.client.get(f"/api/elements/{element_id}", cookies=self.cookie).status_code, 200)

    def test_stage_three_draws_the_looks_and_the_crowds_in_advance(self):
        self._base_actor()
        task = _task()
        task["owner_user_id"] = self.user.id
        task["assets"]["2"] = "禁军列阵。"
        calls: list = []
        database = f"sqlite+aiosqlite:///{Path(self.temp.name) / 'looks.sqlite3'}"

        def plain(model, prompt, ref_images=None, size=None, **kwargs):
            calls.append(prompt)
            return "https://assets.example.test/look.png", "seedream"

        with (
            patch("app.api.element_api.element_image_gateway.generate_image", side_effect=plain),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
            patch("app.core.project_asset_completion.settings.database_url", return_value=database),
        ):
            readiness = project_asset_completion.complete_project_assets(task, generate_missing=True)
        drawn = {call.split("造型名称：")[1].split("\n")[0] for call in calls if "造型名称：" in call}
        self.assertEqual(drawn, {"沈无咎·麻灰拭剑奴衣", "沈无咎·染血残衣"})
        self.assertTrue(any("资产名称：禁军" in call and "黑铁札甲" in call for call in calls), calls)
        self.assertEqual(readiness["kinds"]["extra"]["ready"], 1)
        # 苏问剑没有身份视图：这张失败被记下，不挡别的。
        self.assertEqual(readiness["generation_failed"], ["月白守冢袍"])

    def test_a_look_is_drawn_from_the_characters_own_face(self):
        self._base_actor()
        self._file_looks()
        look = self._actors()["沈无咎·染血残衣"]
        calls: list = []
        with (
            self._drawing(calls),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
        ):
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["ref_images"], [f"data:image/png;base64,{base64.b64encode(VALID_PNG).decode('ascii')}"])
        self.assertEqual(calls[0]["size"], LOOK_BOARD_SIZE)
        self.assertTrue(calls[0]["require_reference_support"])
        self.assertIn("大片暗红浸染", calls[0]["prompt"])
        self.assertNotIn("被指为凶手", calls[0]["prompt"])
        self.assertEqual([file["slot"] for file in response.json()["files"]], ["front"])
        # 一张展示板就算就绪，不要求五个身份视图；普通演员还是要。
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(self._actors()[SHEN]["status"], "draft")

    def _wounded_look(self) -> dict:
        self._base_actor()
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["makeup"] = [{"name": "沈无咎·左颊剑伤", "description": "左颊一道三寸血口。第9-10集"}]
        asyncio.run(_file_character_looks(task=task, task_id=TASK_ID, owner_id=self.user.id, store=self.store))
        return self._actors()["沈无咎·染血残衣·左颊剑伤"]

    def _checked_draw(self, look: dict, verdicts: list, *, drawn: list | None = None):
        calls: list = [] if drawn is None else drawn
        checks: list = []

        def describe(model, system, prompt, image, **kwargs):
            checks.append(prompt)
            return verdicts.pop(0), "deepseek-flash"

        with (
            self._drawing(calls),
            patch("app.api.element_api.element_image_gateway.describe_image", side_effect=describe),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
        ):
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), calls, checks

    def test_a_look_without_makeup_is_not_checked(self):
        self._base_actor()
        self._file_looks()
        result, calls, checks = self._checked_draw(self._actors()["沈无咎·染血残衣"], [])
        self.assertEqual((len(calls), checks), (1, []))
        self.assertIsNone(result["metadata"]["look_check"])

    def test_a_wound_that_checks_out_is_drawn_once(self):
        result, calls, checks = self._checked_draw(self._wounded_look(), ['{"passed": true, "problems": []}'])
        self.assertEqual((len(calls), len(checks)), (1, 1))
        self.assertIn("左颊一道三寸血口", checks[0])
        self.assertEqual(result["metadata"]["look_check"], {"passed": True, "problems": [], "model": "deepseek-flash"})

    def test_a_wrong_wound_is_redrawn_once_with_what_was_wrong(self):
        result, calls, _checks = self._checked_draw(
            self._wounded_look(), ['{"passed": false, "problems": ["正脸特写右颊多了一道伤"]}', '{"passed": true, "problems": []}'],
        )
        self.assertEqual(len(calls), 2)
        self.assertNotIn("上一张的妆效有这些问题", calls[0]["prompt"])
        self.assertIn("上一张的妆效有这些问题，这次务必改正：正脸特写右颊多了一道伤", calls[1]["prompt"])
        self.assertTrue(result["metadata"]["look_check"]["passed"])

    def test_a_wound_still_wrong_after_the_redraw_is_kept_and_flagged(self):
        result, calls, checks = self._checked_draw(
            self._wounded_look(), ['{"passed": false, "problems": ["侧面没画伤"]}', '{"passed": false, "problems": ["血色鲜红"]}'],
        )
        self.assertEqual((len(calls), len(checks)), (2, 2))
        self.assertEqual(result["metadata"]["look_check"]["problems"], ["血色鲜红"])
        self.assertFalse(result["metadata"]["look_check"]["passed"])
        self.assertEqual([file["slot"] for file in result["files"]], ["front"])

    def test_with_no_model_that_can_see_the_look_is_kept_unchecked(self):
        look = self._wounded_look()
        calls: list = []
        with (
            self._drawing(calls),
            patch("app.api.element_api.element_image_gateway.describe_image", return_value=(None, "")),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
        ):
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(response.json()["metadata"]["look_check"])

    def test_a_check_that_gives_no_answer_is_asked_once_more(self):
        result, calls, checks = self._checked_draw(self._wounded_look(), ["", '{"passed": true, "problems": []}'])
        self.assertEqual((len(calls), len(checks)), (1, 2))
        self.assertTrue(result["metadata"]["look_check"]["passed"])

    def test_a_check_that_never_answers_leaves_the_look_unchecked(self):
        result, calls, checks = self._checked_draw(self._wounded_look(), ["", "想了很久"])
        self.assertEqual((len(calls), len(checks)), (1, 2))
        self.assertIsNone(result["metadata"]["look_check"])

    def test_a_redraw_that_fails_keeps_the_first_picture_and_its_problems(self):
        look = self._wounded_look()
        answers = iter([("https://assets.example.test/look.png", "seedream"), (None, "")])
        with (
            patch("app.api.element_api.element_image_gateway.generate_image", side_effect=lambda *a, **k: next(answers)),
            patch("app.api.element_api.element_image_gateway.describe_image", return_value=('{"passed": false, "problems": ["侧面没画伤"]}', "deepseek-flash")),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
        ):
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metadata"]["look_check"]["problems"], ["侧面没画伤"])
        self.assertEqual([file["slot"] for file in response.json()["files"]], ["front"])

    def test_without_a_face_nothing_is_paid_for(self):
        self._base_actor(image=False)
        self._file_looks()
        look = self._actors()["沈无咎·染血残衣"]
        with patch("app.api.element_api.element_image_gateway.generate_image") as generate:
            response = self.client.post(f"/api/elements/{look['id']}/regenerate", json={"prompt": ""}, cookies=self.cookie)
        self.assertEqual(response.status_code, 422)
        self.assertIn(SHEN, response.json()["detail"])
        generate.assert_not_called()

    def test_the_bulk_job_draws_only_the_missing_looks(self):
        self._base_actor()
        self._file_looks()
        calls: list = []
        with (
            self._drawing(calls),
            patch("app.api.element_api.fetch_remote_image_bytes", return_value=VALID_PNG),
        ):
            started = self.client.post(
                "/api/elements/generation-jobs", json={"kind": "actor", "looks": True, "task_id": TASK_ID}, cookies=self.cookie,
            )
            self.assertEqual(started.status_code, 202, started.text)
            job = self.client.get(f"/api/elements/generation-jobs/{started.json()['id']}", cookies=self.cookie).json()
        # 苏问剑还没有设定集，她的那套失败，沈无咎的两套出图；底子演员本人不算定妆图。
        self.assertEqual((job["total"], job["succeeded"], job["failed"]), (3, 2, 1))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self._actors()[SHEN]["files"][0]["slot"], "front")
        self.assertEqual(len(self._actors()[SHEN]["files"]), 1)

    def test_the_readiness_route_is_not_taken_for_a_kind_of_asset(self):
        repository = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        repository.save_task(TASK_ID, _task())
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: None
        with patch.object(drama_api.service, "repo", repository):
            response = self.client.get(f"/api/drama/{TASK_ID}/production-assets/readiness", cookies=self.cookie)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["kinds"]["look"]["total"], 3)
        self.assertFalse(response.json()["complete"])

    def test_actors_still_refuse_the_bulk_job_without_the_looks_flag(self):
        response = self.client.post("/api/elements/generation-jobs", json={"kind": "actor", "task_id": TASK_ID}, cookies=self.cookie)
        self.assertEqual(response.status_code, 422)


class PanelStillTests(unittest.TestCase):
    def test_the_panel_says_which_outfit_the_person_wears(self):
        references = [{"kind": "actor", "name": SHEN, "image_url": "data:look", "variant": "染血残衣"}]
        self.assertEqual(_costume_notes([SHEN], references, [])[SHEN], "「沈无咎」穿图1 的「染血残衣」")


if __name__ == "__main__":
    unittest.main()
