import os
import unittest
from uuid import uuid4

from backend.vector_store import PgVectorStore, VectorRecord, VectorSearchQuery

PGVECTOR_DSN = os.environ.get("PDF_INSPECTOR_TEST_PGVECTOR_DSN")


@unittest.skipUnless(PGVECTOR_DSN, "pgvector integration DSN is not configured")
class PgVectorIntegrationTests(unittest.TestCase):
    def test_real_pgvector_upsert_and_deletion(self):
        assert PGVECTOR_DSN is not None
        store = PgVectorStore(PGVECTOR_DSN)
        suffix = uuid4().hex
        knowledge_base_id = f"kb-{suffix}"
        document_id = f"doc-{suffix}"

        def make_record(chunk_id, embedding):
            return VectorRecord(
                chunk_id=f"{chunk_id}-{suffix}",
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                embedding=embedding,
                content_hash=f"hash-{chunk_id}",
                text=f"content for {chunk_id}",
                page_start=1,
                page_end=1,
                section_path=["Integration"],
                kind="text",
                embedding_provider="hash",
                embedding_model="hash-v1",
                metadata={"pages": [1]},
            )

        try:
            first = make_record("first", [1.0, 0.0, 0.0])
            second = make_record("second", [0.0, 1.0, 0.0])
            store.upsert([first, second])
            self.assertEqual(2, store.count(document_id=document_id))
            hits = store.search(
                VectorSearchQuery(
                    knowledge_base_id=knowledge_base_id,
                    embedding=[1.0, 0.0, 0.0],
                    embedding_provider="hash",
                    embedding_model="hash-v1",
                    top_k=2,
                    min_score=0.1,
                    document_ids=(document_id,),
                    page_start=1,
                    page_end=1,
                    kinds=("text",),
                    section_path_prefix=("Integration",),
                )
            )
            self.assertEqual([first.chunk_id], [hit.chunk_id for hit in hits])
            self.assertAlmostEqual(1.0, hits[0].score)

            store.upsert([make_record("first", [0.5, 0.5, 0.0])])
            self.assertEqual(2, store.count(document_id=document_id))
            store.delete_chunks([first.chunk_id])
            self.assertEqual(1, store.count(document_id=document_id))
            store.delete_document(document_id)
            self.assertEqual(0, store.count(document_id=document_id))
        finally:
            store.delete_knowledge_base(knowledge_base_id)


if __name__ == "__main__":
    unittest.main()
