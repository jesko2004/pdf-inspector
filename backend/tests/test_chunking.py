import unittest

from backend.chunking import chunk_pages


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
        pages = [(1, "# 标题\n\n正文")]
        first = chunk_pages(pages, document_id="same")
        second = chunk_pages(pages, document_id="same")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
