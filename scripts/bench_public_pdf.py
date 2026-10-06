"""Run all 200 public OpenDataLoader PDFs against two explicitly supplied CLIs.

This public benchmark is separate from the unavailable firecrawl/pdf-evals
repository. It does not waive or silently satisfy that named policy gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

CORPUS_COMMIT = "340f25d70f5b2dbc4bc1cc6b154769f74b1fc745"
BASELINE_COMMIT = "13cf480813f7a77a9adbe723c15ac246a023a9be"
IDS = {f"0103000000{n:04d}" for n in range(1, 201)}
SCORES = ("overall_mean", "nid_mean", "nid_s_mean", "teds_mean", "teds_s_mean", "mhs_mean", "mhs_s_mean")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k != "processing_time_ms"}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def gates(baseline: dict, candidate: dict, cases: list[dict]) -> list[str]:
    failures = []
    if {c["id"] for c in cases} != IDS or len(cases) != 200:
        failures.append("case coverage is not exactly the pinned 200-document corpus")
    for c in cases:
        if c.get("error"):
            failures.append(f"{c['id']}: execution failure")
        if not c.get("markdown_equal") or not c.get("normalized_json_equal"):
            failures.append(f"{c['id']}: snapshot changed")
    for label, evaluation in (("baseline", baseline), ("candidate", candidate)):
        docs = evaluation.get("documents", [])
        if len(docs) != 200 or {d["document_id"] for d in docs} != IDS:
            failures.append(f"{label}: evaluator did not cover all 200 documents")
        if evaluation.get("metrics", {}).get("missing_predictions") != 0:
            failures.append(f"{label}: missing predictions")
        if any(not d.get("prediction_available") for d in docs):
            failures.append(f"{label}: unavailable document prediction")
    a = baseline.get("metrics", {}).get("score", {})
    b = candidate.get("metrics", {}).get("score", {})
    for key in SCORES:
        x, y = a.get(key), b.get(key)
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not math.isfinite(x) or not math.isfinite(y):
            failures.append(f"{key}: finite score missing")
        elif y < x - 1e-12:
            failures.append(f"{key}: candidate regressed by {y - x:+.8f}")
    return failures


def run(args) -> int:
    corpus = args.corpus_root.resolve()
    output = args.output_dir.resolve()
    binaries = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    python = args.python.absolute()
    assert all(p.is_file() for p in (*binaries.values(), python))
    head = subprocess.check_output(["git", "-C", str(corpus), "rev-parse", "HEAD"], text=True).strip()
    if head != CORPUS_COMMIT:
        raise ValueError(f"corpus commit must be {CORPUS_COMMIT}, got {head}")
    tracked_changes = subprocess.check_output(["git", "-C", str(corpus), "status", "--porcelain", "--untracked-files=no"], text=True)
    if tracked_changes.strip():
        raise ValueError("public corpus/evaluator has modified tracked files")
    pdfs = sorted((corpus / "pdfs").glob("*.pdf"))
    truth = sorted((corpus / "ground-truth/markdown").glob("*.md"))
    if len(pdfs) != 200 or len(truth) != 200 or {p.stem for p in pdfs} != IDS or {p.stem for p in truth} != IDS:
        raise ValueError("missing, extra or mismatched corpus/ground-truth documents")
    if any(not p.read_bytes().startswith(b"%PDF-") for p in pdfs):
        raise ValueError("a corpus input is not a real PDF (possibly an LFS pointer)")
    inputs = pdfs + truth + sorted((corpus / "src").glob("*.py"))
    input_hashes = {p.relative_to(corpus).as_posix(): digest(p) for p in inputs}
    if output.exists():
        raise ValueError("output directory already exists; preserve prior results and use a new path")
    output.mkdir(parents=True)
    for label in binaries:
        for name in ("markdown", "raw-json", "stderr"):
            (output / label / name).mkdir(parents=True)
    started = datetime.now(timezone.utc).isoformat()
    cases = []
    env = {**os.environ, "RUST_LOG": "error"}
    elapsed = {label: 0.0 for label in binaries}
    for i, pdf in enumerate(pdfs, 1):
        c = {"id": pdf.stem, "pdf_sha256": digest(pdf), "outputs": {}}
        payloads = {}
        for label, binary in binaries.items():
            before = time.perf_counter()
            try:
                result = subprocess.run([str(binary), str(pdf), "--json"], capture_output=True, timeout=args.timeout, env=env)
                seconds = time.perf_counter() - before
                elapsed[label] += seconds
                (output / label / "raw-json" / f"{pdf.stem}.json").write_bytes(result.stdout)
                (output / label / "stderr" / f"{pdf.stem}.log").write_bytes(result.stderr)
                if result.returncode != 0:
                    raise RuntimeError(f"CLI exit {result.returncode}")
                data = json.loads(result.stdout.decode("utf8"))
                if not isinstance(data, dict) or "error" in data or "markdown" not in data:
                    raise ValueError("CLI JSON missing extraction result")
                md = data["markdown"] or ""
                if not isinstance(md, str):
                    raise ValueError("markdown must be a string or null")
                (output / label / "markdown" / f"{pdf.stem}.md").write_text(md, encoding="utf8")
                payloads[label] = data
                c["outputs"][label] = {"exit_code": result.returncode, "seconds": seconds,
                    "raw_sha256": sha256(result.stdout).hexdigest(), "markdown_sha256": sha256(md.encode()).hexdigest(),
                    "empty_markdown": not bool(md.strip()), "pdf_type": data.get("pdf_type"),
                    "pages_needing_ocr": data.get("pages_needing_ocr")}
            except Exception as exc:
                c["error"] = f"{label}: {type(exc).__name__}: {exc}"
        if len(payloads) == 2:
            c["markdown_equal"] = payloads["baseline"]["markdown"] == payloads["candidate"]["markdown"]
            c["normalized_json_equal"] = normalize(payloads["baseline"]) == normalize(payloads["candidate"])
        cases.append(c)
        save(output / "checkpoint.json", {"cases": cases, "finished": i, "total": 200})
        if i % 20 == 0 or c.get("error"):
            print(f"Processed {i}/200; failures={sum(bool(x.get('error')) for x in cases)}", flush=True)
    evaluations = {}
    for label in binaries:
        save(output / label / "summary.json", {"engine_name": label, "engine_version": "pdf-inspector-0.1.7",
             "document_count": 200, "total_elapsed": elapsed[label], "date": started,
             "binary_sha256": digest(binaries[label]), "ocr": "disabled; native CLI semantics retained"})
        command = [str(python), str(corpus / "src/evaluator.py"), "--prediction-root", str(output), "--engine", label, "--log-level", "WARNING"]
        with (output / f"evaluator-{label}.log").open("wb") as log:
            result = subprocess.run(command, cwd=corpus, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"official evaluator {label} failed; see preserved log")
        evaluations[label] = json.loads((output / label / "evaluation.json").read_text(encoding="utf8"))
    failures = gates(evaluations["baseline"], evaluations["candidate"], cases)
    if any(digest(corpus / p) != v for p, v in input_hashes.items()):
        failures.append("corpus/ground truth/evaluator changed during execution")
    report = {"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if failures else "passed", "corpus_repository": "https://github.com/firecrawl/opendataloader-bench",
        "corpus_commit": head, "corpus_path": str(corpus), "documents": 200, "baseline_commit": BASELINE_COMMIT,
        "baseline_dependency_lock": "same pinned Cargo.lock as candidate; baseline repository did not track a lockfile",
        "binaries": {label: {"path": str(p), "sha256": digest(p)} for label, p in binaries.items()},
        "input_fingerprints": input_hashes, "runner_sha256": digest(Path(__file__)), "python": str(python),
        "snapshots_changed": sum(not c.get("markdown_equal") or not c.get("normalized_json_equal") for c in cases),
        "execution_errors": sum(bool(c.get("error")) for c in cases),
        "empty_markdown_ids": {label: [c["id"] for c in cases if c["outputs"].get(label, {}).get("empty_markdown")] for label in binaries},
        "scores": {label: evaluations[label]["metrics"]["score"] for label in binaries},
        "metric_coverage": {label: {k: v for k, v in evaluations[label]["metrics"].items() if k != "score"} for label in binaries},
        "failures": failures, "cases": cases,
        "scope": "complete public corpus native-CLI no-regression comparison plus unmodified upstream ground-truth evaluator; no OCR or LLM",
        "designated_pdf_evals_obtained": False, "satisfies_current_named_policy_without_user_change": False,
        "limitations": "A no-regression pass does not mean every extraction is correct. Empty native output for scanned PDFs is scored and reported, never skipped. Original pdf-evals has not been obtained or run."}
    save(output / "report.json", report)
    print(json.dumps({k: report[k] for k in ("status", "documents", "snapshots_changed", "execution_errors", "scores", "empty_markdown_ids", "failures")}, ensure_ascii=False), flush=True)
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["test"])
    p.add_argument("--corpus-root", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()
    if args.timeout <= 0:
        p.error("timeout must be positive")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
