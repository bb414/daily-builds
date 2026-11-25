"""Tests for the command-line interface."""

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from missing_minutes import model as M  # noqa: E402
from missing_minutes.cli import main  # noqa: E402


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(list(argv))
    return buf.getvalue()


class Cli(unittest.TestCase):
    def test_run_prints_a_report(self):
        out = run("run", "--preset", "loans", "--seed", "42")
        self.assertIn("Where the minutes went", out)
        self.assertIn("Credit committee", out)
        self.assertIn("Change in end-to-end time", out)

    def test_run_json_matches_the_model(self):
        out = json.loads(run("run", "--preset", "claims", "--seed", "5", "--json"))
        self.assertEqual(out["total"], M.compare(M.preset_config("claims"), 5)["total"])

    def test_export_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            run("export", "--preset", "complaints", "--out", path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), M.preset_config("complaints"))
            out = json.loads(run("run", "--config", path, "--seed", "1", "--json"))
            self.assertEqual(out["total"], M.compare(M.preset_config("complaints"), 1)["total"])

    def test_sweep_writes_one_row_per_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.csv")
            run("sweep", "--preset", "claims", "--param", "adoption", "--values", "0.25:0.75:0.25", "--out", path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([float(r["adoption"]) for r in rows], [0.25, 0.5, 0.75])
        self.assertTrue(all(r["all_cases_finished"] == "True" for r in rows))

    def test_rank_lists_every_option_and_writes_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.csv")
            out = run("rank", "--preset", "complaints", "--out", path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertIn("(current)", out)
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(r["current"] == "True" for r in rows), 1)

    def test_run_reports_banking_the_saving(self):
        out = run("run", "--preset", "claims", "--cut", "1")
        self.assertIn("Cut 1 of 5 people", out)

    def test_bad_config_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            cfg = M.preset_config("claims")
            cfg["ai"]["step"] = 3
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            with self.assertRaises(SystemExit) as ctx:
                run("run", "--config", path)
            self.assertIn("cannot sit on a wait", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
