"""Private child entry point. No HTTP access; parent supplies managed paths."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

from .process_isolation import apply_posix_memory_limit


class WorkerMetrics:
    def __init__(self):
        self.observations = []

    def observe(self, operation, seconds, outcome="success"):
        self.observations.append((operation, seconds, outcome))

    @contextmanager
    def timer(self, operation):
        started = perf_counter()
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            self.observe(operation, perf_counter() - started, outcome)


def main() -> None:
    request, output = map(Path, sys.argv[1:3])
    memory_bytes, max_bytes = map(int, sys.argv[3:5])
    # Windows assignment is completed by the parent before this release byte.
    if sys.stdin.buffer.read(1) != b"1":
        return
    metrics = WorkerMetrics()
    try:
        apply_posix_memory_limit(memory_bytes)
        payload = json.loads(request.read_text(encoding="utf-8"))
        if payload["operation"] == "preview":
            from .source_preview import render_source_page
            image = render_source_page(Path(payload["pdf_path"]), payload["page"])
            if len(image) > max_bytes:
                raise ValueError("preview exceeds configured byte limit")
            output.with_name("preview.png").write_bytes(image)
            data = None
        elif payload["operation"] == "process":
            from .config import Settings
            from .ocr import create_ocr_provider
            from .processor import process_document
            from .profiles import Profile
            import pymupdf

            # Page-tree inspection is itself inside the memory/deadline fence.
            path = Path(payload["pdf_path"])
            with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:
                if document.needs_pass:
                    raise ValueError("encrypted PDF requires an unlocked source")
                if document.page_count > payload["max_pages"]:
                    raise ValueError("PDF exceeds configured page count limit")
            settings = Settings(
                data_dir=request.parent, builtin_profile_dir=request.parent,
                **payload["ocr_settings"],
            )
            data = process_document(
                path, Profile.model_validate(payload["profile"]),
                ocr_provider=create_ocr_provider(settings), metrics=metrics,
            )
        else:
            raise ValueError("unsupported native worker operation")
        envelope = {"ok": True, "data": data}
    except MemoryError:
        envelope = {"ok": False, "code": "ProcessingMemoryLimitError",
                    "message": "native worker could not allocate within its memory limit"}
    except Exception as exc:
        envelope = {"ok": False, "code": type(exc).__name__, "message": str(exc)[:2000]}
    envelope["observations"] = metrics.observations
    encoded = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_bytes:
        encoded = b'{"ok":false,"code":"ProcessingResultTooLargeError","message":"native result exceeds configured byte limit"}'
    output.write_bytes(encoded)


if __name__ == "__main__":
    main()
