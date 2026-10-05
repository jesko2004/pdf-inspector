"""Console entry point for the local API server."""

from __future__ import annotations

import ipaddress
import os

from .config import Settings


def run() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "backend dependencies are missing; install with `pip install -e '.[backend]'`"
        ) from exc
    host = os.environ.get("PDF_INSPECTOR_HOST", "127.0.0.1")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if not loopback and not Settings.from_env().api_keys:
        raise RuntimeError("non-loopback serving requires configured API keys")
    uvicorn.run(
        "backend.app:create_app",
        host=host,
        port=int(os.environ.get("PDF_INSPECTOR_PORT", "8000")),
        reload=False,
        factory=True,
    )
