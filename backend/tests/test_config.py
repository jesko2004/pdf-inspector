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
        ):
            with self.assertRaisesRegex(ValueError, "OCR_PROVIDER"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
