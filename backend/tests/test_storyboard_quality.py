import unittest

from app.core.storyboard_quality import (
    build_five_view_prompt,
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

    def test_five_view_prompt_locks_identity_and_order(self):
        prompt = build_five_view_prompt("林夏", "左眼下泪痣、低马尾、米白风衣", "写实电影")
        for label in ["正面", "正面四分之三", "标准侧面", "背面四分之三", "背面"]:
            self.assertIn(label, prompt)
        self.assertIn("同一人物", prompt)
        self.assertIn("五个视图", prompt)

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
