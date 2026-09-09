import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.vector_store import (
    PgVectorStore,
    SQLiteVectorStore,
    VectorRecord,
    VectorSearchQuery,
)


def record(chunk_id, document_id="doc-1"):
    return VectorRecord(
        chunk_id=chunk_id,
        knowledge_base_id="kb-1",
        document_id=document_id,
        embedding=[0.1, 0.2, 0.3],
        content_hash=f"hash-{chunk_id}",
        text=f"text {chunk_id}",
        page_start=1,
        page_end=2,
        section_path=["Section"],
        kind="text",
        embedding_provider="hash",
        embedding_model="hash-v1",
        metadata={"source_chunk_id": chunk_id},
    )


class VectorStoreTests(unittest.TestCase):
    def test_sqlite_upsert_and_lifecycle_deletion(self):
        with TemporaryDirectory() as temporary:
            store = SQLiteVectorStore(Path(temporary) / "vectors.sqlite3")
            store.upsert([record("one"), record("two"), record("three", "doc-2")])
            self.assertEqual(3, store.count())
            self.assertEqual(2, store.count(document_id="doc-1"))

            updated = record("one")
            store.upsert([updated])
            self.assertEqual(3, store.count())
            self.assertEqual(2, len(store.list_records("doc-1")))

            store.delete_chunks(["one"])
            self.assertEqual(1, store.count(document_id="doc-1"))
            store.delete_document("doc-1")
            self.assertEqual(1, store.count())
            store.delete_knowledge_base("kb-1")
            self.assertEqual(0, store.count())

    def test_sqlite_similarity_search_ranking_and_metadata_filters(self):
        with TemporaryDirectory() as temporary:
            store = SQLiteVectorStore(Path(temporary) / "vectors.sqlite3")
            first = record("first", "doc-1")
            first = VectorRecord(
                **{
                    **first.__dict__,
                    "embedding": [1.0, 0.0, 0.0],
                    "page_start": 2,
                    "page_end": 2,
                    "section_path": ["Guide", "Install"],
                    "metadata": {"pages": [2]},
                }
            )
            second = record("second", "doc-2")
            second = VectorRecord(
                **{
                    **second.__dict__,
                    "embedding": [0.0, 1.0, 0.0],
                    "page_start": 8,
                    "page_end": 8,
                    "section_path": ["Guide", "Repair"],
                    "metadata": {"pages": [8]},
                }
            )
            store.upsert([first, second])

            ranked = store.search(
                VectorSearchQuery(
                    knowledge_base_id="kb-1",
                    embedding=[1.0, 0.0, 0.0],
                    embedding_provider="hash",
                    embedding_model="hash-v1",
                    top_k=2,
                    min_score=-1,
                )
            )
            self.assertEqual(["first", "second"], [hit.chunk_id for hit in ranked])

            hits = store.search(
                VectorSearchQuery(
                    knowledge_base_id="kb-1",
                    embedding=[1.0, 0.0, 0.0],
                    embedding_provider="hash",
                    embedding_model="hash-v1",
                    top_k=5,
                    min_score=0.5,
                    document_ids=("doc-1",),
                    page_start=2,
                    page_end=2,
                    kinds=("text",),
                    section_path_prefix=("Guide", "Install"),
                )
            )
            self.assertEqual(["first"], [hit.chunk_id for hit in hits])
            self.assertEqual(1.0, hits[0].score)

            no_hits = store.search(
                VectorSearchQuery(
                    knowledge_base_id="kb-1",
                    embedding=[1.0, 0.0, 0.0],
                    embedding_provider="hash",
                    embedding_model="hash-v1",
                    top_k=5,
                    min_score=0.5,
                    section_path_prefix=("Guide", "Repair"),
                )
            )
            self.assertEqual([], no_hits)

    def test_pgvector_uses_extension_vector_column_and_transactional_upsert(self):
        calls = []

        class Result:
            @staticmethod
            def fetchone():
                return (0,)

            @staticmethod
            def fetchall():
                return []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params=None):
                calls.append(("execute", " ".join(sql.split()), params))
                return Result()

            def cursor(self):
                return self

            def executemany(self, sql, params):
                calls.append(("executemany", " ".join(sql.split()), list(params)))

        psycopg = types.ModuleType("psycopg")
        psycopg.connect = lambda *_args, **_kwargs: Connection()
        psycopg_types = types.ModuleType("psycopg.types")
        psycopg_json = types.ModuleType("psycopg.types.json")
        psycopg_json.Jsonb = lambda value: value
        pgvector = types.ModuleType("pgvector")
        pgvector.Vector = lambda value: value
        pgvector_psycopg = types.ModuleType("pgvector.psycopg")
        pgvector_psycopg.register_vector = lambda connection: calls.append(
            ("register", connection)
        )
        modules = {
            "psycopg": psycopg,
            "psycopg.types": psycopg_types,
            "psycopg.types.json": psycopg_json,
            "pgvector": pgvector,
            "pgvector.psycopg": pgvector_psycopg,
        }
        with patch.dict(sys.modules, modules):
            store = PgVectorStore("postgresql://example")
            store.upsert([record("pg-one")])
            store.delete_document("doc-1")
            store.search(
                VectorSearchQuery(
                    knowledge_base_id="kb-1",
                    embedding=[0.1, 0.2, 0.3],
                    embedding_provider="hash",
                    embedding_model="hash-v1",
                    top_k=3,
                    document_ids=("doc-1",),
                    page_start=1,
                    page_end=4,
                    kinds=("text",),
                    section_path_prefix=("Section",),
                )
            )

        statements = [
            item[1] for item in calls if item[0] in {"execute", "executemany"}
        ]
        self.assertTrue(
            any("CREATE EXTENSION IF NOT EXISTS vector" in sql for sql in statements)
        )
        self.assertTrue(any("embedding vector NOT NULL" in sql for sql in statements))
        self.assertTrue(
            any("ON CONFLICT(chunk_id) DO UPDATE" in sql for sql in statements)
        )
        self.assertTrue(
            any("DELETE FROM pdf_inspector_vectors" in sql for sql in statements)
        )
        self.assertTrue(any("embedding <=> %s" in sql for sql in statements))
        self.assertTrue(any("section_path ->> 0 = %s" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
