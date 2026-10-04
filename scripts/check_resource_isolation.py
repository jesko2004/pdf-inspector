"""Local live-HTTP fault experiment; synthetic PDFs, no paid model calls.

Run with the installed backend Python. This is a bounded fault experiment,
not a production load rating. Keep every measured request in the JSON report.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def spin(pid_file):
    Path(pid_file).write_text(str(os.getpid()), encoding="ascii")
    while True:
        pass


def slow_ocr(directory, pdf):
    root = Path(directory)
    identity = Path(pdf).stem
    child_pid = root / f"{identity}.child.pid"
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--spin", str(child_pid)],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    spin(root / f"{identity}.adapter.pid")


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
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file() and stat.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def make_pdf(scanned=False, *, width=595, height=842):
    import pymupdf
    with pymupdf.open() as document:
        page = document.new_page(width=width, height=height)
        page.insert_text((50, 70), "RESOURCE CHECK ORIGINAL PAGE", fontsize=16)
        if not scanned:
            return document.tobytes()
        png = page.get_pixmap(dpi=150, alpha=False).tobytes("png")
    with pymupdf.open() as document:
        page = document.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=png)
        return document.tobytes()


def summarize(rows):
    values = sorted(row["elapsed_ms"] for row in rows)
    def percentile(fraction):
        import math
        return values[max(0, math.ceil(len(values) * fraction) - 1)]
    return {"n": len(values), "p50_ms": percentile(0.5), "p95_ms": percentile(0.95),
            "max_ms": max(values)} if values else {"n": 0}


def experiment(output):
    import httpx
    from backend.process_isolation import WindowsJob

    output.mkdir(parents=True, exist_ok=True)
    checks = []
    requests = []
    report = {"schema_version": 1, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "platform": platform.platform(), "python": platform.python_version(),
              "configuration": {"workers": 1, "max_active_tasks": 3,
                                "process_timeout_seconds": 3, "process_memory_mb": 512,
                                "ocr_provider": "command", "ocr_timeout_seconds": 30},
              "scope": "synthetic fault experiment on local HTTP; not a production capacity or quality claim",
              "checks": checks, "requests": requests}
    report["source_sha256"] = {
        name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
        for name in ("backend/process_isolation.py", "backend/isolated_worker.py",
                     "backend/service.py", "backend/config.py", "backend/app.py",
                     "backend/ocr.py", "backend/source_preview.py",
                     "scripts/check_resource_isolation.py")
    }
    import pdf_inspector
    # The package exports a nested compiled extension; record its exact build.
    extension = next(Path(pdf_inspector.__file__).parent.glob("*.pyd"), None)
    if extension is None:
        extension = next(Path(pdf_inspector.__file__).parent.glob("*.so"), None)
    report["native_build"] = {
        "version": getattr(pdf_inspector, "__version__", "unknown"),
        "sha256": hashlib.sha256(extension.read_bytes()).hexdigest() if extension else None,
    }
    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
    with TemporaryDirectory(prefix="resource-http-") as temporary:
        root = Path(temporary)
        pid_root = root / "pids"
        pid_root.mkdir()
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        env = os.environ.copy()
        # Never reuse a caller's data directory, credentials, model service or
        # remote storage in an acceptance experiment.
        for key in list(env):
            if key.startswith("PDF_INSPECTOR_"):
                del env[key]
        env.update({
            "PYTHONUTF8": "1", "PDF_INSPECTOR_DATA_DIR": str(root / "data"),
            "PDF_INSPECTOR_BUILTIN_PROFILE_DIR": str(PROJECT / "backend" / "profiles"),
            "PDF_INSPECTOR_HOST": "127.0.0.1", "PDF_INSPECTOR_PORT": str(port),
            "PDF_INSPECTOR_WORKERS": "1", "PDF_INSPECTOR_MAX_ACTIVE_TASKS": "3",
            "PDF_INSPECTOR_PROCESS_TIMEOUT_SECONDS": "3", "PDF_INSPECTOR_PROCESS_MEMORY_MB": "512",
            "PDF_INSPECTOR_OCR_PROVIDER": "command", "PDF_INSPECTOR_OCR_TIMEOUT_SECONDS": "30",
            "PDF_INSPECTOR_OCR_COMMAND_JSON": json.dumps([
                sys.executable, str(Path(__file__).resolve()), "--slow-ocr", str(pid_root), "{pdf}", "{pages}",
            ]),
        })
        log = output / "server.log"
        guardian = None
        server = None
        try:
            with log.open("wb") as stream:
                server = subprocess.Popen(
                    [sys.executable, "-c", "from backend.server import run; run()"],
                    cwd=PROJECT, env=env, stdout=stream, stderr=stream,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
                if os.name == "nt":
                    guardian = WindowsJob(server, 4 * 1024 * 1024 * 1024)
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20, trust_env=False) as client:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if server.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("local HTTP server did not become ready; inspect server.log")
                        time.sleep(0.05)

                    def request(group, method, path, **kwargs):
                        started = time.perf_counter()
                        response = client.request(method, path, **kwargs)
                        requests.append({"group": group, "method": method, "path": path,
                                         "status": response.status_code,
                                         "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)})
                        return response

                    scanned = make_pdf(scanned=True)
                    native = make_pdf()
                    report["input_sha256"] = {
                        "scanned": hashlib.sha256(scanned).hexdigest(),
                        "native": hashlib.sha256(native).hexdigest(),
                    }
                    def upload(name, data):
                        return request("upload", "POST", "/v1/tasks", data={"profile_id": "manual_query"},
                                       files={"file": (name, data, "application/pdf")})
                    first = upload("slow-one.pdf", scanned)
                    second = upload("slow-two.pdf", scanned)
                    normal = upload("normal.pdf", native)
                    check("three tasks admitted", all(r.status_code == 202 for r in (first, second, normal)))
                    rejected = upload("over-capacity.pdf", native)
                    check("fourth task rejected while first three active", rejected.status_code == 429)
                    tasks = [r.json()["id"] for r in (first, second, normal)]
                    observations = {}
                    started = time.monotonic()
                    while len(observations) < 3:
                        response = request("health_during_slow_work", "GET", "/health")
                        check("health responsive during fault", response.status_code == 200)
                        for identity in tasks:
                            response = request("task_poll", "GET", f"/v1/tasks/{identity}")
                            row = response.json()
                            if row["status"] in {"failed", "ready", "needs_review"}:
                                observations.setdefault(identity, row)
                        if time.monotonic() - started > 20:
                            raise AssertionError("work queue did not recover within experiment deadline")
                        time.sleep(0.1)
                    report["tasks"] = [observations[identity] for identity in tasks]
                    for identity in tasks[:2]:
                        row = observations[identity]
                        check("slow OCR deadline persisted", row["status"] == "failed" and row["error"]["code"] == "ProcessingTimeoutError")
                    check("native task after consecutive timeouts succeeded", observations[tasks[2]]["status"] in {"ready", "needs_review"})
                    # Adapter and grandchild files prove OCR actually started,
                    # rather than merely timing out during Python cold startup.
                    pid_files = list(pid_root.glob("*.pid"))
                    check("two OCR adapters and two descendants started", len(pid_files) == 4)
                    pids = [int(path.read_text(encoding="ascii")) for path in pid_files]
                    until = time.monotonic() + 3
                    while any(process_running(pid) for pid in pids) and time.monotonic() < until:
                        time.sleep(0.01)
                    check("all OCR descendants stopped", not any(process_running(pid) for pid in pids))
                    report["terminated_pids"] = pids
                    preview = request("preview", "GET", f"/v1/tasks/{tasks[2]}/source/pages/1.png")
                    check("preview remains usable", preview.status_code == 200 and preview.content.startswith(b"\x89PNG"))
                    corrupt = upload("corrupt.pdf", b"%PDF-1.7\ninvalid")
                    check("corrupt source admitted for async validation", corrupt.status_code == 202)
                    broken_preview = request("corrupt_preview", "GET", f'/v1/tasks/{corrupt.json()["id"]}/source/pages/1.png')
                    check("corrupt preview is controlled client error", broken_preview.status_code == 422)
                    check("final health usable", request("final_health", "GET", "/health").status_code == 200)
                    report["queue_recovery_elapsed_seconds"] = round(time.monotonic() - started, 3)
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if server is not None:
                if guardian is not None:
                    guardian.terminate()
                elif os.name != "nt":
                    import signal
                    try:
                        os.killpg(server.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                if guardian is not None:
                    guardian.close()
            report["latency"] = {group: summarize([r for r in requests if r["group"] == group])
                                 for group in sorted({r["group"] for r in requests})}
            report["passed"] = bool(checks) and all(c["passed"] for c in checks) and "error" not in report
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(checks),
                      "latency": report["latency"], "report": str(output / "report.json")}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--spin":
        spin(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "--slow-ocr":
        slow_ocr(sys.argv[2], sys.argv[3])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--output-dir", type=Path, required=True)
        args = parser.parse_args()
        experiment(args.output_dir.resolve())
