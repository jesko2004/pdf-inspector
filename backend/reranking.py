"""Optional local second-stage reranking with a fail-open provider boundary."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

from .config import Settings


class RerankerProvider(Protocol):
    name: str
    model: str

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_n: int
    ) -> list[tuple[str, float]]: ...


class FlashRankReranker:
    """CPU-only FlashRank adapter loaded once during service startup."""

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


def create_reranker(settings: Settings) -> RerankerProvider | None:
    if settings.rerank_provider == "none":
        return None
    if settings.rerank_provider == "flashrank":
        return FlashRankReranker(
            model=settings.rerank_model,
            cache_dir=settings.rerank_cache_dir,
            max_length=settings.rerank_max_length,
        )
    raise ValueError(f"unsupported rerank provider: {settings.rerank_provider}")
