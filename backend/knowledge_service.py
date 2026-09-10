"""Knowledge-base orchestration, embedding batches, retries, and reindexing."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Callable

from .advanced_retrieval import RuleBasedQueryRewriter, reciprocal_rank_fusion
from .config import Settings
from .embeddings import EmbeddingProvider, create_embedding_provider
from .knowledge_store import (
    InvalidKnowledgeStateError,
    KnowledgeDocumentNotFoundError,
    KnowledgeStore,
)
from .reranking import RerankerProvider, create_reranker
from .service import ResultNotReadyError, TaskService
from .task_store import RESULT_STATUSES
from .vector_store import VectorRecord, VectorSearchHit, VectorSearchQuery, VectorStore

EmbeddingFactory = Callable[[str, str, int], EmbeddingProvider]
RerankerFactory = Callable[[Settings], RerankerProvider | None]
LOGGER = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(
        self,
        settings: Settings,
        task_service: TaskService,
        store: KnowledgeStore,
        vector_store: VectorStore,
        *,
        embedding_factory: EmbeddingFactory | None = None,
        reranker_factory: RerankerFactory | None = None,
        start_workers: bool = True,
        metrics=None,
    ):
        self.settings = settings
        self.task_service = task_service
        self.store = store
        self.vector_store = vector_store
        self.embedding_factory = embedding_factory or self._default_embedding_factory
        self.start_workers = start_workers
        self.metrics = metrics
        self.query_rewriter = RuleBasedQueryRewriter(dict(settings.query_aliases))
        self.reranker: RerankerProvider | None = None
        self.reranker_initialization_error: str | None = None
        try:
            self.reranker = (reranker_factory or create_reranker)(settings)
        except Exception as exc:  # noqa: BLE001 - baseline retrieval must remain available
            self.reranker_initialization_error = type(exc).__name__
            LOGGER.warning(
                "reranker initialization failed; using baseline retrieval: %s",
                type(exc).__name__,
            )
        self.rerank_executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-rerank")
            if self.reranker is not None
            else None
        )
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

    def _embed(
        self, provider: EmbeddingProvider, texts: list[str]
    ) -> list[list[float]]:
        if self.metrics is None:
            return provider.embed(texts)
        with self.metrics.timer("embedding"):
            return provider.embed(texts)

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
        self,
        knowledge_base_id: str,
        task_id: str,
        document_key: str | None,
        *,
        version: str | None = None,
        effective_from: str | None = None,
        effective_to: str | None = None,
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
                version=version,
                effective_from=effective_from,
                effective_to=effective_to,
                preserve_history=bool(version or effective_from or effective_to),
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

    @staticmethod
    def _normalize_vector(vector: list[float], dimensions: int) -> list[float]:
        try:
            normalized = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "embedding provider returned a non-numeric vector"
            ) from exc
        if len(normalized) != dimensions:
            raise ValueError(
                "embedding provider returned an unexpected vector dimension"
            )
        if any(not math.isfinite(value) for value in normalized):
            raise ValueError("embedding provider returned a non-finite vector value")
        if not any(value != 0 for value in normalized):
            raise ValueError("embedding provider returned a zero vector")
        return normalized

    def _search_hits(
        self,
        knowledge_base: dict[str, Any],
        embedding: list[float],
        *,
        top_k: int,
        min_score: float,
        document_ids: list[str],
        page_start: int | None,
        page_end: int | None,
        kinds: list[str],
        section_path_prefix: list[str],
        table_filters: dict[str, str] | None = None,
    ) -> list[VectorSearchHit]:
        return self.vector_store.search(
            VectorSearchQuery(
                knowledge_base_id=knowledge_base["id"],
                embedding=embedding,
                embedding_provider=knowledge_base["embedding_provider"],
                embedding_model=knowledge_base["embedding_model"],
                top_k=top_k,
                min_score=min_score,
                document_ids=tuple(document_ids),
                page_start=page_start,
                page_end=page_end,
                kinds=tuple(kinds),
                section_path_prefix=tuple(section_path_prefix),
                table_filters=tuple(sorted((table_filters or {}).items())),
            )
        )

    def _format_hits(
        self,
        hits: list[VectorSearchHit],
        fusion: dict[str, tuple[float, list[str]]] | None = None,
    ) -> list[dict[str, Any]]:
        documents = {
            document_id: self.store.get_document(document_id)
            for document_id in {hit.document_id for hit in hits}
        }
        items = []
        for rank, hit in enumerate(hits, start=1):
            document = documents[hit.document_id]
            pages = hit.metadata.get("pages")
            if not isinstance(pages, list) or not pages:
                pages = list(range(hit.page_start, hit.page_end + 1))
            parent_pages = hit.metadata.get("parent_pages")
            context_pages = (
                parent_pages
                if isinstance(parent_pages, list) and parent_pages
                else pages
            )
            citation = {
                "chunk_id": hit.chunk_id,
                "document_id": document["id"],
                "document_key": document["document_key"],
                "filename": document["filename"],
                "version": document.get("version"),
                "pages": context_pages,
                "section_path": hit.section_path,
            }
            fusion_score, matched_queries = (fusion or {}).get(hit.chunk_id, (None, []))
            items.append(
                {
                    "rank": rank,
                    "original_rank": rank,
                    "score": round(hit.score, 8),
                    "chunk_id": hit.chunk_id,
                    "document_id": document["id"],
                    "document_key": document["document_key"],
                    "filename": document["filename"],
                    "task_id": document["task_id"],
                    "version": document.get("version"),
                    "effective_from": document.get("effective_from"),
                    "effective_to": document.get("effective_to"),
                    "is_current": document.get("is_current", True),
                    "content": hit.text,
                    "context_content": hit.metadata.get("parent_text", hit.text),
                    "parent_id": hit.metadata.get("parent_id"),
                    "context_pages": context_pages,
                    "table": hit.metadata.get("table"),
                    "content_hash": hit.content_hash,
                    "kind": hit.kind,
                    "page_start": hit.page_start,
                    "page_end": hit.page_end,
                    "pages": pages,
                    "section_path": hit.section_path,
                    "citation": citation,
                    "fusion_score": round(fusion_score, 8)
                    if fusion_score is not None
                    else None,
                    "matched_queries": matched_queries,
                    "rerank_score": None,
                    "reranked": False,
                }
            )
        return items

    def _rerank_items(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        requested: bool,
        top_k: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        final_limit = min(top_k, self.settings.rerank_top_n)
        metadata: dict[str, Any] = {
            "requested": requested,
            "applied": False,
            "provider": self.settings.rerank_provider,
            "model": self.settings.rerank_model,
            "candidate_count": len(items),
            "top_n": final_limit,
            "latency_ms": 0.0,
            "fallback_reason": None,
        }
        if not requested or not items:
            return items[:top_k], metadata
        if self.reranker is None or self.rerank_executor is None:
            metadata["fallback_reason"] = (
                "initialization_error"
                if self.reranker_initialization_error
                else "provider_disabled"
            )
            if self.metrics is not None:
                self.metrics.increment(
                    "pdf_inspector_rerank_fallbacks_total",
                    reason=metadata["fallback_reason"],
                )
            return items[:final_limit], metadata

        started = perf_counter()
        future = self.rerank_executor.submit(
            self.reranker.rerank,
            query,
            items,
            final_limit,
        )
        try:
            ranked = future.result(timeout=self.settings.rerank_timeout_ms / 1000)
            by_id = {item["chunk_id"]: item for item in items}
            reranked = []
            for rank, (chunk_id, score) in enumerate(ranked, start=1):
                item = dict(by_id[chunk_id])
                item.update(
                    {
                        "rank": rank,
                        "rerank_score": round(float(score), 8),
                        "reranked": True,
                    }
                )
                reranked.append(item)
            metadata["applied"] = True
            metadata["latency_ms"] = round((perf_counter() - started) * 1000, 3)
            if self.metrics is not None:
                self.metrics.observe("rerank", metadata["latency_ms"] / 1000)
            return reranked, metadata
        except FutureTimeoutError:
            future.cancel()
            fallback_reason = "timeout"
        except Exception as exc:  # noqa: BLE001 - reranking must fail open
            fallback_reason = "provider_error"
            LOGGER.warning(
                "reranking failed; using fused retrieval order: %s",
                type(exc).__name__,
            )
        metadata["latency_ms"] = round((perf_counter() - started) * 1000, 3)
        metadata["fallback_reason"] = fallback_reason
        if self.metrics is not None:
            self.metrics.observe("rerank", metadata["latency_ms"] / 1000, "error")
            self.metrics.increment(
                "pdf_inspector_rerank_fallbacks_total", reason=fallback_reason
            )
        return items[:final_limit], metadata

    def search(
        self,
        knowledge_base_id: str,
        query: str,
        *,
        top_k: int,
        min_score: float,
        document_ids: list[str],
        page_start: int | None,
        page_end: int | None,
        kinds: list[str],
        section_path_prefix: list[str],
        table_filters: dict[str, str] | None = None,
        rewrite_query: bool = False,
        max_query_variants: int = 3,
        rerank: bool = False,
        include_historical: bool = False,
        versions: list[str] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        knowledge_base = self.store.get_knowledge_base(knowledge_base_id)
        variants = (
            self.query_rewriter.rewrite(query, max_query_variants)
            if rewrite_query
            else [query]
        )
        candidate_limit = (
            max(top_k, self.settings.rerank_candidates) if rerank else top_k
        )
        eligible_document_ids = self.store.eligible_document_ids(
            knowledge_base_id,
            document_ids=document_ids,
            versions=versions or [],
            as_of=as_of,
            include_historical=include_historical,
        )
        if not eligible_document_ids:
            return {
                "knowledge_base_id": knowledge_base_id,
                "query": query,
                "query_variants": variants,
                "route_count": len(variants),
                "top_k": top_k,
                "min_score": min_score,
                "returned": 0,
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "embedding_provider": knowledge_base["embedding_provider"],
                "embedding_model": knowledge_base["embedding_model"],
                "rerank": self._rerank_items(query, [], requested=rerank, top_k=top_k)[
                    1
                ],
                "items": [],
            }
        provider = self.embedding_factory(
            knowledge_base["embedding_provider"],
            knowledge_base["embedding_model"],
            int(knowledge_base["embedding_dimensions"]),
        )
        vectors = self._embed(provider, variants)
        if len(vectors) != len(variants):
            raise ValueError("embedding provider returned an unexpected batch size")
        retrieval_started = perf_counter()
        route_inputs = []
        for variant, raw_vector in zip(variants, vectors):
            embedding = self._normalize_vector(
                raw_vector, int(knowledge_base["embedding_dimensions"])
            )
            route_inputs.append((variant, embedding))

        def retrieve(route):
            variant, embedding = route
            return (
                variant,
                self._search_hits(
                    knowledge_base,
                    embedding,
                    top_k=min(max(candidate_limit * 2, candidate_limit), 100),
                    min_score=min_score,
                    document_ids=eligible_document_ids,
                    page_start=page_start,
                    page_end=page_end,
                    kinds=kinds,
                    section_path_prefix=section_path_prefix,
                    table_filters=table_filters or {},
                ),
            )

        if len(route_inputs) == 1:
            routes = [retrieve(route_inputs[0])]
        else:
            with ThreadPoolExecutor(
                max_workers=len(route_inputs), thread_name_prefix="retrieval-route"
            ) as route_executor:
                routes = list(route_executor.map(retrieve, route_inputs))
        if self.metrics is not None:
            self.metrics.observe("retrieval", perf_counter() - retrieval_started)
        if len(routes) == 1:
            hits = routes[0][1][:candidate_limit]
            items = self._format_hits(hits)
        else:
            fused = reciprocal_rank_fusion(routes, limit=candidate_limit)
            hits = [hit for hit, _score, _queries in fused]
            fusion = {hit.chunk_id: (score, queries) for hit, score, queries in fused}
            items = self._format_hits(hits, fusion)
        items, rerank_metadata = self._rerank_items(
            query,
            items,
            requested=rerank,
            top_k=top_k,
        )
        return {
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "query_variants": variants,
            "route_count": len(routes),
            "top_k": top_k,
            "min_score": min_score,
            "returned": len(items),
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "embedding_provider": knowledge_base["embedding_provider"],
            "embedding_model": knowledge_base["embedding_model"],
            "rerank": rerank_metadata,
            "items": items,
        }

    @staticmethod
    def _hit_matches_expected(item: dict[str, Any], expected: dict[str, Any]) -> bool:
        if item["document_id"] != expected["document_id"]:
            return False
        expected_pages = set(expected.get("pages", []))
        return not expected_pages or bool(expected_pages.intersection(item["pages"]))

    def evaluate_retrieval(
        self,
        knowledge_base_id: str,
        cases: list[dict[str, Any]],
        *,
        top_k: int,
        min_score: float,
        document_ids: list[str],
        page_start: int | None,
        page_end: int | None,
        kinds: list[str],
        section_path_prefix: list[str],
        table_filters: dict[str, str] | None = None,
        rewrite_query: bool = False,
        max_query_variants: int = 3,
        compare_rewrite: bool = False,
        rerank: bool = False,
        compare_rerank: bool = False,
        include_historical: bool = False,
        versions: list[str] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if rewrite_query or compare_rewrite or rerank or compare_rerank:
            advanced_rewrite = rewrite_query or compare_rewrite
            advanced_rerank = rerank or compare_rerank
            advanced = self._evaluate_search_routes(
                knowledge_base_id,
                cases,
                top_k=top_k,
                min_score=min_score,
                document_ids=document_ids,
                page_start=page_start,
                page_end=page_end,
                kinds=kinds,
                section_path_prefix=section_path_prefix,
                table_filters=table_filters or {},
                rewrite_query=advanced_rewrite,
                max_query_variants=max_query_variants,
                rerank=advanced_rerank,
                include_historical=include_historical,
                versions=versions or [],
                as_of=as_of,
            )
            if compare_rewrite or compare_rerank:
                baseline = self.evaluate_retrieval(
                    knowledge_base_id,
                    cases,
                    top_k=top_k,
                    min_score=min_score,
                    document_ids=document_ids,
                    page_start=page_start,
                    page_end=page_end,
                    kinds=kinds,
                    section_path_prefix=section_path_prefix,
                    table_filters=table_filters,
                    rewrite_query=rewrite_query if not compare_rewrite else False,
                    max_query_variants=max_query_variants,
                    rerank=rerank if not compare_rerank else False,
                    include_historical=include_historical,
                    versions=versions,
                    as_of=as_of,
                )
                advanced["comparison"] = {
                    "features": {
                        "rewrite": compare_rewrite,
                        "rerank": compare_rerank,
                    },
                    "baseline": {
                        "mean_recall_at_k": baseline["mean_recall_at_k"],
                        "mrr": baseline["mrr"],
                        "mean_latency_ms": baseline["mean_latency_ms"],
                    },
                    "recall_delta": round(
                        advanced["mean_recall_at_k"] - baseline["mean_recall_at_k"],
                        6,
                    ),
                    "mrr_delta": round(advanced["mrr"] - baseline["mrr"], 6),
                    "latency_delta_ms": round(
                        advanced["mean_latency_ms"] - baseline["mean_latency_ms"],
                        3,
                    ),
                }
            return advanced
        started = perf_counter()
        knowledge_base = self.store.get_knowledge_base(knowledge_base_id)
        document_ids = self.store.eligible_document_ids(
            knowledge_base_id,
            document_ids=document_ids,
            versions=versions or [],
            as_of=as_of,
            include_historical=include_historical,
        )
        provider = self.embedding_factory(
            knowledge_base["embedding_provider"],
            knowledge_base["embedding_model"],
            int(knowledge_base["embedding_dimensions"]),
        )
        embedding_started = perf_counter()
        vectors = self._embed(provider, [case["query"] for case in cases])
        embedding_ms = (perf_counter() - embedding_started) * 1000
        if len(vectors) != len(cases):
            raise ValueError("embedding provider returned an unexpected batch size")

        results = []
        for case, raw_vector in zip(cases, vectors):
            case_started = perf_counter()
            embedding = self._normalize_vector(
                raw_vector, int(knowledge_base["embedding_dimensions"])
            )
            hits = self._search_hits(
                knowledge_base,
                embedding,
                top_k=top_k,
                min_score=min_score,
                document_ids=document_ids,
                page_start=page_start,
                page_end=page_end,
                kinds=kinds,
                section_path_prefix=section_path_prefix,
                table_filters=table_filters,
            )
            items = self._format_hits(hits)
            expected_sources = case["expected_sources"]
            matched_sources = sum(
                any(self._hit_matches_expected(item, expected) for item in items)
                for expected in expected_sources
            )
            first_rank = next(
                (
                    item["rank"]
                    for item in items
                    if any(
                        self._hit_matches_expected(item, expected)
                        for expected in expected_sources
                    )
                ),
                None,
            )
            case_latency = (perf_counter() - case_started) * 1000 + embedding_ms / len(
                cases
            )
            results.append(
                {
                    "id": case["id"],
                    "query": case["query"],
                    "recall_at_k": round(matched_sources / len(expected_sources), 6),
                    "reciprocal_rank": round(1 / first_rank, 6) if first_rank else 0.0,
                    "first_relevant_rank": first_rank,
                    "expected_source_count": len(expected_sources),
                    "matched_source_count": matched_sources,
                    "latency_ms": round(case_latency, 3),
                    "retrieved": [
                        {
                            "rank": item["rank"],
                            "score": item["score"],
                            "chunk_id": item["chunk_id"],
                            "document_id": item["document_id"],
                            "pages": item["pages"],
                        }
                        for item in items
                    ],
                }
            )

        latencies = sorted(result["latency_ms"] for result in results)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        return {
            "knowledge_base_id": knowledge_base_id,
            "case_count": len(results),
            "top_k": top_k,
            "mean_recall_at_k": round(
                sum(result["recall_at_k"] for result in results) / len(results), 6
            ),
            "mrr": round(
                sum(result["reciprocal_rank"] for result in results) / len(results),
                6,
            ),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 3),
            "p95_latency_ms": round(latencies[p95_index], 3),
            "embedding_latency_ms": round(embedding_ms, 3),
            "total_latency_ms": round((perf_counter() - started) * 1000, 3),
            "results": results,
        }

    def _evaluate_search_routes(
        self,
        knowledge_base_id: str,
        cases: list[dict[str, Any]],
        **search_options,
    ) -> dict[str, Any]:
        started = perf_counter()
        results = []
        for case in cases:
            search = self.search(
                knowledge_base_id,
                case["query"],
                **search_options,
            )
            items = search["items"]
            expected_sources = case["expected_sources"]
            matched_sources = sum(
                any(self._hit_matches_expected(item, expected) for item in items)
                for expected in expected_sources
            )
            first_rank = next(
                (
                    item["rank"]
                    for item in items
                    if any(
                        self._hit_matches_expected(item, expected)
                        for expected in expected_sources
                    )
                ),
                None,
            )
            results.append(
                {
                    "id": case["id"],
                    "query": case["query"],
                    "query_variants": search["query_variants"],
                    "rerank": search["rerank"],
                    "recall_at_k": round(matched_sources / len(expected_sources), 6),
                    "reciprocal_rank": round(1 / first_rank, 6) if first_rank else 0.0,
                    "first_relevant_rank": first_rank,
                    "expected_source_count": len(expected_sources),
                    "matched_source_count": matched_sources,
                    "latency_ms": search["latency_ms"],
                    "retrieved": [
                        {
                            "rank": item["rank"],
                            "score": item["score"],
                            "fusion_score": item["fusion_score"],
                            "rerank_score": item["rerank_score"],
                            "original_rank": item["original_rank"],
                            "chunk_id": item["chunk_id"],
                            "document_id": item["document_id"],
                            "pages": item["pages"],
                        }
                        for item in items
                    ],
                }
            )
        latencies = sorted(result["latency_ms"] for result in results)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        return {
            "knowledge_base_id": knowledge_base_id,
            "case_count": len(results),
            "top_k": search_options["top_k"],
            "rewrite_query": search_options["rewrite_query"],
            "rerank": search_options["rerank"],
            "rerank_applied_cases": sum(
                result["rerank"]["applied"] for result in results
            ),
            "mean_recall_at_k": round(
                sum(result["recall_at_k"] for result in results) / len(results), 6
            ),
            "mrr": round(
                sum(result["reciprocal_rank"] for result in results) / len(results), 6
            ),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 3),
            "p95_latency_ms": round(latencies[p95_index], 3),
            "total_latency_ms": round((perf_counter() - started) * 1000, 3),
            "results": results,
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
        if self.rerank_executor is not None:
            self.rerank_executor.shutdown(wait=True, cancel_futures=False)

    def as_langchain_runnable(self, knowledge_base_id: str, **search_options):
        """Return an optional LangChain Core Runnable without replacing storage."""
        from .langchain_adapter import build_search_runnable

        return build_search_runnable(self, knowledge_base_id, **search_options)

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
            vectors = self._embed(provider, [chunk["text"] for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("embedding provider returned an unexpected batch size")
            records = []
            for chunk, vector in zip(chunks, vectors):
                normalized_vector = self._normalize_vector(
                    vector, int(document["embedding_dimensions"])
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
                            **chunk.get("metadata", {}),
                            "pages": chunk["pages"],
                        },
                    )
                )
            self.vector_store.upsert(records)
            self.store.complete_batch(batch_id)
        except Exception as exc:  # noqa: BLE001 - batch boundary persists failures
            self.store.fail_batch(batch_id, type(exc).__name__, str(exc))
