# PDF task API and business profiles

The optional backend turns the native extractor into a persistent local HTTP service. It is designed for trusted internal networks; put authentication, TLS, and rate limiting at the gateway before exposing it publicly.

## Install and start

Build the Python extension and install the optional server dependencies:

```bash
pip install maturin
maturin develop --features python
pip install -e ".[backend]"
pdf-inspector-api
```

To run OCR locally, install the additional models and inference runtime:

```bash
pip install -e ".[backend,ocr]"
```

The service listens on `127.0.0.1:8000`. OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

Environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `PDF_INSPECTOR_DATA_DIR` | `.pdf-inspector-data` | SQLite database, uploads, results, and custom profiles |
| `PDF_INSPECTOR_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `PDF_INSPECTOR_WORKERS` | `2` | In-process extraction workers |
| `PDF_INSPECTOR_HOST` | `127.0.0.1` | Listen address |
| `PDF_INSPECTOR_PORT` | `8000` | Listen port |
| `PDF_INSPECTOR_OCR_PROVIDER` | `none` | `none`, built-in `rapidocr`, or external `command` |
| `PDF_INSPECTOR_OCR_COMMAND_JSON` | unset | OCR adapter command as a JSON string array |
| `PDF_INSPECTOR_OCR_TIMEOUT_SECONDS` | `180` | Per-document OCR timeout |
| `PDF_INSPECTOR_OCR_DPI` | `200` | PDF render resolution for built-in RapidOCR (72-600) |
| `PDF_INSPECTOR_OCR_MIN_CONFIDENCE` | `0.5` | Minimum RapidOCR line confidence (0-1) |

For multi-host deployment, replace the in-process executor and local files with a shared queue/object store. A single service process is durable across restarts: SQLite retains tasks and interrupted `processing` tasks are queued again on startup.

## Task workflow

Create a task with the built-in purchase-quote profile:

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks \
  -F "profile_id=purchase_quote" \
  -F "file=@quote.pdf;type=application/pdf"
```

Poll status and progress:

```bash
curl http://127.0.0.1:8000/v1/tasks/TASK_ID
```

Statuses are `queued`, `processing`, `ready`, `needs_review`, and `failed`. `ready` and `needs_review` both have a result; `needs_review` means a required field/table is missing, values conflict/fail validation, or a page still requires OCR.

Read or download the result:

```bash
curl http://127.0.0.1:8000/v1/tasks/TASK_ID/result
curl -OJ "http://127.0.0.1:8000/v1/tasks/TASK_ID/result?download=true"
```

Retry a failed task:

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks/TASK_ID/retry
```

Each task snapshots the profile version used at submission. Updating a custom profile does not silently change an existing task or its retry.

## Extraction profiles

Profiles may be stored as UTF-8 JSON under `backend/profiles/` (built-in, read-only through the API), or created through `POST /v1/profiles`. Custom profiles are stored under the data directory and can be replaced with `PUT /v1/profiles/{id}`.

```json
{
  "id": "my_quote",
  "name": "我的报价单",
  "version": 1,
  "fields": {
    "supplier_name": {
      "aliases": ["供应商", "报价单位", "Supplier"],
      "required": true,
      "pages": [1]
    },
    "quote_date": {
      "aliases": ["报价日期", "Quote Date"],
      "type": "date",
      "required": true
    },
    "total_amount": {
      "aliases": ["含税总额", "Grand Total"],
      "type": "decimal",
      "required": true,
      "min_value": "0",
      "pages": [1],
      "bbox": [300, 500, 580, 760]
    }
  }
}
```

Field options:

| Option | Meaning |
|---|---|
| `aliases` | Labels accepted before `:`, `：`, or a Markdown table separator |
| `type` | `text`, `decimal`, or `date`; normalized values are returned as strings |
| `required` | Missing values make the task `needs_review` |
| `pages` | Allowed 1-indexed pages |
| `section_start`, `section_end` | Case-insensitive section boundary text |
| `bbox` | `[x1,y1,x2,y2]` in PDF points with a top-left origin; requires `pages` |
| `pattern` | Optional full-match regular expression, at most 256 characters |
| `min_value`, `max_value` | Inclusive bounds for decimal fields |

Every extracted field retains `source_text`, 1-indexed `page`, all `candidates`, and the configured `bbox` where applicable. Conflicting candidate values are never chosen silently.

The built-in `purchase_quote` profile covers supplier, quote number/date, total amount, currency, contact, and a required `line_items` table. Product name, model, quantity, unit, unit price, and line amount are mapped from Chinese or English headers. Decimal values and common units are normalized before output.

## Business tables

Add a `tables` object to a profile to map varying source headers to canonical columns:

```json
{
  "tables": {
    "line_items": {
      "required": true,
      "columns": {
        "product_name": {
          "aliases": ["品名", "产品名称", "Item"],
          "required": true
        },
        "quantity": {
          "aliases": ["数量", "Qty"],
          "type": "decimal",
          "required": true,
          "min_value": "0"
        },
        "unit": {
          "aliases": ["单位", "Unit"],
          "type": "unit"
        }
      }
    }
  }
}
```

Column types are `text`, `decimal`, `integer`, and `unit`. Every table result retains its source page, original headers, Markdown, normalized rows, and row-level validation issues. Tables that do not match a configured schema are still returned with generated column names.

Read all tables or download one as an Excel-compatible UTF-8 CSV:

```bash
curl http://127.0.0.1:8000/v1/tasks/TASK_ID/tables
curl -OJ http://127.0.0.1:8000/v1/tasks/TASK_ID/tables/line_items_1.csv
```

## Per-page OCR completion

The native detector supplies `pages_needing_ocr`. The task processor sends only those pages to a configured adapter and merges successful OCR output back into the original page order before field extraction, table normalization, and chunking.

### Built-in local RapidOCR

The built-in provider renders only the requested pages with PyMuPDF and recognizes Chinese/English text locally with RapidOCR and ONNX Runtime. No PDF or recognized text is sent to an external service. Lines below the configured confidence threshold are discarded, the remaining lines are restored to top-to-bottom order, and their mean confidence is recorded on the page.

```powershell
$env:PDF_INSPECTOR_OCR_PROVIDER='rapidocr'
$env:PDF_INSPECTOR_OCR_DPI='200'
$env:PDF_INSPECTOR_OCR_MIN_CONFIDENCE='0.5'
pdf-inspector-api
```

### External command adapter

Configure an adapter command as a JSON array. `{pdf}` is replaced with the uploaded PDF path and `{pages}` with a comma-separated 1-indexed page list:

```powershell
$env:PDF_INSPECTOR_OCR_PROVIDER='command'
$env:PDF_INSPECTOR_OCR_COMMAND_JSON='["python","ocr_adapter.py","--pdf","{pdf}","--pages","{pages}"]'
```

The command must write UTF-8 JSON to stdout:

```json
{
  "pages": [
    {"page": 2, "markdown": "OCR 后的 Markdown", "confidence": 0.97}
  ]
}
```

This contract can wrap PaddleOCR, a GPU OCR service, or a cloud OCR SDK without coupling the task service to one vendor. For backward compatibility, setting the command without `PDF_INSPECTOR_OCR_PROVIDER` still selects the command provider. Missing or failed pages remain in `document.pages_needing_ocr` and cause `needs_review`; successful pages record `extraction_method: "ocr"` and confidence.

## Knowledge-base preprocessing

Every result contains a `chunks` array suitable for embedding or direct ingestion by LangChain/LlamaIndex. Chunking tracks Markdown headings across pages and emits deterministic IDs, content hashes, page citations, `section_path`, `kind`, and both Markdown/plain text. Tables stay atomic; oversized tables split only between rows and repeat their header.

Before chunks are returned, recurring first/last-page lines (including changing page numbers) are removed, punctuation-only and very short text chunks are rejected, and normalized exact duplicates inside the same section are collapsed. Duplicate chunks retain the combined `pages`, `page_start`, `page_end`, and `source_occurrences`, so deduplication does not lose source citations. Tables are exempt from the minimum-length rule.

```bash
curl http://127.0.0.1:8000/v1/tasks/TASK_ID/chunks
```

The endpoint also returns a `quality` object with candidate/emitted counts, rejection reasons, duplicate counts, and removed margin lines. The same report is stored as `chunk_quality` in the complete task result, making ingestion quality observable.

Recommended vector-store metadata fields are `id`, `page_start`, `page_end`, `section_path`, `kind`, and `content_hash`. The stable ID/hash pair supports idempotent upsert and incremental re-indexing when documents change.

## API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/v1/profiles` | List complete built-in and custom profiles |
| `GET` | `/v1/profiles/{id}` | Read a profile |
| `POST` | `/v1/profiles` | Create a custom profile |
| `PUT` | `/v1/profiles/{id}` | Replace a custom profile |
| `POST` | `/v1/tasks` | Upload a PDF and queue extraction |
| `GET` | `/v1/tasks` | List tasks with pagination |
| `GET` | `/v1/tasks/{id}` | Read task status and progress |
| `GET` | `/v1/tasks/{id}/result` | Read/download structured JSON |
| `GET` | `/v1/tasks/{id}/tables` | Read normalized business tables |
| `GET` | `/v1/tasks/{id}/tables/{table_id}.csv` | Download one table as CSV |
| `GET` | `/v1/tasks/{id}/chunks` | Read RAG-ready chunks |
| `POST` | `/v1/tasks/{id}/retry` | Retry a failed task |
