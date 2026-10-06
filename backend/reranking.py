"""Optional local second-stage reranking with a fail-open provider boundary."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .process_isolation import ProcessRunner


class RerankerProvider(Protocol):
    name: str
    model: str

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_n: int
    ) -> list[tuple[str, float]]: ...


class FlashRankReranker:
    """CPU-only FlashRank adapter loaded inside each bounded worker."""

    name = "flashrank"

    def __init__(self, *, model: str, cache_dir: Path, max_length: int):
        try:
            from flashrank import Ranker, RerankRequest
        except ImportError as exc:
            raise RuntimeError(
                "FlashRank is unavailable; install the 'rag-langchain' extra and "
                "verify the ONNX Runtime installation"
            ) from exc
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self._request_type = RerankRequest
        self._ranker = Ranker(
            model_name=model,
            cache_dir=str(cache_dir),
            max_length=max_length,
        )

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_n: int
    ) -> list[tuple[str, float]]:
        passages = [
            {
                "id": item["chunk_id"],
                # Rerank the precise child chunk; parent context is restored later.
                "text": item["content"],
            }
            for item in candidates
        ]
        response = self._ranker.rerank(
            self._request_type(query=query, passages=passages)
        )
        ranked = []
        candidate_ids = {item["chunk_id"] for item in candidates}
        seen = set()
        for item in response:
            chunk_id = str(item.get("id", ""))
            try:
                score = float(item["score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("reranker returned an invalid score") from exc
            if (
                chunk_id not in candidate_ids
                or chunk_id in seen
                or not math.isfinite(score)
            ):
                raise ValueError("reranker returned an invalid candidate")
            seen.add(chunk_id)
            ranked.append((chunk_id, score))
            if len(ranked) >= top_n:
                break
        if len(ranked) != min(top_n, len(candidates)):
            raise ValueError("reranker returned too few candidates")
        return ranked


class IsolatedReranker:
    """Each optional local inference has a finite, killable process lifetime."""

    name = "flashrank"

    def __init__(self, settings: Settings, *, worker_command=None):
        self.model = settings.rerank_model
        self.settings = settings
        self.runner = ProcessRunner(workers=1, memory_mb=settings.process_memory_mb,
            max_result_bytes=settings.process_max_result_bytes,
            temporary_dir=settings.data_dir / "work", worker_command=worker_command)

    def rerank(self, query, candidates, top_n):
        ranked = self.runner.run({"operation": "rerank", "model": self.model,
            "cache_dir": str(self.settings.rerank_cache_dir.resolve()),
            "max_length": self.settings.rerank_max_length, "query": query,
            "candidates": [{"chunk_id": c["chunk_id"], "content": c["content"]} for c in candidates],
            "top_n": top_n}, timeout_seconds=self.settings.rerank_timeout_ms / 1000)
        if not isinstance(ranked, list) or len(ranked) != min(top_n, len(candidates)):
            raise ValueError("invalid isolated reranking result")
        allowed = {c["chunk_id"] for c in candidates}
        seen = set()
        result = []
        for chunk_id, raw_score in ranked:
            score = float(raw_score)
            if chunk_id not in allowed or chunk_id in seen or not math.isfinite(score):
                raise ValueError("invalid isolated reranking candidate")
            seen.add(chunk_id)
            result.append((chunk_id, score))
        return result

    def close(self):
        self.runner.close()


def create_reranker(settings: Settings) -> RerankerProvider | None:
    if settings.rerank_provider == "none":
        return None
    if settings.rerank_provider == "flashrank":
        return IsolatedReranker(settings)
    raise ValueError(f"unsupported rerank provider: {settings.rerank_provider}")
