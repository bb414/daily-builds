"""The browser app and the Python package must give the same answers.

These tests run the app's MODEL block in Node.js (through tests/model_harness.js) and compare
every output with the Python port. They are skipped if Node.js is not installed.
"""

import json
import math
import random
import shutil
import subprocess
import unittest
from pathlib import Path

from reliance_lab import model

NODE = shutil.which("node")
HARNESS = Path(__file__).with_name("model_harness.js")


def run_js(calls):
    result = subprocess.run([NODE, str(HARNESS)], input=json.dumps(calls), capture_output=True,
                            text=True, check=True)

    def fix(v):
        if v == "Infinity":
            return math.inf
        if v == "-Infinity":
            return -math.inf
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        return v

    return fix(json.loads(result.stdout))


EDGE_PARAMS = [
    {},
    {"human": 0.5, "ai": 0.99, "overlap": 1, "aiSignal": 0, "humanSignal": 0},
    {"human": 0.99, "ai": 0.5, "overlap": -1, "aiSignal": 4, "humanSignal": 4},
    {"human": 0.8, "ai": 0.8, "overlap": 1},
    {"aiBias": 2, "humanBias": -2, "threshold": 0.99, "deferRate": 1},
    {"aiBias": -2, "humanBias": 2, "threshold": 0.5, "deferRate": 0},
    {"human": 0.7, "ai": 0.8, "aiSignal": 0, "threshold": 0.8},
]


@unittest.skipUnless(NODE, "Node.js is needed to run the browser app's model")
class AgreementTests(unittest.TestCase):
    def assert_same(self, js, py, where=""):
        if isinstance(py, dict):
            self.assertEqual(sorted(js), sorted(py), where)
            for k in py:
                self.assert_same(js[k], py[k], f"{where}.{k}")
        elif isinstance(py, (list, tuple)):
            self.assertEqual(len(js), len(py), where)
            for i, (a, b) in enumerate(zip(js, py)):
                self.assert_same(a, b, f"{where}[{i}]")
        elif isinstance(py, bool) or py is None or isinstance(py, str):
            self.assertEqual(js, py, where)
        elif isinstance(py, (int, float)):
            if math.isinf(py):
                self.assertEqual(js, py, where)
            else:
                self.assertTrue(math.isclose(js, py, rel_tol=1e-11, abs_tol=1e-12), f"{where}: {js} != {py}")
        else:
            self.fail(f"{where}: unexpected type {type(py)}")

    def test_normal_cdf(self):
        xs = [-40, -8, -3.2, -1, -0.01, 0, 0.5, 2, 6.9, 7.2, 12]
        js = run_js([{"fn": "normCdf", "args": [x]} for x in xs])
        self.assert_same(js, [model.norm_cdf(x) for x in xs], "normal")

    def test_model_analysis_agrees(self):
        rng = random.Random(21)
        params = list(EDGE_PARAMS)
        for _ in range(150):
            params.append({
                "human": round(rng.uniform(0.5, 0.99), 3), "ai": round(rng.uniform(0.5, 0.99), 3),
                "overlap": round(rng.uniform(-1, 1), 3), "aiSignal": round(rng.uniform(0, 4), 2),
                "humanSignal": round(rng.uniform(0, 4), 2), "aiBias": round(rng.uniform(-2, 2), 2),
                "humanBias": round(rng.uniform(-2, 2), 2), "threshold": round(rng.uniform(0.5, 0.99), 2),
                "deferRate": round(rng.random(), 2),
            })
        js = run_js([{"fn": "analyse", "args": [p]} for p in params])
        for p, j in zip(params, js):
            self.assert_same(j, model.analyse(p), json.dumps(p))

    def test_threshold_curves_agree(self):
        js = run_js([{"fn": "thresholdCurve", "args": [p, 30]} for p in EDGE_PARAMS])
        for p, j in zip(EDGE_PARAMS, js):
            self.assert_same(j, model.threshold_curve(p, 30), json.dumps(p))

    def test_gain_grids_agree(self):
        calls = [{"fn": "gainGrid", "args": [p, rule, 15]} for p in EDGE_PARAMS[:4] for rule in model.POLICIES]
        js = run_js(calls)
        for call, j in zip(calls, js):
            p, rule, steps = call["args"]
            self.assert_same(j, model.gain_grid(p, rule, steps), f"grid {rule} {json.dumps(p)}")

    def test_sensitivity_agrees(self):
        calls = [{"fn": "sensitivity", "args": [p, rule]} for p in EDGE_PARAMS for rule in model.POLICIES]
        js = run_js(calls)
        for call, j in zip(calls, js):
            p, rule = call["args"]
            self.assert_same(j, model.sensitivity(p, rule), f"sensitivity {rule} {json.dumps(p)}")

    def test_per_100_agrees(self):
        rng = random.Random(8)
        params = list(EDGE_PARAMS) + [{"human": round(rng.uniform(0.5, 0.99), 3), "ai": round(rng.uniform(0.5, 0.99), 3),
                                       "overlap": round(rng.uniform(-1, 1), 2), "aiSignal": round(rng.uniform(0, 4), 1),
                                       "humanSignal": round(rng.uniform(0, 4), 1)} for _ in range(60)]
        calls = [{"fn": "per100", "args": [p, rule]} for p in params for rule in model.POLICIES]
        js = run_js(calls)
        for call, j in zip(calls, js):
            p, rule = call["args"]
            self.assert_same(j, model.per_100(p, rule), f"per100 {rule} {json.dumps(p)}")

    def test_labels_and_defaults_agree(self):
        js = run_js([{"fn": "normalise", "args": [{}]}])[0]
        self.assert_same(js, model.normalise({}), "defaults")


if __name__ == "__main__":
    unittest.main()
