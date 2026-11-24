"""Prove the browser app's model and the Python port agree.

These tests run the MODEL block from app/index.html in Node.js (through
tests/model_bridge.js) and compare it with the Python package. They are
skipped if Node.js is not installed.
"""

import json
import pathlib
import random
import shutil
import subprocess
import unittest

from markdown_ladder import model

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def call_js(calls):
    result = subprocess.run([NODE, str(ROOT / "tests" / "model_bridge.js")], input=json.dumps({"calls": calls}),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def random_configs(n, seed):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        out.append({
            "stock": rng.randint(1, 90), "days": rng.randint(1, 10), "price": round(rng.uniform(1, 30), 2),
            "unitCost": round(rng.uniform(0, 8), 2), "wasteCost": round(rng.uniform(-2, 4), 2),
            "demand": round(rng.uniform(0.2, 30), 1), "elasticity": round(rng.uniform(0, 5), 1),
            "startDay": rng.randint(0, 6), "pattern": rng.choice(list(model.WEEK_PATTERNS)), "monotone": rng.random() < 0.75,
        })
    return out


def assert_close(test, js, py, path="result"):
    if isinstance(py, dict):
        test.assertEqual(set(py), set(js), path)
        for k in py:
            assert_close(test, js[k], py[k], path + "." + k)
    elif isinstance(py, list):
        test.assertEqual(len(js), len(py), path)
        for k, (a, b) in enumerate(zip(js, py)):
            assert_close(test, a, b, "%s[%d]" % (path, k))
    elif isinstance(py, float) or isinstance(js, float):
        test.assertAlmostEqual(js, py, delta=1e-9 * max(1.0, abs(py)), msg=path)
    else:
        test.assertEqual(js, py, path)


@unittest.skipUnless(NODE, "Node.js is not installed")
class ParityTests(unittest.TestCase):
    def test_constants_match(self):
        js = call_js([{"fn": name} for name in ("LADDER", "DAY_NAMES", "WEEK_PATTERNS", "FIELDS", "PRESETS")])
        self.assertEqual(js, [model.LADDER, model.DAY_NAMES, model.WEEK_PATTERNS, model.FIELDS, model.PRESETS])

    def test_settings_are_read_the_same_way(self):
        odd = [{}, None, "text", [], {"stock": "45", "days": " 3 ", "price": "1e3", "demand": None, "elasticity": [2]},
               {"stock": 12.5, "days": 2.5, "startDay": -1, "pattern": "office", "monotone": 0},
               {"stock": "0x10", "wasteCost": "-Infinity", "price": True, "pattern": "constructor", "monotone": False},
               {"stock": [], "days": [[4]], "price": "", "unitCost": {}, "elasticity": "7_0"}]
        js = call_js([{"fn": "normalise", "args": [c]} for c in odd])
        for c, j in zip(odd, js):
            self.assertEqual(j, model.normalise(c), repr(c))

    def test_plans_match(self):
        cfgs = list(model.PRESETS.values()) + random_configs(60, 1)
        js = call_js([{"fn": "solve", "args": [c]} for c in cfgs])
        for c, j in zip(cfgs, js):
            py = model.solve(c)
            self.assertEqual(j["policy"], py["policy"], repr(c))
            assert_close(self, j["value"], py["value"], "value")
            assert_close(self, j["Q"], py["Q"], "Q")

    def test_evaluations_match(self):
        cfgs = list(model.PRESETS.values()) + random_configs(40, 2)
        rules = [{"pct": 30, "daysLeft": 2}, {"pct": 10, "daysLeft": 5}, {"pct": 50, "daysLeft": 1}]
        calls = [{"fn": "comparePolicies", "args": [c, rules[k % 3]]} for k, c in enumerate(cfgs)]
        js = call_js(calls)
        for k, (c, j) in enumerate(zip(cfgs, js)):
            py = model.compare_policies(c, rules[k % 3])
            self.assertEqual([r["name"] for r in j["rows"]], [r["name"] for r in py["rows"]])
            for jr, pr in zip(j["rows"], py["rows"]):
                assert_close(self, jr["result"], pr["result"], "%s %r" % (pr["name"], c))


if __name__ == "__main__":
    unittest.main()
