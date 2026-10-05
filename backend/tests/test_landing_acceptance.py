import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.config import Settings
from backend.embeddings import HashEmbeddingProvider, EmbeddingError
from backend.knowledge_service import KnowledgeService
from backend.llm import LlmError, LlmResult
from backend.model_readiness import check_models
from backend.rag_service import RagService
from scripts.minimum_landing import ROOT, run, run_fingerprint


class ProbeLlm:
    text = json.dumps({"answerable": True, "claims": [{"text": "Supply voltage is 24 V.", "evidence": [{"chunk_id": "probe-source", "quote": "The controller supply voltage is 24 V."}]}]})

    def generate(self, messages, *, max_tokens):
        return LlmResult(self.text, {"completion_tokens": 30})

    def stream(self, messages, *, max_tokens):
        yield self.text[:10]
        yield self.text[10:]


class ReadinessTests(unittest.TestCase):
    def configured(self, root):
        return Settings(data_dir=Path(root), builtin_profile_dir=ROOT / "backend/profiles", embedding_provider="openai_compatible", embedding_model="real-embedding", embedding_base_url="http://localhost/v1", embedding_dimensions=8, llm_provider="openai_compatible", llm_model="real-chat", llm_base_url="http://localhost/v1")

    def test_missing_configuration_does_not_call_models(self):
        with TemporaryDirectory() as root, patch("backend.model_readiness.create_embedding_provider") as factory:
            result = check_models(Settings(data_dir=Path(root), builtin_profile_dir=Path(root)))
        self.assertFalse(result["ready"])
        self.assertEqual("configuration_required", result["status"])
        factory.assert_not_called()

    def test_batch_grounded_generation_and_stream_contracts(self):
        with TemporaryDirectory() as root:
            result = check_models(self.configured(root), embedding=HashEmbeddingProvider(dimensions=8), llm=ProbeLlm())
        self.assertTrue(result["ready"])
        self.assertEqual(3, len(result["checks"]))
        self.assertEqual(30, result["checks"][1]["usage"]["completion_tokens"])

    def test_zero_vectors_fail_contract(self):
        class ZeroEmbedding:
            def embed(self, _texts):
                return [[0.0] * 8] * 2
        with TemporaryDirectory() as root:
            result = check_models(self.configured(root), embedding=ZeroEmbedding(), llm=ProbeLlm())
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"][0]["passed"])

    def test_wrong_evidence_and_refusal_fail_answerable_probe(self):
        for text in ['{"answerable":false,"claims":[]}', ProbeLlm.text.replace("probe-source", "outside")]:
            with self.subTest(text=text), TemporaryDirectory() as root:
                llm = ProbeLlm()
                llm.text = text
                result = check_models(self.configured(root), embedding=HashEmbeddingProvider(dimensions=8), llm=llm)
                self.assertFalse(result["ready"])
                self.assertFalse(result["checks"][1]["passed"])

    def test_provider_errors_do_not_leak_echoed_credentials(self):
        class FailingEmbedding:
            def embed(self, _texts):
                raise EmbeddingError("HTTP 401: echoed PRIVATE_SECRET")
        with TemporaryDirectory() as root:
            result = check_models(replace(self.configured(root), embedding_api_key="PRIVATE_SECRET"), embedding=FailingEmbedding(), llm=ProbeLlm())
        self.assertNotIn("PRIVATE_SECRET", json.dumps(result))
        self.assertFalse(result["ready"])


class ResumeTests(unittest.TestCase):
    def dataset(self):
        dataset = json.loads((ROOT / "examples/minimum_landing_eval.json").read_text(encoding="utf-8"))
        dataset["documents"] = dataset["documents"][:1]
        dataset["cases"] = [dataset["cases"][0], dataset["cases"][6]]
        return dataset

    def settings(self, root):
        return Settings(data_dir=Path(root) / "work", builtin_profile_dir=ROOT / "backend/profiles")

    def test_successful_resume_has_zero_embedding_and_generation_calls(self):
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            output = Path(root) / "report.json"
            first = run(self.dataset(), settings, output)
            with patch.object(HashEmbeddingProvider, "embed", side_effect=AssertionError("paid call repeated")), patch.object(RagService, "answer", side_effect=AssertionError("generation repeated")):
                second = run(self.dataset(), settings, output, resume=True)
            self.assertEqual(first["answers"], second["answers"])
            self.assertEqual("completed", second["status"])

    def test_one_failure_is_retained_and_only_explicit_retry_calls_again(self):
        original = RagService.answer
        queries = []
        def flaky(service, prepared):
            queries.append(prepared.question)
            if "critical temperature" in prepared.question.lower():
                raise LlmError("provider echoed PRIVATE_SECRET")
            return original(service, prepared)
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            output = Path(root) / "report.json"
            with patch.object(RagService, "answer", autospec=True, side_effect=flaky):
                first = run(self.dataset(), settings, output)
            self.assertEqual(2, len(queries))
            self.assertEqual("incomplete", first["status"])
            self.assertEqual(1, first["answer_statuses"]["error"])
            self.assertNotIn("PRIVATE_SECRET", output.read_text(encoding="utf-8"))
            with patch.object(RagService, "answer", side_effect=AssertionError("implicit retry")):
                unchanged = run(self.dataset(), settings, output, resume=True)
            self.assertEqual("incomplete", unchanged["status"])
            with patch.object(RagService, "answer", autospec=True, side_effect=original) as retry:
                repaired = run(self.dataset(), settings, output, resume=True, retry_failed=True)
            self.assertEqual(1, retry.call_count)
            self.assertEqual("completed", repaired["status"])

    def test_model_or_question_change_rejects_stale_resume_before_calling(self):
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            dataset = self.dataset()
            output = Path(root) / "report.json"
            run(dataset, settings, output)
            for changed in [replace(settings, llm_model="other"), replace(settings, rag_max_context_tokens=2000)]:
                with patch.object(HashEmbeddingProvider, "embed", side_effect=AssertionError("model call")), self.assertRaisesRegex(ValueError, "changed"):
                    run(dataset, changed, output, resume=True)
            dataset["cases"][0]["query"] = "changed question"
            with self.assertRaisesRegex(ValueError, "changed"):
                run(dataset, settings, output, resume=True)

    def test_new_run_cannot_overwrite_existing_service_or_checkpoint(self):
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            settings.data_dir.mkdir()
            settings.database_path.touch()
            with self.assertRaisesRegex(ValueError, "fresh isolated"):
                run(self.dataset(), settings, Path(root) / "report.json")

    def test_api_key_rotation_does_not_invalidate_identical_model_outputs(self):
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            first = run_fingerprint(self.dataset(), replace(settings, llm_api_key="old"))
            second = run_fingerprint(self.dataset(), replace(settings, llm_api_key="new"))
        self.assertEqual(first, second)

    def test_retrying_failed_index_batches_recovers_document(self):
        original = HashEmbeddingProvider.embed
        failed = False
        def fail_once(provider, texts):
            nonlocal failed
            if not failed:
                failed = True
                raise EmbeddingError("temporary embedding failure")
            return original(provider, texts)
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            output = Path(root) / "report.json"
            with patch.object(HashEmbeddingProvider, "embed", autospec=True, side_effect=fail_once), self.assertRaises(EmbeddingError):
                run(self.dataset(), settings, output)
            self.assertEqual("incomplete", json.loads(output.read_text(encoding="utf-8"))["status"])
            repaired = run(self.dataset(), settings, output, resume=True, retry_failed=True)
            self.assertEqual("completed", repaired["status"])


if __name__ == "__main__":
    unittest.main()
