"""Deterministic binomial-model statistics implemented with the standard library.

The tails are sums of binomial masses, not a normal approximation. Centered
recurrences avoid overflow and avoid underflow at the distribution's mode.
Very small tail values can still round to zero in double precision.
"""
from __future__ import annotations

from collections import Counter
import math

from .catalog import PILES, build_deck


class BinomialTails:
    """Inclusive lower/upper tails in O(n) time and memory, then O(1) per count."""

    def __init__(self, n: int, p: float):
        if type(n) is not int or n < 0:
            raise ValueError("n must be a nonnegative integer.")
        if not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("p must be finite and between 0 and 1.")
        self.n = n
        masses = [0.0] * (n + 1)
        if p == 0 or n == 0:
            masses[0] = 1.0
        elif p == 1:
            masses[n] = 1.0
        else:
            mode = min(n, math.floor((n + 1) * p))
            masses[mode] = 1.0
            for k in range(mode, 0, -1):
                masses[k - 1] = masses[k] * (k / (n - k + 1)) * ((1 - p) / p)
            for k in range(mode, n):
                masses[k + 1] = masses[k] * ((n - k) / (k + 1)) * (p / (1 - p))
            total = math.fsum(masses)
            masses = [mass / total for mass in masses]
        self.lower = [0.0] * (n + 1)
        self.upper = [0.0] * (n + 1)
        running = 0.0
        for k, mass in enumerate(masses):
            running += mass
            self.lower[k] = min(1.0, running)
        running = 0.0
        for k in range(n, -1, -1):
            running += masses[k]
            self.upper[k] = min(1.0, running)
        self.lower[-1] = self.upper[0] = 1.0

    def at(self, k: int) -> tuple[float, float, float]:
        if type(k) is not int or not 0 <= k <= self.n:
            raise ValueError("k must be an integer between 0 and n.")
        lo, hi = self.lower[k], self.upper[k]
        return lo, hi, min(1.0, 2 * min(lo, hi))


def binom_two_sided(n: int, k: int, p: float) -> tuple[float, float, float]:
    """Convenience entry point; reuse BinomialTails for multiple counts."""
    return BinomialTails(n, p).at(k)


def holm(pvals: list[float], alpha: float = 0.05) -> list[tuple[float, bool]]:
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be finite and between 0 and 1.")
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in pvals):
        raise ValueError("Every p-value must be finite and between 0 and 1.")
    adjusted = [1.0] * len(pvals)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(pvals)), key=pvals.__getitem__)):
        running = max(running, min(1.0, (len(pvals) - rank) * pvals[index]))
        adjusted[index] = running
    return [(p, p <= alpha) for p in adjusted]


def band(z: float) -> str:
    return "接近基线" if abs(z) < 1 else "普通偏离" if abs(z) < 2 else "极端候选"


def build_statistics(protocol: dict, receipt: dict, records: list[dict]) -> dict:
    """Analyze already validated records. This function never creates an RNG."""
    n = protocol["draws"]
    if type(n) is not int or n <= 0 or len(records) != n:
        raise ValueError("Statistics require exactly the planned positive number of records.")
    deck = build_deck()
    counts = Counter((row["pile"], row["card_id"]) for row in records)
    reversed_counts = Counter((row["pile"], row["card_id"]) for row in records if row["reversed"])
    # Only two card probabilities: 1/70 for a suit card, 1/110 for a major.
    tails = {size: BinomialTails(n, 1 / (5 * size)) for size in (14, 22)}
    result = {
        "schema_version": 1, "question": protocol["question"], "actual_n": n,
        "protocol": protocol, "receipt": receipt,
        "analysis": {
            "card_baseline": "Unconditional on pile count: n/70 for suit cards, n/110 for majors.",
            "tail_definition": "Inclusive binomial tails; min(1, 2*min(P(X<=k), P(X>=k))).",
            "multiplicity": "Holm separately within each pile, alpha=0.05; not one global 78-card family.",
            "family_sizes": [14, 14, 14, 14, 22],
            "numerics": "Centered binomial recurrences; floating-point arithmetic; tiny tails may round to zero.",
            "scope": "Descriptive statistics only; no authored meanings or automatic interpretation.",
        },
        "piles": [],
    }
    pile_sd = math.sqrt(n * 0.2 * 0.8)
    for key, label, element, suit in PILES:
        cards = deck[key]
        size = len(cards)
        p = 1 / (5 * size)
        expected = n * p
        sd = math.sqrt(n * p * (1 - p))
        rows = []
        for card in cards:
            k = counts[key, card["id"]]
            rev = reversed_counts[key, card["id"]]
            lo, hi, two = tails[size].at(k)
            z = (k - expected) / sd
            rows.append({
                "card_id": card["id"], "zh": card["zh"], "class": card["class"],
                "count": k, "upright": k - rev, "reversed": rev,
                "expected": expected, "delta": k - expected,
                "relative_delta": (k - expected) / expected, "z": z,
                "band": band(z), "p_lower": lo, "p_upper": hi, "p_two": two,
            })
        for row, (adjusted, flag) in zip(rows, holm([row["p_two"] for row in rows])):
            row["p_holm"], row["holm_flag"] = adjusted, flag
        rows.sort(key=lambda row: (-row["z"], row["card_id"]))
        total = sum(row["count"] for row in rows)
        result["piles"].append({
            "key": key, "label": label, "element": element, "suit": suit,
            "size": size, "count": total, "expected": n / 5, "sd": pile_sd,
            "delta": total - n / 5, "z": (total - n / 5) / pile_sd,
            "card_expected": expected, "card_sd": sd, "cards": rows,
            "highlights": [dict(row) for row in rows if row["band"] != "接近基线"],
        })
    return result
