"""Tests for the Python package beyond agreement with the app: command line and key rulings."""

import contextlib
import csv
import io
import json
import pathlib
import tempfile
import unittest

from ai_act_triage import model, register
from ai_act_triage.__main__ import main

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class RulingTests(unittest.TestCase):
    def test_key_rulings(self):
        self.assertEqual(model.classify({"annex3": "employment"})["tier"], "highRisk")
        self.assertEqual(model.classify({"role": "provider", "annex3": "employment", "derogation": "preparatory"})["tier"], "exempt63")
        self.assertEqual(model.classify({"prohibited": ["socialScoring"]})["tier"], "prohibited")
        self.assertEqual(model.classify({"role": "provider", "interacts": True})["tier"], "transparency")
        self.assertEqual(model.classify({})["tier"], "minimal")
        self.assertEqual(model.classify({"eu": False})["tier"], "outOfScope")

    def test_rules_file_is_consistent(self):
        keys = set(model.RULES["dates"])
        for p in model.RULES["prohibitions"]:
            self.assertIn(p["dateKey"], keys)
        for o in model.RULES["obligations"]:
            if "dateKey" in o:
                self.assertIn(o["dateKey"], keys)
            self.assertIn(o["role"], ("provider", "deployer", "both"))
        for d in model.RULES["dates"].values():
            self.assertTrue(model.valid_iso(d["amended"]))
            self.assertTrue(d["original"] is None or model.valid_iso(d["original"]))
            self.assertGreaterEqual(d["amended"], d["original"] or "", "the Omnibus never brought a date forward")


class CommandLineTests(unittest.TestCase):
    def test_classify_example(self):
        code, out, _ = run_cli("classify", str(ROOT / "examples" / "shortlister.json"), "--as-of", "2026-11-24")
        self.assertEqual(code, 0)
        self.assertIn("High-risk (Annex III use)", out)
        self.assertIn("2 December 2027  in 373 days", out)
        self.assertIn("Maximum fine: €15m", out)

    def test_classify_lists_what_would_change_the_result(self):
        code, out, _ = run_cli("classify", str(ROOT / "examples" / "shortlister.json"), "--as-of", "2026-11-24")
        self.assertIn("What would change the result (20 single changes tried, 10 matter):", out)
        self.assertIn('"Annex III use" from Employment to none: becomes Minimal risk; 8 duties removed, no specific fine tier (was up to €15m).', out)
        self.assertIn('"SME or start-up" from no to yes: stays High-risk (Annex III use); maximum fine €12m (was €15m).', out)

    def test_classify_lists_what_it_could_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "odd.json"
            path.write_text(json.dumps({"role": "Deployer", "annex3": "Employment", "profiling": "yes", "colour": "blue"}), encoding="utf-8")
            code, out, _ = run_cli("classify", str(path), "--as-of", "2026-11-24")
            self.assertEqual(code, 0)
            self.assertIn("Minimal risk", out)
            self.assertIn('Notes on the input:\n  - role "Deployer" is not one of: provider, deployer, both', out)
            self.assertIn('unknown answer "colour" was ignored', out)
            path.write_text(json.dumps({"annex3": "employment", "sme": True}), encoding="utf-8")
            code, out, _ = run_cli("classify", str(path), "--as-of", "2026-11-24")
            self.assertIn("No turnover was given, so this is the fixed amount", out)

    def test_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.json"
            bad.write_text("{nope", encoding="utf-8")
            self.assertEqual(run_cli("classify", str(bad))[0], 2)
            good = pathlib.Path(tmp) / "good.json"
            good.write_text(json.dumps({"annex1": True, "role": "provider"}), encoding="utf-8")
            self.assertEqual(run_cli("classify", str(good), "--as-of", "2026-02-30")[0], 2)
            code, out, _ = run_cli("classify", str(good), "--as-of", "2029-01-01")
            self.assertIn("applies", out)
            self.assertNotRegex(out, r"in [0-9]+ days", "by 2029 everything applies")


class RegisterTests(unittest.TestCase):
    def test_example_register_matches_the_app_examples(self):
        rows, warnings = register.load(ROOT / "examples" / "register.csv")
        self.assertEqual(warnings, [])
        self.assertEqual([r["notes"] for r in rows], [[]] * len(rows))
        self.assertEqual(len(rows), len(model.RULES["examples"]))
        for row, example in zip(rows, model.RULES["examples"]):
            self.assertEqual(model.classify(row["answers"]), model.classify(example), example["name"])

    def test_register_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, dc = pathlib.Path(tmp) / "plan.md", pathlib.Path(tmp) / "duties.csv"
            code, out, _ = run_cli("register", str(ROOT / "examples" / "register.csv"), "--as-of", "2026-11-24", "--markdown", str(md), "--csv", str(dc))
            self.assertEqual(code, 0)
            self.assertIn("AI register: 9 systems", out)
            self.assertIn("2 December 2027", out)
            self.assertIn("What the Digital Omnibus moved", out)
            self.assertIn("not legal advice", md.read_text(encoding="utf-8"))
            with open(dc, encoding="utf-8", newline="") as f:
                duties = list(csv.DictReader(f))
            total = sum(len(model.classify(e)["obligations"]) for e in model.RULES["examples"])
            self.assertEqual(len(duties), total)

    def test_example_register_file_is_what_the_app_writes(self):
        self.assertEqual(register.to_csv(model.RULES["examples"]), (ROOT / "examples" / "register.csv").read_text(encoding="utf-8"))

    def test_json_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "register.json"
            path.write_text(json.dumps({"systems": model.RULES["examples"][:3] + [7]}), encoding="utf-8")
            rows, warnings = register.load(path)
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[3]["notes"], ["the answers are not an object, so the defaults were used"])
            code, out, _ = run_cli("register", str(path))
            self.assertEqual(code, 0)
            self.assertIn("AI register: 4 systems", out)
            for bad in ("{}", "[]", "nope"):
                path.write_text(bad, encoding="utf-8")
                self.assertEqual(run_cli("register", str(path))[0], 2, bad)

    def test_messy_register_is_read_with_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "messy.csv"
            path.write_text("\ufeff Name ,ROLE,annex3,profiling,prohibited,turnover,colour\n"
                            "A,deployer,employment,maybe,socialScoring; madeUp,lots,blue\n"
                            ",,,,,,\n"
                            "B,boss,,yes,,12,\n", encoding="utf-8")
            rows, warnings = register.load(path)
            self.assertEqual(warnings, ["ignored unknown column(s): colour"])
            self.assertEqual(len(rows), 2, "blank rows are skipped")
            a, b = rows
            self.assertEqual(a["answers"]["prohibited"], ["socialScoring"])
            self.assertEqual(len(a["notes"]), 3, a["notes"])
            self.assertEqual(model.classify(a["answers"])["tier"], "prohibited")
            self.assertNotIn("role", b["answers"])
            self.assertEqual(len(b["notes"]), 1)
            code, out, _ = run_cli("register", str(path))
            self.assertEqual(code, 0)
            self.assertIn("Notes on the input:", out)
            for bad in ("", "name\n", "title\nx\n"):
                path.write_text(bad, encoding="utf-8")
                self.assertEqual(run_cli("register", str(path))[0], 2, repr(bad))


if __name__ == "__main__":
    unittest.main()
