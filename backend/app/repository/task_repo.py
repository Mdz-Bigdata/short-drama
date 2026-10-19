# -*- coding: utf-8 -*-
"""SQL-backed task repository with the original synchronous API.

Tasks used to live in one ``tasks_db.json`` blob: every read parsed the whole
file, every write rewrote it, and a corrupted read could wipe unrelated tasks.
Rows now live in the same SQL database as the platform store (PostgreSQL in
production; tests that pass a legacy ``*.json`` path transparently get a
private SQLite file next to it). The public surface — ``get_task``,
``save_task``, ``mutate_task``, ``list_all_tasks``, ``delete_task`` and the
two error types — is unchanged, so every existing caller keeps working.

On first use the repository imports the legacy JSON file once, records a
migration marker, and leaves the JSON untouched as a backup.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from app import settings

logger = logging.getLogger("app.repository.task_repo")

_WRITE_LOCK = threading.RLock()
_ResultT = TypeVar("_ResultT")

_ENGINE_LOCK = threading.Lock()
_ENGINES: Dict[str, Engine] = {}
_READY_URLS: set[str] = set()

_METADATA = sa.MetaData()
_TASKS = sa.Table(
    "drama_tasks",
    _METADATA,
    sa.Column("task_id", sa.Text, primary_key=True),
    sa.Column("payload", sa.Text, nullable=False),
    sa.Column("script_revision", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("created_ns", sa.BigInteger, nullable=False),
    sa.Column("updated_ns", sa.BigInteger, nullable=False),
)
_META = sa.Table(
    "drama_task_meta",
    _METADATA,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
_MIGRATION_MARKER = "legacy_json_migrated"


# Records that provider sinks append through mutate_task while a stage thread
# still holds an older in-memory copy of the task: the usage ledger, accepted
# video jobs and the generation queue. The stored row is the authority for them;
# a progress save of the stale copy must not take them back.
SINK_OWNED_TASK_KEYS = ("usage_records",)
SINK_OWNED_ASSET_KEYS = ("5_jobs", "5_queue")


def _keep_sink_owned(incoming: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(incoming)
    for key in SINK_OWNED_TASK_KEYS:
        if key in current:
            merged[key] = deepcopy(current[key])
    current_assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
    if any(key in current_assets for key in SINK_OWNED_ASSET_KEYS):
        assets = dict(merged.get("assets") or {}) if isinstance(merged.get("assets"), dict) else {}
        for key in SINK_OWNED_ASSET_KEYS:
            if key in current_assets:
                assets[key] = deepcopy(current_assets[key])
        merged["assets"] = assets
    return merged


class StaleTaskWriteError(RuntimeError):
    """Raised when an old task snapshot tries to overwrite a newer script revision."""


class TaskStoreUnavailableError(RuntimeError):
    """Raised when the task database cannot be reached, read or migrated.

    This must never be confused with an empty database: treating an unreadable
    store as empty is exactly the failure mode that used to let one bad read
    destroy every other task.
    """


def _script_revision(task: object) -> int:
    if not isinstance(task, dict):
        return 0
    try:
        return max(0, int(task.get("script_revision", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _chat_event_id(event: object) -> str:
    return str(event.get("id") or "").strip() if isinstance(event, dict) else ""


def _legacy_chat_key(event: object) -> str:
    """Match old sender/text events with their canonical role/content shape."""
    if isinstance(event, dict):
        role = event.get("role") or event.get("sender")
        role = "assistant" if role == "ai" else role
        content = event.get("content") if "content" in event else event.get("text")
        if role is not None and content is not None:
            return json.dumps([role, content], ensure_ascii=False, sort_keys=True)
    return json.dumps(event, ensure_ascii=False, sort_keys=True)


def _merge_chat_history(current: object, incoming: object) -> list:
    """Keep durable event order and append unseen snapshot events.

    Stable IDs are immutable: a stale copy cannot rewrite an existing event.
    Legacy events have no reliable identity, so compare occurrence counts rather
    than a set; this preserves repeated messages without replaying whole history.
    """
    merged = []
    seen_ids: set[str] = set()
    for chat_event in current if isinstance(current, list) else []:
        event_id = _chat_event_id(chat_event)
        if event_id and event_id in seen_ids:
            continue
        merged.append(chat_event)
        if event_id:
            seen_ids.add(event_id)
    durable_counts = Counter(_legacy_chat_key(event) for event in merged)
    legacy_counts = Counter(_legacy_chat_key(item) for item in merged if not _chat_event_id(item))
    synthetic_counts: Counter[str] = Counter()
    incoming_counts: Counter[str] = Counter()
    for chat_event in incoming if isinstance(incoming, list) else []:
        event_id = _chat_event_id(chat_event)
        if event_id:
            if event_id.startswith("legacy-") and event_id[7:].isdigit():
                key = _legacy_chat_key(chat_event)
                synthetic_counts[key] += 1
                if synthetic_counts[key] <= legacy_counts[key]:
                    continue
            if event_id not in seen_ids:
                merged.append(chat_event)
                seen_ids.add(event_id)
        else:
            key = _legacy_chat_key(chat_event)
            incoming_counts[key] += 1
            if incoming_counts[key] > durable_counts[key]:
                merged.append(chat_event)
    return merged


def _sync_database_url() -> str:
    explicit = (os.getenv("TASKS_DATABASE_URL") or "").strip()
    if explicit:
        return explicit
    platform_url = settings.database_url()
    return platform_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")


def _engine_for(url: str) -> Engine:
    with _ENGINE_LOCK:
        engine = _ENGINES.get(url)
        if engine is None:
            engine = sa.create_engine(url, pool_pre_ping=True, future=True)
            if engine.dialect.name == "sqlite":
                @event.listens_for(engine, "connect")
                def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.close()
            _ENGINES[url] = engine
        return engine


class TaskRepository:
    def __init__(self, db_path: str | None = None, *, database_url: str | None = None):
        default_path = Path(__file__).resolve().parents[2] / "tasks_db.json"
        self.db_path = Path(db_path or os.getenv("TASKS_DB_PATH") or default_path).expanduser().resolve()
        if database_url:
            self._database_url = database_url
        elif db_path is not None:
            # Tests and legacy callers hand us a JSON path; give them a private
            # SQLite database beside it instead of the shared platform server.
            sqlite_file = self.db_path.with_suffix(".sqlite3")
            sqlite_file.parent.mkdir(parents=True, exist_ok=True)
            self._database_url = f"sqlite:///{sqlite_file}"
        else:
            self._database_url = _sync_database_url()

    # ------------------------------------------------------------------ setup

    @property
    def engine(self) -> Engine:
        return _engine_for(self._database_url)

    def _ensure_ready(self) -> None:
        """Create tables and run the one-time legacy JSON import lazily.

        Construction must stay side-effect free: modules build repositories at
        import time, and a database that is down should surface as a 503 from
        the request that needed it, not as a crash at import.
        """
        if self._database_url in _READY_URLS:
            return
        with _WRITE_LOCK:
            if self._database_url in _READY_URLS:
                return
            try:
                _METADATA.create_all(self.engine, checkfirst=True)
                self._migrate_legacy_json()
            except TaskStoreUnavailableError:
                raise
            except (SQLAlchemyError, OSError) as exc:
                raise TaskStoreUnavailableError(f"任务库初始化失败: {exc}") from exc
            _READY_URLS.add(self._database_url)

    def _migrate_legacy_json(self) -> None:
        with self.engine.begin() as connection:
            marker = connection.execute(
                sa.select(_META.c.value).where(_META.c.key == _MIGRATION_MARKER)
            ).scalar()
            if marker is not None:
                return
            imported = 0
            if self.db_path.exists():
                try:
                    raw = self.db_path.read_text(encoding="utf-8")
                    legacy = json.loads(raw)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    # Refuse to run against a store whose legacy data cannot be
                    # read: starting "empty" here would silently orphan it.
                    raise TaskStoreUnavailableError(
                        f"旧版任务库 {self.db_path.name} 无法读取，已停止迁移以避免数据丢失"
                    ) from exc
                if not isinstance(legacy, dict):
                    raise TaskStoreUnavailableError(
                        f"旧版任务库 {self.db_path.name} 格式异常，已停止迁移以避免数据丢失"
                    )
                now = time.time_ns()
                for offset, (task_id, task) in enumerate(legacy.items()):
                    if not isinstance(task, dict):
                        continue
                    exists = connection.execute(
                        sa.select(_TASKS.c.task_id).where(_TASKS.c.task_id == str(task_id))
                    ).scalar()
                    if exists is not None:
                        continue
                    connection.execute(_TASKS.insert().values(
                        task_id=str(task_id),
                        payload=json.dumps(task, ensure_ascii=False),
                        script_revision=_script_revision(task),
                        created_ns=now + offset,
                        updated_ns=now + offset,
                    ))
                    imported += 1
            connection.execute(_META.insert().values(
                key=_MIGRATION_MARKER,
                value=json.dumps({"imported": imported, "source": str(self.db_path)}),
            ))
            if imported:
                logger.warning(
                    "[任务库迁移] 已从 %s 导入 %d 个任务到 SQL 存储；原 JSON 文件保留为备份",
                    self.db_path.name, imported,
                )

    # ------------------------------------------------------------- primitives

    @staticmethod
    def _load_payload(raw: object) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _translate(exc: Exception) -> TaskStoreUnavailableError:
        return TaskStoreUnavailableError(f"任务库不可用: {exc.__class__.__name__}")

    def _snapshot_payload(self, task_data: Dict[str, Any], current_raw: object = None) -> str:
        current = self._load_payload(current_raw) if current_raw is not None else None
        durable_history = current.get("chat_history") if current else None
        incoming_history = task_data.get("chat_history")
        if isinstance(durable_history, list) or isinstance(incoming_history, list):
            task_data = {
                **task_data,
                "chat_history": _merge_chat_history(durable_history, incoming_history),
            }
        if current and isinstance(current.get("workflow_control"), dict):
            # Workflow reservations and pause intent are atomically maintained
            # through mutate_task; background result snapshots cannot own them.
            task_data = {
                **task_data,
                "workflow_control": deepcopy(current["workflow_control"]),
            }
        if current:
            task_data = _keep_sink_owned(task_data, current)
        return json.dumps(task_data, ensure_ascii=False)

    # -------------------------------------------------------------- public API

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_ready()
        try:
            with self.engine.connect() as connection:
                raw = connection.execute(
                    sa.select(_TASKS.c.payload).where(_TASKS.c.task_id == task_id)
                ).scalar()
        except (DBAPIError, SQLAlchemyError) as exc:
            raise self._translate(exc) from exc
        return self._load_payload(raw) if raw is not None else None

    def list_all_tasks(self) -> List[Dict[str, Any]]:
        self._ensure_ready()
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    sa.select(_TASKS.c.payload).order_by(_TASKS.c.created_ns, _TASKS.c.task_id)
                ).scalars().all()
        except (DBAPIError, SQLAlchemyError) as exc:
            raise self._translate(exc) from exc
        tasks: List[Dict[str, Any]] = []
        for raw in rows:
            task = self._load_payload(raw)
            if task is not None:
                tasks.append(task)
        return tasks

    def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        self._ensure_ready()
        incoming_revision = _script_revision(task_data)
        with _WRITE_LOCK:
            try:
                with self.engine.begin() as connection:
                    current = connection.execute(
                        sa.select(_TASKS.c.script_revision, _TASKS.c.payload)
                        .where(_TASKS.c.task_id == task_id)
                        .with_for_update()
                    ).first()
                    current_revision = current.script_revision if current is not None else None
                    if current_revision is not None and int(current_revision) > incoming_revision:
                        raise StaleTaskWriteError("任务剧本已更新，拒绝旧快照覆盖")
                    payload = self._snapshot_payload(task_data, current.payload if current is not None else None)
                    now = time.time_ns()
                    if current_revision is None:
                        connection.execute(_TASKS.insert().values(
                            task_id=task_id,
                            payload=payload,
                            script_revision=incoming_revision,
                            created_ns=now,
                            updated_ns=now,
                        ))
                    else:
                        connection.execute(
                            _TASKS.update()
                            .where(_TASKS.c.task_id == task_id)
                            .values(payload=payload, script_revision=incoming_revision, updated_ns=now)
                        )
            except StaleTaskWriteError:
                raise
            except IntegrityError as exc:
                # A cross-process insert race: the row now exists, retry as update.
                try:
                    with self.engine.begin() as connection:
                        current = connection.execute(
                            sa.select(_TASKS.c.script_revision, _TASKS.c.payload)
                            .where(_TASKS.c.task_id == task_id)
                            .with_for_update()
                        ).first()
                        current_revision = current.script_revision if current is not None else None
                        if current_revision is not None and int(current_revision) > incoming_revision:
                            raise StaleTaskWriteError("任务剧本已更新，拒绝旧快照覆盖")
                        payload = self._snapshot_payload(task_data, current.payload if current is not None else None)
                        connection.execute(
                            _TASKS.update()
                            .where(_TASKS.c.task_id == task_id)
                            .values(
                                payload=payload,
                                script_revision=incoming_revision,
                                updated_ns=time.time_ns(),
                            )
                        )
                except StaleTaskWriteError:
                    raise
                except (DBAPIError, SQLAlchemyError) as retry_exc:
                    raise self._translate(retry_exc) from exc
            except (DBAPIError, SQLAlchemyError) as exc:
                raise self._translate(exc) from exc

    def mutate_task(
        self,
        task_id: str,
        mutation: Callable[[Dict[str, Any]], _ResultT],
    ) -> Optional[_ResultT]:
        """Read, mutate and persist one task inside a single row-locked transaction."""
        self._ensure_ready()
        with _WRITE_LOCK:
            try:
                with self.engine.begin() as connection:
                    raw = connection.execute(
                        sa.select(_TASKS.c.payload)
                        .where(_TASKS.c.task_id == task_id)
                        .with_for_update()
                    ).scalar()
                    task = self._load_payload(raw) if raw is not None else None
                    if task is None:
                        return None
                    result = mutation(task)
                    connection.execute(
                        _TASKS.update()
                        .where(_TASKS.c.task_id == task_id)
                        .values(
                            payload=json.dumps(task, ensure_ascii=False),
                            script_revision=_script_revision(task),
                            updated_ns=time.time_ns(),
                        )
                    )
                    return result
            except (DBAPIError, SQLAlchemyError) as exc:
                raise self._translate(exc) from exc

    def delete_task(self, task_id: str) -> bool:
        self._ensure_ready()
        with _WRITE_LOCK:
            try:
                with self.engine.begin() as connection:
                    outcome = connection.execute(
                        _TASKS.delete().where(_TASKS.c.task_id == task_id)
                    )
                    return bool(outcome.rowcount)
            except (DBAPIError, SQLAlchemyError) as exc:
                raise self._translate(exc) from exc
