"""Tests for the command line, the CSV export and the audit of an export."""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path

from fittotrain import audit, crmcsv, model
from fittotrain.__main__ import main

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(list(args))
    return buf.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lab_text_and_json(self):
        text = run_cli("lab", "--preset", "typical", "--seed", "4", "--deals", "1500")
        self.assertIn("Pilot illusion", text)
        data = json.loads(run_cli("lab", "--json", "--seed", "4", "--deals", "1500", "--set", "zombies=0.6"))
        self.assertEqual(data["settings"]["zombies"], 0.6)
        self.assertNotIn("crm", data)
        direct = model.run_lab({"seed": 4, "deals": 1500, "zombies": 0.6})
        self.assertAlmostEqual(data["live"]["auc"], direct["live"]["auc"], places=12)

    def test_bad_set_option_is_explained(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli("lab", "--set", "nonsense=1")
        self.assertIn("unknown defect", str(ctx.exception))
        with self.assertRaises(SystemExit):
            run_cli("lab", "--set", "zombies=lots")

    def test_generate_then_audit_round_trip(self):
        out = self.dir / "crm.csv"
        truth = self.dir / "truth.csv"
        run_cli("generate", "--preset", "typical", "--seed", "3", "--deals", "2000", "-o", str(out), "--truth", str(truth))
        crm = model.build_crm(model.generate_world(dict(model.PRESETS["typical"], seed=3, deals=2000)))
        with open(out, newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), len(crm["history"]))
        self.assertEqual(list(rows[0].keys()), crmcsv.COLUMNS)
        records, info = crmcsv.read_export(out)
        self.assertEqual(info["bad_amounts"], 0)
        a = audit.audit_export(records, info, as_of=model.BASE_DATE + timedelta(days=model.GO_LIVE), seed=3)
        direct = model.audit_crm(crm)
        for got, want in zip(a["rows"], direct["rows"][:5]):
            self.assertEqual(got["key"], want["key"])
            self.assertAlmostEqual(got["value"], want["value"], places=12)
        bt = a["backtests"]
        self.assertLess(bt["repaired"]["auc"], bt["random"]["auc"] - 0.05)
        lab = model.run_lab(dict(model.PRESETS["typical"], seed=3, deals=2000), fixes=False)
        self.assertEqual(bt["steps"], lab["repaired"]["steps"])
        self.assertAlmostEqual(bt["repaired"]["auc"], lab["repaired"]["backtest"]["auc"], places=12)
        self.assertAlmostEqual(bt["random"]["auc"], lab["backtest"]["auc"], places=12)
        suspects = {fs["field"] for fs in a["fieldSignal"] if fs["suspect"]}
        self.assertIn("champion", suspects)
        self.assertNotIn("discount", suspects)
        with open(truth, newline="") as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), len(rows))

    def test_audit_text_runs_from_the_command_line(self):
        out = self.dir / "crm.csv"
        run_cli("generate", "--seed", "5", "--deals", "1000", "-o", str(out))
        text = run_cli("audit", str(out))
        self.assertIn("readiness audit", text)
        self.assertIn("Leak check", text)
        data = json.loads(run_cli("audit", str(out), "--json", "--as-of", "2025-06-24"))
        self.assertEqual(data["asOf"], "2025-06-24")

    def test_minimal_export_with_messy_values(self):
        p = self.dir / "mini.csv"
        p.write_text(
            "opportunity_id,account_name,created_date,close_date,status,amount\n"
            "A1,North Co,2025-01-01,2025-02-01,Closed Won,\"12,000\"\n"
            "A2,North Co,2025-01-05,2025-02-10,closed_lost,\n"
            "A3,South Co,2025-01-09,2025-01-20,open,0\n"
            ",,,,,\n", encoding="utf-8")
        records, info = crmcsv.read_export(p)
        self.assertEqual(len(records), 3)
        self.assertEqual([r["status"] for r in records], ["won", "lost", "open"])
        self.assertEqual(info["bad_amounts"], 2)
        self.assertTrue(all(r["stakeholders"] is None for r in records))
        a = audit.audit_export(records, info)
        self.assertEqual(a["rows"][0]["key"], "amounts")
        self.assertIsNone(a["backtests"]["random"])
        self.assertIsNone(a["fieldSignal"])
        text = run_cli("audit", str(p))
        self.assertIn("Not enough closed deals", text)

    def test_record_keys(self):
        self.assertEqual(crmcsv.record_key("D-42"), 42)
        self.assertEqual(crmcsv.record_key("R-42"), 1000042)
        self.assertEqual(crmcsv.record_key("OPP-0001"), crmcsv.record_key("OPP-0001"))
        self.assertNotEqual(crmcsv.record_key("OPP-0001"), crmcsv.record_key("OPP-0002"))
        self.assertTrue(0 <= crmcsv.record_key("\u00e9t\u00e9-7") < 2 ** 32)

    def test_unreadable_exports_fail_clearly(self):
        bad = self.dir / "bad.csv"
        bad.write_text("id,name\n1,x\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            run_cli("audit", str(bad))
        self.assertIn("missing required column", str(ctx.exception))
        bad.write_text("opportunity_id,account_name,created_date,close_date,status,amount\n1,x,01/02/2025,2025-03-01,won,5\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            run_cli("audit", str(bad))
        self.assertIn("YYYY-MM-DD", str(ctx.exception))
        bad.write_text("opportunity_id,account_name,created_date,close_date,status,amount\n1,x,2025-01-02,2025-03-01,maybe,5\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            run_cli("audit", str(bad))
        self.assertIn("won, lost or open", str(ctx.exception))
        with self.assertRaises(SystemExit):
            run_cli("audit", str(self.dir / "missing.csv"))

    def test_settings_file_from_the_browser_app(self):
        f = self.dir / "fit-to-train-settings.json"
        f.write_text(json.dumps({"app": "fit-to-train", "version": 1, "settings": {
            "seed": 7, "deals": 1500, "blanks": 0, "retrofill": 0.5, "zombies": 0.2, "recreated": 0,
            "placeholders": 0, "loggingShift": 0}}), encoding="utf-8")
        data = json.loads(run_cli("lab", "--json", "--settings", str(f)))
        self.assertEqual(data["settings"]["seed"], 7)
        self.assertEqual(data["settings"]["retrofill"], 0.5)
        flat = self.dir / "flat.json"
        flat.write_text(json.dumps({"zombies": 0.7}), encoding="utf-8")
        data = json.loads(run_cli("lab", "--json", "--settings", str(flat), "--deals", "1000", "--set", "blanks=0.1"))
        self.assertEqual((data["settings"]["zombies"], data["settings"]["blanks"]), (0.7, 0.1))
        bad = self.dir / "bad.json"
        bad.write_text("{\"hello\": 1}", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            run_cli("lab", "--settings", str(bad))
        self.assertIn("not a Fit to train settings file", str(ctx.exception))
        bad.write_text("not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            run_cli("lab", "--settings", str(bad))

    def test_lab_on_several_worlds(self):
        text = run_cli("lab", "--worlds", "2", "--deals", "1000", "--preset", "typical")
        self.assertIn("the same settings on 2 other worlds", text)
        self.assertIn("one to fix first", text)
        data = json.loads(run_cli("lab", "--worlds", "2", "--deals", "1000", "--json"))
        self.assertEqual(len(data["worlds"]), 2)
        self.assertEqual(sum(data["fixWinners"]["live"].values()), 2)

    def test_sweep_writes_csv_and_html(self):
        out = self.dir / "reports"
        text = run_cli("sweep", "zombies", "--levels", "3", "--worlds", "1", "--deals", "1000", "--out", str(out))
        self.assertIn("sweep of zombie deals", text)
        with open(out / "sweep_zombies.csv", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([float(r["level"]) for r in rows], [0.0, 0.4, 0.8])
        page = (out / "sweep_zombies.html").read_text(encoding="utf-8")
        self.assertIn("<svg", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http", page.replace("http-equiv", ""))

    def test_module_entry_point(self):
        res = subprocess.run([sys.executable, "-m", "fittotrain", "lab", "--deals", "1000"], cwd=ROOT,
                             capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Ranking score", res.stdout)


if __name__ == "__main__":
    unittest.main()
