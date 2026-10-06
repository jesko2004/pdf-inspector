# PDF task API and business profiles

## 2026年10月6日负责人确认与交付

使用者在公开回归结果与正式门槛说明之后明确回复“我已经审核过，没有问题，可以进行下一步”。本轮总体验收确认及采用公开完整 200 份回归的授权已记录在 [负责人确认](evidence/single-machine-owner-acceptance-2026-10-06.json)。用户接受固定资料的已知局限，授权继续提交、CI 和发布；未收到逐题标签导出，原空白模板及逐题人工计数仍保留，不能把总体确认伪造为 30 份逐题表单。

固定 8 项内的工程可靠性、实际 Ollama 接入、五项质量修复、30 题 AI 原文复核、Word 原生分页与公开完整回归已完成。公开回归是已实际运行的正式替代门槛，AGENTS.md 已按用户确认更新；原 pdf-evals 仍未取得、未执行，没有采用测试豁免。公开 200 份均完成，输出无变化，7 项指标无下降；1 份原生空输出也计入。后端 246 通过、2 项本机 PostgreSQL 配置缺失跳过；真实数据库检查由仓库 CI 执行。

验收证据见 [本轮证据](evidence/single-machine-reliability-2026-10-05.json)与[公开回归](external-public-regression.md)。实际提交、精确提交 CI 和合并状态以 [GitHub PR](https://github.com/jesko2004/pdf-inspector/pulls)、[Actions](https://github.com/jesko2004/pdf-inspector/actions)及 [本轮发布](https://github.com/jesko2004/pdf-inspector/releases/tag/single-machine-2026-10-06)为准；本轮发布包含实际 SHA 和验收附件，全部检查通过才合并发布，完成后停止。下方较早状态仅为历史审计，不能作为新的阻塞条件或重新开启旧清单。

## 以下为负责人确认前的历史说明

## 2026年10月6日收尾状态

2026年10月6日：原第 11、12、21、26、27 题的五项质量问题已关闭。完整 30 题为 24 作答、6 拒答、0 调用错误、0 误拒答；AI 逐条核对展示的声明及证据，24 题事实有原文支持、6 题拒答合理。这是两份已知 PDF 的 AI 事实与引用复核，不是通用准确率或独立人工签署；用户人工仍为 0/30。

- 新报告 `test_output/minimum-landing/ollama-acceptance-v2-20261006.json`，独立目录 `.pdf-inspector-data/ollama-acceptance-v2-20261006`。旧报告全部保留，未逐题挑选重试结果。
- [修复验收页](../output/30题Ollama修复验收/核对结果.html)列原页、答案、引用及理由；[完整包](../output/30题Ollama修复验收包.zip)含原 PDF、页面图和绑定新报告的人工空白模板。旧审核包保留。
- 四道价格现覆盖同一车型行、税后金额与 KRW 表头；中文日期误拒答已关闭。答案未硬编码。短表格介绍复制到同页同节的后续父片段；旧资料须重新解析及入库，单独重算向量不迁移正文。
- 严格 JSON、来源身份和原文摘录仍校验；服务器仅补充实际输入中同一行标签、邻近短表头。重复同文声明保留首项，其他项及摘录保存在 `validation.duplicate_claims_omitted`；所有原始项必须先通过契约及精确摘录校验。
- `grounded_json` 的普通与流式 OpenAI 兼容请求现在带 JSON Schema `response_format`。服务仍独立校验，不能假设提供方一定遵守 Schema；不支持时明确失败，不自动放宽或改成文本。[Ollama 官方格式说明](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx)。
- 局限保留：英文日期题有时用中文回答，事实正确；物性父引用附带第 3 页，实际依据在第 2 页；中文型号存在性题的强制拒答标签有歧义。旧中文焓重复项误引熵的反例保留，不能宣称模型原始输出全部正确。
- 后端最终 248 项中 246 通过、2 项真实 PostgreSQL 未配置跳过；真实 HTTP 冷备份恢复 11 项通过。沙箱无法加载 ONNX DLL／清理原生服务进程的首轮失败保留，同一断言在原生执行环境通过。Rust 源码未变，893 项及格式、严格 Clippy、release 有效日志保留。
- 最终 30 次成功生成返回 prompt 56169、completion 2531、total 58700；不含历史运行、调试、Embedding 或契约检查，也不是账单。仍为本机 Ollama 的 1024 维向量和 8192 窗口生成别名；字符估算预算 1200、输出 1200。固定 seed 不保证新入库随机来源 ID 改变后输出一致。
- Word 保留 93 题、四段回答、139 个书签、2 张表；使用已校验 SHA256 和官方签名的工作区原生 LibreOffice 渲染，最终 50 页已逐页检查通过，未发现遮挡、裁切或表格溢出；结论及指纹见 [证据](evidence/single-machine-reliability-2026-10-05.json)。原生工具不是服务依赖。
- `F:/pdf-evals/bench.py` 尚未取得。已登录账号读取预期两个仓库均为 404，代码搜索无套件，使用者回复“没有地址”；404 不证明仓库不存在。`AGENTS.md` 要求提交前运行该套件，使用者拒绝例外；外部回归未执行，未提交、PR、CI 或发布。
- 原 44 个暂存文件保留，本轮未新增暂存，固定 8 项不扩展。

## 2026年10月5日及以前的说明与验收快照

以下保留操作说明与历史数字。当前状态以上方收尾记录及证据为准。

The optional backend turns the native extractor into a persistent HTTP service. It includes optional API-key authentication, role checks, rate limits, audit records, Prometheus metrics, and verified local backups. Terminate TLS at a trusted reverse proxy before exposing it publicly.

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

To expose the existing search as a LangChain Runnable and enable the optional
CPU-only FlashRank reranker:

```bash
pip install -e ".[backend,rag-langchain]"
```

The `rag-langchain` extra requires Python 3.10 or newer. FlashRank downloads its
selected model on first use (about 100 MB for the default multilingual model),
so production deployments should pre-warm the model cache before accepting
traffic.

The service listens on `127.0.0.1:8000`. OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

The local upload/query/source-review/feedback page is at `/demo`. See
[the minimum landing report](minimum-landing.md) for reproducible offline evaluation
and the remaining real-model acceptance work. The console launcher refuses a
non-loopback host unless API keys are configured. One OS-owned executor lock is
held per data directory; do not run multiple Uvicorn workers against it.

Environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `PDF_INSPECTOR_DATA_DIR` | `.pdf-inspector-data` | SQLite database, uploads, results, and custom profiles |
| `PDF_INSPECTOR_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `PDF_INSPECTOR_WORKERS` | `2` | Concurrent isolated PDF operations |
| `PDF_INSPECTOR_PROCESS_TIMEOUT_SECONDS` | `300` | Wall-clock deadline including PDF worker startup |
| `PDF_INSPECTOR_PROCESS_MEMORY_MB` | `2048` | Per-operation MiB budget; Windows aggregate job commit, POSIX per-process address space |
| `PDF_INSPECTOR_PROCESS_MAX_RESULT_BYTES` | `33554432` | Maximum result JSON or preview PNG bytes |
| `PDF_INSPECTOR_PDF_MAX_PAGES` | `2000` | Page-count preflight inside the isolated process |
| `PDF_INSPECTOR_PREVIEW_TIMEOUT_SECONDS` | `15` | Deadline including single-page preview startup |
| `PDF_INSPECTOR_PREVIEW_WORKERS` | `1` | Concurrent previews; capacity exhaustion immediately returns 429 |
| `PDF_INSPECTOR_OCR_MAX_PIXELS` | `20000000` | Built-in OCR raster limit checked before rendering/model initialization |
| `PDF_INSPECTOR_HOST` | `127.0.0.1` | Listen address |
| `PDF_INSPECTOR_PORT` | `8000` | Listen port |
| `PDF_INSPECTOR_OCR_PROVIDER` | `none` | `none`, built-in `rapidocr`, or external `command` |
| `PDF_INSPECTOR_OCR_COMMAND_JSON` | unset | OCR adapter command as a JSON string array |
| `PDF_INSPECTOR_OCR_TIMEOUT_SECONDS` | `180` | Command OCR wait limit; total PDF worker deadline also applies |
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
| `PDF_INSPECTOR_API_KEYS_JSON` | `[]` | API keys and `read`/`write`/`admin` roles; an empty array keeps local development unauthenticated |
| `PDF_INSPECTOR_SEARCH_RATE_LIMIT_PER_MINUTE` | `120` | Per-key/IP search requests per minute |
| `PDF_INSPECTOR_ASK_RATE_LIMIT_PER_MINUTE` | `30` | Per-key/IP answer requests per minute |
| `PDF_INSPECTOR_MAX_ACTIVE_TASKS` | `100` | Maximum combined queued and processing PDF tasks |
| `PDF_INSPECTOR_QUERY_ALIASES_JSON` | `{}` | Optional abbreviation-to-expansion map used by bounded query rewriting |
| `PDF_INSPECTOR_RRF_K` | `60` | RRF rank constant (1-10000); request `rrf_k` can override it |
| `PDF_INSPECTOR_BM25_K1` | `1.2` | BM25 term-frequency saturation (greater than 0, at most 10) |
| `PDF_INSPECTOR_BM25_B` | `0.75` | BM25 length normalization (0-1) |
| `PDF_INSPECTOR_RAG_ANSWER_FORMAT` | `grounded_json` | External model contract: `grounded_json` or compatibility `text`; extractive mode always previews evidence |
| `PDF_INSPECTOR_RERANK_PROVIDER` | `none` | `none` or optional local `flashrank` reranking |
| `PDF_INSPECTOR_RERANK_MODEL` | `ms-marco-MultiBERT-L-12` | FlashRank model; the default supports multilingual workloads |
| `PDF_INSPECTOR_RERANK_CANDIDATES` | `12` | RRF candidates sent to the second-stage reranker (2-100) |
| `PDF_INSPECTOR_RERANK_TOP_N` | `5` | Maximum reranked results returned to generation |
| `PDF_INSPECTOR_RERANK_MAX_LENGTH` | `256` | Maximum query-plus-child token window used by FlashRank (32-512) |
| `PDF_INSPECTOR_RERANK_TIMEOUT_MS` | `500` | Fail-open reranking time budget (10-30000 ms) |

The default service supervises disposable PDF/OCR and preview processes. Timeouts and shutdown terminate ordinary worker descendants; queued tasks persist for restart. Uploads and failed-task retries share the same admission limit. Preview capacity returns 429, preview timeout 504, and worker unavailability 503. See [resource budgets, platform differences and fault evidence](resource-isolation.md).

For multi-host deployment, replace the local scheduling executor and local files with a shared queue/object store. A single service process is durable across restarts: SQLite retains tasks and interrupted `processing` tasks are queued again on startup.

## Minimum landing retrieval and answer contract

Search, ask, and retrieval-evaluation requests accept `retrieval_mode` with values
`vector` (the compatibility default), `bm25`, or `hybrid`, and optional `rrf_k`.
BM25 searches the eligible indexed-child snapshot and applies the same version,
document, page, kind, section, and table scopes. It tokenizes complete ASCII model
identifiers and Chinese characters/bigrams after NFKC normalization. It scans a
small corpus rather than maintaining a large inverted index. BM25-only queries
do not call the query embedding provider; ingestion still uses the existing
embedding lifecycle.

`min_score` applies only to vector cosine scores. BM25 positive scores and RRF
scores are ranking signals, not calibrated answerability thresholds. Results
include `score_kind`, nullable `semantic_score`/`bm25_score`, `fusion_score`, and
per-route raw candidates under `routes`. When a chunk occurs in both routes, its
top-level raw score comes from the first retained hit; inspect the route trace
for both scores. Rewriting can multiply route votes, so redundant variants should
be controlled separately.

Evaluation expected sources can include `required_text`, a list of normalized
text fragments that must occur in the child evidence in addition to matching
document/pages. This avoids counting any chunk on a correct page as relevant;
it remains a lexical diagnostic rather than semantic grading.

After a batch embedding response is normalized, vectors are persisted in a
checkpoint before vector upsert and completion confirmation. Retries reuse the
checkpoint only for the same provider/model/dimensions/generation/chunks payload.
Successful completion removes it. A crash between provider response and checkpoint
commit can still cause another billable call; no provider exactly-once guarantee
or global generation cache is claimed.

Answers report final `status`, `refused`, `claims`, and `validation`, including
streaming completion events. External models default to a strict JSON contract:
an `answerable` boolean and a list of claims, each carrying supplied `chunk_id`
values and verbatim evidence quotes. Unknown fields, duplicate JSON keys,
inconsistent flags, missing sources, and quotes outside the exact truncated
context fail validation. The server renders filenames and pages and returns
only citations used by the claims. No automatic model repair/retry is performed.
`completed` means this contract and quote membership passed; it does not certify
semantic entailment. `validation.semantic_support` makes that boundary explicit.
Extractive evidence previews and compatibility `text` answers are `needs_review`.
Canonical refusal clears citations. Empty text and invalid inline file/page
identities in compatibility mode are generation errors.
Source attributes and body text are escaped before prompt assembly. Context
metadata distinguishes parent deduplication from truncation/omission and declares
`counting_method: character_estimate`; exact model-window accounting is pending.

`GET /demo` serves only the static local page. Data requests still require their
normal role permissions when authentication is enabled. `GET /v1/tasks/{id}/source`
returns the managed original PDF through the read permission; it accepts a task
identity. `GET /v1/tasks/{id}/source/pages/{page}.png` renders one protected page,
with a 2-million-pixel output limit and a 4096-pixel maximum edge. The backend
extra includes PyMuPDF. The page preview avoids dependence on browser PDF plugins;
the original download remains available. Output bounds are not hard memory/CPU
isolation for decoding an arbitrary PDF. Unknown tasks/pages return 404, corrupt
PDFs 422, and a missing preview dependency 503. Images use `Cache-Control: no-store`.

The demo shows verbatim evidence per claim and lets users mark each citation
supported/unsupported/unreviewed and provide a correction. Helpful feedback never
automatically marks all citations valid. New citations include the managed task
ID; legacy citations resolve through the single-document endpoint, without a
200-document listing limit. Offline previews return only their first excerpt's
source citation.

For real-model setup, run `python -m scripts.check_models --output readiness.json`.
Missing configuration triggers no calls. Once configured, the probe makes a small
embedding batch plus grounded generation/stream requests using a non-sensitive
fixture; these requests can consume paid tokens. This is contract validation only.
Reports do not retain raw provider error bodies that might echo credentials.

`python -m scripts.minimum_landing --work-dir EVAL_DIR --output report.json`
keeps an isolated SQLite corpus and atomic evaluation checkpoints. Add `--resume`
to reuse completed units and `--retry-failed` to explicitly rerun failures. The
fingerprint covers input bytes, dataset, provider/model/endpoints, budgets and
pipeline code; key rotation is allowed. Existing service directories are rejected.
Per-case errors are retained while other questions continue. Interrupted provider
responses that were not saved can still be billed again, and retrying a failed
retrieval configuration can repeat query embeddings within that unit. Report usage
totals cover successful retained generation responses, not total billing.

Benchmark datasets now validate unique IDs, document references, strict answerable
flags, positive pages and required evidence before execution. The bilingual v2
fixture has 30 English/Chinese cases; labels still require human review and both
splits share document families. `python -m scripts.score_landing prepare` exports
an unreviewed JSON template and per-case Markdown sheet from a saved report.
`score` grades that report without any model calls, separates machine diagnostics
from explicit human verdicts, reports review coverage and binds reviews to dataset
and report hashes. Use `--dataset`, `--report`, `--output-dir` and optionally
`--reviews`; outputs refuse overwrite unless `--overwrite` is supplied.
The reviewer field records attribution; it does not authenticate a reviewer.

Original source lookup accepts a task
identity, not an arbitrary filesystem path. The page uses `manual_query`, lets
users select a retrieval mode, view source pages, and submit feedback. It is
designed for a small local corpus.

## Production controls

Configure API keys as a JSON array. Keys are accepted through `Authorization: Bearer` or `X-API-Key`; secrets never appear in logs, metrics, or audit rows.

```powershell
$env:PDF_INSPECTOR_API_KEYS_JSON='[
  {"id":"app-reader","key":"replace-read-secret","role":"read"},
  {"id":"pipeline","key":"replace-write-secret","role":"write"},
  {"id":"operator","key":"replace-admin-secret","role":"admin"}
]'
```

`read` can call GET endpoints plus search, evaluation, and answer endpoints. `write` also creates tasks, profiles, knowledge bases, ingestion jobs, retries, and reindex jobs. `admin` additionally deletes resources, reads audit events, and scrapes metrics. `/health` and OpenAPI pages remain public. Authentication is disabled only when the key array is empty.

Every response includes `X-Request-ID`; a valid caller-supplied ID is preserved. Structured request logs and mutating/denied audit events use the same ID. Admins can inspect audit history with `GET /v1/audit-events`. `GET /metrics` exposes Prometheus text metrics for HTTP traffic, operation errors and duration, task/index queue depth, embedding/retrieval/LLM activity, Token usage, refusals, and rate-limit rejection.

Upload bytes, active tasks, per-key/IP search and answer frequency, and RAG context/output Tokens are bounded. Rate and capacity failures return HTTP `429` with a stable error detail; rate responses include `Retry-After`. The in-memory rate limiter is intentionally single-process. Use a gateway or Redis-backed limiter when phase-5 multi-instance work is enabled.

SQLite stores maintain a `schema_migrations` ledger and validate migration names/versions at startup. Migrations run transactionally and are forward-only. The knowledge store schema is currently version 7 (5: atomic publication, 6: index lifecycle, 7: bounded deletion retries); explicit request operations have a separate version-1 ledger in the task database. Future schema changes must be appended as a new migration. Roll back an incompatible release by restoring its verified pre-upgrade backup rather than attempting an in-place downgrade.

Stop the service and wait for the executor to exit before creating a complete local SQLite backup. The backup command takes the same exclusive executor lock and refuses a running service or external vector store:

```powershell
pdf-inspector-backup create .pdf-inspector-data backups\pdf-inspector-20260909.tar.gz
pdf-inspector-backup verify backups\pdf-inspector-20260909.tar.gz
pdf-inspector-backup restore backups\pdf-inspector-20260909.tar.gz .pdf-inspector-restored
```

SQLite files use the SQLite backup API while the executor is stopped; uploads, results, profiles, vectors, audit data and saved request results are checksummed in a versioned manifest. Integrity and foreign-key checks run before publication. Worker directories, executor locks and query leases are excluded. Restore rejects unsafe paths, unsupported members, checksum mismatches, undeclared files and non-empty targets; it verifies and rebinds managed paths in a sibling staging directory before atomically publishing the new directory. Start against the restored directory with the old source unavailable, then check retrieval, original PDF downloads, saved-answer replay and new ingestion. Model credentials remain in local environment variables. See [single-machine operation and acceptance](single-machine-reliability.md).

Uploads and answers accept `Idempotency-Key` (1–128 printable ASCII characters without spaces), scoped to the caller. Same-key payload conflicts return 409; saved results replay with `X-Operation-ID` and `Idempotency-Replayed`. Uncertain paid calls never retry automatically with the same key. Inspect `GET /v1/operations/{id}` before deciding on a new operation. Same-key streaming answers are saved in full before SSE delivery. Requests without a key retain the previous behavior.

Administrators can inspect `GET /v1/maintenance/vector-deletions` and explicitly replay blocked work with `POST /v1/maintenance/vector-deletions/retry`. Background maintenance runs every 5 seconds, processes at most 1000 entries, retries temporary failures with bounded backoff and blocks after the fifth failure; permissions and invalid parameters block immediately. Pending and blocked counts are exposed as metrics. Rate-limit identity/bucket entries are capped at 10000 and active entries are retained when the table is full.

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

`ready` means the implemented checks did not require review; it does not certify that every visible character or image-text region was extracted. Undetected omissions may not produce `needs_review`. Check source pages when missing text could affect business evidence, and resolve conflicting field candidates against their sources. The known invoice BSB conflict correctly remains `needs_review`; changing it to `ready` is not an acceptance goal.

The current [offline acceptance scope](acceptance-scope.md) uses a single instance, SQLite, local RapidOCR, and hash/extractive providers. It validates the local workflow, not real-model answer quality or production service levels. The [acceptance report](acceptance-report.md) separates completed checks from remaining closeout work.

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

The native detector supplies `pages_needing_ocr`. The task processor sends those pages to a configured adapter and merges successful OCR output back into the original page order before field extraction, table normalization, and chunking. Local RapidOCR additionally supports the bounded cover-supplement path described below; command adapters retain the page-level contract.

This is not exhaustive image-text region detection on every page with a native text layer. The catalogue cover case (Q-04) is addressed by the local supplement path, while general native/image text completion remains outside the acceptance guarantee. Review source pages when business evidence depends on content outside the validated scope.

### Built-in local RapidOCR

The built-in provider renders only the requested pages with PyMuPDF and recognizes Chinese/English text locally with RapidOCR and ONNX Runtime. No PDF or recognized text is sent to an external service. Lines below the configured confidence threshold are discarded, the remaining lines are restored to top-to-bottom order, and their mean confidence is recorded on the page.

The confidence describes retained recognized lines, not completeness of page coverage. Complete handwriting or rotated-stamp recognition is outside the current acceptance guarantee. Cosmetic formatting limitations may be deferred only while key values, units, field meanings, and source relationships remain intact; semantic errors still require correction.

For a native page with at most 200 text characters wholly inside the outer 15% margins and a displayed image covering at least 80% of the page, RapidOCR also checks for supplementary image text. Rotated or cropped pages are excluded from this path. Normal body pages do not initialize the OCR engine or render images for supplementation. These conservative conditions target image covers; small logos, dense native pages, arbitrary image regions, and complete layout reconstruction are not included.

Supplementation preserves native Markdown, places recognized additions before it, and filters OCR lines whose bounds substantially overlap native spans. It records `extraction_method: "native+ocr"`, `ocr_confidence`, and `ocr.supplemented_pages`; page-level `requested_pages`/`completed_pages` retain their existing meaning. The additions enter field extraction and chunks with their source page. Bounding-box profile fields still use native region extraction, so supplementation does not add OCR-aware field coordinates.

Empty cover recognition produces `ocr_supplement_empty`; a supplementary check failure produces `ocr_supplement_failed`. Both preserve native output and require review. Details appear in `document.issues`, `ocr.supplement_unresolved_pages`, and `ocr.supplement_error`. If inspection fails before a page can be identified, the issue's page list may be empty; this does not mean the check passed. Supplementary processing time is recorded as the `ocr_supplement` metric.

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
- Revisions submitted with the same `document_key` compare chunk kind, section, pages, and content hash. Unchanged indexed chunks keep their vectors; new or changed chunks are embedded. Retired vectors stay available to in-flight queries and are excluded by the published snapshot; explicit document deletion removes all generations.
- Batch attempts and errors survive restarts. Interrupted `processing` batches are returned to `queued` during startup.

Rebuild every document after changing the embedding provider, model, or dimensions:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/reindex \
  -H "Content-Type: application/json" \
  -d '{"embedding_provider":"openai_compatible","embedding_model":"new-model","embedding_dimensions":1536}'
```

Reindexing allocates new physical chunk IDs and preserves the old published model and vectors. The model configuration and all document snapshots switch together after the entire rebuild succeeds. Failed batches remain observable and independently retryable. See [atomic index publication](atomic-index-publication.md) for migration, failure, history, and storage limits.

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

All filters are optional. Page bounds use overlap semantics, so a chunk is included when any of its pages falls inside the requested range. `section_path_prefix` matches the beginning of the complete heading path. Each request pins the published model, document metadata and allowed chunk IDs in one read transaction. Vector and BM25 routes share that snapshot; partial replacement generations remain unpublished.

Every hit has a stable response shape with rank, cosine score, chunk ID, source document/task, original content, content hash, kind, page range, section path, and a ready-to-render `citation` object. The response also records end-to-end search latency.

Evaluate a version-controlled question set with expected document/page evidence:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/retrieval-evaluations \
  -H "Content-Type: application/json" \
  --data @examples/retrieval_eval.sample.json
```

The evaluator reports per-case Recall@K, reciprocal rank, first relevant rank, matched sources, and latency, plus aggregate mean Recall@K, MRR, mean latency, p95 latency, embedding time, and total runtime. An expected source with no `pages` accepts any hit from its document; when pages are supplied, at least one cited page must overlap.

### Advanced retrieval

Table chunks carry normalized headers, rows, and cell coordinates. Their embedding text repeats each row as `header=value`, while the original Markdown remains available. Combine semantic search with row-level constraints:

```json
{
  "query": "What is the X100 price?",
  "kinds": ["table"],
  "table_filters": {"Model": "X100", "Unit": "USD"}
}
```

表格字符串过滤采用等值匹配。数值区间、显式单位／币种、重名列身份和命中行证据投影见 [精确表格查询](precise-table-query.md)；需要子串匹配须使用 `contains`。

Set `rewrite_query: true` to remove common conversational prefixes, split bounded compound questions, batch their embeddings, retrieve up to five routes concurrently, deduplicate, and rank them with reciprocal-rank fusion. Search responses expose `query_variants`, `matched_queries`, semantic score, fusion score, and route count. Retrieval evaluation accepts `compare_rewrite: true` and reports baseline Recall@K/MRR/latency plus deltas, so query rewriting must demonstrate measurable value rather than being enabled by assumption.

Install the `rag-langchain` extra, configure `PDF_INSPECTOR_RERANK_PROVIDER=flashrank`, and send `"rerank": true` to apply a local second-stage reranker. The default remains disabled. RRF first returns up to `RERANK_CANDIDATES`; FlashRank scores child chunks in a bounded disposable subprocess and returns at most `RERANK_TOP_N`; only then does RAG restore parent context. Its deadline includes process startup, model loading and inference, so the 500 ms default may fall back on a cold start. Timeouts terminate ordinary worker descendants and release capacity; explicit injected rerankers retain the trusted thread path. Results retain `original_rank`, semantic/fusion scores, `rerank_score`, and an applied/fallback trace. Capacity, initialization, inference and timeout failures preserve the original RRF order and increment fallback metrics. Actual reranking quality has not been validated in this delivery.

Use `"compare_rerank": true` on retrieval evaluations to compare Recall@K, MRR, and latency against the same pipeline without reranking. A rollout should keep Recall@5 at or above baseline, improve MRR or nDCG on the versioned evaluation set, and keep p95 added latency within the configured budget.

The storage and retrieval implementation remains framework-independent. When another LangChain component needs this knowledge source, expose it as a standard Runnable without copying vectors or changing citations:

```python
runnable = app.state.knowledge.as_langchain_runnable(
    knowledge_base_id,
    top_k=5,
    min_score=0.2,
    document_ids=[],
    page_start=None,
    page_end=None,
    kinds=[],
    section_path_prefix=[],
    rerank=True,
)
documents = runnable.invoke("What is the X100 purchase price?")
```

Every child chunk stores a deterministic parent section ID and its complete section context. Retrieval ranks the smaller child, while RAG uses the parent text and inherited page range. Multiple children from one parent are collapsed before context budgeting, preventing repeated sections from consuming the prompt.

Create traceable document versions by supplying version and validity metadata during ingestion:

```json
{
  "task_id": "TASK_ID",
  "document_key": "employee-policy",
  "version": "2026.2",
  "effective_from": "2026-06-01T00:00:00+00:00"
}
```

Submitting changed content with explicit version metadata archives the previous revision without deleting its chunks or vectors. Normal search returns only the current effective revision. Use `versions`, `as_of`, or `include_historical` to retrieve older evidence; every result and citation includes its version.

Each RAG answer returns an `answer_id` and is stored with its question, citations, retrieval trace, and refusal state. Record useful/incorrect citations and an optional correction:

```json
{
  "answer_id": "ANSWER_ID",
  "helpful": true,
  "valid_citation_ids": ["CHUNK_ID"],
  "invalid_citation_ids": [],
  "correction": "Optional corrected answer"
}
```

Feedback summaries report helpful rate, citation precision, and refusal rate and accept `created_from`/`created_to` windows for before/after comparisons. The evaluation-case export removes email addresses and phone numbers and converts validated citations into expected document/page evidence. Feed those cases into the retrieval evaluator to compare Recall@K and MRR across changes.

LangChain Core remains an optional boundary rather than the owner of retrieval. It standardizes interoperability through a Runnable, while indexing, filters, RRF, reranking fallback, citations, evaluation, permissions, and limits remain owned by this service. LangGraph and full agent orchestration are deliberately excluded from this lightweight stage.

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
$env:PDF_INSPECTOR_RAG_ANSWER_FORMAT='grounded_json'
```

Ask a grounded question:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge-bases/KB_ID/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How do I install the controller?","top_k":6}'
```

The response includes the answer, refusal flag, source citations, retrieval timing, context-token estimate, truncation status, provider/model, usage, and generation latency. Context selection follows search rank and stays within the configured character-estimate source budget; an oversized final chunk is truncated. When no result meets the evidence threshold, the service returns a fixed bilingual refusal without calling the LLM.

`context.selection` explains each candidate as `selected`, `duplicate_parent`,
`body_truncated`, `budget_omitted` or `empty_content`. `truncated` only covers body
cuts and budget omissions; deduplication alone is not truncation. Source token
estimates include block separators. `prompt_estimated_tokens` estimates system
and user message contents, and `estimated_total_with_output_reserve` includes the
generation reserve. These estimates exclude chat framing and model tokenization;
`model_window_verified` remains false. They are diagnostics, not a guarantee that
the full request fits a real model's context window.

The external model must return this JSON shape (the API returns a rendered answer,
not this raw model payload):

```json
{"answerable":true,"claims":[{"text":"A concise answer","evidence":[{"chunk_id":"SUPPLIED_CHUNK_ID","quote":"Exact text from the supplied source"}]}]}
```

When evidence does not answer the question, the model returns
`{"answerable":false,"claims":[]}`. Prompting and quote checks do not independently
prove that the question is answerable; real-model negative-case evaluation is required.
Use `text` only for models that cannot follow the JSON contract; those results
remain `needs_review`. JSON overhead and evidence quotes consume the output budget.
Malformed or token-limited output fails rather than triggering another billable call.

Set `"stream": true` to receive Server-Sent Events. Structured mode emits `metadata`,
buffers the model JSON, then emits a rendered `token` and `done` only after validation.
`metadata.buffered_until_validated` declares this behavior. On failure it emits
`error` without a final answer or saved successful answer. Extractive/text modes
retain incremental tokens. A provider stream needs `[DONE]` or `finish_reason: stop`;
premature EOF, provider errors, and length-limited finishes fail. Status, validation
and claims are persisted for both normal and streaming answers; legacy saved
non-refusal answers migrate to `needs_review`. Proxy buffering is disabled.

## Verified local Ollama configuration and limits

The fixed eight-item delivery now uses local Ollama 0.35.1: `qwen3-embedding:0.6b`
(1024 dimensions) and the `pdf-inspector-qwen3-instruct:4b` alias of
`qwen3:4b-instruct` (original template, context 8192, seed 42). Embedding,
grounded generation and streaming contract checks pass. See
[the reproducible setup and actual evaluation](single-machine-reliability.md).

New extraction retains heading text such as symbol definitions in searchable,
quotable bodies. Existing stored task results/chunks are unchanged; re-extract
and ingest old documents to get the new bodies. Vector reindexing alone cannot
change old extracted text. Grounded context shares its budget across retrieved
parents instead of letting a long first table consume all remaining evidence.
The local measured setup uses a context budget of 1200 tokens estimated from
characters and an output reserve of 1200 tokens; the estimate remains model-unverified.

OpenAI-compatible usage retains only non-negative integer `prompt_tokens`,
`completion_tokens` and `total_tokens`. Nested cache/reasoning details are not
added again. The final 30-question run has no call errors and six correct
negative-case refusals, but still has an answerable Chinese date refusal,
missing currencies in English prices and incomplete price evidence quotes.
Exact-quote validation does not establish semantic completeness. AI review is
separate from user acceptance; quality and publication remain pending.

## API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/metrics` | Prometheus metrics (admin) |
| `GET` | `/v1/audit-events` | Mutating and denied request audit trail (admin) |
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
| `POST` | `/v1/knowledge-bases/{id}/feedback` | Record answer and citation feedback |
| `GET` | `/v1/knowledge-bases/{id}/feedback` | List feedback |
| `GET` | `/v1/knowledge-bases/{id}/feedback/summary` | Compare answer-quality metrics by time window |
| `GET` | `/v1/knowledge-bases/{id}/feedback/evaluation-cases` | Export redacted retrieval evaluation cases |
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
