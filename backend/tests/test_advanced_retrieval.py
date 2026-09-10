import sqlite3
import unittest
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from pydantic import ValidationError

from backend.advanced_retrieval import RuleBasedQueryRewriter, attach_parent_context
from backend.chunking import chunk_pages
from backend.config import Settings
from backend.knowledge_models import KnowledgeDocumentIngest, KnowledgeSearchRequest
from backend.knowledge_service import KnowledgeService
from backend.knowledge_store import ADVANCED_RETRIEVAL_MIGRATION, KnowledgeStore
from backend.migrations import Migration, apply_migrations
from backend.rag_service import RagService
from backend.tests.test_knowledge_service import (
    FakeTaskService,
    RecordingEmbeddingFactory,
    chunk,
)
from backend.vector_store import SQLiteVectorStore


class PreferredReranker:
    name = "flashrank"
    model = "test-reranker"

    def __init__(self):
        self.preferred_chunk_id = None
        self.fail = False
        self.delay = 0.0
        self.calls = []

    def rerank(self, query, candidates, top_n):
        self.calls.append((query, [item["chunk_id"] for item in candidates], top_n))
        if self.delay:
            sleep(self.delay)
        if self.fail:
            raise RuntimeError("planned reranker failure")
        ordered = sorted(
            candidates,
            key=lambda item: item["chunk_id"] != self.preferred_chunk_id,
        )
        return [
            (item["chunk_id"], 1 - index * 0.1)
            for index, item in enumerate(ordered[:top_n])
        ]


class AdvancedRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings = Settings(
            data_dir=root,
            builtin_profile_dir=root / "profiles",
            worker_count=1,
            embedding_dimensions=128,
            embedding_batch_size=4,
            rag_min_evidence_score=-1,
            rerank_provider="flashrank",
            rerank_timeout_ms=20,
        )
        self.tasks = FakeTaskService()
        self.store = KnowledgeStore(self.settings.knowledge_database_path)
        self.vectors = SQLiteVectorStore(self.settings.knowledge_database_path)
        self.factory = RecordingEmbeddingFactory()
        self.reranker = PreferredReranker()
        self.service = KnowledgeService(
            self.settings,
            self.tasks,
            self.store,
            self.vectors,
            embedding_factory=self.factory,
            reranker_factory=lambda _settings: self.reranker,
            start_workers=False,
        )
        self.knowledge_base = self.service.create_knowledge_base(
            name="Advanced retrieval",
            description="",
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def add_task(self, task_id, content, chunks):
        path = Path(self.temporary.name) / f"{task_id}.pdf"
        path.write_bytes(content)
        self.tasks.tasks.rows[task_id] = {
            "id": task_id,
            "status": "ready",
            "filename": f"{task_id}.pdf",
            "pdf_path": str(path),
        }
        self.tasks.results[task_id] = {"chunks": chunks}

    def ingest(self, task_id, chunks, **options):
        self.add_task(task_id, f"%PDF-{task_id}".encode(), chunks)
        document = self.service.ingest_task(
            self.knowledge_base["id"], task_id, "manual", **options
        )
        self.service.run_pending(document["id"])
        return document

    def search(self, query, **options):
        defaults = {
            "top_k": 5,
            "min_score": -1,
            "document_ids": [],
            "page_start": None,
            "page_end": None,
            "kinds": [],
            "section_path_prefix": [],
        }
        defaults.update(options)
        return self.service.search(self.knowledge_base["id"], query, **defaults)

    def test_table_metadata_structured_filter_and_citation(self):
        chunks = chunk_pages(
            [
                (
                    3,
                    (
                        "# Price list\n\n"
                        "| Model | Price | Unit |\n"
                        "|---|---:|---|\n"
                        "| X100 | 99.50 | USD |\n"
                        "| X200 | 149.00 | USD |"
                    ),
                )
            ],
            document_id="table-document",
        )
        table_chunk = next(item for item in chunks if item["kind"] == "table")
        self.assertEqual(
            ["Model", "Price", "Unit"], table_chunk["metadata"]["table"]["headers"]
        )
        self.assertEqual("X100", table_chunk["metadata"]["table"]["rows"][0]["Model"])
        self.ingest("table", chunks)

        result = self.search(
            "X100 price",
            kinds=["table"],
            table_filters={"Model": "X100", "Unit": "USD"},
        )
        self.assertEqual(1, result["returned"])
        self.assertEqual("X100", result["items"][0]["table"]["rows"][0]["Model"])
        self.assertEqual([3], result["items"][0]["citation"]["pages"])
        self.assertEqual(
            [],
            self.search(
                "X100 price",
                kinds=["table"],
                table_filters={"Model": "missing"},
            )["items"],
        )

    def test_query_rewrite_rrf_and_evaluation_comparison(self):
        variants = RuleBasedQueryRewriter({"采购单": "采购订单"}).rewrite(
            "采购单金额",
            3,
        )
        self.assertIn("采购订单金额", variants)
        target = chunk("alpha-route", 2)
        document = self.ingest("rewrite", [target])
        compound = target["text"] + " and unrelated phrase"
        baseline = self.search(compound, min_score=0.99)
        rewritten = self.search(
            compound,
            min_score=0.99,
            rewrite_query=True,
            max_query_variants=3,
        )
        self.assertEqual([], baseline["items"])
        self.assertEqual(document["id"], rewritten["items"][0]["document_id"])
        self.assertIn(target["text"], rewritten["items"][0]["matched_queries"])

        evaluation = self.service.evaluate_retrieval(
            self.knowledge_base["id"],
            [
                {
                    "id": "compound",
                    "query": compound,
                    "expected_sources": [{"document_id": document["id"], "pages": [2]}],
                }
            ],
            top_k=1,
            min_score=0.99,
            document_ids=[],
            page_start=None,
            page_end=None,
            kinds=[],
            section_path_prefix=[],
            compare_rewrite=True,
        )
        self.assertEqual(1.0, evaluation["mean_recall_at_k"])
        self.assertEqual(1.0, evaluation["comparison"]["recall_delta"])

    def test_rerank_reorders_candidates_compares_metrics_and_fails_open(self):
        document = self.ingest(
            "rerank",
            [chunk("first", 1), chunk("preferred", 2), chunk("third", 3)],
        )
        baseline = self.search("neutral query", top_k=3)
        preferred = baseline["items"][-1]
        self.reranker.preferred_chunk_id = preferred["chunk_id"]

        reranked = self.search("neutral query", top_k=3, rerank=True)
        self.assertTrue(reranked["rerank"]["applied"])
        self.assertEqual(preferred["chunk_id"], reranked["items"][0]["chunk_id"])
        self.assertEqual(3, reranked["items"][0]["original_rank"])
        self.assertEqual(1.0, reranked["items"][0]["rerank_score"])

        evaluation = self.service.evaluate_retrieval(
            self.knowledge_base["id"],
            [
                {
                    "id": "rerank-case",
                    "query": "neutral query",
                    "expected_sources": [
                        {"document_id": document["id"], "pages": preferred["pages"]}
                    ],
                }
            ],
            top_k=1,
            min_score=-1,
            document_ids=[],
            page_start=None,
            page_end=None,
            kinds=[],
            section_path_prefix=[],
            compare_rerank=True,
        )
        self.assertEqual(1.0, evaluation["mrr"])
        self.assertGreater(evaluation["comparison"]["mrr_delta"], 0)
        self.assertTrue(evaluation["comparison"]["features"]["rerank"])

        self.reranker.fail = True
        fallback = self.search("neutral query", top_k=1, rerank=True)
        self.assertFalse(fallback["rerank"]["applied"])
        self.assertEqual("provider_error", fallback["rerank"]["fallback_reason"])
        self.assertEqual(
            baseline["items"][0]["chunk_id"], fallback["items"][0]["chunk_id"]
        )

        self.reranker.fail = False
        self.reranker.delay = 0.05
        timed_out = self.search("neutral query", top_k=1, rerank=True)
        self.assertFalse(timed_out["rerank"]["applied"])
        self.assertEqual("timeout", timed_out["rerank"]["fallback_reason"])

    @unittest.skipUnless(find_spec("langchain_core"), "langchain-core is optional")
    def test_existing_search_is_exposed_as_a_langchain_runnable(self):
        source = chunk("langchain-adapter", 7)
        self.ingest("langchain-adapter", [source])
        runnable = self.service.as_langchain_runnable(
            self.knowledge_base["id"],
            top_k=1,
            min_score=-1,
            document_ids=[],
            page_start=None,
            page_end=None,
            kinds=[],
            section_path_prefix=[],
        )

        documents = runnable.invoke(source["text"])

        self.assertEqual(source["text"], documents[0].page_content)
        self.assertEqual([7], documents[0].metadata["citation"]["pages"])

    def test_parent_chunk_is_used_as_generation_context(self):
        chunks = chunk_pages(
            [
                (
                    4,
                    (
                        "# Installation\n\n"
                        "First disconnect all power before opening the controller.\n\n"
                        "Then connect terminal A and terminal B using shielded cable."
                    ),
                )
            ],
            document_id="parent-document",
            target_chars=55,
            max_chars=80,
            overlap_chars=10,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(1, len({item["metadata"]["parent_id"] for item in chunks}))
        self.ingest("parent", chunks)
        hit = self.search(chunks[0]["text"], min_score=0.99)["items"][0]
        self.assertIn("terminal A", hit["context_content"])
        self.assertEqual([4], hit["context_pages"])

        rag = RagService(self.settings, self.service)
        prepared = rag.prepare(
            self.knowledge_base["id"],
            chunks[0]["text"],
            top_k=5,
            min_score=0.99,
            document_ids=[],
            page_start=None,
            page_end=None,
            kinds=[],
            section_path_prefix=[],
        )
        self.assertIn("terminal A", prepared.messages[1]["content"])
        self.assertEqual(1, prepared.retrieval["used"])

    def test_parent_context_keeps_source_order_and_is_bounded(self):
        chunks = [
            {
                "id": f"child-{sequence}",
                "markdown": text,
                "text": text,
                "page_start": 1,
                "pages": [1],
                "section_path": ["Section"],
                "metadata": {"sequence": sequence},
            }
            for sequence, text in (
                (1, "first block"),
                (2, "second block"),
                (3, "third block"),
            )
        ]
        attach_parent_context(chunks, "document", max_parent_chars=25)

        self.assertEqual(
            "first block\n\nsecond block", chunks[0]["metadata"]["parent_text"]
        )
        self.assertEqual(
            chunks[0]["metadata"]["parent_id"], chunks[1]["metadata"]["parent_id"]
        )
        self.assertNotEqual(
            chunks[1]["metadata"]["parent_id"], chunks[2]["metadata"]["parent_id"]
        )

    def test_document_versions_default_to_current_and_support_as_of(self):
        old = self.ingest(
            "version-one",
            [chunk("old-policy", 1)],
            version="2026.1",
            effective_from="2026-01-01T00:00:00+00:00",
        )
        new = self.ingest(
            "version-two",
            [chunk("new-policy", 1)],
            version="2026.2",
            effective_from="2026-06-01T00:00:00+00:00",
        )
        documents = self.store.list_documents(self.knowledge_base["id"], 10, 0)
        self.assertEqual(2, len(documents))
        self.assertEqual(
            {"2026.1": False, "2026.2": True},
            {item["version"]: item["is_current"] for item in documents},
        )
        current = self.search(chunk("old-policy")["text"])
        self.assertEqual(new["id"], current["items"][0]["document_id"])
        historical = self.search(
            chunk("old-policy")["text"],
            include_historical=True,
            versions=["2026.1"],
        )
        self.assertEqual(old["id"], historical["items"][0]["document_id"])
        self.assertEqual("2026.1", historical["items"][0]["citation"]["version"])
        as_of = self.search(
            chunk("old-policy")["text"],
            as_of="2026-03-01T00:00:00+00:00",
        )
        self.assertEqual(old["id"], as_of["items"][0]["document_id"])

    def test_version_datetimes_require_timezone_offsets(self):
        with self.assertRaisesRegex(ValidationError, "timezone offset"):
            KnowledgeDocumentIngest(
                task_id="task",
                effective_from="2026-01-01T00:00:00",
            )
        with self.assertRaisesRegex(ValidationError, "timezone offset"):
            KnowledgeSearchRequest(
                query="policy",
                as_of="2026-01-01T00:00:00",
            )

    def test_advanced_schema_migrates_from_version_one(self):
        database = Path(self.temporary.name) / "legacy-knowledge.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                """
                CREATE TABLE knowledge_documents (
                    id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    document_key TEXT NOT NULL
                );
                CREATE TABLE knowledge_chunks (id TEXT PRIMARY KEY);
                INSERT INTO knowledge_documents(id, knowledge_base_id, document_key)
                VALUES ('document', 'knowledge-base', 'manual.pdf');
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
            document = connection.execute(
                "SELECT logical_document_key, version, is_current "
                "FROM knowledge_documents WHERE id = 'document'"
            ).fetchone()
            chunk_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
            }
            versions = connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE component = 'knowledge' ORDER BY version"
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(("manual.pdf", "1", 1), document)
        self.assertIn("metadata_json", chunk_columns)
        self.assertEqual([(1,), (2,)], versions)


if __name__ == "__main__":
    unittest.main()
