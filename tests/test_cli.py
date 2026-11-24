import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from reliance_lab.__main__ import main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CommandLineTests(unittest.TestCase):
    def test_model_report(self):
        code, out, _ = run(["model"])
        self.assertEqual(code, 0)
        self.assertIn("Go with whoever is surer                       88.9%", out)
        self.assertIn("Out of every 100 cases", out)
        code, out, _ = run(["model", "--human", "0.8", "--ai", "0.8", "--rule", "fixed"])
        self.assertIn("Person alone 80.0%", out)
        self.assertIn('with "defer at a fixed rate"', out)

    def test_model_json(self):
        code, out, _ = run(["model", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertAlmostEqual(data["ceiling"], 0.88896, places=4)
        self.assertEqual(sum(data["per100"]["optimal"].values()), 100)

    def test_bad_input(self):
        code, _, err = run(["model", "--human", "nan"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)
        code, _, err = run(["sweep", "--margin", "-1"])
        self.assertEqual(code, 2)

    def test_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sweep.csv"
            page = Path(tmp) / "sweep.html"
            code, out, _ = run(["sweep", "--csv", str(path), "--html", str(page)])
            self.assertEqual(code, 0)
            self.assertIn("Sweep: 3888 combinations", out)
            self.assertEqual(len(path.read_text().strip().splitlines()), 3889)
            text = page.read_text()
            self.assertTrue(text.startswith("<!DOCTYPE html>"))
            self.assertIn("3,888 combinations", text)
            self.assertEqual(text.count('class="mini"'), 8)
            self.assertNotIn("http", text.replace('xmlns="http://www.w3.org/2000/svg"', ""))


if __name__ == "__main__":
    unittest.main()
