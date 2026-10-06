import unittest
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory

from backend.config import Settings
from backend.llm import LlmResult, estimate_tokens
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

    def test_grounded_budget_preserves_later_row_and_unit_sources(self):
        with TemporaryDirectory() as temporary:
            settings = replace(self.settings(temporary), llm_provider="openai_compatible",
                               llm_model="local-instruct", rag_answer_format="grounded_json")
            first = {**source_item("Verbose earlier equipment " * 500), "parent_id": "parent-1"}
            later = {**source_item("Version Ultra costs 200 KRW."),
                     "parent_id": "parent-2", "chunk_id": "price-source"}
            prepared = self.prepare(RagService(settings, FakeKnowledge([first, later])))
        self.assertEqual(["chunk-1", "price-source"], [s["chunk_id"] for s in prepared.sources])
        self.assertEqual("Version Ultra costs 200 KRW.", prepared.sources[1]["text"])
        self.assertLessEqual(prepared.context["estimated_tokens"], 128)
        self.assertEqual(0, prepared.context["budget_omitted"])
        self.assertEqual(1, prepared.context["body_truncated"])
        self.assertEqual("balanced_parent_share", prepared.context["allocation_method"])

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

    def test_parent_deduplication_does_not_mean_truncation(self):
        with TemporaryDirectory() as temporary:
            first = {**source_item(), "parent_id": "parent-1"}
            duplicate = {**first, "chunk_id": "chunk-2"}
            service = RagService(self.settings(temporary), FakeKnowledge([first, duplicate]))
            prepared = self.prepare(service)
        self.assertFalse(prepared.context["truncated"])
        self.assertEqual(1, prepared.context["deduplicated"])
        self.assertEqual(0, prepared.context["omitted"])
        self.assertEqual([], prepared.context["truncation_reasons"])
        self.assertEqual("duplicate_parent", prepared.context["selection"][1]["reason"])

    def test_cut_body_and_later_duplicates_have_distinct_reasons(self):
        with TemporaryDirectory() as temporary:
            first = {**source_item("evidence " * 500), "parent_id": "parent-1"}
            duplicate = {**first, "chunk_id": "chunk-2"}
            omitted = {**source_item(), "parent_id": "parent-2", "chunk_id": "chunk-3"}
            service = RagService(self.settings(temporary), FakeKnowledge([first, duplicate, omitted]))
            prepared = self.prepare(service)
        self.assertEqual(["body_truncated", "duplicate_parent", "budget_omitted"], [item["reason"] for item in prepared.context["selection"]])
        self.assertEqual(1, prepared.context["body_truncated"])
        self.assertEqual(1, prepared.context["budget_omitted"])
        self.assertEqual(1, prepared.context["deduplicated"])
        self.assertEqual(1, prepared.context["omitted"])

    def test_wrapper_too_large_omits_parent_once(self):
        with TemporaryDirectory() as temporary:
            first = {**source_item(), "parent_id": "parent-1", "filename": "verylong" * 200}
            duplicate = {**first, "chunk_id": "chunk-2"}
            prepared = self.prepare(RagService(self.settings(temporary), FakeKnowledge([first, duplicate])))
        self.assertTrue(prepared.refused)
        self.assertEqual(0, prepared.context["body_truncated"])
        self.assertEqual(1, prepared.context["budget_omitted"])
        self.assertEqual(1, prepared.context["deduplicated"])
        self.assertEqual(["budget_omitted"], prepared.context["truncation_reasons"])

    def test_empty_source_is_skipped_without_claiming_budget_truncation(self):
        with TemporaryDirectory() as temporary:
            first = source_item(" ")
            second = {**source_item(), "chunk_id": "chunk-2"}
            prepared = self.prepare(RagService(self.settings(temporary), FakeKnowledge([first, second])))
        self.assertFalse(prepared.context["truncated"])
        self.assertEqual(1, prepared.context["empty_content"])
        self.assertEqual(1, len(prepared.sources))
        self.assertEqual("chunk-2", prepared.sources[0]["chunk_id"])

    def test_source_separators_and_prompt_overhead_are_counted_with_explicit_scope(self):
        with TemporaryDirectory() as temporary:
            settings = replace(self.settings(temporary), rag_max_context_tokens=512)
            items = [{**source_item("电压 24V"), "chunk_id": f"chunk-{index}"} for index in range(3)]
            prepared = self.prepare(RagService(settings, FakeKnowledge(items)))
        source_content = prepared.messages[1]["content"].split("Sources:\n", 1)[1]
        self.assertEqual(estimate_tokens(source_content), prepared.context["estimated_tokens"])
        self.assertLessEqual(prepared.context["estimated_tokens"], 128)
        self.assertEqual(sum(estimate_tokens(message["content"]) for message in prepared.messages), prepared.context["prompt_estimated_tokens"])
        self.assertEqual(prepared.context["prompt_estimated_tokens"] + 64, prepared.context["estimated_total_with_output_reserve"])
        self.assertFalse(prepared.context["model_window_verified"])

    def test_zero_or_negative_explicit_budget_rejected(self):
        with TemporaryDirectory() as temporary:
            service = RagService(self.settings(temporary), FakeKnowledge([]))
            for context_budget, output_budget in ((0, 64), (-1, 64), (128, 0), (128, -1)):
                with self.subTest(context=context_budget, output=output_budget), self.assertRaisesRegex(ValueError, "positive"):
                    service.prepare("kb", "question", top_k=5, min_score=0, document_ids=[], page_start=None, page_end=None, kinds=[], section_path_prefix=[], max_context_tokens=context_budget, max_output_tokens=output_budget)


if __name__ == "__main__":
    unittest.main()
