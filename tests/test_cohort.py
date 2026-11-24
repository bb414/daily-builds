import json
import os
import tempfile
import unittest

import helpers  # noqa: F401  (puts the project on the path)

from second_opinion import cohort
from second_opinion.metrics import score
from second_opinion.synth import simulate_cohort, simulate_session


class StatsTests(unittest.TestCase):
    def test_bootstrap_interval_contains_the_mean(self):
        values = [0.2, 0.4, 0.5, 0.5, 0.7, 0.9, 1.0, 0.3]
        lo, hi = cohort.bootstrap_ci(values, resamples=1000)
        mean = sum(values) / len(values)
        self.assertLess(lo, mean)
        self.assertGreater(hi, mean)
        self.assertEqual(cohort.bootstrap_ci([0.5]), (None, None))
        self.assertEqual(cohort.bootstrap_ci(values, resamples=500), cohort.bootstrap_ci(values, resamples=500))

    def test_permutation_test(self):
        same = [0.5, 0.6, 0.4, 0.5, 0.55, 0.45] * 3
        diff, p = cohort.permutation_test(same, list(same), permutations=500)
        self.assertEqual(diff, 0)
        self.assertGreater(p, 0.9)
        diff, p = cohort.permutation_test([0.9] * 10 + [0.8] * 10, [0.2] * 10 + [0.3] * 10, permutations=500)
        self.assertAlmostEqual(diff, 0.6)
        self.assertLess(p, 0.01)
        self.assertEqual(cohort.permutation_test([1], [0, 1]), (None, None))


class LoadingTests(unittest.TestCase):
    def test_json_list_folder_and_errors(self):
        sessions = simulate_cohort(4, seed=2)
        with tempfile.TemporaryDirectory() as d:
            for s in sessions[:2]:
                with open(os.path.join(d, s["id"] + ".json"), "w") as f:
                    json.dump(s, f)
            with open(os.path.join(d, "several.json"), "w") as f:
                json.dump(sessions[2:], f)
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write("ignored")
            loaded = cohort.load_sessions([d])
            self.assertEqual(sorted(s["id"] for s in loaded), sorted(s["id"] for s in sessions))
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{not json")
            with self.assertRaises(cohort.SessionFileError):
                cohort.load_file(bad)
            with open(bad, "w") as f:
                json.dump({"format": "other"}, f)
            with self.assertRaises(cohort.SessionFileError):
                cohort.load_file(bad)
            empty = os.path.join(d, "empty.csv")
            open(empty, "w").close()
            with self.assertRaises(cohort.SessionFileError):
                cohort.load_file(empty)
            wrong = os.path.join(d, "wrong.csv")
            with open(wrong, "w") as f:
                f.write("a,b\n1,2\n")
            with self.assertRaises(cohort.SessionFileError):
                cohort.load_file(wrong)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.sessions = (simulate_cohort(30, seed=1, condition={"advice": "verdict"})
                         + simulate_cohort(30, seed=2, condition={"advice": "reason"}))

    def test_groups_and_profiles(self):
        summary = cohort.summarise(self.sessions, resamples=300)
        self.assertEqual(summary["people"], 60)
        self.assertEqual([g["name"] for g in summary["groups"]],
                         ["advice: reason, feedback off", "advice: verdict, feedback off"])
        for g in summary["groups"]:
            self.assertEqual(g["people"], 30)
            self.assertEqual(sum(g["profiles"].values()), 30)
            st = g["stats"]["withFinal"]
            self.assertEqual(st["n"], 30)
            self.assertLessEqual(st["low"], st["mean"])
            self.assertGreaterEqual(st["high"], st["mean"])
            expected = sum(score(s)["accuracy"]["withFinal"] for s in self.sessions
                           if cohort.condition_label(s["condition"]) == g["name"]) / 30
            self.assertAlmostEqual(st["mean"], expected)

    def test_grouping_options(self):
        by_feedback = cohort.summarise(self.sessions, by="feedback", resamples=100)
        self.assertEqual([g["name"] for g in by_feedback["groups"]], ["feedback off"])
        by_advice = cohort.summarise(self.sessions, by="advice", resamples=100)
        self.assertEqual(len(by_advice["groups"]), 2)

    def test_comparisons(self):
        summary = cohort.summarise(self.sessions, resamples=100)
        comps = cohort.compare_groups(summary, "rsr", permutations=300)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["reference"], "advice: reason, feedback off")
        self.assertTrue(0 < comps[0]["p"] <= 1)
        single = cohort.summarise(self.sessions[:5], resamples=100)
        self.assertEqual(cohort.compare_groups(single, "rsr"), [])


class SynthTests(unittest.TestCase):
    def test_reproducible_and_complete(self):
        a = simulate_session(99, {"advice": "confidence"})
        self.assertEqual(a, simulate_session(99, {"advice": "confidence"}))
        self.assertTrue(score(a)["complete"])
        self.assertTrue(a["synthetic"])
        self.assertEqual(a["condition"], {"advice": "confidence", "feedback": False})

    def test_assumed_effects_show_up_in_large_samples(self):
        def mean(values):
            values = [v for v in values if v is not None]
            return sum(values) / len(values)
        verdict = [score(s) for s in simulate_cohort(300, seed=4, condition={"advice": "verdict"})]
        reason = [score(s) for s in simulate_cohort(300, seed=4, condition={"advice": "reason"})]
        # Showing a reason is assumed to raise reliance, so more people follow wrong advice.
        self.assertGreater(mean([r["reliance"]["followWhenWrong"] for r in reason]),
                           mean([r["reliance"]["followWhenWrong"] for r in verdict]))
        # A crutch effect lowers solo accuracy after the checker phase.
        none = [score(s)["accuracy"]["after"] for s in simulate_cohort(300, seed=6)]
        crutch = [score(s)["accuracy"]["after"] for s in simulate_cohort(300, seed=6, crutch=1.5)]
        self.assertGreater(mean(none), mean(crutch) + 0.05)
        # Feedback lets people learn the checker's weak spots.
        fb = [score(s) for s in simulate_cohort(300, seed=4, condition={"advice": "reason", "feedback": True})]
        self.assertLess(mean([r["reliance"]["followWhenWrong"] for r in fb]),
                        mean([r["reliance"]["followWhenWrong"] for r in reason]))


if __name__ == "__main__":
    unittest.main()
