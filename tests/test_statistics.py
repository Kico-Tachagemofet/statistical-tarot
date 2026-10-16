import math
import unittest

from statistical_tarot.statistics import BinomialTails, band, binom_two_sided, holm


def integer_reference(n, denominator):
    """Independent exact integer masses for p=1/denominator."""
    weights = [math.comb(n, k) * (denominator - 1) ** (n - k) for k in range(n + 1)]
    total = denominator ** n
    assert sum(weights) == total
    return weights, total


def original_loggamma_reference(n, k, p):
    """Numerical definition used by the predecessor: inclusive sums of PMFs."""
    def pmf(i):
        return math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                        + i * math.log(p) + (n - i) * math.log(1 - p))
    lo = sum(pmf(i) for i in range(k + 1))
    hi = sum(pmf(i) for i in range(k, n + 1))
    return lo, hi, min(1.0, 2 * min(lo, hi))


class StatisticsTests(unittest.TestCase):
    def test_integer_reference_including_endpoints(self):
        for denominator in (2, 5, 70, 110):
            n = 16
            weights, total = integer_reference(n, denominator)
            table = BinomialTails(n, 1 / denominator)
            for k in range(n + 1):
                lo, hi = sum(weights[:k + 1]) / total, sum(weights[k:]) / total
                expected = lo, hi, min(1.0, 2 * min(lo, hi))
                with self.subTest(p=1 / denominator, k=k):
                    for actual, target in zip(table.at(k), expected):
                        self.assertTrue(math.isclose(actual, target, rel_tol=3e-14, abs_tol=1e-15))

    def test_inclusive_tails_share_observed_mass(self):
        lo, hi, two = binom_two_sided(4, 0, 0.5)
        self.assertEqual((lo, hi, two), (1 / 16, 1, 1 / 8))
        table = BinomialTails(4, 0.5)
        self.assertEqual(table.at(2), (11 / 16, 11 / 16, 1.0))

    def test_matches_original_1000_draw_definition(self):
        for p in (1 / 70, 1 / 110):
            table = BinomialTails(1000, p)
            for k in (0, 1, 5, 9, 14, 20, 35, 50):
                for actual, reference in zip(table.at(k), original_loggamma_reference(1000, k, p)):
                    self.assertTrue(math.isclose(actual, reference, rel_tol=2e-11, abs_tol=2e-12))

    def test_large_n_avoids_zero_at_distribution_center(self):
        for p in (1 / 70, 1 / 110):
            table = BinomialTails(100_000, p)
            lo, hi, two = table.at(round(100_000 * p))
            self.assertTrue(0.45 < lo < 0.55 and 0.45 < hi < 0.55)
            self.assertGreater(two, 0.9)
            self.assertEqual(table.at(0)[1], 1)
            self.assertEqual(table.at(100_000)[0], 1)

    def test_degenerate_and_invalid_parameters(self):
        self.assertEqual(binom_two_sided(0, 0, 0.4), (1, 1, 1))
        self.assertEqual(binom_two_sided(5, 0, 0), (1, 1, 1))
        self.assertEqual(binom_two_sided(5, 1, 0), (1, 0, 0))
        self.assertEqual(binom_two_sided(5, 4, 1), (0, 1, 0))
        self.assertEqual(binom_two_sided(5, 5, 1), (1, 1, 1))
        for n, p in ((-1, .2), (True, .2), (3, -.1), (3, float("nan"))):
            with self.assertRaises(ValueError):
                BinomialTails(n, p)
        with self.assertRaises(ValueError):
            BinomialTails(3, .2).at(True)

    def test_holm_known_example_ties_zero_and_one(self):
        actual = holm([.01, .04, .03])
        for (value, flag), expected in zip(actual, (.03, .06, .06)):
            self.assertAlmostEqual(value, expected)
            self.assertEqual(flag, expected <= .05)
        self.assertEqual(holm([0, .01, .01, 1]), [(0, True), (.03, True), (.03, True), (1, False)])
        self.assertEqual(holm([]), [])
        for values in ([float("nan")], [-1], [1.01]):
            with self.assertRaises(ValueError):
                holm(values)

    def test_display_boundaries_are_not_significance_tests(self):
        self.assertEqual(band(0.999), "接近基线")
        self.assertEqual(band(-1), "普通偏离")
        self.assertEqual(band(1.999), "普通偏离")
        self.assertEqual(band(-2), "极端候选")


if __name__ == "__main__":
    unittest.main()
