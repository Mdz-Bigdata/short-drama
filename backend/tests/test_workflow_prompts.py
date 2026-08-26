import unittest

from app.core.workflow_prompts import (
    STORYBOARD_SCRIPT_PROMPT,
    VIDEO_STORYBOARD_PROMPT,
    build_video_batch_prompt,
)
from app.service.drama_service import parse_storyboard_table


class WorkflowPromptTests(unittest.TestCase):
    def test_storyboard_prompt_contains_attached_breakdown_contract(self):
        for rule in (
            "情绪转变需切镜",
            "复杂动作需切镜",
            "人物变化需切镜",
            "空间转场需切镜",
            "时间跳跃需切镜",
            "对话的视线乒乓逻辑",
            "摄影机的变化",
            "视觉特效独占镜头",
        ):
            self.assertIn(rule, STORYBOARD_SCRIPT_PROMPT)
        for column in ("镜号", "时长", "景别", "摄法", "画面内容", "台词/音效", "入镜角色", "场景标识"):
            self.assertIn(column, STORYBOARD_SCRIPT_PROMPT)
        self.assertIn("不少于50字", STORYBOARD_SCRIPT_PROMPT)
        self.assertIn("输出前自检清单", STORYBOARD_SCRIPT_PROMPT)

    def test_video_prompt_contains_attached_batch_and_continuity_contract(self):
        for rule in (
            "批次拆分规则",
            "台词时长判断规则",
            "台词处理规则",
            "镜头节奏规则",
            "空间关系规则",
            "连续性规则",
            "音效规则",
            "输出格式要求",
        ):
            self.assertIn(rule, VIDEO_STORYBOARD_PROMPT)
        self.assertIn("每个汉字约0.3秒", VIDEO_STORYBOARD_PROMPT)
        self.assertIn("只生成音效，禁止生成音乐。禁止生成任何字幕。", VIDEO_STORYBOARD_PROMPT)
        self.assertIn("以下是详细剧情：", VIDEO_STORYBOARD_PROMPT)

    def test_video_batch_prompt_is_standalone_and_preserves_dialogue(self):
        result = build_video_batch_prompt(
            batch_index=2,
            visual_style="电影感真人实拍",
            duration_seconds=8,
            spatial_relationship="室内办公室，办公桌在房间中央，林夏站在桌前面向周明，周明坐在桌后看向林夏。",
            timeline="0-3秒，中景，固定镜头，林夏攥紧信封停在桌前。3-8秒，近景，缓慢推镜，林夏说：\"这封信我从来没有打开过。\"",
            sound="纸张摩擦声、压低的呼吸声",
        )

        self.assertIn("【批次 2】", result)
        self.assertIn("预计时长：8秒", result)
        self.assertIn("空间关系：室内办公室", result)
        self.assertIn("以下是详细剧情：", result)
        self.assertIn("这封信我从来没有打开过。", result)
        self.assertIn("只生成音效，禁止生成音乐。禁止生成任何字幕。", result)
        self.assertNotIn("同上", result)

    def test_storyboard_table_parser_keeps_duration_sound_cast_and_scene(self):
        table = """
| 镜号 | 景别 | 机位角度 | 运镜 | 画面内容 | 台词对白 | 声音 | 时长 | 叙事目的 | 入镜角色 | 场景标识 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 全景 | 平视 | 固定 | 北京西站广场建立镜头，林夏站在出站口前。 | 林夏：终于到了。 | 人群脚步声 | 3.5秒 | 建立空间 | 林夏 | E1S01 北京西站广场 |
"""

        shot = parse_storyboard_table(table, [])[0]

        self.assertEqual(shot["angle"], "平视")
        self.assertEqual(shot["sound"], "人群脚步声")
        self.assertEqual(shot["duration"], "3.5秒")
        self.assertEqual(shot["characters"], ["林夏"])
        self.assertEqual(shot["scene_id"], "E1S01")
        self.assertEqual(shot["scene"], "北京西站广场")


if __name__ == "__main__":
    unittest.main()
