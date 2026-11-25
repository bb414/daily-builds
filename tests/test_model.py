"""Tests for the Python model. Run from the repository root: python -m unittest discover -s tests"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from missing_minutes import model as M  # noqa: E402

DAY = M.DAY


def single(**extra):
    cfg = {
        "name": "One desk", "arrivalsPerDay": 40, "slaDays": 5, "measureDays": 300, "warmupDays": 20,
        "steps": [{"name": "Desk", "kind": "team", "staff": 1, "minutes": 9, "cv": 0.5}],
        "ai": {"step": 0, "saving": 0, "adoption": 1, "checkMinutes": 0, "errorRate": 0},
    }
    cfg.update(extra)
    return M.normalise(cfg)


class RandomNumbers(unittest.TestCase):
    def test_streams_are_in_the_open_unit_interval_and_repeatable(self):
        a, b = M.Rng(123), M.Rng(123)
        xs = [a.next() for _ in range(2000)]
        self.assertEqual(xs, [b.next() for _ in range(2000)])
        self.assertTrue(all(0 < x < 1 for x in xs))
        self.assertAlmostEqual(sum(xs) / len(xs), 0.5, delta=0.02)

    def test_spread_has_mean_one(self):
        r = M.Rng(9)
        vals = [M.spread(0.7, r.next(), r.next()) for _ in range(20000)]
        self.assertAlmostEqual(sum(vals) / len(vals), 1.0, delta=0.02)
        self.assertEqual(M.spread(0, 0.3, 0.4), 1)


class Simulation(unittest.TestCase):
    def test_presets_are_valid_and_finish(self):
        for key in M.PRESETS:
            cfg = M.preset_config(key)
            self.assertEqual(M.validate(cfg), [], key)
            r = M.compare(cfg, 42)
            self.assertTrue(r["complete"], key)

    def test_parts_add_up_to_the_total(self):
        for key in M.PRESETS:
            r = M.compare(M.preset_config(key), 3)
            self.assertAlmostEqual(sum(p["value"] for p in r["parts"]), r["total"], places=6)
            self.assertAlmostEqual(r["ai"]["touchTotal"] + r["ai"]["waitTotal"], r["ai"]["leadMean"], places=6)

    def test_ai_that_changes_nothing_changes_nothing(self):
        cfg = M.preset_config("complaints")
        cfg["ai"].update({"saving": 0, "adoption": 1, "checkMinutes": 0, "errorRate": 0})
        r = M.compare(cfg, 4)
        self.assertEqual(r["total"], 0)

    def test_single_desk_matches_pollaczek_khinchine(self):
        rho = 40 * 9 / DAY
        expected = rho / (1 - rho) * 9 * (1 + 0.25) / 2
        got = sum(M.simulate(single(), s, no_ai=True)["steps"][0]["wait"] for s in (1, 2, 3)) / 3
        self.assertLess(abs(got - expected) / expected, 0.12, (got, expected))

    def test_daily_batch_waits_half_a_day(self):
        cfg = single(steps=[{"name": "Run", "kind": "batch", "batchDays": [0, 1, 2, 3, 4], "capacity": 500, "minutes": 0.1, "cv": 0}])
        r = M.simulate(cfg, 4, no_ai=True)
        self.assertLess(abs(r["steps"][0]["wait"] - DAY / 2) / (DAY / 2), 0.05)

    def test_overloaded_step_is_reported(self):
        cfg = M.preset_config("claims")
        cfg["steps"][1]["staff"] = 3
        self.assertFalse(M.compare(cfg, 1)["complete"])

    def test_errors_need_a_check_to_be_caught(self):
        cfg = M.preset_config("claims")
        cfg["ai"].update({"step": 5, "errorRate": 0.2})
        r = M.compare(cfg, 2)
        self.assertEqual(r["ai"]["aiSendBacksPer100"], 0)
        self.assertGreater(r["ai"]["escapedPer100"], 10)


class Validation(unittest.TestCase):
    def test_messages(self):
        cfg = M.preset_config("claims")
        cfg["steps"][2]["reworkTo"] = 4
        cfg["ai"]["step"] = 3
        errs = M.validate(cfg)
        self.assertTrue(any("earlier step" in e for e in errs))
        self.assertTrue(any("cannot sit on a wait" in e for e in errs))

    def test_normalise(self):
        c = M.normalise({"steps": [{"kind": "batch", "batchDays": [3, 3, 9, 1]}, {"kind": "odd"}]})
        self.assertEqual(c["steps"][0]["batchDays"], [1, 3])
        self.assertEqual(c["steps"][1]["kind"], "team")
        self.assertEqual(c["ai"]["step"], -1)

    def test_formatting(self):
        self.assertEqual(M.fmt_duration(12.4), "12 min")
        self.assertEqual(M.fmt_duration(-90), "-1.5 h")
        self.assertEqual(M.fmt_duration(900), "2.0 days")


if __name__ == "__main__":
    unittest.main()


class Options(unittest.TestCase):
    def test_placements_include_the_current_ai(self):
        cfg = M.preset_config("loans")
        cmp = M.compare(cfg, 42)
        rows = M.placements(cfg, 42, cmp["base"])
        current = [o for o in rows if o["current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["total"], cmp["total"])
        self.assertEqual([o["total"] for o in rows], sorted(o["total"] for o in rows))

    def test_bank_savings(self):
        cfg = M.preset_config("claims")
        cmp = M.compare(cfg, 42)
        b = M.bank_savings(cfg, 42, cmp)
        self.assertEqual(b["cut"], 2)
        self.assertFalse(b["stable"])
        self.assertFalse(M.bank_savings(cfg, 42, cmp, 0)["possible"])


class Robustness(unittest.TestCase):
    def test_seeds_and_tornado(self):
        cfg = M.preset_config("complaints")
        rb = M.robustness(cfg, 7, 3)
        self.assertEqual([x["seed"] for x in rb["runs"]], [7, 8, 9])
        self.assertEqual(rb["runs"][0]["total"], M.compare(cfg, 7)["total"])
        rows = M.sensitivity(cfg, 7)
        self.assertEqual([r["swing"] for r in rows], sorted((r["swing"] for r in rows), reverse=True))

    def test_erlang_c(self):
        self.assertAlmostEqual(M.erlang_c(2, 1), 1 / 3)
        self.assertAlmostEqual(M.wait_multiple(1, 1, 0.8), 4)
        self.assertEqual(M.wait_multiple(3, 1, 1), math.inf)


class Setups(unittest.TestCase):
    def test_wrapper_and_bare_config(self):
        import json
        import tempfile
        cfg = M.preset_config("loans")
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.json"), os.path.join(d, "b.json")
            with open(a, "w") as f:
                json.dump({"app": "missing-minutes", "version": 1, "seed": 77, "config": cfg}, f)
            with open(b, "w") as f:
                json.dump(cfg, f)
            self.assertEqual(M.load_setup(a), (cfg, 77))
            self.assertEqual(M.load_setup(b), (cfg, None))
