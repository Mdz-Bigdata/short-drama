import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.export.delivery import CaptionCue, DeliveryExporter
from app.ingest.parsers import SourceIngestor, SourceIngestError
from app.repository.studio_repo import ConcurrencyError, StudioRepository
from app.schema.studio import (
    ArtifactKind,
    AssetReadinessRequest,
    CharacterReference,
    EffectReference,
    FiveViewReference,
    GenerationJobRequest,
    ProjectCreate,
    PropReference,
    SceneReference,
)
from app.story.story_graph import StoryGraphBuilder


def _five_views() -> list[FiveViewReference]:
    return [
        FiveViewReference(view="front", uri="https://cdn.example/front.png"),
        FiveViewReference(view="front_three_quarter", uri="https://cdn.example/front-3q.png"),
        FiveViewReference(view="profile", uri="https://cdn.example/profile.png"),
        FiveViewReference(view="rear_three_quarter", uri="https://cdn.example/rear-3q.png"),
        FiveViewReference(view="back", uri="https://cdn.example/back.png"),
    ]


class SourceAndStoryTests(unittest.TestCase):
    def test_ingests_markdown_with_hash_and_traceable_spans(self):
        document = SourceIngestor().ingest(
            "episode.md",
            "# 第一集\n\n场景：雨夜客厅\n\n林夏：我知道了。\n\n她把信封扣在桌上。".encode("utf-8"),
        )
        self.assertEqual(document.format, "markdown")
        self.assertEqual(len(document.sha256), 64)
        self.assertTrue(document.spans)
        self.assertEqual(document.spans[0].source_id, document.id)

        graph = StoryGraphBuilder().build(document)
        self.assertIn("林夏", [character.name for character in graph.characters])
        self.assertIn("雨夜客厅", [scene.name for scene in graph.scenes])
        self.assertTrue(all(event.evidence_span_ids for event in graph.events))

    def test_ingests_fdx_and_rejects_hostile_docx_archive(self):
        fdx = b'<?xml version="1.0"?><FinalDraft><Content><Paragraph Type="Scene Heading"><Text>INT. OFFICE - NIGHT</Text></Paragraph><Paragraph Type="Dialogue"><Text>Stay.</Text></Paragraph></Content></FinalDraft>'
        document = SourceIngestor().ingest("scene.fdx", fdx)
        self.assertEqual(document.format, "fdx")
        self.assertIn("INT. OFFICE - NIGHT", document.text)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.xml", "malicious")
        with self.assertRaises(SourceIngestError):
            SourceIngestor().ingest("hostile.docx", buffer.getvalue())


class DurableStudioRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.project = self.repo.create_project("owner-1", ProjectCreate(name="雨夜来信"))

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def test_versions_are_optimistic_and_downstream_artifacts_become_stale(self):
        script_v1 = self.repo.put_artifact(
            self.project.id, "owner-1", ArtifactKind.script, {"text": "版本一"},
            expected_latest_version=0,
        )
        board = self.repo.put_artifact(
            self.project.id, "owner-1", ArtifactKind.storyboard,
            {"panels": 9}, parents=[script_v1.id], expected_latest_version=0,
        )
        script_v2 = self.repo.put_artifact(
            self.project.id, "owner-1", ArtifactKind.script, {"text": "版本二"},
            expected_latest_version=1,
        )

        self.assertEqual(script_v2.version, 2)
        self.assertTrue(self.repo.get_artifact(board.id, "owner-1").stale)
        with self.assertRaises(ConcurrencyError):
            self.repo.put_artifact(
                self.project.id, "owner-1", ArtifactKind.script, {"text": "冲突"},
                expected_latest_version=1,
            )
        self.assertIsNone(self.repo.get_project(self.project.id, "other-user"))

    def test_generation_jobs_are_idempotent_and_budget_is_reserved_once(self):
        request = GenerationJobRequest(
            provider="minimax_h3",
            operation="video_generation",
            idempotency_key="shot-1-v1",
            descriptor={"prompt_hash": "abc", "mode": "first_last_frame"},
            budget_units=12,
            max_attempts=3,
        )
        first = self.repo.create_job(self.project.id, "owner-1", request)
        second = self.repo.create_job(self.project.id, "owner-1", request)

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.repo.project_reserved_budget(self.project.id, "owner-1"), 12)
        running = self.repo.transition_job(first.id, "owner-1", "running", provider_task_id="remote-1")
        resumed = self.repo.get_job(first.id, "owner-1")
        self.assertEqual(running.provider_task_id, "remote-1")
        self.assertEqual(resumed.provider_task_id, "remote-1")


class AssetAndExportTests(unittest.TestCase):
    def test_asset_readiness_requires_five_views_and_all_four_asset_categories(self):
        ready = AssetReadinessRequest(
            characters=[
                CharacterReference(
                    id="char-1", name="林夏", identity_dna="泪痣、低马尾、米白风衣",
                    approved=True, views=_five_views(),
                )
            ],
            scenes=[
                SceneReference(
                    id="scene-1", name="雨夜客厅", layout="木桌位于中央，窗在北侧",
                    entrances=["南门"], camera_axis="南北轴", light_direction="西侧台灯",
                    time_weather="夜晚、下雨", approved=True,
                )
            ],
            props=[
                PropReference(
                    id="prop-1", name="信封", owner="林夏", states=["密封", "已拆开", "扣在桌上"],
                    approved=True,
                )
            ],
            effects=[
                EffectReference(
                    id="effect-1", name="雨丝", source="窗外", target="玻璃窗",
                    lifecycle=["稀疏", "增强", "保持"], end_state="持续落下", approved=True,
                )
            ],
        )
        self.assertTrue(ready.readiness().ready)

        not_ready = ready.model_copy(update={"effects": []})
        report = not_ready.readiness()
        self.assertFalse(report.ready)
        self.assertIn("effects", report.missing_categories)

    def test_export_generates_srt_ass_and_jianying_timeline(self):
        cues = [
            CaptionCue(start_ms=0, end_ms=1250, text="我知道了。", speaker="林夏"),
            CaptionCue(start_ms=1500, end_ms=3000, text="雨声更近。", speaker="旁白"),
        ]
        exporter = DeliveryExporter()
        srt = exporter.render_srt(cues)
        ass = exporter.render_ass(cues, aspect_ratio="9:16")
        draft = exporter.render_jianying(
            clips=[{"uri": "clip-1.mp4", "duration_ms": 3000}],
            captions=cues,
            audio=[{"uri": "bgm.mp3", "start_ms": 0, "duration_ms": 3000, "kind": "bgm"}],
        )

        self.assertIn("00:00:00,000 --> 00:00:01,250", srt)
        self.assertIn("[Events]", ass)
        payload = json.loads(draft)
        self.assertEqual(payload["format"], "jianying-compatible-draft-v1")
        self.assertEqual(len(payload["tracks"]["captions"]), 2)


class StudioApiContractTests(unittest.TestCase):
    def test_studio_and_sd25_routes_are_registered(self):
        from app.api.production_api import router as production_router
        from app.api.studio_api import router as studio_router

        production_paths = {route.path for route in production_router.routes}
        studio_paths = {route.path for route in studio_router.routes}
        self.assertIn("/api/production/sd25/compile", production_paths)
        self.assertTrue({
            "/api/studio/projects",
            "/api/studio/projects/{project_id}/sources",
            "/api/studio/projects/{project_id}/artifacts",
            "/api/studio/projects/{project_id}/jobs",
            "/api/studio/assets/readiness",
            "/api/studio/exports/preview",
        }.issubset(studio_paths))


if __name__ == "__main__":
    unittest.main()
