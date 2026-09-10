import unittest

from backend.profiles import Profile
from backend.table_data import extract_business_tables, table_to_csv


class TableDataTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(
            id="quote",
            name="报价单",
            version=1,
            fields={"supplier": {"aliases": ["供应商"]}},
            tables={
                "line_items": {
                    "required": True,
                    "columns": {
                        "product_name": {
                            "aliases": ["品名", "Item"],
                            "required": True,
                        },
                        "quantity": {
                            "aliases": ["数量", "Qty"],
                            "type": "decimal",
                            "required": True,
                        },
                        "unit": {"aliases": ["单位"], "type": "unit"},
                        "unit_price": {
                            "aliases": ["单价"],
                            "type": "decimal",
                            "required": True,
                        },
                    },
                }
            },
        )

    def test_maps_headers_and_normalizes_rows(self):
        markdown = """| 品名 | 数量 | 单位 | 单价 |
|---|---:|:---:|---:|
| 服务器 | 2 | PCS | ￥12,500.00 |
"""
        result = extract_business_tables([(3, markdown)], self.profile)
        self.assertEqual("ready", result["status"])
        table = result["items"][0]
        self.assertEqual("line_items", table["schema_id"])
        self.assertEqual("12500.00", table["rows"][0]["unit_price"])
        self.assertEqual("件", table["rows"][0]["unit"])
        self.assertEqual(3, table["row_sources"][0]["page"])
        self.assertIn("服务器,2,件,12500.00", table_to_csv(table))

    def test_usd_code_and_dollar_symbol_preserve_numeric_amount(self):
        for raw in ("USD $950.00", "USD 950.00", "$950.00"):
            with self.subTest(raw=raw):
                markdown = f"| Item | Qty | 单位 | 单价 |\n|---|---|---|---|\n| Support | 1 | PCS | {raw} |"
                result = extract_business_tables([(1, markdown)], self.profile)
                self.assertEqual("ready", result["status"])
                self.assertEqual("950.00", result["items"][0]["rows"][0]["unit_price"])
        invalid = "| Item | Qty | 单位 | 单价 |\n|---|---|---|---|\n| Support | 1 | PCS | USD $$950.00 |"
        self.assertEqual("needs_review", extract_business_tables([(1, invalid)], self.profile)["status"])

    def test_invalid_required_cell_and_missing_table_need_review(self):
        invalid = """| 品名 | 数量 | 单位 | 单价 |
|---|---|---|---|
| 服务器 | two | 台 | 100 |
"""
        result = extract_business_tables([(1, invalid)], self.profile)
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("invalid_decimal", result["items"][0]["issues"][0]["reason"])

        missing = extract_business_tables([(1, "没有表格")], self.profile)
        self.assertEqual("required_table_missing", missing["issues"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
