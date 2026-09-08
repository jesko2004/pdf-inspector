import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.processor import process_document
from backend.profiles import Profile


class FakeEngine:
    def extract_pages_markdown(self, _path):
        return SimpleNamespace(
            pages=[
                SimpleNamespace(
                    page=1,
                    markdown="供应商：甲公司\n报价日期：2026-01-02",
                    needs_ocr=False,
                ),
                SimpleNamespace(page=2, markdown="总额：100", needs_ocr=False),
            ],
            pages_needing_ocr=[],
            pages_with_tables=[2],
            pages_with_columns=[],
            is_complex=True,
        )

    def extract_text_in_regions(self, _path, page_regions):
        self.page_regions = page_regions
        return [
            SimpleNamespace(
                page=2,
                regions=[SimpleNamespace(text="总额：88", needs_ocr=False)],
            )
        ]


class ProcessorTests(unittest.TestCase):
    def test_combines_page_markers_and_region_scope(self):
        profile = Profile(
            id="quote",
            name="报价",
            version=1,
            fields={
                "supplier": {"aliases": ["供应商"], "required": True},
                "date": {"aliases": ["报价日期"], "type": "date", "required": True},
                "total": {
                    "aliases": ["总额"],
                    "type": "decimal",
                    "required": True,
                    "pages": [2],
                    "bbox": [0, 0, 200, 100],
                },
            },
        )
        engine = FakeEngine()
        result = process_document(Path("quote.pdf"), profile, engine)
        self.assertEqual("ready", result["status"])
        self.assertEqual("88", result["fields"]["total"]["value"])
        self.assertEqual(2, result["fields"]["total"]["page"])
        self.assertIn("<!-- Page 2 -->", result["markdown"])
        self.assertEqual([(2, [[0.0, 0.0, 200.0, 100.0]])], engine.page_regions)
        self.assertEqual([2], result["document"]["pages_with_tables"])

    def test_ocr_pages_force_review(self):
        engine = FakeEngine()
        page_result = engine.extract_pages_markdown("")
        page_result.pages_needing_ocr = [2]
        engine.extract_pages_markdown = lambda _path: page_result
        profile = Profile(
            id="simple",
            name="Simple",
            version=1,
            fields={"supplier": {"aliases": ["供应商"], "required": True}},
        )
        result = process_document(Path("quote.pdf"), profile, engine)
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("ocr_required", result["document"]["issues"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
