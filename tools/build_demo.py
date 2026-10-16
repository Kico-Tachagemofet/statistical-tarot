"""Build a visibly SYNTHETIC demo from arithmetic patterns, never from an RNG.

Run from the project root with: python tools/build_demo.py
The raw fixture directory is exclusive-create; reruns refuse to replace it.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from statistical_tarot.catalog import build_deck  # noqa: E402
from statistical_tarot.core import (analyze_run, make_protocol, save_json_new,  # noqa: E402
                                   sha256_file)


def main() -> None:
    folder = ROOT / "examples" / "synthetic-run"
    folder.mkdir(parents=True, exist_ok=False)
    question = "SYNTHETIC DEMO — deterministic test data, not a reading."
    protocol = make_protocol(question, 1000, synthetic=True)
    protocol["prepared_at"] = "2000-01-01T00:00:00+00:00"
    protocol["fixture_recipe"] = "Arithmetic schedule: 24 fire, 18 water, 20 air, 16 earth, 22 major per 100; repeat ten times."
    save_json_new(folder / "protocol.json", protocol)
    deck = build_deck()
    schedule = (["fire"] * 24 + ["water"] * 18 + ["air"] * 20 + ["earth"] * 16 + ["major"] * 22)
    offsets: Counter[str] = Counter()
    with (folder / "raw.ndjson").open("x", encoding="utf-8", newline="\n") as stream:
        for index in range(1, 1001):
            pile = schedule[(index - 1) % 100]
            offset = offsets[pile]
            # A deliberate, documented hotspot makes the sample UI legible.
            card_index = 0 if offset % 7 == 0 else offset % len(deck[pile])
            card = deck[pile][card_index]
            offsets[pile] += 1
            row = {"draw": index, "pile": pile, "card_id": card["id"],
                   "zh": card["zh"], "reversed": index % 3 == 0}
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    save_json_new(folder / "receipt.json", {
        "status": "completed", "completed_at": "2000-01-01T00:00:01+00:00",
        "draws": 1000, "requested_draws": 1000, "completed_draws": 1000,
        "synthetic": True, "raw_sha256": sha256_file(folder / "raw.ndjson"),
        "protocol_sha256": sha256_file(folder / "protocol.json"),
    })
    stats = analyze_run(folder)
    save_json_new(ROOT / "examples" / "demo-statistics.json", stats)
    print("Created SYNTHETIC fixtures. No sampling or entropy calls were made.")


if __name__ == "__main__":
    main()
