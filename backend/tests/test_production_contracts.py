import unittest

from pydantic import ValidationError

from app.schema.production import (
    CharacterAsset,
    FiveView,
    H3VideoRequest,
    NineGridStoryboard,
    StoryAssetCatalog,
    StoryboardPanel,
)


def _panel(index: int) -> StoryboardPanel:
    return StoryboardPanel(
        index=index,
        characters=["林夏"],
        shot_size="中景",
        camera_angle="平视",
        camera_movement="缓慢推近",
        camera_reason="让观众从空间信息进入人物克制情绪",
        lens_mm=50,
        aperture="T2.8",
        composition="林夏位于右侧三分线，信封在前景，空椅保留负空间",
        action_axis="沿木桌南北轴，人物不越轴",
        eyeline="林夏先看信封，再看空椅，视线高度连续",
        subject_action=f"角色完成第 {index} 个可见动作",
        expression="眉心轻收，呼吸逐渐变慢",
        scene="客厅",
        props=["信封"],
        effects=["窗外雨丝"],
        sound="雨声",
        lighting="西侧暖色台灯为主光，窗外冷色雨夜为辅光",
        edit_in="承接上一格动作或以空间建立切入",
        edit_out="在视线或动作完成点切出",
        generation_mode="first_last_frame",
        continuity_in="承接上一格动作方向" if index > 1 else "建立空间",
        continuity_out="保持人物朝向和信封位置",
    )


class ProductionContractTests(unittest.TestCase):
    def test_character_requires_exact_ordered_five_views(self):
        character = CharacterAsset(
            name="林夏",
            identity_dna="椭圆脸、左眼下泪痣、低马尾、米白风衣",
            views=[
                FiveView(view="front", image_url="https://cdn.example/front.png"),
                FiveView(view="front_three_quarter", image_url="https://cdn.example/front-3q.png"),
                FiveView(view="profile", image_url="https://cdn.example/profile.png"),
                FiveView(view="rear_three_quarter", image_url="https://cdn.example/rear-3q.png"),
                FiveView(view="back", image_url="https://cdn.example/back.png"),
            ],
        )
        self.assertEqual([v.view for v in character.views], [
            "front", "front_three_quarter", "profile", "rear_three_quarter", "back"
        ])

        with self.assertRaises(ValidationError):
            CharacterAsset(
                name="林夏",
                identity_dna="固定身份",
                views=character.views[:3],
            )

    def test_story_assets_require_all_four_categories(self):
        with self.assertRaises(ValidationError):
            StoryAssetCatalog(characters=[], scenes=["客厅"], props=["信封"], effects=["雨丝"])

    def test_storyboard_is_exact_three_by_three_and_has_nine_unique_panels(self):
        board = NineGridStoryboard(
            title="雨夜来信",
            assets=StoryAssetCatalog(
                characters=["林夏"], scenes=["客厅"], props=["信封"], effects=["雨丝"]
            ),
            panels=[_panel(i) for i in range(1, 10)],
        )
        self.assertEqual((board.rows, board.columns), (3, 3))
        dumped = board.panels[0].model_dump()
        for field in [
            "characters", "camera_reason", "lens_mm", "aperture", "composition",
            "action_axis", "eyeline", "lighting", "edit_in", "edit_out", "generation_mode",
        ]:
            self.assertIn(field, dumped)

        with self.assertRaises(ValidationError):
            NineGridStoryboard(
                title="错误分镜",
                assets=board.assets,
                panels=[_panel(i) for i in range(1, 9)],
            )

    def test_h3_reference_limits_and_audio_guard(self):
        request = H3VideoRequest(
            prompt="同一人物在同一轴线上转身",
            reference_images=[f"https://cdn.example/{i}.png" for i in range(9)],
            reference_videos=["https://cdn.example/action.mp4"],
            reference_audios=["https://cdn.example/voice.mp3"],
            duration_seconds=8,
        )
        self.assertEqual(request.inferred_mode, "reference")

        with self.assertRaises(ValidationError):
            H3VideoRequest(
                prompt="超限",
                reference_images=[f"https://cdn.example/{i}.png" for i in range(10)],
            )
        with self.assertRaises(ValidationError):
            H3VideoRequest(
                prompt="音频不能单独输入",
                reference_audios=["https://cdn.example/voice.mp3"],
            )

    def test_h3_detects_first_last_frame_mode(self):
        request = H3VideoRequest(
            prompt="从门边走到窗边",
            first_frame="https://cdn.example/first.png",
            last_frame="https://cdn.example/last.png",
            duration_seconds=6,
        )
        self.assertEqual(request.inferred_mode, "first_last_frame")


if __name__ == "__main__":
    unittest.main()
