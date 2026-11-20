"""招式分解图(画布工具)与兵器套路(第 4 阶段，只在剧本没写招的打戏里)。

No model is called: the requests are rendered and read.
"""

import re
import unittest
from pathlib import Path

from app.core import canvas_tools, move_sheets, prompt_data, style_moves, sword_techniques, weapon_forms, weapon_moves
from app.core.canvas_tools import CanvasToolError

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED = "沈无咎挺枪直刺，裴仲玄挥刀格开，一掌拍在他肩头，又一脚踢中小腹"
NAMED_ONLY = "两人在渡口交手，沈无咎挺枪，裴仲玄挥刀"


def _sheet(text="", **params):
    return canvas_tools.image_prompt(canvas_tools.get_tool("move_sheet"), params, text)


class MoveSheetTableTests(unittest.TestCase):
    def test_fifteen_sets_of_eight_or_five_moves_each_with_a_layout_and_known_rules(self):
        data = prompt_data.load("move_sheets")
        sets = move_sheets.sets()
        self.assertEqual(len(sets), 15)
        self.assertEqual(len({item["id"] for item in sets}), 15)
        self.assertEqual(sum(len(item["moves"]) for item in sets), 96)
        for item in sets:
            with self.subTest(item["id"]):
                self.assertIn(len(item["moves"]), (5, 8))
                self.assertIn(str(len(item["moves"])), data["layouts"])
                self.assertTrue(item["rules"])
                self.assertTrue(set(item["rules"]) <= set(data["rules"]))
                self.assertEqual(len({move["name"] for move in item["moves"]}), len(item["moves"]))
                self.assertTrue(all(len(move["how"]) >= 8 for move in item["moves"]), "each move says what is seen")
        self.assertIn(move_sheets.default_set(), {item["id"] for item in sets})

    def test_the_picker_and_the_form_show_the_same_sets(self):
        text = (ROOT / "frontend" / "src" / "features" / "canvas" / "canvasTools.ts").read_text(encoding="utf-8")
        row = text[text.index("id: 'move_sheet'"):]
        row = row[:row.index("note:")]
        shown = re.findall(r"\['(\w+)', \(\) => t\('([^']+)'\)\]", row)
        self.assertEqual(shown, [(item["id"], item["label"]) for item in move_sheets.catalog()])
        self.assertIn(f"fallback: '{move_sheets.default_set()}'", row)


class MoveSheetPromptTests(unittest.TestCase):
    def test_the_tool_calls_the_image_model_with_one_character_picture(self):
        tool = canvas_tools.get_tool("move_sheet")
        self.assertEqual((tool.group, tool.engine, tool.output, tool.images, tool.needs_prompt), ("skill", "image", "image", 1, False))

    def test_every_move_of_the_set_is_a_panel_in_order_and_the_person_is_the_picture(self):
        prompt = _sheet(set="staff")
        chosen = move_sheets.get("staff")
        places = [prompt.index(move["how"]) for move in chosen["moves"]]
        self.assertEqual(places, sorted(places))
        for words in ("图1是人物", "每一格都是同一个人，手里一根粗细一致的长棍，棍和人一样高，也就是和人两臂平伸的宽度一样长", "每一格只画写到的那一个瞬间", "不换成别的招",
                      "从头顶到脚底的全身都拍到，不拍半身和特写", "背景是没有建筑和陈设的素色空场",
                      "它始终顺着画面摆、不朝镜头伸过来", "8 个独立画格，排成 4 行 2 列",
                      "兵器的长度、粗细和形制每一格相同", "拿它和人的身高比，每一格都一样长", "兵器再长也整根画在格内",
                      "兵器两头到格边都留着空白", "握兵器的手和握点看得清", "不被画格边缘裁掉", "只有写了腾空、跃起的那一格人才离地", "其余每一格双脚都踩在地上",
                      "不出现任何字、旗幡、匾额和招牌"):
            self.assertIn(words, prompt)
        self.assertTrue(prompt.endswith("不画标题、编号、招式名和说明文字。" + prompt_data.text("canvas_tools", "module.no_text")))
        for move in chosen["moves"]:
            self.assertNotIn(move["name"], prompt.replace(move["how"], ""), "the move's name is not something to draw")

    def test_five_move_sets_take_two_rows_and_a_crowd_keeps_the_lead_recognisable(self):
        prompt = _sheet(set="breakout")
        for words in ("5 个独立画格，分三排：上排 2 格、中排 2 格、下排 1 格占满整行", "主角始终是图1这个人", "每一格里他们在主角的哪一边看得清", "主角手里的兵器指向对手所在的那一边"):
            self.assertIn(words, prompt)
        self.assertIn("光效只从身上、掌上发出来或沿兵器走过的路线出现", _sheet(set="spell"))
        self.assertIn("两手空着，手指看得清", _sheet(set="bare"))
        self.assertNotIn("素色空场", _sheet(set="qinggong"), "sets that need roofs, walls or rocks keep their setting")

    def test_nothing_chosen_is_the_default_set_what_the_user_adds_is_kept_and_an_unknown_set_is_refused(self):
        self.assertEqual(_sheet(), _sheet(set=move_sheets.default_set()))
        self.assertIn("不出现任何字、旗幡、匾额和招牌。夜里的庭院。不画标题", _sheet("夜里的庭院。", set="spear"))
        with self.assertRaises(CanvasToolError) as raised:
            _sheet(set="nunchaku")
        self.assertIn("没有这组招式：nunchaku", str(raised.exception))


class MoveSheetRunTests(unittest.TestCase):
    def test_a_run_sends_the_character_picture_and_the_sheet_request_to_the_image_model(self):
        from types import SimpleNamespace

        from app.core import studio_canvas
        from app.service import canvas_tool_ops

        seen = {}

        def generate_image(model, prompt, ref_images=None, size=None, **options):
            seen.update(model=model, prompt=prompt, ref_images=ref_images, size=size, options=options)
            return "http://localhost/media/sheet.png", "stand-in"

        drama = SimpleNamespace(gateway=SimpleNamespace(generate_image=generate_image))
        result = canvas_tool_ops._run_image(
            canvas_tools.get_tool("move_sheet"), studio_canvas.Inputs(ref_images=["http://localhost/media/hero.png"]),
            {"set": "spear"}, "雨夜的码头", "stand-in-image", "t", {}, drama, "/tmp",
        )
        self.assertEqual(result, {"url": "http://localhost/media/sheet.png"})
        self.assertEqual(seen["ref_images"], ["http://localhost/media/hero.png"])
        self.assertEqual(seen["prompt"], _sheet("雨夜的码头", set="spear"))
        width, height = (int(value) for value in seen["size"].split("x"))
        self.assertEqual(width * 4, height * 3, "the sheet is asked for at 3:4, not left to the model's default ratio")
        self.assertTrue(seen["options"]["require_reference_support"], "a model that cannot take the picture is refused, not run blind")


class SwordSheetTests(unittest.TestCase):
    def test_the_thirteen_named_items_are_two_sheets_from_the_grip_to_the_close(self):
        first, second = move_sheets.get("sword_basics_a"), move_sheets.get("sword_basics_b")
        self.assertEqual([move["name"] for move in first["moves"]], ["握剑", "起势", "刺剑", "劈剑", "点剑", "撩剑", "崩剑", "绞剑"])
        self.assertEqual([move["name"] for move in second["moves"]], ["挂剑", "扫剑", "带剑", "截剑", "收势"])
        prompt = _sheet(set="sword_basics_a")
        for words in ("右手持一柄细长的中式长剑", "虎口贴着护手", "右臂和剑连成一条水平直线", "手腕上提，剑尖向前下方啄出", "手腕下沉，剑尖向上翘到眉的高度"):
            self.assertIn(words, prompt)
        self.assertIn("5 个独立画格，分三排：上排 2 格、中排 2 格、下排 1 格占满整行", _sheet(set="sword_basics_b"))

    def test_the_duel_sheet_pairs_an_attack_with_its_answer_and_keeps_the_sides(self):
        prompt = _sheet(set="sword_duel")
        for words in ("主角右手持剑弓步直刺，剑尖指向对手胸口", "用自己的剑贴住主角的剑向身侧带开", "对手举剑下劈，主角横剑举过头顶架住",
                      "上排 2 格、中排 2 格、下排 1 格占满整行", "剑身是银白的钢色、只有一条，剑柄不带剑穗",
                      "腰间、背后和地上都没有别的剑和剑鞘",
                      "每一格里两人谁在左谁在右不变", "主角始终是图1这个人", "每一格手里都有一柄同样长短的剑", "两个人都整个在格内"):
            self.assertIn(words, prompt)


class SwordTechniqueTests(unittest.TestCase):
    def test_the_table_has_the_named_items_and_every_alias_names_one_technique(self):
        table = prompt_data.load("sword_techniques")["techniques"]
        names = [item["name"] for item in table]
        self.assertEqual(len(names), len(set(names)))
        for wanted in ("握剑", "起势", "刺剑", "劈剑", "点剑", "撩剑", "崩剑", "绞剑", "挂剑", "扫剑", "带剑", "截剑", "收势",
                       "云剑", "架剑", "抱剑", "穿剑", "斩剑", "腕花"):
            self.assertIn(wanted, names)
        seen: dict[str, str] = {}
        for item in table:
            self.assertGreaterEqual(len(item["how"]), 20, item["name"])
            self.assertTrue(item["use"], item["name"])
            for alias in item["aliases"]:
                self.assertGreaterEqual(len(alias), 2, f"{item['name']}: a one-character alias matches everything")
                self.assertNotIn(alias, seen, f"{alias} names both {seen.get(alias)} and {item['name']}")
                seen[alias] = item["name"]

    def test_only_the_techniques_the_scene_names_are_sent_and_only_when_a_sword_is_there(self):
        scene = "沈无咎拔剑直刺，裴仲玄侧身一带，反手上撩，剑尖一点他手腕"
        self.assertEqual(sword_techniques.techniques_in(scene), ["刺剑", "点剑", "撩剑", "带剑"])
        brief = sword_techniques.technique_brief(scene)
        self.assertTrue(brief.startswith("【剑法】"))
        for words in ("- 刺剑：剑尖领着走直线送出去，手臂和剑连成一条直线", "- 带剑：", "对手收不住、身子前扑", "对剑的通则：剑不和兵器硬碰"):
            self.assertIn(words, brief)
        self.assertNotIn("- 劈剑：", brief)
        self.assertEqual(sword_techniques.techniques_in("两人持棍横扫，一人架住"), [], "the same words with another weapon are not sword techniques")
        self.assertEqual(sword_techniques.technique_brief("两人持剑相斗，难分高下"), "", "a sword fight that names no technique gets the sequence instead")

    def test_everything_named_at_once_stays_inside_the_budget_and_no_line_is_cut(self):
        data = prompt_data.load("sword_techniques")
        scene = "长剑 " + " ".join(item["aliases"][0] for item in data["techniques"])
        self.assertEqual(len(sword_techniques.techniques_in(scene)), len(data["techniques"]))
        brief = sword_techniques.technique_brief(scene)
        self.assertLessEqual(len(brief), data["budget"])
        self.assertTrue(brief.endswith(data["usage"]))
        ends = tuple(item["use"][-6:] for item in data["techniques"])
        self.assertTrue(all(line.endswith(ends) for line in brief.splitlines()[1:-1]))

    def test_an_unchoreographed_sword_fight_runs_through_the_thirteen_items_in_order(self):
        line = prompt_data.load("weapon_forms")["forms"]["剑"]
        places = [line.index(word) for word in ("握剑", "起势", "直刺", "抡劈", "一点", "上撩", "崩开", "一绞", "挂向", "横扫", "一带", "截住", "收剑")]
        self.assertEqual(places, sorted(places))
        self.assertIn("每一次防都接着还一剑", line)
        self.assertIn("握剑虎口贴护手", {str(item["name"]): str(item["moves"]) for item in prompt_data.load("weapon_moves")["weapons"]}["剑"])

    def test_the_storyboard_request_reads_the_sword_table_for_fight_scenes(self):
        service = (ROOT / "backend" / "app" / "service" / "drama_service.py").read_text(encoding="utf-8")
        self.assertIn('sword_techniques.technique_brief(scene_content) if scene_kind == "fight" else ""', service)


class WeaponFormTests(unittest.TestCase):
    def test_only_the_weapons_of_the_scene_and_only_when_the_script_did_not_write_the_moves(self):
        self.assertFalse(style_moves.choreographed(NAMED_ONLY))
        brief = weapon_forms.forms_brief(NAMED_ONLY)
        self.assertTrue(brief.startswith("【兵器套路】"))
        self.assertIn("- 刀：", brief)
        self.assertIn("- 枪：", brief)
        self.assertNotIn("- 剑：", brief)
        self.assertIn("剧本写了的那几下照剧本", brief)
        self.assertTrue(style_moves.choreographed(SCRIPTED))
        self.assertEqual(weapon_forms.forms_brief(SCRIPTED), "")
        self.assertEqual(weapon_forms.forms_brief("两人在渡口交手，各出一拳"), "", "no weapon with a sequence in the scene")

    def test_each_sequence_runs_from_a_stance_to_a_close_and_belongs_to_a_weapon_of_the_weapon_table(self):
        data = prompt_data.load("weapon_forms")
        weapons = {str(item["name"]) for item in prompt_data.load("weapon_moves")["weapons"]}
        self.assertEqual(set(data["forms"]), {"棍", "剑", "刀", "枪", "弓箭"})
        self.assertTrue(set(data["forms"]) <= weapons)
        for name, line in data["forms"].items():
            with self.subTest(name):
                self.assertGreaterEqual(line.count("→"), 4)
                self.assertLessEqual(len(line), 150 if name != "剑" else 230, "the sword runs through thirteen named items")
        everything = "两人交手：长棍 长剑 长刀 长枪 弯弓"
        brief = weapon_forms.forms_brief(everything)
        self.assertLessEqual(len(brief), data["budget"])
        self.assertEqual(len(brief.splitlines()), 6, "all five fit with the lead")

    def test_long_weapons_stay_whole_in_a_wide_or_medium_frame(self):
        table = {str(item["name"]): str(item["moves"]) for item in prompt_data.load("weapon_moves")["weapons"]}
        self.assertIn("全景和中景里枪尖到枪尾整根在画内", table["枪"])
        self.assertIn("全景和中景里整根棍在画内，两手握在棍上的位置看得清", table["棍"])
        self.assertIn("整根在画内", weapon_moves.weapon_brief("沈无咎挺枪"))

    def test_the_storyboard_request_reads_the_sequences_right_after_the_style_table(self):
        service = (ROOT / "backend" / "app" / "service" / "drama_service.py").read_text(encoding="utf-8")
        self.assertIn('weapon_forms.forms_brief(scene_content) if scene_kind == "fight" else ""', service)
        self.assertLess(service.index("styles_brief = style_moves.style_brief("), service.index("weapon_forms.forms_brief(scene_content)"))


class VoiceDescriptionTests(unittest.TestCase):
    def test_a_designed_voice_names_its_register_as_well_as_its_timbre(self):
        spec = prompt_data.text("agent_prompts", "dna_structurer")
        self.assertIn("性别+年龄+音区+音色+语速+气质", spec)
        example = re.search(r"如 ([^)]+)\)", spec[spec.index("40字以内音色短描述"):]).group(1)
        self.assertIn("音区", example)
        self.assertLessEqual(len(example), 40)


if __name__ == "__main__":
    unittest.main()
