from __future__ import annotations

import re
import unittest

from app.api.production_api import router
from app.api.drama_api import router as drama_router
from app.core.agent_council import AgentCouncilCompiler, CAPABILITIES, KNOWLEDGE_SOURCE_FILES
from app.schema.agent_council import (
    ALL_AGENT_ROLES,
    AgentArtifactEvidence,
    AgentRole,
    CouncilCompileRequest,
    CouncilIssue,
    CouncilReleaseEvidence,
)
from app.service.drama_service import DramaService, dialogue_delivery_profile


class AgentCouncilCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = AgentCouncilCompiler()
        self.request = CouncilCompileRequest(
            title="雨夜归来",
            premise="被误解的女主在证据曝光后完成反击，并在集尾发现更大的幕后操控者。",
            genre="都市复仇悬疑",
            platform="douyin",
            episode_count=12,
            visual_style="冷蓝雨夜写实电影感",
            action_intensity="high",
        )
        self.plan = self.compiler.compile(self.request)

    def test_all_sources_agents_and_capabilities_are_traceable(self) -> None:
        self.assertEqual(len(self.plan.agents), 8)
        self.assertEqual(tuple(agent.role for agent in self.plan.agents), ALL_AGENT_ROLES)
        self.assertEqual(len(self.plan.source_records), len(KNOWLEDGE_SOURCE_FILES))
        self.assertEqual({record.filename for record in self.plan.source_records}, set(KNOWLEDGE_SOURCE_FILES))
        self.assertTrue(all(record.sha256 and record.byte_size > 0 for record in self.plan.source_records))
        self.assertTrue(all(record.capability_ids for record in self.plan.source_records))
        self.assertTrue(all(capability.owners for capability in CAPABILITIES))
        self.assertTrue(all(agent.required_outputs for agent in self.plan.agents))
        self.assertTrue(self.plan.coverage["all_sources_mapped"])
        self.assertTrue(self.plan.coverage["all_capabilities_owned"])

    def test_role_briefs_include_hard_production_contracts(self) -> None:
        prompts = {agent.role: agent.system_prompt for agent in self.plan.agents}
        for role, prompt in prompts.items():
            self.assertIn("严格五视图", prompt, role.value)
            self.assertIn("3×3九宫格", prompt, role.value)
            self.assertIn("首尾帧", prompt, role.value)
            self.assertIn("不支持的输入不得静默丢弃", prompt, role.value)
            self.assertIsNone(re.search(r"\bsk_[A-Za-z0-9]{20,}\b", prompt))
        self.assertIn("语速、情绪、停顿、重音", prompts[AgentRole.AUDIO_DIRECTOR])
        self.assertIn("S/A/B/C", prompts[AgentRole.COMPOSER_PUBLISHER])
        self.assertIn("真实高光", prompts[AgentRole.PR_AGENT])

    def test_platform_and_action_rules_are_adaptive(self) -> None:
        self.assertEqual(self.plan.delivery.aspect_ratio, "9:16")
        self.assertEqual((self.plan.delivery.width, self.plan.delivery.height), (1080, 1920))
        self.assertEqual(self.plan.delivery.fps, 30)
        self.assertEqual(self.plan.constitution.reversal_interval_seconds, (15, 30))
        self.assertIn("action_physics", self.plan.negative_prompt_modules)
        horizontal = self.compiler.compile(self.request.model_copy(update={"platform": "bilibili"}))
        self.assertEqual(horizontal.delivery.aspect_ratio, "16:9")
        self.assertEqual((horizontal.delivery.width, horizontal.delivery.height), (1920, 1080))
        self.assertEqual(horizontal.delivery.fps, 24)
        self.assertEqual(horizontal.constitution.reversal_interval_seconds, (30, 60))

    def _approved_evidence(self) -> CouncilReleaseEvidence:
        artifacts = [
            AgentArtifactEvidence(
                role=agent.role,
                artifact_ids=agent.required_outputs,
                approved=True,
            )
            for agent in self.plan.agents
        ]
        return CouncilReleaseEvidence(
            artifacts=artifacts,
            issues=[CouncilIssue(
                code="cosmetic.minor",
                severity="C",
                owner=AgentRole.VISUAL_DIRECTOR,
                detail="不影响叙事的轻微背景纹理差异",
            )],
            dimension_scores={
                "story": 4.6,
                "character": 4.5,
                "continuity": 4.4,
                "storyboard": 4.5,
                "visual": 4.3,
                "audio": 4.4,
                "delivery": 4.5,
                "compliance": 4.7,
            },
            five_view_order=["front", "front_three_quarter", "profile", "rear_three_quarter", "back"],
            storyboard_rows=3,
            storyboard_columns=3,
            storyboard_panel_count=9,
            storyboard_motion_fingerprints_match=True,
            video_route_accepted=True,
            dialogue_timing_approved=True,
            audio_mix_approved=True,
            final_media_present=True,
            subtitles_approved=True,
            rights_and_provenance_approved=True,
            platform_compliance_approved=True,
            human_final_review=True,
        )

    def test_release_gate_accepts_only_complete_approved_evidence(self) -> None:
        report = self.compiler.evaluate_release(self._approved_evidence())
        self.assertTrue(report.releasable)
        self.assertGreaterEqual(report.total_score, 85)
        self.assertEqual(report.severity_counts["C"], 1)
        self.assertFalse(report.blocking_codes)

    def test_release_gate_fails_closed_on_structural_or_severity_failure(self) -> None:
        evidence = self._approved_evidence().model_copy(update={
            "five_view_order": ["front", "profile", "front_three_quarter", "rear_three_quarter", "back"],
            "storyboard_motion_fingerprints_match": False,
            "unsupported_references_dropped": True,
            "issues": [CouncilIssue(
                code="identity.face_changed",
                severity="S",
                owner=AgentRole.CHARACTER_DESIGNER,
                detail="主角身份漂移",
            )],
        })
        report = self.compiler.evaluate_release(evidence)
        self.assertFalse(report.releasable)
        self.assertIn("character.five_view_order", report.blocking_codes)
        self.assertIn("storyboard.motion_fingerprint", report.blocking_codes)
        self.assertIn("video.route_accepted", report.blocking_codes)
        self.assertIn("issues.no_unresolved_s", report.blocking_codes)

    def test_dialogue_direction_keeps_verbatim_text_and_checks_short_line(self) -> None:
        profile = dialogue_delivery_profile("你终于回来了", "sad")
        self.assertEqual(profile["verbatim_text"], "你终于回来了")
        self.assertEqual(profile["characters_per_minute"], 210)
        self.assertTrue(profile["max_15_han_characters_passed"])
        self.assertIn("呼气", profile["breath"])

    def test_agent_council_routes_are_registered(self) -> None:
        paths = {route.path for route in router.routes}
        self.assertIn("/api/production/agent-council/capabilities", paths)
        self.assertIn("/api/production/agent-council/compile", paths)
        self.assertIn("/api/production/agent-council/release-gate", paths)
        self.assertIn(
            "/api/drama/{task_id}/quality/council",
            {route.path for route in drama_router.routes},
        )

    def test_task_completes_only_after_video_and_council_gates(self) -> None:
        class Repo:
            task = {
                "status": "awaiting_council_review",
                "assets": {"7": {"quality_gate": {"passed": True}}, "8": {}},
            }

            def get_task(self, task_id: str):
                return self.task if task_id == "task-1" else None

            def save_task(self, task_id: str, task: dict) -> None:
                self.task = task

        service = DramaService.__new__(DramaService)
        service.repo = Repo()
        service.agent_council = self.compiler
        result = service.submit_council_release("task-1", self._approved_evidence())
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["assets"]["8"]["council_release_gate"]["releasable"])


if __name__ == "__main__":
    unittest.main()
