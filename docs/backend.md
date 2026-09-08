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

The service listens on `127.0.0.1:8000`. OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

Environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `PDF_INSPECTOR_DATA_DIR` | `.pdf-inspector-data` | SQLite database, uploads, results, and custom profiles |
| `PDF_INSPECTOR_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `PDF_INSPECTOR_WORKERS` | `2` | In-process extraction workers |
| `PDF_INSPECTOR_HOST` | `127.0.0.1` | Listen address |
| `PDF_INSPECTOR_PORT` | `8000` | Listen port |

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

Statuses are `queued`, `processing`, `ready`, `needs_review`, and `failed`. `ready` and `needs_review` both have a result; `needs_review` means a required field is missing, values conflict/fail validation, or a page requires OCR.

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

The built-in `purchase_quote` profile covers supplier, quote number/date, product name, quantity, unit price, total amount, currency, and contact. It extracts labeled scalar values. Reconstructing multiple product rows from arbitrary tables belongs to the separate structured-table stage.

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
| `POST` | `/v1/tasks/{id}/retry` | Retry a failed task |
