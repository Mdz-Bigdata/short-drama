import unittest

from pydantic import ValidationError

from app.schema.production import (
    CharacterAsset,
    FiveView,
    H3VideoRequest,
    H3ReferenceBinding,
    NineGridStoryboard,
    StoryAssetCatalog,
    StoryboardPanel,
)
from app.schema.minimax_audio import (
    MiniMaxMusicCoverRequest,
    MiniMaxMusicRequest,
    MiniMaxTTSRequest,
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
    def test_minimax_audio_contracts_cover_every_speech_model_and_music_mode(self):
        speech_models = (
            "speech-2.8-hd", "speech-2.8-turbo",
            "speech-2.6-hd", "speech-2.6-turbo",
            "speech-02-hd", "speech-02-turbo",
            "speech-01-hd", "speech-01-turbo",
        )
        for model in speech_models:
            with self.subTest(model=model):
                request = MiniMaxTTSRequest(
                    model=model,
                    text="同一角色使用稳定音色完成短剧配音。",
                    voice_id="male-qn-qingse",
                )
                self.assertEqual(request.model, model)

        music = MiniMaxMusicRequest(
            prompt="Mandopop, Festive, Upbeat",
            lyrics_optimizer=True,
        )
        self.assertEqual(music.model, "music-3.0")
        cover = MiniMaxMusicCoverRequest(
            audio_url="https://cdn.example/reference.mp3",
            prompt="爵士风格，慵懒深夜酒吧，萨克斯",
        )
        self.assertEqual(cover.model, "music-cover")

        with self.assertRaises(ValidationError):
            MiniMaxMusicRequest(prompt="没有歌词策略的歌曲")
        with self.assertRaises(ValidationError):
            MiniMaxMusicCoverRequest(
                audio_url="http://127.0.0.1/private.mp3",
                prompt="爵士风格，慵懒深夜酒吧，萨克斯",
            )

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

    def test_storyboard_is_exact_three_by_three_and_leaves_unused_slots_blank(self):
        board = NineGridStoryboard(
            title="雨夜来信",
            assets=StoryAssetCatalog(
                characters=["林夏"], scenes=["客厅"], props=["信封"], effects=["雨丝"]
            ),
            panels=[_panel(i) for i in range(1, 10)],
        )
        self.assertEqual((board.rows, board.columns), (3, 3))
        self.assertEqual(board.empty_slots, 0)
        dumped = board.panels[0].model_dump()
        for field in [
            "characters", "camera_reason", "lens_mm", "aperture", "composition",
            "action_axis", "eyeline", "lighting", "edit_in", "edit_out", "generation_mode",
        ]:
            self.assertIn(field, dumped)

        partial = NineGridStoryboard(
            title="三拍九宫格",
            assets=board.assets,
            panels=[_panel(i) for i in range(1, 4)],
        )
        self.assertEqual(partial.empty_slots, 6)

        with self.assertRaises(ValidationError):
            NineGridStoryboard(
                title="错误分镜",
                assets=board.assets,
                panels=[_panel(1), _panel(3)],
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

    def test_h3_accepts_bounded_inline_tail_frames_but_rejects_unsafe_media(self):
        request = H3VideoRequest(
            prompt="以前一段真实尾帧继续动作",
            first_frame="data:image/jpeg;base64,YWJj",
        )
        self.assertEqual(request.inferred_mode, "first_frame")

        for unsafe in (
            "file:///tmp/frame.jpg",
            "data:text/plain;base64,YWJj",
            "https://user:password@cdn.example/frame.jpg",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValidationError):
                H3VideoRequest(prompt="拒绝不安全素材", first_frame=unsafe)

        with self.assertRaises(ValidationError):
            H3VideoRequest(
                prompt="视频引用不能伪装成内联图片",
                reference_videos=["data:image/jpeg;base64,YWJj"],
            )

    def test_h3_structured_references_require_stable_slots_order_hash_and_provenance(self):
        request = H3VideoRequest(
            prompt="锁定角色身份并参考动作与声音节奏",
            reference_bindings=[
                H3ReferenceBinding(
                    slot_id="character-linxia",
                    order=1,
                    media_type="image",
                    uri="https://cdn.example/linxia.png",
                    role="identity",
                    priority=100,
                    content_sha256="a" * 64,
                    provenance="asset:char-linxia:v3",
                ),
                H3ReferenceBinding(
                    slot_id="motion-walk",
                    order=2,
                    media_type="video",
                    uri="https://cdn.example/walk.mp4",
                    role="motion",
                    priority=80,
                    content_sha256="b" * 64,
                    provenance="licensed-reference:walk-01",
                ),
                H3ReferenceBinding(
                    slot_id="voice-rhythm",
                    order=3,
                    media_type="audio",
                    uri="https://cdn.example/voice.wav",
                    role="voice",
                    priority=70,
                    content_sha256="c" * 64,
                    provenance="authorized-voice:linxia:v1",
                ),
            ],
            duration_seconds=8,
        )
        self.assertEqual(request.inferred_mode, "reference")

        with self.assertRaises(ValidationError):
            H3VideoRequest(
                prompt="参考顺序不能含洞",
                reference_bindings=[
                    request.reference_bindings[0],
                    request.reference_bindings[1].model_copy(update={"order": 3}),
                ],
            )


if __name__ == "__main__":
    unittest.main()
