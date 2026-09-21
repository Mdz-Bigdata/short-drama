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
    def test_empty_shot_is_not_compiled_as_a_fictional_character(self):
        panel = _panel(1).model_copy(update={"characters": ["空镜（无人物）"], "subject_action": "月光照亮泥地棋盘"})
        board = NineGridStoryboard(
            title="空镜", assets=StoryAssetCatalog(characters=["空镜（无人物）"], scenes=["天牢"], props=["棋盘"], effects=["月光尘埃"]),
            panels=[panel],
        )
        result = compile_storyboard_prompt_detail(board, script_text="月光照亮泥地棋盘", visual_style="写实")
        self.assertEqual(result.foundation["characters"], [])
        self.assertIn("空镜，无人物", result.still_prompts[0].prompt)
        self.assertNotIn("空镜（无人物）的角色五视图", result.still_prompts[0].prompt)

    def test_scene_identity_and_current_costume_are_preserved(self):
        board = NineGridStoryboard(
            title="天牢月光", scene_number=3,
            assets=StoryAssetCatalog(characters=["沈砚"], scenes=["天牢"], props=["铁链"], effects=["月光尘埃"]),
            panels=[_panel(1)],
        )
        result = compile_storyboard_prompt_detail(
            board, script_text="沈砚抬头望月", visual_style="写实", episode="第2集", scene_id="E2S03",
            production_context={
                "costumes": [{"name": "沈砚囚服", "description": "灰白粗麻，右肩破损"}],
                "scenes": [{"name": "天牢", "description": "北墙气孔；泥地棋盘"}],
            },
        )
        self.assertEqual(result.shot_number, "E2S03")
        self.assertIn("右肩破损", result.foundation["characters"][0]["costume"])
        self.assertIn("北墙气孔", result.foundation["scene_and_props"]["spatial_structure"])

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

    def test_keeps_the_prompt_detail_concise_and_scene_focused(self):
        board = NineGridStoryboard(
            title="精简分镜",
            assets=StoryAssetCatalog(
                characters=["未出场角色", "沈砚"],
                scenes=["天牢"],
                props=["未出场道具", "石子", "铁链", "腐草堆"],
                effects=["月光尘埃"],
            ),
            panels=[_panel(1, "我终于找到你了"), _panel(2), _panel(3)],
        )

        result = compile_storyboard_prompt_detail(
            board,
            script_text="长" * 2_000,
            visual_style="电影写实",
        )

        self.assertEqual(result.foundation["script_text"], "长" * 2_000)
        self.assertEqual([item["name"] for item in result.foundation["characters"]], ["沈砚"])
        self.assertNotIn(
            "未出场道具",
            [item["name"] for item in result.foundation["scene_and_props"]["props"]],
        )
        self.assertEqual(result.foundation["verbatim_dialogue"][0]["speaker"], "沈砚")
        self.assertNotIn("未出场角色", result.foundation["shot_visual_design"]["base_content"])
        self.assertNotIn("未出场道具", result.foundation["shot_visual_design"]["base_content"])
        for prompt in result.still_prompts:
            self.assertNotIn("未出场角色", prompt.prompt)
            self.assertNotIn("未出场道具", prompt.prompt)
        self.assertEqual(
            result.foundation["narrative_goal"],
            "沈砚完成第1个连续动作阶段 → 沈砚完成第2个连续动作阶段 → 沈砚完成第3个连续动作阶段",
        )

    def test_bare_dialogue_uses_the_character_in_its_current_panel(self):
        second_panel = _panel(2, "这句台词属于当前拍角色")
        second_panel.characters = ["贺兰霆"]
        board = NineGridStoryboard(
            title="多角色台词归属",
            assets=StoryAssetCatalog(
                characters=["沈砚", "贺兰霆"],
                scenes=["天牢"],
                props=["石子", "铁链", "腐草堆"],
                effects=["月光尘埃"],
            ),
            panels=[_panel(1), second_panel, _panel(3)],
        )

        result = compile_storyboard_prompt_detail(
            board,
            script_text="沈砚沉默。贺兰霆开口。",
            visual_style="电影写实",
        )

        self.assertEqual(result.foundation["verbatim_dialogue"][0]["speaker"], "贺兰霆")
        self.assertIn("贺兰霆", result.still_prompts[1].prompt)
        self.assertNotIn("沈砚：这句台词属于当前拍角色", result.still_prompts[1].prompt)

    def test_derives_sound_cues_damage_table_crowd_and_anchored_landmarks_from_panels(self):
        stained = _panel(2).model_copy(update={"subject_action": "沈砚指尖擦过棋盘，泥点沾上袖口"})
        crowd = _panel(3).model_copy(update={
            "characters": ["沈砚", "狱卒们"],
            "sound": "铁门吱呀、脚步声逼近",
            "subject_action": "狱卒们从走廊尽头列队走来",
        })
        board = NineGridStoryboard(
            title="天牢月光",
            assets=StoryAssetCatalog(characters=["沈砚", "狱卒们"], scenes=["天牢"], props=["石子", "铁链", "腐草堆"], effects=["月光尘埃"]),
            panels=[_panel(1), stained, crowd],
        )

        result = compile_storyboard_prompt_detail(
            board, script_text="沈砚划线，狱卒逼近", visual_style="写实",
            character_profiles={"沈砚": "长发束起"},
            production_context={"props": [
                {"name": "铁门", "description": "沈砚正前方约5米，走廊尽头"},
                {"name": "腐草堆", "description": "沈砚身下"},
            ]},
        )

        foundation = result.foundation
        self.assertEqual(
            [(item["start_seconds"], item["end_seconds"]) for item in foundation["timed_sounds"]],
            [(0.0, 4.0), (4.0, 6.0)],
        )
        self.assertEqual(foundation["damage_timeline"][0]["seconds"], 2.0)
        self.assertEqual(foundation["damage_timeline"][0]["subject"], "沈砚")
        self.assertIn("泥点沾上袖口", foundation["damage_timeline"][0]["change"])
        self.assertEqual(foundation["extras_and_crowd"]["label"], "狱卒们")
        self.assertIn("列队走来", foundation["extras_and_crowd"]["motion_parameters"])
        self.assertEqual([item["name"] for item in foundation["scene_and_props"]["landmarks"]], ["铁门"])
        self.assertIn("铁门：沈砚正前方约5米", result.video_segments[0].prompt)
        self.assertIn("铁门吱呀", result.video_segments[-1].prompt)
        self.assertIn("2秒沈砚：第2拍", result.still_prompts[-1].prompt)
        self.assertTrue(result.submission_ready)

    def test_clean_shot_keeps_timelines_empty_and_omits_the_crowd_block(self):
        board = NineGridStoryboard(
            title="天牢月光",
            assets=StoryAssetCatalog(characters=["沈砚"], scenes=["天牢"], props=["石子"], effects=["月光尘埃"]),
            panels=[_panel(1), _panel(2)],
        )

        result = compile_storyboard_prompt_detail(board, script_text="沈砚抬头望月", visual_style="写实")

        self.assertEqual(result.foundation["damage_timeline"], [])
        self.assertNotIn("extras_and_crowd", result.foundation)
        self.assertEqual(len(result.foundation["timed_sounds"]), 1)
        self.assertEqual(result.foundation["timed_sounds"][0]["end_seconds"], 4.0)
        self.assertEqual(result.foundation["scene_and_props"]["landmarks"], [])
        self.assertIn("本段内变化：无", result.video_segments[0].prompt)
        self.assertIn("污损时间表之外新增", result.video_segments[0].prompt)

    def test_screen_coordinate_positions_are_derived_from_panel_composition(self):
        positioned = _panel(1).model_copy(update={
            "composition": "沈砚位于画面左侧三分之一的中景，朝向画面右侧，中央过道保持空白，不要进入画面中心",
        })
        board = NineGridStoryboard(
            title="天牢月光",
            assets=StoryAssetCatalog(characters=["沈砚"], scenes=["天牢"], props=["石子"], effects=["月光尘埃"]),
            panels=[positioned, _panel(2)],
        )
        result = compile_storyboard_prompt_detail(board, script_text="沈砚抬头望月", visual_style="写实")
        positions = result.foundation["shot_visual_design"]["frame_positions"]
        self.assertEqual(positions[0]["subject"], "沈砚")
        self.assertEqual((positions[0]["region"], positions[0]["depth"], positions[0]["facing"]), ("画面左侧三分之一", "中景", "朝向画面右侧"))
        self.assertIn("不要进入画面中心", positions[0]["forbidden_zone"])
        self.assertIn("画面坐标：沈砚位于画面左侧三分之一的中景，朝向画面右侧", result.still_prompts[0].prompt)

    def test_sound_layers_are_split_into_near_mid_and_far(self):
        panel = _panel(1).model_copy(update={"sound": "石子摩擦泥地、铁链轻响、风穿气孔、远处滴水"})
        board = NineGridStoryboard(
            title="天牢月光",
            assets=StoryAssetCatalog(characters=["沈砚"], scenes=["天牢"], props=["石子"], effects=["月光尘埃"]),
            panels=[panel, _panel(2)],
        )
        result = compile_storyboard_prompt_detail(board, script_text="沈砚抬头望月", visual_style="写实")
        design = result.foundation["sound_design"]
        self.assertEqual(design["near"], "石子摩擦泥地、铁链轻响")
        self.assertEqual(design["mid"], "风穿气孔")
        self.assertEqual(design["far"], "远处滴水")
        self.assertIn("音效分层：近—石子摩擦泥地、铁链轻响；中—风穿气孔；远—远处滴水", result.video_segments[0].prompt)

if __name__ == "__main__":
    unittest.main()
