"""Application layer for durable, traceable studio capabilities."""

from __future__ import annotations

import os
from pathlib import Path
import hashlib
from typing import Any

from app.export.delivery import CaptionCue, DeliveryExporter
from app.ingest.parsers import SourceIngestor
from app.repository.studio_repo import ConcurrencyError, StudioRepository
from app.schema.studio import (
    ArtifactCreateRequest,
    ArtifactKind,
    AssetReadinessRequest,
    ExportPreviewRequest,
    GenerationJobRequest,
    JobTransitionRequest,
    ProjectCreate,
    AgentKeyCreateRequest,
    CanvasPromoteRequest,
    CanvasDuplicateRequest,
    CanvasPutRequest,
    CostEventRequest,
    DirectorWorldPutRequest,
    ReviewCreateRequest,
)
from app.service.project_archive import ProjectArchiveService
from app.story.story_graph import StoryGraphBuilder


class StudioService:
    def __init__(self, repository: StudioRepository | None = None):
        if repository is None:
            backend_root = Path(__file__).resolve().parents[2]
            configured = os.getenv("STUDIO_DB_PATH", "").strip()
            path = Path(configured).expanduser() if configured else backend_root / "runtime" / "studio.sqlite3"
            repository = StudioRepository(path)
        self.repository = repository
        self.ingestor = SourceIngestor()
        self.graph_builder = StoryGraphBuilder()
        self.exporter = DeliveryExporter()
        self.archive = ProjectArchiveService(repository)

    def create_project(self, owner_id: str, request: ProjectCreate) -> dict[str, Any]:
        return self.repository.create_project(owner_id, request).model_dump()

    def list_projects(self, owner_id: str) -> list[dict[str, Any]]:
        return [record.model_dump() for record in self.repository.list_projects(owner_id)]

    def ingest_source(self, project_id: str, owner_id: str, filename: str, content: bytes) -> dict[str, Any]:
        document = self.ingestor.ingest(filename, content)
        source_version = self.repository.latest_artifact_version(project_id, owner_id, ArtifactKind.source)
        source_artifact = self.repository.put_artifact(
            project_id, owner_id, ArtifactKind.source, document.model_dump(mode="json"),
            expected_latest_version=source_version, status="review",
        )
        graph = self.graph_builder.build(document)
        graph_version = self.repository.latest_artifact_version(project_id, owner_id, ArtifactKind.story_graph)
        graph_artifact = self.repository.put_artifact(
            project_id, owner_id, ArtifactKind.story_graph, graph.model_dump(mode="json"),
            parents=[source_artifact.id], expected_latest_version=graph_version, status="review",
        )
        return {
            "source": document.model_dump(),
            "source_artifact": source_artifact.model_dump(),
            "story_graph": graph.model_dump(),
            "story_graph_artifact": graph_artifact.model_dump(),
        }

    def put_artifact(
        self, project_id: str, owner_id: str, request: ArtifactCreateRequest
    ) -> dict[str, Any]:
        return self.repository.put_artifact(
            project_id, owner_id, request.kind, request.payload, parents=request.parents,
            expected_latest_version=request.expected_latest_version, status=request.status,
        ).model_dump()

    def list_artifacts(self, project_id: str, owner_id: str) -> list[dict[str, Any]]:
        if not self.repository.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        return [record.model_dump() for record in self.repository.list_artifacts(project_id, owner_id)]

    def create_job(
        self, project_id: str, owner_id: str, request: GenerationJobRequest
    ) -> dict[str, Any]:
        return self.repository.create_job(project_id, owner_id, request).model_dump()

    def get_job(self, job_id: str, owner_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id, owner_id)
        if not job:
            raise PermissionError("job not found or not owned by actor")
        return job.model_dump()

    def list_jobs(self, project_id: str, owner_id: str) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.repository.list_jobs(project_id, owner_id)
        ]

    def cancel_job(self, job_id: str, owner_id: str) -> dict[str, Any]:
        return self.repository.request_job_cancel(job_id, owner_id).model_dump(mode="json")

    def transition_job(
        self, job_id: str, owner_id: str, request: JobTransitionRequest
    ) -> dict[str, Any]:
        return self.repository.transition_job(
            job_id, owner_id, request.status, provider_task_id=request.provider_task_id,
        ).model_dump()

    @staticmethod
    def asset_readiness(request: AssetReadinessRequest) -> dict[str, Any]:
        return request.readiness().model_dump()

    def export_preview(self, request: ExportPreviewRequest) -> dict[str, Any]:
        cues = [CaptionCue.model_validate(caption.model_dump()) for caption in request.captions]
        return {
            "srt": self.exporter.render_srt(cues),
            "ass": self.exporter.render_ass(cues, aspect_ratio=request.aspect_ratio),
            "jianying": self.exporter.render_jianying(
                clips=request.clips, captions=cues, audio=request.audio,
                transitions=request.transitions,
            ),
        }

    def issue_agent_key(
        self, project_id: str, owner_id: str, request: AgentKeyCreateRequest
    ) -> dict[str, Any]:
        # The plaintext token is returned exactly once; only its digest persists.
        return self.repository.issue_agent_key(project_id, owner_id, request).model_dump()

    def revoke_agent_key(self, key_id: str, owner_id: str) -> dict[str, str]:
        self.repository.revoke_agent_key(key_id, owner_id)
        return {"status": "revoked", "key_id": key_id}

    def create_review(
        self, artifact_id: str, owner_id: str, request: ReviewCreateRequest
    ) -> dict[str, Any]:
        return self.repository.create_review(artifact_id, owner_id, request).model_dump(mode="json")

    def list_reviews(self, artifact_id: str, owner_id: str) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.repository.list_reviews(artifact_id, owner_id)
        ]

    def put_canvas(
        self, project_id: str, owner_id: str, request: CanvasPutRequest
    ) -> dict[str, Any]:
        return self.repository.put_canvas(project_id, owner_id, request).model_dump(mode="json")

    def get_canvas(self, project_id: str, owner_id: str) -> dict[str, Any]:
        record = self.repository.get_canvas(project_id, owner_id)
        if not record:
            return {
                "project_id": project_id,
                "version": 0,
                "nodes": [],
                "edges": [],
                "created_at": "",
            }
        return record.model_dump(mode="json")

    def promote_canvas_node(
        self, project_id: str, owner_id: str, request: CanvasPromoteRequest
    ) -> dict[str, Any]:
        return self.repository.promote_canvas_node(
            project_id,
            owner_id,
            node_id=request.node_id,
            target_kind=request.target_kind,
            expected_version=request.expected_version,
        ).model_dump(mode="json")

    def duplicate_canvas_nodes(
        self, project_id: str, owner_id: str, request: CanvasDuplicateRequest
    ) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id)
        if not canvas or canvas.version != request.expected_version:
            latest = canvas.version if canvas else 0
            raise ConcurrencyError(
                f"canvas version conflict: expected {request.expected_version}, latest is {latest}"
            )
        by_id = {node.id: node for node in canvas.nodes}
        missing = [node_id for node_id in request.node_ids if node_id not in by_id]
        if missing:
            raise ValueError(f"canvas nodes do not exist: {', '.join(missing)}")

        def duplicate_id(kind: str, source_id: str) -> str:
            digest = hashlib.sha256(
                f"{request.operation_id}:{kind}:{source_id}".encode("utf-8")
            ).hexdigest()[:24]
            return f"dup:{digest}"

        mapping = {node_id: duplicate_id("node", node_id) for node_id in request.node_ids}
        existing_ids = {node.id for node in canvas.nodes}
        if existing_ids & set(mapping.values()):
            raise ValueError("canvas duplicate operation_id has already been applied")
        duplicates = []
        for source_id in request.node_ids:
            source = by_id[source_id]
            payload = dict(source.payload)
            payload["duplicated_from"] = source.id
            payload["duplicate_operation_id"] = request.operation_id
            duplicates.append(source.model_copy(update={
                "id": mapping[source_id],
                "x": source.x + request.offset_x,
                "y": source.y + request.offset_y,
                "payload": payload,
            }))

        selected = set(request.node_ids)
        duplicate_edges = [
            edge.model_copy(update={
                "id": duplicate_id("edge", edge.id),
                "source": mapping[edge.source],
                "target": mapping[edge.target],
                "payload": {**edge.payload, "duplicated_from": edge.id},
            })
            for edge in canvas.edges
            if edge.source in selected and edge.target in selected
        ]
        put = CanvasPutRequest(
            expected_version=canvas.version,
            nodes=[*canvas.nodes, *duplicates],
            edges=[*canvas.edges, *duplicate_edges],
        )
        return self.repository.put_canvas(project_id, owner_id, put).model_dump(mode="json")

    def canvas_outline(self, project_id: str, owner_id: str) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id)
        if not canvas:
            return {"project_id": project_id, "version": 0, "tracks": {"mainline": [], "freezone": []}}
        tracks: dict[str, list[dict[str, Any]]] = {"mainline": [], "freezone": []}
        for node in sorted(canvas.nodes, key=lambda item: (item.track, item.y, item.x, item.id)):
            tracks[node.track].append({
                "id": node.id,
                "kind": node.kind,
                "artifact_id": node.artifact_id,
                "label": str(node.payload.get("label") or node.payload.get("title") or node.id)[:200],
                "position": {"x": node.x, "y": node.y},
            })
        return {"project_id": project_id, "version": canvas.version, "tracks": tracks}

    def put_director_world(
        self, project_id: str, owner_id: str, request: DirectorWorldPutRequest
    ) -> dict[str, Any]:
        return self.repository.put_director_world(
            project_id, owner_id, request
        ).model_dump(mode="json")

    def get_director_world(self, project_id: str, owner_id: str) -> dict[str, Any]:
        record = self.repository.get_director_world(project_id, owner_id)
        if not record:
            raise ValueError("Director World has not been configured")
        return record.model_dump(mode="json")

    def director_frame_plan(self, project_id: str, owner_id: str) -> dict[str, Any]:
        return self.repository.director_frame_plan(project_id, owner_id).model_dump(mode="json")

    def record_cost(
        self, project_id: str, owner_id: str, request: CostEventRequest
    ) -> dict[str, Any]:
        return self.repository.record_cost(project_id, owner_id, request).model_dump(mode="json")

    def list_costs(self, project_id: str, owner_id: str) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.repository.list_costs(project_id, owner_id)
        ]

    def cost_summary(self, project_id: str, owner_id: str) -> dict[str, Any]:
        return self.repository.cost_summary(project_id, owner_id).model_dump(mode="json")

    def export_project_archive(self, project_id: str, owner_id: str) -> bytes:
        return self.archive.export_project(project_id, owner_id)

    def import_project_archive(
        self, content: bytes, *, owner_id: str, project_name: str
    ) -> dict[str, Any]:
        return self.archive.import_project(
            content, owner_id=owner_id, project_name=project_name
        ).model_dump(mode="json")
