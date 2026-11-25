"""The browser app and the Python package must give the same answers.

These tests run the app's MODEL block in Node.js (through tests/model_harness.js) and compare its
output with the Python port on the same settings and luck. They are skipped without Node.js.
"""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from leaderboard_luck import check, model

NODE = shutil.which("node")
HARNESS = Path(__file__).with_name("model_harness.js")


def run_js(calls):
    result = subprocess.run([NODE, str(HARNESS)], input=json.dumps(calls), capture_output=True, text=True,
                            check=True)

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


SETTINGS = [
    {"sims": 120},
    {"sims": 120, "rule": "sharpe", "teams": 7, "days": 9},
    {"sims": 120, "rule": "drawdown", "drawdownLimit": 0.07, "fatTails": True, "seed": 77},
    {"sims": 100, "teams": 60, "days": 45, "gamblers": 0.55, "gamblerMultiple": 4, "correlation": 0.9, "yourSharpe": -0.4},
    {"sims": 100, "fieldVol": 0.5, "gamblerMultiple": 4, "gamblers": 0.8, "fatTails": True, "days": 120,
     "yourVol": 1, "rule": "drawdown", "drawdownLimit": 0.6, "seed": 4294967295},
    {"sims": 100, "skillSpread": 0, "correlation": 0, "teams": 3, "days": 5, "yourSharpe": 3},
    {"sims": 100, "catchUp": True, "rivalsCatchUp": 0.5, "rule": "sharpe", "checkpoint": 0.4},
    {"sims": 100, "catchUp": True, "catchUpVol": 1, "rivalsCatchUp": 1, "rule": "drawdown", "drawdownLimit": 0.12,
     "fatTails": True, "teams": 40, "days": 30, "checkpoint": 0.9, "seed": 12},
    {"sims": 100, "leverageCap": True, "volCap": 0.3, "cost": 0.2, "catchUp": True, "rivalsCatchUp": 1},
    {"sims": 100, "leverageCap": True, "volCap": 0.05, "yourVol": 1, "rule": "drawdown", "drawdownLimit": 0.03,
     "cost": 0.5, "days": 60, "seed": 5},
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
                self.assertTrue(math.isclose(js, py, rel_tol=1e-9, abs_tol=1e-12), f"{where}: {js} != {py}")
        else:
            self.fail(f"{where}: unexpected type {type(py)}")

    def test_random_numbers_agree(self):
        js = run_js([{"fn": "competitionSeed", "args": [s, k]} for s in (0, 1, 4294967295) for k in (0, 1, 19999)])
        py = [model.competition_seed(s, k) for s in (0, 1, 4294967295) for k in (0, 1, 19999)]
        self.assertEqual(js, py)

    def test_simulations_agree(self):
        js = run_js([{"fn": "simulate", "args": [p]} for p in SETTINGS])
        for p, j in zip(SETTINGS, js):
            self.assert_same(j, model.simulate(p), json.dumps(p))

    def test_sample_challenges_agree(self):
        calls = [{"fn": "sampleCompetition", "args": [p, k]} for p in SETTINGS for k in (0, 7)]
        js = run_js(calls)
        for call, j in zip(calls, js):
            p, k = call["args"]
            self.assert_same(j, model.sample_competition(p, k), f"sample {k} {json.dumps(p)}")

    def test_skill_by_length_agrees(self):
        settings = [{"teams": 10}, {"teams": 8, "catchUp": True, "rivalsCatchUp": 1, "fatTails": True, "seed": 3}]
        js = run_js([{"fn": "skillByLength", "args": [p, 12]} for p in settings])
        for p, j in zip(settings, js):
            self.assert_same(j, model.skill_by_length(p, 12), f"skill {json.dumps(p)}")

    def test_leaderboard_checks_agree(self):
        texts = [
            check.example_table("month")["text"],
            check.example_table("year")["text"],
            "Rank\tFund\tP&L (%)\tRisk\n1\tAlpha\t8.4\t21\n2\tBeta\t\u22121.5\t\n3\tGamma\tn/a\t30\n4\tDelta\t(3.2)\t12\n",
            'Team;Return;Volatility\n"Smith, Jones";0,05;0,2\nLee;-0,02;0,3\nPark;0,11;0,45\n',
            "Team,Sharpe,True skill\nA,1.2,0.5\nB,-0.3,0.1\nC,2.5,1.0\nD,0.4,-0.2\n",
            "Oak, 8.4%, 21%\nElm, 4.0%, 23%\nAsh, -100%, 80%\n",
        ]
        options = [{}, {"days": 250}, {"days": 40, "correlation": 0.6}, {"assumedVol": 0.5, "seed": 9},
                   {"days": 5, "sims": 3000}, {"correlation": 0}]
        js = run_js([{"fn": "parseTable", "args": [t]} for t in texts])
        for t, j in zip(texts, js):
            self.assert_same(j, check.parse_table(t), f"parse {t[:20]!r}")
        tables = [check.parse_table(t) for t in texts]
        js = run_js([{"fn": "checkLeaderboard", "args": [t, o]} for t, o in zip(tables, options)])
        for t, o, j in zip(tables, options, js):
            self.assert_same(j, check.check_leaderboard(t, o), f"check {o}")
        js = run_js([{"fn": "exampleTable", "args": [kind]} for kind in ("month", "year")])
        self.assertEqual(js, [check.example_table("month"), check.example_table("year")])

    def test_defaults_agree(self):
        self.assert_same(run_js([{"fn": "normalise", "args": [{}]}])[0], model.normalise({}), "defaults")


if __name__ == "__main__":
    unittest.main()
