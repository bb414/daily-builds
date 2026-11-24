import contextlib
import io
import json
import os
import tempfile
import unittest

import helpers  # noqa: F401  (puts the project on the path)

from second_opinion.__main__ import main


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_synth_score_and_cohort(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "sessions")
            code, out, _ = run("synth", "--n", "12", "--advice", "verdict", "--advice", "reason", "--out", folder)
            self.assertEqual(code, 0)
            self.assertIn("Wrote 24 synthetic sessions", out)
            files = sorted(os.listdir(folder))
            self.assertEqual(len(files), 24)

            code, out, _ = run("score", os.path.join(folder, files[0]))
            self.assertEqual(code, 0)
            self.assertIn("Profile:", out)
            self.assertIn("The moments that mattered", out)
            self.assertIn("What if you had used a simple rule?", out)
            self.assertIn("best in hindsight", out)

            code, out, _ = run("score", "--json", os.path.join(folder, files[0]))
            self.assertEqual(code, 0)
            self.assertIn("reliance", json.loads(out))

            report = os.path.join(d, "report.html")
            code, out, _ = run("cohort", folder, "--html", report, "--resamples", "200", "--permutations", "200")
            self.assertEqual(code, 0)
            self.assertIn("cohort of 24 people", out)
            self.assertIn("Differences from advice: reason, feedback off", out)
            with open(report, encoding="utf-8") as f:
                page = f.read()
            self.assertIn("<svg", page)
            self.assertIn("Which simple rule would have served each group best?", page)
            self.assertIn("synthetic", page)
            self.assertNotIn("http://", page)
            self.assertNotIn("https://", page)

    def test_power(self):
        code, out, _ = run("power", "--sizes", "10,30", "--reps", "10", "--assume", "reason=1.2")
        self.assertEqual(code, 0)
        self.assertIn("People per arm", out)
        self.assertIn("reason +1.20", out)
        self.assertIn("planning aid", out)
        code, _, err = run("power", "--a", "shouting")
        self.assertEqual(code, 2)
        self.assertIn("advice style", err)
        code, _, err = run("power", "--sizes", "1")
        self.assertEqual(code, 2)
        code, _, err = run("power", "--assume", "reason")
        self.assertEqual(code, 2)
        code, _, err = run("power", "--alpha", "2")
        self.assertEqual(code, 2)

    def test_errors_are_friendly(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("[1, 2")
            code, _, err = run("score", bad)
            self.assertEqual(code, 2)
            self.assertIn("not valid JSON", err)
            code, _, err = run("cohort", os.path.join(d, "missing.json"))
            self.assertEqual(code, 2)
            code, _, err = run("cohort", d)
            self.assertEqual(code, 2)
            os.remove(bad)
            code, _, err = run("cohort", d)
            self.assertEqual(code, 1)
            self.assertIn("No sessions found", err)
            code, _, err = run("synth", "--n", "0", "--out", d)
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()


class RoundingTests(unittest.TestCase):
    def test_reports_round_like_the_app(self):
        from second_opinion.report import pct, signed_points
        self.assertEqual(pct(10 / 16), "63%")
        self.assertEqual(pct(0.125), "13%")
        self.assertEqual(pct(None), "n/a")
        self.assertEqual(signed_points(-0.0625), "-6 points")
        self.assertEqual(signed_points(0.005), "+1 point")
        self.assertEqual(signed_points(0.0), "0 points")
