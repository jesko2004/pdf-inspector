# pdf-inspector

Fast PDF classification and text extraction. Detects whether a PDF is text-based or scanned, extracts text with position awareness, and converts to clean Markdown — all without OCR. Python bindings via [PyO3](https://pyo3.rs) for the [pdf-inspector](https://github.com/jesko2004/pdf-inspector) Rust library.

## Features

- **Smart classification** — `text_based` / `scanned` / `image_based` / `mixed` in ~10–50ms, with a confidence score and per-page OCR routing.
- **Markdown conversion** — headings, lists, code blocks, bold/italic, URL linking, and dual-mode table detection (PDF drawing ops + text-alignment heuristics).
- **Layout-aware extraction** — multi-column reading order, position and font info per text item, RTL support.
- **Robust text decoding** — CID/Type0 fonts via ToUnicode CMaps, plus automatic flagging of broken encodings so callers can fall back to OCR.
- **Lightweight** — native Rust core, no ML models, no external services; ships type stubs.

## Install

```bash
git clone https://github.com/jesko2004/pdf-inspector.git
cd pdf-inspector
pip install maturin
maturin develop --release
```

## Usage

```python
import pdf_inspector

# Full processing: detect + extract + convert to Markdown
result = pdf_inspector.process_pdf("document.pdf")
print(result.pdf_type)      # "text_based", "scanned", "image_based", "mixed"
print(result.confidence)     # 0.0 - 1.0
print(result.page_count)     # number of pages
print(result.markdown)       # Markdown string or None

# Process specific pages only
result = pdf_inspector.process_pdf("document.pdf", pages=[1, 3, 5])

# Process from bytes (no filesystem needed)
with open("document.pdf", "rb") as f:
    result = pdf_inspector.process_pdf_bytes(f.read())

# Fast detection only (no text extraction)
result = pdf_inspector.detect_pdf("document.pdf")
if result.pdf_type == "text_based":
    print("Can extract locally!")
else:
    print(f"Pages needing OCR: {result.pages_needing_ocr}")

# Plain text extraction
text = pdf_inspector.extract_text("document.pdf")

# Positioned text items with font info
items = pdf_inspector.extract_text_with_positions("document.pdf")
for item in items[:5]:
    print(f"'{item.text}' at ({item.x:.0f}, {item.y:.0f}) size={item.font_size}")

# Per-page markdown (one Markdown string per page, plus layout metadata)
result = pdf_inspector.extract_pages_markdown("document.pdf")
for page in result.pages:
    print(f"Page {page.page}: {len(page.markdown)} chars, needs_ocr={page.needs_ocr}")

# Restrict to specific 1-indexed pages (preserves caller order)
result = pdf_inspector.extract_pages_markdown("document.pdf", pages=[1, 3])
```

All public page inputs and result fields are 1-indexed. Passing page `0`
raises `ValueError`.

## API reference

| Function | Description |
|---|---|
| `process_pdf(path, pages=None)` | Full processing (detect + extract + markdown) |
| `process_pdf_bytes(data, pages=None)` | Full processing from bytes |
| `detect_pdf(path)` | Fast detection only (returns PdfResult) |
| `detect_pdf_bytes(data)` | Fast detection from bytes |
| `classify_pdf(path)` | Lightweight classification (returns PdfClassification) |
| `classify_pdf_bytes(data)` | Lightweight classification from bytes |
| `extract_text(path)` | Plain text extraction |
| `extract_text_bytes(data)` | Plain text extraction from bytes |
| `extract_text_with_positions(path, pages=None)` | Text with X/Y coords and font info |
| `extract_text_with_positions_bytes(data, pages=None)` | Text with positions from bytes |
| `extract_text_in_regions(path, page_regions)` | Extract text in bounding-box regions |
| `extract_text_in_regions_bytes(data, page_regions)` | Region extraction from bytes |
| `extract_pages_markdown(path, pages=None)` | Per-page Markdown + layout metadata (all pages by default) |
| `extract_pages_markdown_bytes(data, pages=None)` | Per-page Markdown from bytes |

## Types

Type stubs (`pdf_inspector.pyi`) ship with the package. Result types at a glance:

```python
class PdfResult:                     # process_pdf / detect_pdf
    pdf_type: str                    # "text_based" | "scanned" | "image_based" | "mixed"
    markdown: str | None             # extracted Markdown (None for detect_pdf)
    page_count: int
    processing_time_ms: int
    pages_needing_ocr: list[int]
    title: str | None
    confidence: float                # 0.0 - 1.0
    is_complex_layout: bool
    pages_with_tables: list[int]
    pages_with_columns: list[int]
    has_encoding_issues: bool        # broken font encodings — consider OCR fallback

class PdfClassification:             # classify_pdf
    pdf_type: str
    page_count: int
    pages_needing_ocr: list[int]     # 1-indexed
    confidence: float

class TextItem:                      # extract_text_with_positions
    text: str
    x: float
    y: float
    width: float
    height: float
    font: str
    font_size: float
    page: int
    is_bold: bool
    is_italic: bool
    is_underline: bool
    is_strikeout: bool
    item_type: str

class PageRegionTexts:               # extract_text_in_regions
    page: int                        # 1-indexed
    regions: list[RegionText]        # RegionText: text: str, needs_ocr: bool

class PagesExtractionResult:         # extract_pages_markdown
    pages: list[PageMarkdown]        # PageMarkdown: page (1-indexed), markdown, needs_ocr
    pages_with_tables: list[int]     # 1-indexed
    pages_with_columns: list[int]    # 1-indexed
    pages_needing_ocr: list[int]     # 1-indexed
    is_complex: bool                 # any page has tables or multi-column layout
```
