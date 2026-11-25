"""The browser app's model (run in Node.js) and the Python port must agree.

Every calculation follows the same order in both languages and avoids
functions whose last digit can differ between them (exp, log, sin), so
results are compared exactly, not just to a tolerance.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from whatwouldittake import model as M  # noqa: E402

NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "Node.js is not installed")
class AgreementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.run([NODE, os.path.join(ROOT, "tests", "dump_js.js")], check=True,
                             capture_output=True, text=True).stdout
        cls.js = json.loads(raw)
        cls.train = M.generate_cohort(M.DEFAULTS["nTrain"], M.DEFAULTS["trainSeed"])
        cls.model = M.train_model(cls.train)
        cls.tables = M.cost_tables(cls.train)
        cls.background = M.background_sample(cls.train, 64)
        cls.cohort = M.generate_cohort(M.DEFAULTS["nAudit"], M.DEFAULTS["auditSeed"])
        cls.settings = M.default_settings()
        cls.tight = M.default_settings()
        cls.tight[0]["weight"] = 2
        cls.tight[1]["cap"] = 6
        cls.tight[4]["actionable"] = True
        cls.tight[5]["actionable"] = True

    def test_features_and_presets(self):
        self.assertEqual(self.js["features"], M.FEATURES)
        self.assertEqual(self.js["presets"], M.PRESETS)

    def test_random_numbers(self):
        r = M.mulberry32(2026)
        self.assertEqual(self.js["randoms"], [r() for _ in range(50)])

    def test_cohorts(self):
        self.assertEqual(self.js["trainLabels"], [r["y"] for r in self.train])
        self.assertEqual(self.js["trainX"], [r["x"] for r in self.train[:200]])
        strong = M.generate_cohort(300, 47, 0.7)
        self.assertEqual(self.js["strongX"], [[r["x"], r["g"], r["y"]] for r in strong])

    def test_model(self):
        self.assertEqual(self.js["base"], self.model["base"])
        self.assertEqual(self.js["splits"], self.model["splits"])
        self.assertEqual(self.js["tables"], self.tables)
        self.assertEqual(self.js["preds"], [M.predict(self.model, r["x"]) for r in self.cohort])

    def _summary(self, r):
        return {"status": r["status"], "cost": r["cost"], "score": r["score"], "values": r["values"], "explored": r["explored"]}

    def test_recourse(self):
        py = [self._summary(M.find_recourse(self.model, self.tables, r["x"], self.settings)) for r in self.cohort[:80]]
        self.assertEqual(self.js["recourse"], py)
        py = [self._summary(M.find_recourse(self.model, self.tables, r["x"], self.tight, margin=0.04, max_levers=2))
              for r in self.cohort[80:140]]
        self.assertEqual(self.js["recourseTight"], py)

    def test_options(self):
        for p, js in zip(M.PRESETS, self.js["options"]):
            o = M.recourse_options(self.model, self.tables, p["x"], self.settings)
            self.assertEqual(js["status"], o["status"], p["name"])
            self.assertEqual(js["options"], [{"cost": q["cost"], "values": q["values"], "lever": q["lever"], "mask": q["mask"]}
                                             for q in o["options"]], p["name"])

    def test_shapley(self):
        for p, js in zip(M.PRESETS, self.js["shapley"]):
            self.assertEqual(js, M.shapley(self.model, p["x"], self.background), p["name"])

    def test_audit(self):
        self.assertEqual(self.js["audit"], M.audit(self.model, self.tables, self.cohort, self.settings)["groups"])
        self.assertEqual(self.js["auditTight"],
                         M.audit(self.model, self.tables, self.cohort, self.tight, margin=0.04, max_levers=2)["groups"])

    def test_hold(self):
        self.assertEqual(self.js["margins"], M.MARGINS)
        self.assertEqual(self.js["nextSplits"], M.next_model(3 / 6, 2)["splits"])
        table = M.route_table(self.model, self.tables, self.cohort[:200], self.tight, M.MARGINS, max_levers=3)
        self.assertEqual(self.js["hold"], M.hold_summary(M.next_model(3 / 6, 2), self.cohort[:200], table, M.MARGINS))


if __name__ == "__main__":
    unittest.main()
