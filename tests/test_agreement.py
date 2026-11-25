"""Proves the browser app's model (run in Node.js) and the Python model agree.

Skipped when Node.js is not installed.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from missing_minutes import model as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = shutil.which("node")
TOL = 1e-9


def run_js(jobs):
    out = subprocess.run([NODE, os.path.join(HERE, "load_model.js")], input=json.dumps(jobs),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def custom_configs():
    """A few hand-made processes that exercise every kind of step."""
    yield {
        "name": "Mixed", "arrivalsPerDay": 18, "slaDays": 6, "measureDays": 60, "warmupDays": 10,
        "steps": [
            {"name": "Sort", "kind": "team", "staff": 1, "minutes": 14, "cv": 1.2},
            {"name": "Supplier", "kind": "delay", "share": 0.3, "minutes": 500, "cv": 0.5},
            {"name": "Panel", "kind": "batch", "batchDays": [0, 2, 4], "capacity": 12, "minutes": 9, "cv": 0.3},
            {"name": "Review", "kind": "team", "staff": 2, "minutes": 30, "cv": 0.8, "reworkTo": 0, "reworkRate": 0.2},
        ],
        "ai": {"step": 0, "saving": 0.6, "adoption": 0.9, "checkMinutes": 3, "errorRate": 0.15, "catchRate": 0.7},
    }
    yield {
        "name": "Overloaded", "arrivalsPerDay": 30, "measureDays": 40, "drainDays": 10,
        "steps": [{"name": "Only desk", "kind": "team", "staff": 1, "minutes": 16, "cv": 0.4}],
        "ai": {"step": 0, "saving": 0.1, "adoption": 0.5},
    }


def assert_close(test, a, b, path="result"):
    if isinstance(a, dict):
        test.assertEqual(sorted(a), sorted(b), path)
        for k in a:
            assert_close(test, a[k], b[k], path + "." + k)
    elif isinstance(a, list):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_close(test, x, y, "%s[%d]" % (path, i))
    elif isinstance(a, bool) or a is None or isinstance(a, str):
        test.assertEqual(a, b, path)
    else:
        test.assertLessEqual(abs(a - b), TOL * max(1.0, abs(a)), "%s: %r vs %r" % (path, a, b))


@unittest.skipUnless(NODE, "Node.js is not installed")
class Agreement(unittest.TestCase):
    def test_presets_agree(self):
        jobs, py = [], []
        for key in M.PRESETS:
            for seed in (1, 42):
                cfg = M.preset_config(key)
                jobs.append({"fn": "compare", "config": cfg, "seed": seed})
                py.append(M.compare(cfg, seed))
        for js, p in zip(run_js(jobs), py):
            assert_close(self, js, p)

    def test_custom_processes_agree(self):
        cfgs = list(custom_configs())
        js = run_js([{"fn": "compare", "config": c, "seed": 7} for c in cfgs])
        for j, c in zip(js, cfgs):
            assert_close(self, j, M.compare(c, 7))

    def test_lead_time_lists_agree(self):
        cfg = M.preset_config("loans")
        js = run_js([{"fn": "simulate", "config": cfg, "seed": 3, "opts": {"keepLeadTimes": True}}])[0]
        assert_close(self, js, M.simulate(cfg, 3, keep_lead_times=True))

    def test_normalise_and_validate_agree(self):
        odd = [
            {"steps": []},
            {"arrivalsPerDay": "abc", "steps": [{"kind": "batch", "batchDays": [5, 2, 2]}], "ai": {"step": 3}},
            {"steps": [{"kind": "delay", "minutes": -1, "reworkTo": 0}, {"staff": 0, "reworkTo": 0, "reworkRate": 0.9}], "ai": {"step": 0}},
            M.preset_config("claims"),
        ]
        js = run_js([{"fn": "normalise", "config": c} for c in odd] + [{"fn": "validate", "config": c} for c in odd])
        n = len(odd)
        for i, c in enumerate(odd):
            self.assertEqual(js[i], M.normalise(c))
            self.assertEqual(js[n + i], M.validate(M.normalise(c)))


if __name__ == "__main__":
    unittest.main()
