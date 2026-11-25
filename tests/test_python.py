"""Tests for the Python companion: model properties and the command-line tool."""

import contextlib
import csv
import io
import itertools
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from whatwouldittake import cli  # noqa: E402
from whatwouldittake import model as M  # noqa: E402

TRAIN = M.generate_cohort(M.DEFAULTS["nTrain"], M.DEFAULTS["trainSeed"])
MODEL = M.train_model(TRAIN)
TABLES = M.cost_tables(TRAIN)
COHORT = M.generate_cohort(M.DEFAULTS["nAudit"], M.DEFAULTS["auditSeed"])


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


def brute_force(x, settings, max_levers=M.D):
    ranges = []
    for j, f in enumerate(M.FEATURES):
        s = settings[j]
        if not s["actionable"] or s["cap"] <= 0:
            ranges.append([x[j]])
        elif f["dir"] > 0:
            ranges.append(range(x[j], min(f["max"], x[j] + s["cap"]) + 1))
        else:
            ranges.append(range(x[j], max(f["min"], x[j] - s["cap"]) - 1, -1))
    best = None
    for z in itertools.product(*ranges):
        if sum(1 for a, b in zip(z, x) if a != b) > max_levers:
            continue
        if M.predict(MODEL, list(z)) >= MODEL["threshold"]:
            c = sum(M.feature_cost(TABLES, settings, j, x[j], z[j]) for j in range(M.D))
            if best is None or c < best - 1e-12:
                best = c
    return best


class ModelTest(unittest.TestCase):
    def test_quota(self):
        self.assertEqual(sum(r["y"] for r in TRAIN), round(0.38 * 1600))

    def test_accuracy(self):
        ok = sum(1 for r in COHORT if (M.predict(MODEL, r["x"]) >= 0.5) == (r["y"] == 1))
        self.assertGreater(ok / len(COHORT), 0.75)

    def test_recourse_is_exact(self):
        settings = M.default_settings()
        rejected = [r for r in COHORT if M.predict(MODEL, r["x"]) < 0.5][:12]
        for r in rejected:
            res = M.find_recourse(MODEL, TABLES, r["x"], settings, max_levers=2)
            bf = brute_force(r["x"], settings, max_levers=2)
            if bf is None:
                self.assertEqual(res["status"], "none")
            else:
                self.assertAlmostEqual(res["cost"], bf, places=9)

    def test_shapley_efficiency(self):
        bg = M.background_sample(TRAIN, 64)
        for p in M.PRESETS:
            sh = M.shapley(MODEL, p["x"], bg)
            self.assertAlmostEqual(sum(sh["phi"]), sh["value"] - sh["base"], places=9)

    def test_audit_counts(self):
        a = M.audit(MODEL, TABLES, COHORT, M.default_settings())
        self.assertEqual(sum(g["n"] for g in a["groups"]), len(COHORT))
        for g in a["groups"]:
            self.assertEqual(g["shortlisted"] + g["rejected"], g["n"])


class CliTest(unittest.TestCase):
    def test_explain_preset(self):
        code, out = run_cli("explain", "--preset", "Near miss")
        self.assertEqual(code, 0)
        self.assertIn("Not shortlisted", out)
        self.assertIn("Route A", out)

    def test_explain_values_and_rules(self):
        code, out = run_cli("explain", "--test", "62", "--experience", "9", "--projects", "3", "--certs", "1",
                            "--degree", "Third", "--gap", "3", "--fix", "test", "--weight", "experience=2")
        self.assertEqual(code, 0)
        self.assertNotIn("Test score 62 points to", out)

    def test_explain_rejects_bad_values(self):
        with self.assertRaises(SystemExit):
            run_cli("explain", "--preset", "Near miss", "--test", "140")
        with self.assertRaises(SystemExit):
            run_cli("explain", "--preset", "Near miss", "--degree", "Distinction")
        with self.assertRaises(SystemExit):
            run_cli("explain", "--preset", "Nobody")
        with self.assertRaises(SystemExit):
            run_cli("explain", "--preset", "Near miss", "--cap", "test")

    def test_sample_plans_audit_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "applicants.csv")
            dst = os.path.join(d, "plans.csv")
            rep = os.path.join(d, "audit.md")
            run_cli("sample", "--n", "25", "--out", src)
            code, out = run_cli("plans", src, "--out", dst)
            self.assertEqual(code, 0)
            with open(dst, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 25)
            for row in rows:
                if row["decision"] == "shortlisted":
                    self.assertEqual(row["route_status"], "already")
                elif row["routes"] != "0":
                    self.assertGreaterEqual(float(row["cheapest_new_score"]), 0.5)
            code, _ = run_cli("audit", "--csv", src, "--out", rep)
            self.assertEqual(code, 0)
            with open(rep, encoding="utf-8") as fh:
                self.assertIn("| Shortlisted |", fh.read())

    def test_plans_reports_bad_csv(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bad.csv")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("test,experience\n50,3\n")
            with self.assertRaises(SystemExit) as e:
                run_cli("plans", src)
            self.assertIn("missing column", str(e.exception))
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("test,experience,projects,certs,degree,gap\n50,3,1,1,2:1,abc\n")
            with self.assertRaises(SystemExit) as e:
                run_cli("plans", src)
            self.assertIn("line 2", str(e.exception))

    def test_hold_report_and_raw_csv(self):
        with tempfile.TemporaryDirectory() as d:
            rep = os.path.join(d, "hold.md")
            raw = os.path.join(d, "raw.csv")
            code, _ = run_cli("hold", "--retrains", "2", "--points", "0", "3", "--out", rep, "--raw", raw)
            self.assertEqual(code, 0)
            with open(rep, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("+1.5 months of experience", text)
            self.assertIn("| +0.3 |", text)
            with open(raw, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2 * 2 * len(M.MARGINS) * 3)
            for row in rows:
                self.assertLessEqual(int(row["kept"]), int(row["routes"]))
                self.assertLessEqual(int(row["routes"]), int(row["rejected"]))

    def test_hold_rejects_bad_arguments(self):
        for argv in (["--retrains", "0"], ["--points", "9"], ["--target", "1.5"]):
            with self.assertRaises(SystemExit):
                run_cli("hold", *argv)

    def test_audit_synthetic(self):
        code, out = run_cli("audit", "--n", "120")
        self.assertEqual(code, 0)
        self.assertIn("First in family at university", out)


if __name__ == "__main__":
    unittest.main()
