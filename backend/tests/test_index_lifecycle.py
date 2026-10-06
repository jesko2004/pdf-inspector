import json
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from unittest.mock import patch

from backend.index_lifecycle import (
    IndexGenerationNotFoundError, _lease_path, drain_deletions, leased_snapshot, queue_deletions,
)
from backend.knowledge_store import InvalidKnowledgeStateError, KnowledgeBaseNotFoundError, KnowledgeStore
from backend.tests import test_index_publication as publications
from backend.tests import test_knowledge_service as helpers
from backend.vector_store import SQLiteVectorStore


class IndexLifecycleTests(unittest.TestCase):
    setUp = publications.IndexPublicationTests.setUp
    tearDown = publications.IndexPublicationTests.tearDown
    add_task = publications.IndexPublicationTests.add_task
    create_knowledge_base = publications.IndexPublicationTests.create_knowledge_base
    prepare = publications.IndexPublicationTests.prepare
    search = publications.IndexPublicationTests.search
    assert_only_task = publications.IndexPublicationTests.assert_only_task

    def publish(self, name, **options):
        if not hasattr(self, "kb"):
            self.kb = self.create_knowledge_base()
        document = self.prepare(name, [helpers.chunk(name)], **options)
        self.service.run_pending()
        return document, self.current()

    def current(self):
        return self.service.list_index_generations(self.kb["id"])["active_generation_id"]

    def gc(self, **options):
        return self.service.collect_index_garbage(self.kb["id"], **options)

    def rollback(self, target, expected=None):
        return self.service.rollback_index(self.kb["id"], generation_id=target,
                                          expected_generation_id=expected or self.current(), reason="operator reviewed regression")

    def test_only_complete_publications_create_generations_and_restart_is_idempotent(self):
        self.kb = self.create_knowledge_base()
        original = self.current()
        document = self.prepare("partial", [helpers.chunk("good"), helpers.chunk("FAIL")])
        self.factory.fail_marker = "FAIL"
        self.service.run_pending()
        self.assertEqual(original, self.current())
        self.factory.fail_marker = None
        self.service.retry_document(self.kb["id"], document["id"])
        self.service.run_pending()
        summary = self.service.list_index_generations(self.kb["id"])
        self.assertEqual(2, len(summary["items"]))
        self.assertEqual(2, summary["items"][0]["chunk_count"])
        self.service.store = KnowledgeStore(self.store.database_path)
        self.assertEqual(summary, self.service.list_index_generations(self.kb["id"]))

    def test_rollback_switches_content_citations_and_model_without_embedding(self):
        document, old = self.publish("old")
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
        self.service.run_pending()
        self.publish("new")
        before = len(self.factory.calls)
        result = self.rollback(old)
        self.assertTrue(result["changed"])
        self.assertEqual(before, len(self.factory.calls))
        self.assert_only_task("old")
        self.assertEqual("hash-v1", self.search()["embedding_model"])
        self.assertEqual(document["id"], self.search()["items"][0]["document_id"])

    def test_rollback_freezes_ingest_retry_and_restart_until_full_reindex(self):
        _, old = self.publish("old")
        self.publish("added", key="second")
        self.publish("new")
        self.rollback(old)
        self.assert_only_task("old")
        with self.assertRaisesRegex(InvalidKnowledgeStateError, "full reindex"):
            self.prepare("blocked", [helpers.chunk("blocked")])
        with self.assertRaisesRegex(InvalidKnowledgeStateError, "full reindex"):
            self.store.retry_failed_batches(self.store.list_documents(self.kb["id"], 10, 0)[0]["id"])
        self.service.store = KnowledgeStore(self.store.database_path)
        self.assert_only_task("old")
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider=None, embedding_model=None, embedding_dimensions=None)
        self.assert_only_task("old")
        self.service.run_pending()
        summary = self.service.list_index_generations(self.kb["id"])
        self.assertFalse(summary["staging_requires_reindex"])
        self.assertEqual({"new", "added"}, {i["citation"]["task_id"] for i in self.search()["items"]})
        self.publish("allowed")

    def test_rollback_rejects_stale_expected_cross_kb_missing_vectors_and_busy_index(self):
        document, old = self.publish("old")
        _, current = self.publish("new")
        with self.assertRaisesRegex(InvalidKnowledgeStateError, "changed"):
            self.rollback(old, expected=old)
        other = self.service.create_knowledge_base(name="other", description="", embedding_provider=None, embedding_model=None, embedding_dimensions=None)
        with self.assertRaises(IndexGenerationNotFoundError):
            self.service.rollback_index(other["id"], generation_id=old,
                expected_generation_id=self.service.list_index_generations(other["id"])["active_generation_id"], reason="test")
        old_ids = set(self.vectors.chunk_ids(self.kb["id"])) - {i["chunk_id"] for i in self.search()["items"]}
        self.vectors.delete_chunks(list(old_ids))
        with self.assertRaisesRegex(InvalidKnowledgeStateError, "missing"):
            self.rollback(old)
        self.prepare("busy", [helpers.chunk("busy")])
        with self.assertRaisesRegex(InvalidKnowledgeStateError, "active"):
            self.rollback(old)
        self.assertEqual(current, self.current())
        self.assertEqual(document["id"], self.store.list_documents(self.kb["id"], 10, 0)[0]["id"])

    def test_gc_preview_is_read_only_and_apply_requires_current_generation(self):
        self.publish("one")
        self.publish("two")
        self.publish("three")
        current = self.current()
        before = self.service.list_index_generations(self.kb["id"])
        result = self.gc(keep_generations=1)
        self.assertEqual(2, result["reclaimable_vectors"])
        self.assertEqual(3, self.vectors.count())
        self.assertEqual(before, self.service.list_index_generations(self.kb["id"]))
        self.assertEqual([], self.store.pending_vector_deletions())
        with self.assertRaises(ValueError):
            self.gc(keep_generations=1, dry_run=False)
        with self.assertRaises(InvalidKnowledgeStateError):
            self.gc(keep_generations=1, dry_run=False, expected_generation_id="stale")
        applied = self.gc(keep_generations=1, dry_run=False, expected_generation_id=current)
        self.assertEqual(2, applied["deleted_vectors"])
        self.assertEqual(1, self.vectors.count())
        self.assert_only_task("three")

    def test_gc_always_retains_older_active_rollback_generation(self):
        _, old = self.publish("old")
        self.publish("middle")
        _, latest = self.publish("latest")
        self.rollback(old)
        result = self.gc(keep_generations=1, dry_run=False, expected_generation_id=old)
        self.assertEqual({old, latest}, set(result["retained_generation_ids"]))
        self.assertEqual(2, self.vectors.count())
        self.assert_only_task("old")
        self.rollback(latest)
        self.assert_only_task("latest")

    def test_in_flight_query_survives_publication_and_gc_then_releases_vectors(self):
        for mode in ("vector", "hybrid"):
            with self.subTest(mode=mode):
                old_task = "old-" + mode
                new_task = "new-" + mode
                self.publish(old_task)
                self.prepare(new_task, [helpers.chunk(new_task)])
                original = self.vectors.search
                def cutover(query):
                    self.service.run_pending()
                    result = self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
                    self.assertEqual(1, result["deferred_vectors"])
                    self.assertEqual(2, self.vectors.count())
                    return original(query)
                with patch.object(self.vectors, "search", side_effect=cutover):
                    result = self.search(mode)
                self.assertEqual({old_task}, {i["citation"]["task_id"] for i in result["items"]})
                self.assertEqual([], self.store.pending_vector_deletions())
                self.assertEqual(1, self.vectors.count())
                self.assert_only_task(new_task)

    def test_document_and_kb_delete_defer_physical_deletion_for_readers(self):
        for whole_kb in (False, True):
            with self.subTest(whole_kb=whole_kb):
                if whole_kb:
                    self.service.delete_knowledge_base(self.kb["id"])
                    del self.kb
                document, old = self.publish("old-" + str(whole_kb))
                original = self.vectors.search
                def delete(query):
                    if whole_kb:
                        self.service.delete_knowledge_base(self.kb["id"])
                    else:
                        self.service.delete_document(self.kb["id"], document["id"])
                    self.assertEqual(1, self.vectors.count())
                    return original(query)
                with patch.object(self.vectors, "search", side_effect=delete):
                    result = self.search()
                self.assertEqual(1, len(result["items"]))
                self.assertEqual(0, self.vectors.count())
                if whole_kb:
                    with self.assertRaises(KnowledgeBaseNotFoundError):
                        self.search()
                else:
                    self.assertEqual([], self.search()["items"])
                    with self.assertRaises(IndexGenerationNotFoundError):
                        self.rollback(old)

    def test_live_reader_is_not_expired_by_old_timestamp_and_missing_file_fails_closed(self):
        self.publish("old")
        with leased_snapshot(self.store, self.kb["id"], document_ids=[], versions=[], as_of=None, include_historical=False):
            with self.store._connect() as connection:
                connection.execute("UPDATE retrieval_leases SET created_at='1900-01-01'")
            self.publish("new")
            result = self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
            self.assertEqual(1, result["deferred_vectors"])
            self.assertEqual(2, self.vectors.count())
        self.service._drain_vector_deletions()
        self.assertEqual(1, self.vectors.count())
        missing = str(uuid4())
        ids = self.vectors.chunk_ids(self.kb["id"])
        with self.store._connect() as connection:
            connection.execute("INSERT INTO retrieval_leases VALUES (?, ?, ?, ?)", (missing, self.kb["id"], json.dumps(ids), "1900"))
        self.publish("newer")
        self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
        self.assertEqual(2, self.vectors.count())
        self.assertTrue(self.store.pending_vector_deletions())

    def test_crashed_reader_is_reaped_by_os_lock_ownership(self):
        self.publish("old")
        lease_id = str(uuid4())
        path = _lease_path(self.store, lease_id)
        code = "from pathlib import Path; import sys; from backend.execution_lock import SingleExecutorLock; lock=SingleExecutorLock(Path(sys.argv[1])); print('locked', flush=True); sys.stdin.read()"
        child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual("locked", child.stdout.readline().strip())
            with self.store._connect() as connection:
                connection.execute("INSERT INTO retrieval_leases VALUES (?, ?, ?, ?)",
                    (lease_id, self.kb["id"], json.dumps(self.vectors.chunk_ids(self.kb["id"])), "1900"))
            self.publish("new")
            preview = self.gc(keep_generations=1)
            self.assertEqual(1, preview["deferred_vectors"])
            child.kill()
            child.communicate(timeout=10)
            result = self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
            self.assertEqual(1, result["deleted_vectors"])
            with self.store._connect() as connection:
                self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM retrieval_leases").fetchone()[0])
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_failed_physical_delete_persists_outbox_and_retry_does_not_embed(self):
        self.publish("old")
        self.publish("new")
        before = len(self.factory.calls)
        with patch.object(self.vectors, "delete_chunks", side_effect=RuntimeError("remote unavailable")):
            with self.assertRaises(RuntimeError):
                self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
        self.assertEqual(1, len(self.service.list_index_generations(self.kb["id"])["items"]))
        self.assertEqual(1, len(self.store.pending_vector_deletions()))
        self.service._drain_vector_deletions()
        self.assertEqual(before, len(self.factory.calls))
        self.assertEqual(1, self.vectors.count())
        self.assert_only_task("new")

    def test_shared_sqlite_delete_and_ack_rollback_together_and_reused_ids_are_protected(self):
        self.publish("old")
        old_ids = self.vectors.chunk_ids(self.kb["id"])
        self.publish("new")
        with patch.object(self.service, "_drain_vector_deletions", return_value=0):
            self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
        def fail_ack(connection, ids):
            self.vectors.delete_chunks(ids, connection=connection)
            raise RuntimeError("ack failure")
        with self.assertRaises(RuntimeError):
            drain_deletions(self.store, fail_ack)
        self.assertEqual(2, self.vectors.count())
        self.assertEqual(old_ids, self.store.pending_vector_deletions())
        current_ids = [i["chunk_id"] for i in self.search()["items"]]
        with self.store._connect() as connection:
            queue_deletions(connection, self.kb["id"], current_ids)
        self.service._drain_vector_deletions()
        self.assertEqual(1, self.vectors.count())
        self.assertEqual([], self.store.pending_vector_deletions())

    def test_external_sqlite_vector_database_uses_idempotent_outbox(self):
        self.vectors = SQLiteVectorStore(self.store.database_path.parent / "separate-vectors.sqlite")
        self.service.vector_store = self.vectors
        self.publish("old")
        self.publish("new")
        result = self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
        self.assertEqual(1, result["deleted_vectors"])
        self.assert_only_task("new")

    def test_batch_evaluation_pins_vectors_through_publication_and_gc(self):
        document, _ = self.publish("old")
        self.prepare("new", [helpers.chunk("new")])
        original = self.vectors.search
        def cutover(query):
            self.service.run_pending()
            self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
            return original(query)
        with patch.object(self.vectors, "search", side_effect=cutover):
            result = self.service.evaluate_retrieval(self.kb["id"],
                [{"id": "old", "query": "Useful knowledge", "expected_sources": [{"document_id": document["id"], "pages": [1]}]}],
                top_k=5, min_score=-1, document_ids=[], page_start=None, page_end=None, kinds=[], section_path_prefix=[])
        self.assertEqual(1.0, result["mean_recall_at_k"])
        self.assertEqual(1, self.vectors.count())

    def test_concurrent_reader_publisher_and_gc_use_transactional_lease(self):
        self.publish("old")
        self.prepare("new", [helpers.chunk("new")])
        entered, release = Event(), Event()
        original = self.vectors.search
        def paused(query):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test reader barrier")
            return original(query)
        with ThreadPoolExecutor(max_workers=1) as executor, patch.object(self.vectors, "search", side_effect=paused):
            reader = executor.submit(self.search)
            try:
                self.assertTrue(entered.wait(10))
                self.service.run_pending()
                gc = self.gc(keep_generations=1, dry_run=False, expected_generation_id=self.current())
                self.assertEqual(1, gc["deferred_vectors"])
                self.assertEqual(2, self.vectors.count())
            finally:
                release.set()
            result = reader.result(timeout=10)
        self.assertEqual("old", result["items"][0]["citation"]["task_id"])
        self.assertEqual(1, self.vectors.count())
        self.assert_only_task("new")


if __name__ == "__main__":
    unittest.main()
