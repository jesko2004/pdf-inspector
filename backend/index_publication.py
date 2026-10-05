"""Durable publication pointers and immutable retrieval snapshots."""

import json

from .migrations import Migration


INDEX_PUBLICATION_MIGRATION = Migration(
    5, "atomic_index_publication", """
    ALTER TABLE knowledge_bases ADD COLUMN index_rebuild_pending INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE published_knowledge_bases (
        knowledge_base_id TEXT PRIMARY KEY REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        config_json TEXT NOT NULL,
        published_at TEXT NOT NULL
    );
    CREATE TABLE published_document_indexes (
        document_id TEXT PRIMARY KEY REFERENCES knowledge_documents(id) ON DELETE CASCADE,
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        document_json TEXT NOT NULL,
        chunks_json TEXT NOT NULL,
        published_at TEXT NOT NULL
    );
    CREATE INDEX published_document_kb_idx ON published_document_indexes(knowledge_base_id);
    """,
)


def initialize_publications(store, connection):
    """Seed legacy ready documents once; never publish a partial generation."""
    for row in connection.execute("SELECT * FROM knowledge_bases").fetchall():
        connection.execute(
            "INSERT OR IGNORE INTO published_knowledge_bases VALUES (?, ?, ?)",
            (row["id"], json.dumps(dict(row)), row["updated_at"]),
        )
    documents = connection.execute(
        "SELECT d.* FROM knowledge_documents d LEFT JOIN published_document_indexes p ON p.document_id = d.id "
        "WHERE d.status = 'ready' AND p.document_id IS NULL"
    ).fetchall()
    for row in documents:
        # Reindexing can leave individual staging documents ready at restart.
        pending = connection.execute("SELECT index_rebuild_pending FROM knowledge_bases WHERE id = ?", (row["knowledge_base_id"],)).fetchone()
        if not pending[0]:
            _save_document(store, connection, row, row["updated_at"])


def _save_document(store, connection, row, now):
    chunks = [store._public_chunk(dict(c)) for c in connection.execute(
        "SELECT * FROM knowledge_chunks WHERE document_id = ? ORDER BY page_start, id", (row["id"],)
    ).fetchall()]
    if any(c["status"] != "indexed" for c in chunks):
        return
    connection.execute(
        "INSERT INTO published_document_indexes VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(document_id) DO UPDATE SET document_json = excluded.document_json, "
        "chunks_json = excluded.chunks_json, published_at = excluded.published_at",
        (row["id"], row["knowledge_base_id"], json.dumps(store._public_document(dict(row)), ensure_ascii=False),
         json.dumps(chunks, ensure_ascii=False), now),
    )


def publish_ready(store, connection, document_id, now):
    row = connection.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
    if row is None or row["status"] != "ready":
        return
    kb = connection.execute("SELECT * FROM knowledge_bases WHERE id = ?", (row["knowledge_base_id"],)).fetchone()
    connection.execute("INSERT OR IGNORE INTO published_knowledge_bases VALUES (?, ?, ?)",
                       (kb["id"], json.dumps(dict(kb)), now))
    if kb["index_rebuild_pending"]:
        unfinished = connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE knowledge_base_id = ? AND status != 'ready'",
            (kb["id"],),
        ).fetchone()[0]
        if unfinished:
            return
        for document in connection.execute("SELECT * FROM knowledge_documents WHERE knowledge_base_id = ?", (kb["id"],)).fetchall():
            _save_document(store, connection, document, now)
        connection.execute("UPDATE knowledge_bases SET index_rebuild_pending = 0 WHERE id = ?", (kb["id"],))
        config = dict(kb)
        config["index_rebuild_pending"] = 0
        connection.execute(
            "INSERT INTO published_knowledge_bases VALUES (?, ?, ?) "
            "ON CONFLICT(knowledge_base_id) DO UPDATE SET config_json = excluded.config_json, published_at = excluded.published_at",
            (kb["id"], json.dumps(config), now),
        )
        return
    # A versioned replacement retires the prior published document in this same
    # transaction. Preparing or failing a new document leaves its pointer intact.
    previous = connection.execute(
        "SELECT * FROM published_document_indexes WHERE knowledge_base_id = ? AND document_id != ? "
        "AND json_extract(document_json, '$.document_key') = ? "
        "AND json_extract(document_json, '$.is_current') = 1",
        (kb["id"], document_id, row["logical_document_key"]),
    ).fetchall()
    for old in previous:
        document = json.loads(old["document_json"])
        document["is_current"] = False
        end = row["effective_from"] or now
        document["effective_to"] = min(document.get("effective_to") or end, end)
        connection.execute("UPDATE published_document_indexes SET document_json = ? WHERE document_id = ?",
                           (json.dumps(document, ensure_ascii=False), old["document_id"]))
        connection.execute("UPDATE knowledge_documents SET is_current = 0, effective_to = ? WHERE id = ?",
                           (document["effective_to"], old["document_id"]))
    _save_document(store, connection, row, now)


def retrieval_snapshot(store, knowledge_base_id, *, document_ids, versions, as_of, include_historical):
    from .knowledge_store import KnowledgeBaseNotFoundError
    from .task_store import utc_now

    with store._connect() as connection:
        connection.execute("BEGIN")
        current = connection.execute("SELECT * FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)).fetchone()
        if current is None:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        published = connection.execute("SELECT config_json FROM published_knowledge_bases WHERE knowledge_base_id = ?", (knowledge_base_id,)).fetchone()
        config = json.loads(published[0]) if published else dict(current)
        # Descriptive KB edits do not require a new index.
        config.update(name=current["name"], description=current["description"])
        rows = connection.execute("SELECT * FROM published_document_indexes WHERE knowledge_base_id = ? ORDER BY document_id", (knowledge_base_id,)).fetchall()
        candidates = []
        moment = as_of or utc_now()
        for row in rows:
            document = json.loads(row["document_json"])
            if document_ids and document["id"] not in document_ids:
                continue
            if versions and document.get("version") not in versions:
                continue
            if as_of is not None or not include_historical:
                if document.get("effective_from") and document["effective_from"] > moment:
                    continue
                if document.get("effective_to") and document["effective_to"] <= moment:
                    continue
            candidates.append((document, row))
        if as_of is None and not include_historical:
            # A ready version dated in the future must not hide the currently
            # effective old version before its business activation date.
            active = {}
            for document, row in candidates:
                key = document["document_key"]
                rank = (document["is_current"], document.get("effective_from") or "", row["published_at"])
                if key not in active or rank > active[key][0]:
                    active[key] = (rank, document, row)
            candidates = [(document, row) for _rank, document, row in active.values()]
        documents = {document["id"]: document for document, _row in candidates}
        chunks = [chunk for _document, row in candidates for chunk in json.loads(row["chunks_json"])]
        return config, documents, chunks
