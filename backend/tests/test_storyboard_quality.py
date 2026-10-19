import unittest

from app.core.actor_sheet_layout import (
    ACTOR_SHEET_CELL_ORDER,
    ACTOR_SHEET_LAYOUT,
    REGION_TITLES,
    actor_sheet_cell_boxes,
)
from app.core.storyboard_quality import (
    build_actor_sheet_prompt,
    build_nine_grid_prompt,
    validate_storyboard_continuity,
)
from tests.test_production_contracts import _panel
from app.schema.production import NineGridStoryboard, StoryAssetCatalog


class StoryboardQualityTests(unittest.TestCase):
    def setUp(self):
        self.board = NineGridStoryboard(
            title="雨夜来信",
            assets=StoryAssetCatalog(
                characters=["林夏"], scenes=["客厅"], props=["信封"], effects=["雨丝"]
            ),
            panels=[_panel(i) for i in range(1, 10)],
        )

    def test_actor_sheet_prompt_describes_every_region_and_grid(self):
        prompt = build_actor_sheet_prompt("林夏", "左眼下泪痣、低马尾、米白风衣", "写实电影")

        # 三个区域标题必须逐字出现——模型照着它画，画错就切错。
        for title in REGION_TITLES:
            self.assertIn(title, prompt)
        self.assertEqual(REGION_TITLES, ("主肖像", "全身与元素", "细节矩阵"))
        # 标题只用中文：画面上不能再出现英文区域名。
        for english in ["MAIN PORTRAIT", "FULL BODY", "DETAIL MATRIX", "大写"]:
            self.assertNotIn(english, prompt)
        self.assertIn("不写英文", prompt)
        # 三栏宽度与中栏内部比例
        for proportion in ["20%", "40%", "60%"]:
            self.assertIn(proportion, prompt)
        # 三个网格形状
        self.assertIn("1行×3列", prompt)
        self.assertIn("2行×4列", prompt)
        self.assertIn("4行×3列", prompt)
        # 全身格按真实成人比例出图，参考图的大脸不得原尺寸搬进全身格。
        self.assertIn("7.5到8头身", prompt)
        self.assertIn("禁止大头小身", prompt)
        # 每个子格下方的编号中文标注
        for caption in ["1. 鞋履特写", "8. 裙摆下摆刺绣", "1. 正脸特写", "2. 左侧45°侧脸", "3. 右侧45°侧脸", "12. 动态姿态或小配件"]:
            self.assertIn(caption, prompt)
        # 用户自己的说法
        for phrase in [
            "21:9", "高级灰白渐变", "无任何环境杂物", "纯白间隔",
            "脚底对齐", "同一条基线", "头顶在同一高度", "不重叠", "不粘连",
        ]:
            self.assertIn(phrase, prompt)
        # 身份锁与禁止项沿用旧提示词的约束
        self.assertIn("同一人物", prompt)
        self.assertIn("左眼下泪痣、低马尾、米白风衣", prompt)
        self.assertIn("写实电影", prompt)
        for lock in ["脸型", "五官比例", "发际线", "水印", "场景道具"]:
            self.assertIn(lock, prompt)
        # 可执行画面描述：不得夹带 markdown / 元指令 / 文档引用
        for forbidden in ["##", "```", "参考文档", ".md", "请按", "模板"]:
            self.assertNotIn(forbidden, prompt)

    def test_actor_sheet_layout_proportions_and_cell_tiling(self):
        layout = ACTOR_SHEET_LAYOUT
        self.assertAlmostEqual(
            layout.left_portrait_width + layout.middle_width + layout.right_details_width, 1.0
        )
        self.assertEqual(len(ACTOR_SHEET_CELL_ORDER), 25)
        self.assertEqual(len(set(ACTOR_SHEET_CELL_ORDER)), 25)
        self.assertEqual(ACTOR_SHEET_CELL_ORDER[:5], ("portrait", "full_body", "front", "profile", "back"))
        self.assertEqual(ACTOR_SHEET_CELL_ORDER[13:16], ("face_front", "face_three_quarter", "face_three_quarter_right"))
        self.assertEqual(ACTOR_SHEET_CELL_ORDER[-1], "detail_accessory")

        # 纯几何：25 个框必须严格铺满标题带以下的画布、互不重叠；标题带不属于任何格子。
        width, height = layout.default_width, layout.default_height
        band = round(height * layout.title_band_ratio)
        boxes = actor_sheet_cell_boxes(width, height)
        self.assertEqual([cell for cell, _ in boxes], list(ACTOR_SHEET_CELL_ORDER))
        covered = 0
        occupied: set[tuple[int, int]] = set()
        for _cell, (left, top, right, bottom) in boxes:
            self.assertLess(left, right)
            self.assertLess(top, bottom)
            covered += (right - left) * (bottom - top)
            corner = (left, top)
            self.assertNotIn(corner, occupied)
            occupied.add(corner)
        self.assertEqual(covered, width * (height - band))

        # 逐像素确认无重叠：每个像素恰好被一个格子覆盖。
        for sample_x in range(0, width, 97):
            for sample_y in range(band, height, 89):
                hits = [
                    cell for cell, (left, top, right, bottom) in boxes
                    if left <= sample_x < right and top <= sample_y < bottom
                ]
                self.assertEqual(len(hits), 1, (sample_x, sample_y, hits))

    def test_nine_grid_prompt_contains_all_panels_and_layout_guards(self):
        prompt = build_nine_grid_prompt(self.board)
        self.assertIn("3×3", prompt)
        self.assertIn("从左到右、从上到下", prompt)
        self.assertIn("禁止合并格子", prompt)
        for i in range(1, 10):
            self.assertIn(f"第{i}格", prompt)
        for category in ["角色", "场景", "道具", "特效"]:
            self.assertIn(category, prompt)
        for detail in ["50mm", "T2.8", "构图", "轴线", "视线", "灯光", "入剪", "出剪", "首尾帧"]:
            self.assertIn(detail, prompt)

    def test_continuity_validator_reports_axis_and_prop_breaks(self):
        panels = [p.model_copy(deep=True) for p in self.board.panels]
        panels[1].continuity_in = ""
        panels[1].props = []
        report = validate_storyboard_continuity(panels)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.panel_index == 2 for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
