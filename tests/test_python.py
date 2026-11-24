"""Tests for the Python package: the model and the command line."""

import contextlib
import io
import math
import pathlib
import tempfile
import unittest

from markdown_ladder import model, report

ROOT = pathlib.Path(__file__).resolve().parent.parent
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

    def test_freshness_lowers_demand_day_by_day(self):
        cfg = model.normalise({"demand": 10, "freshness": 20, "pattern": "flat"})
        self.assertAlmostEqual(model.demand_rate(cfg, 0, 0), 10)
        self.assertAlmostEqual(model.demand_rate(cfg, 2, 0), 10 * 0.8 ** 2)
        stale = model.solve(dict(model.PRESETS["mochi"], freshness=30))["value"]
        fresh = model.solve(dict(model.PRESETS["mochi"], freshness=0))["value"]
        self.assertLess(stale, fresh)

    def test_quantiles(self):
        self.assertEqual(model.quantile([0.05, 0.05, 0.4, 0.5], 0.1), 1)
        self.assertEqual(model.quantile([0.05, 0.05, 0.4, 0.5], 0.5), 2)
        self.assertEqual(model.quantile([0.05, 0.05, 0.4, 0.5], 0.9), 3)
        self.assertEqual(model.quantile([1.0], 0.9), 0)

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
        self.assertIn("Best plan (this model)      £540.02", out)
        self.assertIn("10% off    £540.02   <- best", out)
        self.assertIn("Mon 60 (60-60), Tue 54 (51-57)", out)
        self.assertIn("Units  Mon", out)

    def test_plan_with_own_numbers(self):
        code, out, _ = run_cli("plan", "--stock", "20", "--days", "2", "--price", "3", "--demand", "8", "--elasticity", "2",
                               "--pattern", "office", "--start-day", "4", "--allow-price-rises", "--rule-pct", "50", "--rule-days", "1")
        self.assertEqual(code, 0)
        self.assertIn("20 units, 2 selling days from Fri", out)
        self.assertIn("prices may go back up", out)
        self.assertIn("50% off with 1 day left", out)

    def test_adjusted_arguments_are_explained(self):
        code, out, err = run_cli("plan", "--days", "0", "--demand", "500")
        self.assertEqual(code, 0)
        self.assertIn("Note: days 0 changed to 1 (allowed 1 to 21, whole numbers).", err)
        self.assertIn("Note: demand 500.0 changed to 100 (allowed 0.1 to 100).", err)

    def test_bad_arguments_are_rejected(self):
        self.assertEqual(run_cli("plan", "--preset", "nope")[0], 2)
        self.assertEqual(run_cli("plan", "--rule-pct", "25")[0], 2)


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_example_range(self):
        md, csv_path = self.dir / "r.md", self.dir / "cards.csv"
        code, out, _ = run_cli("range", str(ROOT / "examples" / "range.csv"), "--markdown", str(md), "--csv", str(csv_path))
        self.assertEqual(code, 0)
        self.assertIn("Chocolate truffle box           60     7     £540.02", out)
        self.assertIn("### Strawberry tarts", md.read_text(encoding="utf-8"))
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "product,day,weekday,pct10_from_units,pct20_from_units,pct30_from_units,pct50_from_units")
        self.assertEqual(len(lines), 1 + 7 + 3 + 2 + 14 + 5 + 2 + 4 + 10)

    def test_bad_ranges_are_explained(self):
        (self.dir / "a.csv").write_text("name,stock\nX,5\n", encoding="utf-8")
        code, _, err = run_cli("range", str(self.dir / "a.csv"))
        self.assertEqual(code, 2)
        self.assertIn("missing the column(s): days, price, demand", err)
        (self.dir / "b.csv").write_text("", encoding="utf-8")
        self.assertIn("is empty", run_cli("range", str(self.dir / "b.csv"))[2])
        self.assertEqual(run_cli("range", str(self.dir / "missing.csv"))[0], 2)

    def test_odd_values_are_adjusted_and_reported(self):
        (self.dir / "c.csv").write_text("name,stock,days,price,demand,pattern\nOdd,999,abc,4,5,weekly\n", encoding="utf-8")
        products = report.load_range(self.dir / "c.csv")
        self.assertEqual(products[0]["cfg"]["stock"], 300)
        self.assertEqual(products[0]["cfg"]["days"], 7)
        self.assertEqual(len(products[0]["notes"]), 3)
        code, out, _ = run_cli("range", str(self.dir / "c.csv"))
        self.assertIn("Adjusted inputs:", out)

    def test_rows_with_extra_cells_are_read(self):
        (self.dir / "d.csv").write_text("name,stock,days,price,demand\nA,10,3,5,4,extra\n\n", encoding="utf-8")
        products = report.load_range(self.dir / "d.csv")
        self.assertEqual([p["name"] for p in products], ["A"])

    def test_robustness_is_not_capped_by_input_limits(self):
        cfg = {"stock": 300, "days": 1, "price": 5, "demand": 100, "elasticity": 1, "wasteCost": 0.5}
        top = next(c for c in model.robustness(cfg) if c["demandFactor"] == 1.5 and c["elasticityFactor"] == 1)
        self.assertGreater(top["ideal"], model.solve(dict(cfg, demand=150))["value"] + 1)
        self.assertAlmostEqual(top["ideal"], model.solve_exact(dict(model.normalise(cfg), demand=150))["value"])

    def test_robust_command(self):
        code, out, _ = run_cli("robust", "--preset", "truffles")
        self.assertEqual(code, 0)
        self.assertIn("as planned         90%         98%         100%", out)
        self.assertIn("93% *", out)

    def test_shelf_card_and_robustness_in_python(self):
        sol = model.solve(model.PRESETS["mochi"])
        card = model.shelf_card(sol)
        self.assertEqual([r["from"][1] for r in card["rows"]], [39, 26, 11])
        self.assertAlmostEqual(card["gap"], 0, places=7)
        cells = model.robustness(model.PRESETS["mochi"])
        self.assertTrue(all(c["planned"] <= c["ideal"] + 1e-7 for c in cells))


if __name__ == "__main__":
    unittest.main()
