"""Ensure incomplete runs and adverse results cannot pass the public gate."""
from copy import deepcopy
import unittest

from scripts.bench_public_pdf import gates, IDS, normalize, SCORES


class PublicGateTests(unittest.TestCase):
    def setUp(self):
        self.evaluation = {
            "documents": [{"document_id": key, "prediction_available": True} for key in sorted(IDS)],
            "metrics": {"missing_predictions": 0, "score": {key: 0.5 for key in SCORES}},
        }
        self.cases = [{"id": key, "markdown_equal": True, "normalized_json_equal": True} for key in sorted(IDS)]

    def test_complete_equal_run_passes(self):
        self.assertEqual(gates(self.evaluation, deepcopy(self.evaluation), self.cases), [])

    def test_missing_or_duplicate_case_fails(self):
        self.assertTrue(gates(self.evaluation, self.evaluation, self.cases[:-1]))
        duplicated = self.cases[:-1] + [self.cases[0]]
        self.assertTrue(gates(self.evaluation, self.evaluation, duplicated))

    def test_execution_and_snapshot_failures(self):
        for change in ({"error": "CLI timeout"}, {"markdown_equal": False}, {"normalized_json_equal": False}):
            with self.subTest(change=change):
                cases = deepcopy(self.cases)
                cases[0].update(change)
                self.assertTrue(gates(self.evaluation, self.evaluation, cases))

    def test_evaluator_cannot_silently_drop_or_hide_document(self):
        for label in ("baseline", "candidate"):
            for change in ("drop", "duplicate", "unavailable", "missing"):
                with self.subTest(label=label, change=change):
                    damaged = deepcopy(self.evaluation)
                    if change == "drop":
                        damaged["documents"].pop()
                    elif change == "duplicate":
                        damaged["documents"][-1] = damaged["documents"][0]
                    elif change == "unavailable":
                        damaged["documents"][0]["prediction_available"] = False
                    else:
                        damaged["metrics"]["missing_predictions"] = 1
                    baseline, candidate = (damaged, self.evaluation) if label == "baseline" else (self.evaluation, damaged)
                    self.assertTrue(gates(baseline, candidate, self.cases))

    def test_each_metric_regression_and_invalid_score_fails(self):
        for metric in SCORES:
            for value in (0.49, None, float("nan"), float("inf")):
                with self.subTest(metric=metric, value=value):
                    candidate = deepcopy(self.evaluation)
                    candidate["metrics"]["score"][metric] = value
                    self.assertTrue(gates(self.evaluation, candidate, self.cases))

    def test_normalization_ignores_only_processing_time(self):
        a = {"processing_time_ms": 1, "pages": [{"text": "source", "processing_time_ms": 2}], "page_count": 3}
        b = deepcopy(a)
        b["processing_time_ms"] = 99
        b["pages"][0]["processing_time_ms"] = 88
        self.assertEqual(normalize(a), normalize(b))
        b["pages"][0]["text"] = "altered"
        self.assertNotEqual(normalize(a), normalize(b))


if __name__ == "__main__":
    unittest.main()
