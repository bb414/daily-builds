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
    DEFAULT_ASSUMPTIONS,
    HARD_TO_MEASURE,
    IN_PROGRESS,
    KILLED,
    LONG_TIMESCALES,
    NO_ROUTE,
    OUTCOMES,
    PURGATORY,
    SCALED,
    TECH_COMPLEXITY,
    UNCLEAR_ROI,
    Assumptions,
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
    base.setdefault("scaling_cost", DEFAULT_ASSUMPTIONS.scaling_cost(base["complexity"]))
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
        for strategy in (MOMENTUM, GOVERNANCE):
            for seed in range(30):
                r = simulate_once(strategy, random.Random(seed))
                self.assertEqual(sum(r.outcomes.values()), r.pilots)
                self.assertEqual(sum(r.barriers.values()), r.outcomes[KILLED] + r.outcomes[PURGATORY])

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


class DepthMechanics(unittest.TestCase):
    """Loop 1: budget recycling, platform effects and the in-progress outcome."""

    def test_recycling_launches_extra_pilots(self):
        base = replace(GOVERNANCE, recycle_budget=False)
        launched_without = sum(simulate_once(base, random.Random(s)).pilots for s in range(40))
        launched_with = sum(simulate_once(GOVERNANCE, random.Random(s)).pilots for s in range(40))
        self.assertEqual(launched_without, 40 * GOVERNANCE.pilots)
        self.assertGreater(launched_with, launched_without)

    def test_no_recycled_launches_inside_the_cutoff(self):
        # With a horizon no longer than the cutoff, freed budget can never be reused.
        for seed in range(20):
            r = simulate_once(GOVERNANCE, random.Random(seed), quarters=DEFAULT_ASSUMPTIONS.launch_cutoff)
            self.assertEqual(r.pilots, GOVERNANCE.pilots)

    def test_platform_effect_makes_scaling_cheaper(self):
        plain = replace(GOVERNANCE, platform_effect=0.0, recycle_budget=False)
        platform = replace(plain, platform_effect=0.3)

        def cost_per_scaled(strategy):
            spend = scaled = 0
            for seed in range(150):
                r = simulate_once(strategy, random.Random(seed))
                spend += r.scaling_spend
                scaled += r.outcomes[SCALED]
            return spend / scaled

        self.assertLess(cost_per_scaled(platform), cost_per_scaled(plain))

    def test_platform_discount_never_goes_below_the_floor(self):
        heavy = replace(GOVERNANCE, platform_effect=0.5, pilots=40, scaling_capacity=5)
        a = DEFAULT_ASSUMPTIONS
        cheapest_possible = a.scaling_cost_base * a.platform_floor
        for seed in range(20):
            r = simulate_once(heavy, random.Random(seed))
            if r.outcomes[SCALED]:
                self.assertGreaterEqual(r.scaling_spend / r.outcomes[SCALED], cheapest_possible - 1e-9)

    def test_young_pilots_are_in_progress_not_purgatory(self):
        for seed in range(20):
            r = simulate_once(MOMENTUM, random.Random(seed), quarters=DEFAULT_ASSUMPTIONS.purgatory_age - 1)
            self.assertEqual(r.outcomes[PURGATORY], 0)
        r = simulate_once(MOMENTUM, random.Random(1), quarters=2)
        self.assertGreater(r.outcomes[IN_PROGRESS], 0)

    def test_assumptions_are_validated(self):
        with self.assertRaises(ValueError):
            Assumptions(value_median=0)
        with self.assertRaises(ValueError):
            Assumptions(platform_floor=0)
        with self.assertRaises(ValueError):
            Strategy(name="bad", platform_effect=0.9)

    def test_better_world_means_more_value(self):
        rich = Assumptions(value_median=600)
        self.assertGreater(
            simulate(MOMENTUM, runs=80, assumptions=rich).net_value.mean,
            simulate(MOMENTUM, runs=80).net_value.mean,
        )


class TimelineAndRobustness(unittest.TestCase):
    """Loop 2: quarter-by-quarter timeline, payback quarter and the robustness check."""

    def test_timeline_matches_the_final_result(self):
        for strategy in (MOMENTUM, GOVERNANCE):
            r = simulate_once(strategy, random.Random(8), quarters=10)
            self.assertEqual([t.quarter for t in r.timeline], list(range(1, 11)))
            last = r.timeline[-1]
            self.assertAlmostEqual(last.net_value, r.net_value)
            self.assertEqual(last.scaled, r.outcomes[SCALED])
            self.assertEqual(last.stopped, r.outcomes[KILLED])
            self.assertEqual(last.piloting, r.outcomes[PURGATORY] + r.outcomes[IN_PROGRESS])
            scaled = [t.scaled for t in r.timeline]
            self.assertEqual(scaled, sorted(scaled))

    def test_payback_quarter(self):
        good = simulate(GOVERNANCE, runs=150)
        bad = simulate(MOMENTUM, runs=150)
        self.assertIsNotNone(good.payback_quarter)
        self.assertIsNone(bad.payback_quarter)
        q = good.payback_quarter
        self.assertTrue(all(t.net_value >= 0 for t in good.timeline[q - 1 :]))
        self.assertLess(good.timeline[q - 2].net_value, 0)

    def test_robustness_runs_every_scenario(self):
        from pilot_purgatory.robustness import SCENARIOS, Scenario, run_robustness

        self.assertEqual(len(SCENARIOS), 11)
        self.assertEqual(len({sc.name for sc in SCENARIOS}), 11)
        picked = [SCENARIOS[0], Scenario("Tiny horizon", "test", quarters=6, roi_hurdle=2.0, abandon_rate=0.1)]
        report = run_robustness(runs=25, scenarios=picked)
        self.assertEqual(len(report.results), 2)
        self.assertEqual(sum(report.top_lever_counts.values()), 2)
        self.assertTrue(all(r.top_lever in LEVERS for r in report.results))

    def test_scenario_overrides_apply_to_strategies(self):
        from pilot_purgatory.robustness import Scenario

        sc = Scenario("x", "y", roi_hurdle=2.0, abandon_rate=0.1)
        self.assertEqual(sc.apply(MOMENTUM).roi_hurdle, 2.0)
        self.assertEqual(sc.apply(GOVERNANCE).abandon_rate, 0.1)
        self.assertIs(Scenario("x", "y").apply(MOMENTUM), MOMENTUM)


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
        self.assertEqual(page.count("<svg"), 4)
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

    def test_cli_robustness_flag(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--runs", "10", "--robustness", "--no-levers"])
        self.assertEqual(code, 0)
        self.assertIn("Robustness: strategy first beats pilots first", buf.getvalue())

    def test_cli_rejects_bad_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--runs", "0"]), 2)


class EdgeCases(unittest.TestCase):
    """Loop 4 audit: extreme settings must never break the model or its reports."""

    CASES = [
        ("one quarter", MOMENTUM, 1),
        ("one pilot", replace(MOMENTUM, pilots=1), 12),
        ("no capacity", replace(GOVERNANCE, scaling_capacity=0), 12),
        ("heavy screening", replace(GOVERNANCE, screening=0.9, pilots=40), 12),
        ("sponsors always leave", replace(MOMENTUM, abandon_rate=1.0), 12),
        ("almost no hurdle", replace(GOVERNANCE, roi_hurdle=0.01, scaling_capacity=5), 12),
        ("maximum platform", replace(GOVERNANCE, platform_effect=0.5, scaling_capacity=5), 20),
    ]

    def test_extreme_settings(self):
        for name, strategy, quarters in self.CASES:
            with self.subTest(name):
                r = simulate_once(strategy, random.Random(1), quarters)
                self.assertEqual(sum(r.outcomes.values()), r.pilots)
                s = simulate(strategy, runs=30, quarters=quarters)
                self.assertTrue(math.isfinite(s.net_value.mean))
                self.assertEqual(len(s.timeline), quarters)
                text = text_report([s, s], [], seed=1)
                self.assertIn("Payback quarter", text)

    def test_no_capacity_means_nothing_goes_live(self):
        s = simulate(replace(GOVERNANCE, scaling_capacity=0), runs=30)
        self.assertEqual(s.outcome_share[SCALED], 0)
        self.assertTrue(math.isnan(s.median_quarters_to_scale))
        self.assertIn("n/a", text_report([s], [], seed=1))

    def test_sponsors_always_leaving_stops_everything_in_quarter_one(self):
        r = simulate_once(replace(MOMENTUM, abandon_rate=1.0), random.Random(2))
        self.assertEqual(r.outcomes[KILLED], MOMENTUM.pilots)
        self.assertEqual(r.timeline[0].stopped, MOMENTUM.pilots)


class NoStrayText(unittest.TestCase):
    def test_source_has_no_em_dashes(self):
        root = Path(__file__).resolve().parents[1]
        for path in list(root.glob("pilot_purgatory/*.py")) + [root / "README.md"]:
            if path.exists():
                self.assertNotIn("\u2014", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
