import math
import random
import unittest
from statistics import NormalDist

from reliance_lab.model import (DEFAULTS, POLICIES, analyse, evaluate, joint_cells, logit, norm_cdf,
                                norm_inv, normalise, sigmoid, threshold_curve)


def random_params(rng: random.Random) -> dict:
    return {
        "human": rng.uniform(0.5, 0.99), "ai": rng.uniform(0.5, 0.99),
        "overlap": rng.uniform(-0.6, 1.0), "aiSignal": rng.uniform(0, 4),
        "humanSignal": rng.uniform(0, 4), "aiBias": rng.uniform(-2, 2),
        "humanBias": rng.uniform(-2, 2), "threshold": rng.uniform(0.5, 0.99),
        "deferRate": rng.random(),
    }


class NormalFunctionTests(unittest.TestCase):
    def test_norm_cdf_matches_the_standard_library(self):
        for x in [-9, -6.5, -3, -1, -0.2, 0, 0.4, 1.7, 3.3, 7.5, 40]:
            self.assertAlmostEqual(norm_cdf(x), 0.5 * math.erfc(-x / math.sqrt(2)), places=14)
        self.assertEqual(norm_cdf(math.inf), 1.0)
        self.assertEqual(norm_cdf(-math.inf), 0.0)
        self.assertTrue(math.isnan(norm_cdf(math.nan)))

    def test_norm_inv_matches_the_standard_library(self):
        for p in [1e-6, 0.001, 0.02, 0.2, 0.5, 0.77, 0.98, 0.9999]:
            self.assertAlmostEqual(norm_inv(p), NormalDist().inv_cdf(p), places=9)
        self.assertEqual(norm_inv(0), -math.inf)
        self.assertEqual(norm_inv(1), math.inf)


class ModelTests(unittest.TestCase):
    def test_defaults_give_the_documented_headline(self):
        a = analyse()
        self.assertAlmostEqual(a["ceiling"], 0.88896, places=4)
        self.assertAlmostEqual(a["policies"]["fixed"]["team"], 0.82, places=10)
        self.assertAlmostEqual(a["cells"]["p00"], 0.06842, places=4)

    def test_accuracy_and_errors_add_up_to_one(self):
        rng = random.Random(1)
        for _ in range(300):
            a = analyse(random_params(rng))
            for key in POLICIES:
                r = a["policies"][key]
                self.assertAlmostEqual(r["team"] + r["shared"] + r["overErrors"] + r["underErrors"], 1, places=12)
                self.assertAlmostEqual(r["rair"] + r["underRelianceRate"], 1, places=12)
                self.assertAlmostEqual(r["rsr"] + r["overRelianceRate"], 1, places=12)

    def test_a_fixed_deferral_rate_never_beats_the_better_solo(self):
        rng = random.Random(2)
        for _ in range(300):
            p = random_params(rng)
            r = evaluate(p, "fixed")
            self.assertLessEqual(r["team"], max(p["human"], p["ai"]) + 1e-12)
            self.assertGreaterEqual(r["team"], min(p["human"], p["ai"]) - 1e-12)

    def test_the_best_possible_rule_is_never_beaten(self):
        rng = random.Random(3)
        for _ in range(200):
            p = random_params(rng)
            a = analyse(p)
            for key in POLICIES:
                self.assertLessEqual(a["policies"][key]["team"], a["ceiling"] + 1e-12, key)
            for point in threshold_curve(p, 40):
                self.assertLessEqual(point["team"], a["ceiling"] + 1e-12)
            self.assertGreaterEqual(a["ceiling"], a["best"] - 1e-12)

    def test_whoever_is_surer_is_optimal_when_honest_and_independent(self):
        for human, ai, da, dh in [(0.7, 0.8, 1.5, 1.0), (0.9, 0.6, 0.5, 2.5), (0.75, 0.75, 3, 0.2)]:
            p = {"human": human, "ai": ai, "overlap": 0, "aiSignal": da, "humanSignal": dh,
                 "aiBias": 0, "humanBias": 0}
            a = analyse(p)
            self.assertAlmostEqual(a["policies"]["surer"]["team"], a["ceiling"], places=12)

    def test_overconfidence_breaks_whoever_is_surer(self):
        honest = analyse({"overlap": 0})
        biased = analyse({"overlap": 0, "aiBias": 1.5})
        self.assertLess(biased["policies"]["surer"]["team"], honest["policies"]["surer"]["team"] - 0.005)
        self.assertAlmostEqual(biased["ceiling"], honest["ceiling"], places=12)

    def test_no_confidence_signal_means_no_gain(self):
        for overlap in [-0.3, 0, 0.5]:
            a = analyse({"human": 0.7, "ai": 0.8, "overlap": overlap, "aiSignal": 0, "humanSignal": 0})
            self.assertAlmostEqual(a["ceiling"], 0.8, places=12)

    def test_threshold_rule_with_an_uninformative_ai(self):
        # With no signal every shown confidence equals sigmoid(logit(ai) + bias): all or nothing.
        r = evaluate({"ai": 0.8, "aiSignal": 0, "aiBias": 0, "threshold": 0.79}, "threshold")
        self.assertEqual(r["followRate"], 1.0)
        r = evaluate({"ai": 0.8, "aiSignal": 0, "aiBias": 0, "threshold": 0.81}, "threshold")
        self.assertEqual(r["followRate"], 0.0)

    def test_joint_cells_respect_the_marginals_and_clamp(self):
        c = joint_cells(0.7, 0.9, 0.3)
        self.assertAlmostEqual(c["p11"] + c["p10"], 0.7, places=12)
        self.assertAlmostEqual(c["p11"] + c["p01"], 0.9, places=12)
        self.assertAlmostEqual(c["rho"], 0.3, places=12)
        self.assertFalse(c["clamped"])
        c = joint_cells(0.7, 0.9, 1.0)
        self.assertTrue(c["clamped"])
        self.assertAlmostEqual(c["p11"], 0.7, places=12)
        self.assertAlmostEqual(c["p10"], 0.0, places=12)

    def test_identical_answers_mean_nothing_to_decide(self):
        a = analyse({"human": 0.8, "ai": 0.8, "overlap": 1})
        self.assertAlmostEqual(a["cells"]["p01"] + a["cells"]["p10"], 0, places=12)
        for key in POLICIES:
            self.assertAlmostEqual(a["policies"][key]["team"], 0.8, places=12)

    def test_normalise_clamps_and_rejects(self):
        p = normalise({"human": 2, "ai": 0.1, "deferRate": -1})
        self.assertEqual((p["human"], p["ai"], p["deferRate"]), (0.99, 0.5, 0.0))
        self.assertEqual(normalise(None), {k: float(v) for k, v in DEFAULTS.items()})
        for bad in [math.nan, math.inf, "0.7", True]:
            with self.assertRaises(ValueError):
                normalise({"human": bad})
        with self.assertRaises(ValueError):
            evaluate({}, "coin-toss")

    def test_closed_forms_match_a_simulation(self):
        rng = random.Random(4)
        p = normalise({"human": 0.72, "ai": 0.83, "overlap": 0.25, "aiSignal": 1.8, "humanSignal": 0.9,
                       "aiBias": 0.6, "humanBias": 0.3, "threshold": 0.85, "deferRate": 0.6})
        a = analyse(p)
        c = a["cells"]
        la, lh = logit(p["ai"]), logit(p["human"])
        log_odds = math.log(c["p01"] / c["p10"])
        right = {key: 0 for key in POLICIES}
        n = 120_000
        for _ in range(n):
            u = rng.random()
            if u < c["p11"]:
                h, ai = 1, 1
            elif u < c["p11"] + c["p10"]:
                h, ai = 1, 0
            elif u < c["p11"] + c["p10"] + c["p01"]:
                h, ai = 0, 1
            else:
                h, ai = 0, 0
            s = rng.gauss(p["aiSignal"] / 2 if ai else -p["aiSignal"] / 2, 1)
            t = rng.gauss(p["humanSignal"] / 2 if h else -p["humanSignal"] / 2, 1)
            shown_ai = sigmoid(la + p["aiBias"] + p["aiSignal"] * s)
            shown_h = sigmoid(lh + p["humanBias"] + p["humanSignal"] * t)
            follow = {
                "fixed": rng.random() < p["deferRate"],
                "threshold": shown_ai >= p["threshold"],
                "surer": shown_ai > shown_h,
                "optimal": log_odds + p["aiSignal"] * s - p["humanSignal"] * t > 0,
            }
            for key in POLICIES:
                final = h if h == ai else (ai if follow[key] else h)
                right[key] += final
        for key in POLICIES:
            self.assertAlmostEqual(right[key] / n, a["policies"][key]["team"], delta=0.006, msg=key)


if __name__ == "__main__":
    unittest.main()


class SweepTests(unittest.TestCase):
    def test_gain_grid_matches_single_evaluations(self):
        from reliance_lab.model import gain_grid
        g = gain_grid({"aiSignal": 2}, "surer", 9)
        self.assertEqual(len(g["values"]), 9)
        self.assertAlmostEqual(g["values"][-1], 0.99, places=12)
        self.assertEqual(g["gains"][2][5], evaluate({"aiSignal": 2, "human": g["values"][2], "ai": g["values"][5]}, "surer")["gain"])

    def test_sweep_summary(self):
        from reliance_lab.sweep import GRID, run_sweep, summarise, sweep_csv, sweep_report
        small = {"human": (0.7, 0.8), "ai": (0.7, 0.8), "aiSignal": (0.0, 2.0), "aiBias": (0.0, 1.0)}
        rows = run_sweep(small)
        self.assertEqual(len(rows), 16)
        summary = summarise(rows, grid=small)
        self.assertEqual(summary["rules"]["fixed"]["shareBeatsBoth"], 0)
        self.assertEqual(summary["rules"]["optimal"]["shareWorse"], 0)
        effects = {e["level"]: e["meanBestGain"] for e in summary["effects"]["aiSignal"]}
        self.assertGreater(effects[2.0], effects[0.0])
        self.assertIn("biasGap", summary["effects"])
        self.assertIn("Overconfidence gap", sweep_report(summary))
        self.assertEqual(len(sweep_csv(rows).strip().splitlines()), 17)
        self.assertEqual(len(run_sweep()), math.prod(len(v) for v in GRID.values()))
