import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings

BUILTIN_PROFILES = Path(__file__).resolve().parents[1] / "profiles"


def processor(_pdf_path, profile):
    return {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "status": "needs_review",
        "fields": {
            "supplier_name": {
                "value": "API 测试供应商",
                "page": 1,
                "source_text": "供应商：API 测试供应商",
                "status": "extracted",
                "reason": None,
                "candidates": [],
            }
        },
        "issues": [{"field": "quote_date", "reason": "required_field_missing"}],
        "document": {"page_count": 1, "pages_needing_ocr": []},
        "tables": {
            "status": "ready",
            "issues": [],
            "items": [
                {
                    "id": "line_items_1",
                    "columns": ["item", "amount"],
                    "rows": [{"item": "服务器", "amount": "100"}],
                }
            ],
        },
        "chunks": [{"id": "chunk-1", "page_start": 1, "text": "测试供应商"}],
        "markdown": "<!-- Page 1 -->\n供应商：API 测试供应商",
    }


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        settings = Settings(
            data_dir=Path(self.temporary.name),
            builtin_profile_dir=BUILTIN_PROFILES,
            max_upload_bytes=2048,
            worker_count=1,
        )
        self.app = create_app(settings, processor=processor, start_workers=False)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_full_http_task_workflow(self):
        response = self.client.post(
            "/v1/tasks",
            data={"profile_id": "purchase_quote"},
            files={"file": ("quote.pdf", b"%PDF-1.7\ntest", "application/pdf")},
        )
        self.assertEqual(202, response.status_code)
        task = response.json()
        self.assertEqual("queued", task["status"])

        waiting = self.client.get(f"/v1/tasks/{task['id']}/result")
        self.assertEqual(409, waiting.status_code)
        self.app.state.service.run_pending(task["id"])

        status = self.client.get(f"/v1/tasks/{task['id']}")
        self.assertEqual("needs_review", status.json()["status"])
        result = self.client.get(f"/v1/tasks/{task['id']}/result")
        self.assertEqual(200, result.status_code)
        self.assertEqual(
            "API 测试供应商", result.json()["fields"]["supplier_name"]["value"]
        )
        download = self.client.get(
            f"/v1/tasks/{task['id']}/result", params={"download": "true"}
        )
        self.assertIn("attachment", download.headers["content-disposition"])

        tables = self.client.get(f"/v1/tasks/{task['id']}/tables")
        self.assertEqual("line_items_1", tables.json()["items"][0]["id"])
        csv_response = self.client.get(
            f"/v1/tasks/{task['id']}/tables/line_items_1.csv"
        )
        self.assertEqual(200, csv_response.status_code)
        self.assertIn("服务器,100", csv_response.text)
        chunks = self.client.get(f"/v1/tasks/{task['id']}/chunks")
        self.assertEqual("chunk-1", chunks.json()["items"][0]["id"])
        self.assertEqual({}, chunks.json()["quality"])

    def test_profiles_and_upload_errors(self):
        profiles = self.client.get("/v1/profiles")
        self.assertEqual(200, profiles.status_code)
        self.assertIn(
            "purchase_quote", {item["id"] for item in profiles.json()["items"]}
        )

        custom = {
            "id": "invoice",
            "name": "发票",
            "version": 1,
            "fields": {"number": {"aliases": ["发票号码"], "required": True}},
        }
        created = self.client.post("/v1/profiles", json=custom)
        self.assertEqual(201, created.status_code)
        self.assertFalse(created.json()["builtin"])
        self.assertEqual(409, self.client.post("/v1/profiles", json=custom).status_code)

        bad_file = self.client.post(
            "/v1/tasks",
            files={"file": ("fake.pdf", b"hello", "application/pdf")},
        )
        self.assertEqual(422, bad_file.status_code)
        missing_profile = self.client.post(
            "/v1/tasks",
            data={"profile_id": "missing"},
            files={"file": ("quote.pdf", b"%PDF-1.7\ntest", "application/pdf")},
        )
        self.assertEqual(404, missing_profile.status_code)

    def test_knowledge_base_ingestion_reindex_and_deletion_workflow(self):
        task_response = self.client.post(
            "/v1/tasks",
            data={"profile_id": "purchase_quote"},
            files={"file": ("manual.pdf", b"%PDF-1.7\nmanual", "application/pdf")},
        )
        task = task_response.json()
        self.app.state.service.run_pending(task["id"])

        created = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "产品手册", "description": "内部产品资料"},
        )
        self.assertEqual(201, created.status_code)
        knowledge_base = created.json()
        self.assertEqual("hash", knowledge_base["embedding_provider"])

        ingested = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/documents",
            json={"task_id": task["id"]},
        )
        self.assertEqual(202, ingested.status_code)
        document = ingested.json()
        self.app.state.knowledge.run_pending(document["id"])

        status = self.client.get(
            f"/v1/knowledge-bases/{knowledge_base['id']}/documents/{document['id']}"
        )
        self.assertEqual("ready", status.json()["status"])
        self.assertEqual(100, status.json()["progress"])
        chunks = self.client.get(
            f"/v1/knowledge-bases/{knowledge_base['id']}/documents/"
            f"{document['id']}/chunks"
        )
        self.assertEqual("indexed", chunks.json()["items"][0]["status"])
        batches = self.client.get(
            f"/v1/knowledge-bases/{knowledge_base['id']}/documents/"
            f"{document['id']}/batches"
        )
        self.assertEqual("completed", batches.json()["items"][0]["status"])

        search = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={
                "query": "测试供应商",
                "top_k": 3,
                "min_score": -1,
                "document_ids": [document["id"]],
                "page_start": 1,
                "page_end": 1,
                "kinds": ["text"],
            },
        )
        self.assertEqual(200, search.status_code)
        self.assertEqual(1, search.json()["returned"])
        self.assertEqual(document["id"], search.json()["items"][0]["document_id"])
        self.assertEqual("manual.pdf", search.json()["items"][0]["filename"])
        self.assertEqual([1], search.json()["items"][0]["citation"]["pages"])

        evaluation = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/retrieval-evaluations",
            json={
                "top_k": 1,
                "min_score": -1,
                "cases": [
                    {
                        "id": "supplier-question",
                        "query": "测试供应商",
                        "expected_sources": [
                            {"document_id": document["id"], "pages": [1]}
                        ],
                    }
                ],
            },
        )
        self.assertEqual(200, evaluation.status_code)
        self.assertEqual(1.0, evaluation.json()["mean_recall_at_k"])
        self.assertEqual(1.0, evaluation.json()["mrr"])

        answer = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/ask",
            json={"question": "测试供应商", "min_score": -1},
        )
        self.assertEqual(200, answer.status_code)
        self.assertFalse(answer.json()["refused"])
        self.assertEqual([1], answer.json()["citations"][0]["pages"])
        self.assertIn("测试供应商", answer.json()["answer"])

        streamed = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/ask",
            json={"question": "测试供应商", "min_score": -1, "stream": True},
        )
        self.assertEqual(200, streamed.status_code)
        self.assertTrue(
            streamed.headers["content-type"].startswith("text/event-stream")
        )
        self.assertIn("event: metadata", streamed.text)
        self.assertIn("event: token", streamed.text)
        self.assertIn("event: done", streamed.text)

        refused = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/ask",
            json={"question": "unknown", "document_ids": ["missing-document"]},
        )
        self.assertEqual(200, refused.status_code)
        self.assertTrue(refused.json()["refused"])
        self.assertEqual([], refused.json()["citations"])

        updated = self.client.patch(
            f"/v1/knowledge-bases/{knowledge_base['id']}",
            json={"description": "已更新的内部资料"},
        )
        self.assertEqual("已更新的内部资料", updated.json()["description"])
        reindexed = self.client.post(
            f"/v1/knowledge-bases/{knowledge_base['id']}/reindex",
            json={"embedding_model": "hash-v2"},
        )
        self.assertEqual(202, reindexed.status_code)
        self.app.state.knowledge.run_pending(document["id"])
        self.assertEqual(
            "ready",
            self.client.get(
                f"/v1/knowledge-bases/{knowledge_base['id']}/documents/{document['id']}"
            ).json()["status"],
        )

        deleted_document = self.client.delete(
            f"/v1/knowledge-bases/{knowledge_base['id']}/documents/{document['id']}"
        )
        self.assertEqual(204, deleted_document.status_code)
        deleted_knowledge_base = self.client.delete(
            f"/v1/knowledge-bases/{knowledge_base['id']}"
        )
        self.assertEqual(204, deleted_knowledge_base.status_code)

        metrics = self.client.get("/metrics")
        self.assertEqual(200, metrics.status_code)
        self.assertIn('operation="pdf_processing"', metrics.text)
        self.assertIn('operation="embedding"', metrics.text)
        self.assertIn('operation="retrieval"', metrics.text)
        self.assertIn('operation="llm_generation"', metrics.text)


if __name__ == "__main__":
    unittest.main()
