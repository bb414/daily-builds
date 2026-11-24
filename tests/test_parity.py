"""Proves the browser app's model (run in Node.js) and the Python port give the same numbers."""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from champion_seeding import model

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def run_js(jobs):
    proc = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(jobs),
                          capture_output=True, text=True, check=True, cwd=ROOT)
    return json.loads(proc.stdout)


def assert_same(test, a, b, path="result"):
    if isinstance(a, dict):
        test.assertEqual(set(a), set(b), path)
        for key in a:
            assert_same(test, a[key], b[key], path + "." + key)
    elif isinstance(a, list):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(test, x, y, "%s[%d]" % (path, i))
    elif isinstance(a, (bool, str)) or a is None:
        test.assertEqual(a, b, path)
    else:
        test.assertTrue(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), "%s: %r != %r" % (path, a, b))


SETTINGS = [
    dict(model.preset_params("assistant"), runs=10),
    dict(model.preset_params("plugin"), runs=10, weeks=40),
    dict(model.preset_params("silos"), runs=10, people=120, teams=9),
    {"people": 40, "teams": 30, "departments": 6, "champions": 30, "championWeight": 5, "runs": 10, "weeks": 8, "seed": 9999},
    {"people": 300, "teams": 2, "departments": 1, "champions": 1, "socialProof": 0.6, "tiesTeam": 12, "tiesOrg": 4,
     "runs": 10, "weeks": 20, "lapse": 0.3, "fit": 0.3},
    {"socialProof": "0.2", "peerPull": ".3", "runs": "10", "weeks": "16", "strategy": "bogus", "spontaneous": 0.03},
    dict(model.preset_params("assistant"), runs=10, weeks=20, custom=[0, 5, 9, 44], strategy="custom"),
    dict(model.preset_params("assistant"), runs=10, weeks=20, custom="3, 3, 170, 400, x", strategy="custom"),
]


@unittest.skipIf(NODE is None, "Node.js is needed to run the browser app's model")
class ParityTest(unittest.TestCase):
    def test_networks_match(self):
        js = run_js([{"network": s} for s in SETTINGS])
        for s, out in zip(SETTINGS, js):
            net = model.build_network(s)
            py = {k: net[k] for k in ("adj", "team", "need", "suit", "betweenness", "degree", "outsideShare", "teamTies")}
            with self.subTest(settings=s):
                assert_same(self, out, py)

    def test_comparisons_and_explanations_match(self):
        js = run_js([{"compare": s} for s in SETTINGS])
        for s, out in zip(SETTINGS, js):
            cmp = model.compare_strategies(s)
            with self.subTest(settings=s):
                assert_same(self, out["compare"], cmp)
                self.assertEqual(out["why"], model.explain(cmp))

    def test_sweeps_match(self):
        params = {"people": 60, "teams": 5, "runs": 10, "weeks": 12}
        jobs = [{"sweep": {"params": params, "key": k}} for k in model.SWEEP_KEYS]
        for job, out in zip(jobs, run_js(jobs)):
            sw = model.sweep(params, job["sweep"]["key"])
            assert_same(self, out["sweep"], sw, job["sweep"]["key"])
            assert_same(self, out["spans"], model.winner_spans(sw))

    def test_robustness_and_settings_files_match(self):
        params = {"people": 60, "teams": 5, "runs": 10, "weeks": 12, "custom": [1, 2]}
        js = run_js([{"robust": params}])[0]
        assert_same(self, js, model.robustness(params))
        files = [{"app": "champion-seeding", "params": dict(model.preset_params("silos"), custom=[4, 40])},
                 {"champions": "12", "custom": "1,2,3"}]
        for f, out in zip(files, run_js([{"settings": f} for f in files])):
            self.assertEqual(out, model.read_settings_file(f))

    def test_settings_are_read_the_same_way(self):
        odd = [{"champions": v} for v in (" ", "0x10", [9], True, "1e999", "12abc", " 12 ", "1e1", None, 2.5, 0.49999999999999994)]
        odd += [{"people": 40, "teams": 30, "departments": 6}, {"teams": 2, "departments": 5}, {"strategy": "spread"},
                {"strategy": 3}, {"socialProof": -1}, {"seed": 10 ** 400}, {"custom": "5, 3,3, x, 999, -1, 2.5, 7"},
                {"custom": [9, "4", 4, True, None, 1e9]}, {"custom": [1, 2, 3], "champions": 2}, {"strategy": "custom"},
                {"strategy": "custom", "custom": [7]}, {"custom": 12}]
        js = run_js([{"normalise": o} for o in odd])
        for o, out in zip(odd, js):
            self.assertEqual(out, model.normalise_params(o), repr(o))

    def test_constants_presets_and_labels_match(self):
        src = ("const M=require('./tests/load_model.js').loadModel();"
               "process.stdout.write(JSON.stringify({C:M.CONSTANTS,P:M.PARAMS,K:M.STRATEGY_KEYS,"
               "S:Object.fromEntries(Object.entries(M.STRATEGIES).map(([k,v])=>[k,v.label])),"
               "R:Object.fromEntries(Object.entries(M.PRESETS).map(([k,v])=>[k,{label:v.label,params:v.params}])),D:M.DEFAULTS}))")
        src = src.replace("D:M.DEFAULTS}", "D:M.DEFAULTS,W:M.SWEEPS,WK:M.SWEEP_KEYS}")
        js = json.loads(subprocess.run([NODE, "-e", src], capture_output=True, text=True, check=True, cwd=ROOT).stdout)
        self.assertEqual(js["W"], model.SWEEPS)
        self.assertEqual(js["WK"], model.SWEEP_KEYS)
        self.assertEqual(js["C"], model.CONSTANTS)
        self.assertEqual(js["K"], model.STRATEGY_KEYS)
        self.assertEqual(js["S"], model.STRATEGY_LABELS)
        self.assertEqual(js["R"], model.PRESETS)
        self.assertEqual(js["D"], model.DEFAULTS)
        js_specs = [(s["key"], s["group"], s["min"], s["max"], s["def"], bool(s.get("int"))) for s in js["P"]]
        self.assertEqual(js_specs, [tuple(x) for x in model.PARAMS])
        self.assertEqual({s["key"]: s["label"] for s in js["P"]}, model.PARAM_LABELS)
