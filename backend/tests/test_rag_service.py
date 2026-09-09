import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.config import Settings
from backend.llm import LlmResult
from backend.rag_service import REFUSAL, RagService


class FakeKnowledge:
    def __init__(self, items):
        self.items = items

    def search(self, knowledge_base_id, question, **_filters):
        return {
            "knowledge_base_id": knowledge_base_id,
            "query": question,
            "returned": len(self.items),
            "latency_ms": 1.25,
            "items": self.items,
        }


class RecordingProvider:
    name = "recording"
    model = "recording-v1"

    def __init__(self):
        self.calls = []

    def generate(self, messages, *, max_tokens):
        self.calls.append((messages, max_tokens))
        return LlmResult("grounded answer [manual.pdf p.2]", {"completion_tokens": 8})

    def stream(self, messages, *, max_tokens):
        self.calls.append((messages, max_tokens))
        yield "grounded "
        yield "answer"


def source_item(content="evidence"):
    citation = {
        "document_id": "doc-1",
        "document_key": "manual",
        "filename": "manual.pdf",
        "pages": [2],
        "section_path": ["Guide"],
    }
    return {
        "chunk_id": "chunk-1",
        "filename": "manual.pdf",
        "pages": [2],
        "section_path": ["Guide"],
        "content": content,
        "citation": citation,
    }


class RagServiceTests(unittest.TestCase):
    def settings(self, root):
        return Settings(
            data_dir=Path(root),
            builtin_profile_dir=Path(root) / "profiles",
            llm_provider="extractive",
            llm_model="extractive-v1",
            rag_max_context_tokens=128,
            rag_max_output_tokens=64,
        )

    def prepare(self, service):
        return service.prepare(
            "kb-1",
            "What is required?",
            top_k=5,
            min_score=0.2,
            document_ids=[],
            page_start=None,
            page_end=None,
            kinds=[],
            section_path_prefix=[],
            max_context_tokens=128,
            max_output_tokens=64,
        )

    def test_context_budget_citations_and_generation(self):
        with TemporaryDirectory() as temporary:
            provider = RecordingProvider()
            knowledge = FakeKnowledge([source_item("evidence " * 500)])
            service = RagService(
                self.settings(temporary),
                knowledge,
                llm_factory=lambda _provider, _model: provider,
            )
            prepared = self.prepare(service)
            result = service.answer(prepared)

        self.assertTrue(prepared.context["truncated"])
        self.assertLessEqual(prepared.context["estimated_tokens"], 128)
        self.assertEqual([2], result["citations"][0]["pages"])
        self.assertFalse(result["refused"])
        self.assertEqual(64, provider.calls[0][1])

    def test_no_evidence_refuses_without_calling_llm(self):
        with TemporaryDirectory() as temporary:
            provider = RecordingProvider()
            service = RagService(
                self.settings(temporary),
                FakeKnowledge([]),
                llm_factory=lambda _provider, _model: provider,
            )
            result = service.answer(self.prepare(service))

        self.assertTrue(result["refused"])
        self.assertEqual(REFUSAL, result["answer"])
        self.assertEqual([], result["citations"])
        self.assertEqual([], provider.calls)

    def test_stream_emits_metadata_tokens_and_done(self):
        with TemporaryDirectory() as temporary:
            provider = RecordingProvider()
            service = RagService(
                self.settings(temporary),
                FakeKnowledge([source_item()]),
                llm_factory=lambda _provider, _model: provider,
            )
            events = list(service.stream(self.prepare(service)))

        self.assertEqual(
            ["metadata", "token", "token", "done"], [e["event"] for e in events]
        )
        self.assertEqual("grounded answer", events[-1]["data"]["answer"])


if __name__ == "__main__":
    unittest.main()
