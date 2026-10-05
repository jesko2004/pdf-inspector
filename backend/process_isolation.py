"""Supervise finite native operations in disposable, killable process trees."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Semaphore
from time import monotonic


class ProcessingTimeoutError(RuntimeError):
    pass


class ProcessingCancelledError(RuntimeError):
    pass


class ProcessingCapacityError(RuntimeError):
    pass


class ProcessingWorkerError(RuntimeError):
    pass


class ProcessingResultTooLargeError(RuntimeError):
    pass


class ProcessingLimitsUnavailableError(RuntimeError):
    pass


class WorkerOperationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WindowsJob:
    """Bound aggregate committed memory and kill descendants when closed.

    The worker waits on stdin until assignment succeeds. Never permit a
    breakaway or silently continue without the requested limits.
    """

    def __init__(self, process: subprocess.Popen, memory_bytes: int):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ProcessingLimitsUnavailableError("cannot create worker Job Object")
        limits = ExtendedLimits()
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_JOB_MEMORY
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x200
        limits.JobMemoryLimit = memory_bytes
        if not kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ) or not kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise ProcessingLimitsUnavailableError(
                f"cannot apply worker Job Object limits (Windows error {error})"
            )

    def terminate(self) -> None:
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def apply_posix_memory_limit(memory_bytes: int) -> None:
    """POSIX per-process address-space limit, inherited by ordinary children."""
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


class ProcessRunner:
    def __init__(
        self, *, workers: int, memory_mb: int, max_result_bytes: int,
        temporary_dir: Path, worker_command: tuple[str, ...] | None = None,
        metrics=None,
    ):
        self.memory_bytes = memory_mb * 1024 * 1024
        self.max_result_bytes = max_result_bytes
        self.temporary_dir = temporary_dir
        self.command = worker_command or (sys.executable, "-m", "backend.isolated_worker")
        self.metrics = metrics
        self._slots = Semaphore(workers)
        self._closed = Event()
        self._lock = Lock()
        self._active: dict[subprocess.Popen, WindowsJob | None] = {}

    @staticmethod
    def _terminate(process: subprocess.Popen, job: WindowsJob | None) -> None:
        if job is not None:
            job.terminate()
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        # Reap the worker before releasing the slot or removing its files.
        process.wait(timeout=5)

    def run(self, payload: dict, *, timeout_seconds: float, binary: bool = False):
        if self._closed.is_set():
            raise ProcessingCancelledError("worker runner is closed")
        if not self._slots.acquire(blocking=False):
            raise ProcessingCapacityError("native operation capacity reached; retry later")
        process = None
        job = None
        started = monotonic()
        try:
            self.temporary_dir.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix="worker-", dir=self.temporary_dir) as root:
                request = Path(root) / "request.json"
                result = Path(root) / "result"
                request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                # Keep native pools from multiplying the service's worker
                # parallelism or reserving many thread stacks under RLIMIT_AS.
                worker_environment = os.environ.copy()
                for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
                    worker_environment[name] = "1"
                with self._lock:
                    if self._closed.is_set():
                        raise ProcessingCancelledError("worker runner is closed")
                    process = subprocess.Popen(
                        [*self.command, str(request), str(result), str(self.memory_bytes),
                         str(self.max_result_bytes)],
                        cwd=Path(__file__).resolve().parent.parent,
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=worker_environment,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                    try:
                        if os.name == "nt":
                            job = WindowsJob(process, self.memory_bytes)
                        self._active[process] = job
                        process.stdin.write(b"1")
                        process.stdin.close()
                    except BaseException:
                        self._terminate(process, job)
                        process.stdin.close()
                        if job is not None:
                            job.close()
                        self._active.pop(process, None)
                        raise
                try:
                    while process.poll() is None:
                        if self._closed.wait(0.02):
                            raise ProcessingCancelledError("native operation cancelled on shutdown")
                        if monotonic() - started >= timeout_seconds:
                            raise ProcessingTimeoutError(
                                f"native operation exceeded {timeout_seconds:g} second deadline"
                            )
                    if self._closed.is_set():
                        raise ProcessingCancelledError("native operation cancelled on shutdown")
                    if monotonic() - started >= timeout_seconds:
                        raise ProcessingTimeoutError(
                            f"native operation exceeded {timeout_seconds:g} second deadline"
                        )
                    if process.returncode != 0 or not result.is_file():
                        raise ProcessingWorkerError(
                            f"native worker exited without a valid result (exit {process.returncode})"
                        )
                    if result.stat().st_size > self.max_result_bytes:
                        raise ProcessingResultTooLargeError("native result exceeds configured byte limit")
                    try:
                        envelope = json.loads(result.read_text(encoding="utf-8"))
                        if not isinstance(envelope, dict) or type(envelope.get("ok")) is not bool:
                            raise ValueError("invalid worker result envelope")
                    except (ValueError, UnicodeError) as exc:
                        raise ProcessingWorkerError("native worker returned an invalid result") from exc
                    if self.metrics is not None:
                        for operation, seconds, outcome in envelope.get("observations", []):
                            self.metrics.observe(operation, seconds, outcome)
                    if not envelope.get("ok"):
                        raise WorkerOperationError(
                            envelope.get("code", "ProcessingWorkerError"),
                            envelope.get("message", "native operation failed"),
                        )
                    if binary:
                        image = Path(root) / "preview.png"
                        if not image.is_file() or image.stat().st_size > self.max_result_bytes:
                            raise ProcessingResultTooLargeError("preview exceeds configured byte limit")
                        return image.read_bytes()
                    return envelope["data"]
                finally:
                    # Also clean up descendants left behind after a successful
                    # command OCR or an OCR-local timeout that kept native text.
                    with self._lock:
                        self._terminate(process, job)
                        self._active.pop(process, None)
                        if job is not None:
                            job.close()
        finally:
            self._slots.release()

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            for process, job in self._active.items():
                self._terminate(process, job)
