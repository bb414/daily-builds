"""Checks that the browser app's model (run in Node.js) agrees with the Python package."""

import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from rangefinder import model as M

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "index.html"
NODE = shutil.which("node")


def js(calls):
    proc = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(calls),
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def close(test, a, b, path="", rel=1e-9):
    """Recursive comparison: exact for everything except floats, which may differ in the last few bits
    because exp and log are computed by different maths libraries."""
    if isinstance(a, dict):
        test.assertEqual(set(a), set(b), path)
        for k in a:
            close(test, a[k], b[k], path + "." + k, rel)
    elif isinstance(a, list):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            close(test, x, y, "%s[%d]" % (path, i), rel)
    elif isinstance(a, float) or isinstance(b, float):
        test.assertLessEqual(abs(a - b), rel * max(1.0, abs(a), abs(b)), path)
    else:
        test.assertEqual(a, b, path)


def variants():
    """Every template plus edge cases: every kind of range, signs, fixed drivers, odd sample sizes."""
    out = [copy.deepcopy(t) for t in M.TEMPLATES]
    mix = copy.deepcopy(M.TEMPLATES[0])
    kinds = ["lognormal", "normal", "share", "uniform", "fixed", "lognormal"]
    for d, k in zip(mix["terms"][0]["drivers"], kinds):
        d["dist"] = k
        if k == "share":
            d["low"], d["high"] = 1, 99
        if k == "normal":
            d["low"], d["high"] = -3, 12
    mix["samples"] = 1234
    mix["seed"] = 4294967295
    mix["threshold"] = 0
    out.append(mix)
    neg = copy.deepcopy(M.TEMPLATES[1])
    neg["terms"][0]["sign"] = -1
    neg["samples"] = 5000
    neg["seed"] = 0
    neg["threshold"] = None
    out.append(neg)
    return out


@unittest.skipUnless(NODE, "Node.js is not installed")
class AppAgreesWithPython(unittest.TestCase):
    def test_templates_and_constants_are_identical(self):
        got = js([{"get": k} for k in ("TEMPLATES", "DISTS", "DIST_LABELS", "Z95", "Z90", "MAX_TERMS",
                                        "MAX_DRIVERS_PER_TERM", "MAX_DRIVERS", "MIN_SAMPLES", "MAX_SAMPLES",
                                        "DEFAULT_SAMPLES", "DEFAULT_SEED", "FORMAT", "VERSION", "MAX_ABS",
                                        "CURRENCY_PREFIXES")])
        self.assertEqual(got, [M.TEMPLATES, list(M.DISTS), M.DIST_LABELS, M.Z95, M.Z90, M.MAX_TERMS,
                               M.MAX_DRIVERS_PER_TERM, M.MAX_DRIVERS, M.MIN_SAMPLES, M.MAX_SAMPLES,
                               M.DEFAULT_SAMPLES, M.DEFAULT_SEED, M.FORMAT, M.VERSION, M.MAX_ABS,
                               list(M.CURRENCY_PREFIXES)])

    def test_samples_agree(self):
        models = variants()
        got = js([{"fn": "simulate", "args": [m, None, None]} for m in models])
        for m, g in zip(models, got):
            values, columns = M.simulate(m)
            close(self, [values, columns], g, m["title"])

    def test_analysis_agrees(self):
        models = variants()
        got = js([{"fn": "analyse", "args": [m, None, None]} for m in models])
        for m, g in zip(models, got):
            close(self, M.analyse(m), g, m["title"])

    def test_narrowing_agrees(self):
        calls, expect = [], []
        for m in variants():
            for ti, term in enumerate(m["terms"]):
                for di in range(len(term["drivers"])):
                    for f in (0, 0.25, 0.5, 1):
                        calls.append({"fn": "narrowDriver", "args": [m, ti, di, f]})
                        expect.append(M.narrow_driver(m, ti, di, f))
        got = js(calls)
        for g, e in zip(got, expect):
            close(self, e, g, "narrow")

    def test_inverse_normal_agrees(self):
        ps = [1e-12, 1e-6, 0.01, 0.02425, 0.2, 0.5, 0.77, 0.97576, 0.999, 1 - 1e-12]
        got = js([{"fn": "invNorm", "args": [p]} for p in ps])
        for p, g in zip(ps, got):
            self.assertAlmostEqual(g, M.inv_norm(p), delta=1e-12 * max(1, abs(g)))

    def test_validation_gives_the_same_messages(self):
        base = M.TEMPLATES[0]

        def changed(fn):
            m = copy.deepcopy(base)
            fn(m)
            return m

        d0 = lambda m: m["terms"][0]["drivers"][0]
        cases = [
            base, None, [], "x", {}, {"format": "other"},
            changed(lambda m: m.update(title=5)), changed(lambda m: m.update(unit="x" * 13)),
            changed(lambda m: m.update(unitPosition="mid")), changed(lambda m: m.update(threshold="1")),
            changed(lambda m: m.update(threshold=None)), changed(lambda m: m.update(samples=999)),
            changed(lambda m: m.update(samples=1500.5)), changed(lambda m: m.update(seed=-1)),
            changed(lambda m: m.update(seed=4294967296)), changed(lambda m: m.update(terms=[])),
            changed(lambda m: m.update(terms="x")), changed(lambda m: m["terms"].append(5)),
            changed(lambda m: m["terms"][0].update(sign=2)), changed(lambda m: m["terms"][0].update(sign=True)),
            changed(lambda m: m["terms"][0].update(name=None)), changed(lambda m: m["terms"][0].update(drivers=[])),
            changed(lambda m: d0(m).update(name="")), changed(lambda m: d0(m).update(dist="beta")),
            changed(lambda m: d0(m).update(low="5")), changed(lambda m: d0(m).update(high=None)),
            changed(lambda m: d0(m).update(low=30000, high=22000)), changed(lambda m: d0(m).update(low=0)),
            changed(lambda m: d0(m).update(dist="share", low=5, high=100)),
            changed(lambda m: d0(m).update(dist="fixed", high=None)),
            changed(lambda m: d0(m).update(low=True)),
            changed(lambda m: m["terms"][0]["drivers"].extend([copy.deepcopy(d0(m)) for _ in range(7)])),
            changed(lambda m: d0(m).update(name="\x1c")), changed(lambda m: d0(m).update(name="\ufeff")),
            changed(lambda m: d0(m).update(name=" \t ")), changed(lambda m: m.update(unit="\U0001D461" * 7)),
            changed(lambda m: m.update(unit="\U0001D461" * 13)), changed(lambda m: d0(m).update(low=1e300, high=1e308)),
            changed(lambda m: m.update(threshold=2e15)), changed(lambda m: d0(m).update(dist="fixed", low=-1e16)),
        ]
        got = js([{"fn": "validateModel", "args": [c]} for c in cases])
        self.assertEqual(got, [M.validate_model(c) for c in cases])
        self.assertEqual(got[0], [])
        valid = sum(1 for g in got if not g)
        self.assertEqual(valid, 6)  # the base model, an empty threshold, a fixed driver, two odd names, a 7-character unit

    def test_formatting_is_identical(self):
        xs = [0, 1, -1, 0.5, 1.125, 2.675, 12.345, 99.95, 999.4, 999.5, 1234, 12345, 123456, 999499, 999500,
              1234567, 2.5e9, 1e15, -45100, 0.1234, 0.004567, 1e-9, -0.0005, 7.005, 1.005, 100.5, 0.0995,
              2.5e12, 999.6e12, 6e30, -1e300, 4.567e-5]
        got = js([{"fn": "formatNumber", "args": [x]} for x in xs]
                 + [{"fn": "formatValue", "args": [x, u, p]} for x in (-59200, 0, 3.5) for u, p in
                    (("£", "prefix"), ("t", "suffix"), ("", "prefix"))]
                 + [{"fn": "formatDriver", "args": [x, d]} for x in (0.1234, 4.5, 1500) for d in
                    ({"dist": "share"}, {"dist": "lognormal", "unit": "£"}, {"dist": "normal", "unit": "bikes"},
                     {"dist": "normal"}, {"dist": "normal", "unit": "$"})])
        expect = ([M.format_number(x) for x in xs]
                  + [M.format_value(x, u, p) for x in (-59200, 0, 3.5) for u, p in
                     (("£", "prefix"), ("t", "suffix"), ("", "prefix"))]
                  + [M.format_driver(x, d) for x in (0.1234, 4.5, 1500) for d in
                     ({"dist": "share"}, {"dist": "lognormal", "unit": "£"}, {"dist": "normal", "unit": "bikes"},
                      {"dist": "normal"}, {"dist": "normal", "unit": "$"})])
        self.assertEqual(got, expect)


class AppFileChecks(unittest.TestCase):
    def setUp(self):
        self.html = APP.read_text(encoding="utf-8")

    def test_no_external_requests(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?https?:""", self.html))
        for word in ("@import", "fetch(", "XMLHttpRequest", "<link"):
            self.assertNotIn(word, self.html)

    def test_model_markers(self):
        self.assertEqual(self.html.count("/* MODEL START */"), 1)
        self.assertEqual(self.html.count("/* MODEL END */"), 1)


if __name__ == "__main__":
    unittest.main()
