import unittest

from backend.chunking import ChunkQualityConfig, chunk_pages, chunk_pages_with_report


class ChunkingTests(unittest.TestCase):
    def test_preserves_page_section_and_table_integrity(self):
        pages = [
            (1, "# 产品手册\n\n简介内容。"),
            (
                2,
                "## 参数\n\n| 名称 | 数值 |\n|---|---|\n| 内存 | 32 GB |\n| 硬盘 | 1 TB |",
            ),
        ]
        chunks = chunk_pages(
            pages,
            document_id="doc-1",
            target_chars=40,
            max_chars=80,
            overlap_chars=10,
        )
        table = next(chunk for chunk in chunks if chunk["kind"] == "table")
        self.assertEqual(2, table["page_start"])
        self.assertEqual(["产品手册", "参数"], table["section_path"])
        self.assertIn("| 内存 | 32 GB |", table["markdown"])
        self.assertEqual(64, len(table["content_hash"]))

    def test_chunk_ids_are_deterministic(self):
        pages = [(1, "# 标题\n\n这是一段足够长且可以稳定生成知识库片段的正文。")]
        first = chunk_pages(pages, document_id="same")
        second = chunk_pages(pages, document_id="same")
        self.assertEqual(first, second)
        self.assertEqual(1, len(first))

    def test_removes_repeated_margins_and_reports_quality(self):
        labels = ["Alpha", "Beta", "Gamma"]
        pages = [
            (
                page,
                "Company Confidential\n\n"
                f"Department {labels[page - 1]}\n"
                f"Unique business content for {labels[page - 1]} with enough useful detail.\n"
                f"Revision {labels[page - 1]}\n\n"
                f"Page {page}",
            )
            for page in range(1, 4)
        ]
        chunks, report = chunk_pages_with_report(pages, document_id="margins")

        self.assertEqual(6, report["repeated_margin_lines_removed"])
        self.assertEqual(3, len(chunks))
        self.assertTrue(
            all("Company Confidential" not in chunk["markdown"] for chunk in chunks)
        )
        self.assertTrue(all("Page " not in chunk["markdown"] for chunk in chunks))

    def test_deduplicates_normalized_chunks_and_merges_page_citations(self):
        repeated = "The same sufficiently detailed policy paragraph appears twice."
        chunks, report = chunk_pages_with_report(
            [(1, repeated), (2, f"  {repeated}  ")], document_id="duplicates"
        )

        self.assertEqual(1, len(chunks))
        self.assertEqual([1, 2], chunks[0]["pages"])
        self.assertEqual(2, chunks[0]["source_occurrences"])
        self.assertEqual(1, report["duplicates_removed"])

    def test_filters_low_information_text_but_preserves_small_tables(self):
        pages = [
            (1, "---- !!!"),
            (2, "tiny"),
            (3, "| Key | Value |\n|---|---|\n| A | 1 |"),
        ]
        chunks, report = chunk_pages_with_report(
            pages,
            document_id="quality",
            quality_config=ChunkQualityConfig(min_text_chars=10),
        )

        self.assertEqual(["table"], [chunk["kind"] for chunk in chunks])
        self.assertEqual(2, report["low_quality_removed"])
        self.assertEqual(
            {"no_alphanumeric_content": 1, "too_short": 1},
            report["rejected_by_reason"],
        )

    def test_repeated_table_headers_are_not_removed_as_page_margins(self):
        pages = [
            (
                page,
                "| Item | Amount |\n"
                "|---|---:|\n"
                f"| Product {page} | {page}00 |\n"
                f"Notes for product number {page}\n"
                f"End marker {page}",
            )
            for page in range(1, 4)
        ]
        chunks, report = chunk_pages_with_report(pages, document_id="tables")

        table_chunks = [chunk for chunk in chunks if chunk["kind"] == "table"]
        self.assertEqual(3, len(table_chunks))
        self.assertTrue(
            all("| Item | Amount |" in chunk["markdown"] for chunk in table_chunks)
        )
        self.assertNotIn("| Item | Amount |", report["repeated_margins"])


if __name__ == "__main__":
    unittest.main()
