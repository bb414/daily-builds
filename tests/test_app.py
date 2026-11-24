"""Checks that the browser app's model (run in Node.js) agrees exactly with the Python package."""

import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from saveorsink import model as M

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "index.html"
NODE = shutil.which("node")


def js(calls):
    proc = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(calls),
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def plain(x):
    return json.loads(json.dumps(x))


def variants():
    out = []
    for preset in M.PRESETS:
        for rescue in M.RESCUE_MODES:
            s = M.default_settings(preset)
            s["rescue"] = rescue
            out.append(s)
    odd = M.default_settings("shifts")
    odd.update(seed=4294967295, startBalance=-2000, overdraftLimit=0, overdraftRate=99.9, savingsRate=19.5,
               spendVariability=1.5, hoursVariability=2, shockChance=1, shockSize=5000)
    odd["rules"] = {"roundup": {"multiplier": 10}, "weekly": {"amount": 1000}, "payday": {"percent": 100},
                    "smart": {"horizon": 120, "buffer": 0, "aggressiveness": 1, "cap": 5000, "knowsBills": False},
                    "planner": {"buffer": 0, "aggressiveness": 1, "cap": 5000}}
    out.append(odd)
    zero = M.default_settings("tight")
    zero.update(loanPerTerm=0, rent=0, bills=0, everydayPerWeek=0, socialPerWeek=0, shockChance=0, seed=0)
    out.append(zero)
    return out


@unittest.skipUnless(NODE, "Node.js is not installed")
class AppAgreesWithPython(unittest.TestCase):
    def test_constants(self):
        keys = ["FORMAT", "VERSION", "MONTHS", "MONTH_STARTS", "DAYS", "LOAN_DAYS", "BILL_DAY", "RULES", "RULE_NAMES",
                "RESCUE_MODES", "PRESETS"]
        got = js([{"get": k} for k in keys])
        expect = [M.FORMAT, M.VERSION, [list(m) for m in M.MONTHS], M.MONTH_STARTS, M.DAYS, M.LOAN_DAYS,
                  M.BILL_DAY, M.RULES, M.RULE_NAMES, list(M.RESCUE_MODES), M.PRESETS]
        self.assertEqual(got, expect)
        got = js([{"get": "LIMITS"}, {"get": "RULE_LIMITS"}] + [{"fn": "defaultSettings", "args": [p]} for p in M.PRESETS])
        self.assertEqual(got[0], {k: list(v) for k, v in M.LIMITS.items()})
        self.assertEqual(got[1], {r: {k: list(v) for k, v in f.items()} for r, f in M.RULE_LIMITS.items()})
        self.assertEqual(got[2:], [M.default_settings(p) for p in M.PRESETS])

    def test_years_are_identical(self):
        calls, expect = [], []
        for s in variants():
            for seed in (0, 1, 77, 4294967295):
                calls.append({"fn": "generateYear", "args": [s, seed]})
                expect.append(plain(M.generate_year(s, seed)))
        self.assertEqual(js(calls), expect)

    def test_every_rule_runs_identically(self):
        calls, expect = [], []
        for s in variants():
            days = M.generate_year(s, M.year_seed(s["seed"], 3))
            for rule in M.RULES:
                calls.append({"fn": "simulate", "args": [s, days, rule, True]})
                expect.append(plain(M.simulate(s, days, rule, trace=True)))
        self.assertEqual(js(calls), expect)

    def test_stress_tests_are_identical(self):
        calls, expect = [], []
        for s in variants():
            calls.append({"fn": "stressTest", "args": [s, 25]})
            expect.append(plain(M.stress_test(s, 25)))
        self.assertEqual(js(calls), expect)

    def test_validation_and_helpers(self):
        base = M.default_settings()

        def changed(fn):
            s = copy.deepcopy(base)
            fn(s)
            return s

        cases = [base, None, [], {}, changed(lambda s: s.update(rent=-1)), changed(lambda s: s.update(seed=1.5)),
                 changed(lambda s: s.update(seed=4294967296)), changed(lambda s: s.update(hourlyPay=True)),
                 changed(lambda s: s.update(rescue="sometimes")), changed(lambda s: s.update(rules=[])),
                 changed(lambda s: s["rules"].pop("payday")), changed(lambda s: s["rules"]["smart"].update(horizon=2.5)),
                 changed(lambda s: s["rules"]["smart"].update(knowsBills=1)),
                 changed(lambda s: s["rules"]["roundup"].update(multiplier=0)),
                 changed(lambda s: s.update(shockChance="0.5", startBalance=None))]
        got = js([{"fn": "validateSettings", "args": [c]} for c in cases])
        self.assertEqual(got, [M.validate_settings(c) for c in cases])
        came = [[], [{"savedIn": 0, "rescued": 0}], [{"savedIn": 300, "rescued": 100}, {"savedIn": 7, "rescued": 3}]]
        amounts = [0, 5, 99, 100, 123456, 99999, 99999.6, -4570, 123449.5, 0.4, -0.4, 1e8, 2449, -123456.7]
        got = js([{"fn": "money", "args": [a]} for a in amounts] + [{"fn": "money", "args": [a, True]} for a in amounts]
                 + [{"fn": "yearSeed", "args": [s, k]} for s in (0, 1, 4294967295) for k in (0, 5, 999)]
                 + [{"fn": "pennies", "args": [x]} for x in (0, 0.005, 1.234, 11.5, 2999.995)]
                 + [{"fn": "nextLoanDay", "args": [d]} for d in range(M.DAYS)]
                 + [{"fn": "cameBack", "args": [rs]} for rs in came])
        expect = ([M.money(a) for a in amounts] + [M.money(a, signed=True) for a in amounts]
                  + [M.year_seed(s, k) for s in (0, 1, 4294967295) for k in (0, 5, 999)]
                  + [M.pennies(x) for x in (0, 0.005, 1.234, 11.5, 2999.995)]
                  + [M.next_loan_day(d) for d in range(M.DAYS)]
                  + [M.came_back(rs) for rs in came])
        self.assertEqual(got, expect)


class AppFileChecks(unittest.TestCase):
    def setUp(self):
        self.html = APP.read_text(encoding="utf-8")

    def test_no_external_requests(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?https?:""", self.html))
        for word in ("@import", "fetch(", "XMLHttpRequest", "<link"):
            self.assertNotIn(word, self.html)

    def test_model_markers(self):
        self.assertEqual(self.html.count("/* MODEL START */"), 1)
        self.assertEqual(self.html.count("/* MODEL END */"), 1)


if __name__ == "__main__":
    unittest.main()
