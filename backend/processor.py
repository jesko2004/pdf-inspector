"""Adapter from the native extractor to business-field results."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .profiles import Profile, extract_fields


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


def _document_markdown(pages: list[Any]) -> str:
    parts = []
    for page in pages:
        parts.append(f"<!-- Page {page.page} -->\n\n{page.markdown.strip()}")
    return "\n\n".join(parts).strip() + "\n"


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
    pdf_path: Path, profile: Profile, engine: Any | None = None
) -> dict:
    """Extract per-page Markdown and apply a snapshotted business profile."""
    engine = engine or _load_engine()
    page_result = engine.extract_pages_markdown(str(pdf_path))
    markdown = _document_markdown(list(page_result.pages))
    scoped = _region_markdown(pdf_path, profile, engine)
    extraction = extract_fields(markdown, profile, scoped)

    ocr_pages = sorted(set(page_result.pages_needing_ocr))
    document_issues = []
    if ocr_pages:
        document_issues.append(
            {
                "reason": "ocr_required",
                "pages": ocr_pages,
                "message": "这些页面没有可靠文本层，需要 OCR 后重新处理字段。",
            }
        )
        extraction["status"] = "needs_review"

    return {
        **extraction,
        "document": {
            "page_count": len(page_result.pages),
            "pages_needing_ocr": ocr_pages,
            "pages_with_tables": list(page_result.pages_with_tables),
            "pages_with_columns": list(page_result.pages_with_columns),
            "is_complex_layout": bool(page_result.is_complex),
            "issues": document_issues,
        },
        "markdown": markdown,
    }
