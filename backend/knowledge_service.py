"""Knowledge-base orchestration, embedding batches, retries, and reindexing."""

from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Callable

from .config import Settings
from .embeddings import EmbeddingProvider, create_embedding_provider
from .knowledge_store import (
    InvalidKnowledgeStateError,
    KnowledgeDocumentNotFoundError,
    KnowledgeStore,
)
from .service import ResultNotReadyError, TaskService
from .task_store import RESULT_STATUSES
from .vector_store import VectorRecord, VectorStore

EmbeddingFactory = Callable[[str, str, int], EmbeddingProvider]


class KnowledgeService:
    def __init__(
        self,
        settings: Settings,
        task_service: TaskService,
        store: KnowledgeStore,
        vector_store: VectorStore,
        *,
        embedding_factory: EmbeddingFactory | None = None,
        start_workers: bool = True,
    ):
        self.settings = settings
        self.task_service = task_service
        self.store = store
        self.vector_store = vector_store
        self.embedding_factory = embedding_factory or self._default_embedding_factory
        self.start_workers = start_workers
        self.executor = ThreadPoolExecutor(
            max_workers=settings.worker_count, thread_name_prefix="knowledge-index"
        )
        self._future_lock = Lock()
        self._futures = set()
        if start_workers:
            self._drain_vector_deletions()
            for batch_id in self.store.recover_incomplete():
                self._submit(batch_id)

    def _default_embedding_factory(
        self, provider: str, model: str, dimensions: int
    ) -> EmbeddingProvider:
        return create_embedding_provider(
            provider=provider,
            model=model,
            dimensions=dimensions,
            base_url=self.settings.embedding_base_url,
            api_key=self.settings.embedding_api_key,
            timeout_seconds=self.settings.embedding_timeout_seconds,
        )

    def validate_embedding_configuration(
        self, provider: str, model: str, dimensions: int
    ) -> None:
        if provider not in {"hash", "openai_compatible"}:
            raise ValueError(
                "embedding_provider must be one of: hash, openai_compatible"
            )
        if not model:
            raise ValueError("embedding_model must not be empty")
        if not 8 <= dimensions <= 4096:
            raise ValueError("embedding_dimensions must be between 8 and 4096")
        created = self.embedding_factory(provider, model, dimensions)
        if created.dimensions != dimensions:
            raise ValueError("embedding provider dimensions do not match configuration")

    def create_knowledge_base(
        self,
        *,
        name: str,
        description: str,
        embedding_provider: str | None,
        embedding_model: str | None,
        embedding_dimensions: int | None,
    ) -> dict:
        if (
            embedding_provider is not None
            and embedding_provider != self.settings.embedding_provider
            and (embedding_model is None or embedding_dimensions is None)
        ):
            raise ValueError(
                "embedding_model and embedding_dimensions are required when "
                "selecting a non-default provider"
            )
        provider = embedding_provider or self.settings.embedding_provider
        model = embedding_model or self.settings.embedding_model
        dimensions = embedding_dimensions or self.settings.embedding_dimensions
        self.validate_embedding_configuration(provider, model, dimensions)
        return self.store.create_knowledge_base(
            name=name,
            description=description,
            embedding_provider=provider,
            embedding_model=model,
            embedding_dimensions=dimensions,
        )

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _chunk_set_hash(chunks: list[dict]) -> str:
        digest = hashlib.sha256()
        identities = []
        for chunk in chunks:
            content_hash = (
                chunk.get("content_hash")
                or hashlib.sha256(
                    str(chunk.get("text") or chunk.get("markdown") or "").encode(
                        "utf-8"
                    )
                ).hexdigest()
            )
            identity = {
                "content_hash": content_hash,
                "kind": chunk.get("kind", "text"),
                "pages": chunk.get("pages", []),
                "section_path": chunk.get("section_path", []),
            }
            identities.append(
                json.dumps(
                    identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            )
        for identity in sorted(identities):
            digest.update(identity.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def ingest_task(
        self, knowledge_base_id: str, task_id: str, document_key: str | None
    ) -> dict:
        self.store.get_knowledge_base(knowledge_base_id)
        task = self.task_service.tasks.get(task_id)
        if task["status"] not in RESULT_STATUSES:
            raise ResultNotReadyError(task["status"])
        result = self.task_service.get_result(task_id)
        chunks = list(result.get("chunks", []))
        filename = task["filename"]
        key = (document_key or filename).strip()
        if not key:
            raise ValueError("document_key must not be empty")
        document, batch_ids, removed_vector_ids, idempotent = (
            self.store.prepare_document(
                knowledge_base_id=knowledge_base_id,
                task_id=task_id,
                document_key=key,
                filename=filename,
                content_hash=self._file_hash(Path(task["pdf_path"])),
                chunk_set_hash=self._chunk_set_hash(chunks),
                chunks=chunks,
                batch_size=self.settings.embedding_batch_size,
            )
        )
        if removed_vector_ids or self.store.pending_vector_deletions(1):
            self._drain_vector_deletions()
        if idempotent and document["status"] == "queued":
            batch_ids = [
                batch["id"]
                for batch in self.store.list_batches(document["id"])
                if batch["status"] == "queued"
            ]
        if self.start_workers:
            for batch_id in batch_ids:
                self._submit(batch_id)
        return {**document, "idempotent": idempotent}

    def _drain_vector_deletions(self) -> None:
        while True:
            chunk_ids = self.store.pending_vector_deletions()
            if not chunk_ids:
                return
            self.vector_store.delete_chunks(chunk_ids)
            self.store.complete_vector_deletions(chunk_ids)

    def get_document(self, knowledge_base_id: str, document_id: str) -> dict:
        document = self.store.get_document(document_id)
        if document["knowledge_base_id"] != knowledge_base_id:
            raise KnowledgeDocumentNotFoundError(document_id)
        return document

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        document = self.get_document(knowledge_base_id, document_id)
        if document["status"] in {"queued", "indexing"}:
            raise InvalidKnowledgeStateError(
                "cannot delete a document while indexing is active"
            )
        self.vector_store.delete_document(document_id)
        self.store.delete_document(document_id)

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        self.store.get_knowledge_base(knowledge_base_id)
        if self.store.has_active_documents(knowledge_base_id):
            raise InvalidKnowledgeStateError(
                "cannot delete a knowledge base while indexing is active"
            )
        self.vector_store.delete_knowledge_base(knowledge_base_id)
        self.store.delete_knowledge_base(knowledge_base_id)

    def retry_document(self, knowledge_base_id: str, document_id: str) -> dict:
        self.get_document(knowledge_base_id, document_id)
        batch_ids = self.store.retry_failed_batches(document_id)
        if self.start_workers:
            for batch_id in batch_ids:
                self._submit(batch_id)
        return self.store.get_document(document_id)

    def reindex_knowledge_base(
        self,
        knowledge_base_id: str,
        *,
        embedding_provider: str | None,
        embedding_model: str | None,
        embedding_dimensions: int | None,
    ) -> dict:
        knowledge_base = self.store.get_knowledge_base(knowledge_base_id)
        if (
            embedding_provider is not None
            and embedding_provider != knowledge_base["embedding_provider"]
            and (embedding_model is None or embedding_dimensions is None)
        ):
            raise ValueError(
                "embedding_model and embedding_dimensions are required when "
                "changing the provider"
            )
        provider = embedding_provider or knowledge_base["embedding_provider"]
        model = embedding_model or knowledge_base["embedding_model"]
        dimensions = embedding_dimensions or knowledge_base["embedding_dimensions"]
        self.validate_embedding_configuration(provider, model, dimensions)
        documents = self.store.list_documents(knowledge_base_id, 100000, 0)
        if any(document["status"] in {"queued", "indexing"} for document in documents):
            raise InvalidKnowledgeStateError(
                "cannot reindex while document indexing is active"
            )
        batch_map = self.store.reindex_knowledge_base(
            knowledge_base_id,
            embedding_provider=provider,
            embedding_model=model,
            embedding_dimensions=dimensions,
            batch_size=self.settings.embedding_batch_size,
        )
        if self.start_workers:
            for batch_ids in batch_map.values():
                for batch_id in batch_ids:
                    self._submit(batch_id)
        return {
            "knowledge_base": self.store.get_knowledge_base(knowledge_base_id),
            "documents_queued": len(batch_map),
            "batches_queued": sum(len(items) for items in batch_map.values()),
        }

    def run_pending(self, document_id: str | None = None) -> None:
        """Synchronously drain queued batches for operations and tests."""
        if document_id is None:
            batch_ids = self.store.recover_incomplete()
        else:
            batch_ids = [
                batch["id"]
                for batch in self.store.list_batches(document_id)
                if batch["status"] == "queued"
            ]
        for batch_id in batch_ids:
            self._run_batch(batch_id)

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _submit(self, batch_id: str) -> None:
        future = self.executor.submit(self._run_batch, batch_id)
        with self._future_lock:
            self._futures.add(future)

        def discard(completed):
            with self._future_lock:
                self._futures.discard(completed)

        future.add_done_callback(discard)

    def _run_batch(self, batch_id: str) -> None:
        if not self.store.begin_batch(batch_id):
            return
        try:
            document, chunks = self.store.get_batch_payload(batch_id)
            provider = self.embedding_factory(
                document["embedding_provider"],
                document["embedding_model"],
                int(document["embedding_dimensions"]),
            )
            vectors = provider.embed([chunk["text"] for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("embedding provider returned an unexpected batch size")
            records = []
            for chunk, vector in zip(chunks, vectors):
                try:
                    normalized_vector = [float(value) for value in vector]
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "embedding provider returned a non-numeric vector"
                    ) from exc
                if len(normalized_vector) != document["embedding_dimensions"]:
                    raise ValueError(
                        "embedding provider returned an unexpected vector dimension"
                    )
                if any(not math.isfinite(value) for value in normalized_vector):
                    raise ValueError(
                        "embedding provider returned a non-finite vector value"
                    )
                records.append(
                    VectorRecord(
                        chunk_id=chunk["id"],
                        knowledge_base_id=document["knowledge_base_id"],
                        document_id=document["id"],
                        embedding=normalized_vector,
                        content_hash=chunk["content_hash"],
                        text=chunk["text"],
                        page_start=chunk["page_start"],
                        page_end=chunk["page_end"],
                        section_path=chunk["section_path"],
                        kind=chunk["kind"],
                        embedding_provider=document["embedding_provider"],
                        embedding_model=document["embedding_model"],
                        metadata={
                            "pages": chunk["pages"],
                        },
                    )
                )
            self.vector_store.upsert(records)
            self.store.complete_batch(batch_id)
        except Exception as exc:  # noqa: BLE001 - batch boundary persists failures
            self.store.fail_batch(batch_id, type(exc).__name__, str(exc))
