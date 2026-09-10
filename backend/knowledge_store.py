"""SQLite metadata store for knowledge bases, documents, chunks, and batches."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .migrations import Migration, apply_migrations
from .task_store import utc_now

DOCUMENT_STATUSES = {"queued", "indexing", "ready", "partial", "failed"}
BATCH_STATUSES = {"queued", "processing", "completed", "failed"}


class KnowledgeBaseNotFoundError(KeyError):
    pass


class KnowledgeDocumentNotFoundError(KeyError):
    pass


class KnowledgeConflictError(ValueError):
    pass


class InvalidKnowledgeStateError(ValueError):
    pass


class EmbeddingBatchNotFoundError(KeyError):
    pass


class KnowledgeAnswerNotFoundError(KeyError):
    pass


ADVANCED_RETRIEVAL_MIGRATION = Migration(
    2,
    "advanced_retrieval_versions_and_feedback",
    """
    ALTER TABLE knowledge_documents ADD COLUMN logical_document_key TEXT;
    ALTER TABLE knowledge_documents ADD COLUMN version TEXT;
    ALTER TABLE knowledge_documents ADD COLUMN effective_from TEXT;
    ALTER TABLE knowledge_documents ADD COLUMN effective_to TEXT;
    ALTER TABLE knowledge_documents ADD COLUMN is_current INTEGER NOT NULL DEFAULT 1;
    UPDATE knowledge_documents
       SET logical_document_key = document_key,
           version = COALESCE(version, '1')
     WHERE logical_document_key IS NULL;
    ALTER TABLE knowledge_chunks ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
    CREATE INDEX IF NOT EXISTS knowledge_documents_version_idx
        ON knowledge_documents(knowledge_base_id, logical_document_key, is_current);
    CREATE TABLE IF NOT EXISTS rag_answers (
        id TEXT PRIMARY KEY,
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        refused INTEGER NOT NULL,
        citations_json TEXT NOT NULL,
        retrieval_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS answer_feedback (
        id TEXT PRIMARY KEY,
        answer_id TEXT NOT NULL REFERENCES rag_answers(id) ON DELETE CASCADE,
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        helpful INTEGER NOT NULL,
        valid_citation_ids_json TEXT NOT NULL,
        invalid_citation_ids_json TEXT NOT NULL,
        correction TEXT,
        comment TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS answer_feedback_kb_idx
        ON answer_feedback(knowledge_base_id, created_at);
    """,
)


def _chunk_key(chunk: dict[str, Any]) -> str:
    section = json.dumps(
        chunk.get("section_path", []), ensure_ascii=False, separators=(",", ":")
    )
    content_hash = (
        chunk.get("content_hash")
        or hashlib.sha256(
            str(chunk.get("text") or chunk.get("markdown") or "").encode("utf-8")
        ).hexdigest()
    )
    pages = json.dumps(chunk.get("pages", []), separators=(",", ":"))
    identity = f"{chunk.get('kind', 'text')}\0{section}\0{pages}\0{content_hash}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class KnowledgeStore:
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id)
                        ON DELETE CASCADE,
                    task_id TEXT NOT NULL,
                    document_key TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    chunk_set_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'indexing', 'ready', 'partial', 'failed')
                    ),
                    generation INTEGER NOT NULL DEFAULT 1,
                    total_chunks INTEGER NOT NULL DEFAULT 0,
                    indexed_chunks INTEGER NOT NULL DEFAULT 0,
                    failed_chunks INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    indexed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(knowledge_base_id, document_key),
                    UNIQUE(knowledge_base_id, content_hash)
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES knowledge_documents(id)
                        ON DELETE CASCADE,
                    source_chunk_id TEXT NOT NULL,
                    chunk_key TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    text TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    pages_json TEXT NOT NULL,
                    section_path_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'indexed', 'failed')
                    ),
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(document_id, chunk_key)
                );

                CREATE TABLE IF NOT EXISTS embedding_batches (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES knowledge_documents(id)
                        ON DELETE CASCADE,
                    generation INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'processing', 'completed', 'failed')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    chunk_ids_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vector_deletions (
                    chunk_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS knowledge_documents_kb_idx
                    ON knowledge_documents(knowledge_base_id, updated_at);
                CREATE INDEX IF NOT EXISTS knowledge_chunks_document_idx
                    ON knowledge_chunks(document_id, status);
                CREATE INDEX IF NOT EXISTS embedding_batches_status_idx
                    ON embedding_batches(status, created_at);
                """
            )
            apply_migrations(
                connection,
                "knowledge",
                (
                    Migration(1, "baseline_knowledge_schema", "SELECT 1;"),
                    ADVANCED_RETRIEVAL_MIGRATION,
                ),
            )

    def batch_status_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM embedding_batches GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def create_knowledge_base(
        self,
        *,
        name: str,
        description: str,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> dict[str, Any]:
        knowledge_base_id = str(uuid4())
        now = utc_now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO knowledge_bases (
                        id, name, description, embedding_provider, embedding_model,
                        embedding_dimensions, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        knowledge_base_id,
                        name,
                        description,
                        embedding_provider,
                        embedding_model,
                        embedding_dimensions,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise KnowledgeConflictError(
                f"knowledge base name already exists: {name}"
            ) from exc
        return self.get_knowledge_base(knowledge_base_id)

    def get_knowledge_base(self, knowledge_base_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT kb.*,
                       COUNT(DISTINCT d.id) AS document_count,
                       COUNT(c.id) AS chunk_count
                  FROM knowledge_bases kb
             LEFT JOIN knowledge_documents d ON d.knowledge_base_id = kb.id
             LEFT JOIN knowledge_chunks c ON c.document_id = d.id
                 WHERE kb.id = ?
              GROUP BY kb.id
                """,
                (knowledge_base_id,),
            ).fetchone()
        if row is None:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        return dict(row)

    def list_knowledge_bases(self, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT kb.*,
                       COUNT(DISTINCT d.id) AS document_count,
                       COUNT(c.id) AS chunk_count
                  FROM knowledge_bases kb
             LEFT JOIN knowledge_documents d ON d.knowledge_base_id = kb.id
             LEFT JOIN knowledge_chunks c ON c.document_id = d.id
              GROUP BY kb.id
              ORDER BY kb.created_at DESC
                 LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_knowledge_base(
        self, knowledge_base_id: str, *, name: str, description: str
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE knowledge_bases
                       SET name = ?, description = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (name, description, utc_now(), knowledge_base_id),
                )
        except sqlite3.IntegrityError as exc:
            raise KnowledgeConflictError(
                f"knowledge base name already exists: {name}"
            ) from exc
        if cursor.rowcount != 1:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        return self.get_knowledge_base(knowledge_base_id)

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)
            )
        if cursor.rowcount != 1:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)

    def get_document(self, document_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)
            ).fetchone()
        if row is None:
            raise KnowledgeDocumentNotFoundError(document_id)
        return self._public_document(dict(row))

    def list_documents(
        self, knowledge_base_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        self.get_knowledge_base(knowledge_base_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_documents
                 WHERE knowledge_base_id = ?
              ORDER BY created_at DESC
                 LIMIT ? OFFSET ?
                """,
                (knowledge_base_id, limit, offset),
            ).fetchall()
        return [self._public_document(dict(row)) for row in rows]

    def eligible_document_ids(
        self,
        knowledge_base_id: str,
        *,
        document_ids: list[str],
        versions: list[str],
        as_of: str | None,
        include_historical: bool,
    ) -> list[str]:
        self.get_knowledge_base(knowledge_base_id)
        where = ["knowledge_base_id = ?"]
        parameters: list[Any] = [knowledge_base_id]
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            where.append(f"id IN ({placeholders})")
            parameters.extend(document_ids)
        if versions:
            placeholders = ",".join("?" for _ in versions)
            where.append(f"version IN ({placeholders})")
            parameters.extend(versions)
        if as_of is not None:
            where.extend(
                [
                    "(effective_from IS NULL OR effective_from <= ?)",
                    "(effective_to IS NULL OR effective_to > ?)",
                ]
            )
            parameters.extend([as_of, as_of])
        elif not include_historical:
            now = utc_now()
            where.extend(
                [
                    "is_current = 1",
                    "(effective_from IS NULL OR effective_from <= ?)",
                    "(effective_to IS NULL OR effective_to > ?)",
                ]
            )
            parameters.extend([now, now])
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM knowledge_documents WHERE " + " AND ".join(where),
                parameters,
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def has_active_documents(self, knowledge_base_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM knowledge_documents
                 WHERE knowledge_base_id = ? AND status IN ('queued', 'indexing')
                """,
                (knowledge_base_id,),
            ).fetchone()
        assert row is not None
        return bool(row["count"])

    @staticmethod
    def _public_document(row: dict[str, Any]) -> dict[str, Any]:
        row["storage_document_key"] = row["document_key"]
        row["document_key"] = row.get("logical_document_key") or row["document_key"]
        row["is_current"] = bool(row.get("is_current", 1))
        total = int(row["total_chunks"])
        completed = int(row["indexed_chunks"]) + int(row["failed_chunks"])
        row["progress"] = 100 if total == 0 else round(completed * 100 / total)
        return row

    def list_chunks(
        self, document_id: str, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.get_document(document_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_chunks
                 WHERE document_id = ?
              ORDER BY page_start, id
                 LIMIT ? OFFSET ?
                """,
                (document_id, limit, offset),
            ).fetchall()
        return [self._public_chunk(dict(row)) for row in rows]

    @staticmethod
    def _public_chunk(row: dict[str, Any]) -> dict[str, Any]:
        row["pages"] = json.loads(row.pop("pages_json"))
        row["section_path"] = json.loads(row.pop("section_path_json"))
        row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
        return row

    def list_batches(self, document_id: str) -> list[dict[str, Any]]:
        self.get_document(document_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM embedding_batches WHERE document_id = ? "
                "ORDER BY created_at, id",
                (document_id,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["chunk_ids"] = json.loads(item.pop("chunk_ids_json"))
            results.append(item)
        return results

    def prepare_document(
        self,
        *,
        knowledge_base_id: str,
        task_id: str,
        document_key: str,
        filename: str,
        content_hash: str,
        chunk_set_hash: str,
        chunks: list[dict[str, Any]],
        batch_size: int,
        version: str | None = None,
        effective_from: str | None = None,
        effective_to: str | None = None,
        preserve_history: bool = False,
    ) -> tuple[dict[str, Any], list[str], list[str], bool]:
        knowledge_base = self.get_knowledge_base(knowledge_base_id)
        now = utc_now()
        incoming = {_chunk_key(chunk): chunk for chunk in chunks}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate_row = connection.execute(
                "SELECT * FROM knowledge_documents "
                "WHERE knowledge_base_id = ? AND content_hash = ?",
                (knowledge_base_id, content_hash),
            ).fetchone()
            current_row = connection.execute(
                "SELECT * FROM knowledge_documents "
                "WHERE knowledge_base_id = ? AND logical_document_key = ? "
                "AND is_current = 1",
                (knowledge_base_id, document_key),
            ).fetchone()
            if (
                current_row is not None
                and current_row["content_hash"] == content_hash
                and current_row["chunk_set_hash"] == chunk_set_hash
            ):
                return self._public_document(dict(current_row)), [], [], True
            if duplicate_row is not None and current_row is None:
                if duplicate_row["chunk_set_hash"] == chunk_set_hash:
                    return self._public_document(dict(duplicate_row)), [], [], True
                current_row = duplicate_row
            elif duplicate_row is not None and duplicate_row["id"] != current_row["id"]:
                return self._public_document(dict(duplicate_row)), [], [], True
            if current_row is not None and current_row["status"] in {
                "queued",
                "indexing",
            }:
                raise InvalidKnowledgeStateError(
                    "cannot replace a document while indexing is active"
                )

            if (
                current_row is not None
                and preserve_history
                and current_row["content_hash"] != content_hash
            ):
                archived_key = (
                    f"{document_key}@{current_row['version'] or '1'}:"
                    f"{current_row['id'][:8]}"
                )
                connection.execute(
                    """
                    UPDATE knowledge_documents
                       SET document_key = ?, is_current = 0,
                           effective_to = COALESCE(effective_to, ?, ?), updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        archived_key,
                        effective_from,
                        now,
                        now,
                        current_row["id"],
                    ),
                )
                current_row = None

            if current_row is None:
                document_id = str(uuid4())
                generation = 1
                existing: dict[str, sqlite3.Row] = {}
                connection.execute(
                    """
                    INSERT INTO knowledge_documents (
                        id, knowledge_base_id, task_id, document_key, filename,
                        content_hash, chunk_set_hash, status, generation,
                        logical_document_key, version, effective_from, effective_to,
                        is_current, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        document_id,
                        knowledge_base_id,
                        task_id,
                        document_key,
                        filename,
                        content_hash,
                        chunk_set_hash,
                        generation,
                        document_key,
                        version or "1",
                        effective_from,
                        effective_to,
                        now,
                        now,
                    ),
                )
            else:
                document_id = current_row["id"]
                generation = int(current_row["generation"]) + 1
                existing_rows = connection.execute(
                    "SELECT * FROM knowledge_chunks WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
                existing = {row["chunk_key"]: row for row in existing_rows}
                connection.execute(
                    "DELETE FROM embedding_batches WHERE document_id = ?",
                    (document_id,),
                )

            removed_vector_ids = [
                row["id"] for key, row in existing.items() if key not in incoming
            ]
            if removed_vector_ids:
                placeholders = ",".join("?" for _ in removed_vector_ids)
                connection.execute(
                    f"DELETE FROM knowledge_chunks WHERE id IN ({placeholders})",
                    removed_vector_ids,
                )

            pending_chunk_ids = []
            indexed_count = 0
            for key, chunk in incoming.items():
                old = existing.get(key)
                retain_embedding = bool(
                    old is not None
                    and old["status"] == "indexed"
                    and old["embedding_provider"]
                    == knowledge_base["embedding_provider"]
                    and old["embedding_model"] == knowledge_base["embedding_model"]
                    and old["embedding_dimensions"]
                    == knowledge_base["embedding_dimensions"]
                )
                chunk_id = (
                    old["id"]
                    if old is not None
                    else hashlib.sha256(f"{document_id}:{key}".encode()).hexdigest()[
                        :32
                    ]
                )
                status = "indexed" if retain_embedding else "queued"
                if retain_embedding:
                    indexed_count += 1
                else:
                    pending_chunk_ids.append(chunk_id)
                    if old is not None and old["status"] == "indexed":
                        removed_vector_ids.append(chunk_id)
                chunk_text = str(chunk.get("text") or chunk.get("markdown") or "")
                values = (
                    str(chunk.get("id") or chunk_id),
                    key,
                    chunk.get("content_hash")
                    or hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                    chunk.get("kind", "text"),
                    str(chunk.get("markdown") or chunk.get("text") or ""),
                    chunk_text,
                    int(chunk.get("page_start", 1)),
                    int(chunk.get("page_end", chunk.get("page_start", 1))),
                    json.dumps(chunk.get("pages", [chunk.get("page_start", 1)])),
                    json.dumps(chunk.get("section_path", []), ensure_ascii=False),
                    json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                    status,
                    knowledge_base["embedding_provider"],
                    knowledge_base["embedding_model"],
                    knowledge_base["embedding_dimensions"],
                    now,
                )
                if old is None:
                    connection.execute(
                        """
                        INSERT INTO knowledge_chunks (
                            id, document_id, source_chunk_id, chunk_key, content_hash,
                            kind, markdown, text, page_start, page_end, pages_json,
                            section_path_json, metadata_json, status, embedding_provider,
                            embedding_model, embedding_dimensions, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (chunk_id, document_id, *values, now),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE knowledge_chunks
                           SET source_chunk_id = ?, chunk_key = ?, content_hash = ?,
                               kind = ?, markdown = ?, text = ?, page_start = ?,
                               page_end = ?, pages_json = ?, section_path_json = ?,
                               metadata_json = ?, status = ?, embedding_provider = ?, embedding_model = ?,
                               embedding_dimensions = ?, error_code = NULL,
                               error_message = NULL, updated_at = ?
                         WHERE id = ?
                        """,
                        (*values, chunk_id),
                    )

            if removed_vector_ids:
                connection.executemany(
                    "INSERT OR IGNORE INTO vector_deletions (chunk_id, created_at) "
                    "VALUES (?, ?)",
                    [(chunk_id, now) for chunk_id in set(removed_vector_ids)],
                )

            batch_ids = self._insert_batches(
                connection, document_id, generation, pending_chunk_ids, batch_size, now
            )
            status = "queued" if pending_chunk_ids else "ready"
            indexed_at = now if status == "ready" else None
            connection.execute(
                """
                UPDATE knowledge_documents
                   SET task_id = ?, filename = ?, content_hash = ?, chunk_set_hash = ?,
                       status = ?,
                       generation = ?, total_chunks = ?, indexed_chunks = ?,
                       failed_chunks = 0, error_code = NULL, error_message = NULL,
                       indexed_at = ?, version = COALESCE(?, version),
                       effective_from = COALESCE(?, effective_from),
                       effective_to = COALESCE(?, effective_to), updated_at = ?
                 WHERE id = ?
                """,
                (
                    task_id,
                    filename,
                    content_hash,
                    chunk_set_hash,
                    status,
                    generation,
                    len(incoming),
                    indexed_count,
                    indexed_at,
                    version,
                    effective_from,
                    effective_to,
                    now,
                    document_id,
                ),
            )
        return (
            self.get_document(document_id),
            batch_ids,
            sorted(set(removed_vector_ids)),
            False,
        )

    def pending_vector_deletions(self, limit: int = 1000) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunk_id FROM vector_deletions ORDER BY created_at, chunk_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["chunk_id"] for row in rows]

    def record_answer(self, answer: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO rag_answers(
                    id, knowledge_base_id, question, answer, refused,
                    citations_json, retrieval_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    answer["answer_id"],
                    answer["knowledge_base_id"],
                    answer["question"],
                    answer["answer"],
                    int(answer["refused"]),
                    json.dumps(answer["citations"], ensure_ascii=False),
                    json.dumps(answer["retrieval"], ensure_ascii=False),
                    utc_now(),
                ),
            )

    def create_feedback(
        self, knowledge_base_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        feedback_id = str(uuid4())
        now = utc_now()
        with self._connect() as connection:
            answer = connection.execute(
                "SELECT * FROM rag_answers WHERE id = ? AND knowledge_base_id = ?",
                (payload["answer_id"], knowledge_base_id),
            ).fetchone()
            if answer is None:
                raise KnowledgeAnswerNotFoundError(payload["answer_id"])
            citation_ids = {
                citation.get("chunk_id")
                for citation in json.loads(answer["citations_json"])
            }
            supplied = set(payload.get("valid_citation_ids", [])).union(
                payload.get("invalid_citation_ids", [])
            )
            if not supplied.issubset(citation_ids):
                raise ValueError(
                    "feedback contains citation IDs not used by the answer"
                )
            connection.execute(
                """
                INSERT INTO answer_feedback(
                    id, answer_id, knowledge_base_id, helpful,
                    valid_citation_ids_json, invalid_citation_ids_json,
                    correction, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    payload["answer_id"],
                    knowledge_base_id,
                    int(payload["helpful"]),
                    json.dumps(payload.get("valid_citation_ids", [])),
                    json.dumps(payload.get("invalid_citation_ids", [])),
                    payload.get("correction"),
                    payload.get("comment"),
                    now,
                ),
            )
        return self.get_feedback(feedback_id)

    def get_feedback(self, feedback_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM answer_feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
        if row is None:
            raise KeyError(feedback_id)
        item = dict(row)
        item["helpful"] = bool(item["helpful"])
        item["valid_citation_ids"] = json.loads(item.pop("valid_citation_ids_json"))
        item["invalid_citation_ids"] = json.loads(item.pop("invalid_citation_ids_json"))
        return item

    def list_feedback(
        self, knowledge_base_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        self.get_knowledge_base(knowledge_base_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM answer_feedback WHERE knowledge_base_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (knowledge_base_id, limit, offset),
            ).fetchall()
        return [self.get_feedback(row["id"]) for row in rows]

    def feedback_summary(
        self,
        knowledge_base_id: str,
        *,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> dict[str, Any]:
        self.get_knowledge_base(knowledge_base_id)
        where = ["f.knowledge_base_id = ?"]
        parameters: list[Any] = [knowledge_base_id]
        if created_from is not None:
            where.append("f.created_at >= ?")
            parameters.append(created_from)
        if created_to is not None:
            where.append("f.created_at < ?")
            parameters.append(created_to)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(helpful) AS helpful,
                       SUM(json_array_length(valid_citation_ids_json)) AS valid_citations,
                       SUM(json_array_length(invalid_citation_ids_json)) AS invalid_citations,
                       SUM(a.refused) AS refusals
                  FROM answer_feedback f
                  JOIN rag_answers a ON a.id = f.answer_id
                 WHERE {" AND ".join(where)}
                """,
                parameters,
            ).fetchone()
        assert row is not None
        total = int(row["total"] or 0)
        valid = int(row["valid_citations"] or 0)
        invalid = int(row["invalid_citations"] or 0)
        return {
            "knowledge_base_id": knowledge_base_id,
            "created_from": created_from,
            "created_to": created_to,
            "feedback_count": total,
            "helpful_rate": round(int(row["helpful"] or 0) / total, 6)
            if total
            else None,
            "citation_precision": round(valid / (valid + invalid), 6)
            if valid + invalid
            else None,
            "refusal_rate": round(int(row["refusals"] or 0) / total, 6)
            if total
            else None,
        }

    def feedback_evaluation_cases(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        from .advanced_retrieval import redact_feedback_text

        self.get_knowledge_base(knowledge_base_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.*, a.question, a.citations_json
                  FROM answer_feedback f
                  JOIN rag_answers a ON a.id = f.answer_id
                 WHERE f.knowledge_base_id = ? AND f.helpful = 1
              ORDER BY f.created_at, f.id
                """,
                (knowledge_base_id,),
            ).fetchall()
        cases = []
        for row in rows:
            valid_ids = set(json.loads(row["valid_citation_ids_json"]))
            expected = []
            for citation in json.loads(row["citations_json"]):
                if citation.get("chunk_id") not in valid_ids:
                    continue
                source = {
                    "document_id": citation["document_id"],
                    "pages": citation.get("pages", []),
                }
                if source not in expected:
                    expected.append(source)
            if not expected:
                continue
            cases.append(
                {
                    "id": f"feedback-{row['id']}",
                    "query": redact_feedback_text(row["question"]),
                    "expected_sources": expected,
                    "expected_answer": redact_feedback_text(row["correction"] or ""),
                }
            )
        return cases

    def complete_vector_deletions(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM vector_deletions WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )

    @staticmethod
    def _insert_batches(
        connection: sqlite3.Connection,
        document_id: str,
        generation: int,
        chunk_ids: list[str],
        batch_size: int,
        now: str,
    ) -> list[str]:
        batch_ids = []
        for start in range(0, len(chunk_ids), batch_size):
            batch_id = str(uuid4())
            batch_ids.append(batch_id)
            connection.execute(
                """
                INSERT INTO embedding_batches (
                    id, document_id, generation, status, chunk_ids_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    batch_id,
                    document_id,
                    generation,
                    json.dumps(chunk_ids[start : start + batch_size]),
                    now,
                    now,
                ),
            )
        return batch_ids

    def begin_batch(self, batch_id: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE embedding_batches
                   SET status = 'processing', attempts = attempts + 1,
                       error_code = NULL, error_message = NULL, updated_at = ?
                 WHERE id = ? AND status = 'queued'
                """,
                (now, batch_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE knowledge_documents SET status = 'indexing', updated_at = ?
                     WHERE id = (SELECT document_id FROM embedding_batches WHERE id = ?)
                    """,
                    (now, batch_id),
                )
        return cursor.rowcount == 1

    def get_batch_payload(self, batch_id: str) -> tuple[dict[str, Any], list[dict]]:
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM embedding_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise EmbeddingBatchNotFoundError(batch_id)
            document = connection.execute(
                """
                SELECT d.*, kb.embedding_provider, kb.embedding_model,
                       kb.embedding_dimensions
                  FROM knowledge_documents d
                  JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
                 WHERE d.id = ?
                """,
                (batch["document_id"],),
            ).fetchone()
            chunk_ids = json.loads(batch["chunk_ids_json"])
            chunks_by_id = {}
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                rows = connection.execute(
                    f"SELECT * FROM knowledge_chunks WHERE id IN ({placeholders})",
                    chunk_ids,
                ).fetchall()
                chunks_by_id = {
                    row["id"]: self._public_chunk(dict(row)) for row in rows
                }
        if document is None:
            raise KnowledgeDocumentNotFoundError(batch["document_id"])
        return dict(document), [chunks_by_id[chunk_id] for chunk_id in chunk_ids]

    def complete_batch(self, batch_id: str) -> None:
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM embedding_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise EmbeddingBatchNotFoundError(batch_id)
            if batch["status"] != "processing":
                raise InvalidKnowledgeStateError(
                    f"batch must be processing, got {batch['status']}"
                )
            now = utc_now()
            chunk_ids = json.loads(batch["chunk_ids_json"])
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                connection.execute(
                    f"UPDATE knowledge_chunks SET status = 'indexed', "
                    f"error_code = NULL, error_message = NULL, updated_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (now, *chunk_ids),
                )
            connection.execute(
                "UPDATE embedding_batches SET status = 'completed', updated_at = ? "
                "WHERE id = ?",
                (now, batch_id),
            )
            self._refresh_document(connection, batch["document_id"], now)

    def fail_batch(self, batch_id: str, error_code: str, error_message: str) -> None:
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM embedding_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise EmbeddingBatchNotFoundError(batch_id)
            if batch["status"] != "processing":
                return
            now = utc_now()
            chunk_ids = json.loads(batch["chunk_ids_json"])
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                connection.execute(
                    f"UPDATE knowledge_chunks SET status = 'failed', "
                    f"error_code = ?, error_message = ?, updated_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (error_code[:120], error_message[:2000], now, *chunk_ids),
                )
            connection.execute(
                """
                UPDATE embedding_batches
                   SET status = 'failed', error_code = ?, error_message = ?, updated_at = ?
                 WHERE id = ?
                """,
                (error_code[:120], error_message[:2000], now, batch_id),
            )
            self._refresh_document(connection, batch["document_id"], now)

    @staticmethod
    def _refresh_document(
        connection: sqlite3.Connection, document_id: str, now: str
    ) -> None:
        counts = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) AS indexed,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
              FROM knowledge_chunks WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()
        active = connection.execute(
            """
            SELECT COUNT(*) AS count FROM embedding_batches
             WHERE document_id = ? AND status IN ('queued', 'processing')
            """,
            (document_id,),
        ).fetchone()
        assert counts is not None and active is not None
        total = int(counts["total"] or 0)
        indexed = int(counts["indexed"] or 0)
        failed = int(counts["failed"] or 0)
        if int(active["count"]) > 0:
            status = "indexing"
        elif failed:
            status = "partial" if indexed else "failed"
        else:
            status = "ready"
        connection.execute(
            """
            UPDATE knowledge_documents
               SET status = ?, total_chunks = ?, indexed_chunks = ?, failed_chunks = ?,
                   error_code = CASE WHEN ? > 0 THEN 'embedding_batch_failed' ELSE NULL END,
                   error_message = CASE WHEN ? > 0 THEN 'one or more embedding batches failed' ELSE NULL END,
                   indexed_at = CASE WHEN ? = 'ready' THEN ? ELSE indexed_at END,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                status,
                total,
                indexed,
                failed,
                failed,
                failed,
                status,
                now,
                now,
                document_id,
            ),
        )

    def retry_failed_batches(self, document_id: str) -> list[str]:
        self.get_document(document_id)
        now = utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, chunk_ids_json FROM embedding_batches "
                "WHERE document_id = ? AND status = 'failed' ORDER BY created_at",
                (document_id,),
            ).fetchall()
            if not rows:
                raise InvalidKnowledgeStateError(
                    "document has no failed embedding batches to retry"
                )
            batch_ids = [row["id"] for row in rows]
            chunk_ids = [
                chunk_id
                for row in rows
                for chunk_id in json.loads(row["chunk_ids_json"])
            ]
            placeholders = ",".join("?" for _ in batch_ids)
            connection.execute(
                f"UPDATE embedding_batches SET status = 'queued', error_code = NULL, "
                f"error_message = NULL, updated_at = ? WHERE id IN ({placeholders})",
                (now, *batch_ids),
            )
            if chunk_ids:
                chunk_placeholders = ",".join("?" for _ in chunk_ids)
                connection.execute(
                    f"UPDATE knowledge_chunks SET status = 'queued', error_code = NULL, "
                    f"error_message = NULL, updated_at = ? "
                    f"WHERE id IN ({chunk_placeholders})",
                    (now, *chunk_ids),
                )
            connection.execute(
                """
                UPDATE knowledge_documents
                   SET status = 'queued', failed_chunks = 0,
                       error_code = NULL, error_message = NULL, updated_at = ?
                 WHERE id = ?
                """,
                (now, document_id),
            )
        return batch_ids

    def reindex_knowledge_base(
        self,
        knowledge_base_id: str,
        *,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimensions: int,
        batch_size: int,
    ) -> dict[str, list[str]]:
        self.get_knowledge_base(knowledge_base_id)
        now = utc_now()
        with self._connect() as connection:
            active = connection.execute(
                """
                SELECT COUNT(*) AS count FROM knowledge_documents
                 WHERE knowledge_base_id = ? AND status IN ('queued', 'indexing')
                """,
                (knowledge_base_id,),
            ).fetchone()
            assert active is not None
            if active["count"]:
                raise InvalidKnowledgeStateError(
                    "cannot reindex while document indexing is active"
                )
            connection.execute(
                """
                UPDATE knowledge_bases
                   SET embedding_provider = ?, embedding_model = ?,
                       embedding_dimensions = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    embedding_provider,
                    embedding_model,
                    embedding_dimensions,
                    now,
                    knowledge_base_id,
                ),
            )
            documents = connection.execute(
                "SELECT id, generation FROM knowledge_documents "
                "WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            ).fetchall()
            batch_map = {}
            for document in documents:
                document_id = document["id"]
                generation = int(document["generation"]) + 1
                connection.execute(
                    "DELETE FROM embedding_batches WHERE document_id = ?",
                    (document_id,),
                )
                connection.execute(
                    """
                    UPDATE knowledge_chunks
                       SET status = 'queued', embedding_provider = ?,
                           embedding_model = ?, embedding_dimensions = ?,
                           error_code = NULL, error_message = NULL, updated_at = ?
                     WHERE document_id = ?
                    """,
                    (
                        embedding_provider,
                        embedding_model,
                        embedding_dimensions,
                        now,
                        document_id,
                    ),
                )
                chunk_ids = [
                    row["id"]
                    for row in connection.execute(
                        "SELECT id FROM knowledge_chunks WHERE document_id = ? "
                        "ORDER BY page_start, id",
                        (document_id,),
                    ).fetchall()
                ]
                batch_ids = self._insert_batches(
                    connection, document_id, generation, chunk_ids, batch_size, now
                )
                batch_map[document_id] = batch_ids
                connection.execute(
                    """
                    UPDATE knowledge_documents
                       SET status = ?, generation = ?, indexed_chunks = 0,
                           failed_chunks = 0, error_code = NULL, error_message = NULL,
                           indexed_at = NULL, updated_at = ?
                     WHERE id = ?
                    """,
                    ("queued" if chunk_ids else "ready", generation, now, document_id),
                )
        return batch_map

    def delete_document(self, document_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_documents WHERE id = ?", (document_id,)
            )
        if cursor.rowcount != 1:
            raise KnowledgeDocumentNotFoundError(document_id)

    def recover_incomplete(self) -> list[str]:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE embedding_batches SET status = 'queued', updated_at = ? "
                "WHERE status = 'processing'",
                (now,),
            )
            connection.execute(
                "UPDATE knowledge_documents SET status = 'queued', updated_at = ? "
                "WHERE status = 'indexing'",
                (now,),
            )
            rows = connection.execute(
                "SELECT id FROM embedding_batches WHERE status = 'queued' "
                "ORDER BY created_at, id"
            ).fetchall()
        return [row["id"] for row in rows]
