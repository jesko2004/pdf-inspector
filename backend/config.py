"""Runtime configuration for the PDF task service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    builtin_profile_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    worker_count: int = 2
    ocr_provider: str = "none"
    ocr_command: tuple[str, ...] | None = None
    ocr_timeout_seconds: int = 180
    ocr_dpi: int = 200
    ocr_min_confidence: float = 0.5
    vector_store: str = "sqlite"
    pgvector_dsn: str | None = field(default=None, repr=False)
    embedding_provider: str = "hash"
    embedding_model: str = "hash-v1"
    embedding_dimensions: int = 256
    embedding_batch_size: int = 32
    embedding_base_url: str | None = None
    embedding_api_key: str | None = field(default=None, repr=False)
    embedding_timeout_seconds: float = 60
    llm_provider: str = "extractive"
    llm_model: str = "extractive-v1"
    llm_base_url: str | None = None
    llm_api_key: str | None = field(default=None, repr=False)
    llm_timeout_seconds: float = 120
    rag_max_context_tokens: int = 4000
    rag_max_output_tokens: int = 800
    rag_min_evidence_score: float = 0.2
    api_keys: tuple[tuple[str, str, str], ...] = field(
        default_factory=tuple, repr=False
    )
    search_rate_limit_per_minute: int = 120
    ask_rate_limit_per_minute: int = 30
    max_active_tasks: int = 100
    query_aliases: tuple[tuple[str, str], ...] = ()
    rerank_provider: str = "none"
    rerank_model: str = "ms-marco-MultiBERT-L-12"
    rerank_candidates: int = 12
    rerank_top_n: int = 5
    rerank_max_length: int = 256
    rerank_timeout_ms: int = 500

    @classmethod
    def from_env(cls) -> Settings:
        project_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(
            os.environ.get(
                "PDF_INSPECTOR_DATA_DIR", project_dir / ".pdf-inspector-data"
            )
        )
        profile_dir = Path(
            os.environ.get(
                "PDF_INSPECTOR_BUILTIN_PROFILE_DIR",
                project_dir / "backend" / "profiles",
            )
        )
        max_upload_mb = int(os.environ.get("PDF_INSPECTOR_MAX_UPLOAD_MB", "50"))
        workers = int(os.environ.get("PDF_INSPECTOR_WORKERS", "2"))
        ocr_provider_raw = os.environ.get("PDF_INSPECTOR_OCR_PROVIDER")
        ocr_timeout = int(os.environ.get("PDF_INSPECTOR_OCR_TIMEOUT_SECONDS", "180"))
        ocr_dpi = int(os.environ.get("PDF_INSPECTOR_OCR_DPI", "200"))
        ocr_min_confidence = float(
            os.environ.get("PDF_INSPECTOR_OCR_MIN_CONFIDENCE", "0.5")
        )
        ocr_command_raw = os.environ.get("PDF_INSPECTOR_OCR_COMMAND_JSON")
        vector_store = os.environ.get("PDF_INSPECTOR_VECTOR_STORE", "sqlite").lower()
        pgvector_dsn = os.environ.get("PDF_INSPECTOR_PGVECTOR_DSN")
        embedding_provider = os.environ.get(
            "PDF_INSPECTOR_EMBEDDING_PROVIDER", "hash"
        ).lower()
        embedding_model = os.environ.get("PDF_INSPECTOR_EMBEDDING_MODEL", "hash-v1")
        embedding_dimensions = int(
            os.environ.get("PDF_INSPECTOR_EMBEDDING_DIMENSIONS", "256")
        )
        embedding_batch_size = int(
            os.environ.get("PDF_INSPECTOR_EMBEDDING_BATCH_SIZE", "32")
        )
        embedding_base_url = os.environ.get("PDF_INSPECTOR_EMBEDDING_BASE_URL")
        embedding_api_key = os.environ.get("PDF_INSPECTOR_EMBEDDING_API_KEY")
        embedding_timeout = float(
            os.environ.get("PDF_INSPECTOR_EMBEDDING_TIMEOUT_SECONDS", "60")
        )
        llm_provider = os.environ.get(
            "PDF_INSPECTOR_LLM_PROVIDER", "extractive"
        ).lower()
        llm_model = os.environ.get("PDF_INSPECTOR_LLM_MODEL", "extractive-v1")
        llm_base_url = os.environ.get("PDF_INSPECTOR_LLM_BASE_URL")
        llm_api_key = os.environ.get("PDF_INSPECTOR_LLM_API_KEY")
        llm_timeout = float(os.environ.get("PDF_INSPECTOR_LLM_TIMEOUT_SECONDS", "120"))
        rag_max_context_tokens = int(
            os.environ.get("PDF_INSPECTOR_RAG_MAX_CONTEXT_TOKENS", "4000")
        )
        rag_max_output_tokens = int(
            os.environ.get("PDF_INSPECTOR_RAG_MAX_OUTPUT_TOKENS", "800")
        )
        rag_min_evidence_score = float(
            os.environ.get("PDF_INSPECTOR_RAG_MIN_EVIDENCE_SCORE", "0.2")
        )
        api_keys_raw = os.environ.get("PDF_INSPECTOR_API_KEYS_JSON", "[]")
        search_rate_limit = int(
            os.environ.get("PDF_INSPECTOR_SEARCH_RATE_LIMIT_PER_MINUTE", "120")
        )
        ask_rate_limit = int(
            os.environ.get("PDF_INSPECTOR_ASK_RATE_LIMIT_PER_MINUTE", "30")
        )
        max_active_tasks = int(os.environ.get("PDF_INSPECTOR_MAX_ACTIVE_TASKS", "100"))
        query_aliases_raw = os.environ.get("PDF_INSPECTOR_QUERY_ALIASES_JSON", "{}")
        rerank_provider = (
            os.environ.get("PDF_INSPECTOR_RERANK_PROVIDER", "none").strip().lower()
        )
        rerank_model = os.environ.get(
            "PDF_INSPECTOR_RERANK_MODEL", "ms-marco-MultiBERT-L-12"
        ).strip()
        rerank_candidates = int(os.environ.get("PDF_INSPECTOR_RERANK_CANDIDATES", "12"))
        rerank_top_n = int(os.environ.get("PDF_INSPECTOR_RERANK_TOP_N", "5"))
        rerank_max_length = int(
            os.environ.get("PDF_INSPECTOR_RERANK_MAX_LENGTH", "256")
        )
        rerank_timeout_ms = int(
            os.environ.get("PDF_INSPECTOR_RERANK_TIMEOUT_MS", "500")
        )
        ocr_command = None
        if ocr_command_raw:
            parsed = json.loads(ocr_command_raw)
            if (
                not isinstance(parsed, list)
                or not parsed
                or not all(
                    isinstance(argument, str) and argument for argument in parsed
                )
            ):
                raise ValueError(
                    "PDF_INSPECTOR_OCR_COMMAND_JSON must be a non-empty JSON string array"
                )
            ocr_command = tuple(parsed)
        ocr_provider = (
            ocr_provider_raw.strip().lower()
            if ocr_provider_raw
            else ("command" if ocr_command is not None else "none")
        )
        if max_upload_mb < 1:
            raise ValueError("PDF_INSPECTOR_MAX_UPLOAD_MB must be positive")
        if workers < 1:
            raise ValueError("PDF_INSPECTOR_WORKERS must be positive")
        if ocr_timeout < 1:
            raise ValueError("PDF_INSPECTOR_OCR_TIMEOUT_SECONDS must be positive")
        if ocr_provider not in {"none", "rapidocr", "command"}:
            raise ValueError(
                "PDF_INSPECTOR_OCR_PROVIDER must be one of: none, rapidocr, command"
            )
        if not 72 <= ocr_dpi <= 600:
            raise ValueError("PDF_INSPECTOR_OCR_DPI must be between 72 and 600")
        if not 0 <= ocr_min_confidence <= 1:
            raise ValueError("PDF_INSPECTOR_OCR_MIN_CONFIDENCE must be between 0 and 1")
        if vector_store not in {"sqlite", "pgvector"}:
            raise ValueError(
                "PDF_INSPECTOR_VECTOR_STORE must be one of: sqlite, pgvector"
            )
        if vector_store == "pgvector" and not pgvector_dsn:
            raise ValueError(
                "PDF_INSPECTOR_PGVECTOR_DSN is required when vector store is pgvector"
            )
        if embedding_provider not in {"hash", "openai_compatible"}:
            raise ValueError(
                "PDF_INSPECTOR_EMBEDDING_PROVIDER must be one of: hash, openai_compatible"
            )
        if not embedding_model.strip():
            raise ValueError("PDF_INSPECTOR_EMBEDDING_MODEL must not be empty")
        if not 8 <= embedding_dimensions <= 4096:
            raise ValueError(
                "PDF_INSPECTOR_EMBEDDING_DIMENSIONS must be between 8 and 4096"
            )
        if not 1 <= embedding_batch_size <= 256:
            raise ValueError(
                "PDF_INSPECTOR_EMBEDDING_BATCH_SIZE must be between 1 and 256"
            )
        if embedding_timeout <= 0:
            raise ValueError("PDF_INSPECTOR_EMBEDDING_TIMEOUT_SECONDS must be positive")
        if llm_provider not in {"extractive", "openai_compatible"}:
            raise ValueError(
                "PDF_INSPECTOR_LLM_PROVIDER must be one of: extractive, openai_compatible"
            )
        if not llm_model.strip():
            raise ValueError("PDF_INSPECTOR_LLM_MODEL must not be empty")
        if llm_provider == "openai_compatible" and not llm_base_url:
            raise ValueError(
                "PDF_INSPECTOR_LLM_BASE_URL is required for openai_compatible"
            )
        if llm_timeout <= 0:
            raise ValueError("PDF_INSPECTOR_LLM_TIMEOUT_SECONDS must be positive")
        if not 128 <= rag_max_context_tokens <= 128000:
            raise ValueError(
                "PDF_INSPECTOR_RAG_MAX_CONTEXT_TOKENS must be between 128 and 128000"
            )
        if not 1 <= rag_max_output_tokens <= 16000:
            raise ValueError(
                "PDF_INSPECTOR_RAG_MAX_OUTPUT_TOKENS must be between 1 and 16000"
            )
        if not -1 <= rag_min_evidence_score <= 1:
            raise ValueError(
                "PDF_INSPECTOR_RAG_MIN_EVIDENCE_SCORE must be between -1 and 1"
            )
        try:
            parsed_api_keys = json.loads(api_keys_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("PDF_INSPECTOR_API_KEYS_JSON must be valid JSON") from exc
        if not isinstance(parsed_api_keys, list):
            raise ValueError(  # noqa: TRY004 - environment configuration is invalid
                "PDF_INSPECTOR_API_KEYS_JSON must be a JSON array"
            )
        api_keys = []
        for item in parsed_api_keys:
            if not isinstance(item, dict):
                raise ValueError(  # noqa: TRY004 - environment configuration is invalid
                    "each API key entry must be an object"
                )
            key_id = item.get("id")
            secret = item.get("key")
            role = item.get("role")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (key_id, secret, role)
            ):
                raise ValueError("each API key requires non-empty id, key, and role")
            if role not in {"read", "write", "admin"}:
                raise ValueError("API key role must be one of: read, write, admin")
            api_keys.append((key_id.strip(), secret, role))
        if len({item[0] for item in api_keys}) != len(api_keys):
            raise ValueError("API key IDs must be unique")
        if len({item[1] for item in api_keys}) != len(api_keys):
            raise ValueError("API key secrets must be unique")
        if search_rate_limit < 1:
            raise ValueError(
                "PDF_INSPECTOR_SEARCH_RATE_LIMIT_PER_MINUTE must be positive"
            )
        if ask_rate_limit < 1:
            raise ValueError("PDF_INSPECTOR_ASK_RATE_LIMIT_PER_MINUTE must be positive")
        if max_active_tasks < 1:
            raise ValueError("PDF_INSPECTOR_MAX_ACTIVE_TASKS must be positive")
        try:
            parsed_query_aliases = json.loads(query_aliases_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "PDF_INSPECTOR_QUERY_ALIASES_JSON must be valid JSON"
            ) from exc
        if not isinstance(parsed_query_aliases, dict):
            raise ValueError(  # noqa: TRY004 - environment configuration is invalid
                "PDF_INSPECTOR_QUERY_ALIASES_JSON must be a JSON object"
            )
        query_aliases = []
        for alias, expansion in parsed_query_aliases.items():
            if not all(
                isinstance(value, str) and value.strip() for value in (alias, expansion)
            ):
                raise ValueError(
                    "query aliases and expansions must be non-empty strings"
                )
            query_aliases.append((alias.strip(), expansion.strip()))
        if rerank_provider not in {"none", "flashrank"}:
            raise ValueError(
                "PDF_INSPECTOR_RERANK_PROVIDER must be one of: none, flashrank"
            )
        if not rerank_model:
            raise ValueError("PDF_INSPECTOR_RERANK_MODEL must not be empty")
        if not 2 <= rerank_candidates <= 100:
            raise ValueError(
                "PDF_INSPECTOR_RERANK_CANDIDATES must be between 2 and 100"
            )
        if not 1 <= rerank_top_n <= rerank_candidates:
            raise ValueError(
                "PDF_INSPECTOR_RERANK_TOP_N must be between 1 and RERANK_CANDIDATES"
            )
        if not 32 <= rerank_max_length <= 512:
            raise ValueError(
                "PDF_INSPECTOR_RERANK_MAX_LENGTH must be between 32 and 512"
            )
        if not 10 <= rerank_timeout_ms <= 30000:
            raise ValueError(
                "PDF_INSPECTOR_RERANK_TIMEOUT_MS must be between 10 and 30000"
            )
        return cls(
            data_dir=data_dir,
            builtin_profile_dir=profile_dir,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            worker_count=workers,
            ocr_provider=ocr_provider,
            ocr_command=ocr_command,
            ocr_timeout_seconds=ocr_timeout,
            ocr_dpi=ocr_dpi,
            ocr_min_confidence=ocr_min_confidence,
            vector_store=vector_store,
            pgvector_dsn=pgvector_dsn,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            embedding_batch_size=embedding_batch_size,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_timeout_seconds=embedding_timeout,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_timeout_seconds=llm_timeout,
            rag_max_context_tokens=rag_max_context_tokens,
            rag_max_output_tokens=rag_max_output_tokens,
            rag_min_evidence_score=rag_min_evidence_score,
            api_keys=tuple(api_keys),
            search_rate_limit_per_minute=search_rate_limit,
            ask_rate_limit_per_minute=ask_rate_limit,
            max_active_tasks=max_active_tasks,
            query_aliases=tuple(query_aliases),
            rerank_provider=rerank_provider,
            rerank_model=rerank_model,
            rerank_candidates=rerank_candidates,
            rerank_top_n=rerank_top_n,
            rerank_max_length=rerank_max_length,
            rerank_timeout_ms=rerank_timeout_ms,
        )

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def result_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def custom_profile_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tasks.sqlite3"

    @property
    def knowledge_database_path(self) -> Path:
        return self.data_dir / "knowledge.sqlite3"

    @property
    def audit_database_path(self) -> Path:
        return self.data_dir / "audit.sqlite3"

    @property
    def rerank_cache_dir(self) -> Path:
        return self.data_dir / "models" / "flashrank"

    def create_directories(self) -> None:
        for path in (
            self.data_dir,
            self.upload_dir,
            self.result_dir,
            self.custom_profile_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
