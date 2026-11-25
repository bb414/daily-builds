"""Tests for the Python companion: model, jobs CSV and command-line tool.

Run from the repository root with: python -m unittest discover -s tests
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cleanhours import cli, jobs_csv, model, report  # noqa: E402


def cfg(**over):
    c = dict(model.DEFAULT_CONFIG)
    c.update(over)
    return c


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {p: model.run(cfg(preset=p)) for p in model.PRESETS}

    def test_dispatch_balances_and_orders(self):
        p = model.PRESETS["windy"]
        for D, W, S in [(25, 30, 0), (30, 0, 0), (42, 0, 0), (60, 0, 0), (18, 5, 5)]:
            o = model.dispatch(p, D, W, S)
            gen = o["nuclear"] + o["wind"] + o["solar"] + sum(o["thermal"]) + o["shortfall"]
            self.assertAlmostEqual(gen, D, places=9)
        self.assertEqual(model.dispatch(p, 25, 30, 0)["code"], 0)
        self.assertEqual(model.dispatch(p, 30, 0, 0)["code"], 1)
        self.assertEqual(model.dispatch(p, 42, 0, 0)["code"], 2)
        self.assertEqual(model.dispatch(p, 60, 0, 0)["code"], 3)

    def test_perfect_forecast_matches_actual(self):
        c = cfg(forecastError=0)
        g = model.simulate_grid(c)
        f = model.forecast(g, c, 2000, 48)
        self.assertEqual(f["avg"], g["avg"][2000:2048])
        self.assertEqual(f["marg"], g["marg"][2000:2048])

    def test_hindsight_is_best_on_real_emissions(self):
        for res in self.results.values():
            best = res["policies"]["oracle"]["real"]
            for key in model.POLICY_KEYS:
                self.assertLessEqual(best, res["policies"][key]["real"] + 1e-9)

    def test_three_stories(self):
        self.assertEqual(self.results["windy"]["policies"]["avg"]["verdict"], "understates")
        self.assertEqual(self.results["sunny"]["policies"]["avg"]["verdict"], "overstates")
        self.assertEqual(self.results["coal"]["policies"]["avg"]["verdict"], "backfires")

    def test_no_flexibility_changes_nothing(self):
        res = model.run(cfg(slack=0))
        for key in model.POLICY_KEYS:
            self.assertEqual(res["policies"][key]["real"], res["policies"]["now"]["real"])

    def test_grid_summary_is_plausible(self):
        s = self.results["windy"]["summary"]
        self.assertTrue(0 < s["curtailShare"] < 0.5)
        self.assertTrue(50 < s["weightedAvg"] < 400)
        self.assertEqual(sum(s["hoursByCode"]), model.HOURS)

    def test_validation(self):
        self.assertEqual(model.validate_jobs(model.DEFAULT_JOBS), [])
        self.assertTrue(model.validate_jobs([]))
        bad = dict(model.DEFAULT_JOBS[1], hours=10, window=5)
        self.assertIn("window", model.validate_jobs([bad])[0])
        self.assertTrue(model.validate_jobs([dict(model.DEFAULT_JOBS[1], mw=True)]))


class JobsCsvTests(unittest.TestCase):
    def test_round_trip(self):
        text = jobs_csv.format_jobs(model.DEFAULT_JOBS)
        self.assertEqual(jobs_csv.parse_jobs(text), model.DEFAULT_JOBS)

    def test_errors(self):
        with self.assertRaises(jobs_csv.JobsError):
            jobs_csv.parse_jobs("")
        with self.assertRaises(jobs_csv.JobsError):
            jobs_csv.parse_jobs("name,mw\nx,1\n")
        header = ",".join(jobs_csv.COLUMNS)
        with self.assertRaises(jobs_csv.JobsError):
            jobs_csv.parse_jobs(header + "\nA,two,4,1,0,18,14,yes\n")
        with self.assertRaises(jobs_csv.JobsError):
            jobs_csv.parse_jobs(header + "\nA,2,4,1,0,18,14,maybe\n")
        with self.assertRaises(jobs_csv.JobsError):
            jobs_csv.parse_jobs(header + "\nA,2,4,1,0,18,3,yes\n")

    def test_blank_lines_and_bom(self):
        header = ",".join(jobs_csv.COLUMNS)
        jobs = jobs_csv.parse_jobs("﻿" + header + "\nA,2,4,1,0,18,14,Yes\n,,,,,,,\n")
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["pausable"])


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_run_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli("run", "--preset", "sunny", "--out", d)
            self.assertEqual(code, 0)
            self.assertIn("overstates its benefit", out)
            for f in ["summary.md", "schedulers.csv", "jobs.csv", "grid_hours.csv"]:
                self.assertTrue(os.path.exists(os.path.join(d, f)), f)
            with open(os.path.join(d, "grid_hours.csv")) as fh:
                self.assertEqual(sum(1 for _ in fh), model.HOURS + 1)

    def test_template_then_run_with_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "jobs.csv")
            self.run_cli("template", "--out", path)
            code, out = self.run_cli("run", "--jobs", path, "--preset", "coal")
            self.assertEqual(code, 0)
            self.assertIn("raises real emissions", out)

    def test_sweep(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli("sweep", "--presets", "windy", "--seeds", "1-2", "--slack", "0,1", "--out", d, "--quiet")
            self.assertEqual(code, 0)
            with open(os.path.join(d, "sweep.csv")) as fh:
                self.assertEqual(sum(1 for _ in fh), 1 + 2 * 2 * 4)
            self.assertIn("| Windy island | Hindsight best | 4 |", out)

    def test_bad_input_exits_cleanly(self):
        with self.assertRaises(SystemExit):
            self.run_cli("run", "--jobs", "/no/such/file.csv")
        with self.assertRaises(SystemExit):
            self.run_cli("run", "--slack", "9")
        with self.assertRaises(SystemExit):
            self.run_cli("run", "--seed", "0")
        with self.assertRaises(SystemExit):
            self.run_cli("sweep", "--presets", "mars")

    def test_formatting(self):
        self.assertEqual(report.tonnes(1234.4), "+1,234 t")
        self.assertEqual(report.tonnes(-0.4), "0 t")
        self.assertEqual(report.pct(0.1234), "+12.3%")
        self.assertEqual(report.pct(-0.0001), "0.0%")


if __name__ == "__main__":
    unittest.main()
