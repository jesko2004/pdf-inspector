import json
import sqlite3
import unittest
from dataclasses import replace
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient

from backend.answer_validation import REFUSAL
from backend.app import create_app
from backend.config import Settings
from backend.grounded_answer import GroundedAnswer, validate_grounded_answer
from backend.knowledge_store import KnowledgeStore
from backend.llm import LlmError, LlmResult, OpenAICompatibleLlmProvider
from backend.rag_service import RagService
from backend.tests import test_rag_service as fixtures
from backend.tests import test_api as api_fixtures


def contract(quote="evidence", chunk_id="chunk-1"):
    return json.dumps({"answerable": True, "claims": [{"text": "Supported claim", "evidence": [{"chunk_id": chunk_id, "quote": quote}]}]})


class Provider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def generate(self, messages, *, max_tokens):
        self.calls += 1
        return LlmResult(self.text, {})

    def stream(self, messages, *, max_tokens):
        self.calls += 1
        yield self.text[:10]
        yield self.text[10:]


class GroundedAnswerTests(unittest.TestCase):
    def test_unique_reformatted_line_breaks_are_restored_and_audited(self):
        body = "2028/03-2028/07\nExample Tool (Automation)"
        source = {"chunk_id": "chunk-1", "text": body,
                  "citation": {"filename": "profile.pdf", "pages": [1]}}
        model_quote = body.replace("\n", " ")
        result = validate_grounded_answer(contract(model_quote), [source], restore_line_breaks=True)
        self.assertEqual(body, result["claims"][0]["evidence"][0]["quote"])
        self.assertEqual("exact_match", result["validation"]["evidence_quotes"])
        self.assertEqual([{"chunk_id": "chunk-1", "model_quote": model_quote, "source_quote": body}],
                         result["validation"]["evidence_line_break_restorations"])
        self.assertEqual(body, source["text"])

    def test_line_break_restoration_rejects_changed_words_and_ambiguous_spans(self):
        cases = [
            ("Supply\n24 V", "Supply 25 V"),
            ("Supply\n24 V", "Supply24 V"),
            ("Supply24 V", "Supply 24 V"),
            ("Supply\n24 V", "supply 24 V"),
            ("Supply\n24 V", "Supply ２４ V"),
            ("Supply\nnot\n24 V", "Supply 24 V"),
            ("Supply\n24 V; Supply\r\n24 V", "Supply 24 V"),
            ("A\nA\nA", "A A"),
            ("Supply\n" + " " * 4000 + "24 V", "Supply 24 V"),
            ("Supply  24 V", "Supply 24 V"),
        ]
        for body, quote in cases:
            with self.subTest(body=body, quote=quote), self.assertRaises(LlmError):
                validate_grounded_answer(contract(quote), [{
                    "chunk_id": "chunk-1", "text": body,
                    "citation": {"filename": "manual.pdf", "pages": [1]},
                }], restore_line_breaks=True)
        with self.assertRaises(LlmError):
            validate_grounded_answer(contract("Supply 24 V", "outside"), [{
                "chunk_id": "chunk-1", "text": "Supply\n24 V",
                "citation": {"filename": "manual.pdf", "pages": [1]},
            }], restore_line_breaks=True)

    def test_line_break_restoration_agrees_in_normal_and_buffered_stream_answers(self):
        body = "Supply\n24 V"
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract("Supply 24 V"), [fixtures.source_item(body)])
            result = service.answer(prepared)
            events = list(service.stream(prepared))
        self.assertEqual(body, result["claims"][0]["evidence"][0]["quote"])
        self.assertEqual(result["claims"], events[-1]["data"]["claims"])
        self.assertEqual(result["validation"], events[-1]["data"]["validation"])
        self.assertEqual(["metadata", "token", "done"], [item["event"] for item in events])

    def test_multiline_evidence_keeps_line_breaks_or_quotes_lines_separately(self):
        body = "2028/03-2028/07\nExample Tool (Automation)"
        source = {"chunk_id": "chunk-1", "text": body,
                  "citation": {"filename": "profile.pdf", "pages": [1]}}
        result = validate_grounded_answer(contract(body), [source])
        self.assertEqual(body, result["claims"][0]["evidence"][0]["quote"])
        payload = json.loads(contract())
        payload["claims"][0]["evidence"] = [
            {"chunk_id": "chunk-1", "quote": line} for line in body.splitlines()
        ]
        result = validate_grounded_answer(json.dumps(payload), [source])
        self.assertEqual(body.splitlines(), [item["quote"] for item in result["claims"][0]["evidence"]])
        with self.assertRaises(LlmError):
            validate_grounded_answer(contract(body.replace("\n", " ")), [source])

    def test_duplicate_claims_keep_first_evidence_and_audit_later_copies(self):
        source = {"chunk_id": "chunk-1", "text": "Supply 24 V; frequency 50 Hz",
                  "citation": {"chunk_id": "chunk-1", "filename": "manual.pdf", "pages": [1]}}
        payload = json.loads(contract("Supply 24 V"))
        duplicate = json.loads(contract("frequency 50 Hz"))["claims"][0]
        payload["claims"].append(duplicate)
        result = validate_grounded_answer(json.dumps(payload), [source])
        self.assertEqual(1, len(result["claims"]))
        self.assertEqual("Supply 24 V", result["claims"][0]["evidence"][0]["quote"])
        self.assertEqual([duplicate], result["validation"]["duplicate_claims_omitted"])
        self.assertEqual(1, result["answer"].count("Supported claim"))
        payload["claims"][1]["evidence"][0]["quote"] = "invented"
        with self.assertRaises(LlmError):
            validate_grounded_answer(json.dumps(payload), [source])

    def test_table_evidence_adds_exact_local_identity_and_intro(self):
        body = ('Unit: GBP\n\nTable columns: Model, Price. Rows: '
                'Model [column_1]=Alpha; Price [column_2]=190 | '
                'Model [column_1]=Beta; Price [column_2]=210')
        source = {"chunk_id": "chunk-1", "text": body,
                  "citation": {"filename": "manual.pdf", "pages": [4]}}
        result = validate_grounded_answer(contract("Price [column_2]=210"), [source])
        quotes = [x["quote"] for x in result["claims"][0]["evidence"]]
        self.assertEqual(["Price [column_2]=210", "Model [column_1]=Beta", "Unit: GBP"], quotes)
        self.assertTrue(all(quote in body for quote in quotes))
        self.assertEqual(2, result["validation"]["evidence_context_entries_added"])
        self.assertEqual("model_asserted_not_independently_checked", result["validation"]["semantic_support"])
        with self.assertRaises(LlmError):
            validate_grounded_answer(contract("Price [column_2]=211"), [source])

    def test_table_context_never_selects_ambiguous_or_cross_row_identity(self):
        body = ('Unit: GBP\n\nTable columns: Model, Price. Rows: '
                'Model [column_1]=Alpha; Price [column_2]=210 | '
                'Model [column_1]=Beta; Price [column_2]=210')
        source = {"chunk_id": "chunk-1", "text": body,
                  "citation": {"filename": "manual.pdf", "pages": [4]}}
        for quote in ["Price [column_2]=210", "Price [column_2]=210 | Model [column_1]=Beta"]:
            result = validate_grounded_answer(contract(quote), [source])
            self.assertEqual(1, len(result["claims"][0]["evidence"]))

    def test_structured_provider_constrains_normal_and_stream_requests(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=Path(root), llm_provider="openai_compatible",
                                llm_base_url="http://localhost/v1", rag_answer_format="grounded_json")
            service = RagService(settings, fixtures.FakeKnowledge([]))
            provider = service._provider()
            for stream in (False, True):
                payload = json.loads(provider._request([], 100, stream=stream).data)
                self.assertEqual(GroundedAnswer.model_json_schema(), payload["response_format"]["json_schema"]["schema"])
                self.assertTrue(payload["response_format"]["json_schema"]["strict"])
            service.settings = replace(settings, rag_answer_format="text")
            self.assertNotIn("response_format", json.loads(service._provider()._request([], 100, stream=False).data))

    def service(self, root, text, items=None, **overrides):
        provider = Provider(text)
        settings = Settings(data_dir=Path(root), builtin_profile_dir=Path(root), llm_provider="openai_compatible", **overrides)
        service = RagService(settings, fixtures.FakeKnowledge(items if items is not None else [fixtures.source_item()]), llm_factory=lambda *_args: provider)
        prepared = service.prepare("kb", "question", top_k=5, min_score=0.2, document_ids=[], page_start=None, page_end=None, kinds=[], section_path_prefix=[])
        return service, prepared, provider

    def test_valid_contract_renders_citations_and_keeps_only_used_sources(self):
        with TemporaryDirectory() as root:
            other = fixtures.source_item("other")
            other["chunk_id"] = "chunk-2"
            service, prepared, provider = self.service(root, contract(), [fixtures.source_item(), other])
            result = service.answer(prepared)
        self.assertEqual("Supported claim [manual.pdf p.2]", result["answer"])
        self.assertEqual("completed", result["status"])
        self.assertEqual("exact_match", result["validation"]["evidence_quotes"])
        self.assertEqual(["chunk-1"], [item["chunk_id"] for item in result["citations"]])
        self.assertEqual(1, provider.calls)

    def test_refusal_contract_and_stream_agree(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, '{"answerable":false,"claims":[]}')
            answer = service.answer(prepared)
            events = list(service.stream(prepared))
        self.assertTrue(answer["refused"])
        self.assertEqual(REFUSAL, answer["answer"])
        self.assertEqual([], answer["citations"])
        self.assertEqual(answer["answer"], events[-1]["data"]["answer"])
        self.assertEqual("refused", events[-1]["data"]["status"])

    def test_valid_stream_does_not_expose_raw_json(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract())
            events = list(service.stream(prepared))
        self.assertEqual(["metadata", "token", "done"], [event["event"] for event in events])
        self.assertTrue(events[0]["data"]["buffered_until_validated"])
        self.assertEqual("Supported claim [manual.pdf p.2]", events[1]["data"]["text"])

    def test_unknown_source_and_invented_quote_fail_without_retry(self):
        for text in [contract(chunk_id="outside"), contract(quote="invented")]:
            with self.subTest(text=text), TemporaryDirectory() as root:
                service, prepared, provider = self.service(root, text)
                with self.assertRaises(LlmError):
                    service.answer(prepared)
                self.assertEqual(1, provider.calls)

    def test_truncated_parent_text_cannot_be_used_as_evidence(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract("TAIL_SECRET"), [fixtures.source_item("evidence " * 500 + "TAIL_SECRET")], rag_max_context_tokens=128)
            self.assertTrue(prepared.context["truncated"])
            self.assertNotIn("TAIL_SECRET", prepared.sources[0]["text"])
            with self.assertRaises(LlmError):
                service.answer(prepared)

    def test_invalid_stream_emits_no_answer_token_or_done(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract("fabricated"))
            stream = iter(service.stream(prepared))
            self.assertEqual("metadata", next(stream)["event"])
            with self.assertRaises(LlmError):
                next(stream)

    def test_contract_rejects_malformed_ambiguous_and_conflicting_values(self):
        bad = ["```json\n{}\n```", '{"answerable":true,"claims":[]}', '{"answerable":"false","claims":[]}', '{"answerable":false,"answerable":true,"claims":[]}', '{"answerable":false,"claims":[],"extra":1}', '{"answerable":NaN,"claims":[]}', contract(" ")]
        payload = json.loads(contract())
        payload["answerable"] = False
        bad.append(json.dumps(payload))
        for text in bad:
            with self.subTest(text=text), self.assertRaises(LlmError):
                validate_grounded_answer(text, [])

    def test_source_html_is_decoded_and_search_results_not_mutated(self):
        item = fixtures.source_item("A&B < C")
        before = json.dumps(item, sort_keys=True)
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract("A&B < C"), [item])
            result = service.answer(prepared)
        self.assertFalse(result["refused"])
        self.assertEqual(before, json.dumps(item, sort_keys=True))

    def test_extractive_and_legacy_text_require_review(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, "excerpt [manual.pdf p.2]", rag_answer_format="text")
            self.assertEqual("needs_review", service.answer(prepared)["status"])
            service.settings = replace(service.settings, llm_provider="extractive")
            result = service.answer(prepared)
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("evidence_preview", result["validation"]["answer_mode"])

    def test_non_contiguous_pages_render_without_inventing_middle_pages(self):
        item = fixtures.source_item()
        item["citation"]["pages"] = [2, 4]
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, contract(), [item])
            result = service.answer(prepared)
        self.assertEqual("Supported claim [manual.pdf p.2] [manual.pdf p.4]", result["answer"])

    def test_validation_persists_and_rerecording_preserves_feedback(self):
        with TemporaryDirectory() as root:
            store = KnowledgeStore(Path(root) / "knowledge.sqlite")
            kb = store.create_knowledge_base(name="test", description="", embedding_provider="hash", embedding_model="hash-v1", embedding_dimensions=256)
            service, prepared, _ = self.service(root, contract())
            answer = service.answer(prepared)
            answer["knowledge_base_id"] = kb["id"]
            store.record_answer(answer)
            feedback = store.create_feedback(kb["id"], {"answer_id": answer["answer_id"], "helpful": True})
            store.record_answer(answer)
            reopened = KnowledgeStore(store.database_path)
            self.assertEqual(feedback["id"], reopened.get_feedback(feedback["id"])["id"])
            with closing(sqlite3.connect(store.database_path)) as connection:
                row = connection.execute("SELECT status, validation_json, claims_json FROM rag_answers").fetchone()
            self.assertEqual("completed", row[0])
            self.assertEqual("exact_match", json.loads(row[1])["evidence_quotes"])
            self.assertEqual("evidence", json.loads(row[2])[0]["evidence"][0]["quote"])

    def test_transport_rejects_partial_error_or_length_limited_streams(self):
        for lines in [
            [b'data: {"choices":[{"delta":{"content":"partial"}}]}'],
            [b'data: {"error":{"message":"failed"}}', b'data: [DONE]'],
            [b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}', b'data: [DONE]'],
            [b'data: []'],
        ]:
            with self.subTest(lines=lines):
                provider = OpenAICompatibleLlmProvider(base_url="http://localhost/v1", api_key=None, model="test", stream_transport=lambda *_: lines)
                with self.assertRaises(LlmError):
                    list(provider.stream([], max_tokens=20))

    def test_transport_accepts_stop_marker_without_done(self):
        provider = OpenAICompatibleLlmProvider(base_url="http://localhost/v1", api_key=None, model="test", stream_transport=lambda *_: [b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'])
        self.assertEqual(["ok"], list(provider.stream([], max_tokens=20)))

    def test_truncated_non_stream_generation_is_rejected(self):
        provider = OpenAICompatibleLlmProvider(base_url="http://localhost/v1", api_key=None, model="test", transport=lambda *_: json.dumps({"choices": [{"message": {"content": contract()}, "finish_reason": "length"}]}).encode())
        with self.assertRaises(LlmError):
            provider.generate([], max_tokens=20)

    def test_literal_document_references_are_not_treated_as_extractive_claims(self):
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, "See appendix [other.pdf p.9]")
            service.settings = replace(service.settings, llm_provider="extractive")
            result = service.answer(prepared)
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("not_applicable", result["validation"]["citation_identity"])

    def test_offline_excerpt_only_returns_its_first_source_citation(self):
        second = fixtures.source_item("unrelated source")
        second["chunk_id"] = "chunk-2"
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, "evidence", [fixtures.source_item(), second])
            service.settings = replace(service.settings, llm_provider="extractive")
            answer = service.answer(prepared)
        self.assertEqual(2, len(prepared.citations))
        self.assertEqual(["chunk-1"], [item["chunk_id"] for item in answer["citations"]])

    def test_model_cannot_insert_its_own_filename_page_citation(self):
        payload = json.loads(contract())
        payload["claims"][0]["text"] = "Claim [invented.pdf p.8]"
        with TemporaryDirectory() as root:
            service, prepared, _ = self.service(root, json.dumps(payload))
            with self.assertRaises(LlmError):
                service.answer(prepared)

    def test_http_validates_before_persistence_in_normal_and_stream_modes(self):
        with TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), builtin_profile_dir=api_fixtures.BUILTIN_PROFILES, llm_provider="openai_compatible")
            provider = Provider("invalid JSON")
            app = create_app(settings, processor=api_fixtures.processor, start_workers=False, llm_factory=lambda *_: provider)
            with TestClient(app) as client:
                task = client.post("/v1/tasks", data={"profile_id": "manual_query"}, files={"file": ("manual.pdf", b"%PDF-1.7\ntest", "application/pdf")}).json()
                app.state.service.run_pending(task["id"])
                kb = client.post("/v1/knowledge-bases", json={"name": "Grounded contract"}).json()
                base = f'/v1/knowledge-bases/{kb["id"]}'
                document = client.post(base + "/documents", json={"task_id": task["id"]}).json()
                app.state.knowledge.run_pending(document["id"])
                request = {"question": "测试供应商", "retrieval_mode": "bm25"}
                self.assertEqual(502, client.post(base + "/ask", json=request).status_code)
                failed_stream = client.post(base + "/ask", json={**request, "stream": True})
                self.assertIn("event: error", failed_stream.text)
                self.assertNotIn("event: token", failed_stream.text)
                self.assertNotIn("event: done", failed_stream.text)
                with closing(sqlite3.connect(settings.knowledge_database_path)) as connection:
                    self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM rag_answers").fetchone()[0])
                hit = client.post(base + "/search", json={"query": "测试供应商", "retrieval_mode": "bm25"}).json()["items"][0]
                provider.text = contract("测试供应商", hit["chunk_id"])
                normal = client.post(base + "/ask", json=request)
                self.assertEqual(200, normal.status_code)
                streamed = client.post(base + "/ask", json={**request, "stream": True})
                self.assertIn("event: done", streamed.text)
                with closing(sqlite3.connect(settings.knowledge_database_path)) as connection:
                    rows = connection.execute("SELECT status, validation_json, claims_json FROM rag_answers").fetchall()
                self.assertEqual(2, len(rows))
                self.assertTrue(all(row[0] == "completed" and json.loads(row[1])["evidence_quotes"] == "exact_match" and json.loads(row[2])[0]["evidence"][0]["quote"] == "测试供应商" for row in rows))


if __name__ == "__main__":
    unittest.main()
