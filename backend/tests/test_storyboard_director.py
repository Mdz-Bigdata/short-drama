import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth_api import get_current_user
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.schema.storyboard_director import (
    CameraDesign,
    ColorDesign,
    ContinuityLocks,
    DirectorCharacter,
    DirectorProp,
    DirectorScene,
    DynamicsDesign,
    GlobalVisualRules,
    ShotVisualDesign,
    StoryboardDirectorRequest,
    StoryEvent,
    TimedDialogue,
    TransitionDesign,
    TransitionEdge,
)
from main import app


def _request(**updates) -> StoryboardDirectorRequest:
    values = {
        "project_name": "雨夜来信",
        "episode": "第1集",
        "scene_number": 3,
        "shot_number": "S03-07",
        "duration_seconds": 9,
        "script_text": "林夏拿起信封。\n林夏：我知道了。\n她把信放回桌面。",
        "narrative_goal": "观众看懂林夏确认真相并克制情绪。",
        "characters": [DirectorCharacter(
            name="林夏",
            identity="调查记者",
            age_impression="28岁",
            appearance="椭圆脸、左眼下泪痣、黑色短发",
            costume="米白风衣、深灰长裤",
            accessories="左腕银色手表",
            physical_state="被雨淋湿，左肩有水渍",
            psychological_state="警惕且克制",
        )],
        "scene": DirectorScene(
            time="雨夜",
            location="咖啡厅窗边",
            weather="暴雨",
            spatial_structure="林夏在画面右侧窗边，木桌居中，空椅在桌对面，入口位于背景左侧",
            props=[DirectorProp(
                name="信封", initial_state="封口已拆开",
                initial_position="林夏右手中", allowed_motion="右手抬起后放到桌面中央",
            )],
            environmental_sound="连续雨声、远处低频雷声、纸张摩擦声",
        ),
        "timed_dialogue": [TimedDialogue(
            kind="dialogue", speaker="林夏", exact_text="我知道了。",
            start_seconds=3, end_seconds=4.5,
        )],
        "events": [
            StoryEvent(kind="action", text="林夏拿起信封", prop_change="信封从桌面进入右手"),
            StoryEvent(kind="dialogue", text="林夏克制地确认信息", speaker="林夏", exact_text="我知道了。"),
            StoryEvent(kind="action", text="林夏把信放回桌面", prop_change="信封回到桌面中央"),
        ],
        "global_visual": GlobalVisualRules(
            visual_style="电影写实",
            era_and_region="当代中国城市",
            art_direction="深色木质咖啡厅，现代但不出现品牌标识",
            overall_atmosphere="压抑、克制",
        ),
        "continuity": ContinuityLocks(
            face_anchor="椭圆脸、左眼下泪痣、黑色短发",
            body_anchor="中等身高、肩窄、清瘦",
            costume_anchor="米白风衣，左肩固定水渍",
            accessory_anchor="银色手表始终在左腕",
            wound_and_stain_anchor="左肩水渍大小与颜色不变",
            scene_structure="木桌、空椅、窗和入口位置固定",
            prop_positions="信封仅在桌面中央与林夏右手之间移动",
            key_light_direction="画面左侧窗外冷光，右后方暖色实景灯补光",
            camera_axis="摄影机始终位于桌子南侧，不越过林夏—空椅轴线",
            screen_direction="林夏面向画面左侧空椅，右手由右向左放信",
            spatial_orientation="林夏右、空椅左、窗后、入口左后，前后左右关系固定",
        ),
        "shot_visual": ShotVisualDesign(
            base_content="林夏、窗边木桌、空椅和拆开的信封",
            composition="林夏位于右侧三分线，空椅形成负空间，信封是视觉中心",
            shot_size="中近景",
            lens="50mm",
            camera_angle="平视",
            camera_height="胸部高度",
            depth_of_field="浅景深但信封与面部可读",
            spatial_layers="前景雨滴玻璃，中景林夏与木桌，背景入口虚化",
        ),
        "color": ColorDesign(
            primary_color="冷蓝灰",
            secondary_color="深棕",
            accent_color="暖琥珀",
            color_temperature="窗侧4200K、实景灯3000K",
            start_state="低照度冷蓝灰，面部保留暖色轮廓",
            change_reason="林夏身体轻微前倾使暖色轮廓光覆盖面部",
            peak_state="对白时眼部高光清晰，背景仍低照度",
            end_state="暖色轮廓减弱，信封落入冷色桌面区域",
        ),
        "dynamics": DynamicsDesign(
            subject_direction="右手由下向上，再向左下方桌面移动",
            subject_trajectory="自然短弧线",
            force_source="林夏手臂主动发力与信封重力",
            speed_curve="缓起—短暂停顿—缓慢下落—停止",
            center_of_gravity="上身轻微前倾后回到椅背",
            visual_flow="从信封移动到林夏眼神，再回到桌面信封",
            secondary_motion="湿发末端和风衣袖口轻微跟随",
            inertia_and_follow_through="信封落桌后边缘轻颤一次，手指自然松开",
            motion_blur="仅手部下落阶段允许轻微模糊",
            stable_regions="面部、泪痣、手表和桌面结构清晰",
        ),
        "camera": CameraDesign(
            movement_type="极慢推近",
            start_position="桌子南侧、距林夏2.5米、胸部高度",
            end_position="同轴线侧、距林夏1.8米、胸部高度",
            path="沿光轴直线前移",
            direction="由南向北",
            speed_curve="缓入—对白时近乎停住—缓出",
            subject_following="锁定林夏双眼与信封之间的视觉关系",
            composition_change="从中景过渡到中近景，空椅始终保留在左侧",
            focus_change="先对焦信封，再平滑跟焦林夏双眼，最后回到信封",
            stability="稳定器，几乎无手持抖动",
            forbidden_behaviors="禁止旋转、突然推近、越轴和随机变焦",
        ),
        "transitions": TransitionDesign(
            entry=TransitionEdge(
                adjacent_shot="S03-06", transition_type="声音先行硬切",
                visual_handoff="承接上一镜信封特写的纸张方向",
                audio_handoff="雨声提前0.2秒进入", duration_seconds=0.2,
                included_in_shot_duration=True,
            ),
            internal_linkage="右手动作、视线、信封位置、雨声和推镜速度连续",
            exit=TransitionEdge(
                adjacent_shot="S03-08", transition_type="视线匹配硬切",
                visual_handoff="以林夏看向空椅的视线交给下一镜",
                audio_handoff="保留雨声尾音", duration_seconds=0,
            ),
        ),
    }
    values.update(updates)
    return StoryboardDirectorRequest(**values)


class StoryboardDirectorTests(unittest.TestCase):
    def setUp(self):
        self.compiler = StoryboardDirectorCompiler()

    def test_compiles_all_director_deliverables_without_filler_beats(self):
        result = self.compiler.compile(_request())

        self.assertTrue(result.submission_ready)
        self.assertEqual(len(result.beats), 3)
        self.assertEqual(len(result.still_prompts), 3)
        self.assertEqual(len(result.video_segments), 2)
        self.assertEqual((result.grid_pages[0].used_slots, result.grid_pages[0].empty_slots), (3, 6))
        self.assertEqual(result.beats[0].start_seconds, 0)
        self.assertEqual(result.beats[-1].end_seconds, 9)
        self.assertEqual(result.beats[0].end_seconds, result.beats[1].start_seconds)
        self.assertEqual(result.beats[0].end_state, result.beats[1].start_state)
        self.assertNotIn("3×3", result.still_prompts[0].prompt)
        self.assertIn("3×3", result.grid_pages[0].composite_prompt)
        self.assertIn("纯留白", result.grid_pages[0].composite_prompt)

    def test_more_than_nine_real_events_are_paginated(self):
        events = [StoryEvent(text=f"角色完成可见动作{i}") for i in range(1, 11)]
        result = self.compiler.compile(_request(events=events, duration_seconds=20))

        self.assertEqual(len(result.beats), 10)
        self.assertEqual(len(result.grid_pages), 2)
        self.assertEqual((result.grid_pages[0].used_slots, result.grid_pages[0].empty_slots), (9, 0))
        self.assertEqual((result.grid_pages[1].used_slots, result.grid_pages[1].empty_slots), (1, 8))
        self.assertEqual(len(result.video_segments), 9)

    def test_fallback_parser_ignores_metadata_but_preserves_real_repeated_events(self):
        result = self.compiler.compile(_request(
            events=[],
            timed_dialogue=[],
            script_text=(
                "场景1：咖啡厅 - 夜晚\n时间：午夜\n地点：窗边\n"
                "林夏敲门。\n林夏敲门。\n林夏：谁在那里？"
            ),
        ))

        self.assertEqual(len(result.beats), 3)
        self.assertEqual(result.beats[0].core_event, "林夏敲门。")
        self.assertEqual(result.beats[1].core_event, "林夏敲门。")
        self.assertEqual(result.beats[2].verbatim_line, "林夏：谁在那里？")

    def test_prompts_lock_camera_color_motion_sound_and_verbatim_dialogue(self):
        result = self.compiler.compile(_request())
        still = result.still_prompts[1].prompt
        video = result.video_segments[0].prompt

        for label in ("当前帧核心画面", "角色与表演", "空间与道具", "画面动势", "构图与摄影", "光影与色调", "连续性锁定"):
            self.assertIn(label, still)
        for label in ("起始状态", "结束状态", "主体运动", "次级运动", "摄影机运动", "色调变化", "声音与台词", "强制连续性"):
            self.assertIn(label, video)
        self.assertIn("我知道了。", still)
        self.assertIn("我知道了。", video)

    def test_rejects_dialogue_outside_shot_duration(self):
        with self.assertRaises(ValidationError):
            _request(timed_dialogue=[TimedDialogue(
                kind="dialogue", speaker="林夏", exact_text="我知道了。",
                start_seconds=8, end_seconds=10,
            )])

        with self.assertRaises(ValidationError):
            _request(duration_seconds=9.0004)

    def test_authenticated_api_exposes_the_complete_director_plan(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
        try:
            response = TestClient(app).post(
                "/api/production/storyboard-director/compile",
                json=_request().model_dump(mode="json"),
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["schema_version"], "storyboard-director.v1")
        self.assertEqual(len(body["grid_pages"][0]["cells"]), 9)
        self.assertEqual(body["grid_pages"][0]["empty_slots"], 6)


if __name__ == "__main__":
    unittest.main()
