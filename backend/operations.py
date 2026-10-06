"""Persist explicit request identities; never retry an uncertain paid call."""

from contextlib import contextmanager
from hashlib import sha256
import json
import sqlite3
from uuid import uuid4

from .migrations import Migration, apply_migrations
from .task_store import utc_now


class OperationConflictError(ValueError):
    def __init__(self, code, operation_id):
        super().__init__(code)
        self.code, self.operation_id = code, operation_id


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class OperationStore:
    def __init__(self, database_path, *, recover_incomplete=False):
        self.database_path = database_path
        with self._connect() as connection:
            apply_migrations(connection, "operations", (Migration(1, "explicit_request_identity", """
                CREATE TABLE request_operations (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, scope TEXT NOT NULL,
                    key_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, result_json TEXT, error_code TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(actor, scope, key_hash)
                );
            """),))
            if recover_incomplete:
                connection.execute("UPDATE request_operations SET status='uncertain', error_code='executor_restarted', updated_at=? WHERE status='processing'", (utc_now(),))

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, operation_id, actor):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM request_operations WHERE id=? AND actor=?", (operation_id, actor)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return {"id": row["id"], "scope": row["scope"], "status": row["status"],
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "error_code": row["error_code"], "result": json.loads(row["result_json"]) if row["result_json"] else None}

    def complete(self, operation_id, result):
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        with self._connect() as connection:
            connection.execute("UPDATE request_operations SET status='completed', result_json=?, error_code=NULL, updated_at=? WHERE id=?", (encoded, utc_now(), operation_id))

    def execute(self, actor, scope, key, request_fingerprint, callback, *, recover=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("Idempotency-Key must contain 1-128 printable ASCII characters without spaces")
        key_hash = sha256(key.encode()).hexdigest()
        owner = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM request_operations WHERE actor=? AND scope=? AND key_hash=?", (actor, scope, key_hash)).fetchone()
            if row is None:
                # Bound active synchronous paid operations, independently of
                # thread-pool capacity. Replays are still allowed at capacity.
                if scope.startswith("ask:") and connection.execute("SELECT COUNT(*) FROM request_operations WHERE scope LIKE 'ask:%' AND status='processing'").fetchone()[0] >= 2:
                    raise OperationConflictError("paid_operation_capacity", None)
                operation_id = str(uuid4())
                connection.execute("INSERT INTO request_operations VALUES (?, ?, ?, ?, ?, 'processing', NULL, NULL, ?, ?)",
                                   (operation_id, actor, scope, key_hash, request_fingerprint, utc_now(), utc_now()))
                owner = True
            else:
                operation_id = row["id"]
                if row["fingerprint"] != request_fingerprint:
                    raise OperationConflictError("idempotency_key_payload_conflict", operation_id)
                if row["status"] == "completed":
                    return json.loads(row["result_json"]), operation_id, True
                if row["status"] == "retryable":
                    connection.execute("UPDATE request_operations SET status='processing', updated_at=? WHERE id=?", (utc_now(), operation_id))
                    owner = True
        if not owner:
            # Upload and task creation use the same immutable UUID. Even if the
            # response checkpoint was lost, its existing task can be recovered.
            result = recover(operation_id) if recover is not None else None
            if result is not None:
                self.complete(operation_id, result)
                return result, operation_id, True
            raise OperationConflictError("operation_" + row["status"], operation_id)
        try:
            result = callback(operation_id)
            self.complete(operation_id, result)
            return result, operation_id, False
        except BaseException as exc:
            # Only an explicit local upload-capacity rejection is proven to
            # precede any effects. A paid provider timeout may already be billed.
            status = "retryable" if scope == "upload" and getattr(exc, "status_code", None) == 429 else "failed_or_uncertain"
            with self._connect() as connection:
                connection.execute("UPDATE request_operations SET status=?, error_code=?, updated_at=? WHERE id=? AND status != 'completed'", (status, type(exc).__name__, utc_now(), operation_id))
            raise
