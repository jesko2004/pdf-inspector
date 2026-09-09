import os
import unittest
from unittest.mock import patch

from backend.config import Settings


class ConfigTests(unittest.TestCase):
    def test_rapidocr_environment_options(self):
        environment = {
            "PDF_INSPECTOR_OCR_PROVIDER": "rapidocr",
            "PDF_INSPECTOR_OCR_DPI": "240",
            "PDF_INSPECTOR_OCR_MIN_CONFIDENCE": "0.65",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual("rapidocr", settings.ocr_provider)
        self.assertEqual(240, settings.ocr_dpi)
        self.assertEqual(0.65, settings.ocr_min_confidence)

    def test_command_configuration_remains_backward_compatible(self):
        environment = {
            "PDF_INSPECTOR_OCR_COMMAND_JSON": '["ocr-adapter", "{pdf}", "{pages}"]'
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual("command", settings.ocr_provider)
        self.assertEqual(("ocr-adapter", "{pdf}", "{pages}"), settings.ocr_command)

    def test_invalid_ocr_provider_is_rejected(self):
        with patch.dict(
            os.environ, {"PDF_INSPECTOR_OCR_PROVIDER": "unknown"}, clear=True
        ), self.assertRaisesRegex(ValueError, "OCR_PROVIDER"):
            Settings.from_env()

    def test_pgvector_and_embedding_environment_options(self):
        environment = {
            "PDF_INSPECTOR_VECTOR_STORE": "pgvector",
            "PDF_INSPECTOR_PGVECTOR_DSN": "postgresql://user:secret@db/example",
            "PDF_INSPECTOR_EMBEDDING_PROVIDER": "openai_compatible",
            "PDF_INSPECTOR_EMBEDDING_MODEL": "embed-v1",
            "PDF_INSPECTOR_EMBEDDING_DIMENSIONS": "1536",
            "PDF_INSPECTOR_EMBEDDING_BATCH_SIZE": "20",
            "PDF_INSPECTOR_EMBEDDING_BASE_URL": "http://model:8000/v1",
            "PDF_INSPECTOR_EMBEDDING_API_KEY": "private-key",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual("pgvector", settings.vector_store)
        self.assertEqual("openai_compatible", settings.embedding_provider)
        self.assertEqual(1536, settings.embedding_dimensions)
        self.assertEqual(20, settings.embedding_batch_size)
        self.assertNotIn("secret", repr(settings))
        self.assertNotIn("private-key", repr(settings))

    def test_pgvector_requires_a_dsn(self):
        with patch.dict(
            os.environ, {"PDF_INSPECTOR_VECTOR_STORE": "pgvector"}, clear=True
        ), self.assertRaisesRegex(ValueError, "PGVECTOR_DSN"):
            Settings.from_env()

    def test_openai_compatible_llm_and_rag_environment_options(self):
        environment = {
            "PDF_INSPECTOR_LLM_PROVIDER": "openai_compatible",
            "PDF_INSPECTOR_LLM_MODEL": "chat-model",
            "PDF_INSPECTOR_LLM_BASE_URL": "http://model:8000/v1",
            "PDF_INSPECTOR_LLM_API_KEY": "private-llm-key",
            "PDF_INSPECTOR_LLM_TIMEOUT_SECONDS": "90",
            "PDF_INSPECTOR_RAG_MAX_CONTEXT_TOKENS": "8192",
            "PDF_INSPECTOR_RAG_MAX_OUTPUT_TOKENS": "1200",
            "PDF_INSPECTOR_RAG_MIN_EVIDENCE_SCORE": "0.35",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual("openai_compatible", settings.llm_provider)
        self.assertEqual("chat-model", settings.llm_model)
        self.assertEqual(8192, settings.rag_max_context_tokens)
        self.assertEqual(1200, settings.rag_max_output_tokens)
        self.assertEqual(0.35, settings.rag_min_evidence_score)
        self.assertNotIn("private-llm-key", repr(settings))

    def test_openai_compatible_llm_requires_base_url(self):
        with patch.dict(
            os.environ,
            {"PDF_INSPECTOR_LLM_PROVIDER": "openai_compatible"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "LLM_BASE_URL"):
            Settings.from_env()


if __name__ == "__main__":
    unittest.main()
