import unittest

from app.core.storyboard_prompt_detail import compile_storyboard_prompt_detail
from app.schema.production import NineGridStoryboard, StoryAssetCatalog, StoryboardPanel


def _panel(index: int, dialogue: str = "") -> StoryboardPanel:
    return StoryboardPanel(
        index=index,
        characters=["沈砚"],
        shot_size="近景" if index > 1 else "全景",
        camera_angle="平视偏俯角30度",
        camera_movement="固定镜头",
        camera_reason="保持孤独压迫感并交代动作变化",
        lens_mm=50,
        aperture="T2.8",
        composition="9:16竖构图，人物居中偏下，棋盘与月光形成纵向联系",
        action_axis="摄影机始终位于棋盘南侧，不越轴",
        eyeline="沈砚由棋盘逐步抬眼望向上方气孔",
        shot_purpose="emotion",
        story_beat=f"沈砚动作阶段{index}",
        duration_seconds=2.0,
        subject_action=f"沈砚完成第{index}个连续动作阶段",
        expression="呼吸克制，目光逐步从棋盘移向月光",
        scene="天牢腐草堆与泥地棋盘",
        props=["石子", "铁链", "腐草堆"],
        effects=["月光尘埃"],
        dialogue=dialogue,
        sound="石子摩擦泥地、铁链轻响、远处滴水",
        lighting="顶部气孔漏入冷白月光，低照度高反差",
        edit_in="承接上一状态的动作与声音",
        edit_out="在动作完成并形成清晰姿态时交给下一拍",
        generation_mode="auto",
        blocking="沈砚盘坐腐草堆，右手操作石子，铁链垂在膝旁",
        start_state=f"第{index}拍开始状态",
        end_state=f"第{index}拍结束状态",
        continuity_in="建立天牢空间" if index == 1 else f"承接第{index - 1}拍结束状态",
        continuity_out=f"把第{index}拍结束姿态交给下一拍",
    )


class StoryboardPromptDetailTests(unittest.TestCase):
    def test_compiles_every_template_section_for_the_grid_prompt_viewer(self):
        board = NineGridStoryboard(
            title="天牢月光",
            assets=StoryAssetCatalog(
                characters=["沈砚"],
                scenes=["天牢"],
                props=["石子", "铁链", "腐草堆"],
                effects=["月光尘埃"],
            ),
            panels=[_panel(1, "旁白：天牢最深处，月光从半尺见方的气孔漏进来。"), _panel(2), _panel(3)],
        )

        result = compile_storyboard_prompt_detail(
            board,
            script_text="天牢最深处，沈砚盘坐在腐草堆上，在泥地棋盘上划线后抬头望月。",
            visual_style="真人电视剧风格，精品短剧画风，大师级构图",
            episode="第1集",
        )

        foundation = result.foundation
        for key in (
            "shot_information",
            "narrative_goal",
            "script_text",
            "characters",
            "scene_and_props",
            "verbatim_dialogue",
            "global_visual_rules",
            "continuity_locks",
            "shot_visual_design",
            "color_design",
            "dynamics_design",
            "camera_design",
            "transition_design",
        ):
            self.assertIn(key, foundation)
        self.assertEqual(len(result.beats), 3)
        self.assertEqual(len(result.still_prompts), 3)
        self.assertEqual(len(result.video_segments), 2)
        self.assertEqual(len(result.grid_pages[0].cells), 9)
        self.assertGreaterEqual(len(result.continuity_checks), 10)
        self.assertIn("当前帧核心画面", result.still_prompts[0].prompt)
        self.assertIn("摄影机运动", result.video_segments[0].prompt)


if __name__ == "__main__":
    unittest.main()
