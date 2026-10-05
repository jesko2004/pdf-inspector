"""Export a review packet or score a saved benchmark; never call a model."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.evaluation import EvaluationReviews, fingerprint, load_json, validate_dataset


def validate_report(dataset: dict, report: dict) -> dict:
    if report.get("dataset_sha256") != fingerprint(dataset):
        raise ValueError("report dataset fingerprint differs or is absent; use the matching versioned report")
    cases = {case["id"]: case for case in dataset["cases"]}
    rows = {}
    for row in report.get("answers", []):
        identifier = row["id"]
        if identifier in rows or identifier not in cases:
            raise ValueError("duplicate or unknown report case ID")
        if type(row.get("expected_answerable")) is not bool or row["expected_answerable"] != cases[identifier]["answerable"]:
            raise ValueError("report answerability differs from dataset")
        if ("answer" in row) == ("error" in row):
            raise ValueError("report row must contain exactly one answer or error")
        if "answer" in row:
            answer = row["answer"]
            if answer.get("question") != cases[identifier]["query"] or type(answer.get("refused")) is not bool:
                raise ValueError("report question or refusal flag is invalid")
            if not isinstance(answer.get("answer"), str) or not isinstance(answer.get("citations"), list):
                raise ValueError("report answer or citations are invalid")
            for citation in answer["citations"]:
                if not isinstance(citation.get("document_id"), str) or any(type(page) is not int or page < 1 for page in citation.get("pages", [])):
                    raise ValueError("report citation document or pages are invalid")
        rows[identifier] = row
    keys = [source["key"] for source in report.get("inputs", [])]
    if len(set(keys)) != len(keys) or not set(keys).issubset({source["key"] for source in dataset["documents"]}):
        raise ValueError("duplicate or unknown report input")
    return rows


def review_template(dataset: dict, report: dict) -> dict:
    dataset = validate_dataset(dataset)
    validate_report(dataset, report)
    return {
        "schema_version": 1,
        "dataset_sha256": fingerprint(dataset),
        "report_sha256": fingerprint(report),
        "reviews": [{"case_id": case["id"], "reviewer": "", "reviewed_at": None,
                     "label_verdict": "unreviewed", "answer_verdict": "unreviewed",
                     "citation_verdict": "unreviewed", "failure_stage": None, "comment": ""}
                    for case in dataset["cases"]],
    }


def code_block(value: str) -> str:
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
    return f"{fence}text\n{value}\n{fence}"


def review_sheet(dataset: dict, report: dict) -> str:
    dataset = validate_dataset(dataset)
    rows = validate_report(dataset, report)
    sources = {source["key"]: source for source in dataset["documents"]}
    lines = ["# 逐题审核表", "", "标签和机器诊断均不代表人工验收。先回到 PDF 原页确认参考标签，再审核本次答案及引用。",
             "", "填写 review-template.json：label_verdict（confirmed/incorrect/uncertain）、answer_verdict（correct/incorrect/uncertain）、citation_verdict（supported/unsupported/uncertain/not_applicable）。",
             "审核必须填写 reviewer 与带时区的 reviewed_at；判断依据写入 comment。资料或答案变更后重新导出审核表。错误标签先修数据并重新评测，不把旧答案套到新标签上。", ""]
    for index, case in enumerate(dataset["cases"], 1):
        row = rows.get(case["id"], {})
        answer = row.get("answer", {})
        lines += [f"## {index}. {case['id']}", "", code_block(json.dumps({
            "query": case["query"], "split": case["split"], "category": case["category"], "language": case["language"],
            "source_pdf": sources[case["document"]]["path"], "expected_answerable": case["answerable"],
            "expected_pages": case["pages"], "required_source_text": case["required_text"],
            "expected_answer_fragments": case["expected_answer_fragments"],
        }, ensure_ascii=False, indent=2)), "", "本次答案：", "", code_block(answer.get("answer", row.get("error", "尚未执行"))), "",
            "来源与逐条证据：", "", code_block(json.dumps({"citations": answer.get("citations", []), "claims": answer.get("claims", []), "context": answer.get("context", {})}, ensure_ascii=False, indent=2)), ""]
    return "\n".join(lines)


def ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator, "rate": round(numerator / denominator, 6) if denominator else None}


def split_scope(dataset: dict) -> dict:
    families = {source["key"]: source.get("family", source["key"]) for source in dataset["documents"]}
    split_families = {split: {families[case["document"]] for case in dataset["cases"] if case["split"] == split} for split in ("tuning", "check")}
    overlap = sorted(split_families["tuning"] & split_families["check"])
    return {"shared_document_families": overlap,
            "document_family_overlap_detected": bool(overlap),
            "independent_holdout_certified": False,
            "note": "No observed family overlap does not certify independence; family labels, near duplicates and sampling still require review."}


def score(dataset: dict, report: dict, reviews: dict | None = None) -> dict:
    dataset = validate_dataset(dataset)
    rows = validate_report(dataset, report)
    assessments = {}
    if reviews is not None:
        checked = EvaluationReviews.model_validate(reviews)
        if checked.dataset_sha256 != fingerprint(dataset) or checked.report_sha256 != fingerprint(report):
            raise ValueError("stale reviews: dataset or report changed")
        known_ids = {case["id"] for case in dataset["cases"]}
        for review in checked.reviews:
            if review.case_id not in known_ids:
                raise ValueError("review refers to an unknown case")
            answer = rows.get(review.case_id, {}).get("answer")
            if not answer and (review.answer_verdict == "correct" or review.citation_verdict in {"supported", "not_applicable"}):
                raise ValueError("missing or failed answer cannot be reviewed as correct or supported")
            case = next(case for case in dataset["cases"] if case["id"] == review.case_id)
            if answer and review.label_verdict == "confirmed" and review.answer_verdict == "correct" and answer["refused"] == case["answerable"]:
                raise ValueError("correct verdict conflicts with confirmed answerability")
            if answer and ((review.citation_verdict == "not_applicable" and not answer["refused"]) or
                           (review.citation_verdict == "supported" and (answer["refused"] or not answer["citations"]))):
                raise ValueError("citation verdict conflicts with refusal or absent citations")
            assessments[review.case_id] = review.model_dump(mode="json")
    documents = {source["key"]: source.get("document_id") for source in report.get("inputs", [])}
    results = []
    for case in dataset["cases"]:
        row = rows.get(case["id"], {})
        answer = row.get("answer")
        positive = case["answerable"]
        citation_match = None
        if positive and answer is not None and documents.get(case["document"]):
            pages = {page for citation in answer["citations"] if citation["document_id"] == documents[case["document"]] for page in citation["pages"]}
            citation_match = set(case["pages"]).issubset(pages)
        results.append({"id": case["id"], "split": case["split"], "category": case["category"], "language": case["language"],
            "expected_answerable": positive, "execution": "answer" if answer else ("error" if "error" in row else "missing"),
            "status": answer.get("status") if answer else None,
            "refusal_matches": answer["refused"] == (not positive) if answer else None,
            "refused": answer["refused"] if answer else None,
            "expected_fragments_present": all(fragment.casefold() in answer["answer"].casefold() for fragment in case["expected_answer_fragments"]) if positive and answer and not answer["refused"] else None,
            "final_citation_covers_expected_document_pages": citation_match,
            "review": assessments.get(case["id"]),
        })

    def summarize(items):
        positives = [item for item in items if item["expected_answerable"]]
        negatives = [item for item in items if not item["expected_answerable"]]
        label_confirmed = [item for item in items if item["review"] and item["review"]["label_verdict"] == "confirmed"]
        judged = [item for item in label_confirmed if item["review"]["answer_verdict"] in {"correct", "incorrect"}]
        citations_judged = [item for item in label_confirmed if item["review"]["citation_verdict"] in {"supported", "unsupported"}]
        return {
            "cases": len(items), "errors": sum(item["execution"] == "error" for item in items), "missing": sum(item["execution"] == "missing" for item in items),
            "machine_diagnostics": {
                "correct_refusal": ratio(sum(item["refused"] is True for item in negatives), len(negatives)),
                "unanswerable_not_refused": sum(item["refused"] is False for item in negatives),
                "answerable_over_refused": sum(item["refused"] is True for item in positives),
                "answerable_fragment_match": ratio(sum(item["expected_fragments_present"] is True for item in positives), len(positives)),
                "citation_page_match": ratio(sum(item["final_citation_covers_expected_document_pages"] is True for item in positives), len(positives)),
            },
            "human_review": {
                "labels_confirmed": len(label_confirmed), "labels_incorrect": sum(bool(item["review"]) and item["review"]["label_verdict"] == "incorrect" for item in items),
                "answer_review_coverage": ratio(len(judged), len(items)),
                "answer_correctness_among_reviewed": ratio(sum(item["review"]["answer_verdict"] == "correct" for item in judged), len(judged)),
                "citation_support_among_reviewed": ratio(sum(item["review"]["citation_verdict"] == "supported" for item in citations_judged), len(citations_judged)),
            },
        }

    output = {"scored_at": datetime.now(timezone.utc).isoformat(), "dataset_sha256": fingerprint(dataset), "report_sha256": fingerprint(report),
        "annotation_status": dataset["annotation_status"], "model_calls": 0, "split_scope": split_scope(dataset),
        "overall": summarize(results), "by_split": {}, "by_category": {}, "by_language": {}, "results": results,
        "limitations": ["Machine fragment and document/page matches are diagnostics, not semantic correctness.",
                        "Errors and missing results remain in machine denominators; unknown human verdicts are not passes.",
                        "Human rates cover only confirmed labels with explicit verdicts; partial review can be selection biased.",
                        "No real-user feedback, independent holdout or production quality inferred."]}
    for field in ("split", "category", "language"):
        output["by_" + field] = {name: summarize([item for item in results if item[field] == name]) for name in sorted({item[field] for item in results})}
    return output


def score_summary(result: dict) -> str:
    overall = result["overall"]
    machine, human = overall["machine_diagnostics"], overall["human_review"]
    return "\n".join(["# 评测审核汇总", "", f"问题 {overall['cases']}；调用错误 {overall['errors']}；未执行 {overall['missing']}。本命令模型调用为 0。",
        f"无答案题正确拒答 {machine['correct_refusal']['numerator']}/{machine['correct_refusal']['denominator']}；仍作答 {machine['unanswerable_not_refused']}。",
        f"有答案题关键片段出现 {machine['answerable_fragment_match']['numerator']}/{machine['answerable_fragment_match']['denominator']}；此值不是答案准确率。",
        f"已确认标签 {human['labels_confirmed']}；答案人工审核覆盖 {human['answer_review_coverage']['numerator']}/{human['answer_review_coverage']['denominator']}。",
        f"已审答案正确 {human['answer_correctness_among_reviewed']['numerator']}/{human['answer_correctness_among_reviewed']['denominator']}；未经审核项不算通过。",
        "", "调参与检查集共享文档族：" + (", ".join(result["split_scope"]["shared_document_families"]) or "未发现（仍需复核分组与近重复）"),
        "", "完整分组、逐题诊断与人工结论见同目录 JSON。机器诊断不验证引用的语义支持；人工比例仅覆盖明确审核的子集。", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "score"])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare" and args.reviews:
        parser.error("--reviews only applies to score")
    try:
        dataset, report = validate_dataset(load_json(args.dataset)), load_json(args.report)
        if args.action == "prepare":
            payload = review_template(dataset, report)
            outputs = {"review-template.json": json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "review-sheet.md": review_sheet(dataset, report)}
        else:
            payload = score(dataset, report, load_json(args.reviews) if args.reviews else None)
            outputs = {"score.json": json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "score.md": score_summary(payload)}
        for name in outputs:
            path = args.output_dir / name
            if path.resolve() in {candidate.resolve() for candidate in (args.dataset, args.report, args.reviews) if candidate}:
                raise ValueError("output cannot overwrite an input")
            if path.exists() and not args.overwrite:
                raise ValueError("output already exists; use a new directory or explicit --overwrite")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, value in outputs.items():
            path = args.output_dir / name
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(value, encoding="utf-8")
            temporary.replace(path)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"action": args.action, "output_dir": str(args.output_dir), "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
