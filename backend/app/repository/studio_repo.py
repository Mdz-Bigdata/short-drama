"""Transactional SQLite repository for versioned artifacts and paid jobs.

SQLite usage follows the Python DB-API documentation and every value is bound as
a parameter: https://docs.python.org/3/library/sqlite3.html
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.schema.studio import (
    ArtifactKind,
    ArtifactRecord,
    GenerationJobRecord,
    GenerationJobRequest,
    ProjectCreate,
    ProjectRecord,
    AgentAuthorization,
    AgentKeyCreateRequest,
    AgentKeyRecord,
    CanvasEdge,
    CanvasNode,
    CanvasPutRequest,
    CanvasRecord,
    CostEventRecord,
    CostEventRequest,
    CurrencyCostSummary,
    DirectorFrame,
    DirectorFramePlan,
    DirectorWorldPutRequest,
    DirectorWorldRecord,
    IssuedAgentKey,
    ProjectCostSummary,
    ReviewCreateRequest,
    ReviewRecord,
    utc_now_iso,
)


class ConcurrencyError(RuntimeError):
    pass


class StudioRepository:
    _JOB_TRANSITIONS = {
        "queued": {"running", "cancelled", "failed"},
        "running": {"succeeded", "failed", "cancelled"},
        "succeeded": {"accepted", "rejected"},
        "rejected": {"queued"},
        "failed": {"queued"},
        "cancelled": {"queued"},
        "accepted": set(),
    }

    def __init__(self, path: str | Path):
        db_path = Path(path).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    parents TEXT NOT NULL,
                    stale INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, kind, version)
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id, kind, version);

                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    descriptor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_task_id TEXT,
                    budget_units INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    logs TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_project ON generation_jobs(project_id, status);

                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_keys (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_prefix TEXT NOT NULL,
                    token_digest TEXT NOT NULL UNIQUE,
                    scopes TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_keys_project ON agent_keys(project_id, revoked);

                CREATE TABLE IF NOT EXISTS artifact_reviews (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    checks TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_artifact ON artifact_reviews(artifact_id, created_at);

                CREATE TABLE IF NOT EXISTS canvas_versions (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    nodes TEXT NOT NULL,
                    edges TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, version)
                );

                CREATE TABLE IF NOT EXISTS director_world_versions (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    unit TEXT NOT NULL,
                    anchors TEXT NOT NULL,
                    actors TEXT NOT NULL,
                    cameras TEXT NOT NULL,
                    continuity_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, version)
                );

                CREATE TABLE IF NOT EXISTS cost_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    episode_id TEXT,
                    shot_id TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_cost_project ON cost_events(project_id, currency, phase);
                """
            )
            self._ensure_column("generation_jobs", "lease_owner", "TEXT")
            self._ensure_column("generation_jobs", "lease_expires_at", "TEXT")
            self._ensure_column(
                "generation_jobs", "cancel_requested", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column("generation_jobs", "logs", "TEXT NOT NULL DEFAULT '[]'")

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {
            row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def close(self) -> None:
        self._connection.close()

    def create_project(self, owner_id: str, request: ProjectCreate) -> ProjectRecord:
        now = utc_now_iso()
        record = ProjectRecord(
            id=f"prj_{uuid.uuid4().hex}", owner_id=owner_id,
            name=request.name.strip(), description=request.description.strip(),
            created_at=now, updated_at=now,
        )
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO projects(id, owner_id, name, description, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (record.id, record.owner_id, record.name, record.description, now, now),
            )
            self._audit(record.id, owner_id, "project.created", record.id, {})
        return record

    def get_project(self, project_id: str, owner_id: str) -> ProjectRecord | None:
        row = self._connection.execute(
            "SELECT * FROM projects WHERE id = ? AND owner_id = ?", (project_id, owner_id)
        ).fetchone()
        return ProjectRecord.model_validate(dict(row)) if row else None

    def list_projects(self, owner_id: str) -> list[ProjectRecord]:
        rows = self._connection.execute(
            "SELECT * FROM projects WHERE owner_id = ? ORDER BY updated_at DESC", (owner_id,)
        ).fetchall()
        return [ProjectRecord.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _canonical_payload(payload: dict[str, Any]) -> tuple[str, str]:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def put_artifact(
        self,
        project_id: str,
        owner_id: str,
        kind: ArtifactKind,
        payload: dict[str, Any],
        *,
        parents: list[str] | None = None,
        expected_latest_version: int,
        status: str = "draft",
    ) -> ArtifactRecord:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        parent_ids = list(dict.fromkeys(parents or []))
        encoded, content_hash = self._canonical_payload(payload)
        now = utc_now_iso()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS latest FROM artifacts WHERE project_id = ? AND kind = ?",
                    (project_id, kind.value),
                ).fetchone()
                latest = int(row["latest"])
                if latest != expected_latest_version:
                    raise ConcurrencyError(
                        f"artifact version conflict: expected {expected_latest_version}, latest is {latest}"
                    )
                if parent_ids:
                    placeholders = ",".join("?" for _ in parent_ids)
                    valid = self._connection.execute(
                        f"SELECT id FROM artifacts WHERE project_id = ? AND owner_id = ? AND id IN ({placeholders})",
                        (project_id, owner_id, *parent_ids),
                    ).fetchall()
                    if len(valid) != len(parent_ids):
                        raise ValueError("artifact parent is missing or belongs to another project")
                record = ArtifactRecord(
                    id=f"art_{uuid.uuid4().hex}", project_id=project_id, owner_id=owner_id,
                    kind=kind, version=latest + 1, payload=payload, content_hash=content_hash,
                    parents=parent_ids, stale=False, status=status, created_at=now,
                )
                self._connection.execute(
                    """INSERT INTO artifacts(
                        id, project_id, owner_id, kind, version, payload, content_hash,
                        parents, stale, status, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id, project_id, owner_id, kind.value, record.version, encoded,
                        content_hash, json.dumps(parent_ids), 0, status, now,
                    ),
                )
                if latest:
                    old_rows = self._connection.execute(
                        "SELECT id FROM artifacts WHERE project_id = ? AND kind = ? AND version < ?",
                        (project_id, kind.value, record.version),
                    ).fetchall()
                    self._mark_descendants_stale(project_id, {row["id"] for row in old_rows})
                self._connection.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id)
                )
                self._audit(project_id, owner_id, "artifact.versioned", record.id, {
                    "kind": kind.value, "version": record.version, "content_hash": content_hash,
                })
                self._connection.commit()
                return record
            except Exception:
                self._connection.rollback()
                raise

    def _mark_descendants_stale(self, project_id: str, roots: set[str]) -> None:
        frontier = set(roots)
        seen = set(roots)
        while frontier:
            rows = self._connection.execute(
                "SELECT id, parents FROM artifacts WHERE project_id = ? AND stale = 0", (project_id,)
            ).fetchall()
            descendants = {
                row["id"] for row in rows
                if set(json.loads(row["parents"] or "[]")) & frontier
            }
            descendants -= seen
            if not descendants:
                break
            placeholders = ",".join("?" for _ in descendants)
            self._connection.execute(
                f"UPDATE artifacts SET stale = 1 WHERE id IN ({placeholders})", tuple(descendants)
            )
            seen.update(descendants)
            frontier = descendants

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        data["parents"] = json.loads(data["parents"])
        data["stale"] = bool(data["stale"])
        return ArtifactRecord.model_validate(data)

    def get_artifact(self, artifact_id: str, owner_id: str) -> ArtifactRecord | None:
        row = self._connection.execute(
            "SELECT * FROM artifacts WHERE id = ? AND owner_id = ?", (artifact_id, owner_id)
        ).fetchone()
        return self._artifact_from_row(row) if row else None

    def list_artifacts(self, project_id: str, owner_id: str) -> list[ArtifactRecord]:
        rows = self._connection.execute(
            "SELECT * FROM artifacts WHERE project_id = ? AND owner_id = ? ORDER BY kind, version",
            (project_id, owner_id),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def create_review(
        self, artifact_id: str, reviewer_id: str, request: ReviewCreateRequest
    ) -> ReviewRecord:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT * FROM artifacts WHERE id = ? AND owner_id = ?",
                    (artifact_id, reviewer_id),
                ).fetchone()
                if not row:
                    raise PermissionError("artifact not found or not owned by reviewer")
                artifact = self._artifact_from_row(row)
                if request.decision == "approve" and artifact.stale:
                    raise ValueError("stale artifacts must be regenerated before approval")
                now = utc_now_iso()
                record = ReviewRecord(
                    id=f"rev_{uuid.uuid4().hex}",
                    project_id=artifact.project_id,
                    artifact_id=artifact.id,
                    reviewer_id=reviewer_id,
                    decision=request.decision,
                    comment=request.comment.strip(),
                    checks=request.checks,
                    created_at=now,
                )
                self._connection.execute(
                    """INSERT INTO artifact_reviews(
                        id, project_id, artifact_id, reviewer_id, decision, comment, checks, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id,
                        record.project_id,
                        record.artifact_id,
                        reviewer_id,
                        record.decision,
                        record.comment,
                        json.dumps(record.checks, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                status = {
                    "request_changes": "review",
                    "approve": "approved",
                    "reject": "rejected",
                }[request.decision]
                self._connection.execute(
                    "UPDATE artifacts SET status = ? WHERE id = ?", (status, artifact.id)
                )
                self._audit(
                    artifact.project_id,
                    reviewer_id,
                    f"review.{request.decision}",
                    artifact.id,
                    {"review_id": record.id, "checks": record.checks},
                )
                self._connection.commit()
                return record
            except Exception:
                self._connection.rollback()
                raise

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> ReviewRecord:
        data = dict(row)
        data["checks"] = json.loads(data["checks"])
        return ReviewRecord.model_validate(data)

    def list_reviews(self, artifact_id: str, owner_id: str) -> list[ReviewRecord]:
        artifact = self.get_artifact(artifact_id, owner_id)
        if not artifact:
            raise PermissionError("artifact not found or not owned by actor")
        rows = self._connection.execute(
            "SELECT * FROM artifact_reviews WHERE artifact_id = ? ORDER BY created_at, rowid",
            (artifact_id,),
        ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def put_canvas(
        self, project_id: str, owner_id: str, request: CanvasPutRequest
    ) -> CanvasRecord:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        artifact_ids = {node.artifact_id for node in request.nodes if node.artifact_id}
        if artifact_ids:
            placeholders = ",".join("?" for _ in artifact_ids)
            rows = self._connection.execute(
                f"SELECT id FROM artifacts WHERE project_id = ? AND owner_id = ? AND id IN ({placeholders})",
                (project_id, owner_id, *sorted(artifact_ids)),
            ).fetchall()
            if {row["id"] for row in rows} != artifact_ids:
                raise ValueError("canvas artifact references must belong to the same project")
        now = utc_now_iso()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS latest FROM canvas_versions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                latest = int(row["latest"])
                if latest != request.expected_version:
                    raise ConcurrencyError(
                        f"canvas version conflict: expected {request.expected_version}, latest is {latest}"
                    )
                record = CanvasRecord(
                    project_id=project_id,
                    version=latest + 1,
                    nodes=request.nodes,
                    edges=request.edges,
                    created_at=now,
                )
                self._connection.execute(
                    "INSERT INTO canvas_versions(project_id, version, nodes, edges, created_at) VALUES(?, ?, ?, ?, ?)",
                    (
                        project_id,
                        record.version,
                        json.dumps([node.model_dump(mode="json") for node in record.nodes], ensure_ascii=False, sort_keys=True),
                        json.dumps([edge.model_dump(mode="json") for edge in record.edges], ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                self._audit(project_id, owner_id, "canvas.versioned", project_id, {"version": record.version})
                self._connection.commit()
                return record
            except Exception:
                self._connection.rollback()
                raise

    @staticmethod
    def _canvas_from_row(row: sqlite3.Row) -> CanvasRecord:
        data = dict(row)
        data["nodes"] = [CanvasNode.model_validate(item) for item in json.loads(data["nodes"])]
        data["edges"] = [CanvasEdge.model_validate(item) for item in json.loads(data["edges"])]
        return CanvasRecord.model_validate(data)

    def get_canvas(self, project_id: str, owner_id: str) -> CanvasRecord | None:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        row = self._connection.execute(
            "SELECT * FROM canvas_versions WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return self._canvas_from_row(row) if row else None

    def promote_canvas_node(
        self,
        project_id: str,
        owner_id: str,
        *,
        node_id: str,
        target_kind: ArtifactKind,
        expected_version: int,
    ) -> CanvasRecord:
        canvas = self.get_canvas(project_id, owner_id)
        if not canvas or canvas.version != expected_version:
            latest = canvas.version if canvas else 0
            raise ConcurrencyError(
                f"canvas version conflict: expected {expected_version}, latest is {latest}"
            )
        found = False
        nodes: list[CanvasNode] = []
        for node in canvas.nodes:
            if node.id == node_id:
                found = True
                if not node.artifact_id:
                    raise ValueError("only artifact-backed nodes can be promoted")
                artifact = self.get_artifact(node.artifact_id, owner_id)
                if not artifact or artifact.project_id != project_id or artifact.kind != target_kind:
                    raise ValueError("promoted node must reference the requested artifact kind")
                node = node.model_copy(update={"track": "mainline"})
            nodes.append(node)
        if not found:
            raise ValueError("canvas node not found")
        record = self.put_canvas(
            project_id,
            owner_id,
            CanvasPutRequest(expected_version=expected_version, nodes=nodes, edges=canvas.edges),
        )
        with self._lock, self._connection:
            self._audit(
                project_id,
                owner_id,
                "canvas.promoted",
                node_id,
                {"target_kind": target_kind.value, "version": record.version},
            )
        return record

    def put_director_world(
        self, project_id: str, owner_id: str, request: DirectorWorldPutRequest
    ) -> DirectorWorldRecord:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        now = utc_now_iso()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS latest FROM director_world_versions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                latest = int(row["latest"])
                if latest != request.expected_version:
                    raise ConcurrencyError(
                        f"Director World version conflict: expected {request.expected_version}, latest is {latest}"
                    )
                record = DirectorWorldRecord(
                    project_id=project_id,
                    version=latest + 1,
                    unit=request.unit,
                    anchors=request.anchors,
                    actors=request.actors,
                    cameras=request.cameras,
                    continuity_state=request.continuity_state,
                    created_at=now,
                )
                self._connection.execute(
                    """INSERT INTO director_world_versions(
                        project_id, version, unit, anchors, actors, cameras, continuity_state, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id,
                        record.version,
                        record.unit,
                        json.dumps([item.model_dump(mode="json") for item in record.anchors], ensure_ascii=False, sort_keys=True),
                        json.dumps([item.model_dump(mode="json") for item in record.actors], ensure_ascii=False, sort_keys=True),
                        json.dumps([item.model_dump(mode="json") for item in record.cameras], ensure_ascii=False, sort_keys=True),
                        json.dumps(record.continuity_state, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                self._audit(project_id, owner_id, "director_world.versioned", project_id, {"version": record.version})
                self._connection.commit()
                return record
            except Exception:
                self._connection.rollback()
                raise

    @staticmethod
    def _world_from_row(row: sqlite3.Row) -> DirectorWorldRecord:
        data = dict(row)
        for name in ("anchors", "actors", "cameras", "continuity_state"):
            data[name] = json.loads(data[name])
        return DirectorWorldRecord.model_validate(data)

    def get_director_world(self, project_id: str, owner_id: str) -> DirectorWorldRecord | None:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        row = self._connection.execute(
            "SELECT * FROM director_world_versions WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return self._world_from_row(row) if row else None

    def director_frame_plan(self, project_id: str, owner_id: str) -> DirectorFramePlan:
        world = self.get_director_world(project_id, owner_id)
        if not world:
            raise ValueError("Director World has not been configured")
        frames = [
            DirectorFrame(
                order=camera.order,
                camera_id=camera.id,
                anchor_id=camera.anchor_id,
                position=camera.position,
                target=camera.target,
                focal_length_mm=camera.focal_length_mm,
                focus_distance_m=camera.focus_distance_m,
                axis=camera.axis,
                actors=world.actors,
                continuity_state=world.continuity_state,
            )
            for camera in sorted(world.cameras, key=lambda item: (item.order, item.id))
        ]
        return DirectorFramePlan(
            project_id=project_id,
            world_version=world.version,
            unit=world.unit,
            frames=frames,
        )

    def record_cost(
        self, project_id: str, owner_id: str, request: CostEventRequest
    ) -> CostEventRecord:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM cost_events WHERE project_id = ? AND idempotency_key = ?",
                (project_id, request.idempotency_key),
            ).fetchone()
            if existing:
                record = self._cost_from_row(existing)
                expected = request.model_dump(mode="json")
                actual = record.model_dump(mode="json", exclude={"id", "project_id", "owner_id", "created_at"})
                if expected != actual:
                    raise ValueError("cost idempotency key was reused with different data")
                return record
            now = utc_now_iso()
            record = CostEventRecord(
                id=f"cost_{uuid.uuid4().hex}",
                project_id=project_id,
                owner_id=owner_id,
                created_at=now,
                **request.model_dump(),
            )
            with self._connection:
                self._connection.execute(
                    """INSERT INTO cost_events(
                        id, project_id, owner_id, idempotency_key, phase, provider, operation,
                        amount, currency, episode_id, shot_id, metadata, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id,
                        project_id,
                        owner_id,
                        record.idempotency_key,
                        record.phase,
                        record.provider,
                        record.operation,
                        str(record.amount),
                        record.currency,
                        record.episode_id,
                        record.shot_id,
                        json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                self._audit(project_id, owner_id, f"cost.{record.phase}", record.id, {
                    "amount": str(record.amount), "currency": record.currency,
                })
            return record

    @staticmethod
    def _cost_from_row(row: sqlite3.Row) -> CostEventRecord:
        data = dict(row)
        data["metadata"] = json.loads(data["metadata"])
        data["amount"] = Decimal(data["amount"])
        return CostEventRecord.model_validate(data)

    def list_costs(self, project_id: str, owner_id: str) -> list[CostEventRecord]:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        rows = self._connection.execute(
            "SELECT * FROM cost_events WHERE project_id = ? AND owner_id = ? ORDER BY created_at, id",
            (project_id, owner_id),
        ).fetchall()
        return [self._cost_from_row(row) for row in rows]

    def cost_summary(self, project_id: str, owner_id: str) -> ProjectCostSummary:
        totals: dict[str, dict[str, Decimal]] = {}
        for event in self.list_costs(project_id, owner_id):
            currency = totals.setdefault(
                event.currency,
                {phase: Decimal("0") for phase in ("estimated", "reserved", "actual", "released")},
            )
            currency[event.phase] += event.amount
        return ProjectCostSummary(
            project_id=project_id,
            currencies=[
                CurrencyCostSummary(currency=currency, **phases)
                for currency, phases in sorted(totals.items())
            ],
        )

    def latest_artifact_version(self, project_id: str, owner_id: str, kind: ArtifactKind) -> int:
        row = self._connection.execute(
            """SELECT COALESCE(MAX(version), 0) AS latest FROM artifacts
               WHERE project_id = ? AND owner_id = ? AND kind = ?""",
            (project_id, owner_id, kind.value),
        ).fetchone()
        return int(row["latest"])

    def create_job(
        self, project_id: str, owner_id: str, request: GenerationJobRequest
    ) -> GenerationJobRecord:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM generation_jobs WHERE project_id = ? AND owner_id = ? AND idempotency_key = ?",
                (project_id, owner_id, request.idempotency_key),
            ).fetchone()
            if existing:
                current = self._job_from_row(existing)
                expected_descriptor, _ = self._canonical_payload(request.descriptor)
                actual_descriptor, _ = self._canonical_payload(current.descriptor)
                expected_contract = (
                    request.provider,
                    request.operation,
                    request.budget_units,
                    request.max_attempts,
                    expected_descriptor,
                )
                actual_contract = (
                    current.provider,
                    current.operation,
                    current.budget_units,
                    current.max_attempts,
                    actual_descriptor,
                )
                if expected_contract != actual_contract:
                    raise ValueError("idempotency key was already used with a different paid request")
                return current
            now = utc_now_iso()
            record = GenerationJobRecord(
                id=f"job_{uuid.uuid4().hex}", project_id=project_id, owner_id=owner_id,
                provider=request.provider, operation=request.operation,
                idempotency_key=request.idempotency_key, descriptor=request.descriptor,
                status="queued", budget_units=request.budget_units, attempts=0,
                max_attempts=request.max_attempts, created_at=now, updated_at=now,
            )
            with self._connection:
                self._connection.execute(
                    """INSERT INTO generation_jobs(
                        id, project_id, owner_id, provider, operation, idempotency_key,
                        descriptor, status, provider_task_id, budget_units, attempts,
                        max_attempts, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id, project_id, owner_id, record.provider, record.operation,
                        record.idempotency_key, json.dumps(record.descriptor, ensure_ascii=False, sort_keys=True),
                        record.status, None, record.budget_units, 0, record.max_attempts, now, now,
                    ),
                )
                self._audit(project_id, owner_id, "job.queued", record.id, {
                    "provider": record.provider, "budget_units": record.budget_units,
                })
            return record

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> GenerationJobRecord:
        data = dict(row)
        data["descriptor"] = json.loads(data["descriptor"])
        data["cancel_requested"] = bool(data.get("cancel_requested", 0))
        data["logs"] = json.loads(data.get("logs") or "[]")
        return GenerationJobRecord.model_validate(data)

    def get_job(self, job_id: str, owner_id: str) -> GenerationJobRecord | None:
        row = self._connection.execute(
            "SELECT * FROM generation_jobs WHERE id = ? AND owner_id = ?", (job_id, owner_id)
        ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, project_id: str, owner_id: str) -> list[GenerationJobRecord]:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        rows = self._connection.execute(
            """SELECT * FROM generation_jobs WHERE project_id = ? AND owner_id = ?
               ORDER BY created_at DESC, id DESC""",
            (project_id, owner_id),
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def acquire_next_job(self, worker_id: str, *, lease_seconds: int = 60) -> GenerationJobRecord | None:
        if not worker_id or len(worker_id) > 120 or lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError("worker id or lease duration is invalid")
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    """SELECT * FROM generation_jobs
                       WHERE status = 'queued' AND cancel_requested = 0 AND attempts < max_attempts
                       ORDER BY created_at, id LIMIT 1"""
                ).fetchone()
                if not row:
                    self._connection.commit()
                    return None
                current = self._job_from_row(row)
                self._connection.execute(
                    """UPDATE generation_jobs SET status = 'running', attempts = attempts + 1,
                       lease_owner = ?, lease_expires_at = ?, updated_at = ?
                       WHERE id = ? AND status = 'queued'""",
                    (worker_id, expires, now.isoformat(), current.id),
                )
                self._audit(current.project_id, worker_id, "job.leased", current.id, {
                    "lease_expires_at": expires, "attempt": current.attempts + 1,
                })
                updated = self._connection.execute(
                    "SELECT * FROM generation_jobs WHERE id = ?", (current.id,)
                ).fetchone()
                self._connection.commit()
                assert updated is not None
                return self._job_from_row(updated)
            except Exception:
                self._connection.rollback()
                raise

    def _leased_job(self, job_id: str, worker_id: str) -> GenerationJobRecord:
        row = self._connection.execute(
            "SELECT * FROM generation_jobs WHERE id = ? AND status = 'running' AND lease_owner = ?",
            (job_id, worker_id),
        ).fetchone()
        if not row:
            raise PermissionError("active job lease not found for worker")
        return self._job_from_row(row)

    def heartbeat_job(
        self, job_id: str, worker_id: str, *, lease_seconds: int = 60
    ) -> GenerationJobRecord:
        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError("lease duration is invalid")
        with self._lock, self._connection:
            current = self._leased_job(job_id, worker_id)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
            self._connection.execute(
                "UPDATE generation_jobs SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (expires, utc_now_iso(), job_id),
            )
        refreshed = self.get_job(job_id, current.owner_id)
        assert refreshed is not None
        return refreshed

    def set_provider_task_id(
        self, job_id: str, worker_id: str, provider_task_id: str
    ) -> GenerationJobRecord:
        if not provider_task_id or len(provider_task_id) > 300:
            raise ValueError("provider task id is invalid")
        with self._lock, self._connection:
            current = self._leased_job(job_id, worker_id)
            if current.provider_task_id and current.provider_task_id != provider_task_id:
                raise ValueError("provider task id is immutable after first assignment")
            self._connection.execute(
                "UPDATE generation_jobs SET provider_task_id = ?, updated_at = ? WHERE id = ?",
                (provider_task_id, utc_now_iso(), job_id),
            )
            self._audit(current.project_id, worker_id, "job.provider_task_linked", job_id, {
                "provider_task_id": provider_task_id,
            })
        updated = self.get_job(job_id, current.owner_id)
        assert updated is not None
        return updated

    def append_job_log(self, job_id: str, worker_id: str, message: str) -> GenerationJobRecord:
        clean = message.strip()
        if not clean or len(clean) > 2000:
            raise ValueError("job log message is invalid")
        with self._lock, self._connection:
            current = self._leased_job(job_id, worker_id)
            logs = [*current.logs, {"at": utc_now_iso(), "message": clean}][-200:]
            self._connection.execute(
                "UPDATE generation_jobs SET logs = ?, updated_at = ? WHERE id = ?",
                (json.dumps(logs, ensure_ascii=False), utc_now_iso(), job_id),
            )
        updated = self.get_job(job_id, current.owner_id)
        assert updated is not None
        return updated

    def request_job_cancel(self, job_id: str, owner_id: str) -> GenerationJobRecord:
        current = self.get_job(job_id, owner_id)
        if not current:
            raise PermissionError("job not found or not owned by actor")
        if current.status in {"accepted", "cancelled", "failed", "rejected"}:
            raise ValueError("job can no longer be cancelled")
        with self._lock, self._connection:
            if current.status == "queued":
                self._connection.execute(
                    "UPDATE generation_jobs SET status = 'cancelled', cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (utc_now_iso(), job_id),
                )
            else:
                self._connection.execute(
                    "UPDATE generation_jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (utc_now_iso(), job_id),
                )
            self._audit(current.project_id, owner_id, "job.cancel_requested", job_id, {})
        updated = self.get_job(job_id, owner_id)
        assert updated is not None
        return updated

    def recover_expired_jobs(self, *, now_iso: str | None = None) -> int:
        boundary = now_iso or utc_now_iso()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                rows = self._connection.execute(
                    """SELECT * FROM generation_jobs
                       WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
                    (boundary,),
                ).fetchall()
                for row in rows:
                    current = self._job_from_row(row)
                    status = "failed" if current.attempts >= current.max_attempts else "queued"
                    if current.cancel_requested:
                        status = "cancelled"
                    self._connection.execute(
                        """UPDATE generation_jobs SET status = ?, lease_owner = NULL,
                           lease_expires_at = NULL, updated_at = ? WHERE id = ?""",
                        (status, boundary, current.id),
                    )
                    self._audit(current.project_id, "system-recovery", f"job.{status}", current.id, {
                        "provider_task_id_preserved": bool(current.provider_task_id),
                        "reason": "expired_lease",
                    })
                self._connection.commit()
                return len(rows)
            except Exception:
                self._connection.rollback()
                raise

    def transition_job(
        self,
        job_id: str,
        owner_id: str,
        status: str,
        *,
        provider_task_id: str | None = None,
    ) -> GenerationJobRecord:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT * FROM generation_jobs WHERE id = ? AND owner_id = ?",
                    (job_id, owner_id),
                ).fetchone()
                if not row:
                    raise PermissionError("job not found or not owned by actor")
                current = self._job_from_row(row)
                if status not in self._JOB_TRANSITIONS.get(current.status, set()):
                    raise ValueError(f"invalid job transition: {current.status} -> {status}")
                attempts = current.attempts + (1 if status == "running" else 0)
                if attempts > current.max_attempts:
                    raise ValueError("job attempt budget exhausted")
                now = utc_now_iso()
                self._connection.execute(
                    """UPDATE generation_jobs SET status = ?, provider_task_id = COALESCE(?, provider_task_id),
                       attempts = ?, lease_owner = CASE WHEN ? = 'running' THEN lease_owner ELSE NULL END,
                       lease_expires_at = CASE WHEN ? = 'running' THEN lease_expires_at ELSE NULL END,
                       updated_at = ? WHERE id = ? AND owner_id = ? AND status = ?""",
                    (
                        status, provider_task_id, attempts, status, status, now,
                        job_id, owner_id, current.status,
                    ),
                )
                self._audit(current.project_id, owner_id, f"job.{status}", job_id, {
                    "provider_task_id": provider_task_id or current.provider_task_id,
                    "attempts": attempts,
                })
                updated_row = self._connection.execute(
                    "SELECT * FROM generation_jobs WHERE id = ? AND owner_id = ?",
                    (job_id, owner_id),
                ).fetchone()
                self._connection.commit()
                assert updated_row is not None
                return self._job_from_row(updated_row)
            except Exception:
                self._connection.rollback()
                raise

    def project_reserved_budget(self, project_id: str, owner_id: str) -> int:
        row = self._connection.execute(
            """SELECT COALESCE(SUM(budget_units), 0) AS total FROM generation_jobs
               WHERE project_id = ? AND owner_id = ? AND status IN ('queued', 'running', 'succeeded')""",
            (project_id, owner_id),
        ).fetchone()
        return int(row["total"])

    def issue_agent_key(
        self, project_id: str, owner_id: str, request: AgentKeyCreateRequest
    ) -> IssuedAgentKey:
        if not self.get_project(project_id, owner_id):
            raise PermissionError("project not found or not owned by actor")
        key_id = f"ak_{uuid.uuid4().hex}"
        token = f"sdk_{uuid.uuid4().hex}.{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = utc_now_iso()
        record = AgentKeyRecord(
            id=key_id, project_id=project_id, owner_id=owner_id,
            name=request.name.strip(), token_prefix=token[:16], scopes=request.scopes,
            revoked=False, created_at=now,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO agent_keys(
                    id, project_id, owner_id, name, token_prefix, token_digest, scopes, revoked, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    record.id, project_id, owner_id, record.name, record.token_prefix,
                    digest, json.dumps(request.scopes), now,
                ),
            )
            self._audit(project_id, owner_id, "agent_key.issued", key_id, {
                "name": record.name, "scopes": request.scopes,
            })
        return IssuedAgentKey(key=record, token=token)

    def verify_agent_key(self, token: str, *, required_scope: str) -> AgentAuthorization:
        if not token.startswith("sdk_") or len(token) > 256:
            raise PermissionError("invalid agent key")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = self._connection.execute(
            "SELECT * FROM agent_keys WHERE token_digest = ?", (digest,)
        ).fetchone()
        if not row or bool(row["revoked"]) or not hmac.compare_digest(row["token_digest"], digest):
            raise PermissionError("invalid or revoked agent key")
        scopes = json.loads(row["scopes"])
        if required_scope not in scopes:
            raise PermissionError("agent key does not grant the required scope")
        return AgentAuthorization(
            key_id=row["id"], project_id=row["project_id"], owner_id=row["owner_id"], scopes=scopes,
        )

    def revoke_agent_key(self, key_id: str, owner_id: str) -> None:
        row = self._connection.execute(
            "SELECT project_id FROM agent_keys WHERE id = ? AND owner_id = ?", (key_id, owner_id)
        ).fetchone()
        if not row:
            raise PermissionError("agent key not found or not owned by actor")
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE agent_keys SET revoked = 1 WHERE id = ? AND owner_id = ?", (key_id, owner_id)
            )
            self._audit(row["project_id"], owner_id, "agent_key.revoked", key_id, {})

    def debug_agent_key_storage(self, key_id: str) -> str:
        """Test-only fingerprint view; never returns through an HTTP route."""
        row = self._connection.execute(
            "SELECT token_prefix, token_digest FROM agent_keys WHERE id = ?", (key_id,)
        ).fetchone()
        return f"{row['token_prefix']}:{row['token_digest']}" if row else ""

    def project_snapshot(self, project_id: str, owner_id: str) -> dict[str, Any]:
        project = self.get_project(project_id, owner_id)
        if not project:
            raise PermissionError("project not found or not owned by actor")
        artifacts = [item.model_dump(mode="json") for item in self.list_artifacts(project_id, owner_id)]
        review_rows = self._connection.execute(
            "SELECT * FROM artifact_reviews WHERE project_id = ? ORDER BY created_at, rowid",
            (project_id,),
        ).fetchall()
        job_rows = self._connection.execute(
            "SELECT * FROM generation_jobs WHERE project_id = ? AND owner_id = ? ORDER BY created_at, id",
            (project_id, owner_id),
        ).fetchall()
        canvas_rows = self._connection.execute(
            "SELECT * FROM canvas_versions WHERE project_id = ? ORDER BY version", (project_id,)
        ).fetchall()
        world_rows = self._connection.execute(
            "SELECT * FROM director_world_versions WHERE project_id = ? ORDER BY version",
            (project_id,),
        ).fetchall()
        return {
            "schema_version": 1,
            "project": project.model_dump(mode="json"),
            "artifacts": artifacts,
            "reviews": [self._review_from_row(row).model_dump(mode="json") for row in review_rows],
            "jobs": [self._job_from_row(row).model_dump(mode="json") for row in job_rows],
            "canvas_versions": [self._canvas_from_row(row).model_dump(mode="json") for row in canvas_rows],
            "director_world_versions": [self._world_from_row(row).model_dump(mode="json") for row in world_rows],
            "cost_events": [item.model_dump(mode="json") for item in self.list_costs(project_id, owner_id)],
        }

    def import_project_snapshot(
        self, snapshot: dict[str, Any], *, owner_id: str, project_name: str
    ) -> ProjectRecord:
        if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("project"), dict):
            raise ValueError("unsupported project snapshot schema")
        ProjectCreate(name=project_name)
        project_id = f"prj_{uuid.uuid4().hex}"
        now = utc_now_iso()
        record = ProjectRecord(
            id=project_id,
            owner_id=owner_id,
            name=project_name.strip(),
            description=str(snapshot["project"].get("description", ""))[:2000],
            created_at=now,
            updated_at=now,
        )
        raw_artifacts = snapshot.get("artifacts", [])
        raw_reviews = snapshot.get("reviews", [])
        raw_jobs = snapshot.get("jobs", [])
        raw_canvases = snapshot.get("canvas_versions", [])
        raw_worlds = snapshot.get("director_world_versions", [])
        raw_costs = snapshot.get("cost_events", [])
        if not all(
            isinstance(items, list)
            for items in (raw_artifacts, raw_reviews, raw_jobs, raw_canvases, raw_worlds, raw_costs)
        ):
            raise ValueError("project snapshot collections must be arrays")
        artifacts = [ArtifactRecord.model_validate(item) for item in raw_artifacts]
        reviews = [ReviewRecord.model_validate(item) for item in raw_reviews]
        jobs = [GenerationJobRecord.model_validate(item) for item in raw_jobs]
        canvases = [CanvasRecord.model_validate(item) for item in raw_canvases]
        worlds = [DirectorWorldRecord.model_validate(item) for item in raw_worlds]
        costs = [CostEventRecord.model_validate(item) for item in raw_costs]
        artifact_map = {item.id: f"art_{uuid.uuid4().hex}" for item in artifacts}
        if len(artifact_map) != len(artifacts):
            raise ValueError("project snapshot contains duplicate artifact ids")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO projects(id, owner_id, name, description, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                    (record.id, owner_id, record.name, record.description, now, now),
                )
                for artifact in artifacts:
                    _, computed_hash = self._canonical_payload(artifact.payload)
                    if computed_hash != artifact.content_hash:
                        raise ValueError("artifact content hash does not match archived payload")
                    if any(parent not in artifact_map for parent in artifact.parents):
                        raise ValueError("artifact parent is missing from archive")
                    self._connection.execute(
                        """INSERT INTO artifacts(
                            id, project_id, owner_id, kind, version, payload, content_hash,
                            parents, stale, status, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            artifact_map[artifact.id],
                            project_id,
                            owner_id,
                            artifact.kind.value,
                            artifact.version,
                            json.dumps(artifact.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                            artifact.content_hash,
                            json.dumps([artifact_map[parent] for parent in artifact.parents]),
                            int(artifact.stale),
                            artifact.status,
                            artifact.created_at,
                        ),
                    )
                for review in reviews:
                    if review.artifact_id not in artifact_map:
                        raise ValueError("review references an artifact missing from archive")
                    self._connection.execute(
                        """INSERT INTO artifact_reviews(
                            id, project_id, artifact_id, reviewer_id, decision, comment, checks, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"rev_{uuid.uuid4().hex}",
                            project_id,
                            artifact_map[review.artifact_id],
                            owner_id,
                            review.decision,
                            review.comment,
                            json.dumps(review.checks, ensure_ascii=False, sort_keys=True),
                            review.created_at,
                        ),
                    )
                for job in jobs:
                    restored_status = "queued" if job.status == "running" else job.status
                    self._connection.execute(
                        """INSERT INTO generation_jobs(
                            id, project_id, owner_id, provider, operation, idempotency_key,
                            descriptor, status, provider_task_id, budget_units, attempts,
                            max_attempts, lease_owner, lease_expires_at, cancel_requested,
                            logs, created_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)""",
                        (
                            f"job_{uuid.uuid4().hex}", project_id, owner_id, job.provider,
                            job.operation, job.idempotency_key,
                            json.dumps(job.descriptor, ensure_ascii=False, sort_keys=True),
                            restored_status, job.provider_task_id, job.budget_units, job.attempts,
                            job.max_attempts, int(job.cancel_requested),
                            json.dumps(job.logs, ensure_ascii=False), job.created_at, now,
                        ),
                    )
                for canvas in canvases:
                    nodes = []
                    for node in canvas.nodes:
                        data = node.model_dump(mode="json")
                        if data.get("artifact_id") in artifact_map:
                            data["artifact_id"] = artifact_map[data["artifact_id"]]
                        nodes.append(data)
                    self._connection.execute(
                        "INSERT INTO canvas_versions(project_id, version, nodes, edges, created_at) VALUES(?, ?, ?, ?, ?)",
                        (
                            project_id, canvas.version,
                            json.dumps(nodes, ensure_ascii=False, sort_keys=True),
                            json.dumps([edge.model_dump(mode="json") for edge in canvas.edges], ensure_ascii=False, sort_keys=True),
                            canvas.created_at,
                        ),
                    )
                for world in worlds:
                    self._connection.execute(
                        """INSERT INTO director_world_versions(
                            project_id, version, unit, anchors, actors, cameras, continuity_state, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            project_id, world.version, world.unit,
                            json.dumps([item.model_dump(mode="json") for item in world.anchors], ensure_ascii=False, sort_keys=True),
                            json.dumps([item.model_dump(mode="json") for item in world.actors], ensure_ascii=False, sort_keys=True),
                            json.dumps([item.model_dump(mode="json") for item in world.cameras], ensure_ascii=False, sort_keys=True),
                            json.dumps(world.continuity_state, ensure_ascii=False, sort_keys=True),
                            world.created_at,
                        ),
                    )
                for cost in costs:
                    self._connection.execute(
                        """INSERT INTO cost_events(
                            id, project_id, owner_id, idempotency_key, phase, provider, operation,
                            amount, currency, episode_id, shot_id, metadata, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"cost_{uuid.uuid4().hex}", project_id, owner_id,
                            cost.idempotency_key, cost.phase, cost.provider, cost.operation,
                            str(cost.amount), cost.currency, cost.episode_id, cost.shot_id,
                            json.dumps(cost.metadata, ensure_ascii=False, sort_keys=True), cost.created_at,
                        ),
                    )
                self._audit(project_id, owner_id, "project.imported", project_id, {
                    "artifacts": len(artifacts), "jobs": len(jobs), "cost_events": len(costs),
                })
                self._connection.commit()
                return record
            except Exception:
                self._connection.rollback()
                raise

    def _audit(
        self, project_id: str, actor_id: str, event_type: str, subject_id: str, details: dict[str, Any]
    ) -> None:
        self._connection.execute(
            """INSERT INTO audit_events(project_id, actor_id, event_type, subject_id, details, created_at)
               VALUES(?, ?, ?, ?, ?, ?)""",
            (
                project_id, actor_id, event_type, subject_id,
                json.dumps(details, ensure_ascii=False, sort_keys=True), utc_now_iso(),
            ),
        )
