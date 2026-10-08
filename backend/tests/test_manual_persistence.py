"""The personal document workflow survives service restarts and in-place updates."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.tests.test_api import BUILTIN_PROFILES, processor


def resume_processor(pdf_path, profile):
    result = processor(pdf_path, profile)
    text = Path(pdf_path).read_bytes().split(b"\n", 1)[1].decode()
    result["chunks"] = [
        {"id": "resume-text", "kind": "text", "page_start": 1, "text": text}
    ]
    result["markdown"] = text
    return result


class ManualPersistenceTests(unittest.TestCase):
    def test_delete_requires_admin_blocks_active_indexing_and_preserves_other_bases(self):
        with TemporaryDirectory() as temporary:
            settings = Settings(
                data_dir=Path(temporary), builtin_profile_dir=BUILTIN_PROFILES,
                api_keys=(("writer", "write-secret", "write"), ("admin", "admin-secret", "admin")),
            )
            writer = {"Authorization": "Bearer write-secret"}
            admin = {"Authorization": "Bearer admin-secret"}
            app = create_app(settings, processor=resume_processor, start_workers=False)
            with TestClient(app) as client:
                first = client.post("/v1/knowledge-bases", headers=writer, json={"name": "不用的资料"}).json()
                second = client.post("/v1/knowledge-bases", headers=writer, json={"name": "保留的资料"}).json()
                base = "/v1/knowledge-bases/" + first["id"]
                kept = "/v1/knowledge-bases/" + second["id"]
                task = client.post("/v1/tasks", headers=writer,
                    data={"profile_id": "manual_query"},
                    files={"file": ("简历.pdf", b"%PDF-1.7\ndeletableresume", "application/pdf")}).json()
                app.state.service.run_pending(task["id"])
                document = client.post(base + "/documents", headers=writer,
                    json={"task_id": task["id"], "document_key": "resume"}).json()
                self.assertEqual(409, client.delete(base, headers=admin).status_code)
                app.state.knowledge.run_pending(document["id"])
                answer = client.post(base + "/ask", headers=writer,
                    json={"question": "deletableresume", "retrieval_mode": "bm25", "min_score": 0})
                self.assertEqual(200, answer.status_code, answer.text)
                self.assertTrue(app.state.knowledge.vector_store.chunk_ids(first["id"]))
                self.assertEqual(403, client.delete(base, headers=writer).status_code)
                self.assertEqual(200, client.get(base, headers=writer).status_code)
                self.assertEqual(204, client.delete(base, headers=admin).status_code)
                self.assertEqual(404, client.get(base, headers=writer).status_code)
                self.assertEqual(404, client.get(base + "/documents", headers=writer).status_code)
                self.assertEqual([], app.state.knowledge.vector_store.chunk_ids(first["id"]))
                self.assertEqual(200, client.get(kept, headers=writer).status_code)
                self.assertEqual([second["id"]], [item["id"] for item in client.get("/v1/knowledge-bases", headers=writer).json()["items"]])
                # Uploaded sources can belong to several bases; deleting a base does not delete them.
                self.assertEqual(200, client.get(f"/v1/tasks/{task['id']}/source", headers=writer).status_code)
                with app.state.knowledge.store._connect() as connection:
                    self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM rag_answers WHERE knowledge_base_id = ?", (first["id"],)).fetchone()[0])
            with TestClient(create_app(settings, processor=resume_processor, start_workers=False)) as client:
                self.assertEqual(404, client.get(base, headers=writer).status_code)
                self.assertEqual(200, client.get(kept, headers=writer).status_code)

    def test_demo_never_reuses_a_cached_page_and_launch_urls_load_current_ui(self):
        with TemporaryDirectory() as temporary:
            settings = Settings(data_dir=Path(temporary), builtin_profile_dir=BUILTIN_PROFILES)
            with TestClient(create_app(settings, start_workers=False)) as client:
                first = client.get("/demo")
                self.assertEqual(200, first.status_code)
                self.assertIn("no-store", first.headers["cache-control"])
                self.assertEqual("no-cache", first.headers["pragma"])
                # A browser presenting a previous validator still receives the full current page.
                second = client.get("/demo?ui=current&session=new-launch", headers={
                    "If-None-Match": first.headers["etag"],
                    "If-Modified-Since": first.headers["last-modified"],
                })
                self.assertEqual(200, second.status_code)
                self.assertNotIn('value="资料查询"', second.text)
                self.assertIn('id="uploadTarget"', second.text)
                self.assertIn('id="documentScope"', second.text)
                self.assertIn('content="2026.10.08.4"', second.text)
                self.assertIn('id="deleteKb"', second.text)

    def test_saved_resume_reopens_updates_without_extra_documents_and_deduplicates(self):
        with TemporaryDirectory() as temporary:
            settings = Settings(
                data_dir=Path(temporary),
                builtin_profile_dir=BUILTIN_PROFILES,
                worker_count=1,
                rag_min_evidence_score=0,
            )

            def open_app():
                return create_app(settings, processor=resume_processor, start_workers=False)

            def ingest(app, client, base, filename, content, key):
                response = client.post(
                    "/v1/tasks",
                    data={"profile_id": "manual_query"},
                    files={"file": (filename, content, "application/pdf")},
                )
                self.assertEqual(202, response.status_code, response.text)
                task_id = response.json()["id"]
                app.state.service.run_pending(task_id)
                response = client.post(
                    base + "/documents",
                    json={"task_id": task_id, "document_key": key},
                )
                self.assertEqual(202, response.status_code, response.text)
                document = response.json()
                app.state.knowledge.run_pending(document["id"])
                return document, task_id

            old_bytes = b"%PDF-1.7\nlegacyresumeexperience"
            new_bytes = b"%PDF-1.7\nupdatedresumeexperience"
            app = open_app()
            with TestClient(app) as client:
                response = client.post("/v1/knowledge-bases", json={"name": "我的资料"})
                self.assertEqual(201, response.status_code, response.text)
                kb_id = response.json()["id"]
                base = "/v1/knowledge-bases/" + kb_id
                original, original_task = ingest(
                    app, client, base, "简历.pdf", old_bytes, "resume-stable-key"
                )

            # A fresh service must recover the original file, extracted text, and vectors.
            app = open_app()
            with TestClient(app) as client:
                libraries = client.get("/v1/knowledge-bases").json()["items"]
                self.assertEqual([kb_id], [item["id"] for item in libraries])
                documents = client.get(base + "/documents").json()["items"]
                self.assertEqual(1, len(documents))
                self.assertEqual("ready", documents[0]["status"])
                self.assertEqual(old_bytes, client.get(f"/v1/tasks/{original_task}/source").content)
                self.assertIn(
                    "legacyresumeexperience",
                    client.get(f"/v1/tasks/{original_task}/result").json()["markdown"],
                )
                vector = client.post(base + "/search", json={
                    "query": "legacyresumeexperience", "retrieval_mode": "vector"
                })
                self.assertEqual(200, vector.status_code, vector.text)
                self.assertEqual(original["id"], vector.json()["items"][0]["document_id"])

                updated, latest_task = ingest(
                    app, client, base, "简历新版.pdf", new_bytes, "resume-stable-key"
                )
                self.assertEqual(original["id"], updated["id"])
                self.assertEqual(1, len(client.get(base + "/documents").json()["items"]))
                duplicate, _ = ingest(
                    app, client, base, "另一个文件名.pdf", new_bytes, "another-key"
                )
                self.assertTrue(duplicate["idempotent"])
                self.assertEqual(updated["id"], duplicate["id"])

            app = open_app()
            with TestClient(app) as client:
                documents = client.get(base + "/documents").json()["items"]
                self.assertEqual(1, len(documents))
                self.assertEqual("简历新版.pdf", documents[0]["filename"])
                self.assertEqual(new_bytes, client.get(f"/v1/tasks/{latest_task}/source").content)
                for query, count in [("updatedresumeexperience", 1), ("legacyresumeexperience", 0)]:
                    response = client.post(base + "/search", json={
                        "query": query, "retrieval_mode": "bm25",
                        "document_ids": [original["id"]],
                    })
                    self.assertEqual(200, response.status_code, response.text)
                    self.assertEqual(count, response.json()["returned"])
                answer = client.post(base + "/ask", json={
                    "question": "updatedresumeexperience", "retrieval_mode": "bm25",
                    "document_ids": [original["id"]],
                })
                self.assertEqual(200, answer.status_code, answer.text)
                self.assertIn("updatedresumeexperience", answer.json()["answer"])


if __name__ == "__main__":
    unittest.main()
