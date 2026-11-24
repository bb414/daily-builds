"""Tests for the Python companion: model behaviour, statistics, the virtual experiment and the CLI."""

import contextlib
import csv
import io
import json
import os
import tempfile
import unittest

from skill_fade import cli, experiment, model, stats


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

    def test_only_plain_numbers_are_accepted(self):
        default = model.DEFAULTS["rounds"]
        for raw in (" ", "0x40", [100], "1_000", "\u0661\u0662\u0660", "1e999", "Infinity", "12abc", {}, True,
                    10 ** 400, "nan"):
            self.assertEqual(model.normalise_params({"rounds": raw})["rounds"], default, repr(raw))
        self.assertEqual(model.normalise_params({"rounds": " 120 "})["rounds"], 120)
        self.assertEqual(model.normalise_params({"rounds": "1e2"})["rounds"], 100)
        self.assertEqual(model.normalise_params({"aiAccuracy": ".9"})["aiAccuracy"], 0.9)
        self.assertEqual(model.normalise_params({"driftAt": 0.49999999999999994})["driftAt"], 1)
        self.assertEqual(model.normalise_params("rounds=40")["rounds"], default)

    def test_stress_test_can_only_make_the_ai_worse(self):
        p = model.normalise_params({"aiAccuracy": 0.7, "driftAccuracy": 0.95})
        self.assertEqual(p["driftAccuracy"], 0.7)

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

    def test_power_flags_when_the_smallest_size_is_enough(self):
        p = dict(self.params, decayRate=0.01, feedbackRate=0.0, complacency=1.0)
        pw = experiment.power_curve(p, "ai_first", sizes=[150, 300], reps=30, pool=150, items=40)
        if pw["results"][0]["rightWay"] >= 0.8:
            self.assertTrue(pw["neededAtMost"])
            self.assertEqual(pw["needed"], 150)
        code, out = run_cli("power", "--sizes", "300", "--reps", "20", "--pool", "150", "--items", "40",
                            "--set", "rounds=60", "--set", "decayRate=0.01", "--set", "feedbackRate=0",
                            "--set", "complacency=1")
        self.assertTrue("or fewer" in out or "not reached" in out or "About" in out)

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
            self.assertNotIn("\u2014", md)

    def test_power_output(self):
        code, out = run_cli("power", "--sizes", "10,20", "--reps", "20", "--pool", "40", "--set", "rounds=30")
        self.assertEqual(code, 0)
        self.assertIn("Participants per arm", out)

    def test_compare_and_stress_test_output(self):
        code, out = run_cli("compare", "--set", "people=50", "--set", "rounds=40", "--set", "driftAt=20")
        self.assertEqual(code, 0)
        for label in model.WORKFLOW_LABELS.values():
            self.assertIn(label, out)
        self.assertIn("Accuracy once the AI gets worse (after case 20)", out)
        code, out = run_cli("compare", "--set", "people=50", "--set", "rounds=40", "--json")
        rows = json.loads(out)
        self.assertEqual([r["workflow"] for r in rows], model.WORKFLOW_KEYS)
        code, out = run_cli("run", "--set", "people=50", "--set", "rounds=40", "--set", "driftAt=20")
        self.assertIn("Stress test: after case 20", out)
        self.assertIn("Time per case", out)

    def test_robustness_output(self):
        code, out = run_cli("robustness", "--set", "people=30", "--set", "rounds=30")
        self.assertEqual(code, 0)
        self.assertIn("The verdict held in", out)
        self.assertIn("Rubber-stamping (AI first)", out)
        code, out = run_cli("robustness", "--workflow", "none", "--set", "people=30", "--set", "rounds=30")
        self.assertIn("no verdict to test", out)

    def test_config_file_from_the_browser(self):
        settings = {"app": "skill-fade", "version": 1,
                    "params": dict(model.preset_params("invoice_fraud"), people=60, rounds=30)}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(settings, fh)
            code, out = run_cli("run", "--config", path, "--json")
            data = json.loads(out)
            self.assertEqual(data["result"]["params"]["workflow"], "human_first")
            self.assertEqual(data["result"]["params"]["people"], 60)
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            for path_arg in (bad, os.path.join(tmp, "missing.json")):
                with self.assertRaises(SystemExit):
                    run_cli("run", "--config", path_arg)
        with self.assertRaises(ValueError):
            model.read_settings_file({"hello": 1})
        with self.assertRaises(ValueError):
            model.read_settings_file([1, 2])

    def test_bad_arguments_exit_cleanly(self):
        for args in (["run", "--set", "nonsense=1"], ["run", "--set", "novalue"], ["run", "--preset", "nope"],
                     ["power", "--sizes", "a,b"], ["experiment", "--arms", "none,magic", "--n", "4"],
                     ["experiment", "--arms", ",", "--n", "4"], ["power", "--items", "0", "--reps", "2", "--pool", "4"],
                     ["experiment", "--n", "3", "--items", "3", "--set", "rounds=20", "--csv", "/nonexistent/dir/x.csv"],
                     ["experiment", "--n", "3", "--items", "3", "--set", "rounds=20", "--markdown", "/nonexistent/dir/x.md"],
                     ["run", "--set", "rounds=1OO"], ["run", "--set", "workflow=humanfirst"],
                     ["run", "--set", "showConfidence=maybe"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    cli.main(list(args))
            self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()


class HygieneTest(unittest.TestCase):
    def test_no_em_dashes_anywhere(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dash = "\u2014"
        found = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                path = os.path.join(folder, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        if dash in fh.read():
                            found.append(os.path.relpath(path, root))
                except (UnicodeDecodeError, OSError):
                    continue
        self.assertEqual(found, [])
