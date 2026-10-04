import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from backend.evaluation import fingerprint, validate_dataset
from scripts.score_landing import load_json, review_sheet, review_template, score


def dataset():
    return validate_dataset({
        "version": "test-v1", "scenario": "Parameter lookup", "annotation_status": "draft", "scope": "test data",
        "documents": [{"key": "manual", "path": "tests/fixtures/manual.pdf", "family": "controller"}],
        "cases": [
            {"id": "voltage", "split": "tuning", "query": "电源电压？", "document": "manual", "pages": [2], "required_text": ["24 V"], "expected_answer_fragments": ["24", "V"], "answerable": True, "language": "zh", "category": "parameter"},
            {"id": "warranty", "split": "check", "query": "Warranty?", "document": "manual", "pages": [], "required_text": [], "expected_answer_fragments": [], "answerable": False, "language": "en", "category": "unanswerable"},
        ],
    })


def report(value):
    return {
        "dataset_sha256": fingerprint(value), "inputs": [{"key": "manual", "document_id": "doc-1"}],
        "answers": [
            {"id": "voltage", "expected_answerable": True, "answer": {"question": "电源电压？", "answer": "24 V", "status": "needs_review", "refused": False, "citations": [{"document_id": "doc-1", "pages": [2]}]}},
            {"id": "warranty", "expected_answerable": False, "answer": {"question": "Warranty?", "answer": "24 V", "status": "needs_review", "refused": False, "citations": [{"document_id": "doc-1", "pages": [2]}]}},
        ],
    }


class DatasetTests(unittest.TestCase):
    def test_duplicate_unknown_and_inconsistent_labels_rejected(self):
        for change in ("duplicate", "unknown", "negative_evidence", "no_evidence", "string_bool", "boolean_page", "blank_fragment", "unexpected_field"):
            value = dataset()
            if change == "duplicate":
                value["cases"].append(copy.deepcopy(value["cases"][0]))
            elif change == "unknown":
                value["cases"][0]["document"] = "outside"
            elif change == "negative_evidence":
                value["cases"][1]["pages"] = [1]
            elif change == "no_evidence":
                value["cases"][0]["required_text"] = []
            elif change == "string_bool":
                value["cases"][0]["answerable"] = "true"
            elif change == "boolean_page":
                value["cases"][0]["pages"] = [True]
            elif change == "blank_fragment":
                value["cases"][0]["required_text"] = [" "]
            else:
                value["cases"][0]["extra"] = 1
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_dataset(value)

    def test_relative_pdf_paths_only(self):
        for path in ("../manual.pdf", "D:/private/manual.pdf", "/manual.pdf", "tests/manual.txt", "tests/../../manual.pdf"):
            value = dataset()
            value["documents"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValidationError):
                validate_dataset(value)

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for value in ('{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"a":NaN}', '[]'):
                path.write_text(value, encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_json(path)


class ReviewTests(unittest.TestCase):
    def setup_inputs(self):
        value = dataset()
        saved = report(value)
        return value, saved, review_template(value, saved)

    def reviewed(self, template):
        template["reviews"][0].update(reviewer="test-reviewer", reviewed_at="2026-10-04T18:00:00+08:00", label_verdict="confirmed", answer_verdict="correct", citation_verdict="supported")
        return template

    def test_unreviewed_is_not_quality_pass_even_with_matching_keywords(self):
        value, saved, template = self.setup_inputs()
        with patch("backend.embeddings.create_embedding_provider", side_effect=AssertionError("model call")), patch("backend.llm.create_llm_provider", side_effect=AssertionError("model call")):
            result = score(value, saved, template)
        self.assertEqual(0, result["model_calls"])
        self.assertEqual(1, result["overall"]["machine_diagnostics"]["unanswerable_not_refused"])
        self.assertEqual(1.0, result["overall"]["machine_diagnostics"]["answerable_fragment_match"]["rate"])
        self.assertIsNone(result["overall"]["human_review"]["answer_correctness_among_reviewed"]["rate"])
        self.assertEqual(0, result["overall"]["human_review"]["answer_review_coverage"]["numerator"])

    def test_explicit_review_has_own_denominator_and_split_groups(self):
        value, saved, template = self.setup_inputs()
        result = score(value, saved, self.reviewed(template))
        self.assertEqual({"numerator": 1, "denominator": 2, "rate": 0.5}, result["overall"]["human_review"]["answer_review_coverage"])
        self.assertEqual(1, result["overall"]["human_review"]["answer_correctness_among_reviewed"]["denominator"])
        self.assertEqual(1, result["by_language"]["zh"]["cases"])
        self.assertEqual(1, result["by_split"]["check"]["cases"])
        self.assertTrue(result["split_scope"]["document_family_overlap_detected"])
        self.assertFalse(result["split_scope"]["independent_holdout_certified"])

    def test_stale_duplicate_unknown_reviews_rejected(self):
        for change in ("stale_answer", "stale_dataset", "duplicate", "unknown"):
            value, saved, template = self.setup_inputs()
            if change == "stale_answer":
                saved["answers"][0]["answer"]["answer"] = "changed"
            elif change == "stale_dataset":
                template["dataset_sha256"] = "0" * 64
            elif change == "duplicate":
                template["reviews"].append(copy.deepcopy(template["reviews"][0]))
            else:
                template["reviews"][0]["case_id"] = "outside"
            with self.subTest(change=change), self.assertRaises(ValueError):
                score(value, saved, template)

    def test_reviews_need_reviewer_timezone_and_failure_explanation(self):
        for change in ("reviewer", "naive_time", "comment"):
            value, saved, template = self.setup_inputs()
            self.reviewed(template)
            if change == "reviewer":
                template["reviews"][0]["reviewer"] = " "
            elif change == "naive_time":
                template["reviews"][0]["reviewed_at"] = "2026-10-04T18:00:00"
            else:
                template["reviews"][0]["failure_stage"] = "generation"
            with self.subTest(change=change), self.assertRaises(ValidationError):
                score(value, saved, template)

    def test_incorrect_or_uncertain_labels_do_not_enter_correctness_rate(self):
        value, saved, template = self.setup_inputs()
        self.reviewed(template)
        for verdict in ("incorrect", "uncertain"):
            template["reviews"][0]["label_verdict"] = verdict
            self.assertIsNone(score(value, saved, template)["overall"]["human_review"]["answer_correctness_among_reviewed"]["rate"])

    def test_execution_errors_and_missing_answers_remain_in_denominators(self):
        value, saved, template = self.setup_inputs()
        saved["answers"][1].pop("answer")
        saved["answers"][1]["error"] = "provider unavailable"
        result = score(value, saved)
        self.assertEqual(1, result["overall"]["errors"])
        self.assertEqual(0.0, result["overall"]["machine_diagnostics"]["correct_refusal"]["rate"])
        saved["answers"] = []
        self.assertEqual(2, score(value, saved)["overall"]["missing"])

    def test_incompatible_correct_and_citation_verdicts_rejected(self):
        for change in ("failed_correct", "supported_without_citations", "not_applicable_answer", "wrong_refusal_correct"):
            value, saved, template = self.setup_inputs()
            if change == "failed_correct":
                saved["answers"][0] = {"id": "voltage", "expected_answerable": True, "error": "failure"}
            elif change == "supported_without_citations":
                saved["answers"][0]["answer"]["citations"] = []
            elif change == "wrong_refusal_correct":
                saved["answers"][0]["answer"]["refused"] = True
            template = review_template(value, saved)
            self.reviewed(template)
            if change == "not_applicable_answer":
                template["reviews"][0]["citation_verdict"] = "not_applicable"
            with self.subTest(change=change), self.assertRaises(ValueError):
                score(value, saved, template)

    def test_machine_citation_checks_document_and_all_expected_pages(self):
        value = dataset()
        value["cases"][0]["pages"] = [2, 3]
        saved = report(value)
        self.assertFalse(score(value, saved)["results"][0]["final_citation_covers_expected_document_pages"])
        saved["answers"][0]["answer"]["citations"].append({"document_id": "outside", "pages": [3]})
        self.assertFalse(score(value, saved)["results"][0]["final_citation_covers_expected_document_pages"])
        saved["answers"][0]["answer"]["citations"].append({"document_id": "doc-1", "pages": [3]})
        self.assertTrue(score(value, saved)["results"][0]["final_citation_covers_expected_document_pages"])

    def test_review_sheet_keeps_untrusted_answer_in_code_fence(self):
        value, saved, _ = self.setup_inputs()
        saved["answers"][0]["answer"]["answer"] = '```\n<script>unsafe</script>\n```'
        sheet = review_sheet(value, saved)
        self.assertIn('````text\n```\n<script>unsafe</script>\n```\n````', sheet)
        self.assertIn("tests/fixtures/manual.pdf", sheet)

    def test_mismatched_or_duplicate_report_rejected(self):
        value, saved, _ = self.setup_inputs()
        saved["answers"].append(copy.deepcopy(saved["answers"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            score(value, saved)
        saved["dataset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            score(value, saved)


if __name__ == "__main__":
    unittest.main()
