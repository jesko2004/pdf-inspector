import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.config import Settings
from backend.knowledge_service import KnowledgeService
from backend.knowledge_store import KnowledgeConflictError, KnowledgeStore
from backend.vector_store import SQLiteVectorStore


class FakeTaskStore:
    def __init__(self):
        self.rows = {}

    def get(self, task_id):
        return self.rows[task_id]


class FakeTaskService:
    def __init__(self):
        self.tasks = FakeTaskStore()
        self.results = {}

    def get_result(self, task_id):
        return self.results[task_id]


class RecordingEmbeddingFactory:
    def __init__(self):
        self.calls = []
        self.fail_marker = None

    def __call__(self, provider, model, dimensions):
        factory = self

        class Provider:
            name = provider

            def __init__(self):
                self.model = model
                self.dimensions = dimensions

            def embed(self, texts):
                factory.calls.append((model, tuple(texts)))
                if factory.fail_marker and any(
                    factory.fail_marker in text for text in texts
                ):
                    raise RuntimeError("planned embedding failure")
                return [[1.0 / dimensions] * dimensions for _ in texts]

        return Provider()


def chunk(name, page=1, section=None):
    text = f"Useful knowledge content for {name}"
    return {
        "id": f"source-{name}",
        "kind": "text",
        "markdown": text,
        "text": text,
        "page_start": page,
        "page_end": page,
        "pages": [page],
        "section_path": section or ["Manual"],
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
    }


class KnowledgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings = Settings(
            data_dir=root,
            builtin_profile_dir=root / "profiles",
            worker_count=1,
            embedding_dimensions=16,
            embedding_batch_size=1,
        )
        self.tasks = FakeTaskService()
        self.store = KnowledgeStore(self.settings.knowledge_database_path)
        self.vectors = SQLiteVectorStore(self.settings.knowledge_database_path)
        self.factory = RecordingEmbeddingFactory()
        self.service = KnowledgeService(
            self.settings,
            self.tasks,
            self.store,
            self.vectors,
            embedding_factory=self.factory,
            start_workers=False,
        )

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def add_task(self, task_id, filename, content, chunks):
        path = Path(self.temporary.name) / f"{task_id}.pdf"
        path.write_bytes(content)
        self.tasks.tasks.rows[task_id] = {
            "id": task_id,
            "status": "ready",
            "filename": filename,
            "pdf_path": str(path),
        }
        self.tasks.results[task_id] = {"chunks": chunks}

    def create_knowledge_base(self):
        return self.service.create_knowledge_base(
            name="Engineering manuals",
            description="Internal documentation",
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )

    def test_knowledge_base_crud_and_unique_names(self):
        knowledge_base = self.create_knowledge_base()
        self.assertEqual(0, knowledge_base["document_count"])
        with self.assertRaises(KnowledgeConflictError):
            self.create_knowledge_base()

        updated = self.store.update_knowledge_base(
            knowledge_base["id"], name="Updated manuals", description="Updated"
        )
        self.assertEqual("Updated manuals", updated["name"])
        self.service.delete_knowledge_base(knowledge_base["id"])
        self.assertEqual([], self.store.list_knowledge_bases(10, 0))

    def test_idempotent_ingestion_batches_progress_and_vectors(self):
        knowledge_base = self.create_knowledge_base()
        self.add_task(
            "task-1",
            "manual.pdf",
            b"%PDF-version-one",
            [chunk("alpha", 1), chunk("beta", 2), chunk("gamma", 3)],
        )
        document = self.service.ingest_task(knowledge_base["id"], "task-1", None)
        duplicate = self.service.ingest_task(knowledge_base["id"], "task-1", None)

        self.assertEqual(document["id"], duplicate["id"])
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual("queued", document["status"])
        self.assertEqual(3, len(self.store.list_batches(document["id"])))

        self.service.run_pending(document["id"])
        completed = self.store.get_document(document["id"])
        self.assertEqual("ready", completed["status"])
        self.assertEqual(100, completed["progress"])
        self.assertEqual(3, completed["indexed_chunks"])
        self.assertEqual(3, self.vectors.count(document_id=document["id"]))
        self.assertTrue(
            all(
                batch["status"] == "completed" and batch["attempts"] == 1
                for batch in self.store.list_batches(document["id"])
            )
        )

    def test_only_failed_batch_is_retried(self):
        knowledge_base = self.create_knowledge_base()
        self.add_task(
            "task-failure",
            "failure.pdf",
            b"%PDF-failure",
            [chunk("good-one"), chunk("FAIL"), chunk("good-two")],
        )
        self.factory.fail_marker = "FAIL"
        document = self.service.ingest_task(knowledge_base["id"], "task-failure", None)
        self.service.run_pending(document["id"])

        failed = self.store.get_document(document["id"])
        self.assertEqual("partial", failed["status"])
        self.assertEqual(2, failed["indexed_chunks"])
        self.assertEqual(1, failed["failed_chunks"])
        calls_before_retry = len(self.factory.calls)

        self.factory.fail_marker = None
        self.service.retry_document(knowledge_base["id"], document["id"])
        self.service.run_pending(document["id"])
        recovered = self.store.get_document(document["id"])

        self.assertEqual("ready", recovered["status"])
        self.assertEqual(calls_before_retry + 1, len(self.factory.calls))
        self.assertEqual(3, self.vectors.count(document_id=document["id"]))
        attempts = [
            batch["attempts"] for batch in self.store.list_batches(document["id"])
        ]
        self.assertEqual([1, 1, 2], sorted(attempts))

    def test_incremental_update_reuses_unchanged_chunk(self):
        knowledge_base = self.create_knowledge_base()
        shared = chunk("shared", 1)
        self.add_task(
            "task-old",
            "manual.pdf",
            b"%PDF-old",
            [shared, chunk("removed", 2)],
        )
        document = self.service.ingest_task(
            knowledge_base["id"], "task-old", "manual-stable-key"
        )
        self.service.run_pending(document["id"])
        self.assertEqual(2, len(self.factory.calls))

        self.add_task(
            "task-new",
            "manual.pdf",
            b"%PDF-new",
            [shared, chunk("added", 3)],
        )
        updated = self.service.ingest_task(
            knowledge_base["id"], "task-new", "manual-stable-key"
        )
        self.assertFalse(updated["idempotent"])
        self.assertEqual(1, updated["indexed_chunks"])
        self.assertEqual(1, self.vectors.count(document_id=document["id"]))

        self.service.run_pending(document["id"])
        self.assertEqual(3, len(self.factory.calls))
        self.assertEqual(2, self.vectors.count(document_id=document["id"]))
        self.assertEqual("ready", self.store.get_document(document["id"])["status"])

    def test_document_hash_deduplicates_across_different_keys(self):
        knowledge_base = self.create_knowledge_base()
        content = b"%PDF-identical"
        chunks = [chunk("same")]
        self.add_task("task-a", "a.pdf", content, chunks)
        first = self.service.ingest_task(knowledge_base["id"], "task-a", "key-a")
        self.service.run_pending(first["id"])

        self.add_task("task-b", "b.pdf", content, chunks)
        duplicate = self.service.ingest_task(
            knowledge_base["id"], "task-b", "different-key"
        )
        self.assertEqual(first["id"], duplicate["id"])
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(1, len(self.store.list_documents(knowledge_base["id"], 10, 0)))

    def test_same_pdf_reconciles_when_chunk_set_changes(self):
        knowledge_base = self.create_knowledge_base()
        content = b"%PDF-same-file"
        self.add_task("task-v1", "same.pdf", content, [chunk("old")])
        document = self.service.ingest_task(
            knowledge_base["id"], "task-v1", "stable-key"
        )
        self.service.run_pending(document["id"])

        self.add_task("task-v2", "same.pdf", content, [chunk("new")])
        updated = self.service.ingest_task(
            knowledge_base["id"], "task-v2", "stable-key"
        )
        self.assertFalse(updated["idempotent"])
        self.service.run_pending(updated["id"])
        stored_chunks = self.store.list_chunks(updated["id"])
        self.assertEqual(
            ["source-new"], [item["source_chunk_id"] for item in stored_chunks]
        )
        self.assertEqual(1, self.vectors.count(document_id=updated["id"]))

    def test_ingestion_normalizes_markdown_only_chunks(self):
        knowledge_base = self.create_knowledge_base()
        markdown = "## Installation\n\nConnect the device before startup."
        self.add_task(
            "task-markdown-only",
            "markdown-only.pdf",
            b"%PDF-markdown-only",
            [
                {
                    "id": None,
                    "kind": "text",
                    "markdown": markdown,
                    "page_start": 4,
                    "page_end": 4,
                    "pages": [4],
                    "section_path": ["Installation"],
                }
            ],
        )

        document = self.service.ingest_task(
            knowledge_base["id"], "task-markdown-only", None
        )
        self.service.run_pending(document["id"])

        stored = self.store.list_chunks(document["id"])[0]
        vector = self.vectors.list_records(document["id"])[0]
        expected_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        self.assertEqual(markdown, stored["text"])
        self.assertEqual(expected_hash, stored["content_hash"])
        self.assertTrue(stored["source_chunk_id"])
        self.assertEqual(markdown, vector["text"])

    def test_failed_vector_cleanup_is_persisted_and_retried(self):
        knowledge_base = self.create_knowledge_base()
        self.add_task(
            "task-cleanup-old",
            "cleanup.pdf",
            b"%PDF-cleanup-old",
            [chunk("keep"), chunk("remove")],
        )
        document = self.service.ingest_task(
            knowledge_base["id"], "task-cleanup-old", "cleanup-key"
        )
        self.service.run_pending(document["id"])

        self.add_task(
            "task-cleanup-new",
            "cleanup.pdf",
            b"%PDF-cleanup-new",
            [chunk("keep"), chunk("add")],
        )
        original_delete = self.vectors.delete_chunks

        def fail_delete(_chunk_ids):
            raise RuntimeError("vector database unavailable")

        self.vectors.delete_chunks = fail_delete
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.service.ingest_task(
                knowledge_base["id"], "task-cleanup-new", "cleanup-key"
            )
        self.assertTrue(self.store.pending_vector_deletions())

        self.vectors.delete_chunks = original_delete
        resumed = self.service.ingest_task(
            knowledge_base["id"], "task-cleanup-new", "cleanup-key"
        )
        self.assertTrue(resumed["idempotent"])
        self.assertEqual([], self.store.pending_vector_deletions())
        self.service.run_pending(document["id"])
        self.assertEqual(2, self.vectors.count(document_id=document["id"]))

    def test_reindex_and_cascade_delete(self):
        knowledge_base = self.create_knowledge_base()
        self.add_task(
            "task-reindex",
            "manual.pdf",
            b"%PDF-reindex",
            [chunk("one"), chunk("two")],
        )
        document = self.service.ingest_task(knowledge_base["id"], "task-reindex", None)
        self.service.run_pending(document["id"])

        result = self.service.reindex_knowledge_base(
            knowledge_base["id"],
            embedding_provider="hash",
            embedding_model="hash-v2",
            embedding_dimensions=24,
        )
        self.assertEqual(2, result["batches_queued"])
        self.assertEqual(2, self.vectors.count(document_id=document["id"]))
        self.service.run_pending(document["id"])
        chunks = self.store.list_chunks(document["id"])
        self.assertTrue(all(item["embedding_model"] == "hash-v2" for item in chunks))
        self.assertEqual(2, self.vectors.count(document_id=document["id"]))
        self.assertTrue(
            all(
                item["embedding_model"] == "hash-v2"
                for item in self.vectors.list_records(document["id"])
            )
        )

        self.service.delete_document(knowledge_base["id"], document["id"])
        self.assertEqual(0, self.vectors.count())
        self.service.delete_knowledge_base(knowledge_base["id"])

    def test_interrupted_batch_is_recovered_without_losing_attempts(self):
        knowledge_base = self.create_knowledge_base()
        self.add_task(
            "task-recovery",
            "recovery.pdf",
            b"%PDF-recovery",
            [chunk("recover")],
        )
        document = self.service.ingest_task(knowledge_base["id"], "task-recovery", None)
        batch = self.store.list_batches(document["id"])[0]
        self.assertTrue(self.store.begin_batch(batch["id"]))
        self.assertEqual("indexing", self.store.get_document(document["id"])["status"])

        recovered = self.store.recover_incomplete()
        self.assertEqual([batch["id"]], recovered)
        self.assertEqual("queued", self.store.get_document(document["id"])["status"])
        self.service.run_pending(document["id"])
        final_batch = self.store.list_batches(document["id"])[0]
        self.assertEqual("completed", final_batch["status"])
        self.assertEqual(2, final_batch["attempts"])


if __name__ == "__main__":
    unittest.main()
