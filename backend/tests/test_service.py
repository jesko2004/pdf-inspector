import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.config import Settings
from backend.service import ResultNotReadyError, TaskService, UploadValidationError
from backend.task_store import InvalidTaskStateError

BUILTIN_PROFILES = Path(__file__).resolve().parents[1] / "profiles"


def successful_processor(pdf_path, profile):
    return {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "status": "ready",
        "fields": {"supplier_name": {"value": "测试供应商"}},
        "issues": [],
        "document": {"page_count": 1, "pages_needing_ocr": []},
        "markdown": "<!-- Page 1 -->\n测试",
    }


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.settings = Settings(
            data_dir=Path(self.temporary.name),
            builtin_profile_dir=BUILTIN_PROFILES,
            max_upload_bytes=1024,
            worker_count=1,
        )
        self.service = TaskService(
            self.settings, processor=successful_processor, start_workers=False
        )

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def create_task(self):
        return self.service.create_task(
            "../../quote.pdf", BytesIO(b"%PDF-1.7\nminimal"), "purchase_quote"
        )

    def test_task_lifecycle_and_result_download(self):
        task = self.create_task()
        self.assertEqual("queued", task["status"])
        self.assertEqual("quote.pdf", task["filename"])
        self.assertEqual(0, task["progress"])
        with self.assertRaises(ResultNotReadyError):
            self.service.get_result(task["id"])

        self.service.run_pending(task["id"])
        completed = self.service.get_task(task["id"])
        self.assertEqual("ready", completed["status"])
        self.assertEqual(1, completed["attempts"])
        self.assertEqual(100, completed["progress"])
        result = self.service.get_result(task["id"])
        self.assertEqual(task["id"], result["task_id"])
        self.assertEqual(1, result["attempt"])
        self.assertEqual("测试供应商", result["fields"]["supplier_name"]["value"])
        json.loads(self.service.get_result_path(task["id"]).read_text(encoding="utf-8"))

    def test_rejects_non_pdf_empty_and_oversized_uploads(self):
        for payload in (b"", b"not a pdf", b"%PDF-" + b"x" * 1024):
            with self.subTest(size=len(payload)), self.assertRaises(
                UploadValidationError
            ):
                self.service.create_task("bad.pdf", BytesIO(payload), "purchase_quote")
        self.assertEqual([], list(self.settings.upload_dir.iterdir()))

    def test_failed_task_can_be_retried(self):
        def failing_processor(_pdf_path, _profile):
            raise RuntimeError("extractor failed")

        self.service.processor = failing_processor
        task = self.create_task()
        self.service.run_pending(task["id"])
        failed = self.service.get_task(task["id"])
        self.assertEqual("failed", failed["status"])
        self.assertEqual("RuntimeError", failed["error"]["code"])
        self.assertIn("extractor failed", failed["error"]["message"])

        self.service.processor = successful_processor
        retried = self.service.retry(task["id"])
        self.assertEqual("queued", retried["status"])
        self.service.run_pending(task["id"])
        self.assertEqual("ready", self.service.get_task(task["id"])["status"])
        self.assertEqual(2, self.service.get_task(task["id"])["attempts"])
        with self.assertRaises(InvalidTaskStateError):
            self.service.retry(task["id"])

    def test_profile_is_snapshotted_when_task_is_created(self):
        task = self.create_task()
        stored = self.service.tasks.get(task["id"])
        snapshot = json.loads(stored["profile_json"])
        self.assertEqual("purchase_quote", snapshot["id"])
        self.assertIn("supplier_name", snapshot["fields"])

    def test_interrupted_processing_is_requeued(self):
        task = self.create_task()
        self.assertTrue(self.service.tasks.begin_attempt(task["id"]))
        recovered = self.service.tasks.recover_incomplete()
        self.assertIn(task["id"], recovered)
        self.assertEqual("queued", self.service.get_task(task["id"])["status"])


if __name__ == "__main__":
    unittest.main()
