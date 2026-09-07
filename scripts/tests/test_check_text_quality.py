import unittest

from scripts.check_text_quality import analyze_text, evaluate


class TextQualityChecks(unittest.TestCase):
    def test_arabic_expectation_catches_cjk_substitution(self):
        report = analyze_text("錯誤文字" * 30)
        failures = evaluate(
            report,
            expected_scripts=["arabic"],
            forbidden_scripts=["han"],
            min_script_characters=20,
            max_replacement_characters=0,
        )
        self.assertTrue(any("arabic" in failure for failure in failures))
        self.assertTrue(any("forbidden script han" in failure for failure in failures))

    def test_valid_arabic_passes_script_gate(self):
        report = analyze_text("اللغة العربية نص صحيح " * 10)
        failures = evaluate(
            report,
            expected_scripts=["arabic"],
            forbidden_scripts=["han"],
            min_script_characters=20,
            max_replacement_characters=0,
        )
        self.assertEqual(failures, [])

    def test_bilingual_han_and_latin_are_both_allowed(self):
        report = analyze_text("中文表格 English form " * 10)
        failures = evaluate(
            report,
            expected_scripts=["han", "latin"],
            forbidden_scripts=[],
            min_script_characters=20,
            max_replacement_characters=None,
        )
        self.assertEqual(failures, [])

    def test_mojibake_and_control_characters_fail(self):
        report = analyze_text("bad Ãƒ text 锟 \x81")
        failures = evaluate(
            report,
            expected_scripts=[],
            forbidden_scripts=[],
            min_script_characters=1,
            max_replacement_characters=0,
        )
        self.assertTrue(any("C1 control count" in failure for failure in failures))
        self.assertTrue(any("mojibake markers" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
