import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import pdf_inspector
except ImportError:
    pdf_inspector = None

from backend.config import Settings
from backend.service import TaskService

PROJECT_DIR = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    pdf_inspector is not None, "native Python extension is not installed"
)
class RealExtractorTests(unittest.TestCase):
    def test_fixture_runs_through_persistent_task_pipeline(self):
        fixture = PROJECT_DIR / "tests" / "fixtures" / "thermo-freon12.pdf"
        with TemporaryDirectory() as temporary:
            settings = Settings(
                data_dir=Path(temporary),
                builtin_profile_dir=PROJECT_DIR / "backend" / "profiles",
                worker_count=1,
            )
            service = TaskService(settings, start_workers=False)
            try:
                task = service.create_task(
                    fixture.name, BytesIO(fixture.read_bytes()), "purchase_quote"
                )
                service.run_pending(task["id"])
                completed = service.get_task(task["id"])
                self.assertIn(completed["status"], {"ready", "needs_review"})
                result = service.get_result(task["id"])
                self.assertEqual(3, result["document"]["page_count"])
                self.assertIn("<!-- Page 1 -->", result["markdown"])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
