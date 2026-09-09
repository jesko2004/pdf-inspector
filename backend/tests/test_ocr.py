import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.ocr import CommandOcrProvider, RapidOcrProvider


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

    def test_rapidocr_renders_only_requested_pages_and_orders_lines(self):
        class FakePixmap:
            def __init__(self, page_index):
                self.page_index = page_index

            def tobytes(self, image_format):
                self.image_format = image_format
                return f"page-{self.page_index}".encode()

        class FakePage:
            def __init__(self, page_index):
                self.page_index = page_index

            def get_pixmap(self, *, dpi, alpha):
                self.render_options = (dpi, alpha)
                return FakePixmap(self.page_index)

        class FakeDocument:
            page_count = 3

            def __init__(self):
                self.loaded = []
                self.closed = False

            def load_page(self, page_index):
                self.loaded.append(page_index)
                return FakePage(page_index)

            def close(self):
                self.closed = True

        class FakeEngine:
            def __init__(self):
                self.calls = []

            def __call__(self, image, *, text_score):
                self.calls.append((image, text_score))
                return SimpleNamespace(
                    boxes=[
                        [[10, 50], [50, 50], [50, 60], [10, 60]],
                        [[10, 10], [50, 10], [50, 20], [10, 20]],
                        [[10, 80], [50, 80], [50, 90], [10, 90]],
                    ],
                    txts=("second line", "first line", "discarded"),
                    scores=(0.8, 0.9, 0.2),
                )

        document = FakeDocument()
        engine = FakeEngine()
        provider = RapidOcrProvider(
            dpi=240,
            min_confidence=0.5,
            engine=engine,
            document_opener=lambda _path: document,
        )
        result = provider.extract_pages(Path("sample.pdf"), [3, 2, 2])

        self.assertEqual([1, 2], document.loaded)
        self.assertTrue(document.closed)
        self.assertEqual([2, 3], [page.page for page in result])
        self.assertEqual("first line\n\nsecond line", result[0].markdown)
        self.assertAlmostEqual(0.85, result[0].confidence)
        self.assertEqual((b"page-1", 0.5), engine.calls[0])

    def test_rapidocr_rejects_pages_outside_document(self):
        document = SimpleNamespace(page_count=1, close=lambda: None)
        provider = RapidOcrProvider(
            engine=lambda _image, **_options: None,
            document_opener=lambda _path: document,
        )
        with self.assertRaisesRegex(ValueError, "exceed"):
            provider.extract_pages(Path("sample.pdf"), [2])

    @unittest.skipUnless(
        importlib.util.find_spec("rapidocr") and importlib.util.find_spec("pymupdf"),
        "optional OCR dependencies are not installed",
    )
    def test_rapidocr_recognizes_a_real_image_only_pdf(self):
        import pymupdf

        with TemporaryDirectory() as temporary:
            source = pymupdf.open()
            source_page = source.new_page(width=600, height=240)
            source_page.insert_text(
                (45, 125), "INVOICE TOTAL 123.45", fontsize=34, color=(0, 0, 0)
            )
            raster = source_page.get_pixmap(dpi=200, alpha=False).tobytes("png")
            source.close()

            scanned = pymupdf.open()
            scanned_page = scanned.new_page(width=600, height=240)
            scanned_page.insert_image(scanned_page.rect, stream=raster)
            path = Path(temporary) / "scanned.pdf"
            scanned.save(path)
            scanned.close()

            result = RapidOcrProvider(dpi=200, min_confidence=0.3).extract_pages(
                path, [1]
            )

        self.assertEqual(1, len(result))
        self.assertIn("INVOICE", result[0].markdown.upper())
        self.assertIn("123.45", result[0].markdown)
        self.assertGreater(result[0].confidence or 0, 0.3)


if __name__ == "__main__":
    unittest.main()
