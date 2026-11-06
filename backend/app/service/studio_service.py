"""Application layer for durable, traceable studio capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
import hashlib
import uuid
from typing import Any

from app import settings
from app.core import bgm_library, media_compositor, studio_canvas
from app.export.delivery import CaptionCue, DeliveryExporter
from app.ingest.parsers import SourceIngestor
from app.repository.studio_repo import ConcurrencyError, StudioRepository
from app.platform.access_audit import record_access_from_thread
from app.platform.permissions import authorize
from app.platform.uploads import MAX_IMAGE_UPLOAD_BYTES, UploadValidationError, validate_image_upload
from app.schema.studio import (
    CANVAS_MAIN_ID,
    ArtifactCreateRequest,
    ArtifactKind,
    AssetReadinessRequest,
    ExportPreviewRequest,
    GenerationJobRequest,
    JobTransitionRequest,
    ProjectCreate,
    AgentKeyCreateRequest,
    CanvasBoardCreate,
    CanvasBoardPatch,
    CanvasPromoteRequest,
    CanvasDuplicateRequest,
    CanvasPutRequest,
    CostEventRequest,
    DirectorWorldPutRequest,
    ReviewCreateRequest,
)
from app.service.project_archive import ProjectArchiveService
from app.service.studio_canvas_runs import CanvasRunner
from app.story.story_graph import StoryGraphBuilder

MAX_CANVAS_VIDEO_BYTES = 200 * 1024 * 1024


class StudioService:
    def __init__(self, repository: StudioRepository | None = None):
        if repository is None:
            configured = os.getenv("STUDIO_DB_PATH", "").strip()
            path = Path(configured).expanduser() if configured else settings.RUNTIME_DIR / "studio.sqlite3"
            repository = StudioRepository(path)
        self.repository = repository
        self.ingestor = SourceIngestor()
        self.graph_builder = StoryGraphBuilder()
        self.exporter = DeliveryExporter()
        self.archive = ProjectArchiveService(repository)
        self.canvas_runs = CanvasRunner(repository)

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
        self, project_id: str, owner_id: str, request: CanvasPutRequest, *, canvas_id: str = CANVAS_MAIN_ID
    ) -> dict[str, Any]:
        return self.repository.put_canvas(project_id, owner_id, request, canvas_id=canvas_id).model_dump(mode="json")

    def get_canvas(self, project_id: str, owner_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        record = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        if not record:
            return {
                "project_id": project_id,
                "version": 0,
                "nodes": [],
                "edges": [],
                "created_at": "",
                "canvas_id": canvas_id,
            }
        return record.model_dump(mode="json")

    def promote_canvas_node(
        self, project_id: str, owner_id: str, request: CanvasPromoteRequest, *, canvas_id: str = CANVAS_MAIN_ID, drama: Any = None, user: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        node = next((item for item in (canvas.nodes if canvas else []) if item.id == request.node_id), None)
        runs = self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id) if node else {}
        # A generated or uploaded result has no artifact until it is committed; committing makes one, then promotes.
        if node is not None and (request.node_id in runs or not node.artifact_id):
            source = studio_canvas.commit_source(node.model_dump(mode="json"), runs[request.node_id].model_dump(mode="json") if request.node_id in runs else None)
            if not source:
                raise ValueError("only artifact-backed nodes can be promoted")
            medium = str((source.get("output") or {}).get("medium") or "")
            if studio_canvas.commit_target_kind(node.model_dump(mode="json"), medium) != request.target_kind.value:
                raise ValueError("promoted node must reference the requested artifact kind")
            outcome = self.commit_canvas_nodes(
                project_id, owner_id, canvas_id=canvas_id, node_ids=[request.node_id], expected_version=request.expected_version, drama=drama, user=user,
            )
            result = outcome["results"][0]
            if result["status"] != "committed":
                raise ValueError(result.get("reason") or "提交失败")
            return outcome["canvas"]
        return self.repository.promote_canvas_node(
            project_id,
            owner_id,
            node_id=request.node_id,
            target_kind=request.target_kind,
            expected_version=request.expected_version,
            canvas_id=canvas_id,
        ).model_dump(mode="json")

    def duplicate_canvas_nodes(
        self, project_id: str, owner_id: str, request: CanvasDuplicateRequest, *, canvas_id: str = CANVAS_MAIN_ID
    ) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
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
        return self.repository.put_canvas(project_id, owner_id, put, canvas_id=canvas_id).model_dump(mode="json")

    def canvas_outline(self, project_id: str, owner_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
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

    # ------------------------------------------------------------------ the node canvas

    def task_canvas_project(self, task_id: str, owner_id: str, title: str) -> dict[str, Any]:
        project = self.repository.project_for_task(task_id, owner_id, title)
        return {
            "project_id": project.id, "task_id": task_id,
            "canvases": [item.model_dump(mode="json") for item in self.repository.list_canvases(project.id, owner_id)],
        }

    def list_canvases(self, project_id: str, owner_id: str) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.repository.list_canvases(project_id, owner_id)]

    def create_canvas(self, project_id: str, owner_id: str, request: CanvasBoardCreate) -> dict[str, Any]:
        return self.repository.create_canvas(project_id, owner_id, request.title).model_dump(mode="json")

    def patch_canvas(self, project_id: str, owner_id: str, canvas_id: str, request: CanvasBoardPatch) -> dict[str, Any]:
        return self.repository.patch_canvas(project_id, owner_id, canvas_id, title=request.title, bookmarks=request.bookmarks).model_dump(mode="json")

    def delete_canvas(self, project_id: str, owner_id: str, canvas_id: str) -> dict[str, Any]:
        self.repository.delete_canvas(project_id, owner_id, canvas_id)
        return {"id": canvas_id, "deleted": True}

    def list_canvas_versions(self, project_id: str, owner_id: str, *, canvas_id: str = CANVAS_MAIN_ID, limit: int = 100) -> dict[str, Any]:
        items = self.repository.list_canvas_versions(project_id, owner_id, canvas_id=canvas_id, limit=limit)
        return {"canvas_id": canvas_id, "versions": [item.model_dump(mode="json") for item in items]}

    def restore_canvas_version(self, project_id: str, owner_id: str, version: int, *, expected_version: int, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        """A restore is a new version with the old content: history only ever grows, and the restore can itself be undone."""
        older = self.repository.get_canvas_version(project_id, owner_id, version, canvas_id=canvas_id)
        if older is None:
            raise ValueError(f"画布没有第 {version} 版（可能已被清理）")
        return self.repository.put_canvas(
            project_id, owner_id, CanvasPutRequest(expected_version=expected_version, nodes=older.nodes, edges=older.edges), canvas_id=canvas_id,
        ).model_dump(mode="json")

    def store_canvas_upload(self, project_id: str, owner_id: str, filename: str, content_type: str, content: bytes) -> dict[str, Any]:
        """Check the bytes, not the claim, then store under a name the server made up."""
        if not self.repository.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        from app.service.director_desk_service import sniff_media

        declared = (content_type or "").split(";", 1)[0].strip().lower()
        if declared.startswith("audio/"):
            try:
                _, suffix = bgm_library.validate_audio_upload(filename, declared, content)
            except bgm_library.BgmUploadError as exc:
                raise ValueError(str(exc)) from exc
            medium, extension = "audio", suffix.lstrip(".")
        else:
            sniffed = sniff_media(content) or ""
            if sniffed.startswith("image/"):
                try:
                    validate_image_upload(filename or f"upload.{sniffed.split('/')[1]}", sniffed, content)
                except UploadValidationError as exc:
                    raise ValueError(str(exc)) from exc
                if len(content) > MAX_IMAGE_UPLOAD_BYTES:
                    raise ValueError(f"图片不能超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB")
                medium, extension = "image", {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[sniffed]
            elif sniffed.startswith("video/"):
                if len(content) > MAX_CANVAS_VIDEO_BYTES:
                    raise ValueError(f"视频不能超过 {MAX_CANVAS_VIDEO_BYTES // (1024 * 1024)} MB")
                medium, extension = "video", "webm" if sniffed.endswith("webm") else "mp4"
            else:
                raise ValueError("只支持图片（PNG、JPEG、WebP）、视频（MP4、WebM）和音频（MP3、WAV、M4A、AAC、OGG）")
        os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
        name = f"canvas_up_{uuid.uuid4().hex}.{extension}"
        with open(os.path.join(media_compositor.MEDIA_DIR, name), "wb") as handle:
            handle.write(content)
        return {
            "medium": medium, "url": media_compositor.public_url(name), "filename": str(filename or "")[:200], "size": len(content),
            "provenance": {"origin": "upload", "filename": str(filename or "")[:200], "sha256": hashlib.sha256(content).hexdigest()},
        }

    def _canvas_task(self, project_id: str, owner_id: str, drama: Any, user: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
        """The drama task behind a canvas, checked against the person asking: running spends that project's money."""
        task_id = self.repository.task_for_project(project_id, owner_id)
        if not task_id or drama is None:
            raise ValueError("这个画布没有关联项目，只能编辑，不能运行或写回")
        task = drama.repo.get_task(task_id)
        if not task:
            raise PermissionError("task not found")
        task_owner = str(task.get("owner_user_id") or "")
        if task_owner != owner_id:
            decision = authorize(user or {}, owner_id=task_owner, write=True)
            if not decision.allowed:
                raise PermissionError("task not owned by actor")
            if decision.cross_account:
                record_access_from_thread(user or {}, resource_id=task_id, owner_id=task_owner, write=True, via="studio.canvas_run")
        return task_id, task

    def canvas_run_options(self, project_id: str, owner_id: str, drama: Any, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _, task = self._canvas_task(project_id, owner_id, drama, user)
        return self.canvas_runs.options(task)

    def canvas_shots(self, project_id: str, owner_id: str, drama: Any, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """The project's scenes and shots, for picking what a previz or a result is about."""
        task_id, task = self._canvas_task(project_id, owner_id, drama, user)
        shots = [
            {"scene_id": str(shot.get("scene_id") or ""), "shot_id": shot.get("shot_id"), "shot_uid": shot.get("shot_uid"), "desc": str(shot.get("desc") or "")[:80]}
            for shot in (task.get("assets") or {}).get("4") or []
            if isinstance(shot, Mapping) and shot.get("scene_id")
        ]
        return {"task_id": task_id, "shots": shots}

    def assess_canvas_run(
        self, project_id: str, owner_id: str, *, canvas_id: str, node_ids: list[str], confirmed: list[dict[str, int]] | None, drama: Any, user: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _, task = self._canvas_task(project_id, owner_id, drama, user)
        return self.canvas_runs.assess(project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, task=task, drama=drama, confirmed=confirmed)

    def start_canvas_run(
        self, project_id: str, owner_id: str, *, canvas_id: str, node_ids: list[str], expected_version: int, operation_id: str, confirm: bool,
        confirmed: list[dict[str, int]] | None, drama: Any, user: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id, task = self._canvas_task(project_id, owner_id, drama, user)
        return self.canvas_runs.start(
            project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, expected_version=expected_version,
            operation_id=operation_id, confirm=confirm, task=task, task_id=task_id, drama=drama, confirmed=confirmed,
        )

    def cancel_canvas_run(self, project_id: str, owner_id: str, batch_id: str, key: str | None) -> dict[str, Any]:
        if not self.repository.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        return self.canvas_runs.cancel(project_id, batch_id, key)

    def canvas_outputs(self, project_id: str, owner_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        """What each node shows and how its last run went; what the canvas polls while something runs."""
        version = self.repository.latest_canvas_version(project_id, owner_id, canvas_id=canvas_id)
        runs = self.repository.list_canvas_runs(project_id, owner_id, canvas_id=canvas_id)
        active = self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id)
        latest: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        for run in runs:
            counts[run.node_id] = counts.get(run.node_id, 0) + 1
            if run.node_id not in latest:
                latest[run.node_id] = {"run_id": run.id, "status": run.status, "error": run.error, "batch_id": run.batch_id}
        return {
            "canvas_id": canvas_id, "version": version,
            "outputs": {node_id: {"run_id": run.id, **(run.output or {})} for node_id, run in active.items() if run.output},
            "latest": latest, "history_counts": counts,
            "running": sum(1 for item in latest.values() if item["status"] in {"queued", "running"}),
        }

    def canvas_node_history(self, project_id: str, owner_id: str, node_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        active = self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id).get(node_id)
        runs = self.repository.list_canvas_runs(project_id, owner_id, canvas_id=canvas_id, node_id=node_id)
        return {"node_id": node_id, "active_run_id": active.id if active else None, "runs": [run.model_dump(mode="json") for run in runs]}

    def restore_canvas_run(self, project_id: str, owner_id: str, node_id: str, run_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        self.repository.restore_canvas_run(project_id, owner_id, canvas_id, node_id, run_id)
        return self.canvas_node_history(project_id, owner_id, node_id, canvas_id=canvas_id)

    def delete_canvas_run(self, project_id: str, owner_id: str, node_id: str, run_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        self.repository.delete_canvas_run(project_id, owner_id, canvas_id, node_id, run_id)
        return self.canvas_node_history(project_id, owner_id, node_id, canvas_id=canvas_id)

    def _optional_task(self, project_id: str, owner_id: str, drama: Any, user: Mapping[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
        if drama is None or not self.repository.task_for_project(project_id, owner_id):
            return None, None
        return self._canvas_task(project_id, owner_id, drama, user)

    def preview_canvas_commit(self, project_id: str, owner_id: str, *, canvas_id: str, node_ids: list[str], drama: Any = None, user: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _, task = self._optional_task(project_id, owner_id, drama, user)
        return self.canvas_runs.preview_commit(project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, task=task)

    def commit_canvas_nodes(
        self, project_id: str, owner_id: str, *, canvas_id: str, node_ids: list[str], expected_version: int, drama: Any = None, user: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id, task = self._optional_task(project_id, owner_id, drama, user)
        return self.canvas_runs.commit(
            project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, node_ids=node_ids, expected_version=expected_version, task=task, task_id=task_id, drama=drama,
        )

    def summarize_canvas(self, project_id: str, owner_id: str, *, canvas_id: str = CANVAS_MAIN_ID) -> dict[str, Any]:
        canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
        runs = {node_id: run.model_dump(mode="json") for node_id, run in self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id).items()}
        document = canvas.model_dump(mode="json") if canvas else {"nodes": [], "edges": []}
        return {
            "canvas_id": canvas_id, "version": canvas.version if canvas else 0,
            "canvases": [{"id": item.id, "title": item.title} for item in self.repository.list_canvases(project_id, owner_id)],
            **studio_canvas.summarize(document, runs),
        }

    def edit_canvas(
        self, project_id: str, owner_id: str, operations: list[Mapping[str, Any]], *, canvas_id: str = CANVAS_MAIN_ID, base_version: int | None = None,
    ) -> dict[str, Any]:
        """A request's operations as one document change: one new version, or nothing at all."""
        with self.repository.canvas_write_lock():
            canvas = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
            latest = canvas.version if canvas else 0
            if base_version is not None and int(base_version) != latest:
                raise ConcurrencyError(f"canvas version conflict: expected {base_version}, latest is {latest}")
            document = canvas.model_dump(mode="json") if canvas else {"nodes": [], "edges": []}
            changed, refs = studio_canvas.apply_operations(document, operations)
            record = self.repository.put_canvas(
                project_id, owner_id, CanvasPutRequest(expected_version=latest, nodes=changed["nodes"], edges=changed["edges"]), canvas_id=canvas_id,
            )
        return {"version": record.version, "created": refs, "node_count": len(record.nodes), "edge_count": len(record.edges)}

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
