# -*- coding: utf-8 -*-
"""Atomic local task repository used by the resumable development workflow."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar


_WRITE_LOCK = threading.RLock()
_ResultT = TypeVar("_ResultT")


class StaleTaskWriteError(RuntimeError):
    """Raised when an old task snapshot tries to overwrite a newer script revision."""


class TaskStoreUnavailableError(RuntimeError):
    """Raised when the task database exists but cannot be read or parsed.

    This must never be confused with an empty database: treating an unreadable
    file as ``{}`` lets the very next write replace every stored task with a
    single-task snapshot.
    """


def _script_revision(task: object) -> int:
    if not isinstance(task, dict):
        return 0
    try:
        return max(0, int(task.get("script_revision", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


class TaskRepository:
    def __init__(self, db_path: str | None = None):
        default_path = Path(__file__).resolve().parents[2] / "tasks_db.json"
        self.db_path = Path(db_path or os.getenv("TASKS_DB_PATH") or default_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._write_db({})

    def _read_db(self) -> Dict[str, Any]:
        try:
            raw = self.db_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # A missing database is genuinely empty; anything else is a fault.
            return {}
        except OSError as exc:
            raise TaskStoreUnavailableError(f"任务库读取失败: {exc.strerror or exc}") from exc
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TaskStoreUnavailableError("任务库内容已损坏，拒绝在此状态下写入") from exc
        if not isinstance(data, dict):
            raise TaskStoreUnavailableError("任务库格式异常，拒绝在此状态下写入")
        return data

    def _write_db(self, data: Dict[str, Any]) -> None:
        temporary = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            os.replace(temporary, self.db_path)
        except BaseException:
            # A partial temp file (ENOSPC, interrupt) must not be left behind.
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        with _WRITE_LOCK:
            db = self._read_db()
            current = db.get(task_id)
            current_revision = _script_revision(current)
            incoming_revision = _script_revision(task_data)
            if current_revision > incoming_revision:
                raise StaleTaskWriteError("任务剧本已更新，拒绝旧快照覆盖")
            db[task_id] = task_data
            self._write_db(db)

    def mutate_task(
        self,
        task_id: str,
        mutation: Callable[[Dict[str, Any]], _ResultT],
    ) -> Optional[_ResultT]:
        """Read, mutate and persist one task while holding the repository write lock."""
        with _WRITE_LOCK:
            db = self._read_db()
            task = db.get(task_id)
            if not isinstance(task, dict):
                return None
            result = mutation(task)
            db[task_id] = task
            self._write_db(db)
            return result

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._read_db().get(task_id)

    def list_all_tasks(self) -> List[Dict[str, Any]]:
        return list(self._read_db().values())

    def delete_task(self, task_id: str) -> bool:
        with _WRITE_LOCK:
            db = self._read_db()
            if task_id not in db:
                return False
            db.pop(task_id)
            self._write_db(db)
            return True
