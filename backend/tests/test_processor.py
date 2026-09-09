import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.processor import process_document
from backend.profiles import Profile
from backend.ocr import OcrPage


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


class FakeOcrProvider:
    name = "fake-ocr"

    def extract_pages(self, _pdf_path, pages):
        return [
            OcrPage(page=page, markdown="总额：88", confidence=0.98)
            for page in pages
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
        self.assertIn("emitted_chunks", result["chunk_quality"])

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

    def test_ocr_pages_are_merged_before_business_extraction(self):
        engine = FakeEngine()
        page_result = engine.extract_pages_markdown("")
        page_result.pages[1].markdown = ""
        page_result.pages_needing_ocr = [2]
        engine.extract_pages_markdown = lambda _path: page_result
        profile = Profile(
            id="simple",
            name="Simple",
            version=1,
            fields={
                "supplier": {"aliases": ["供应商"], "required": True},
                "total": {
                    "aliases": ["总额"],
                    "type": "decimal",
                    "required": True,
                },
            },
        )
        result = process_document(
            Path("quote.pdf"), profile, engine, ocr_provider=FakeOcrProvider()
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual("88", result["fields"]["total"]["value"])
        self.assertEqual([2], result["document"]["pages_ocr_completed"])
        self.assertEqual([], result["document"]["pages_needing_ocr"])
        self.assertEqual("ocr", result["document"]["pages"][1]["extraction_method"])

    def test_full_pipeline_outputs_fields_tables_and_rag_chunks(self):
        engine = FakeEngine()
        page_result = engine.extract_pages_markdown("")
        page_result.pages[0].markdown = "供应商：甲公司\n报价日期：2026-01-02\n总额：200"
        page_result.pages[1].markdown = ""
        page_result.pages_needing_ocr = [2]
        engine.extract_pages_markdown = lambda _path: page_result

        class TableOcrProvider:
            name = "table-ocr"

            def extract_pages(self, _pdf_path, _pages):
                return [
                    OcrPage(
                        page=2,
                        markdown=(
                            "## 商品明细\n\n"
                            "| 品名 | 数量 | 单位 | 单价 |\n"
                            "|---|---:|:---:|---:|\n"
                            "| 服务器 | 2 | PCS | ￥100 |"
                        ),
                        confidence=0.99,
                    )
                ]

        profile = Profile(
            id="quote",
            name="报价单",
            version=1,
            fields={
                "supplier": {"aliases": ["供应商"], "required": True},
                "date": {
                    "aliases": ["报价日期"],
                    "type": "date",
                    "required": True,
                },
                "total": {
                    "aliases": ["总额"],
                    "type": "decimal",
                    "required": True,
                },
            },
            tables={
                "line_items": {
                    "required": True,
                    "columns": {
                        "product": {"aliases": ["品名"], "required": True},
                        "quantity": {
                            "aliases": ["数量"],
                            "type": "decimal",
                            "required": True,
                        },
                        "unit": {"aliases": ["单位"], "type": "unit"},
                        "price": {
                            "aliases": ["单价"],
                            "type": "decimal",
                            "required": True,
                        },
                    },
                }
            },
        )
        result = process_document(
            Path("quote.pdf"), profile, engine, ocr_provider=TableOcrProvider()
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual("甲公司", result["fields"]["supplier"]["value"])
        row = result["tables"]["items"][0]["rows"][0]
        self.assertEqual(
            {"product": "服务器", "quantity": "2", "unit": "件", "price": "100"},
            row,
        )
        table_chunk = next(
            chunk for chunk in result["chunks"] if chunk["kind"] == "table"
        )
        self.assertEqual(2, table_chunk["page_start"])
        self.assertEqual(["商品明细"], table_chunk["section_path"])


if __name__ == "__main__":
    unittest.main()
