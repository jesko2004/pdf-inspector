"""Grounded RAG orchestration over the built-in knowledge search API."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Iterable
from uuid import uuid4

from .config import Settings
from .knowledge_service import KnowledgeService
from .llm import LlmProvider, create_llm_provider, estimate_tokens, truncate_to_tokens

REFUSAL = "知识库中没有足够信息 / Not enough information in the knowledge base."
LlmFactory = Callable[[str, str], LlmProvider]


@dataclass(frozen=True)
class PreparedAnswer:
    answer_id: str
    knowledge_base_id: str
    question: str
    messages: list[dict[str, str]]
    citations: list[dict[str, Any]]
    retrieval: dict[str, Any]
    context: dict[str, Any]
    max_output_tokens: int
    refused: bool


class RagService:
    def __init__(
        self,
        settings: Settings,
        knowledge: KnowledgeService,
        *,
        llm_factory: LlmFactory | None = None,
    ):
        self.settings = settings
        self.knowledge = knowledge
        self.llm_factory = llm_factory or self._default_llm_factory

    def _default_llm_factory(self, provider: str, model: str) -> LlmProvider:
        return create_llm_provider(
            provider=provider,
            model=model,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
        )

    def _provider(self) -> LlmProvider:
        return self.llm_factory(self.settings.llm_provider, self.settings.llm_model)

    def prepare(
        self,
        knowledge_base_id: str,
        question: str,
        *,
        top_k: int,
        min_score: float | None,
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
        max_context_tokens: int | None = None,
        max_output_tokens: int | None = None,
    ) -> PreparedAnswer:
        context_budget = min(
            max_context_tokens or self.settings.rag_max_context_tokens,
            self.settings.rag_max_context_tokens,
        )
        output_budget = min(
            max_output_tokens or self.settings.rag_max_output_tokens,
            self.settings.rag_max_output_tokens,
        )
        effective_min_score = (
            self.settings.rag_min_evidence_score if min_score is None else min_score
        )
        search = self.knowledge.search(
            knowledge_base_id,
            question,
            top_k=top_k,
            min_score=effective_min_score,
            document_ids=document_ids,
            page_start=page_start,
            page_end=page_end,
            kinds=kinds,
            section_path_prefix=section_path_prefix,
            table_filters=table_filters or {},
            rewrite_query=rewrite_query,
            max_query_variants=max_query_variants,
            rerank=rerank,
            include_historical=include_historical,
            versions=versions or [],
            as_of=as_of,
        )
        selected = []
        blocks = []
        used_tokens = 0
        truncated = False
        for item in search["items"]:
            parent_id = item.get("parent_id") or item["chunk_id"]
            if any(
                selected_item.get("parent_id") == parent_id
                for selected_item in selected
            ):
                continue
            header = (
                f'<source chunk_id="{item["chunk_id"]}" '
                f'file="{item["filename"]}" pages="{item.get("context_pages", item["pages"])}" '
                f'section="{item["section_path"]}">\n'
            )
            footer = "\n</source>"
            wrapper_tokens = estimate_tokens(header + footer)
            remaining = context_budget - used_tokens - wrapper_tokens
            if remaining <= 0:
                truncated = True
                break
            context_content = item.get("context_content", item["content"])
            content = truncate_to_tokens(context_content, remaining)
            if not content:
                truncated = True
                break
            if content != context_content:
                truncated = True
            block = header + content + footer
            block_tokens = estimate_tokens(block)
            blocks.append(block)
            used_tokens += block_tokens
            selected.append(item)
            selected[-1]["parent_id"] = parent_id
            if truncated:
                break

        refused = not selected
        system = (
            "Answer only from the supplied knowledge-base sources. "
            "Never invent facts. Cite claims using [filename p.X] or [filename pp.X-Y]. "
            f"If the sources do not answer the question, reply exactly: {REFUSAL} "
            "Use the same primary language as the question."
        )
        user = f"Question:\n{question}\n\nSources:\n" + "\n\n".join(blocks)
        citations = [item["citation"] for item in selected]
        return PreparedAnswer(
            answer_id=str(uuid4()),
            knowledge_base_id=knowledge_base_id,
            question=question,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            citations=citations,
            retrieval={
                "returned": search["returned"],
                "used": len(selected),
                "latency_ms": search["latency_ms"],
                "min_score": effective_min_score,
                "query_variants": search.get("query_variants", [question]),
                "route_count": search.get("route_count", 1),
                "rerank": search.get("rerank", {"requested": False, "applied": False}),
            },
            context={
                "estimated_tokens": used_tokens,
                "max_tokens": context_budget,
                "truncated": truncated or len(selected) < search["returned"],
            },
            max_output_tokens=output_budget,
            refused=refused,
        )

    def answer(self, prepared: PreparedAnswer) -> dict[str, Any]:
        started = perf_counter()
        if prepared.refused:
            text = REFUSAL
            usage: dict[str, int] = {}
        else:
            result = self._provider().generate(
                prepared.messages, max_tokens=prepared.max_output_tokens
            )
            text = result.text
            usage = result.usage
        return {
            "answer_id": prepared.answer_id,
            "knowledge_base_id": prepared.knowledge_base_id,
            "question": prepared.question,
            "answer": text,
            "refused": prepared.refused,
            "llm_provider": self.settings.llm_provider,
            "llm_model": self.settings.llm_model,
            "citations": prepared.citations,
            "retrieval": prepared.retrieval,
            "context": prepared.context,
            "usage": usage,
            "generation_latency_ms": round((perf_counter() - started) * 1000, 3),
        }

    def stream(self, prepared: PreparedAnswer) -> Iterable[dict[str, Any]]:
        started = perf_counter()
        yield {
            "event": "metadata",
            "data": {
                "knowledge_base_id": prepared.knowledge_base_id,
                "answer_id": prepared.answer_id,
                "question": prepared.question,
                "refused": prepared.refused,
                "llm_provider": self.settings.llm_provider,
                "llm_model": self.settings.llm_model,
                "citations": prepared.citations,
                "retrieval": prepared.retrieval,
                "context": prepared.context,
            },
        }
        tokens = (
            [REFUSAL]
            if prepared.refused
            else self._provider().stream(
                prepared.messages, max_tokens=prepared.max_output_tokens
            )
        )
        answer_parts = []
        for token in tokens:
            answer_parts.append(token)
            yield {"event": "token", "data": {"text": token}}
        yield {
            "event": "done",
            "data": {
                "answer_id": prepared.answer_id,
                "answer": "".join(answer_parts),
                "generation_latency_ms": round((perf_counter() - started) * 1000, 3),
            },
        }
