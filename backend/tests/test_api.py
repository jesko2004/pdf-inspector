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


if __name__ == "__main__":
    unittest.main()
