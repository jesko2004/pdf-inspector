"""Retain complete publications, pin readers and reclaim unreferenced vectors."""

from contextlib import contextmanager
from functools import wraps
from hashlib import sha256
import json
from uuid import uuid4

from .execution_lock import SingleExecutorLock
from .migrations import Migration
from .task_store import utc_now


INDEX_LIFECYCLE_MIGRATION = Migration(6, "index_lifecycle", """
    CREATE TABLE index_generations (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE,
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        config_json TEXT NOT NULL,
        documents_json TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX index_generations_kb_idx ON index_generations(knowledge_base_id, sequence);
    CREATE TABLE index_generation_state (
        knowledge_base_id TEXT PRIMARY KEY REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        active_generation_id TEXT NOT NULL,
        rolled_back INTEGER NOT NULL DEFAULT 0
    );
    -- Readers remain protected even after the KB is explicitly deleted.
    CREATE TABLE retrieval_leases (
        id TEXT PRIMARY KEY,
        knowledge_base_id TEXT NOT NULL,
        chunk_ids_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE index_lifecycle_events (
        id TEXT PRIMARY KEY,
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        action TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    ALTER TABLE vector_deletions ADD COLUMN knowledge_base_id TEXT;
""")


class IndexGenerationNotFoundError(KeyError):
    pass


def _require_kb(connection, knowledge_base_id):
    from .knowledge_store import KnowledgeBaseNotFoundError
    row = connection.execute("SELECT * FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)).fetchone()
    if row is None:
        raise KnowledgeBaseNotFoundError(knowledge_base_id)
    return row


def publication_frozen(connection, knowledge_base_id):
    row = connection.execute("SELECT rolled_back FROM index_generation_state WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
    return bool(row and row[0])


def assert_mutation_allowed(connection, knowledge_base_id):
    from .knowledge_store import InvalidKnowledgeStateError
    kb = _require_kb(connection, knowledge_base_id)
    if publication_frozen(connection, knowledge_base_id) and not kb["index_rebuild_pending"]:
        raise InvalidKnowledgeStateError("publication was rolled back; complete a full reindex before ingesting or retrying documents")


def _event(connection, knowledge_base_id, action, detail):
    connection.execute("INSERT INTO index_lifecycle_events VALUES (?, ?, ?, ?, ?)",
                       (str(uuid4()), knowledge_base_id, action, json.dumps(detail), utc_now()))


def capture_generation(connection, knowledge_base_id, now, *, reset_override=False):
    kb = _require_kb(connection, knowledge_base_id)
    pointer = connection.execute("SELECT config_json FROM published_knowledge_bases WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
    config = pointer[0] if pointer else json.dumps(dict(kb))
    if not pointer:
        connection.execute("INSERT INTO published_knowledge_bases VALUES (?, ?, ?)", (knowledge_base_id, config, now))
    documents = [dict(r) for r in connection.execute(
        "SELECT * FROM published_document_indexes WHERE knowledge_base_id = ? ORDER BY document_id", (knowledge_base_id,)).fetchall()]
    encoded = json.dumps(documents, ensure_ascii=False, sort_keys=True)
    fingerprint = sha256((config + "\0" + encoded).encode()).hexdigest()
    state = connection.execute("SELECT * FROM index_generation_state WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
    current = connection.execute("SELECT fingerprint FROM index_generations WHERE id = ?", (state["active_generation_id"],)).fetchone() if state else None
    if current and current[0] == fingerprint:
        if reset_override:
            connection.execute("UPDATE index_generation_state SET rolled_back = 0 WHERE knowledge_base_id = ?", (knowledge_base_id,))
        return state["active_generation_id"]
    generation_id = str(uuid4())
    connection.execute("INSERT INTO index_generations (id, knowledge_base_id, config_json, documents_json, fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (generation_id, knowledge_base_id, config, encoded, fingerprint, now))
    connection.execute("INSERT INTO index_generation_state VALUES (?, ?, ?) ON CONFLICT(knowledge_base_id) DO UPDATE SET active_generation_id=excluded.active_generation_id, rolled_back=excluded.rolled_back",
                       (knowledge_base_id, generation_id, 0 if reset_override else int(bool(state and state["rolled_back"]))))
    return generation_id


def initialize_lifecycle(connection):
    for row in connection.execute("SELECT id FROM knowledge_bases").fetchall():
        if connection.execute("SELECT 1 FROM index_generation_state WHERE knowledge_base_id = ?", (row[0],)).fetchone() is None:
            capture_generation(connection, row[0], utc_now())


def _lease_path(store, lease_id):
    return store.database_path.parent / "index-leases" / (lease_id + ".lock")


@contextmanager
def leased_snapshot(store, knowledge_base_id, **filters):
    from .index_publication import retrieval_snapshot
    lease_id = str(uuid4())
    path = _lease_path(store, lease_id)
    lock = None
    try:
        with store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = retrieval_snapshot(store, knowledge_base_id, _connection=connection, **filters)
            lock = SingleExecutorLock(path)
            connection.execute("INSERT INTO retrieval_leases VALUES (?, ?, ?, ?)",
                               (lease_id, knowledge_base_id, json.dumps([c["id"] for c in snapshot[2]]), utc_now()))
        yield snapshot
    finally:
        if lock is not None:
            try:
                with store._connect() as connection:
                    connection.execute("DELETE FROM retrieval_leases WHERE id = ?", (lease_id,))
            finally:
                lock.close()
                # Never unlink after a failed metadata release: missing files
                # fail closed so a remaining lease still protects its vectors.
            if path.exists():
                path.unlink()


def leased_retrieval(function):
    @wraps(function)
    def wrapped(self, knowledge_base_id, *args, **kwargs):
        filters = {"document_ids": kwargs.get("document_ids", []), "versions": kwargs.get("versions") or [],
                   "as_of": kwargs.get("as_of"), "include_historical": kwargs.get("include_historical", False)}
        try:
            with leased_snapshot(self.store, knowledge_base_id, **filters) as snapshot:
                kwargs["_snapshot"] = snapshot
                return function(self, knowledge_base_id, *args, **kwargs)
        finally:
            # A completed reader can release pending explicit deletions.
            self._drain_vector_deletions_best_effort()
    return wrapped


def _live_lease_chunks(store, connection, *, reap):
    protected = set()
    for row in connection.execute("SELECT * FROM retrieval_leases").fetchall():
        path = _lease_path(store, row["id"])
        if not path.is_file():
            protected.update(json.loads(row["chunk_ids_json"]))
            continue
        try:
            probe = SingleExecutorLock(path)
        except (OSError, RuntimeError):
            protected.update(json.loads(row["chunk_ids_json"]))
            continue
        # The operating system has released ownership, including after a crash.
        try:
            if reap:
                connection.execute("DELETE FROM retrieval_leases WHERE id = ?", (row["id"],))
        finally:
            probe.close()
        # Leave inert files in place until a future maintenance pass; a failed
        # transaction must never turn a stale row into a missing-file lease.
    return protected


def _structural_chunks(connection):
    protected = {r[0] for r in connection.execute("SELECT id FROM knowledge_chunks")}
    for row in connection.execute("SELECT chunks_json FROM published_document_indexes"):
        protected.update(c["id"] for c in json.loads(row[0]))
    for row in connection.execute("SELECT documents_json FROM index_generations"):
        for document in json.loads(row[0]):
            protected.update(c["id"] for c in json.loads(document["chunks_json"]))
    return protected


def queue_deletions(connection, knowledge_base_id, chunk_ids):
    connection.executemany("INSERT OR IGNORE INTO vector_deletions (chunk_id, created_at, knowledge_base_id) VALUES (?, ?, ?)",
                           [(cid, utc_now(), knowledge_base_id) for cid in chunk_ids])


def invalidate_document_generations(connection, knowledge_base_id, document_id):
    ids = [r["id"] for r in connection.execute("SELECT id, documents_json FROM index_generations WHERE knowledge_base_id = ?", (knowledge_base_id,))
           if any(d["document_id"] == document_id for d in json.loads(r["documents_json"]))]
    connection.executemany("DELETE FROM index_generations WHERE id = ?", [(i,) for i in ids])


def generation_summary(store, knowledge_base_id):
    with store._connect() as connection:
        _require_kb(connection, knowledge_base_id)
        state = connection.execute("SELECT * FROM index_generation_state WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
        items = []
        for row in connection.execute("SELECT * FROM index_generations WHERE knowledge_base_id = ? ORDER BY sequence DESC", (knowledge_base_id,)):
            config = json.loads(row["config_json"])
            documents = json.loads(row["documents_json"])
            items.append({"id": row["id"], "created_at": row["created_at"], "current": row["id"] == state["active_generation_id"],
                          "embedding_provider": config["embedding_provider"], "embedding_model": config["embedding_model"],
                          "embedding_dimensions": config["embedding_dimensions"], "document_count": len(documents),
                          "chunk_count": sum(len(json.loads(d["chunks_json"])) for d in documents)})
        return {"knowledge_base_id": knowledge_base_id, "active_generation_id": state["active_generation_id"],
                "staging_requires_reindex": bool(state["rolled_back"]), "items": items}


def collect_garbage(store, knowledge_base_id, vector_ids, *, keep_generations, dry_run, expected_generation_id):
    from .knowledge_store import InvalidKnowledgeStateError
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_kb(connection, knowledge_base_id)
        state = connection.execute("SELECT * FROM index_generation_state WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
        if expected_generation_id is not None and expected_generation_id != state["active_generation_id"]:
            raise InvalidKnowledgeStateError("published generation changed; obtain a new garbage collection plan")
        rows = connection.execute("SELECT * FROM index_generations WHERE knowledge_base_id = ? ORDER BY sequence DESC", (knowledge_base_id,)).fetchall()
        retained = {r["id"] for r in rows[:keep_generations]} | {state["active_generation_id"]}
        pruned = [r["id"] for r in rows if r["id"] not in retained]
        protected = {r[0] for r in connection.execute("SELECT id FROM knowledge_chunks")}
        for row in connection.execute("SELECT chunks_json FROM published_document_indexes"):
            protected.update(c["id"] for c in json.loads(row[0]))
        # Include all other KBs too: the outbox and physical identities are global.
        for row in connection.execute("SELECT * FROM index_generations"):
            if row["knowledge_base_id"] != knowledge_base_id or row["id"] in retained:
                for document in json.loads(row["documents_json"]):
                    protected.update(c["id"] for c in json.loads(document["chunks_json"]))
        live = _live_lease_chunks(store, connection, reap=not dry_run)
        orphaned = sorted(set(vector_ids) - protected)
        reclaimable = sorted(set(vector_ids) - protected - live)
        result = {"knowledge_base_id": knowledge_base_id, "active_generation_id": state["active_generation_id"],
                  "dry_run": dry_run, "retained_generation_ids": sorted(retained), "pruned_generation_ids": pruned,
                  "reclaimable_vectors": len(reclaimable), "sample_chunk_ids": reclaimable[:100],
                  "deferred_vectors": len(set(orphaned) & live),
                  "protected_by_readers": len(set(vector_ids) & live)}
        if not dry_run:
            connection.executemany("DELETE FROM index_generations WHERE id = ?", [(i,) for i in pruned])
            queue_deletions(connection, knowledge_base_id, orphaned)
            _event(connection, knowledge_base_id, "garbage_collection", result)
        return result


def drain_deletions(store, delete_locked, *, knowledge_base_id=None, scheduled=False):
    from time import time
    from .maintenance import record_failure
    deleted = 0
    while True:
        eligible = []
        try:
            deleted += _drain_one(store, delete_locked, knowledge_base_id, scheduled, time(), eligible)
        except Exception as exc:
            record_failure(store, eligible, exc)
            raise
        if scheduled or not eligible:
            return deleted


def _drain_one(store, delete_locked, knowledge_base_id, scheduled, now, eligible):
        with store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT chunk_id, blocked, next_attempt_at FROM vector_deletions" +
                (" WHERE knowledge_base_id = ?" if knowledge_base_id is not None else "") + " ORDER BY created_at, chunk_id",
                (knowledge_base_id,) if knowledge_base_id is not None else ()).fetchall()
            if not rows:
                return 0
            structural = _structural_chunks(connection)
            live = _live_lease_chunks(store, connection, reap=True)
            # Reused physical identities no longer belong to the deletion task.
            connection.executemany("DELETE FROM vector_deletions WHERE chunk_id = ?", [(r[0],) for r in rows if r[0] in structural])
            eligible.extend([r[0] for r in rows if r[0] not in structural and r[0] not in live
                and (not scheduled or (not r[1] and r[2] <= now))][:1000])
            if not eligible:
                return 0
            # SQLite may share this very database. The adapter then reuses this
            # transaction; remote stores delete idempotently before outbox ack.
            delete_locked(connection, eligible)
            connection.executemany("DELETE FROM vector_deletions WHERE chunk_id = ?", [(i,) for i in eligible])
            return len(eligible)


def rollback_generation(store, knowledge_base_id, generation_id, expected_generation_id, reason, vector_ids):
    from .knowledge_store import InvalidKnowledgeStateError
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_kb(connection, knowledge_base_id)
        state = connection.execute("SELECT * FROM index_generation_state WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
        if state["active_generation_id"] != expected_generation_id:
            raise InvalidKnowledgeStateError("published generation changed; review the current generation before rollback")
        row = connection.execute("SELECT * FROM index_generations WHERE id = ? AND knowledge_base_id = ?", (generation_id, knowledge_base_id)).fetchone()
        if row is None:
            raise IndexGenerationNotFoundError(generation_id)
        busy = connection.execute("SELECT COUNT(*) FROM knowledge_documents WHERE knowledge_base_id = ? AND status IN ('queued', 'indexing')", (knowledge_base_id,)).fetchone()[0]
        if busy:
            raise InvalidKnowledgeStateError("cannot roll back while indexing is active")
        documents = json.loads(row["documents_json"])
        existing = {r[0] for r in connection.execute("SELECT id FROM knowledge_documents WHERE knowledge_base_id = ?", (knowledge_base_id,))}
        if any(d["document_id"] not in existing for d in documents):
            raise InvalidKnowledgeStateError("generation refers to deleted documents")
        required = {c["id"] for d in documents for c in json.loads(d["chunks_json"])}
        if required - set(vector_ids):
            raise InvalidKnowledgeStateError("generation vectors are missing; rollback refused")
        if generation_id == state["active_generation_id"]:
            return {"active_generation_id": generation_id, "changed": False,
                    "staging_requires_reindex": bool(state["rolled_back"])}
        connection.execute("DELETE FROM published_document_indexes WHERE knowledge_base_id = ?", (knowledge_base_id,))
        connection.executemany("INSERT INTO published_document_indexes VALUES (?, ?, ?, ?, ?)",
                               [(d["document_id"], knowledge_base_id, d["document_json"], d["chunks_json"], d["published_at"]) for d in documents])
        connection.execute("UPDATE published_knowledge_bases SET config_json = ?, published_at = ? WHERE knowledge_base_id = ?",
                           (row["config_json"], utc_now(), knowledge_base_id))
        connection.execute("UPDATE knowledge_bases SET index_rebuild_pending = 0 WHERE id = ?", (knowledge_base_id,))
        connection.execute("UPDATE index_generation_state SET active_generation_id = ?, rolled_back = 1 WHERE knowledge_base_id = ?", (generation_id, knowledge_base_id))
        _event(connection, knowledge_base_id, "rollback", {"from": expected_generation_id, "to": generation_id, "reason": reason})
        return {"active_generation_id": generation_id, "changed": True, "staging_requires_reindex": True}
