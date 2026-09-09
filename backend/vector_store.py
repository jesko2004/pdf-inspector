"""Vector persistence backends for local development and PostgreSQL/pgvector."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol

from .config import Settings
from .task_store import utc_now


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    knowledge_base_id: str
    document_id: str
    embedding: list[float]
    content_hash: str
    text: str
    page_start: int
    page_end: int
    section_path: list[str]
    kind: str
    embedding_provider: str
    embedding_model: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    name: str

    def upsert(self, records: list[VectorRecord]) -> None: ...

    def delete_chunks(self, chunk_ids: list[str]) -> None: ...

    def delete_document(self, document_id: str) -> None: ...

    def delete_knowledge_base(self, knowledge_base_id: str) -> None: ...

    def count(self, *, document_id: str | None = None) -> int: ...


class SQLiteVectorStore:
    """JSON-vector fallback with the same lifecycle contract as pgvector."""

    name = "sqlite"

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_vectors (
                    chunk_id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    section_path_json TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_vectors_kb_idx "
                "ON knowledge_vectors(knowledge_base_id, document_id)"
            )

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        now = utc_now()
        rows = [
            (
                record.chunk_id,
                record.knowledge_base_id,
                record.document_id,
                json.dumps(record.embedding, separators=(",", ":")),
                len(record.embedding),
                record.content_hash,
                record.text,
                record.page_start,
                record.page_end,
                json.dumps(record.section_path, ensure_ascii=False),
                record.kind,
                record.embedding_provider,
                record.embedding_model,
                json.dumps(record.metadata, ensure_ascii=False),
                now,
            )
            for record in records
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO knowledge_vectors (
                    chunk_id, knowledge_base_id, document_id, embedding_json,
                    embedding_dimensions, content_hash, text, page_start, page_end,
                    section_path_json, kind, embedding_provider, embedding_model,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    knowledge_base_id = excluded.knowledge_base_id,
                    document_id = excluded.document_id,
                    embedding_json = excluded.embedding_json,
                    embedding_dimensions = excluded.embedding_dimensions,
                    content_hash = excluded.content_hash,
                    text = excluded.text,
                    page_start = excluded.page_start,
                    page_end = excluded.page_end,
                    section_path_json = excluded.section_path_json,
                    kind = excluded.kind,
                    embedding_provider = excluded.embedding_provider,
                    embedding_model = excluded.embedding_model,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM knowledge_vectors WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )

    def delete_document(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_vectors WHERE document_id = ?", (document_id,)
            )

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_vectors WHERE knowledge_base_id = ?",
                (knowledge_base_id,),
            )

    def count(self, *, document_id: str | None = None) -> int:
        with self._connect() as connection:
            if document_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM knowledge_vectors"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM knowledge_vectors "
                    "WHERE document_id = ?",
                    (document_id,),
                ).fetchone()
        assert row is not None
        return int(row["count"])

    def list_records(self, document_id: str) -> list[dict[str, Any]]:
        """Inspection helper used by local operations and contract tests."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_vectors WHERE document_id = ? "
                "ORDER BY chunk_id",
                (document_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class PgVectorStore:
    """Production vector store backed by PostgreSQL and the pgvector extension."""

    name = "pgvector"

    def __init__(self, dsn: str):
        if not dsn:
            raise ValueError("pgvector DSN must not be empty")
        self.dsn = dsn
        self._initialize()

    @contextmanager
    def _connect(self):
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise RuntimeError(
                "pgvector dependencies are missing; install with "
                '`pip install -e ".[backend,pgvector]"`'
            ) from exc
        with psycopg.connect(self.dsn) as connection:
            register_vector(connection)
            yield connection

    def _initialize(self) -> None:
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise RuntimeError(
                "pgvector dependencies are missing; install with "
                '`pip install -e ".[backend,pgvector]"`'
            ) from exc
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pdf_inspector_vectors (
                    chunk_id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    embedding vector NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    section_path JSONB NOT NULL,
                    kind TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    metadata JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS pdf_inspector_vectors_kb_idx "
                "ON pdf_inspector_vectors(knowledge_base_id, document_id)"
            )

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        from pgvector import Vector
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            connection.cursor().executemany(
                """
                INSERT INTO pdf_inspector_vectors (
                    chunk_id, knowledge_base_id, document_id, embedding,
                    embedding_dimensions, content_hash, text, page_start, page_end,
                    section_path, kind, embedding_provider, embedding_model,
                    metadata, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT(chunk_id) DO UPDATE SET
                    knowledge_base_id = excluded.knowledge_base_id,
                    document_id = excluded.document_id,
                    embedding = excluded.embedding,
                    embedding_dimensions = excluded.embedding_dimensions,
                    content_hash = excluded.content_hash,
                    text = excluded.text,
                    page_start = excluded.page_start,
                    page_end = excluded.page_end,
                    section_path = excluded.section_path,
                    kind = excluded.kind,
                    embedding_provider = excluded.embedding_provider,
                    embedding_model = excluded.embedding_model,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        record.chunk_id,
                        record.knowledge_base_id,
                        record.document_id,
                        Vector(record.embedding),
                        len(record.embedding),
                        record.content_hash,
                        record.text,
                        record.page_start,
                        record.page_end,
                        Jsonb(record.section_path),
                        record.kind,
                        record.embedding_provider,
                        record.embedding_model,
                        Jsonb(record.metadata),
                    )
                    for record in records
                ],
            )

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM pdf_inspector_vectors WHERE chunk_id = ANY(%s)",
                (chunk_ids,),
            )

    def delete_document(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM pdf_inspector_vectors WHERE document_id = %s",
                (document_id,),
            )

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM pdf_inspector_vectors WHERE knowledge_base_id = %s",
                (knowledge_base_id,),
            )

    def count(self, *, document_id: str | None = None) -> int:
        with self._connect() as connection:
            if document_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM pdf_inspector_vectors"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM pdf_inspector_vectors WHERE document_id = %s",
                    (document_id,),
                ).fetchone()
        assert row is not None
        return int(row[0])


def create_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_store == "sqlite":
        return SQLiteVectorStore(settings.knowledge_database_path)
    if settings.vector_store == "pgvector":
        assert settings.pgvector_dsn is not None
        return PgVectorStore(settings.pgvector_dsn)
    raise ValueError(f"unknown vector store: {settings.vector_store}")
