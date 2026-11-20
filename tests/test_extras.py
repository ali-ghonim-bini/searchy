from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Config
from app.extras import calculate, calculator_result, web_result


class CalculatorTests(unittest.TestCase):
    def test_arithmetic(self) -> None:
        cases = {
            "2+2": "4", "(1200 - 350) * 1.14": "969", "10 / 4": "2.5", "2^10": "1024",
            "7 % 3": "1", "-3 * -2": "6", "sqrt(16)": "4", "1/3": "0.3333333333",
            "round(pi, 2)": "3.14", "6 × 7": "42",
        }
        for expression, expected in cases.items():
            self.assertEqual(calculate(expression), expected, expression)

    def test_ordinary_searches_are_not_calculations(self) -> None:
        for text in ("2024", "report", "-5", "pi", "ext:pdf", "", "a-b", "notes 2+2"):
            self.assertIsNone(calculate(text), text)

    def test_unsafe_or_broken_input_is_rejected(self) -> None:
        for text in (
            "__import__('os').system('true')", "open('x')", "1/0", "2**99999", "9**9**9",
            "(1+", "'a'*3", "sqrt(-1)", "abs(x=1)", "1+" * 60 + "1",
        ):
            self.assertIsNone(calculate(text), text)

    def test_result_row(self) -> None:
        result = calculator_result(" 3 * 14 ")
        self.assertEqual((result.kind, result.name, result.payload), ("calc", "= 42", "42"))
        self.assertIsNone(calculator_result("holiday"))


class WebResultTests(unittest.TestCase):
    def test_query_is_escaped_into_the_url(self) -> None:
        result = web_result("c++ & rust", "https://duckduckgo.com/?q={query}")
        self.assertEqual(result.payload, "https://duckduckgo.com/?q=c%2B%2B+%26+rust")
        self.assertEqual((result.kind, result.detail), ("web", "duckduckgo.com"))

    def test_disabled_or_empty(self) -> None:
        self.assertIsNone(web_result("rust", ""))
        self.assertIsNone(web_result("  ", "https://duckduckgo.com/?q={query}"))

    def test_config_rejects_bad_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            for value in ("ftp://x/{query}", "https://example.com/search"):
                env_file.write_text(f"WEB_SEARCH_URL={value}\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    Config.load(env_file)
            env_file.write_text("WEB_SEARCH_URL=\n", encoding="utf-8")
            self.assertEqual(Config.load(env_file).web_search_url, "")


if __name__ == "__main__":
    unittest.main()
