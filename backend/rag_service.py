"""Grounded RAG orchestration over the built-in knowledge search API."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Iterable

from .config import Settings
from .knowledge_service import KnowledgeService
from .llm import LlmProvider, create_llm_provider, estimate_tokens, truncate_to_tokens

REFUSAL = "知识库中没有足够信息 / Not enough information in the knowledge base."
LlmFactory = Callable[[str, str], LlmProvider]


@dataclass(frozen=True)
class PreparedAnswer:
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
        max_context_tokens: int | None,
        max_output_tokens: int | None,
    ) -> PreparedAnswer:
        context_budget = max_context_tokens or self.settings.rag_max_context_tokens
        output_budget = max_output_tokens or self.settings.rag_max_output_tokens
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
        )
        selected = []
        blocks = []
        used_tokens = 0
        truncated = False
        for item in search["items"]:
            header = (
                f'<source chunk_id="{item["chunk_id"]}" '
                f'file="{item["filename"]}" pages="{item["pages"]}" '
                f'section="{item["section_path"]}">\n'
            )
            footer = "\n</source>"
            wrapper_tokens = estimate_tokens(header + footer)
            remaining = context_budget - used_tokens - wrapper_tokens
            if remaining <= 0:
                truncated = True
                break
            content = truncate_to_tokens(item["content"], remaining)
            if not content:
                truncated = True
                break
            if content != item["content"]:
                truncated = True
            block = header + content + footer
            block_tokens = estimate_tokens(block)
            blocks.append(block)
            used_tokens += block_tokens
            selected.append(item)
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
                "answer": "".join(answer_parts),
                "generation_latency_ms": round((perf_counter() - started) * 1000, 3),
            },
        }
