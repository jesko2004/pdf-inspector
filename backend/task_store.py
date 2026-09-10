"""SQLite persistence for task lifecycle state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .migrations import Migration, apply_migrations

TERMINAL_STATUSES = {"ready", "needs_review", "failed"}
RESULT_STATUSES = {"ready", "needs_review"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TaskNotFoundError(KeyError):
    pass


class InvalidTaskStateError(ValueError):
    pass


class TaskStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_version INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'processing', 'ready', 'needs_review', 'failed')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    pdf_path TEXT NOT NULL,
                    result_path TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS tasks_status_idx ON tasks(status, created_at)"
            )
            apply_migrations(
                connection,
                "tasks",
                (Migration(1, "baseline_task_schema", "SELECT 1;"),),
            )

    def count_active(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('queued', 'processing')"
            ).fetchone()
        assert row is not None
        return int(row[0])

    def status_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, filename, profile_id, profile_version, profile_json,
                    status, attempts, pdf_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["filename"],
                    row["profile_id"],
                    row["profile_version"],
                    row["profile_json"],
                    row["pdf_path"],
                    now,
                    now,
                ),
            )
        return self.get(row["id"])

    def get(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return dict(row)

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_attempt(self, task_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                   SET status = 'processing', attempts = attempts + 1,
                       error_code = NULL, error_message = NULL, updated_at = ?
                 WHERE id = ? AND status = 'queued'
                """,
                (utc_now(), task_id),
            )
        return cursor.rowcount == 1

    def finish(self, task_id: str, status: str, result_path: str) -> dict[str, Any]:
        if status not in RESULT_STATUSES:
            raise ValueError(f"invalid result status: {status}")
        self._transition(
            task_id,
            from_status="processing",
            status=status,
            result_path=result_path,
            error_code=None,
            error_message=None,
        )
        return self.get(task_id)

    def fail(self, task_id: str, error_code: str, error_message: str) -> dict[str, Any]:
        self._transition(
            task_id,
            from_status="processing",
            status="failed",
            result_path=None,
            error_code=error_code[:120],
            error_message=error_message[:2000],
        )
        return self.get(task_id)

    def retry(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                   SET status = 'queued', result_path = NULL,
                       error_code = NULL, error_message = NULL, updated_at = ?
                 WHERE id = ? AND status = 'failed'
                """,
                (utc_now(), task_id),
            )
        if cursor.rowcount != 1:
            row = self.get(task_id)
            raise InvalidTaskStateError(
                f"only failed tasks can be retried; current status is {row['status']}"
            )
        return self.get(task_id)

    def recover_incomplete(self) -> list[str]:
        """Requeue work interrupted by the previous process."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'queued', updated_at = ? WHERE status = 'processing'",
                (utc_now(),),
            )
            rows = connection.execute(
                "SELECT id FROM tasks WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [row["id"] for row in rows]

    def _transition(
        self,
        task_id: str,
        *,
        from_status: str,
        status: str,
        result_path: str | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                   SET status = ?, result_path = ?, error_code = ?,
                       error_message = ?, updated_at = ?
                 WHERE id = ? AND status = ?
                """,
                (
                    status,
                    result_path,
                    error_code,
                    error_message,
                    utc_now(),
                    task_id,
                    from_status,
                ),
            )
        if cursor.rowcount != 1:
            row = self.get(task_id)
            raise InvalidTaskStateError(
                f"task transition {from_status} -> {status} rejected from {row['status']}"
            )
