"""Grounded RAG orchestration over the built-in knowledge search API."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape, unescape
from time import perf_counter
from typing import Any, Callable, Iterable
from uuid import uuid4

from .config import Settings
from .answer_validation import REFUSAL, validate_answer
from .grounded_answer import SYSTEM_PROMPT, validate_grounded_answer
from .knowledge_service import KnowledgeService
from .llm import LlmProvider, create_llm_provider, estimate_tokens, truncate_to_tokens

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
    sources: list[dict[str, Any]] = field(default_factory=list)


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
        retrieval_mode: str = "vector",
        rrf_k: int | None = None,
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
        if (max_context_tokens is not None and max_context_tokens <= 0) or (max_output_tokens is not None and max_output_tokens <= 0):
            raise ValueError("token budgets must be positive")
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
            retrieval_mode=retrieval_mode,
            rrf_k=rrf_k,
            include_historical=include_historical,
            versions=versions or [],
            as_of=as_of,
        )
        selected = []
        sources = []
        blocks = []
        used_tokens = 0
        body_truncated = 0
        deduplicated = 0
        budget_omitted = 0
        empty_content = 0
        seen_parents = set()
        selection = []
        budget_exhausted = False
        for item in search["items"]:
            parent_id = item.get("parent_id") or item["chunk_id"]
            decision = {"chunk_id": item["chunk_id"], "parent_id": parent_id}
            selection.append(decision)
            if parent_id in seen_parents:
                deduplicated += 1
                decision["reason"] = "duplicate_parent"
                continue
            seen_parents.add(parent_id)
            if budget_exhausted:
                budget_omitted += 1
                decision["reason"] = "budget_omitted"
                continue
            header = (
                f'<source chunk_id="{escape(item["chunk_id"], quote=True)}" '
                f'file="{escape(item["filename"], quote=True)}" pages="{item.get("context_pages", item["pages"])}" '
                f'section="{escape(str(item["section_path"]), quote=True)}">\n'
            )
            footer = "\n</source>"
            wrapper_tokens = estimate_tokens(header + footer)
            remaining = context_budget - used_tokens - wrapper_tokens - (1 if blocks else 0)
            if remaining <= 0:
                budget_exhausted = True
                budget_omitted += 1
                decision["reason"] = "budget_omitted"
                continue
            context_content = item.get("context_content", item["content"])
            context_content = escape(context_content, quote=False)
            if not context_content.strip():
                empty_content += 1
                decision["reason"] = "empty_content"
                continue
            content = truncate_to_tokens(context_content, remaining)
            if not content:
                budget_exhausted = True
                budget_omitted += 1
                decision["reason"] = "budget_omitted"
                continue
            if content != context_content:
                body_truncated += 1
                budget_exhausted = True
                decision["reason"] = "body_truncated"
            else:
                decision["reason"] = "selected"
            block = header + content + footer
            blocks.append(block)
            used_tokens = estimate_tokens("\n\n".join(blocks))
            selected.append(dict(item))
            selected[-1]["parent_id"] = parent_id
            citation = {**item["citation"], "chunk_id": item["chunk_id"]}
            selected[-1]["citation"] = citation
            sources.append({
                "chunk_id": item["chunk_id"],
                "text": unescape(content),
                "citation": citation,
            })

        refused = not selected
        system = (
            "Answer only from the supplied knowledge-base sources. "
            "Never invent facts. Cite claims using [filename p.X] or [filename pp.X-Y]. "
            f"If the sources do not answer the question, reply exactly: {REFUSAL} "
            "Use the same primary language as the question."
        )
        if self._structured():
            system = SYSTEM_PROMPT
        user = f"Question:\n{question}\n\nSources:\n" + "\n\n".join(blocks)
        prompt_tokens = estimate_tokens(system) + estimate_tokens(user)
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
                "retrieval_mode": search.get("retrieval_mode", "vector"),
                "rrf_k": search.get("rrf_k"),
                "rerank": search.get("rerank", {"requested": False, "applied": False}),
            },
            context={
                "estimated_tokens": used_tokens,
                "max_tokens": context_budget,
                "truncated": body_truncated > 0 or budget_omitted > 0,
                "deduplicated": deduplicated,
                "omitted": budget_omitted + empty_content,
                "body_truncated": body_truncated,
                "budget_omitted": budget_omitted,
                "empty_content": empty_content,
                "selection": selection,
                "truncation_reasons": (["body_truncated"] if body_truncated else []) + (["budget_omitted"] if budget_omitted else []),
                "counting_method": "character_estimate",
                "prompt_estimated_tokens": prompt_tokens,
                "estimated_total_with_output_reserve": prompt_tokens + output_budget,
                "prompt_counting_scope": "message_content_only_no_chat_framing",
                "model_window_verified": False,
            },
            max_output_tokens=output_budget,
            refused=refused,
            sources=sources,
        )

    def _structured(self) -> bool:
        return (
            self.settings.llm_provider != "extractive"
            and self.settings.rag_answer_format == "grounded_json"
        )

    def _validate(self, prepared: PreparedAnswer, text: str) -> dict[str, Any]:
        if self._structured() and not prepared.refused:
            return validate_grounded_answer(text, prepared.sources)
        validation = validate_answer(
            text, prepared.citations,
            extractive=self.settings.llm_provider == "extractive",
        )
        return {
            "answer": text,
            "validation": validation,
            "claims": [],
            "citations": [] if validation["refused"] else (
                prepared.citations[:1]
                if self.settings.llm_provider == "extractive"
                else prepared.citations
            ),
        }

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
        checked = self._validate(prepared, text)
        validation = checked["validation"]
        return {
            "answer_id": prepared.answer_id,
            "knowledge_base_id": prepared.knowledge_base_id,
            "question": prepared.question,
            "answer": checked["answer"],
            "claims": checked["claims"],
            "refused": validation["refused"],
            "status": validation["status"],
            "validation": validation,
            "llm_provider": self.settings.llm_provider,
            "llm_model": self.settings.llm_model,
            "citations": checked["citations"],
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
                "buffered_until_validated": self._structured(),
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
            if not self._structured():
                yield {"event": "token", "data": {"text": token}}
        text = "".join(answer_parts)
        checked = self._validate(prepared, text)
        validation = checked["validation"]
        if self._structured():
            yield {"event": "token", "data": {"text": checked["answer"]}}
        yield {
            "event": "done",
            "data": {
                "answer_id": prepared.answer_id,
                "answer": checked["answer"],
                "claims": checked["claims"],
                "refused": validation["refused"],
                "status": validation["status"],
                "validation": validation,
                "citations": checked["citations"],
                "generation_latency_ms": round((perf_counter() - started) * 1000, 3),
            },
        }
