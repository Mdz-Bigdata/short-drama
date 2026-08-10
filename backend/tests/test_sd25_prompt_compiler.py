import unittest

from pydantic import ValidationError

from app.core.sd25_compiler import Sd25PromptCompiler
from app.schema.production import (
    Sd25Asset,
    Sd25CompileRequest,
    Sd25DialogueEntry,
    NineGridStoryboard,
    StoryAssetCatalog,
)
from tests.test_production_contracts import _panel


class Sd25PromptCompilerTests(unittest.TestCase):
    def setUp(self):
        self.compiler = Sd25PromptCompiler()

    def test_compiles_multimodal_generation_with_explicit_unused_assets(self):
        request = Sd25CompileRequest(
            goal="林夏在雨夜打开信封，读完后克制地看向空椅。",
            assets=[
                Sd25Asset(
                    ref="@图片1",
                    media_type="image",
                    role="character",
                    subject="林夏",
                    observations="椭圆脸、左眼下泪痣、低马尾、米白风衣",
                    required=True,
                ),
                Sd25Asset(
                    ref="@图片2",
                    media_type="image",
                    role="scene",
                    subject="雨夜客厅",
                    observations="木桌、暖色台灯、窗外雨丝",
                    required=True,
                ),
                Sd25Asset(
                    ref="@视频1",
                    media_type="video",
                    role="camera",
                    subject="镜头运动",
                    observations="从信封插入镜头缓慢推近到人物近景",
                    duration_seconds=6,
                    required=True,
                ),
                Sd25Asset(
                    ref="@图片3",
                    media_type="image",
                    role="style",
                    subject="未采用风格图",
                    observations="高饱和插画风",
                ),
            ],
            dialogue=[
                Sd25DialogueEntry(
                    speaker="林夏",
                    text="我知道了。",
                    language="中文",
                    delivery="克制，句尾发紧，开口前停顿半拍",
                    position="画内",
                )
            ],
        )

        result = self.compiler.compile(request)

        self.assertEqual(result.mode, "generation_reference")
        self.assertIn("@图片1用于林夏", result.prompt)
        self.assertIn("@视频1用于镜头运动", result.prompt)
        self.assertIn("【未采用素材】", result.prompt)
        self.assertIn("@图片3未参与本任务", result.prompt)
        self.assertIn("林夏使用中文", result.prompt)
        self.assertIn("{我知道了。}", result.prompt)
        self.assertEqual(result.unused_assets, ["@图片3"])

    def test_first_last_frame_sentences_are_exact_and_generation_parameters_are_separate(self):
        request = Sd25CompileRequest(
            goal="林夏从门边走到窗边，最后转身面对镜头。",
            first_frame_ref="@图片1",
            last_frame_ref="@图片2",
            parameters={"duration_seconds": 8, "aspect_ratio": "9:16", "resolution": "1080p"},
            assets=[
                Sd25Asset(
                    ref="@图片1", media_type="image", role="keyframe", subject="开始状态",
                    observations="林夏站在门边，右手握信封", required=True,
                ),
                Sd25Asset(
                    ref="@图片2", media_type="image", role="keyframe", subject="结束状态",
                    observations="林夏站在窗边，转身面对镜头", required=True,
                ),
            ],
        )

        result = self.compiler.compile(request)

        self.assertEqual(result.mode, "generation_first_last_frame")
        self.assertIn("@图片1作为首帧。", result.prompt)
        self.assertIn("@图片2作为尾帧。", result.prompt)
        self.assertNotIn("9:16", result.prompt)
        self.assertNotIn("1080p", result.prompt)
        self.assertNotIn("8秒", result.prompt)
        self.assertEqual(result.parameters["duration_seconds"], 8)

    def test_edit_and_extension_require_a_single_source_video_and_close_the_scope(self):
        with self.assertRaises(ValidationError):
            Sd25CompileRequest(goal="替换人物", task="edit")

        request = Sd25CompileRequest(
            goal="只把红色自行车替换为深灰色巡逻车。",
            task="edit",
            source_video_ref="@视频1",
            assets=[
                Sd25Asset(
                    ref="@视频1", media_type="video", role="source", subject="编辑母版",
                    observations="公园道路与原始运动轨迹", duration_seconds=8, required=True,
                ),
                Sd25Asset(
                    ref="@图片1", media_type="image", role="prop", subject="深灰色巡逻车",
                    observations="车身结构、颜色和透明挡风板", required=True,
                ),
            ],
        )

        result = self.compiler.compile(request)
        self.assertEqual(result.mode, "edit")
        self.assertIn("@视频1是唯一编辑母版", result.prompt)
        self.assertIn("其他可见人物、道具和背景元素保持原样", result.prompt)

    def test_hard_material_limits_fail_before_provider_submission(self):
        assets = [
            Sd25Asset(
                ref=f"@图片{i}", media_type="image", role="style", subject=f"参考{i}",
                observations="参考", required=True,
            )
            for i in range(1, 32)
        ]
        with self.assertRaises(ValidationError):
            Sd25CompileRequest(goal="超限任务", assets=assets)

    def test_asset_reference_type_duration_and_parameter_bounds_are_fail_closed(self):
        with self.assertRaises(ValidationError):
            Sd25Asset(
                ref="@图片1", media_type="video", role="camera", subject="错误类型",
                observations="不应把图片编号声明成视频", duration_seconds=4,
            )
        with self.assertRaises(ValidationError):
            Sd25Asset(
                ref="@视频1", media_type="video", role="camera", subject="缺失时长",
                observations="缺失的时长无法参与总时长上限校验",
            )
        with self.assertRaises(ValidationError):
            Sd25CompileRequest(
                goal="参数超限",
                parameters={f"parameter_{index}": index for index in range(33)},
            )

    def test_compiles_exact_nine_grid_as_ordered_video_reference(self):
        board = NineGridStoryboard(
            title="雨夜来信",
            assets=StoryAssetCatalog(
                characters=["林夏"], scenes=["雨夜客厅"], props=["信封"], effects=["雨丝"]
            ),
            panels=[_panel(i) for i in range(1, 10)],
        )
        request = Sd25CompileRequest(
            goal="按九宫格生成连续运镜视频。",
            storyboard_ref="@图片1",
            storyboard=board,
            assets=[
                Sd25Asset(
                    ref="@图片1", media_type="image", role="keyframe", subject="九宫格分镜",
                    observations="严格3×3电影分镜", required=True,
                )
            ],
        )
        result = self.compiler.compile(request)
        self.assertEqual(result.mode, "generation_storyboard")
        self.assertIn("按照从左到右、从上到下", result.prompt)
        self.assertIn("镜头9", result.prompt)
        self.assertIn("50mm", result.prompt)
        self.assertIn("不采用图中的线稿画风、文字标注或占位人物", result.prompt)

    def test_compiles_coarse_blockout_as_motion_skeleton(self):
        request = Sd25CompileRequest(
            goal="把白模重渲染为真人雨夜追逐。",
            blockout_ref="@视频1",
            blockout_granularity="coarse",
            assets=[
                Sd25Asset(
                    ref="@视频1", media_type="video", role="action", subject="粗粒度白模",
                    observations="两人追逐路径、站位、机位与切镜", duration_seconds=10, required=True,
                )
            ],
        )
        result = self.compiler.compile(request)
        self.assertEqual(result.mode, "generation_blockout_coarse")
        self.assertIn("粗粒度白模参考", result.prompt)
        self.assertIn("不采用其中的白模外观、材质和场景", result.prompt)
        self.assertIn("轨迹线、坐标轴、控制器、相机锥体和文字标记不进入成片", result.prompt)

    def test_audio_only_edit_preserves_picture_phoneme_timing_and_sync(self):
        request = Sd25CompileRequest(
            goal="只将对白替换成更克制、带半拍停顿的表演。",
            task="edit",
            edit_scope="audio",
            source_video_ref="@视频1",
            assets=[
                Sd25Asset(
                    ref="@视频1", media_type="video", role="source", subject="编辑母版",
                    observations="8秒雨夜对话", duration_seconds=8, required=True,
                ),
                Sd25Asset(
                    ref="@音频1", media_type="audio", role="voice", subject="林夏音色",
                    observations="克制、呼吸发紧", duration_seconds=8, required=True,
                ),
            ],
            dialogue=[
                Sd25DialogueEntry(
                    speaker="林夏", text="我知道了。", delivery="开口前停半拍，句尾收紧",
                    position="画内", audio_ref="@音频1",
                )
            ],
        )
        result = self.compiler.compile(request)
        self.assertIn("画面逐帧保持不变", result.prompt)
        self.assertIn("原始音素时点、口型时点和音画同步", result.prompt)
        self.assertIn("【对白账本】", result.prompt)

    def test_edit_then_extend_is_two_ordered_primary_steps(self):
        request = Sd25CompileRequest(
            goal="先把伞替换成透明伞，再向后延长到林夏走出画面。",
            task="edit_then_extend",
            edit_scope="visual",
            source_video_ref="@视频1",
            extension_direction="after",
            assets=[
                Sd25Asset(
                    ref="@视频1", media_type="video", role="source", subject="原始母版",
                    observations="林夏撑黑伞走近门口", duration_seconds=8, required=True,
                ),
                Sd25Asset(
                    ref="@图片1", media_type="image", role="prop", subject="透明伞",
                    observations="透明伞面和银色伞骨", required=True,
                ),
            ],
        )
        result = self.compiler.compile(request)
        self.assertEqual(result.mode, "edit_then_extend")
        self.assertEqual([step.mode for step in result.steps], ["edit", "extend_after"])
        self.assertIn("第一步输出的视频", result.steps[1].prompt)
        self.assertNotEqual(result.steps[0].prompt, result.steps[1].prompt)

    def test_dialogue_audio_reference_must_be_present(self):
        with self.assertRaises(ValidationError):
            Sd25CompileRequest(
                goal="说一句话",
                dialogue=[
                    Sd25DialogueEntry(
                        speaker="林夏", text="等等。", delivery="急促", audio_ref="@音频1"
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
