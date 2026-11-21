from __future__ import annotations

import unittest

from app.emoji import characters, emoji_results, is_emoji_query


class EmojiTests(unittest.TestCase):
    def found(self, text: str) -> list[str]:
        return [result.payload for result in emoji_results(text, 60)]

    def test_names_find_characters(self) -> None:
        self.assertIn("😀", self.found(":grinning face"))
        self.assertIn("🔥", self.found(":fire"))
        self.assertIn("€", self.found(":euro"))
        self.assertIn("°", self.found(":degree"))
        self.assertIn("→", self.found(":rightwards arrow"))
        self.assertEqual(self.found(":fire")[0], "🔥")

    def test_everyday_words(self) -> None:
        self.assertEqual(self.found(":lol")[0], "😂")
        self.assertEqual(self.found(":thumbsup")[0], "👍")
        self.assertIn("—", self.found(":dash"))
        self.assertEqual(self.found(":heart")[0], "❤")
        self.assertGreater(len(self.found(":heart")), 10)

    def test_word_forms_are_matched_when_little_is_found(self) -> None:
        smiles = self.found(":smile")
        self.assertEqual(smiles[0], "😊")
        self.assertIn("😃", smiles)
        self.assertIn("😂", self.found(":tears"))

    def test_query_rules(self) -> None:
        self.assertTrue(is_emoji_query("  :smile"))
        self.assertFalse(is_emoji_query("smile"))
        self.assertFalse(is_emoji_query("12:30"))
        self.assertEqual(self.found(":"), [])
        self.assertEqual(self.found(":a"), [])
        self.assertEqual(self.found(":zzqxw"), [])
        self.assertLessEqual(len(emoji_results(":face", 5)), 5)

    def test_result_row_and_table(self) -> None:
        result = emoji_results(":fire", 5)[0]
        self.assertEqual((result.kind, result.name), ("emoji", "🔥   fire"))
        self.assertGreater(len(characters()), 1500)
        self.assertIs(characters(), characters())


if __name__ == "__main__":
    unittest.main()
