import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from backend.knowledge_store import InvalidKnowledgeStateError, KnowledgeStore
from backend import index_publication
from backend.tests import test_knowledge_service as helpers


class IndexPublicationTests(unittest.TestCase):
    setUp = helpers.KnowledgeServiceTests.setUp
    tearDown = helpers.KnowledgeServiceTests.tearDown
    add_task = helpers.KnowledgeServiceTests.add_task
    create_knowledge_base = helpers.KnowledgeServiceTests.create_knowledge_base

    def prepare(self, name, contents, key="manual", **options):
        self.add_task(name, name + ".pdf", ("%PDF-" + name).encode(), contents)
        return self.service.ingest_task(self.kb["id"], name, key, **options)

    def search(self, mode="vector", **options):
        defaults = dict(top_k=100, min_score=-1, document_ids=[], page_start=None,
                        page_end=None, kinds=[], section_path_prefix=[], retrieval_mode=mode)
        defaults.update(options)
        return self.service.search(self.kb["id"], "Useful knowledge", **defaults)

    def assert_only_task(self, task, **options):
        for mode in ("vector", "bm25", "hybrid"):
            result = self.search(mode, **options)
            self.assertTrue(result["items"])
            self.assertEqual({task}, {item["citation"]["task_id"] for item in result["items"]})

    def test_initial_partial_generation_is_not_retrievable(self):
        self.kb = self.create_knowledge_base()
        document = self.prepare("initial", [helpers.chunk("one"), helpers.chunk("FAIL")])
        self.factory.fail_marker = "FAIL"
        self.service.run_pending(document["id"])
        self.assertEqual("partial", self.store.get_document(document["id"])["status"])
        for mode in ("vector", "bm25", "hybrid"):
            self.assertEqual([], self.search(mode)["items"])

    def test_failed_replacement_keeps_old_source_until_successful_retry(self):
        self.kb = self.create_knowledge_base()
        old = self.prepare("old", [helpers.chunk("old")])
        self.service.run_pending(old["id"])
        new = self.prepare("new", [helpers.chunk("new"), helpers.chunk("FAIL")])
        self.assertEqual(old["id"], new["id"])
        self.assert_only_task("old")
        self.factory.fail_marker = "FAIL"
        self.service.run_pending(new["id"])
        self.assert_only_task("old")
        self.factory.fail_marker = None
        before = len(self.factory.calls)
        self.service.retry_document(self.kb["id"], new["id"])
        self.service.run_pending(new["id"])
        self.assertEqual(before + 1, len(self.factory.calls))
        self.assert_only_task("new")
        self.assertEqual(3, self.vectors.count())

    def test_version_replacement_publishes_current_and_history_together(self):
        self.kb = self.create_knowledge_base()
        old = self.prepare("old", [helpers.chunk("old")], version="v1", effective_from="2026-01-01T00:00:00+00:00")
        self.service.run_pending(old["id"])
        new = self.prepare("new", [helpers.chunk("new")], version="v2", effective_from="2026-02-01T00:00:00+00:00")
        self.assertNotEqual(old["id"], new["id"])
        self.assert_only_task("old")
        self.assertEqual([], self.search(include_historical=True, versions=["v2"])["items"])
        self.service.run_pending(new["id"])
        self.assert_only_task("new")
        self.assert_only_task("old", include_historical=True, versions=["v1"])
        self.assert_only_task("old", as_of="2026-01-15T00:00:00+00:00")

    def test_rebuild_publishes_all_documents_and_model_in_one_transaction(self):
        self.kb = self.create_knowledge_base()
        one = self.prepare("one", [helpers.chunk("one")], key="one")
        two = self.prepare("two", [helpers.chunk("two")], key="two")
        self.service.run_pending()
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
        self.service.run_pending(one["id"])
        for mode in ("vector", "bm25", "hybrid"):
            result = self.search(mode)
            self.assertEqual("hash-v1", result["embedding_model"])
            self.assertEqual(2, len(result["items"]))
        # A ready staging document must not be published by migration/restart.
        self.store = KnowledgeStore(self.settings.knowledge_database_path)
        self.service.store = self.store
        self.assertEqual("hash-v1", self.search()["embedding_model"])
        self.service.run_pending(two["id"])
        self.assertEqual("hash-v2", self.search()["embedding_model"])
        self.assertEqual(2, len(self.search()["items"]))
        self.assertEqual(4, self.vectors.count())
        self.assertEqual(0, self.store.get_knowledge_base(self.kb["id"])["index_rebuild_pending"])

    def test_rebuild_failure_preserves_model_and_retry_finishes_publication(self):
        self.kb = self.create_knowledge_base()
        document = self.prepare("old", [helpers.chunk("one"), helpers.chunk("FAIL")])
        self.service.run_pending()
        self.factory.fail_marker = "FAIL"
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
        self.service.run_pending()
        self.assertEqual("hash-v1", self.search()["embedding_model"])
        self.assertEqual(2, len(self.search()["items"]))
        with self.assertRaises(InvalidKnowledgeStateError):
            self.prepare("blocked", [helpers.chunk("other")], key="other")
        with self.assertRaises(InvalidKnowledgeStateError):
            self.service.reindex_knowledge_base(self.kb["id"], embedding_provider=None, embedding_model=None, embedding_dimensions=None)
        self.factory.fail_marker = None
        self.service.retry_document(self.kb["id"], document["id"])
        self.service.run_pending()
        self.assertEqual("hash-v2", self.search()["embedding_model"])

    def test_in_flight_hybrid_query_keeps_old_chunks_and_citation_after_cutover(self):
        self.kb = self.create_knowledge_base()
        document = self.prepare("old", [helpers.chunk("old")])
        self.service.run_pending()
        self.prepare("new", [helpers.chunk("new")])
        original = self.vectors.search
        def cutover_then_search(query):
            self.service.run_pending()
            return original(query)
        with patch.object(self.vectors, "search", side_effect=cutover_then_search):
            result = self.search("hybrid", rewrite_query=True)
        self.assertEqual(1, len(result["items"]))
        self.assertEqual("old", result["items"][0]["citation"]["task_id"])
        self.assertIn("for old", result["items"][0]["context_content"])
        self.assert_only_task("new")
        self.assertEqual(document["id"], result["items"][0]["document_id"])

    def test_same_model_rebuild_also_waits_for_whole_generation(self):
        self.kb = self.create_knowledge_base()
        document = self.prepare("old", [helpers.chunk("one"), helpers.chunk("two")])
        self.service.run_pending()
        old_ids = {r["chunk_id"] for r in self.search()["items"]}
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider=None, embedding_model=None, embedding_dimensions=None)
        batch = self.store.list_batches(document["id"])[0]
        self.service._run_batch(batch["id"])
        self.assertEqual(old_ids, {r["chunk_id"] for r in self.search()["items"]})
        self.service.run_pending()
        self.assertTrue(old_ids.isdisjoint({r["chunk_id"] for r in self.search()["items"]}))

    def test_empty_replacement_never_leaks_retired_vectors(self):
        self.kb = self.create_knowledge_base()
        old = self.prepare("old", [helpers.chunk("old")])
        self.service.run_pending()
        self.prepare("empty", [])
        for mode in ("vector", "bm25", "hybrid"):
            self.assertEqual([], self.search(mode)["items"])
        self.assertEqual(1, self.vectors.count())
        self.service.delete_document(self.kb["id"], old["id"])
        self.assertEqual(0, self.vectors.count())

    def test_empty_knowledge_base_can_publish_new_model(self):
        self.kb = self.create_knowledge_base()
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
        self.assertEqual("hash-v2", self.search()["embedding_model"])
        self.assertEqual([], self.search()["items"])

    def test_migration_seeds_ready_legacy_index_and_is_idempotent(self):
        self.kb = self.create_knowledge_base()
        self.prepare("legacy", [helpers.chunk("legacy")])
        self.service.run_pending()
        with closing(sqlite3.connect(self.settings.knowledge_database_path)) as connection, connection:
            connection.execute("DROP TABLE index_lifecycle_events")
            connection.execute("DROP TABLE retrieval_leases")
            connection.execute("DROP TABLE index_generation_state")
            connection.execute("DROP TABLE index_generations")
            connection.execute("DROP TABLE vector_deletions")
            connection.execute("CREATE TABLE vector_deletions (chunk_id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
            connection.execute("DROP TABLE published_document_indexes")
            connection.execute("DROP TABLE published_knowledge_bases")
            connection.execute("ALTER TABLE knowledge_bases DROP COLUMN index_rebuild_pending")
            connection.execute("DELETE FROM schema_migrations WHERE component = 'knowledge' AND version >= 5")
        for _ in range(2):
            self.service.store = KnowledgeStore(self.settings.knowledge_database_path)
            self.assert_only_task("legacy")

    def test_in_flight_query_keeps_old_model_during_complete_rebuild(self):
        self.kb = self.create_knowledge_base()
        self.prepare("old", [helpers.chunk("old")])
        self.service.run_pending()
        original = self.service._embed
        def rebuild_then_embed(provider, texts):
            self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
            self.service.run_pending()
            return original(provider, texts)
        with patch.object(self.service, "_embed", side_effect=rebuild_then_embed) as call:
            # Avoid recursively patching the background document embedding.
            def once(provider, texts):
                call.side_effect = original
                return rebuild_then_embed(provider, texts)
            call.side_effect = once
            result = self.search()
        self.assertEqual("hash-v1", result["embedding_model"])
        self.assertEqual(1, len(result["items"]))
        self.assertEqual("hash-v2", self.search()["embedding_model"])

    def test_future_version_keeps_effective_old_version_available(self):
        self.kb = self.create_knowledge_base()
        old = self.prepare("old", [helpers.chunk("old")], version="v1", effective_from="2026-01-01T00:00:00+00:00")
        self.service.run_pending()
        self.prepare("future", [helpers.chunk("future")], version="v2", effective_from="2099-01-01T00:00:00+00:00")
        self.service.run_pending()
        self.assert_only_task("old")
        self.assert_only_task("future", as_of="2099-02-01T00:00:00+00:00")
        self.assertEqual(old["id"], self.search()["items"][0]["document_id"])

    def test_deleting_failed_rebuild_document_releases_completed_publication(self):
        self.kb = self.create_knowledge_base()
        self.prepare("good", [helpers.chunk("good")], key="good")
        bad = self.prepare("bad", [helpers.chunk("FAIL")], key="bad")
        self.service.run_pending()
        self.factory.fail_marker = "FAIL"
        self.service.reindex_knowledge_base(self.kb["id"], embedding_provider="hash", embedding_model="hash-v2", embedding_dimensions=24)
        self.service.run_pending()
        self.assertEqual("hash-v1", self.search()["embedding_model"])
        self.service.delete_document(self.kb["id"], bad["id"])
        self.assert_only_task("good")
        self.assertEqual("hash-v2", self.search()["embedding_model"])

    def test_failed_publication_transaction_keeps_old_pointer_and_reuses_checkpoint(self):
        self.kb = self.create_knowledge_base()
        self.prepare("old", [helpers.chunk("old")], version="v1")
        self.service.run_pending()
        new = self.prepare("new", [helpers.chunk("new")], version="v2")
        save = index_publication._save_document
        def fail_after_write(*args):
            save(*args)
            raise RuntimeError("injected publication failure after snapshot write")
        with patch.object(index_publication, "_save_document", side_effect=fail_after_write):
            self.service.run_pending()
        self.assertEqual("failed", self.store.get_document(new["id"])["status"])
        self.assert_only_task("old")
        calls = len(self.factory.calls)
        self.service.retry_document(self.kb["id"], new["id"])
        self.service.run_pending()
        self.assertEqual(calls, len(self.factory.calls))
        self.assert_only_task("new")


if __name__ == "__main__":
    unittest.main()
