import contextlib
import io
import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from crutch_check import model as M
from crutch_check import stats
from crutch_check.__main__ import main as cli
from crutch_check.cohort import SCENARIOS, simulate_cohort
from crutch_check.htmlreport import study_html
from crutch_check.study import analyse, item_table, participant_summary, study_report


class StatsTests(unittest.TestCase):
    def test_t_distribution_matches_tables(self):
        # Two-sided critical values from standard t tables.
        self.assertAlmostEqual(stats.t_two_sided_p(2.228, 10), 0.05, places=3)
        self.assertAlmostEqual(stats.t_two_sided_p(2.042, 30), 0.05, places=3)
        self.assertAlmostEqual(stats.t_two_sided_p(2.750, 30), 0.01, places=3)
        self.assertAlmostEqual(stats.t_two_sided_p(1.96, 1e6), 0.05, places=3)
        self.assertEqual(stats.t_two_sided_p(0, 5), 1.0)

    def test_welch_and_effect_size(self):
        a, b = [1, 2, 3, 4, 5], [2, 3, 4, 5, 9]
        t, df, p = stats.welch_t(a, b)
        self.assertAlmostEqual(t, (3 - 4.6) / math.sqrt(2.5 / 5 + 7.3 / 5))
        self.assertTrue(0 < p < 1)
        self.assertLess(stats.hedges_g(a, b), 0)
        self.assertIsNone(stats.welch_t([1], [2, 3]))
        self.assertIsNone(stats.hedges_g([1, 1], [1, 1]))

    def test_permutation_and_bootstrap(self):
        a, b = [1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]
        p = stats.permutation_test(a, b, n_perm=2000)
        self.assertLess(p, 0.01)
        self.assertGreater(stats.permutation_test(a, a, n_perm=500), 0.9)
        lo, hi = stats.bootstrap_ci(a, b, n_boot=1000)
        self.assertTrue(lo <= -6 <= hi)
        self.assertIsNone(stats.permutation_test([], b))

    def test_pearson(self):
        self.assertAlmostEqual(stats.pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(stats.pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertIsNone(stats.pearson([1, 2], [1, 2]))
        self.assertIsNone(stats.pearson([1, 1, 1], [1, 2, 3]))
        self.assertAlmostEqual(stats.pearson([1, None, 2, 3], [1, 5, 2, 3]), 1.0)


class CohortTests(unittest.TestCase):
    def test_balanced_and_reproducible(self):
        a = simulate_cohort(10, "mixed", seed=4)
        self.assertEqual(len(a), 20)
        self.assertEqual(sum(s["arm"] == "checker" for s in a), 10)
        self.assertEqual(a, simulate_cohort(10, "mixed", seed=4))
        self.assertNotEqual(a, simulate_cohort(10, "mixed", seed=5))
        for s in a:
            M.validate_session(s)
            self.assertTrue(M.score_session(s)["complete"])

    def test_simulated_participants_can_be_rerun_in_the_app(self):
        s = simulate_cohort(3, "helper", seed=1, study="trial")[0]
        rebuilt = M.build_session(M.participant_seed("trial", s["participant"]), s["arm"], None,
                                  s["participant"], "trial")
        self.assertEqual([t["messageId"] for t in rebuilt["trials"]], [t["messageId"] for t in s["trials"]])

    def test_scenarios_push_learning_the_right_way(self):
        crutch = analyse(simulate_cohort(400, "crutch", seed=2), n_perm=200, n_boot=200)
        helper = analyse(simulate_cohort(400, "helper", seed=2), n_perm=200, n_boot=200)
        self.assertLess(crutch["gain"]["difference"], 0)
        self.assertGreater(helper["gain"]["difference"], 0)
        self.assertLess(crutch["reliance"]["switchGainR"], 0)
        # The checker always helps while it is being used, whatever happens afterwards.
        self.assertGreater(crutch["during"]["difference"], 0.03)

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            simulate_cohort(5, "nonsense")
        with self.assertRaises(ValueError):
            simulate_cohort(0)
        self.assertTrue(all("about" in v for v in SCENARIOS.values()))


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.sessions = simulate_cohort(15, "mixed", seed=9)

    def test_summary_matches_scoring(self):
        s = self.sessions[0]
        row = participant_summary(s)
        res = M.score_session(s)
        self.assertEqual(row["pre"], res["rounds"][0]["accuracy"])
        self.assertEqual(row["post"], res["rounds"][2]["accuracy"])
        self.assertEqual(row["gain"], res["change"]["accuracy"])

    def test_group_means_are_right(self):
        an = analyse(self.sessions, n_perm=200, n_boot=200)
        for arm in ("checker", "control"):
            group = [participant_summary(s) for s in self.sessions if s["arm"] == arm]
            self.assertAlmostEqual(an["arms"][arm]["pre"]["mean"], sum(r["pre"] for r in group) / 15)
            self.assertAlmostEqual(an["arms"][arm]["gain"]["mean"], sum(r["gain"] for r in group) / 15)
        self.assertAlmostEqual(an["gain"]["difference"],
                               an["arms"]["checker"]["gain"]["mean"] - an["arms"]["control"]["gain"]["mean"])
        lo, hi = an["gain"]["ci"]
        self.assertLessEqual(lo, hi)
        self.assertEqual(sum(an["reliance"]["profiles"].values()), 15)

    def test_incomplete_and_duplicates_are_left_out(self):
        extra = json.loads(json.dumps(self.sessions[:2]))
        partial = json.loads(json.dumps(self.sessions[2]))
        partial["participant"] = "PARTIAL"
        partial["trials"][-1]["final"] = None
        an = analyse(self.sessions + extra + [partial], n_perm=100, n_boot=100)
        self.assertEqual(an["duplicates"], 2)
        self.assertEqual(an["incomplete"], 1)
        self.assertEqual(an["complete"], 30)

    def test_one_arm_only(self):
        only = [s for s in self.sessions if s["arm"] == "checker"]
        an = analyse(only, n_perm=100, n_boot=100)
        self.assertIsNone(an["gain"])
        self.assertEqual(an["arms"]["control"]["n"], 0)
        text = study_report(an)
        self.assertIn("needs at least two complete sessions", text)
        self.assertIn("<svg", study_html(an))
        controls = [s for s in self.sessions if s["arm"] == "control"]
        an = analyse(controls, n_perm=100, n_boot=100)
        self.assertIsNone(an["reliance"])
        study_report(an)
        study_html(an)

    def test_item_table(self):
        items = item_table(self.sessions)
        self.assertEqual(sum(i["aloneN"] + i["assistedN"] for i in items), 30 * 28)
        accs = [i["aloneAccuracy"] for i in items if i["aloneAccuracy"] is not None]
        self.assertEqual(accs, sorted(accs))
        for i in items:
            self.assertLessEqual(i["followedWrong"], i["checkerWrongN"])

    def test_html_report_is_self_contained(self):
        page = study_html(analyse(self.sessions, n_perm=100, n_boot=100))
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?https?:""", page))
        self.assertEqual(page.count("<svg"), 3)
        self.assertNotIn("\u2014", page)


class PowerTests(unittest.TestCase):
    def test_power_grows_with_sample_size(self):
        from crutch_check.power import expected_gain_difference, power_curve, power_report
        res = power_curve("crutch", sizes=(10, 120), sims=30, seed=3)
        small, large = res["rows"]
        self.assertLess(small["afterPower"], large["afterPower"])
        self.assertGreaterEqual(large["duringPower"], 0.9)
        self.assertAlmostEqual(res["expected"], expected_gain_difference("crutch"))
        self.assertAlmostEqual(res["expected"], -0.10)
        self.assertLess(abs(large["meanDifference"] - res["expected"]), 0.03)
        self.assertIn("Per group", power_report(res))

    def test_no_effect_means_few_detections(self):
        from crutch_check.power import power_curve, power_report
        res = power_curve("none", sizes=(40,), sims=60, seed=5)
        self.assertLessEqual(res["rows"][0]["afterPower"], 0.15)
        self.assertIn("false alarms", power_report(res))

    def test_report_names_the_smallest_size_that_is_enough(self):
        from crutch_check.power import power_curve, power_report
        res = power_curve("crutch", sizes=(200, 150), sims=10, seed=2)
        self.assertEqual([r["n"] for r in res["rows"]], [150, 200])
        self.assertIn("About 150 per group", power_report(res))

    def test_bad_arguments(self):
        from crutch_check.power import power_curve
        with self.assertRaises(ValueError):
            power_curve("nope")
        with self.assertRaises(ValueError):
            power_curve("crutch", sizes=(1,), sims=2)
        with self.assertRaises(ValueError):
            power_curve("crutch", sims=0)

    def test_analysis_includes_strategies_and_signal_detection(self):
        an = analyse(simulate_cohort(20, "mixed", seed=2), n_perm=100, n_boot=100)
        keys = [x["key"] for x in an["reliance"]["strategies"]]
        self.assertEqual(keys, [k for k, _ in M.STRATEGIES])
        always = an["reliance"]["strategies"][2]["mean"]
        self.assertAlmostEqual(always, an["reliance"]["checker"]["mean"])
        self.assertIsNotNone(an["arms"]["control"]["dPre"]["mean"])
        text = study_report(an)
        self.assertIn("Always follow the checker", text)
        self.assertIn("Sensitivity d'", text)


class StudyCliTests(unittest.TestCase):
    def test_simulate_then_analyse(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = str(Path(d) / "sim.json")
            report = str(Path(d) / "r.html")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli(["simulate", "--n", "8", "--scenario", "crutch", "-o", bundle]), 0)
                self.assertEqual(cli(["analyse", bundle, "--html", report, "--permutations", "200",
                                      "--bootstrap", "200"]), 0)
            out = buf.getvalue()
            self.assertIn("16 complete (8 with the checker, 8 without)", out)
            self.assertTrue(Path(report).read_text().startswith("<!doctype html>"))

    def test_zero_resamples_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = str(Path(d) / "sim.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cli(["simulate", "--n", "3", "-o", bundle])
                self.assertEqual(cli(["analyse", bundle, "--bootstrap", "0"]), 2)
            self.assertIn("Error:", buf.getvalue())

    def test_power_command(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli(["power", "--scenario", "helper", "--sizes", "10", "20", "--sims", "5"]), 0)
        self.assertIn("scenario 'helper'", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
