"""Tests for the pilot purgatory simulator. Run with: python -m unittest discover -s tests"""

import contextlib
import io
import math
import random
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilot_purgatory import GOVERNANCE, LEVERS, MOMENTUM, Strategy, simulate, simulate_once  # noqa: E402
from pilot_purgatory.__main__ import main  # noqa: E402
from pilot_purgatory.analysis import lever_effects  # noqa: E402
from pilot_purgatory.model import (  # noqa: E402
    BARRIERS,
    HARD_TO_MEASURE,
    LONG_TIMESCALES,
    NO_ROUTE,
    OUTCOMES,
    PURGATORY,
    SCALED,
    TECH_COMPLEXITY,
    UNCLEAR_ROI,
    Pilot,
    blocking_barrier,
    draw_pilot,
    effective_measurability,
    expected_evidenced_roi,
    launch_portfolio,
)
from pilot_purgatory.report import html_report, money, points, text_report  # noqa: E402


def make_pilot(**kw):
    base = dict(value=500.0, measurability=0.5, complexity=0.5, time_to_value=2, run_cost=50.0)
    base.update(kw)
    return Pilot(**base)


class DrawAndLaunch(unittest.TestCase):
    def test_drawn_pilots_have_valid_attributes(self):
        rng = random.Random(1)
        for _ in range(2000):
            p = draw_pilot(rng)
            self.assertGreater(p.value, 0)
            self.assertTrue(0 <= p.measurability <= 1)
            self.assertTrue(0 <= p.complexity <= 1)
            self.assertTrue(1 <= p.time_to_value <= 7)
            self.assertTrue(30 <= p.run_cost <= 90)

    def test_roughly_one_in_five_candidates_is_worth_scaling(self):
        rng = random.Random(7)
        worth = sum(draw_pilot(rng).true_roi >= 1.5 for _ in range(5000)) / 5000
        self.assertTrue(0.12 < worth < 0.32, worth)

    def test_screening_keeps_the_requested_number_and_raises_quality(self):
        unscreened = launch_portfolio(replace(MOMENTUM, pilots=200), random.Random(3))
        screened = launch_portfolio(replace(MOMENTUM, pilots=200, screening=0.5), random.Random(3))
        self.assertEqual(len(screened), 200)
        mean = lambda ps: sum(p.true_roi for p in ps) / len(ps)  # noqa: E731
        self.assertGreater(mean(screened), mean(unscreened))


class Measurement(unittest.TestCase):
    def test_metrics_up_front_raises_measurability_but_caps_at_one(self):
        p = make_pilot(measurability=0.9)
        self.assertAlmostEqual(effective_measurability(p, MOMENTUM), 0.9)
        self.assertAlmostEqual(effective_measurability(p, replace(MOMENTUM, metrics_upfront=True)), 1.0)

    def test_better_measurement_means_more_evidenced_value(self):
        low = make_pilot(measurability=0.1)
        high = make_pilot(measurability=0.9)
        self.assertLess(expected_evidenced_roi(low, MOMENTUM), expected_evidenced_roi(high, MOMENTUM))
        self.assertLessEqual(expected_evidenced_roi(high, MOMENTUM), high.true_roi)


class BarrierAttribution(unittest.TestCase):
    def test_pilot_that_never_produced_evidence_is_long_timescales(self):
        p = make_pilot(time_to_value=6)
        p.end_age = 3
        self.assertEqual(blocking_barrier(p, MOMENTUM), LONG_TIMESCALES)

    def test_valuable_but_poorly_evidenced_pilot_is_hard_to_measure(self):
        p = make_pilot(value=800.0, measurability=0.05, complexity=0.2)  # true ROI ~2.8
        p.end_age = 10
        self.assertGreaterEqual(p.true_roi, MOMENTUM.roi_hurdle)
        self.assertEqual(blocking_barrier(p, MOMENTUM), HARD_TO_MEASURE)

    def test_valuable_and_well_evidenced_pilot_had_no_route_to_scale(self):
        p = make_pilot(value=2000.0, measurability=0.95, complexity=0.2)
        p.end_age = 10
        self.assertEqual(blocking_barrier(p, MOMENTUM), NO_ROUTE)

    def test_complexity_is_blamed_only_when_it_is_the_binding_constraint(self):
        p = make_pilot(value=800.0, complexity=0.95)  # fails at its own cost, passes at average cost
        p.end_age = 10
        self.assertLess(p.true_roi, MOMENTUM.roi_hurdle)
        self.assertEqual(blocking_barrier(p, MOMENTUM), TECH_COMPLEXITY)

    def test_low_value_pilot_is_unclear_roi(self):
        p = make_pilot(value=100.0, complexity=0.9)
        p.end_age = 10
        self.assertEqual(blocking_barrier(p, MOMENTUM), UNCLEAR_ROI)


class SingleRun(unittest.TestCase):
    def test_every_pilot_ends_in_exactly_one_outcome(self):
        for seed in range(30):
            r = simulate_once(GOVERNANCE, random.Random(seed))
            self.assertEqual(sum(r.outcomes.values()), GOVERNANCE.pilots)
            self.assertEqual(sum(r.barriers.values()), r.pilots - r.outcomes[SCALED])

    def test_runs_are_reproducible(self):
        a = simulate_once(MOMENTUM, random.Random(99))
        b = simulate_once(MOMENTUM, random.Random(99))
        self.assertEqual(a, b)

    def test_scaling_never_exceeds_capacity(self):
        tight = replace(GOVERNANCE, pilots=40, screening=0.0, scaling_capacity=1)
        for seed in range(20):
            r = simulate_once(tight, random.Random(seed), quarters=6)
            self.assertLessEqual(r.outcomes[SCALED], 6)
            self.assertEqual(len(r.quarters_to_scale), r.outcomes[SCALED])

    def test_nothing_scales_before_a_strategy_exists(self):
        never = replace(MOMENTUM, strategy_quarter=99)
        r = simulate_once(never, random.Random(5))
        self.assertEqual(r.outcomes[SCALED], 0)
        self.assertEqual(r.value_captured, 0)

    def test_spend_adds_up(self):
        r = simulate_once(MOMENTUM, random.Random(11))
        self.assertLessEqual(r.wasted_spend, r.pilot_spend + 1e-9)
        self.assertAlmostEqual(r.net_value, r.value_captured - r.pilot_spend - r.scaling_spend)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            Strategy(name="bad", pilots=0)
        with self.assertRaises(ValueError):
            Strategy(name="bad", screening=0.95)
        with self.assertRaises(ValueError):
            simulate_once(MOMENTUM, random.Random(1), quarters=0)


class MonteCarlo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.momentum = simulate(MOMENTUM, runs=200, seed=42)
        cls.governance = simulate(GOVERNANCE, runs=200, seed=42)

    def test_shares_sum_to_one(self):
        for s in (self.momentum, self.governance):
            self.assertAlmostEqual(sum(s.outcome_share[o] for o in OUTCOMES), 1.0)
            self.assertAlmostEqual(sum(s.barrier_share[b] for b in BARRIERS), 1.0)
            self.assertLessEqual(s.net_value.p10, s.net_value.mean)
            self.assertLessEqual(s.net_value.mean, s.net_value.p90)

    def test_strategy_first_beats_pilots_first(self):
        self.assertGreater(self.governance.outcome_share[SCALED], self.momentum.outcome_share[SCALED])
        self.assertLess(self.governance.outcome_share[PURGATORY], self.momentum.outcome_share[PURGATORY])
        self.assertGreater(self.governance.net_value.mean, self.momentum.net_value.mean)

    def test_every_lever_is_measured(self):
        baseline, effects = lever_effects(MOMENTUM, runs=60, seed=1)
        self.assertEqual({e.lever for e in effects}, set(LEVERS))
        self.assertEqual(effects, sorted(effects, key=lambda e: e.net_value_change, reverse=True))
        self.assertEqual(baseline.strategy, MOMENTUM)


class Reports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summaries = [simulate(s, runs=40, seed=3) for s in (MOMENTUM, GOVERNANCE)]
        cls.effects = lever_effects(MOMENTUM, runs=40, seed=3)[1]

    def test_formatting_helpers(self):
        self.assertEqual(money(1234), "£1.2m")
        self.assertEqual(money(-6400), "-£6.4m")
        self.assertEqual(points(-6.2), "down 6 points")
        self.assertEqual(points(1.0), "up 1 point")
        self.assertEqual(points(0.2), "no change")

    def test_text_report_covers_every_barrier_and_lever(self):
        text = text_report(self.summaries, self.effects, seed=3)
        for name in list(BARRIERS) + list(LEVERS):
            self.assertIn(name, text)

    def test_html_report_is_self_contained(self):
        page = html_report(self.summaries, self.effects, seed=3)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertEqual(page.count("<svg"), 3)
        self.assertNotRegex(page, r"(src|href)=\"https?://")
        self.assertNotIn("\u2014", page)

    def test_cli_writes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.html"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--runs", "20", "--seed", "1", "--html", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertIn("Pilot purgatory simulator", buf.getvalue())

    def test_cli_rejects_bad_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--runs", "0"]), 2)


class NoStrayText(unittest.TestCase):
    def test_source_has_no_em_dashes(self):
        root = Path(__file__).resolve().parents[1]
        for path in list(root.glob("pilot_purgatory/*.py")) + [root / "README.md"]:
            if path.exists():
                self.assertNotIn("\u2014", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
