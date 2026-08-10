import io
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from app.repository.studio_repo import ConcurrencyError, StudioRepository
from app.schema.studio import (
    ArtifactKind,
    CanvasEdge,
    CanvasNode,
    CanvasPutRequest,
    CostEventRequest,
    DirectorWorldPutRequest,
    GenerationJobRequest,
    ProjectCreate,
    ReviewCreateRequest,
    SpatialActor,
    SpatialAnchor,
    SpatialCamera,
    Vec3,
)
from app.service.project_archive import ProjectArchiveError, ProjectArchiveService


class WorkbenchRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.project = self.repo.create_project("owner-1", ProjectCreate(name="雨夜来信"))
        self.script = self.repo.put_artifact(
            self.project.id,
            "owner-1",
            ArtifactKind.script,
            {"text": "林夏推门进来。"},
            expected_latest_version=0,
            status="review",
        )

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def test_review_history_is_append_only_and_stale_artifacts_cannot_be_approved(self):
        review = self.repo.create_review(
            self.script.id,
            "owner-1",
            ReviewCreateRequest(
                decision="request_changes",
                comment="对白缺少停顿和潜台词。",
                checks={"source_traceable": True, "emotion_rhythm": False},
            ),
        )
        approved = self.repo.create_review(
            self.script.id,
            "owner-1",
            ReviewCreateRequest(
                decision="approve",
                comment="已补足情绪节奏。",
                checks={"source_traceable": True, "emotion_rhythm": True},
            ),
        )
        self.assertNotEqual(review.id, approved.id)
        self.assertEqual(
            [item.decision for item in self.repo.list_reviews(self.script.id, "owner-1")],
            ["request_changes", "approve"],
        )
        self.assertEqual(self.repo.get_artifact(self.script.id, "owner-1").status, "approved")

        board = self.repo.put_artifact(
            self.project.id,
            "owner-1",
            ArtifactKind.storyboard,
            {"panels": 9},
            parents=[self.script.id],
            expected_latest_version=0,
            status="review",
        )
        self.repo.put_artifact(
            self.project.id,
            "owner-1",
            ArtifactKind.script,
            {"text": "新版本"},
            expected_latest_version=1,
        )
        with self.assertRaises(ValueError):
            self.repo.create_review(
                board.id,
                "owner-1",
                ReviewCreateRequest(decision="approve", comment="不能批准过期分镜"),
            )

    def test_dual_track_canvas_promotion_is_versioned(self):
        canvas = self.repo.put_canvas(
            self.project.id,
            "owner-1",
            CanvasPutRequest(
                expected_version=0,
                nodes=[
                    CanvasNode(
                        id="candidate-1",
                        kind="candidate",
                        track="freezone",
                        x=120,
                        y=80,
                        width=320,
                        height=180,
                        artifact_id=self.script.id,
                        payload={"label": "对白候选 B"},
                    ),
                    CanvasNode(
                        id="main-1",
                        kind="artifact",
                        track="mainline",
                        x=0,
                        y=0,
                        width=320,
                        height=180,
                        artifact_id=self.script.id,
                    ),
                ],
                edges=[CanvasEdge(id="compare-1", source="main-1", target="candidate-1", kind="variant")],
            ),
        )
        self.assertEqual(canvas.version, 1)
        promoted = self.repo.promote_canvas_node(
            self.project.id,
            "owner-1",
            node_id="candidate-1",
            target_kind=ArtifactKind.script,
            expected_version=1,
        )
        self.assertEqual(promoted.version, 2)
        self.assertEqual(
            next(node.track for node in promoted.nodes if node.id == "candidate-1"),
            "mainline",
        )
        with self.assertRaises(ConcurrencyError):
            self.repo.promote_canvas_node(
                self.project.id,
                "owner-1",
                node_id="candidate-1",
                target_kind=ArtifactKind.script,
                expected_version=1,
            )

    def test_director_world_validates_references_and_builds_deterministic_frame_plan(self):
        world = self.repo.put_director_world(
            self.project.id,
            "owner-1",
            DirectorWorldPutRequest(
                expected_version=0,
                unit="meter",
                anchors=[
                    SpatialAnchor(id="door", label="南门", position=Vec3(x=0, y=0, z=0)),
                    SpatialAnchor(id="window", label="北窗", position=Vec3(x=0, y=5, z=0)),
                ],
                actors=[
                    SpatialActor(
                        actor_id="linxia",
                        anchor_id="door",
                        offset=Vec3(x=0.2, y=0, z=0),
                        gaze_anchor_id="window",
                        continuity_state={"right_hand": "holds-envelope"},
                    )
                ],
                cameras=[
                    SpatialCamera(
                        id="cam-b",
                        order=2,
                        anchor_id="window",
                        position=Vec3(x=1, y=4, z=1.6),
                        target=Vec3(x=0, y=1, z=1.5),
                        focal_length_mm=50,
                        focus_distance_m=3.2,
                        axis="南北轴",
                    ),
                    SpatialCamera(
                        id="cam-a",
                        order=1,
                        anchor_id="door",
                        position=Vec3(x=1, y=-2, z=1.6),
                        target=Vec3(x=0, y=0, z=1.5),
                        focal_length_mm=35,
                        focus_distance_m=2.1,
                        axis="南北轴",
                    ),
                ],
                continuity_state={"screen_direction": "left-to-right"},
            ),
        )
        self.assertEqual(world.version, 1)
        plan = self.repo.director_frame_plan(self.project.id, "owner-1")
        self.assertEqual([frame.camera_id for frame in plan.frames], ["cam-a", "cam-b"])
        self.assertEqual(plan.frames[0].actors[0].actor_id, "linxia")

    def test_cost_ledger_is_idempotent_and_never_mixes_currencies(self):
        estimate = CostEventRequest(
            idempotency_key="shot-1-estimate-v1",
            phase="estimated",
            provider="minimax_h3",
            operation="video_generation",
            amount=Decimal("1.25"),
            currency="CNY",
            episode_id="ep-1",
            shot_id="shot-1",
        )
        first = self.repo.record_cost(self.project.id, "owner-1", estimate)
        second = self.repo.record_cost(self.project.id, "owner-1", estimate)
        self.assertEqual(first.id, second.id)
        self.repo.record_cost(
            self.project.id,
            "owner-1",
            CostEventRequest(
                idempotency_key="shot-1-actual-v1",
                phase="actual",
                provider="elevenlabs",
                operation="dialogue",
                amount=Decimal("0.40"),
                currency="USD",
                episode_id="ep-1",
                shot_id="shot-1",
            ),
        )
        summary = self.repo.cost_summary(self.project.id, "owner-1")
        self.assertEqual({row.currency for row in summary.currencies}, {"CNY", "USD"})
        self.assertEqual(
            next(row.estimated for row in summary.currencies if row.currency == "CNY"),
            Decimal("1.25"),
        )

    def test_job_lease_recovers_without_losing_provider_task_id_or_resubmitting(self):
        job = self.repo.create_job(
            self.project.id,
            "owner-1",
            GenerationJobRequest(
                provider="minimax_h3",
                operation="video_generation",
                idempotency_key="lease-shot-1",
                descriptor={"mode": "first_last_frame"},
                budget_units=10,
                max_attempts=2,
            ),
        )
        acquired = self.repo.acquire_next_job("worker-a", lease_seconds=30)
        self.assertEqual(acquired.id, job.id)
        self.assertEqual(acquired.lease_owner, "worker-a")
        polled = self.repo.set_provider_task_id(job.id, "worker-a", "remote-task-9")
        self.assertEqual(polled.provider_task_id, "remote-task-9")
        self.repo.append_job_log(job.id, "worker-a", "provider task accepted")
        recovered = self.repo.recover_expired_jobs(now_iso="9999-01-01T00:00:00+00:00")
        self.assertEqual(recovered, 1)
        queued = self.repo.get_job(job.id, "owner-1")
        self.assertEqual(queued.status, "queued")
        self.assertEqual(queued.provider_task_id, "remote-task-9")
        self.assertTrue(queued.logs)

    def test_job_idempotency_key_locks_provider_operation_and_budget(self):
        original = GenerationJobRequest(
            provider="minimax_h3",
            operation="video_generation",
            idempotency_key="immutable-paid-request",
            descriptor={"prompt_hash": "abc"},
            budget_units=10,
            max_attempts=2,
        )
        self.repo.create_job(self.project.id, "owner-1", original)
        with self.assertRaises(ValueError):
            self.repo.create_job(
                self.project.id,
                "owner-1",
                original.model_copy(update={"budget_units": 99}),
            )
        with self.assertRaises(ValueError):
            self.repo.create_job(
                self.project.id,
                "owner-1",
                original.model_copy(update={"provider": "elevenlabs"}),
            )

    def test_archive_round_trip_preserves_workbench_data_under_new_identity(self):
        self.repo.create_review(
            self.script.id,
            "owner-1",
            ReviewCreateRequest(decision="approve", comment="通过"),
        )
        self.repo.record_cost(
            self.project.id,
            "owner-1",
            CostEventRequest(
                idempotency_key="archive-cost-1",
                phase="actual",
                provider="local",
                operation="render",
                amount=Decimal("2.00"),
                currency="CNY",
            ),
        )
        archive = ProjectArchiveService(self.repo).export_project(self.project.id, "owner-1")
        imported = ProjectArchiveService(self.repo).import_project(
            archive,
            owner_id="owner-2",
            project_name="雨夜来信（导入）",
        )
        self.assertNotEqual(imported.id, self.project.id)
        self.assertEqual(imported.owner_id, "owner-2")
        imported_artifacts = self.repo.list_artifacts(imported.id, "owner-2")
        self.assertEqual(len(imported_artifacts), 1)
        self.assertEqual(
            len(self.repo.list_reviews(imported_artifacts[0].id, "owner-2")),
            1,
        )
        self.assertEqual(
            self.repo.cost_summary(imported.id, "owner-2").currencies[0].actual,
            Decimal("2.00"),
        )

    def test_archive_rejects_tampering_and_undeclared_entries_before_writing(self):
        service = ProjectArchiveService(self.repo)
        original = service.export_project(self.project.id, "owner-1")
        with zipfile.ZipFile(io.BytesIO(original), "r") as source:
            manifest = source.read("manifest.json")
            payload = json.loads(source.read("project.json"))
        payload["project"]["name"] = "被篡改"
        tampered = io.BytesIO()
        with zipfile.ZipFile(tampered, "w") as target:
            target.writestr("manifest.json", manifest)
            target.writestr("project.json", json.dumps(payload).encode())
        before = len(self.repo.list_projects("owner-2"))
        with self.assertRaises(ProjectArchiveError):
            service.import_project(
                tampered.getvalue(), owner_id="owner-2", project_name="不应写入"
            )
        self.assertEqual(len(self.repo.list_projects("owner-2")), before)

        undeclared = io.BytesIO()
        with zipfile.ZipFile(undeclared, "w") as target:
            target.writestr("manifest.json", manifest)
            target.writestr("project.json", b"{}")
            target.writestr("../escape.txt", b"unsafe")
        with self.assertRaises(ProjectArchiveError):
            service.import_project(
                undeclared.getvalue(), owner_id="owner-2", project_name="不应写入"
            )


class WorkbenchApiContractTests(unittest.TestCase):
    def test_workbench_routes_are_registered(self):
        from app.api.studio_api import router

        paths = {route.path for route in router.routes}
        self.assertTrue(
            {
                "/api/studio/artifacts/{artifact_id}/reviews",
                "/api/studio/projects/{project_id}/canvas",
                "/api/studio/projects/{project_id}/canvas/promote",
                "/api/studio/projects/{project_id}/director-world",
                "/api/studio/projects/{project_id}/director-world/frame-plan",
                "/api/studio/projects/{project_id}/costs",
                "/api/studio/projects/{project_id}/costs/summary",
                "/api/studio/projects/{project_id}/archive",
                "/api/studio/import",
            }.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
