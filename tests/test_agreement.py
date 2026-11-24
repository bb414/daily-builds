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

from reliance_lab import model, sessions
from reliance_lab.synthetic import make_class

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

    def test_normal_functions(self):
        xs = [-40, -8, -3.2, -1, -0.01, 0, 0.5, 2, 6.9, 7.2, 12]
        ps = [1e-7, 0.01, 0.024, 0.3, 0.5, 0.9, 0.976, 0.999999]
        js = run_js([{"fn": "normCdf", "args": [x]} for x in xs] + [{"fn": "normInv", "args": [p]} for p in ps])
        py = [model.norm_cdf(x) for x in xs] + [model.norm_inv(p) for p in ps]
        self.assert_same(js, py, "normal")

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

    def test_session_scoring_agrees(self):
        class_sessions = make_class(24, seed=11)
        trial_sets = [s["trials"] for s in class_sessions]
        trial_sets += [[dict(t, aiConfidence=None) for t in s["trials"]] for s in class_sessions[:4]]
        # Sessions built from the app's own payment generator, answered by a fixed rule.
        generated = run_js([{"fn": "generateCases", "args": [{"n": 20, "code": f"agree-{i}", "aiAccuracy": 0.8,
                                                               "aiStyle": style}]}
                            for i, style in enumerate(["calibrated", "confident", "hidden"])])
        for cases in generated:
            trials = []
            for c in cases:
                p_fraud = c["idealFraudProbability"]
                initial = "fraud" if p_fraud >= 0.5 else "genuine"
                conf = 0.95 if abs(p_fraud - 0.5) > 0.4 else (0.85 if abs(p_fraud - 0.5) > 0.25 else 0.55)
                final = c["ai"] if c["aiConfidence"] is not None and c["aiConfidence"] > conf else initial
                trials.append({"id": c["id"], "truth": c["truth"], "initial": initial, "initialConfidence": conf,
                               "ai": c["ai"], "aiConfidence": c["aiConfidence"], "final": final})
            trial_sets.append(trials)
        calls = []
        for trials in trial_sets:
            calls += [{"fn": "scoreSession", "args": [trials]},
                      {"fn": "counterfactuals", "args": [trials, 0.75]},
                      {"fn": "counterfactuals", "args": [trials, 0.9]},
                      {"fn": "estimateParams", "args": [trials]}]
            calls += [{"fn": "classifyTrial", "args": [t]} for t in trials]
        js = run_js(calls)
        i = 0
        for k, trials in enumerate(trial_sets):
            self.assert_same(js[i], sessions.score_session(trials), f"score {k}")
            self.assert_same(js[i + 1], sessions.counterfactuals(trials, 0.75), f"cf75 {k}")
            self.assert_same(js[i + 2], sessions.counterfactuals(trials, 0.9), f"cf90 {k}")
            self.assert_same(js[i + 3], sessions.estimate_params(trials), f"estimate {k}")
            i += 4
            for t in trials:
                self.assertEqual(js[i], sessions.classify_trial(t))
                i += 1

    def test_labels_and_defaults_agree(self):
        js = run_js([{"fn": "normalise", "args": [{}]}])[0]
        self.assert_same(js, model.normalise({}), "defaults")


if __name__ == "__main__":
    unittest.main()
