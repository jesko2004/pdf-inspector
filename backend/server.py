"""Console entry point for the local API server."""

from __future__ import annotations

import os


def run() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "backend dependencies are missing; install with `pip install -e '.[backend]'`"
        ) from exc
    uvicorn.run(
        "backend.app:create_app",
        host=os.environ.get("PDF_INSPECTOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("PDF_INSPECTOR_PORT", "8000")),
        reload=False,
        factory=True,
    )
