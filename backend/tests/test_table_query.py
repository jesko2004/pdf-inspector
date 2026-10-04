import unittest
import sys
import types
from contextlib import contextmanager
from unittest.mock import patch

from pydantic import ValidationError

from backend.advanced_retrieval import table_metadata
from backend.chunking import chunk_pages
from backend.knowledge_models import KnowledgeAskRequest, KnowledgeSearchRequest
from backend.table_query import TableQueryError, compile_filters, matching_rows
from backend.tests import test_advanced_retrieval as helpers
from backend.vector_store import PgVectorStore, VectorSearchQuery


def metadata(headers, rows):
    return {"table": table_metadata("\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]))}


class TablePredicateTests(unittest.TestCase):
    def test_exact_values_keep_model_punctuation_and_numeric_boundaries(self):
        table = metadata(["Model", "Price"], [["X1000", "1950"], ["X100", "950"], ["X-100", "950"]])
        hits = matching_rows(table, {"Model": "X100", "Price": "950"})
        self.assertEqual([2], [r["row"] for r in hits])
        self.assertEqual([3], [r["row"] for r in matching_rows(table, {"Model": "X-100"})])
        self.assertEqual(3, len(matching_rows(table, {"Model": {"op": "contains", "value": "X"}})))

    def test_all_predicates_must_match_same_row(self):
        table = metadata(["Model", "Price"], [["X100", "1950"], ["X200", "950"]])
        self.assertEqual([], matching_rows(table, {"Model": "X100", "Price": "950"}))

    def test_numeric_ranges_are_inclusive_and_use_decimals(self):
        table = metadata(["Price"], [["949.99"], ["950.00"], ["1,950.00"], ["1950.01"]])
        self.assertEqual([2, 3], [r["row"] for r in matching_rows(table, {
            "Price": {"op": "between", "min_value": "950", "max_value": "1950"},
        })])
        self.assertEqual([2], [r["row"] for r in matching_rows(table, {
            "Price": {"value_type": "number", "value": "950"},
        })])
        self.assertEqual([4], [r["row"] for r in matching_rows(table, {
            "Price": {"op": "gt", "value": "1950"},
        })])

    def test_unit_conversion_never_guesses_a_missing_unit(self):
        table = metadata(["Weight"], [["950 g"], ["0.95 kg"], ["950"], ["950 ml"], ["950 unknown"]])
        filters = {"Weight": {"value_type": "number", "value": "0.95", "unit": "kg"}}
        self.assertEqual([1, 2], [r["row"] for r in matching_rows(table, filters)])
        self.assertEqual([3], [r["row"] for r in matching_rows(table, {"Weight": {"op": "eq", "value_type": "number", "value": "950"}})])

    def test_currency_requires_explicit_source_and_no_exchange_conversion(self):
        table = metadata(["Price", "Currency"], [["$950", "USD"], ["950", "CNY"], ["950 USD", "USD"], ["¥950", "USD"]])
        condition = {"value_type": "number", "value": "950", "currency": "USD"}
        self.assertEqual([3], [r["row"] for r in matching_rows(table, {"Price": condition})])
        condition["currency_column"] = "Currency"
        self.assertEqual([1, 3], [r["row"] for r in matching_rows(table, {"Price": condition})])

    def test_sibling_units_are_same_row_and_conflicting_units_do_not_match(self):
        table = metadata(["Weight", "Unit"], [["950", "g"], ["950", "kg"], ["950 g", "kg"]])
        self.assertEqual([1], [r["row"] for r in matching_rows(table, {
            "Weight": {"value_type": "number", "value": "0.95", "unit": "kg", "unit_column": "Unit"},
        })])

    def test_duplicate_columns_preserve_both_values_and_require_identity(self):
        table = metadata(["Model", "Price", "Price"], [["X100", "950", "1950"]])
        self.assertNotIn("Price", table["table"]["rows"][0])
        self.assertEqual("1950", table["table"]["row_values"][0][2])
        with self.assertRaises(TableQueryError):
            matching_rows(table, {"Price": "950"})
        rows = matching_rows(table, {"column_2": "950", "column_3": "1950"})
        self.assertEqual("column_3", rows[0]["cells"][2]["column_id"])
        # Existing indices already contain positional cells; no re-embedding needed.
        del table["table"]["row_values"]
        self.assertEqual(1, len(matching_rows(table, {"column_3": "1950"})))

    def test_malformed_conditions_fail_request_validation(self):
        invalid = [
            {"op": "unknown", "value": "950"},
            {"op": "between", "min_value": "100", "max_value": "10"},
            {"op": "gt", "value": "NaN"}, {"op": "gt", "value": "1e99"},
            {"op": "gt", "value": "95,00"},
            {"op": "contains", "value": "9", "value_type": "number"},
            {"value": "950", "unit": "g"},
            {"value_type": "number", "value": "950", "currency": "$"},
            {"value_type": "number", "value": "950", "unit": "gal"},
            {"value_type": "number", "value": "950", "unit_column": "Unit"},
        ]
        for condition in invalid:
            with self.subTest(condition=condition), self.assertRaises(ValidationError):
                KnowledgeAskRequest(question="price?", table_filters={"Price": condition})
        with self.assertRaises(TableQueryError):
            compile_filters({"Price": "950", " Price ": "1950"})
        payload = KnowledgeSearchRequest(query="X100", table_filters={"Model": " X100 "})
        self.assertEqual(" X100 ", payload.table_filters["Model"].value)

    def test_pgvector_match_after_old_candidate_cutoff_is_returned(self):
        nonmatch = metadata(["Model"], [["X1000"]])
        match = metadata(["Model"], [["X100"]])
        source = [(f"c{i}", "kb", "doc", "hash", "table", 1, 1, [], "table", nonmatch, 1.0)
                  for i in range(300)]
        source.append(("target", "kb", "doc", "hash", "table", 1, 1, [], "table", match, 0.5))
        class Cursor:
            def fetchmany(self, size):
                rows = source[:size]
                del source[:size]
                return rows
        class Connection:
            def execute(self, sql, params):
                self_sql.append(sql)
                return Cursor()
        @contextmanager
        def connect():
            yield Connection()
        self_sql = []
        store = object.__new__(PgVectorStore)
        pgvector = types.ModuleType("pgvector")
        pgvector.Vector = lambda values: values
        with patch.object(store, "_connect", connect), patch.dict(sys.modules, {"pgvector": pgvector}):
            hits = store.search(VectorSearchQuery("kb", [1.0], "hash", "hash-v1", 1,
                                                 table_filters=(("Model", "X100"),)))
        self.assertEqual(["target"], [h.chunk_id for h in hits])
        self.assertNotIn("LIMIT", self_sql[0])


class TableServiceTests(unittest.TestCase):
    setUp = helpers.AdvancedRetrievalTests.setUp
    tearDown = helpers.AdvancedRetrievalTests.tearDown
    add_task = helpers.AdvancedRetrievalTests.add_task
    ingest = helpers.AdvancedRetrievalTests.ingest
    search = helpers.AdvancedRetrievalTests.search

    def test_projection_prevents_unmatched_rows_reentering_parent_context(self):
        chunks = chunk_pages([(3, "# Prices\n\n| Model | Price |\n|---|---|\n| X100 | 950 |\n| X1000 | 1950 |")], document_id="prices")
        self.ingest("table-query", chunks)
        for mode in ("vector", "bm25", "hybrid"):
            with self.subTest(mode=mode):
                item = self.search("X100 price", retrieval_mode=mode, table_filters={"Model": "X100"})["items"][0]
                self.assertIn("950", item["content"])
                self.assertNotIn("1950", item["context_content"])
                self.assertNotIn("X1000", item["content"])
                self.assertEqual(item["content"], item["context_content"])
                self.assertEqual([3], item["citation"]["pages"])
                self.assertEqual([1], [r["row"] for r in item["matched_table_rows"]])

    def test_ambiguous_input_fails_before_query_embedding(self):
        chunks = chunk_pages([(1, "| Price | Price |\n|---|---|\n|950|1950|")], document_id="prices")
        self.ingest("ambiguous", chunks)
        with patch.object(self.service, "_embed", side_effect=AssertionError("must not spend tokens")):
            with self.assertRaises(TableQueryError):
                self.search("price", table_filters={"Price": "950"})
            with self.assertRaises(TableQueryError):
                self.search("price", table_filters={"Price": {"op": "gt", "value": "NaN"}})


if __name__ == "__main__":
    unittest.main()
