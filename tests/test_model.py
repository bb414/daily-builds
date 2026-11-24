import contextlib
import copy
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from statistics import NormalDist

from rangefinder import model as M
from rangefinder.__main__ import main as cli


def one_driver(dist, low, high, sign=1):
    return {"format": M.FORMAT, "version": 1, "title": "t", "outputName": "x", "unit": "", "unitPosition": "prefix",
            "threshold": None, "terms": [{"name": "a", "sign": sign, "drivers": [
                {"name": "d", "dist": dist, "low": low, "high": high, "unit": ""}]}]}


class TemplateTests(unittest.TestCase):
    def test_templates_are_valid_and_distinct(self):
        self.assertGreaterEqual(len(M.TEMPLATES), 3)
        keys = [t["key"] for t in M.TEMPLATES]
        self.assertEqual(len(keys), len(set(keys)))
        for t in M.TEMPLATES:
            self.assertEqual(M.validate_model(t), [], t["key"])
            self.assertTrue(t["about"] and t["thresholdLabel"])

    def test_templates_use_each_driver_once(self):
        for t in M.TEMPLATES:
            names = [d["name"] for _, _, d in M.drivers_of(t)]
            self.assertEqual(len(names), len(set(names)), t["key"])


class DistributionTests(unittest.TestCase):
    def check_range(self, dist, low, high, scale=1):
        values, _ = M.simulate(one_driver(dist, low, high), 20000, 3)
        srt = sorted(values)
        if dist == "uniform":
            self.assertAlmostEqual(srt[0], low, delta=(high - low) * 0.001)
            self.assertAlmostEqual(srt[-1], high, delta=(high - low) * 0.001)
            self.assertAlmostEqual(M.percentile(srt, 0.5), (low + high) / 2, delta=(high - low) * 0.002)
            return
        # A 90% range: about 5% of samples below low and 5% above high.
        self.assertAlmostEqual(M.percentile(srt, 0.05), low / scale, delta=abs(high - low) / scale * 0.002)
        self.assertAlmostEqual(M.percentile(srt, 0.95), high / scale, delta=abs(high - low) / scale * 0.002)

    def test_each_kind_of_range_hits_its_90_percent_interval(self):
        self.check_range("lognormal", 10, 1000)
        self.check_range("normal", -50, 150)
        self.check_range("share", 5, 25, scale=100)
        self.check_range("uniform", 2, 4)

    def test_fixed_and_quantiles(self):
        values, _ = M.simulate(one_driver("fixed", 7, 7), 2000, 1)
        self.assertEqual(set(values), {7.0})
        d = {"dist": "lognormal", "low": 10, "high": 1000}
        self.assertAlmostEqual(M.quantile(d, 0), 100)
        self.assertAlmostEqual(M.quantile(d, 1), 100 * math.exp(math.log(10) * M.Z90 / M.Z95))
        self.assertAlmostEqual(M.midpoint({"dist": "share", "low": 10, "high": 30}), 0.2)
        self.assertAlmostEqual(M.quantile({"dist": "share", "low": 10, "high": 90}, 0), 0.5)

    def test_inverse_normal(self):
        for p in (1e-9, 0.01, 0.02425, 0.3, 0.5, 0.9, 0.99, 1 - 1e-9):
            self.assertAlmostEqual(M.inv_norm(p), NormalDist().inv_cdf(p), delta=1e-7)
        self.assertAlmostEqual(M.Z95, NormalDist().inv_cdf(0.95), places=12)
        self.assertAlmostEqual(M.Z90, NormalDist().inv_cdf(0.90), places=12)

    def test_latin_hypercube_strata(self):
        # Each of n equal slices of probability gets exactly one sample.
        _, cols = M.simulate(one_driver("uniform", 0, 1), 1000, 5)
        self.assertEqual(sorted(math.floor(x * 1000) for x in cols[0]), list(range(1000)))

    def test_reproducible_and_seed_dependent(self):
        t = M.TEMPLATES[0]
        self.assertEqual(M.simulate(t, 2000, 4), M.simulate(t, 2000, 4))
        self.assertNotEqual(M.simulate(t, 2000, 4)[0], M.simulate(t, 2000, 5)[0])


class AnalysisTests(unittest.TestCase):
    def test_estimate_is_sum_of_signed_products(self):
        t = M.TEMPLATES[1]
        values, cols = M.simulate(t, 1000, 2)
        k = 17
        c = [col[k] for col in cols]
        expect = c[0] * c[1] * c[2] - c[3] - c[4] * c[5]
        self.assertAlmostEqual(values[k], expect, places=6)

    def test_percentiles_and_summary(self):
        self.assertEqual(M.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(M.percentile([1, 2, 3, 4], 1), 4)
        self.assertEqual(M.percentile([5], 0.3), 5)
        r = M.analyse(M.TEMPLATES[0])
        self.assertTrue(r["p5"] <= r["p10"] <= r["p25"] <= r["p50"] <= r["p75"] <= r["p90"] <= r["p95"])
        self.assertEqual(r["n"], M.DEFAULT_SAMPLES)
        # Skewed products: plugging in midpoints overstates the median.
        self.assertGreater(r["atMidpoints"], r["p50"] * 1.5)

    def test_variance_shares_match_a_brute_force_check(self):
        # For a product of independent drivers, Var(E[V|x_i]) / Var(V) can be checked by binning x_i.
        t = M.TEMPLATES[0]
        r = M.analyse(t, 40000, 9)
        values, cols = M.simulate(t, 40000, 9)
        var = M.variance(values)
        i = r["tornado"][0]
        pairs = sorted(zip(cols[i], values))
        bins = 200
        size = len(pairs) // bins
        cond = [M.mean([v for _, v in pairs[b * size:(b + 1) * size]]) for b in range(bins)]
        brute = M.variance(cond) / var
        self.assertAlmostEqual(r["drivers"][i]["varShare"], brute, delta=0.03)
        self.assertGreater(r["interaction"], 0.05)

    def test_purely_additive_model_has_no_interaction(self):
        m = one_driver("normal", 0, 10)
        m["terms"].append({"name": "b", "sign": -1, "drivers": [{"name": "e", "dist": "uniform", "low": 0, "high": 5, "unit": ""}]})
        r = M.analyse(m, 20000, 1)
        self.assertAlmostEqual(sum(d["varShare"] for d in r["drivers"]), 1.0, delta=0.02)
        self.assertLess(r["interaction"], 0.02)

    def test_tornado(self):
        r = M.analyse(M.TEMPLATES[1])
        swings = [r["drivers"][i]["swing"] for i in r["tornado"]]
        self.assertEqual(swings, sorted(swings, reverse=True))
        cost = next(d for d in r["drivers"] if d["name"].startswith("Licence"))
        self.assertGreater(cost["lowOut"], cost["highOut"])  # a higher cost lowers the estimate

    def test_threshold(self):
        m = copy.deepcopy(M.TEMPLATES[2])
        m["threshold"] = -1e12
        self.assertEqual(M.analyse(m)["probAbove"], 1.0)
        m["threshold"] = None
        self.assertIsNone(M.analyse(m)["probAbove"])

    def test_invalid_model_raises(self):
        with self.assertRaises(ValueError):
            M.analyse(one_driver("lognormal", 0, 10))


class ValidationTests(unittest.TestCase):
    def problems(self, **changes):
        m = copy.deepcopy(M.TEMPLATES[0])
        d = m["terms"][0]["drivers"][0]
        for k, v in changes.items():
            d[k] = v
        return M.validate_model(m)

    def test_driver_rules(self):
        self.assertIn("low value must be below", self.problems(low=5, high=5)[0])
        self.assertIn("above zero", self.problems(low=-1, high=5)[0])
        self.assertIn("between 0 and 100", self.problems(dist="share", low=0, high=50)[0])
        self.assertIn("between 0 and 100", self.problems(dist="share", low=10, high=100)[0])
        self.assertIn("needs numbers", self.problems(low=None)[0])
        self.assertIn("needs a name", self.problems(name="  ")[0])
        self.assertIn("unknown kind", self.problems(dist="beta")[0])
        self.assertEqual(self.problems(dist="fixed", low=3, high=None), [])
        self.assertEqual(self.problems(dist="normal", low=-5, high=5), [])

    def test_model_rules(self):
        self.assertEqual(M.validate_model(None), ["This is not a Range finder model."])
        self.assertIn("format", M.validate_model({"terms": []})[0])
        m = copy.deepcopy(M.TEMPLATES[0])
        m["terms"] = []
        self.assertIn("at least one term", M.validate_model(m)[0])
        m = copy.deepcopy(M.TEMPLATES[0])
        m["terms"][0]["drivers"] = []
        self.assertIn("at least one driver", M.validate_model(m)[0])
        m = copy.deepcopy(M.TEMPLATES[0])
        m["terms"][0]["sign"] = True
        self.assertIn("added (+1)", M.validate_model(m)[0])
        for key, value, text in (("threshold", "x", "threshold"), ("samples", 50, "Samples"),
                                 ("seed", -1, "seed"), ("unit", "x" * 13, "12 characters"),
                                 ("unitPosition", "middle", "prefix or suffix"), ("title", 3, "title")):
            m = copy.deepcopy(M.TEMPLATES[0])
            m[key] = value
            self.assertIn(text, M.validate_model(m)[0], key)

    def test_size_limits(self):
        m = copy.deepcopy(M.TEMPLATES[0])
        d = m["terms"][0]["drivers"][0]
        m["terms"] = [{"name": "t%d" % i, "sign": 1, "drivers": [dict(d, name="d%d%d" % (i, j)) for j in range(4)]}
                      for i in range(8)]
        self.assertEqual(M.validate_model(m), ["The estimate can have at most 30 drivers."])


class FormatTests(unittest.TestCase):
    def test_numbers(self):
        cases = {0: "0", 1: "1", 12.345: "12.3", 999.4: "999", 999.5: "1k", 1234: "1.23k", 12345: "12.3k",
                 999499: "999k", 999500: "1m", 1234567: "1.23m", 2.5e9: "2.5bn", -45100: "-45.1k",
                 0.1234: "0.123", 0.004567: "0.00457", 1e-9: "0", float("nan"): "n/a", 1.125: "1.13"}
        for x, s in cases.items():
            self.assertEqual(M.format_number(x), s, x)

    def test_values_and_drivers(self):
        self.assertEqual(M.format_value(-59200, "£", "prefix"), "-£59.2k")
        self.assertEqual(M.format_value(12500, "tonnes", "suffix"), "12.5k tonnes")
        self.assertEqual(M.format_value(5, "", "prefix"), "5")
        self.assertEqual(M.format_driver(0.123, {"dist": "share"}), "12.3%")
        self.assertEqual(M.format_driver(4.5, {"dist": "lognormal", "unit": "£"}), "£4.5")
        self.assertEqual(M.format_driver(1500, {"dist": "lognormal", "unit": "bikes"}), "1.5k bikes")


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli(list(argv))
        return code, buf.getvalue()

    def test_template_run_and_csv(self):
        code, out = self.run_cli("template")
        self.assertEqual(code, 0)
        self.assertIn("meal-kits", out)
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "m.json")
            self.assertEqual(self.run_cli("template", "bike-share", "-o", path)[0], 0)
            code, out = self.run_cli("run", path, "--samples", "2000", "--csv", str(Path(d) / "s.csv"))
            self.assertEqual(code, 0)
            self.assertIn("most likely between", out)
            import csv
            with open(Path(d) / "s.csv", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 2001)
            self.assertEqual(len(rows[0]), 8)
            self.assertEqual(rows[0][1], "Rides per bike per day")

    def test_errors_are_clean(self):
        code, out = self.run_cli("run", "missing.json")
        self.assertEqual(code, 2)
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps(one_driver("lognormal", 5, 1)))
            code, out = self.run_cli("run", str(bad))
            self.assertEqual(code, 2)
            self.assertIn("low value must be below", out)
            self.assertEqual(self.run_cli("template", "nope")[0], 2)


if __name__ == "__main__":
    unittest.main()
