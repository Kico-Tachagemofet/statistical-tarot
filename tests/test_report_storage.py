import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from statistical_tarot.report import write_page


class ReportStorageTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.temp_root = root / ".test-tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.out = Path(self.temp.name)
        self.stats = json.loads((root / "examples" / "demo-statistics.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.assertTrue(self.out.resolve().is_relative_to(self.temp_root.resolve()))
        self.temp.cleanup()

    def test_hardlinked_page_cannot_overwrite_raw(self):
        raw = self.out / "raw.ndjson"
        original = b'SYNTHETIC ORIGINAL RECORDS\n'
        raw.write_bytes(original)
        try:
            os.link(raw, self.out / "page.html")
        except OSError as exc:
            self.skipTest(f"Hard links are unavailable on this filesystem: {exc}")
        write_page(self.out, self.stats)
        self.assertEqual(raw.read_bytes(), original)
        self.assertIn("<!doctype html", (self.out / "page.html").read_text(encoding="utf-8").lower())

    def test_failed_replace_preserves_previous_page(self):
        prior = b'<!doctype html><title>PREVIOUS REPORT</title>'
        (self.out / "page.html").write_bytes(prior)
        with patch("os.replace", side_effect=OSError("synthetic replace failure")):
            with self.assertRaises(OSError):
                write_page(self.out, self.stats)
        self.assertEqual((self.out / "page.html").read_bytes(), prior)

    def test_existing_pending_report_is_not_overwritten(self):
        pending = self.out / ".page.html.pending"
        pending.write_bytes(b'OTHER WRITER PENDING')
        with self.assertRaises(FileExistsError):
            write_page(self.out, self.stats)
        self.assertEqual(pending.read_bytes(), b'OTHER WRITER PENDING')


if __name__ == "__main__":
    unittest.main()
