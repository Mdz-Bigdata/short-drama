# -*- coding: utf-8 -*-
"""Design sheets: what has to be locked before a single frame is generated.

A character sheet describes a look and never a temperament; a scene sheet holds the
room and nobody in it; a prop earns a sheet only if the story leans on it.
"""

import unittest

from app.core import asset_sheets as sheets
from app.core import style_packs
from app.core.style_packs import PaletteColour

TASK = {
    "config": {"title_suggestion": "暗室回声"},
    "assets": {
        "2": "林夏把录音笔递给周教授。桌上放着茶杯。周教授掏出一张照片，指尖发抖。",
        "3_characters": [
            {"name": "林夏", "desc": "22岁女记者，齐耳短发，青灰大衣，性格倔强不肯低头"},
            {"name": "周教授", "description": "花白头发，深色西装，金丝眼镜"},
        ],
        "2_breakdown": {
            "production_assets": {
                "scenes": [{"name": "办公室", "description": "北侧档案柜，冷白顶灯，深夜"}],
                "props": [
                    {"name": "录音笔", "description": "银色金属外壳，边角磨损"},
                    {"name": "照片", "description": "泛黄的合影"},
                    {"name": "茶杯", "description": "白瓷"},
                ],
            },
        },
    },
}


class CharacterSheetTests(unittest.TestCase):
    def test_a_character_sheet_describes_a_look_not_a_temperament(self):
        sheet = sheets.character_sheet("林夏", "22岁女记者，齐耳短发，青灰大衣，性格倔强不肯低头")

        self.assertEqual(sheet.kind, "character")
        self.assertIn("齐耳短发", sheet.prompt)
        self.assertNotIn("性格倔强", sheet.prompt)
        self.assertTrue(any("性格倔强" in note for note in sheet.notes))
        self.assertIn("齐耳短发", sheet.anchors)

    def test_the_layout_is_the_part_that_makes_the_sheet_reusable(self):
        sheet = sheets.character_sheet("周教授", "花白头发")

        for requirement in ("正面(FRONT)", "侧面(PROFILE)", "背面(BACK)", "纯白背景", "不得出现任何文字"):
            self.assertIn(requirement, sheet.layout)
        self.assertIn(sheet.layout, sheet.prompt)

    def test_a_card_with_no_appearance_says_so(self):
        sheet = sheets.character_sheet("神秘人", "")

        self.assertTrue(any("没有给出外形" in note for note in sheet.notes))

    def test_the_style_pack_reaches_the_sheet(self):
        sheet = sheets.character_sheet("林夏", "齐耳短发", pack=style_packs.ANIME_2D_CEL)

        self.assertIn("cel-shaded anime", sheet.prompt)


class SceneSheetTests(unittest.TestCase):
    def test_a_scene_prompt_opens_by_emptying_the_room(self):
        sheet = sheets.scene_sheet("办公室", "北侧档案柜，冷白顶灯，深夜")

        self.assertTrue(sheet.prompt.startswith(sheets.EMPTY_SCENE_PREFIX))
        self.assertIn(sheets.EMPTY_SCENE_SUFFIX, sheet.prompt)
        self.assertIn("四宫格", sheet.layout)
        for angle in ("高角度航拍俯瞰", "低角度仰视", "侧面视角", "反面视角"):
            self.assertIn(angle, sheet.layout)

    def test_a_bare_noun_is_given_a_name_that_identifies_the_place(self):
        self.assertEqual(sheets.scene_name("办公室", "冷白顶灯，深夜"), "顶灯深夜办公室")
        self.assertEqual(sheets.scene_name("咖啡厅", "暖光靠窗，木桌"), "暖光木咖啡厅")
        # A name that already identifies the place is left alone.
        self.assertEqual(sheets.scene_name("夜雨玻璃长廊", ""), "夜雨玻璃长廊")
        self.assertGreaterEqual(len(sheets.scene_name("门口", "")), sheets.MIN_SCENE_NAME_CHARS)


class PropAndPaletteTests(unittest.TestCase):
    def test_only_the_props_the_story_leans_on_get_a_sheet(self):
        result = sheets.extract_sheets(TASK, pack=style_packs.FILM_35MM)

        names = [sheet.name for sheet in result.props]
        self.assertIn("录音笔", names)          # handed over
        self.assertIn("照片", names)            # taken out
        self.assertNotIn("茶杯", names)         # just sitting there
        self.assertTrue(any("茶杯" in warning for warning in result.warnings))

    def test_a_palette_sheet_states_every_colour_and_what_it_is_bound_to(self):
        result = sheets.extract_sheets(
            TASK, pack=style_packs.FILM_35MM,
            palette_colours=[PaletteColour(name="冷白", hex="#DDE6EE", bound_to="顶灯")],
        )

        palette = result.palette
        self.assertIsNotNone(palette)
        self.assertIn("COLOR REFERENCE", palette.name)
        self.assertIn("顶灯冷白#DDE6EE", palette.prompt)
        self.assertIn("白底平色块", palette.prompt)
        self.assertTrue(any("色板结构" in note for note in palette.notes))

    def test_a_palette_is_optional(self):
        self.assertIsNone(sheets.extract_sheets(TASK, pack=style_packs.FILM_35MM).palette)


class SheetSetTests(unittest.TestCase):
    def test_a_task_yields_one_sheet_per_asset_that_needs_locking(self):
        result = sheets.extract_sheets(TASK, pack=style_packs.FILM_35MM)

        self.assertEqual([sheet.name for sheet in result.characters], ["林夏", "周教授"])
        self.assertEqual([sheet.name for sheet in result.scenes], ["顶灯深夜办公室"])
        self.assertEqual(len(result.all), len(result.characters) + len(result.scenes) + len(result.props))

    def test_a_project_without_a_cast_says_what_is_missing(self):
        result = sheets.extract_sheets({"assets": {}}, pack=style_packs.FILM_35MM)

        self.assertEqual(result.characters, [])
        self.assertTrue(any("第3阶段" in warning for warning in result.warnings))

    def test_the_document_carries_the_four_blocks_and_every_required_field(self):
        result = sheets.extract_sheets(
            TASK, pack=style_packs.FILM_35MM,
            palette_colours=[PaletteColour(name="冷白", hex="#DDE6EE", bound_to="顶灯")],
        )

        text = sheets.render_markdown(result, title="暗室回声 资产")

        for block in ("【人物资产】", "【场景资产】", "【道具资产】", "【色板资产】"):
            self.assertIn(block, text)
        for field in ("功能定位", "稳定识别锚点", "描述提示词", "固定格式输出"):
            self.assertIn(field, text)
        self.assertIn("色板结构说明", text)


if __name__ == "__main__":
    unittest.main()
