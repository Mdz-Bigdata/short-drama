import base64
import io
import unittest
import zipfile

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth_api import get_current_user
from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.core.shot_motion_contract import ShotMotionContract
from app.schema.production import Sd25Asset
from app.schema.script_prompts import (
    ScriptPromptCompileRequest,
    ScriptVideoRouteInput,
    ShotReferenceAssignment,
)
from main import app


SCRIPT = """场景1：咖啡厅内 - 夜晚
林夏（28岁，黑色短发，身穿米白风衣）坐在窗边，右手握着一封信。
【林夏】（克制）我知道了。
林夏把信放在木桌上，看向对面的空椅。
"""


class ScriptPromptPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = ScriptPromptPipeline()

    def _request(self, **updates):
        values = {
            "title": "雨夜来信",
            "script_text": SCRIPT,
            "character_overrides": {
                "林夏": "28岁女性，椭圆脸，左眼下泪痣，黑色短发，米白风衣"
            },
            "exports": ["json"],
        }
        values.update(updates)
        return ScriptPromptCompileRequest(**values)

    def test_full_pipeline_builds_five_view_exact_grids_and_shared_motion_contracts(self):
        result = self.pipeline.compile(self._request())

        self.assertTrue(result.submission_ready)
        self.assertEqual(result.template_sources, [
            "script-to-video-prompts", "sd25-pe", "universal-storyboard-prompt"
        ])
        self.assertEqual(result.characters[0].five_view_order, [
            "front", "front_three_quarter", "profile", "rear_three_quarter", "back"
        ])
        self.assertIn("正面、正面四分之三、标准侧面、背面四分之三、背面", result.characters[0].five_view_prompt)
        self.assertEqual((result.storyboards[0].rows, result.storyboards[0].columns), (3, 3))
        self.assertEqual([panel.index for panel in result.storyboards[0].panels], [1, 2, 3])
        self.assertEqual(result.storyboards[0].empty_slots, 6)
        self.assertEqual(len(result.director_plans[0].beats), 3)
        self.assertEqual(len(result.director_plans[0].video_segments), 2)
        self.assertEqual(len(result.shot_prompts), 3)
        for panel, prompts in zip(result.storyboards[0].panels, result.shot_prompts, strict=True):
            contract = ShotMotionContract.from_panel(panel)
            self.assertEqual(prompts.contract_fingerprint, contract.contract_fingerprint)
            self.assertEqual(
                prompts.director_plan_fingerprint,
                result.director_plans[0].plan_fingerprint,
            )
            self.assertIn(panel.camera_movement, prompts.motion_prompt)
            self.assertIn(panel.subject_action, prompts.storyboard_image_prompt)
            self.assertIn(panel.subject_action, prompts.sd25_prompt)

    def test_identity_facts_are_not_invented_when_script_and_override_are_missing(self):
        result = self.pipeline.compile(ScriptPromptCompileRequest(
            title="未定妆",
            script_text="场景1：房间 - 白天\n【阿青】等等。",
            exports=["json"],
        ))

        self.assertFalse(result.submission_ready)
        self.assertEqual(result.characters[0].identity_status, "needs_review")
        self.assertIn("剧本未提供足够", result.characters[0].identity_dna)
        self.assertTrue(any(issue.code == "missing_identity_dna" for issue in result.consistency.issues))

    def test_ordered_keyframes_and_auto_first_last_route_are_applied_to_one_shot(self):
        assets = [
            Sd25Asset(
                ref=f"@图片{index}", media_type="image", role="keyframe",
                subject=f"关键状态{index}", observations=f"第{index}个可见状态", required=True,
            )
            for index in range(1, 4)
        ]
        assignment = ShotReferenceAssignment(
            scene_number=1,
            panel_index=1,
            assets=assets,
            first_frame_ref="@图片1",
            last_frame_ref="@图片3",
            keyframe_refs=["@图片1", "@图片2", "@图片3"],
            route=ScriptVideoRouteInput(
                model="Seedance 2.5",
                first_frame="https://cdn.example/first.png",
                last_frame="https://cdn.example/last.png",
                exact_end_frame_required=True,
            ),
        )
        result = self.pipeline.compile(self._request(
            reference_assignments=[assignment],
            provider_parameters={"aspect_ratio": "9:16", "duration_seconds": 8},
        ))
        shot = result.shot_prompts[0]

        self.assertEqual(shot.sd25_mode, "generation_keyframes")
        self.assertIn("以@图片1、@图片2、@图片3的顺序作为关键帧", shot.sd25_prompt)
        self.assertEqual(shot.video_reference_plan["mode"], "first_last_frame")
        self.assertNotIn("aspect_ratio", shot.provider_parameters)
        self.assertEqual(shot.provider_parameters["duration_seconds"], 8)

    def test_exports_escape_html_and_harden_spreadsheet_formulas(self):
        malicious_name = '=HYPERLINK("https://evil.example","x")'
        result = self.pipeline.compile(self._request(
            title="<script>alert(1)</script>",
            script_text=(
                "场景1：办公室 - 白天\n"
                f"【{malicious_name}】不要点击。"
            ),
            character_overrides={malicious_name: "28岁女性，黑色短发，灰色西装"},
            exports=["csv", "xlsx", "html", "markdown"],
        ))

        self.assertNotIn("<script>alert(1)</script>", result.exports["html"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result.exports["html"])
        self.assertNotIn("<script>alert(1)</script>", result.exports["markdown"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result.exports["markdown"])
        self.assertIn("'=HYPERLINK", result.exports["csv"])
        xlsx = base64.b64decode(result.exports["xlsx_base64"])
        with zipfile.ZipFile(io.BytesIO(xlsx)) as archive:
            worksheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertNotIn("<f>", worksheet)
        self.assertIn("'=HYPERLINK", worksheet)
        self.assertIn('<dimension ref="A1:X2"/>', worksheet)

    def test_chinese_and_standard_screenplay_syntax_preserve_speakers_and_dialogue(self):
        screenplay = self.pipeline.parse_screenplay(
            "INT. OFFICE - NIGHT\nSARAH\n(quietly)\nI know.\n\n外景：街道 - 清晨\n李娜：走吧。",
            "混合格式",
        )

        self.assertEqual(len(screenplay.scenes), 2)
        self.assertEqual(screenplay.scenes[0].int_ext, "INT")
        self.assertEqual(screenplay.scenes[1].int_ext, "EXT")
        dialogues = [
            (element.speaker, element.content)
            for scene in screenplay.scenes for element in scene.elements
            if element.type == "dialogue"
        ]
        self.assertEqual(dialogues, [("SARAH", "I know."), ("李娜", "走吧。")])

    def test_action_only_character_is_found_without_treating_metadata_as_a_speaker(self):
        screenplay = self.pipeline.parse_screenplay(
            "场景1：屋顶 - 夜晚\n时间：午夜\n动作：风吹动衣角。\n顾言（32岁，男性，黑色短发）站在栏杆前。",
            "无对白角色",
        )

        self.assertEqual(screenplay.all_characters, ["顾言"])
        self.assertFalse(any(
            element.type == "dialogue"
            for scene in screenplay.scenes for element in scene.elements
        ))

    def test_authenticated_file_endpoint_uses_safe_ingestion_and_complete_pipeline(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
        try:
            client = TestClient(app)
            response = client.post(
                "/api/production/script-prompts/compile-file",
                params=[("title", "上传剧本"), ("exports", "json")],
                files={"file": ("scene.md", SCRIPT.encode("utf-8"), "text/markdown")},
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source_format"], "markdown")
        self.assertEqual(len(body["storyboards"][0]["panels"]), 3)
        self.assertEqual(body["storyboards"][0]["empty_slots"], 6)
        self.assertEqual(len(body["shot_prompts"]), 3)

    def test_video_route_rejects_credentialed_or_non_http_media_locators(self):
        for locator in ("file:///tmp/frame.png", "https://user:pass@cdn.example/frame.png"):
            with self.assertRaises(ValidationError):
                ScriptVideoRouteInput(first_frame=locator)


if __name__ == "__main__":
    unittest.main()
