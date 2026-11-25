"""Tests for the portfolio allocator, the reports and the command line."""

import contextlib
import csv
import io
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from assurance_mix import model as M
from assurance_mix import portfolio, report
from assurance_mix.__main__ import main

from helpers import ROOT

INVENTORY = ROOT / "examples" / "inventory.csv"


def run_cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(args))
    return code, out.getvalue()


class PortfolioTests(unittest.TestCase):
    def test_reads_inventory(self):
        systems, notes = portfolio.read_inventory(INVENTORY)
        self.assertEqual(len(systems), 8)
        self.assertEqual(notes, [])
        self.assertEqual(systems[-1]["raw"]["exclude"], "redteam")
        self.assertEqual(systems[-1]["raw"]["weeks"], "12")

    def test_messy_inventory(self):
        text = "Name,STAKES,colour,model\nA,shapes,blue,genai\n,,,\nB,banana,,ml\n"
        systems, notes = portfolio.read_inventory(text, is_text=True)
        self.assertEqual([s["name"] for s in systems], ["A", "B"])
        self.assertTrue(any("colour" in n for n in notes))
        alloc = portfolio.allocate(systems, 100, 8)
        self.assertTrue(any('Unknown answer "banana"' in n for n in alloc["notes"]))

    def test_optimal_matches_brute_force(self):
        systems, _ = portfolio.read_inventory(INVENTORY)
        systems = systems[:4]
        for budget in (60, 150, 260):
            alloc = portfolio.allocate(systems, budget, 8)
            opt = alloc["optimal"]
            self.assertLessEqual(opt["cost"], budget)
            fronts = [r["frontier"] for r in alloc["systems"]]
            best = None
            for combo in itertools.product(*fronts):
                cost = sum(p["cost"] for p in combo)
                if cost > budget:
                    continue
                key = (sum(1 for p in combo if p["worst"] > 8 + M.EPS), sum(p["worst"] for p in combo), cost)
                if best is None or key < best:
                    best = key
            self.assertEqual((opt["above"], opt["cost"]), (best[0], best[2]))
            self.assertAlmostEqual(opt["totalWorst"], best[1], places=9)

    def test_optimal_beats_or_ties_baselines(self):
        systems, _ = portfolio.read_inventory(INVENTORY)
        for budget in (100, 250, 400, 700):
            alloc = portfolio.allocate(systems, budget, 8)
            o = alloc["optimal"]
            for b in alloc["baselines"].values():
                if b is None:
                    continue
                self.assertLessEqual(b["cost"], budget + 1e-9)
                self.assertLessEqual((o["above"], round(o["totalWorst"], 9)), (b["above"], round(b["totalWorst"], 9)))

    def test_budget_too_small(self):
        systems, _ = portfolio.read_inventory(INVENTORY)
        alloc = portfolio.allocate(systems, 5, 8)
        self.assertIsNone(alloc["optimal"])
        self.assertTrue(any("does not cover" in n for n in alloc["notes"]))
        self.assertIn("No allocation is possible", report.portfolio_report(alloc))


class ReportAndCliTests(unittest.TestCase):
    def test_plan_report_example(self):
        code, out = run_cli("plan", "--example", "shortlister")
        self.assertEqual(code, 0)
        self.assertIn("Cheapest plan that meets your appetite: £105k, 11 techniques, live in 9 weeks", out)
        self.assertIn("Not legal advice".lower(), out.lower())
        self.assertIn("From pilot to scale", out)
        self.assertIn("Limited roll-out (now)", out)

    def test_plan_file_and_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sys.json"
            f.write_text(json.dumps({"name": "Test system", "answers": M.DATA["examples"][3]["answers"]}), encoding="utf-8")
            md = Path(d) / "plan.md"
            code, out = run_cli("plan", str(f), "--appetite", "2", "--markdown", str(md))
            self.assertEqual(code, 0)
            self.assertIn("No plan meets your appetite of 2.0", out)
            text = md.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Assurance mix: Test system"))
            self.assertIn("| Technique | Stage | Cost | Why it is there |", text)

    def test_plan_json(self):
        code, out = run_cli("plan", "--example", "policy", "--json")
        data = json.loads(out)
        self.assertEqual(data["cheapest"]["ids"], ["dpia"])

    def test_bad_inputs(self):
        with self.assertRaises(SystemExit):
            run_cli("plan", "--example", "nope")
        with self.assertRaises(SystemExit):
            run_cli("plan", str(ROOT / "missing.json"))

    def test_portfolio_cli_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            md, cs = Path(d) / "p.md", Path(d) / "p.csv"
            code, out = run_cli("portfolio", str(INVENTORY), "--budget", "400", "--markdown", str(md), "--csv", str(cs))
            self.assertEqual(code, 0)
            self.assertIn("Optimised", out)
            with cs.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0][0], "system")
            self.assertEqual(len(rows), 1 + 8 * 4)
            self.assertIn("| Approach |", md.read_text(encoding="utf-8"))

    def test_techniques_cli(self):
        code, out = run_cli("techniques")
        self.assertIn("Formal verification", out)

    def test_rounding_matches_app(self):
        self.assertEqual(report.sc(7.85), "7.9")
        self.assertEqual(report.sc(0.05), "0.1")
        self.assertEqual(report.pct(0.004), "<1%")
        self.assertEqual(report.money(1234.4), "£1,234k")


if __name__ == "__main__":
    unittest.main()
