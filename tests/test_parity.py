"""The browser app's model (run in Node.js) and the Python companion must agree exactly.

Skipped if Node.js is not installed.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cleanhours import jobs_csv, model  # noqa: E402

CONFIGS = [
    {},
    {"preset": "coal"},
    {"preset": "sunny", "seed": 7, "forecastError": 2.5, "slack": 1.75},
    {"preset": "windy", "seed": 23, "windScale": 2.5, "solarScale": 0.5, "forecastError": 0},
    {"preset": "coal", "seed": 4, "slack": 0},
    {"preset": "windy", "seed": 2, "windScale": 0.5, "slack": 3, "jobs": [
        {"name": "Odd one", "mw": 7.3, "hours": 30, "everyDays": 5, "firstDay": 2, "releaseHour": 23, "window": 200, "pausable": False},
        {"name": "Tiny", "mw": 0.2, "hours": 1, "everyDays": 1, "firstDay": 0, "releaseHour": 0, "window": 2, "pausable": True},
    ]},
]


CURVES = [
    {"config": {"preset": "windy"}, "field": "windScale", "values": [0.5, 1.25, 3]},
    {"config": {"preset": "sunny", "seed": 3}, "field": "slack", "values": [0, 0.5, 2.75]},
]


ROBUST = {"config": {"preset": "coal", "slack": 1.5}, "seeds": [1, 2, 3, 4]}
EXPLAIN = {"config": {"preset": "sunny", "forecastError": 1.5}, "indices": [0, 400, 1100, 1200]}
CSV_JOBS = model.DEFAULT_JOBS + [
    {"name": 'Name with, a comma and "quotes"', "mw": 0.1 + 0.2, "hours": 3, "everyDays": 2, "firstDay": 1,
     "releaseHour": 5, "window": 9, "pausable": True},
]


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = {"configs": CONFIGS, "curves": CURVES, "robustness": ROBUST, "explain": EXPLAIN,
                   "csvJobs": CSV_JOBS}
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "js_run.js")], input=json.dumps(payload),
                             capture_output=True, text=True, check=True).stdout
        cls.js = json.loads(out)

    def test_identical_curves(self):
        for spec, js in zip(CURVES, self.js["curves"]):
            c = dict(model.DEFAULT_CONFIG)
            c.update(spec["config"])
            with self.subTest(field=spec["field"]):
                self.assertEqual(js, model.curve(c, spec["field"], spec["values"]))

    def test_identical_robustness(self):
        c = dict(model.DEFAULT_CONFIG)
        c.update(ROBUST["config"])
        self.assertEqual(self.js["robustness"], model.robustness(c, ROBUST["seeds"]))

    def test_identical_run_explanations(self):
        c = dict(model.DEFAULT_CONFIG)
        c.update(EXPLAIN["config"])
        res = model.run(c)
        for i, js in zip(EXPLAIN["indices"], self.js["explain"]):
            with self.subTest(index=i):
                self.assertEqual(js, model.explain_run(res, i))

    def test_jobs_csv_is_interchangeable(self):
        self.assertEqual(self.js["csvText"], jobs_csv.format_jobs(CSV_JOBS))
        self.assertEqual(self.js["csvParsed"], jobs_csv.parse_jobs(self.js["csvText"]))
        self.assertEqual(jobs_csv.parse_jobs(self.js["csvText"]), CSV_JOBS)

    def test_same_presets_and_jobs(self):
        self.assertEqual(self.js["presets"], model.PRESETS)
        self.assertEqual(self.js["jobs"], model.DEFAULT_JOBS)

    def test_identical_results(self):
        for over, js in zip(CONFIGS, self.js["results"]):
            c = dict(model.DEFAULT_CONFIG)
            c.update(over)
            py = model.run(c)
            with self.subTest(config=over):
                self.assertEqual(js["instances"], py["instances"])
                self.assertEqual(js["summary"], py["summary"])
                for key in ["avg", "marg", "code", "demand", "curtail"]:
                    self.assertEqual(js["grid"][key], py["grid"][key], key)
                for key in model.POLICY_KEYS:
                    a, b = js["policies"][key], py["policies"][key]
                    self.assertEqual(sorted(a), sorted(b))
                    for field in a:
                        self.assertEqual(a[field], b[field], "%s.%s" % (key, field))


if __name__ == "__main__":
    unittest.main()
