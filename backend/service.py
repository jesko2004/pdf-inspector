"""Task orchestration, validation, persistence, and worker execution."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Callable
from uuid import uuid4

from .config import Settings
from .execution_lock import SingleExecutorLock
from .process_isolation import ProcessRunner, ProcessingCancelledError
from .profile_store import ProfileStore
from .profiles import Profile
from .task_store import RESULT_STATUSES, InvalidTaskStateError, TaskStore


class UploadValidationError(ValueError):
    pass


class CapacityExceededError(RuntimeError):
    pass


Processor = Callable[[Path, Profile], dict]


class TaskService:
    def __init__(
        self,
        settings: Settings,
        *,
        processor: Processor | None = None,
        start_workers: bool = True,
        metrics=None,
    ):
        if settings.ocr_provider == "command" and not settings.ocr_command:
            raise ValueError("PDF_INSPECTOR_OCR_COMMAND_JSON is required for command OCR")
        settings.create_directories()
        self._execution_lock = (
            SingleExecutorLock(settings.data_dir / "executor.lock") if start_workers else None
        )
        try:
            self._initialize_services(settings, processor, start_workers, metrics)
        except BaseException:
            if self._execution_lock is not None:
                self._execution_lock.close()
            raise

    def _initialize_services(self, settings, processor, start_workers, metrics):
        if self._execution_lock is not None:
            from .resource_lifecycle import cleanup_owned_files
            cleaned = cleanup_owned_files(settings.data_dir)
            if metrics is not None:
                metrics.increment("pdf_inspector_stale_files_cleaned_total", cleaned)
        self.settings = settings
        self.profiles = ProfileStore(
            settings.builtin_profile_dir, settings.custom_profile_dir
        )
        self.tasks = TaskStore(settings.database_path)
        self._runner = ProcessRunner(
            workers=settings.worker_count, memory_mb=settings.process_memory_mb,
            max_result_bytes=settings.process_max_result_bytes,
            temporary_dir=settings.data_dir / "work", metrics=metrics,
        )
        self._preview_runner = ProcessRunner(
            workers=settings.preview_worker_count, memory_mb=settings.process_memory_mb,
            max_result_bytes=settings.process_max_result_bytes,
            temporary_dir=settings.data_dir / "work", metrics=metrics,
        )
        # Explicit injection is reserved for trusted embedding applications
        # and unit tests. The normal HTTP/CLI path always uses the child.
        self.processor = processor if processor is not None else self._process_isolated
        self.start_workers = start_workers
        self.metrics = metrics
        self.executor = ThreadPoolExecutor(
            max_workers=settings.worker_count, thread_name_prefix="pdf-task"
        )
        self._future_lock = Lock()
        self._futures = set()
        self._admission_lock = Lock()
        self._closing = False
        if start_workers:
            for task_id in self.tasks.recover_incomplete():
                self._submit(task_id)

    def create_task(self, filename: str, stream: BinaryIO, profile_id: str, *, task_id: str | None = None) -> dict:
        # Single-process admission: check and creation must share one critical section.
        with self._admission_lock:
            return self._create_task(filename, stream, profile_id, task_id=task_id)

    def _create_task(self, filename: str, stream: BinaryIO, profile_id: str, *, task_id: str | None = None) -> dict:
        if self._closing:
            raise ProcessingCancelledError("task service is shutting down")
        if self.tasks.count_active() >= self.settings.max_active_tasks:
            raise CapacityExceededError("active task limit reached; retry later")
        profile = self.profiles.get(profile_id)
        from uuid import UUID
        task_id = task_id or str(uuid4())
        if str(UUID(task_id)) != task_id:
            raise UploadValidationError("invalid internal task identity")
        destination = self.settings.upload_dir / f"{task_id}.pdf"
        temporary = destination.with_suffix(".upload")
        try:
            self._save_validated_upload(stream, temporary)
            temporary.replace(destination)
            row = self.tasks.create(
                {
                    "id": task_id,
                    "filename": Path(filename or "document.pdf").name,
                    "profile_id": profile.id,
                    "profile_version": profile.version,
                    "profile_json": profile.model_dump_json(),
                    "pdf_path": str(destination),
                }
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        if self.start_workers:
            self._submit(task_id)
        return public_task(row)

    def get_task(self, task_id: str) -> dict:
        return public_task(self.tasks.get(task_id))

    def list_tasks(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return [public_task(row) for row in self.tasks.list(limit, offset)]

    def get_result_path(self, task_id: str) -> Path:
        row = self.tasks.get(task_id)
        if row["status"] not in RESULT_STATUSES:
            raise ResultNotReadyError(row["status"])
        path = Path(row["result_path"])
        if not path.is_file():
            raise FileNotFoundError(f"result file missing for task {task_id}")
        return path

    def get_result(self, task_id: str) -> dict:
        return json.loads(self.get_result_path(task_id).read_text(encoding="utf-8"))

    def retry(self, task_id: str) -> dict:
        with self._admission_lock:
            if self._closing:
                raise ProcessingCancelledError("task service is shutting down")
            # Preserve 404/409 semantics before checking capacity.
            row = self.tasks.get(task_id)
            if row["status"] != "failed":
                raise InvalidTaskStateError(
                    f"only failed tasks can be retried; current status is {row['status']}"
                )
            if self.tasks.count_active() >= self.settings.max_active_tasks:
                raise CapacityExceededError("active task limit reached; retry later")
            row = self.tasks.retry(task_id)
            if self.start_workers:
                self._submit(task_id)
            return public_task(row)

    def run_pending(self, task_id: str) -> None:
        """Run a queued task synchronously; useful for operational recovery and tests."""
        self._run_task(task_id)

    def close(self) -> None:
        with self._admission_lock:
            self._closing = True
            # Cancel queued futures before killing the active process; otherwise
            # an executor thread could claim another row during shutdown.
            self.executor.shutdown(wait=False, cancel_futures=True)
        self._runner.close()
        self._preview_runner.close()
        # Queued rows remain durable and are recovered on the next startup.
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self._execution_lock is not None:
            self._execution_lock.close()

    def _process_isolated(self, pdf_path: Path, profile: Profile) -> dict:
        settings = self.settings
        return self._runner.run(
            {
                "operation": "process", "pdf_path": str(pdf_path.resolve()),
                "profile": profile.model_dump(mode="json"),
                "max_pages": settings.pdf_max_pages,
                # Model/API credentials used by retrieval never enter this file.
                "ocr_settings": {
                    name: getattr(settings, name) for name in (
                        "ocr_provider", "ocr_command", "ocr_timeout_seconds",
                        "ocr_dpi", "ocr_min_confidence", "ocr_max_pixels",
                    )
                },
            }, timeout_seconds=settings.process_timeout_seconds,
        )

    def render_preview(self, pdf_path: Path, page: int) -> bytes:
        return self._preview_runner.run(
            {"operation": "preview", "pdf_path": str(pdf_path.resolve()), "page": page},
            timeout_seconds=self.settings.preview_timeout_seconds, binary=True,
        )

    def _save_validated_upload(self, stream: BinaryIO, destination: Path) -> None:
        size = 0
        prefix = bytearray()
        with destination.open("xb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise UploadValidationError("upload stream must return bytes")
                size += len(chunk)
                if size > self.settings.max_upload_bytes:
                    raise UploadValidationError(
                        f"file exceeds {self.settings.max_upload_bytes} byte limit"
                    )
                if len(prefix) < 1024:
                    prefix.extend(chunk[: 1024 - len(prefix)])
                output.write(chunk)
        if size == 0:
            destination.unlink(missing_ok=True)
            raise UploadValidationError("empty upload")
        if not bytes(prefix).lstrip().startswith(b"%PDF-"):
            destination.unlink(missing_ok=True)
            raise UploadValidationError("file does not have a PDF header")

    def _submit(self, task_id: str) -> None:
        future = self.executor.submit(self._run_task, task_id)
        with self._future_lock:
            self._futures.add(future)

        def discard(completed):
            with self._future_lock:
                self._futures.discard(completed)

        future.add_done_callback(discard)

    def _run_task(self, task_id: str) -> None:
        if not self.tasks.begin_attempt(task_id):
            return
        row = self.tasks.get(task_id)
        try:
            profile = Profile.model_validate_json(row["profile_json"])
            timing = (
                self.metrics.timer("pdf_processing")
                if self.metrics is not None
                else nullcontext()
            )
            with timing:
                result = self.processor(Path(row["pdf_path"]), profile)
            result.update(
                {
                    "task_id": task_id,
                    "filename": row["filename"],
                    "attempt": row["attempts"],
                }
            )
            status = result.get("status")
            if status not in RESULT_STATUSES:
                raise ValueError(f"processor returned invalid status: {status}")
            destination = self.settings.result_dir / f"{task_id}.json"
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(destination)
            self.tasks.finish(task_id, status, str(destination))
        except Exception as exc:  # noqa: BLE001 - worker boundary records all task failures
            self.tasks.fail(task_id, getattr(exc, "code", type(exc).__name__), str(exc))


class ResultNotReadyError(ValueError):
    pass


def public_task(row: dict) -> dict:
    task = {
        key: row[key]
        for key in (
            "id",
            "filename",
            "profile_id",
            "profile_version",
            "status",
            "attempts",
            "created_at",
            "updated_at",
        )
    }
    task["error"] = (
        {"code": row["error_code"], "message": row["error_message"]}
        if row["error_code"]
        else None
    )
    task["result_url"] = (
        f"/v1/tasks/{row['id']}/result" if row["status"] in RESULT_STATUSES else None
    )
    task["progress"] = {
        "queued": 0,
        "processing": 50,
        "ready": 100,
        "needs_review": 100,
        "failed": 100,
    }[row["status"]]
    return task
