"""Tests for the Python package: the model and the command line."""

import contextlib
import io
import math
import unittest

from markdown_ladder import model
from markdown_ladder.__main__ import main


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ModelTests(unittest.TestCase):
    def test_one_unit_one_day(self):
        sol = model.solve({"stock": 1, "days": 1, "price": 10, "wasteCost": 2, "demand": 0.7, "elasticity": 0})
        self.assertAlmostEqual(sol["value"], 10 * (1 - math.exp(-0.7)) - 2 * math.exp(-0.7), places=12)

    def test_best_plan_is_consistent_and_unbeaten(self):
        for key, preset in model.PRESETS.items():
            cmp = model.compare_policies(preset)
            best = cmp["rows"][0]["result"]
            self.assertAlmostEqual(best["profit"], cmp["solution"]["value"], places=7, msg=key)
            for r in cmp["rows"][1:]:
                self.assertGreaterEqual(best["profit"], r["result"]["profit"] - 1e-7, msg=key + " " + r["name"])
            self.assertAlmostEqual(best["sold"] + best["waste"], preset["stock"], places=7)

    def test_settings_are_clamped(self):
        cfg = model.normalise({"stock": 5000, "days": -2, "price": "x", "pattern": "nope"})
        self.assertEqual((cfg["stock"], cfg["days"], cfg["price"], cfg["pattern"]), (300, 1, 12.0, "flat"))
        self.assertEqual(model.normalise({"startDay": 2.5})["startDay"], 3, "halves round up, as in JavaScript")

    def test_rule_step(self):
        self.assertEqual(model.rule_step("30"), 3)
        self.assertEqual(model.rule_step(25), 0)
        self.assertEqual(model.rule_step(None), 0)


class CommandLineTests(unittest.TestCase):
    def test_plan_for_a_preset(self):
        code, out, _ = run_cli("plan", "--preset", "truffles")
        self.assertEqual(code, 0)
        self.assertIn("Best plan (this model)      £570.90", out)
        self.assertIn("10% off    £570.90   <- best", out)
        self.assertIn("Units  Mon", out)

    def test_plan_with_own_numbers(self):
        code, out, _ = run_cli("plan", "--stock", "20", "--days", "2", "--price", "3", "--demand", "8", "--elasticity", "2",
                               "--pattern", "office", "--start-day", "4", "--allow-price-rises", "--rule-pct", "50", "--rule-days", "1")
        self.assertEqual(code, 0)
        self.assertIn("20 units, 2 selling days from Fri", out)
        self.assertIn("prices may go back up", out)
        self.assertIn("50% off with 1 day left", out)

    def test_bad_arguments_are_rejected(self):
        self.assertEqual(run_cli("plan", "--preset", "nope")[0], 2)
        self.assertEqual(run_cli("plan", "--rule-pct", "25")[0], 2)


if __name__ == "__main__":
    unittest.main()
