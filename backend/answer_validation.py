"""Deterministic refusal and inline citation identity checks.

These checks do not certify that a cited passage entails an answer.
"""

from __future__ import annotations

import re

from .llm import LlmError

REFUSAL = "知识库中没有足够信息 / Not enough information in the knowledge base."
_CITATION = re.compile(r"\[([^\[\]\n]+?)\s+pp?\.\s*(\d+)(?:\s*[-–]\s*(\d+))?\]")


def validate_answer(text: str, citations: list[dict], *, extractive: bool) -> dict:
    stripped = text.strip()
    if not stripped:
        raise LlmError("LLM returned an empty final answer")
    refusal = stripped.rstrip(".。 ").casefold() in {
        REFUSAL.rstrip(".。 ").casefold(),
        "知识库中没有足够信息",
        "not enough information in the knowledge base",
    }
    if refusal:
        return {"refused": True, "status": "refused", "citation_identity": "not_applicable", "inline_citations": []}
    if extractive:
        return {
            "refused": False, "status": "needs_review", "answer_mode": "evidence_preview",
            "semantic_support": "not_checked", "citation_identity": "not_applicable",
            "inline_citations": [],
        }
    references = []
    for match in _CITATION.finditer(text):
        filename, first, last = match.groups()
        start, end = int(first), int(last or first)
        if end < start or end - start > 1000:
            raise LlmError("LLM returned an invalid citation page range")
        pages = set(range(start, end + 1))
        if not any(citation["filename"] == filename and pages <= set(citation["pages"]) for citation in citations):
            raise LlmError("LLM cited a source or page outside this answer's evidence")
        references.append({"filename": filename, "pages": sorted(pages)})
    return {
        "refused": False,
        "status": "needs_review",
        "answer_mode": "unstructured_text",
        "semantic_support": "not_checked",
        "citation_identity": "valid" if references else "not_present",
        "inline_citations": references,
    }
