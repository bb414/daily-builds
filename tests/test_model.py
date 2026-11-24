import base64
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

    def test_next_loan_day(self):
        self.assertEqual([M.next_loan_day(d) for d in (0, 20, 21, 22, 125, 126, 230, 231, 364)],
                         [21, 21, 126, 126, 126, 231, 231, M.DAYS, M.DAYS])

    def test_term_planner(self):
        r = self.run_rule("planner", rescue="never")
        self.assertTrue(all(x["moved"] == 0 for x in r["daily"][:M.LEARNING_DAYS]))
        self.assertTrue(all(x["moved"] <= 10000 for x in r["daily"]))
        self.assertGreater(r["savedIn"], 0)
        s = copy.deepcopy(self.s)
        s["rules"]["planner"]["cap"] = 0
        self.assertEqual(M.simulate(s, self.days, "planner")["savedIn"], 0)
        # Budgeting all the way to the next loan payment is far calmer than a two-week forecast.
        smart = self.run_rule("smart")
        planner = self.run_rule("planner")
        self.assertLess(planner["rescues"] * 5, smart["rescues"])
        self.assertLess(planner["savedIn"], smart["savedIn"])

    def test_planner_counts_every_rent_before_the_next_loan(self):
        # Each loan payment has to cover every rent payment until the next one, so higher rent leaves less to move.
        s = copy.deepcopy(self.s)
        s.update(rescue="never", shockChance=0)
        saved = []
        for rent in (300, 520, 700):
            s["rent"] = rent
            saved.append(M.simulate(s, M.generate_year(s, 5), "planner")["savedIn"])
        self.assertGreater(saved[0], saved[1])
        self.assertGreater(saved[1], saved[2])
        self.assertGreater(saved[2], 0)

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
        self.assertEqual(a["none"]["cameBack"], 0)
        for r in M.RULES[1:]:
            self.assertTrue(0 <= a[r]["cameBack"] <= 1, r)
        self.assertGreater(a["smart"]["cameBack"], a["planner"]["cameBack"])
        self.assertEqual(M.stress_test(dict(s, rescue="never"), 10)["smart"]["cameBack"], 0)
        just = M.stress_test(s, 30, rules=["planner"])
        self.assertEqual(set(just), {"planner"})
        self.assertEqual(just["planner"], a["planner"])

    def test_came_back(self):
        self.assertEqual(M.came_back([]), 0)
        self.assertEqual(M.came_back([{"savedIn": 0, "interestEarned": 0, "rescued": 0}]), 0)
        self.assertEqual(M.came_back([{"savedIn": 300, "interestEarned": 0, "rescued": 100},
                                      {"savedIn": 90, "interestEarned": 10, "rescued": 100}]), 0.5)
        # Raids can take back interest as well as money moved in, but never more than went in.
        for preset in M.PRESETS:
            summary = M.stress_test(M.default_settings(preset), 40)
            for r in M.RULES:
                self.assertTrue(0 <= summary[r]["cameBack"] <= 1, (preset, r, summary[r]["cameBack"]))

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            M.stress_test(M.default_settings(), 0)
        self.assertEqual(M.stress_test(M.default_settings(), 3.0)["none"]["years"], 3)
        self.assertEqual(M.sweep(M.default_settings(), "planner", years=2.0)["years"], 2)
        s = M.default_settings()
        s["rent"] = -5
        with self.assertRaises(ValueError):
            M.stress_test(s, 10)


class SweepTests(unittest.TestCase):
    def test_grid_and_frontier(self):
        s = M.default_settings("tight")
        s["rescue"] = "never"
        out = M.sweep(s, "smart", {"horizon": [14, 90], "buffer": [0, 800]}, years=20)
        self.assertEqual(out["dials"], ["horizon", "buffer"])
        self.assertEqual([(r["horizon"], r["buffer"]) for r in out["rows"]], [(14, 0), (14, 800), (90, 0), (90, 800)])
        self.assertEqual(out, M.sweep(s, "smart", {"horizon": [14, 90], "buffer": [0, 800]}, years=20))
        rows = out["rows"]
        self.assertTrue(any(r["frontier"] for r in rows))
        for r in rows:
            dominated = any(o is not r and o["net"] >= r["net"] and o["beyondChance"] <= r["beyondChance"]
                            and o["meanRescues"] <= r["meanRescues"]
                            and (o["net"], -o["beyondChance"], -o["meanRescues"])
                            != (r["net"], -r["beyondChance"], -r["meanRescues"]) for o in rows)
            self.assertEqual(r["frontier"], not dominated)
        # Looking further ahead with a bigger cushion is safer on the tight budget.
        by = {(r["horizon"], r["buffer"]): r for r in rows}
        self.assertLess(by[(90, 800)]["beyondChance"], by[(14, 0)]["beyondChance"])
        # A row matches a plain stress test with the same settings.
        t = copy.deepcopy(s)
        t["rules"]["smart"].update(horizon=90, buffer=0)
        x = M.stress_test(t, 20, rules=["none", "smart"])["smart"]
        self.assertEqual((by[(90, 0)]["endPot"], by[(90, 0)]["net"], by[(90, 0)]["beyondChance"]),
                         (x["endPot"]["p50"], x["net"]["p50"], x["beyondChance"]))
        self.assertEqual(out["beyondWithoutSaving"], M.stress_test(s, 20, rules=["none"])["none"]["beyondChance"])

    def test_defaults_and_errors(self):
        s = M.default_settings()
        out = M.sweep(s, "planner", years=2)
        self.assertEqual(out["dials"], ["buffer", "aggressiveness"])
        self.assertEqual(len(out["rows"]), 20)
        for rule, dials, years, text in (
                ("weekly", None, 5, "rule must be"),
                ("smart", {"horizon": [7]}, 5, "exactly two"),
                ("smart", {"horizon": [7], "colour": [1]}, 5, "no dial called colour"),
                ("smart", {"horizon": [7.5], "buffer": [0]}, 5, "whole numbers"),
                ("smart", {"horizon": [7], "buffer": []}, 5, "buffer values"),
                ("planner", {"buffer": [0], "aggressiveness": [1.5]}, 5, "aggressiveness values"),
                ("planner", {"buffer": [0], "aggressiveness": [1]}, 0, "years"),
                ("planner", {"buffer": list(range(100)), "aggressiveness": [0.1 * i for i in range(10)]}, 5000,
                 "too large")):
            with self.assertRaises(ValueError) as ctx:
                M.sweep(s, rule, dials, years)
            self.assertIn(text, str(ctx.exception), (rule, dials))
        bad = M.default_settings()
        bad["rent"] = -1
        with self.assertRaises(ValueError):
            M.sweep(bad)


class LinkTests(unittest.TestCase):
    def test_round_trip_and_errors(self):
        s = M.default_settings("shifts")
        link = M.encode_link(s)
        self.assertTrue(link.startswith("s="))
        self.assertNotIn("=", link[2:])
        self.assertEqual(M.decode_link("file:///home/me/app/index.html#" + link), s)
        self.assertEqual(M.decode_link(link), s)
        self.assertEqual(M.decode_link("  ?x=1&" + link + "  "), s)
        for text, message in (("", M.LINK_MISSING), ("#t=e30", M.LINK_MISSING), ("#s=abcde", M.LINK_DAMAGED),
                              ("#s=bm90IGpzb24", M.LINK_DAMAGED), ("#s=TmFO", M.LINK_DAMAGED)):
            with self.assertRaises(ValueError) as ctx:
                M.decode_link(text)
            self.assertEqual(str(ctx.exception), message, text)


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
            code, out = self.run_cli("sweep", "--preset", "tight", "--rescue", "never", "--years", "5",
                                     "--dial", "horizon=14,90", "--dial", "buffer=0,800", "--csv", str(Path(d) / "w.csv"))
            self.assertEqual(code, 0, out)
            self.assertIn("Looks ahead", out)
            self.assertIn("on the frontier", out)
            rows = (Path(d) / "w.csv").read_text().splitlines()
            self.assertEqual(len(rows), 5)
            self.assertTrue(rows[0].startswith("horizon,buffer,set_aside_median"))
            with open(Path(d) / "list.json", "w") as f:
                f.write("[1]")
            code, out = self.run_cli("run", "--settings", str(Path(d) / "list.json"), "--seed", "3")
            self.assertEqual((code, out.strip()), (2, "Error: These are not Save or sink settings."))
            with open(Path(d) / "deep.json", "w") as f:
                f.write("[" * 100000 + "]" * 100000)
            code, out = self.run_cli("run", "--settings", str(Path(d) / "deep.json"))
            self.assertEqual(code, 2)
            self.assertIn("nested too deeply", out)
            self.assertEqual(self.run_cli("settings", "tight", "--link", "-o", str(Path(d) / "l.txt"))[0], 0)
            self.assertTrue((Path(d) / "l.txt").read_text().startswith("#s="))
            code, out = self.run_cli("settings", "tight", "--link")
            link = out.splitlines()[0]
            self.assertEqual(link, "#" + M.encode_link(M.default_settings("tight")))
            self.assertTrue(link.startswith("#s="))
            code, out = self.run_cli("run", "--years", "5", "--link", "file:///app/index.html" + link)
            self.assertEqual(code, 0)
            self.assertIn("Tight budget", out)

    def test_wording(self):
        code, out = self.run_cli("run", "--years", "1", "--preset", "tight", "--rescue", "near-limit")
        self.assertIn("1 simulated year\n", out)
        s = M.default_settings("tight")
        s.update(overdraftLimit=50, rescue="near-limit")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            path.write_text(json.dumps(s))
            code, out = self.run_cli("run", "--years", "2", "--settings", str(path))
            self.assertIn("as soon as they are overdrawn (the limit is under £100)", out)
            s["overdraftLimit"] = 0
            path.write_text(json.dumps(s))
            code, out = self.run_cli("sweep", "--years", "1", "--settings", str(path), "--dial", "horizon=1",
                                     "--dial", "buffer=0", "--csv", str(Path(d) / "w.csv"))
            self.assertIn("No interest-free overdraft", out)
            self.assertIn("1 day ", out)
            self.assertIn("The one setting is on the frontier", out)
            self.assertIn("Wrote 1 row to", out)

    def test_errors(self):
        for argv in (("run", "--years", "0"), ("run", "--settings", "missing.json"), ("year", "--rule", "magic"),
                     ("year", "--year", "0"), ("sweep", "--dial", "horizon"), ("sweep", "--dial", "horizon=a,b"),
                     ("sweep", "--dial", "horizon=7", "--dial", "horizon=14"), ("sweep", "--dial", "cap=1"),
                     ("sweep", "--years", "0"), ("run", "--link", "#s=abc"), ("run", "--link", "#s=e30"),
                     ("run", "--link", "s=bnVsbA", "--rescue", "never"), ("run", "--link", ""), ("run", "--settings", ""),
                     ("sweep", "--dial", "horizon=inf", "--dial", "buffer=0"),
                     ("sweep", "--dial", "horizon=nan", "--dial", "buffer=0"),
                     ("run", "--link", "#" + M.encode_link(dict(M.default_settings(), preset=["x"]))),
                     ("run", "--link", "#s=" + base64.urlsafe_b64encode(b"[" * 5000 + b"]" * 5000).decode())):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("Error:", out)


if __name__ == "__main__":
    unittest.main()
