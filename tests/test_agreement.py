"""The browser app's model (run in Node.js) and the Python package must agree exactly."""

import json
import os
import shutil
import subprocess
import unittest

from mislabelled import model as M

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = [
    {"persona": "student", "weeks": 13, "seed": 1, "checks": 40, "target": 5, "slip": 0, "weight": 20, "perWeek": 3},
    {"persona": "graduate", "weeks": 9, "seed": 77, "checks": 30, "target": 3, "slip": 0.15, "weight": 8, "perWeek": 1},
    {"persona": "sixthformer", "weeks": 26, "seed": 4242, "checks": 25, "target": 10, "slip": 0.3, "weight": 45, "perWeek": 6},
]


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the browser model")
class AgreementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = os.path.join(HERE, "js", "dump_model.js")
        raw = subprocess.run(["node", script, json.dumps(CASES)], check=True, capture_output=True, text=True).stdout
        cls.js = json.loads(raw)

    def test_random_numbers_and_arithmetic(self):
        r = M.mulberry32(2026)
        self.assertEqual(self.js["rng"], [r(), r(), r(), r()])
        self.assertEqual(self.js["ln"], [M.ln(x) for x in [0.37, 1, 2, 17, 4000.5]])
        self.assertEqual(self.js["exp"], [M.exp(x) for x in [-30.2, -2.5, -0.01, 0, 1.9]])

    def test_population_is_identical(self):
        py = [[d["desc"], d["feats"], d["cat"]] for d in M.build_population()["docs"]]
        self.assertEqual(self.js["population"], py)

    def test_statements_predictions_and_strategies_are_identical(self):
        for case, js in zip(CASES, self.js["cases"]):
            with self.subTest(case=case):
                st = M.generate_statement(case["persona"], case["weeks"], case["seed"])
                self.assertEqual(js["tx"], [[t["date"], t["desc"], t["pennies"], t["cat"], t["wd"]] for t in st["tx"]])
                session = M.Session(st, weight=case["weight"])
                self.assertEqual(js["dayOne"]["pred"], session.model.pred)
                self.assertEqual(js["dayOne"]["conf"], session.model.conf)  # bit-for-bit, not approximately
                py = M.compare_strategies(st, checks=case["checks"], target=case["target"], slip=case["slip"],
                                          weight=case["weight"])
                for a, b in zip(js["compare"], py):
                    self.assertEqual(a["strategy"], b["strategy"])
                    self.assertEqual(a["picks"], b["picks"])
                    self.assertEqual(a["toTarget"], b["toTarget"])
                    self.assertEqual(a["points"], json.loads(json.dumps(b["points"])))
                weekly = M.compare_weekly(st, per_week=case["perWeek"], slip=case["slip"], weight=case["weight"])
                self.assertEqual(js["weekly"], json.loads(json.dumps(weekly)))
                self.assertEqual(js["bands"], json.loads(json.dumps(M.confidence_bands(session))))
                s2 = M.Session(st, weight=case["weight"])
                s2.correct(3, 5)
                s2.correct(7, 1)
                s2.correct(3, 2)
                self.assertEqual(js["refiled"], {"conf": s2.model.conf, "order": s2.order, "checks": s2.checks})
                robust = M.robustness(case["persona"], 4, [case["seed"], case["seed"] + 1], checks=15,
                                      target=case["target"], slip=case["slip"], weight=case["weight"])
                self.assertEqual(js["robust"], json.loads(json.dumps(robust)))


if __name__ == "__main__":
    unittest.main()
