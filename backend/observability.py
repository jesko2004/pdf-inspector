"""Request tracing, in-memory Prometheus metrics, rate limits, and audit events."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter
from typing import Iterator

from .migrations import Migration, apply_migrations
from .task_store import utc_now


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
            defaultdict(float)
        )
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    @staticmethod
    def _key(
        name: str, labels: dict[str, str] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted((labels or {}).items()))

    def increment(self, name: str, value: float = 1, **labels: str) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def observe(self, operation: str, seconds: float, outcome: str = "success") -> None:
        labels = {"operation": operation, "outcome": outcome}
        self.increment("pdf_inspector_operation_duration_seconds_count", **labels)
        self.increment(
            "pdf_inspector_operation_duration_seconds_sum", seconds, **labels
        )

    @contextmanager
    def timer(self, operation: str) -> Iterator[None]:
        started = perf_counter()
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            self.observe(operation, perf_counter() - started, outcome)

    def render(self) -> str:
        with self._lock:
            items = list(self._counters.items()) + list(self._gauges.items())
        lines = []
        for (name, labels), value in sorted(items):
            suffix = ""
            if labels:
                rendered = ",".join(
                    f'{key}="{label.replace(chr(34), chr(92) + chr(34))}"'
                    for key, label in labels
                )
                suffix = "{" + rendered + "}"
            lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + "\n"


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(
        self, identity: str, bucket: str, limit: int, window: float = 60
    ) -> tuple[bool, int]:
        now = monotonic()
        key = (identity, bucket)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window - (now - events[0])) + 1)
                return False, retry_after
            events.append(now)
        return True, 0


AUDIT_MIGRATIONS = (
    Migration(
        1,
        "initial_audit_log",
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            request_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_role TEXT,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            client_ip TEXT
        );
        CREATE INDEX IF NOT EXISTS audit_events_time_idx ON audit_events(occurred_at DESC);
        """,
    ),
)


class AuditStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            apply_migrations(connection, "audit", AUDIT_MIGRATIONS)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record(
        self,
        *,
        request_id: str,
        actor_id: str,
        actor_role: str | None,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client_ip: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events(
                    occurred_at, request_id, actor_id, actor_role, method, path,
                    status_code, duration_ms, client_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    request_id,
                    actor_id,
                    actor_role,
                    method,
                    path,
                    status_code,
                    round(duration_ms, 3),
                    client_ip,
                ),
            )

    def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]


def json_log(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
