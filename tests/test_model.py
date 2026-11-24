import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from saveorsink import model as M
from saveorsink.__main__ import main as cli


def totals(days, kind=None):
    money_in = sum(a for d in days for _, a in d["in"])
    money_out = sum(a for d in days for _, a, k in d["out"] if kind is None or k == kind)
    return money_in, money_out


class CalendarTests(unittest.TestCase):
    def test_year_shape(self):
        self.assertEqual(M.DAYS, 365)
        self.assertEqual(M.MONTH_STARTS[:3], [0, 30, 61])
        self.assertEqual(M.MONTH_STARTS[4], 122)   # 1 January
        self.assertEqual(M.LOAN_DAYS, [21, 126, 231])


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.s = M.default_settings("steady")
        self.days = M.generate_year(self.s, 1)

    def test_scheduled_payments(self):
        loans = [d for d, day in enumerate(self.days) for label, _ in day["in"] if label == "Student loan"]
        self.assertEqual(loans, M.LOAN_DAYS)
        rents = [d for d, day in enumerate(self.days) for x in day["out"] if x[0] == "Rent"]
        self.assertEqual(rents, M.MONTH_STARTS)
        bills = [d for d, day in enumerate(self.days) for x in day["out"] if x[0] == "Phone and subscriptions"]
        self.assertEqual(bills, [m + 9 for m in M.MONTH_STARTS])
        wages = [d for d, day in enumerate(self.days) for label, _ in day["in"] if label == "Wages"]
        self.assertTrue(all(d % 7 == 4 for d in wages))   # Fridays

    def test_amounts_are_whole_pennies_and_roughly_right(self):
        for day in self.days:
            for item in day["in"] + day["out"]:
                self.assertIsInstance(item[1], int)
                self.assertGreater(item[1], 0)
        # Averaged over many years, everyday spending matches the setting.
        total = 0
        for k in range(60):
            days = M.generate_year(self.s, k + 100)
            total += sum(a for d in days for label, a, _ in d["out"] if label == "Everyday spending")
        self.assertAlmostEqual(total / 60 / 100, self.s["everydayPerWeek"] / 7 * 365, delta=60)

    def test_reproducible(self):
        self.assertEqual(M.generate_year(self.s, 5), M.generate_year(self.s, 5))
        self.assertNotEqual(M.generate_year(self.s, 5), M.generate_year(self.s, 6))

    def test_no_job_means_no_wages(self):
        days = M.generate_year(M.default_settings("tight"), 3)
        self.assertFalse(any(label == "Wages" for d in days for label, _ in d["in"]))


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.s = M.default_settings("steady")
        self.days = M.generate_year(self.s, 2)

    def run_rule(self, rule, **changes):
        s = copy.deepcopy(self.s)
        s.update(changes)
        return M.simulate(s, self.days, rule, trace=True)

    def test_money_is_conserved(self):
        # Moving money between your own accounts creates nothing: only interest changes the total.
        none = self.run_rule("none")
        for rescue in M.RESCUE_MODES:
            for rule in M.RULES:
                r = self.run_rule(rule, rescue=rescue)
                left = r["endBalance"] + r["endPot"] + r["overdraftCost"] - r["interestEarned"]
                self.assertEqual(left, none["endBalance"] + none["overdraftCost"], (rule, rescue))

    def test_no_saving_never_touches_the_pot(self):
        r = self.run_rule("none")
        self.assertEqual((r["savedIn"], r["endPot"], r["rescues"]), (0, 0, 0))

    def test_weekly_saves_every_monday(self):
        r = self.run_rule("weekly", rescue="never")
        moves = [d for d, x in enumerate(r["daily"]) if x["moved"]]
        self.assertEqual(moves, list(range(0, 365, 7)))
        self.assertEqual(r["savedIn"], 53 * 1500)

    def test_round_ups(self):
        r = self.run_rule("roundup", rescue="never")
        expect = sum((100 - a % 100) % 100 for d in self.days for _, a, k in d["out"] if k == "card")
        self.assertEqual(r["savedIn"], expect)
        s = copy.deepcopy(self.s)
        s["rules"]["roundup"]["multiplier"] = 3
        s["rescue"] = "never"
        self.assertEqual(M.simulate(s, self.days, "roundup")["savedIn"], 3 * expect)

    def test_payday_share(self):
        r = self.run_rule("payday", rescue="never")
        money_in, _ = totals(self.days)
        self.assertAlmostEqual(r["savedIn"], money_in * 0.10, delta=len(self.days))

    def test_smart_saver_learns_first_and_respects_its_cap(self):
        r = self.run_rule("smart", rescue="never")
        self.assertTrue(all(x["moved"] == 0 for x in r["daily"][:M.LEARNING_DAYS]))
        self.assertTrue(all(x["moved"] <= 10000 for x in r["daily"]))
        self.assertGreater(r["savedIn"], 0)
        s = copy.deepcopy(self.s)
        s["rules"]["smart"]["aggressiveness"] = 0
        self.assertEqual(M.simulate(s, self.days, "smart")["savedIn"], 0)

    def test_knowing_the_bills_makes_it_more_careful(self):
        s = copy.deepcopy(self.s)
        s["rescue"] = "never"
        knows = M.simulate(s, self.days, "smart")["savedIn"]
        s["rules"]["smart"]["knowsBills"] = False
        blind = M.simulate(s, self.days, "smart")["savedIn"]
        self.assertGreater(blind, knows)

    def test_rescues(self):
        r = self.run_rule("smart", rescue="overdrawn")
        for x in r["daily"]:
            if x["pot"] > 0:
                self.assertGreaterEqual(x["balance"], 0 if not x["rescued"] else 0)
        self.assertGreater(r["rescues"], 0)
        never = self.run_rule("smart", rescue="never")
        self.assertEqual(never["rescues"], 0)
        self.assertEqual(M.rescue_point(dict(self.s, rescue="near-limit")), -90000)
        self.assertEqual(M.rescue_point(dict(self.s, rescue="near-limit", overdraftLimit=50)), 0)

    def test_overdraft_interest_only_beyond_the_limit(self):
        s = copy.deepcopy(self.s)
        s.update(startBalance=-1500, overdraftLimit=1000, overdraftRate=36.5, everydayPerWeek=0, socialPerWeek=0,
                 shockChance=0, rent=0, bills=0, loanPerTerm=0, hoursPerWeek=0)
        days = M.generate_year(s, 1)
        r = M.simulate(s, days, "none")
        # £500 beyond the limit at 36.5% a year simple: 50,000p x 0.001 a day, but the interest compounds monthly.
        self.assertEqual(r["daysBeyond"], 365)
        self.assertGreater(r["overdraftCost"], 365 * 50)
        self.assertLess(r["overdraftCost"], 365 * 60)
        s.update(startBalance=-900)
        self.assertEqual(M.simulate(s, M.generate_year(s, 1), "none")["overdraftCost"], 0)


class StressTests(unittest.TestCase):
    def test_summary(self):
        s = M.default_settings("shifts")
        a = M.stress_test(s, 30)
        self.assertEqual(a, M.stress_test(s, 30))
        self.assertEqual(set(a), set(M.RULES))
        for r in M.RULES:
            x = a[r]
            self.assertTrue(x["endPot"]["p10"] <= x["endPot"]["p50"] <= x["endPot"]["p90"])
            self.assertTrue(0 <= x["beyondChance"] <= 1)
        self.assertEqual(a["none"]["net"]["p50"], 0)
        self.assertEqual(a["weekly"]["savedIn"]["p50"], 79500)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            M.stress_test(M.default_settings(), 0)
        s = M.default_settings()
        s["rent"] = -5
        with self.assertRaises(ValueError):
            M.stress_test(s, 10)


class ValidationTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(M.validate_settings(M.default_settings()), [])
        self.assertEqual(M.validate_settings(None), ["These are not Save or sink settings."])
        for key, value, text in (("rent", -1, "rent must be"), ("seed", 1.5, "whole number"), ("rescue", "x", "rescue"),
                                 ("hourlyPay", True, "hourlyPay"), ("rules", [], "rules must be")):
            s = M.default_settings()
            s[key] = value
            self.assertIn(text, M.validate_settings(s)[0], key)
        s = M.default_settings()
        s["rules"]["smart"]["horizon"] = 0
        self.assertIn("rules.smart.horizon", M.validate_settings(s)[0])
        s = M.default_settings()
        s["rules"]["smart"]["knowsBills"] = "yes"
        self.assertIn("knowsBills", M.validate_settings(s)[0])
        s = M.default_settings()
        del s["rules"]["weekly"]
        self.assertIn("rules.weekly is missing", M.validate_settings(s)[0])


class FormatTests(unittest.TestCase):
    def test_money(self):
        cases = [(0, "£0.00"), (5, "£0.05"), (123456, "£1,235"), (99999, "£999.99"), (-4570, "-£45.70"),
                 (123449.5, "£1,234"), (0.4, "£0.00"), (-0.4, "£0.00"), (100000000, "£1,000,000")]
        for p, text in cases:
            self.assertEqual(M.money(p), text, p)
        self.assertEqual(M.money(2449, signed=True), "+£24.49")
        self.assertEqual(M.money(None), "n/a")


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli(list(argv))
        return code, buf.getvalue()

    def test_run_year_and_settings(self):
        code, out = self.run_cli("run", "--years", "20", "--preset", "tight", "--rescue", "never")
        self.assertEqual(code, 0)
        self.assertIn("Smart saver", out)
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "s.json")
            self.assertEqual(self.run_cli("settings", "shifts", "-o", path)[0], 0)
            code, out = self.run_cli("year", "--settings", path, "--rule", "payday", "--csv", str(Path(d) / "y.csv"))
            self.assertEqual(code, 0)
            self.assertIn("Aug", out)
            self.assertEqual(len((Path(d) / "y.csv").read_text().splitlines()), 366)
            code, out = self.run_cli("run", "--settings", path, "--years", "10", "--json", str(Path(d) / "r.json"))
            self.assertEqual(code, 0)
            self.assertIn("smart", json.loads((Path(d) / "r.json").read_text()))

    def test_errors(self):
        for argv in (("run", "--years", "0"), ("run", "--settings", "missing.json"), ("year", "--rule", "magic"),
                     ("year", "--year", "0")):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("Error:", out)


if __name__ == "__main__":
    unittest.main()
