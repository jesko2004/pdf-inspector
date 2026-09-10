"""Pluggable per-page OCR integration for mixed and scanned PDFs."""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import Settings


@dataclass(frozen=True)
class OcrPage:
    page: int
    markdown: str
    confidence: float | None = None


class OcrProvider(Protocol):
    name: str

    def extract_pages(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]: ...


class CommandOcrProvider:
    """Run an OCR adapter without a shell and consume its JSON stdout."""

    name = "command"

    def __init__(self, command: tuple[str, ...], timeout_seconds: int = 180):
        if not command:
            raise ValueError("OCR command must not be empty")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def extract_pages(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]:
        page_list = ",".join(map(str, pages))
        command = [
            argument.replace("{pdf}", str(pdf_path)).replace("{pages}", page_list)
            for argument in self.command
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        )
        payload = json.loads(completed.stdout)
        entries = payload.get("pages") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ValueError(
                "OCR command must return a JSON list or a {pages: [...]} object"
            )
        requested = set(pages)
        results = []
        for entry in entries:
            page = int(entry["page"])
            markdown = str(entry.get("markdown") or entry.get("text") or "").strip()
            if page not in requested or not markdown:
                continue
            confidence = entry.get("confidence")
            results.append(
                OcrPage(
                    page=page,
                    markdown=markdown,
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return results


class OcrDependencyError(RuntimeError):
    """Raised when an explicitly selected OCR backend is not installed."""


class RapidOcrProvider:
    """Render selected PDF pages and recognize them with local RapidOCR models."""

    name = "rapidocr"

    def __init__(
        self,
        dpi: int = 200,
        min_confidence: float = 0.5,
        *,
        engine: Any | None = None,
        document_opener: Callable[[str], Any] | None = None,
    ):
        if not 72 <= dpi <= 600:
            raise ValueError("OCR DPI must be between 72 and 600")
        if not 0 <= min_confidence <= 1:
            raise ValueError("OCR minimum confidence must be between 0 and 1")
        self.dpi = dpi
        self.min_confidence = min_confidence
        self._engine = engine
        self._document_opener = document_opener
        self._lock = threading.Lock()

    def _load_dependencies(self) -> tuple[Any, Callable[[str], Any]]:
        document_opener = self._load_document_opener()
        with self._lock:
            if self._engine is None:
                try:
                    from rapidocr import RapidOCR
                    self._engine = RapidOCR()
                except ImportError as exc:
                    raise OcrDependencyError(
                        "RapidOCR or its ONNX runtime is not installed; run "
                        "`pip install -e \".[backend,ocr]\"`"
                    ) from exc
        return self._engine, document_opener

    def _load_document_opener(self) -> Callable[[str], Any]:
        with self._lock:
            if self._document_opener is None:
                try:
                    import pymupdf
                except ImportError as exc:
                    raise OcrDependencyError(
                        "PyMuPDF is not installed; run `pip install -e \".[backend,ocr]\"`"
                    ) from exc
                self._document_opener = pymupdf.open
        return self._document_opener

    @staticmethod
    def _output_rows(output: Any) -> list[tuple[Any, str, float]]:
        """Normalize RapidOCR 3.x output while accepting the legacy tuple shape."""
        if isinstance(output, tuple) and len(output) == 2:
            output = output[0]
        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if boxes is not None and texts is not None and scores is not None:
            return [
                (box, str(text), float(score))
                for box, text, score in zip(boxes, texts, scores)
            ]
        if isinstance(output, list):
            return [
                (entry[0], str(entry[1]), float(entry[2]))
                for entry in output
                if isinstance(entry, (list, tuple)) and len(entry) >= 3
            ]
        return []

    @staticmethod
    def _box_metrics(box: Any) -> tuple[float, float, float]:
        points = list(box)
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return min(ys), min(xs), max(ys) - min(ys)

    def _recognize(
        self, image: bytes, excluded_boxes: list[tuple[float, float, float, float]] | None = None
    ) -> tuple[str, float | None]:
        assert self._engine is not None
        output = self._engine(image, text_score=self.min_confidence)
        rows = []
        for box, text, score in self._output_rows(output):
            text = text.strip()
            if text and score >= self.min_confidence:
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
                x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
                area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
                # Spatial exclusion preserves repeated words in distinct places.
                # Do not remove an OCR line that extends substantially beyond
                # a native span: it may also contain new image text.
                if area > 0 and any(
                    max(0.0, min(x1, right) - max(x0, left))
                    * max(0.0, min(y1, bottom) - max(y0, top)) >= area * 0.8
                    for left, top, right, bottom in (excluded_boxes or [])
                ):
                    continue
                y, x, height = self._box_metrics(box)
                rows.append((y, x, height, text, score))
        rows.sort(key=lambda row: (row[0], row[1]))
        if not rows:
            return "", None

        heights = sorted(row[2] for row in rows if row[2] > 0)
        median_height = heights[len(heights) // 2] if heights else 12.0
        markdown_lines: list[str] = []
        previous_bottom: float | None = None
        for y, _x, height, text, _score in rows:
            if (
                previous_bottom is not None
                and y - previous_bottom > max(8.0, median_height * 1.2)
            ):
                markdown_lines.append("")
            markdown_lines.append(text)
            previous_bottom = max(previous_bottom or y, y + height)
        confidence = sum(row[4] for row in rows) / len(rows)
        return "\n".join(markdown_lines).strip(), confidence

    def extract_pages(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]:
        if not pages:
            return []
        if any(page < 1 for page in pages):
            raise ValueError("OCR pages must use positive 1-indexed page numbers")
        engine, document_opener = self._load_dependencies()
        self._engine = engine
        document = document_opener(str(pdf_path))
        try:
            page_count = int(document.page_count)
            invalid = [page for page in pages if page > page_count]
            if invalid:
                raise ValueError(
                    f"OCR page numbers exceed the {page_count}-page document: {invalid}"
                )
            results = []
            for page_number in sorted(set(pages)):
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(dpi=self.dpi, alpha=False)
                image = pixmap.tobytes("png")
                # A service instance is shared by worker threads. Most inference
                # sessions are not documented as safe for concurrent mutation.
                with self._lock:
                    markdown, confidence = self._recognize(image)
                if markdown:
                    results.append(OcrPage(page_number, markdown, confidence))
            return results
        finally:
            document.close()

    @staticmethod
    def _cover_native_boxes(page: Any) -> list[tuple[float, float, float, float]]:
        """Select sparse marginal text over a dominant image, not body pages.

        Coordinates come from displayed image bounds, not pixel dimensions of
        an unused image resource. Deliberately exclude rotated/cropped pages
        until their coordinate transforms have separate coverage.
        """
        if page.rotation or page.cropbox != page.mediabox:
            return []
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            return []
        spans = [
            span
            for block in page.get_text('dict', flags=0)['blocks']
            if block['type'] == 0
            for line in block['lines']
            for span in line['spans']
            if span['text'].strip()
        ]
        if not spans or sum(len(span['text'].strip()) for span in spans) > 200:
            return []
        boxes = [tuple(span['bbox']) for span in spans]
        # Every span must be wholly in the outer 15% margin. Even a short
        # central paragraph prevents this supplementary OCR path.
        for left, top, right, bottom in boxes:
            if not (
                right <= rect.x0 + rect.width * 0.15
                or left >= rect.x1 - rect.width * 0.15
                or bottom <= rect.y0 + rect.height * 0.15
                or top >= rect.y1 - rect.height * 0.15
            ):
                return []
        for image in page.get_image_info():
            left, top, right, bottom = image['bbox']
            visible_area = max(0.0, min(right, rect.x1) - max(left, rect.x0)) * max(
                0.0, min(bottom, rect.y1) - max(top, rect.y0)
            )
            if visible_area >= rect.width * rect.height * 0.8:
                return boxes
        return []

    def extract_supplements(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]:
        """Return only image-cover additions; an empty candidate needs review.

        This optional provider hook never replaces native Markdown and is not
        a general guarantee of image-text coverage on all native pages.
        """
        if not pages:
            return []
        document_opener = self._load_document_opener()
        document = document_opener(str(pdf_path))
        try:
            results = []
            for page_number in sorted(set(pages)):
                if not 1 <= page_number <= document.page_count:
                    raise ValueError('Supplement pages must be within the document')
                page = document.load_page(page_number - 1)
                boxes = self._cover_native_boxes(page)
                if not boxes:
                    continue
                self._load_dependencies()
                scale = self.dpi / 72
                excluded = [
                    ((left - 2) * scale, (top - 2) * scale,
                     (right + 2) * scale, (bottom + 2) * scale)
                    for left, top, right, bottom in boxes
                ]
                image = page.get_pixmap(dpi=self.dpi, alpha=False).tobytes('png')
                with self._lock:
                    markdown, confidence = self._recognize(image, excluded)
                results.append(OcrPage(page_number, markdown, confidence))
            return results
        finally:
            document.close()


def create_ocr_provider(settings: Settings) -> OcrProvider | None:
    provider = settings.ocr_provider
    if provider == "rapidocr":
        return RapidOcrProvider(settings.ocr_dpi, settings.ocr_min_confidence)
    if provider == "command":
        if settings.ocr_command is None:
            raise ValueError(
                "PDF_INSPECTOR_OCR_COMMAND_JSON is required for the command OCR provider"
            )
        return CommandOcrProvider(settings.ocr_command, settings.ocr_timeout_seconds)
    if provider == "none":
        return None
    raise ValueError(
        "PDF_INSPECTOR_OCR_PROVIDER must be one of: none, rapidocr, command"
    )
