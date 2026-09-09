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
| `PDF_INSPECTOR_VECTOR_STORE` | `sqlite` | `sqlite` for local use or `pgvector` for production |
| `PDF_INSPECTOR_PGVECTOR_DSN` | unset | PostgreSQL connection string; required for `pgvector` |
| `PDF_INSPECTOR_EMBEDDING_PROVIDER` | `hash` | Built-in `hash` or `openai_compatible` |
| `PDF_INSPECTOR_EMBEDDING_MODEL` | `hash-v1` | Model identifier stored with every index |
| `PDF_INSPECTOR_EMBEDDING_DIMENSIONS` | `256` | Expected vector dimensions (8-4096) |
| `PDF_INSPECTOR_EMBEDDING_BATCH_SIZE` | `32` | Chunks per independently retryable batch (1-256) |
| `PDF_INSPECTOR_EMBEDDING_BASE_URL` | unset | OpenAI-compatible API base URL, normally ending in `/v1` |
| `PDF_INSPECTOR_EMBEDDING_API_KEY` | unset | Optional bearer token; never written to the database |
| `PDF_INSPECTOR_EMBEDDING_TIMEOUT_SECONDS` | `60` | Timeout for one embedding HTTP batch |

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

## Built-in knowledge bases

The knowledge layer persists this relationship:

```text
KnowledgeBase
└── Document (source task, file hash, chunk-set hash, status, progress)
    ├── Chunk (text, Markdown, pages, section path, content hash, index status)
    └── EmbeddingBatch (chunk IDs, attempts, status, last error)
```

Knowledge metadata and batch progress always use `.pdf-inspector-data/knowledge.sqlite3`. The default SQLite vector backend stores JSON vectors in the same file so development and tests work without external infrastructure. Use PostgreSQL + pgvector for production vector storage:

```bash
pip install -e ".[backend,pgvector]"
```

Enable pgvector in the target database and configure the service:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

```powershell
$env:PDF_INSPECTOR_VECTOR_STORE='pgvector'
$env:PDF_INSPECTOR_PGVECTOR_DSN='postgresql://pdf_user:password@localhost:5432/pdf_inspector'
pdf-inspector-api
```

The service creates `pdf_inspector_vectors`, stores vectors with their knowledge-base/document/chunk IDs and source metadata, and performs transactional upserts. The column uses unbounded `vector` so different knowledge bases may use different dimensions. A later retrieval deployment can add dimension-specific partial HNSW indexes when its production model dimensions are fixed.

### Embedding providers

The built-in `hash` provider is deterministic, local, dependency-free, and intended for development, lifecycle testing, and offline demos. For semantic retrieval, use an OpenAI-compatible embedding endpoint:

```powershell
$env:PDF_INSPECTOR_EMBEDDING_PROVIDER='openai_compatible'
$env:PDF_INSPECTOR_EMBEDDING_BASE_URL='https://api.example.com/v1'
$env:PDF_INSPECTOR_EMBEDDING_API_KEY='replace-me'
$env:PDF_INSPECTOR_EMBEDDING_MODEL='text-embedding-model'
$env:PDF_INSPECTOR_EMBEDDING_DIMENSIONS='1536'
```

The provider sends batched `POST /embeddings` requests with `model`, `input`, `encoding_format: float`, and `dimensions`. It validates response indexes, count, dimensions, and finite numeric values before writing any vector.

### Create and manage a knowledge base

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases \
  -H "Content-Type: application/json" \
  -d '{"name":"Product manuals","description":"Internal product documentation"}'

curl http://127.0.0.1:8000/v1/knowledge-bases
curl -X PATCH http://127.0.0.1:8000/v1/knowledge-bases/KB_ID \
  -H "Content-Type: application/json" \
  -d '{"description":"Updated documentation"}'
```

Deleting a knowledge base cascades through its documents, chunks, batches, and vectors. It does not delete source PDF tasks, uploads, or extraction results. Deletion is rejected while indexing is active.

### Ingest a completed PDF task

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/documents \
  -H "Content-Type: application/json" \
  -d '{"task_id":"TASK_ID","document_key":"product-manual"}'
```

`document_key` identifies a logical document across revisions and defaults to the uploaded filename. A task must already be `ready` or `needs_review`. Its quality-filtered chunks are copied into the knowledge base and split into independently persisted embedding batches.

Poll the document and inspect chunks or batches:

```bash
curl http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/documents/DOCUMENT_ID
curl http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/documents/DOCUMENT_ID/chunks
curl http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/documents/DOCUMENT_ID/batches
```

Document statuses are `queued`, `indexing`, `ready`, `partial`, and `failed`. When one batch fails, later batches continue. `partial` means some chunks are indexed and some failed; retrying queues only failed batches:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/documents/DOCUMENT_ID/retry
```

### Idempotency, incremental updates, and reindexing

- A unique PDF file hash prevents the same file from being inserted twice into one knowledge base, even under different document keys.
- A chunk-set hash detects changes caused by a newer preprocessing pipeline even when the source PDF is unchanged.
- Revisions submitted with the same `document_key` compare chunk kind, section, pages, and content hash. Unchanged indexed chunks keep their vectors; new or changed chunks are embedded; removed vectors are deleted through a durable cleanup queue.
- Batch attempts and errors survive restarts. Interrupted `processing` batches are returned to `queued` during startup.

Rebuild every document after changing the embedding provider, model, or dimensions:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/reindex \
  -H "Content-Type: application/json" \
  -d '{"embedding_provider":"openai_compatible","embedding_model":"new-model","embedding_dimensions":1536}'
```

Reindexing uses stable chunk IDs and overwrites each vector only after its replacement batch succeeds. A failed batch therefore remains observable and independently retryable rather than forcing the entire document to restart.

### Search and retrieval evaluation

Search a knowledge base with cosine similarity:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/search \
  -H "Content-Type: application/json" \
  -d '{
    "query":"How do I install the controller?",
    "top_k":5,
    "min_score":0.25,
    "document_ids":["DOCUMENT_ID"],
    "page_start":1,
    "page_end":20,
    "kinds":["text"],
    "section_path_prefix":["Installation"]
  }'
```

All filters are optional. Page bounds use overlap semantics, so a chunk is included when any of its pages falls inside the requested range. `section_path_prefix` matches the beginning of the complete heading path. Search only considers vectors produced by the knowledge base's current provider, model, and dimensions, preventing stale vectors from a partial reindex from being returned.

Every hit has a stable response shape with rank, cosine score, chunk ID, source document/task, original content, content hash, kind, page range, section path, and a ready-to-render `citation` object. The response also records end-to-end search latency.

Evaluate a version-controlled question set with expected document/page evidence:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/retrieval-evaluations \
  -H "Content-Type: application/json" \
  --data @examples/retrieval_eval.sample.json
```

The evaluator reports per-case Recall@K, reciprocal rank, first relevant rank, matched sources, and latency, plus aggregate mean Recall@K, MRR, mean latency, p95 latency, embedding time, and total runtime. An expected source with no `pages` accepts any hit from its document; when pages are supplied, at least one cited page must overlap.

LangChain is intentionally not required by the search core. A future optional adapter can expose this API as a LangChain Retriever without moving indexing, filtering, citation, or evaluation behavior out of the service.

### Grounded RAG answers

The answer layer uses the same provider boundary as the indexing layer. Its offline `extractive` provider returns source text directly for local development. Configure any OpenAI-compatible chat-completions endpoint, including a locally hosted compatible model, for generated answers:

```powershell
$env:PDF_INSPECTOR_LLM_PROVIDER='openai_compatible'
$env:PDF_INSPECTOR_LLM_BASE_URL='http://localhost:8000/v1'
$env:PDF_INSPECTOR_LLM_API_KEY='optional-local-or-remote-key'
$env:PDF_INSPECTOR_LLM_MODEL='chat-model'
$env:PDF_INSPECTOR_RAG_MAX_CONTEXT_TOKENS='4000'
$env:PDF_INSPECTOR_RAG_MAX_OUTPUT_TOKENS='800'
$env:PDF_INSPECTOR_RAG_MIN_EVIDENCE_SCORE='0.2'
```

Ask a grounded question:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How do I install the controller?","top_k":6}'
```

The response includes the answer, refusal flag, source citations, retrieval timing, context-token estimate, truncation status, provider/model, usage, and generation latency. Context selection follows search rank and never exceeds the configured budget; an oversized final chunk is truncated. When no result meets the evidence threshold, the service returns a fixed bilingual refusal without calling the LLM.

Set `"stream": true` to receive Server-Sent Events. The stream emits `metadata`, one or more `token` events, then `done`; provider failures are returned as an `error` event. Proxy buffering is disabled through response headers.

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
| `POST` | `/v1/knowledge-bases` | Create a knowledge base |
| `GET` | `/v1/knowledge-bases` | List knowledge bases |
| `GET` | `/v1/knowledge-bases/{id}` | Read a knowledge base and counts |
| `POST` | `/v1/knowledge-bases/{id}/search` | Search indexed chunks with metadata filters |
| `POST` | `/v1/knowledge-bases/{id}/retrieval-evaluations` | Evaluate Recall@K, MRR, and latency |
| `POST` | `/v1/knowledge-bases/{id}/ask` | Return a grounded answer or SSE stream with citations |
| `PATCH` | `/v1/knowledge-bases/{id}` | Update name or description |
| `DELETE` | `/v1/knowledge-bases/{id}` | Delete a knowledge base and its index |
| `POST` | `/v1/knowledge-bases/{id}/documents` | Ingest a completed PDF task |
| `GET` | `/v1/knowledge-bases/{id}/documents` | List indexed documents |
| `GET` | `/v1/knowledge-bases/{id}/documents/{document_id}` | Read status and progress |
| `GET` | `/v1/knowledge-bases/{id}/documents/{document_id}/chunks` | Inspect stored chunks |
| `GET` | `/v1/knowledge-bases/{id}/documents/{document_id}/batches` | Inspect embedding batches |
| `POST` | `/v1/knowledge-bases/{id}/documents/{document_id}/retry` | Retry failed batches only |
| `DELETE` | `/v1/knowledge-bases/{id}/documents/{document_id}` | Delete document chunks and vectors |
| `POST` | `/v1/knowledge-bases/{id}/reindex` | Rebuild vectors with a new model |
