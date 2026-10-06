"""Small, explicit model-contract probes before a billable corpus evaluation."""

from __future__ import annotations

from time import perf_counter
from urllib.parse import urlsplit

from .config import Settings
from .embeddings import EmbeddingError, create_embedding_provider
from .grounded_answer import GroundedAnswer, SYSTEM_PROMPT, validate_grounded_answer
from .knowledge_service import KnowledgeService
from .llm import LlmError, create_llm_provider


def configuration_issues(settings: Settings) -> list[str]:
    issues = []
    for kind in ("embedding", "llm"):
        if getattr(settings, f"{kind}_provider") != "openai_compatible":
            issues.append(f"{kind}: configure openai_compatible for real-model validation")
        url = getattr(settings, f"{kind}_base_url") or ""
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            issues.append(f"{kind}: a valid base URL is required")
        model = getattr(settings, f"{kind}_model")
        if not model.strip() or model in {"hash-v1", "extractive-v1"}:
            issues.append(f"{kind}: configure the actual model identifier")
    if settings.rag_answer_format != "grounded_json":
        issues.append("use grounded_json for model-contract acceptance")
    return issues


def safe_error(exc: Exception, settings: Settings) -> str:
    # Endpoint bodies may echo credentials. Reports never retain provider detail.
    if isinstance(exc, (EmbeddingError, LlmError)):
        return f"{type(exc).__name__}: model request or contract validation failed"
    return type(exc).__name__


def check_models(settings: Settings, *, embedding=None, llm=None) -> dict:
    issues = configuration_issues(settings)
    if issues:
        return {"ready": False, "status": "configuration_required", "issues": issues, "checks": []}
    embedding = embedding or create_embedding_provider(
        provider=settings.embedding_provider, model=settings.embedding_model,
        dimensions=settings.embedding_dimensions, base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key, timeout_seconds=settings.embedding_timeout_seconds,
    )
    llm = llm or create_llm_provider(
        provider=settings.llm_provider, model=settings.llm_model,
        base_url=settings.llm_base_url, api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        response_schema=GroundedAnswer.model_json_schema(),
    )
    sources = [{"chunk_id": "probe-source", "text": "The controller supply voltage is 24 V.", "citation": {"chunk_id": "probe-source", "filename": "contract-probe.txt", "pages": [1]}}]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": 'Question: What is the supply voltage?\nSources:\n<source chunk_id="probe-source">\nThe controller supply voltage is 24 V.\n</source>'},
    ]
    checks = []
    for name in ("embedding_batch", "grounded_generation", "grounded_stream"):
        started = perf_counter()
        try:
            usage = {}
            if name == "embedding_batch":
                vectors = embedding.embed(["controller supply voltage", "控制器供电电压"])
                if len(vectors) != 2:
                    raise EmbeddingError("embedding batch count mismatch")
                for vector in vectors:
                    KnowledgeService._normalize_vector(vector, settings.embedding_dimensions)
            else:
                if name == "grounded_generation":
                    result = llm.generate(messages, max_tokens=settings.rag_max_output_tokens)
                    text, usage = result.text, result.usage
                else:
                    text = "".join(llm.stream(messages, max_tokens=settings.rag_max_output_tokens))
                checked = validate_grounded_answer(text, sources)
                if checked["validation"]["refused"] or not any("24 V" in evidence["quote"] for claim in checked["claims"] for evidence in claim["evidence"]):
                    raise LlmError("model did not answer the answerable contract probe")
            checks.append({"name": name, "passed": True, "usage": usage, "latency_ms": round((perf_counter() - started) * 1000, 3)})
        except (EmbeddingError, LlmError, ValueError, TypeError) as exc:
            checks.append({"name": name, "passed": False, "error": safe_error(exc, settings), "latency_ms": round((perf_counter() - started) * 1000, 3)})
    return {
        "ready": all(check["passed"] for check in checks),
        "status": "checked", "issues": [], "checks": checks,
        "models": {"embedding": settings.embedding_model, "llm": settings.llm_model, "dimensions": settings.embedding_dimensions},
        "scope": "Contract smoke check only; not retrieval quality, semantic entailment, or negative-case acceptance.",
    }
