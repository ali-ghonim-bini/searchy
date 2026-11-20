from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.preview import describe, format_size


class PreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def details(self, path: Path) -> dict[str, str]:
        return dict(describe(path).details)

    def test_sizes_use_decimal_units(self) -> None:
        self.assertEqual(
            [format_size(n) for n in (0, 999, 1000, 1_500_000, 2_000_000_000)],
            ["0 bytes", "999 bytes", "1.0 kB", "1.5 MB", "2.0 GB"],
        )

    def test_text_file_shows_its_first_lines(self) -> None:
        path = self.root / "notes.txt"
        path.write_text("\n".join(f"line {n} " + "x" * 200 for n in range(100)), encoding="utf-8")
        preview = describe(path)
        lines = preview.text.splitlines()
        self.assertEqual((len(lines), lines[0][:6], len(lines[0])), (20, "line 0", 80))
        self.assertEqual(self.details(path)["Type"], "text/plain")
        self.assertEqual(self.details(path)["Location"], str(self.root))

    def test_binary_and_empty_files_have_no_text(self) -> None:
        binary = self.root / "data.bin"
        binary.write_bytes(b"\x00\x01\x02" * 50)
        empty = self.root / "empty.txt"
        empty.touch()
        latin = self.root / "latin.txt"
        latin.write_bytes(b"caf\xe9 " * 20)
        self.assertEqual([describe(p).text for p in (binary, empty, latin)], [None, None, None])
        self.assertEqual(self.details(binary)["Size"], "150 bytes")

    def test_text_cut_inside_a_character_is_still_text(self) -> None:
        path = self.root / "accents.txt"
        path.write_bytes(("é" * 3000).encode("utf-8"))
        self.assertTrue(describe(path).text.startswith("ééé"))

    def test_folder_shows_its_item_count(self) -> None:
        folder = self.root / "docs"
        folder.mkdir()
        (folder / "a.txt").touch()
        self.assertEqual(self.details(folder)["Contains"], "1 item")
        self.assertEqual(self.details(folder)["Type"], "Folder")

    def test_image_is_marked_and_missing_file_is_reported(self) -> None:
        image = self.root / "photo.png"
        image.write_bytes(b"not really a png")
        self.assertTrue(describe(image).is_image)
        self.assertEqual(self.details(self.root / "gone.txt"), {"Status": "No longer available"})


if __name__ == "__main__":
    unittest.main()
