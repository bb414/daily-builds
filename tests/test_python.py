"""Tests for the Python companion: model behaviour, statistics, the virtual experiment and the CLI."""

import contextlib
import csv
import io
import json
import math
import os
import tempfile
import unittest

from reliance_lab import cli, experiment, model, stats


def run_cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


class StatsTest(unittest.TestCase):
    def test_incomplete_beta_known_values(self):
        self.assertAlmostEqual(stats.betainc(1, 1, 0.3), 0.3, places=12)
        self.assertAlmostEqual(stats.betainc(2, 3, 0.4), 0.5248, places=10)
        self.assertEqual(stats.betainc(2, 3, 0), 0.0)
        self.assertEqual(stats.betainc(2, 3, 1), 1.0)

    def test_t_distribution_against_tables(self):
        # Two-sided p for t = 2.228 with 10 df is 0.05; t = 1.96 with huge df is about 0.05.
        self.assertAlmostEqual(stats.t_two_sided_p(2.228, 10), 0.05, places=3)
        self.assertAlmostEqual(stats.t_two_sided_p(1.96, 1e6), 0.05, places=3)
        self.assertAlmostEqual(stats.t_critical(10), 2.228, places=3)
        self.assertAlmostEqual(stats.t_critical(30), 2.042, places=3)
        self.assertEqual(stats.t_two_sided_p(0, 5), 1.0)

    def test_welch_on_known_data(self):
        a = [5.1, 4.9, 6.2, 5.8, 6.0, 5.5, 5.3]
        b = [4.1, 4.5, 4.9, 4.4, 3.9, 4.6]
        res = stats.welch(a, b)
        self.assertAlmostEqual(res["diff"], stats.mean(a) - stats.mean(b), places=12)
        self.assertLess(res["p"], 0.01)
        self.assertLess(res["low"], res["diff"])
        self.assertGreater(res["high"], res["diff"])
        self.assertGreater(res["d"], 1)
        # Swapping the groups flips the sign but not the p-value.
        swapped = stats.welch(b, a)
        self.assertAlmostEqual(swapped["diff"], -res["diff"], places=12)
        self.assertAlmostEqual(swapped["p"], res["p"], places=12)

    def test_welch_edge_cases(self):
        same = stats.welch([0.5, 0.5, 0.5], [0.5, 0.5])
        self.assertEqual(same["p"], 1.0)
        apart = stats.welch([1, 1, 1], [0, 0, 0])
        self.assertEqual(apart["p"], 0.0)
        with self.assertRaises(ValueError):
            stats.welch([1], [1, 2])


class ModelTest(unittest.TestCase):
    def test_normalise_rejects_junk(self):
        p = model.normalise_params({"aiAccuracy": "high", "rounds": "33.6", "people": [], "showConfidence": "off",
                                    "workflow": "AI first"})
        self.assertEqual(p["aiAccuracy"], model.DEFAULTS["aiAccuracy"])
        self.assertEqual(p["rounds"], 34)
        self.assertEqual(p["people"], model.DEFAULTS["people"])
        self.assertFalse(p["showConfidence"])
        self.assertEqual(p["workflow"], model.DEFAULTS["workflow"])
        self.assertEqual(model.normalise_params({"seed": float("nan")})["seed"], 42)

    def test_presets_survive_normalising(self):
        for key, preset in model.PRESETS.items():
            p = model.preset_params(key)
            for k, v in preset["params"].items():
                self.assertEqual(p[k], v, "%s.%s" % (key, k))

    def test_counts_are_consistent(self):
        r = model.simulate(dict(model.preset_params("scam_teens"), people=60, rounds=50))
        k = r["counts"]
        self.assertEqual(k["bothRight"] + k["bothWrong"] + k["rescueChances"] + k["misleadChances"], r["cases"])
        self.assertEqual(k["human"], k["bothRight"] + k["misleadChances"])
        self.assertEqual(k["ai"], k["bothRight"] + k["rescueChances"])
        self.assertEqual(len(r["series"]["team"]), 50)
        self.assertEqual(r["series"]["skillRounds"][0], 0)
        self.assertEqual(r["series"]["skillRounds"][-1], 50)

    def test_moving_average(self):
        self.assertEqual(model.moving_average([1, 2, 3, 4], 2), [1, 1.5, 2.5, 3.5])


class ExperimentTest(unittest.TestCase):
    params = dict(model.preset_params("scam_teens"), rounds=60)

    def test_experiment_shapes_and_determinism(self):
        e1 = experiment.run_experiment(self.params, n=12, items=10)
        e2 = experiment.run_experiment(self.params, n=12, items=10)
        self.assertEqual(e1["summary"], e2["summary"])
        self.assertEqual(e1["control"], "none")
        self.assertEqual(set(e1["comparisons"]), {"ai_first", "human_first"})
        for arm in e1["arms"]:
            self.assertEqual(len(e1["data"][arm]), 12)
            for row in e1["data"][arm]:
                self.assertTrue(0 <= row["pre"] <= 1 and 0 <= row["post"] <= 1)
                self.assertAlmostEqual(row["change"], row["post"] - row["pre"])
                # Scores are whole numbers of items.
                self.assertAlmostEqual(row["pre"] * 10, round(row["pre"] * 10))
        self.assertEqual(e1["summary"]["none"]["deferral"], 0)

    def test_arms_hold_different_people(self):
        e = experiment.run_experiment(self.params, arms=["none", "human_first"], n=5, items=10)
        before = [r["trueBefore"] for r in e["data"]["none"]]
        other = [r["trueBefore"] for r in e["data"]["human_first"]]
        self.assertNotEqual(before, other)

    def test_control_falls_back_to_first_arm(self):
        e = experiment.run_experiment(self.params, arms=["human_first", "ai_first"], n=5, items=5)
        self.assertEqual(e["control"], "human_first")
        self.assertEqual(list(e["comparisons"]), ["ai_first"])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            experiment.run_experiment(self.params, arms=["none", "magic"], n=5)
        with self.assertRaises(ValueError):
            experiment.run_experiment(self.params, arms=["none", "none"], n=5)
        with self.assertRaises(ValueError):
            experiment.run_experiment(self.params, n=1)
        with self.assertRaises(ValueError):
            experiment.run_experiment(self.params, items=0)
        with self.assertRaises(ValueError):
            experiment.power_curve(self.params, "none", "none")
        with self.assertRaises(ValueError):
            experiment.power_curve(self.params, "ai_first", sizes=[1])

    def test_power_rises_with_sample_size(self):
        p = dict(self.params, decayRate=0.008, feedbackRate=0.1)
        pw = experiment.power_curve(p, "ai_first", sizes=[10, 200], reps=60, pool=200, items=20)
        self.assertLess(pw["effect"]["diff"], 0)
        self.assertGreater(pw["results"][1]["rightWay"], pw["results"][0]["rightWay"])
        for row in pw["results"]:
            self.assertLessEqual(row["rightWay"], row["power"])

    def test_smallest_size_interpolates(self):
        rows = [{"n": 20, "rightWay": 0.4}, {"n": 40, "rightWay": 0.6}, {"n": 80, "rightWay": 0.9}]
        self.assertEqual(experiment.smallest_size_for(rows, 0.8), 67)
        self.assertEqual(experiment.smallest_size_for(rows, 0.3), 20)
        self.assertIsNone(experiment.smallest_size_for(rows, 0.95))


class CliTest(unittest.TestCase):
    def test_run_text_and_json(self):
        code, out = run_cli("run", "--set", "people=50", "--set", "rounds=40")
        self.assertEqual(code, 0)
        self.assertIn("Verdict:", out)
        code, out = run_cli("run", "--workflow", "none", "--set", "people=50", "--set", "rounds=40", "--json")
        data = json.loads(out)
        self.assertEqual(data["verdict"]["key"], "baseline")
        self.assertIsNone(data["result"]["misledRate"])

    def test_experiment_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "p.csv")
            md_path = os.path.join(tmp, "r.md")
            code, out = run_cli("experiment", "--n", "6", "--items", "5", "--set", "rounds=30",
                                "--csv", csv_path, "--markdown", md_path)
            self.assertEqual(code, 0)
            with open(csv_path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 18)
            self.assertEqual(rows[0]["arm"], "none")
            with open(md_path, encoding="utf-8") as fh:
                md = fh.read()
            self.assertIn("| Arm | Pre-test |", md)
            self.assertNotIn("—", md)

    def test_power_output(self):
        code, out = run_cli("power", "--sizes", "10,20", "--reps", "20", "--pool", "40", "--set", "rounds=30")
        self.assertEqual(code, 0)
        self.assertIn("Participants per arm", out)

    def test_bad_arguments_exit_cleanly(self):
        for args in (["run", "--set", "nonsense=1"], ["run", "--set", "novalue"], ["run", "--preset", "nope"],
                     ["power", "--sizes", "a,b"], ["experiment", "--arms", "none,magic", "--n", "4"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stderr(io.StringIO()):
                    run_cli(*args)
            self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
