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


class ValueOfInformationTests(unittest.TestCase):
    def test_properties(self):
        for t in M.TEMPLATES:
            r = M.analyse(t)
            v = r["voi"]
            self.assertEqual(v["decision"], "go" if r["mean"] >= t["threshold"] else "hold")
            expected_wrong = (1 - r["probAbove"]) if v["decision"] == "go" else r["probAbove"]
            self.assertAlmostEqual(v["wrongChance"], expected_wrong)
            for x in v["drivers"]:
                self.assertGreaterEqual(x["evppi"], 0)
                self.assertLessEqual(x["evppi"], v["evpi"] * 1.02 + 1e-9)
                self.assertTrue(0 <= x["flip"] <= 1)
            evppis = [v["drivers"][i]["evppi"] for i in v["order"]]
            self.assertEqual(evppis, sorted(evppis, reverse=True))
            for i, d in enumerate(r["drivers"]):
                if d["dist"] == "fixed":
                    self.assertEqual(v["drivers"][i]["evppi"], 0)
                    self.assertEqual(v["drivers"][i]["flip"], 0)

    def test_evpi_matches_its_definition(self):
        t = M.TEMPLATES[1]
        r = M.analyse(t)
        values, _ = M.simulate(t)
        thr = t["threshold"]
        direct = M.mean([max(v - thr, 0) for v in values]) - max(M.mean(values) - thr, 0)
        self.assertAlmostEqual(r["voi"]["evpi"], direct, delta=1e-6 * abs(direct))

    def test_evppi_matches_a_brute_force_check(self):
        # Bin the samples by one driver and use the bin averages as E[V | driver].
        t = M.TEMPLATES[0]
        r = M.analyse(t, 40000, 3)
        values, cols = M.simulate(t, 40000, 3)
        i = r["voi"]["order"][0]
        thr = t["threshold"]
        pairs = sorted(zip(cols[i], values))
        bins = 400
        size = len(pairs) // bins
        cond = [M.mean([v for _, v in pairs[b * size:(b + 1) * size]]) for b in range(bins)]
        brute = M.mean([max(c - thr, 0) for c in cond]) - max(M.mean(values) - thr, 0)
        self.assertAlmostEqual(r["voi"]["drivers"][i]["evppi"], brute, delta=abs(brute) * 0.1)

    def test_no_decision_no_value(self):
        m = copy.deepcopy(M.TEMPLATES[0])
        m["threshold"] = 1
        v = M.analyse(m)["voi"]
        self.assertEqual(v["decision"], "go")
        self.assertEqual(v["evpi"], 0)
        self.assertTrue(all(x["evppi"] == 0 and x["flip"] == 0 for x in v["drivers"]))
        m["threshold"] = None
        self.assertIsNone(M.analyse(m)["voi"])


class AuditRegressionTests(unittest.TestCase):
    def test_flip_chances_use_the_same_baseline_as_the_call(self):
        # Regression: the call used the sample mean but the flips and EVPPI used f(means). With a
        # threshold between the two, the flips were measured against the opposite call.
        for t in M.TEMPLATES:
            m = copy.deepcopy(t)
            r = M.analyse(m)
            base = M.evaluate(m, [d["mean"] for d in r["drivers"]])
            m["threshold"] = (r["mean"] + base) / 2
            r = M.analyse(m)
            v = r["voi"]
            _, cols = M.simulate(m)
            go = r["mean"] >= m["threshold"]
            self.assertEqual(v["decision"], "go" if go else "hold")
            for i, d in enumerate(r["drivers"]):
                conds = [r["mean"] + d["slope"] * (x - d["mean"]) for x in cols[i]]
                flips = sum(1 for c in conds if (c >= m["threshold"]) != go) / len(conds)
                self.assertAlmostEqual(v["drivers"][i]["flip"], flips, msg=t["key"])

    def test_all_fixed_model(self):
        m = one_driver("fixed", 7, 7)
        m["threshold"] = 5
        r = M.analyse(m)
        self.assertEqual(r["interaction"], 0.0)
        self.assertEqual((r["p10"], r["p90"]), (7.0, 7.0))
        from rangefinder.report import text_report
        text = text_report(m, r)
        self.assertIn("nothing is worth checking first", text)
        self.assertNotIn("Check first", text)

    def test_numbers_out_of_bounds_are_problems_not_crashes(self):
        self.assertIn("between -1e15 and 1e15", M.validate_model(one_driver("lognormal", 1e300, 1e308))[0])
        self.assertIn("needs numbers", M.validate_model(one_driver("lognormal", 10 ** 400, 10 ** 401))[0])
        m = one_driver("normal", 0, 1)
        m["threshold"] = 1e16
        self.assertIn("threshold", M.validate_model(m)[0])

    def test_names_are_trimmed_of_ascii_space_only(self):
        self.assertEqual(M.strip_name("  a b \t"), "a b")
        self.assertEqual(M.strip_name("\x1c"), "\x1c")
        m = one_driver("normal", 0, 1)
        m["terms"][0]["drivers"][0]["name"] = " \n "
        self.assertIn("needs a name", M.validate_model(m)[0])

    def test_percent_rounds_halves_up(self):
        self.assertEqual([M.percent(x) for x in (0.325, 0.125, 0.5, 0.004, 0.995)], [33, 13, 50, 0, 100])


class NarrowingTests(unittest.TestCase):
    def test_narrowing_keeps_the_median_and_shrinks_the_range(self):
        t = M.TEMPLATES[0]
        for di, d in enumerate(t["terms"][0]["drivers"]):
            half = M.narrow_driver(t, 0, di, 0.5)["terms"][0]["drivers"][di]
            self.assertAlmostEqual(M.quantile(half, 0), M.quantile(d, 0), places=9)
            if d["dist"] == "lognormal":
                self.assertAlmostEqual(math.log(half["high"] / half["low"]), math.log(d["high"] / d["low"]) / 2)
            same = M.narrow_driver(t, 0, di, 1)["terms"][0]["drivers"][di]
            self.assertAlmostEqual(same["low"], d["low"])
            self.assertAlmostEqual(same["high"], d["high"])
        normal = one_driver("normal", 10, 30)
        n = M.narrow_driver(normal, 0, 0, 0.25)["terms"][0]["drivers"][0]
        self.assertEqual((n["low"], n["high"]), (17.5, 22.5))
        self.assertEqual(t["terms"][0]["drivers"][0]["low"], 22000)  # the original is untouched

    def test_pinning_down(self):
        t = M.TEMPLATES[1]
        pinned = M.narrow_driver(t, 0, 1, 0)
        d = pinned["terms"][0]["drivers"][1]
        self.assertEqual(d["dist"], "fixed")
        self.assertAlmostEqual(d["low"], M.quantile(t["terms"][0]["drivers"][1], 0))
        self.assertLess(d["low"], 1)  # a percentage is pinned as a fraction
        self.assertEqual(M.validate_model(pinned), [])
        before, after = M.analyse(t), M.analyse(pinned)
        self.assertLess(after["p90"] - after["p10"], before["p90"] - before["p10"])

    def test_plan_command(self):
        from rangefinder.__main__ import pilot_plan
        base, rows = pilot_plan(M.TEMPLATES[1], 0.5)
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["widthChange"] for r in rows], sorted(r["widthChange"] for r in rows))
        self.assertTrue(all(r["widthChange"] < 0.01 for r in rows))


class DeepTests(unittest.TestCase):
    def test_sobol_first_order_matches_the_app(self):
        from rangefinder.deep import sobol
        t = M.TEMPLATES[0]
        r = M.analyse(t)
        s = sobol(t, 8000, 5)
        for app, chk in zip(r["drivers"], s):
            self.assertAlmostEqual(app["varShare"], chk["first"], delta=0.04, msg=app["name"])
            self.assertGreaterEqual(chk["total"], chk["first"] - 0.03)
        self.assertGreater(sum(x["total"] for x in s), 1.0)  # a product has interactions

    def test_additive_model_has_equal_first_and_total(self):
        from rangefinder.deep import sobol
        m = one_driver("normal", 0, 10)
        m["terms"].append({"name": "b", "sign": 1, "drivers": [{"name": "e", "dist": "uniform", "low": 0, "high": 20, "unit": ""}]})
        for x in sobol(m, 8000, 2):
            self.assertAlmostEqual(x["first"], x["total"], delta=0.03)

    def test_stability(self):
        from rangefinder.deep import stability
        st = stability(M.TEMPLATES[2], seeds=5, n=2000)
        self.assertLess(st["p50"]["sd"], abs(st["p50"]["mean"]) * 0.2 + 5000)
        self.assertTrue(0 <= st["probAbove"]["min"] <= st["probAbove"]["max"] <= 1)
        m = copy.deepcopy(M.TEMPLATES[2])
        m["threshold"] = None
        self.assertNotIn("probAbove", stability(m, seeds=2, n=1000))


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
                 0.1234: "0.123", 0.004567: "0.00457", 1e-9: "0", float("nan"): "n/a", 1.125: "1.13",
                 2.5e12: "2.5tn", 999.6e12: "1000tn", 1e15: "1000tn+", -6e30: "-1000tn+"}
        for x, s in cases.items():
            self.assertEqual(M.format_number(x), s, x)

    def test_values_and_drivers(self):
        self.assertEqual(M.format_value(-59200, "£", "prefix"), "-£59.2k")
        self.assertEqual(M.format_value(12500, "tonnes", "suffix"), "12.5k tonnes")
        self.assertEqual(M.format_value(5, "", "prefix"), "5")
        self.assertEqual(M.format_driver(0.123, {"dist": "share"}), "12.3%")
        self.assertEqual(M.format_driver(4.5, {"dist": "lognormal", "unit": "£"}), "£4.5")
        self.assertEqual(M.format_driver(1500, {"dist": "lognormal", "unit": "bikes"}), "1.5k bikes")
        self.assertEqual(M.format_driver(19.2, {"dist": "lognormal", "unit": "$"}), "$19.2")


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

    def test_deep_command(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "m.json")
            self.run_cli("template", "ai-assistant", "-o", path)
            code, out = self.run_cli("deep", path, "--samples", "1500", "--seeds", "3")
            self.assertEqual(code, 0)
            self.assertIn("Total-effect", out)
            self.assertIn("Chance of clearing", out)

    def test_bad_arguments_and_odd_models_are_clean(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "m.json")
            self.run_cli("template", "meal-kits", "-o", path)
            for argv in (("run", path, "--samples", "0"), ("run", path, "--samples", "5"),
                         ("deep", path, "--seeds", "0"), ("run", path, "--threshold", "1e20")):
                code, out = self.run_cli(*argv)
                self.assertEqual(code, 2, argv)
                self.assertIn("Error:", out)
            fixed = Path(d) / "fixed.json"
            fixed.write_text(json.dumps(one_driver("fixed", 3, 3)))
            code, out = self.run_cli("plan", str(fixed))
            self.assertEqual(code, 0)
            self.assertIn("no range to narrow", out)
            zero = one_driver("fixed", 0, 0)
            zero["terms"][0]["drivers"].append({"name": "e", "dist": "normal", "low": 0, "high": 20000, "unit": ""})
            zfile = Path(d) / "zero.json"
            zfile.write_text(json.dumps(zero))
            code, out = self.run_cli("plan", str(zfile))
            self.assertEqual(code, 0)
            self.assertIn("n/a", out)
            bom = Path(d) / "bom.json"
            bom.write_bytes(b"\xef\xbb\xbf" + json.dumps(M.TEMPLATES[2]).encode("utf-8"))
            self.assertEqual(self.run_cli("run", str(bom), "--samples", "1000")[0], 0)

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
