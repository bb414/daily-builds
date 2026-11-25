"""The browser app's model (run in Node.js) and the Python package must agree."""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from fittotrain import model

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
TOL = 1e-9

CASES = [
    {},
    {"seed": 1, "deals": 1000},
    {"seed": 99, "deals": 8000, "blanks": 0.6, "retrofill": 0.8, "zombies": 0.8, "recreated": 0.5,
     "placeholders": 0.8, "loggingShift": 0.7},
    dict(model.PRESETS["clean"], seed=7),
    dict(model.PRESETS["tidy"], seed=123456),
    dict(model.PRESETS["chaos"], seed=4294967295, deals=2500),
    {"seed": -42.7, "deals": "3333", "zombies": 9, "blanks": -1, "retrofill": "nonsense"},
]


def run_js(settings, worlds=None):
    args = [NODE, str(ROOT / "tests" / "run_model.js"), json.dumps(settings)] + ([str(worlds)] if worlds else [])
    out = subprocess.run(args,
                         capture_output=True, text=True, check=True, cwd=ROOT)
    return json.loads(out.stdout)


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=TOL, abs_tol=TOL)
    return a == b


def compare(test, js, py, path="result"):
    if isinstance(py, dict):
        test.assertIsInstance(js, dict, path)
        for k, v in py.items():
            if k in ("crm",):
                continue
            test.assertIn(k, js, "%s.%s missing from the browser result" % (path, k))
            compare(test, js[k], v, "%s.%s" % (path, k))
    elif isinstance(py, (list, tuple)):
        test.assertEqual(len(js), len(py), path)
        for i, (a, b) in enumerate(zip(js, py)):
            compare(test, a, b, "%s[%d]" % (path, i))
    else:
        test.assertTrue(close(js, py), "%s: browser %r vs Python %r" % (path, js, py))


@unittest.skipIf(NODE is None, "Node.js is not installed")
class TestParity(unittest.TestCase):
    def test_random_numbers_agree(self):
        js = run_js({})
        g = model.mulberry32(12345)
        compare(self, js["random"], [g() for _ in range(5)], "random")
        compare(self, js["mix"], [model.mix(0, 0), model.mix(2026, 1), model.mix(4294967295, 1000123)], "mix")

    def test_lab_results_agree(self):
        for case in CASES:
            with self.subTest(case=case):
                js = run_js(case)
                py = model.run_lab(case)
                py_view = {k: v for k, v in py.items() if k != "crm"}
                compare(self, js, py_view)

    def test_robustness_agrees(self):
        for case, n in (({"seed": 11, "deals": 1000}, 3), (dict(model.PRESETS["chaos"], seed=4294967294, deals=1200), 4)):
            with self.subTest(case=case):
                js = run_js(case, n)["robustness"]
                compare(self, js, model.robustness(case, n), "robustness")

    def test_records_agree(self):
        for case in CASES[:4]:
            with self.subTest(case=case):
                js = run_js(case)
                h = model.run_lab(case)["crm"]["history"]
                sample = h[:40] + h[-10:]
                for a, b in zip(js["sample"], sample):
                    compare(self, a, {k: v for k, v in b.items() if k != "truth"}, "record %s" % b["id"])


if __name__ == "__main__":
    unittest.main()
