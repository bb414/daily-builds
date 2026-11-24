"""Proves the browser app's model (run in Node.js) and the Python port give the same numbers."""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from reliance_lab import model

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

CASES = [
    dict(model.preset_params("scam_teens"), people=80),
    dict(model.preset_params("invoice_fraud"), people=60, rounds=120),
    dict(model.preset_params("lead_triage"), people=60, rounds=100),
    dict(model.preset_params("scam_teens"), workflow="human_first", showConfidence=False, people=50, seed=7),
    dict(model.preset_params("scam_teens"), workflow="on_request", errorOverlap=1, aiOverconfidence=1, people=50),
    dict(model.preset_params("scam_teens"), workflow="none", people=50, rounds=33),
    {"aiAccuracy": 0.99, "humanAccuracy": 0.5, "people": 50, "rounds": 40, "skillSpread": 1.5, "difficultySpread": 2,
     "learningRate": 0.01, "decayRate": 0.01, "trustRate": 0.1, "aversion": 6, "seed": 9999},
    {"aiAccuracy": "0.7", "rounds": "45", "workflow": "bogus", "showConfidence": "no", "people": 50},
    dict(model.preset_params("scam_teens"), people=60, driftAt=50, driftAccuracy=0.55),
    dict(model.preset_params("lead_triage"), people=40, rounds=90, driftAt=10, driftAccuracy=0.99, workflow="ai_first"),
]


def run_js(configs):
    proc = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(configs),
                          capture_output=True, text=True, check=True, cwd=ROOT)
    return json.loads(proc.stdout)


def assert_close(test, a, b, path="result"):
    if isinstance(a, dict):
        test.assertEqual(set(a), set(b), path)
        for key in a:
            assert_close(test, a[key], b[key], path + "." + key)
    elif isinstance(a, list):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_close(test, x, y, "%s[%d]" % (path, i))
    elif isinstance(a, bool) or a is None or isinstance(a, str):
        test.assertEqual(a, b, path)
    else:
        test.assertTrue(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), "%s: %r != %r" % (path, a, b))


@unittest.skipIf(NODE is None, "Node.js is needed to run the browser app's model")
class ParityTest(unittest.TestCase):
    def test_constants_presets_and_ranges_match(self):
        out = subprocess.run([NODE, "-e", (
            "const M=require('./tests/load_model.js').loadModel();"
            "process.stdout.write(JSON.stringify({C:M.CONSTANTS,P:M.PARAMS,W:M.WORKFLOW_KEYS,"
            "R:Object.fromEntries(Object.entries(M.PRESETS).map(([k,v])=>[k,v.params])),D:M.DEFAULTS,T:M.TOLERANCE,V:M.VERDICTS}))")],
            capture_output=True, text=True, check=True, cwd=ROOT).stdout
        js = json.loads(out)
        self.assertEqual(js["C"], model.CONSTANTS)
        self.assertEqual(js["W"], model.WORKFLOW_KEYS)
        self.assertEqual(js["D"], model.DEFAULTS)
        self.assertEqual(js["T"], model.TOLERANCE)
        self.assertEqual(js["V"], model.VERDICTS)
        self.assertEqual(js["R"], {k: v["params"] for k, v in model.PRESETS.items()})
        py_specs = [(k, g, lo, hi, d, i) for k, g, lo, hi, d, i in model.PARAMS]
        js_specs = [(s["key"], s["group"], s["min"], s["max"], s["def"], bool(s.get("int"))) for s in js["P"]]
        self.assertEqual(js_specs, py_specs)

    def test_odd_inputs_are_read_the_same_way(self):
        odd = [{"rounds": v} for v in (" ", "0x40", [100], "1_000", "\u0661\u0662\u0660", "1e999", " 120 ", "1e2", True,
                                       None, "", "12abc", 125, 0.49999999999999994, -3, 1e308)]
        odd += [{"driftAt": 0.49999999999999994}, {"driftAt": 2.5}, {"aiAccuracy": 0.7, "driftAccuracy": 0.95}]
        odd += [{"showConfidence": v} for v in ("no", "OFF", " 0 ", 0, 2, "yes", None)]
        odd += [{"workflow": w} for w in ("AI first", "none", None, 3)]
        js = run_js([{"__normalise": o} for o in odd])
        for o, js_out in zip(odd, js):
            self.assertEqual(js_out, model.normalise_params(o), repr(o))

    def test_random_numbers_match(self):
        out = subprocess.run([NODE, "-e", (
            "const M=require('./tests/load_model.js').loadModel();const r=M.makeRng(M.mixSeed(42,3));"
            "const xs=[];for(let i=0;i<50;i++){xs.push(r.uniform());xs.push(r.normal());}"
            "process.stdout.write(JSON.stringify(xs))")], capture_output=True, text=True, check=True, cwd=ROOT).stdout
        rng = model.Rng(model.mix_seed(42, 3))
        expected = []
        for _ in range(50):
            expected.append(rng.uniform())
            expected.append(rng.normal())
        assert_close(self, json.loads(out), expected, "rng")

    def test_workflow_comparison_matches(self):
        config = dict(model.preset_params("invoice_fraud"), people=40, rounds=80, driftAt=40)
        js = run_js([{"__compare": config}])[0]
        py = model.compare_workflows(config)
        self.assertEqual(len(js), len(py))
        for js_row, py_row in zip(js, py):
            assert_close(self, js_row, py_row, "compare." + py_row["workflow"])

    def test_robustness_and_explanations_match(self):
        config = dict(model.preset_params("scam_teens"), people=30, rounds=40)
        js = run_js([{"__sensitivity": config}])[0]
        assert_close(self, js, model.sensitivity(config), "sensitivity")
        configs = [dict(c, people=40) for c in CASES]
        js_text = run_js([{"__explain": c} for c in configs])
        for c, text in zip(configs, js_text):
            self.assertEqual(text, model.explain(model.analyse(c)))

    def test_full_results_match(self):
        js = run_js(CASES)
        for config, js_out in zip(CASES, js):
            py_out = model.analyse(config)
            with self.subTest(config=config):
                assert_close(self, js_out, py_out)
