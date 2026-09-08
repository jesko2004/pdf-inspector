import unittest
from decimal import Decimal

from pydantic import ValidationError

from backend.profiles import FieldRule, Profile, extract_fields, normalize_value


def quote_profile(**field_overrides) -> Profile:
    fields = {
        "supplier": {"aliases": ["供应商", "Supplier"], "required": True},
        "date": {
            "aliases": ["报价日期", "Quote Date"],
            "type": "date",
            "required": True,
        },
        "total": {
            "aliases": ["总额", "Total"],
            "type": "decimal",
            "required": True,
            "min_value": "0",
        },
    }
    fields.update(field_overrides)
    return Profile(id="test_quote", name="测试报价单", version=2, fields=fields)


class ProfileTests(unittest.TestCase):
    def test_extracts_typed_values_with_page_evidence(self):
        markdown = """<!-- Page 1 -->

| 供应商 | 示例科技有限公司 |
| 报价日期 | 2026年3月8日 |

<!-- Page 2 -->

总额：￥12,345.60元
"""
        result = extract_fields(markdown, quote_profile())

        self.assertEqual("ready", result["status"])
        self.assertEqual("示例科技有限公司", result["fields"]["supplier"]["value"])
        self.assertEqual(1, result["fields"]["supplier"]["page"])
        self.assertEqual("2026-03-08", result["fields"]["date"]["value"])
        self.assertEqual("12345.60", result["fields"]["total"]["value"])
        self.assertEqual(2, result["fields"]["total"]["page"])
        self.assertIn("￥12,345.60元", result["fields"]["total"]["source_text"])

    def test_missing_required_field_needs_review(self):
        result = extract_fields("<!-- Page 1 -->\n供应商：甲方", quote_profile())
        self.assertEqual("needs_review", result["status"])
        self.assertEqual(
            {"date", "total"}, {issue["field"] for issue in result["issues"]}
        )

    def test_conflicting_values_are_not_silently_chosen(self):
        markdown = """<!-- Page 1 -->
供应商：甲方
报价日期：2026-01-01
总额：10
<!-- Page 2 -->
总额：20
"""
        result = extract_fields(markdown, quote_profile())
        self.assertEqual("conflicting_values", result["fields"]["total"]["reason"])
        self.assertIsNone(result["fields"]["total"]["value"])
        self.assertEqual(2, len(result["fields"]["total"]["candidates"]))

    def test_page_and_bbox_scope_are_validated(self):
        with self.assertRaises(ValidationError):
            FieldRule(aliases=["总额"], bbox=(0, 0, 100, 100))
        rule = FieldRule(aliases=["总额"], pages=[1], bbox=(0, 0, 100, 100))
        self.assertEqual((0.0, 0.0, 100.0, 100.0), rule.bbox)

    def test_pattern_and_numeric_bounds(self):
        rule = FieldRule(aliases=["编号"], pattern=r"Q-\d{4}", type="text")
        self.assertEqual("Q-1234", normalize_value("Q-1234", rule))
        with self.assertRaisesRegex(ValueError, "pattern_mismatch"):
            normalize_value("1234", rule)
        decimal_rule = FieldRule(aliases=["数量"], type="decimal", min_value=Decimal(1))
        with self.assertRaisesRegex(ValueError, "below_minimum"):
            normalize_value("0", decimal_rule)

    def test_scoped_markdown_restricts_bbox_field(self):
        profile = quote_profile(
            total={
                "aliases": ["总额"],
                "type": "decimal",
                "required": True,
                "pages": [2],
                "bbox": [0, 0, 200, 100],
            }
        )
        full = "<!-- Page 1 -->\n供应商：甲方\n报价日期：2026-01-01\n总额：99"
        scoped = {"total": "<!-- Page 2 -->\n总额：10"}
        result = extract_fields(full, profile, scoped)
        self.assertEqual("10", result["fields"]["total"]["value"])
        self.assertEqual(2, result["fields"]["total"]["page"])
        self.assertEqual(
            [0.0, 0.0, 200.0, 100.0], result["fields"]["total"]["candidates"][0]["bbox"]
        )


if __name__ == "__main__":
    unittest.main()
