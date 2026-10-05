"""Test-only worker with real CPU, allocation, crash and descendant failures."""

import json
import os
import subprocess
import sys
from pathlib import Path

from backend.process_isolation import apply_posix_memory_limit


def main():
    request, output = map(Path, sys.argv[1:3])
    if sys.stdin.buffer.read(1) != b"1":
        return
    apply_posix_memory_limit(int(sys.argv[3]))
    payload = json.loads(request.read_text(encoding="utf-8"))
    pid_file = payload.get("pid_file")
    if payload.get("operation") == "process":
        pid_file = str(Path(payload["pdf_path"]).with_suffix(".pid"))
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="ascii")
    case = payload.get("case", "hang")
    if case == "crash":
        os._exit(17)
    if case in {"hang", "descendant", "orphan_success"}:
        if case != "hang":
            script = (
                "import os,sys; from pathlib import Path; "
                "Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); "
                "exec('while True: pass')"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", script, payload["child_pid_file"]],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            # The grandchild must be running before this case is considered set up.
            import time
            deadline = time.monotonic() + 5
            while not Path(payload["child_pid_file"]).is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            if case == "orphan_success":
                output.write_text('{"ok":true,"data":{"status":"ready"}}', encoding="utf-8")
                return
        while True:
            pass
    if case == "memory":
        try:
            allocation = bytearray(512 * 1024 * 1024)
            allocation[0] = 1
        except MemoryError:
            output.write_text('{"ok":false,"code":"ProcessingMemoryLimitError","message":"allocation denied"}', encoding="utf-8")
            return
        raise RuntimeError("test memory fence failed")
    if case == "oversized":
        output.write_text(json.dumps({"ok": True, "data": "x" * 100000}), encoding="utf-8")
        return
    output.write_text(json.dumps({"ok": True, "data": {"status": "ready", "pid": os.getpid()}}), encoding="utf-8")


if __name__ == "__main__":
    main()
