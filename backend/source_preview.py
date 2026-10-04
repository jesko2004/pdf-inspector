"""Bounded single-page previews independent of the browser's PDF plugin."""

from pathlib import Path
from math import sqrt


class PreviewUnavailableError(RuntimeError):
    pass


class PreviewPageNotFoundError(ValueError):
    pass


def render_source_page(path: Path, page: int, *, max_pixels: int = 2_000_000, max_edge: int = 4096) -> bytes:
    try:
        import pymupdf
    except ImportError as exc:
        raise PreviewUnavailableError("install the backend extra for PDF page previews") from exc
    if page < 1:
        raise PreviewPageNotFoundError("page numbering starts at 1")
    try:
        # Read with a Python-owned handle: failed native opens must not retain a
        # Windows file lock on a corrupt upload.
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as document:
            if page > len(document):
                raise PreviewPageNotFoundError("source page does not exist")
            if document.needs_pass:
                raise ValueError("encrypted source cannot be previewed")
            source = document[page - 1]
            width, height = source.rect.width, source.rect.height
            if width <= 0 or height <= 0:
                raise ValueError("invalid source page geometry")
            scale = min(2.0, sqrt(max_pixels / (width * height)), max_edge / max(width, height)) * 0.99
            pixmap = source.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
            return pixmap.tobytes("png")
    except PreviewPageNotFoundError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise ValueError("source page rendering failed") from exc
