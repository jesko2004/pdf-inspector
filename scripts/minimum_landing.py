"""PDF -> KB -> evaluation with explicit resume and no automatic model retry."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from backend.config import Settings
from backend.embeddings import EmbeddingError
from backend.execution_lock import SingleExecutorLock
from backend.evaluation import fingerprint, load_json, validate_dataset
from backend.knowledge_service import KnowledgeService
from backend.knowledge_store import KnowledgeStore
from backend.llm import LlmError
from backend.model_readiness import configuration_issues, safe_error
from backend.rag_service import RagService
from backend.service import TaskService
from backend.vector_store import create_vector_store

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_fingerprint(dataset: dict, settings: Settings) -> str:
    fields = [
        "embedding_provider", "embedding_model", "embedding_dimensions", "embedding_batch_size",
        "embedding_base_url", "llm_provider", "llm_model", "llm_base_url", "rag_answer_format",
        "rag_max_context_tokens", "rag_max_output_tokens", "rag_min_evidence_score",
        "bm25_k1", "bm25_b", "query_aliases",
    ]
    code = list((ROOT / "backend").glob("*.py")) + list((ROOT / "src").rglob("*.rs"))
    code += [Path(__file__), ROOT / "backend/profiles/manual_query.json"]
    payload = {
        "dataset": dataset,
        "inputs": {source["key"]: hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() for source in dataset["documents"]},
        "settings": {name: getattr(settings, name) for name in fields},
        "code": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(code)},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarize(report: dict) -> None:
    rows = report["answers"]
    successes = [row for row in rows if "answer" in row]
    report["answer_statuses"] = {status: sum(row["answer"]["status"] == status for row in successes) for status in ["completed", "needs_review", "refused"]}
    report["answer_statuses"]["error"] = len(rows) - len(successes)
    report["unanswerable_completed"] = sum(not row["expected_answerable"] and row["answer"]["status"] == "completed" for row in successes)
    negatives = [row for row in rows if not row["expected_answerable"]]
    report["negative_cases"] = {
        "total": len(negatives),
        "correct_refusals": sum("answer" in row and row["answer"]["refused"] for row in negatives),
        "not_refused": sum("answer" in row and not row["answer"]["refused"] for row in negatives),
        "errors": sum("error" in row for row in negatives),
    }
    report["refusal_mismatches"] = sum(not row["refusal_matches"] for row in successes)
    usage = {}
    for row in successes:
        for name, value in row["answer"].get("usage", {}).items():
            if isinstance(value, int):
                usage[name] = usage.get(name, 0) + value
    report["reported_generation_usage"] = usage
    report["usage_scope"] = "Reported successful generation usage only; embedding, failed calls and preflight excluded. Not a billing total."


def run(dataset: dict, settings: Settings, output: Path, *, resume: bool = False, retry_failed: bool = False) -> dict:
    if retry_failed and not resume:
        raise ValueError("retry_failed requires resume")
    dataset = validate_dataset(dataset)
    for source in dataset["documents"]:
        if not (ROOT / source["path"]).resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("document path escapes the repository")
    signature = run_fingerprint(dataset, settings)
    state_path = settings.data_dir / "evaluation-state.json"
    if state_path.exists():
        if not resume:
            raise ValueError("evaluation workspace exists; use --resume or a new directory")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["fingerprint"] != signature:
            raise ValueError("dataset, input files, model configuration or pipeline changed; use a new directory")
    else:
        if resume:
            raise ValueError("no evaluation checkpoint exists in this directory")
        if settings.database_path.exists() or settings.knowledge_database_path.exists():
            raise ValueError("choose a fresh isolated evaluation work directory")
        state = {"fingerprint": signature, "knowledge_base_id": None, "documents": {}, "retrieval": {}, "answers": {}}
        write_json(state_path, state)

    tasks = TaskService(settings, start_workers=False)
    knowledge = KnowledgeService(settings, tasks, KnowledgeStore(settings.knowledge_database_path), create_vector_store(settings), start_workers=False)
    if resume:
        tasks.tasks.recover_incomplete()
        knowledge.store.recover_incomplete()
    rag = RagService(settings, knowledge)
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(), "scenario": dataset["scenario"],
        "fingerprint": signature, "annotation_status": dataset["annotation_status"], "python": platform.python_version(),
        "dataset_sha256": fingerprint(dataset), "dataset_version": dataset["version"],
        "embedding": {"provider": settings.embedding_provider, "model": settings.embedding_model, "dimensions": settings.embedding_dimensions},
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model, "answer_format": "evidence_preview" if settings.llm_provider == "extractive" else settings.rag_answer_format},
        "real_model_validation": settings.embedding_provider != "hash" and settings.llm_provider != "extractive",
        "inputs": [], "retrieval_reports": [], "answers": [], "status": "running",
        "limitations": ["Small fixture corpus, assistant draft labels pending human review", "Tuning/check split shares documents; not an independent corpus holdout", "Keyword presence is diagnostic, not semantic answer grading", "No user feedback or production SLA inferred", "Model identity and quote checks do not independently certify semantic quality"],
    }

    def save():
        write_json(state_path, state)
        summarize(report)
        write_json(output, report)

    try:
        if state["knowledge_base_id"]:
            kb = knowledge.store.get_knowledge_base(state["knowledge_base_id"])
        else:
            kb = knowledge.create_knowledge_base(name="Minimum landing benchmark", description=dataset["scenario"], embedding_provider=None, embedding_model=None, embedding_dimensions=None)
            state["knowledge_base_id"] = kb["id"]
            save()
        documents = {}
        for source in dataset["documents"]:
            key = source["key"]
            entry = state["documents"].setdefault(key, {})
            path = ROOT / source["path"]
            if "task_id" not in entry:
                task = tasks.create_task(path.name, BytesIO(path.read_bytes()), "manual_query")
                entry["task_id"] = task["id"]
                save()
            task = tasks.get_task(entry["task_id"])
            if retry_failed and task["status"] == "failed":
                task = tasks.retry(task["id"])
            if task["status"] in {"queued", "processing"}:
                tasks.run_pending(task["id"])
                task = tasks.get_task(task["id"])
            if task["status"] not in {"ready", "needs_review"}:
                raise RuntimeError("PDF processing failed; inspect the isolated task state")
            if "document_id" not in entry:
                document = knowledge.ingest_task(kb["id"], task["id"], key, version="fixture-v1")
                entry["document_id"] = document["id"]
                save()
            document = knowledge.store.get_document(entry["document_id"])
            if retry_failed and document["status"] in {"failed", "partial"}:
                knowledge.retry_document(kb["id"], document["id"])
            knowledge.run_pending(document["id"])
            document = knowledge.store.get_document(document["id"])
            if document["status"] != "ready":
                raise EmbeddingError("document indexing incomplete")
            documents[key] = document["id"]
            result = tasks.get_result(task["id"])
            report["inputs"].append({"key": key, "document_id": document["id"], "filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "task_status": task["status"], "chunk_count": len(result["chunks"])})
            save()
        defaults = dict(top_k=5, min_score=0.2, document_ids=[], page_start=None, page_end=None, kinds=[], section_path_prefix=[])
        for mode in ["vector", "bm25", "hybrid"]:
            for constant in ([10, 30, 60, 100] if mode == "hybrid" else [60]):
                key = f"{mode}:{constant}"
                cached = state["retrieval"].get(key)
                if cached is None or (retry_failed and "error" in cached):
                    try:
                        cases = [{"id": case["id"], "query": case["query"], "expected_sources": [{"document_id": documents[case["document"]], "pages": case["pages"], "required_text": case["required_text"]}]} for case in dataset["cases"] if case["answerable"]]
                        cached = knowledge.evaluate_retrieval(kb["id"], cases, **defaults, retrieval_mode=mode, rrf_k=constant)
                        cached["tuning_ids"] = [case["id"] for case in dataset["cases"] if case["split"] == "tuning" and case["answerable"]]
                        for split in ["tuning", "check"]:
                            ids = {case["id"] for case in dataset["cases"] if case["split"] == split}
                            rows = [row for row in cached["results"] if row["id"] in ids]
                            cached[split] = {"cases": len(rows), "recall_at_k": sum(row["recall_at_k"] for row in rows) / len(rows) if rows else None, "mrr": sum(row["reciprocal_rank"] for row in rows) / len(rows) if rows else None}
                    except (EmbeddingError, LlmError, ValueError) as exc:
                        cached = {"retrieval_mode": mode, "rrf_k": constant, "error": safe_error(exc, settings)}
                    state["retrieval"][key] = cached
                report["retrieval_reports"].append(cached)
                save()
        for case in dataset["cases"]:
            cached = state["answers"].get(case["id"])
            if cached is None or (retry_failed and "error" in cached):
                started = perf_counter()
                try:
                    prepared = rag.prepare(kb["id"], case["query"], **{**defaults, "document_ids": [documents[case["document"]]]}, retrieval_mode="hybrid", rrf_k=60)
                    answer = rag.answer(prepared)
                    cached = {"id": case["id"], "expected_answerable": case["answerable"], "answer": answer, "expected_fragments_present": all(fragment.casefold() in answer["answer"].casefold() for fragment in case["expected_answer_fragments"]), "refusal_matches": answer["refused"] == (not case["answerable"])}
                except (EmbeddingError, LlmError, ValueError) as exc:
                    cached = {"id": case["id"], "expected_answerable": case["answerable"], "error": safe_error(exc, settings)}
                cached["total_latency_ms"] = round((perf_counter() - started) * 1000, 3)
                state["answers"][case["id"]] = cached
            cached.update({name: case[name] for name in ("split", "category", "language", "document")})
            report["answers"].append(cached)
            save()
        report["status"] = "incomplete" if any("error" in row for row in report["answers"] + report["retrieval_reports"]) else "completed"
        save()
        return report
    except Exception as exc:
        report["status"] = "incomplete"
        report["pipeline_error"] = safe_error(exc, settings)
        save()
        raise
    finally:
        knowledge.close()
        tasks.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "examples/minimum_landing_eval.json")
    parser.add_argument("--output", type=Path, default=ROOT / "test_output/minimum-landing/report.json")
    parser.add_argument("--work-dir", type=Path, help="isolated persistent directory")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--require-real-models", action="store_true")
    args = parser.parse_args()
    configured = Settings.from_env()
    if args.require_real_models and configuration_issues(configured):
        parser.error("; ".join(configuration_issues(configured)))
    if (args.resume or args.retry_failed) and not args.work_dir:
        parser.error("resume/retry-failed requires --work-dir")
    dataset = load_json(args.dataset)

    def execute(directory):
        settings = replace(configured, data_dir=Path(directory), vector_store="sqlite", ocr_provider="none")
        lock = SingleExecutorLock(settings.data_dir / "executor.lock")
        try:
            return run(dataset, settings, args.output, resume=args.resume, retry_failed=args.retry_failed)
        finally:
            lock.close()

    if args.work_dir:
        report = execute(args.work_dir)
    else:
        with TemporaryDirectory(prefix="pdf-minimum-landing-") as temporary:
            report = execute(temporary)
    print(json.dumps({"report": str(args.output), "status": report["status"], "real_model_validation": report["real_model_validation"], "documents": len(report["inputs"]), "questions": len(report["answers"]), "answer_statuses": report["answer_statuses"], "negative_cases": report["negative_cases"], "refusal_mismatches": report["refusal_mismatches"]}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
