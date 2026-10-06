"""Bounded persistent deletion retries for the single executor."""
from threading import Event, Thread
from time import time

from .migrations import Migration

DELETION_RETRY_MIGRATION = Migration(7, "bounded_deletion_retries", """
    ALTER TABLE vector_deletions ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE vector_deletions ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0;
    ALTER TABLE vector_deletions ADD COLUMN error_code TEXT;
    ALTER TABLE vector_deletions ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0;
""")


def record_failure(store, chunk_ids, error):
    permanent = isinstance(error, (PermissionError, ValueError)) or type(error).__name__ in {
        "InvalidPassword", "InsufficientPrivilege", "UndefinedTable"}
    with store._connect() as connection:
        for chunk_id in chunk_ids:
            row = connection.execute("SELECT attempts FROM vector_deletions WHERE chunk_id=?", (chunk_id,)).fetchone()
            if row is None:
                continue
            attempts = row[0] + 1
            connection.execute("UPDATE vector_deletions SET attempts=?, next_attempt_at=?, error_code=?, blocked=? WHERE chunk_id=?",
                (attempts, time() + min(60, 2 ** min(attempts, 6)), type(error).__name__, int(permanent or attempts >= 5), chunk_id))


def deletion_status(store):
    with store._connect() as connection:
        counts = connection.execute("SELECT COUNT(*), COALESCE(SUM(blocked), 0), MIN(created_at) FROM vector_deletions").fetchone()
        rows = connection.execute("SELECT chunk_id, knowledge_base_id, attempts, next_attempt_at, error_code, blocked, created_at FROM vector_deletions ORDER BY created_at, chunk_id LIMIT 100").fetchall()
    return {"pending": counts[0], "blocked": counts[1], "oldest_created_at": counts[2], "items": [dict(row) for row in rows], "limit": 100}


def reset_deletions(store):
    with store._connect() as connection:
        connection.execute("UPDATE vector_deletions SET attempts=0, next_attempt_at=0, error_code=NULL, blocked=0")


class MaintenanceWorker:
    def __init__(self, callback):
        self.stop = Event()
        self.thread = Thread(target=self._run, args=(callback,), name="knowledge-maintenance", daemon=True)
        self.thread.start()

    def _run(self, callback):
        while not self.stop.wait(5):
            callback()

    def close(self):
        self.stop.set()
        self.thread.join()
