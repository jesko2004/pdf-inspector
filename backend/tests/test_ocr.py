import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.ocr import CommandOcrProvider


class OcrTests(unittest.TestCase):
    def test_command_provider_substitutes_pages_and_reads_json(self):
        payload = json.dumps(
            {"pages": [{"page": 2, "markdown": "OCR 文本", "confidence": 0.97}]},
            ensure_ascii=False,
        )
        script = "import sys; sys.stdout.buffer.write(sys.argv[1].encode('utf-8'))"
        provider = CommandOcrProvider(
            (sys.executable, "-c", script, payload, "{pdf}", "{pages}")
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.pdf"
            path.write_bytes(b"%PDF-test")
            result = provider.extract_pages(path, [2])
        self.assertEqual(2, result[0].page)
        self.assertEqual("OCR 文本", result[0].markdown)
        self.assertEqual(0.97, result[0].confidence)


if __name__ == "__main__":
    unittest.main()
