"""Run the existing API with a private readiness marker and graceful stop signal."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import uvicorn


def main() -> None:
    control = Path(sys.argv[1]).resolve()
    # Running a script by absolute path otherwise adds only this tools directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    server = uvicorn.Server(
        uvicorn.Config(
            "backend.app:create_app",
            host="127.0.0.1",
            port=8000,
            factory=True,
            reload=False,
        )
    )

    def monitor() -> None:
        published = False
        while not server.should_exit:
            if (control / "stop").exists():
                server.should_exit = True
                return
            if server.started and not published:
                (control / "ready.json").write_text(
                    json.dumps({"pid": os.getpid(), "url": "http://127.0.0.1:8000/demo"}),
                    encoding="utf-8",
                )
                published = True
            time.sleep(0.2)

    threading.Thread(target=monitor, daemon=True).start()
    server.run()
    if not server.started:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
