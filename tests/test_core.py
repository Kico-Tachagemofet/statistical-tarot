from collections import Counter
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from statistical_tarot.catalog import PILES, build_deck
from statistical_tarot.cli import main
from statistical_tarot.core import (MAX_DRAWS, RunError, analyze_run, draw_run,
    make_protocol, read_completed_run, save_json_new, sha256_file, validate_statistics)
from statistical_tarot.statistics import holm


class ArithmeticRNG:
    """Test double only: never uses an entropy source."""
    def __init__(self, interrupt_after=None):
        self.completed = 0
        self.pick = 0
        self.interrupt_after = interrupt_after

    def randrange(self, limit):
        if self.interrupt_after is not None and self.completed == self.interrupt_after:
            raise KeyboardInterrupt
        self.pick += 1
        return self.completed % limit

    def getrandbits(self, bits):
        assert bits == 1
        value = self.completed % 2
        self.completed += 1
        return value


def fixture(folder, n=20):
    """Create fixed synthetic records, with no draw_run call and no RNG."""
    folder.mkdir()
    protocol = make_protocol("SYNTHETIC TEST DATA", n, synthetic=True)
    save_json_new(folder / "protocol.json", protocol)
    deck = build_deck()
    rows = []
    for index in range(1, n + 1):
        key = PILES[(index - 1) % 5][0]
        card = deck[key][(index - 1) % len(deck[key])]
        rows.append({"draw": index, "pile": key, "card_id": card["id"],
                     "zh": card["zh"], "reversed": index % 2 == 0})
    (folder / "raw.ndjson").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    save_json_new(folder / "receipt.json", {
        "status": "completed", "completed_at": "2000-01-01T00:00:01+00:00",
        "draws": n, "requested_draws": n, "completed_draws": n, "synthetic": True,
        "raw_sha256": sha256_file(folder / "raw.ndjson"),
        "protocol_sha256": sha256_file(folder / "protocol.json"),
    })
    return rows


def refresh_receipt(folder):
    path = folder / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["raw_sha256"] = sha256_file(folder / "raw.ndjson")
    receipt["protocol_sha256"] = sha256_file(folder / "protocol.json")
    path.write_text(json.dumps(receipt), encoding="utf-8")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.base = Path(self.temp.name)

    def tearDown(self):
        # Verify the recursive temporary-directory cleanup stays inside the test root.
        self.assertTrue(self.base.resolve().is_relative_to(self.temp_root.resolve()))
        self.temp.cleanup()

    def test_catalog_is_complete_and_has_only_native_metadata(self):
        deck = build_deck()
        self.assertEqual([len(deck[key]) for key, *_ in PILES], [14, 14, 14, 14, 22])
        self.assertEqual(len({c["id"] for pile in deck.values() for c in pile}), 78)
        self.assertTrue(all(set(c) == {"id", "zh", "class"} for pile in deck.values() for c in pile))
        self.assertEqual(Counter(c["class"] for c in deck["fire"]), {"minor_pip": 10, "court": 4})

    def test_existing_empty_directory_is_never_reused(self):
        folder = self.base / "existing"
        folder.mkdir()
        with patch("statistical_tarot.core.SystemRandom", side_effect=AssertionError("must not start")):
            with self.assertRaisesRegex(RunError, "already exists"):
                draw_run("test", folder, 5)
        self.assertEqual(list(folder.iterdir()), [])

    def test_invalid_requests_are_rejected_before_directory_or_rng(self):
        for index, n in enumerate((0, -1, True, MAX_DRAWS + 1)):
            folder = self.base / str(index)
            with patch("statistical_tarot.core.SystemRandom", side_effect=AssertionError("must not start")):
                with self.assertRaises(RunError):
                    draw_run("test", folder, n)
            self.assertFalse(folder.exists())
        with self.assertRaises(RunError):
            draw_run("  ", self.base / "empty-question", 1)

    def test_protocol_and_raw_exist_before_fake_rng_and_complete(self):
        folder = self.base / "completed"
        def constructor():
            self.assertTrue((folder / "protocol.json").is_file())
            self.assertTrue((folder / "raw.ndjson").is_file())
            self.assertEqual(json.loads((folder / "protocol.json").read_text(encoding="utf-8"))["draws"], 10)
            return ArithmeticRNG()
        with patch("statistical_tarot.core.SystemRandom", side_effect=constructor) as rng:
            receipt = draw_run("synthetic fake RNG test", folder, 10)
        self.assertEqual(rng.call_count, 1)
        self.assertEqual(receipt["status"], "completed")
        _, _, rows = read_completed_run(folder)
        self.assertEqual(len(rows), 10)
        self.assertEqual(Counter(row["pile"] for row in rows), dict.fromkeys([p[0] for p in PILES], 2))

    def test_interruption_persists_partial_and_blocks_every_restart(self):
        folder = self.base / "partial"
        with patch("statistical_tarot.core.SystemRandom", return_value=ArithmeticRNG(interrupt_after=3)):
            with self.assertRaises(KeyboardInterrupt):
                draw_run("test interruption", folder, 10)
        receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["completed_draws"], 3)
        self.assertEqual(len((folder / "raw.ndjson").read_text(encoding="utf-8").splitlines()), 3)
        with self.assertRaisesRegex(RunError, "incomplete|interrupted"):
            analyze_run(folder)
        with patch("statistical_tarot.core.SystemRandom", side_effect=AssertionError("must not restart")):
            with self.assertRaises(RunError):
                draw_run("same run", folder, 10)

    def test_failure_after_complete_raw_still_marks_uncertain(self):
        folder = self.base / "receipt-failed"
        real_save = save_json_new
        failed = False
        def fail_once(path, value):
            nonlocal failed
            if path.name == "receipt.json" and value.get("status") == "completed" and not failed:
                failed = True
                raise OSError("synthetic receipt failure")
            return real_save(path, value)
        with patch("statistical_tarot.core.SystemRandom", return_value=ArithmeticRNG()), patch("statistical_tarot.core.save_json_new", side_effect=fail_once):
            with self.assertRaises(OSError):
                draw_run("test", folder, 3)
        self.assertEqual(json.loads((folder / "receipt.json").read_text(encoding="utf-8"))["status"], "partial")
        with self.assertRaises(RunError):
            read_completed_run(folder)

    def test_missing_receipt_refuses_uncertain_run(self):
        folder = self.base / "no-receipt"
        fixture(folder)
        (folder / "receipt.json").unlink()
        with self.assertRaisesRegex(RunError, "incomplete|uncertain"):
            analyze_run(folder)

    def test_hash_mismatch_refuses_changed_raw_or_protocol(self):
        for target in ("raw.ndjson", "protocol.json"):
            with self.subTest(file=target):
                folder = self.base / target
                fixture(folder)
                with (folder / target).open("a", encoding="utf-8") as stream:
                    stream.write(" ")
                with self.assertRaises(RunError):
                    analyze_run(folder)

    def test_record_validation_even_if_hash_is_updated(self):
        cases = {
            "sequence": lambda r: r[0].update(draw=2),
            "boolean-sequence": lambda r: r[0].update(draw=True),
            "orientation": lambda r: r[0].update(reversed=0),
            "unknown-card": lambda r: r[0].update(card_id="missing"),
            "wrong-pile": lambda r: r[0].update(pile="major"),
            "unknown-pile": lambda r: r[0].update(pile="other"),
            "wrong-name": lambda r: r[0].update(zh="wrong"),
            "missing-row": lambda r: r.pop(),
            "extra-row": lambda r: r.append(dict(r[-1], draw=len(r) + 1)),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                folder = self.base / name
                rows = fixture(folder)
                mutate(rows)
                (folder / "raw.ndjson").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                refresh_receipt(folder)
                with self.assertRaises(RunError):
                    analyze_run(folder)

    def test_catalog_mismatch_and_receipt_count_mismatch(self):
        for label in ("catalog", "receipt-count"):
            folder = self.base / label
            fixture(folder)
            if label == "catalog":
                path = folder / "protocol.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["catalog_sha256"] = "0" * 64
                path.write_text(json.dumps(value), encoding="utf-8")
                refresh_receipt(folder)
            else:
                path = folder / "receipt.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["completed_draws"] = True
                path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(RunError):
                analyze_run(folder)

    def test_analysis_is_deterministic_and_preserves_sources(self):
        folder = self.base / "analyze"
        fixture(folder, 100)
        before = {name: (folder / name).read_bytes() for name in ("protocol.json", "raw.ndjson", "receipt.json")}
        with patch("statistical_tarot.core.SystemRandom", side_effect=AssertionError("analysis cannot draw")):
            first = analyze_run(folder)
            second = analyze_run(folder)
        self.assertEqual(first, second)
        for name, data in before.items():
            self.assertEqual((folder / name).read_bytes(), data)
        validate_statistics(first)
        self.assertEqual(sum(pile["count"] for pile in first["piles"]), 100)
        self.assertEqual(sum(len(pile["cards"]) for pile in first["piles"]), 78)
        for pile in first["piles"]:
            self.assertAlmostEqual(pile["card_expected"], 100 / (5 * pile["size"]))
            reference = holm([row["p_two"] for row in pile["cards"]])
            for row, (p, flag) in zip(pile["cards"], reference):
                self.assertEqual((row["p_holm"], row["holm_flag"]), (p, flag))
            self.assertTrue(all(set(h) == set(pile["cards"][0]) for h in pile["highlights"]))

    def test_single_record_preserves_zero_frequency_cards_and_empty_piles(self):
        folder = self.base / "one"
        fixture(folder, 1)
        stats = analyze_run(folder)
        validate_statistics(stats)
        self.assertEqual(sum(row["count"] == 0 for pile in stats["piles"] for row in pile["cards"]), 77)
        self.assertEqual(sum(pile["count"] == 0 for pile in stats["piles"]), 4)

    def test_render_validator_rejects_nonfinite_metrics_and_missing_cards(self):
        folder = self.base / "validation"
        fixture(folder)
        stats = analyze_run(folder)
        invalid = copy.deepcopy(stats)
        invalid["piles"][0]["cards"][0]["z"] = float("nan")
        with self.assertRaises(RunError):
            validate_statistics(invalid)
        invalid = copy.deepcopy(stats)
        invalid["piles"][0]["cards"].pop()
        with self.assertRaises(RunError):
            validate_statistics(invalid)

    def test_render_validator_rejects_inconsistent_five_pile_model(self):
        folder = self.base / "model-validation"
        fixture(folder)
        stats = analyze_run(folder)
        for card_level, field, value in (
            (True, "expected", -1), (True, "expected", 99), (True, "z", -99),
            (False, "expected", 99), (False, "sd", -1), (False, "sd", 99),
            (False, "z", 99), (False, "card_expected", 99), (False, "card_sd", 99),
        ):
            with self.subTest(card_level=card_level, field=field, value=value):
                invalid = copy.deepcopy(stats)
                target = invalid["piles"][0]["cards"][0] if card_level else invalid["piles"][0]
                target[field] = value
                with self.assertRaises(RunError):
                    validate_statistics(invalid)
    def test_cli_analyze_and_render_never_construct_rng(self):
        folder = self.base / "cli"
        fixture(folder)
        calls = []
        def writer(out, stats):
            calls.append((out, stats["actual_n"]))
            (out / "page.html").write_text("<!doctype html><title>SYNTHETIC TEST</title>", encoding="utf-8")
        report = types.ModuleType("statistical_tarot.report")
        report.write_page = writer
        with patch.dict("sys.modules", {"statistical_tarot.report": report}), patch("statistical_tarot.core.SystemRandom", side_effect=AssertionError("no draw")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["analyze", "--input", str(folder)]), 0)
            destination = self.base / "rendered"
            self.assertEqual(main(["render", "--input", str(folder / "statistics.json"), "--out", str(destination)]), 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue((destination / "page.html").is_file())


if __name__ == "__main__":
    unittest.main()
