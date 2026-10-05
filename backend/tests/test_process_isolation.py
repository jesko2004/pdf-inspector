import ctypes
import importlib.util
import os
import struct
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.ocr import OcrResourceLimitError, RapidOcrProvider
from backend.process_isolation import (
    ProcessRunner, ProcessingCancelledError, ProcessingCapacityError,
    ProcessingResultTooLargeError, ProcessingTimeoutError, ProcessingWorkerError,
    WorkerOperationError,
)
from backend.service import CapacityExceededError, TaskService

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
FIXTURE_COMMAND = (sys.executable, "-m", "backend.tests.isolation_fixture")


def wait_for_file(path, timeout=5):
    deadline = time.monotonic() + timeout
    while not path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not path.is_file():
        raise AssertionError(f"worker never created {path.name}")
    return int(path.read_text(encoding="ascii"))


def process_running(pid):
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    # A killed orphan may briefly be a zombie awaiting its new parent's reap.
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file() and stat.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class ProcessIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runner = ProcessRunner(
            workers=1, memory_mb=128, max_result_bytes=4096,
            temporary_dir=self.root / "work", worker_command=FIXTURE_COMMAND,
        )

    def tearDown(self):
        self.runner.close()
        self.temporary.cleanup()

    def assert_stopped(self, *pids):
        deadline = time.monotonic() + 3
        while any(process_running(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(any(process_running(pid) for pid in pids))

    def test_timeout_kills_busy_worker_and_descendant_then_reuses_slot(self):
        parent = self.root / "parent.pid"
        child = self.root / "child.pid"
        with self.assertRaises(ProcessingTimeoutError):
            self.runner.run({"case": "descendant", "pid_file": str(parent),
                             "child_pid_file": str(child)}, timeout_seconds=2)
        self.assert_stopped(wait_for_file(parent), wait_for_file(child))
        result = self.runner.run({"case": "success"}, timeout_seconds=5)
        self.assertEqual("ready", result["status"])
        self.assertEqual([], list((self.root / "work").iterdir()))

    def test_success_also_cleans_orphaned_ocr_descendants(self):
        child = self.root / "child.pid"
        self.runner.run({"case": "orphan_success", "child_pid_file": str(child)}, timeout_seconds=5)
        self.assert_stopped(wait_for_file(child))

    def test_crash_and_oversized_result_leave_next_operation_usable(self):
        for case, error in [("crash", ProcessingWorkerError),
                            ("oversized", ProcessingResultTooLargeError)]:
            with self.subTest(case=case), self.assertRaises(error):
                self.runner.run({"case": case}, timeout_seconds=5)
            self.assertEqual("ready", self.runner.run({"case": "success"}, timeout_seconds=5)["status"])

    def test_os_memory_limit_denies_allocation(self):
        with self.assertRaises(WorkerOperationError) as caught:
            self.runner.run({"case": "memory"}, timeout_seconds=5)
        self.assertEqual("ProcessingMemoryLimitError", caught.exception.code)

    def test_capacity_rejects_immediately_and_shutdown_kills_active_work(self):
        pid_file = self.root / "worker.pid"
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.runner.run, {"case": "hang", "pid_file": str(pid_file)}, timeout_seconds=30)
            pid = wait_for_file(pid_file)
            started = time.monotonic()
            with self.assertRaises(ProcessingCapacityError):
                self.runner.run({"case": "success"}, timeout_seconds=5)
            self.assertLess(time.monotonic() - started, 0.5)
            self.runner.close()
            with self.assertRaises(ProcessingCancelledError):
                future.result(timeout=5)
            self.assert_stopped(pid)

    def test_limits_are_required_before_operation_gate_is_released(self):
        if os.name != "nt":
            self.skipTest("Windows assignment fence")
        pid_file = self.root / "unreleased.pid"
        from backend.process_isolation import ProcessingLimitsUnavailableError
        with patch("backend.process_isolation.WindowsJob", side_effect=ProcessingLimitsUnavailableError("injected unavailable")):
            with self.assertRaises(ProcessingLimitsUnavailableError):
                self.runner.run({"case": "success", "pid_file": str(pid_file)}, timeout_seconds=5)
        self.assertFalse(pid_file.exists())


class NativeResourceIntegrationTests(unittest.TestCase):
    def pdf(self, width=595, height=842, pages=1):
        import pymupdf
        with pymupdf.open() as document:
            for _ in range(pages):
                page = document.new_page(width=width, height=height)
                page.insert_text((50, 60), "This PDF has native readable text.")
            return document.tobytes()

    def test_page_limit_and_corrupt_pdf_do_not_block_next_task_or_preview(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=PROFILES, pdf_max_pages=1)
            app = create_app(settings, start_workers=False)
            with TestClient(app) as client:
                service = app.state.service
                for filename, data in [("pages.pdf", self.pdf(pages=2)), ("bad.pdf", b"%PDF-1.7\ninvalid")]:
                    task = service.create_task(filename, BytesIO(data), "manual_query")
                    service.run_pending(task["id"])
                    self.assertEqual("failed", service.get_task(task["id"])["status"])
                task = service.create_task("good.pdf", BytesIO(self.pdf()), "manual_query")
                service.run_pending(task["id"])
                self.assertIn(service.get_task(task["id"])["status"], {"ready", "needs_review"})
                image = client.get(f'/v1/tasks/{task["id"]}/source/pages/1.png')
                self.assertEqual(200, image.status_code)
                width, height = struct.unpack(">II", image.content[16:24])
                self.assertLessEqual(width * height, 2_000_000)
                self.assertIn("pdf_extraction", app.state.metrics.render())

    def test_huge_ocr_page_rejected_before_render_and_model_initialization(self):
        import pymupdf
        with TemporaryDirectory() as root:
            path = Path(root) / "huge.pdf"
            path.write_bytes(self.pdf(width=20000, height=15000))
            provider = RapidOcrProvider(document_opener=lambda p: pymupdf.open(p))
            with patch.object(provider, "_load_dependencies", side_effect=AssertionError("model must not start")):
                with self.assertRaises(OcrResourceLimitError):
                    provider.extract_pages(path, [1])

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "local OCR runtime required")
    def test_real_ocr_runs_inside_default_memory_fence(self):
        import pymupdf
        with pymupdf.open() as original:
            page = original.new_page(width=600, height=240)
            page.insert_text((45, 125), "INVOICE TOTAL 123.45", fontsize=34)
            image = page.get_pixmap(dpi=200, alpha=False).tobytes("png")
        with pymupdf.open() as scanned:
            page = scanned.new_page(width=600, height=240)
            page.insert_image(page.rect, stream=image)
            content = scanned.tobytes()
        with TemporaryDirectory() as root, patch.dict(os.environ, {
            "OPENBLAS_NUM_THREADS": "64", "OMP_NUM_THREADS": "64",
        }):
            settings = Settings(data_dir=Path(root), builtin_profile_dir=PROFILES,
                                ocr_provider="rapidocr", ocr_min_confidence=0.3)
            service = TaskService(settings, start_workers=False)
            try:
                task = service.create_task("scan.pdf", BytesIO(content), "manual_query")
                service.run_pending(task["id"])
                completed = service.get_task(task["id"])
                self.assertIn(completed["status"], {"ready", "needs_review"}, completed.get("error"))
                result = service.get_result(task["id"])
                self.assertEqual([1], result["ocr"]["completed_pages"], result["ocr"])
                self.assertIn("123.45", result["markdown"])
            finally:
                service.close()

    def test_task_timeout_is_persisted_and_retry_capacity_is_bounded(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=PROFILES,
                                process_timeout_seconds=0.001, max_active_tasks=1)
            service = TaskService(settings, start_workers=False)
            try:
                failed = service.create_task("slow.pdf", BytesIO(self.pdf()), "manual_query")
                service.run_pending(failed["id"])
                self.assertEqual("ProcessingTimeoutError", service.get_task(failed["id"])["error"]["code"])
                queued = service.create_task("queued.pdf", BytesIO(self.pdf()), "manual_query")
                with self.assertRaises(CapacityExceededError):
                    service.retry(failed["id"])
                self.assertEqual("failed", service.get_task(failed["id"])["status"])
                service.settings = replace(settings, process_timeout_seconds=20)
                service.run_pending(queued["id"])
                service.retry(failed["id"])
                service.run_pending(failed["id"])
                self.assertIn(service.get_task(failed["id"])["status"], {"ready", "needs_review"})
                self.assertEqual(2, service.get_task(failed["id"])["attempts"])
            finally:
                service.close()

    def test_preview_http_reports_capacity_and_timeout_without_losing_health(self):
        with TemporaryDirectory() as root:
            app = create_app(Settings(data_dir=Path(root), builtin_profile_dir=PROFILES,
                                      preview_timeout_seconds=0.001), start_workers=False)
            with TestClient(app) as client:
                task = app.state.service.create_task("good.pdf", BytesIO(self.pdf()), "manual_query")
                route = f'/v1/tasks/{task["id"]}/source/pages/1.png'
                response = client.get(route)
                self.assertEqual(504, response.status_code)
                with patch.object(app.state.service._preview_runner, "run", side_effect=ProcessingCapacityError()):
                    response = client.get(route)
                    self.assertEqual(429, response.status_code)
                    self.assertEqual("1", response.headers["retry-after"])
                self.assertEqual(200, client.get("/health").status_code)

    def test_resource_config_rejects_nonfinite_and_impossible_limits(self):
        for name, value in [("process_timeout_seconds", float("nan")),
                            ("preview_timeout_seconds", float("inf")),
                            ("process_memory_mb", 0), ("ocr_max_pixels", True),
                            ("pdf_max_pages", 0)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                Settings(data_dir=Path("unused"), builtin_profile_dir=PROFILES, **{name: value})
        with patch.dict(os.environ, {"PDF_INSPECTOR_PROCESS_TIMEOUT_SECONDS": "12.5",
                                     "PDF_INSPECTOR_PROCESS_MEMORY_MB": "512",
                                     "PDF_INSPECTOR_PDF_MAX_PAGES": "20"}):
            settings = Settings.from_env()
            self.assertEqual(12.5, settings.process_timeout_seconds)
            self.assertEqual(512, settings.process_memory_mb)
            self.assertEqual(20, settings.pdf_max_pages)

    def test_shutdown_preserves_unclaimed_queue_and_restart_recovers_it(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=PROFILES,
                                worker_count=1, process_timeout_seconds=30)
            service = TaskService(settings, start_workers=True)
            service._runner.command = FIXTURE_COMMAND
            first = service.create_task("active.pdf", BytesIO(self.pdf()), "manual_query")
            wait_for_file(settings.upload_dir / f'{first["id"]}.pid')
            queued = service.create_task("queued.pdf", BytesIO(self.pdf()), "manual_query")
            started = time.monotonic()
            service.close()
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual("ProcessingCancelledError", service.get_task(first["id"])["error"]["code"])
            self.assertEqual("queued", service.get_task(queued["id"])["status"])
            restarted = TaskService(settings, start_workers=True)
            try:
                deadline = time.monotonic() + 10
                while restarted.get_task(queued["id"])["status"] in {"queued", "processing"} and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertIn(restarted.get_task(queued["id"])["status"], {"ready", "needs_review"})
            finally:
                restarted.close()

    def test_retry_http_does_not_exceed_admission_limit(self):
        with TemporaryDirectory() as root:
            app = create_app(Settings(data_dir=Path(root), builtin_profile_dir=PROFILES,
                                      max_active_tasks=1), processor=lambda *_args: {}, start_workers=False)
            with TestClient(app) as client:
                service = app.state.service
                failed = service.create_task("failed.pdf", BytesIO(self.pdf()), "manual_query")
                service.run_pending(failed["id"])
                service.create_task("queued.pdf", BytesIO(self.pdf()), "manual_query")
                response = client.post(f'/v1/tasks/{failed["id"]}/retry')
                self.assertEqual(429, response.status_code)
                self.assertEqual("1", response.headers["retry-after"])
                self.assertEqual("failed", service.get_task(failed["id"])["status"])


if __name__ == "__main__":
    unittest.main()
