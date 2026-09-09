"""Adapter from the native extractor to business-field results."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from .chunking import chunk_pages
from .ocr import OcrProvider
from .profiles import Profile, extract_fields
from .table_data import extract_business_tables


class ExtractorUnavailableError(RuntimeError):
    pass


def _load_engine():
    try:
        import pdf_inspector
    except ImportError as exc:
        raise ExtractorUnavailableError(
            "pdf_inspector Python extension is not installed; run `maturin develop --features python`"
        ) from exc
    return pdf_inspector


def _document_markdown(pages: list[dict]) -> str:
    parts = []
    for page in pages:
        parts.append(f"<!-- Page {page['page']} -->\n\n{page['markdown'].strip()}")
    return "\n\n".join(parts).strip() + "\n"


def _document_id(pdf_path: Path) -> str:
    digest = hashlib.sha256()
    if not pdf_path.is_file():
        digest.update(str(pdf_path).encode("utf-8"))
        return digest.hexdigest()
    with pdf_path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _region_markdown(pdf_path: Path, profile: Profile, engine: Any) -> dict[str, str]:
    requests: dict[int, list[list[float]]] = defaultdict(list)
    owners: dict[tuple[int, int], list[str]] = defaultdict(list)
    scoped_parts: dict[str, list[str]] = defaultdict(list)
    for field_name, rule in profile.fields.items():
        if rule.bbox is None:
            continue
        scoped_parts[field_name] = []
        assert rule.pages is not None
        for page in rule.pages:
            index = len(requests[page])
            requests[page].append(list(rule.bbox))
            owners[(page, index)].append(field_name)

    if not requests:
        return {}

    page_regions = [(page, regions) for page, regions in sorted(requests.items())]
    results = engine.extract_text_in_regions(str(pdf_path), page_regions)
    for page_result in results:
        for index, region in enumerate(page_result.regions):
            for field_name in owners[(page_result.page, index)]:
                scoped_parts[field_name].append(
                    f"<!-- Page {page_result.page} -->\n\n{region.text.strip()}"
                )
    return {name: "\n\n".join(parts) for name, parts in scoped_parts.items()}


def process_document(
    pdf_path: Path,
    profile: Profile,
    engine: Any | None = None,
    ocr_provider: OcrProvider | None = None,
) -> dict:
    """Extract, OCR-complete, normalize tables, and create RAG-ready chunks."""
    engine = engine or _load_engine()
    page_result = engine.extract_pages_markdown(str(pdf_path))
    pages = [
        {
            "page": int(page.page),
            "markdown": page.markdown,
            "extraction_method": "native",
            "ocr_confidence": None,
        }
        for page in page_result.pages
    ]
    pages_by_number = {page["page"]: page for page in pages}
    requested_ocr_pages = sorted(set(page_result.pages_needing_ocr))
    completed_ocr_pages: list[int] = []
    ocr_error = None
    if requested_ocr_pages and ocr_provider is not None:
        try:
            for ocr_page in ocr_provider.extract_pages(pdf_path, requested_ocr_pages):
                if ocr_page.page not in pages_by_number:
                    continue
                pages_by_number[ocr_page.page].update(
                    markdown=ocr_page.markdown,
                    extraction_method="ocr",
                    ocr_confidence=ocr_page.confidence,
                )
                completed_ocr_pages.append(ocr_page.page)
        except Exception as exc:  # noqa: BLE001 - OCR failure keeps native partial output
            ocr_error = {"code": type(exc).__name__, "message": str(exc)}
    completed_ocr_pages = sorted(set(completed_ocr_pages))
    unresolved_ocr_pages = sorted(set(requested_ocr_pages) - set(completed_ocr_pages))

    markdown = _document_markdown(pages)
    scoped = _region_markdown(pdf_path, profile, engine)
    extraction = extract_fields(markdown, profile, scoped)
    page_markdown = [(page["page"], page["markdown"]) for page in pages]
    tables = extract_business_tables(page_markdown, profile)
    chunks = chunk_pages(
        page_markdown,
        document_id=_document_id(pdf_path),
    )

    document_issues = []
    if unresolved_ocr_pages:
        document_issues.append(
            {
                "reason": "ocr_failed" if ocr_error else "ocr_required",
                "pages": unresolved_ocr_pages,
                "message": (
                    "部分页面 OCR 执行失败，需要人工检查或重试。"
                    if ocr_error
                    else "这些页面没有可靠文本层，且未配置 OCR 提供方。"
                ),
                "error": ocr_error,
            }
        )
        extraction["status"] = "needs_review"
    if tables["status"] == "needs_review":
        extraction["status"] = "needs_review"

    return {
        **extraction,
        "document": {
            "page_count": len(page_result.pages),
            "pages_needing_ocr": unresolved_ocr_pages,
            "pages_ocr_completed": completed_ocr_pages,
            "pages_with_tables": list(page_result.pages_with_tables),
            "pages_with_columns": list(page_result.pages_with_columns),
            "is_complex_layout": bool(page_result.is_complex),
            "pages": pages,
            "issues": document_issues,
        },
        "ocr": {
            "provider": ocr_provider.name if ocr_provider is not None else None,
            "requested_pages": requested_ocr_pages,
            "completed_pages": completed_ocr_pages,
            "unresolved_pages": unresolved_ocr_pages,
            "error": ocr_error,
        },
        "tables": tables,
        "chunks": chunks,
        "markdown": markdown,
    }
