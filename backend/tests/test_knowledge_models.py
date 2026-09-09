import unittest

from pydantic import ValidationError

from backend.knowledge_models import (
    KnowledgeRetrievalEvaluationRequest,
    KnowledgeSearchRequest,
)


class KnowledgeModelTests(unittest.TestCase):
    def test_search_filters_are_trimmed_and_deduplicated(self):
        request = KnowledgeSearchRequest(
            query="  installation requirements  ",
            document_ids=[" doc-1 ", "doc-1"],
            kinds=[" text ", "text"],
            section_path_prefix=[" Guide ", "Install"],
        )

        self.assertEqual("installation requirements", request.query)
        self.assertEqual(["doc-1"], request.document_ids)
        self.assertEqual(["text"], request.kinds)
        self.assertEqual(["Guide", "Install"], request.section_path_prefix)

    def test_search_rejects_an_inverted_page_range(self):
        with self.assertRaisesRegex(ValidationError, "page_start"):
            KnowledgeSearchRequest(query="question", page_start=5, page_end=4)

    def test_evaluation_requires_unique_case_ids(self):
        case = {
            "id": "duplicate",
            "query": "question",
            "expected_sources": [{"document_id": "doc-1", "pages": [1]}],
        }
        with self.assertRaisesRegex(ValidationError, "case IDs"):
            KnowledgeRetrievalEvaluationRequest(cases=[case, case])


if __name__ == "__main__":
    unittest.main()
